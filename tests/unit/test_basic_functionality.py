"""Basic functionality tests for implemented features only."""

import pytest
import os
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class TestBasicFunctionality:
    """Test basic functionality that actually exists."""

    def test_import_main_modules(self, mock_env_vars):
        """Test that main modules can be imported without errors."""
        try:
            import earnings_swing
            import api_clients
            import uptrend_stocks
            assert True  # If we reach here, imports succeeded
        except ImportError as e:
            pytest.fail(f"Failed to import modules: {e}")

    def test_api_clients_creation(self, mock_env_vars):
        """Test that API clients can be created."""
        from api_clients import get_alpaca_client, get_eodhd_client, get_finviz_client
        
        with patch('alpaca_trade_api.REST'):
            alpaca_client = get_alpaca_client('paper')
            assert alpaca_client is not None
            
        eodhd_client = get_eodhd_client()
        assert eodhd_client is not None
        
        finviz_client = get_finviz_client()
        assert finviz_client is not None

    def test_finviz_client_url_building(self, mock_env_vars):
        """Test FinvizClient URL building functionality."""
        from api_clients import get_finviz_client
        
        client = get_finviz_client()
        
        # Test basic URL building
        filters = {'cap': 'smallover', 'sh_price': 'o10'}
        url = client.build_screener_url(filters)
        
        assert 'elite.finviz.com/export.ashx' in url
        assert 'cap_smallover' in url
        assert 'sh_price_o10' in url

    def test_earnings_swing_constants(self, mock_env_vars):
        """Test that earnings swing module has expected constants."""
        import earnings_swing
        
        assert hasattr(earnings_swing, 'NUMBER_OF_STOCKS')
        assert hasattr(earnings_swing, 'EARNINGS_FILTERS')
        assert hasattr(earnings_swing, 'EARNINGS_COLUMNS')
        assert hasattr(earnings_swing, 'TZ_NY')

    def test_uptrend_stocks_constants(self, mock_env_vars):
        """Test that uptrend stocks module has expected constants."""
        import uptrend_stocks
        
        assert hasattr(uptrend_stocks, 'TZ_NY')
        assert hasattr(uptrend_stocks, 'TZ_UTC')
        assert hasattr(uptrend_stocks, 'COL_COUNT')
        assert hasattr(uptrend_stocks, 'COL_RATIO')

    @patch('requests.get')
    def test_finviz_client_error_handling(self, mock_get, mock_env_vars):
        """Test that FinvizClient handles errors gracefully."""
        from api_clients import get_finviz_client
        
        # Mock a network error
        mock_get.side_effect = Exception("Network error")
        
        client = get_finviz_client()
        result = client.get_stock_count('https://example.com/test')
        
        # Should return 0 on error, not crash
        assert result == 0

    def test_module_attributes_exist(self, mock_env_vars):
        """Test that expected attributes exist in modules."""
        import earnings_swing
        import uptrend_stocks
        
        # Test earnings_swing attributes
        assert isinstance(earnings_swing.NUMBER_OF_STOCKS, int)
        assert isinstance(earnings_swing.EARNINGS_FILTERS, dict)
        assert isinstance(earnings_swing.EARNINGS_COLUMNS, list)
        
        # Test uptrend_stocks attributes
        assert isinstance(uptrend_stocks.COL_COUNT, str)
        assert isinstance(uptrend_stocks.COL_RATIO, str)

    def test_timezone_configuration(self, mock_env_vars):
        """Test timezone configuration across modules."""
        import earnings_swing
        import uptrend_stocks
        from zoneinfo import ZoneInfo
        
        # Both modules should use the same timezone
        assert earnings_swing.TZ_NY == ZoneInfo("US/Eastern")
        assert uptrend_stocks.TZ_NY == ZoneInfo("US/Eastern")
        assert earnings_swing.TZ_NY == uptrend_stocks.TZ_NY

    def test_client_singleton_behavior(self, mock_env_vars):
        """Test that client singletons work correctly."""
        from api_clients import get_finviz_client, get_eodhd_client
        
        # Test Finviz client singleton
        client1 = get_finviz_client()
        client2 = get_finviz_client()
        assert client1 is client2
        
        # Test EODHD client singleton
        eodhd1 = get_eodhd_client()
        eodhd2 = get_eodhd_client()
        assert eodhd1 is eodhd2

    def test_environment_variable_handling(self, mock_env_vars):
        """Test that environment variables are handled correctly."""
        from api_clients import FinvizClient, EODHDClient
        
        # These should work with mocked environment variables
        finviz_client = FinvizClient()
        assert finviz_client.api_key == 'test_finviz_key'
        
        eodhd_client = EODHDClient()
        assert eodhd_client.api_key == 'test_eodhd_key'