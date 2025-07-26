"""Pytest configuration and fixtures for the stock trading system tests."""

import pytest
import os
import sys
from datetime import datetime, date, time
from unittest.mock import Mock, patch
import pandas as pd

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Mock external dependencies before importing
from unittest.mock import MagicMock

# Mock alpaca_trade_api
sys.modules['alpaca_trade_api'] = MagicMock()
sys.modules['alpaca_trade_api.common'] = MagicMock()
sys.modules['alpaca_trade_api.rest'] = MagicMock()

# Mock gspread and oauth2client
sys.modules['gspread'] = MagicMock()
sys.modules['oauth2client'] = MagicMock()
sys.modules['oauth2client.service_account'] = MagicMock()

# Mock technical analysis libraries
sys.modules['talib'] = MagicMock()
sys.modules['yfinance'] = MagicMock()
sys.modules['scipy'] = MagicMock()
sys.modules['scipy.stats'] = MagicMock()

# Mock other dependencies
sys.modules['openai'] = MagicMock()
sys.modules['smtplib'] = MagicMock()

@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'ALPACA_API_KEY_LIVE': 'test_live_key',
        'ALPACA_SECRET_KEY_LIVE': 'test_live_secret',
        'ALPACA_API_KEY_PAPER': 'test_paper_key',
        'ALPACA_SECRET_KEY_PAPER': 'test_paper_secret',
        'ALPACA_API_KEY_PAPER_SHORT': 'test_paper_short_key',
        'ALPACA_SECRET_KEY_PAPER_SHORT': 'test_paper_short_secret',
        'FINVIZ_API_KEY': 'test_finviz_key',
        'FMP_API_KEY': 'test_fmp_key',
        'OPENAI_API_KEY': 'test_openai_key',
        'ALPHA_VANTAGE_API_KEY': 'test_alpha_vantage_key',
        'GMAIL_PASSWORD': 'test_gmail_password'
    }):
        yield

@pytest.fixture
def sample_stock_data():
    """Sample stock data for testing."""
    return pd.DataFrame({
        'Date': pd.date_range('2023-01-01', periods=5),
        'Open': [100.0, 101.0, 99.0, 102.0, 103.0],
        'High': [105.0, 106.0, 104.0, 107.0, 108.0],
        'Low': [95.0, 96.0, 94.0, 97.0, 98.0],
        'Close': [102.0, 98.0, 103.0, 105.0, 107.0],
        'Volume': [1000000, 1100000, 900000, 1200000, 1300000]
    })

@pytest.fixture
def mock_alpaca_api():
    """Mock Alpaca API for testing."""
    mock_api = Mock()
    mock_api.get_account.return_value = Mock(
        id='test_account',
        equity='100000',
        buying_power='50000',
        status='ACTIVE'
    )
    mock_api.list_positions.return_value = []
    mock_api.list_orders.return_value = []
    mock_api.get_calendar.return_value = [
        Mock(date=date.today(), open=time(9, 30), close=time(16, 0))
    ]
    return mock_api

@pytest.fixture
def mock_finviz_response():
    """Mock Finviz screener response."""
    return pd.DataFrame({
        'Ticker': ['AAPL', 'GOOGL', 'MSFT'],
        'Company': ['Apple Inc.', 'Alphabet Inc.', 'Microsoft Corporation'],
        'Price': [150.0, 2500.0, 300.0],
        'Change': [0.02, -0.01, 0.01],
        'Volume': [50000000, 1500000, 25000000],
        'Market Cap': ['2.5T', '1.8T', '2.2T']
    })

@pytest.fixture
def mock_fmp_response():
    """Mock FMP API response."""
    return [
        {
            'date': '2023-01-01',
            'open': 100.0,
            'high': 105.0,
            'low': 95.0,
            'close': 102.0,
            'adjusted_close': 102.0,
            'volume': 1000000
        },
        {
            'date': '2023-01-02', 
            'open': 101.0,
            'high': 106.0,
            'low': 96.0,
            'close': 98.0,
            'adjusted_close': 98.0,
            'volume': 1100000
        }
    ]

@pytest.fixture
def mock_requests_get():
    """Mock requests.get for HTTP calls."""
    with patch('requests.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_response.content = b'Ticker,Price,Change\nAAPL,150.0,0.02\nGOOGL,2500.0,-0.01'
        mock_get.return_value = mock_response
        yield mock_get

@pytest.fixture(autouse=True)
def mock_dotenv():
    """Auto-mock dotenv loading."""
    with patch('dotenv.load_dotenv'):
        yield

