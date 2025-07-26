import requests
import pandas as pd
import io
import time
import subprocess
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from typing import List, Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import dividend_portfolio_management
import strategy_allocation
import risk_management
from api_clients import get_alpaca_client, get_eodhd_client

load_dotenv()

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

test_mode = False
test_datetime = pd.Timestamp(datetime.now().astimezone(TZ_NY))

ALPACA_ACCOUNT = 'live'

if ALPACA_ACCOUNT == 'live':
    TRADE_PY_FILE = 'src/orb.py'
else:
    TRADE_PY_FILE = 'src/orb_paper.py'

# API クライアントの初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
eodhd_client = get_eodhd_client()
api = alpaca_client.api  # 後方互換性のため

# FinvizのAPIキー設定
FINVIZ_API_KEY = os.getenv('FINVIZ_API_KEY')

# Finvizリトライ設定
FINVIZ_MAX_RETRIES = 5  # 最大リトライ回数
FINVIZ_RETRY_WAIT = 1   # 初回リトライ待機時間（秒）

# EODHDクライアントは既に初期化済み

# SCREENER: 基本情報フィルター
# - 決算日 (Earnings Date): 昨日の引け後または本日の寄り付き前
# - EPSサプライズ (EPS Surprise): 予想を5%以上上回る
# - 変化 (Change): 当日株価が上昇
# - 株価 (Price): $10以上
# - 平均出来高 (Average Volume): 200K株以上

SCREENER_URL = f"https://elite.finviz.com/export.ashx?v=151&f=earningsdate_yesterdayafter|todaybefore," \
               f"fa_epsrev_eo5,sh_avgvol_o200,sh_price_o10,ta_change_u&ft=4&o=-epssurprise&ar=60&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13," \
               f"73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35," \
               f"36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58," \
               f"80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110," \
               f"125,126,59,68,70,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth={FINVIZ_API_KEY}"

# for test
# SCREENER_URL = f"https://elite.finviz.com/export.ashx?v=151&f=earningsdate_nextweek," \
#                f"fa_epsrev_eo5,sh_avgvol_o200,sh_price_o10&ft=4&o=-epssurprise&ar=60&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13," \
#                f"73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35," \
#                f"36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58," \
#                f"80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110," \
#                f"125,126,59,68,70,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth={FINVIZ_API_KEY}"


NUMBER_OF_STOCKS = 5


def get_tickers_from_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        '../config/spreadsheetautomation-430123-8795f1278b02.json', scope)
    client = gspread.authorize(creds)

    # Google Sheetsを開く
    max_retries = 5
    attempt = 0
    worksheet = None
    tickers = []

    while attempt < max_retries:
        try:
            worksheet = client.open("trade_commands").worksheet("trade commands")
            break

        except Exception as error:
            attempt += 1
            print(datetime.now().astimezone(TZ_NY),
                  "failed to open spreadsheet.", error)
            if attempt == max_retries:
                print("reached maximum retries.")
                raise
            else:
                time.sleep(10)

    if worksheet:
        data = worksheet.get_all_records()

        # ヘッダー行を取得し、'symbol'の列番号を探す
        header = worksheet.row_values(1)
        symbol_col = header.index('symbol') + 1  # 列番号は1から始まるので+1

        for i, record in enumerate(data):
            symbol = record['symbol']
            print(symbol)

            if symbol != "":
                # Convert Finviz symbol format (with hyphen) to Alpaca format (with dot)
                symbol = symbol.replace('-', '.')
                tickers.append(symbol)

                # シンボルを削除（該当するセルを空にする）
                worksheet.update_cell(i + 2, symbol_col, '')  # i+2: データ部分のインデックスに1行目のヘッダーを考慮

    print('Trading tickers: ', tickers)

    return tickers


def get_tickers_from_screener(url, num):
    filtered_df = None
    tickers = []

    retries = 0

    try:
        # 中小型株のシンボルを取得
        mid_small_symbols = set(get_mid_small_cap_symbols())
        print(f"スクリーニング対象の中小型株銘柄数: {len(mid_small_symbols)}")

        while retries < FINVIZ_MAX_RETRIES:
            resp = requests.get(url)
            print(resp)

            if resp.status_code == 200:
                df = pd.read_csv(io.BytesIO(resp.content), sep=",")

                # Mid/Small cap銘柄のみをフィルタリング
                df['Ticker'] = df['Ticker'].str.replace('-', '.')  # Finvizのフォーマットを変換
                df = df[df['Ticker'].isin(mid_small_symbols)]
                print(f"中小型株のみに絞り込み後: {len(df)}銘柄")

                if len(df) == 0:
                    print("条件に合致する中小型株が見つかりませんでした")
                    return []

                # 株価変動率による絞り込み
                print("\n株価変動率による絞り込みを開始")
                today = datetime.now().date()
                start_date = (today - timedelta(days=40)).strftime('%Y-%m-%d')
                end_date = today.strftime('%Y-%m-%d')

                price_filtered_tickers = []
                for ticker in df['Ticker'].tolist():
                    try:
                        # 株価データの取得
                        price_data = get_historical_data(ticker, start_date, end_date)
                        if price_data is None or len(price_data) < 20:
                            print(f"{ticker}: 十分な株価データがありません")
                            continue

                        # 20日間の価格変動率を計算
                        price_change = calculate_price_change(price_data, 20)
                        print(f"{ticker}: 20日間の価格変動率 = {price_change:.2f}%")

                        # 変動率が0%以上の銘柄のみを対象とする
                        if price_change >= 0:
                            price_filtered_tickers.append(ticker)
                        else:
                            print(f"{ticker}: 価格変動率が0%未満のため除外")

                    except Exception as e:
                        print(f"{ticker}の株価データ取得中にエラー: {str(e)}")
                        continue

                # 株価変動率でフィルタリングされた銘柄のみを残す
                df = df[df['Ticker'].isin(price_filtered_tickers)]
                print(f"\n株価変動率フィルター後の銘柄数: {len(df)}")

                if len(df) == 0:
                    print("株価変動率の条件を満たす銘柄が見つかりませんでした")
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
                break

            elif resp.status_code == 429:
                retries += 1
                wait_time = FINVIZ_RETRY_WAIT * (2 ** (retries - 1))
                print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print(f"Error fetching tickers from Finviz. Status code: {resp.status_code}")
                break

        # append tickers from screener
        if filtered_df is not None:
            for ticker in filtered_df['Ticker']:
                if ticker not in tickers:
                    tickers.append(ticker)

        return tickers

    except Exception as e:
        print(f"スクリーニング処理中にエラーが発生: {str(e)}")
        return []


def sleep_until_open(time_to_minutes=2):
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
                        print("time to next open", next_open_dt - current_dt)
                        if test_mode:
                            time.sleep(0.01)
                        else:
                            time.sleep(60)
                    else:
                        print(current_dt, "open time reached.")
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
        print('recent trading pnl is below criteria. exit trading.')
        return

    # target allocation size for strategy #1
    target_value = strategy_allocation.get_target_value('strategy1', account=ALPACA_ACCOUNT)
    size = int(target_value * 0.06 / 3)
    print(size)

    # wait until 2 minutes before the market opens
    sleep_until_open(time_to_minutes=2)

    try:
        # Finvizスクリーナーから銘柄を取得（中小型株のみ）
        tickers_screener = get_tickers_from_screener(SCREENER_URL, NUMBER_OF_STOCKS)
        print(f"Finvizスクリーナーから{len(tickers_screener)}銘柄を取得しました")

    except Exception as error:
        print("failed to get tickers from finviz screener.")
        tickers_screener = []
    
    try:
        # get tickers from google spreadsheet
        tickers_sheet = get_tickers_from_sheet()
        print(f"スプレッドシートから{len(tickers_sheet)}銘柄を取得しました")

    except Exception as error:
        print("failed to get tickers from google spreadsheet.")
        tickers_sheet = []

    # combine two and remove duplicated tickers
    tickers = list(set(tickers_screener+tickers_sheet))

    print('Final trading tickers: ', tickers)

    if len(tickers) > 0:
        for ticker in tickers:
            # 高配当ポートフォリオの銘柄はトレード対象外
            if ticker in dividend_portfolio_management.dividend_symbols:
                print(ticker, "is in dividend portfolio. skipped.")
                continue
            else:
                print('Executing gap up trade for', ticker)
                process[ticker] = subprocess.Popen(['python3', TRADE_PY_FILE, str(ticker), '--swing', 'True',
                                                    '--pos_size', str(size), '--range', '0', '--dynamic_rate', 'False',
                                                    '--ema_trail', 'False'])

        for ticker in tickers:
            process[ticker].wait()


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

        print(f"取得した中型・小型株銘柄数: {len(symbols)}")
        return symbols

    except Exception as e:
        print(f"中型・小型株銘柄リストの取得に失敗: {str(e)}")
        raise

def get_historical_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """EODHDから株価データを取得"""
    # 銘柄名のピリオドをハイフンに置換（例：BRK.B → BRK-B）
    api_symbol = symbol.replace('.', '-')
    print(f"データ取得開始: {symbol} (API用シンボル: {api_symbol})")

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
        print(f"株価データの取得に失敗: {symbol}, {str(e)}")
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


if __name__ == '__main__':
    swing_earnings_stocks()
