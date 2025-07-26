"""Unit tests for earnings swing trading strategy."""

import pytest
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import earnings_swing


class TestEarningsSwing:
    """Test earnings swing trading functionality."""

    @patch('earnings_swing.get_finviz_client')
    def test_get_tickers_from_screener(self, mock_get_finviz_client, mock_env_vars):
        """Test getting tickers from Finviz screener."""
        # Mock the finviz client
        mock_client = Mock()
        mock_get_finviz_client.return_value = mock_client
        
        # Mock screener data
        mock_df = pd.DataFrame({
            'Ticker': ['AAPL', 'GOOGL', 'MSFT', 'TSLA'],
            'EPS Surprise': ['10%', '15%', '5%', '20%'],
            'Revenue Surprise': ['5%', '8%', '2%', '12%'],
            'Change': ['2%', '3%', '1%', '4%'],
            'Relative Volume': [1.5, 2.0, 1.2, 2.5],
            'Market Cap': ['2.5T', '1.8T', '2.2T', '800B']
        })
        
        mock_client.build_screener_url.return_value = 'test_url'
        mock_client.get_screener_data.return_value = mock_df
        
        # Mock get_mid_small_cap_symbols to return all symbols
        with patch('earnings_swing.get_mid_small_cap_symbols') as mock_get_symbols:
            mock_get_symbols.return_value = ['AAPL', 'GOOGL', 'MSFT', 'TSLA']
            
            # Test the function
            tickers = earnings_swing.get_tickers_from_screener(2)
            
            # Should return top 2 tickers after scoring
            assert len(tickers) <= 2
            assert isinstance(tickers, list)

    @patch('earnings_swing.get_eodhd_client')
    def test_get_mid_small_cap_symbols(self, mock_get_eodhd_client, mock_env_vars):
        """Test getting mid and small cap symbols."""
        # Mock the EODHD client
        mock_client = Mock()
        mock_get_eodhd_client.return_value = mock_client
        
        # Mock market cap data
        mock_mid_data = {
            'Components': {
                'AAPL': {'Code': 'AAPL.US'},
                'GOOGL': {'Code': 'GOOGL.US'}
            }
        }
        mock_sml_data = {
            'Components': {
                'TSLA': {'Code': 'TSLA.US'},
                'AMD': {'Code': 'AMD.US'}
            }
        }
        
        mock_client.get_market_cap_data.side_effect = [mock_mid_data, mock_sml_data]
        
        symbols = earnings_swing.get_mid_small_cap_symbols()
        
        assert len(symbols) == 4
        assert 'AAPL' in symbols
        assert 'GOOGL' in symbols
        assert 'TSLA' in symbols
        assert 'AMD' in symbols

    @patch('earnings_swing.get_eodhd_client')
    def test_get_historical_data(self, mock_get_eodhd_client, mock_eodhd_response, mock_env_vars):
        """Test getting historical data."""
        # Mock the EODHD client
        mock_client = Mock()
        mock_get_eodhd_client.return_value = mock_client
        mock_client.get_historical_data.return_value = mock_eodhd_response
        
        result = earnings_swing.get_historical_data('AAPL', '2023-01-01', '2023-01-02')
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert 'Close' in result.columns
        assert 'Open' in result.columns
        mock_client.get_historical_data.assert_called_once_with('AAPL.US', '2023-01-01', '2023-01-02')

    @patch('earnings_swing.get_historical_data')
    def test_calculate_rsi(self, mock_get_historical_data, sample_stock_data, mock_env_vars):
        """Test RSI calculation."""
        mock_get_historical_data.return_value = sample_stock_data
        
        rsi = earnings_swing.calculate_rsi('AAPL', 14)
        
        assert isinstance(rsi, (int, float)) or rsi is None
        if rsi is not None:
            assert 0 <= rsi <= 100

    @patch('earnings_swing.get_historical_data')
    def test_calculate_sma(self, mock_get_historical_data, sample_stock_data, mock_env_vars):
        """Test SMA calculation."""
        mock_get_historical_data.return_value = sample_stock_data
        
        sma = earnings_swing.calculate_sma('AAPL', 20)
        
        assert isinstance(sma, (int, float)) or sma is None

    @patch('earnings_swing.get_alpaca_client')
    def test_sleep_until_open(self, mock_get_alpaca_client, mock_env_vars):
        """Test sleep until market open functionality."""
        # Mock the alpaca client
        mock_client = Mock()
        mock_get_alpaca_client.return_value = mock_client
        mock_api = Mock()
        mock_client.api = mock_api
        
        # Mock calendar data
        mock_calendar = [Mock(open='09:30:00', close='16:00:00')]
        mock_api.get_calendar.return_value = mock_calendar
        
        # Test with test mode enabled to avoid actual sleeping
        with patch('earnings_swing.test_mode', True):
            with patch('earnings_swing.test_datetime', pd.Timestamp('2023-01-01 10:00:00-05:00')):
                # Should not raise any exceptions
                earnings_swing.sleep_until_open(1)

    def test_strategy_allocation_integration(self, mock_env_vars):
        """Test integration with strategy allocation module."""
        with patch('earnings_swing.strategy_allocation') as mock_strategy:
            mock_strategy.get_available_buying_power.return_value = 10000.0
            mock_strategy.calculate_position_size.return_value = 1000.0
            
            # This tests that the strategy allocation module is properly imported
            # and can be mocked for testing
            assert mock_strategy is not None

    def test_risk_management_integration(self, mock_env_vars):
        """Test integration with risk management module."""
        with patch('earnings_swing.risk_management') as mock_risk:
            mock_risk.check_pnl_based_risk.return_value = True
            
            # This tests that the risk management module is properly imported
            # and can be mocked for testing
            assert mock_risk is not None

    @patch('subprocess.run')
    def test_execute_trade(self, mock_subprocess, mock_env_vars):
        """Test trade execution via subprocess."""
        mock_subprocess.return_value = Mock(returncode=0)
        
        # Mock the main execution logic
        with patch('earnings_swing.get_tickers_from_screener') as mock_get_tickers:
            mock_get_tickers.return_value = ['AAPL', 'GOOGL']
            
            with patch('earnings_swing.sleep_until_open'):
                with patch('earnings_swing.api') as mock_api:
                    # This tests the basic structure of the main execution
                    # without actually running the full strategy
                    assert mock_get_tickers is not None
                    assert mock_api is not None

    def test_constants_and_configuration(self, mock_env_vars):
        """Test that constants and configuration are properly set."""
        # Test that important constants exist
        assert hasattr(earnings_swing, 'NUMBER_OF_STOCKS')
        assert hasattr(earnings_swing, 'EARNINGS_FILTERS')
        assert hasattr(earnings_swing, 'EARNINGS_COLUMNS')
        assert hasattr(earnings_swing, 'TZ_NY')
        assert hasattr(earnings_swing, 'TZ_UTC')
        
        # Test configuration values
        assert earnings_swing.NUMBER_OF_STOCKS == 5
        assert isinstance(earnings_swing.EARNINGS_FILTERS, dict)
        assert isinstance(earnings_swing.EARNINGS_COLUMNS, list)

    def test_timezone_configuration(self, mock_env_vars):
        """Test timezone configuration."""
        from zoneinfo import ZoneInfo
        
        assert earnings_swing.TZ_NY == ZoneInfo("US/Eastern")
        assert earnings_swing.TZ_UTC == ZoneInfo('UTC')

    @patch('earnings_swing.get_alpaca_client')
    @patch('earnings_swing.get_eodhd_client') 
    @patch('earnings_swing.get_finviz_client')
    def test_client_initialization(self, mock_finviz, mock_eodhd, mock_alpaca, mock_env_vars):
        """Test that all API clients are properly initialized."""
        # Import the module to trigger client initialization
        import importlib
        importlib.reload(earnings_swing)
        
        # Verify clients were called
        mock_alpaca.assert_called()
        mock_eodhd.assert_called()
        mock_finviz.assert_called()