import argparse
import sys
from datetime import datetime, timedelta
import datetime
import os
from dotenv import load_dotenv
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
import alpaca_trade_api as tradeapi
import pandas_ta as ta
import pandas as pd
import time
import math
from logging_config import get_logger

from common_constants import ACCOUNT, TIMEZONE
load_dotenv()

logger = get_logger(__name__)

class TradingError(Exception):
    """取引関連のエラー"""
    pass

ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)

TZ_NY = TIMEZONE.NY  # Migrated from common_constants
TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants

# 設定値をconfig.pyから取得
from config import trading_config
LIMIT_RATE = trading_config.ORB_LIMIT_RATE
SLIPAGE_RATE = trading_config.ORB_SLIPAGE_RATE

# Default 1st order parameters: 3% stop and 6% profit for day trade
STOP_RATE_1 = trading_config.ORB_STOP_RATE_1
PROFIT_RATE_1 = trading_config.ORB_PROFIT_RATE_1

# Default 2nd order parameters: 4% stop and 8% profit for day trade
STOP_RATE_2 = trading_config.ORB_STOP_RATE_2
PROFIT_RATE_2 = trading_config.ORB_PROFIT_RATE_2

# Default 3rd order parameters: 8% stop and 30% profit for swing
STOP_RATE_3 = trading_config.ORB_STOP_RATE_3
PROFIT_RATE_3 = trading_config.ORB_PROFIT_RATE_3

# Import dependency injection components
from orb_config import get_orb_config, ORBConfiguration
from orb_state_manager import TradingState, get_session_manager

# making entries only within 150 minutes from the open
# opening range timeframe in minutes
ENTRY_PERIOD = trading_config.ORB_ENTRY_PERIOD

# グローバル変数を排除し、依存性注入による状態管理に移行
# REMOVED: Global variables (POSITION_SIZE, opening_range, test_mode, test_datetime, close_dt, order_status)
# REPLACED: TradingState class for state management

api = alpaca_client.api  # 後方互換性のため


def get_latest_high(symbol, state: TradingState = None):
    """
    最新の高値を取得（依存性注入版）
    
    Args:
        symbol: 銘柄シンボル
        state: 取引状態（省略時はデフォルト状態を作成）
    """
    if state is None:
        state = TradingState()
    
    current_datetime = state.get_current_datetime()

    if state.test_mode:
        # bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
        #                     start=current_datetime.date(), end=current_datetime.date()).df

        start_time = pd.Timestamp(current_datetime) - timedelta(minutes=60)
        end_time = pd.Timestamp(current_datetime)

        # Note: bars_1min would need to be passed as parameter or retrieved from state
        # bars = bars_1min.between_time(start_time.astimezone(TZ_UTC).time(), end_time.astimezone(TZ_UTC).time())
        # bars = bars[bars.index <= end_time]

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


def is_above_ema(symbol, timeframe=5, length=50):
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

        # if ema != 0 and latest_open > latest_close > ema:
        if ema != 0 and latest_close > ema:
            print(symbol, 'is above', length, 'ema')
            return True
    else:
        print("failed to get bars")

    print(symbol, 'is below', length, 'ema')
    return False


def is_opening_range_break(symbol, range_high):
    latest_close = get_latest_close(symbol)

    print("opening range high, latest close", range_high, latest_close)

    if latest_close > range_high:
        print(symbol, 'above Opening range high')
        return True
    else:
        print(symbol, 'below opening range high')
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
    """
    ブラケット注文を送信する
    
    Args:
        symbol: 銘柄シンボル
        qty: 注文数量
        limit_price: 指値価格
        profit_target: 利益確定価格
        stop_price: ストップロス価格
        
    Returns:
        注文レスポンス、またはエラー/テストモードの場合はFalse
    """
    if test_mode:
        logger.info(f"TEST MODE: Would submit bracket order for {symbol}: qty={qty}, limit={limit_price}, profit={profit_target}, stop={stop_price}")
        return False
    
    try:
        logger.info(f"Submitting bracket order for {symbol}: qty={qty}, limit={limit_price:.2f}, profit={profit_target:.2f}, stop={stop_price:.2f}")
        
        resp = alpaca_client.submit_order(
            symbol=symbol,
            side='buy',
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
        
        logger.info(f"Bracket order submitted successfully for {symbol}: order_id={resp.id}")
        return resp
        
    except Exception as e:
        logger.error(f"Failed to submit bracket order for {symbol}: {str(e)}", exc_info=True)
        # 重要: 取引エラーは再発生させて上位で処理できるようにする
        raise TradingError(f"Bracket order submission failed for {symbol}: {str(e)}") from e


def submit_bracket_orders(symbol, dynamic_rate=True, trading_state: TradingState = None):
    """
    ブラケット注文送信（依存性注入版）
    
    Args:
        symbol: 銘柄シンボル
        dynamic_rate: 動的レート使用フラグ
        trading_state: 取引状態（省略時は新規作成）
    """
    if trading_state is None:
        trading_state = TradingState()
        
    order1 = None
    order2 = None
    order3 = None

    current_dt = trading_state.get_current_datetime()

    if dynamic_rate:
        set_stop_profit_rate(symbol)

    entry_price = get_latest_close(symbol)
    qty = get_position_size(entry_price)

    if qty < 1:
        print("the stock price is higher than your position size. set qty=1.")
        qty = 1
        # return order1, order2, order3

    limit_price = get_entry_limit(entry_price)
    profit_target_1 = get_profit_target(entry_price, PROFIT_RATE_1)
    stop_price_1 = get_stop_price(entry_price, STOP_RATE_1)

    profit_target_2 = get_profit_target(entry_price, PROFIT_RATE_2)
    stop_price_2 = get_stop_price(entry_price, STOP_RATE_2)

    profit_target_3 = get_profit_target(entry_price, PROFIT_RATE_3)
    stop_price_3 = get_stop_price(entry_price, STOP_RATE_3)

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
    positions = []
    resp = api.list_positions()

    for pos in resp:
        positions.append(pos.symbol)

    if symbol in positions:
        print("you have position", symbol)
        return True
    else:
        print("no position")
        return False


def cancel_and_close_position(order, retries=3, delay=0.5):
    resp = None
    if test_mode:
        return resp

    else:
        print("cancel and close order", datetime.datetime.now().astimezone(TZ_NY), order.symbol, order.qty)

        if order is None:
            print("the order is not valid.")
            return resp

        # まず注文をキャンセル
        if order.legs is not None:
            if len(order.legs) > 0:
                for sub_order in order.legs:
                    try:
                        api.cancel_order(sub_order.id)
                        print(datetime.datetime.now().astimezone(TZ_NY), "sub order canceled.", resp)
                    except Exception as error:
                        print(datetime.datetime.now().astimezone(TZ_NY), "failed to cancel sub order.", error)

        try:
            api.cancel_order(order.id)
            print(datetime.datetime.now().astimezone(TZ_NY), "order canceled.", resp)
        except Exception as error:
            print(datetime.datetime.now().astimezone(TZ_NY), "failed to cancel order.", error)

        # 注文のキャンセルが反映されるまで待機
        time.sleep(delay)

        # ポジションの存在を確認
        if check_position(order.symbol):
            try:
                # 現在のポジション情報を取得
                position = api.get_position(order.symbol)
                if position is None:
                    print("No position found for", order.symbol)
                    return resp

                # 実際のポジション数量を使用
                actual_qty = abs(float(position.qty))
                print("Actual position quantity:", actual_qty)

                for attempt in range(retries):
                    try:
                        resp = api.close_position(order.symbol, qty=actual_qty)
                        print(resp)
                        return resp
                    except Exception as error:
                        print(datetime.datetime.now().astimezone(TZ_NY),
                              f"Attempt {attempt + 1}:",
                              "failed to close position. it might have been sold by stop loss order or take profit order.",
                              error)
                        time.sleep(delay)

                print("close position failed after retries.")
            except Exception as error:
                print("Failed to get position information:", error)

        return resp


def cancel_and_close_all_position(symbol, delay=0.5, max_wait_time=15):
    """
    原子的操作で指定されたシンボルのすべての注文をキャンセルし、ポジションをクローズする
    
    Args:
        symbol (str): 取引対象のシンボル
        delay (float): 待機時間（秒）
        max_wait_time (int): 最大待機時間（秒）
        
    Returns:
        dict: 実行結果と詳細情報
    """
    result = {
        'success': False,
        'orders_cancelled': 0,
        'position_closed': False,
        'errors': [],
        'final_position': None
    }
    
    try:
        logger.info(f"Starting atomic cancel and close for {symbol}")
        
        # 1️⃣ 現在のポジション情報を事前取得（一貫性チェック用）
        initial_position = None
        try:
            initial_position = alpaca_client.api.get_position(symbol)
            logger.info(f"Initial position for {symbol}: qty={initial_position.qty}, available={initial_position.qty_available}")
        except Exception as e:
            if 'position does not exist' not in str(e).lower():
                logger.warning(f"Could not get initial position for {symbol}: {e}")
        
        # 2️⃣ 全ての関連注文を原子的に取得・キャンセル
        cancelled_orders = []
        try:
            open_orders = alpaca_client.api.list_orders(status='open', symbols=[symbol])
            logger.info(f"Found {len(open_orders)} open orders for {symbol}")
            
            if open_orders:
                # 注文を並行してキャンセル（ただし結果を順次確認）
                cancel_requests = []
                for order in open_orders:
                    try:
                        alpaca_client.cancel_order(order.id)
                        cancel_requests.append(order.id)
                        logger.info(f"Cancel requested for order {order.id} ({order.order_type}, qty={order.qty})")
                    except Exception as e:
                        logger.error(f"Failed to cancel order {order.id}: {e}")
                        result['errors'].append(f"Cancel failed for order {order.id}: {e}")
                
                # 各キャンセル要求の完了を確認
                from orb_helper import _wait_for_order_cancellation
                for order_id in cancel_requests:
                    if _wait_for_order_cancellation(alpaca_client, order_id, max_wait_time, delay):
                        cancelled_orders.append(order_id)
                        result['orders_cancelled'] += 1
                    else:
                        logger.warning(f"Order {order_id} cancellation timed out or failed")
                        result['errors'].append(f"Order {order_id} cancellation timeout")
                        
        except Exception as e:
            logger.error(f"Error during order cancellation phase for {symbol}: {e}")
            result['errors'].append(f"Order cancellation phase error: {e}")
        
        # 3️⃣ 短時間待機してキャンセル処理の完全な反映を待つ
        time.sleep(delay * 2)
        
        # 4️⃣ 最終ポジション状態を確認してからクローズ
        try:
            final_position = alpaca_client.api.get_position(symbol)
            result['final_position'] = {
                'qty': final_position.qty,
                'qty_available': final_position.qty_available,
                'market_value': final_position.market_value
            }
            
            # 利用可能数量が0より大きい場合のみクローズ
            available_qty = abs(float(final_position.qty_available))
            if available_qty > 0:
                logger.info(f"Closing position for {symbol}: available_qty={available_qty}")
                
                # 部分クローズの可能性を考慮して数量を指定
                close_response = alpaca_client.close_position(symbol, qty=available_qty)
                
                # クローズ操作の確認
                if close_response:
                    result['position_closed'] = True
                    logger.info(f"Position closed successfully for {symbol}")
                else:
                    logger.warning(f"Position close response was empty for {symbol}")
                    result['errors'].append("Empty close response")
                    
            else:
                logger.info(f"No available quantity to close for {symbol}")
                result['position_closed'] = True  # 既にクローズ済みとして扱う
                
        except Exception as e:
            if 'position does not exist' in str(e).lower():
                logger.info(f"Position already closed or does not exist for {symbol}")
                result['position_closed'] = True
            else:
                logger.error(f"Error closing position for {symbol}: {e}")
                result['errors'].append(f"Position close error: {e}")
                
        # 5️⃣ 最終的な成功判定
        result['success'] = result['position_closed'] and len(result['errors']) == 0
        
        if result['success']:
            logger.info(f"Successfully completed cancel and close for {symbol}: {result['orders_cancelled']} orders cancelled")
        else:
            logger.warning(f"Cancel and close completed with issues for {symbol}: {result}")
            
        return result
        
    except Exception as error:
        logger.error(f"Critical error in cancel_and_close_all_position for {symbol}: {error}", exc_info=True)
        result['errors'].append(f"Critical error: {error}")
        return result


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


def is_uptrend(symbol, timeframe=5, short=10, long=20):
    if test_mode:
        current_time = test_datetime
    else:
        current_time = datetime.datetime.now().astimezone(TZ_NY)

    days = math.ceil(long * 5 / 360 * 2) + 3
    start_dt = current_time - timedelta(days=days)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_time.strftime("%Y-%m-%d")

    if test_mode:
        # テストモードではローカルスコープの bars_5min を参照
        # グローバル変数を避けてメモリリークを防止
        from orb_memory_utils import _get_test_bars_5min
        bars = _get_test_bars_5min(symbol, start_date, end_date, bars_5min)
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
            is_ema10_up = (bars['EMA10'].tail(2).iloc[1] - bars['EMA10'].tail(2).iloc[0]) >= 0
            print("is ema 10 up?", is_ema10_up)
        else:
            ema10 = 0
        if bars['EMA20'].tail(1).iloc[0] is not None:
            ema20 = float(bars['EMA20'].tail(1).iloc[0])
        else:
            ema20 = 0

        latest_price = get_latest_close(symbol)

        print(current_time, "ema20, ema10, price", ema20, ema10, latest_price)

        if ema20 != 0 and latest_price > ema10 > ema20 and is_ema10_up:
            print('uptrend')
            return True
    else:
        print("failed to get bars")

    print('not uptrend')
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

    volatility = get_daily_volatility(symbol)
    if volatility != 0:
        # 1st order
        STOP_RATE_1 = volatility
        PROFIT_RATE_1 = volatility * 4
        #STOP_RATE_1 = volatility / 8
        #PROFIT_RATE_1 = volatility * 1.5

        # 2nd order
        STOP_RATE_2 = volatility * 1.5
        PROFIT_RATE_2 = volatility * 6
        #STOP_RATE_2 = volatility / 6
        #PROFIT_RATE_2 = volatility * 4

        # 3rd order
        STOP_RATE_3 = volatility * 2
        PROFIT_RATE_3 = volatility * 10
        #STOP_RATE_3 = volatility / 5
        #PROFIT_RATE_3 = volatility * 10

    print('Order1 stop:', STOP_RATE_1 * 100, 'profit target:', PROFIT_RATE_1 * 100)
    print('Order2 stop:', STOP_RATE_2 * 100, 'profit target:', PROFIT_RATE_2 * 100)
    print('Order3 stop:', STOP_RATE_3 * 100, 'profit target:', PROFIT_RATE_3 * 100)


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


def start_trading(config: ORBConfiguration = None):
    """
    ORB取引の開始（依存性注入版）
    
    Args:
        config: ORB設定オブジェクト（省略時はデフォルト設定を使用）
    """
    if config is None:
        config = get_orb_config()
    
    # 取引状態の初期化
    session_manager = get_session_manager(config)
    # bars_1min, bars_5min はローカル変数として使用してメモリリークを防止
    close_time = config.market.market_close_time
    open_time = config.market.market_open_time
    current_dt = pd.Timestamp(datetime.datetime.now().astimezone(config.market.ny_timezone))

    ap = argparse.ArgumentParser()
    ap.add_argument('symbol')
    ap.add_argument('--pos_size', default=3000)
    ap.add_argument('--range', default=5)
    ap.add_argument('--swing', default=False)
    ap.add_argument('--dynamic_rate', default=True)
    ap.add_argument('--test_mode', default=False)
    ap.add_argument('--test_date', default='2023-12-06')
    ap.add_argument('--ema_trail', default=False)
    ap.add_argument('--daily_log', default=False)
    ap.add_argument('--trend_check', default=True)
    args = vars(ap.parse_args())

    # 引数から取引パラメータを取得
    symbol = args['symbol']
    test_mode = args['test_mode']
    if isinstance(test_mode, str):
        test_mode = test_mode == 'True' or test_mode == 'true'
        
    opening_range = int(args['range'])
    if isinstance(args['dynamic_rate'], str):
        dynamic_rate = args['dynamic_rate'] == 'True' or args['dynamic_rate'] == 'true'
    else:
        dynamic_rate = args['dynamic_rate']
    
    # 取引状態オブジェクトの作成
    trading_state = session_manager.create_session(
        symbol,
        test_mode=test_mode,
        opening_range=opening_range,
        config=config
    )
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

    account = api.get_account()
    portfolio_value = float(account.portfolio_value)
    position_market_value = float(account.position_market_value)

    if test_mode:
        print(is_swing)
    elif portfolio_value * 1.5 < position_market_value:
        print("margin usage exceeds 50% of portfolio value. disabling swing trading.")
        is_swing = False

    # position size will be automatically calculated.
    if args['pos_size'] == 'auto':
        trading_state.position_size = float(portfolio_value) / 18 / 3
    else:
        trading_state.position_size = int(args['pos_size'])

    print('start trading', symbol, 'position size', trading_state.position_size)

    if test_mode:
        test_datetime = pd.Timestamp(args['test_date'] + " " + str(open_time), tz=config.market.ny_timezone)
        trading_state.test_datetime = test_datetime
        cal = api.get_calendar(start=str(test_datetime.date()), end=str(test_datetime.date()))
        if len(cal) > 0:
            close_time = cal[0].close
            trading_state.close_dt = pd.Timestamp(str(test_datetime.date()) + " " + str(close_time), tz=config.market.ny_timezone)
        else:
            print("market will not open on the date. finish trading.")
            return

        # テストモード用データ取得（メモリ効率化）
        days = math.ceil(50 * 5 / 360 * 2) + 3
        start_dt = (test_datetime - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # 大量データの取得時はメモリ使用量を監視
        logger.info(f"Loading test data for {symbol} from {start_dt} to {test_datetime.date()}")
        
        try:
            bars_1min = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Minute),
                                     start=start_dt, end=str(test_datetime.date())).df
            bars_5min = api.get_bars(symbol, TimeFrame(5, TimeFrameUnit.Minute),
                                     start=start_dt, end=str(test_datetime.date())).df
            
            logger.info(f"Test data loaded: 1min bars={len(bars_1min)}, 5min bars={len(bars_5min)}")
            
            # データサイズが大きすぎる場合は警告
            if len(bars_1min) > 10000 or len(bars_5min) > 2000:
                logger.warning(f"Large dataset loaded - consider reducing date range for memory efficiency")
                
        except Exception as e:
            logger.error(f"Failed to load test data for {symbol}: {e}")
            return
        
        # 大量データ処理時のメモリ監視
        from orb_memory_utils import log_memory_if_high
        log_memory_if_high(threshold_mb=300)

        # opening range time
        # test_datetime = test_datetime + timedelta(minutes=opening_range-1) + timedelta(seconds=59)
        test_datetime = test_datetime + timedelta(minutes=opening_range)
        current_dt = pd.Timestamp(test_datetime)

    else:
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
        uptrend_short = is_uptrend(symbol, short=10, long=20)
        above_ema = is_above_ema(symbol, timeframe=5, length=50)
    else:
        uptrend_short = True
        above_ema = True

    if opening_range != 0:
        range_high, range_low = get_opening_range(symbol, opening_range)
        range_break = is_opening_range_break(symbol, range_high)
    else:
        range_break = True

    if test_mode:
        current_dt = pd.Timestamp(test_datetime)
    else:
        current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

    while not (uptrend_short and above_ema and range_break):
        if test_mode:
            test_datetime += timedelta(minutes=1)
            # time.sleep(0.01)
        else:
            print(current_dt, "waiting for uptrend and opening range break...")
            time.sleep(60)

        if test_mode:
            current_dt = pd.Timestamp(test_datetime)
        else:
            current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))

        open_dt = pd.Timestamp(str(current_dt.date()) + " " + str(open_time), tz=TZ_NY)

        if trend_check:
            uptrend_short = is_uptrend(symbol, short=10, long=20)
            above_ema = is_above_ema(symbol, timeframe=5, length=50)
        else:
            uptrend_short = True
            above_ema = True


        if opening_range != 0:
            range_break = is_opening_range_break(symbol, range_high)
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
            above_ema15 = is_above_ema(symbol, timeframe=5, length=15)
            if above_ema15:
                print(current_dt, symbol, "above 15ema")
            else:
                if order1_open:
                    print("####", current_dt, symbol, "closing 1st order")
                    cancel_and_close_position(order1)
                    order1_open = False
                    order_status['order1']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order1']['exit_price'] = latest_price

            above_ema21 = is_above_ema(symbol, timeframe=5, length=21)
            if above_ema21:
                print(current_dt, symbol, "above 21ema")
            else:
                if order2_open:
                    print("####", current_dt, symbol, "closing 2nd order")
                    cancel_and_close_position(order2)
                    order2_open = False
                    order_status['order2']['exit_time'] = str(current_dt)
                    latest_price = get_latest_close(symbol)
                    order_status['order2']['exit_price'] = latest_price

            above_ema51 = is_above_ema(symbol, timeframe=5, length=51)
            if above_ema15 or above_ema21 or above_ema51:
                print(current_dt, symbol, "above ema 15 or 21 or 51")
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
        if order1_open or order2_open or order3_open:
            print("####", current_dt, symbol, "closing all open orders")
            cancel_and_close_all_position(symbol)
            
            # 最新価格を取得
            latest_price = get_latest_close(symbol)
            
            # 注文状態を更新
            if order1_open:
                order1_open = False
                order_status['order1']['exit_time'] = str(current_dt)
                order_status['order1']['exit_price'] = latest_price
                
            if order2_open:
                order2_open = False
                order_status['order2']['exit_time'] = str(current_dt)
                order_status['order2']['exit_price'] = latest_price
                
            if order3_open:
                order3_open = False
                order_status['order3']['exit_time'] = str(current_dt)
                order_status['order3']['exit_price'] = latest_price
    else:

        if test_mode:
            today_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
            bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day),
                                start=str(close_dt.date()), end=str(close_dt.date())).df

            latest_price = bars['close'].tail(1).iloc[0]
            stop_price = order_status['order3']['entry_price'] * (1 - STOP_RATE_1)

            if stop_price > latest_price:
                latest_price = stop_price

            while True:
                print(test_datetime)
                cal = api.get_calendar(start=str(test_datetime.date()), end=str(test_datetime.date()))

                if len(cal) > 0:
                    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day),
                                        start=str(test_datetime.date()), end=str(test_datetime.date())).df

                    latest_price = bars['close'].tail(1).iloc[0]
                    stop_price = order_status['order3']['entry_price'] * (1 - STOP_RATE_1)

                    if stop_price > latest_price:
                        latest_price = stop_price

                    downtrend = False
                    if downtrend or is_below_ema(symbol, 21):
                    # if downtrend or is_below_ema(symbol, 51):
                        print(datetime.datetime.now().astimezone(TZ_NY), "closing all position of", symbol)
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
                        print(test_datetime, "is still above 5 and 10 and 21 EMA. Do nothing.")

                if order1_open == False and order2_open == False and order3_open == False:
                    break

                today_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
                stop_price = order_status['order3']['entry_price'] * (1 - STOP_RATE_1)
                if stop_price > latest_price:
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
            print(order,
              (order_status[order]['exit_price'] - order_status[order]['entry_price']) * order_status[order]['qty'],
              (order_status[order]['exit_price'] / order_status[order]['entry_price'] - 1) * 100)
            total_profit += (order_status[order]['exit_price']* (1 - SLIPAGE_RATE) - \
                            order_status[order]['entry_price'] * (1 + SLIPAGE_RATE)) * \
                            order_status[order]['qty']
        else:
            print(order, "keep holding for swing.")

    print("#### total profit", total_profit)

    print_order_status(order_status)
    
    # テストモード終了時のメモリクリーンアップ
    if test_mode:
        try:
            from orb_memory_utils import cleanup_large_dataframes, log_memory_if_high
            # 最終メモリ使用量をチェック
            log_memory_if_high(threshold_mb=200)
            # 大量データのクリーンアップ
            cleanup_large_dataframes(bars_1min, bars_5min)
            logger.info(f"Memory cleanup completed for {symbol}")
        except Exception as e:
            logger.error(f"Error during memory cleanup: {e}")

    if test_mode:
        if daily_log:
            with open('reports/orb_report_' + str(datetime.date.today()) + '.csv', mode='a') as report_file:
                # report_file.write(str(test_datetime.date()) + "," + symbol + "," + str(round(total_profit, 2)) + "\n")
                entry_date = pd.Timestamp(order_status['order1']['entry_time'] , tz=TZ_NY)
                entry_date = entry_date.date()
                exit_date = pd.Timestamp(order_status['order3']['exit_time'] , tz=TZ_NY)
                exit_date = exit_date.date()
                report_file.write(str(entry_date) + "," + str(exit_date) + "," + symbol + "," + str(round(total_profit, 2)) + "\n")

        else:
            with open('reports/orb_report_' + symbol + '.csv', mode='a') as report_file:
                report_file.write(str(test_datetime.date()) + "," + symbol + "," + str(round(total_profit, 2)) + "\n")


if __name__ == '__main__':
    start_trading()
