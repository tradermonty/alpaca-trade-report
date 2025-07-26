import requests
import io
import argparse
import datetime
import pandas as pd
import time
from datetime import timedelta
import os
from dotenv import load_dotenv

from api_clients import get_alpaca_client, get_finviz_client

import uptrend_stocks
import dividend_portfolio_management
import strategy_allocation
import risk_management

from common_constants import ACCOUNT, TIMEZONE
load_dotenv()

ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
finviz_client = get_finviz_client()

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

# Finvizスクリーナーのフィルター設定
TREND_REVERSION_FILTERS = {
    'cap': 'midover',
    'fa_epsqoq': 'o10',
    'fa_epsrev': '5tox1to',
    'fa_fpe': 'profitable',
    'fa_salesqoq': 'o10',
    'sec': 'technology|industrials|healthcare|communicationservices|consumercyclical|financial|utilities|realestate|consumerdefensive',
    'sh_avgvol': 'o1000',
    'sh_price': 'o10',
    'ta_rsi': 'nob60',
    'ta_sma200': 'pa',
    'ta_sma50': 'pa',
    'ta_volatility': '1.5tox'
}

TREND_REVERSION_COLUMNS = [
    0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,36,37,38,39,40,41,
    90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68,70,
    80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110,
    111,112,113,114,115,116,117,118,119,120,121,122,123,124,105
]

# LONG_SIGNAL_COL = "Q"  # Long Signal
# SHORT_SIGNAL_COL = "W"  # Short Signal

# 設定値をconfig.pyから取得
from config import trading_config
NUMBER_STOCKS = trading_config.TREND_REVERSION_NUMBER_STOCKS
LIMIT_RATE = trading_config.TREND_REVERSION_LIMIT_RATE
STOP_RATE = trading_config.TREND_REVERSION_STOP_RATE  # 8% stop
PROFIT_RATE = trading_config.TREND_REVERSION_PROFIT_RATE  # 40% profit
UPTREND_THRESH = trading_config.UPTREND_THRESHOLD

api = alpaca_client.api  # 後方互換性のため


def get_tickers_from_screener(num):
    filtered_df = None
    tickers = []

    # FinvizClientを使用してスクリーナーURLを構築
    screener_url = finviz_client.build_screener_url(
        filters=TREND_REVERSION_FILTERS,
        columns=TREND_REVERSION_COLUMNS,
        order='-marketcap'
    )
    
    # スクリーナーデータを取得
    df = finviz_client.get_screener_data(screener_url)
    
    if df is not None and len(df) > 0:
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

        # EPS growth this year 25%-: 1
        df['EPS growth this year'] = df['EPS growth this year'].str.replace('%', '').astype(float) / 100.0
        df.loc[df['EPS growth this year'] > 0.25, 'score'] += 1

        # EPS growth next year 25%-: 1
        df['EPS growth next year'] = df['EPS growth next year'].str.replace('%', '').astype(float) / 100.0
        df.loc[df['EPS growth next year'] > 0.25, 'score'] += 1

        # Sales growth 8-25%: 1, 25%-: 2
        df['Sales growth quarter over quarter'] = df['Sales growth quarter over quarter'].str.replace('%', '').astype(float) / 100.0
        df.loc[df['Sales growth quarter over quarter'] > 0.08, 'score'] += 1
        df.loc[df['Sales growth quarter over quarter'] > 0.25, 'score'] += 1

        # EPS growth 8-25%: 1, 25%-: 2
        df['EPS growth quarter over quarter'] = df['EPS growth quarter over quarter'].str.replace('%', '').astype(float) / 100.0
        df.loc[df['EPS growth quarter over quarter'] > 0.08, 'score'] += 1
        df.loc[df['EPS growth quarter over quarter'] > 0.25, 'score'] += 1

        # Total score > 0
        filtered_df = df[df['score'] > 0]

        filtered_df = filtered_df.sort_values(by='score', ascending=False)

        # Filter top # tickers
        filtered_df = filtered_df.head(num)
    else:
        print("Failed to get trend reversion data from Finviz.")
        return []

    # append tickers from screener
    if filtered_df is not None:
        for ticker in filtered_df['Ticker']:
            if ticker not in tickers:
                ticker = ticker.replace('-', '.')
                tickers.append(ticker)

    return tickers


def is_closing_time_range(range_minutes=1):
    current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    cal = api.get_calendar(start=str(current_dt.date()), end=str(current_dt.date()))
    if len(cal) > 0:
        close_time = cal[0].close
        close_dt = pd.Timestamp(str(current_dt.date()) + " " + str(close_time), tz=TZ_NY)
    else:
        print("market will not open on the date.")
        return

    if close_dt - timedelta(minutes=range_minutes) <= current_dt < close_dt:
        print("past closing time")
        return True
    else:
        print(current_dt, "it's not in closing time range")
        return False


def sleep_until_next_close(time_to_minutes=1):
    market_dt = datetime.date.today()

    days = 1

    cal = api.get_calendar(start=str(market_dt), end=str(market_dt))

    while True:
        if len(cal) == 0:
            market_dt += timedelta(days=days)
            cal = api.get_calendar(start=str(market_dt), end=str(market_dt))
            days += 1
        else:
            close_time = cal[0].close
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

            next_close_dt = pd.Timestamp(str(market_dt) + " " + str(close_time), tz=TZ_NY)

            if current_dt > next_close_dt:
                market_dt += timedelta(days=days)
                cal = api.get_calendar(start=str(market_dt), end=str(market_dt))
                days += 1
            else:
                while True:
                    if next_close_dt > current_dt + timedelta(minutes=time_to_minutes):
                        print("time to next close", next_close_dt - current_dt)
                        time.sleep(60)
                    else:
                        print(current_dt, "close time reached.")
                        break

                    current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
                break


def get_latest_close(symbol):
    bar = api.get_latest_bar(symbol)
    close = bar.c

    return close


def get_entry_limit(entry_price):
    return round(entry_price * (1 + LIMIT_RATE), 2)


def get_profit_target(entry_price, profit_rate):
    return round(entry_price * (1 + profit_rate), 2)


def get_stop_price(entry_price, stop_rate):
    return round(entry_price * (1 - stop_rate), 2)


def send_bracket_order(symbol, qty, limit_price, profit_target, stop_price):
    resp = api.submit_order(
        symbol=symbol,
        side='buy',
        # type='market',
        type='limit',
        qty=qty,
        limit_price=limit_price,
        time_in_force='gtc',
        order_class='bracket',
        take_profit=dict(
            limit_price=profit_target,
        ),
        stop_loss=dict(
            stop_price=stop_price,
        )
    )
    return resp


def close_position(symbol, qty=0, retries=3, delay=0.5):
    try:
        pos = api.get_position(symbol)

    except Exception as error:
        print(symbol, "getting position has been failed.", error)
        return

    if pos is not None:
        if qty == 0:
            qty = pos.qty

        orders = api.list_orders(symbols=[symbol])

        for order in orders:
            print("cancel order", order)
            try:
                api.cancel_order(order.id)
                print(symbol, "order canceled", order.symbol, order.id, order.qty)
                time.sleep(delay)

            except Exception as error:
                print(symbol, "failed to cancel order.", error)

        for attempt in range(retries):
            try:
                print("submitting sell order", symbol, "qty", qty)
                resp = api.submit_order(symbol=symbol,
                                        qty=qty,
                                        side='sell',
                                        type='market',
                                        time_in_force='day')
                print(resp)
                return

            except Exception as error:
                print(symbol,
                      f"Attempt {attempt + 1}:", "submit sell order has been failed.", error)
                time.sleep(delay)

        print("sell order failed after retries.")


def buy(symbol, pos_size):
    entry_price = get_latest_close(symbol)
    qty = int(pos_size / entry_price)

    if qty < 1:
        print("the stock price is higher than your position size. set qty=1.")
        qty = 1

    limit_price = get_entry_limit(entry_price)
    profit_target = get_profit_target(entry_price, PROFIT_RATE)
    stop_price = get_stop_price(entry_price, STOP_RATE)

    try:
        print("submit buy order - ", symbol)
        order = send_bracket_order(symbol, qty, limit_price, profit_target, stop_price)
        print(order)

    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to submit order.", symbol, error)


def sell(symbol):
    pos = None

    try:
        pos = api.get_position(symbol)

    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to get position.", symbol, error)

    if pos is not None:
        print("submit sell order - ", symbol)
        close_position(symbol)


def get_existing_positions():
    positions = api.list_positions()
    print("current positions", positions)
    return positions


def run_trend_reversion_trade():

    if not risk_management.check_pnl_criteria():
        print('recent trading pnl is below criteria. exit trading.')
        return

    ap = argparse.ArgumentParser()
    ap.add_argument('--pos_size')
    ap.add_argument('--close_time_range', default=3)
    args = vars(ap.parse_args())

    if args['pos_size'] is None:
        # target allocation size for strategy #2
        target_value = strategy_allocation.get_target_value('strategy2', account=ALPACA_ACCOUNT)
        pos_size = int(target_value / NUMBER_STOCKS)
    else:
        pos_size = int(args['pos_size'])

    close_time_range = args['close_time_range']

    cal = api.get_calendar(start=str(datetime.date.today()), end=str(datetime.date.today()))
    if len(cal) <= 0:
        print("market will not open today. exiting trade.")
        return

    while True:
        sleep_until_next_close(time_to_minutes=close_time_range)
        if is_closing_time_range(range_minutes=close_time_range):
            break

    long_signal = uptrend_stocks.get_long_signal()
    uptrend_ratio = uptrend_stocks.get_ratio()

    print("long signal: ", long_signal)

    # finvizのスクリーナーでトレードする銘柄を抽出
    symbols = get_tickers_from_screener(NUMBER_STOCKS)

    if long_signal == "Entry" and uptrend_ratio < UPTREND_THRESH:
        print("long trade - trend revert to up")
        for symbol in symbols:
            # 高配当ポートフォリオの銘柄はトレード対象外
            if symbol in dividend_portfolio_management.dividend_symbols:
                print(symbol, "is in dividend portfolio. skipped.")
                continue
            else:
                buy(symbol, pos_size)
                time.sleep(1)
    else:
        print("long trade - do nothing")


if __name__ == '__main__':
    run_trend_reversion_trade()
