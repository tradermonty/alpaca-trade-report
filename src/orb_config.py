"""
ORB Trading System Configuration Management
グローバル状態を排除し、設定を一元管理するコンフィギュレーションクラス
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo
from logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TradingConfig:
    """取引関連の設定"""
    # Position sizing
    position_size_rate: float = 0.8
    position_divider: int = 3
    
    # Stop and profit rates
    stop_rate_1: float = 0.015
    stop_rate_2: float = 0.02
    stop_rate_3: float = 0.025
    profit_rate_1: float = 0.02
    profit_rate_2: float = 0.04
    profit_rate_3: float = 0.08

    # Entry limit offset (percentage, e.g. 0.006 = 0.6%)
    limit_rate: float = 0.006
    
    # Risk management
    slippage_rate: float = 0.001
    max_position_correlation: float = 0.7
    portfolio_heat: float = 0.02  # 2% portfolio risk per trade
    
    # Entry conditions
    entry_period_minutes: int = 150
    min_volume_threshold: float = 1.5  # 相対出来高
    trend_confirmation_required: bool = True


@dataclass
class MarketConfig:
    """マーケット関連の設定"""
    # Timezone
    ny_timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("US/Eastern"))
    utc_timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    
    # Market hours
    market_open_time: str = "09:30:00"
    market_close_time: str = "16:00:00"
    pre_market_start: str = "04:00:00"
    after_market_end: str = "20:00:00"
    
    # Trading windows
    opening_range_default: int = 5  # minutes
    entry_cutoff_minutes: int = 150  # from market open
    swing_max_days: int = 90


@dataclass
class TechnicalConfig:
    """テクニカル分析の設定"""
    # EMA settings
    ema_short_period: int = 10
    ema_long_period: int = 20
    ema_trend_period: int = 50
    ema_trail_periods: Dict[str, int] = field(default_factory=lambda: {
        'fast': 15,
        'medium': 21,
        'slow': 51
    })
    
    # Timeframes
    primary_timeframe: str = "5Min"
    trend_timeframe: str = "15Min"
    
    # Breakout validation
    min_breakout_volume: float = 1.2
    consolidation_threshold: float = 0.005  # 0.5% range


@dataclass
class SystemConfig:
    """システム関連の設定"""
    # API settings
    max_retries: int = 3
    retry_delay: float = 1.0
    request_timeout: int = 30
    connection_pool_size: int = 10
    
    # Memory management
    memory_threshold_percent: float = 80.0
    large_dataframe_threshold: int = 10000
    dataframe_memory_threshold: int = 50 * 1024 * 1024  # 50MB
    
    # Logging
    log_level: str = "INFO"
    log_rotation_size: str = "10MB"
    log_retention_days: int = 30
    
    # Performance
    max_concurrent_operations: int = 5
    cache_ttl_seconds: int = 300


@dataclass
class TestConfig:
    """テスト関連の設定"""
    test_mode_sleep: float = 0.01
    default_test_date: str = "2023-12-06"
    test_portfolio_value: float = 100000.0
    mock_data_path: str = "tests/data"
    
    # Test market conditions
    test_opening_range_high: float = 100.0
    test_opening_range_low: float = 95.0
    test_latest_price: float = 102.0


class ORBConfiguration:
    """ORB取引システムの統一設定管理クラス"""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        設定の初期化
        
        Args:
            config_file: 設定ファイルのパス（オプション）
        """
        self._trading = TradingConfig()
        self._market = MarketConfig()
        self._technical = TechnicalConfig()
        self._system = SystemConfig()
        self._test = TestConfig()
        
        # 環境変数から設定を上書き
        self._load_from_environment()
        
        # 設定ファイルから読み込み（指定された場合）
        if config_file and os.path.exists(config_file):
            self._load_from_file(config_file)
        
        logger.info("ORB Configuration initialized")
    
    @property
    def trading(self) -> TradingConfig:
        """取引設定を取得"""
        return self._trading
    
    @property
    def market(self) -> MarketConfig:
        """マーケット設定を取得"""
        return self._market
    
    @property
    def technical(self) -> TechnicalConfig:
        """テクニカル設定を取得"""
        return self._technical
    
    @property
    def system(self) -> SystemConfig:
        """システム設定を取得"""
        return self._system
    
    @property
    def test(self) -> TestConfig:
        """テスト設定を取得"""
        return self._test
    
    def _load_from_environment(self):
        """環境変数から設定を読み込み"""
        # Trading config from environment
        if os.getenv('ORB_POSITION_SIZE_RATE'):
            self._trading.position_size_rate = float(os.getenv('ORB_POSITION_SIZE_RATE'))
        
        if os.getenv('ORB_STOP_RATE_1'):
            self._trading.stop_rate_1 = float(os.getenv('ORB_STOP_RATE_1'))
        
        if os.getenv('ORB_PROFIT_RATE_1'):
            self._trading.profit_rate_1 = float(os.getenv('ORB_PROFIT_RATE_1'))

        if os.getenv('ORB_LIMIT_RATE'):
            self._trading.limit_rate = float(os.getenv('ORB_LIMIT_RATE'))
        
        # Market config from environment
        if os.getenv('ORB_OPENING_RANGE_DEFAULT'):
            self._market.opening_range_default = int(os.getenv('ORB_OPENING_RANGE_DEFAULT'))
        
        # System config from environment
        if os.getenv('ORB_MAX_RETRIES'):
            self._system.max_retries = int(os.getenv('ORB_MAX_RETRIES'))
        
        if os.getenv('ORB_LOG_LEVEL'):
            self._system.log_level = os.getenv('ORB_LOG_LEVEL')
    
    def _load_from_file(self, config_file: str):
        """設定ファイルから読み込み"""
        try:
            import json
            with open(config_file, 'r') as f:
                config_data = json.load(f)
            
            # Update configurations from file
            if 'trading' in config_data:
                for key, value in config_data['trading'].items():
                    if hasattr(self._trading, key):
                        setattr(self._trading, key, value)
            
            if 'market' in config_data:
                for key, value in config_data['market'].items():
                    if hasattr(self._market, key):
                        setattr(self._market, key, value)
            
            if 'technical' in config_data:
                for key, value in config_data['technical'].items():
                    if hasattr(self._technical, key):
                        setattr(self._technical, key, value)
            
            if 'system' in config_data:
                for key, value in config_data['system'].items():
                    if hasattr(self._system, key):
                        setattr(self._system, key, value)
            
            logger.info(f"Configuration loaded from {config_file}")
            
        except Exception as e:
            logger.error(f"Failed to load configuration from {config_file}: {e}")
    
    def get_order_parameters(self) -> Dict[str, float]:
        """注文パラメータを取得"""
        return {
            'stop_rate_1': self._trading.stop_rate_1,
            'stop_rate_2': self._trading.stop_rate_2,
            'stop_rate_3': self._trading.stop_rate_3,
            'profit_rate_1': self._trading.profit_rate_1,
            'profit_rate_2': self._trading.profit_rate_2,
            'profit_rate_3': self._trading.profit_rate_3,
            'slippage_rate': self._trading.slippage_rate
        }
    
    def get_ema_parameters(self) -> Dict[str, int]:
        """EMAパラメータを取得"""
        return {
            'short_period': self._technical.ema_short_period,
            'long_period': self._technical.ema_long_period,
            'trend_period': self._technical.ema_trend_period,
            'trail_fast': self._technical.ema_trail_periods['fast'],
            'trail_medium': self._technical.ema_trail_periods['medium'],
            'trail_slow': self._technical.ema_trail_periods['slow']
        }
    
    def get_risk_parameters(self) -> Dict[str, float]:
        """リスク管理パラメータを取得"""
        return {
            'position_size_rate': self._trading.position_size_rate,
            'position_divider': self._trading.position_divider,
            'portfolio_heat': self._trading.portfolio_heat,
            'max_correlation': self._trading.max_position_correlation
        }
    
    def get_market_timing(self) -> Dict[str, Any]:
        """マーケットタイミング設定を取得"""
        return {
            'timezone': self._market.ny_timezone,
            'market_open': self._market.market_open_time,
            'market_close': self._market.market_close_time,
            'opening_range_minutes': self._market.opening_range_default,
            'entry_cutoff_minutes': self._market.entry_cutoff_minutes,
            'swing_max_days': self._market.swing_max_days
        }
    
    def validate_configuration(self) -> bool:
        """設定の妥当性をチェック"""
        try:
            # Trading config validation
            assert 0 < self._trading.position_size_rate <= 1.0, "Position size rate must be between 0 and 1"
            assert self._trading.position_divider > 0, "Position divider must be positive"
            assert all(rate > 0 for rate in [
                self._trading.stop_rate_1, self._trading.stop_rate_2, self._trading.stop_rate_3
            ]), "Stop rates must be positive"
            
            # Market config validation
            assert 1 <= self._market.opening_range_default <= 60, "Opening range must be 1-60 minutes"
            assert self._market.entry_cutoff_minutes > self._market.opening_range_default, \
                "Entry cutoff must be after opening range"
            
            # Technical config validation
            assert self._technical.ema_short_period < self._technical.ema_long_period, \
                "Short EMA period must be less than long EMA period"
            assert all(period > 0 for period in self._technical.ema_trail_periods.values()), \
                "EMA trail periods must be positive"
            
            # System config validation
            assert self._system.max_retries >= 0, "Max retries must be non-negative"
            assert self._system.request_timeout > 0, "Request timeout must be positive"
            
            logger.info("Configuration validation passed")
            return True
            
        except AssertionError as e:
            logger.error(f"Configuration validation failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during configuration validation: {e}")
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """設定を辞書形式で取得"""
        return {
            'trading': {
                'position_size_rate': self._trading.position_size_rate,
                'stop_rates': [self._trading.stop_rate_1, self._trading.stop_rate_2, self._trading.stop_rate_3],
                'profit_rates': [self._trading.profit_rate_1, self._trading.profit_rate_2, self._trading.profit_rate_3],
                'slippage_rate': self._trading.slippage_rate,
                'portfolio_heat': self._trading.portfolio_heat
            },
            'market': {
                'opening_range_default': self._market.opening_range_default,
                'entry_cutoff_minutes': self._market.entry_cutoff_minutes,
                'swing_max_days': self._market.swing_max_days
            },
            'technical': {
                'ema_periods': {
                    'short': self._technical.ema_short_period,
                    'long': self._technical.ema_long_period,
                    'trend': self._technical.ema_trend_period
                },
                'ema_trail_periods': self._technical.ema_trail_periods
            },
            'system': {
                'max_retries': self._system.max_retries,
                'memory_threshold': self._system.memory_threshold_percent,
                'log_level': self._system.log_level
            }
        }
    
    def save_to_file(self, config_file: str):
        """設定をファイルに保存"""
        try:
            import json
            config_dict = self.to_dict()
            with open(config_file, 'w') as f:
                json.dump(config_dict, f, indent=2)
            logger.info(f"Configuration saved to {config_file}")
        except Exception as e:
            logger.error(f"Failed to save configuration to {config_file}: {e}")


# Global configuration instance
_config_instance: Optional[ORBConfiguration] = None


def get_orb_config(config_file: Optional[str] = None) -> ORBConfiguration:
    """
    ORB設定のシングルトンインスタンスを取得
    
    Args:
        config_file: 設定ファイルのパス（初回のみ有効）
        
    Returns:
        ORBConfiguration: 設定インスタンス
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ORBConfiguration(config_file)
        if not _config_instance.validate_configuration():
            raise ValueError("Invalid ORB configuration")
    return _config_instance


def reset_config():
    """設定インスタンスをリセット（テスト用）"""
    global _config_instance
    _config_instance = None