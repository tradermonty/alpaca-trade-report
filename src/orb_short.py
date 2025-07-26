import argparse
import sys
from datetime import datetime, timedelta
import datetime
import os
from dotenv import load_dotenv
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
import pandas_ta as ta
import pandas as pd
import time
from zoneinfo import ZoneInfo
import math

load_dotenv()


ALPACA_ACCOUNT = 'paper_short'  # Changed to match api_clients mapping

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

LIMIT_RATE = 0.006
SLIPAGE_RATE = 0.003

# Default 1st order parameters: 3% stop and 6% profit for day trade
STOP_RATE_1 = 0.06
PROFIT_RATE_1 = 0.06

# Default 2nd order parameters: 4% stop and 8% profit for day trade
STOP_RATE_2 = 0.06
PROFIT_RATE_2 = 0.12

# Default 3rd order parameters: 8% stop and 30% profit for swing
STOP_RATE_3 = 0.06
PROFIT_RATE_3 = 0.30

# per order position size
POSITION_SIZE = 0

# making entries only within 150 minutes from the open
ENTRY_PERIOD = 120

opening_range = 0
test_mode = False
test_datetime = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
close_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
bars_1min = ""
bars_5min = ""

order_status = {"order1": {"qty": 0, "entry_time": "", "entry_price": 0, "exit_time": "", "exit_price": 0},
                "order2": {"qty": 0, "entry_time": "", "entry_price": 0, "exit_time": "", "exit_price": 0},
                "order3": {"qty": 0, "entry_time": "", "entry_price": 0, "exit_time": "", "exit_price": 0}}

api = alpaca_client.api  # 後方互換性のため


def get_latest_high(symbol):
    global test_datetime

    if test_mode:

        start_time = pd.Timestamp(test_datetime) - timedelta(minutes=60)
        end_time = pd.Timestamp(test_datetime)

        bars = bars_1min.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())

        high = bars['high'].tail(1).iloc[0]

    else:
        bar = api.get_latest_bar(symbol)
        high = bar.h

    return high


def get_latest_close(symbol):
    global test_datetime
    close = 0

    if test_mode:
        # bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
        #                     start=test_datetime.date(), end=test_datetime.date()).df

        start_time = pd.Timestamp(test_datetime) - timedelta(minutes=60)
        end_time = pd.Timestamp(test_datetime) - timedelta(minutes=1)

        bars = bars_1min.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())
        # bars = bars_1min[bars_1min.index <= end_time]
        if bars.size > 0:
            close = bars['close'].tail(1).iloc[0]

    else:
        bar = api.get_latest_bar(symbol)
        close = bar.c

    return close


def get_latest_bar(symbol):
    global test_datetime
    open = 0
    close = 0

    if test_mode:
        # bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
        #                     start=test_datetime.date(), end=test_datetime.date()).df

        start_time = pd.Timestamp(test_datetime) - timedelta(minutes=60)
        end_time = pd.Timestamp(test_datetime) - timedelta(minutes=1)

        bars = bars_1min.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())
        # bars = bars_1min[bars_1min.index <= end_time]
        if bars.size > 0:
            open = bars['open'].tail(1).iloc[0]
            close = bars['close'].tail(1).iloc[0]

    else:
        bar = api.get_latest_bar(symbol)
        open = bar.o
        close = bar.c

    return open, close


def get_position_size(entry_price):
    return int(POSITION_SIZE / entry_price)


def get_entry_limit(entry_price):
    return round(entry_price * (1 + LIMIT_RATE), 2)


def get_profit_target(entry_price, profit_rate):
    return round(entry_price * (1 + profit_rate), 2)


def get_stop_price(entry_price, stop_rate):
    return round(entry_price * (1 - stop_rate), 2)


def get_opening_range(symbol, period=2):
    global test_datetime
    opening_range_high = 0
    opening_range_low = 0

    if period > 30:
        period = 30

    if test_mode:
        current_time = test_datetime
    else:
        current_time = datetime.datetime.now().astimezone(TZ_NY)

    bars = api.get_bars(symbol, TimeFrame(period, TimeFrameUnit.Minute),
                        start=str(current_time.date()), end=str(current_time.date())).df

    start_time = pd.Timestamp(str(current_time.date()), tz=TZ_NY).replace(hour=9, minute=30, second=0)

    filtered_bars = bars.between_time(start_time.astimezone(TZ_UTC).time(), start_time.astimezone(TZ_UTC).time())

    if filtered_bars.size > 0:
        opening_range_high = filtered_bars['high'].max()
        opening_range_low = filtered_bars['low'].min()
    else:
        print(symbol, period, 'failed to get opening range. trying to get latest bar instead')

        start_time = pd.Timestamp(str(current_time.date()), tz=TZ_NY).replace(hour=9, minute=30, second=0)
        start_time -= timedelta(minutes=period)
        end_time = pd.Timestamp(str(current_time.date()), tz=TZ_NY).replace(hour=9, minute=30, second=0)
        end_time += timedelta(minutes=period)

        filtered_bars = bars.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())

        if filtered_bars.size > 0:
            opening_range_high = filtered_bars['high'].max()
            opening_range_low = filtered_bars['low'].min()

    return opening_range_high, opening_range_low


def is_above_ema(symbol, period_ema):
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

        if ema != 0 and latest_price > ema:
            print(symbol, "is above ema")
            return True
    else:
        print(symbol, "failed to get bars")

    print(symbol, "is below ema", period_ema)
    return False


def is_below_ema(symbol, timeframe=5, length=50):
    """
    価格がEMAの下にあるかどうかを判定する関数
    
    Args:
        symbol (str): 銘柄のシンボル
        timeframe (int): 時間枠（分）
        length (int): EMAの期間
        
    Returns:
        bool: 価格がEMAの下にある場合はTrue、それ以外はFalse
    """
    if test_mode:
        current_time = test_datetime
    else:
        current_time = datetime.datetime.now().astimezone(TZ_NY)

    days = math.ceil(length * timeframe / 360 * 2) + 3
    start_dt = current_time - timedelta(days=days)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_time.strftime("%Y-%m-%d")

    if test_mode:
        bars = bars_5min
    else:
        bars = api.get_bars(symbol, TimeFrame(timeframe, TimeFrameUnit.Minute), start=start_date, end=end_date).df

    if bars.size > 0:
        if test_mode:
            specific_date = pd.Timestamp(current_time.date())
            bars = bars[bars.index.date <= specific_date.date()]
            bars = bars[bars.index <= current_time - timedelta(minutes=5)]

        bars['EMA'] = ta.ema(bars['close'], length=length)

        if bars['EMA'].tail(1).iloc[0] is not None:
            ema = float(bars['EMA'].tail(1).iloc[0])
        else:
            ema = 0

        latest_open, latest_close = get_latest_bar(symbol)

        print(current_time, "ema", length, "price", ema, latest_open, latest_close)

        if ema != 0 and latest_close < ema:
            print(symbol, 'is below', length, 'ema')
            return True
    else:
        print("failed to get bars")

    print(symbol, 'is above', length, 'ema')
    return False


def is_opening_range_break(symbol, range_low):
    """
    オープニングレンジの下ブレイクを判定する関数
    
    Args:
        symbol (str): 銘柄のシンボル
        range_low (float): オープニングレンジの下限
        
    Returns:
        bool: オープニングレンジの下ブレイクの場合はTrue、それ以外はFalse
        
    Note:
        オープニングレンジの下ブレイクとは、価格がオープニングレンジの下限を下回ることです。
        これはショートエントリーのシグナルとして使用されます。
    """
    latest_close = get_latest_close(symbol)

    print("opening range low, latest close", range_low, latest_close)

    if latest_close < range_low:
        print(symbol, 'below Opening range low')
        return True
    else:
        print(symbol, 'above opening range low')
        return False


def is_entry_period(period=30):
    if test_mode:
        open_dt = pd.Timestamp(str(test_datetime.date()), tz=TZ_NY).replace(hour=9, minute=30, second=0)
        current_dt = test_datetime
    else:
        open_dt = pd.Timestamp(str(datetime.date.today()), tz=TZ_NY).replace(hour=9, minute=30, second=0)
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    if open_dt < current_dt < open_dt + timedelta(minutes=period):
        print("within entry period")
        return True
    else:
        print("entry period has ended")
        return False


def is_closing_time():
    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    if close_dt - timedelta(minutes=2) < current_dt:
        print("past closing time")
        return True
    else:
        print(current_dt, "it's not closing time yet")
        return False


def send_bracket_order(symbol, qty, limit_price, profit_target, stop_price):
    if test_mode:
        return False
    else:
        resp = api.submit_order(
            symbol=symbol,
            side='sell',
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


def submit_bracket_orders(symbol, dynamic_rate=True):
    """
    ショートポジション用の括弧注文を発注する関数
    
    Args:
        symbol (str): 銘柄のシンボル
        dynamic_rate (bool): 動的なストップロス/利益確定率を使用するかどうか
        
    Returns:
        tuple: (order1, order2, order3) - 3つの注文オブジェクト
        
    Note:
        3つの注文を発注します：
        1. 短期トレード用（小さいストップロス/利益確定）
        2. 中期トレード用（中程度のストップロス/利益確定）
        3. 長期トレード用（大きいストップロス/利益確定）
        
        dynamic_rate=Trueの場合、ボラティリティに基づいてストップロス/利益確定率が動的に調整されます。
    """
    global order_status
    order1 = None
    order2 = None
    order3 = None

    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    if dynamic_rate:
        set_stop_profit_rate(symbol)

    entry_price = get_latest_close(symbol)
    qty = get_position_size(entry_price)

    if qty < 1:
        print("the stock price is higher than your position size. set qty=1.")
        qty = 1

    # ショートポジション用の価格計算
    limit_price = round(entry_price * (1 - LIMIT_RATE), 2)  # エントリー価格より少し下で注文
    profit_target_1 = round(entry_price * (1 - PROFIT_RATE_1), 2)  # 利益確定価格
    stop_price_1 = round(entry_price * (1 + STOP_RATE_1), 2)  # ストップロス価格

    profit_target_2 = round(entry_price * (1 - PROFIT_RATE_2), 2)
    stop_price_2 = round(entry_price * (1 + STOP_RATE_2), 2)

    profit_target_3 = round(entry_price * (1 - PROFIT_RATE_3), 2)
    stop_price_3 = round(entry_price * (1 + STOP_RATE_3), 2)

    try:
        print("1st order", symbol, entry_price, limit_price, profit_target_1, stop_price_1, qty)
        order1 = send_bracket_order(symbol, qty, limit_price, profit_target_1, stop_price_1)
        order_status['order1']['entry_time'] = str(current_dt)
        order_status['order1']['entry_price'] = entry_price
        order_status['order1']['qty'] = qty

        print("2nd order", symbol, entry_price, limit_price, profit_target_2, stop_price_2, qty)
        order2 = send_bracket_order(symbol, qty, limit_price, profit_target_2, stop_price_2)
        order_status['order2']['entry_time'] = str(current_dt)
        order_status['order2']['entry_price'] = entry_price
        order_status['order2']['qty'] = qty

        print("3rd order", symbol, entry_price, limit_price, profit_target_3, stop_price_3, qty)
        order3 = send_bracket_order(symbol, qty, limit_price, profit_target_3, stop_price_3)
        order_status['order3']['entry_time'] = str(current_dt)
        order_status['order3']['entry_price'] = entry_price
        order_status['order3']['qty'] = qty

    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY),
              "failed to submit order.", error)

    print_order_status(order_status)

    return order1, order2, order3


def check_position(symbol):
    """
    ショートポジションの有無を確認する関数
    
    Args:
        symbol (str): 確認する銘柄のシンボル
        
    Returns:
        bool: ショートポジションがある場合はTrue、ない場合はFalse
    """
    try:
        positions = []
        resp = api.list_positions()

        for pos in resp:
            if pos.symbol == symbol and float(pos.qty) < 0:  # ショートポジションの場合
                positions.append(pos.symbol)

        if symbol in positions:
            print(f"ショートポジションがあります: {symbol}")
            return True
        else:
            print(f"ショートポジションはありません: {symbol}")
            return False
            
    except Exception as e:
        print(f"ポジション確認中にエラーが発生しました: {str(e)}")
        return False


def cancel_and_close_position(order, retries=3, delay=0.5):
    """
    ショートポジションをキャンセルしてクローズする関数
    
    Args:
        order: キャンセルする注文オブジェクト
        retries (int): リトライ回数
        delay (float): リトライ間隔（秒）
        
    Returns:
        resp: ポジションクローズのレスポンス
    """
    resp = None
    if test_mode:
        return resp

    print("注文のキャンセルとポジションのクローズ", datetime.datetime.now().astimezone(TZ_NY), order.symbol, order.qty)

    if order is None:
        print("注文が無効です")
        return resp

    if order.legs is not None:
        if len(order.legs) > 0:
            for sub_order in order.legs:
                try:
                    api.cancel_order(sub_order.id)
                    print(datetime.datetime.now().astimezone(TZ_NY), "サブ注文をキャンセルしました", resp)
                except Exception as error:
                    print(datetime.datetime.now().astimezone(TZ_NY), "サブ注文のキャンセルに失敗しました", error)

    try:
        api.cancel_order(order.id)
        print(datetime.datetime.now().astimezone(TZ_NY), "注文をキャンセルしました", resp)
    except Exception as error:
        print(datetime.datetime.now().astimezone(TZ_NY), "注文のキャンセルに失敗しました", error)

    if check_position(order.symbol):
        for attempt in range(retries):
            try:
                # order.qtyをfloat型に変換してからabs()関数を使用
                qty = abs(float(order.qty))
                resp = api.close_position(order.symbol, qty=qty)  # ショートポジションのクローズ
                print(resp)
                return resp
            except Exception as error:
                print(datetime.datetime.now().astimezone(TZ_NY),
                      f"試行 {attempt + 1}:",
                      "ポジションのクローズに失敗しました。ストップロス注文または利益確定注文で既にクローズされている可能性があります。",
                      error)
                time.sleep(delay)

        print("リトライ後もポジションのクローズに失敗しました")

    return resp


def print_order_status(d, indent=0):
    for key, value in d.items():
        print('\t' * indent + str(key))
        if isinstance(value, dict):
            print_order_status(value, indent + 1)
        else:
            print('\t' * (indent + 1) + str(value))


def get_opening_price(symbol):
    opening_price = 0
    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=str(datetime.date.today()),
                        end=str(datetime.date.today())).df
    if bars.size > 0:
        opening_price = bars['open'][0]

    return opening_price


def is_downtrend(symbol, timeframe=5, short=10, long=20):
    """
    銘柄が下降トレンドかどうかを判定する関数
    
    Args:
        symbol (str): 銘柄のシンボル
        timeframe (int): 時間枠（分）
        short (int): 短期EMAの期間
        long (int): 長期EMAの期間
        
    Returns:
        bool: 下降トレンドの場合はTrue、それ以外はFalse
        
    Note:
        下降トレンドの条件：
        - 価格が短期EMAの下にある
        - 短期EMAが長期EMAの下にある
        - 短期EMAが下降傾向にある
    """
    if test_mode:
        current_time = test_datetime
    else:
        current_time = datetime.datetime.now().astimezone(TZ_NY)

    days = math.ceil(long * 5 / 360 * 2) + 3
    start_dt = current_time - timedelta(days=days)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_time.strftime("%Y-%m-%d")

    if test_mode:
        bars = bars_5min
    else:
        bars = api.get_bars(symbol, TimeFrame(timeframe, TimeFrameUnit.Minute), start=start_date, end=end_date).df

    if bars.size > 0:
        if test_mode:
            specific_date = pd.Timestamp(current_time.date())
            bars = bars[bars.index <= current_time - timedelta(minutes=5)]

        bars['EMA10'] = ta.ema(bars['close'], length=short)
        bars['EMA20'] = ta.ema(bars['close'], length=long)

        if bars['EMA10'].tail(1).iloc[0] is not None:
            ema10 = float(bars['EMA10'].tail(1).iloc[0])
            is_ema10_down = (bars['EMA10'].tail(2).iloc[1] - bars['EMA10'].tail(2).iloc[0]) <= 0
            print("is ema 10 down?", is_ema10_down)
        else:
            ema10 = 0
        if bars['EMA20'].tail(1).iloc[0] is not None:
            ema20 = float(bars['EMA20'].tail(1).iloc[0])
        else:
            ema20 = 0

        latest_price = get_latest_close(symbol)

        print(current_time, "ema20, ema10, price", ema20, ema10, latest_price)

        if ema20 != 0 and latest_price < ema10 < ema20 and is_ema10_down:
            print('downtrend')
            return True
    else:
        print("failed to get bars")

    print('not downtrend')
    return False


def get_daily_volatility(symbol, period=6):
    volatility = 0.02
    if test_mode:
        current_time = test_datetime
    else:
        current_time = datetime.datetime.now().astimezone(TZ_NY)

    start_dt = current_time - timedelta(days=period * 30)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_time.strftime("%Y-%m-%d")

    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=start_date, end=end_date).df

    if bars.size > 0:
        bars['change'] = abs((bars['open'] - bars['close']) / bars['close'])
        volatility = bars['change'].mean()
    else:
        print("### use fixed volatility.")

    print("daily volatility", volatility)
    return volatility


def set_stop_profit_rate(symbol):
    global STOP_RATE_1, PROFIT_RATE_1, STOP_RATE_2, PROFIT_RATE_2, STOP_RATE_3, PROFIT_RATE_3

    try:
        # ボラティリティを取得
        volatility = get_daily_volatility(symbol)
        
        if volatility != 0:
            # 1st order: より厳密なリスク管理
            STOP_RATE_1 = volatility * 0.8  # ストップロスを少し狭く設定
            PROFIT_RATE_1 = volatility * 3  # 利益確定を3倍に設定

            # 2nd order: 中期的なリスク管理
            STOP_RATE_2 = volatility * 1.2
            PROFIT_RATE_2 = volatility * 5

            # 3rd order: より広いリスク管理（スイングトレード用）
            STOP_RATE_3 = volatility * 1.5
            PROFIT_RATE_3 = volatility * 8

        print('Order1 ストップロス:', STOP_RATE_1 * 100, '% 利益確定:', PROFIT_RATE_1 * 100, '%')
        print('Order2 ストップロス:', STOP_RATE_2 * 100, '% 利益確定:', PROFIT_RATE_2 * 100, '%')
        print('Order3 ストップロス:', STOP_RATE_3 * 100, '% 利益確定:', PROFIT_RATE_3 * 100, '%')
        
    except Exception as e:
        print(f"ストップロスと利益確定の設定中にエラーが発生しました: {str(e)}")
        # デフォルト値を設定
        STOP_RATE_1, PROFIT_RATE_1 = 0.02, 0.06
        STOP_RATE_2, PROFIT_RATE_2 = 0.03, 0.09
        STOP_RATE_3, PROFIT_RATE_3 = 0.04, 0.12


def get_ema(symbol, period_ema):
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


def start_trading():
    global test_mode, test_datetime, order_status, opening_range, POSITION_SIZE, close_dt, bars_1min, bars_5min
    close_time = '16:00:00'
    open_time = '09:30:01'
    current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    ap = argparse.ArgumentParser()
    ap.add_argument('symbol')
    ap.add_argument('--pos_size', default=3000)
    ap.add_argument('--range', default=5)
    ap.add_argument('--swing', default=True)
    ap.add_argument('--dynamic_rate', default=True)
    ap.add_argument('--test_mode', default=False)
    ap.add_argument('--test_date', default='2023-12-06')
    ap.add_argument('--ema_trail', default=False)
    ap.add_argument('--daily_log', default=False)
    ap.add_argument('--trend_check', default=True)
    args = vars(ap.parse_args())

    test_mode = args['test_mode']
    symbol = args['symbol']
    opening_range = int(args['range'])
    if isinstance(args['dynamic_rate'], str):
        dynamic_rate = args['dynamic_rate'] == 'True' or args['dynamic_rate'] == 'true'
    else:
        dynamic_rate = args['dynamic_rate']
    if isinstance(args['ema_trail'], str):
        ema_trail = args['ema_trail'] == 'True' or args['ema_trail'] == 'true'
    else:
        ema_trail = args['ema_trail']
    if isinstance(args['daily_log'], str):
        daily_log = args['daily_log'] == 'True' or args['daily_log'] == 'true'
    else:
        daily_log = args['daily_log']
    if isinstance(args['swing'], str):
        is_swing = args['swing'] == 'True' or args['swing'] == 'true'
    else:
        is_swing = args['swing']
    if isinstance(args['trend_check'], str):
        trend_check = args['trend_check'] == 'True' or args['trend_check'] == 'true'
    else:
        trend_check = args['trend_check']

    # ショート可能かどうかをチェック
    if not is_shortable(symbol):
        print(f"Trading stopped: {symbol} is not shortable")
        return

    account = api.get_account()
    portfolio_value = float(account.portfolio_value)
    position_market_value = float(account.position_market_value)

    if test_mode:
        print(is_swing)

        test_datetime = pd.Timestamp(args['test_date'] + " " + str(open_time), tz=TZ_NY)
        cal = api.get_calendar(start=str(test_datetime.date()), end=str(test_datetime.date()))
        if len(cal) > 0:
            close_time = cal[0].close
            close_dt = pd.Timestamp(str(test_datetime.date()) + " " + str(close_time), tz=TZ_NY)
        else:
            print("market will not open on the date. finish trading.")
            return

        days = math.ceil(50 * 5 / 360 * 2) + 3
        start_dt = (test_datetime - timedelta(days=days)).strftime("%Y-%m-%d")
        bars_1min = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
                                 start=start_dt, end=str(test_datetime.date())).df
        bars_5min = api.get_bars(symbol, TimeFrame(5, TimeFrameUnit.Minute),
                                 start=start_dt, end=str(test_datetime.date())).df

        # opening range time
        # test_datetime = test_datetime + timedelta(minutes=opening_range-1) + timedelta(seconds=59)
        test_datetime = test_datetime + timedelta(minutes=opening_range)
        current_dt = pd.Timestamp(test_datetime)


    elif portfolio_value * 1.5 < position_market_value:
        print("margin usage exceeds 50% of portfolio value. disabling swing trading.")
        is_swing = False

    # position size will be automatically calculated.
    if args['pos_size'] == 'auto':
        # ポートフォリオの0.3%をリスクとして設定
        risk_amount = portfolio_value * 0.001
        # デフォルトのストップロス率を使用してポジションサイズを計算
        POSITION_SIZE = int(risk_amount / (get_latest_close(symbol) * STOP_RATE_1))
    else:
        POSITION_SIZE = int(args['pos_size'])

    # 最小ポジションサイズを1に設定
    if POSITION_SIZE < 1:
        POSITION_SIZE = 1

    # 証拠金要件をチェック
    if not check_margin_requirements(symbol, POSITION_SIZE, get_latest_close(symbol)):
        print(f"Trading stopped: Margin requirements not met for {symbol}")
        return

    print('start trading', symbol, 'position size', POSITION_SIZE)

    if not test_mode:
        cal = api.get_calendar(start=str(datetime.date.today()), end=str(datetime.date.today()))
        if len(cal) > 0:
            close_time = cal[0].close
            open_time = cal[0].open

            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
            open_dt = pd.Timestamp(str(current_dt.date()) + " " + str(open_time), tz=TZ_NY)
            close_dt = pd.Timestamp(str(current_dt.date()) + " " + str(close_time), tz=TZ_NY)

            if open_dt > current_dt:
                seconds_to_open = (open_dt - current_dt).seconds
                print(datetime.datetime.now().astimezone(TZ_NY), "waiting for market open...", seconds_to_open,
                      "seconds")
                time.sleep(seconds_to_open)
        else:
            print("market will not open today. exit trading.")
            return

        market_clock = api.get_clock()

        while not market_clock.is_open:
            time.sleep(1)
            market_clock = api.get_clock()
            print(datetime.datetime.now().astimezone(TZ_NY), "waiting for market open...")

        # wait for opening range complete
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
        open_dt = pd.Timestamp(str(datetime.date.today()) + " " + str(open_time), tz=TZ_NY)
        opening_range_dt = open_dt + timedelta(minutes=opening_range)

        if current_dt < opening_range_dt:
            seconds_to_range_complete = (opening_range_dt - current_dt).seconds - 10
            print(datetime.datetime.now().astimezone(TZ_NY), "wait for opening range completion...",
                  seconds_to_range_complete)
            time.sleep(seconds_to_range_complete)

        while current_dt < opening_range_dt:
            print(datetime.datetime.now().astimezone(TZ_NY), "wait for opening range completion...")
            time.sleep(1)
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))


    if trend_check:
        downtrend = is_downtrend(symbol, short=10, long=20)
        below_ema = is_below_ema(symbol, timeframe=5, length=50)
    else:
        downtrend = True
        below_ema = True

    if opening_range != 0:
        range_high, range_low = get_opening_range(symbol, opening_range)
        range_break = is_opening_range_break(symbol, range_low)
    else:
        range_break = True

    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    while not (downtrend and below_ema and range_break):
        if test_mode:
            test_datetime += timedelta(minutes=1)
            # time.sleep(0.01)
        else:
            print(current_dt, "waiting for downtrend and opening range break...")
            time.sleep(60)

        if test_mode:
            current_dt = pd.Timestamp(test_datetime)
        else:
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

        open_dt = pd.Timestamp(str(current_dt.date()) + " " + str(open_time), tz=TZ_NY)

        if trend_check:
            downtrend = is_downtrend(symbol, short=10, long=20)
            below_ema = is_below_ema(symbol, timeframe=5, length=50)
        else:
            downtrend = True
            below_ema = True


        if opening_range != 0:
            range_break = is_opening_range_break(symbol, range_low)
        else:
            range_break = True

        if not is_entry_period(ENTRY_PERIOD):
            print("entry period ends. finish trading without entries.")
            return

    order1, order2, order3 = submit_bracket_orders(symbol, dynamic_rate)
    if order1 is None or order2 is None or order3 is None:
        print("####", current_dt, "failed to submit orders.")
        return

    order1_open = True
    order2_open = True
    order3_open = True

    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
    cal = api.get_calendar(start=str(current_dt.date()), end=str(current_dt.date()))
    close_dt = pd.Timestamp(str(current_dt.date()) + " " + str(cal[0].close), tz=TZ_NY)

    stop_price1 = get_stop_price(order_status['order1']['entry_price'], STOP_RATE_1)
    stop_price2 = get_stop_price(order_status['order2']['entry_price'], STOP_RATE_2)
    stop_price3 = get_stop_price(order_status['order3']['entry_price'], STOP_RATE_3)
    target_price1 = get_profit_target(order_status['order1']['entry_price'], PROFIT_RATE_1)
    target_price2 = get_profit_target(order_status['order2']['entry_price'], PROFIT_RATE_2)
    target_price3 = get_profit_target(order_status['order3']['entry_price'], PROFIT_RATE_3)

    while not is_closing_time():
        if test_mode:
            current_dt = pd.Timestamp(test_datetime)
        else:
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
        if order1_open == order2_open == order3_open == False:
            print(current_dt, "all orders closed")
            break
        if test_mode:
            # time.sleep(0.01)
            test_datetime += timedelta(minutes=1)
        else:
            if close_dt - timedelta(minutes=opening_range+1) < datetime.datetime.now().astimezone(TZ_NY):
                print(close_dt - datetime.datetime.now().astimezone(TZ_NY), "to close.")
                time.sleep(10)
            else:
                time.sleep(60)

        latest_price = get_latest_close(symbol)
        print(current_dt, symbol, "latest price", latest_price)

        if target_price1 < latest_price and order1_open:
            print("####", current_dt, symbol, "closing 1st order")
            cancel_and_close_position(order1)
            order1_open = False
            order_status['order1']['exit_time'] = str(current_dt)
            order_status['order1']['exit_price'] = target_price1

            # raise stop price for 2nd and 3rd orders.
            stop_price2 = order_status['order2']['entry_price']
            stop_price3 = order_status['order3']['entry_price']

        if target_price2 < latest_price and order2_open:
            print("####", current_dt, symbol, "closing 2nd order")
            cancel_and_close_position(order2)
            order2_open = False
            order_status['order2']['exit_time'] = str(current_dt)
            order_status['order2']['exit_price'] = target_price2

        if target_price3 < latest_price and order3_open:
            print("####", current_dt, symbol, "closing 3rd order")
            cancel_and_close_position(order3)
            order3_open = False
            order_status['order3']['exit_time'] = str(current_dt)
            order_status['order3']['exit_price'] = target_price3

        if stop_price1 > latest_price and order1_open:
            print("####", current_dt, symbol, "closing 1st order")
            cancel_and_close_position(order1)
            order1_open = False
            order_status['order1']['exit_time'] = str(current_dt)
            order_status['order1']['exit_price'] = stop_price1

        if stop_price2 > latest_price and order2_open:
            print("####", current_dt, symbol, "closing 2nd order")
            cancel_and_close_position(order2)
            order2_open = False
            order_status['order2']['exit_time'] = str(current_dt)
            order_status['order2']['exit_price'] = stop_price2

        if stop_price3 > latest_price and order3_open:
            print("####", current_dt, symbol, "closing 3rd order")
            cancel_and_close_position(order3)
            order3_open = False
            order_status['order3']['exit_time'] = str(current_dt)
            order_status['order3']['exit_price'] = stop_price3

        if test_mode:
            current_dt = pd.Timestamp(test_datetime)
        else:
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

        open_dt = pd.Timestamp(str(current_dt.date()) + " " + str(open_time), tz=TZ_NY)

        if ema_trail is not False:
            below_ema15 = is_below_ema(symbol, timeframe=5, length=15)
            if below_ema15:
                print(current_dt, symbol, "below 15ema")
            else:
                if order1_open:
                    print("####", current_dt, symbol, "closing 1st order")
                    cancel_and_close_position(order1)
                    order1_open = False
                    order_status['order1']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order1']['exit_price'] = latest_price

            below_ema21 = is_below_ema(symbol, timeframe=5, length=21)
            if below_ema21:
                print(current_dt, symbol, "below 21ema")
            else:
                if order2_open:
                    print("####", current_dt, symbol, "closing 2nd order")
                    cancel_and_close_position(order2)
                    order2_open = False
                    order_status['order2']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order2']['exit_price'] = latest_price

            below_ema51 = is_below_ema(symbol, timeframe=5, length=51)
            if below_ema15 or below_ema21 or below_ema51:
                print(current_dt, symbol, "below ema 15 or 21 or 51")
            else:
                if order1_open:
                    print("####", current_dt, symbol, "closing 1rd order")
                    cancel_and_close_position(order1)
                    order1_open = False
                    order_status['order1']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order1']['exit_price'] = latest_price
                if order2_open:
                    print("####", current_dt, symbol, "closing 2nd order")
                    cancel_and_close_position(order2)
                    order2_open = False
                    order_status['order2']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order2']['exit_price'] = latest_price
                if order3_open:
                    print("####", current_dt, symbol, "closing 3rd order")
                    cancel_and_close_position(order3)
                    order3_open = False
                    order_status['order3']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order3']['exit_price'] = latest_price

    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    if not is_swing:
        # close orders at the market close
        if order1_open:
            print("####", current_dt, symbol, "closing 1st order")
            cancel_and_close_position(order1)
            order1_open = False
            order_status['order1']['exit_time'] = str(current_dt)
            latest_price = get_latest_close(symbol)
            order_status['order1']['exit_price'] = latest_price

        if order2_open:
            print("####", current_dt, symbol, "closing 2nd order")
            cancel_and_close_position(order2)
            order2_open = False
            order_status['order2']['exit_time'] = str(current_dt)
            latest_price = get_latest_close(symbol)
            order_status['order2']['exit_price'] = latest_price

        if order3_open:
            print("####", current_dt, symbol, "closing 3rd order")
            cancel_and_close_position(order3)
            order3_open = False
            order_status['order3']['exit_time'] = str(current_dt)
            latest_price = get_latest_close(symbol)
            order_status['order3']['exit_price'] = latest_price
    else:

        if test_mode:
            today_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

            while True:
                print(test_datetime)
                cal = api.get_calendar(start=str(test_datetime.date()), end=str(test_datetime.date()))

                if len(cal) > 0:
                    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day),
                                        start=str(test_datetime.date()), end=str(test_datetime.date())).df
                    latest_price = bars['close'].tail(1).iloc[0]
                    stop_price = order_status['order3']['entry_price'] * (1 + 0.06)

                    if stop_price < latest_price:
                        latest_price = stop_price

                    downtrend = False
                    if downtrend or is_above_ema(symbol, 21):
                        print(datetime.datetime.now().astimezone(TZ_NY), "closing all position of", symbol)
                        print("stop_price", stop_price, "latest_price"  , latest_price)

                        if order1_open:
                            print("####", test_datetime, symbol, "closing 1st order - swing")
                            cancel_and_close_position(order1)
                            order1_open = False
                            order_status['order1']['exit_time'] = str(test_datetime)
                            order_status['order1']['exit_price'] = latest_price

                        if order2_open:
                            print("####", test_datetime, symbol, "closing 2nd order - swing")
                            cancel_and_close_position(order2)
                            order2_open = False
                            order_status['order2']['exit_time'] = str(test_datetime)
                            order_status['order2']['exit_price'] = latest_price

                        if order3_open:
                            print("####", test_datetime, symbol, "closing 3rd order - swing")
                            cancel_and_close_position(order3)
                            order3_open = False
                            order_status['order3']['exit_time'] = str(test_datetime)
                            order_status['order3']['exit_price'] = latest_price

                    else:
                        print(test_datetime, "is still below 21 EMA. Do nothing.")

                if order1_open == False and order2_open == False and order3_open == False:
                    break

                today_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
                stop_price = order_status['order3']['entry_price'] * (1 + 0.06)
                if stop_price < latest_price:
                    latest_price = stop_price

                if pd.Timestamp(order_status['order1']['entry_time']) + timedelta(days=90) < \
                        test_datetime or test_datetime + timedelta(days=2) > today_dt:
                    print('passed 30 days from open or today. closing orders')

                    if order1_open:
                        print("####", test_datetime, symbol, "closing 1st order - swing")
                        cancel_and_close_position(order1)
                        order1_open = False
                        order_status['order1']['exit_time'] = str(test_datetime)
                        order_status['order1']['exit_price'] = latest_price

                    if order2_open:
                        print("####", test_datetime, symbol, "closing 2nd order - swing")
                        cancel_and_close_position(order2)
                        order2_open = False
                        order_status['order2']['exit_time'] = str(test_datetime)
                        order_status['order2']['exit_price'] = latest_price

                    if order3_open:
                        print("####", test_datetime, symbol, "closing 3rd order - swing")
                        cancel_and_close_position(order3)
                        order3_open = False
                        order_status['order3']['exit_time'] = str(test_datetime)
                        order_status['order3']['exit_price'] = latest_price

                    break

                test_datetime += timedelta(days=1)
                    

    total_profit = 0
    for order in order_status:
        if order_status[order]['exit_price'] != 0:
            # ショートポジションの利益計算
            profit = (order_status[order]['entry_price'] - order_status[order]['exit_price']) * order_status[order]['qty']
            profit_rate = (1 - order_status[order]['exit_price'] / order_status[order]['entry_price']) * 100
            
            print(order, profit, profit_rate)
            
            # スリッページを考慮した利益計算
            total_profit += (order_status[order]['entry_price'] * (1 - SLIPAGE_RATE) - \
                           order_status[order]['exit_price'] * (1 + SLIPAGE_RATE)) * \
                           order_status[order]['qty']
        else:
            print(order, "keep holding for swing.")

    print("#### total profit", total_profit)

    print_order_status(order_status)

    if test_mode:
        if daily_log:
            with open('reports/orb_short_report_' + str(datetime.date.today()) + '.csv', mode='a') as report_file:
                # report_file.write(str(test_datetime.date()) + "," + symbol + "," + str(round(total_profit, 2)) + "\n")
                entry_date = pd.Timestamp(order_status['order1']['entry_time'] , tz=TZ_NY)
                entry_date = entry_date.date()
                exit_date = pd.Timestamp(order_status['order3']['exit_time'] , tz=TZ_NY)
                exit_date = exit_date.date()
                report_file.write(str(entry_date) + "," + str(exit_date) + "," + symbol + "," + str(round(total_profit, 2)) + "\n")

        else:
            with open('reports/orb_report_' + symbol + '.csv', mode='a') as report_file:
                report_file.write(str(test_datetime.date()) + "," + symbol + "," + str(round(total_profit, 2)) + "\n")


def is_shortable(symbol):
    """
    銘柄がショート可能かどうかを確認する関数
    
    Args:
        symbol (str): 確認する銘柄のシンボル
        
    Returns:
        bool: ショート可能な場合はTrue、不可能な場合はFalse
        
    Note:
        以下の条件を全て満たす必要があります：
        - 取引可能（tradable）
        - ショート可能（shortable）
        - 借りやすい銘柄（easy_to_borrow）
        - 証拠金取引可能（marginable）
        - アクティブな銘柄（status = 'active'）
        - NYSEまたはNASDAQの銘柄
        - 維持証拠金率が50%以下
        - ショート証拠金要件が50%以下
    """
    try:
        # 銘柄の詳細情報を取得
        asset = api.get_asset(symbol)
        
        # ショート可能な条件をチェック
        if (asset.tradable and  # 取引可能
            asset.shortable and  # ショート可能
            asset.easy_to_borrow and  # 借りやすい銘柄
            asset.marginable and  # 証拠金取引可能
            asset.status == 'active' and  # アクティブな銘柄
            asset.exchange in ['NYSE', 'NASDAQ'] and  # NYSEまたはNASDAQの銘柄
            asset.maintenance_margin_requirement <= 50 and  # 維持証拠金率が50%以下
            float(asset.margin_requirement_short) <= 50):  # ショート証拠金要件が50%以下
            
            print(f"{symbol} is shortable")
            print(f"Maintenance margin requirement: {asset.maintenance_margin_requirement}%")
            print(f"Short margin requirement: {asset.margin_requirement_short}%")
            return True
        else:
            print(f"{symbol} is not shortable")
            if not asset.tradable:
                print("Reason: Not tradable")
            if not asset.shortable:
                print("Reason: Not shortable")
            if not asset.easy_to_borrow:
                print("Reason: Not easy to borrow")
            if not asset.marginable:
                print("Reason: Not marginable")
            if asset.status != 'active':
                print(f"Reason: Status is {asset.status}")
            if asset.exchange not in ['NYSE', 'NASDAQ']:
                print(f"Reason: Exchange is {asset.exchange}")
            if asset.maintenance_margin_requirement > 50:
                print(f"Reason: Maintenance margin requirement ({asset.maintenance_margin_requirement}%) is too high")
            if float(asset.margin_requirement_short) > 50:
                print(f"Reason: Short margin requirement ({asset.margin_requirement_short}%) is too high")
            return False
            
    except Exception as e:
        print(f"Error checking if {symbol} is shortable: {str(e)}")
        return False


def check_margin_requirements(symbol, position_size, entry_price):
    """
    ショートポジションの証拠金要件をチェックする関数
    
    Args:
        symbol (str): 銘柄のシンボル
        position_size (int): ポジションサイズ
        entry_price (float): エントリー価格
        
    Returns:
        bool: 証拠金要件を満たす場合はTrue、満たさない場合はFalse
        
    Note:
        以下の条件をチェックします：
        - 必要証拠金が利用可能証拠金を超えていないか
        - 維持証拠金要件がポートフォリオの50%を超えていないか
    """
    try:
        # アカウント情報を取得
        account = api.get_account()
        portfolio_value = float(account.portfolio_value)
        
        # 銘柄の詳細情報を取得
        asset = api.get_asset(symbol)
        
        # ショートポジションに必要な証拠金を計算
        position_value = position_size * entry_price
        required_margin = position_value * float(asset.margin_requirement_short) / 100
        
        # 利用可能な証拠金を計算
        available_margin = float(account.buying_power)
        
        # 証拠金要件をチェック
        if required_margin > available_margin:
            print(f"証拠金不足: 必要証拠金 {required_margin:.2f} > 利用可能証拠金 {available_margin:.2f}")
            return False
            
        # 維持証拠金要件もチェック
        maintenance_margin = position_value * float(asset.maintenance_margin_requirement) / 100
        if maintenance_margin > portfolio_value * 0.5:  # ポートフォリオの50%を超えないように
            print(f"維持証拠金要件を超えています: {maintenance_margin:.2f}")
            return False
            
        print(f"証拠金要件を満たしています: 必要証拠金 {required_margin:.2f} <= 利用可能証拠金 {available_margin:.2f}")
        return True
        
    except Exception as e:
        print(f"証拠金要件のチェック中にエラーが発生しました: {str(e)}")
        return False


if __name__ == '__main__':
    start_trading()
