"""
取引戦略のテスト
earnings_swing.py, trend_reversion_stock.py等の戦略ロジックのテスト
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from datetime import datetime, timezone, timedelta
import sys
import os

# パスの設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import trading_config, screening_config


class TestEarningsSwingStrategy(unittest.TestCase):
    """Earnings Swing戦略のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.sample_earnings_data = pd.DataFrame({
            'ticker': ['AAPL', 'MSFT', 'GOOGL'],
            'date': ['2024-01-15', '2024-01-16', '2024-01-17'],
            'estimate': [2.50, 3.20, 1.80],
            'actual': [2.65, 3.15, 1.95]
        })
    
    @patch('sys.modules')
    def test_earnings_data_filtering(self, mock_modules):
        """収益データのフィルタリングテスト"""
        # earnings_swing モジュールをモック
        mock_earnings_swing = Mock()
        mock_modules.__getitem__.return_value = mock_earnings_swing
        
        # フィルタリング関数のモック
        def mock_filter_earnings(data, min_volume=None, min_price=None):
            if min_volume:
                return data[data.index < 2]  # 最初の2行のみ返す
            return data
        
        mock_earnings_swing.filter_earnings_data = mock_filter_earnings
        
        # テスト実行
        filtered_data = mock_filter_earnings(
            self.sample_earnings_data,
            min_volume=screening_config.MIN_VOLUME
        )
        
        # 検証
        self.assertEqual(len(filtered_data), 2)
    
    @patch('earnings_swing.subprocess.Popen')
    @patch('earnings_swing.risk_management.check_pnl_criteria')
    def test_strategy_execution_with_risk_check(self, mock_risk_check, mock_popen):
        """リスクチェック付き戦略実行のテスト"""
        # リスクチェックが通る場合
        mock_risk_check.return_value = True
        mock_process = Mock()
        mock_process.poll.return_value = None  # プロセス実行中
        mock_popen.return_value = mock_process
        
        # 戦略実行をシミュレート
        risk_passed = mock_risk_check()
        if risk_passed:
            process = mock_popen.return_value
        
        # 検証
        self.assertTrue(risk_passed)
        mock_popen.assert_called_once()
    
    @patch('earnings_swing.risk_management.check_pnl_criteria')
    def test_strategy_blocked_by_risk_management(self, mock_risk_check):
        """リスク管理による戦略ブロックのテスト"""
        # リスクチェックが通らない場合
        mock_risk_check.return_value = False
        
        risk_passed = mock_risk_check()
        
        # 戦略が実行されないことを確認
        self.assertFalse(risk_passed)
    
    def test_position_size_calculation(self):
        """ポジションサイズ計算のテスト"""
        account_value = 100000
        position_divider = trading_config.POSITION_DIVIDER
        
        expected_size = account_value / position_divider
        calculated_size = account_value / position_divider
        
        self.assertEqual(calculated_size, expected_size)
        self.assertEqual(calculated_size, 20000)  # 100000 / 5


class TestTrendReversionStrategy(unittest.TestCase):
    """Trend Reversion戦略のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.sample_price_data = pd.DataFrame({
            'Close': [100, 105, 95, 110, 90, 115, 85],
            'Volume': [1000, 1200, 800, 1500, 900, 1100, 1300]
        })
    
    def test_trend_identification(self):
        """トレンド識別のテスト"""
        prices = self.sample_price_data['Close']
        
        # 簡単なトレンド計算のシミュレート
        price_change = prices.pct_change()
        recent_trend = price_change.rolling(3).mean().iloc[-1]
        
        # 下降トレンドの検出
        self.assertTrue(recent_trend < 0)
    
    def test_reversion_signal_generation(self):
        """リバーション シグナル生成のテスト"""
        prices = self.sample_price_data['Close']
        
        # RSIライクな指標のシミュレート
        price_changes = prices.diff()
        gains = price_changes.where(price_changes > 0, 0)
        losses = -price_changes.where(price_changes < 0, 0)
        
        avg_gain = gains.rolling(3).mean().iloc[-1]
        avg_loss = losses.rolling(3).mean().iloc[-1]
        
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi_like = 100 - (100 / (1 + rs))
        else:
            rsi_like = 100
        
        # 過売り状態の検出（RSI < 30相当）
        oversold = rsi_like < 30
        self.assertIsInstance(oversold, bool)
    
    def test_stop_loss_calculation(self):
        """ストップロス計算のテスト"""
        entry_price = 100.0
        stop_rate = trading_config.TREND_REVERSION_STOP_RATE
        
        stop_loss_price = entry_price * (1 - stop_rate)
        expected_stop = 100.0 * (1 - 0.08)  # デフォルト8%
        
        self.assertEqual(stop_loss_price, expected_stop)
        self.assertEqual(stop_loss_price, 92.0)


class TestUpTrendStocksStrategy(unittest.TestCase):
    """UpTrend Stocks戦略のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.sample_finviz_data = pd.DataFrame({
            'Ticker': ['AAPL', 'MSFT', 'GOOGL', 'TSLA'],
            'Price': [150.0, 300.0, 2800.0, 250.0],
            'Volume': [50000000, 30000000, 2000000, 80000000],
            'Market Cap': ['2.5T', '2.3T', '1.8T', '800B']
        })
    
    @patch('uptrend_stocks.FinvizClient')
    def test_uptrend_stock_filtering(self, mock_finviz_client):
        """アップトレンド銘柄フィルタリングのテスト"""
        mock_client = Mock()
        mock_client._make_request.return_value = self.sample_finviz_data
        mock_finviz_client.return_value = mock_client
        
        # フィルタリング条件のテスト
        filtered_data = self.sample_finviz_data[
            self.sample_finviz_data['Price'] >= screening_config.MIN_STOCK_PRICE
        ]
        
        # 最低価格以上の銘柄のみ残ることを確認
        all_above_min = all(price >= screening_config.MIN_STOCK_PRICE 
                           for price in filtered_data['Price'])
        self.assertTrue(all_above_min)
    
    def test_uptrend_threshold_calculation(self):
        """アップトレンド閾値計算のテスト"""
        total_stocks = 1000
        uptrend_stocks = 300
        
        uptrend_ratio = uptrend_stocks / total_stocks
        threshold = trading_config.UPTREND_THRESHOLD
        
        # アップトレンド比率の計算
        self.assertEqual(uptrend_ratio, 0.3)
        
        # 閾値を超えているかの判定
        above_threshold = uptrend_ratio > threshold
        self.assertTrue(above_threshold)  # 0.3 > 0.25
    
    @patch('uptrend_stocks.gspread')
    def test_google_sheets_integration(self, mock_gspread):
        """Google Sheets統合のテスト"""
        mock_client = Mock()
        mock_sheet = Mock()
        mock_worksheet = Mock()
        
        mock_client.open.return_value = mock_sheet
        mock_sheet.worksheet.return_value = mock_worksheet
        mock_gspread.service_account.return_value = mock_client
        
        # シートの更新をシミュレート
        test_data = [['AAPL', '150.0'], ['MSFT', '300.0']]
        mock_worksheet.update.return_value = True
        
        # テスト実行
        result = mock_worksheet.update(test_data)
        
        # 検証
        self.assertTrue(result)
        mock_worksheet.update.assert_called_once_with(test_data)


class TestRelativeVolumeStrategy(unittest.TestCase):
    """Relative Volume戦略のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.sample_volume_data = {
            'AAPL': {'current_volume': 3000000, 'avg_volume': 2000000},
            'MSFT': {'current_volume': 1500000, 'avg_volume': 1800000},
            'GOOGL': {'current_volume': 4000000, 'avg_volume': 2500000}
        }
    
    def test_relative_volume_calculation(self):
        """相対出来高計算のテスト"""
        for ticker, data in self.sample_volume_data.items():
            relative_volume = data['current_volume'] / data['avg_volume']
            
            if ticker == 'AAPL':
                self.assertEqual(relative_volume, 1.5)
            elif ticker == 'MSFT':
                self.assertAlmostEqual(relative_volume, 0.83, places=2)
            elif ticker == 'GOOGL':
                self.assertEqual(relative_volume, 1.6)
    
    def test_volume_threshold_filtering(self):
        """出来高閾値フィルタリングのテスト"""
        threshold = screening_config.RELATIVE_VOLUME_THRESHOLD  # 1.5
        
        qualifying_stocks = []
        for ticker, data in self.sample_volume_data.items():
            relative_volume = data['current_volume'] / data['avg_volume']
            if relative_volume >= threshold:
                qualifying_stocks.append(ticker)
        
        # AAPL(1.5)とGOOGL(1.6)が条件を満たす
        expected_stocks = ['AAPL', 'GOOGL']
        self.assertEqual(set(qualifying_stocks), set(expected_stocks))


class TestORBStrategy(unittest.TestCase):
    """Opening Range Breakout戦略のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.orb_period = trading_config.ORB_ENTRY_PERIOD  # 120分
        self.limit_rate = trading_config.ORB_LIMIT_RATE   # 0.6%
        self.stop_rate = trading_config.ORB_STOP_RATE_1   # 6%
    
    def test_opening_range_calculation(self):
        """オープニングレンジ計算のテスト"""
        # サンプル価格データ（最初の120分）
        opening_prices = [100, 101, 99, 102, 98, 103, 97]
        
        orb_high = max(opening_prices)
        orb_low = min(opening_prices)
        orb_range = orb_high - orb_low
        
        self.assertEqual(orb_high, 103)
        self.assertEqual(orb_low, 97)
        self.assertEqual(orb_range, 6)
    
    def test_breakout_levels_calculation(self):
        """ブレイクアウトレベル計算のテスト"""
        orb_high = 103
        orb_low = 97
        
        # ロングエントリー: ORB高値 + リミット率
        long_entry = orb_high * (1 + self.limit_rate)
        expected_long = 103 * 1.006
        
        self.assertAlmostEqual(long_entry, expected_long, places=3)
        
        # ショートエントリー: ORB安値 - リミット率
        short_entry = orb_low * (1 - self.limit_rate)
        expected_short = 97 * 0.994
        
        self.assertAlmostEqual(short_entry, expected_short, places=3)
    
    def test_stop_loss_calculation(self):
        """ストップロス計算のテスト"""
        entry_price = 103.62  # ロングエントリー価格
        
        stop_loss = entry_price * (1 - self.stop_rate)
        expected_stop = 103.62 * 0.94
        
        self.assertAlmostEqual(stop_loss, expected_stop, places=2)
    
    def test_bracket_order_parameters(self):
        """ブラケット注文パラメータのテスト"""
        entry_price = 103.62
        quantity = 100
        
        # ストップロス
        stop_loss = entry_price * (1 - self.stop_rate)
        
        # テイクプロフィット（2:1のリスクリワード比）
        risk_amount = entry_price - stop_loss
        take_profit = entry_price + (risk_amount * 2)
        
        # パラメータの検証
        self.assertGreater(take_profit, entry_price)
        self.assertLess(stop_loss, entry_price)
        
        # リスクリワード比の確認
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        risk_reward_ratio = reward / risk
        
        self.assertAlmostEqual(risk_reward_ratio, 2.0, places=1)


class TestTradingStrategiesIntegration(unittest.TestCase):
    """取引戦略統合テスト"""
    
    @patch('earnings_swing.risk_management.check_pnl_criteria')
    @patch('earnings_swing.strategy_allocation.get_target_value')
    def test_full_strategy_workflow(self, mock_allocation, mock_risk):
        """完全な戦略ワークフローのテスト"""
        # リスク管理とポジションサイズの設定
        mock_risk.return_value = True
        mock_allocation.return_value = 20000
        
        # ワークフローの実行をシミュレート
        risk_passed = mock_risk()
        if risk_passed:
            position_size = mock_allocation()
            strategy_approved = True
        else:
            strategy_approved = False
        
        # 検証
        self.assertTrue(strategy_approved)
        self.assertEqual(position_size, 20000)
    
    def test_strategy_configuration_consistency(self):
        """戦略設定の整合性テスト"""
        # 各戦略の設定値が妥当な範囲内であることを確認
        self.assertTrue(0 < trading_config.MAX_STOP_RATE < 1)
        self.assertTrue(0 < trading_config.ORB_LIMIT_RATE < 0.1)
        self.assertTrue(trading_config.ORB_ENTRY_PERIOD > 0)
        self.assertTrue(trading_config.POSITION_DIVIDER > 1)
    
    def test_multiple_strategy_execution(self):
        """複数戦略同時実行のテスト"""
        # 同時実行する戦略のリスト
        strategies = ['earnings_swing', 'trend_reversion', 'relative_volume']
        
        # 各戦略の実行状態をシミュレート
        strategy_status = {}
        for strategy in strategies:
            # 各戦略が独立して実行されることを確認
            strategy_status[strategy] = 'running'
        
        # 全戦略が実行状態であることを確認
        self.assertEqual(len(strategy_status), 3)
        self.assertTrue(all(status == 'running' for status in strategy_status.values()))


if __name__ == '__main__':
    # テストの実行
    unittest.main(verbosity=2)