"""
ORB (Opening Range Breakout) トレーディングシステム

インターフェース分離パターンを使用したクリーンなアーキテクチャで実装。
グローバル状態を排除し、依存性注入による疎結合設計を採用。
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

# インターフェース経由でorb.pyの機能にアクセス（循環依存回避）
from trading_interfaces import (
    TradingInterface, OrderManagementInterface, 
    MarketDataInterface, TimeManagementInterface,
    ORBAdapter
)

logger = get_logger(__name__)


@dataclass
class TradingParameters:
    """取引パラメータを管理するデータクラス"""
    symbol: str
    position_value: float  # USD amount per trade
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
    order1_open: bool = False
    order2_open: bool = False
    order3_open: bool = False
    trail_order_active: bool = False
    last_trail_price: float = 0.0


class TradeValueCalculator:
    """トレードごとの使用金額 (USD) を計算するユーティリティ"""
    
    def __init__(self, adapter: ORBAdapter):
        self.adapter = adapter
    
    def calculate_trade_value(self, pos_value_arg: str, config: ORBConfiguration) -> float:
        """1回のトレードで使用するUSD金額を計算"""
        if pos_value_arg == 'auto':
            # アカウント情報を取得
            positions = self.adapter.get_positions()
            portfolio_value = sum(float(pos.get('market_value', 0)) for pos in positions)
            
            # 設定から計算ロジックを取得
            return (portfolio_value * config.trading.position_size_rate / 
                   (18 * config.trading.position_divider))
        else:
            return float(pos_value_arg)


class MarketSession:
    """マーケットセッション管理クラス"""
    
    def __init__(self, params: TradingParameters, adapter: ORBAdapter):
        self.params = params
        self.adapter = adapter
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
            f"{self.params.test_date} {open_time}", 
            tz=self.params.config.market.ny_timezone
        )
        
        # マーケットカレンダーの確認はアダプター経由で行う
        # (実装は別途必要)
        return True
    
    def _initialize_live_session(self) -> bool:
        """ライブモード用のセッション初期化"""
        # 現在時刻の取得と設定
        self.current_dt = pd.Timestamp.now(tz=self.params.config.market.ny_timezone)
        return True
    
    def is_market_open(self) -> bool:
        """マーケットが開いているかチェック"""
        return self.adapter.is_entry_period()
    
    def is_closing_time(self) -> bool:
        """クローズ時間かチェック"""
        return self.adapter.is_closing_time()


class TradingEngine:
    """取引エンジンクラス"""
    
    def __init__(self, params: TradingParameters):
        self.params = params
        self.adapter = ORBAdapter()
        self.position_calculator = TradeValueCalculator(self.adapter)
        self.market_session = MarketSession(params, self.adapter)
        self.order_state = OrderState()
        
    def execute_strategy(self) -> bool:
        """ORB戦略を実行"""
        try:
            # セッション初期化
            if not self.market_session.initialize_session():
                logger.error("Failed to initialize market session")
                return False
            
            # トレンドチェック
            if self.params.trend_check and not self._check_trend():
                logger.info(f"{self.params.symbol}: Trend check failed")
                return False
            
            # オープニングレンジの取得
            high, low = self.adapter.get_opening_range(
                self.params.symbol, self.params.opening_range
            )
            
            if high == 0 or low == 0:
                logger.warning(f"{self.params.symbol}: Invalid opening range")
                return False
            
            # ブレイクアウト判定と注文実行
            return self._execute_breakout_strategy(high, low)
            
        except Exception as e:
            logger.error(f"Strategy execution failed for {self.params.symbol}: {e}")
            return False
    
    def _check_trend(self) -> bool:
        """トレンド判定（アップトレンド + EMA50上抜け）"""
        if not self.adapter.is_uptrend(self.params.symbol):
            return False

        # EMA50 上抜けを常時チェック
        if not self.adapter.is_above_ema(self.params.symbol):
            return False

        return True
    
    def _execute_breakout_strategy(self, high: float, low: float) -> bool:
        """ブレイクアウト戦略の実行"""
        # ブレイクアウト判定
        if not self.adapter.is_opening_range_break(self.params.symbol, high, low):
            logger.info(f"{self.params.symbol}: No breakout detected")
            return False
        
        # ポジション金額 (USD)を計算
        position_value = self.position_calculator.calculate_trade_value(
            str(self.params.position_value), self.params.config
        )
        
        # エントリー価格の設定
        #   安全策: 高値に対して (high * limit_rate) もしくは最小幅 $0.05 の大きい方を上乗せし
        #          Marketable Limit として発注する
        t_cfg = self.params.config.trading
        limit_offset = max(0.05, high * t_cfg.limit_rate)
        entry_price = round(high + limit_offset, 2)

        # --- 注文価格計算 --------------------------------------------------

        stops = [
            self.adapter.get_stop_price(self.params.symbol, entry_price, t_cfg.stop_rate_1),
            self.adapter.get_stop_price(self.params.symbol, entry_price, t_cfg.stop_rate_2),
            self.adapter.get_stop_price(self.params.symbol, entry_price, t_cfg.stop_rate_3),
        ]
        targets = [
            self.adapter.get_profit_target(self.params.symbol, entry_price, t_cfg.profit_rate_1),
            self.adapter.get_profit_target(self.params.symbol, entry_price, t_cfg.profit_rate_2),
            self.adapter.get_profit_target(self.params.symbol, entry_price, t_cfg.profit_rate_3),
        ]

        # --- 注文分割 ------------------------------------------------------
        # position_value は USD → 株数へ換算
        qty_total = max(1, math.floor(position_value / entry_price))  # 最低1株
        qty_each = max(1, qty_total // 3)
        # 端数がある場合は 1 本目に加算
        qtys = [qty_each, qty_each, qty_total - qty_each * 2]

        self.order_qtys = {
            'order1': qtys[0],
            'order2': qtys[1],
            'order3': qtys[2],
        }

        order_ids = {}
        for idx in range(3):
            if qtys[idx] <= 0:
                logger.warning("Qty for order %d is 0, skipping" % (idx+1))
                continue
            try:
                oid_list = self.adapter.submit_bracket_orders(
                    self.params.symbol,
                    qtys[idx],
                    entry_price,
                    stops[idx],
                    targets[idx]
                )
                order_ids[f'order{idx+1}'] = oid_list[0] if isinstance(oid_list, list) else oid_list
            except Exception as e:
                logger.error(f"Failed to submit order {idx+1}: {e}")
                return False

        # チェック
        if len(order_ids) < 3:
            logger.error("Not all bracket orders were placed successfully")
            return False

        # 保存
        self.orders = order_ids
        self.order_prices = {
            'order1': {'entry': entry_price, 'stop': stops[0], 'target': targets[0]},
            'order2': {'entry': entry_price, 'stop': stops[1], 'target': targets[1]},
            'order3': {'entry': entry_price, 'stop': stops[2], 'target': targets[2]},
        }

        self.order_state.order1_open = True
        self.order_state.order2_open = True
        self.order_state.order3_open = True

        logger.info(f"{self.params.symbol}: All bracket orders submitted successfully")
        return True
    
    def monitor_and_manage_orders(self):
        """注文監視と管理"""
        logger.info("Starting order monitoring loop")

        # 監視間隔（秒）
        sleep_sec = (self.params.config.test.test_mode_sleep
                     if self.params.test_mode else 60)

        while True:
            # マーケットクローズチェック
            if self.market_session.is_closing_time():
                if self.params.is_swing:
                    # スイングトレード: ポジションを持ち越し、単に監視ループを終了
                    logger.info("Market close – swing trade, keeping positions open. Exiting monitoring loop")
                    break

                # デイトレード: 未決済ポジションを全てクローズ
                logger.info("Market close – day trade, closing all open positions")
                try:
                    mc_latest_price = self.adapter.get_latest_price(self.params.symbol)
                except Exception:
                    mc_latest_price = None

                if self.order_state.order1_open:
                    self._close_order('order1', mc_latest_price or self.order_prices['order1']['entry'])
                if self.order_state.order2_open:
                    self._close_order('order2', mc_latest_price or self.order_prices['order2']['entry'])
                if self.order_state.order3_open:
                    self._close_order('order3', mc_latest_price or self.order_prices['order3']['entry'])

                break

            # すべての注文がクローズされているか
            if not any([
                self.order_state.order1_open,
                self.order_state.order2_open,
                self.order_state.order3_open
            ]):
                logger.info("All orders closed – exiting monitoring loop")
                break

            try:
                latest_price = self.adapter.get_latest_price(self.params.symbol)
            except Exception as e:
                logger.warning(f"Failed to fetch latest price: {e}")
                time.sleep(sleep_sec)
                continue

            current_ts = pd.Timestamp.now(tz=self.params.config.market.ny_timezone)
            logger.debug(f"{current_ts} {self.params.symbol} latest price: {latest_price}")

            # --- 利確判定 -------------------------------------------------
            if (self.order_state.order1_open and
                    latest_price >= self.order_prices['order1']['target']):
                self._close_order('order1', self.order_prices['order1']['target'])

                # 1st order 利確後は 2nd/3rd のストップをエントリー価格まで引き上げ
                self.order_prices['order2']['stop'] = self.order_prices['order2']['entry']
                self.order_prices['order3']['stop'] = self.order_prices['order3']['entry']

            if (self.order_state.order2_open and
                    latest_price >= self.order_prices['order2']['target']):
                self._close_order('order2', self.order_prices['order2']['target'])

            if (self.order_state.order3_open and
                    latest_price >= self.order_prices['order3']['target']):
                self._close_order('order3', self.order_prices['order3']['target'])

            # --- ストップロス判定 -----------------------------------------
            if (self.order_state.order1_open and
                    latest_price <= self.order_prices['order1']['stop']):
                self._close_order('order1', self.order_prices['order1']['stop'])

            if (self.order_state.order2_open and
                    latest_price <= self.order_prices['order2']['stop']):
                self._close_order('order2', self.order_prices['order2']['stop'])

            if (self.order_state.order3_open and
                    latest_price <= self.order_prices['order3']['stop']):
                self._close_order('order3', self.order_prices['order3']['stop'])

            # 待機
            time.sleep(sleep_sec)

    # ---------------------------------------------------------------------
    # internal helpers
    # ---------------------------------------------------------------------

    def _close_order(self, order_key: str, exit_price: float):
        """注文をクローズし、状態を更新する簡易ヘルパー"""
        logger.info(f"Closing {order_key} at price {exit_price}")

        try:
            if hasattr(self.adapter, 'cancel_and_close_position'):
                self.adapter.cancel_and_close_position(self.orders.get(order_key), self.params.symbol)
            elif hasattr(self.adapter, 'close_position'):
                self.adapter.close_position(self.params.symbol)
        except Exception as e:
            logger.warning(f"Adapter cancel/close failed: {e}")

        # 状態を更新
        if order_key == 'order1':
            self.order_state.order1_open = False
        elif order_key == 'order2':
            self.order_state.order2_open = False
        elif order_key == 'order3':
            self.order_state.order3_open = False

        # --- trade log ---------------------------------------------------
        try:
            from trade_logger import log_trade
            entry_time = ''  # could store earlier if needed
            log_trade(
                self.params.symbol,
                'orb',
                order_key,
                self.order_prices[order_key]['entry'],
                exit_price,
                self.order_qtys.get(order_key, 0),
                entry_time
            )
        except Exception as e:
            logger.warning(f"Trade logging failed: {e}")


class ORBStrategy:
    """ORB戦略のメインクラス"""
    
    def __init__(self, config: ORBConfiguration = None):
        self.config = config or get_orb_config()
        
    def start_trading(self, symbol: str, position_size: float = 100, 
                     opening_range: int = 30, is_swing: bool = False,
                     dynamic_rate: bool = False, ema_trail: bool = False,
                     daily_log: bool = False, trend_check: bool = True,
                     test_mode: bool = False, test_date: str = "2023-12-06") -> bool:
        """
        取引を開始（メインエントリーポイント）
        
        Args:
            symbol: 取引銘柄
            position_size: ポジションサイズ
            opening_range: オープニングレンジ（分）
            is_swing: スイング取引フラグ
            dynamic_rate: 動的レート調整フラグ
            ema_trail: EMAトレイル使用フラグ
            daily_log: 日次ログフラグ
            trend_check: トレンドチェックフラグ
            test_mode: テストモードフラグ
            test_date: テスト日付
            
        Returns:
            bool: 取引実行成功フラグ
        """
        # パラメータの構築
        params = TradingParameters(
            symbol=symbol,
            position_value=position_size,
            opening_range=opening_range,
            is_swing=is_swing,
            dynamic_rate=dynamic_rate,
            ema_trail=ema_trail,
            daily_log=daily_log,
            trend_check=trend_check,
            test_mode=test_mode,
            test_date=test_date,
            config=self.config
        )
        
        # 取引エンジンの実行
        engine = TradingEngine(params)
        result = engine.execute_strategy()
        
        if result:
            logger.info(f"ORB strategy executed successfully for {symbol}")
            # 注文監視を開始（非同期処理が望ましい）
            engine.monitor_and_manage_orders()
        else:
            logger.warning(f"ORB strategy execution failed for {symbol}")
        
        return result


def create_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のパーサーを作成"""
    parser = argparse.ArgumentParser(description='ORB Trading Strategy')
    parser.add_argument('symbol', help='Trading symbol')
    parser.add_argument('--position-size', default='100', help='Position size or "auto"')
    parser.add_argument('--opening-range', type=int, default=30, help='Opening range in minutes')
    parser.add_argument('--swing', action='store_true', help='Enable swing trading')
    parser.add_argument('--dynamic-rate', action='store_true', help='Enable dynamic rate adjustment')
    parser.add_argument('--ema-trail', action='store_true', help='Enable EMA trailing')
    parser.add_argument('--daily-log', action='store_true', help='Enable daily logging')
    parser.add_argument('--no-trend-check', action='store_true', help='Disable trend checking')
    parser.add_argument('--test-mode', action='store_true', help='Enable test mode')
    parser.add_argument('--test-date', default='2023-12-06', help='Test date for test mode')
    
    return parser


def main():
    """メイン関数"""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # 設定の読み込み
    config = get_orb_config()
    
    # 戦略インスタンスの作成
    strategy = ORBStrategy(config)
    
    # 取引実行
    try:
        position_size = float(args.position_size) if args.position_size != 'auto' else args.position_size
        
        success = strategy.start_trading(
            symbol=args.symbol,
            position_size=position_size,
            opening_range=args.opening_range,
            is_swing=args.swing,
            dynamic_rate=args.dynamic_rate,
            ema_trail=args.ema_trail,
            daily_log=args.daily_log,
            trend_check=not args.no_trend_check,
            test_mode=args.test_mode,
            test_date=args.test_date
        )
        
        if success:
            logger.info(f"ORB trading completed successfully for {args.symbol}")
        else:
            logger.error(f"ORB trading failed for {args.symbol}")
            
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}", exc_info=True)


if __name__ == "__main__":
    main()