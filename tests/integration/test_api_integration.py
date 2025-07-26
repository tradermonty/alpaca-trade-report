"""Integration tests for API clients."""

import pytest
import pandas as pd
from unittest.mock import patch, Mock
import requests
import time

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from api_clients import AlpacaClient, get_fmp_client, FinvizClient


class TestAPIIntegration:
    """Integration tests for API clients with external services."""

    @pytest.mark.integration
    def test_alpaca_client_initialization(self, mock_env_vars):
        """Test that AlpacaClient can be initialized properly."""
        with patch('alpaca_trade_api.REST') as mock_rest:
            client = AlpacaClient('paper')
            assert client is not None
            assert client.account_type == 'paper'
            mock_rest.assert_called_once()

    @pytest.mark.integration
    def test_fmp_client_initialization(self):
        """Test that FMP client can be initialized properly."""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            assert client is not None

    @pytest.mark.integration
    @patch('requests.Session.get')
    def test_fmp_historical_data_flow(self, mock_get):
        """Test the complete flow of an FMP API call."""
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

    @pytest.mark.integration
    @patch('requests.Session.get')
    def test_fmp_client_retry_mechanism(self, mock_get):
        """Test FMP client retry mechanism."""
        # Mock responses: first two fail, third succeeds
        mock_responses = [
            Mock(status_code=500, raise_for_status=Mock(side_effect=requests.exceptions.HTTPError())),
            Mock(status_code=429, raise_for_status=Mock(side_effect=requests.exceptions.HTTPError())),
            Mock(status_code=200, json=lambda: [{"symbol": "AAPL", "close": 190.50}])
        ]
        mock_get.side_effect = mock_responses
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client(max_retries=2, retry_delay=0.1)
            result = client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
            
            # Should succeed on third attempt
            assert result is not None
            assert len(result) == 1
            assert result[0]['symbol'] == 'AAPL'

    @pytest.mark.integration
    @patch('requests.Session.get')
    def test_fmp_market_cap_data(self, mock_get):
        """Test FMP market cap data retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "symbol": "AAPL",
                "marketCap": 3000000000000,
                "price": 190.50
            },
            {
                "symbol": "MSFT", 
                "marketCap": 2800000000000,
                "price": 370.00
            }
        ]
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client()
            result = client.get_market_cap_data(['AAPL', 'MSFT'])
            
            assert result is not None
            assert 'AAPL' in result
            assert 'MSFT' in result
            assert result['AAPL']['marketCap'] == 3000000000000

    @pytest.mark.integration
    @patch('requests.Session.get')
    def test_fmp_mid_small_cap_symbols(self, mock_get):
        """Test FMP mid/small cap symbols retrieval."""
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

    @pytest.mark.integration
    def test_finviz_client_initialization(self):
        """Test Finviz client initialization."""
        client = FinvizClient()
        assert client is not None

    @pytest.mark.integration
    @patch('pandas.read_html')
    @patch('requests.Session.get')
    def test_finviz_screener_integration(self, mock_get, mock_read_html):
        """Test Finviz screener integration."""
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
        url = client.build_screener_url(
            filters=['cap_midover'],
            columns=['ticker', 'price'],
            order='-volume'
        )
        
        result = client.get_screener_data(url)
        
        assert result is not None
        assert len(result) == 2
        assert 'AAPL' in result['Ticker'].values

    @pytest.mark.integration
    def test_client_singletons(self):
        """Test that client factory functions work correctly."""
        from api_clients import get_alpaca_client, get_fmp_client, get_finviz_client
        
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret',
        }):
            # Test Alpaca client singleton
            alpaca1 = get_alpaca_client('paper')
            alpaca2 = get_alpaca_client('paper')
            assert alpaca1 is alpaca2
            
            # Test FMP client
            fmp_client = get_fmp_client()
            assert fmp_client is not None
            
            # Test Finviz client
            finviz_client = get_finviz_client()
            assert finviz_client is not None

    @pytest.mark.integration
    @patch('requests.Session.get')
    def test_error_handling_across_clients(self, mock_get):
        """Test error handling consistency across different API clients."""
        # Mock network error
        mock_get.side_effect = requests.exceptions.ConnectionError()
        
        # FMP client should handle network errors
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            client = get_fmp_client(max_retries=1)
            result = client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
            assert result is None

    @pytest.mark.integration
    def test_rate_limiting_behavior(self):
        """Test rate limiting behavior across clients."""
        # This would be a more complex test in a real scenario
        # For now, just test that clients can be created without rate limit issues
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            clients = [get_fmp_client() for _ in range(5)]
            assert len(clients) == 5
            # All should be the same instance due to singleton pattern
            assert all(client is clients[0] for client in clients[1:])

    @pytest.mark.integration
    def test_missing_api_keys_handling(self):
        """Test handling of missing API keys."""
        # Clear environment variables
        with patch.dict(os.environ, {}, clear=True):
            # FMP client should raise ValueError for missing key
            with pytest.raises(ValueError, match="FMP_API_KEY"):
                get_fmp_client()

    @pytest.mark.integration
    @patch('requests.Session.get')
    def test_data_consistency_across_apis(self, mock_get):
        """Test data format consistency across different API sources."""
        # Mock FMP response
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
        
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_key'}):
            fmp_client = get_fmp_client()
            
            # Test that data format is consistent
            price_data = fmp_client.get_historical_price_data('AAPL', '2023-12-01', '2023-12-01')
            
            assert isinstance(price_data, list)
            assert len(price_data) > 0
            assert 'symbol' in price_data[0]
            assert 'close' in price_data[0]
            assert isinstance(price_data[0]['close'], (int, float))


@pytest.fixture
def mock_env_vars():
    """Fixture to provide mock environment variables."""
    return {
        'FMP_API_KEY': 'test_fmp_key',
        'ALPACA_API_KEY': 'test_alpaca_key',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret',
        'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets'
    }


if __name__ == '__main__':
    pytest.main([__file__])