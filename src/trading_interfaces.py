"""
取引機能の抽象インターフェース
循環依存を解決するためのインターフェース分離パターン
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from api_clients import get_alpaca_client
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit

TZ_NY = None
try:
    from zoneinfo import ZoneInfo
    TZ_NY = ZoneInfo("US/Eastern")
except Exception:
    pass

logger = logging.getLogger(__name__)

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
    def is_above_ema(self, symbol: str) -> bool:
        """EMA上判定"""
        pass

class MarketDataInterface(ABC):
    """マーケットデータの抽象インターフェース"""
    
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
    def submit_bracket_orders(self, symbol: str, qty: float, entry_price: float, 
                            stop_price: float, target_price: float) -> Optional[List[str]]:
        """ブラケット注文送信"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """ポジション取得"""
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

class ORBAdapter(TradingInterface, OrderManagementInterface, 
                MarketDataInterface, TimeManagementInterface):
    """orb.pyの機能をインターフェース経由で提供するアダプター"""
    
    def __init__(self):
        # 遅延インポートで循環依存を回避
        self._orb_module = None
        self._alpaca = get_alpaca_client('paper')  # デフォルト paper
    
    @property
    def orb(self):
        """遅延インポートでorb.pyにアクセス"""
        if self._orb_module is None:
            # 循環インポートを避けるため、実際のorb実装は使用しない
            pass
        return self._orb_module
    
    def is_uptrend(self, symbol: str) -> bool:
        """5-minute EMA10/EMA20 を用いたアップトレンド判定

        条件:
        1. 最新終値 > EMA10
        2. EMA10 > EMA20
        3. EMA10 が上昇中（直近2本の差分 >= 0）
        """
        try:
            bars = self._alpaca.get_bars(symbol, TimeFrame(5, TimeFrameUnit.Minute), limit=120)
            if hasattr(bars, 'df'):
                bars = bars.df
            # データ不足なら判定不可 → true (安全側で許可)
            if len(bars) < 30:
                return True

            bars['ema_short'] = bars['close'].ewm(span=10).mean()
            bars['ema_long'] = bars['close'].ewm(span=20).mean()

            ema_short_latest = bars['ema_short'].iloc[-1]
            ema_short_prev = bars['ema_short'].iloc[-2]
            ema_long_latest = bars['ema_long'].iloc[-1]
            price_latest = bars['close'].iloc[-1]

            is_price_above = price_latest > ema_short_latest
            is_ema_cross = ema_short_latest > ema_long_latest
            is_ema_rising = (ema_short_latest - ema_short_prev) >= 0

            return bool(is_price_above and is_ema_cross and is_ema_rising)
        except Exception:
            # 取得失敗時は false にするとエントリーが一切できない恐れがあるため true
            return True
    
    def is_above_ema(self, symbol: str) -> bool:
        try:
            bars = self._alpaca.get_bars(symbol, TimeFrame(5, TimeFrameUnit.Minute), limit=100)
            if hasattr(bars, 'df'):
                bars = bars.df
            ema = bars['close'].ewm(span=50).mean().iloc[-1]
            price = bars['close'].iloc[-1]
            return bool(price > ema)
        except Exception:
            return True
    
    def get_opening_range(self, symbol: str, minutes: int) -> Tuple[float, float]:
        """オープニングレンジ取得"""
        # 過去minutes分のバーで高値・安値を取得
        end_dt = datetime.now(tz=TZ_NY)
        start_dt = end_dt - timedelta(minutes=minutes)
        bars_df = self._alpaca.get_bars(symbol, TimeFrame(minutes, TimeFrameUnit.Minute), start=str(start_dt.date()), end=str(end_dt.date()))
        if hasattr(bars_df, 'df'):
            bars_df = bars_df.df
        if bars_df.empty:
            return (0.0, 0.0)
        return (bars_df['high'].max(), bars_df['low'].min())
    
    def is_opening_range_break(self, symbol: str, high: float, low: float) -> bool:
        """オープニングレンジブレイク判定"""
        # プレースホルダー実装
        latest_close = self.get_latest_price(symbol)
        return latest_close > high
    
    def submit_bracket_orders(self, symbol: str, qty: float, entry_price: float, 
                            stop_price: float, target_price: float) -> Optional[List[str]]:
        """ブラケット注文送信"""
        # プレースホルダー実装
        side = 'buy'
        # Alpaca bracket order
        order = self._alpaca.api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type='limit',
            limit_price=entry_price,
            time_in_force='day',
            order_class='bracket',
            stop_loss={'stop_price': stop_price},
            take_profit={'limit_price': target_price}
        )
        return [order.id]
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """ポジション取得"""
        # プレースホルダー実装
        return self._alpaca.get_positions()
    
    def get_stop_price(self, symbol: str, entry_price: float, stop_rate: float) -> float:
        """ストップ価格計算"""
        return entry_price * (1 - stop_rate)
    
    def get_profit_target(self, symbol: str, entry_price: float, profit_rate: float) -> float:
        """利益目標価格計算"""
        return entry_price * (1 + profit_rate)

    # ------------------------------------------------------------------
    # 追加ユーティリティ
    # ------------------------------------------------------------------

    def get_latest_price(self, symbol: str) -> float:
        """最新価格を取得（ダミー実装）"""
        # 本番環境ではマーケットデータ API から取得する
        # ここではテスト値を返す
        bar = self._alpaca.api.get_latest_trade(symbol)
        return float(bar.p) if hasattr(bar, 'p') else 0.0

    def close_position(self, symbol: str):
        """ポジションをクローズする（ダミー実装）"""
        # 実際のブローカー API 呼び出しは省略
        try:
            self._alpaca.close_position(symbol)
        except Exception:
            pass

    def cancel_and_close_position(self, order_id: str, symbol: str, retries: int = 3, delay: float = 0.5):
        """注文IDのキャンセルを試み、失敗したらポジションをクローズ"""
        for attempt in range(retries):
            try:
                self._alpaca.cancel_order(order_id)
                return True
            except Exception as e:
                logger.debug(f"cancel_order attempt {attempt+1} failed: {e}")
                if attempt == retries - 1:
                    # 最終リトライ後にポジションを成行でクローズ
                    self.close_position(symbol)
                    return False
                time.sleep(delay)
    
    def is_entry_period(self) -> bool:
        """エントリー期間判定"""
        # マーケットオープンから150分以内
        open_dt = datetime.now(tz=TZ_NY).replace(hour=9, minute=30, second=0, microsecond=0)
        return open_dt < datetime.now(tz=TZ_NY) < open_dt + timedelta(minutes=150)
    
    def is_closing_time(self) -> bool:
        """クローズ時間判定"""
        close_dt = datetime.now(tz=TZ_NY).replace(hour=16, minute=0, second=0, microsecond=0)
        return datetime.now(tz=TZ_NY) >= close_dt