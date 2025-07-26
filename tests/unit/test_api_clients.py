"""Unit tests for API clients."""

import pytest
import pandas as pd
import os
from unittest.mock import Mock, patch, MagicMock
import requests
from datetime import datetime

from api_clients import AlpacaClient, EODHDClient, FinvizClient
from api_clients import get_alpaca_client, get_eodhd_client, get_finviz_client


class TestAlpacaClient:
    """Test AlpacaClient class."""

    def test_init_live_account(self, mock_env_vars):
        """Test AlpacaClient initialization for live account."""
        with patch('alpaca_trade_api.REST') as mock_rest:
            client = AlpacaClient('live')
            assert client.account_type == 'live'
            mock_rest.assert_called_once()

    def test_init_paper_account(self, mock_env_vars):
        """Test AlpacaClient initialization for paper account."""
        with patch('alpaca_trade_api.REST') as mock_rest:
            client = AlpacaClient('paper')
            assert client.account_type == 'paper'
            mock_rest.assert_called_once()

    def test_init_missing_keys(self):
        """Test AlpacaClient initialization with missing API keys."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="API keys not found"):
                AlpacaClient('live')

    def test_get_account(self, mock_env_vars, mock_alpaca_api):
        """Test get_account method."""
        with patch('alpaca_trade_api.REST', return_value=mock_alpaca_api):
            client = AlpacaClient('live')
            account = client.get_account()
            assert account is not None
            mock_alpaca_api.get_account.assert_called_once()

    def test_get_positions(self, mock_env_vars, mock_alpaca_api):
        """Test get_positions method."""
        with patch('alpaca_trade_api.REST', return_value=mock_alpaca_api):
            client = AlpacaClient('live')
            positions = client.get_positions()
            assert positions == []
            mock_alpaca_api.list_positions.assert_called_once()

    def test_submit_order(self, mock_env_vars, mock_alpaca_api):
        """Test submit_order method."""
        with patch('alpaca_trade_api.REST', return_value=mock_alpaca_api):
            client = AlpacaClient('live')
            mock_alpaca_api.submit_order.return_value = Mock(id='test_order_id')
            
            order = client.submit_order('AAPL', 100, 'buy')
            assert order.id == 'test_order_id'
            mock_alpaca_api.submit_order.assert_called_once_with(
                symbol='AAPL', qty=100, side='buy', type='market', time_in_force='day'
            )


class TestEODHDClient:
    """Test EODHDClient class."""

    def test_init(self, mock_env_vars):
        """Test EODHDClient initialization."""
        client = EODHDClient()
        assert client.api_key == 'test_eodhd_key'
        assert client.base_url == 'https://eodhd.com/api'
        assert client.max_retries == 3
        assert client.retry_delay == 1.0

    def test_init_missing_key(self):
        """Test EODHDClient initialization with missing API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="EODHD_API_KEY not found"):
                EODHDClient()

    @patch('requests.get')
    def test_make_request_success(self, mock_get, mock_env_vars):
        """Test successful API request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_get.return_value = mock_response

        client = EODHDClient()
        result = client._make_request('test_endpoint')
        
        assert result == {'status': 'success'}
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_make_request_retry(self, mock_get, mock_env_vars):
        """Test API request with retry logic."""
        # First call returns 429, second call succeeds
        mock_response_fail = Mock()
        mock_response_fail.status_code = 429
        
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {'status': 'success'}
        
        mock_get.side_effect = [mock_response_fail, mock_response_success]

        with patch('time.sleep'):  # Mock sleep to speed up test
            client = EODHDClient()
            result = client._make_request('test_endpoint')
            
        assert result == {'status': 'success'}
        assert mock_get.call_count == 2

    def test_get_fundamentals(self, mock_env_vars):
        """Test get_fundamentals method."""
        with patch.object(EODHDClient, '_make_request') as mock_request:
            mock_request.return_value = {'symbol': 'AAPL', 'sector': 'Technology'}
            
            client = EODHDClient()
            result = client.get_fundamentals('AAPL')
            
            assert result['symbol'] == 'AAPL'
            mock_request.assert_called_once_with('fundamentals/AAPL')


class TestFinvizClient:
    """Test FinvizClient class."""

    def test_init(self, mock_env_vars):
        """Test FinvizClient initialization."""
        client = FinvizClient()
        assert client.api_key == 'test_finviz_key'
        assert client.base_url == 'https://elite.finviz.com'
        assert client.max_retries == 5
        assert client.retry_delay == 1.0

    def test_init_missing_key(self):
        """Test FinvizClient initialization with missing API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="FINVIZ_API_KEY not found"):
                FinvizClient()

    @patch('requests.get')
    def test_make_request_success(self, mock_get, mock_env_vars):
        """Test successful Finviz API request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'Ticker,Price,Change\nAAPL,150.0,0.02\nGOOGL,2500.0,-0.01'
        mock_get.return_value = mock_response

        client = FinvizClient()
        result = client._make_request('test_url')
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert 'Ticker' in result.columns
        mock_get.assert_called_once_with('test_url', timeout=30)

    def test_get_stock_count(self, mock_env_vars):
        """Test get_stock_count method."""
        with patch.object(FinvizClient, '_make_request') as mock_request:
            mock_df = pd.DataFrame({'Ticker': ['AAPL', 'GOOGL', 'MSFT']})
            mock_request.return_value = mock_df
            
            client = FinvizClient()
            count = client.get_stock_count('test_url')
            
            assert count == 3
            mock_request.assert_called_once_with('test_url')

    def test_get_stock_count_error(self, mock_env_vars):
        """Test get_stock_count method with error."""
        with patch.object(FinvizClient, '_make_request') as mock_request:
            mock_request.side_effect = Exception('API Error')
            
            client = FinvizClient()
            count = client.get_stock_count('test_url')
            
            assert count == 0

    def test_build_screener_url(self, mock_env_vars):
        """Test build_screener_url method."""
        client = FinvizClient()
        
        filters = {'cap': 'smallover', 'sh_price': 'o10'}
        columns = '0,1,2,3'
        order = '-epssurprise'
        
        url = client.build_screener_url(filters, columns, order)
        
        assert 'elite.finviz.com/export.ashx' in url
        assert 'cap_smallover' in url
        assert 'sh_price_o10' in url
        assert 'o=-epssurprise' in url
        assert 'c=0,1,2,3' in url
        assert f'auth={client.api_key}' in url

    def test_get_uptrend_screener_url(self, mock_env_vars):
        """Test get_uptrend_screener_url method."""
        client = FinvizClient()
        
        url = client.get_uptrend_screener_url('sec_technology')
        
        assert 'elite.finviz.com/export.ashx' in url
        assert 'sec_technology' in url
        assert 'ta_sma20_pa' in url
        assert 'ta_sma200_pa' in url

    def test_get_total_screener_url(self, mock_env_vars):
        """Test get_total_screener_url method."""
        client = FinvizClient()
        
        url = client.get_total_screener_url('sec_technology')
        
        assert 'elite.finviz.com/export.ashx' in url
        assert 'sec_technology' in url
        assert 'cap_microover' in url

    def test_get_news_data(self, mock_env_vars):
        """Test get_news_data method."""
        with patch.object(FinvizClient, '_make_request') as mock_request:
            mock_df = pd.DataFrame({
                'Date': ['2023-01-01', '2023-01-02'],
                'Title': ['News 1', 'News 2'],
                'Ticker': ['AAPL', 'GOOGL']
            })
            mock_request.return_value = mock_df
            
            client = FinvizClient()
            result = client.get_news_data(['AAPL', 'GOOGL'], '2023-01-01', '2023-01-02')
            
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 2
            mock_request.assert_called_once()


class TestSingletonFunctions:
    """Test singleton functions."""

    def test_get_alpaca_client_singleton(self, mock_env_vars):
        """Test that get_alpaca_client returns the same instance."""
        with patch('alpaca_trade_api.REST'):
            client1 = get_alpaca_client('live')
            client2 = get_alpaca_client('live')
            assert client1 is client2

    def test_get_alpaca_client_different_accounts(self, mock_env_vars):
        """Test that different account types return different instances."""
        with patch('alpaca_trade_api.REST'):
            live_client = get_alpaca_client('live')
            paper_client = get_alpaca_client('paper')
            assert live_client is not paper_client

    def test_get_eodhd_client_singleton(self, mock_env_vars):
        """Test that get_eodhd_client returns the same instance."""
        client1 = get_eodhd_client()
        client2 = get_eodhd_client()
        assert client1 is client2

    def test_get_finviz_client_singleton(self, mock_env_vars):
        """Test that get_finviz_client returns the same instance."""
        client1 = get_finviz_client()
        client2 = get_finviz_client()
        assert client1 is client2