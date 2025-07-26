import requests
import pandas as pd
import io
import time
import subprocess
import os
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from api_clients import get_alpaca_client

import news_analysis

load_dotenv()

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

test_mode = False
test_datetime = pd.Timestamp(datetime.now().astimezone(TZ_NY))

ALPACA_ACCOUNT = 'paper'

if ALPACA_ACCOUNT == 'live':
    TRADE_PY_FILE = 'src/orb.py'
else:
    TRADE_PY_FILE = 'src/orb_paper.py'

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
api = alpaca_client.api  # 後方互換性のため

# FinvizのAPIキー設定
FINVIZ_API_KEY = os.getenv('FINVIZ_API_KEY')

# Finvizリトライ設定
FINVIZ_MAX_RETRIES = 5  # 最大リトライ回数
FINVIZ_RETRY_WAIT = 1   # 初回リトライ待機時間（秒）

EXCLUDE_EARNINGS = True  # 決算発表を行った銘柄は除外
NUMBER_OF_STOCKS = 4
MINUTES_FROM_OPEN = 2
#TRADE_PY_FILE = 'src/orb.py'
TRADE_PY_FILE = 'src/orb_paper.py'


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
                            time.sleep(1)
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


def get_earnings_tickers():
    url = f"https://elite.finviz.com/export.ashx?v=151&f=cap_smallover,earningsdate_yesterdayafter|todaybefore," \
          f"sh_avgvol_o200,sh_price_o10,ta_volatility_1tox&ft=4&o=-epssurprise&ar=60&c=0,1," \
          f"2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28," \
          f"29,30,31,84,32,33,34,35,36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52," \
          f"53,54,55,56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101," \
          f"104,102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&&auth=" \
          f"{FINVIZ_API_KEY} "

    # # test for this week earnings
    # url = f"https://elite.finviz.com/export.ashx?v=151&f=cap_smallover,earningsdate_thisweek," \
    #       f"sh_avgvol_o200,sh_price_o10,ta_volatility_1tox&ft=4&o=-epssurprise&ar=60&c=0,1," \
    #       f"2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28," \
    #       f"29,30,31,84,32,33,34,35,36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52," \
    #       f"53,54,55,56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101," \
    #       f"104,102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&&auth=" \
    #       f"{FINVIZ_API_KEY} "

    tickers = []

    retries = 0
    while retries < FINVIZ_MAX_RETRIES:

        resp = requests.get(url)
        print(resp)

        if resp.status_code == 200:
            df = pd.read_csv(io.BytesIO(resp.content), sep=",")

            if df is not None:
                for ticker in df['Ticker']:
                    if ticker not in tickers:
                        tickers.append(ticker)
            break

        elif resp.status_code == 429:
            retries += 1
            wait_time = FINVIZ_RETRY_WAIT * (2 ** (retries - 1))
            print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        else:
            print("Failed to get tickers. Exit trading.")
            break

    return tickers


def trade_relative_volume_stocks(num):
    filtered_df = []
    url = f"https://elite.finviz.com/export.ashx?v=151&p=i3&f=cap_smallover,ind_stocksonly,sh_avgvol_o200," \
            f"sh_price_o10,sh_relvol_o1.5,ta_change_u2&ft=4&o=-relativevolume&ar=10&c=0,1,2,79,3,4,5,6,7,8,9,10," \
            f"11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32," \
            f"33,34,35,36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55," \
            f"56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104," \
            f"102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth=" \
            f"{FINVIZ_API_KEY}"

    # wait until the market opens and then wait for 2 minutes
    sleep_until_open(time_to_minutes=0)
    time.sleep(60 * MINUTES_FROM_OPEN)

    retries = 0
    while retries < FINVIZ_MAX_RETRIES:

        resp = requests.get(url)

        if resp.status_code == 200:
            df = pd.read_csv(io.BytesIO(resp.content), sep=",")
            print(df)
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
    #         # Total score > 5
    #         filtered_df = df[df['score'] > 5]


            # Filter top N tickers
            filtered_df = df.sort_values(by='No.', ascending=True).head(20)
            break

        elif resp.status_code == 429:
            retries += 1
            wait_time = FINVIZ_RETRY_WAIT * (2 ** (retries - 1))
            print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        else:
            print("Failed to get tickers. Exit trading.")
            return

    earnings_tickers = get_earnings_tickers()

    process = {}
    tickers = []

    for ticker in filtered_df['Ticker']:
        if EXCLUDE_EARNINGS and ticker in earnings_tickers:
            print(ticker, "Skip tickers with earnings release.")
            continue

        result = news_analysis.analyze(ticker, datetime.today().strftime('%Y-%m-%d'))
        # result = news_analysis.analyze(ticker, "2024-10-18")  # for test
        print(ticker, result)

        if int(result['category']) < 5:  # 1. 決算発表, 2. 業績予想, 3. アナリストレーティング, 4. S&P指数への組み込み
            print('Executing gap up trade for', ticker)
            process[ticker] = subprocess.Popen(['python3', TRADE_PY_FILE, str(ticker), '--swing', 'False',
                                                '--pos_size', 'auto', '--range', '5', '--dynamic_rate', 'True',
                                                '--ema_trail', 'True'])
            tickers.append(ticker)
            if len(tickers) >= num:
                break

    print('Trading tickers: ', tickers)

    for ticker in tickers:
        process[ticker].wait()

    # export screening result
    filtered_df.to_csv('export.csv', index=False)


if __name__ == '__main__':
    trade_relative_volume_stocks(NUMBER_OF_STOCKS)
