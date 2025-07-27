# Alpaca Trade Report Generator

A comprehensive trading performance analysis tool that generates detailed reports from Alpaca brokerage accounts. This tool fetches trading data, enriches it with earnings information, and creates both CSV and interactive HTML reports with advanced performance metrics.

## Features

- **Automated Trade Analysis**: Fetches and analyzes all trades from your Alpaca account
- **Earnings Integration**: Enriches trade data with earnings calendar information from Financial Modeling Prep API
- **Performance Metrics**: Calculates Win Rate, CAGR, Sharpe Ratio, Maximum Drawdown, and more
- **Interactive Reports**: Generates beautiful dark-themed HTML reports with Plotly charts
- **Multi-language Support**: Available in English and Japanese
- **CSV Export**: Detailed trade-by-trade data in CSV format
- **Risk Management Analysis**: Tracks stop-loss effectiveness and position sizing
- **Graceful Degradation**: Runs with basic functionality when optional APIs are unavailable

## Prerequisites

- Python 3.11 or higher
- macOS/Linux/Windows

## Installation

1. Clone the repository:
```bash
git clone https://github.com/tradermonty/alpaca-trade-report.git
cd alpaca-trade-report
```

2. No additional system dependencies required

3. Create and activate a virtual environment:
```bash
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

4. Install Python dependencies:
```bash
pip install -r requirements.txt
```

5. Set up environment variables:
```bash
cp .env.sample .env
```

Edit `.env` and add your API keys:
```
# Required
ALPACA_API_KEY=your-alpaca-api-key
ALPACA_SECRET_KEY=your-alpaca-secret-key
ALPACA_API_URL=https://api.alpaca.markets  # or https://paper-api.alpaca.markets for paper trading

# Optional (for enhanced features)
# FMP_API_KEY=your-fmp-api-key
# OPENAI_API_KEY=your-openai-api-key
```

## Usage

### Basic Usage

Generate a report for the last 30 days:
```bash
python src/alpaca_trade_report.py --start_date 2024-12-26 --end_date 2025-01-26 --language en
```

Generate a report for the default period (last 30 days):
```bash
python src/alpaca_trade_report.py
```

### Command-line Arguments

- `--start_date`: Start date for analysis (YYYY-MM-DD) - defaults to 30 days ago
- `--end_date`: End date for analysis (YYYY-MM-DD) - defaults to today
- `--language`: Report language (`en` for English, `ja` for Japanese) - defaults to English

## Output Files

The tool generates two types of reports:

1. **CSV Report**: `reports/alpaca_trade_report_YYYY-MM-DD_YYYY-MM-DD.csv`
   - Detailed trade-by-trade analysis
   - Entry/exit prices and dates
   - Profit/loss calculations
   - Earnings information (if FMP API available)

2. **HTML Report**: `reports/portfolio_report_YYYY-MM-DD_to_YYYY-MM-DD.html`
   - Interactive dashboard with dark theme
   - Performance charts (equity curve, drawdown, monthly returns)
   - Sortable tables with all trades
   - Key performance metrics summary
   - Enhanced analysis features (with optional APIs)

## API Requirements

### Alpaca API (Required)
- Sign up at [Alpaca](https://alpaca.markets/)
- Both live and paper trading accounts are supported
- Free tier is sufficient for personal use

### Financial Modeling Prep API (Optional)
- Sign up at [Financial Modeling Prep](https://financialmodelingprep.com/)
- Used for earnings calendar and company profile data
- The tool runs in degraded mode without this API (basic trade analysis only)
- Free tier: 250 calls/day
- Starter: 300 calls/minute
- Premium: 750 calls/minute

### OpenAI API (Optional)
- Used for AI-powered trade analysis features
- Sign up at [OpenAI](https://platform.openai.com/)
- Not required for basic functionality

## Performance Metrics

The tool calculates and displays:
- **Total Return**: Overall portfolio performance
- **CAGR**: Compound Annual Growth Rate
- **Win Rate**: Percentage of profitable trades
- **Sharpe Ratio**: Risk-adjusted returns
- **Maximum Drawdown**: Largest peak-to-trough decline
- **Average Win/Loss**: Mean profit on winning/losing trades
- **Profit Factor**: Ratio of gross profits to gross losses

## Development

### Code Formatting
```bash
black src/
isort src/
```

### Linting
```bash
flake8 src/
mypy src/
```

### Testing
```bash
pytest
pytest -v  # Verbose output
```

Note: Test suite is currently minimal and should be expanded.

### API Rate Limits
- The tool implements automatic rate limiting for FMP API
- If you hit rate limits, the tool will automatically slow down requests
- Consider upgrading your FMP plan for faster processing

### Memory Issues
For large date ranges with many trades:
- Process data in smaller chunks
- Increase Python's memory limit if needed

## Troubleshooting

### Missing API Keys
- **FMP API Key Missing**: The tool will run in degraded mode, skipping earnings-related analysis
- **OpenAI API Key Missing**: AI-powered features will be disabled, but core functionality remains
- **Alpaca API Key Missing**: The tool cannot function without valid Alpaca credentials

### Common Issues
- **401 Unauthorized**: Check your API keys are correct and active
- **Rate Limiting**: Tool automatically handles FMP rate limits with exponential backoff
- **Empty Reports**: Ensure your date range contains actual trades in your Alpaca account

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for informational purposes only. It is not financial advice. Always do your own research and consider consulting with a financial advisor before making investment decisions.