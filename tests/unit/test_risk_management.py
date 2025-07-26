"""Unit tests for risk management module."""

import pytest
import json
from unittest.mock import Mock, patch, mock_open
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import risk_management


class TestRiskManagement:
    """Test risk management functionality."""

    def test_check_pnl_based_risk_no_file(self, mock_env_vars):
        """Test PnL check when no log file exists."""
        with patch('os.path.exists', return_value=False):
            result = risk_management.check_pnl_based_risk()
            # Should return True (safe to trade) when no history exists
            assert result == True

    def test_check_pnl_based_risk_within_limit(self, mock_env_vars):
        """Test PnL check when within acceptable risk limit."""
        # Mock PnL data within the last 30 days with positive performance
        mock_pnl_data = {
            "trades": [
                {
                    "date": (datetime.now() - timedelta(days=5)).isoformat(),
                    "pnl": 100.0,
                    "cumulative_pnl": 100.0
                },
                {
                    "date": (datetime.now() - timedelta(days=10)).isoformat(), 
                    "pnl": 50.0,
                    "cumulative_pnl": 150.0
                }
            ]
        }
        
        mock_file_content = json.dumps(mock_pnl_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)):
                result = risk_management.check_pnl_based_risk()
                assert result == True

    def test_check_pnl_based_risk_exceeds_limit(self, mock_env_vars):
        """Test PnL check when exceeding risk limit."""
        # Mock PnL data with significant losses (> 6% assuming 10k account)
        mock_pnl_data = {
            "trades": [
                {
                    "date": (datetime.now() - timedelta(days=5)).isoformat(),
                    "pnl": -700.0,  # More than 6% of a typical account
                    "cumulative_pnl": -700.0
                }
            ]
        }
        
        mock_file_content = json.dumps(mock_pnl_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)):
                with patch('risk_management.get_alpaca_client') as mock_get_client:
                    mock_client = Mock()
                    mock_get_client.return_value = mock_client
                    mock_account = Mock()
                    mock_account.equity = '10000'  # $10k account
                    mock_client.get_account.return_value = mock_account
                    
                    result = risk_management.check_pnl_based_risk()
                    # Should return False (not safe to trade) when losses exceed 6%
                    assert result == False

    def test_check_pnl_based_risk_old_data(self, mock_env_vars):
        """Test PnL check when data is older than 30 days."""
        # Mock PnL data older than 30 days
        mock_pnl_data = {
            "trades": [
                {
                    "date": (datetime.now() - timedelta(days=35)).isoformat(),
                    "pnl": -1000.0,
                    "cumulative_pnl": -1000.0
                }
            ]
        }
        
        mock_file_content = json.dumps(mock_pnl_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)):
                result = risk_management.check_pnl_based_risk()
                # Should return True since old data shouldn't affect current risk assessment
                assert result == True

    def test_check_pnl_based_risk_invalid_json(self, mock_env_vars):
        """Test PnL check with invalid JSON file."""
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data='invalid json')):
                result = risk_management.check_pnl_based_risk()
                # Should return True (safe to trade) when file is corrupted
                assert result == True

    def test_check_pnl_based_risk_empty_trades(self, mock_env_vars):
        """Test PnL check with empty trades list."""
        mock_pnl_data = {"trades": []}
        mock_file_content = json.dumps(mock_pnl_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)):
                result = risk_management.check_pnl_based_risk()
                assert result == True

    @patch('risk_management.get_alpaca_client')
    def test_get_account_equity(self, mock_get_client, mock_env_vars):
        """Test getting account equity."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_account = Mock()
        mock_account.equity = '25000.50'
        mock_client.get_account.return_value = mock_account
        
        equity = risk_management.get_account_equity()
        assert equity == 25000.50

    @patch('risk_management.get_alpaca_client')
    def test_get_account_equity_error(self, mock_get_client, mock_env_vars):
        """Test getting account equity with API error."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.get_account.side_effect = Exception("API Error")
        
        equity = risk_management.get_account_equity()
        # Should return a default value or handle error gracefully
        assert equity is not None or equity == 0

    def test_calculate_risk_percentage(self, mock_env_vars):
        """Test risk percentage calculation."""
        # Test with different account sizes and loss amounts
        assert risk_management.calculate_risk_percentage(10000, -500) == 5.0
        assert risk_management.calculate_risk_percentage(50000, -3000) == 6.0
        assert risk_management.calculate_risk_percentage(10000, 500) == -5.0  # Profit

    def test_calculate_risk_percentage_zero_equity(self, mock_env_vars):
        """Test risk percentage calculation with zero equity."""
        result = risk_management.calculate_risk_percentage(0, -100)
        # Should handle division by zero gracefully
        assert result is not None

    @patch('risk_management.get_alpaca_client')
    def test_log_trade_pnl(self, mock_get_client, mock_env_vars):
        """Test logging trade PnL."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock existing PnL file
        existing_data = {"trades": []}
        mock_file_content = json.dumps(existing_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)) as mock_file:
                risk_management.log_trade_pnl('AAPL', 100, 105, 10, 'buy')
                
                # Verify that file was opened for writing
                mock_file.assert_called()

    def test_is_within_risk_limits_basic(self, mock_env_vars):
        """Test basic risk limit checking."""
        # Test various scenarios
        assert risk_management.is_within_risk_limits(10000, -500) == True  # 5% loss - within limit
        assert risk_management.is_within_risk_limits(10000, -700) == False  # 7% loss - exceeds limit
        assert risk_management.is_within_risk_limits(10000, 500) == True   # Profit - always within limit

    def test_get_risk_threshold(self, mock_env_vars):
        """Test getting risk threshold."""
        threshold = risk_management.get_risk_threshold()
        assert isinstance(threshold, (int, float))
        assert threshold > 0  # Should be a positive percentage

    def test_format_pnl_for_logging(self, mock_env_vars):
        """Test PnL formatting for logging."""
        trade_data = risk_management.format_pnl_for_logging(
            symbol='AAPL',
            entry_price=100.0,
            exit_price=105.0,
            quantity=10,
            side='buy'
        )
        
        assert isinstance(trade_data, dict)
        assert 'symbol' in trade_data
        assert 'pnl' in trade_data
        assert 'date' in trade_data
        assert trade_data['symbol'] == 'AAPL'

    def test_load_pnl_history(self, mock_env_vars):
        """Test loading PnL history."""
        mock_pnl_data = {
            "trades": [
                {
                    "date": datetime.now().isoformat(),
                    "symbol": "AAPL",
                    "pnl": 100.0
                }
            ]
        }
        mock_file_content = json.dumps(mock_pnl_data)
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=mock_file_content)):
                history = risk_management.load_pnl_history()
                
                assert isinstance(history, dict)
                assert 'trades' in history
                assert len(history['trades']) == 1

    def test_load_pnl_history_no_file(self, mock_env_vars):
        """Test loading PnL history when file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            history = risk_management.load_pnl_history()
            
            assert isinstance(history, dict)
            assert 'trades' in history
            assert len(history['trades']) == 0

    @patch('risk_management.datetime')
    def test_filter_recent_trades(self, mock_datetime, mock_env_vars):
        """Test filtering trades from recent period."""
        # Mock current time
        mock_now = datetime(2023, 6, 15)
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat
        
        trades = [
            {"date": "2023-06-10T10:00:00", "pnl": 100},  # 5 days ago - recent
            {"date": "2023-05-10T10:00:00", "pnl": 200},  # 36 days ago - old
            {"date": "2023-06-14T10:00:00", "pnl": -50},  # 1 day ago - recent
        ]
        
        recent_trades = risk_management.filter_recent_trades(trades, days=30)
        
        assert len(recent_trades) == 2  # Should only include recent trades
        assert all(trade["date"] >= "2023-05-16" for trade in recent_trades)