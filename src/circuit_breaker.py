"""
サーキットブレーカーパターンの実装
API障害時の自動復旧と負荷軽減
"""

import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Any, Optional
from logging_config import get_logger
from config import retry_config

logger = get_logger(__name__)


class CircuitBreakerState(Enum):
    """サーキットブレーカーの状態"""
    CLOSED = "CLOSED"      # 正常状態（リクエスト通す）
    OPEN = "OPEN"          # 開放状態（リクエスト遮断）
    HALF_OPEN = "HALF_OPEN"  # 半開状態（テストリクエストのみ）


class CircuitBreaker:
    """
    サーキットブレーカーパターンの実装
    連続した失敗回数が閾値を超えると回路を開き、一定時間後に回復をテスト
    """
    
    def __init__(
        self,
        failure_threshold: int = retry_config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: int = retry_config.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        name: str = "DefaultCircuitBreaker"
    ):
        """
        Args:
            failure_threshold: 失敗回数の閾値
            recovery_timeout: 復旧テストまでの待機時間（秒）
            name: サーキットブレーカーの名前
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitBreakerState.CLOSED
        
        logger.info(f"Circuit breaker '{name}' initialized with threshold={failure_threshold}, timeout={recovery_timeout}s")
    
    def __call__(self, func: Callable) -> Callable:
        """
        デコレーターとして使用する場合の実装
        
        Args:
            func: 保護対象の関数
            
        Returns:
            サーキットブレーカー機能付きの関数
        """
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        サーキットブレーカー経由で関数を実行
        
        Args:
            func: 実行する関数
            *args, **kwargs: 関数の引数
            
        Returns:
            関数の実行結果
            
        Raises:
            CircuitBreakerOpenException: 回路が開いている場合
        """
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN state")
            else:
                raise CircuitBreakerOpenException(
                    f"Circuit breaker '{self.name}' is OPEN. "
                    f"Next reset attempt in {self._time_until_reset():.1f} seconds"
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
            
        except Exception as e:
            self._on_failure(e)
            raise
    
    def _should_attempt_reset(self) -> bool:
        """復旧テストを試行すべきかどうかを判定"""
        if self.last_failure_time is None:
            return True
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout
    
    def _time_until_reset(self) -> float:
        """次の復旧テストまでの残り時間を取得"""
        if self.last_failure_time is None:
            return 0.0
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return max(0.0, self.recovery_timeout - elapsed)
    
    def _on_success(self):
        """成功時の処理"""
        if self.state == CircuitBreakerState.HALF_OPEN:
            logger.info(f"Circuit breaker '{self.name}' recovery successful, closing circuit")
            self.state = CircuitBreakerState.CLOSED
        
        self.failure_count = 0
        self.last_failure_time = None
    
    def _on_failure(self, exception: Exception):
        """失敗時の処理"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        logger.warning(
            f"Circuit breaker '{self.name}' failure #{self.failure_count}: {exception}"
        )
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            # HALF_OPEN状態での失敗は即座にOPEN状態に戻す
            self.state = CircuitBreakerState.OPEN
            logger.warning(f"Circuit breaker '{self.name}' recovery failed, reopening circuit")
            
        elif self.failure_count >= self.failure_threshold:
            # 閾値を超えた場合はOPEN状態にする
            self.state = CircuitBreakerState.OPEN
            logger.error(
                f"Circuit breaker '{self.name}' opened due to {self.failure_count} failures. "
                f"Will attempt recovery in {self.recovery_timeout} seconds"
            )
    
    def force_open(self):
        """サーキットブレーカーを強制的に開く"""
        self.state = CircuitBreakerState.OPEN
        self.last_failure_time = datetime.now()
        logger.warning(f"Circuit breaker '{self.name}' force opened")
    
    def force_close(self):
        """サーキットブレーカーを強制的に閉じる"""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        logger.info(f"Circuit breaker '{self.name}' force closed")
    
    def get_status(self) -> dict:
        """現在の状態を取得"""
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'failure_threshold': self.failure_threshold,
            'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'time_until_reset': self._time_until_reset() if self.state == CircuitBreakerState.OPEN else None
        }


class CircuitBreakerOpenException(Exception):
    """サーキットブレーカーが開いている時の例外"""
    pass


# グローバルサーキットブレーカーインスタンス
alpaca_circuit_breaker = CircuitBreaker(name="AlpacaAPI")
eodhd_circuit_breaker = CircuitBreaker(name="EODHDAPI")
finviz_circuit_breaker = CircuitBreaker(name="FinvizAPI")


def get_circuit_breaker(api_name: str) -> CircuitBreaker:
    """API名に基づいてサーキットブレーカーを取得"""
    circuit_breakers = {
        'alpaca': alpaca_circuit_breaker,
        'eodhd': eodhd_circuit_breaker,
        'finviz': finviz_circuit_breaker,
    }
    
    return circuit_breakers.get(api_name.lower(), CircuitBreaker(name=api_name))


def get_all_circuit_breaker_status() -> list:
    """すべてのサーキットブレーカーの状態を取得"""
    return [
        alpaca_circuit_breaker.get_status(),
        eodhd_circuit_breaker.get_status(),
        finviz_circuit_breaker.get_status(),
    ]