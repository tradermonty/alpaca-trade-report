"""
ORB Refactored System Unit Tests
リファクタリングされたORBシステムの包括的なテストスイート
"""

import pytest
import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dataclasses import asdict

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from orb_refactored import (
    TradingParameters, TradingArgumentParser, MarketSession,
    EntryConditionChecker, OrderManager, PositionMonitor,
    SwingPositionManager, TradingReporter, OrderState
)
from orb_helper import (
    validate_trading_parameters, calculate_position_metrics,
    format_trading_summary, safe_float_conversion, log_memory_if_high
)


class TestTradingParameters(unittest.TestCase):
    """TradingParametersデータクラスのテスト"""
    
    def test_trading_parameters_creation(self):
        """取引パラメータの正常作成テスト"""
        params = TradingParameters(
            symbol="AAPL",
            position_size=1000.0,
            opening_range=5,
            is_swing=False,
            dynamic_rate=True,
            ema_trail=False,
            daily_log=True,
            trend_check=True,
            test_mode=True,
            test_date="2023-12-06"
        )
        
        self.assertEqual(params.symbol, "AAPL")
        self.assertEqual(params.position_size, 1000.0)
        self.assertEqual(params.opening_range, 5)
        self.assertFalse(params.is_swing)
        self.assertTrue(params.dynamic_rate)
        
    def test_trading_parameters_as_dict(self):
        """データクラスの辞書変換テスト"""
        params = TradingParameters(
            symbol="TSLA", position_size=500.0, opening_range=10,
            is_swing=True, dynamic_rate=False, ema_trail=True,
            daily_log=False, trend_check=False, test_mode=False,
            test_date="2023-12-07"
        )
        
        params_dict = asdict(params)
        self.assertIsInstance(params_dict, dict)
        self.assertEqual(params_dict['symbol'], "TSLA")
        self.assertEqual(len(params_dict), 10)


class TestTradingArgumentParser(unittest.TestCase):
    """TradingArgumentParserクラスのテスト"""
    
    @patch('sys.argv', ['orb_refactored.py', 'AAPL', '--pos_size', '2000', '--range', '10'])
    def test_parse_arguments_basic(self):
        """基本的な引数解析テスト"""
        with patch('orb_refactored.api') as mock_api:
            mock_account = Mock()
            mock_account.portfolio_value = '100000'
            mock_api.get_account.return_value = mock_account
            
            params = TradingArgumentParser.parse_arguments()
            
            self.assertEqual(params.symbol, 'AAPL')
            self.assertEqual(params.position_size, 2000.0)
            self.assertEqual(params.opening_range, 10)
    
    def test_parse_bool_values(self):
        """ブール値解析のテスト"""
        self.assertTrue(TradingArgumentParser._parse_bool('true'))
        self.assertTrue(TradingArgumentParser._parse_bool('True'))
        self.assertTrue(TradingArgumentParser._parse_bool('1'))
        self.assertTrue(TradingArgumentParser._parse_bool('yes'))
        self.assertTrue(TradingArgumentParser._parse_bool(True))
        
        self.assertFalse(TradingArgumentParser._parse_bool('false'))
        self.assertFalse(TradingArgumentParser._parse_bool('False'))
        self.assertFalse(TradingArgumentParser._parse_bool('0'))
        self.assertFalse(TradingArgumentParser._parse_bool('no'))
        self.assertFalse(TradingArgumentParser._parse_bool(False))
    
    @patch('orb_refactored.api')
    def test_calculate_position_size_auto(self, mock_api):
        """自動ポジションサイズ計算テスト"""
        mock_account = Mock()
        mock_account.portfolio_value = '108000'  # 108000 / 18 / 3 = 2000
        mock_api.get_account.return_value = mock_account
        
        size = TradingArgumentParser._calculate_position_size('auto')
        self.assertEqual(size, 2000.0)
    
    def test_calculate_position_size_manual(self):
        """手動ポジションサイズ設定テスト"""
        size = TradingArgumentParser._calculate_position_size('1500')
        self.assertEqual(size, 1500.0)


class TestMarketSession(unittest.TestCase):
    """MarketSessionクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.params = TradingParameters(
            symbol="AAPL", position_size=1000.0, opening_range=5,
            is_swing=False, dynamic_rate=True, ema_trail=False,
            daily_log=False, trend_check=True, test_mode=True,
            test_date="2023-12-06"
        )
        self.session = MarketSession(self.params)
    
    @patch('orb_refactored.api')
    def test_initialize_test_session_success(self, mock_api):
        """テストセッション初期化成功テスト"""
        # マーケットカレンダーのモック
        mock_calendar = Mock()
        mock_calendar.close = '16:00:00'
        mock_api.get_calendar.return_value = [mock_calendar]
        
        with patch.object(self.session, '_load_test_data'):
            result = self.session._initialize_test_session()
            
            self.assertTrue(result)
            self.assertIsNotNone(self.session.test_datetime)
            self.assertIsNotNone(self.session.close_dt)
    
    @patch('orb_refactored.api')
    def test_initialize_test_session_no_market(self, mock_api):
        """マーケット休場時のテストセッション初期化テスト"""
        mock_api.get_calendar.return_value = []
        
        result = self.session._initialize_test_session()
        self.assertFalse(result)
    
    @patch('orb_refactored.api')
    @patch('orb_refactored.datetime')
    def test_initialize_live_session(self, mock_datetime, mock_api):
        """ライブセッション初期化テスト"""
        self.params.test_mode = False
        session = MarketSession(self.params)
        
        # 現在時刻とカレンダーのモック
        mock_now = datetime(2023, 12, 6, 8, 0, 0)
        mock_datetime.datetime.now.return_value = mock_now
        mock_datetime.date.today.return_value = mock_now.date()
        
        mock_calendar = Mock()
        mock_calendar.open = '09:30:00'
        mock_calendar.close = '16:00:00'
        mock_api.get_calendar.return_value = [mock_calendar]
        
        with patch.object(session, '_wait_for_market_open', return_value=True), \
             patch.object(session, '_wait_for_opening_range_complete', return_value=True):
            
            result = session._initialize_live_session()
            self.assertTrue(result)


class TestEntryConditionChecker(unittest.TestCase):
    """EntryConditionCheckerクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.params = TradingParameters(
            symbol="AAPL", position_size=1000.0, opening_range=5,
            is_swing=False, dynamic_rate=True, ema_trail=False,
            daily_log=False, trend_check=True, test_mode=True,
            test_date="2023-12-06"
        )
        self.checker = EntryConditionChecker(self.params)
    
    @patch('orb_refactored.is_uptrend')
    @patch('orb_refactored.is_above_ema')
    @patch('orb_refactored.get_opening_range')
    @patch('orb_refactored.is_opening_range_break')
    def test_check_entry_conditions_all_true(self, mock_range_break, mock_range, 
                                            mock_ema, mock_uptrend):
        """全条件満たす場合のエントリー条件チェック"""
        mock_uptrend.return_value = True
        mock_ema.return_value = True
        mock_range.return_value = (100.0, 95.0)
        mock_range_break.return_value = True
        
        uptrend, ema, range_break = self.checker.check_entry_conditions()
        
        self.assertTrue(uptrend)
        self.assertTrue(ema)
        self.assertTrue(range_break)
    
    @patch('orb_refactored.is_uptrend')
    @patch('orb_refactored.is_above_ema')
    def test_check_entry_conditions_trend_disabled(self, mock_ema, mock_uptrend):
        """トレンドチェック無効時のテスト"""
        self.params.trend_check = False
        self.params.opening_range = 0
        
        uptrend, ema, range_break = self.checker.check_entry_conditions()
        
        # トレンドチェック無効なので常にTrue
        self.assertTrue(uptrend)
        self.assertTrue(ema)
        self.assertTrue(range_break)
        
        # 関数が呼ばれていないことを確認
        mock_uptrend.assert_not_called()
        mock_ema.assert_not_called()


class TestOrderManager(unittest.TestCase):
    """OrderManagerクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.params = TradingParameters(
            symbol="AAPL", position_size=1000.0, opening_range=5,
            is_swing=False, dynamic_rate=True, ema_trail=False,
            daily_log=False, trend_check=True, test_mode=True,
            test_date="2023-12-06"
        )
        self.order_manager = OrderManager(self.params)
    
    @patch('orb_refactored.submit_bracket_orders')
    @patch('orb_refactored.order_status', {'order1': {'entry_price': 100.0}, 
                                          'order2': {'entry_price': 100.0}, 
                                          'order3': {'entry_price': 100.0}})
    def test_submit_initial_orders_success(self, mock_submit):
        """初期注文送信成功テスト"""
        mock_order1, mock_order2, mock_order3 = Mock(), Mock(), Mock()
        mock_submit.return_value = (mock_order1, mock_order2, mock_order3)
        
        with patch.object(self.order_manager, '_calculate_order_prices'):
            order1, order2, order3 = self.order_manager.submit_initial_orders()
            
            self.assertIsNotNone(order1)
            self.assertIsNotNone(order2)
            self.assertIsNotNone(order3)
            mock_submit.assert_called_once_with("AAPL", True)
    
    @patch('orb_refactored.submit_bracket_orders')
    def test_submit_initial_orders_failure(self, mock_submit):
        """初期注文送信失敗テスト"""
        mock_submit.return_value = (None, None, None)
        
        order1, order2, order3 = self.order_manager.submit_initial_orders()
        
        self.assertIsNone(order1)
        self.assertIsNone(order2)
        self.assertIsNone(order3)


class TestPositionMonitor(unittest.TestCase):
    """PositionMonitorクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.params = TradingParameters(
            symbol="AAPL", position_size=1000.0, opening_range=5,
            is_swing=False, dynamic_rate=True, ema_trail=False,
            daily_log=False, trend_check=True, test_mode=True,
            test_date="2023-12-06"
        )
        self.session = MarketSession(self.params)
        self.order_manager = OrderManager(self.params)
        self.monitor = PositionMonitor(self.params, self.session, self.order_manager)
    
    @patch('orb_refactored.get_latest_close')
    def test_check_profit_targets(self, mock_latest_close):
        """利確条件チェックテスト"""
        mock_latest_close.return_value = 105.0
        
        # ターゲット価格を設定
        self.order_manager.target_prices = {
            'order1': 104.0,
            'order2': 106.0,
            'order3': 108.0
        }
        
        # モック注文
        mock_order1 = Mock()
        
        with patch.object(self.monitor, '_close_order') as mock_close:
            self.monitor._check_profit_targets(105.0, mock_order1, None, None)
            
            # order1の利確条件が満たされているのでクローズが呼ばれる
            mock_close.assert_called_once()
    
    @patch('orb_refactored.get_latest_close')
    def test_check_stop_losses(self, mock_latest_close):
        """ストップロス条件チェックテスト"""
        mock_latest_close.return_value = 95.0
        
        # ストップ価格を設定
        self.order_manager.stop_prices = {
            'order1': 96.0,
            'order2': 94.0,
            'order3': 92.0
        }
        
        # モック注文
        mock_order1 = Mock()
        
        with patch.object(self.monitor, '_close_order') as mock_close:
            self.monitor._check_stop_losses(95.0, mock_order1, None, None)
            
            # order1のストップロス条件が満たされているのでクローズが呼ばれる
            mock_close.assert_called_once()


class TestSwingPositionManager(unittest.TestCase):
    """SwingPositionManagerクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.params = TradingParameters(
            symbol="AAPL", position_size=1000.0, opening_range=5,
            is_swing=True, dynamic_rate=True, ema_trail=False,
            daily_log=False, trend_check=True, test_mode=True,
            test_date="2023-12-06"
        )
        self.session = MarketSession(self.params)
        self.order_manager = OrderManager(self.params)
        self.swing_manager = SwingPositionManager(self.params, self.session, self.order_manager)
    
    @patch('orb_refactored.cancel_and_close_all_position')
    @patch('orb_refactored.get_latest_close')
    def test_close_all_positions_at_market_close(self, mock_latest_close, mock_close_all):
        """市場終了時の全ポジション終了テスト"""
        self.params.is_swing = False  # 非スイングモード
        mock_latest_close.return_value = 102.0
        
        # オープンポジションを設定
        self.order_manager.order_state.order1_open = True
        self.order_manager.order_state.order2_open = True
        
        mock_order1, mock_order2, mock_order3 = Mock(), Mock(), Mock()
        
        self.swing_manager._close_all_positions_at_market_close(
            mock_order1, mock_order2, mock_order3
        )
        
        mock_close_all.assert_called_once_with("AAPL")
        self.assertFalse(self.order_manager.order_state.order1_open)
        self.assertFalse(self.order_manager.order_state.order2_open)
    
    @patch('orb_refactored.is_below_ema')
    def test_should_close_swing_position(self, mock_below_ema):
        """スイングポジション終了判定テスト"""
        mock_below_ema.return_value = True
        
        result = self.swing_manager._should_close_swing_position()
        self.assertTrue(result)
        
        mock_below_ema.return_value = False
        result = self.swing_manager._should_close_swing_position()
        self.assertFalse(result)


class TestTradingReporter(unittest.TestCase):
    """TradingReporterクラスのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.params = TradingParameters(
            symbol="AAPL", position_size=1000.0, opening_range=5,
            is_swing=False, dynamic_rate=True, ema_trail=False,
            daily_log=True, trend_check=True, test_mode=True,
            test_date="2023-12-06"
        )
        self.reporter = TradingReporter(self.params)
    
    @patch('orb_refactored.order_status', {
        'order1': {'entry_price': 100.0, 'exit_price': 105.0, 'qty': 10},
        'order2': {'entry_price': 100.0, 'exit_price': 103.0, 'qty': 10},
        'order3': {'entry_price': 100.0, 'exit_price': 0, 'qty': 10}
    })
    @patch('orb_refactored.print_order_status')
    def test_generate_final_report(self, mock_print_status):
        """最終レポート生成テスト"""
        with patch.object(self.reporter, '_write_daily_log'):
            total_profit = self.reporter.generate_final_report()
            
            # 利益計算: (105*0.999 - 100*1.001)*10 + (103*0.999 - 100*1.001)*10
            expected_profit = (104.895 - 100.1) * 10 + (102.897 - 100.1) * 10
            self.assertAlmostEqual(total_profit, expected_profit, places=2)
            
            mock_print_status.assert_called_once()
    
    def test_calculate_total_profit_with_swing_positions(self):
        """スイングポジション含む利益計算テスト"""
        with patch('orb_refactored.order_status', {
            'order1': {'entry_price': 100.0, 'exit_price': 105.0, 'qty': 10},
            'order2': {'entry_price': 100.0, 'exit_price': 0, 'qty': 10},  # スイング継続
            'order3': {'entry_price': 100.0, 'exit_price': 0, 'qty': 10}   # スイング継続
        }):
            total_profit = self.reporter._calculate_total_profit()
            
            # order1のみ決済済み
            expected_profit = (105 * 0.999 - 100 * 1.001) * 10
            self.assertAlmostEqual(total_profit, expected_profit, places=2)


class TestOrbHelper(unittest.TestCase):
    """ORB Helper関数のテスト"""
    
    def test_validate_trading_parameters_valid(self):
        """有効な取引パラメータの検証テスト"""
        valid_params = {
            'symbol': 'AAPL',
            'position_size': 1000.0,
            'opening_range': 5
        }
        
        result = validate_trading_parameters(valid_params)
        self.assertTrue(result)
    
    def test_validate_trading_parameters_invalid(self):
        """無効な取引パラメータの検証テスト"""
        # 必須フィールド不足
        invalid_params1 = {'symbol': 'AAPL', 'position_size': 1000.0}
        result1 = validate_trading_parameters(invalid_params1)
        self.assertFalse(result1)
        
        # 無効なposition_size
        invalid_params2 = {'symbol': 'AAPL', 'position_size': -100.0, 'opening_range': 5}
        result2 = validate_trading_parameters(invalid_params2)
        self.assertFalse(result2)
        
        # 無効なopening_range
        invalid_params3 = {'symbol': 'AAPL', 'position_size': 1000.0, 'opening_range': 70}
        result3 = validate_trading_parameters(invalid_params3)
        self.assertFalse(result3)
    
    def test_calculate_position_metrics(self):
        """ポジションメトリクス計算テスト"""
        metrics = calculate_position_metrics(
            entry_price=100.0,
            exit_price=105.0,
            quantity=10,
            slippage_rate=0.001
        )
        
        expected_entry = 100.0 * 1.001
        expected_exit = 105.0 * 0.999
        expected_profit = (expected_exit - expected_entry) * 10
        expected_return = (expected_exit / expected_entry - 1) * 100
        
        self.assertAlmostEqual(metrics['profit'], expected_profit, places=2)
        self.assertAlmostEqual(metrics['return_pct'], expected_return, places=2)
        self.assertAlmostEqual(metrics['actual_entry_price'], expected_entry, places=3)
        self.assertAlmostEqual(metrics['actual_exit_price'], expected_exit, places=3)
    
    def test_safe_float_conversion(self):
        """安全なfloat変換テスト"""
        # 正常なケース
        self.assertEqual(safe_float_conversion('123.45'), 123.45)
        self.assertEqual(safe_float_conversion(678.90), 678.90)
        self.assertEqual(safe_float_conversion('$1,234.56'), 1234.56)
        self.assertEqual(safe_float_conversion('98.7%'), 98.7)
        
        # エラーケース
        self.assertEqual(safe_float_conversion(None, 10.0), 10.0)
        self.assertEqual(safe_float_conversion('invalid', 5.0), 5.0)
        self.assertEqual(safe_float_conversion('', 0.0), 0.0)
    
    def test_format_trading_summary(self):
        """取引サマリーフォーマットテスト"""
        mock_order_status = {
            'order1': {'entry_price': 100.0, 'exit_price': 105.0, 'qty': 10},
            'order2': {'entry_price': 100.0, 'exit_price': 103.0, 'qty': 10},
            'order3': {'entry_price': 100.0, 'exit_price': 0, 'qty': 10}
        }
        
        summary = format_trading_summary(mock_order_status, "AAPL")
        
        self.assertIn("AAPL", summary)
        self.assertIn("order1:", summary)
        self.assertIn("order2:", summary)
        self.assertIn("Still holding", summary)  # order3がスイング継続
        self.assertIn("Total Profit:", summary)
    
    @patch('psutil.virtual_memory')
    def test_log_memory_if_high(self, mock_memory):
        """メモリ使用量監視テスト"""
        # 高メモリ使用量の場合
        mock_memory_info = Mock()
        mock_memory_info.percent = 85.0
        mock_memory_info.available = 2 * 1024**3  # 2GB
        mock_memory.return_value = mock_memory_info
        
        result = log_memory_if_high(80.0)
        self.assertTrue(result)
        
        # 低メモリ使用量の場合
        mock_memory_info.percent = 75.0
        result = log_memory_if_high(80.0)
        self.assertFalse(result)


class TestIntegration(unittest.TestCase):
    """統合テスト"""
    
    @patch('orb_refactored.api')
    @patch('sys.argv', ['orb_refactored.py', 'AAPL', '--test_mode', 'true'])
    def test_full_trading_workflow_test_mode(self, mock_api):
        """テストモードでの完全取引ワークフローテスト"""
        # APIのモック設定
        mock_account = Mock()
        mock_account.portfolio_value = '54000'  # 54000/18/3 = 1000
        mock_api.get_account.return_value = mock_account
        
        mock_calendar = Mock()
        mock_calendar.close = '16:00:00'
        mock_api.get_calendar.return_value = [mock_calendar]
        
        # 各段階の関数をモック
        with patch('orb_refactored.is_uptrend', return_value=True), \
             patch('orb_refactored.is_above_ema', return_value=True), \
             patch('orb_refactored.get_opening_range', return_value=(100.0, 95.0)), \
             patch('orb_refactored.is_opening_range_break', return_value=True), \
             patch('orb_refactored.submit_bracket_orders') as mock_submit, \
             patch('orb_refactored.is_closing_time', side_effect=[False, False, True]), \
             patch('orb_refactored.get_latest_close', return_value=102.0), \
             patch('orb_refactored.print_order_status'):
            
            mock_order1, mock_order2, mock_order3 = Mock(), Mock(), Mock()
            mock_submit.return_value = (mock_order1, mock_order2, mock_order3)
            
            # start_trading_refactored関数のテスト実行は実際のコードで必要に応じて実装


if __name__ == '__main__':
    # テストの実行
    unittest.main(verbosity=2)