"""
API クライアントのテスト
FMPClient, FinvizClient, AlpacaClientの単体テスト
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

from api_clients import FinvizClient, AlpacaClient, get_fmp_client
from config import retry_config, system_config


class TestFMPClient(unittest.TestCase):
    """FMP APIクライアントのテスト"""
    
    def setUp(self):
        """テスト準備"""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            self.client = get_fmp_client()
    
    @patch('requests.Session.get')
    def test_successful_request(self, mock_get):
        """正常なAPIリクエストのテスト"""
        # モックレスポンスの設定
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "symbol": "AAPL",
                "date": "2023-12-01",
                "open": 190.50,
                "high": 195.00,
                "low": 189.00,
                "close": 194.50,
                "volume": 50000000
            }
        ]
        mock_get.return_value = mock_response
        
        # APIコールの実行
        result = self.client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
        
        # アサーション
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['symbol'], 'AAPL')
        self.assertEqual(result[0]['close'], 194.50)
    
    @patch('requests.Session.get')
    def test_market_cap_data(self, mock_get):
        """時価総額データ取得のテスト"""
        # モックレスポンスの設定
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "symbol": "AAPL",
                "marketCap": 3000000000000,
                "price": 190.50
            }
        ]
        mock_get.return_value = mock_response
        
        # APIコールの実行
        result = self.client.get_market_cap_data(['AAPL'])
        
        # アサーション
        self.assertIsNotNone(result)
        self.assertIn('AAPL', result)
        self.assertEqual(result['AAPL']['marketCap'], 3000000000000)

    @patch('requests.Session.get')
    def test_mid_small_cap_symbols(self, mock_get):
        """中小型株銘柄リスト取得のテスト"""
        # S&P400とS&P600のモックレスポンス
        mock_responses = [
            Mock(status_code=200, json=lambda: [
                {"symbol": "ABC", "name": "ABC Corp"},
                {"symbol": "DEF", "name": "DEF Inc"}
            ]),
            Mock(status_code=200, json=lambda: [
                {"symbol": "GHI", "name": "GHI LLC"},
                {"symbol": "JKL", "name": "JKL Corp"}
            ])
        ]
        mock_get.side_effect = mock_responses
        
        # APIコールの実行
        result = self.client.get_mid_small_cap_symbols()
        
        # アサーション
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 4)
        self.assertIn('ABC', result)
        self.assertIn('DEF', result)
        self.assertIn('GHI', result)
        self.assertIn('JKL', result)

    @patch('requests.Session.get')
    def test_api_error_handling(self, mock_get):
        """APIエラーハンドリングのテスト"""
        # エラーレスポンスの設定
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        mock_get.return_value = mock_response
        
        # APIコールの実行
        result = self.client.get_historical_price_data('INVALID', '2023-12-01', '2023-12-01')
        
        # アサーション
        self.assertIsNone(result)

    @patch('requests.Session.get')
    def test_rate_limit_handling(self, mock_get):
        """レート制限処理のテスト"""
        # レート制限レスポンスの設定
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        mock_get.return_value = mock_response
        
        # APIコールの実行
        result = self.client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
        
        # アサーション
        self.assertIsNone(result)


class TestFinvizClient(unittest.TestCase):
    """Finviz クライアントのテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.client = FinvizClient()
    
    @patch('api_clients.requests.Session.get')
    def test_screener_url_building(self, mock_get):
        """スクリーナーURL構築のテスト"""
        url = self.client.build_screener_url(
            filters=['cap_midover'],
            columns=['ticker', 'price'],
            order='-volume'
        )
        
        # アサーション
        self.assertIn('finviz.com', url)
        self.assertIn('cap_midover', url)
        self.assertIn('ticker', url)
        self.assertIn('o=-volume', url)

    @patch('api_clients.requests.Session.get')
    def test_screener_data_parsing(self, mock_get):
        """スクリーナーデータ解析のテスト"""
        # モックHTMLレスポンス（簡略化）
        mock_html = """
        <table>
            <tr><td>Ticker</td><td>Price</td><td>Volume</td></tr>
            <tr><td>AAPL</td><td>190.50</td><td>50M</td></tr>
            <tr><td>MSFT</td><td>370.00</td><td>30M</td></tr>
        </table>
        """
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = mock_html
        mock_get.return_value = mock_response
        
        # APIコールの実行
        with patch('pandas.read_html') as mock_read_html:
            mock_read_html.return_value = [pd.DataFrame({
                'Ticker': ['AAPL', 'MSFT'],
                'Price': ['190.50', '370.00'],
                'Volume': ['50M', '30M']
            })]
            
            result = self.client.get_screener_data('test_url')
            
            # アサーション
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 2)
            self.assertEqual(result.iloc[0]['Ticker'], 'AAPL')


class TestAlpacaClient(unittest.TestCase):
    """Alpaca クライアントのテスト"""
    
    def setUp(self):
        """テスト準備"""
        with patch.dict(os.environ, {
            'ALPACA_API_KEY': 'test_key',
            'ALPACA_SECRET_KEY': 'test_secret',
            'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets'
        }):
            self.client = AlpacaClient()
    
    @patch('alpaca_trade_api.REST')
    def test_client_initialization(self, mock_rest):
        """クライアント初期化のテスト"""
        # アサーション
        self.assertIsNotNone(self.client)
        self.assertIsNotNone(self.client.api)

    @patch('alpaca_trade_api.REST')
    def test_get_positions(self, mock_rest):
        """ポジション取得のテスト"""
        # モックポジションデータ
        mock_positions = [
            Mock(symbol='AAPL', qty='100', market_value='19050.00'),
            Mock(symbol='MSFT', qty='50', market_value='18500.00')
        ]
        mock_rest.return_value.list_positions.return_value = mock_positions
        
        # APIコールの実行
        positions = self.client.get_positions()
        
        # アサーション
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0]['symbol'], 'AAPL')
        self.assertEqual(positions[0]['qty'], '100')

    @patch('alpaca_trade_api.REST')
    def test_submit_order(self, mock_rest):
        """注文送信のテスト"""
        # モック注文レスポンス
        mock_order = Mock(id='order_123', symbol='AAPL', qty='100')
        mock_rest.return_value.submit_order.return_value = mock_order
        
        # APIコールの実行
        order = self.client.submit_order(
            symbol='AAPL',
            qty=100,
            side='buy',
            type='market',
            time_in_force='day'
        )
        
        # アサーション
        self.assertIsNotNone(order)
        self.assertEqual(order.id, 'order_123')
        self.assertEqual(order.symbol, 'AAPL')


class TestAPIClientIntegration(unittest.TestCase):
    """API クライアント統合テスト"""
    
    def setUp(self):
        """テスト準備"""
        self.test_env = {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret',
            'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets'
        }
    
    @patch.dict(os.environ, {
        'FMP_API_KEY': 'test_fmp_key',
        'ALPACA_API_KEY': 'test_alpaca_key',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret',
    })
    def test_client_factory_functions(self):
        """クライアント工場関数のテスト"""
        from api_clients import get_alpaca_client, get_fmp_client, get_finviz_client
        
        # クライアント取得
        alpaca_client = get_alpaca_client('paper')
        fmp_client = get_fmp_client()
        finviz_client = get_finviz_client()
        
        # アサーション
        self.assertIsNotNone(alpaca_client)
        self.assertIsNotNone(fmp_client)
        self.assertIsNotNone(finviz_client)
        self.assertIsInstance(alpaca_client, AlpacaClient)
        self.assertIsInstance(finviz_client, FinvizClient)

    @patch('requests.Session.get')
    def test_end_to_end_data_flow(self, mock_get):
        """エンドツーエンドデータフローのテスト"""
        # FMPモックレスポンス
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "symbol": "AAPL",
                "date": "2023-12-01",
                "close": 190.50,
                "volume": 50000000
            }
        ]
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, self.test_env):
            fmp_client = get_fmp_client()
            
            # データ取得
            price_data = fmp_client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
            
            # アサーション
            self.assertIsNotNone(price_data)
            self.assertEqual(price_data[0]['symbol'], 'AAPL')

    def test_missing_api_keys(self):
        """APIキー不足のテスト"""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                get_fmp_client()


if __name__ == '__main__':
    unittest.main()