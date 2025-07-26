"""
API クライアントのテスト
EODHDClient, FinvizClient, AlpacaClientの単体テスト
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import requests
from datetime import datetime, timedelta
import sys
import os

# パスの設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from api_clients import EODHDClient, FinvizClient, AlpacaClient
from config import retry_config, system_config


class TestEODHDClient(unittest.TestCase):
    """EODHD APIクライアントのテスト"""
    
    def setUp(self):
        """テスト準備"""
        with patch.dict(os.environ, {'EODHD_API_KEY': 'test_key'}):
            self.client = EODHDClient()
    
    @patch('api_clients.requests.Session.get')
    def test_successful_request(self, mock_get):
        """正常なAPIリクエストのテスト"""
        # モックレスポンスの設定
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'test': 'data'}
        mock_get.return_value = mock_response
        
        # テスト実行
        result = self.client._make_request('test_endpoint')
        
        # 検証
        self.assertEqual(result, {'test': 'data'})
        mock_get.assert_called_once()
    
    @patch('api_clients.requests.Session.get')
    def test_rate_limit_retry(self, mock_get):
        """レート制限時のリトライテスト"""
        # 最初はレート制限、2回目は成功
        mock_response_fail = Mock()
        mock_response_fail.status_code = 429
        
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {'success': True}
        
        mock_get.side_effect = [mock_response_fail, mock_response_success]
        
        with patch('time.sleep'):  # スリープを無効化
            result = self.client._make_request('test_endpoint')
        
        self.assertEqual(result, {'success': True})
        self.assertEqual(mock_get.call_count, 2)
    
    @patch('api_clients.requests.Session.get')
    def test_connection_error_handling(self, mock_get):
        """接続エラーのハンドリングテスト"""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")
        
        with self.assertRaises(requests.exceptions.ConnectionError):
            self.client._make_request('test_endpoint')
    
    def test_historical_data_parsing(self):
        """履歴データのパースのテスト"""
        with patch.object(self.client, '_make_request') as mock_request:
            # モックデータ
            mock_data = [
                {'Date': '2024-01-01', 'Open': 100, 'High': 105, 'Low': 99, 'Close': 104, 'Volume': 1000},
                {'Date': '2024-01-02', 'Open': 104, 'High': 108, 'Low': 103, 'Close': 107, 'Volume': 1200}
            ]
            mock_request.return_value = mock_data
            
            result = self.client.get_historical_data('AAPL.US', '2024-01-01', '2024-01-02')
            
            # データフレームの検証
            self.assertIsInstance(result, pd.DataFrame)
            self.assertEqual(len(result), 2)
            self.assertIn('Close', result.columns)
    
    def tearDown(self):
        """テスト後処理"""
        if hasattr(self.client, 'session'):
            self.client.close()


class TestFinvizClient(unittest.TestCase):
    """Finviz APIクライアントのテスト"""
    
    def setUp(self):
        """テスト準備"""
        with patch.dict(os.environ, {'FINVIZ_API_KEY': 'test_key'}):
            self.client = FinvizClient()
    
    @patch('api_clients.requests.Session.get')
    def test_screener_data_fetch(self, mock_get):
        """スクリーナーデータ取得のテスト"""
        # CSVデータのモック
        csv_data = "Ticker,Price,Change\nAAPL,150.0,2.5%\nMSFT,300.0,1.8%"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = csv_data.encode('utf-8')
        mock_get.return_value = mock_response
        
        result = self.client._make_request('test_url')
        
        # データフレームの検証
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 2)
        self.assertIn('Ticker', result.columns)
        self.assertEqual(result.iloc[0]['Ticker'], 'AAPL')
    
    def test_stock_count_calculation(self):
        """銘柄数計算のテスト"""
        with patch.object(self.client, '_make_request') as mock_request:
            # モックデータフレーム
            mock_df = pd.DataFrame({
                'Ticker': ['AAPL', 'MSFT', 'GOOGL'],
                'Price': [150, 300, 2800]
            })
            mock_request.return_value = mock_df
            
            count = self.client.get_stock_count('test_url')
            
            self.assertEqual(count, 3)
    
    def test_screener_url_construction(self):
        """スクリーナーURL構築のテスト"""
        uptrend_url = self.client.get_uptrend_screener_url()
        total_url = self.client.get_total_screener_url()
        
        self.assertIn('finviz.com', uptrend_url)
        self.assertIn('finviz.com', total_url)
        self.assertIn('export.ashx', uptrend_url)
    
    def tearDown(self):
        """テスト後処理"""
        if hasattr(self.client, 'session'):
            self.client.close()


class TestAlpacaClient(unittest.TestCase):
    """Alpaca APIクライアントのテスト"""
    
    def setUp(self):
        """テスト準備"""
        with patch.dict(os.environ, {
            'ALPACA_API_KEY_LIVE': 'test_key',
            'ALPACA_SECRET_KEY_LIVE': 'test_secret'
        }):
            self.client = AlpacaClient('live')
    
    @patch('api_clients.tradeapi.REST')
    def test_client_initialization(self, mock_rest):
        """クライアント初期化のテスト"""
        mock_api = Mock()
        mock_rest.return_value = mock_api
        
        with patch.dict(os.environ, {
            'ALPACA_API_KEY_LIVE': 'test_key',
            'ALPACA_SECRET_KEY_LIVE': 'test_secret'
        }):
            client = AlpacaClient('live')
            
        self.assertIsNotNone(client.api)
        mock_rest.assert_called_once()
    
    def test_retry_mechanism(self):
        """リトライメカニズムのテスト"""
        with patch.object(self.client, '_api') as mock_api:
            # 最初は失敗、2回目は成功
            mock_api.get_account.side_effect = [
                Exception("Network error"),
                Mock(portfolio_value=100000)
            ]
            
            with patch('time.sleep'):
                result = self.client.get_account()
            
            self.assertIsNotNone(result)
            self.assertEqual(mock_api.get_account.call_count, 2)
    
    def test_position_management(self):
        """ポジション管理のテスト"""
        with patch.object(self.client, '_api') as mock_api:
            # モックポジション
            mock_position = Mock()
            mock_position.symbol = 'AAPL'
            mock_position.qty = '100'
            mock_position.market_value = '15000'
            
            mock_api.list_positions.return_value = [mock_position]
            
            positions = self.client.get_positions()
            
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0].symbol, 'AAPL')
    
    def test_order_submission(self):
        """注文送信のテスト"""
        with patch.object(self.client, '_api') as mock_api:
            mock_order = Mock()
            mock_order.id = 'order_123'
            mock_order.symbol = 'AAPL'
            mock_api.submit_order.return_value = mock_order
            
            result = self.client.submit_order(
                symbol='AAPL',
                qty=100,
                side='buy',
                type='market'
            )
            
            self.assertEqual(result.id, 'order_123')
            mock_api.submit_order.assert_called_once()


class TestAPIClientsIntegration(unittest.TestCase):
    """API クライアント統合テスト"""
    
    def setUp(self):
        """テスト準備"""
        # 環境変数をモック
        self.env_patcher = patch.dict(os.environ, {
            'EODHD_API_KEY': 'test_eodhd_key',
            'FINVIZ_API_KEY': 'test_finviz_key',
            'ALPACA_API_KEY_LIVE': 'test_alpaca_key',
            'ALPACA_SECRET_KEY_LIVE': 'test_alpaca_secret'
        })
        self.env_patcher.start()
    
    def test_client_factory_functions(self):
        """クライアントファクトリー関数のテスト"""
        from api_clients import get_alpaca_client, get_eodhd_client, get_finviz_client
        
        # クライアント取得のテスト
        alpaca_client = get_alpaca_client('live')
        eodhd_client = get_eodhd_client()
        finviz_client = get_finviz_client()
        
        self.assertIsInstance(alpaca_client, AlpacaClient)
        self.assertIsInstance(eodhd_client, EODHDClient)
        self.assertIsInstance(finviz_client, FinvizClient)
    
    def test_singleton_behavior(self):
        """シングルトン動作のテスト"""
        from api_clients import get_eodhd_client
        
        client1 = get_eodhd_client()
        client2 = get_eodhd_client()
        
        # 同じインスタンスが返されることを確認
        self.assertIs(client1, client2)
    
    def tearDown(self):
        """テスト後処理"""
        self.env_patcher.stop()


if __name__ == '__main__':
    # テストの実行
    unittest.main(verbosity=2)