"""Integration tests for API clients."""

import pytest
import pandas as pd
from unittest.mock import patch
import requests
import time

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from api_clients import AlpacaClient, EODHDClient, FinvizClient


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
    def test_eodhd_client_initialization(self, mock_env_vars):
        """Test that EODHDClient can be initialized properly."""
        client = EODHDClient()
        assert client is not None
        assert client.api_key == 'test_eodhd_key'
        assert client.base_url == 'https://eodhd.com/api'

    @pytest.mark.integration
    def test_finviz_client_initialization(self, mock_env_vars):
        """Test that FinvizClient can be initialized properly."""
        client = FinvizClient()
        assert client is not None
        assert client.api_key == 'test_finviz_key'
        assert client.base_url == 'https://elite.finviz.com'

    @pytest.mark.integration
    @patch('requests.get')
    def test_eodhd_api_call_flow(self, mock_get, mock_env_vars):
        """Test the complete flow of an EODHD API call."""
        # Mock successful response
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'General': {'Code': 'AAPL', 'Name': 'Apple Inc.'},
            'Highlights': {'MarketCapitalization': 2500000000000}
        }

        client = EODHDClient()
        result = client.get_fundamentals('AAPL')
        
        assert result is not None
        assert 'General' in result
        mock_get.assert_called_once()
        
        # Verify the request was made with correct parameters
        call_args = mock_get.call_args
        assert 'eodhd.com' in call_args[0][0]
        assert call_args[1]['params']['api_token'] == 'test_eodhd_key'

    @pytest.mark.integration
    @patch('requests.get')
    def test_eodhd_retry_mechanism(self, mock_get, mock_env_vars):
        """Test EODHD client retry mechanism."""
        # First call returns 429, second call succeeds
        mock_responses = [
            type('MockResponse', (), {'status_code': 429}),
            type('MockResponse', (), {
                'status_code': 200,
                'json': lambda: {'status': 'success'}
            })
        ]
        mock_get.side_effect = mock_responses

        with patch('time.sleep'):  # Mock sleep to speed up test
            client = EODHDClient(max_retries=2, retry_delay=0.1)
            result = client.get_fundamentals('AAPL')
            
            assert result == {'status': 'success'}
            assert mock_get.call_count == 2

    @pytest.mark.integration
    @patch('requests.get')
    def test_finviz_screener_flow(self, mock_get, mock_env_vars):
        """Test the complete flow of a Finviz screener call."""
        # Mock CSV response
        csv_data = """Ticker,Company,Price,Change,Volume
AAPL,Apple Inc.,150.00,0.02,50000000
GOOGL,Alphabet Inc.,2500.00,-0.01,1500000
MSFT,Microsoft Corporation,300.00,0.01,25000000"""
        
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.content = csv_data.encode('utf-8')

        client = FinvizClient()
        
        filters = {'cap': 'smallover', 'sh_price': 'o10'}
        columns = '0,1,2,3,4'
        url = client.build_screener_url(filters, columns)
        
        result = client.get_screener_data(url)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert 'Ticker' in result.columns
        assert 'AAPL' in result['Ticker'].values
        
        mock_get.assert_called_once_with(url, timeout=30)

    @pytest.mark.integration
    @patch('requests.get')
    def test_finviz_retry_on_rate_limit(self, mock_get, mock_env_vars):
        """Test Finviz client handles rate limits with retry."""
        csv_data = "Ticker,Price\nAAPL,150.00"
        
        # First call returns 429, second call succeeds
        mock_responses = [
            type('MockResponse', (), {'status_code': 429}),
            type('MockResponse', (), {
                'status_code': 200,
                'content': csv_data.encode('utf-8')
            })
        ]
        mock_get.side_effect = mock_responses

        with patch('time.sleep'):  # Mock sleep to speed up test
            client = FinvizClient(max_retries=2, retry_delay=0.1)
            result = client.get_stock_count('test_url')
            
            assert result == 1  # One stock in the CSV
            assert mock_get.call_count == 2

    @pytest.mark.integration
    @patch('alpaca_trade_api.REST')
    def test_alpaca_account_integration(self, mock_rest, mock_env_vars):
        """Test Alpaca client account integration."""
        # Mock the REST API
        mock_api = mock_rest.return_value
        mock_account = type('MockAccount', (), {
            'id': 'test_account_id',
            'equity': '100000.00',
            'buying_power': '50000.00',
            'status': 'ACTIVE'
        })
        mock_api.get_account.return_value = mock_account

        client = AlpacaClient('paper')
        account = client.get_account()
        
        assert account.id == 'test_account_id'
        assert account.equity == '100000.00'
        assert account.buying_power == '50000.00'
        mock_api.get_account.assert_called_once()

    @pytest.mark.integration
    @patch('alpaca_trade_api.REST')
    def test_alpaca_order_submission_flow(self, mock_rest, mock_env_vars):
        """Test Alpaca order submission integration."""
        # Mock the REST API
        mock_api = mock_rest.return_value
        mock_order = type('MockOrder', (), {
            'id': 'test_order_id',
            'symbol': 'AAPL',
            'qty': '100',
            'side': 'buy',
            'status': 'accepted'
        })
        mock_api.submit_order.return_value = mock_order

        client = AlpacaClient('paper')
        order = client.submit_order('AAPL', 100, 'buy')
        
        assert order.id == 'test_order_id'
        assert order.symbol == 'AAPL'
        assert order.qty == '100'
        
        mock_api.submit_order.assert_called_once_with(
            symbol='AAPL',
            qty=100,
            side='buy', 
            type='market',
            time_in_force='day'
        )

    @pytest.mark.integration
    def test_client_singleton_behavior(self, mock_env_vars):
        """Test that singleton functions return the same instances."""
        from api_clients import get_alpaca_client, get_eodhd_client, get_finviz_client
        
        with patch('alpaca_trade_api.REST'):
            # Test Alpaca client singleton
            client1 = get_alpaca_client('live')
            client2 = get_alpaca_client('live') 
            assert client1 is client2
            
            # Different account types should be different instances
            paper_client = get_alpaca_client('paper')
            assert client1 is not paper_client
        
        # Test EODHD client singleton
        eodhd1 = get_eodhd_client()
        eodhd2 = get_eodhd_client()
        assert eodhd1 is eodhd2
        
        # Test Finviz client singleton
        finviz1 = get_finviz_client()
        finviz2 = get_finviz_client()
        assert finviz1 is finviz2

    @pytest.mark.integration
    @patch('requests.get')
    def test_error_handling_across_clients(self, mock_get, mock_env_vars):
        """Test error handling across different clients."""
        # Test network error handling
        mock_get.side_effect = requests.exceptions.ConnectionError("Network error")
        
        # EODHD client should handle network errors
        client = EODHDClient(max_retries=1)
        with pytest.raises(requests.exceptions.ConnectionError):
            client.get_fundamentals('AAPL')
        
        # Finviz client should handle network errors
        finviz_client = FinvizClient(max_retries=1)
        result = finviz_client.get_stock_count('test_url')
        assert result == 0  # Should return 0 on error

    @pytest.mark.integration
    @patch('requests.get')  
    def test_finviz_news_integration(self, mock_get, mock_env_vars):
        """Test Finviz news data integration."""
        csv_data = """Date,Title,Link,Ticker
2023-01-01,Apple releases new iPhone,http://example.com,AAPL
2023-01-02,Google announces AI breakthrough,http://example.com,GOOGL"""
        
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.content = csv_data.encode('utf-8')

        client = FinvizClient()
        result = client.get_news_data(['AAPL', 'GOOGL'], '2023-01-01', '2023-01-02')
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert 'Date' in result.columns
        assert 'Title' in result.columns
        assert 'Ticker' in result.columns

    @pytest.mark.integration
    def test_configuration_validation(self, mock_env_vars):
        """Test that all clients validate their configuration properly."""
        # Test missing API keys
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="EODHD_API_KEY"):
                EODHDClient()
            
            with pytest.raises(ValueError, match="FINVIZ_API_KEY"):
                FinvizClient()
            
            with pytest.raises(ValueError, match="API keys not found"):
                AlpacaClient('live')