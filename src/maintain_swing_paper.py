import argparse
import datetime
from datetime import timedelta
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
import pandas_ta as ta
import pandas as pd
import time
import math
import os
from zoneinfo import ZoneInfo
import requests
import io
from dotenv import load_dotenv

import uptrend_stocks
import dividend_portfolio_management
import trend_reversion_etf

load_dotenv()

# FinvizのAPIキー設定
FINVIZ_API_KEY = os.getenv('FINVIZ_API_KEY')

# Finvizリトライ設定
FINVIZ_MAX_RETRIES = 5  # 最大リトライ回数
FINVIZ_RETRY_WAIT = 1   # 初回リトライ待機時間（秒）

# FINVIZ_SCREEN_EARNINGS = "https://elite.finviz.com/export.ashx?v=151&p=i3&f=cap_smallover,earningsdate_todayafter|tomorrowbefore,ind_stocksonly,sh_avgvol_o500,sh_price_o10&ft=4&o=-relativevolume&ar=10&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105&auth=0d1b37f2-0b77-4d66-8776-63ff5362f253"
FINVIZ_SCREEN_EARNINGS = f"https://elite.finviz.com/export.ashx?v=151&p=i3&f=cap_smallover," \
                         f"earningsdate_todayafter|tomorrowbefore,ind_stocksonly,sh_avgvol_o500," \
                         f"sh_price_o10&ft=4&o=-relativevolume&ar=10&c=0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75," \
                         f"14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35," \
                         f"36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55," \
                         f"56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103," \
                         f"100,101,104,102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123," \
                         f"124,105&auth={FINVIZ_API_KEY}"

ALPACA_ACCOUNT = 'paper_short'  # Changed to match api_clients mapping

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)

# スイングトレードの管理対象外
EXCLUDED_SYMBOL_LIST = trend_reversion_etf.LONG_SYMBOLS + \
                       trend_reversion_etf.SHORT_SYMBOLS + \
                       dividend_portfolio_management.dividend_symbols

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

MAX_STOP_RATE = 0.06

test_mode = False
test_datetime = ""

api = alpaca_client.api  # 後方互換性のため


def get_upcoming_earnings():
    tickers = []

    retries = 0
    while retries < FINVIZ_MAX_RETRIES:
        resp = requests.get(FINVIZ_SCREEN_EARNINGS)

        if resp.status_code == 200:
            df = pd.read_csv(io.BytesIO(resp.content), sep=",")
            for ticker in df['Ticker']:
                tickers.append(ticker)
            break

        elif resp.status_code == 429:
            retries += 1
            wait_time = FINVIZ_RETRY_WAIT * (2 ** (retries - 1))
            print(f"Rate limit exceeded. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        else:
            print(f"Error fetching data from Finviz. Status code: {resp.status_code}")
            break

    print('Tickers upcoming earnings', tickers)

    return tickers


def get_latest_close(symbol):
    global test_datetime

    if test_mode:
        bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
                            start=test_datetime.date(), end=test_datetime.date()).df

        start_time = pd.Timestamp(test_datetime) - timedelta(minutes=5)
        end_time = pd.Timestamp(test_datetime)

        bars = bars.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())

        close = bars['close'].tail(1).iloc[0]

    else:
        bar = api.get_latest_bar(symbol)
        close = bar.c

    return close


def is_closing_time_range(range_minutes=1):
    if test_mode:
        # close_dt = pd.Timestamp(str(test_datetime.date()) + " " + str(close_time), tz=TZ_NY)
        # close_dt -= timedelta(minutes=2)
        current_dt = pd.Timestamp(test_datetime)
    else:
        # close_dt = pd.Timestamp(str(datetime.date.today()) + " " + str(close_time), tz=TZ_NY)
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


def is_long_position(position):
    """
    ポジションがロングポジションかどうかを判定する
    Args:
        position: Alpacaのポジションオブジェクト
    Returns:
        bool: ロングポジションの場合はTrue、ショートポジションの場合はFalse
    """
    return float(position.qty) > 0


def get_position_direction(position):
    """
    ポジションの方向性を取得する
    Args:
        position: Alpacaのポジションオブジェクト
    Returns:
        str: 'long' または 'short'
    """
    return 'long' if is_long_position(position) else 'short'


def get_existing_positions():
    positions = api.list_positions()
    print("current positions", positions)
    for pos in positions:
        direction = get_position_direction(pos)
        print(f"Position {pos.symbol}: {direction} position with qty {pos.qty}")
    return positions


def is_below_ema(symbol, period_ema):
    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    start_dt = current_dt - timedelta(days=period_ema * 10)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_dt.strftime("%Y-%m-%d")

    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=start_date, end=end_date).df

    if bars.size > 0:
        bars['EMA'] = ta.ema(bars['close'], length=period_ema)

        if bars['EMA'].tail(1).iloc[0] is not None:
            ema = float(bars['EMA'].tail(1).iloc[0])
        else:
            ema = 0

        latest_price = float(bars['close'].tail(1).iloc[0])
        print(symbol, "ema", period_ema, ema, latest_price)

        if ema != 0 and latest_price < ema:
            print(symbol, "is below ema")
            return True
    else:
        print(symbol, "failed to get bars")

    print(symbol, "is above ema", period_ema)
    return False


def crossed_below_ema_within_n_days(symbol, period_ema, days=2):
    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    # 過去n日分のデータを取得するため、EMA計算に十分なデータを含めて取得
    start_dt = current_dt - timedelta(days=period_ema * 10)
    end_date = current_dt.strftime("%Y-%m-%d")
    start_date = start_dt.strftime("%Y-%m-%d")

    # バー情報を取得
    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=start_date, end=end_date).df

    if bars.size > 0:
        # EMAを計算
        bars['EMA'] = ta.ema(bars['close'], length=period_ema)

        # 最新の(n+1)日分のデータをチェック
        recent_bars = bars.tail(days + 1)

        if len(recent_bars) < (days + 1):
            print(symbol, "Not enough data to check EMA cross")
            return False

        # 最新の(n+1)日間の価格とEMAの関係を確認
        for i in range(1, len(recent_bars)):
            previous_close = recent_bars['close'].iloc[i - 1]
            previous_ema = recent_bars['EMA'].iloc[i - 1]
            current_close = recent_bars['close'].iloc[i]
            current_ema = recent_bars['EMA'].iloc[i]

            # 前日の終値がEMA以上で、当日の終値がEMAを下回った場合
            if previous_close >= previous_ema and current_close < current_ema:
                print(symbol, f"crossed below EMA within {days} days")
                return True

    else:
        print(symbol, "failed to get bars")

    print(symbol, f"did not cross below EMA within {days} days")
    return False


def get_ema(symbol, period_ema):
    global test_datetime
    ema = 0

    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    start_dt = current_dt - timedelta(days=period_ema * 10)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_dt.strftime("%Y-%m-%d")

    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=start_date, end=end_date).df

    if bars.size > 0:
        bars['EMA'] = ta.ema(bars['close'], length=period_ema)
        if bars['EMA'].tail(1).iloc[0] is not None:
            ema = round(float(bars['EMA'].tail(1).iloc[0]), 2)
    else:
        print(symbol, "failed to get bars")

    return ema


def close_position(symbol, qty, retries=3, delay=0.5):
    try:
        pos = api.get_position(symbol)
        if pos is None:
            print(f"No position found for {symbol}")
            return

        direction = get_position_direction(pos)
        print(f"Closing {direction} position for {symbol} with qty {qty}")

    except Exception as error:
        print(symbol, "getting position has been failed.", error)
        return

    if pos is not None:
        orders = api.list_orders(symbols=[symbol])

        for order in orders:
            print("cancel order", order)
            try:
                api.cancel_order(order.id)
                print(symbol, "order canceled", order.symbol, order.id, order.qty)

            except Exception as error:
                print(symbol, "failed to cancel order.", error)

        time.sleep(delay)

        if abs(float(pos.qty)) >= abs(float(qty)):
            for attempt in range(retries):
                try:
                    side = 'sell' if direction == 'long' else 'buy'
                    print(f"submitting {side} order", symbol, "qty", qty)
                    resp = api.submit_order(symbol=symbol,
                                         qty=qty,
                                         side=side,
                                         type='market',
                                         time_in_force='day')
                    print(resp)
                    return

                except Exception as error:
                    print(symbol,
                          f"Attempt {attempt + 1}:", "submit order has been failed.", error)
                    time.sleep(delay)

            print("order failed after retries.")

        else:
            print("qty is larger than ", pos.qty)


def update_stop_order(symbol, cancel_order=True):
    resp = None
    pos = None

    if cancel_order:
        orders = api.list_orders(symbols=[symbol])

        for order in orders:
            try:
                api.cancel_order(order.id)
                print(symbol, "order canceled", order.symbol, order.id, order.qty)

            except Exception as error:
                print(symbol, "failed to cancel order.", error)

    try:
        pos = api.get_position(symbol)
        if pos is None:
            print(f"No position found for {symbol}")
            return

        direction = get_position_direction(pos)
        print(f"Updating stop order for {direction} position {symbol}")

    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to get position.", error)

    if pos is not None:
        ema = round(get_ema(symbol, 21), 2)
        latest_close = get_latest_close(symbol)
        avg_entry_price = round(float(pos.avg_entry_price), 2)

        if direction == 'long':
            if avg_entry_price * (1 + MAX_STOP_RATE) < latest_close:
                if avg_entry_price < ema < latest_close:
                    print("new stop is ema.")
                    new_stop = ema
                else:
                    print("new stop is average entry price.")
                    new_stop = avg_entry_price
            else:
                print("new stop is MAX_STOP_RATE.", MAX_STOP_RATE)
                new_stop = round(avg_entry_price * (1 - MAX_STOP_RATE), 2)
        else:  # short position
            if avg_entry_price * (1 - MAX_STOP_RATE) > latest_close:
                if latest_close < ema < avg_entry_price:
                    print("new stop is ema.")
                    new_stop = ema
                else:
                    print("new stop is average entry price.")
                    new_stop = avg_entry_price
            else:
                print("new stop is MAX_STOP_RATE.", MAX_STOP_RATE)
                new_stop = round(avg_entry_price * (1 + MAX_STOP_RATE), 2)

        print(symbol, "updated stop order", new_stop, "qty", pos.qty)

        try:
            side = 'sell' if direction == 'long' else 'buy'
            resp = api.submit_order(
                symbol=symbol,
                side=side,
                type='stop',
                qty=abs(float(pos.qty)),
                time_in_force='gtc',
                stop_price=str(new_stop)
            )
            print(resp)

        except Exception as error:
            print(datetime.datetime.now().astimezone(TZ_NY),
                  "failed to submit order.", error)

    return resp


def sleep_until_next_close(time_to_minutes=1):
    global test_datetime
    if test_mode:
        market_dt = test_datetime.date()
    else:
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
            if test_mode:
                current_dt = pd.Timestamp(test_datetime)
            else:
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
                        if test_mode:
                            time.sleep(0.01)
                        else:
                            time.sleep(60)
                    else:
                        print(current_dt, "close time reached.")
                        break

                    if test_mode:
                        test_datetime += timedelta(minutes=time_to_minutes)
                        current_dt = pd.Timestamp(test_datetime)
                    else:
                        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
                break

            if test_mode:
                test_datetime += timedelta(minutes=time_to_minutes)


def maintain_swing_position():
    global test_mode, test_datetime
    open_time = '15:50:50'

    ap = argparse.ArgumentParser()
    ap.add_argument('--close_time_range', default=2)
    ap.add_argument('--test_mode', default=False)
    ap.add_argument('--test_date', default='2023-12-22')
    args = vars(ap.parse_args())

    test_mode = args['test_mode']
    close_time_range = args['close_time_range']

    if test_mode:
        test_datetime = pd.Timestamp(args['test_date'] + " " + str(open_time), tz=TZ_NY)
    else:
        cal = api.get_calendar(start=str(datetime.date.today()), end=str(datetime.date.today()))
        if len(cal) <= 0:
            print("market will not open today. exit process.")
            return

    # テストモードの場合は1回だけ実行
    if test_mode:
        if is_closing_time_range(range_minutes=close_time_range):
            # Close positions with upcoming earnings
            print("Checking positions with upcoming earnings.")
            tickers = get_upcoming_earnings()
            if len(tickers) > 0:
                positions = get_existing_positions()
                for pos in positions:
                    if pos.symbol in EXCLUDED_SYMBOL_LIST:
                        print(pos.symbol, "is on excluded symbol list. skipped.")
                        continue

                    if pos.symbol in tickers:
                        direction = get_position_direction(pos)
                        if direction == 'short':
                            print(datetime.datetime.now().astimezone(TZ_NY),
                                  "closing short position with upcoming earnings", pos.symbol)
                            close_position(pos.symbol, float(pos.qty))
                        elif uptrend_stocks.is_downtrend():
                            print(datetime.datetime.now().astimezone(TZ_NY),
                                  "closing long position with upcoming earnings in downtrend", pos.symbol)
                            close_position(pos.symbol, float(pos.qty))
                        else:
                            print(datetime.datetime.now().astimezone(TZ_NY),
                                  "keeping long position with upcoming earnings as market is not in downtrend", pos.symbol)

            positions = get_existing_positions()
            for pos in positions:
                if pos.symbol in EXCLUDED_SYMBOL_LIST:
                    print(pos.symbol, "is on excluded symbol list. skipped.")
                    continue
                else:
                    if crossed_below_ema_within_n_days(pos.symbol, 21, days=1):
                        print(datetime.datetime.now().astimezone(TZ_NY), "closing all position of", pos.symbol)
                        close_position(pos.symbol, pos.qty)
                    else:
                        print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                              "is still above 21 EMA. Do nothing.")
                        update_stop_order(pos.symbol)

            # double check if stop orders are placed
            positions = get_existing_positions()
            for pos in positions:
                if pos.symbol in EXCLUDED_SYMBOL_LIST:
                    print(pos.symbol, "is on excluded symbol list. skipped.")
                    continue
                else:
                    orders = api.list_orders(symbols=[pos.symbol])
                    if len(orders) == 0:
                        print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                              "does not have stop order. Resubmitting stop order.")
                        update_stop_order(pos.symbol, cancel_order=False)
                    else:
                        print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                              "stop order confirmed.")
    else:
        while True:
            sleep_until_next_close(time_to_minutes=close_time_range)

            if is_closing_time_range(range_minutes=close_time_range):
                # Close positions with upcoming earnings
                print("Checking positions with upcoming earnings.")
                tickers = get_upcoming_earnings()
                if len(tickers) > 0:
                    positions = get_existing_positions()
                    for pos in positions:
                        if pos.symbol in EXCLUDED_SYMBOL_LIST:
                            print(pos.symbol, "is on excluded symbol list. skipped.")
                            continue

                        if pos.symbol in tickers:
                            direction = get_position_direction(pos)
                            if direction == 'short':
                                print(datetime.datetime.now().astimezone(TZ_NY),
                                      "closing short position with upcoming earnings", pos.symbol)
                                close_position(pos.symbol, float(pos.qty))
                            elif uptrend_stocks.is_downtrend():
                                print(datetime.datetime.now().astimezone(TZ_NY),
                                      "closing long position with upcoming earnings in downtrend", pos.symbol)
                                close_position(pos.symbol, float(pos.qty))
                            else:
                                print(datetime.datetime.now().astimezone(TZ_NY),
                                      "keeping long position with upcoming earnings as market is not in downtrend", pos.symbol)

                positions = get_existing_positions()
                for pos in positions:
                    if pos.symbol in EXCLUDED_SYMBOL_LIST:
                        print(pos.symbol, "is on excluded symbol list. skipped.")
                        continue
                    else:
                        if crossed_below_ema_within_n_days(pos.symbol, 21, days=1):
                            print(datetime.datetime.now().astimezone(TZ_NY), "closing all position of", pos.symbol)
                            close_position(pos.symbol, pos.qty)
                        else:
                            print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                                  "is still above 21 EMA. Do nothing.")
                            update_stop_order(pos.symbol)

                # double check if stop orders are placed
                positions = get_existing_positions()
                for pos in positions:
                    if pos.symbol in EXCLUDED_SYMBOL_LIST:
                        print(pos.symbol, "is on excluded symbol list. skipped.")
                        continue
                    else:
                        orders = api.list_orders(symbols=[pos.symbol])
                        if len(orders) == 0:
                            print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                                  "does not have stop order. Resubmitting stop order.")
                            update_stop_order(pos.symbol, cancel_order=False)
                        else:
                            print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                                  "stop order confirmed.")
                break

            time.sleep(10)


if __name__ == '__main__':
    maintain_swing_position()
