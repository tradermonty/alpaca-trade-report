import requests
import pandas as pd
import io
import time
import asyncio
from datetime import datetime, date, timedelta
import os
from dotenv import load_dotenv
from typing import List, Optional
from logging_config import get_logger
from config import trading_config, timing_config, screening_config, system_config
from parallel_executor import execute_trades_parallel, ParallelExecutor, TradeCommandBuilder
from common_constants import TIMEZONE, ACCOUNT, MARKET  # 共通定数のインポート

logger = get_logger(__name__)

import dividend_portfolio_management
import strategy_allocation
import risk_management
from api_clients import get_alpaca_client, get_eodhd_client, get_finviz_client

load_dotenv()

# 共通定数の使用（重複排除）
TZ_NY = TIMEZONE.NY  # 後方互換性のため
TZ_UTC = TIMEZONE.UTC

TEST_MODE = False  # Migrated to constant naming
TEST_DATETIME = pd.Timestamp(datetime.now().astimezone(TIMEZONE.NY))

# 設定から取得（ハードコード排除）
ALPACA_ACCOUNT = ACCOUNT.get_account_type()

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
eodhd_client = get_eodhd_client()
finviz_client = get_finviz_client()

if ALPACA_ACCOUNT == 'live':
    TRADE_PY_FILE = 'src/orb.py'
else:
    TRADE_PY_FILE = 'src/orb_paper.py'

# API クライアントの初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
eodhd_client = get_eodhd_client()
finviz_client = get_finviz_client()
api = alpaca_client.api  # 後方互換性のため

# SCREENER: 基本情報フィルター
# - 決算日 (Earnings Date): 昨日の引け後または本日の寄り付き前
# - EPSサプライズ (EPS Surprise): 予想を5%以上上回る
# - 変化 (Change): 当日株価が上昇
# - 株価 (Price): $10以上
# - 平均出来高 (Average Volume): 200K株以上

# Finvizスクリーナーのフィルター設定
EARNINGS_FILTERS = {
    'earningsdate': 'yesterdayafter|todaybefore',
    'fa_epsrev': 'eo5',
    'sh_avgvol': 'o200',
    'sh_price': 'o10',
    'ta_change': 'u'
}

EARNINGS_COLUMNS = [
    0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,
    36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,
    80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110,
    125,126,59,68,70,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105
]

NUMBER_OF_STOCKS = screening_config.NUMBER_OF_STOCKS



def get_tickers_from_screener(num):
    filtered_df = None
    tickers = []

    try:
        # 中小型株のシンボルを取得
        mid_small_symbols = set(get_mid_small_cap_symbols())
        logger.info(f"スクリーニング対象の中小型株銘柄数: {len(mid_small_symbols)}")

        # FinvizClientを使用してスクリーナーURLを構築
        screener_url = finviz_client.build_screener_url(
            filters=EARNINGS_FILTERS,
            columns=EARNINGS_COLUMNS,
            order='-epssurprise'
        )
        
        # スクリーナーデータを取得
        df = finviz_client.get_screener_data(screener_url)
        
        if df is not None and len(df) > 0:
            # Mid/Small cap銘柄のみをフィルタリング
            df['Ticker'] = df['Ticker'].str.replace('-', '.')  # Finvizのフォーマットを変換
            df = df[df['Ticker'].isin(mid_small_symbols)]
            logger.info(f"中小型株のみに絞り込み後: {len(df)}銘柄")

            if len(df) == 0:
                logger.warning("条件に合致する中小型株が見つかりませんでした")
                return []

            # 株価変動率による絞り込み
            logger.info("株価変動率による絞り込みを開始")
            today = datetime.now().date()
            start_date = (today - timedelta(days=timing_config.DATA_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')

            # 並行処理で株価データを効率的に取得
            from concurrent_data_fetcher import get_price_filtered_tickers_sync
            price_filtered_tickers = get_price_filtered_tickers_sync(
                df['Ticker'].tolist(), start_date, end_date)

            # 株価変動率でフィルタリングされた銘柄のみを残す
            df = df[df['Ticker'].isin(price_filtered_tickers)]
            logger.info(f"株価変動率フィルター後の銘柄数: {len(df)}")

            if len(df) == 0:
                logger.warning("株価変動率の条件を満たす銘柄が見つかりませんでした")
                return []

            df['score'] = 0

            # EPS Surprise 5%-: 1, 8%-: 2, 15%-: 4, 30%-: 6
            df['EPS Surprise'] = df['EPS Surprise'].str.replace('%', '').astype(float) / 100.0
            df.loc[df['EPS Surprise'] > 0.05, 'score'] += 1
            df.loc[df['EPS Surprise'] > 0.08, 'score'] += 1
            df.loc[df['EPS Surprise'] > 0.10, 'score'] += 2
            df.loc[df['EPS Surprise'] > 0.30, 'score'] += 2

            # Revenue Surprise 2%-: 1, 8%- : 2, 15%- : 3
            df['Revenue Surprise'] = df['Revenue Surprise'].str.replace('%', '').astype(float) / 100.0
            df.loc[df['Revenue Surprise'] > 0.02, 'score'] += 1
            df.loc[df['Revenue Surprise'] > 0.08, 'score'] += 1
            df.loc[df['Revenue Surprise'] > 0.15, 'score'] += 1

            # Price Change 1-8%: 1, 8%-: 2
            df['Change'] = df['Change'].str.replace('%', '').astype(float) / 100.0
            df.loc[df['Change'] > 0.01, 'score'] += 1
            df.loc[df['Change'] > 0.08, 'score'] += 1

            # Relative Volume 1.0-: 2, 1.5-: 4, 2.0-: 6
            df.loc[df['Relative Volume'] > 1.0, 'score'] += 2
            df.loc[df['Relative Volume'] > 1.5, 'score'] += 2
            df.loc[df['Relative Volume'] > 2.0, 'score'] += 2

            # Total score > 0
            filtered_df = df[df['score'] > 0]

            # export screening result
            filtered_df.to_csv('earnings/screen_' + datetime.today().strftime('%Y-%m-%d') + '.csv', index=False)

            filtered_df = filtered_df.sort_values(by='score', ascending=False)

            # Filter top # tickers
            filtered_df = filtered_df.head(num)
        else:
            logger.error("Failed to get screener data from Finviz")
            return []

        # append tickers from screener
        if filtered_df is not None:
            for ticker in filtered_df['Ticker']:
                if ticker not in tickers:
                    tickers.append(ticker)

        return tickers

    except Exception as e:
        logger.error(f"スクリーニング処理中にエラーが発生: {str(e)}", exc_info=True)
        return []


def sleep_until_open(time_to_minutes=timing_config.DEFAULT_MINUTES_TO_OPEN):
    global test_datetime
    if test_mode:
        market_dt = test_datetime.date()
    else:
        market_dt = date.today()

    days = 1

    cal = api.get_calendar(start=str(market_dt), end=str(market_dt))

    while True:
        if len(cal) == 0:
            market_dt += timedelta(days=days)
            cal = api.get_calendar(start=str(market_dt), end=str(market_dt))
            days += 1
        else:
            open_time = cal[0].open
            if test_mode:
                current_dt = pd.Timestamp(test_datetime)
            else:
                current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))

            next_open_dt = pd.Timestamp(str(market_dt) + " " + str(open_time), tz=TZ_NY)

            if current_dt > next_open_dt:
                market_dt += timedelta(days=days)
                cal = api.get_calendar(start=str(market_dt), end=str(market_dt))
                days += 1
            else:
                while True:
                    if next_open_dt > current_dt + timedelta(minutes=time_to_minutes):
                        logger.debug(f"time to next open: {next_open_dt - current_dt}")
                        if test_mode:
                            time.sleep(timing_config.TEST_MODE_SLEEP)
                        else:
                            time.sleep(timing_config.PRODUCTION_SLEEP_MINUTE)
                    else:
                        logger.info(f"{current_dt} - open time reached.")
                        break

                    if test_mode:
                        test_datetime += timedelta(minutes=time_to_minutes)
                        current_dt = pd.Timestamp(test_datetime)
                    else:
                        current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))
                break

            if test_mode:
                test_datetime += timedelta(minutes=time_to_minutes)


def swing_earnings_stocks():
    process = {}

    if not risk_management.check_pnl_criteria():
        logger.warning('recent trading pnl is below criteria. exit trading.')
        return

    # target allocation size for strategy #1
    target_value = strategy_allocation.get_target_value('strategy1', account=ALPACA_ACCOUNT)
    size = int(target_value * trading_config.POSITION_SIZE_RATE / trading_config.POSITION_DIVIDER)
    logger.info(f"Position size per trade: {size}")

    # wait until 2 minutes before the market opens
    sleep_until_open(time_to_minutes=timing_config.DEFAULT_MINUTES_TO_OPEN)

    try:
        # Finvizスクリーナーから銘柄を取得（中小型株のみ）
        tickers_screener = get_tickers_from_screener(NUMBER_OF_STOCKS)
        logger.info(f"Finvizスクリーナーから{len(tickers_screener)}銘柄を取得しました")

    except Exception as error:
        logger.error("failed to get tickers from finviz screener.", exc_info=True)
        tickers_screener = []
    
    # 最終的な取引銘柄リスト
    tickers = tickers_screener

    logger.info(f'Final trading tickers: {tickers}')

    if len(tickers) > 0:
        # 高配当ポートフォリオの銘柄を除外
        valid_tickers = []
        for ticker in tickers:
            if ticker in dividend_portfolio_management.dividend_symbols:
                logger.info(f"{ticker} is in dividend portfolio. skipped.")
            else:
                valid_tickers.append(ticker)
        
        if valid_tickers:
            logger.info(f'Executing parallel gap up trades for {len(valid_tickers)} tickers: {valid_tickers}')
            
            # 非同期で並列実行
            results = asyncio.run(
                execute_trades_parallel(
                    symbols=valid_tickers,
                    trade_file=TRADE_PY_FILE,
                    position_size=size,
                    max_concurrent=system_config.MAX_CONCURRENT_TRADES,
                    swing=True,
                    range_val=0,
                    dynamic_rate=False,
                    ema_trail=False
                )
            )
            
            # 実行結果を分析してレポート
            _analyze_execution_results(results)
        else:
            logger.info("No valid tickers for trading after filtering.")


def get_mid_small_cap_symbols() -> List[str]:
    """EODHDのAPIを使用してS&P 400とS&P 600の銘柄リストを取得"""
    try:
        # S&P 400 (MID)の取得
        mid_data = eodhd_client.get_market_cap_data('MID.INDX')

        # S&P 600 (SML)の取得
        sml_data = eodhd_client.get_market_cap_data('SML.INDX')

        # 構成銘柄の抽出と結合
        symbols = []

        # MIDの構成銘柄を追加
        if 'Components' in mid_data:
            for component in mid_data['Components'].values():
                symbols.append(component['Code'].replace('.US', ''))

        # SMLの構成銘柄を追加
        if 'Components' in sml_data:
            for component in sml_data['Components'].values():
                symbols.append(component['Code'].replace('.US', ''))

        if not symbols:
            raise ValueError("中型・小型株の銘柄リストを取得できませんでした")

        logger.info(f"取得した中型・小型株銘柄数: {len(symbols)}")
        return symbols

    except Exception as e:
        logger.error(f"中型・小型株銘柄リストの取得に失敗: {str(e)}", exc_info=True)
        raise

def get_historical_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """EODHDから株価データを取得"""
    # 銘柄名のピリオドをハイフンに置換（例：BRK.B → BRK-B）
    api_symbol = symbol.replace('.', '-')
    logger.debug(f"データ取得開始: {symbol} (API用シンボル: {api_symbol})")

    try:
        data = eodhd_client.get_historical_data(f"{api_symbol}.US", start_date, end_date)
        if data:
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)

            # 調整済み株価を使用
            df.rename(columns={
                'adjusted_close': 'Close',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'volume': 'Volume'
            }, inplace=True)

            # 調整済みの始値、高値、安値を計算
            adj_ratio = df['Close'] / df['close']
            df['Open'] = df['Open'] * adj_ratio
            df['High'] = df['High'] * adj_ratio
            df['Low'] = df['Low'] * adj_ratio

            # 不要なカラムを削除
            df = df.drop(['close'], axis=1)

            return df

        return None

    except Exception as e:
        logger.error(f"株価データの取得に失敗: {symbol}, {str(e)}", exc_info=True)
        return None

def calculate_price_change(df: pd.DataFrame, days: int = 20) -> float:
    """
    指定された日数の株価変動率を計算

    Args:
        df: 株価データのDataFrame
        days: 計算する期間（デフォルト20日）

    Returns:
        float: 株価変動率（%）
    """
    if len(df) < days:
        return 0.0

    latest_price = df['Close'].iloc[-1]
    price_n_days_ago = df['Close'].iloc[-days]

    return ((latest_price - price_n_days_ago) / price_n_days_ago) * 100


# エントリーポイント
def _analyze_execution_results(results):
    """実行結果を分析してログ出力"""
    successful = [symbol for symbol, result in results.items() if result.success]
    failed = [symbol for symbol, result in results.items() if not result.success]
    
    logger.info(f"Trade execution completed: {len(successful)} successful, {len(failed)} failed")
    
    if successful:
        logger.info(f"Successfully executed trades: {successful}")
        
        # 実行時間の統計
        execution_times = [result.execution_time for result in results.values() if result.success]
        if execution_times:
            avg_time = sum(execution_times) / len(execution_times)
            max_time = max(execution_times)
            min_time = min(execution_times)
            logger.info(f"Execution time stats - Avg: {avg_time:.2f}s, Min: {min_time:.2f}s, Max: {max_time:.2f}s")
    
    if failed:
        logger.error(f"Failed to execute trades: {failed}")
        for symbol in failed:
            result = results[symbol]
            logger.error(f"{symbol} failed with return code {result.return_code}: {result.error_message}")
            if result.stderr:
                logger.error(f"{symbol} stderr: {result.stderr[:200]}...")


if __name__ == '__main__':
    swing_earnings_stocks()
