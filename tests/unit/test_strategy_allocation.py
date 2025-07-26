"""Unit tests for strategy allocation module."""

import pytest
from unittest.mock import Mock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import strategy_allocation


class TestStrategyAllocation:
    """Test strategy allocation functionality."""

    @patch('strategy_allocation.get_alpaca_client')
    def test_get_available_buying_power(self, mock_get_client, mock_env_vars):
        """Test getting available buying power."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_account = Mock()
        mock_account.buying_power = '50000.75'
        mock_client.get_account.return_value = mock_account
        
        buying_power = strategy_allocation.get_available_buying_power()
        assert buying_power == 50000.75

    @patch('strategy_allocation.get_alpaca_client')
    def test_get_available_buying_power_error(self, mock_get_client, mock_env_vars):
        """Test getting buying power with API error."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.get_account.side_effect = Exception("API Error")
        
        buying_power = strategy_allocation.get_available_buying_power()
        # Should handle error gracefully
        assert buying_power is not None

    @patch('strategy_allocation.get_alpaca_client')
    def test_get_account_equity(self, mock_get_client, mock_env_vars):
        """Test getting account equity."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_account = Mock()
        mock_account.equity = '100000.00'
        mock_client.get_account.return_value = mock_account
        
        equity = strategy_allocation.get_account_equity()
        assert equity == 100000.00

    def test_calculate_position_size_basic(self, mock_env_vars):
        """Test basic position size calculation."""
        # Test with 10% allocation of $50k buying power at $100/share
        position_size = strategy_allocation.calculate_position_size(
            buying_power=50000,
            allocation_percentage=0.10,
            stock_price=100.0
        )
        assert position_size == 50  # $5000 / $100 = 50 shares

    def test_calculate_position_size_zero_price(self, mock_env_vars):
        """Test position size calculation with zero stock price."""
        position_size = strategy_allocation.calculate_position_size(
            buying_power=50000,
            allocation_percentage=0.10,
            stock_price=0.0
        )
        assert position_size == 0

    def test_calculate_position_size_high_price(self, mock_env_vars):
        """Test position size calculation with high stock price."""
        # Test with stock price higher than available allocation
        position_size = strategy_allocation.calculate_position_size(
            buying_power=1000,
            allocation_percentage=0.10,  # $100 allocation
            stock_price=200.0  # Cannot buy even 1 share
        )
        assert position_size == 0

    def test_calculate_position_size_fractional(self, mock_env_vars):
        """Test position size calculation with fractional shares."""
        position_size = strategy_allocation.calculate_position_size(
            buying_power=10000,
            allocation_percentage=0.05,  # $500 allocation
            stock_price=333.33  # Results in 1.5 shares
        )
        assert position_size == 1  # Should round down to whole shares

    def test_get_strategy_allocation_earnings_swing(self, mock_env_vars):
        """Test getting strategy allocation for earnings swing."""
        allocation = strategy_allocation.get_strategy_allocation('earnings_swing')
        assert isinstance(allocation, float)
        assert 0 <= allocation <= 1

    def test_get_strategy_allocation_orb(self, mock_env_vars):
        """Test getting strategy allocation for ORB strategy."""
        allocation = strategy_allocation.get_strategy_allocation('orb')
        assert isinstance(allocation, float)
        assert 0 <= allocation <= 1

    def test_get_strategy_allocation_unknown(self, mock_env_vars):
        """Test getting strategy allocation for unknown strategy."""
        allocation = strategy_allocation.get_strategy_allocation('unknown_strategy')
        # Should return a default allocation or 0
        assert isinstance(allocation, float)
        assert allocation >= 0

    @patch('strategy_allocation.get_alpaca_client')
    def test_get_current_positions_value(self, mock_get_client, mock_env_vars):
        """Test getting current positions value."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock positions
        mock_positions = [
            Mock(market_value='5000.00', symbol='AAPL'),
            Mock(market_value='3000.00', symbol='GOOGL'),
            Mock(market_value='2000.00', symbol='MSFT')
        ]
        mock_client.get_positions.return_value = mock_positions
        
        total_value = strategy_allocation.get_current_positions_value()
        assert total_value == 10000.00

    @patch('strategy_allocation.get_alpaca_client')
    def test_get_current_positions_value_no_positions(self, mock_get_client, mock_env_vars):
        """Test getting positions value with no positions."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.get_positions.return_value = []
        
        total_value = strategy_allocation.get_current_positions_value()
        assert total_value == 0.0

    def test_calculate_max_position_size(self, mock_env_vars):
        """Test calculating maximum position size."""
        max_size = strategy_allocation.calculate_max_position_size(
            account_equity=100000,
            max_risk_per_trade=0.02,  # 2% max risk
            stock_price=100.0,
            stop_loss_percentage=0.05  # 5% stop loss
        )
        # Max risk = $2000, with 5% stop loss, max position = $40000, shares = 400
        assert max_size == 400

    def test_calculate_max_position_size_zero_stop_loss(self, mock_env_vars):
        """Test max position size calculation with zero stop loss."""
        max_size = strategy_allocation.calculate_max_position_size(
            account_equity=100000,
            max_risk_per_trade=0.02,
            stock_price=100.0,
            stop_loss_percentage=0.0
        )
        # Should handle division by zero gracefully
        assert max_size >= 0

    def test_validate_position_size(self, mock_env_vars):
        """Test position size validation."""
        # Valid position size
        assert strategy_allocation.validate_position_size(100, 50000, 100.0) == True
        
        # Position size too large for buying power
        assert strategy_allocation.validate_position_size(1000, 50000, 100.0) == False
        
        # Zero or negative position size
        assert strategy_allocation.validate_position_size(0, 50000, 100.0) == False
        assert strategy_allocation.validate_position_size(-10, 50000, 100.0) == False

    def test_get_allocation_by_market_conditions(self, mock_env_vars):
        """Test getting allocation based on market conditions."""
        # Mock uptrend condition
        with patch('strategy_allocation.is_market_uptrend', return_value=True):
            allocation = strategy_allocation.get_allocation_by_market_conditions('earnings_swing')
            assert isinstance(allocation, float)
            assert allocation > 0

        # Mock downtrend condition  
        with patch('strategy_allocation.is_market_uptrend', return_value=False):
            allocation = strategy_allocation.get_allocation_by_market_conditions('earnings_swing')
            assert isinstance(allocation, float)

    def test_calculate_kelly_criterion(self, mock_env_vars):
        """Test Kelly criterion calculation."""
        kelly_fraction = strategy_allocation.calculate_kelly_criterion(
            win_rate=0.6,  # 60% win rate
            avg_win=100.0,
            avg_loss=50.0
        )
        assert isinstance(kelly_fraction, float)
        assert kelly_fraction >= 0

    def test_calculate_kelly_criterion_negative(self, mock_env_vars):
        """Test Kelly criterion with negative expectation."""
        kelly_fraction = strategy_allocation.calculate_kelly_criterion(
            win_rate=0.3,  # 30% win rate
            avg_win=50.0,
            avg_loss=100.0  # Larger average loss
        )
        # Should return 0 for negative expectation strategies
        assert kelly_fraction <= 0

    def test_adjust_position_for_volatility(self, mock_env_vars):
        """Test position size adjustment for volatility."""
        base_position = 100
        
        # High volatility should reduce position size
        adjusted_position = strategy_allocation.adjust_position_for_volatility(
            base_position, volatility=0.30  # 30% volatility
        )
        assert adjusted_position <= base_position
        
        # Low volatility should maintain or slightly increase position size
        adjusted_position = strategy_allocation.adjust_position_for_volatility(
            base_position, volatility=0.10  # 10% volatility
        )
        assert adjusted_position >= base_position * 0.8  # At least 80% of original

    @patch('strategy_allocation.get_alpaca_client')
    def test_get_day_trading_buying_power(self, mock_get_client, mock_env_vars):
        """Test getting day trading buying power."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_account = Mock()
        mock_account.daytrading_buying_power = '200000.00'
        mock_client.get_account.return_value = mock_account
        
        dt_buying_power = strategy_allocation.get_day_trading_buying_power()
        assert dt_buying_power == 200000.00

    def test_is_position_size_reasonable(self, mock_env_vars):
        """Test if position size is reasonable."""
        # Reasonable position size (5% of account)
        assert strategy_allocation.is_position_size_reasonable(
            position_value=5000, account_equity=100000
        ) == True
        
        # Too large position size (50% of account)
        assert strategy_allocation.is_position_size_reasonable(
            position_value=50000, account_equity=100000
        ) == False
        
        # Very small position size
        assert strategy_allocation.is_position_size_reasonable(
            position_value=100, account_equity=100000
        ) == True

    def test_calculate_diversification_factor(self, mock_env_vars):
        """Test diversification factor calculation."""
        # Single position - no diversification benefit
        factor = strategy_allocation.calculate_diversification_factor(1)
        assert factor == 1.0
        
        # Multiple positions - some diversification benefit
        factor = strategy_allocation.calculate_diversification_factor(5)
        assert 0.8 <= factor <= 1.0
        
        # Many positions - significant diversification
        factor = strategy_allocation.calculate_diversification_factor(20)
        assert 0.5 <= factor <= 0.8