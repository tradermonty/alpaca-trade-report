import requests
import pandas as pd
import io
import time
import asyncio
import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

from api_clients import get_alpaca_client, get_finviz_client
from parallel_executor import execute_trades_parallel
from config import system_config
from logging_config import get_logger

import news_analysis

from common_constants import ACCOUNT, TIMEZONE
logger = get_logger(__name__)

load_dotenv()

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

TEST_MODE = False  # Migrated to constant naming
TEST_DATETIME = pd.Timestamp(datetime.now().astimezone(TZ_NY))

ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper")  # Migrated from common_constants

if ALPACA_ACCOUNT == 'live':
    TRADE_PY_FILE = 'src/orb.py'
else:
    TRADE_PY_FILE = 'src/orb_paper.py'

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
finviz_client = get_finviz_client()
api = alpaca_client.api  # 後方互換性のため

EXCLUDE_EARNINGS = True  # 決算発表を行った銘柄は除外
# 設定値をconfig.pyから取得
from config import trading_config
NUMBER_OF_STOCKS = trading_config.RELATIVE_VOLUME_NUMBER_OF_STOCKS
MINUTES_FROM_OPEN = trading_config.RELATIVE_VOLUME_MINUTES_FROM_OPEN
#TRADE_PY_FILE = 'src/orb.py'
TRADE_PY_FILE = 'src/orb_paper.py'


def sleep_until_open(time_to_minutes=2):
    global test_datetime
    if TEST_MODE:
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
            if TEST_MODE:
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
                        logger.info("Time to next open: %s", next_open_dt - current_dt)
                        if TEST_MODE:
                            time.sleep(0.01)
                        else:
                            time.sleep(1)
                    else:
                        logger.info("%s open time reached.", current_dt)
                        break

                    if TEST_MODE:
                        test_datetime += timedelta(minutes=time_to_minutes)
                        current_dt = pd.Timestamp(test_datetime)
                    else:
                        current_dt = pd.Timestamp(datetime.now().astimezone(TZ_NY))
                break

            if TEST_MODE:
                test_datetime += timedelta(minutes=time_to_minutes)


def get_earnings_tickers():
    # Finvizスクリーナーのフィルター設定
    earnings_filters = {
        'cap': 'smallover',
        'earningsdate': 'yesterdayafter|todaybefore',
        'sh_avgvol': 'o200',
        'sh_price': 'o10',
        'ta_volatility': '1tox'
    }
    
    earnings_columns = [
        0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,
        29,30,31,84,32,33,34,35,36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,
        53,54,55,56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,
        104,102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105
    ]

    tickers = []

    # FinvizClientを使用してスクリーナーURLを構築
    screener_url = finviz_client.build_screener_url(
        filters=earnings_filters,
        columns=earnings_columns,
        order='-epssurprise'
    )
    
    # スクリーナーデータを取得
    df = finviz_client.get_screener_data(screener_url)
    
    if df is not None and len(df) > 0:
        for ticker in df['Ticker']:
            if ticker not in tickers:
                tickers.append(ticker)
    else:
        logger.error("Failed to get earnings tickers from Finviz.")

    return tickers


def trade_relative_volume_stocks(num):
    filtered_df = []
    
    # Finvizスクリーナーのフィルター設定
    relative_volume_filters = {
        'cap': 'smallover',
        'ind': 'stocksonly',
        'sh_avgvol': 'o200',
        'sh_price': 'o10',
        'sh_relvol': 'o1.5',
        'ta_change': 'u2'
    }
    
    relative_volume_columns = [
        0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,
        33,34,35,36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,
        56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,
        102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105
    ]

    # wait until the market opens and then wait for 2 minutes
    sleep_until_open(time_to_minutes=0)
    time.sleep(60 * MINUTES_FROM_OPEN)

    # FinvizClientを使用してスクリーナーURLを構築
    screener_url = finviz_client.build_screener_url(
        filters=relative_volume_filters,
        columns=relative_volume_columns,
        order='-relativevolume'
    )
    
    # スクリーナーデータを取得
    df = finviz_client.get_screener_data(screener_url)
    
    if df is not None and len(df) > 0:
        logger.debug("Filtered dataframe:\n%s", df)
        df['score'] = 0

    #        # EPS Surprise 8%-: 1, 15%- : 2, 30%- : 3
    #        df['EPS Surprise'] = df['EPS Surprise'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['EPS Surprise'] > 0.08, 'score'] += 1
    #        df.loc[df['EPS Surprise'] > 0.15, 'score'] += 1
    #        df.loc[df['EPS Surprise'] > 0.30, 'score'] += 1
    #
    #        # Revenue Surprise 2%-: 1, 8%- : 2, 15%- : 3
    #        df['Revenue Surprise'] = df['Revenue Surprise'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['Revenue Surprise'] > 0.02, 'score'] += 1
    #        df.loc[df['Revenue Surprise'] > 0.08, 'score'] += 1
    #        df.loc[df['Revenue Surprise'] > 0.15, 'score'] += 1
    #
    #        # EPS growth this year 25%-: 1
    #        df['EPS growth this year'] = df['EPS growth this year'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['EPS growth this year'] > 0.25, 'score'] += 1
    #
    #        # EPS growth next year 25%-: 1
    #        df['EPS growth next year'] = df['EPS growth next year'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['EPS growth next year'] > 0.25, 'score'] += 1
    #
    #        # Sales growth 8-25%: 1, 25%-: 2
    #        df['Sales growth quarter over quarter'] = df['Sales growth quarter over quarter'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['Sales growth quarter over quarter'] > 0.08, 'score'] += 1
    #        df.loc[df['Sales growth quarter over quarter'] > 0.25, 'score'] += 1
    #
    #        # EPS growth 8-25%: 1, 25%-: 2
    #        df['EPS growth quarter over quarter'] = df['EPS growth quarter over quarter'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['EPS growth quarter over quarter'] > 0.08, 'score'] += 1
    #        df.loc[df['EPS growth quarter over quarter'] > 0.25, 'score'] += 1
    #
    #        # Price Change 2-8%: 1, 8%-: 2
    #        df['Change'] = df['Change'].str.replace('%', '').astype(float) / 100.0
    #        df.loc[df['Change'] > 0.02, 'score'] += 1
    #        df.loc[df['Change'] > 0.08, 'score'] += 1
    #
        # Filter top N tickers
        filtered_df = df.sort_values(by='No.', ascending=True).head(20)
    else:
        logger.error("Failed to get relative volume data from Finviz.")
        return

    earnings_tickers = get_earnings_tickers()

    valid_tickers = []

    # ニュース分析と選別処理
    for ticker in filtered_df['Ticker']:
        if EXCLUDE_EARNINGS and ticker in earnings_tickers:
            logger.info(f"{ticker}: Skip tickers with earnings release.")
            continue

        try:
            result = news_analysis.analyze(ticker, datetime.today().strftime('%Y-%m-%d'))
            logger.info(f"{ticker}: News analysis result: {result}")

            if int(result['category']) < 5:  # 1. 決算発表, 2. 業績予想, 3. アナリストレーティング, 4. S&P指数への組み込み
                valid_tickers.append(ticker)
                if len(valid_tickers) >= num:
                    break
        except Exception as e:
            logger.error(f"News analysis failed for {ticker}: {e}")
            continue

    if valid_tickers:
        logger.info(f'Executing parallel relative volume trades for {len(valid_tickers)} tickers: {valid_tickers}')
        
        # 非同期で並列実行
        results = asyncio.run(
            execute_trades_parallel(
                symbols=valid_tickers,
                trade_file=TRADE_PY_FILE,
                position_size='auto',
                max_concurrent=system_config.MAX_CONCURRENT_TRADES,
                swing=False,
                range_val=5,
                dynamic_rate=True,
                ema_trail=True
            )
        )
        
        # 実行結果を分析してレポート
        _analyze_execution_results(results)
    else:
        logger.info("No valid tickers found for trading.")

    # export screening result
    filtered_df.to_csv('export.csv', index=False)


def _analyze_execution_results(results):
    """実行結果を分析してログ出力"""
    successful = [symbol for symbol, result in results.items() if result.success]
    failed = [symbol for symbol, result in results.items() if not result.success]
    
    logger.info(f"Relative volume trade execution completed: {len(successful)} successful, {len(failed)} failed")
    
    if successful:
        logger.info(f"Successfully executed trades: {successful}")

        try:
            from trade_logger import log_trade
            for sym in successful:
                log_trade(sym, 'relative_volume')
        except Exception as e:
            logger.warning(f"trade logging failed in relative_volume: {e}")
    
    if failed:
        logger.error(f"Failed to execute trades: {failed}")
        for symbol in failed:
            result = results[symbol]
            logger.error(f"{symbol} failed with return code {result.return_code}: {result.error_message}")
            if result.stderr:
                logger.error(f"{symbol} stderr: {result.stderr[:200]}...")


if __name__ == '__main__':
    trade_relative_volume_stocks(NUMBER_OF_STOCKS)
