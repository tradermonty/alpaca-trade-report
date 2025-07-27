import argparse
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os
from collections import defaultdict
from typing import Optional, List
import logging
from tqdm import tqdm
import plotly.graph_objs as go
from plotly.offline import plot
import webbrowser
import alpaca_trade_api as tradeapi
from openai import OpenAI
from fmp_data_fetcher import FMPDataFetcher
import markdown


# Load environment variables
load_dotenv()
FMP_API_KEY = os.getenv('FMP_API_KEY')
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
ALPACA_API_URL = os.getenv('ALPACA_API_URL', 'https://paper-api.alpaca.markets')

# Require Alpaca keys for core functionality, but continue if missing to allow offline testing
if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    print("Warning: Alpaca API keys not configured. Some live-account features may be disabled.")

# FMP key is optional – data-enrichment steps will be skipped without it

class TradeReport:
    # Dark mode color settings
    DARK_THEME = {
        'bg_color': '#1e293b',
        'plot_bg_color': '#1e293b',
        'grid_color': '#334155',
        'text_color': '#e2e8f0',
        'line_color': '#60a5fa',
        'profit_color': '#22c55e',
        'loss_color': '#ef4444'
    }

    def __init__(self, start_date, end_date, stop_loss=6, trail_stop_ma=21,
                 max_holding_days=90, initial_capital=10000, 
                 risk_limit=6, partial_profit=True, language='en', 
                 pre_earnings_change=-10):
        """Initialize backtest"""
        # Check date validity
        current_date = datetime.now()
        end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_date_dt > current_date:
            print(f"Warning: End date ({end_date}) is in the future. Using current date instead.")
            self.end_date = current_date.strftime('%Y-%m-%d')
        else:
            self.end_date = end_date
        
        self.start_date = start_date
        self.stop_loss = stop_loss
        self.trail_stop_ma = trail_stop_ma
        self.max_holding_days = max_holding_days
        self.initial_capital = initial_capital  # Set as initial value
        self.risk_limit = risk_limit
        self.partial_profit = partial_profit
        # Initialize FMP client (optional)
        try:
            self.fmp_client = FMPDataFetcher()
            if getattr(self.fmp_client, 'disabled', False):
                from fmp_data_fetcher import NullFMPDataFetcher
                self.fmp_client = NullFMPDataFetcher()
        except Exception:
            from fmp_data_fetcher import NullFMPDataFetcher
            self.fmp_client = NullFMPDataFetcher()
        self.language = language
        self.pre_earnings_change = pre_earnings_change
        
        # For trade recording
        self.trades = []
        self.positions = []
        self.equity_curve = []
        
        # Get initial capital from Alpaca API (use initial value on error)
        try:
            self.initial_capital = self.get_account_equity_at_date(start_date)
            print(f"Initial capital: ${self.initial_capital:,.2f} (as of {start_date})")
        except Exception as e:
            print(f"Failed to get initial capital: {str(e)}")
            print(f"Using default value: ${self.initial_capital:,.2f}")
        

    def _load_api_key(self):
        """Load FMP API key"""
        load_dotenv()
        api_key = os.getenv('FMP_API_KEY')
        if not api_key:
            raise ValueError("FMP_API_KEY is not set in .env file")
        return api_key

    def get_earnings_data(self):
        """FMPから決算データを取得してEODHD形式に変換"""
        # Skip if FMP client disabled
        if self.fmp_client is None or self.fmp_client.__class__.__name__ == "NullFMPDataFetcher":
            print("FMP API not configured – skipping earnings data retrieval.")
            return {"earnings": []}
        print(f"\n1. 決算データの取得を開始 ({self.start_date} から {self.end_date})")
        
        try:
            # Get earnings calendar using FMP client
            fmp_earnings_data = self.fmp_client.get_earnings_calendar(
                from_date=self.start_date,
                to_date=self.end_date,
                us_only=True
            )
            
            print(f"Data retrieved from FMP: {len(fmp_earnings_data)} records")
            
            # Convert FMP data to EODHD format
            converted_earnings = []
            for earning in fmp_earnings_data:
                try:
                    # Calculate surprise rate
                    eps_actual = earning.get('epsActual')
                    eps_estimate = earning.get('epsEstimate') or earning.get('epsEstimated')
                    
                    percent = 0
                    if eps_actual is not None and eps_estimate is not None and eps_estimate != 0:
                        try:
                            actual_val = float(eps_actual)
                            estimate_val = float(eps_estimate)
                            if estimate_val != 0:
                                percent = ((actual_val - estimate_val) / abs(estimate_val)) * 100
                        except (ValueError, TypeError):
                            continue
                    
                    # Convert to EODHD format
                    converted_earning = {
                        'code': earning.get('symbol', '') + '.US',
                        'report_date': earning.get('date', ''),
                        'date': earning.get('date', ''),
                        'before_after_market': self._convert_timing(earning.get('time', '')),
                        'currency': 'USD',
                        'actual': eps_actual,
                        'estimate': eps_estimate,
                        'percent': percent,
                        'difference': float(eps_actual or 0) - float(eps_estimate or 0) if eps_actual is not None and eps_estimate is not None else 0,
                        'revenue_actual': earning.get('revenueActual'),
                        'revenue_estimate': earning.get('revenueEstimate'),
                        'updated_from_date': earning.get('updatedFromDate', earning.get('date', '')),
                        'fiscal_date_ending': earning.get('fiscalDateEnding', earning.get('date', ''))
                    }
                    
                    converted_earnings.append(converted_earning)
                    
                except Exception as e:
                    print(f"Conversion error ({earning.get('symbol', 'Unknown')}): {str(e)}")
                    continue
            
            print(f"Data after conversion: {len(converted_earnings)} records")
            
            # Return in EODHD format
            return {'earnings': converted_earnings}
            
        except Exception as e:
            print(f"Error occurred while retrieving earnings data: {str(e)}")
            raise
    
    def _convert_timing(self, fmp_timing):
        """Convert FMP timing information to EODHD format"""
        if not fmp_timing:
            return None
        
        timing_lower = fmp_timing.lower()
        if any(keyword in timing_lower for keyword in ['before', 'pre', 'bmo']):
            return 'BeforeMarket'
        elif any(keyword in timing_lower for keyword in ['after', 'post', 'amc']):
            return 'AfterMarket'
        else:
            return None

    def get_historical_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        Get stock price data for specified symbol using FMP API
        """
        try:
            print(f"Starting price data retrieval: {symbol}")  # Debug log
            print(f"Period: {start_date} to {end_date}")  # Debug log
            
            # Get historical data using FMP client
            price_data = self.fmp_client.get_historical_price_data(
                symbol=symbol,
                from_date=start_date,
                to_date=end_date
            )
            
            if not price_data:
                logging.warning(f"No data: {symbol}")
                return None
                
            # Convert to DataFrame
            df = pd.DataFrame(price_data)
            print(f"Number of records retrieved: {len(df)}")  # Debug log
            
            # Handle FMP date format
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            
            # Remove duplicate data
            df = df[~df.index.duplicated(keep='first')]
            
            # Convert FMP column names to standard format
            df.rename(columns={
                'adjClose': 'Close',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'volume': 'Volume'
            }, inplace=True)
            
            # Add 21-day moving average
            df['MA21'] = df['Close'].rolling(window=21).mean()
            
            logging.info(f"Success: {symbol}")
            return df
            
        except Exception as e:
            logging.error(f"Unexpected error {symbol}: {str(e)}")
            return None

    def determine_trade_date(self, report_date, market_timing):
        """Determine trade date"""
        report_date = datetime.strptime(report_date, "%Y-%m-%d")
        if market_timing == "BeforeMarket":
            return report_date.strftime("%Y-%m-%d")
        else:
            # Treat all non-BeforeMarket as AfterMarket
            next_date = report_date + timedelta(days=1)
            return next_date.strftime("%Y-%m-%d")

    def filter_earnings_data(self, data):
        """Filter earnings data"""
        if 'earnings' not in data:
            raise KeyError("'earnings' key not found in JSON data")
        
        total_records = len(data['earnings'])
        print(f"\nStarting filtering process (total {total_records} records)")
        
        # Stage 1 filtering
        print("\n=== Stage 1 Filtering ===")
        print("Conditions:")
        print("1. .US stocks only")
        print("2. Surprise rate >= 5%")
        print("3. Positive actual value")
        if self.mid_small_only:
            print("4. Market cap < $100 billion")
        
        first_filtered = []
        skipped_count = 0
        
        # Display progress bar using tqdm
        for earning in tqdm(data['earnings'], desc="Stage 1 Filtering", total=total_records):
            try:
                # 1. Check for .US symbols
                if not earning['code'].endswith('.US'):
                    skipped_count += 1
                    continue
                
                # Filter target symbols
                if self.target_symbols is not None:
                    symbol = earning['code'][:-3]  # Remove .US
                    if symbol not in self.target_symbols:
                        skipped_count += 1
                        continue
                
                # 2&3. Check surprise rate and actual values
                try:
                    percent = float(earning.get('percent', 0))
                    actual = float(earning.get('actual', 0))
                except (ValueError, TypeError):
                    skipped_count += 1
                    continue
                
                if percent < 5 or actual <= 0:
                    skipped_count += 1
                    continue
                
                first_filtered.append(earning)
                
            except Exception as e:
                tqdm.write(f"\nError processing symbol ({earning.get('code', 'Unknown')}): {str(e)}")
                skipped_count += 1
                continue
        
        print(f"\nStage 1 Filtering Results:")
        print(f"- Total processed: {total_records}")
        print(f"- Conditions met: {len(first_filtered)}")
        print(f"- Skipped: {skipped_count}")
        
        # Stage 2 Filtering
        print("\n=== Stage 2 Filtering ===")
        print("Conditions:")
        print("4. Gap ratio 0% or higher")
        print("5. Stock price $10 or higher")
        print("6. 20-day average volume >= 200,000 shares")
        print(f"7. Price change rate over past 20 days {self.pre_earnings_change}% or higher")
        
        date_stocks = defaultdict(list)
        processed_count = 0
        skipped_count = 0
        total_second_stage = len(first_filtered)
        
        # Display progress bar using tqdm
        for earning in tqdm(first_filtered, desc="Stage 2 Filtering", total=total_second_stage):
            try:
                market_timing = earning.get('before_after_market')
                trade_date = self.determine_trade_date(
                    earning['report_date'], 
                    market_timing
                )
                
                # Remove .US from symbol code
                symbol = earning['code'][:-3]
                
                tqdm.write(f"\nProcessing: {symbol}")
                tqdm.write(f"- Surprise rate: {float(earning['percent']):.1f}%")
                
                # Extend stock price data period (to get past 20 days of data)
                stock_data = self.get_historical_data(
                    symbol,
                    (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d"),
                    (datetime.strptime(trade_date, "%Y-%m-%d") + 
                     timedelta(days=self.max_holding_days + 30)).strftime("%Y-%m-%d")
                )
                
                if stock_data is None or stock_data.empty:
                    tqdm.write("- Skip: No price data")
                    skipped_count += 1
                    continue

                # Calculate price change rate for past 20 days
                try:
                    current_close = stock_data.loc[:trade_date].iloc[-1]['Close']
                    price_20d_ago = stock_data.loc[:trade_date].iloc[-20]['Close']
                    price_change = ((current_close - price_20d_ago) / price_20d_ago) * 100
                    tqdm.write(f"- Past 20-day price change rate: {price_change:.1f}%")
                except (KeyError, IndexError):
                    tqdm.write("- Skip: Insufficient 20-day price data")
                    skipped_count += 1
                    continue

                # Price change rate filtering
                if price_change < self.pre_earnings_change:
                    tqdm.write(f"- Skip: Price change < {self.pre_earnings_change}%")
                    skipped_count += 1
                    continue

                # Get trade date data
                try:
                    trade_date_data = stock_data.loc[trade_date]
                    prev_day_data = stock_data.loc[:trade_date].iloc[-2]
                except (KeyError, IndexError):
                    tqdm.write("- Skip: No trade date data")
                    skipped_count += 1
                    continue
                
                # Calculate gap rate
                gap = ((trade_date_data['Open'] - prev_day_data['Close']) / prev_day_data['Close']) * 100
                
                # Calculate average volume
                avg_volume = stock_data['Volume'].tail(20).mean()
                
                tqdm.write(f"- Gap rate: {gap:.1f}%")
                tqdm.write(f"- Stock price: ${trade_date_data['Open']:.2f}")
                tqdm.write(f"- Average volume: {avg_volume:,.0f}")
                
                # Check filtering conditions
                if gap < 0:
                    tqdm.write("- Skip: Negative gap rate")
                    skipped_count += 1
                    continue
                if trade_date_data['Open'] < 10:
                    tqdm.write("- Skip: Stock price < $10")
                    skipped_count += 1
                    continue
                if avg_volume < 200000:
                    tqdm.write("- Skip: Insufficient volume")
                    skipped_count += 1
                    continue
                
                # Save data
                stock_data = {
                    'code': symbol,
                    'report_date': earning['report_date'],
                    'trade_date': trade_date,
                    'price': trade_date_data['Open'],  # Revert from 'entry_price' to 'price'
                    'entry_price': trade_date_data['Open'],
                    'prev_close': prev_day_data['Close'],  # Also add prev_close
                    'gap': gap,
                    'volume': trade_date_data['Volume'],
                    'avg_volume': avg_volume,
                    'percent': float(earning['percent'])
                }
                
                date_stocks[trade_date].append(stock_data)
                processed_count += 1
                tqdm.write("→ Conditions met")
                
            except Exception as e:
                tqdm.write(f"\nError processing symbol ({earning.get('code', 'Unknown')}): {str(e)}")
                skipped_count += 1
                continue
        
        # Select top 6 stocks for each trade_date
        selected_stocks = []
        print("\nDaily selections (top 5 stocks):")
        for trade_date in sorted(date_stocks.keys()):
            # Sort by percent in descending order
            date_stocks[trade_date].sort(key=lambda x: float(x['percent']), reverse=True)
            # Select top 5 stocks
            selected = date_stocks[trade_date][:5]
            selected_stocks.extend(selected)
            
            print(f"\n{trade_date}: {len(selected)} stocks")
            for stock in selected:
                print(f"- {stock['code']}: Surprise {stock['percent']:.1f}%, "
                      f"Gap {stock['gap']:.1f}%")
        
        print(f"\nStage 2 Filtering Results:")
        print(f"- Total processed: {total_second_stage}")
        print(f"- Conditions met: {processed_count}")
        print(f"- Skipped: {skipped_count}")
        print(f"- Final selected stocks: {len(selected_stocks)}")
        
        return selected_stocks


    def calculate_metrics(self):
        """Calculate performance metrics"""
        if not self.trades:
            return None
        
        # Convert trades to DataFrame
        df = pd.DataFrame(self.trades)
        
        # Calculate asset progression
        df['equity'] = self.initial_capital + df['pnl'].cumsum()
        
        # Calculate maximum drawdown (asset-based)
        df['running_max'] = df['equity'].cummax()
        df['drawdown'] = (df['running_max'] - df['equity']) / df['running_max'] * 100
        max_drawdown_pct = df['drawdown'].max()
        
        # Calculate basic metrics
        total_trades = len(df)
        winning_trades = len(df[df['pnl_rate'] > 0])  # Use pnl_rate instead of pnl
        losing_trades = len(df[df['pnl_rate'] <= 0])
        
        # Win rate
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Average win/loss rate
        avg_win_loss_rate = df['pnl_rate'].mean()
        
        # Average holding period
        avg_holding_period = df['holding_period'].mean()
        
        # Profit factor
        total_profit = df[df['pnl'] > 0]['pnl'].sum()
        total_loss = abs(df[df['pnl'] <= 0]['pnl'].sum())
        profit_factor = total_profit / total_loss if total_loss != 0 else float('inf')
        
        # Calculate CAGR
        start_date = pd.to_datetime(df['entry_date'].min())
        end_date = pd.to_datetime(df['exit_date'].max())
        years = (end_date - start_date).days / 365.25
        final_capital = self.initial_capital + df['pnl'].sum()
        
        if years > 0:
            cagr = ((final_capital / self.initial_capital) ** (1/years) - 1) * 100
        else:
            cagr = 0
        
        # Aggregate exit reasons
        exit_reasons = df['exit_reason'].value_counts()
        
        # Fix annual performance calculation
        df['year'] = pd.to_datetime(df['entry_date']).dt.strftime('%Y')
        df['cumulative_pnl'] = df['pnl'].cumsum()
        
        # Calculate annual profit/loss
        yearly_pnl = df.groupby('year')['pnl'].sum().reset_index()
        
        # Calculate starting capital for each year
        yearly_returns = []
        current_capital = self.initial_capital
        
        for year in yearly_pnl['year'].values:
            year_pnl = yearly_pnl[yearly_pnl['year'] == year]['pnl'].values[0]
            return_pct = (year_pnl / current_capital) * 100
            
            yearly_returns.append({
                'year': year,
                'pnl': year_pnl,
                'return_pct': return_pct,
                'start_capital': current_capital,
                'end_capital': current_capital + year_pnl
            })
            
            # Update starting capital for next year
            current_capital += year_pnl

        # Fix Expected Value calculation
        avg_win = df[df['pnl_rate'] > 0]['pnl'].mean() if len(df[df['pnl_rate'] > 0]) > 0 else 0  # Average profit for winning trades
        avg_loss = df[df['pnl_rate'] < 0]['pnl'].mean() if len(df[df['pnl_rate'] < 0]) > 0 else 0  # Average loss for losing trades
        win_rate_decimal = winning_trades / total_trades if total_trades > 0 else 0  # Win rate as decimal
        expected_value = (win_rate_decimal * avg_win) + ((1 - win_rate_decimal) * avg_loss)
        
        # Calculate Win/Loss Ratio
        win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        # Calculate average trade position value
        avg_position_size = df['entry_price'].mean() * df['shares'].mean()
        
        # Calculate Expected Value as percentage relative to position size
        expected_value_pct = (expected_value / avg_position_size * 100) if avg_position_size > 0 else 0
        
        # Calculate Calmar Ratio
        calmar_ratio = abs(cagr / max_drawdown_pct) if max_drawdown_pct != 0 else float('inf')
        
        # Calculate Pareto Ratio (based on 80/20 rule)
        sorted_profits = df[df['pnl'] > 0]['pnl'].sort_values(ascending=False)
        top_20_percent = sorted_profits.head(int(len(sorted_profits) * 0.2))
        pareto_ratio = (top_20_percent.sum() / sorted_profits.sum() * 100) if not sorted_profits.empty else 0
        
        metrics = {
            'number_of_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'avg_win_loss_rate': round(avg_win_loss_rate, 2),
            'avg_holding_period': round(avg_holding_period, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown_pct': round(max_drawdown_pct, 2),
            'initial_capital': self.initial_capital,
            'final_capital': round(final_capital, 2),
            'total_return_pct': round((final_capital - self.initial_capital) / self.initial_capital * 100, 2),
            'exit_reasons': exit_reasons.to_dict(),
            'cagr': round(cagr, 2),
            'yearly_returns': yearly_returns,
            'expected_value': round(expected_value, 2),
            'expected_value_pct': round(expected_value_pct, 2),
            'avg_position_size': round(avg_position_size, 2),
            'calmar_ratio': round(calmar_ratio, 2),
            'pareto_ratio': round(pareto_ratio, 1),
            'avg_win': round(avg_win, 2) if not pd.isna(avg_win) else 0,
            'avg_loss': round(avg_loss, 2) if not pd.isna(avg_loss) else 0,
            'win_loss_ratio': round(win_loss_ratio, 2)
        }
        
        # Display results
        print("\nBacktest Results:")
        print(f"Number of trades: {metrics['number_of_trades']}")
        print(f"Ave win/loss rate: {metrics['avg_win_loss_rate']:.2f}%")
        print(f"Ave holding period: {metrics['avg_holding_period']} days")
        print(f"Win rate: {metrics['win_rate']:.1f}%")
        print(f"Profit factor: {metrics['profit_factor']}")
        print(f"Max drawdown: {metrics['max_drawdown_pct']:.2f}%")
        print(f"\nExit reason breakdown:")
        for reason, count in metrics['exit_reasons'].items():
            print(f"- {reason}: {count}")
        print(f"\nAsset progression:")
        print(f"Initial capital: ${metrics['initial_capital']:,.2f}")
        print(f"Final capital: ${metrics['final_capital']:,.2f}")
        print(f"Total return: {metrics['total_return_pct']:.2f}%")
        print(f"Average position size: ${metrics['avg_position_size']:,.2f}")
        print(f"Expected Value: {metrics['expected_value_pct']:.2f}%")
        print(f"Calmar Ratio: {metrics['calmar_ratio']:.2f}")
        print(f"Pareto Ratio: {metrics['pareto_ratio']:.1f}%")
        
        return metrics

    def generate_report(self):
        """Generate trade report"""
        if not self.trades:
            print("No trade records available")
            return
                
        # Output trade records to CSV file
        output_file = f"reports/alpaca_trade_report_{self.start_date}_{self.end_date}.csv"
        df = pd.DataFrame(self.trades)
        df = df[['entry_date', 'exit_date', 'ticker', 'holding_period', 
                 'entry_price', 'exit_price', 'pnl_rate', 'pnl', 'exit_reason']]
        df.to_csv(output_file, index=False)
        print(f"\nTrade records saved to {output_file}")

    def check_risk_management(self, current_date, current_capital):
        """
        Check if past month P&L is below -risk_limit% of total assets
        """
        if not self.trades:
            return True  # No restriction if no trade history
        
        # Calculate date 1 month ago from current date
        one_month_ago = (datetime.strptime(current_date, "%Y-%m-%d") - 
                        timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Extract confirmed trades from past 1 month
        recent_trades = [
            trade for trade in self.trades
            if trade['exit_date'] >= one_month_ago and trade['exit_date'] <= current_date
        ]
        
        if not recent_trades:
            return True  # No restriction if no confirmed trades in past 1 month
        
        # Calculate total profit/loss for past 1 month
        total_pnl = sum(trade['pnl'] for trade in recent_trades)
        
        # Calculate profit/loss rate (ratio to current total assets)
        pnl_ratio = (total_pnl / current_capital) * 100

        print(f"\nRisk management check ({current_date}):")
        print(f"- Past month P&L: ${total_pnl:,.2f}")
        print(f"- Current total assets: ${current_capital:,.2f}")
        print(f"- Past month P&L: ${total_pnl:,.2f}")
        print(f"- P&L ratio: {pnl_ratio:.2f}%")
        
        # Return False if below -risk_limit%
        if pnl_ratio < -self.risk_limit:
            print(f"※ Restricting new trades as profit/loss ratio is below -{self.risk_limit}%")
            return False
        
        return True

    def get_text(self, key):
        """Get text according to language"""
        texts = {
            'report_title': {
                'ja': 'Alpacaトレードレポート',
                'en': 'Alpaca Trade Report'
            },
            'total_trades': {
                'ja': '総トレード数',
                'en': 'Total Trades'
            },
            'win_rate': {
                'ja': '勝率',
                'en': 'Win Rate'
            },
            'avg_pnl': {
                'ja': '平均損益率',
                'en': 'Avg. PnL'
            },
            'profit_factor': {
                'ja': 'プロフィットファクター',
                'en': 'Profit Factor'
            },
            'max_drawdown': {
                'ja': '最大ドローダウン',
                'en': 'Max Drawdown'
            },
            'total_return': {
                'ja': '総リターン',
                'en': 'Total Return'
            },
            'cumulative_pnl': {
                'ja': '累計損益推移',
                'en': 'Cumulative PnL'
            },
            'pnl_distribution': {
                'ja': '損益率分布',
                'en': 'PnL Distribution'
            },
            'yearly_performance': {
                'ja': '年間パフォーマンス',
                'en': 'Yearly Performance'
            },
            'trade_history': {
                'ja': 'トレード履歴',
                'en': 'Trade History'
            },
            'symbol': {
                'ja': '銘柄',
                'en': 'Symbol'
            },
            'entry_date': {
                'ja': 'エントリー日時',
                'en': 'Entry Date'
            },
            'entry_price': {
                'ja': 'エントリー価格',
                'en': 'Entry Price'
            },
            'exit_date': {
                'ja': '決済日時',
                'en': 'Exit Date'
            },
            'exit_price': {
                'ja': '決済価格',
                'en': 'Exit Price'
            },
            'holding_period': {
                'ja': '保有期間',
                'en': 'Holding Period'
            },
            'shares': {
                'ja': '株数',
                'en': 'Shares'
            },
            'pnl_rate': {
                'ja': '損益率',
                'en': 'PnL Rate'
            },
            'pnl': {
                'ja': '損益',
                'en': 'PnL'
            },
            'exit_reason': {
                'ja': '決済理由',
                'en': 'Exit Reason'
            },
            'profit': {
                'ja': '利益',
                'en': 'Profit'
            },
            'loss': {
                'ja': '損失',
                'en': 'Loss'
            },
            'date': {
                'ja': '日時',
                'en': 'Date'
            },
            'pnl_amount': {
                'ja': '損益 ($)',
                'en': 'PnL ($)'
            },
            'year': {
                'ja': '年',
                'en': 'Year'
            },
            'return_pct': {
                'en': 'Return (%)',
                'ja': 'リターン (%)'
            },
            'days': {
                'ja': '日',
                'en': ' days'
            },
            'number_of_trades': {
                'ja': '取引数',
                'en': 'Number of Trades'
            },
            'drawdown': {
                'ja': 'ドローダウン',
                'en': 'Drawdown'
            },
            'drawdown_chart': {
                'ja': 'ドローダウンチャート',
                'en': 'Drawdown Chart'
            },
            'drawdown_amount': {
                'ja': 'ドローダウン額 ($)',
                'en': 'Drawdown Amount ($)'
            },
            'drawdown_pct': {
                'en': 'Drawdown (%)',
                'ja': 'ドローダウン (%)'
            },
            'monthly_performance_heatmap': {
                'ja': '月次パフォーマンスヒートマップ',
                'en': 'Monthly Performance Heatmap'
            },
            'gap_performance': {
                'ja': 'ギャップサイズ別パフォーマンス',
                'en': 'Performance by Gap Size'
            },
            'pre_earnings_trend_performance': {
                'ja': '決算前トレンド別パフォーマンス',
                'en': 'Performance by Pre-Earnings Trend'
            },
            'average_return': {
                'ja': '平均リターン',
                'en': 'Average Return'
            },
            'number_of_trades_gap': {
                'ja': 'ギャップサイズ別トレード数',
                'en': 'Number of Trades by Gap Size'
            },
            'gap_size': {
                'ja': 'ギャップサイズ',
                'en': 'Gap Size'
            },
            'price_change': {
                'ja': '価格変化率',
                'en': 'Price Change'
            },
            'trend_bin': {
                'ja': 'トレンドビン',
                'en': 'Trend Bin'
            },
            'trend_performance': {
                'ja': 'トレンド別パフォーマンス',
                'en': 'Trend Performance'
            },
            'month': {
                'ja': '月',
                'en': 'Month'
            },
            'analysis_title': {
                'ja': '詳細分析',
                'en': 'Detailed Analysis'
            },
            'monthly_performance': {
                'ja': '月次パフォーマンス',
                'en': 'Monthly Performance'
            },
            'gap_analysis': {
                'ja': 'ギャップ分析',
                'en': 'Gap Analysis'
            },
            'trend_analysis': {
                'ja': 'トレンド分析',
                'en': 'Trend Analysis'
            },
            'trade_report': {
                'ja': 'Alpacaトレードレポート',
                'en': 'Alpaca Trade Report'
            },
            'equity_curve': {
                'ja': '資産推移',
                'en': 'Equity Curve'
            },
            'cumulative_pnl': {
                'ja': '累積損益',
                'en': 'Cumulative P&L'
            },
            'return_distribution': {
                'ja': 'リターン分布',
                'en': 'Return Distribution'
            },
            'pnl_distribution': {
                'ja': '損益分布',
                'en': 'P&L Distribution'
            },
            'yearly_performance_chart': {
                'ja': '年間パフォーマンス',
                'en': 'Yearly Performance'
            },
            'yearly_performance': {
                'ja': '年間パフォーマンス',
                'en': 'Yearly Performance'
            },
            'position_value_history': {
                'ja': 'ポジション金額推移',
                'en': 'Position Value History'
            },
            'sector_performance': {
                'ja': 'セクター別パフォーマンス',
                'en': 'Sector Performance'
            },
            'industry_performance': {
                'ja': '業種別パフォーマンス（上位15業種）',
                'en': 'Industry Performance (Top 15)'
            },
            'sector': {
                'ja': 'セクター',
                'en': 'Sector'
            },
            'industry': {
                'ja': '業種',
                'en': 'Industry'
            },
            'eps_analysis': {
                'ja': 'EPSサプライズ分析',
                'en': 'EPS Surprise Analysis'
            },
            'eps_growth_performance': {
                'ja': 'EPS成長率パフォーマンス',
                'en': 'EPS Growth Performance'
            },
            'eps_acceleration_performance': {
                'ja': 'EPS成長率加速度パフォーマンス',
                'en': 'EPS Growth Acceleration Performance'
            },
            'eps_surprise': {
                'ja': 'EPSサプライズ',
                'en': 'EPS Surprise'
            },
            'eps_growth': {
                'ja': 'EPS成長率',
                'en': 'EPS Growth'
            },
            'eps_acceleration': {
                'ja': '成長率加速度',
                'en': 'Growth Acceleration'
            },
            'eps_surprise_performance': {
                'ja': 'EPSサプライズ別パフォーマンス',
                'en': 'EPS Surprise Performance'
            },
            'volume_trend_analysis': {
                'ja': '出来高トレンド分析',
                'en': 'Volume Trend Analysis'
            },
            'volume_category': {
                'ja': '出来高カテゴリ',
                'en': 'Volume Category'
            },
            'ma200_analysis': {
                'ja': 'MA200分析',
                'en': 'MA200 Analysis'
            },
            'ma50_analysis': {
                'ja': 'MA50分析',
                'en': 'MA50 Analysis'
            },
            'ma200_category': {
                'ja': 'MA200カテゴリ',
                'en': 'MA200 Category'
            },
            'ma50_category': {
                'ja': 'MA50カテゴリ',
                'en': 'MA50 Category'
            },
            'expected_value': {
                'ja': '期待値（%）',
                'en': 'Expected Value (%)'
            },
            'calmar_ratio': {
                'ja': 'カルマー比率',
                'en': 'Calmar Ratio'
            },
            'pareto_ratio': {
                'ja': 'パレート比率',
                'en': 'Pareto Ratio'
            },
            'period': {
                'ja': '期間',
                'en': 'Period'
            },
            'performance_metrics': {
                'ja': 'パフォーマンス指標',
                'en': 'Performance Metrics'
            }
        }
        return texts[key][self.language]

    def generate_html_report(self):
        """Generate HTML report"""
        if not self.trades:
            print("No trade records found")
            return
        
        # Calculate metrics
        metrics = self.calculate_metrics()
        
        # Convert trade records to DataFrame
        df = pd.DataFrame(self.trades)
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        df = df.sort_values('entry_date')
        df['cumulative_pnl'] = df['pnl'].cumsum()
        
        # Get and add sector information
        print("\nRetrieving sector information...")
        sectors = {}
        
        for ticker in tqdm(df['ticker'].unique(), desc="Retrieving sector info"):
            try:
                # Get company profile using FMP client
                profile_data = self.fmp_client.get_company_profile(ticker)
                if profile_data:
                    sectors[ticker] = {
                        'sector': profile_data.get('sector', 'Unknown'),
                        'industry': profile_data.get('industry', 'Unknown')
                    }
                else:
                    sectors[ticker] = {
                        'sector': 'Unknown',
                        'industry': 'Unknown'
                    }
            except Exception as e:
                print(f"Error retrieving sector information for {ticker}: {str(e)}")
                sectors[ticker] = {
                    'sector': 'Unknown',
                    'industry': 'Unknown'
                }
        
        # Add sector information to DataFrame
        df['sector'] = df['ticker'].map(lambda x: sectors.get(x, {}).get('sector', 'Unknown'))
        df['industry'] = df['ticker'].map(lambda x: sectors.get(x, {}).get('industry', 'Unknown'))
        
        # Generate analysis charts
        analysis_charts = self.generate_analysis_charts(df)
        
        # AI analysis section using OpenAI
        ai_analysis_section = self._generate_ai_analysis(metrics)
        
        # Calculate equity curve
        df['equity'] = self.initial_capital + df['cumulative_pnl']
        df['equity_pct'] = (df['equity'] / self.initial_capital - 1) * 100
        
        # Cumulative P&L chart
        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=df['entry_date'],
            y=df['equity_pct'],
            mode='lines',
            name=self.get_text('cumulative_pnl'),
            line=dict(color=TradeReport.DARK_THEME['profit_color'])
        ))
        
        fig_equity.update_layout(
            title=self.get_text('equity_curve'),
            xaxis_title=self.get_text('date'),
            yaxis_title=self.get_text('return_pct'),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color']
        )
        
        equity_chart = plot(fig_equity, output_type='div', include_plotlyjs=False)
        
        # Drawdown chart
        df['running_max'] = df['equity'].cummax()
        df['drawdown'] = (df['running_max'] - df['equity']) / df['running_max'] * 100
        
        fig_drawdown = go.Figure()
        fig_drawdown.add_trace(go.Scatter(
            x=df['entry_date'],
            y=-df['drawdown'],
            mode='lines',
            name=self.get_text('drawdown'),
            line=dict(color=TradeReport.DARK_THEME['loss_color'])
        ))
        
        fig_drawdown.update_layout(
            title=self.get_text('drawdown_chart'),
            xaxis_title=self.get_text('date'),
            yaxis_title=self.get_text('drawdown_pct'),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color']
        )
        
        drawdown_chart = plot(fig_drawdown, output_type='div', include_plotlyjs=False)
        
        # Return distribution chart
        fig_dist = go.Figure()

        # Create separate histograms for positive and negative returns
        positive_returns = df[df['pnl_rate'] >= 0]['pnl_rate']
        negative_returns = df[df['pnl_rate'] < 0]['pnl_rate']

        # Histogram for negative returns
        fig_dist.add_trace(go.Histogram(
            x=negative_returns,
            xbins=dict(
                start=-10,  # From -10%
                end=0,      # Up to 0%
                size=2.5    # Create bins every 2.5%
            ),
            name='Negative Returns',
            marker_color=TradeReport.DARK_THEME['loss_color'],
            hovertemplate='Return: %{x:.1f}%<br>Number of trades: %{y}<extra></extra>'
        ))

        # Histogram for positive returns
        fig_dist.add_trace(go.Histogram(
            x=positive_returns,
            xbins=dict(
                start=0,    # From 0%
                end=100,    # Up to 100%
                size=2.5    # Create bins every 2.5%
            ),
            name='Positive Returns',
            marker_color=TradeReport.DARK_THEME['profit_color'],
            hovertemplate='Return: %{x:.1f}%<br>Number of trades: %{y}<extra></extra>'
        ))

        fig_dist.update_layout(
            title=self.get_text('return_distribution'),
            xaxis_title=self.get_text('return_pct'),
            yaxis_title=self.get_text('number_of_trades'),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color'],
            bargap=0.1,
            showlegend=False,
            barmode='overlay'  # Display histograms overlaid
        )
        
        distribution_chart = plot(fig_dist, output_type='div', include_plotlyjs=False)

        # Annual performance chart
        yearly_data = pd.DataFrame(metrics['yearly_returns'])
        fig_yearly = go.Figure()
        fig_yearly.add_trace(go.Bar(
            x=yearly_data['year'],
            y=yearly_data['return_pct'],
            marker_color=[
                TradeReport.DARK_THEME['profit_color'] if x >= 0 
                else TradeReport.DARK_THEME['loss_color'] 
                for x in yearly_data['return_pct']
            ]
        ))
        
        fig_yearly.update_layout(
            title=self.get_text('yearly_performance'),
            xaxis_title=self.get_text('year'),
            yaxis_title=self.get_text('return_pct'),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color']
        )
        
        yearly_chart = plot(fig_yearly, output_type='div', include_plotlyjs=False)
        
        # HTML template
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Alpaca Trade Report</title>
            <meta charset="UTF-8">
            <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
            <style>
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    margin: 0; 
                    padding: 20px; 
                    background-color: #1e293b; 
                    color: #e2e8f0; 
                    line-height: 1.6;
                }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ 
                    text-align: center; 
                    margin-bottom: 40px; 
                    padding: 20px;
                    background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                    border-radius: 10px;
                }}
                .header h1 {{ 
                    margin: 0; 
                    font-size: 2.5em; 
                    color: #60a5fa; 
                }}
                .header p {{ 
                    margin: 10px 0 0 0; 
                    font-size: 1.2em; 
                    opacity: 0.8; 
                }}
                .section {{ 
                    margin: 30px 0; 
                    padding: 20px; 
                    background-color: #1e293b; 
                    border-radius: 10px; 
                    border: 1px solid #334155;
                }}
                .section h2 {{ 
                    margin-top: 0; 
                    color: #60a5fa; 
                    border-bottom: 2px solid #334155;
                    padding-bottom: 10px;
                }}
                .metrics-grid {{ 
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
                    gap: 15px; 
                }}
                .metric {{ 
                    padding: 15px; 
                    background: linear-gradient(135deg, #374151 0%, #4b5563 100%);
                    border-radius: 8px; 
                    border-left: 4px solid #60a5fa;
                }}
                .metric-label {{ 
                    font-size: 0.9em; 
                    opacity: 0.8; 
                    margin-bottom: 5px; 
                }}
                .metric-value {{ 
                    font-size: 1.4em; 
                    font-weight: bold; 
                }}
                .positive {{ color: #22c55e; }}
                .negative {{ color: #ef4444; }}
                .chart-container {{
                    margin: 20px 0;
                    background-color: #1e293b;
                    padding: 20px;
                    border-radius: 8px;
                }}
                .table-container {{
                    max-height: 400px;
                    overflow-y: auto;
                    border: 1px solid #334155;
                    border-radius: 8px;
                    margin: 10px 0;
                    width: 100%;
                    overflow-x: auto;
                }}
                .sortable-table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                .sortable-table th {{
                    position: sticky;
                    top: 0;
                    background-color: #1e293b;
                    border-bottom: 2px solid #334155;
                    padding: 12px 8px;
                    text-align: left;
                    font-weight: bold;
                    color: #60a5fa;
                    user-select: none;
                    cursor: pointer;
                }}
                .sortable-table th:hover {{
                    background-color: #334155;
                }}
                .sortable-table td {{
                    padding: 10px 8px;
                    border-bottom: 1px solid rgba(51, 65, 85, 0.3);
                }}
                .sortable-table tr:hover {{
                    background-color: rgba(51, 65, 85, 0.3);
                }}
                .profit {{ color: #22c55e; }}
                .loss {{ color: #ef4444; }}
                .analysis-section {{
                    margin: 20px 0;
                }}
                .analysis-section h3 {{
                    color: #60a5fa;
                    margin-bottom: 10px;
                }}
                .asc::after {{
                    content: " ▲";
                }}
                .desc::after {{
                    content: " ▼";
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{self.get_text('trade_report')}</h1>
                    <p>{self.get_text('period')}: {self.start_date} – {self.end_date}</p>
                </div>
                
                <div class="section">
                    <h2>{self.get_text('performance_metrics')}</h2>
                    <div class="metrics-grid">
                        {self._generate_metrics_html(df)}
                    </div>
                </div>
                
                <div class="section">
                    <h2>{self.get_text('equity_curve')}</h2>
                    <div class="chart-container">
                        {equity_chart}
                    </div>
                </div>
                
                <div class="section">
                    <h2>{self.get_text('drawdown_chart')}</h2>
                    <div class="chart-container">
                        {drawdown_chart}
                    </div>
                </div>
                
                <div class="section">
                    <h2>{self.get_text('return_distribution')}</h2>
                    <div class="chart-container">
                        {distribution_chart}
                    </div>
                </div>
                
                <div class="section">
                    <h2>{self.get_text('yearly_performance_chart')}</h2>
                    <div class="chart-container">
                        {yearly_chart}
                    </div>
                </div>
                
                <div class="section">
                    <h2>{self.get_text('analysis_title')}</h2>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('monthly_performance')}</h3>
                        <div class="chart-container">
                            {analysis_charts['monthly']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('sector_performance')}</h3>
                        <div class="chart-container">
                            {analysis_charts['sector']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('industry_performance')}</h3>
                        <div class="chart-container">
                            {analysis_charts['industry']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('gap_analysis')}</h3>
                        <div class="chart-container">
                            {analysis_charts['gap']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('trend_analysis')}</h3>
                        <div class="chart-container">
                            {analysis_charts['trend']}
                        </div>
                    </div>

                    <div class="analysis-section">
                        <h3>{self.get_text('eps_analysis')}</h3>
                        <div class="chart-container">
                            {analysis_charts['eps_surprise']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('eps_growth_performance')}</h3>
                        <div class="chart-container">
                            {analysis_charts['eps_growth']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('eps_acceleration_performance')}</h3>
                        <div class="chart-container">
                            {analysis_charts['eps_acceleration']}
                        </div>
                    </div>
                    <div class="analysis-section">
                        <h3>{self.get_text('volume_trend_analysis')}</h3>
                        <div class="chart-container">
                            {analysis_charts['volume']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('ma200_analysis')}</h3>
                        <div class="chart-container">
                            {analysis_charts['ma200']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>{self.get_text('ma50_analysis')}</h3>
                        <div class="chart-container">
                            {analysis_charts['ma50']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>Market Cap Performance Analysis</h3>
                        <div class="chart-container">
                            {analysis_charts['market_cap']}
                        </div>
                    </div>
                    
                    <div class="analysis-section">
                        <h3>Price Range Performance Analysis</h3>
                        <div class="chart-container">
                            {analysis_charts['price_range']}
                        </div>
                    </div>
                </div>
                
                {ai_analysis_section}

                <div class="section">
                    <h2>{self.get_text('trade_history')}</h2>
                    <div class="table-container">
                        {self._generate_trades_table_html()}
                    </div>
                </div>
                
            </div>
            
            <script>
                // Table sort functionality
                document.querySelectorAll('.sortable-table th').forEach(th => th.addEventListener('click', (() => {{
                        const table = th.closest('table');
                        const tbody = table.querySelector('tbody');
                        const rows = Array.from(tbody.querySelectorAll('tr'));
                        const index = Array.from(th.parentNode.children).indexOf(th);
                        
                        // Determine if numeric (remove $ and % for judgment)
                        const isNumeric = !isNaN(rows[0].children[index].textContent.replace(/[^0-9.-]+/g,""));
                        
                        // Determine sort direction (reverse current state)
                        const direction = th.classList.contains('asc') ? -1 : 1;
                        
                        // Sort processing
                        rows.sort((a, b) => {{
                            const aValue = a.children[index].textContent.replace(/[^0-9.-]+/g,"");
                            const bValue = b.children[index].textContent.replace(/[^0-9.-]+/g,"");
                            
                            if (isNumeric) {{
                                return direction * (parseFloat(aValue) - parseFloat(bValue));
                            }} else {{
                                return direction * aValue.localeCompare(bValue);
                            }}
                        }});
                        
                        // Update sort direction indicator
                        th.closest('tr').querySelectorAll('th').forEach(el => {{
                            el.classList.remove('asc', 'desc');
                        }});
                        th.classList.toggle('asc', direction === 1);
                        th.classList.toggle('desc', direction === -1);
                        
                        // Update table
                        tbody.append(...rows);
                    }})));
                </script>
                

            </body>
        </html>
        """

        # Save HTML file
        output_file = f"reports/alpaca_trade_report_{self.start_date}_{self.end_date}.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_template)
        
        print(f"\nHTML report saved to {output_file}")
        
        # Open report in browser
        webbrowser.open('file://' + os.path.realpath(output_file))

    def _generate_metrics_html(self, df):
        """Generate HTML for metrics display"""
        metrics = self.calculate_metrics()
        
        # Color settings for win rate
        win_rate_class = "positive" if metrics['win_rate'] >= 50 else "negative"
        # Color settings for total return
        total_return_class = "positive" if metrics['total_return_pct'] >= 0 else "negative"
        # Color settings for CAGR
        cagr_class = "positive" if metrics['cagr'] >= 0 else "negative"
        # Color settings for profit factor
        pf_class = "positive" if metrics['profit_factor'] >= 1.0 else "negative"
        # Color settings for expected value
        ev_class = "positive" if metrics['expected_value_pct'] >= 0 else "negative"
        
        return f"""
            <div class="metric">
                <div class="metric-label">Total Trades</div>
                <div class="metric-value">{metrics['number_of_trades']}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value {win_rate_class}">{metrics['win_rate']:.1f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Return</div>
                <div class="metric-value {total_return_class}">{metrics['total_return_pct']:.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">CAGR (Annualized Return)</div>
                <div class="metric-value {cagr_class}">{metrics['cagr']:.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value {pf_class}">{metrics['profit_factor']:.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Max Drawdown</div>
                <div class="metric-value negative">{metrics['max_drawdown_pct']:.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Avg Win</div>
                <div class="metric-value positive">${metrics.get('avg_win', 0):,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Avg Loss</div>
                <div class="metric-value negative">${metrics.get('avg_loss', 0):,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Win/Loss Ratio</div>
                <div class="metric-value">{metrics.get('win_loss_ratio', 0):.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Expected Value</div>
                <div class="metric-value {ev_class}">{metrics['expected_value_pct']:.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Calmar Ratio</div>
                <div class="metric-value">{metrics['calmar_ratio']:.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Pareto Ratio</div>
                <div class="metric-value">{metrics['pareto_ratio']:.1f}%</div>
            </div>
        """

    def _generate_trades_table_html(self):
        """Generate HTML for trade history table"""
        if not self.trades:
            return "<p>No trade records available</p>"
        
        # Convert trades to DataFrame
        df = pd.DataFrame(self.trades)
        df = df.sort_values('entry_date', ascending=False)
        
        table_html = """
        <table class="sortable-table">
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Entry Date</th>
                    <th>Entry Price</th>
                    <th>Exit Date</th>
                    <th>Exit Price</th>
                    <th>Holding Period</th>
                    <th>Shares</th>
                    <th>PnL Rate</th>
                    <th>PnL</th>
                    <th>Exit Reason</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for _, trade in df.iterrows():
            # Color settings based on profit/loss (use profit/loss classes)
            pnl_class = "profit" if trade['pnl'] >= 0 else "loss"
            pnl_rate_class = "profit" if trade['pnl_rate'] >= 0 else "loss"
            holding_period = f"{trade['holding_period']:.0f} days"
            
            table_html += f"""
                <tr>
                    <td>{trade['ticker']}</td>
                    <td>{pd.to_datetime(trade['entry_date']).strftime('%Y-%m-%d')}</td>
                    <td>${trade['entry_price']:.2f}</td>
                    <td>{pd.to_datetime(trade['exit_date']).strftime('%Y-%m-%d')}</td>
                    <td>${trade['exit_price']:.2f}</td>
                    <td>{holding_period}</td>
                    <td>{trade['shares']:,.0f}</td>
                    <td class="{pnl_rate_class}">{trade['pnl_rate']:.2f}%</td>
                    <td class="{pnl_class}">${trade['pnl']:,.2f}</td>
                    <td>{trade['exit_reason']}</td>
                </tr>
            """
        
        table_html += """
            </tbody>
        </table>
        """
        
        return table_html

    def analyze_performance(self):
        """Execute detailed backtest analysis"""
        if not self.trades:
            print("No trade data available for analysis")
            return
        
        # Convert trade data to DataFrame
        df = pd.DataFrame(self.trades)
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        df['exit_date'] = pd.to_datetime(df['exit_date'])
        
        # Monthly performance analysis
        self._analyze_monthly_performance(df)
        
        # Sector and industry analysis
        self._analyze_sector_performance(df)
        
        # Add EPS analysis
        self._analyze_eps_performance(df)
        
        # Gap analysis
        self._analyze_gap_performance(df)
        
        # Trend analysis
        self._analyze_pre_earnings_trend(df)
        
        # Market cap analysis
        self._analyze_market_cap_performance(df)
        
        # Price range analysis
        self._analyze_price_range_performance(df)
        
        # Breakout analysis
        self._analyze_breakout_performance(df)

    def _analyze_monthly_performance(self, df):
        """Monthly performance analysis"""
        print("\n=== Monthly performance analysis ===")
        
        # Extract month and year
        df['year'] = df['entry_date'].dt.year
        df['month'] = df['entry_date'].dt.month
        
        # Monthly summary
        monthly_stats = df.groupby(['year', 'month']).agg({
            'pnl_rate': ['mean', 'std', 'count'],
            'pnl': 'sum'
        }).round(2)
        
        # Monthly statistics
        monthly_summary = df.groupby('month').agg({
            'pnl_rate': ['mean', 'std', 'count'],
            'pnl': 'sum'
        }).round(2)
        
        print("\nMonthly average performance:")
        for month in range(1, 13):
            if month in monthly_summary.index:
                stats = monthly_summary.loc[month]
                print(f"\n{month} month:")
                print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
                print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
                print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")
                print(f"- Cumulative P&L: ${stats[('pnl', 'sum')]:,.2f}")

    def _analyze_sector_performance(self, df):
        """Sector and industry performance analysis"""
        print("\n=== Sector and industry performance analysis ===")
        
        # Get sector information from FMP
        sectors = {}
        for ticker in tqdm(df['ticker'].unique(), desc="Retrieving sector info"):
            try:
                # Get company profile using FMP client
                profile_data = self.fmp_client.get_company_profile(ticker)
                if profile_data:
                    sectors[ticker] = {
                        'sector': profile_data.get('sector', 'Unknown'),
                        'industry': profile_data.get('industry', 'Unknown')
                    }
                else:
                    sectors[ticker] = {
                        'sector': 'Unknown',
                        'industry': 'Unknown'
                    }
            except Exception as e:
                print(f"Sector information retrieval error ({ticker}): {str(e)}")
                sectors[ticker] = {
                    'sector': 'Unknown',
                    'industry': 'Unknown'
                }
        
        # Add sector information to DataFrame
        df['sector'] = df['ticker'].map(lambda x: sectors.get(x, {}).get('sector', 'Unknown'))
        df['industry'] = df['ticker'].map(lambda x: sectors.get(x, {}).get('industry', 'Unknown'))
        
        # Sector-wise statistics
        sector_stats = df.groupby('sector').agg({
            'pnl_rate': ['mean', 'std', 'count'],
            'pnl': 'sum'
        }).round(2)
        
        print("\nSector-wise performance:")
        for sector in sector_stats.index:
            stats = sector_stats.loc[sector]
            print(f"\n{sector}:")
            print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
            print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
            print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")
            print(f"- Total P&L: ${stats[('pnl', 'sum')]:,.2f}")

    def _analyze_eps_performance(self, df):
        """EPS-related performance analysis"""
        print("\n=== EPS analysis ===")
        
        # entry_date to ensure it's a date type
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        
        # Get EPS data
        print("\nGetting EPS data...")
        eps_data = {}
        for ticker, group in df.groupby('ticker'):
            try:
                # Use latest entry date for each ticker
                latest_entry = group['entry_date'].max()
                eps_info = self._get_eps_data(ticker, latest_entry)
                if eps_info:
                    eps_data[ticker] = eps_info
                
            except Exception as e:
                print(f"Error ({ticker}): {str(e)}")
                continue
        
        if not eps_data:
            print("Warning: EPS data could not be retrieved")
            return df
        
        # Add EPS data to DataFrame
        df['eps_surprise'] = df['ticker'].map(lambda x: eps_data.get(x, {}).get('eps_surprise'))
        df['eps_yoy_growth'] = df['ticker'].map(lambda x: eps_data.get(x, {}).get('eps_yoy_growth'))
        df['growth_acceleration'] = df['ticker'].map(lambda x: eps_data.get(x, {}).get('growth_acceleration'))
        
        # Create categories
        df = self._categorize_eps_metrics(df)
        
        # Execute analysis for each category
        categories = [
            ('surprise_category', 'EPS Surprise'),
            ('growth_category', 'EPS Growth Rate'),
            ('growth_acceleration_category', 'EPS Growth Acceleration')
        ]
        
        for category, title in categories:
            stats = df.groupby(category).agg({
                'pnl_rate': ['mean', 'std', 'count'],
                'pnl': ['sum', lambda x: (x > 0).mean() * 100]  # Total and win rate
            }).round(2)
            
            print(f"\n{title} performance:")
            for cat in stats.index:
                if pd.isna(cat):  # Skip if NaN/NA
                    continue
                s = stats.loc[cat]
                print(f"\n{cat}:")
                print(f"- Average return: {s[('pnl_rate', 'mean')]:.2f}%")
                print(f"- Standard deviation: {s[('pnl_rate', 'std')]:.2f}%")
                print(f"- Number of trades: {s[('pnl_rate', 'count')]}")
                print(f"- Win rate: {s[('pnl', '<lambda>')]:.1f}%")
                print(f"- Total P&L: ${s[('pnl', 'sum')]:,.2f}")
        
        # Correlation analysis
        correlations = {
            'EPS Surprise': df['eps_surprise'].corr(df['pnl_rate']),
            'EPS Growth Rate': df['eps_yoy_growth'].corr(df['pnl_rate']),
            'Growth Acceleration': df['growth_acceleration'].corr(df['pnl_rate'])
        }
        
        print("\n=== Correlation with performance ===")
        for metric, corr in correlations.items():
            if not pd.isna(corr):  # Skip if NaN/NA
                print(f"{metric} and performance: {corr:.3f}")
        
        return df

    def _get_eps_data(self, ticker, entry_date):
        """Get EPS data from FMP (simple version)"""
        try:
            # Use FMP client to get earnings surprises data
            earnings_data = self.fmp_client.get_earnings_surprises(ticker, limit=80)
            
            if not earnings_data:
                print(f"Warning: {ticker} earnings data not found")
                return None
            
            # Set date range based on entry date (past 2 years)
            entry_dt = pd.to_datetime(entry_date)
            from_date = entry_dt - timedelta(days=730)  # 2 years before entry date
            
            # Filter by date
            filtered_data = []
            for e in earnings_data:
                earning_date = pd.to_datetime(e['date'])
                if from_date <= earning_date <= entry_dt:
                    filtered_data.append(e)
            
            if not filtered_data:
                print(f"Warning: {ticker} earnings data not found within the period")
                return None
            
            # Sort by date (newest first)
            filtered_data.sort(key=lambda x: x['date'], reverse=True)
            
            # Extract quarters data (get 8 quarters)
            quarters = []
            for e in filtered_data:
                quarter_date = pd.to_datetime(e['date'])
                if len(quarters) == 0 or (quarters[-1]['date'] - quarter_date).days > 60:
                    quarters.append({
                        'date': quarter_date,
                        'eps': float(e['actualEarningResult']) if e['actualEarningResult'] is not None else None,
                        'estimate': float(e['estimatedEarning']) if e['estimatedEarning'] is not None else None
                    })
                if len(quarters) >= 8:  # Stop after getting 8 quarters
                    break
            
            if len(quarters) < 8:
                print(f"Warning: Not enough quarters data ({len(quarters)} quarters)")
                return None
            
            # Calculate EPS surprise (latest quarter)
            current_quarter = quarters[0]
            eps_surprise = None
            if (current_quarter['eps'] is not None and 
                current_quarter['estimate'] is not None and 
                abs(current_quarter['estimate']) > 0.0001):
                eps_surprise = ((current_quarter['eps'] - current_quarter['estimate']) / 
                              abs(current_quarter['estimate'])) * 100
            
            # Calculate YoY growth rate (latest quarter)
            current_growth = None
            if (current_quarter['eps'] is not None and 
                quarters[4]['eps'] is not None and 
                abs(quarters[4]['eps']) > 0.0001):
                current_growth = ((current_quarter['eps'] - quarters[4]['eps']) / 
                                abs(quarters[4]['eps'])) * 100
            
            # Previous quarter's YoY growth rate
            prev_growth = None
            if (quarters[1]['eps'] is not None and 
                quarters[5]['eps'] is not None and 
                abs(quarters[5]['eps']) > 0.0001):
                prev_growth = ((quarters[1]['eps'] - quarters[5]['eps']) / 
                             abs(quarters[5]['eps'])) * 100
            
            # Growth acceleration
            growth_acceleration = None
            if current_growth is not None and prev_growth is not None:
                growth_acceleration = current_growth - prev_growth
            
            return {
                'eps_surprise': eps_surprise,
                'eps_yoy_growth': current_growth,
                'prev_quarter_growth': prev_growth,
                'growth_acceleration': growth_acceleration
            }
            
        except Exception as e:
            print(f"Error retrieving EPS data ({ticker}): {str(e)}")
            return None

    def _categorize_eps_metrics(self, df):
        """Categorize EPS metrics"""
        # Convert None to NaN
        df['eps_surprise'] = pd.to_numeric(df['eps_surprise'], errors='coerce')
        df['eps_yoy_growth'] = pd.to_numeric(df['eps_yoy_growth'], errors='coerce')
        df['growth_acceleration'] = pd.to_numeric(df['growth_acceleration'], errors='coerce')
        
        # Categorize surprise
        df['surprise_category'] = pd.cut(
            df['eps_surprise'],
            bins=[-np.inf, -20, -10, 0, 10, 20, np.inf],
            labels=['<-20%', '-20~-10%', '-10~0%', '0~10%', '10~20%', '>20%'],
            include_lowest=True
        )
        
        # Categorize YoY growth rate
        df['growth_category'] = pd.cut(
            df['eps_yoy_growth'],
            bins=[-np.inf, -50, -25, 0, 25, 50, np.inf],
            labels=['<-50%', '-50~-25%', '-25~0%', '0~25%', '25~50%', '>50%'],
            include_lowest=True
        )
        
        # Categorize growth acceleration
        df['growth_acceleration_category'] = pd.cut(
            df['growth_acceleration'],
            bins=[-np.inf, -30, -15, 0, 15, 30, np.inf],
            labels=['Strong Deceleration', 'Deceleration', 'Mild Deceleration', 
                    'Mild Acceleration', 'Acceleration', 'Strong Acceleration'],
            include_lowest=True
        )
        
        # Set category order
        for col, categories in [
            ('surprise_category', ['<-20%', '-20~-10%', '-10~0%', '0~10%', '10~20%', '>20%']),
            ('growth_category', ['<-50%', '-50~-25%', '-25~0%', '0~25%', '25~50%', '>50%']),
            ('growth_acceleration_category', ['Strong Deceleration', 'Deceleration', 'Mild Deceleration',
                                            'Mild Acceleration', 'Acceleration', 'Strong Acceleration'])
        ]:
            df[col] = pd.Categorical(df[col], categories=categories, ordered=True)
        
        return df

    def _analyze_gap_performance(self, df):
        """Performance analysis by gap size"""
        print("\n=== Performance analysis by gap size ===")
        
        # Create bins by gap rate
        df['gap_bin'] = pd.cut(df['gap'], 
                              bins=[-np.inf, 5, 10, 15, 20, np.inf],
                              labels=['0-5%', '5-10%', '10-15%', '15-20%', '20%+'])
        
        # Statistics by gap size
        gap_stats = df.groupby('gap_bin').agg({
            'pnl_rate': ['mean', 'std', 'count'],
            'pnl': 'sum'
        }).round(2)
        
        # Calculate win rate
        win_rates = df.groupby('gap_bin').apply(
            lambda x: (x['pnl'] > 0).mean() * 100
        ).round(2)
        
        print("\nPerformance by gap size:")
        for gap_bin in gap_stats.index:
            stats = gap_stats.loc[gap_bin]
            print(f"\n{gap_bin}:")
            print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
            print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
            print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")
            print(f"- Win rate: {win_rates[gap_bin]:.1f}%")
            print(f"- Total P&L: ${stats[('pnl', 'sum')]:,.2f}")

    def _analyze_pre_earnings_trend(self, df):
        """Pre-earnings trend analysis"""
        print("\n=== Pre-earnings trend analysis ===")
        
        # Analyze trend for each trade
        trends = []
        for _, trade in df.iterrows():
            # Get pre-earnings stock data
            pre_earnings_start = (pd.to_datetime(trade['entry_date']) - 
                                timedelta(days=30)).strftime('%Y-%m-%d')
            stock_data = self.get_historical_data(
                trade['ticker'],
                pre_earnings_start,
                trade['entry_date']
            )
            
            if stock_data is not None and len(stock_data) >= 20:
                # Calculate 21-day moving average
                stock_data['MA21'] = stock_data['Close'].rolling(window=21).mean()
                
                # Calculate 20-day price change rate
                price_change = ((stock_data['Close'].iloc[-1] - stock_data['Close'].iloc[-20]) / 
                              stock_data['Close'].iloc[-20] * 100)
                
                # Position relative to 20-day moving average
                ma_position = 'above' if stock_data['Close'].iloc[-1] > stock_data['MA21'].iloc[-1] else 'below'
                
                trends.append({
                    'ticker': trade['ticker'],
                    'entry_date': trade['entry_date'],
                    'pre_earnings_change': price_change,
                    'ma_position': ma_position,
                    'pnl_rate': trade['pnl_rate'],
                    'pnl': trade['pnl']  # Add pnl
                })
        
        trend_df = pd.DataFrame(trends)
        
        if not trend_df.empty:
            # Create bins by trend strength
            trend_df['trend_bin'] = pd.cut(trend_df['pre_earnings_change'],
                                         bins=[-np.inf, -20, -10, 0, 10, 20, np.inf],
                                         labels=['<-20%', '-20~-10%', '-10~0%', '0~10%', '10~20%', '>20%'])
            
            # Statistics by trend
            trend_stats = trend_df.groupby('trend_bin').agg({
                'pnl_rate': ['mean', 'std', 'count']
            }).round(2)
            
            print("\nPerformance by trend:")
            for trend_bin in trend_stats.index:
                stats = trend_stats.loc[trend_bin]
                print(f"\n{trend_bin}:")
                print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
                print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
                print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")
        
        return trend_df  # Return DataFrame

    def _analyze_breakout_performance(self, df):
        """Breakout pattern analysis"""
        print("\n=== Breakout pattern analysis ===")
        
        breakouts = []
        for _, trade in df.iterrows():
            # Get pre-earnings stock data
            pre_earnings_start = (pd.to_datetime(trade['entry_date']) - 
                                timedelta(days=60)).strftime('%Y-%m-%d')
            stock_data = self.get_historical_data(
                trade['ticker'],
                pre_earnings_start,
                trade['entry_date']
            )
            
            if stock_data is not None and len(stock_data) >= 20:
                # Calculate 20-day high
                high_20d = stock_data['High'].rolling(window=20).max().iloc[-2]  # 20-day high before the previous day
                
                # Determine if it's a breakout
                is_breakout = trade['entry_price'] > high_20d
                breakout_percent = ((trade['entry_price'] - high_20d) / high_20d * 100) if is_breakout else 0
                
                breakouts.append({
                    'ticker': trade['ticker'],
                    'entry_date': trade['entry_date'],
                    'is_breakout': is_breakout,
                    'breakout_percent': breakout_percent,
                    'pnl_rate': trade['pnl_rate']
                })
        
        breakout_df = pd.DataFrame(breakouts)
        
        # Statistics by breakout presence
        breakout_stats = breakout_df.groupby('is_breakout').agg({
            'pnl_rate': ['mean', 'std', 'count']
        }).round(2)
        
        # Analysis by breakout size
        breakout_df['breakout_bin'] = pd.cut(breakout_df['breakout_percent'],
                                            bins=[-np.inf, 0, 2, 5, 10, np.inf],
                                            labels=['No Breakout', '0-2%', '2-5%', '5-10%', '>10%'])
        
        size_stats = breakout_df.groupby('breakout_bin').agg({
            'pnl_rate': ['mean', 'std', 'count']
        }).round(2)
        
        print("\nPerformance by breakout pattern:")
        for breakout_bin in size_stats.index:
            stats = size_stats.loc[breakout_bin]
            print(f"\n{breakout_bin}:")
            print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
            print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
            print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")

    def generate_analysis_charts(self, df):
        """Generate analysis charts"""
        charts = {}
        
        # Get EPS data and add to DataFrame
        print("\nRetrieving EPS data...")
        eps_data = {}
        
        # Get unique combinations of (ticker, entry_date) for all trades
        trade_keys = df[['ticker', 'entry_date']].drop_duplicates()
        total_trades = len(trade_keys)
        
        # Use tqdm to show progress bar
        for _, row in tqdm(trade_keys.iterrows(), 
                          total=total_trades,
                          desc="Retrieving EPS data",
                          ncols=100):
            ticker = row['ticker']
            entry_date = row['entry_date']
            trade_key = (ticker, entry_date.strftime('%Y-%m-%d'))
            
            try:
                eps_info = self._get_eps_data(ticker, entry_date)
                
                if eps_info:
                    eps_data[trade_key] = eps_info
                    tqdm.write(f"{ticker} ({entry_date.strftime('%Y-%m-%d')}): EPS data retrieved successfully")
                else:
                    tqdm.write(f"{ticker} ({entry_date.strftime('%Y-%m-%d')}): EPS data not found")
                    
                
            except Exception as e:
                tqdm.write(f"{ticker} ({entry_date.strftime('%Y-%m-%d')}): Error - {str(e)}")
                continue

        print(f"\nEPS data retrieval complete: {len(eps_data)}/{total_trades} trades")
        
        # Add EPS data to DataFrame (based on trade_key)
        df['eps_surprise'] = df.apply(
            lambda x: eps_data.get((x['ticker'], x['entry_date'].strftime('%Y-%m-%d')), {}).get('eps_surprise'),
            axis=1
        )
        df['eps_yoy_growth'] = df.apply(
            lambda x: eps_data.get((x['ticker'], x['entry_date'].strftime('%Y-%m-%d')), {}).get('eps_yoy_growth'),
            axis=1
        )
        df['growth_acceleration'] = df.apply(
            lambda x: eps_data.get((x['ticker'], x['entry_date'].strftime('%Y-%m-%d')), {}).get('growth_acceleration'),
            axis=1
        )

        # Categorize EPS metrics
        df = self._categorize_eps_metrics(df)
        
        # Monthly performance and win rate heatmap
        df['year'] = df['entry_date'].dt.year
        df['month'] = df['entry_date'].dt.month
        
        # Calculate average return (specify observed=True explicitly)
        monthly_returns = df.pivot_table(
            values='pnl_rate',
            index='year',
            columns='month',
            aggfunc='mean',
            observed=True  # Avoid warning
        ).round(2)
        
        # Calculate win rate (specify observed=True explicitly)
        monthly_winrate = df.pivot_table(
            values='pnl',
            index='year',
            columns='month',
            aggfunc=lambda x: (x > 0).mean() * 100,
            observed=True  # Avoid warning
        ).round(1)
        
        # Create subplots
        fig = go.Figure()
        
        # Heatmap for average return
        fig.add_trace(go.Heatmap(
            z=monthly_returns.values,
            x=monthly_returns.columns,
            y=monthly_returns.index,
            colorscale=[
                [0.0, TradeReport.DARK_THEME['loss_color']],      # -20% or less: dark red
                [0.2, '#ff6b6b'],                                      # -20% to -10%: light red
                [0.4, '#ffa07a'],                                      # -10% to 0%: lighter red
                [0.5, TradeReport.DARK_THEME['plot_bg_color']],   # 0%: background color
                [0.6, '#98fb98'],                                      # 0% to 10%: light green
                [0.8, '#3cb371'],                                      # 10% to 20%: medium green
                [1.0, TradeReport.DARK_THEME['profit_color']]     # 20% or more: dark green
            ],
            zmid=0,  # Change color to center on 0%
            zmin=-20,  # Same color for -20% or less
            zmax=20,   # Same color for 20% or more
            text=monthly_returns.values.round(1),
            texttemplate='%{text}%',
            hoverongaps=False,
            name=self.get_text('average_return'),
            xaxis='x',
            yaxis='y'
        ))
        
        # Heatmap for win rate
        fig.add_trace(go.Heatmap(
            z=monthly_winrate.values,
            x=monthly_winrate.columns,
            y=monthly_winrate.index,
            colorscale=[
                [0, TradeReport.DARK_THEME['loss_color']],
                [0.5, TradeReport.DARK_THEME['plot_bg_color']],
                [1, TradeReport.DARK_THEME['profit_color']]
            ],
            text=monthly_winrate.values.round(1),
            texttemplate='%{text}%',
            hoverongaps=False,
            name=self.get_text('win_rate'),
            xaxis='x2',
            yaxis='y2'
        ))
        
        # Update layout
        fig.update_layout(
            title=self.get_text('monthly_performance_heatmap'),
            grid=dict(rows=2, columns=1, pattern='independent'),
            annotations=[
                dict(
                    text=self.get_text('average_return'),
                    x=0.5, y=1.1,
                    xref='paper', yref='paper',
                    showarrow=False
                ),
                dict(
                    text=self.get_text('win_rate'),
                    x=0.5, y=0.45,
                    xref='paper', yref='paper',
                    showarrow=False
                )
            ],
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color'],
            height=800  # Adjust graph height
        )
        
        charts['monthly'] = plot(fig, output_type='div', include_plotlyjs=False)
        
        # Performance by gap size
        gap_stats = df.groupby(pd.cut(df['gap'], 
                                     bins=[-np.inf, 5, 10, 15, 20, np.inf],
                                     labels=['0-5%', '5-10%', '10-15%', '15-20%', '20%+'])
                             ).agg({
            'pnl_rate': ['mean', 'count'],
            'pnl': 'sum'
        }).round(2)
        
        fig_gap = go.Figure()
        fig_gap.add_trace(go.Bar(
            x=gap_stats.index,
            y=gap_stats[('pnl_rate', 'mean')],
            name=self.get_text('average_return'),
            text=gap_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
            textposition='auto'
        ))
        
        fig_gap.add_trace(go.Scatter(
            x=gap_stats.index,
            y=gap_stats[('pnl_rate', 'count')],
            name=self.get_text('number_of_trades_gap'),
            yaxis='y2',
            line=dict(color=TradeReport.DARK_THEME['line_color'])
        ))
        
        fig_gap.update_layout(
            title=self.get_text('gap_performance'),
            xaxis_title=self.get_text('gap_size'),
            yaxis_title=self.get_text('return_pct'),
            yaxis2=dict(
                title=self.get_text('number_of_trades_gap'),
                overlaying='y',
                side='right'
            ),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color']
        )
        
        charts['gap'] = plot(fig_gap, output_type='div', include_plotlyjs=False)
        
        # Trend analysis chart
        trend_data = self._calculate_trend_data(df)
        if trend_data is not None and not trend_data.empty and 'trend_bin' in trend_data.columns:
            trend_stats = trend_data.groupby('trend_bin').agg({
                'pnl_rate': ['mean', 'count'],
                'pnl': lambda x: (x > 0).mean() * 100
            }).round(2)
            
            fig_trend = go.Figure(data=[
                go.Bar(
                    x=trend_stats.index,
                    y=trend_stats[('pnl_rate', 'mean')],
                    text=trend_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
                    textposition='auto',
                    marker_color=[
                        TradeReport.DARK_THEME['profit_color'] if x > 0 else TradeReport.DARK_THEME['loss_color']
                        for x in trend_stats[('pnl_rate', 'mean')]
                    ]
                )
            ])
            
            fig_trend.update_layout(
                title=self.get_text('pre_earnings_trend_performance'),
                xaxis_title=self.get_text('price_change'),
                yaxis_title=self.get_text('return_pct'),
                template='plotly_dark',
                paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
                plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color']
            )
            
            charts['trend'] = plot(fig_trend, output_type='div', include_plotlyjs=False)
        else:
            print("Trend data not found")
            charts['trend'] = ""
        
        # Sector-wise performance chart
        sector_stats = df.groupby('sector').agg({
            'pnl_rate': ['mean', 'count'],
            'pnl': lambda x: (x > 0).mean() * 100  # Calculate win rate
        }).round(2)
        
        fig_sector = go.Figure()
        
        # Bar for average return
        fig_sector.add_trace(go.Bar(
            x=sector_stats.index,
            y=sector_stats[('pnl_rate', 'mean')],
            name=self.get_text('average_return'),
            text=sector_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
            textposition='auto',
            marker_color=[
                TradeReport.DARK_THEME['profit_color'] if x > 0 
                else TradeReport.DARK_THEME['loss_color'] 
                for x in sector_stats[('pnl_rate', 'mean')]
            ]
        ))
        
        # Line for win rate
        fig_sector.add_trace(go.Scatter(
            x=sector_stats.index,
            y=sector_stats[('pnl', '<lambda>')],
            name=self.get_text('win_rate'),
            yaxis='y2',
            line=dict(color=TradeReport.DARK_THEME['line_color'])
        ))
        
        fig_sector.update_layout(
            title=self.get_text('sector_performance'),
            xaxis_title=self.get_text('sector'),
            yaxis_title=self.get_text('return_pct'),
            yaxis2=dict(
                title=self.get_text('win_rate'),
                overlaying='y',
                side='right',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color'],
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        
        charts['sector'] = plot(fig_sector, output_type='div', include_plotlyjs=False)
        
        # Industry-wise performance chart
        industry_stats = df.groupby('industry').agg({
            'pnl_rate': ['mean', 'count'],
            'pnl': lambda x: (x > 0).mean() * 100
        }).round(2)
        
        # Select top 15 industries by number of trades
        top_industries = industry_stats.nlargest(15, ('pnl_rate', 'count'))
        
        fig_industry = go.Figure()
        
        # Bar for average return
        fig_industry.add_trace(go.Bar(
            x=top_industries.index,
            y=top_industries[('pnl_rate', 'mean')],
            name=self.get_text('average_return'),
            text=top_industries[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
            textposition='auto',
            marker_color=[
                TradeReport.DARK_THEME['profit_color'] if x > 0 
                else TradeReport.DARK_THEME['loss_color'] 
                for x in top_industries[('pnl_rate', 'mean')]
            ]
        ))
        
        # Line for win rate
        fig_industry.add_trace(go.Scatter(
            x=top_industries.index,
            y=top_industries[('pnl', '<lambda>')],
            name=self.get_text('win_rate'),
            yaxis='y2',
            line=dict(color=TradeReport.DARK_THEME['line_color'])
        ))
        
        fig_industry.update_layout(
            title=self.get_text('industry_performance'),
            xaxis_title=self.get_text('industry'),
            yaxis_title=self.get_text('return_pct'),
            yaxis2=dict(
                title=self.get_text('win_rate'),
                overlaying='y',
                side='right',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor=TradeReport.DARK_THEME['bg_color'],
            plot_bgcolor=TradeReport.DARK_THEME['plot_bg_color'],
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        
        # Rotate X-axis labels by 45 degrees
        fig_industry.update_xaxes(tickangle=45)
        
        charts['industry'] = plot(fig_industry, output_type='div', include_plotlyjs=False)
        
        # EPS surprise-wise performance chart
        surprise_stats = df.groupby('surprise_category', observed=True).agg({
            'pnl_rate': ['mean', 'count'],
            'pnl': lambda x: (x > 0).mean() * 100  # Calculate win rate
        }).round(2)
        
        fig_surprise = go.Figure()
        
        # Bar for average return
        fig_surprise.add_trace(go.Bar(
            x=surprise_stats.index,
            y=surprise_stats[('pnl_rate', 'mean')],
            name=self.get_text('average_return'),
            text=surprise_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
            textposition='auto',
            marker_color=[
                self.DARK_THEME['profit_color'] if x > 0 
                else self.DARK_THEME['loss_color'] 
                for x in surprise_stats[('pnl_rate', 'mean')]
            ]
        ))
        
        # Line for win rate
        fig_surprise.add_trace(go.Scatter(
            x=surprise_stats.index,
            y=surprise_stats[('pnl', '<lambda>')],
            name=self.get_text('win_rate'),
            yaxis='y2',
            line=dict(color=self.DARK_THEME['line_color'])
        ))
        
        fig_surprise.update_layout(
            title=self.get_text('eps_surprise_performance'),
            xaxis_title=self.get_text('eps_surprise'),
            yaxis_title=self.get_text('return_pct'),
            yaxis2=dict(
                title=self.get_text('win_rate'),
                overlaying='y',
                side='right',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor=self.DARK_THEME['bg_color'],
            plot_bgcolor=self.DARK_THEME['plot_bg_color'],
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        
        charts['eps_surprise'] = plot(fig_surprise, output_type='div', include_plotlyjs=False)
        
        # EPS growth rate-wise performance chart
        growth_stats = df.groupby('growth_category', observed=True).agg({
            'pnl_rate': ['mean', 'count'],
            'pnl': lambda x: (x > 0).mean() * 100
        }).round(2)
        
        fig_growth = go.Figure()
        
        # Bar for average return
        fig_growth.add_trace(go.Bar(
            x=growth_stats.index,
            y=growth_stats[('pnl_rate', 'mean')],
            name=self.get_text('average_return'),
            text=growth_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
            textposition='auto',
            marker_color=[
                self.DARK_THEME['profit_color'] if x > 0 
                else self.DARK_THEME['loss_color'] 
                for x in growth_stats[('pnl_rate', 'mean')]
            ]
        ))
        
        # Line for win rate
        fig_growth.add_trace(go.Scatter(
            x=growth_stats.index,
            y=growth_stats[('pnl', '<lambda>')],
            name=self.get_text('win_rate'),
            yaxis='y2',
            line=dict(color=self.DARK_THEME['line_color'])
        ))
        
        fig_growth.update_layout(
            title=self.get_text('eps_growth_performance'),
            xaxis_title=self.get_text('eps_growth'),
            yaxis_title=self.get_text('return_pct'),
            yaxis2=dict(
                title=self.get_text('win_rate'),
                overlaying='y',
                side='right',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor=self.DARK_THEME['bg_color'],
            plot_bgcolor=self.DARK_THEME['plot_bg_color'],
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        
        charts['eps_growth'] = plot(fig_growth, output_type='div', include_plotlyjs=False)
        
        # Growth acceleration-wise performance chart
        acceleration_stats = df.groupby('growth_acceleration_category', observed=True).agg({
            'pnl_rate': ['mean', 'count'],
            'pnl': lambda x: (x > 0).mean() * 100
        }).round(2)
        
        fig_acceleration = go.Figure()
        
        # Bar for average return
        fig_acceleration.add_trace(go.Bar(
            x=acceleration_stats.index,
            y=acceleration_stats[('pnl_rate', 'mean')],
            name=self.get_text('average_return'),
            text=acceleration_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
            textposition='auto',
            marker_color=[
                self.DARK_THEME['profit_color'] if x > 0 
                else self.DARK_THEME['loss_color'] 
                for x in acceleration_stats[('pnl_rate', 'mean')]
            ]
        ))
        
        # Line for win rate
        fig_acceleration.add_trace(go.Scatter(
            x=acceleration_stats.index,
            y=acceleration_stats[('pnl', '<lambda>')],
            name=self.get_text('win_rate'),
            yaxis='y2',
            line=dict(color=self.DARK_THEME['line_color'])
        ))
        
        fig_acceleration.update_layout(
            title=self.get_text('eps_acceleration_performance'),
            xaxis_title=self.get_text('eps_acceleration'),
            yaxis_title=self.get_text('return_pct'),
            yaxis2=dict(
                title=self.get_text('win_rate'),
                overlaying='y',
                side='right',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor=self.DARK_THEME['bg_color'],
            plot_bgcolor=self.DARK_THEME['plot_bg_color'],
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        
        # Rotate X-axis labels by 45 degrees (acceleration category is long)
        fig_acceleration.update_xaxes(tickangle=45)
        
        charts['eps_acceleration'] = plot(fig_acceleration, output_type='div', include_plotlyjs=False)
        
        # Volume trend analysis chart
        volume_data = self._analyze_volume_trend(df)
        if volume_data is not None and not volume_data.empty:
            try:
                volume_stats = volume_data.groupby('volume_category').agg({
                    'pnl_rate': ['mean', 'count'],
                    'pnl': lambda x: (x > 0).mean() * 100
                }).round(2)
                
                fig_volume = go.Figure()
                
                # Bar for average return
                fig_volume.add_trace(go.Bar(
                    x=volume_stats.index,
                    y=volume_stats[('pnl_rate', 'mean')],
                    name=self.get_text('average_return'),
                    text=volume_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
                    textposition='auto',
                    marker_color=[
                        self.DARK_THEME['profit_color'] if x > 0 
                        else self.DARK_THEME['loss_color'] 
                        for x in volume_stats[('pnl_rate', 'mean')]
                    ]
                ))
                
                # Line for win rate
                fig_volume.add_trace(go.Scatter(
                    x=volume_stats.index,
                    y=volume_stats[('pnl', '<lambda>')],
                    name=self.get_text('win_rate'),
                    yaxis='y2',
                    line=dict(color=self.DARK_THEME['line_color'])
                ))
                
                fig_volume.update_layout(
                    title=self.get_text('volume_trend_analysis'),
                    xaxis_title=self.get_text('volume_category'),
                    yaxis_title=self.get_text('return_pct'),
                    yaxis2=dict(
                        title=self.get_text('win_rate'),
                        overlaying='y',
                        side='right',
                        range=[0, 100]
                    ),
                    template='plotly_dark',
                    paper_bgcolor=self.DARK_THEME['bg_color'],
                    plot_bgcolor=self.DARK_THEME['plot_bg_color'],
                    showlegend=True,
                    legend=dict(
                        orientation='h',
                        yanchor='bottom',
                        y=1.02,
                        xanchor='right',
                        x=1
                    )
                )
                
                # Rotate X-axis labels by 45 degrees (category names are long)
                fig_volume.update_xaxes(tickangle=45)
                
                charts['volume'] = plot(fig_volume, output_type='div', include_plotlyjs=False)
            except Exception as e:
                print(f"Volume trend chart generation error: {str(e)}")
                charts['volume'] = ""
        else:
            print("Volume trend data not found")
            charts['volume'] = ""
        
        # Moving average line analysis chart
        ma_data = self._analyze_ma_position(df)
        
        # Add debug information
        print("\nMA analysis results:")
        print(f"Data exists: {ma_data is not None}")
        if ma_data is not None:
            print(f"Data count: {len(ma_data)}")
            print(f"Columns: {ma_data.columns.tolist()}")
        
        # Check if data is correctly retrieved
        if ma_data is not None and not ma_data.empty:
            # MA200 chart
            if 'ma200_category' in ma_data.columns:
                try:
                    ma200_stats = ma_data.groupby('ma200_category').agg({
                        'pnl_rate': ['mean', 'count'],
                        'pnl': lambda x: (x > 0).mean() * 100
                    }).round(2)
                    
                    # ... chart generation code ...
                    fig_ma200 = go.Figure()
                    fig_ma200.add_trace(go.Bar(
                        x=ma200_stats.index,
                        y=ma200_stats[('pnl_rate', 'mean')],
                        name=self.get_text('average_return'),
                        text=ma200_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
                        textposition='auto',
                        marker_color=[
                            self.DARK_THEME['profit_color'] if x > 0 
                            else self.DARK_THEME['loss_color'] 
                            for x in ma200_stats[('pnl_rate', 'mean')]
                        ]
                    ))
                    
                    # Line for win rate
                    fig_ma200.add_trace(go.Scatter(
                        x=ma200_stats.index,
                        y=ma200_stats[('pnl', '<lambda>')],
                        name=self.get_text('win_rate'),
                        yaxis='y2',
                        line=dict(color=self.DARK_THEME['line_color'])
                    ))
                    
                    fig_ma200.update_layout(
                        title=self.get_text('ma200_analysis'),
                        xaxis_title=self.get_text('ma200_category'),
                        yaxis_title=self.get_text('return_pct'),
                        yaxis2=dict(
                            title=self.get_text('win_rate'),
                            overlaying='y',
                            side='right',
                            range=[0, 100]
                        ),
                        template='plotly_dark',
                        paper_bgcolor=self.DARK_THEME['bg_color'],
                        plot_bgcolor=self.DARK_THEME['plot_bg_color'],
                        showlegend=True,
                        legend=dict(
                            orientation='h',
                            yanchor='bottom',
                            y=1.02,
                            xanchor='right',
                            x=1
                        )
                    )
                    
                    charts['ma200'] = plot(fig_ma200, output_type='div', include_plotlyjs=False)
                except Exception as e:
                    print(f"MA200 chart generation error: {str(e)}")
                    charts['ma200'] = ""  # Set empty string when error occurs
            else:
                print("MA200 category not found")
                charts['ma200'] = ""
        else:
            print("MA analysis data not found")
            charts['ma200'] = ""
        
        # Process MA50 similarly
        if ma_data is not None and not ma_data.empty:
            if 'ma50_category' in ma_data.columns:
                try:
                    # ... MA50 chart generation code ...
                    ma50_stats = ma_data.groupby('ma50_category').agg({
                        'pnl_rate': ['mean', 'count'],
                        'pnl': lambda x: (x > 0).mean() * 100
                    }).round(2)
                    
                    fig_ma50 = go.Figure()
                    fig_ma50.add_trace(go.Bar(
                        x=ma50_stats.index,
                        y=ma50_stats[('pnl_rate', 'mean')],
                        name=self.get_text('average_return'),
                        text=ma50_stats[('pnl_rate', 'mean')].apply(lambda x: f'{x:.1f}%'),
                        textposition='auto',
                        marker_color=[
                            self.DARK_THEME['profit_color'] if x > 0 
                            else self.DARK_THEME['loss_color'] 
                            for x in ma50_stats[('pnl_rate', 'mean')]
                        ]
                    ))
                    
                    # Line for win rate
                    fig_ma50.add_trace(go.Scatter(
                        x=ma50_stats.index,
                        y=ma50_stats[('pnl', '<lambda>')],
                        name=self.get_text('win_rate'),
                        yaxis='y2',
                        line=dict(color=self.DARK_THEME['line_color'])
                    ))
                    
                    fig_ma50.update_layout(
                        title=self.get_text('ma50_analysis'),
                        xaxis_title=self.get_text('ma50_category'),
                        yaxis_title=self.get_text('return_pct'),
                        yaxis2=dict(
                            title=self.get_text('win_rate'),
                            overlaying='y',
                            side='right',
                            range=[0, 100]
                        ),
                        template='plotly_dark',
                        paper_bgcolor=self.DARK_THEME['bg_color'],
                        plot_bgcolor=self.DARK_THEME['plot_bg_color'],
                        showlegend=True,
                        legend=dict(
                            orientation='h',
                            yanchor='bottom',
                            y=1.02,
                            xanchor='right',
                            x=1
                        )
                    )
                    
                    charts['ma50'] = plot(fig_ma50, output_type='div', include_plotlyjs=False)
                except Exception as e:
                    print(f"MA50 chart generation error: {str(e)}")
                    charts['ma50'] = ""
            else:
                print("MA50 category not found")
                charts['ma50'] = ""
        else:
            charts['ma50'] = ""
        
        # Market Cap Performance analysis
        try:
            market_cap_stats = self._analyze_market_cap_performance(df)
            if not market_cap_stats.empty:
                charts['market_cap'] = self._create_market_cap_performance_chart(market_cap_stats)
            else:
                charts['market_cap'] = ""
        except Exception as e:
            print(f"Market Cap analysis error: {str(e)}")
            charts['market_cap'] = ""
        
        # Price Range Performance analysis
        try:
            price_range_stats = self._analyze_price_range_performance(df)
            if not price_range_stats.empty:
                charts['price_range'] = self._create_price_range_performance_chart(price_range_stats)
            else:
                charts['price_range'] = ""
        except Exception as e:
            print(f"Price Range analysis error: {str(e)}")
            charts['price_range'] = ""
        
        return charts

    def _calculate_trend_data(self, df):
        """Calculate trend data before earnings"""
        trends = []
        for _, trade in df.iterrows():
            # Get pre-earnings stock data
            pre_earnings_start = (pd.to_datetime(trade['entry_date']) - 
                                timedelta(days=30)).strftime('%Y-%m-%d')
            stock_data = self.get_historical_data(
                trade['ticker'],
                pre_earnings_start,
                trade['entry_date']
            )
            
            if stock_data is not None and len(stock_data) >= 20:
                # Calculate 21-day moving average
                stock_data['MA21'] = stock_data['Close'].rolling(window=21).mean()
                
                # Calculate 20-day price change rate
                price_change = ((stock_data['Close'].iloc[-1] - stock_data['Close'].iloc[-20]) / 
                              stock_data['Close'].iloc[-20] * 100)
                
                # Relationship between 20-day moving average and price
                ma_position = 'above' if stock_data['Close'].iloc[-1] > stock_data['MA21'].iloc[-1] else 'below'
                
                trends.append({
                    'ticker': trade['ticker'],
                    'entry_date': trade['entry_date'],
                    'pre_earnings_change': price_change,
                    'ma_position': ma_position,
                    'pnl_rate': trade['pnl_rate'],
                    'pnl': trade['pnl']  # Add pnl
                })
        
        trend_df = pd.DataFrame(trends)
        
        if not trend_df.empty:
            # Create bins by trend strength
            trend_df['trend_bin'] = pd.cut(trend_df['pre_earnings_change'],
                                         bins=[-np.inf, -20, -10, 0, 10, 20, np.inf],
                                         labels=['<-20%', '-20~-10%', '-10~0%', '0~10%', '10~20%', '>20%'])
            
            # Statistics by trend
            trend_stats = trend_df.groupby('trend_bin').agg({
                'pnl_rate': ['mean', 'std', 'count']
            }).round(2)
            
            print("\nPerformance by trend:")
            for trend_bin in trend_stats.index:
                stats = trend_stats.loc[trend_bin]
                print(f"\n{trend_bin}:")
                print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
                print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
                print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")
        
        return trend_df  # Return DataFrame

    def _analyze_breakout_performance(self, df):
        """Analysis of breakout pattern"""
        print("\n=== Breakout pattern analysis ===")
        
        breakouts = []
        for _, trade in df.iterrows():
            # Get pre-earnings stock data
            pre_earnings_start = (pd.to_datetime(trade['entry_date']) - 
                                timedelta(days=60)).strftime('%Y-%m-%d')
            stock_data = self.get_historical_data(
                trade['ticker'],
                pre_earnings_start,
                trade['entry_date']
            )
            
            if stock_data is not None and len(stock_data) >= 20:
                # Calculate 20-day high
                high_20d = stock_data['High'].rolling(window=20).max().iloc[-2]  # 20-day high before the previous day
                
                # Determine if it's a breakout
                is_breakout = trade['entry_price'] > high_20d
                breakout_percent = ((trade['entry_price'] - high_20d) / high_20d * 100) if is_breakout else 0
                
                breakouts.append({
                    'ticker': trade['ticker'],
                    'entry_date': trade['entry_date'],
                    'is_breakout': is_breakout,
                    'breakout_percent': breakout_percent,
                    'pnl_rate': trade['pnl_rate']
                })
        
        breakout_df = pd.DataFrame(breakouts)
        
        # Statistics by breakout presence
        breakout_stats = breakout_df.groupby('is_breakout').agg({
            'pnl_rate': ['mean', 'std', 'count']
        }).round(2)
        
        # Analysis by breakout size
        breakout_df['breakout_bin'] = pd.cut(breakout_df['breakout_percent'],
                                            bins=[-np.inf, 0, 2, 5, 10, np.inf],
                                            labels=['No Breakout', '0-2%', '2-5%', '5-10%', '>10%'])
        
        size_stats = breakout_df.groupby('breakout_bin').agg({
            'pnl_rate': ['mean', 'std', 'count']
        }).round(2)
        
        print("\nPerformance by breakout pattern:")
        for breakout_bin in size_stats.index:
            stats = size_stats.loc[breakout_bin]
            print(f"\n{breakout_bin}:")
            print(f"- Average return: {stats[('pnl_rate', 'mean')]:.2f}%")
            print(f"- Standard deviation: {stats[('pnl_rate', 'std')]:.2f}%")
            print(f"- Number of trades: {stats[('pnl_rate', 'count')]}")

    def _analyze_ma_position(self, df):
        """Analysis of stock price position relative to moving average"""
        ma_positions = []
        
        print(f"\nStarting MA analysis... Number of trades: {len(df)}")
        
        for _, trade in df.iterrows():
            try:
                print(f"\nProcessing: {trade['ticker']}")
                
                # Get data for 250 days before earnings (for 200-day MA calculation)
                entry_date = pd.to_datetime(trade['entry_date'])
                pre_earnings_start = (entry_date - timedelta(days=300)).strftime('%Y-%m-%d')
                
                # If future date, use current date
                current_date = datetime.now()
                if entry_date > current_date:
                    print(f"Warning: Future date ({entry_date.strftime('%Y-%m-%d')}) specified. Using current date.")
                    entry_date = current_date
                
                print(f"Data retrieval period: {pre_earnings_start} to {entry_date.strftime('%Y-%m-%d')}")
                
                stock_data = self.get_historical_data(
                    trade['ticker'],
                    pre_earnings_start,
                    entry_date.strftime('%Y-%m-%d')
                )
                
                print(f"Data retrieval result: {stock_data is not None}")
                if stock_data is not None:
                    print(f"Data count: {len(stock_data)}")
                
                if stock_data is not None and len(stock_data) >= 200:
                    # Calculate moving averages
                    stock_data['MA200'] = stock_data['Close'].rolling(window=200).mean()
                    stock_data['MA50'] = stock_data['Close'].rolling(window=50).mean()
                    
                    # Calculate the relationship between the latest stock price and the moving average
                    latest_close = stock_data['Close'].iloc[-1]
                    latest_ma200 = stock_data['MA200'].iloc[-1]
                    latest_ma50 = stock_data['MA50'].iloc[-1]
                    
                    print(f"Latest stock price: ${latest_close:.2f}")  # Debug log
                    print(f"MA200: ${latest_ma200:.2f}")  # Debug log
                    print(f"MA50: ${latest_ma50:.2f}")  # Debug log
                    
                    # Categorize the position relative to MA200
                    ma200_diff = (latest_close - latest_ma200) / latest_ma200 * 100
                    if ma200_diff > 30:
                        ma200_category = 'Very Far Above MA200 (>30%)'
                    elif ma200_diff > 15:
                        ma200_category = 'Far Above MA200 (15-30%)'
                    elif ma200_diff > 0:
                        ma200_category = 'Above MA200 (0-15%)'
                    elif ma200_diff > -15:
                        ma200_category = 'Below MA200 (-15-0%)'
                    else:
                        ma200_category = 'Very Far Below MA200 (<-15%)'
                    
                    # Categorize the position relative to MA50
                    ma50_diff = (latest_close - latest_ma50) / latest_ma50 * 100
                    if ma50_diff > 20:
                        ma50_category = 'Very Far Above MA50 (>20%)'
                    elif ma50_diff > 10:
                        ma50_category = 'Far Above MA50 (10-20%)'
                    elif ma50_diff > 0:
                        ma50_category = 'Above MA50 (0-10%)'
                    elif ma50_diff > -10:
                        ma50_category = 'Below MA50 (-10-0%)'
                    else:
                        ma50_category = 'Very Far Below MA50 (<-10%)'
                    
                    ma_positions.append({
                        'ticker': trade['ticker'],
                        'entry_date': trade['entry_date'],
                        'ma200_category': ma200_category,
                        'ma50_category': ma50_category,
                        'pnl_rate': trade['pnl_rate'],
                        'pnl': trade['pnl']
                    })
                    print(f"Analysis completed for {trade['ticker']}")
                    
                else:
                    print(f"Not enough historical data")
                    
            except Exception as e:
                print(f"Error ({trade['ticker']}): {str(e)}")
                continue
        
        result_df = pd.DataFrame(ma_positions)
        print(f"\nAnalysis completed: {len(result_df)} trades")
        
        # Set categories only if data exists
        if not result_df.empty:
            print(f"Columns: {result_df.columns.tolist()}")
            
            # Set order for MA200 category
            if 'ma200_category' in result_df.columns:
                result_df['ma200_category'] = pd.Categorical(
                    result_df['ma200_category'],
                    categories=[
                        'Very Far Below MA200 (<-15%)',
                        'Below MA200 (-15-0%)',
                        'Above MA200 (0-15%)',
                        'Far Above MA200 (15-30%)',
                        'Very Far Above MA200 (>30%)'
                    ],
                    ordered=True
                )
            
            # Set order for MA50 category
            if 'ma50_category' in result_df.columns:
                result_df['ma50_category'] = pd.Categorical(
                    result_df['ma50_category'],
                    categories=[
                        'Very Far Below MA50 (<-10%)',
                        'Below MA50 (-10-0%)',
                        'Above MA50 (0-10%)',
                        'Far Above MA50 (10-20%)',
                        'Very Far Above MA50 (>20%)'
                    ],
                    ordered=True
                )
        
        return result_df


    def _generate_trades_table_html(self):
        """Generate HTML for trade history table"""
        rows = []
        df = pd.DataFrame(self.trades).sort_values('entry_date', ascending=False)
        
        for _, trade in df.iterrows():
            pnl_class = 'profit' if trade['pnl'] >= 0 else 'loss'
            holding_period = f"{trade['holding_period']}{self.get_text('days')}"
            
            row = f"""
                <tr>
                    <td>{trade['ticker']}</td>
                    <td>{pd.to_datetime(trade['entry_date']).strftime('%Y-%m-%d')}</td>
                    <td>${trade['entry_price']:.2f}</td>
                    <td>{pd.to_datetime(trade['exit_date']).strftime('%Y-%m-%d')}</td>
                    <td>${trade['exit_price']:.2f}</td>
                    <td>{holding_period}</td>
                    <td>{trade['shares']}</td>
                    <td class="{pnl_class}">{trade['pnl_rate']:.2f}%</td>
                    <td class="{pnl_class}">${trade['pnl']:.2f}</td>
                    <td>{trade['exit_reason']}</td>
                </tr>
            """
            rows.append(row)
        
        table = f"""
            <table class="sortable-table">
                <thead>
                    <tr>
                        <th>{self.get_text('symbol')}</th>
                        <th>{self.get_text('entry_date')}</th>
                        <th>{self.get_text('entry_price')}</th>
                        <th>{self.get_text('exit_date')}</th>
                        <th>{self.get_text('exit_price')}</th>
                        <th>{self.get_text('holding_period')}</th>
                        <th>{self.get_text('shares')}</th>
                        <th>{self.get_text('pnl_rate')}</th>
                        <th>{self.get_text('pnl')}</th>
                        <th>{self.get_text('exit_reason')}</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        """
        
        return table

    def get_market_cap(self, symbol):
        """Get market cap from FMP"""
        try:
            # Use FMP client to get company profile
            profile_data = self.fmp_client.get_company_profile(symbol)
            if profile_data:
                market_cap = profile_data.get('mktCap')
                if market_cap:
                    return float(market_cap)
            return None
            
        except Exception as e:
            print(f"Market cap retrieval error ({symbol}): {str(e)}")
            return None

    def _categorize_market_cap(self, market_cap):
        """Categorize market cap into categories"""
        if market_cap is None:
            return "Unknown"
        
        market_cap_billions = market_cap / 1_000_000_000  # Convert to billions
        
        if market_cap_billions >= 200:
            return "Mega Cap ($200B+)"
        elif market_cap_billions >= 10:
            return "Large Cap ($10B-$200B)"
        elif market_cap_billions >= 2:
            return "Mid Cap ($2B-$10B)"
        elif market_cap_billions >= 0.3:
            return "Small Cap ($300M-$2B)"
        else:
            return "Micro Cap (<$300M)"

    def _categorize_price_range(self, price):
        """Categorize price into categories"""
        if price is None:
            return "Unknown"
        
        if price > 100:
            return "High Price (>$100)"
        elif price >= 30:
            return "Mid Price ($30-$100)"
        else:
            return "Low Price (<$30)"

    def _analyze_market_cap_performance(self, df):
        """Performance analysis by market cap category"""
        market_cap_performance = []
        
        for _, trade in df.iterrows():
            try:
                symbol = trade['ticker']
                market_cap = self.get_market_cap(symbol)
                market_cap_category = self._categorize_market_cap(market_cap)
                
                market_cap_performance.append({
                    'symbol': symbol,
                    'market_cap': market_cap,
                    'market_cap_category': market_cap_category,
                    'pnl_rate': trade['pnl_rate'],
                    'pnl': trade['pnl']
                })
                
            except Exception as e:
                print(f"Market cap analysis error ({symbol}): {str(e)}")
                continue
        
        if not market_cap_performance:
            print("Market cap data not found")
            return pd.DataFrame()
        
        result_df = pd.DataFrame(market_cap_performance)
        
        # Calculate statistics by category
        category_stats = result_df.groupby('market_cap_category').agg({
            'pnl_rate': ['mean', 'count', lambda x: (x > 0).sum()],
            'pnl': 'sum'
        }).round(2)
        
        category_stats.columns = ['avg_return', 'trade_count', 'winning_trades', 'total_pnl']
        category_stats['win_rate'] = (category_stats['winning_trades'] / category_stats['trade_count'] * 100).round(1)
        
        print("\n=== Market Cap Performance Analysis ===")
        print(category_stats)
        
        return category_stats

    def _analyze_price_range_performance(self, df):
        """Performance analysis by price range"""
        price_range_performance = []
        
        for _, trade in df.iterrows():
            try:
                symbol = trade['ticker']
                entry_price = trade['entry_price']
                price_category = self._categorize_price_range(entry_price)
                
                price_range_performance.append({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'price_category': price_category,
                    'pnl_rate': trade['pnl_rate'],
                    'pnl': trade['pnl']
                })
                
            except Exception as e:
                print(f"Price range analysis error ({symbol}): {str(e)}")
                continue
        
        if not price_range_performance:
            print("Price range data not found")
            return pd.DataFrame()
        
        result_df = pd.DataFrame(price_range_performance)
        
        # Calculate statistics by category
        category_stats = result_df.groupby('price_category').agg({
            'pnl_rate': ['mean', 'count', lambda x: (x > 0).sum()],
            'pnl': 'sum'
        }).round(2)
        
        category_stats.columns = ['avg_return', 'trade_count', 'winning_trades', 'total_pnl']
        category_stats['win_rate'] = (category_stats['winning_trades'] / category_stats['trade_count'] * 100).round(1)
        
        print("\n=== Price Range Performance Analysis ===")
        print(category_stats)
        
        return category_stats

    def _create_market_cap_performance_chart(self, category_stats):
        """Create Market Cap Performance chart"""
        if category_stats.empty:
            return "<p>Market cap data not found</p>"
        
        # Prepare data
        categories = category_stats.index.tolist()
        avg_returns = category_stats['avg_return'].values
        win_rates = category_stats['win_rate'].values
        trade_counts = category_stats['trade_count'].values
        
        # Set colors
        bar_colors = ['#22c55e' if x >= 0 else '#ef4444' for x in avg_returns]
        
        # Create composite chart
        fig = go.Figure()
        
        # Bar chart (average return)
        fig.add_trace(go.Bar(
            x=categories,
            y=avg_returns,
            name='Average Return',
            marker_color=bar_colors,
            text=[f'{x:.1f}% ({int(c)})' for x, c in zip(avg_returns, trade_counts)],
            textposition='outside',
            yaxis='y'
        ))
        
        # Line chart (win rate)
        fig.add_trace(go.Scatter(
            x=categories,
            y=win_rates,
            mode='lines+markers',
            name='Win Rate',
            line=dict(color='#60a5fa', width=3),
            marker=dict(size=8),
            yaxis='y2'
        ))
        
        # Set layout
        fig.update_layout(
            title='Market Cap Performance Analysis',
            xaxis_title='Market Cap Category',
            yaxis=dict(
                title='Return (%)',
                side='left'
            ),
            yaxis2=dict(
                title='Win Rate (%)',
                side='right',
                overlaying='y',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor='#1e293b',
            plot_bgcolor='#1e293b',
            showlegend=True,
            height=500
        )
        
        return plot(fig, output_type='div', include_plotlyjs=False)

    def _create_price_range_performance_chart(self, category_stats):
        """Create Price Range Performance chart"""
        if category_stats.empty:
            return "<p>Price range data not found</p>"
        
        # Prepare data
        categories = category_stats.index.tolist()
        avg_returns = category_stats['avg_return'].values
        win_rates = category_stats['win_rate'].values
        trade_counts = category_stats['trade_count'].values
        
        # Set colors
        bar_colors = ['#22c55e' if x >= 0 else '#ef4444' for x in avg_returns]
        
        # Create composite chart
        fig = go.Figure()
        
        # Bar chart (average return)
        fig.add_trace(go.Bar(
            x=categories,
            y=avg_returns,
            name='Average Return',
            marker_color=bar_colors,
            text=[f'{x:.1f}% ({int(c)})' for x, c in zip(avg_returns, trade_counts)],
            textposition='outside',
            yaxis='y'
        ))
        
        # Line chart (win rate)
        fig.add_trace(go.Scatter(
            x=categories,
            y=win_rates,
            mode='lines+markers',
            name='Win Rate',
            line=dict(color='#60a5fa', width=3),
            marker=dict(size=8),
            yaxis='y2'
        ))
        
        # Set layout
        fig.update_layout(
            title='Price Range Performance Analysis',
            xaxis_title='Price Range Category',
            yaxis=dict(
                title='Return (%)',
                side='left'
            ),
            yaxis2=dict(
                title='Win Rate (%)',
                side='right',
                overlaying='y',
                range=[0, 100]
            ),
            template='plotly_dark',
            paper_bgcolor='#1e293b',
            plot_bgcolor='#1e293b',
            showlegend=True,
            height=500
        )
        
        return plot(fig, output_type='div', include_plotlyjs=False)

    def _analyze_volume_trend(self, df):
        """Analyze volume trend before earnings"""
        volume_trends = []
        
        for _, trade in df.iterrows():
            # Get data for 90 days before earnings (for comparison of 60-day and 20-day averages)
            pre_earnings_start = (pd.to_datetime(trade['entry_date']) - 
                                timedelta(days=90)).strftime('%Y-%m-%d')
            stock_data = self.get_historical_data(
                trade['ticker'],
                pre_earnings_start,
                trade['entry_date']
            )
            
            if stock_data is not None and len(stock_data) >= 60:
                # Calculate recent 20-day and past 60-day average volume
                recent_volume = stock_data['Volume'].tail(20).mean()
                historical_volume = stock_data['Volume'].tail(60).mean()
                
                # Calculate volume change rate
                volume_change = ((recent_volume - historical_volume) / 
                               historical_volume * 100)
                
                # Categorize by volume change rate (5 levels)
                if volume_change >= 100:
                    volume_category = 'Very Large Increase (>100%)'
                elif volume_change >= 50:
                    volume_category = 'Large Increase (50-100%)'
                elif volume_change >= 20:
                    volume_category = 'Moderate Increase (20-50%)'
                elif volume_change >= -20:
                    volume_category = 'Neutral (-20-20%)'
                else:
                    volume_category = 'Decrease (<-20%)'
                
                volume_trends.append({
                    'ticker': trade['ticker'],
                    'entry_date': trade['entry_date'],
                    'volume_change': volume_change,
                    'volume_category': volume_category,
                    'pnl_rate': trade['pnl_rate'],
                    'pnl': trade['pnl']  # Add pnl
                })
        
        return pd.DataFrame(volume_trends)

    def gather_trade_result(self):
        """Retrieve actual trade results from Alpaca"""
        print("\nRetrieving actual trade results from Alpaca...")
        print(f"Period: {self.start_date} to {self.end_date}")
        
        # 1. Retrieve trade data
        print("\n1. Retrieving trade history...")
        df_trades = self.get_activities(self.start_date, self.end_date)
        
        if df_trades.empty:
            print("No trades found within the specified period")
            return
        
        print(f"Retrieved trades: {len(df_trades)}")
        
        # 2. Retrieve corporate actions
        print("\n2. Retrieving corporate actions...")
        df_splits = self.get_corporate_actions(
            self.start_date, 
            self.end_date, 
            df_trades['symbol'].unique().tolist()
        )
        
        # 3. Process trade data
        print("\n3. Processing trade data...")
        self.process_trade_data(df_trades, df_splits)
        
        print("\n4. Trade processing complete")
        print(f"Processed trades: {len(self.trades)}")
        
        # Calculate initial capital (equity at first trade date)
        if self.trades:
            # Sort trades by date
            sorted_trades = sorted(self.trades, key=lambda x: pd.to_datetime(x['entry_date']))
            
            # Get equity at first trade date
            first_trade_date = pd.to_datetime(sorted_trades[0]['entry_date'])
            
            # Use previous day's equity as initial capital
            prev_day = (first_trade_date - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            try:
                self.initial_capital = self.get_account_equity_at_date(prev_day)
                print(f"Initial capital: ${self.initial_capital:,.2f} ({prev_day})")
            except Exception as e:
                print(f"Failed to retrieve initial capital: {str(e)}")
                print(f"Using default value: ${self.initial_capital:,.2f}")
        
        # Record final capital
        self.final_capital = self.get_account_equity()
        print(f"Final capital: ${self.final_capital:,.2f}")

    def get_activities(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get trade history from Alpaca API
        
        Args:
            start_date (str): Start date (YYYY-MM-DD)
            end_date (str): End date (YYYY-MM-DD)
            
        Returns:
            pd.DataFrame: Trade history DataFrame
        """
        # Initialize Alpaca API client
        api = tradeapi.REST(
            ALPACA_API_KEY,
            ALPACA_SECRET_KEY,
            base_url=ALPACA_API_URL,
            api_version='v2'
        )

        activities = []
        page_token = None

        # Use pagination to get all trade history
        while True:
            try:
                response = api.get_activities(
                    activity_types='FILL',
                    after=f"{start_date}T00:00:00Z",
                    until=f"{end_date}T23:59:59Z",
                    page_token=page_token,
                    direction='asc',
                    page_size=100
                )

                if not response:
                    break

                # Convert each activity to dictionary (activity is a list of dictionaries)
                for activity in response:
                    activities.append({
                        'symbol': activity.symbol,
                        'side': activity.side.lower(),
                        'qty': float(activity.qty),
                        'price': float(activity.price),
                        'transaction_time': pd.to_datetime(activity.transaction_time),
                        'order_id': activity.order_id,
                        'type': activity.type
                    })

                # If response is less than 100, there are no more pages (100 is the maximum page size)
                if len(response) < 100:
                    break
                
                # Set next page token
                page_token = response[-1].id

            except Exception as e:
                print(f"Error occurred while retrieving trade history: {str(e)}")
                break

        # Convert activities to DataFrame
        df = pd.DataFrame(activities)
        
        # Sort by date
        if not df.empty:
            df = df.sort_values('transaction_time').reset_index(drop=True)
        
        return df

    def get_corporate_actions(self, start_date: str, end_date: str, symbols: List[str] = None) -> pd.DataFrame:
        """
        Get corporate actions (e.g. stock splits)
        
        Args:
            start_date (str): Start date (YYYY-MM-DD)
            end_date (str): End date (YYYY-MM-DD)
            symbols (List[str], optional): Stock list
            
        Returns:
            pd.DataFrame: Corporate actions information DataFrame
        """
        try:
            # Set API endpoint
            base_url = ALPACA_API_URL.replace('api.', 'data.')
            url = f"{base_url}/v1/corporate-actions"
            
            headers = {
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
                "accept": "application/json"
            }
            
            # Set query parameters
            params = {
                "types": "forward_split",  # Get only stock splits
                "start": start_date,
                "end": end_date,
                "limit": 1000,
                "sort": "asc"
            }
            
            # If symbols are specified, add them as comma-separated list
            if symbols:
                params["symbols"] = ",".join(symbols)
                print(f"\nRetrieving corporate actions for {len(symbols)} stocks")
                print(f"Period: {start_date} to {end_date}")
            
            # Execute API request
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Process response data
            corporate_actions = []
            if isinstance(data, dict) and 'corporate_actions' in data:
                forward_splits = data['corporate_actions'].get('forward_splits', [])
                for split in forward_splits:
                    split_ratio = float(split['new_rate']) / float(split['old_rate'])
                    corporate_actions.append({
                        'symbol': split['symbol'],
                        'split_date': split['ex_date'],
                        'ratio': split_ratio
                    })
                    print(f"Detected stock split: {split['symbol']}, Date: {split['ex_date']}, "
                          f"Ratio: {split['old_rate']}:{split['new_rate']}")
            
            # Create and format DataFrame
            df = pd.DataFrame(corporate_actions)
            if not df.empty:
                # Interpret as UTC timezone
                df['split_date'] = pd.to_datetime(df['split_date']).dt.tz_localize('UTC')
                df = df.sort_values('split_date').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            print(f"Error occurred while retrieving corporate actions: {str(e)}")
            if hasattr(e, 'response'):
                print(f"Response status: {e.response.status_code}")
                print(f"Response content: {e.response.text}")
            
            # If error, return empty DataFrame
            return pd.DataFrame(columns=['symbol', 'split_date', 'ratio'])

    def process_trade_data(self, df_trades: pd.DataFrame, df_splits: pd.DataFrame):
        """
        Process trade data and calculate P&L using FIFO method
        
        Args:
            df_trades (pd.DataFrame): Trade history
            df_splits (pd.DataFrame): Corporate actions information
        """
        if df_trades.empty:
            return
        
        # 1) Sort by time series
        df_trades = df_trades.sort_values(by='transaction_time').reset_index(drop=True)

        # 2) Apply stock splits
        for idx, row in df_splits.iterrows():
            symbol = row['symbol']
            split_time = row['split_date']
            ratio = row['ratio']

            mask = (df_trades['symbol'] == symbol) & (df_trades['transaction_time'] >= split_time)
            df_trades.loc[mask, 'qty'] = df_trades.loc[mask, 'qty'] * ratio
            df_trades.loc[mask, 'price'] = df_trades.loc[mask, 'price'] / ratio

        # 3) Calculate P&L using FIFO method
        trades_summary = []
        positions = {}  # symbol -> [(qty, price, entry_time)]

        for _, trade in df_trades.iterrows():
            symbol = trade['symbol']
            side = trade['side']
            qty = float(trade['qty'])
            price = float(trade['price'])
            time = trade['transaction_time']
            
            if symbol not in positions:
                positions[symbol] = []

            if side == 'buy':
                # Process buy order
                positions[symbol].append((qty, price, time))
                
            elif side == 'sell' and positions[symbol]:
                # Process sell order
                remaining_sell = qty
                
                while remaining_sell > 0 and positions[symbol]:
                    buy_qty, buy_price, buy_time = positions[symbol][0]
                    sell_qty = min(remaining_sell, buy_qty)
                    
                    # Calculate P&L
                    pnl = (price - buy_price) * sell_qty
                    pnl_pct = ((price / buy_price) - 1) * 100
                    
                    # Update position
                    if sell_qty == buy_qty:
                        positions[symbol].pop(0)
                    else:
                        positions[symbol][0] = (buy_qty - sell_qty, buy_price, buy_time)
                    
                    remaining_sell -= sell_qty
                    
                    # Calculate gap size
                    # Get previous day's close price from FMP API
                    prev_day = time.date() - pd.Timedelta(days=1)
                    prev_close = self.get_previous_close(symbol, prev_day)
                    gap_size = ((price / prev_close) - 1) * 100 if prev_close else 0
                    
                    # Calculate holding period
                    holding_period = (time - buy_time).days
                    
                    # Add trade record
                    trade_record = {
                        'entry_date': buy_time.strftime('%Y-%m-%d'),
                        'exit_date': time.strftime('%Y-%m-%d'),
                        'ticker': symbol,
                        'shares': sell_qty,
                        'entry_price': buy_price,
                        'exit_price': price,
                        'pnl': pnl,
                        'pnl_rate': pnl_pct,
                        'holding_period': holding_period,
                        'exit_reason': 'sell',  # Reason is unknown in actual trades
                        'gap': gap_size
                    }
                    
                    self.trades.append(trade_record)

    def get_previous_close(self, symbol: str, date: datetime.date) -> float:
        """
        Get previous day's close price from FMP API
        
        Args:
            symbol (str): Stock code (e.g. AAPL, BF.B, BF.B.US, etc.)
            date (datetime.date): Date
            
        Returns:
            float: Previous day's close price
        """
        try:
            # Remove .US if it exists
            base_symbol = symbol[:-3] if symbol.endswith('.US') else symbol
            
            # Get historical data using FMP client
            from_date = (date - pd.Timedelta(days=5)).strftime('%Y-%m-%d')  # Get data from 5 days ago
            to_date = date.strftime('%Y-%m-%d')
            
            price_data = self.fmp_client.get_historical_price_data(
                symbol=base_symbol,
                from_date=from_date,
                to_date=to_date
            )
            
            # Find latest close price before specified date
            if price_data and len(price_data) > 0:
                for data_point in reversed(price_data):
                    price_date = pd.to_datetime(data_point['date']).date()
                    if price_date < date:
                        # FMP uses 'adjClose' field for adjusted close prices
                        return float(data_point.get('adjClose', data_point.get('close')))
            
            return None
            
        except Exception as e:
            print(f"Error occurred while retrieving previous close for {symbol}: {str(e)}")
            return None

    def get_account_equity(self) -> float:
        """
        Get current account equity from Alpaca API
        
        Returns:
            float: Account equity
        """
        try:
            api = tradeapi.REST(
                ALPACA_API_KEY,
                ALPACA_SECRET_KEY,
                base_url=ALPACA_API_URL,
                api_version='v2'
            )
            account = api.get_account()
            return float(account.equity)
        except Exception as e:
            print(f"Error occurred while retrieving account equity: {str(e)}")
            return self.initial_capital  # If error, return initial capital

    def get_account_equity_at_date(self, date: str) -> float:
        """
        Get account equity at specified date (using portfolio history API)
        
        Args:
            date (str): Date (YYYY-MM-DD)
            
        Returns:
            float: Equity at specified date
        """
        try:
            api = tradeapi.REST(
                ALPACA_API_KEY,
                ALPACA_SECRET_KEY,
                base_url=ALPACA_API_URL,
                api_version='v2'
            )
            
            # Convert date to datetime object and set start and end of that day
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            start_date = date_obj.strftime('%Y-%m-%d')
            end_date = (date_obj + timedelta(days=1)).strftime('%Y-%m-%d')
            
            # Set date according to API parameter format
            # Use correct parameters based on official documentation
            portfolio_history = api.get_portfolio_history(
                timeframe="1D",
                date_start=start_date,
                date_end=end_date,
                extended_hours=False
            )
            
            if portfolio_history and portfolio_history.equity and len(portfolio_history.equity) > 0:
                # Get last value
                return float(portfolio_history.equity[-1])
            else:
                # If no data, return current equity
                print(f"Warning: No asset data at {date}. Using current equity.")
                return self.get_account_equity()
                
        except Exception as e:
            print(f"Error occurred while retrieving equity at {date}: {str(e)}")
            # If error, return default value
            return 10000.0  # Default value

    def _generate_ai_analysis(self, metrics: dict) -> str:
        """Generate AI-based analysis using OpenAI GPT-4.1 (gpt-4o).

        Args:
            metrics: Performance metrics dictionary produced by ``calculate_metrics``.

        Returns:
            HTML snippet containing the analysis result (in English regardless of UI language).
        """
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return "<p><em>AI analysis unavailable: OPENAI_API_KEY not configured.</em></p>"

        client = OpenAI(api_key=openai_api_key)

        system_prompt = (
            "You are an expert risk manager and trading coach. "
            "Analyse the provided trading performance metrics objectively. "
            "Identify strengths, weaknesses, risk issues, and concrete improvement advice. "
            "Respond in a concise report style (bullet points where appropriate)."
        )

        user_content = (
            "Here are the trading performance metrics in JSON. "
            "Please evaluate them.\n\n" + str(metrics)
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.7,
                max_tokens=500,
            )

            analysis_text = response.choices[0].message.content.strip()
            # Ensure bullet lists are separated by a blank line so markdown converts properly
            lines = analysis_text.splitlines()
            fixed_lines = []
            for idx, line in enumerate(lines):
                stripped = line.lstrip()
                if stripped.startswith("-") and (idx == 0 or lines[idx-1].strip() != ""):
                    # insert blank line before standalone bullet list item
                    fixed_lines.append("")
                fixed_lines.append(line)
            analysis_text = "\n".join(fixed_lines)

            # Convert Markdown to HTML with lists rendered correctly
            analysis_html_body = markdown.markdown(analysis_text, extensions=["extra", "sane_lists"])
            analysis_html = (
                "<div class=\"section\">"
                "<h2>AI Insights</h2>" + analysis_html_body + "</div>"
            )
            return analysis_html
        except Exception as e:
            logging.error(f"OpenAI analysis failed: {e}")
            return f"<p><em>AI analysis failed: {str(e)}</em></p>"

def main():
    parser = argparse.ArgumentParser(description='Generate Alpaca trade results report')
    parser.add_argument('--start_date', help='Start date (YYYY-MM-DD)', default=None)
    parser.add_argument('--end_date', help='End date (YYYY-MM-DD)', default=None)
    parser.add_argument('--language', choices=['ja', 'en'], default='en',
                      help='Report language (default: English)')
    
    args = parser.parse_args()
    
    # If start date is not specified, set to 1 month ago
    if not args.start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    else:
        start_date = args.start_date
    
    # If end date is not specified, set to current date
    if not args.end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    else:
        end_date = args.end_date

    # Create report generation instance
    report = TradeReport(
        start_date=start_date,
        end_date=end_date,
        language=args.language
    )
    
    # Get trade results
    report.gather_trade_result()
    
    # Generate report
    if report.trades:
        report.generate_report()
        report.generate_html_report()
    else:
        print("No trades found within the specified period. Report will not be generated.")

if __name__ == '__main__':
    main() 