"""
設定管理のテスト
config.pyの各種設定クラスと機能のテスト
"""

import unittest
from unittest.mock import patch
import sys
import os

# パスの設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import (
    TradingConfig, TimingConfig, RetryConfig, RiskManagementConfig,
    ScreeningConfig, SystemConfig,
    trading_config, timing_config, retry_config, risk_config,
    screening_config, system_config,
    get_config
)


class TestConfigClasses(unittest.TestCase):
    """設定クラスのテスト"""
    
    def test_trading_config_defaults(self):
        """取引設定のデフォルト値テスト"""
        config = TradingConfig()
        
        # 基本設定の検証
        self.assertEqual(config.MAX_STOP_RATE, 0.06)
        self.assertEqual(config.UPTREND_THRESHOLD, 0.25)
        self.assertEqual(config.POSITION_DIVIDER, 5)
        
        # ORB設定の検証
        self.assertEqual(config.ORB_LIMIT_RATE, 0.006)
        self.assertEqual(config.ORB_ENTRY_PERIOD, 120)
        self.assertEqual(config.ORB_STOP_RATE_1, 0.06)
        
        # Trend Reversion設定の検証
        self.assertEqual(config.TREND_REVERSION_STOP_RATE, 0.08)
        self.assertEqual(config.TREND_REVERSION_NUMBER_STOCKS, 20)
    
    def test_timing_config_defaults(self):
        """タイミング設定のデフォルト値テスト"""
        config = TimingConfig()
        
        self.assertEqual(config.DEFAULT_MINUTES_TO_OPEN, 2)
        self.assertEqual(config.DEFAULT_MINUTES_TO_CLOSE, 1)
        self.assertEqual(config.DATA_LOOKBACK_DAYS, 25)
        self.assertEqual(config.MIN_TRADING_DAYS, 20)
        self.assertEqual(config.PRODUCTION_SLEEP_MINUTE, 60)
    
    def test_retry_config_defaults(self):
        """リトライ設定のデフォルト値テスト"""
        config = RetryConfig()
        
        self.assertEqual(config.ALPACA_MAX_RETRIES, 3)
        self.assertEqual(config.FMP_MAX_RETRIES, 3)
        self.assertEqual(config.FINVIZ_MAX_RETRIES, 5)
        self.assertEqual(config.HTTP_TIMEOUT, 30)
        self.assertEqual(config.CIRCUIT_BREAKER_FAILURE_THRESHOLD, 5)
    
    def test_risk_config_defaults(self):
        """リスク管理設定のデフォルト値テスト"""
        config = RiskManagementConfig()
        
        self.assertEqual(config.PNL_CRITERIA, -0.06)
        self.assertEqual(config.PNL_CHECK_PERIOD, 30)
        self.assertEqual(config.PAGE_SIZE, 100)
        self.assertEqual(config.PARETO_RATIO, 0.2)
    
    def test_screening_config_defaults(self):
        """スクリーニング設定のデフォルト値テスト"""
        config = ScreeningConfig()
        
        self.assertEqual(config.NUMBER_OF_STOCKS, 5)
        self.assertEqual(config.MIN_STOCK_PRICE, 10)
        self.assertEqual(config.MIN_VOLUME, 200)
        self.assertEqual(config.RELATIVE_VOLUME_THRESHOLD, 1.5)
    
    def test_system_config_defaults(self):
        """システム設定のデフォルト値テスト"""
        config = SystemConfig()
        
        self.assertEqual(config.LOG_FILE_MAX_BYTES, 10 * 1024 * 1024)
        self.assertEqual(config.LOG_BACKUP_COUNT, 5)
        self.assertEqual(config.MAX_CONCURRENT_TRADES, 3)
        self.assertEqual(config.CONNECTION_POOL_SIZE, 10)
        self.assertEqual(config.SUCCESS_STATUS_CODE, 200)


class TestConfigInstances(unittest.TestCase):
    """設定インスタンスのテスト"""
    
    def test_global_config_instances(self):
        """グローバル設定インスタンスの存在確認"""
        self.assertIsInstance(trading_config, TradingConfig)
        self.assertIsInstance(timing_config, TimingConfig)
        self.assertIsInstance(retry_config, RetryConfig)
        self.assertIsInstance(risk_config, RiskManagementConfig)
        self.assertIsInstance(screening_config, ScreeningConfig)
        self.assertIsInstance(system_config, SystemConfig)
    
    def test_config_values_consistency(self):
        """設定値の整合性テスト"""
        # ストップ率の妥当性
        self.assertTrue(0 < trading_config.MAX_STOP_RATE < 1)
        self.assertTrue(0 < trading_config.ORB_STOP_RATE_1 < 1)
        
        # タイムアウト値の妥当性
        self.assertTrue(retry_config.HTTP_TIMEOUT > 0)
        self.assertTrue(timing_config.PRODUCTION_SLEEP_MINUTE > 0)
        
        # ページサイズの妥当性
        self.assertTrue(risk_config.PAGE_SIZE > 0)
        self.assertTrue(system_config.LOG_BACKUP_COUNT > 0)
    
    def test_singleton_behavior(self):
        """シングルトン的動作の確認"""
        from config import trading_config as tc1
        from config import trading_config as tc2
        
        # 同じインスタンスであることを確認
        self.assertIs(tc1, tc2)


class TestConfigFunctions(unittest.TestCase):
    """設定管理関数のテスト"""
    
    def test_get_config_function(self):
        """get_config関数のテスト"""
        config_dict = get_config()
        
        # 必要なキーが存在することを確認
        expected_keys = ['trading', 'timing', 'retry', 'risk', 'screening', 'system']
        for key in expected_keys:
            self.assertIn(key, config_dict)
        
        # 各設定が適切な型であることを確認
        self.assertIsInstance(config_dict['trading'], TradingConfig)
        self.assertIsInstance(config_dict['timing'], TimingConfig)
    
    def test_update_config_function(self):
        """update_config関数のテスト（未実装の場合はスキップ）"""
        # update_config関数が未実装のためスキップ
        self.skipTest("update_config function not implemented")
    
    def test_get_account_type(self):
        """get_account_type関数のテスト（未実装の場合はスキップ）"""
        try:
            from config import get_account_type
            with patch.dict(os.environ, {'ALPACA_ACCOUNT_TYPE': 'paper'}):
                account_type = get_account_type()
                self.assertEqual(account_type, 'paper')
        except ImportError:
            self.skipTest("get_account_type function not implemented")
    
    def test_get_log_level(self):
        """get_log_level関数のテスト（未実装の場合はスキップ）"""
        try:
            from config import get_log_level
            with patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}):
                log_level = get_log_level()
                self.assertEqual(log_level, 'DEBUG')
        except ImportError:
            self.skipTest("get_log_level function not implemented")


class TestConfigValidation(unittest.TestCase):
    """設定値の妥当性テスト"""
    
    def test_trading_config_validation(self):
        """取引設定の妥当性テスト"""
        config = trading_config
        
        # 率系の設定は0-1の範囲内
        rate_configs = [
            config.MAX_STOP_RATE,
            config.ORB_LIMIT_RATE,
            config.ORB_SLIPAGE_RATE,
            config.TREND_REVERSION_LIMIT_RATE,
            config.TREND_REVERSION_STOP_RATE
        ]
        
        for rate in rate_configs:
            self.assertTrue(0 < rate < 1, f"Rate {rate} is not in valid range (0, 1)")
        
        # 整数系の設定は正の値
        int_configs = [
            config.POSITION_DIVIDER,
            config.EMA_PERIOD_SHORT,
            config.ORB_ENTRY_PERIOD,
            config.TREND_REVERSION_NUMBER_STOCKS
        ]
        
        for int_val in int_configs:
            self.assertTrue(int_val > 0, f"Integer config {int_val} should be positive")
    
    def test_timing_config_validation(self):
        """タイミング設定の妥当性テスト"""
        config = timing_config
        
        # 時間系の設定は正の値
        time_configs = [
            config.DEFAULT_MINUTES_TO_OPEN,
            config.DEFAULT_MINUTES_TO_CLOSE,
            config.DATA_LOOKBACK_DAYS,
            config.PRODUCTION_SLEEP_MINUTE
        ]
        
        for time_val in time_configs:
            self.assertTrue(time_val > 0, f"Time config {time_val} should be positive")
        
        # 合理的な範囲内であることを確認
        self.assertTrue(config.DATA_LOOKBACK_DAYS < 365, "DATA_LOOKBACK_DAYS should be less than a year")
        self.assertTrue(config.DEFAULT_MINUTES_TO_OPEN < 60, "Minutes to open should be less than an hour")
    
    def test_system_config_validation(self):
        """システム設定の妥当性テスト"""
        config = system_config
        
        # ファイルサイズが合理的な範囲内
        self.assertTrue(1024 * 1024 <= config.LOG_FILE_MAX_BYTES <= 100 * 1024 * 1024,
                       "Log file max bytes should be between 1MB and 100MB")
        
        # バックアップ数が合理的
        self.assertTrue(1 <= config.LOG_BACKUP_COUNT <= 20,
                       "Log backup count should be between 1 and 20")
        
        # 並行処理数が合理的
        self.assertTrue(1 <= config.MAX_CONCURRENT_TRADES <= 10,
                       "Max concurrent trades should be between 1 and 10")


class TestConfigIntegration(unittest.TestCase):
    """設定統合テスト"""
    
    def test_config_usage_in_modules(self):
        """他のモジュールでの設定使用テスト"""
        # 実際のモジュールで設定が正しく使用されることを確認
        
        # trading_configが正しく参照されることを確認
        from config import trading_config as tc
        
        # 基本的な設定値のアクセステスト
        self.assertIsNotNone(tc.MAX_STOP_RATE)
        self.assertIsNotNone(tc.ORB_ENTRY_PERIOD)
        
        # 設定値が期待される型であることを確認
        self.assertIsInstance(tc.MAX_STOP_RATE, float)
        self.assertIsInstance(tc.ORB_ENTRY_PERIOD, int)
    
    def test_config_import_patterns(self):
        """設定のインポートパターンテスト"""
        # 様々なインポート方法が機能することを確認
        
        # 個別インポート
        from config import trading_config
        self.assertIsNotNone(trading_config.MAX_STOP_RATE)
        
        # 関数インポート
        from config import get_config
        config_dict = get_config()
        self.assertIsInstance(config_dict, dict)
        
        # 全体インポート
        import config
        self.assertIsNotNone(config.trading_config)


if __name__ == '__main__':
    # テストの実行
    unittest.main(verbosity=2)