import argparse
import datetime
from datetime import timedelta
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client, get_finviz_client
import pandas_ta as ta
import pandas as pd
import time
import math
import os
import requests
import io
from dotenv import load_dotenv
from logging_config import get_logger
from config import trading_config, timing_config, retry_config

import uptrend_stocks
import dividend_portfolio_management
import trend_reversion_etf

from common_constants import ACCOUNT, TIMEZONE
load_dotenv()
logger = get_logger(__name__)

# Finvizスクリーナーのフィルター設定
EARNINGS_FILTERS = {
    'cap': 'smallover',
    'earningsdate': 'todayafter|tomorrowbefore',
    'ind': 'stocksonly',
    'sh_avgvol': 'o500',
    'sh_price': 'o10'
}

EARNINGS_COLUMNS = [
    0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,
    36,37,38,39,40,41,90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68,70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,
    100,101,104,102,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105
]

ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
finviz_client = get_finviz_client()

# スイングトレードの管理対象外
EXCLUDED_SYMBOL_LIST = trend_reversion_etf.LONG_SYMBOLS + \
                       trend_reversion_etf.SHORT_SYMBOLS + \
                       dividend_portfolio_management.dividend_symbols

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

# 設定値は config.py から取得
MAX_STOP_RATE = trading_config.MAX_STOP_RATE

test_mode = False
test_datetime = ""

api = alpaca_client.api  # 後方互換性のため


def get_upcoming_earnings():
    tickers = []

    # FinvizClientを使用してスクリーナーURLを構築
    screener_url = finviz_client.build_screener_url(
        filters=EARNINGS_FILTERS,
        columns=EARNINGS_COLUMNS,
        order='-relativevolume'
    )
    
    # スクリーナーデータを取得
    df = finviz_client.get_screener_data(screener_url)
    
    if df is not None and len(df) > 0:
        for ticker in df['Ticker']:
            tickers.append(ticker)
    else:
        logger.error("Failed to get upcoming earnings data from Finviz.")

    logger.info(f'Tickers upcoming earnings: {tickers}')

    return tickers


def get_latest_close(symbol):
    global test_datetime

    if test_mode:
        bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
                            start=test_datetime.date(), end=test_datetime.date()).df

        start_time = pd.Timestamp(test_datetime) - timedelta(minutes=timing_config.DATA_LOOKBACK_MINUTES)
        end_time = pd.Timestamp(test_datetime)

        bars = bars.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())

        close = bars['close'].tail(1).iloc[0]

    else:
        bar = api.get_latest_bar(symbol)
        close = bar.c

    return close


def is_closing_time_range(range_minutes=timing_config.DEFAULT_MINUTES_TO_CLOSE):
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

    start_dt = current_dt - timedelta(days=period_ema * trading_config.EMA_LOOKBACK_MULTIPLIER)

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


def crossed_below_ema_within_n_days(symbol, period_ema, days=2, threshold=0.02):
    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    # 過去n日分のデータを取得するため、EMA計算に十分なデータを含めて取得
    start_dt = current_dt - timedelta(days=period_ema * trading_config.EMA_LOOKBACK_MULTIPLIER)
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

            # 前日の終値がEMA以上で、当日の終値がEMAを閾値以上下回った場合
            if previous_close >= previous_ema and current_close < current_ema * (1 - threshold):
                print(symbol, f"crossed below EMA with threshold {threshold} within {days} days")
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

    start_dt = current_dt - timedelta(days=period_ema * trading_config.EMA_LOOKBACK_MULTIPLIER)

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


def close_position(symbol, qty, retries=retry_config.ORDER_MAX_RETRIES, delay=retry_config.ORDER_RETRY_DELAY):
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
        return

    if pos is not None:
        ema = round(get_ema(symbol, trading_config.EMA_PERIOD_SHORT), 2)
        latest_close = get_latest_close(symbol)
        avg_entry_price = round(float(pos.avg_entry_price), 2)

        if direction == 'long':
            if avg_entry_price * (1 + trading_config.MAX_STOP_RATE * 2) < latest_close:
                
                if avg_entry_price < ema < latest_close:
                    print("new stop is ema after securing +12% profit.")
                    new_stop = ema
                else:
                    # EMA がエントリー価格を下回る場合は、利益確保のため平均約定値で固定
                    print("ema is below entry price. keeping average entry price as stop.")
                    new_stop = avg_entry_price
            else:
                print("new stop is MAX_STOP_RATE.", trading_config.MAX_STOP_RATE)
                new_stop = round(avg_entry_price * (1 - trading_config.MAX_STOP_RATE), 2)
        else:  # short position
            if avg_entry_price * (1 - trading_config.MAX_STOP_RATE * 2) > latest_close:
                
                if latest_close < ema < avg_entry_price:
                    print("new stop is ema after securing +12% profit.")
                    new_stop = ema
                else:
                    print("ema is above entry price. keeping average entry price as stop.")
                    new_stop = avg_entry_price
            else:
                print("new stop is MAX_STOP_RATE.", trading_config.MAX_STOP_RATE)
                new_stop = round(avg_entry_price * (1 + trading_config.MAX_STOP_RATE), 2)

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
                            time.sleep(timing_config.TEST_MODE_SLEEP)
                        else:
                            time.sleep(timing_config.PRODUCTION_SLEEP_MINUTE)
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


def close_positions_before_earnings():
    """決算前のポジションをクローズする"""
    logger.info("Checking positions with upcoming earnings.")
    tickers = get_upcoming_earnings()
    
    if len(tickers) == 0:
        logger.info("No positions with upcoming earnings found.")
        return
    
    positions = get_existing_positions()
    for pos in positions:
        if pos.symbol in EXCLUDED_SYMBOL_LIST:
            logger.info(f"{pos.symbol} is on excluded symbol list. skipped.")
            continue
        
        if pos.symbol in tickers:
            logger.info(f"Closing position before upcoming earnings: {pos.symbol}")
            close_position(pos.symbol, float(pos.qty))


def update_all_stop_orders():
    """全ポジションのストップオーダーを更新する"""
    positions = get_existing_positions()
    for pos in positions:
        if pos.symbol in EXCLUDED_SYMBOL_LIST:
            logger.info(f"{pos.symbol} is on excluded symbol list. skipped.")
            continue
        else:
            logger.info(f"Updating stop order for {pos.symbol}")
            update_stop_order(pos.symbol)


def verify_stop_orders():
    """全ポジションにストップオーダーが設定されているか確認する"""
    positions = get_existing_positions()
    for pos in positions:
        if pos.symbol in EXCLUDED_SYMBOL_LIST:
            logger.info(f"{pos.symbol} is on excluded symbol list. skipped.")
            continue
        else:
            orders = api.list_orders(symbols=[pos.symbol])
            if len(orders) == 0:
                logger.warning(f"{pos.symbol} does not have stop order. Resubmitting stop order.")
                update_stop_order(pos.symbol, cancel_order=False)
            else:
                logger.info(f"{pos.symbol} stop order confirmed.")


def execute_position_maintenance():
    """ポジションメンテナンスのメイン処理を実行"""
    # 決算前のポジションをクローズ
    close_positions_before_earnings()
    
    # ストップオーダーを更新
    update_all_stop_orders()
    
    # ストップオーダーの存在を確認
    verify_stop_orders()


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
            logger.warning("market will not open today. exit process.")
            return

    # テストモードの場合は1回だけ実行
    if test_mode:
        if is_closing_time_range(range_minutes=close_time_range):
            execute_position_maintenance()
    else:
        # 本番モード：市場クローズ時間まで待って実行
        while True:
            sleep_until_next_close(time_to_minutes=close_time_range)
            
            if is_closing_time_range(range_minutes=close_time_range):
                execute_position_maintenance()
                break
            
            time.sleep(timing_config.PRODUCTION_SLEEP_MEDIUM)


if __name__ == '__main__':
    maintain_swing_position()
