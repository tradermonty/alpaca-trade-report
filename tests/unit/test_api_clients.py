"""Unit tests for API clients."""

import pytest
import pandas as pd
import os
from unittest.mock import Mock, patch, MagicMock
import requests
from datetime import datetime

from api_clients import AlpacaClient, FinvizClient
from api_clients import get_alpaca_client, get_fmp_client, get_finviz_client


class TestAlpacaClient:
    """Test AlpacaClient class."""

    def test_init_live_account(self, mock_env_vars):
        """Test AlpacaClient initialization for live account."""
        with patch.dict(os.environ, mock_env_vars):
            with patch('alpaca_trade_api.REST') as mock_rest:
                client = AlpacaClient('live')
                assert client.account_type == 'live'
                mock_rest.assert_called_once()

    def test_init_paper_account(self, mock_env_vars):
        """Test AlpacaClient initialization for paper account."""
        with patch.dict(os.environ, mock_env_vars):
            with patch('alpaca_trade_api.REST') as mock_rest:
                client = AlpacaClient('paper')
                assert client.account_type == 'paper'
                mock_rest.assert_called_once()

    def test_get_positions(self, mock_env_vars):
        """Test getting positions from Alpaca."""
        with patch.dict(os.environ, mock_env_vars):
            with patch('alpaca_trade_api.REST') as mock_rest:
                # Mock positions data
                mock_positions = [
                    Mock(symbol='AAPL', qty='100', market_value='19050.00'),
                    Mock(symbol='MSFT', qty='50', market_value='18500.00')
                ]
                mock_rest.return_value.list_positions.return_value = mock_positions
                
                client = AlpacaClient('paper')
                positions = client.get_positions()
                
                assert len(positions) == 2
                assert positions[0]['symbol'] == 'AAPL'
                assert positions[1]['symbol'] == 'MSFT'

    def test_submit_order(self, mock_env_vars):
        """Test submitting an order through Alpaca."""
        with patch.dict(os.environ, mock_env_vars):
            with patch('alpaca_trade_api.REST') as mock_rest:
                # Mock order response
                mock_order = Mock(id='order_123', symbol='AAPL', qty='100')
                mock_rest.return_value.submit_order.return_value = mock_order
                
                client = AlpacaClient('paper')
                order = client.submit_order(
                    symbol='AAPL',
                    qty=100,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
                
                assert order.id == 'order_123'
                assert order.symbol == 'AAPL'


class TestFMPClient:
    """Test FMP Client class."""

    def test_init_with_api_key(self):
        """Test FMPClient initialization with API key."""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            assert client is not None

    def test_init_without_api_key(self):
        """Test FMPClient initialization with missing API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="FMP_API_KEY not found"):
                get_fmp_client()

    @patch('requests.Session.get')
    def test_get_historical_price_data_success(self, mock_get):
        """Test successful historical price data retrieval."""
        # Mock successful response
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
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            result = client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
            
            assert result is not None
            assert len(result) == 1
            assert result[0]['symbol'] == 'AAPL'
            assert result[0]['close'] == 194.50

    @patch('requests.Session.get')
    def test_get_historical_price_data_error(self, mock_get):
        """Test historical price data retrieval with API error."""
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            result = client.get_historical_price_data('INVALID', '2023-12-01', '2023-12-01')
            
            assert result is None

    @patch('requests.Session.get')
    def test_get_market_cap_data(self, mock_get):
        """Test market cap data retrieval."""
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
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            result = client.get_market_cap_data(['AAPL'])
            
            assert result is not None
            assert 'AAPL' in result
            assert result['AAPL']['marketCap'] == 3000000000000

    @patch('requests.Session.get')
    def test_get_mid_small_cap_symbols(self, mock_get):
        """Test mid/small cap symbols retrieval."""
        # Mock S&P 400 and S&P 600 responses
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
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            result = client.get_mid_small_cap_symbols()
            
            assert result is not None
            assert len(result) == 4
            assert 'ABC' in result
            assert 'GHI' in result

    @patch('requests.Session.get')
    def test_retry_mechanism(self, mock_get):
        """Test FMP client retry mechanism."""
        # Mock responses: first fails, second succeeds
        mock_responses = [
            Mock(status_code=500, raise_for_status=Mock(side_effect=requests.exceptions.HTTPError())),
            Mock(status_code=200, json=lambda: [{"symbol": "AAPL", "close": 190.50}])
        ]
        mock_get.side_effect = mock_responses
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client(max_retries=2, retry_delay=0.1)
            result = client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
            
            assert result is not None
            assert len(result) == 1
            assert result[0]['symbol'] == 'AAPL'


class TestFinvizClient:
    """Test FinvizClient class."""

    def test_init(self):
        """Test FinvizClient initialization."""
        client = FinvizClient()
        assert client is not None

    def test_build_screener_url(self):
        """Test screener URL building."""
        client = FinvizClient()
        url = client.build_screener_url(
            filters=['cap_midover'],
            columns=['ticker', 'price'],
            order='-volume'
        )
        
        assert 'finviz.com' in url
        assert 'cap_midover' in url
        assert 'ticker' in url
        assert 'o=-volume' in url

    @patch('pandas.read_html')
    @patch('requests.Session.get')
    def test_get_screener_data_success(self, mock_get, mock_read_html):
        """Test successful screener data retrieval."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<table><tr><td>Test</td></tr></table>"
        mock_get.return_value = mock_response
        
        # Mock pandas read_html
        mock_read_html.return_value = [pd.DataFrame({
            'Ticker': ['AAPL', 'MSFT'],
            'Price': ['190.50', '370.00'],
            'Volume': ['50M', '30M']
        })]
        
        client = FinvizClient()
        result = client.get_screener_data('test_url')
        
        assert result is not None
        assert len(result) == 2
        assert 'AAPL' in result['Ticker'].values

    @patch('requests.Session.get')
    def test_get_screener_data_error(self, mock_get):
        """Test screener data retrieval with HTTP error."""
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        mock_get.return_value = mock_response
        
        client = FinvizClient()
        result = client.get_screener_data('invalid_url')
        
        assert result is None


class TestClientFactories:
    """Test client factory functions."""

    def test_get_alpaca_client_singleton(self, mock_env_vars):
        """Test that get_alpaca_client returns singleton instances."""
        with patch.dict(os.environ, mock_env_vars):
            with patch('alpaca_trade_api.REST'):
                client1 = get_alpaca_client('paper')
                client2 = get_alpaca_client('paper')
                assert client1 is client2

    def test_get_fmp_client_singleton(self):
        """Test that get_fmp_client returns singleton instances."""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client1 = get_fmp_client()
            client2 = get_fmp_client()
            assert client1 is client2

    def test_get_finviz_client_singleton(self):
        """Test that get_finviz_client returns singleton instances."""
        client1 = get_finviz_client()
        client2 = get_finviz_client()
        assert client1 is client2

    def test_different_alpaca_accounts(self, mock_env_vars):
        """Test that different Alpaca account types return different instances."""
        with patch.dict(os.environ, mock_env_vars):
            with patch('alpaca_trade_api.REST'):
                paper_client = get_alpaca_client('paper')
                live_client = get_alpaca_client('live')
                assert paper_client is not live_client


@pytest.fixture
def mock_env_vars():
    """Fixture to provide mock environment variables."""
    return {
        'FMP_API_KEY': 'test_fmp_key',
        'ALPACA_API_KEY': 'test_alpaca_key',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret',
        'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets'
    }