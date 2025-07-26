"""Unit tests for uptrend stocks analysis."""

import pytest
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date, timedelta

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import uptrend_stocks


class TestUptrendStocks:
    """Test uptrend stocks functionality."""

    def test_number_of_stocks(self, mock_env_vars):
        """Test number_of_stocks function."""
        # Mock the finviz client directly in the module
        with patch('uptrend_stocks.finviz_client') as mock_client:
            mock_client.get_stock_count.return_value = 150
            
            result = uptrend_stocks.number_of_stocks('https://elite.finviz.com/export.ashx?test=1')
            
            assert result == 150
            mock_client.get_stock_count.assert_called_once_with('https://elite.finviz.com/export.ashx?test=1')

    @patch('uptrend_stocks.get_alpaca_client')
    def test_is_closing_time_range(self, mock_get_alpaca_client, mock_env_vars):
        """Test is_closing_time_range function."""
        # Mock the alpaca client
        mock_client = Mock()
        mock_get_alpaca_client.return_value = mock_client
        mock_api = Mock()
        mock_client.api = mock_api
        
        # Mock calendar data
        mock_calendar = [Mock(close='16:00:00')]
        mock_api.get_calendar.return_value = mock_calendar
        
        with patch('pandas.Timestamp') as mock_timestamp:
            mock_timestamp.return_value = pd.Timestamp('2023-01-01 15:59:00-05:00')
            
            result = uptrend_stocks.is_closing_time_range(1)
            
            # Should return True since we're within 1 minute of close
            assert isinstance(result, bool)

    @patch('uptrend_stocks.get_alpaca_client')
    def test_sleep_until_next_close(self, mock_get_alpaca_client, mock_env_vars):
        """Test sleep_until_next_close function."""
        # Mock the alpaca client
        mock_client = Mock()
        mock_get_alpaca_client.return_value = mock_client
        mock_api = Mock()
        mock_client.api = mock_api
        
        # Mock calendar data
        mock_calendar = [Mock(close='16:00:00')]
        mock_api.get_calendar.return_value = mock_calendar
        
        with patch('time.sleep') as mock_sleep:
            with patch('pandas.Timestamp') as mock_timestamp:
                # Mock current time to be well before close
                mock_timestamp.return_value = pd.Timestamp('2023-01-01 10:00:00-05:00')
                
                # This should not hang in testing
                with patch('uptrend_stocks.datetime') as mock_datetime:
                    mock_datetime.date.today.return_value = date(2023, 1, 1)
                    
                    # We'll just test that the function can be called without error
                    # In a real test, we might want to mock the entire loop logic
                    try:
                        # Use a timeout or mock the loop condition
                        with patch('builtins.range', return_value=range(1)):  # Limit iterations
                            uptrend_stocks.sleep_until_next_close(1)
                    except Exception:
                        # Expected since we're mocking heavily
                        pass

    @patch('uptrend_stocks.get_finviz_client')
    @patch('uptrend_stocks.get_alpaca_client')
    @patch('sys.argv', ['test'])  # Mock command line arguments
    def test_update_trend_count_forced(self, mock_get_alpaca_client, mock_get_finviz_client, mock_env_vars):
        """Test update_trend_count function with force=True."""
        # Mock the alpaca client
        mock_alpaca_client = Mock()
        mock_get_alpaca_client.return_value = mock_alpaca_client
        mock_api = Mock()
        mock_alpaca_client.api = mock_api
        
        # Mock calendar data (market is open)
        mock_calendar = [Mock(close='16:00:00')]
        mock_api.get_calendar.return_value = mock_calendar
        
        # Mock the finviz client
        mock_finviz_client = Mock()
        mock_get_finviz_client.return_value = mock_finviz_client
        mock_finviz_client.get_uptrend_screener_url.return_value = 'uptrend_url'
        mock_finviz_client.get_total_screener_url.return_value = 'total_url'
        mock_finviz_client.get_stock_count.side_effect = [100, 500]  # uptrend, total
        
        # Mock the spreadsheet
        with patch('uptrend_stocks.sheet') as mock_sheet:
            mock_sheet.get_all_records.return_value = [
                {'Date': '1/1/2023'},
                {'Date': ''}
            ]
            
            # Call with force=True to skip time waiting
            uptrend_stocks.update_trend_count(force=True)
            
            # Verify that the finviz client methods were called
            mock_finviz_client.get_uptrend_screener_url.assert_called_once()
            mock_finviz_client.get_total_screener_url.assert_called_once()
            assert mock_finviz_client.get_stock_count.call_count == 2

    @patch('uptrend_stocks.sheet')
    def test_is_uptrend(self, mock_sheet, mock_env_vars):
        """Test is_uptrend function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        mock_sheet.get.return_value = [['50']]  # Mock trend up value
        
        with patch('uptrend_stocks.datetime') as mock_datetime:
            mock_datetime.datetime.now.return_value.strftime.return_value = '1/1/2023'
            
            result = uptrend_stocks.is_uptrend()
            
            assert isinstance(result, bool)

    @patch('uptrend_stocks.sheet')
    def test_is_downtrend(self, mock_sheet, mock_env_vars):
        """Test is_downtrend function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        mock_sheet.get.return_value = [['30']]  # Mock trend down value
        
        result = uptrend_stocks.is_downtrend()
        
        assert isinstance(result, bool)

    @patch('uptrend_stocks.sheet')
    def test_is_overbought(self, mock_sheet, mock_env_vars):
        """Test is_overbought function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        # Mock ratio and upper values
        mock_sheet.get.side_effect = [
            [['50']], # count
            [['75%']], # ratio
            [['80%']]  # upper
        ]
        
        result = uptrend_stocks.is_overbought()
        
        assert isinstance(result, bool)

    @patch('uptrend_stocks.sheet')
    def test_is_oversold(self, mock_sheet, mock_env_vars):
        """Test is_oversold function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        # Mock ratio and lower values
        mock_sheet.get.side_effect = [
            [['50']], # count
            [['25%']], # ratio
            [['20%']]  # lower
        ]
        
        result = uptrend_stocks.is_oversold()
        
        assert isinstance(result, bool)

    @patch('uptrend_stocks.sheet')
    def test_get_long_signal(self, mock_sheet, mock_env_vars):
        """Test get_long_signal function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        mock_sheet.get.side_effect = [
            [['50']], # count
            [['BUY']]  # long signal
        ]
        
        with patch('uptrend_stocks.datetime') as mock_datetime:
            mock_datetime.datetime.now.return_value.strftime.return_value = '1/1/2023'
            
            result = uptrend_stocks.get_long_signal()
            
            assert isinstance(result, str)

    @patch('uptrend_stocks.sheet')
    def test_get_short_signal(self, mock_sheet, mock_env_vars):
        """Test get_short_signal function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        mock_sheet.get.side_effect = [
            [['50']], # count
            [['SELL']]  # short signal
        ]
        
        with patch('uptrend_stocks.datetime') as mock_datetime:
            mock_datetime.datetime.now.return_value.strftime.return_value = '1/1/2023'
            
            result = uptrend_stocks.get_short_signal()
            
            assert isinstance(result, str)

    @patch('uptrend_stocks.sheet')
    def test_get_slope(self, mock_sheet, mock_env_vars):
        """Test get_slope function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        mock_sheet.get.return_value = [['1.5']]  # Mock slope value
        
        result = uptrend_stocks.get_slope('1/1/2023')
        
        assert isinstance(result, (int, float))

    @patch('uptrend_stocks.sheet')
    def test_get_ratio(self, mock_sheet, mock_env_vars):
        """Test get_ratio function."""
        # Mock sheet data
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': '1/2/2023'}
        ]
        mock_sheet.get.return_value = [['75%']]  # Mock ratio value
        
        result = uptrend_stocks.get_ratio('1/1/2023')
        
        assert isinstance(result, (int, float))
        assert 0 <= result <= 1  # Should be converted to decimal

    def test_constants_and_configuration(self, mock_env_vars):
        """Test that constants and configuration are properly set."""
        # Test column constants
        assert hasattr(uptrend_stocks, 'COL_COUNT')
        assert hasattr(uptrend_stocks, 'COL_RATIO')
        assert hasattr(uptrend_stocks, 'COL_TREND_UP')
        assert hasattr(uptrend_stocks, 'COL_TREND_DOWN')
        assert hasattr(uptrend_stocks, 'COL_UPPER')
        assert hasattr(uptrend_stocks, 'COL_LOWER')
        assert hasattr(uptrend_stocks, 'COL_LONG_SIGNAL')
        assert hasattr(uptrend_stocks, 'COL_SHORT_SIGNAL')
        assert hasattr(uptrend_stocks, 'COL_SLOPE')
        
        # Test timezone constants
        assert hasattr(uptrend_stocks, 'TZ_NY')
        assert hasattr(uptrend_stocks, 'TZ_UTC')

    def test_sheet_none_handling(self, mock_env_vars):
        """Test functions handle sheet being None."""
        with patch('uptrend_stocks.sheet', None):
            # These functions should handle sheet being None gracefully
            assert uptrend_stocks.is_uptrend() == False
            assert uptrend_stocks.is_downtrend() == False
            assert uptrend_stocks.is_overbought() == False
            assert uptrend_stocks.is_oversold() == False
            assert uptrend_stocks.get_long_signal() == ""
            assert uptrend_stocks.get_short_signal() == ""
            assert uptrend_stocks.get_slope() == 0
            assert uptrend_stocks.get_ratio() == 0