"""
取引機能の抽象インターフェース
循環依存を解決するためのインターフェース分離パターン
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TradingData:
    """取引データの標準形式"""
    symbol: str
    price: float
    timestamp: datetime
    volume: int

@dataclass
class OrderInfo:
    """注文情報の標準形式"""
    order_id: str
    symbol: str
    status: str
    filled_qty: float
    avg_fill_price: Optional[float] = None

class TradingInterface(ABC):
    """取引機能の抽象インターフェース"""
    
    @abstractmethod
    def is_uptrend(self, symbol: str) -> bool:
        """アップトレンド判定"""
        pass
    
    @abstractmethod
    def is_above_ema(self, symbol: str, period: int = 21) -> bool:
        """EMA上方判定"""
        pass
    
    @abstractmethod
    def is_below_ema(self, symbol: str, period: int = 21) -> bool:
        """EMA下方判定"""
        pass
    
    @abstractmethod
    def get_opening_range(self, symbol: str, minutes: int) -> Tuple[float, float]:
        """オープニングレンジ取得"""
        pass
    
    @abstractmethod
    def is_opening_range_break(self, symbol: str, high: float, low: float) -> bool:
        """オープニングレンジブレイク判定"""
        pass

class OrderManagementInterface(ABC):
    """注文管理の抽象インターフェース"""
    
    @abstractmethod
    def submit_bracket_orders(self, symbol: str, qty: float, 
                            entry_price: float, stop_price: float, 
                            target_price: float) -> Dict[str, str]:
        """ブラケット注文送信"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderInfo:
        """注文状況取得"""
        pass
    
    @abstractmethod
    def cancel_and_close_position(self, symbol: str) -> bool:
        """ポジションクローズ"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """ポジション取得"""
        pass

class MarketDataInterface(ABC):
    """マーケットデータの抽象インターフェース"""
    
    @abstractmethod
    def get_latest_close(self, symbol: str) -> float:
        """最新終値取得"""
        pass
    
    @abstractmethod
    def get_stop_price(self, symbol: str, entry_price: float, 
                      stop_rate: float) -> float:
        """ストップ価格計算"""
        pass
    
    @abstractmethod
    def get_profit_target(self, symbol: str, entry_price: float,
                         profit_rate: float) -> float:
        """利益目標価格計算"""
        pass

class TimeManagementInterface(ABC):
    """時間管理の抽象インターフェース"""
    
    @abstractmethod
    def is_entry_period(self) -> bool:
        """エントリー期間判定"""
        pass
    
    @abstractmethod
    def is_closing_time(self) -> bool:
        """クローズ時間判定"""
        pass

# 実装例: 既存のorb.py機能をラップするアダプター
class ORBAdapter(TradingInterface, OrderManagementInterface, 
                MarketDataInterface, TimeManagementInterface):
    """orb.pyの機能をインターフェース経由で提供するアダプター"""
    
    def __init__(self):
        # 遅延インポートで循環依存を回避
        self._orb_module = None
    
    @property
    def orb(self):
        """遅延インポートでorb.pyにアクセス"""
        if self._orb_module is None:
            import orb
            self._orb_module = orb
        return self._orb_module
    
    def is_uptrend(self, symbol: str) -> bool:
        return self.orb.is_uptrend(symbol)
    
    def is_above_ema(self, symbol: str, period: int = 21) -> bool:
        return self.orb.is_above_ema(symbol)
    
    def is_below_ema(self, symbol: str, period: int = 21) -> bool:
        return self.orb.is_below_ema(symbol)
    
    def get_opening_range(self, symbol: str, minutes: int) -> Tuple[float, float]:
        return self.orb.get_opening_range(symbol, minutes)
    
    def is_opening_range_break(self, symbol: str, high: float, low: float) -> bool:
        return self.orb.is_opening_range_break(symbol, high, low)
    
    def submit_bracket_orders(self, symbol: str, qty: float, 
                            entry_price: float, stop_price: float, 
                            target_price: float) -> Dict[str, str]:
        return self.orb.submit_bracket_orders(symbol, qty, entry_price, 
                                            stop_price, target_price)
    
    def get_order_status(self, order_id: str) -> OrderInfo:
        # グローバル変数order_statusを安全にアクセス
        status_dict = getattr(self.orb, 'order_status', {}).get(order_id, {})
        return OrderInfo(
            order_id=order_id,
            symbol=status_dict.get('symbol', ''),
            status=status_dict.get('status', ''),
            filled_qty=status_dict.get('filled_qty', 0.0),
            avg_fill_price=status_dict.get('avg_fill_price')
        )
    
    def cancel_and_close_position(self, symbol: str) -> bool:
        return self.orb.cancel_and_close_position(symbol)
    
    def get_positions(self) -> List[Dict[str, Any]]:
        return self.orb.api.list_positions()
    
    def get_latest_close(self, symbol: str) -> float:
        return self.orb.get_latest_close(symbol)
    
    def get_stop_price(self, symbol: str, entry_price: float, 
                      stop_rate: float) -> float:
        return self.orb.get_stop_price(symbol, entry_price, stop_rate)
    
    def get_profit_target(self, symbol: str, entry_price: float,
                         profit_rate: float) -> float:
        return self.orb.get_profit_target(symbol, entry_price, profit_rate)
    
    def is_entry_period(self) -> bool:
        return self.orb.is_entry_period()
    
    def is_closing_time(self) -> bool:
        return self.orb.is_closing_time()

# 使用例: orb_refactored.pyでの利用
class RefactoredORBStrategy:
    """リファクタリング版ORB戦略（循環依存なし）"""
    
    def __init__(self, adapter: ORBAdapter):
        self.adapter = adapter
    
    def execute_strategy(self, symbol: str, position_size: float) -> bool:
        """戦略実行（インターフェース経由）"""
        # 直接インポートではなく、インターフェース経由でアクセス
        if not self.adapter.is_uptrend(symbol):
            return False
        
        if not self.adapter.is_entry_period():
            return False
        
        high, low = self.adapter.get_opening_range(symbol, 30)
        
        if self.adapter.is_opening_range_break(symbol, high, low):
            entry_price = high + 0.01
            stop_price = self.adapter.get_stop_price(symbol, entry_price, 0.03)
            target_price = self.adapter.get_profit_target(symbol, entry_price, 0.06)
            
            orders = self.adapter.submit_bracket_orders(
                symbol, position_size, entry_price, stop_price, target_price
            )
            return bool(orders)
        
        return False

# 依存性注入コンテナ
class TradingServiceContainer:
    """取引サービスコンテナ"""
    
    def __init__(self):
        self._adapter = None
    
    @property
    def orb_adapter(self) -> ORBAdapter:
        """ORBアダプターのシングルトン取得"""
        if self._adapter is None:
            self._adapter = ORBAdapter()
        return self._adapter
    
    def create_orb_strategy(self) -> RefactoredORBStrategy:
        """ORB戦略インスタンスを作成"""
        return RefactoredORBStrategy(self.orb_adapter)

# グローバルコンテナ（必要に応じて）
_container = TradingServiceContainer()

def get_orb_strategy() -> RefactoredORBStrategy:
    """ORB戦略を取得（ファクトリー関数）"""
    return _container.create_orb_strategy()
