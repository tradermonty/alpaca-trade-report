"""
ORB (Opening Range Breakout) トレーディングシステム - 循環依存修正版
インターフェース分離パターンを使用してorb.pyとの循環依存を解消
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
    order2_open: bool = False
    order3_open: bool = False
    trail_order_active: bool = False
    last_trail_price: float = 0.0


class PositionSizeCalculator:
    """ポジションサイズ計算クラス"""
    
    def __init__(self, adapter: ORBAdapter):
        self.adapter = adapter
    
    def calculate_position_size(self, pos_size_arg: str, config: ORBConfiguration) -> float:
        """ポジションサイズを計算"""
        if pos_size_arg == 'auto':
            # アカウント情報を取得
            positions = self.adapter.get_positions()
            portfolio_value = sum(float(pos.get('market_value', 0)) for pos in positions)
            
            # 設定から計算ロジックを取得
            return (portfolio_value * config.trading.position_size_rate / 
                   (18 * config.trading.position_divider))
        return float(pos_size_arg)


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
        self.position_calculator = PositionSizeCalculator(self.adapter)
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
        """トレンド判定"""
        if not self.adapter.is_uptrend(self.params.symbol):
            return False
        
        if self.params.ema_trail:
            return self.adapter.is_above_ema(self.params.symbol)
        
        return True
    
    def _execute_breakout_strategy(self, high: float, low: float) -> bool:
        """ブレイクアウト戦略の実行"""
        # ブレイクアウト判定
        if not self.adapter.is_opening_range_break(self.params.symbol, high, low):
            logger.info(f"{self.params.symbol}: No breakout detected")
            return False
        
        # ポジションサイズ計算
        position_size = self.position_calculator.calculate_position_size(
            str(self.params.position_size), self.params.config
        )
        
        # エントリー価格の設定
        entry_price = high + 0.01  # 簡略化
        
        # ストップとターゲットの計算
        stop_price = self.adapter.get_stop_price(
            self.params.symbol, entry_price, 
            self.params.config.trading.orb_stop_rate_1
        )
        
        target_price = self.adapter.get_profit_target(
            self.params.symbol, entry_price,
            self.params.config.trading.orb_profit_rate_1
        )
        
        # 注文送信
        orders = self.adapter.submit_bracket_orders(
            self.params.symbol, position_size, entry_price, stop_price, target_price
        )
        
        if orders:
            logger.info(f"{self.params.symbol}: Bracket orders submitted successfully")
            self.order_state.order1_open = True
            return True
        else:
            logger.error(f"{self.params.symbol}: Failed to submit bracket orders")
            return False
    
    def monitor_and_manage_orders(self):
        """注文監視と管理"""
        # 注文状態の監視ロジック（簡略化）
        # 実際の実装では、注文状態をポーリングし、
        # 必要に応じて追加注文やトレーリングストップを実行
        pass


class ORBRefactoredStrategy:
    """リファクタリング版ORB戦略のメインクラス"""
    
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
            position_size=position_size,
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
    parser = argparse.ArgumentParser(description='ORB Trading Strategy (Refactored)')
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
    strategy = ORBRefactoredStrategy(config)
    
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