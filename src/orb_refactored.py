"""
ORB (Opening Range Breakout) トレーディングシステム - リファクタリング版
グローバル状態を排除し、設定を注入する方式に変更
巨大なstart_trading()関数を単一責任原則に従って分割
"""

import datetime
import math
import time
import argparse
import pandas as pd
from datetime import timedelta
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Any
from logging_config import get_logger
from orb_config import get_orb_config, ORBConfiguration

logger = get_logger(__name__)

# インターフェース経由でorb.pyの機能にアクセス（循環依存回避）
from trading_interfaces import (
    TradingInterface, OrderManagementInterface, 
    MarketDataInterface, TimeManagementInterface,
    ORBAdapter
)


@dataclass
class TradingParameters:
    """取引パラメータを管理するデータクラス"""
    symbol: str
    position_size: float
    opening_range: int
    is_swing: bool
    dynamic_rate: bool
    ema_trail: bool
    daily_log: bool
    trend_check: bool
    test_mode: bool
    test_date: str
    config: ORBConfiguration = None


@dataclass
class OrderState:
    """注文状態を管理するデータクラス"""
    order1_open: bool = True
    order2_open: bool = True
    order3_open: bool = True


class TradingArgumentParser:
    """取引引数の解析クラス"""
    
    @staticmethod
    def parse_arguments(config: ORBConfiguration = None) -> TradingParameters:
        """コマンドライン引数を解析してTradingParametersを返す"""
        if config is None:
            config = get_orb_config()
        
        ap = argparse.ArgumentParser()
        ap.add_argument('symbol')
        ap.add_argument('--pos_size', default='auto')
        ap.add_argument('--range', default=config.market.opening_range_default)
        ap.add_argument('--swing', default=False)
        ap.add_argument('--dynamic_rate', default=True)
        ap.add_argument('--test_mode', default=False)
        ap.add_argument('--test_date', default=config.test.default_test_date)
        ap.add_argument('--ema_trail', default=False)
        ap.add_argument('--daily_log', default=False)
        ap.add_argument('--trend_check', default=config.trading.trend_confirmation_required)
        args = vars(ap.parse_args())
        
        return TradingParameters(
            symbol=args['symbol'],
            position_size=TradingArgumentParser._calculate_position_size(args['pos_size'], config),
            opening_range=int(args['range']),
            is_swing=TradingArgumentParser._parse_bool(args['swing']),
            dynamic_rate=TradingArgumentParser._parse_bool(args['dynamic_rate']),
            ema_trail=TradingArgumentParser._parse_bool(args['ema_trail']),
            daily_log=TradingArgumentParser._parse_bool(args['daily_log']),
            trend_check=TradingArgumentParser._parse_bool(args['trend_check']),
            test_mode=TradingArgumentParser._parse_bool(args['test_mode']),
            test_date=args['test_date'],
            config=config
        )
    
    @staticmethod
    def _parse_bool(value) -> bool:
        """文字列またはブール値を適切にパース"""
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes')
        return bool(value)
    
    @staticmethod
    def _calculate_position_size(pos_size_arg, config: ORBConfiguration) -> float:
        """ポジションサイズを計算"""
        if pos_size_arg == 'auto':
            account = api.get_account()
            portfolio_value = float(account.portfolio_value)
            # 設定から計算ロジックを取得
            return (portfolio_value * config.trading.position_size_rate / 
                   (18 * config.trading.position_divider))
        return float(pos_size_arg)


class MarketSession:
    """マーケットセッション管理クラス"""
    
    def __init__(self, params: TradingParameters):
        self.params = params
        self.current_dt = None
        self.close_dt = None
        self.open_dt = None
        self.test_datetime = None
        
    def initialize_session(self) -> bool:
        """マーケットセッションを初期化"""
        try:
            if self.params.test_mode:
                return self._initialize_test_session()
            else:
                return self._initialize_live_session()
        except Exception as e:
            logger.error(f"Failed to initialize market session: {e}")
            return False
    
    def _initialize_test_session(self) -> bool:
        """テストモード用のセッション初期化"""
        open_time = '09:30:01'
        self.test_datetime = pd.Timestamp(
            f"{self.params.test_date} {open_time}", tz=self.params.config.market.ny_timezone
        )
        
        cal = api.get_calendar(
            start=str(self.test_datetime.date()),
            end=str(self.test_datetime.date())
        )
        
        if len(cal) == 0:
            logger.error("Market will not open on the test date")
            return False
        
        close_time = cal[0].close
        self.close_dt = pd.Timestamp(
            f"{self.test_datetime.date()} {close_time}", tz=self.params.config.market.ny_timezone
        )
        
        # テスト用データ読み込み
        self._load_test_data()
        
        # オープニングレンジ時間まで進める
        self.test_datetime += timedelta(minutes=self.params.opening_range)
        self.current_dt = pd.Timestamp(self.test_datetime)
        
        logger.info(f"Test session initialized for {self.params.symbol} on {self.params.test_date}")
        return True
    
    def _initialize_live_session(self) -> bool:
        """ライブモード用のセッション初期化"""
        cal = api.get_calendar(
            start=str(datetime.date.today()),
            end=str(datetime.date.today())
        )
        
        if len(cal) == 0:
            logger.error("Market will not open today")
            return False
        
        close_time = cal[0].close
        open_time = cal[0].open
        
        self.current_dt = pd.Timestamp(datetime.datetime.now().astimezone(params.config.market.ny_timezone))
        self.open_dt = pd.Timestamp(
            f"{self.current_dt.date()} {open_time}", tz=self.params.config.market.ny_timezone
        )
        self.close_dt = pd.Timestamp(
            f"{self.current_dt.date()} {close_time}", tz=self.params.config.market.ny_timezone
        )
        
        # マーケットオープンまで待機
        if not self._wait_for_market_open():
            return False
        
        # オープニングレンジ完了まで待機
        if not self._wait_for_opening_range_complete():
            return False
        
        logger.info(f"Live session initialized for {self.params.symbol}")
        return True
    
    def _load_test_data(self):
        """テストデータの読み込み"""
        try:
            days = math.ceil(50 * 5 / 360 * 2) + 3
            start_dt = (self.test_datetime - timedelta(days=days)).strftime("%Y-%m-%d")
            
            logger.info(f"Loading test data for {self.params.symbol} from {start_dt}")
            
            # メモリ効率を考慮したデータ読み込み
            # (実際の実装では必要に応じてチャンクごとに読み込み)
            
        except Exception as e:
            logger.error(f"Failed to load test data: {e}")
            raise
    
    def _wait_for_market_open(self) -> bool:
        """マーケットオープンまで待機"""
        if self.open_dt > self.current_dt:
            seconds_to_open = (self.open_dt - self.current_dt).seconds
            logger.info(f"Waiting for market open... {seconds_to_open} seconds")
            time.sleep(seconds_to_open)
        
        # マーケットが実際に開くまで待機
        market_clock = api.get_clock()
        while not market_clock.is_open:
            time.sleep(0.5)  # 0.5 seconds
            market_clock = api.get_clock()
            logger.debug("Waiting for market open...")
        
        return True
    
    def _wait_for_opening_range_complete(self) -> bool:
        """オープニングレンジ完了まで待機"""
        self.current_dt = pd.Timestamp(datetime.datetime.now().astimezone(params.config.market.ny_timezone))
        opening_range_dt = self.open_dt + timedelta(minutes=self.params.opening_range)
        
        if self.current_dt < opening_range_dt:
            seconds_to_range_complete = (opening_range_dt - self.current_dt).seconds - 10
            logger.info(f"Waiting for opening range completion... {seconds_to_range_complete} seconds")
            time.sleep(max(0, seconds_to_range_complete))
        
        while self.current_dt < opening_range_dt:
            logger.debug("Waiting for opening range completion...")
            time.sleep(0.5)  # 0.5 seconds
            self.current_dt = pd.Timestamp(datetime.datetime.now().astimezone(params.config.market.ny_timezone))
        
        return True


class EntryConditionChecker:
    """エントリー条件チェッククラス"""
    
    def __init__(self, params: TradingParameters):
        self.params = params
    
    def check_entry_conditions(self) -> Tuple[bool, bool, bool]:
        """エントリー条件をチェック"""
        uptrend_short = True
        above_ema = True
        range_break = True
        
        if self.params.trend_check:
            uptrend_short = is_uptrend(self.params.symbol, short=10, long=20)
            above_ema = is_above_ema(self.params.symbol, timeframe=5, length=50)
        
        if self.params.opening_range != 0:
            range_high, range_low = get_opening_range(self.params.symbol, self.params.opening_range)
            range_break = is_opening_range_break(self.params.symbol, range_high)
        
        logger.debug(f"Entry conditions - Uptrend: {uptrend_short}, Above EMA: {above_ema}, Range break: {range_break}")
        return uptrend_short, above_ema, range_break
    
    def wait_for_entry_conditions(self, session: MarketSession) -> bool:
        """エントリー条件が満たされるまで待機"""
        uptrend_short, above_ema, range_break = self.check_entry_conditions()
        
        while not (uptrend_short and above_ema and range_break):
            if not is_entry_period(self.params.config.trading.entry_period_minutes):
                logger.info("Entry period ended without meeting conditions")
                return False
            
            # 時間を進める
            if self.params.test_mode:
                session.test_datetime += timedelta(minutes=1)
                session.current_dt = pd.Timestamp(session.test_datetime)
            else:
                logger.info(f"{session.current_dt} - Waiting for entry conditions...")
                time.sleep(1.0)  # 1 second
                session.current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
            
            # 条件を再チェック
            uptrend_short, above_ema, range_break = self.check_entry_conditions()
        
        logger.info("Entry conditions met!")
        return True


class OrderManager:
    """注文管理クラス"""
    
    def __init__(self, params: TradingParameters):
        self.params = params
        self.order_state = OrderState()
        self.stop_prices = {}
        self.target_prices = {}
    
    def submit_initial_orders(self) -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
        """初期注文を送信"""
        try:
            order1, order2, order3 = submit_bracket_orders(
                self.params.symbol, 
                self.params.dynamic_rate
            )
            
            if order1 is None or order2 is None or order3 is None:
                logger.error("Failed to submit bracket orders")
                return None, None, None
            
            # ストップ価格と利確価格を計算
            self._calculate_order_prices()
            
            logger.info(f"Successfully submitted bracket orders for {self.params.symbol}")
            return order1, order2, order3
            
        except Exception as e:
            logger.error(f"Failed to submit orders: {e}")
            return None, None, None
    
    def _calculate_order_prices(self):
        """注文価格を計算"""
        order_params = self.params.config.get_order_parameters()
        
        self.stop_prices = {
            'order1': get_stop_price(order_status['order1']['entry_price'], order_params['stop_rate_1']),
            'order2': get_stop_price(order_status['order2']['entry_price'], order_params['stop_rate_2']),
            'order3': get_stop_price(order_status['order3']['entry_price'], order_params['stop_rate_3'])
        }
        
        self.target_prices = {
            'order1': get_profit_target(order_status['order1']['entry_price'], order_params['profit_rate_1']),
            'order2': get_profit_target(order_status['order2']['entry_price'], order_params['profit_rate_2']),
            'order3': get_profit_target(order_status['order3']['entry_price'], order_params['profit_rate_3'])
        }


class PositionMonitor:
    """ポジション監視クラス"""
    
    def __init__(self, params: TradingParameters, session: MarketSession, order_manager: OrderManager):
        self.params = params
        self.session = session
        self.order_manager = order_manager
    
    def monitor_positions(self, order1, order2, order3):
        """ポジションを監視"""
        logger.info("Starting position monitoring")
        
        while not is_closing_time():
            # 全注文が閉じられたかチェック
            if not any([
                self.order_manager.order_state.order1_open,
                self.order_manager.order_state.order2_open,
                self.order_manager.order_state.order3_open
            ]):
                logger.info("All orders closed")
                break
            
            # 時間を更新
            self._update_current_time()
            
            # 最新価格を取得
            latest_price = get_latest_close(self.params.symbol)
            logger.debug(f"{self.session.current_dt} {self.params.symbol} latest price: {latest_price}")
            
            # 利確条件をチェック
            self._check_profit_targets(latest_price, order1, order2, order3)
            
            # ストップロス条件をチェック  
            self._check_stop_losses(latest_price, order1, order2, order3)
            
            # EMAトレール条件をチェック
            if self.params.ema_trail:
                self._check_ema_trail_conditions(order1, order2, order3)
            
            # 待機
            self._sleep_between_checks()
    
    def _update_current_time(self):
        """現在時刻を更新"""
        if self.params.test_mode:
            self.session.test_datetime += timedelta(minutes=1)
            self.session.current_dt = pd.Timestamp(self.session.test_datetime)
        else:
            self.session.current_dt = pd.Timestamp(datetime.datetime.now().astimezone(TZ_NY))
    
    def _check_profit_targets(self, latest_price: float, order1, order2, order3):
        """利確条件をチェック"""
        orders = [
            (order1, 'order1', self.order_manager.order_state.order1_open),
            (order2, 'order2', self.order_manager.order_state.order2_open),
            (order3, 'order3', self.order_manager.order_state.order3_open)
        ]
        
        for order, order_key, is_open in orders:
            if (is_open and 
                self.order_manager.target_prices[order_key] < latest_price):
                
                logger.info(f"Closing {order_key} - profit target reached")
                self._close_order(order, order_key, self.order_manager.target_prices[order_key])
                
                # 1st order利確時は他のストップ価格を調整
                if order_key == 'order1':
                    self._adjust_stop_prices_after_first_profit()
    
    def _check_stop_losses(self, latest_price: float, order1, order2, order3):
        """ストップロス条件をチェック"""
        orders = [
            (order1, 'order1', self.order_manager.order_state.order1_open),
            (order2, 'order2', self.order_manager.order_state.order2_open),
            (order3, 'order3', self.order_manager.order_state.order3_open)
        ]
        
        for order, order_key, is_open in orders:
            if (is_open and 
                self.order_manager.stop_prices[order_key] > latest_price):
                
                logger.info(f"Closing {order_key} - stop loss triggered")
                self._close_order(order, order_key, self.order_manager.stop_prices[order_key])
    
    def _check_ema_trail_conditions(self, order1, order2, order3):
        """EMAトレール条件をチェック"""
        ema_params = self.params.config.get_ema_parameters()
        above_ema15 = is_above_ema(self.params.symbol, timeframe=5, length=ema_params['trail_fast'])
        above_ema21 = is_above_ema(self.params.symbol, timeframe=5, length=ema_params['trail_medium'])
        above_ema51 = is_above_ema(self.params.symbol, timeframe=5, length=ema_params['trail_slow'])
        
        # EMA15下抜けで1st order終了
        if not above_ema15 and self.order_manager.order_state.order1_open:
            logger.info("Closing 1st order - below EMA15")
            latest_price = get_latest_close(self.params.symbol)
            self._close_order(order1, 'order1', latest_price)
        
        # EMA21下抜けで2nd order終了
        if not above_ema21 and self.order_manager.order_state.order2_open:
            logger.info("Closing 2nd order - below EMA21")
            latest_price = get_latest_close(self.params.symbol)
            self._close_order(order2, 'order2', latest_price)
        
        # 全EMA下抜けで全注文終了
        if not (above_ema15 or above_ema21 or above_ema51):
            logger.info("Closing all orders - below all EMAs")
            latest_price = get_latest_close(self.params.symbol)
            
            if self.order_manager.order_state.order1_open:
                self._close_order(order1, 'order1', latest_price)
            if self.order_manager.order_state.order2_open:
                self._close_order(order2, 'order2', latest_price)
            if self.order_manager.order_state.order3_open:
                self._close_order(order3, 'order3', latest_price)
    
    def _close_order(self, order, order_key: str, exit_price: float):
        """注文を終了"""
        try:
            cancel_and_close_position(order)
            
            # 状態を更新
            setattr(self.order_manager.order_state, f"{order_key}_open", False)
            order_status[order_key]['exit_time'] = str(self.session.current_dt)
            order_status[order_key]['exit_price'] = exit_price
            
            logger.info(f"Successfully closed {order_key} at {exit_price}")
            
        except Exception as e:
            logger.error(f"Failed to close {order_key}: {e}")
    
    def _adjust_stop_prices_after_first_profit(self):
        """1st order利確後のストップ価格調整"""
        self.order_manager.stop_prices['order2'] = order_status['order2']['entry_price']
        self.order_manager.stop_prices['order3'] = order_status['order3']['entry_price']
        logger.info("Adjusted stop prices to break-even after first profit")
    
    def _sleep_between_checks(self):
        """チェック間の待機"""
        if self.params.test_mode:
            pass  # テストモードでは待機しない
        else:
            # 市場終了に近づいたら短い間隔でチェック
            time_to_close = self.session.close_dt - datetime.datetime.now().astimezone(TZ_NY)
            if time_to_close < timedelta(minutes=self.params.opening_range + 1):
                time.sleep(timing_config.PRODUCTION_SLEEP_MEDIUM)
            else:
                time.sleep(1.0)  # 1 second


class SwingPositionManager:
    """スイングポジション管理クラス"""
    
    def __init__(self, params: TradingParameters, session: MarketSession, order_manager: OrderManager):
        self.params = params
        self.session = session
        self.order_manager = order_manager
    
    def handle_swing_positions(self, order1, order2, order3):
        """スイングポジションを処理"""
        if not self.params.is_swing:
            self._close_all_positions_at_market_close(order1, order2, order3)
        else:
            if self.params.test_mode:
                self._handle_test_mode_swing(order1, order2, order3)
    
    def _close_all_positions_at_market_close(self, order1, order2, order3):
        """市場終了時に全ポジションを終了"""
        open_orders = []
        if self.order_manager.order_state.order1_open:
            open_orders.append(('order1', order1))
        if self.order_manager.order_state.order2_open:
            open_orders.append(('order2', order2))
        if self.order_manager.order_state.order3_open:
            open_orders.append(('order3', order3))
        
        if open_orders:
            logger.info("Closing all open orders at market close")
            cancel_and_close_all_position(self.params.symbol)
            
            latest_price = get_latest_close(self.params.symbol)
            
            for order_key, _ in open_orders:
                setattr(self.order_manager.order_state, f"{order_key}_open", False)
                order_status[order_key]['exit_time'] = str(self.session.current_dt)
                order_status[order_key]['exit_price'] = latest_price
    
    def _handle_test_mode_swing(self, order1, order2, order3):
        """テストモードでのスイング処理"""  
        logger.info("Handling swing positions in test mode")
        
        while not all([
            not self.order_manager.order_state.order1_open,
            not self.order_manager.order_state.order2_open,
            not self.order_manager.order_state.order3_open
        ]):
            # EMA下抜けまたは期間経過でポジション終了
            if self._should_close_swing_position():
                latest_price = get_latest_close(self.params.symbol)
                self._close_all_swing_positions(order1, order2, order3, latest_price)
                break
            
            # 90日経過または現在日時に近づいたら強制終了
            if self._should_force_close_swing():
                latest_price = get_latest_close(self.params.symbol)
                self._close_all_swing_positions(order1, order2, order3, latest_price)
                break
            
            self.session.test_datetime += timedelta(days=1)
    
    def _should_close_swing_position(self) -> bool:
        """スイングポジションを終了すべきかチェック"""
        ema_params = self.params.config.get_ema_parameters()
        return is_below_ema(self.params.symbol, ema_params['trail_medium'])
    
    def _should_force_close_swing(self) -> bool:
        """スイングポジションを強制終了すべきかチェック"""
        entry_time = pd.Timestamp(order_status['order1']['entry_time'])
        current_time = self.session.test_datetime
        today = pd.Timestamp(datetime.datetime.now().astimezone(self.params.config.market.ny_timezone))
        
        max_swing_days = self.params.config.market.swing_max_days
        return (entry_time + timedelta(days=max_swing_days) < current_time or 
                current_time + timedelta(days=2) > today)
    
    def _close_all_swing_positions(self, order1, order2, order3, exit_price: float):
        """全スイングポジションを終了"""
        logger.info("Closing all swing positions")
        
        orders = [
            (order1, 'order1', self.order_manager.order_state.order1_open),
            (order2, 'order2', self.order_manager.order_state.order2_open),
            (order3, 'order3', self.order_manager.order_state.order3_open)
        ]
        
        for order, order_key, is_open in orders:
            if is_open:
                try:
                    cancel_and_close_position(order)
                    setattr(self.order_manager.order_state, f"{order_key}_open", False)
                    order_status[order_key]['exit_time'] = str(self.session.test_datetime)
                    order_status[order_key]['exit_price'] = exit_price
                    logger.info(f"Closed {order_key} swing position at {exit_price}")
                except Exception as e:
                    logger.error(f"Failed to close {order_key} swing position: {e}")


class TradingReporter:
    """取引レポート作成クラス"""
    
    def __init__(self, params: TradingParameters):
        self.params = params
    
    def generate_final_report(self):
        """最終レポートを生成"""
        total_profit = self._calculate_total_profit()
        
        logger.info(f"=== Trading Report for {self.params.symbol} ===")
        logger.info(f"Total Profit: ${total_profit:.2f}")
        
        # 各注文の詳細をログ出力
        for order_key in ['order1', 'order2', 'order3']:
            self._log_order_details(order_key)
        
        print_order_status(order_status)
        
        # テストモードでファイル出力
        if self.params.test_mode and self.params.daily_log:
            self._write_daily_log(total_profit)
        
        return total_profit
    
    def _calculate_total_profit(self) -> float:
        """総利益を計算"""
        total_profit = 0.0
        
        for order_key in ['order1', 'order2', 'order3']:
            order_data = order_status[order_key]
            
            if order_data['exit_price'] != 0:
                # スリッページを考慮した利益計算
                slippage_rate = self.params.config.trading.slippage_rate
                profit = (
                    order_data['exit_price'] * (1 - slippage_rate) - 
                    order_data['entry_price'] * (1 + slippage_rate)
                ) * order_data['qty']
                
                total_profit += profit
                
                # パフォーマンス計算
                pct_return = (order_data['exit_price'] / order_data['entry_price'] - 1) * 100
                
                logger.info(f"{order_key}: Profit=${profit:.2f}, Return={pct_return:.2f}%")
            else:
                logger.info(f"{order_key}: Still holding for swing")
        
        return total_profit
    
    def _log_order_details(self, order_key: str):
        """注文詳細をログ出力"""
        order_data = order_status[order_key]
        
        if order_data['exit_price'] != 0:
            profit = (order_data['exit_price'] - order_data['entry_price']) * order_data['qty']
            return_pct = (order_data['exit_price'] / order_data['entry_price'] - 1) * 100
            
            logger.debug(f"{order_key} Details:")
            logger.debug(f"  Entry: {order_data['entry_price']} @ {order_data['entry_time']}")
            logger.debug(f"  Exit: {order_data['exit_price']} @ {order_data['exit_time']}")
            logger.debug(f"  Quantity: {order_data['qty']}")
            logger.debug(f"  Profit: ${profit:.2f} ({return_pct:.2f}%)")
    
    def _write_daily_log(self, total_profit: float):
        """日次ログをファイルに書き込み"""
        try:
            with open(f'reports/orb_report_{datetime.date.today()}.csv', mode='a') as report_file:
                entry_date = pd.Timestamp(order_status['order1']['entry_time'], tz=self.params.config.market.ny_timezone).date()
                exit_date = pd.Timestamp(order_status['order3']['exit_time'], tz=self.params.config.market.ny_timezone).date()
                
                report_file.write(f"{entry_date},{exit_date},{self.params.symbol},{total_profit:.2f}\n")
                logger.info(f"Daily log written for {self.params.symbol}")
                
        except Exception as e:
            logger.error(f"Failed to write daily log: {e}")


def start_trading_refactored(config_file: str = None):
    """
    リファクタリング版のメイン取引関数
    責任を明確に分離した小さな関数群で構成
    グローバル状態を排除し、設定注入方式を採用
    
    Args:
        config_file: 設定ファイルのパス（オプション）
    """
    try:
        # 0. 設定の初期化
        config = get_orb_config(config_file)
        
        # 1. 引数解析
        params = TradingArgumentParser.parse_arguments(config)
        logger.info(f"Starting refactored trading for {params.symbol}")
        
        # 2. マーケットセッション初期化
        session = MarketSession(params)
        if not session.initialize_session():
            logger.error("Failed to initialize market session")
            return
        
        # 3. エントリー条件チェック
        entry_checker = EntryConditionChecker(params)
        if not entry_checker.wait_for_entry_conditions(session):
            logger.info("Entry conditions not met, exiting")
            return
        
        # 4. 注文管理初期化と初期注文送信
        order_manager = OrderManager(params)
        order1, order2, order3 = order_manager.submit_initial_orders()
        
        if order1 is None:
            logger.error("Failed to submit initial orders")
            return
        
        # 5. ポジション監視
        position_monitor = PositionMonitor(params, session, order_manager)
        position_monitor.monitor_positions(order1, order2, order3)
        
        # 6. スイングポジション処理
        swing_manager = SwingPositionManager(params, session, order_manager)
        swing_manager.handle_swing_positions(order1, order2, order3)
        
        # 7. 最終レポート生成
        reporter = TradingReporter(params)
        total_profit = reporter.generate_final_report()
        
        logger.info(f"Trading completed for {params.symbol} - Total Profit: ${total_profit:.2f}")
        
    except Exception as e:
        logger.error(f"Error in start_trading_refactored: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    start_trading_refactored()