"""
ORB戦略 - 状態管理リファクタリング版
グローバル変数を状態管理システムに移行した例
"""

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
from zoneinfo import ZoneInfo
import math
from logging_config import get_logger

# 状態管理システム
from state_manager import (
    get_state_manager, 
    is_test_mode, 
    set_test_mode,
    get_current_account,
    is_trading_enabled
)

load_dotenv()

logger = get_logger(__name__)

class TradingError(Exception):
    """取引関連のエラー"""
    pass


class ORBTradingEngine:
    """
    Opening Range Breakout取引エンジン
    状態管理を使用したクリーンなアーキテクチャ
    """
    
    def __init__(self, symbol: str, position_size: float = 0):
        """
        初期化
        
        Args:
            symbol: 取引銘柄
            position_size: ポジションサイズ
        """
        self.symbol = symbol
        self.position_size = position_size
        
        # 状態管理から設定を取得
        self.state_manager = get_state_manager()
        
        # タイムゾーン設定
        self.TZ_NY = ZoneInfo("US/Eastern")
        self.TZ_UTC = ZoneInfo('UTC')
        
        # 設定値をconfig.pyから取得（グローバル定数ではなくインスタンス変数）
        from config import trading_config
        self.limit_rate = trading_config.ORB_LIMIT_RATE
        self.slipage_rate = trading_config.ORB_SLIPAGE_RATE
        
        # 注文パラメータ
        self.stop_rates = [
            trading_config.ORB_STOP_RATE_1,
            trading_config.ORB_STOP_RATE_2, 
            trading_config.ORB_STOP_RATE_3
        ]
        
        self.profit_rates = [
            trading_config.ORB_PROFIT_RATE_1,
            trading_config.ORB_PROFIT_RATE_2,
            trading_config.ORB_PROFIT_RATE_3
        ]
        
        self.entry_period = trading_config.ORB_ENTRY_PERIOD
        
        # APIクライアント（遅延初期化）
        self._alpaca_client = None
        
        # インスタンス状態（グローバル変数の代替）
        self.opening_range = 0
        self.close_dt = pd.Timestamp(datetime.datetime.now().astimezone(self.TZ_NY))
        
        # 注文状態をディクショナリで管理
        self.order_status = {
            "order1": {"qty": 0, "entry_time": "", "entry_price": 0, "exit_time": "", "exit_price": 0},
            "order2": {"qty": 0, "entry_time": "", "entry_price": 0, "exit_time": "", "exit_price": 0},
            "order3": {"qty": 0, "entry_time": "", "entry_price": 0, "exit_time": "", "exit_price": 0}
        }
        
        # 戦略を状態管理に登録
        self.state_manager.register_strategy(f"orb_{symbol}")
        
        logger.info(f"ORB取引エンジン初期化: {symbol} (ポジションサイズ: {position_size})")
    
    @property
    def alpaca_client(self):
        """AlpacaクライアントのLazy initialization"""
        if self._alpaca_client is None:
            account_type = get_current_account()
            self._alpaca_client = get_alpaca_client(account_type)
            logger.debug(f"Alpacaクライアント初期化: {account_type}")
        return self._alpaca_client
    
    @property
    def api(self):
        """後方互換性のためのAPIアクセス"""
        return self.alpaca_client.api
    
    def get_test_datetime(self) -> pd.Timestamp:
        """テスト用の日時を状態管理から取得"""
        if is_test_mode():
            test_dt = self.state_manager.get('test_datetime')
            if test_dt:
                return pd.Timestamp(test_dt)
        
        return pd.Timestamp(datetime.datetime.now().astimezone(self.TZ_NY))
    
    def get_latest_high(self) -> float:
        """最新の高値を取得（状態管理対応）"""
        try:
            if is_test_mode():
                # テストモードでは状態管理からデータを取得
                test_datetime = self.get_test_datetime()
                
                # キャッシュされたデータを使用
                bars_data = self.state_manager.get_cached_data(f'market_data_{self.symbol}_1min')
                
                if bars_data is not None:
                    start_time = test_datetime - timedelta(minutes=60)
                    end_time = test_datetime
                    
                    bars = bars_data.between_time(
                        start_time.astimezone(self.TZ_UTC).time(), 
                        end_time.astimezone(self.TZ_UTC).time()
                    )
                    
                    if not bars.empty:
                        high = bars['high'].tail(1).iloc[0]
                        self._log_api_call('get_latest_high_test')
                        return high
            
            # 本番モードまたはテストデータが利用できない場合
            bar = self.api.get_latest_bar(self.symbol)
            self._log_api_call('get_latest_high_live')
            return bar.h
            
        except Exception as e:
            logger.error(f"最新高値取得エラー {self.symbol}: {e}")
            raise TradingError(f"最新高値取得失敗: {e}")
    
    def get_latest_close(self) -> float:
        """最新の終値を取得（状態管理対応）"""
        try:
            if is_test_mode():
                # テストモードの処理
                test_datetime = self.get_test_datetime()
                bars_data = self.state_manager.get_cached_data(f'market_data_{self.symbol}_1min')
                
                if bars_data is not None:
                    start_time = test_datetime - timedelta(minutes=60)
                    end_time = test_datetime
                    
                    bars = bars_data.between_time(
                        start_time.astimezone(self.TZ_UTC).time(),
                        end_time.astimezone(self.TZ_UTC).time()
                    )
                    
                    if not bars.empty:
                        close = bars['close'].tail(1).iloc[0]
                        self._log_api_call('get_latest_close_test')
                        return close
            
            # 本番モード
            bar = self.api.get_latest_bar(self.symbol)
            self._log_api_call('get_latest_close_live')
            return bar.c
            
        except Exception as e:
            logger.error(f"最新終値取得エラー {self.symbol}: {e}")
            raise TradingError(f"最新終値取得失敗: {e}")
    
    def _log_api_call(self, call_type: str) -> None:
        """API呼び出しをカウント"""
        self.state_manager.increment_counter(f'api_calls_{call_type}')
    
    def calculate_opening_range(self) -> dict:
        """
        オープニングレンジを計算
        
        Returns:
            dict: {'high': float, 'low': float, 'range': float}
        """
        try:
            current_time = self.get_test_datetime() if is_test_mode() else datetime.datetime.now(self.TZ_NY)
            market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            range_end = market_open + timedelta(minutes=self.entry_period)
            
            if current_time < range_end:
                # まだオープニングレンジ期間中
                bars = self.api.get_bars(
                    self.symbol,
                    TimeFrame.Minute,
                    start=market_open,
                    end=current_time
                ).df
            else:
                # オープニングレンジ期間終了
                bars = self.api.get_bars(
                    self.symbol,
                    TimeFrame.Minute,
                    start=market_open,
                    end=range_end
                ).df
            
            if bars.empty:
                raise TradingError("オープニングレンジのデータが取得できません")
            
            orb_high = bars['high'].max()
            orb_low = bars['low'].min()
            orb_range = orb_high - orb_low
            
            # 結果をキャッシュ
            range_data = {
                'high': orb_high,
                'low': orb_low,
                'range': orb_range,
                'calculated_at': current_time
            }
            
            self.state_manager.cache_data(
                f'orb_range_{self.symbol}',
                range_data,
                ttl_seconds=300  # 5分間キャッシュ
            )
            
            self._log_api_call('calculate_opening_range')
            logger.info(f"ORB計算完了 {self.symbol}: H={orb_high:.2f} L={orb_low:.2f} R={orb_range:.2f}")
            
            return range_data
            
        except Exception as e:
            logger.error(f"オープニングレンジ計算エラー {self.symbol}: {e}")
            raise TradingError(f"オープニングレンジ計算失敗: {e}")
    
    def send_bracket_order(self, side: str, entry_price: float, stop_price: float, profit_price: float, order_num: int = 1) -> dict:
        """
        ブラケット注文送信（状態管理対応）
        
        Args:
            side: 'buy' または 'sell'
            entry_price: エントリー価格
            stop_price: ストップロス価格  
            profit_price: 利確価格
            order_num: 注文番号 (1-3)
        
        Returns:
            dict: 注文結果
        """
        # 取引可能性をチェック
        if not is_trading_enabled():
            raise TradingError("取引が無効化されています")
        
        if self.state_manager.get('emergency_stop', False):
            raise TradingError("緊急停止中です")
        
        try:
            qty = int(self.position_size / entry_price) if self.position_size > 0 else 100
            exit_side = 'sell' if side == 'buy' else 'buy'
            
            # 親注文（エントリー）
            parent_order = self.api.submit_order(
                symbol=self.symbol,
                qty=qty,
                side=side,
                type='limit',
                time_in_force='day',
                limit_price=entry_price
            )
            
            # ストップロス注文
            stop_order = self.api.submit_order(
                symbol=self.symbol,
                qty=qty,
                side=exit_side,
                type='stop',
                time_in_force='day',
                stop_price=stop_price,
                parent_order_id=parent_order.id
            )
            
            # 利確注文
            profit_order = self.api.submit_order(
                symbol=self.symbol,
                qty=qty,
                side=exit_side,
                type='limit',
                time_in_force='day',
                limit_price=profit_price,
                parent_order_id=parent_order.id
            )
            
            # 注文状態を更新
            order_key = f"order{order_num}"
            self.order_status[order_key].update({
                'qty': qty,
                'entry_time': datetime.datetime.now().isoformat(),
                'entry_price': entry_price,
                'parent_order_id': parent_order.id,
                'stop_order_id': stop_order.id,
                'profit_order_id': profit_order.id
            })
            
            # API呼び出し回数をカウント
            self._log_api_call('submit_bracket_order')
            
            logger.info(f"ブラケット注文送信完了 {self.symbol}: {side} {qty}株 @{entry_price:.2f}")
            
            return {
                'parent': parent_order,
                'stop': stop_order,
                'profit': profit_order,
                'order_key': order_key
            }
            
        except Exception as e:
            logger.error(f"ブラケット注文エラー {self.symbol}: {e}")
            # 部分的に作成された注文のクリーンアップ
            self._cleanup_partial_orders()
            raise TradingError(f"ブラケット注文失敗: {e}")
    
    def _cleanup_partial_orders(self) -> None:
        """部分的に作成された注文のクリーンアップ"""
        try:
            # 未約定の注文をキャンセル
            open_orders = self.api.list_orders(status='open', symbols=[self.symbol])
            
            for order in open_orders:
                if order.created_at > datetime.datetime.now(datetime.timezone.utc) - timedelta(minutes=5):
                    # 5分以内に作成された注文のみキャンセル
                    self.api.cancel_order(order.id)
                    logger.warning(f"部分注文クリーンアップ: {order.id}")
            
        except Exception as e:
            logger.error(f"注文クリーンアップエラー: {e}")
    
    def execute_orb_strategy(self) -> bool:
        """
        ORB戦略の実行
        
        Returns:
            bool: 実行成功かどうか
        """
        try:
            logger.info(f"ORB戦略実行開始: {self.symbol}")
            
            # 1. オープニングレンジ計算
            orb_data = self.calculate_opening_range()
            
            # 2. ブレイクアウトレベル計算
            long_entry = orb_data['high'] * (1 + self.limit_rate)
            short_entry = orb_data['low'] * (1 - self.limit_rate)
            
            # 3. 現在価格取得
            current_price = self.get_latest_close()
            
            # 4. エントリー判定
            if current_price > long_entry:
                # ロングエントリー
                stop_price = long_entry * (1 - self.stop_rates[0])
                profit_price = long_entry * (1 + self.profit_rates[0])
                
                result = self.send_bracket_order(
                    side='buy',
                    entry_price=long_entry,
                    stop_price=stop_price,
                    profit_price=profit_price,
                    order_num=1
                )
                
                logger.info(f"ロングエントリー実行: {self.symbol} @{long_entry:.2f}")
                return True
                
            elif current_price < short_entry:
                # ショートエントリー
                stop_price = short_entry * (1 + self.stop_rates[0])
                profit_price = short_entry * (1 - self.profit_rates[0])
                
                result = self.send_bracket_order(
                    side='sell',
                    entry_price=short_entry,
                    stop_price=stop_price,
                    profit_price=profit_price,
                    order_num=1
                )
                
                logger.info(f"ショートエントリー実行: {self.symbol} @{short_entry:.2f}")
                return True
            
            else:
                logger.info(f"エントリー条件未達: {self.symbol} 現在価格={current_price:.2f}")
                return False
                
        except Exception as e:
            logger.error(f"ORB戦略実行エラー {self.symbol}: {e}")
            return False
        
        finally:
            # 戦略実行終了を状態管理に通知
            self.state_manager.unregister_strategy(f"orb_{self.symbol}")
    
    def cleanup(self) -> None:
        """リソースクリーンアップ"""
        try:
            # 状態管理から戦略を除去
            self.state_manager.unregister_strategy(f"orb_{self.symbol}")
            
            # キャッシュクリア
            self.state_manager.clear_cache(f'*_{self.symbol}*')
            
            logger.info(f"ORB戦略クリーンアップ完了: {self.symbol}")
            
        except Exception as e:
            logger.error(f"クリーンアップエラー {self.symbol}: {e}")


def main():
    """メイン実行関数（リファクタリング版）"""
    parser = argparse.ArgumentParser(description='ORB取引戦略（状態管理版）')
    parser.add_argument('symbol', help='取引銘柄')
    parser.add_argument('--position_size', type=float, default=1000, help='ポジションサイズ（USD）')
    parser.add_argument('--test', action='store_true', help='テストモード')
    parser.add_argument('--account', choices=['live', 'paper', 'paper_short'], default='live', help='アカウント種別')
    
    args = parser.parse_args()
    
    # 状態管理初期化
    state_manager = get_state_manager()
    
    # 実行モード設定
    if args.test:
        set_test_mode(True)
        logger.info("テストモードで実行")
    
    # アカウント設定
    from state_manager import set_current_account
    set_current_account(args.account)
    
    # ORB戦略エンジン初期化
    orb_engine = ORBTradingEngine(args.symbol, args.position_size)
    
    try:
        # 戦略実行
        success = orb_engine.execute_orb_strategy()
        
        if success:
            logger.info(f"ORB戦略実行成功: {args.symbol}")
            print(f"✅ ORB戦略実行成功: {args.symbol}")
        else:
            logger.info(f"ORB戦略エントリー条件未達: {args.symbol}")
            print(f"⏳ エントリー条件未達: {args.symbol}")
        
        # システム状態サマリー表示
        summary = state_manager.get_system_summary()
        print(f"\nシステム状態:")
        print(f"  アクティブ戦略: {len(summary['active_strategies'])}")
        print(f"  API呼び出し合計: {summary['api_call_total']}")
        print(f"  取引有効: {summary['trading_enabled']}")
        
    except Exception as e:
        logger.error(f"ORB戦略実行エラー: {e}")
        print(f"❌ エラー: {e}")
        sys.exit(1)
        
    finally:
        # クリーンアップ
        orb_engine.cleanup()


if __name__ == '__main__':
    main()