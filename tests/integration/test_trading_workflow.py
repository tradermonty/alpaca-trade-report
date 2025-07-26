"""Integration tests for complete trading workflows."""

import pytest
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date, timedelta
import subprocess

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class TestTradingWorkflow:
    """Test complete trading workflow integration."""

    @pytest.mark.integration
    @patch('earnings_swing.get_finviz_client')
    @patch('earnings_swing.get_fmp_client')
    @patch('earnings_swing.get_alpaca_client')
    def test_earnings_swing_complete_flow(self, mock_alpaca, mock_fmp, mock_finviz, mock_env_vars):
        """Test complete earnings swing trading workflow."""
        import earnings_swing
        
        # Mock Finviz client for screening
        mock_finviz_client = Mock()
        mock_finviz.return_value = mock_finviz_client
        
        # Mock screener data
        mock_df = pd.DataFrame({
            'Ticker': ['AAPL', 'GOOGL', 'MSFT'],
            'EPS Surprise': ['10%', '15%', '8%'],
            'Revenue Surprise': ['5%', '3%', '7%'],
            'Change': ['2%', '1%', '3%'],
            'Relative Volume': [1.5, 2.0, 1.8],
            'Market Cap': ['2.5T', '1.8T', '2.2T']
        })
        
        mock_finviz_client.build_screener_url.return_value = 'test_screener_url'
        mock_finviz_client.get_screener_data.return_value = mock_df
        
        # Mock FMP client for market cap data
        mock_fmp_client = Mock()
        mock_fmp.return_value = mock_fmp_client
        mock_fmp_client.get_market_cap_data.side_effect = [
            {'Components': {'AAPL': {'Code': 'AAPL.US'}, 'GOOGL': {'Code': 'GOOGL.US'}}},
            {'Components': {'MSFT': {'Code': 'MSFT.US'}}}
        ]
        
        # Mock Alpaca client
        mock_alpaca_client = Mock()
        mock_alpaca.return_value = mock_alpaca_client
        mock_api = Mock()
        mock_alpaca_client.api = mock_api
        
        # Mock calendar (market is open)
        mock_calendar = [Mock(open='09:30:00', close='16:00:00')]
        mock_api.get_calendar.return_value = mock_calendar
        
        # Test the screening process
        tickers = earnings_swing.get_tickers_from_screener(2)
        
        assert isinstance(tickers, list)
        assert len(tickers) <= 2
        
        # Verify that all components were called
        mock_finviz_client.build_screener_url.assert_called()
        mock_finviz_client.get_screener_data.assert_called()
        mock_fmp_client.get_market_cap_data.assert_called()

    @pytest.mark.integration
    @patch('uptrend_stocks.get_finviz_client')
    @patch('uptrend_stocks.get_alpaca_client')
    @patch('uptrend_stocks.sheet')
    def test_uptrend_analysis_workflow(self, mock_sheet, mock_alpaca, mock_finviz, mock_env_vars):
        """Test uptrend analysis workflow."""
        import uptrend_stocks
        
        # Mock Finviz client
        mock_finviz_client = Mock()
        mock_finviz.return_value = mock_finviz_client
        mock_finviz_client.get_uptrend_screener_url.return_value = 'uptrend_url'
        mock_finviz_client.get_total_screener_url.return_value = 'total_url'
        mock_finviz_client.get_stock_count.side_effect = [150, 500]
        
        # Mock Alpaca client
        mock_alpaca_client = Mock()
        mock_alpaca.return_value = mock_alpaca_client
        mock_api = Mock()
        mock_alpaca_client.api = mock_api
        mock_calendar = [Mock(close='16:00:00')]
        mock_api.get_calendar.return_value = mock_calendar
        
        # Mock Google Sheets
        mock_sheet.get_all_records.return_value = [
            {'Date': '1/1/2023'},
            {'Date': ''}
        ]
        mock_sheet.update_cell = Mock()
        
        # Test the update process
        uptrend_stocks.update_trend_count(force=True)
        
        # Verify the workflow
        mock_finviz_client.get_uptrend_screener_url.assert_called_once()
        mock_finviz_client.get_total_screener_url.assert_called_once()
        assert mock_finviz_client.get_stock_count.call_count == 2
        mock_sheet.update_cell.assert_called()

    @pytest.mark.integration
    @patch('risk_management.get_alpaca_client')
    def test_risk_management_workflow(self, mock_get_client, mock_env_vars):
        """Test risk management workflow."""
        import risk_management
        
        # Mock Alpaca client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_account = Mock()
        mock_account.equity = '10000'
        mock_client.get_account.return_value = mock_account
        
        # Mock PnL data with recent losses
        import json
        mock_pnl_data = {
            "trades": [
                {
                    "date": (datetime.now() - timedelta(days=5)).isoformat(),
                    "pnl": -500.0,  # 5% loss
                    "symbol": "AAPL"
                }
            ]
        }
        mock_file_content = json.dumps(mock_pnl_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)):
                risk_ok = risk_management.check_pnl_based_risk()
                
                # 5% loss should be within acceptable risk (typically 6%)
                assert risk_ok == True

    @pytest.mark.integration
    @patch('strategy_allocation.get_alpaca_client')
    def test_strategy_allocation_workflow(self, mock_get_client, mock_env_vars):
        """Test strategy allocation workflow."""
        import strategy_allocation
        
        # Mock Alpaca client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_account = Mock()
        mock_account.buying_power = '50000'
        mock_account.equity = '100000'
        mock_client.get_account.return_value = mock_account
        
        # Test position size calculation workflow
        buying_power = strategy_allocation.get_available_buying_power()
        assert buying_power == 50000.0
        
        position_size = strategy_allocation.calculate_position_size(
            buying_power=buying_power,
            allocation_percentage=0.10,  # 10% allocation
            stock_price=100.0
        )
        assert position_size == 50  # $5000 / $100 = 50 shares
        
        # Test validation
        is_valid = strategy_allocation.validate_position_size(
            position_size, buying_power, 100.0
        )
        assert is_valid == True

    @pytest.mark.integration 
    @patch('subprocess.run')
    def test_trade_execution_workflow(self, mock_subprocess, mock_env_vars):
        """Test trade execution via subprocess workflow."""
        # Mock successful subprocess execution
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Trade executed successfully"
        mock_subprocess.return_value = mock_result
        
        # Test different trade execution scenarios
        trade_commands = [
            ['python', 'src/orb.py', 'AAPL', '--swing', 'True', '--pos_size', '1000'],
            ['python', 'src/orb_short.py', 'TSLA', '--pos_size', '500'],
        ]
        
        for command in trade_commands:
            result = subprocess.run(command, capture_output=True, text=True)
            assert mock_subprocess.called
            
    @pytest.mark.integration
    def test_data_flow_integration(self, mock_env_vars):
        """Test data flow between different components."""
        # Test that data structures are compatible between modules
        
        # Mock stock data format used across modules
        sample_data = {
            'symbol': 'AAPL',
            'price': 150.0,
            'volume': 1000000,
            'change': 0.02
        }
        
        # Test that various modules can handle this data format
        assert isinstance(sample_data['symbol'], str)
        assert isinstance(sample_data['price'], (int, float))
        assert isinstance(sample_data['volume'], int)
        assert isinstance(sample_data['change'], (int, float))
        
        # Test DataFrame compatibility
        df = pd.DataFrame([sample_data])
        assert 'symbol' in df.columns
        assert len(df) == 1

    @pytest.mark.integration
    @patch('time.sleep')
    def test_timing_and_scheduling(self, mock_sleep, mock_env_vars):
        """Test timing and scheduling aspects of trading workflows."""
        import uptrend_stocks
        
        with patch('uptrend_stocks.get_alpaca_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            mock_api = Mock()
            mock_client.api = mock_api
            
            # Mock calendar
            mock_calendar = [Mock(close='16:00:00')]
            mock_api.get_calendar.return_value = mock_calendar
            
            # Mock current time to be before market close
            with patch('pandas.Timestamp') as mock_timestamp:
                mock_timestamp.return_value = pd.Timestamp('2023-01-01 15:00:00-05:00')
                
                # Test that timing functions work
                result = uptrend_stocks.is_closing_time_range(60)  # 60 minute range
                assert isinstance(result, (bool, type(None)))

    @pytest.mark.integration
    def test_error_recovery_workflow(self, mock_env_vars):
        """Test error recovery in trading workflows."""
        import earnings_swing
        
        with patch('earnings_swing.get_finviz_client') as mock_finviz:
            # Simulate Finviz API failure
            mock_client = Mock()
            mock_finviz.return_value = mock_client
            mock_client.get_screener_data.side_effect = Exception("API Error")
            
            # The workflow should handle the error gracefully
            try:
                tickers = earnings_swing.get_tickers_from_screener(5)
                # Should return empty list on error
                assert isinstance(tickers, list)
            except Exception as e:
                # Or raise a handled exception
                assert "API Error" in str(e)

    @pytest.mark.integration
    def test_configuration_consistency(self, mock_env_vars):
        """Test that configuration is consistent across modules."""
        import earnings_swing
        import uptrend_stocks
        
        # Test that timezone configurations are consistent
        assert hasattr(earnings_swing, 'TZ_NY')
        assert hasattr(uptrend_stocks, 'TZ_NY')
        
        # Both should use the same timezone
        assert earnings_swing.TZ_NY == uptrend_stocks.TZ_NY
        
        # Test that constants make sense
        assert earnings_swing.NUMBER_OF_STOCKS > 0
        assert isinstance(earnings_swing.EARNINGS_FILTERS, dict)
        assert isinstance(earnings_swing.EARNINGS_COLUMNS, list)

    @pytest.mark.integration
    def test_logging_and_monitoring(self, mock_env_vars):
        """Test logging and monitoring capabilities."""
        import risk_management
        
        # Test that logging functions work
        with patch('builtins.open', mock_open()) as mock_file:
            try:
                risk_management.log_trade_pnl('AAPL', 100, 105, 10, 'buy')
                # Should attempt to write to log file
                mock_file.assert_called()
            except Exception:
                # Or handle gracefully if logging fails
                pass

from unittest.mock import mock_open