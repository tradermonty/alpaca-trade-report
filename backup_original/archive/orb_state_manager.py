"""
ORB Trading System State Management
グローバル変数を排除し、状態を安全に管理するためのクラス群
"""

import pandas as pd
import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo
from logging_config import get_logger
from orb_config import ORBConfiguration, get_orb_config

logger = get_logger(__name__)


@dataclass
class OrderInfo:
    """個別注文情報"""
    qty: int = 0
    entry_time: str = ""
    entry_price: float = 0.0
    exit_time: str = ""
    exit_price: float = 0.0


@dataclass
class TradingState:
    """
    取引状態を管理するクラス
    グローバル変数の代替として使用
    """
    # Session state
    test_mode: bool = False
    test_datetime: Optional[pd.Timestamp] = None
    close_dt: Optional[pd.Timestamp] = None
    opening_range: int = 0
    position_size: float = 0.0
    
    # Order tracking
    order_status: Dict[str, OrderInfo] = field(default_factory=lambda: {
        "order1": OrderInfo(),
        "order2": OrderInfo(), 
        "order3": OrderInfo()
    })
    
    # Configuration reference
    config: Optional[ORBConfiguration] = None
    
    def __post_init__(self):
        """初期化後の処理"""
        if self.config is None:
            self.config = get_orb_config()
        
        if self.test_datetime is None:
            self.test_datetime = pd.Timestamp(
                datetime.datetime.now().astimezone(self.config.market.ny_timezone)
            )
        
        if self.close_dt is None:
            self.close_dt = pd.Timestamp(
                datetime.datetime.now().astimezone(self.config.market.ny_timezone)
            )
    
    def reset_order_status(self):
        """注文ステータスをリセット"""
        self.order_status = {
            "order1": OrderInfo(),
            "order2": OrderInfo(),
            "order3": OrderInfo()
        }
        logger.info("Order status reset")
    
    def update_order(self, order_key: str, **kwargs):
        """注文情報を更新"""
        if order_key not in self.order_status:
            logger.error(f"Invalid order key: {order_key}")
            return
        
        order_info = self.order_status[order_key]
        for key, value in kwargs.items():
            if hasattr(order_info, key):
                setattr(order_info, key, value)
            else:
                logger.warning(f"Unknown order attribute: {key}")
        
        logger.debug(f"Updated {order_key}: {kwargs}")
    
    def get_order_info(self, order_key: str) -> Optional[OrderInfo]:
        """注文情報を取得"""
        return self.order_status.get(order_key)
    
    def advance_test_time(self, minutes: int = 1):
        """テスト時間を進める"""
        if self.test_mode and self.test_datetime:
            self.test_datetime += pd.Timedelta(minutes=minutes)
            logger.debug(f"Advanced test time to {self.test_datetime}")
    
    def is_market_hours(self) -> bool:
        """マーケット時間かどうかチェック"""
        current_time = self.test_datetime if self.test_mode else pd.Timestamp.now(
            tz=self.config.market.ny_timezone
        )
        
        # 簡単なマーケット時間チェック（実際にはカレンダーAPI使用推奨）
        if current_time.weekday() >= 5:  # 土日
            return False
        
        market_open = current_time.replace(hour=9, minute=30, second=0)
        market_close = current_time.replace(hour=16, minute=0, second=0)
        
        return market_open <= current_time <= market_close
    
    def get_current_datetime(self) -> pd.Timestamp:
        """現在の日時を取得（テスト/本番対応）"""
        if self.test_mode:
            return self.test_datetime
        else:
            return pd.Timestamp.now(tz=self.config.market.ny_timezone)
    
    def calculate_position_pnl(self) -> float:
        """現在ポジションのP&Lを計算"""
        total_pnl = 0.0
        
        for order_key, order_info in self.order_status.items():
            if order_info.exit_price > 0:  # 決済済み
                pnl = (order_info.exit_price - order_info.entry_price) * order_info.qty
                # スリッページを考慮
                slippage_cost = (order_info.entry_price + order_info.exit_price) * \
                               order_info.qty * self.config.trading.slippage_rate
                total_pnl += pnl - slippage_cost
        
        return total_pnl
    
    def to_dict(self) -> Dict[str, Any]:
        """状態を辞書として出力（デバッグ用）"""
        return {
            'test_mode': self.test_mode,
            'test_datetime': str(self.test_datetime),
            'close_dt': str(self.close_dt),
            'opening_range': self.opening_range,
            'position_size': self.position_size,
            'order_status': {
                key: {
                    'qty': info.qty,
                    'entry_time': info.entry_time,
                    'entry_price': info.entry_price,
                    'exit_time': info.exit_time,
                    'exit_price': info.exit_price
                }
                for key, info in self.order_status.items()
            },
            'current_pnl': self.calculate_position_pnl()
        }


class TradingSessionManager:
    """
    取引セッション全体を管理するマネージャークラス
    複数の取引状態を安全に管理
    """
    
    def __init__(self, config: Optional[ORBConfiguration] = None):
        self.config = config or get_orb_config()
        self.active_sessions: Dict[str, TradingState] = {}
        self.session_history: Dict[str, TradingState] = {}
    
    def create_session(self, symbol: str, **kwargs) -> TradingState:
        """新しい取引セッションを作成"""
        if symbol in self.active_sessions:
            logger.warning(f"Session for {symbol} already exists, replacing...")
            self.archive_session(symbol)
        
        session_state = TradingState(config=self.config, **kwargs)
        self.active_sessions[symbol] = session_state
        
        logger.info(f"Created trading session for {symbol}")
        return session_state
    
    def get_session(self, symbol: str) -> Optional[TradingState]:
        """既存セッションを取得"""
        return self.active_sessions.get(symbol)
    
    def archive_session(self, symbol: str):
        """セッションをアーカイブ"""
        if symbol in self.active_sessions:
            self.session_history[f"{symbol}_{datetime.datetime.now().isoformat()}"] = \
                self.active_sessions[symbol]
            del self.active_sessions[symbol]
            logger.info(f"Archived session for {symbol}")
    
    def get_active_symbols(self) -> list[str]:
        """アクティブなシンボル一覧"""
        return list(self.active_sessions.keys())
    
    def cleanup_completed_sessions(self):
        """完了したセッションをクリーンアップ"""
        completed_symbols = []
        
        for symbol, state in self.active_sessions.items():
            # 全注文が決済済みかチェック
            all_closed = all(
                order.exit_price > 0 
                for order in state.order_status.values() 
                if order.qty > 0
            )
            
            if all_closed:
                completed_symbols.append(symbol)
        
        for symbol in completed_symbols:
            self.archive_session(symbol)
        
        if completed_symbols:
            logger.info(f"Cleaned up completed sessions: {completed_symbols}")
    
    def get_total_exposure(self) -> float:
        """全セッションの総エクスポージャーを計算"""
        total_exposure = 0.0
        
        for state in self.active_sessions.values():
            total_exposure += state.position_size
        
        return total_exposure
    
    def emergency_close_all(self):
        """緊急時の全セッション終了"""
        logger.critical("EMERGENCY: Closing all active trading sessions")
        
        for symbol in list(self.active_sessions.keys()):
            self.archive_session(symbol)
        
    def get_system_status(self) -> Dict[str, Any]:
        """システム全体の状態を取得"""
        return {
            'active_sessions': len(self.active_sessions),
            'active_symbols': self.get_active_symbols(),
            'total_sessions_today': len(self.session_history),
            'total_exposure': self.get_total_exposure(),
            'system_memory_usage': len(self.active_sessions) + len(self.session_history)
        }


# シングルトンインスタンス
_session_manager: Optional[TradingSessionManager] = None


def get_session_manager(config: Optional[ORBConfiguration] = None) -> TradingSessionManager:
    """セッションマネージャーのシングルトンインスタンスを取得"""
    global _session_manager
    if _session_manager is None:
        _session_manager = TradingSessionManager(config)
    return _session_manager


def reset_session_manager():
    """セッションマネージャーをリセット（テスト用）"""
    global _session_manager
    _session_manager = None