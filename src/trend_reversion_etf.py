import argparse
import datetime
import pandas as pd
import time
from datetime import timedelta
import math
import numpy as np
import matplotlib.pyplot as plt
import os
from dotenv import load_dotenv

from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
import pandas_ta as ta

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import uptrend_stocks
import strategy_allocation
import risk_management

from common_constants import ACCOUNT, TIMEZONE
load_dotenv()

ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

# LONG_SYMBOLS = ["IWM", "IWR", "EQAL", "SMH", "IPO"]
LONG_SYMBOLS = ["IWR", "TNA"]
# SHORT_SYMBOLS = ["HDGE", "DWSH", "BTAL", "DOG", "RWM"]
SHORT_SYMBOLS = ["DWSH", "BTAL"]

LIMIT_RATE = 0.005
STOP_RATE = 0.04  # 4% stop
PROFIT_RATE = 0.20  # 20% profit
UPTREND_THRESH = 0.25

api = alpaca_client.api  # 後方互換性のため


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


def sell_half(symbol):
    pos = None

    try:
        pos = api.get_position(symbol)

    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to get position.", symbol, error)

    if pos is not None:
        print("submit sell order - ", symbol)
        close_position(symbol, math.ceil(float(pos.qty) / 2))


def get_existing_positions():
    positions = api.list_positions()
    print("current positions", positions)
    return positions


def get_ema(symbol, period_ema):
    global test_datetime
    ema = 0

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

    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to get position.", error)

    if pos is not None:
        ema = round(get_ema(symbol, 21), 2)
        latest_close = get_latest_close(symbol)
        avg_entry_price = round(float(pos.avg_entry_price), 2)
        if avg_entry_price * (1 + STOP_RATE * 2) < latest_close:
            # EMAと最新価格の乖離を計算
            ema_deviation = (latest_close - ema) / ema
            
            if avg_entry_price < ema < latest_close and ema_deviation > 0.05:  # 5%以上の乖離がある場合のみ
                print("new stop is ema due to significant price movement above EMA.")
                new_stop = ema
            else:
                print("new stop is average entry price to protect initial profit.")
                new_stop = avg_entry_price
        else:
            print("new stop is STOP_RATE.", STOP_RATE)
            new_stop = round(avg_entry_price * (1 - STOP_RATE), 2)


        try:
            # stop order
            print(symbol, "updated stop order", new_stop, "qty", pos.qty)
            resp = api.submit_order(
                symbol=symbol,
                side='sell',
                type='stop',
                qty=pos.qty,
                time_in_force='gtc',
                stop_price=str(new_stop)
            )
            print(resp)

            # limit order
            profit_target = get_profit_target(avg_entry_price, PROFIT_RATE)
            print(symbol, "resubmit limit order", profit_target, "qty", pos.qty)
            resp = api.submit_order(
                symbol=symbol,
                side='sell',
                type='limit',
                qty=pos.qty,
                time_in_force='gtc',
                limit_price=str(profit_target)
            )
            print(resp)

        except Exception as error:
            print(datetime.datetime.now().astimezone(TZ_NY),
                  "failed to submit order.", error)

    return resp


def run_trend_reversion_trade():

    ap = argparse.ArgumentParser()
    ap.add_argument('--pos_size')
    ap.add_argument('--close_time_range', default=3)
    args = vars(ap.parse_args())

    if args['pos_size'] is None:
        # target allocation size for strategy #2
        target_value_long = strategy_allocation.get_target_value('strategy3', account=ALPACA_ACCOUNT)
        pos_size_long = int(target_value_long / len(LONG_SYMBOLS))

        target_value_short = strategy_allocation.get_target_value('strategy4', account=ALPACA_ACCOUNT)
        pos_size_short = int(target_value_short / len(SHORT_SYMBOLS))
    else:
        pos_size_long = int(args['pos_size'])
        pos_size_short = int(args['pos_size'])

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
    short_signal = uptrend_stocks.get_short_signal()
    uptrend_ratio = uptrend_stocks.get_ratio()

    print("long signal: ", long_signal)
    print("short signal: ", short_signal)

    if long_signal == "Entry" and uptrend_ratio < UPTREND_THRESH:
        # if not risk_management.check_pnl_criteria():
        #     print('recent trading pnl is below criteria. skip trading.')
        # else:
        print("long trade - trend revert to up")
        for symbol in LONG_SYMBOLS:
            buy(symbol, pos_size_long)
            time.sleep(1)
    elif long_signal == "Exit":
        print("long trade - trend revert to down")
        for symbol in LONG_SYMBOLS:
            sell(symbol)
            time.sleep(1)
    elif uptrend_stocks.is_overbought(check_prev=True):
        print("overbought")
        for symbol in LONG_SYMBOLS:
            sell_half(symbol)
            time.sleep(1)
    else:
        print("long trade - do nothing")

    if short_signal == "Entry" and uptrend_ratio > UPTREND_THRESH:
        # if not risk_management.check_pnl_criteria():
        #     print('recent trading pnl is below criteria. skip trading.')
        # else:
        print("short trade - trend revert to up")
        for symbol in SHORT_SYMBOLS:
            buy(symbol, pos_size_short)
            time.sleep(1)
    elif short_signal == "Exit":
        print("short trade - trend revert to down")
        for symbol in SHORT_SYMBOLS:
            sell(symbol)
            time.sleep(1)
    elif uptrend_stocks.is_oversold(check_prev=True):
        print("oversold")
        for symbol in SHORT_SYMBOLS:
            sell_half(symbol)
            time.sleep(1)
    else:
        print("short trade - do nothing")

    # update stop orders
    positions = get_existing_positions()
    for pos in positions:
        if (pos.symbol in LONG_SYMBOLS and long_signal != "Entry") \
                or (pos.symbol in SHORT_SYMBOLS and short_signal != "Entry"):
            update_stop_order(pos.symbol)
            time.sleep(1)

    # double check if stop orders are placed
    positions = get_existing_positions()
    for pos in positions:
        if pos.symbol in LONG_SYMBOLS or pos.symbol in SHORT_SYMBOLS:
            orders = api.list_orders(symbols=[pos.symbol])
            if len(orders) == 0:
                print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                      "does not have stop order. Resubmitting stop order.")
                update_stop_order(pos.symbol, cancel_order=False)
                time.sleep(1)
            else:
                print(datetime.datetime.now().astimezone(TZ_NY), pos.symbol,
                      "stop order confirmed.")

    # cancel orders if there are ones without position
    orders = api.list_orders(
        status='open',
        limit=100,
        nested=True
    )
    positions = get_existing_positions()
    open_position_symbols = {position.symbol for position in positions}

    for order in orders:
        if order.symbol in LONG_SYMBOLS or order.symbol in SHORT_SYMBOLS:
            if order.symbol not in open_position_symbols:
                print(f"Order for {order.symbol} found, but no open position exists.")
                print(f"Cancelling Order ID: {order.id}...")

                api.cancel_order(order.id)
                print("Order cancelled successfully.")


def create_test_data(entry_price, days, pattern='v_shape'):
    """
    テストデータを作成する関数
    pattern: 
    - 'v_shape' (V字回復)
    - 'uptrend' (上昇トレンド)
    - 'dead_cat' (下落反発)
    - 'sharp_drop' (急落後の反発)
    - 'sideways' (横ばい相場)
    - 'double_bottom' (ダブルボトム)
    - 'head_shoulder' (ヘッドアンドショルダー)
    - 'trend_pullback' (上昇トレンド中の調整)
    """
    dates = pd.date_range(start=datetime.datetime.now(), periods=days, freq='D')
    
    if pattern == 'v_shape':
        # V字回復パターン
        first_half = np.linspace(entry_price * 1.2, entry_price * 0.8, days//2)
        second_half = np.linspace(entry_price * 0.8, entry_price * 1.3, days//2)
        prices = np.concatenate([first_half, second_half])
        entry_day = days//2
        
    elif pattern == 'uptrend':
        # 上昇トレンドパターン
        first_half = np.linspace(entry_price * 0.9, entry_price * 0.8, days//3)
        second_half = np.linspace(entry_price * 0.8, entry_price * 1.0, days//3)
        third_half = np.linspace(entry_price * 1.0, entry_price * 1.3, days//3)
        prices = np.concatenate([first_half, second_half, third_half])
        entry_day = days//3 * 2
        
    elif pattern == 'dead_cat':
        # 下落反発パターン
        first_half = np.linspace(entry_price * 1.2, entry_price * 0.9, days//2)
        second_half = np.linspace(entry_price * 0.9, entry_price * 0.8, days//2)
        prices = np.concatenate([first_half, second_half])
        entry_day = days//2
        
    elif pattern == 'sharp_drop':
        # 急落後の反発パターン
        drop = np.linspace(entry_price * 1.2, entry_price * 0.7, days//3)
        bounce = np.linspace(entry_price * 0.7, entry_price * 1.1, days//3)
        consolidation = np.linspace(entry_price * 1.1, entry_price * 1.15, days//3)
        prices = np.concatenate([drop, bounce, consolidation])
        entry_day = days//3  # 急落後の反発時点でエントリー
        
    elif pattern == 'sideways':
        # 横ばい相場パターン
        base = np.ones(days) * entry_price
        oscillation = np.sin(np.linspace(0, 4*np.pi, days)) * entry_price * 0.05
        prices = base + oscillation
        entry_day = days//2  # 横ばい相場の真ん中でエントリー
        
    elif pattern == 'double_bottom':
        # ダブルボトムパターン
        quarter = days // 4
        remainder = days % 4
        
        # 余剰日数を各セクションに分配
        first_drop = np.linspace(entry_price * 1.2, entry_price * 0.8, quarter + (remainder > 0))
        first_bounce = np.linspace(entry_price * 0.8, entry_price * 1.0, quarter + (remainder > 1))
        second_drop = np.linspace(entry_price * 1.0, entry_price * 0.8, quarter + (remainder > 2))
        second_bounce = np.linspace(entry_price * 0.8, entry_price * 1.3, quarter)
        
        prices = np.concatenate([first_drop, first_bounce, second_drop, second_bounce])
        entry_day = len(first_drop) + len(first_bounce) + len(second_drop)//2  # 2つ目の底でエントリー
        
    elif pattern == 'head_shoulder':
        # ヘッドアンドショルダーパターン
        quarter = days // 4
        remainder = days % 4
        
        # 余剰日数を各セクションに分配
        left_shoulder = np.linspace(entry_price * 0.9, entry_price * 1.1, quarter + (remainder > 0))
        head = np.linspace(entry_price * 1.1, entry_price * 1.3, quarter + (remainder > 1))
        right_shoulder = np.linspace(entry_price * 1.3, entry_price * 1.1, quarter + (remainder > 2))
        breakdown = np.linspace(entry_price * 1.1, entry_price * 0.8, quarter)
        
        prices = np.concatenate([left_shoulder, head, right_shoulder, breakdown])
        entry_day = len(left_shoulder) + len(head) + len(right_shoulder)//2  # 右肩の形成時点でエントリー
        
    elif pattern == 'trend_pullback':
        # 上昇トレンド中の調整パターン
        # 30日を正確に分割
        uptrend = np.linspace(entry_price * 0.8, entry_price * 1.3, 15)  # 前半15日
        pullback = np.linspace(entry_price * 1.3, entry_price * 1.1, 7)  # 中間7日
        continuation = np.linspace(entry_price * 1.1, entry_price * 1.4, 8)  # 後半8日
        
        prices = np.concatenate([uptrend, pullback, continuation])
        entry_day = len(uptrend) + len(pullback)//2  # 調整局面でエントリー
    
    # ノイズを追加（パターンに応じて調整）
    if pattern in ['dead_cat', 'sharp_drop']:
        noise = np.random.normal(0, 0.005, days)  # 下落パターンはノイズを小さく
    elif pattern == 'sideways':
        noise = np.random.normal(0, 0.01, days)  # 横ばい相場は適度なノイズ
    else:
        noise = np.random.normal(0, 0.02, days)  # その他のパターンは通常のノイズ
    prices = prices * (1 + noise)
    
    # EMAを計算
    df = pd.DataFrame({'close': prices}, index=dates)
    df['ema'] = df['close'].ewm(span=21, adjust=False).mean()
    
    return df, entry_day

def plot_test_results(df, entry_price, pattern_name, entry_day, exit_day=None):
    plt.figure(figsize=(12, 6))
    
    # 価格とEMAのプロット
    plt.plot(df.index, df['close'], label='Price', color='blue')
    plt.plot(df.index, df['ema'], label='EMA(21)', color='orange', linestyle='--')
    
    # エントリー価格のライン
    plt.axhline(y=entry_price, color='green', linestyle='-', label='Entry Price')
    
    # ストップロスのライン
    current_stop = None
    stop_prices = []
    
    for i in range(entry_day, len(df)):
        latest_close = df['close'].iloc[i]
        ema = df['ema'].iloc[i]
        
        if entry_price * (1 + STOP_RATE * 2) < latest_close:
            if current_stop is None:
                current_stop = round(entry_price * (1 - STOP_RATE), 2)
            else:
                if ema > current_stop and latest_close > ema:
                    ema_deviation = (latest_close - ema) / ema
                    if ema_deviation > 0.05:
                        current_stop = ema
                elif entry_price < ema < latest_close:
                    current_stop = entry_price
        else:
            if current_stop is None:
                current_stop = round(entry_price * (1 - STOP_RATE), 2)
        
        stop_prices.append(current_stop)
        
        if exit_day is not None and i == exit_day:
            plt.axvline(x=df.index[i], color='red', linestyle=':', label='Stop Loss Triggered')
            break
    
    plt.plot(df.index[entry_day:entry_day+len(stop_prices)], stop_prices, label='Stop Loss', color='red', linestyle=':')
    
    # エントリーポイントのマーク（上向き三角形）
    plt.scatter(df.index[entry_day], df['close'].iloc[entry_day], 
                marker='^', color='green', s=100, label='Entry')
    
    # イグジットポイントのマーク（下向き三角形）
    if exit_day is not None:
        plt.scatter(df.index[exit_day], df['close'].iloc[exit_day], 
                    marker='v', color='red', s=100, label='Exit')
    
    # グラフの装飾
    plt.title(f'{pattern_name} Pattern Test')
    plt.xlabel('Date')
    plt.ylabel('Price')
    plt.legend()
    plt.grid(True)
    
    # 価格範囲の調整
    y_min = min(df['close'].min(), entry_price * 0.8)
    y_max = max(df['close'].max(), entry_price * 1.2)
    plt.ylim(y_min, y_max)
    
    plt.show()

def test_stop_order_behavior():
    # テストケース1: V字回復の底でエントリー
    print("\n=== テストケース1: V字回復の底でエントリー ===")
    v_shape_data, entry_day = create_test_data(100, 30, 'v_shape')
    entry_price = v_shape_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(v_shape_data, entry_price, entry_day)
    plot_test_results(v_shape_data, entry_price, 'V-Shape', entry_day, exit_day)
    
    # テストケース2: V回復後の上昇トレンドでエントリー
    print("\n=== テストケース2: V回復後の上昇トレンドでエントリー ===")
    uptrend_data, entry_day = create_test_data(100, 30, 'uptrend')
    entry_price = uptrend_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(uptrend_data, entry_price, entry_day)
    plot_test_results(uptrend_data, entry_price, 'Uptrend', entry_day, exit_day)
    
    # テストケース3: 下落反発でエントリー
    print("\n=== テストケース3: 下落反発でエントリー ===")
    dead_cat_data, entry_day = create_test_data(100, 30, 'dead_cat')
    entry_price = dead_cat_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(dead_cat_data, entry_price, entry_day)
    plot_test_results(dead_cat_data, entry_price, 'Dead Cat Bounce', entry_day, exit_day)
    
    # テストケース4: 急落後の反発でエントリー
    print("\n=== テストケース4: 急落後の反発でエントリー ===")
    sharp_drop_data, entry_day = create_test_data(100, 30, 'sharp_drop')
    entry_price = sharp_drop_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(sharp_drop_data, entry_price, entry_day)
    plot_test_results(sharp_drop_data, entry_price, 'Sharp Drop Bounce', entry_day, exit_day)
    
    # テストケース5: 横ばい相場でエントリー
    print("\n=== テストケース5: 横ばい相場でエントリー ===")
    sideways_data, entry_day = create_test_data(100, 30, 'sideways')
    entry_price = sideways_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(sideways_data, entry_price, entry_day)
    plot_test_results(sideways_data, entry_price, 'Sideways', entry_day, exit_day)
    
    # テストケース6: ダブルボトムでエントリー
    print("\n=== テストケース6: ダブルボトムでエントリー ===")
    double_bottom_data, entry_day = create_test_data(100, 30, 'double_bottom')
    entry_price = double_bottom_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(double_bottom_data, entry_price, entry_day)
    plot_test_results(double_bottom_data, entry_price, 'Double Bottom', entry_day, exit_day)
    
    # テストケース7: ヘッドアンドショルダーでエントリー
    print("\n=== テストケース7: ヘッドアンドショルダーでエントリー ===")
    head_shoulder_data, entry_day = create_test_data(100, 30, 'head_shoulder')
    entry_price = head_shoulder_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(head_shoulder_data, entry_price, entry_day)
    plot_test_results(head_shoulder_data, entry_price, 'Head and Shoulder', entry_day, exit_day)
    
    # テストケース8: 上昇トレンド中の調整でエントリー
    print("\n=== テストケース8: 上昇トレンド中の調整でエントリー ===")
    trend_pullback_data, entry_day = create_test_data(100, 30, 'trend_pullback')
    entry_price = trend_pullback_data['close'].iloc[entry_day]
    exit_day = test_stop_order_sequence(trend_pullback_data, entry_price, entry_day)
    plot_test_results(trend_pullback_data, entry_price, 'Trend Pullback', entry_day, exit_day)

def test_stop_order_sequence(df, entry_price, entry_day):
    current_stop = None
    for i in range(entry_day, len(df)):  # エントリーポイントから開始
        latest_close = df['close'].iloc[i]
        ema = df['ema'].iloc[i]
        
        # 価格が十分に上昇しているかチェック
        if entry_price * (1 + STOP_RATE * 2) < latest_close:
            if current_stop is None:
                # 初期ストップ
                current_stop = round(entry_price * (1 - STOP_RATE), 2)
                print(f"Day {i}: Initial stop set at {current_stop}")
            else:
                if ema > current_stop and latest_close > ema:
                    # EMAと最新価格の乖離を計算
                    ema_deviation = (latest_close - ema) / ema
                    
                    if ema_deviation > 0.05:
                        new_stop = ema
                        print(f"Day {i}: Stop moved up to EMA: {new_stop:.2f} (deviation: {ema_deviation:.2%})")
                        current_stop = new_stop
                    else:
                        print(f"Day {i}: EMA deviation too small ({ema_deviation:.2%}). Maintaining stop at {current_stop}")
                elif entry_price < ema < latest_close:
                    new_stop = entry_price
                    print(f"Day {i}: Stop set to entry price: {new_stop}")
                    current_stop = new_stop
                else:
                    print(f"Day {i}: Maintaining stop at {current_stop}")
        else:
            if current_stop is None:
                current_stop = round(entry_price * (1 - STOP_RATE), 2)
                print(f"Day {i}: Initial stop set at {current_stop}")
            else:
                print(f"Day {i}: Price not high enough. Maintaining stop at {current_stop}")
        
        # ストップロスが発動したかチェック
        if latest_close <= current_stop:
            print(f"Day {i}: STOP LOSS TRIGGERED! Price: {latest_close:.2f}, Stop: {current_stop}")
            return i  # イグジット日を返す
    
    return None  # イグジットなし


if __name__ == '__main__':
    # 通常のトレード実行
    run_trend_reversion_trade()
    
    # ストップロス動作テスト実行（コメントアウト）
    # print("=== ストップロス動作テスト開始 ===")
    # test_stop_order_behavior()
