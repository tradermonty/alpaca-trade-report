"""
状態管理システムのテスト
グローバル変数リファクタリングの検証
"""

import unittest
from unittest.mock import Mock, patch
import threading
import time
from datetime import datetime, timezone, timedelta
import sys
import os

# パスの設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from state_manager import (
    StateManager, 
    SystemState,
    get_state_manager,
    is_test_mode,
    set_test_mode,
    is_trading_enabled,
    get_current_account,
    set_current_account
)


class TestSystemState(unittest.TestCase):
    """SystemStateデータクラスのテスト"""
    
    def test_system_state_initialization(self):
        """SystemState初期化のテスト"""
        state = SystemState()
        
        # デフォルト値の確認
        self.assertFalse(state.test_mode)
        self.assertIsNone(state.test_datetime)
        self.assertEqual(state.current_account, 'live')
        self.assertTrue(state.trading_enabled)
        self.assertFalse(state.emergency_stop)
        self.assertEqual(state.current_drawdown, 0.0)
        self.assertIsInstance(state.api_call_count, dict)
        self.assertIsInstance(state.active_strategies, set)
        self.assertIsInstance(state.api_health_status, dict)
    
    def test_system_state_fields(self):
        """SystemStateフィールドのテスト"""
        state = SystemState()
        
        # フィールドの存在確認
        required_fields = [
            'test_mode', 'test_datetime', 'current_account',
            'trading_enabled', 'emergency_stop', 'api_call_count',
            'session_start_time', 'active_strategies', 'market_data_cache',
            'screener_cache', 'api_health_status', 'current_drawdown'
        ]
        
        for field in required_fields:
            self.assertTrue(hasattr(state, field), f"フィールド {field} が存在しません")


class TestStateManager(unittest.TestCase):
    """StateManagerクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        # 新しいStateManagerインスタンスを作成（テスト用）
        StateManager._instance = None
        self.state_manager = StateManager()
    
    def tearDown(self):
        """テスト後処理"""
        # シングルトンインスタンスをクリア
        StateManager._instance = None
    
    def test_singleton_pattern(self):
        """シングルトンパターンのテスト"""
        sm1 = StateManager()
        sm2 = StateManager()
        
        # 同じインスタンスであることを確認
        self.assertIs(sm1, sm2)
    
    def test_get_state(self):
        """状態取得のテスト"""
        state = self.state_manager.get_state()
        
        # 返されるのがSystemStateのコピーであることを確認
        self.assertIsInstance(state, SystemState)
        
        # 元の状態と同じ値であることを確認
        original_state = self.state_manager._state
        self.assertEqual(state.test_mode, original_state.test_mode)
        self.assertEqual(state.current_account, original_state.current_account)
    
    def test_update_state(self):
        """状態更新のテスト"""
        # 単一値更新
        self.state_manager.update_state(test_mode=True)
        self.assertTrue(self.state_manager.get('test_mode'))
        
        # 複数値更新
        self.state_manager.update_state(
            trading_enabled=False,
            current_account='paper'
        )
        
        self.assertFalse(self.state_manager.get('trading_enabled'))
        self.assertEqual(self.state_manager.get('current_account'), 'paper')
    
    def test_get_set_individual_values(self):
        """個別値の取得・設定のテスト"""
        # デフォルト値のテスト
        self.assertEqual(self.state_manager.get('unknown_key', 'default'), 'default')
        
        # 値の設定と取得
        self.state_manager.set('test_mode', True)
        self.assertTrue(self.state_manager.get('test_mode'))
        
        self.state_manager.set('current_account', 'paper_short')
        self.assertEqual(self.state_manager.get('current_account'), 'paper_short')
    
    def test_counter_operations(self):
        """カウンター操作のテスト"""
        counter_name = 'test_counter'
        
        # 初期値は0
        self.assertEqual(self.state_manager.get_counter(counter_name), 0)
        
        # インクリメント
        new_value = self.state_manager.increment_counter(counter_name)
        self.assertEqual(new_value, 1)
        self.assertEqual(self.state_manager.get_counter(counter_name), 1)
        
        # 複数インクリメント
        self.state_manager.increment_counter(counter_name, 5)
        self.assertEqual(self.state_manager.get_counter(counter_name), 6)
        
        # リセット
        self.state_manager.reset_counter(counter_name)
        self.assertEqual(self.state_manager.get_counter(counter_name), 0)
    
    def test_cache_operations(self):
        """キャッシュ操作のテスト"""
        # データキャッシュ
        test_data = {'price': 150.0, 'volume': 1000}
        self.state_manager.cache_data('market_data_AAPL', test_data, ttl_seconds=1)
        
        # キャッシュヒット
        cached_data = self.state_manager.get_cached_data('market_data_AAPL')
        self.assertEqual(cached_data, test_data)
        
        # TTL期限切れテスト
        time.sleep(1.1)  # TTLを超過
        expired_data = self.state_manager.get_cached_data('market_data_AAPL')
        self.assertIsNone(expired_data)
        
        # キャッシュミス
        missing_data = self.state_manager.get_cached_data('nonexistent_key')
        self.assertIsNone(missing_data)
    
    def test_cache_clear(self):
        """キャッシュクリアのテスト"""
        # テストデータ設定
        self.state_manager.cache_data('market_data_AAPL', {'price': 150}, 60)
        self.state_manager.cache_data('screener_tech', {'count': 100}, 60)
        self.state_manager.cache_data('market_data_MSFT', {'price': 300}, 60)
        
        # パターンクリア
        self.state_manager.clear_cache('AAPL')
        self.assertIsNone(self.state_manager.get_cached_data('market_data_AAPL'))
        self.assertIsNotNone(self.state_manager.get_cached_data('screener_tech'))
        
        # 全クリア
        self.state_manager.clear_cache('*')
        self.assertIsNone(self.state_manager.get_cached_data('screener_tech'))
        self.assertIsNone(self.state_manager.get_cached_data('market_data_MSFT'))
    
    def test_strategy_management(self):
        """戦略管理のテスト"""
        strategy_name = 'test_strategy'
        
        # 初期状態
        self.assertFalse(self.state_manager.is_strategy_active(strategy_name))
        self.assertEqual(len(self.state_manager.get_active_strategies()), 0)
        
        # 戦略登録
        self.state_manager.register_strategy(strategy_name)
        self.assertTrue(self.state_manager.is_strategy_active(strategy_name))
        self.assertIn(strategy_name, self.state_manager.get_active_strategies())
        
        # 複数戦略登録
        self.state_manager.register_strategy('strategy2')
        self.assertEqual(len(self.state_manager.get_active_strategies()), 2)
        
        # 戦略解除
        self.state_manager.unregister_strategy(strategy_name)
        self.assertFalse(self.state_manager.is_strategy_active(strategy_name))
        self.assertEqual(len(self.state_manager.get_active_strategies()), 1)
    
    def test_api_health_management(self):
        """API健康状態管理のテスト"""
        # 初期状態確認
        health_status = self.state_manager.get_api_health()
        self.assertIn('alpaca', health_status)
        self.assertEqual(health_status['alpaca'], 'unknown')
        
        # 状態更新
        self.state_manager.update_api_health('alpaca', 'healthy')
        alpaca_health = self.state_manager.get_api_health('alpaca')
        self.assertEqual(alpaca_health['alpaca'], 'healthy')
        
        # 複数API状態更新
        self.state_manager.update_api_health('fmp', 'unhealthy')
        all_health = self.state_manager.get_api_health()
        self.assertEqual(all_health['alpaca'], 'healthy')
        self.assertEqual(all_health['fmp'], 'unhealthy')
    
    def test_emergency_stop(self):
        """緊急停止のテスト"""
        # 初期状態
        self.assertTrue(self.state_manager.get('trading_enabled'))
        self.assertFalse(self.state_manager.get('emergency_stop'))
        
        # 戦略登録
        self.state_manager.register_strategy('test_strategy')
        
        # 緊急停止実行
        self.state_manager.emergency_stop("テスト緊急停止")
        
        # 状態確認
        self.assertFalse(self.state_manager.get('trading_enabled'))
        self.assertTrue(self.state_manager.get('emergency_stop'))
        self.assertEqual(len(self.state_manager.get_active_strategies()), 0)
        
        # 取引再開
        self.state_manager.resume_trading("テスト管理者")
        self.assertTrue(self.state_manager.get('trading_enabled'))
        self.assertFalse(self.state_manager.get('emergency_stop'))
    
    def test_state_listeners(self):
        """状態変更リスナーのテスト"""
        callback_called = []
        
        def test_callback(changes, old_values):
            callback_called.append((changes, old_values))
        
        # リスナー追加
        self.state_manager.add_listener('test_mode', test_callback)
        
        # 状態変更
        self.state_manager.update_state(test_mode=True)
        
        # コールバック呼び出し確認
        self.assertEqual(len(callback_called), 1)
        changes, old_values = callback_called[0]
        self.assertEqual(changes['test_mode'], True)
        self.assertEqual(old_values['test_mode'], False)
        
        # リスナー削除
        self.state_manager.remove_listener('test_mode', test_callback)
        self.state_manager.update_state(test_mode=False)
        
        # コールバックが呼ばれないことを確認
        self.assertEqual(len(callback_called), 1)
    
    def test_system_summary(self):
        """システムサマリーのテスト"""
        summary = self.state_manager.get_system_summary()
        
        # 必要なキーの存在確認
        required_keys = [
            'uptime_seconds', 'trading_enabled', 'emergency_stop',
            'test_mode', 'current_account', 'active_strategies',
            'api_call_total', 'api_health', 'cache_entries', 'current_drawdown'
        ]
        
        for key in required_keys:
            self.assertIn(key, summary, f"サマリーに {key} がありません")
        
        # 値の型確認
        self.assertIsInstance(summary['uptime_seconds'], (int, float))
        self.assertIsInstance(summary['trading_enabled'], bool)
        self.assertIsInstance(summary['active_strategies'], list)
        self.assertIsInstance(summary['api_call_total'], int)


class TestStateFunctions(unittest.TestCase):
    """状態管理関数のテスト"""
    
    def setUp(self):
        """テスト準備"""
        StateManager._instance = None
    
    def tearDown(self):
        """テスト後処理"""
        StateManager._instance = None
    
    def test_get_state_manager(self):
        """get_state_manager関数のテスト"""
        sm1 = get_state_manager()
        sm2 = get_state_manager()
        
        # 同じインスタンスが返されることを確認
        self.assertIs(sm1, sm2)
        self.assertIsInstance(sm1, StateManager)
    
    def test_test_mode_functions(self):
        """テストモード関数のテスト"""
        # 初期状態
        self.assertFalse(is_test_mode())
        
        # テストモード有効化
        test_datetime = datetime.now(timezone.utc)
        set_test_mode(True, test_datetime)
        
        self.assertTrue(is_test_mode())
        
        sm = get_state_manager()
        self.assertEqual(sm.get('test_datetime'), test_datetime)
        
        # テストモード無効化
        set_test_mode(False)
        self.assertFalse(is_test_mode())
    
    def test_trading_enabled_function(self):
        """取引有効性チェック関数のテスト"""
        # 初期状態（取引有効）
        self.assertTrue(is_trading_enabled())
        
        # 取引無効化
        sm = get_state_manager()
        sm.update_state(trading_enabled=False)
        self.assertFalse(is_trading_enabled())
        
        # 緊急停止
        sm.update_state(trading_enabled=True, emergency_stop=True)
        self.assertFalse(is_trading_enabled())
        
        # 正常復帰
        sm.update_state(emergency_stop=False)
        self.assertTrue(is_trading_enabled())
    
    def test_account_management_functions(self):
        """アカウント管理関数のテスト"""
        # 初期状態
        self.assertEqual(get_current_account(), 'live')
        
        # アカウント変更
        set_current_account('paper')
        self.assertEqual(get_current_account(), 'paper')
        
        # 無効なアカウント
        with self.assertRaises(ValueError):
            set_current_account('invalid_account')


class TestThreadSafety(unittest.TestCase):
    """スレッドセーフティのテスト"""
    
    def setUp(self):
        """テスト準備"""
        StateManager._instance = None
        self.state_manager = StateManager()
    
    def tearDown(self):
        """テスト後処理"""
        StateManager._instance = None
    
    def test_concurrent_counter_updates(self):
        """並行カウンター更新のテスト"""
        counter_name = 'concurrent_test'
        num_threads = 10
        increments_per_thread = 100
        
        def increment_counter():
            for _ in range(increments_per_thread):
                self.state_manager.increment_counter(counter_name)
        
        # 複数スレッドで並行実行
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=increment_counter)
            threads.append(thread)
            thread.start()
        
        # 全スレッド完了を待機
        for thread in threads:
            thread.join()
        
        # 最終値確認
        expected_value = num_threads * increments_per_thread
        actual_value = self.state_manager.get_counter(counter_name)
        self.assertEqual(actual_value, expected_value)
    
    def test_concurrent_state_updates(self):
        """並行状態更新のテスト"""
        num_threads = 5
        
        def update_state(thread_id):
            for i in range(10):
                self.state_manager.update_state(
                    **{f'thread_{thread_id}_counter': i}
                )
        
        # 複数スレッドで並行実行
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=update_state, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # 全スレッド完了を待機
        for thread in threads:
            thread.join()
        
        # 最終状態確認
        for thread_id in range(num_threads):
            key = f'thread_{thread_id}_counter'
            value = self.state_manager.get(key)
            self.assertEqual(value, 9)  # 0-9の最後の値


class TestStateManagerIntegration(unittest.TestCase):
    """状態管理システム統合テスト"""
    
    def setUp(self):
        """テスト準備"""
        StateManager._instance = None
        self.state_manager = StateManager()
    
    def tearDown(self):
        """テスト後処理"""  
        StateManager._instance = None
        # テスト用の永続化ファイルを削除
        if os.path.exists('system_state.json'):
            os.remove('system_state.json')
    
    def test_full_workflow(self):
        """完全なワークフローのテスト"""
        # 状態管理インスタンスを取得
        sm = get_state_manager()
        
        # 1. 初期設定
        set_test_mode(True)
        set_current_account('paper')
        
        # 2. 戦略実行シミュレーション
        strategy_name = 'test_orb_AAPL'
        sm.register_strategy(strategy_name)
        
        # 3. API呼び出しシミュレーション
        for _ in range(10):
            sm.increment_counter('api_calls_alpaca')
        
        # 4. データキャッシュ
        market_data = {'price': 150.0, 'volume': 1000000}
        sm.cache_data('market_data_AAPL', market_data, 300)
        
        # 5. API健康状態更新
        sm.update_api_health('alpaca', 'healthy')
        
        # 6. 状態確認
        summary = sm.get_system_summary()
        
        self.assertTrue(summary['test_mode'])
        self.assertEqual(summary['current_account'], 'paper')
        self.assertIn(strategy_name, summary['active_strategies'])
        self.assertEqual(summary['api_call_total'], 10)
        self.assertEqual(summary['cache_entries'], 1)
        self.assertEqual(summary['api_health']['alpaca'], 'healthy')
        
        # 7. 戦略終了
        sm.unregister_strategy(strategy_name)
        
        # 8. 最終状態確認
        final_summary = sm.get_system_summary()
        self.assertEqual(len(final_summary['active_strategies']), 0)


if __name__ == '__main__':
    # テストの実行
    unittest.main(verbosity=2)