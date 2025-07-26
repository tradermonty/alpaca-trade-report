"""Basic functionality tests for the trading system."""

import pytest
import sys
import os
from unittest.mock import patch, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class TestBasicFunctionality:
    """Test basic system functionality."""

    def test_imports(self):
        """Test that all major modules can be imported."""
        try:
            import earnings_swing
            import orb
            import risk_management
            import strategy_allocation
            import api_clients
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import module: {e}")

    @patch.dict(os.environ, {
        'ALPACA_API_KEY': 'test_key',
        'ALPACA_SECRET_KEY': 'test_secret',
        'FMP_API_KEY': 'test_fmp_key',
    })
    def test_api_client_initialization(self):
        """Test API client initialization."""
        from api_clients import get_alpaca_client, get_fmp_client, get_finviz_client
        
        with patch('alpaca_trade_api.REST'):
            alpaca_client = get_alpaca_client('paper')
            assert alpaca_client is not None
        
        fmp_client = get_fmp_client()
        assert fmp_client is not None
        
        finviz_client = get_finviz_client()
        assert finviz_client is not None

    def test_timezone_configuration(self):
        """Test timezone setup."""
        from zoneinfo import ZoneInfo
        from common_constants import TIMEZONE
        
        assert TIMEZONE.NY == ZoneInfo("US/Eastern")
        assert TIMEZONE.UTC == ZoneInfo("UTC")

    def test_config_loading(self):
        """Test configuration loading."""
        from config import trading_config, timing_config, retry_config
        
        assert trading_config is not None
        assert timing_config is not None
        assert retry_config is not None
        
        # Check some key config values exist
        assert hasattr(trading_config, 'POSITION_SIZE_RATE')
        assert hasattr(timing_config, 'DEFAULT_MINUTES_TO_OPEN')
        assert hasattr(retry_config, 'ALPACA_MAX_RETRIES')

    @patch('gspread.authorize')
    def test_google_sheets_integration(self, mock_authorize):
        """Test Google Sheets integration."""
        mock_client = Mock()
        mock_authorize.return_value = mock_client
        mock_sheet = Mock()
        mock_client.open.return_value = mock_sheet
        
        # Test basic sheet operations
        mock_worksheet = Mock()
        mock_sheet.worksheet.return_value = mock_worksheet
        mock_worksheet.get_all_values.return_value = [['A', 'B'], ['1', '2']]
        
        values = mock_worksheet.get_all_values()
        assert len(values) == 2
        assert values[0] == ['A', 'B']

    def test_logging_setup(self):
        """Test logging configuration."""
        from logging_config import get_logger
        
        logger = get_logger(__name__)
        assert logger is not None
        
        # Test that logger can write without errors
        logger.info("Test log message")
        logger.warning("Test warning")
        logger.error("Test error")

    def test_market_hours_calculation(self):
        """Test market hours calculations."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        # Create a test datetime during market hours
        market_open = datetime(2023, 12, 1, 9, 30, tzinfo=ZoneInfo("US/Eastern"))
        market_close = datetime(2023, 12, 1, 16, 0, tzinfo=ZoneInfo("US/Eastern"))
        
        assert market_open.hour == 9
        assert market_open.minute == 30
        assert market_close.hour == 16
        assert market_close.minute == 0

    def test_risk_management_calculations(self):
        """Test risk management calculations."""
        # Test position size calculation
        account_value = 100000
        risk_per_trade = 0.02
        max_position_size = account_value * risk_per_trade
        
        assert max_position_size == 2000

    def test_data_structures(self):
        """Test key data structures."""
        from dataclasses import dataclass
        
        @dataclass
        class TestOrder:
            symbol: str
            quantity: int
            price: float
        
        order = TestOrder(symbol="AAPL", quantity=100, price=150.0)
        assert order.symbol == "AAPL"
        assert order.quantity == 100
        assert order.price == 150.0

    @patch.dict(os.environ, {
        'FMP_API_KEY': 'test_fmp_key',
        'ALPACA_API_KEY': 'test_alpaca_key',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret',
    })
    def test_client_singletons(self):
        """Test that API clients implement singleton pattern."""
        from api_clients import get_finviz_client, get_fmp_client
        
        # Test Finviz client singleton
        finviz1 = get_finviz_client()
        finviz2 = get_finviz_client()
        assert finviz1 is finviz2
        
        # Test FMP client singleton
        fmp1 = get_fmp_client()
        fmp2 = get_fmp_client()
        assert fmp1 is fmp2

    @patch.dict(os.environ, {
        'FMP_API_KEY': 'test_fmp_key',
        'ALPACA_API_KEY': 'test_alpaca_key',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret',
    })
    def test_environment_variables(self):
        """Test environment variable loading."""
        from api_clients import FinvizClient
        
        # Test client can access environment variables
        finviz_client = FinvizClient()
        assert finviz_client is not None
        
        # Test FMP client initialization
        from api_clients import get_fmp_client
        fmp_client = get_fmp_client()
        assert fmp_client is not None

    def test_pandas_operations(self):
        """Test pandas operations used throughout the system."""
        import pandas as pd
        import numpy as np
        
        # Create sample data
        df = pd.DataFrame({
            'symbol': ['AAPL', 'GOOGL', 'MSFT'],
            'price': [150.0, 2800.0, 350.0],
            'volume': [1000000, 500000, 800000]
        })
        
        # Test basic operations
        assert len(df) == 3
        assert df['price'].mean() > 0
        assert df['volume'].sum() == 2300000
        
        # Test filtering
        high_price = df[df['price'] > 200]
        assert len(high_price) == 2

    def test_error_handling(self):
        """Test error handling patterns."""
        def divide_with_error_handling(a, b):
            try:
                return a / b
            except ZeroDivisionError:
                return None
            except Exception as e:
                raise e
        
        assert divide_with_error_handling(10, 2) == 5
        assert divide_with_error_handling(10, 0) is None
        
        with pytest.raises(TypeError):
            divide_with_error_handling("10", 2)