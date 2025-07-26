# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

This is a Python-based automated stock trading system. Use the `alpaca` virtual environment:
```bash
workon alpaca
```

The system uses environment variables for API keys stored in `.env` file:
- Multiple Alpaca accounts (live, paper, paper short)
- Finviz Elite API key
- OpenAI API key  
- Alpha Vantage API key
- FMP API key

## Core Architecture

### Trading Strategy Hierarchy

The system implements a multi-layered trading architecture:

1. **Core Modules** (imported by multiple strategies):
   - `strategy_allocation.py` - Calculates position sizes based on account equity and strategy allocation
   - `risk_management.py` - PnL-based risk controls, maintains 30-day rolling performance in `pnl_log.json`
   - `uptrend_stocks.py` - Identifies uptrending stocks using Finviz screeners, updates Google Sheets
   - `dividend_portfolio_management.py` - Manages high-dividend stock exclusion list

2. **Strategy Execution Scripts** (main entry points):
   - `earnings_swing.py` - Earnings-based swing trading (calls `orb.py` via subprocess)
   - `earnings_swing_short.py` - Short-side earnings plays (calls `orb_short.py` via subprocess)
   - `relative_volume_trade.py` - Volume-based day trading (calls `orb.py` via subprocess)
   - `maintain_swing.py/maintain_swing_paper.py` - Portfolio maintenance strategies

3. **Trade Execution Engines** (called via subprocess):
   - `orb.py` - Opening Range Breakout strategy with bracket orders
   - `orb_short.py` - Short-side ORB implementation

4. **Analysis Tools** (standalone utilities):
   - `news_analysis.py` - News sentiment analysis using OpenAI
   - `uptrend_count_sector.py` - Sector-based trend analysis
   - `trend_reversion_*.py` - Mean reversion strategies

### Account Management

The system supports multiple trading modes via `ALPACA_ACCOUNT` variable:
- `'live'` - Uses live Alpaca account credentials
- `'paper'` - Uses paper trading credentials  
- Account-specific API keys loaded from environment variables

### Data Sources Integration

- **Finviz Elite**: Stock screening with retry logic (`FINVIZ_MAX_RETRIES`, `FINVIZ_RETRY_WAIT`)
- **Google Sheets**: Manual trade commands via `config/spreadsheetautomation-*.json`
- **Alpaca API**: Market data, trade execution, account information
- **Financial Modeling Prep (FMP)**: Market cap data, historical prices, index constituents

## Key Execution Patterns

### Subprocess Trading Pattern
Main strategy scripts use subprocess to launch trading engines:
```python
process[ticker] = subprocess.Popen(['python3', TRADE_PY_FILE, str(ticker), '--swing', 'True', '--pos_size', str(size)])
```

### Risk Management Chain
All strategies follow this sequence:
1. Check PnL criteria via `risk_management.check_pnl_criteria()`
2. Calculate position size via `strategy_allocation.get_target_value()`
3. Execute trades only if risk criteria met

### Google Sheets Integration
Several scripts read/write to "US Market - Uptrend Stocks" and "trade_commands" sheets for:
- Manual trade commands
- Uptrend stock lists by sector
- Performance tracking

## File Organization

```
├── src/                   # Source code directory
│   ├── api_clients.py    # Centralized API clients
│   ├── *.py files        # Trading strategies and utilities
├── config/               # Authentication files
├── docs/                 # Strategy design documents
├── reports/              # Generated reports (gitignored except index.html)
└── pnl_log.json         # Risk management data
```

## Testing and Development

The system includes test modes in trading engines:
```python
test_mode = False  # Set to True for backtesting
test_datetime = pd.Timestamp(datetime.now().astimezone(TZ_NY))
```

For development, always ensure:
- `.env` file is properly configured with API keys
- Google Sheets authentication file is in `config/` directory
- Virtual environment `alpaca` is activated
- Risk management checks are functioning before live trading

## API Client Architecture

The system now uses centralized API clients via `api_clients.py`:

**AlpacaClient Usage:**
```python
from src.api_clients import get_alpaca_client

# Get client for specific account type
alpaca_client = get_alpaca_client('live')     # Live trading
alpaca_client = get_alpaca_client('paper')    # Paper trading  
alpaca_client = get_alpaca_client('paper_short')  # Short trading

# Access underlying API for backward compatibility
api = alpaca_client.api
```

**FMPClient Usage:**
```python  
from src.api_clients import get_fmp_client

fmp_client = get_fmp_client()
market_data = fmp_client.get_market_cap_data(['AAPL', 'MSFT'])
historical_data = fmp_client.get_historical_price_data('AAPL', '2024-01-01', '2024-12-31')
```

**Benefits:**
- Centralized error handling and retry logic
- Singleton pattern prevents multiple connections
- Built-in logging and monitoring
- Type safety and documentation

## Critical Dependencies

- `alpaca_trade_api` - Trading API client (wrapped by AlpacaClient)
- `gspread` + `oauth2client` - Google Sheets integration  
- `python-dotenv` - Environment variable management
- `pandas` - Data manipulation
- `requests` - API calls to external services (wrapped by FMPClient)
- `openai` - AI-powered news analysis

## Trading Schedule

The system is designed for US market hours with timezone handling via `ZoneInfo("US/Eastern")`. Many scripts include market calendar integration and automatic scheduling around:
- Market open/close times
- Pre-market and after-hours sessions
- Holiday schedules via Alpaca calendar API