# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Alpaca Trade Report Generator that analyzes trading activity from Alpaca brokerage accounts and generates comprehensive performance reports with both CSV and interactive HTML outputs.

## Environment Setup

1. Create `.env` file from `.env.sample`:
   ```bash
   cp .env.sample .env
   ```

2. Required API keys in `.env`:
   - `ALPACA_API_KEY` - Alpaca trading API key
   - `ALPACA_SECRET_KEY` - Alpaca secret key
   - `FMP_API_KEY` - Financial Modeling Prep API key (for earnings data)
   - `OPENAI_API_KEY` - Optional, for AI-powered analysis

## Common Commands

### Running the Application
```bash
# Generate trade report for last 30 days (English)
python src/alpaca_trade_report.py --start_date 2025-06-26 --end_date 2025-07-26 --language en

# Generate report in Japanese
python src/alpaca_trade_report.py --start_date 2025-06-26 --end_date 2025-07-26 --language ja

# Full command with all parameters
python src/alpaca_trade_report.py \
    --start_date 2025-06-26 \
    --end_date 2025-07-26 \
    --language en \
    --stop_loss 6 \
    --trail_stop_ma 21 \
    --max_holding_days 90 \
    --initial_capital 10000 \
    --risk_limit 6 \
    --partial_profit \
    --pre_earnings_change -10
```

### Development Commands
```bash
# Format code
black src/

# Sort imports
isort src/

# Lint code
flake8 src/

# Type checking
mypy src/

# Run tests (when implemented)
pytest
pytest -v  # Verbose
pytest --asyncio-mode=auto  # For async tests
```

## Architecture Overview

### Core Components

1. **Main Entry Point**: `src/alpaca_trade_report.py`
   - `TradeReport` class orchestrates the entire report generation
   - Handles command-line arguments and language settings
   - Generates both CSV and HTML outputs

2. **API Integration**: `src/fmp_data_fetcher.py`
   - `FMPDataFetcher` class manages Financial Modeling Prep API calls
   - Implements rate limiting (750 calls/min for Premium plan)
   - Handles symbol variants (e.g., BRK.B → BRK-B) automatically
   - Provides earnings calendar and company profile data

### Key Design Patterns

1. **Rate Limiting**
   - Dynamic rate limiting that activates only when API returns 429
   - Optimized for maximum throughput (12.5 calls/second)
   - Automatic cooldown and retry mechanisms

2. **Data Processing Pipeline**
   - Fetch trades from Alpaca API
   - Enrich with earnings data from FMP
   - Calculate performance metrics (Win rate, CAGR, Sharpe ratio)
   - Generate visual reports with Plotly

3. **Multi-language Support**
   - Japanese and English language support
   - Language-specific formatting for dates and numbers
   - Internationalized labels in HTML reports

4. **Error Handling**
   - Graceful fallbacks for API failures
   - Symbol variant handling for special tickers
   - Default values when data unavailable

### Output Formats

1. **CSV Report**: `trade_report_YYYY-MM-DD_to_YYYY-MM-DD.csv`
   - Detailed trade-by-trade analysis
   - Performance metrics per position

2. **HTML Report**: `portfolio_report_YYYY-MM-DD_to_YYYY-MM-DD.html`
   - Interactive dark-themed dashboard
   - Plotly charts for performance visualization
   - Sortable tables with comprehensive metrics

## Testing

Currently, the project has minimal test coverage. When adding tests:
- Use pytest framework
- Place tests in `tests/` directory
- Use `pytest-asyncio` for async code
- Use `pytest-mock` for mocking external APIs

## Important Notes

- The application defaults to Alpaca paper trading API (`https://paper-api.alpaca.markets`)
- FMP API has different rate limits based on plan (Starter: 300/min, Premium: 750/min)
- All monetary values are in USD
- Dates should be in YYYY-MM-DD format
- The report generator handles both realized and unrealized gains/losses