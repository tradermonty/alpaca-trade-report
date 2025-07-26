import requests
import pandas as pd
import io
import time
import subprocess
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv

import alpaca_trade_api as tradeapi
from alpaca_trade_api.common import URL

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import dividend_portfolio_management
import strategy_allocation
import risk_management

load_dotenv()

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

test_mode = False
test_datetime = pd.Timestamp(datetime.now().astimezone(TZ_NY))

ALPACA_ACCOUNT = 'paper2'

if ALPACA_ACCOUNT == 'live':
    TRADE_PY_FILE = 'src/orb_short.py'
else:
    TRADE_PY_FILE = 'src/orb_short_paper.py'

# Alpaca APIの設定
if ALPACA_ACCOUNT == 'live':
    # Alpaca API credentials for live account
    ALPACA_BASE_URL = URL('https://api.alpaca.markets')
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY_LIVE')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY_LIVE')
elif ALPACA_ACCOUNT == 'paper2':
    # Alpaca API credentials for paper account "Day trade test"
    ALPACA_BASE_URL = URL('https://paper-api.alpaca.markets')
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY_PAPER_SHORT')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY_PAPER_SHORT')
else:
    # Alpaca API credentials for paper account
    ALPACA_BASE_URL = URL('https://paper-api.alpaca.markets')
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY_PAPER')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY_PAPER')

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# FinvizのAPIキー設定
FINVIZ_API_KEY = os.getenv('FINVIZ_API_KEY')

# Finvizリトライ設定
FINVIZ_MAX_RETRIES = 5  # 最大リトライ回数
FINVIZ_RETRY_WAIT = 1   # 初回リトライ待機時間（秒）


# SCREENER: 基本情報フィルター
# - 市場時価総額 (Market Cap.): $1B-$30B
# - 決算日 (Earnings Date): 昨日の引け後または本日の寄り付き前
# - EPSサプライズ (EPS Surprise): 予想を5%以上下回る
# - 地域 (Country): アメリカ
# - 平均出来高 (Average Volume): 200K株以上
# - 株価 (Price): $10以上
# - 変化 (Change): 当日株価が下落
# - 月間パフォーマンス (Performance - Month): 過去4週間で下落
# - ボラティリティ (Volatility): 1週間で1%以上

SCREENER_URL = f"https://elite.finviz.com/export.ashx?v=151&f=cap_smallover,earningsdate_yesterdayafter|todaybefore," \
               f"fa_epsrev_en,geo_usa,sh_avgvol_o200,sh_price_o10,ta_change_d,ta_gap_d,ta_perf_4wdown,ta_volatility_1tox" \
               f"&ft=4&o=epssurprise&ar=60&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13," \
               f"73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35," \
               f"36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58," \
               f"80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110," \
               f"125,126,59,68,70,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth={FINVIZ_API_KEY}"


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
                tickers.append(symbol)

                # シンボルを削除（該当するセルを空にする）
                worksheet.update_cell(i + 2, symbol_col, '')  # i+2: データ部分のインデックスに1行目のヘッダーを考慮

    print('Trading tickers: ', tickers)

    return tickers


def get_tickers_from_screener(url, num):
    filtered_df = None
    tickers = []

    retries = 0

    while retries < FINVIZ_MAX_RETRIES:
        resp = requests.get(url)
        print(resp)

        if resp.status_code == 200:
            df = pd.read_csv(io.BytesIO(resp.content), sep=",")
            df['score'] = 0

            # EPS Surprise -5%以下: 1, -8%以下: 2, -15%以下: 4, -30%以下: 6
            df['EPS Surprise'] = df['EPS Surprise'].str.replace('%', '').astype(float) / 100.0
            df.loc[df['EPS Surprise'] < -0.05, 'score'] += 1
            df.loc[df['EPS Surprise'] < -0.08, 'score'] += 1
            df.loc[df['EPS Surprise'] < -0.10, 'score'] += 2
            df.loc[df['EPS Surprise'] < -0.30, 'score'] += 2

            # Revenue Surprise -2%以下: 1, -8%以下: 2, -15%以下: 3
            df['Revenue Surprise'] = df['Revenue Surprise'].str.replace('%', '').astype(float) / 100.0
            df.loc[df['Revenue Surprise'] < -0.02, 'score'] += 1
            df.loc[df['Revenue Surprise'] < -0.08, 'score'] += 1
            df.loc[df['Revenue Surprise'] < -0.15, 'score'] += 1

            # Price Change -1%以下: 1, -8%以下: 2
            df['Change'] = df['Change'].str.replace('%', '').astype(float) / 100.0
            df.loc[df['Change'] < -0.01, 'score'] += 1
            df.loc[df['Change'] < -0.08, 'score'] += 1

            # Relative Volume 1.0-: 2, 1.5-: 4, 2.0-: 6
            df.loc[df['Relative Volume'] > 1.0, 'score'] += 2
            df.loc[df['Relative Volume'] > 1.5, 'score'] += 2
            df.loc[df['Relative Volume'] > 2.0, 'score'] += 2

            # Total score > 0
            filtered_df = df[df['score'] > 0]

            # export screening result
            filtered_df.to_csv('earnings/screen_short_' + datetime.today().strftime('%Y-%m-%d') + '.csv', index=False)

            filtered_df = filtered_df.sort_values(by='score', ascending=False)

            print(filtered_df)

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


def swing_earnings_stocks_short():
    process = {}

    if not risk_management.check_pnl_criteria():
        print('recent trading pnl is below criteria. exit trading.')
        return

    # target allocation size for strategy #1
    target_value = strategy_allocation.get_target_value('strategy1', account=ALPACA_ACCOUNT)
    if ALPACA_ACCOUNT == 'paper2':
        size = 'auto'
    else:
        size = int(target_value * 0.06 / 3)
    print(size)
    
    # wait until 2 minutes before the market opens
    sleep_until_open(time_to_minutes=2)

    try:
        # get tickers from finviz screener
        tickers_screener = get_tickers_from_screener(SCREENER_URL, NUMBER_OF_STOCKS)

    except Exception as error:
        print("failed to get tickers from finviz screener.")
        tickers_screener = []

    try:
        # get tickers from google spreadsheet
        tickers_sheet = get_tickers_from_sheet()

    except Exception as error:
        print("failed to get tickers from google spreadsheet.")
        tickers_sheet = []

    # combine two and remove duplicated tickers
    tickers = list(set(tickers_screener+tickers_sheet))

    print('Trading tickers: ', tickers)

    if len(tickers) > 0:
        for ticker in tickers:
            # 高配当ポートフォリオの銘柄はトレード対象外
            if ticker in dividend_portfolio_management.dividend_symbols:
                print(ticker, "is in dividend portfolio. skipped.")
                continue
            else:
                print('Executing gap down trade for', ticker)
                process[ticker] = subprocess.Popen(['python3', TRADE_PY_FILE, str(ticker), '--swing', 'True',
                                                    '--pos_size', str(size), '--range', '0', '--dynamic_rate', 'False',
                                                    '--ema_trail', 'False'])

        for ticker in tickers:
            process[ticker].wait()


if __name__ == '__main__':
    swing_earnings_stocks_short()
