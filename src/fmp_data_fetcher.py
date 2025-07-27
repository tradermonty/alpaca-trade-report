#!/usr/bin/env python3
"""
Financial Modeling Prep API Data Fetcher
High-precision earnings data provider using FMP API client
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
import time
import json

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FMPDataFetcher:
    """Financial Modeling Prep API client"""
    
    def __init__(self, api_key: str = None):
        """
        Initialize FMPDataFetcher
        
        Args:
            api_key: FMP API key
        """
        self.api_key = api_key or os.getenv('FMP_API_KEY')
        if not self.api_key:
            # Allow creation without API key – enter degraded mode
            logging.warning("FMP_API_KEY not found – running in degraded mode; data-dependent features will be skipped.")
            self.disabled = True
        else:
            self.disabled = False
        
        self.base_url = "https://financialmodelingprep.com/stable"
        self.alt_base_url = "https://financialmodelingprep.com/api/v3"
        self.session = requests.Session()
        
        # Maximum performance rate limiting - 750 calls/min full utilization
        # Starter: 300 calls/min, Premium: 750 calls/min, Ultimate: 3000 calls/min  
        self.rate_limiting_active = False  # Dynamic control flag
        self.calls_per_minute = 750  # Premium plan max value (use to limit)
        self.calls_per_second = 12.5  # 750/60 = 12.5 calls/sec
        self.call_timestamps = []
        self.last_request_time = datetime(1970, 1, 1)
        self.min_request_interval = 0.08  # 1/12.5 = 0.08 second interval (theoretical value)
        self.rate_limit_cooldown_until = datetime(1970, 1, 1)  # Rate limit release time
        
        # Performance optimization flag
        self.max_performance_mode = True  # No limits until 429 error
        
        logger.info("FMP Data Fetcher initialized successfully")
    
    def _rate_limit_check(self):
        """Maximum performance rate limit check - minimal limits until 429 error"""
        now = datetime.now()
        
        # Check for rate limit deactivation after cooldown period
        if self.rate_limiting_active and now > self.rate_limit_cooldown_until:
            self.rate_limiting_active = False
            self.max_performance_mode = True
            logger.info("Rate limiting deactivated - returning to maximum performance")
        
        # Apply strict limits only when 429 error occurs
        if self.rate_limiting_active:
            self.max_performance_mode = False
            # Apply conservative limits
            time_since_last = (now - self.last_request_time).total_seconds()
            if time_since_last < 0.2:  # 0.2 second interval when 429 occurs
                sleep_time = 0.2 - time_since_last
                logger.warning(f"Conservative rate limiting: sleeping {sleep_time:.3f}s")
                time.sleep(sleep_time)
                now = datetime.now()
                
            # Filter call history within the last minute
            self.call_timestamps = [
                ts for ts in self.call_timestamps 
                if (now - ts).total_seconds() < 60
            ]
            
            # Conservative per-minute limit (300 calls/min)
            if len(self.call_timestamps) >= 300:
                sleep_time = 60 - (now - self.call_timestamps[0]).total_seconds() + 1
                logger.warning(f"Conservative per-minute limit: sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
                now = datetime.now()
        elif self.max_performance_mode:
            # Maximum performance mode: completely disable limits until 429 error
            # Only natural rate limiting from network latency
            pass
        else:
            # Normal mode: use up to theoretical limit
            time_since_last = (now - self.last_request_time).total_seconds()
            if time_since_last < self.min_request_interval:
                sleep_time = self.min_request_interval - time_since_last
                time.sleep(sleep_time)
                now = datetime.now()
        
        # Record call history (only during 429 error)
        if self.rate_limiting_active:
            self.call_timestamps.append(now)
        
        self.last_request_time = now

    # ------------------------------------------------------------------
    # Symbol utilities
    # ------------------------------------------------------------------
    def _symbol_variants(self, symbol: str) -> List[str]:
        """Return symbol variations for cases where FMP API requires
        dash notation like `BRK-B`.

        Example: ``BRK.B`` → ["BRK.B", "BRK-B"]
        ``AAPL`` → ["AAPL"]
        """
        if '.' in symbol:
            return [symbol, symbol.replace('.', '-')]
        return [symbol]
    
    def _activate_rate_limiting(self, duration_minutes: int = 5):
        """Activate rate limiting when 429 error occurs"""
        self.rate_limiting_active = True
        self.max_performance_mode = False
        self.rate_limit_cooldown_until = datetime.now() + timedelta(minutes=duration_minutes)
        logger.warning(f"Rate limiting activated for {duration_minutes} minutes due to 429 error")
    
    def _make_request(self, endpoint: str, params: Dict = None, max_retries: int = 3) -> Optional[Dict]:
        """
        Execute FMP API request with retry and exponential backoff
        
        Args:
            endpoint: API endpoint
            params: Request parameters
            max_retries: Maximum retry count
        
        Returns:
            API response
        """
        if params is None:
            params = {}
        
        params['apikey'] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        
        # If client is disabled (e.g., invalid key) immediately return None
        if getattr(self, 'disabled', False):
            logger.debug("FMPDataFetcher disabled – skipping request")
            return None

        for attempt in range(max_retries + 1):
            # Rate limit check (minimal or strict limit after 429 error)
            self._rate_limit_check()
            
            try:
                response = self.session.get(url, params=params, timeout=30)
                
                # Handle different HTTP status codes
                if response.status_code == 404:
                    logger.debug(f"Endpoint not found (404): {endpoint}")
                    return None
                elif response.status_code == 403:
                    logger.warning(f"Access forbidden (403) for {endpoint} - check API plan limits")
                    return None
                elif response.status_code == 401:
                    # Invalid or expired API key – disable further calls
                    logger.error("FMP API responded 401 Unauthorized. Disabling FMPDataFetcher.")
                    self.disabled = True
                    return None
                elif response.status_code == 429:
                    # When 429 error occurs: activate dynamic rate limiting
                    self._activate_rate_limiting(duration_minutes=5)
                    
                    if attempt < max_retries:
                        # Exponential backoff: 2^attempt * 5 seconds + random jitter
                        base_delay = 5 * (2 ** attempt)
                        jitter = base_delay * 0.1 * (0.5 - time.time() % 1)  # ±10% jitter
                        delay = base_delay + jitter
                        
                        logger.warning(f"Rate limit exceeded (429) for {endpoint}. "
                                     f"Activating rate limiting for 5 minutes. "
                                     f"Attempt {attempt + 1}/{max_retries + 1}. "
                                     f"Retrying in {delay:.1f} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded (429) for {endpoint}. Max retries exceeded.")
                        return None
                
                response.raise_for_status()
                
                data = response.json()
                
                # Check for empty or invalid responses
                if data is None:
                    logger.debug(f"Empty response from {endpoint}")
                    return None
                elif isinstance(data, dict) and data.get('Error Message'):
                    logger.debug(f"API error for {endpoint}: {data.get('Error Message')}")
                    return None
                elif isinstance(data, list) and len(data) == 0:
                    logger.debug(f"Empty data array from {endpoint}")
                    return None
                
                logger.debug(f"Successfully fetched data from {endpoint}")
                return data
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    delay = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Request failed for {endpoint}: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    logger.debug(f"Request failed for {endpoint} after {max_retries} retries: {e}")
                    return None
            except json.JSONDecodeError as e:
                logger.debug(f"JSON decode error for {endpoint}: {e}")
                return None
        
        return None
    
    def _get_earnings_for_specific_symbols(self, symbols: List[str], from_date: str, to_date: str) -> List[Dict]:
        """
        Efficiently retrieve earnings data for specific symbols
        
        Args:
            symbols: List of symbols
            from_date: Start date
            to_date: End date
        
        Returns:
            List of earnings data
        """
        all_earnings = []
        
        for symbol in symbols:
            logger.info(f"Fetching earnings for {symbol}")

            data = None

            for sym in self._symbol_variants(symbol):
                # First try earnings-surprises endpoint
                endpoint = f'earnings-surprises/{sym}'
                params = {'limit': 80}

                data = self._make_request(endpoint, params)

                if not data:
                    # Fallback 1: historical/earning_calendar
                    logger.debug(f"earnings-surprises failed for {sym}, trying historical/earning_calendar")
                    original_base = self.base_url
                    self.base_url = self.alt_base_url
                    endpoint = f'historical/earning_calendar/{sym}'
                    data = self._make_request(endpoint, params)
                    self.base_url = original_base

                if not data:
                    # Fallback 2: v3 earnings API
                    logger.debug(f"historical/earning_calendar failed for {sym}, trying v3 earnings API")
                    original_base = self.base_url
                    self.base_url = self.alt_base_url
                    endpoint = f'earnings/{sym}'
                    data = self._make_request(endpoint, params)
                    self.base_url = original_base

                if data:
                    break  # Exit if a successful variation is found
            
            if not data:
                # Final fallback: use cached earnings calendar
                logger.warning(f"No direct earnings data found for {symbol}, will use bulk calendar as fallback")

            # ----------------- Format retrieved data -----------------
            if data:
                # Handle case where data is not a list
                if isinstance(data, dict):
                    data = [data]

                # Filter by date range
                filtered_data = []
                start_dt = datetime.strptime(from_date, '%Y-%m-%d')
                end_dt = datetime.strptime(to_date, '%Y-%m-%d')

                for item in data:
                    if 'date' in item:
                        try:
                            item_date = datetime.strptime(item['date'], '%Y-%m-%d')
                            if start_dt <= item_date <= end_dt:
                                # Convert to earnings-calendar format
                                earnings_item = {
                                    'date': item['date'],
                                    'symbol': symbol,
                                    'epsActual': item.get('actualEarningResult', item.get('eps', item.get('epsActual'))),
                                    'epsEstimate': item.get('estimatedEarning', item.get('epsEstimated', item.get('epsEstimate'))),
                                    'revenue': item.get('revenue'),
                                    'revenueEstimated': item.get('revenueEstimated'),
                                    'time': item.get('time', 'N/A'),
                                    'updatedFromDate': item.get('updatedFromDate', item['date']),
                                    'fiscalDateEnding': item.get('fiscalDateEnding', item['date'])
                                }
                                filtered_data.append(earnings_item)
                        except ValueError as e:
                            logger.debug(f"Date parsing error for {symbol}: {e}")

                logger.info(f"Found {len(filtered_data)} earnings records for {symbol} in date range")
                all_earnings.extend(filtered_data)
        
        return all_earnings
    
    def get_earnings_surprises(self, symbol: str, limit: int = 80) -> Optional[List[Dict]]:
        """
        Retrieve earnings surprise data for specific symbol (multiple endpoint support)
        
        Args:
            symbol: Stock symbol
            limit: Maximum number of records (default: 80 records, about 20 years)
        
        Returns:
            List of earnings surprise data, or None
        """
        logger.info(f"Fetching earnings surprises for {symbol}")
        
        params = {'limit': limit}

        data = None

        # Try symbol variations in sequence
        for sym in self._symbol_variants(symbol):
            # Endpoint 1: earnings-surprises (stable API)
            endpoint = f'earnings-surprises/{sym}'
            data = self._make_request(endpoint, params)

            if not data:
                # Endpoint 2: historical/earning_calendar (v3 API)
                logger.debug(f"earnings-surprises failed for {sym}, trying historical/earning_calendar")
                original_base = self.base_url
                self.base_url = self.alt_base_url
                endpoint = f'historical/earning_calendar/{sym}'
                data = self._make_request(endpoint, params)
                self.base_url = original_base
            
            if data:
                break  # Exit if successful with any variation
                
        if data:
            # Check data format and standardize to list
            if isinstance(data, dict):
                data = [data]
            
            # Standardize data format to earnings-surprises compatible
            standardized_data = []
            for item in data:
                standardized_item = {
                    'date': item.get('date'),
                    'actualEarningResult': item.get('actualEarningResult') or item.get('eps') or item.get('epsActual'),
                    'estimatedEarning': item.get('estimatedEarning') or item.get('epsEstimated') or item.get('epsEstimate')
                }
                standardized_data.append(standardized_item)
            
            logger.info(f"Retrieved {len(standardized_data)} earnings records for {symbol}")
            return standardized_data
        else:
            logger.warning(f"No earnings surprise data found for {symbol}")
            return None
    
    def get_earnings_calendar(self, from_date: str, to_date: str, target_symbols: List[str] = None, us_only: bool = True) -> List[Dict]:
        """
        Bulk retrieve earnings calendar (Premium+ plan required)
        Automatically splits periods longer than 90 days
        
        Args:
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            target_symbols: Target symbol list (all symbols if omitted)
            us_only: Limit to US market only (default: True)
        
        Returns:
            List of earnings data
        """
        # For specific symbols only, use individual symbol API (efficient)
        if target_symbols and len(target_symbols) <= 10:
            logger.info(f"Using individual symbol API for {len(target_symbols)} symbols")
            specific_earnings = self._get_earnings_for_specific_symbols(target_symbols, from_date, to_date)
            
            # Check symbols that couldn't be retrieved via individual API
            found_symbols = set(item['symbol'] for item in specific_earnings)
            missing_symbols = set(target_symbols) - found_symbols
            
            if missing_symbols:
                logger.info(f"Could not find earnings data for {missing_symbols} via individual API")
                # No fallback processing, return only retrieved data
                return specific_earnings
            else:
                # Return if data for all symbols was retrieved
                return specific_earnings
        
        logger.info(f"Fetching earnings calendar from {from_date} to {to_date}")
        
        # Convert dates to datetime objects
        start_dt = datetime.strptime(from_date, '%Y-%m-%d')
        end_dt = datetime.strptime(to_date, '%Y-%m-%d')
        
        # FMP Premium plan limitation check (no data before August 2020)
        fmp_limit_date = datetime(2020, 8, 1)
        if start_dt < fmp_limit_date:
            error_msg = (
                f"\n{'='*60}\n"
                f"FMP Data Source Limitation Error\n"
                f"{'='*60}\n"
                f"Start date: {from_date}\n"
                f"FMP Premium plan limitation: Only data from August 1, 2020 onwards is available\n\n"
                f"Solutions:\n"
                f"1. Change start date to 2020-08-01 or later\n"
                f"{'='*60}"
            )
            logger.error(error_msg)
            raise ValueError(f"FMP Premium plan does not support data before 2020-08-01. Requested start date: {from_date}")
        
        # Warning for cases where start date is after limit but partially in restricted range
        if start_dt < datetime(2020, 9, 1):
            logger.warning(f"Warning: FMP data coverage may be limited for dates close to August 2020. "
                         f"For comprehensive historical analysis, consider using alternative data source.")
        
        # Split if period exceeds 90 days
        max_days = 30  # Split every 30 days (safety margin)
        all_data = []
        
        current_start = start_dt
        while current_start < end_dt:
            current_end = min(current_start + timedelta(days=max_days), end_dt)
            
            params = {
                'from': current_start.strftime('%Y-%m-%d'),
                'to': current_end.strftime('%Y-%m-%d')
            }
            
            logger.info(f"Fetching chunk: {params['from']} to {params['to']}")
            chunk_data = self._make_request('earnings-calendar', params)
            
            if chunk_data is None:
                logger.warning(f"Failed to fetch data for {params['from']} to {params['to']}")
            elif len(chunk_data) == 0:
                logger.info(f"No data for {params['from']} to {params['to']}")
            else:
                all_data.extend(chunk_data)
                logger.info(f"Retrieved {len(chunk_data)} records for this chunk")
            
            # Move to next period
            current_start = current_end + timedelta(days=1)
            
            # Rate limiting is dynamically managed by _rate_limit_check()
            # Remove fixed waiting between chunks to ensure maximum speed
        
        if len(all_data) == 0:
            logger.warning("earnings-calendar endpoint returned no data, trying alternative method")
            return self._get_earnings_calendar_alternative(from_date, to_date, target_symbols, us_only)
        
        # Filter if only specific symbols are requested
        if target_symbols:
            filtered_data = []
            target_set = set(target_symbols)  # Convert to set for fast lookup
            for item in all_data:
                if item.get('symbol', '') in target_set:
                    filtered_data.append(item)
            
            logger.info(f"Filtered to {len(filtered_data)} records for target symbols: {target_symbols}")
            return filtered_data
        
        # Filter to US market only
        if us_only:
            us_data = []
            for item in all_data:
                symbol = item.get('symbol', '')
                # Identify US market symbols (usually determined by exchangeShortName)
                exchange = item.get('exchangeShortName', '').upper()
                if exchange in ['NASDAQ', 'NYSE', 'AMEX', 'NYSE AMERICAN']:
                    us_data.append(item)
                # If exchangeShortName info is missing, determine by typical US symbol patterns
                elif exchange == '' and symbol and not any(x in symbol for x in ['.TO', '.L', '.PA', '.AX', '.DE', '.HK']):
                    us_data.append(item)
            
            logger.info(f"Filtered to {len(us_data)} US market earnings records (from {len(all_data)} total)")
            return us_data
        
        logger.info(f"Retrieved total {len(all_data)} earnings records")
        return all_data
    
    def _get_earnings_calendar_alternative(self, from_date: str, to_date: str, 
                                           target_symbols: List[str] = None, us_only: bool = True) -> List[Dict]:
        """
        Alternative earnings calendar retrieval
        Use individual symbol earnings-surprises API
        
        Args:
            from_date: Start date
            to_date: End date
            target_symbols: Target symbol list (use default list if None)
        """
        logger.info("Using alternative earnings data collection method")
        
        # Premium plan support: Extended symbol list (major S&P 500 symbols)
        major_symbols = [
            # Technology
            'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'TSLA', 'NVDA', 'ORCL', 
            'CRM', 'ADBE', 'NFLX', 'INTC', 'AMD', 'AVGO', 'QCOM', 'TXN', 'CSCO',
            
            # Financial
            'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'AXP', 'USB', 'PNC',
            'TFC', 'COF', 'SCHW', 'CB', 'MMC', 'AON', 'SPGI', 'ICE',
            
            # Healthcare
            'JNJ', 'PFE', 'ABT', 'MRK', 'TMO', 'DHR', 'BMY', 'ABBV', 'LLY', 'UNH',
            'CVS', 'AMGN', 'GILD', 'MDLZ', 'BSX', 'SYK', 'ZTS', 'ISRG',
            
            # Consumer Discretionary
            'TSLA', 'AMZN', 'HD', 'MCD', 'NKE', 'SBUX', 'TGT', 'LOW', 'TJX', 'BKNG',
            'CMG', 'ORLY', 'AZO', 'RCL', 'MAR', 'HLT', 'MGM', 'WYNN',
            
            # Consumer Staples
            'KO', 'PEP', 'WMT', 'COST', 'PG', 'CL', 'KMB', 'GIS', 'K', 'SJM',
            'HSY', 'CPB', 'CAG', 'HRL', 'MKC', 'LW', 'CHD',
            
            # Industrial
            'BA', 'CAT', 'GE', 'MMM', 'HON', 'UPS', 'LMT', 'RTX', 'DE', 'FDX',
            'NOC', 'EMR', 'ETN', 'ITW', 'PH', 'CMI', 'OTIS', 'CARR',
            
            # Energy
            'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PXD', 'OXY', 'VLO', 'MPC', 'PSX',
            'KMI', 'WMB', 'OKE', 'BKR', 'HAL', 'DVN', 'FANG', 'MRO',
            
            # Materials
            'LIN', 'SHW', 'APD', 'ECL', 'FCX', 'NEM', 'DOW', 'DD', 'PPG', 'IFF',
            'ALB', 'CE', 'VMC', 'MLM', 'PKG', 'BALL', 'AMCR',
            
            # Real Estate
            'AMT', 'PLD', 'CCI', 'EQIX', 'PSA', 'WELL', 'DLR', 'O', 'SBAC', 'EQR',
            'AVB', 'VTR', 'ESS', 'MAA', 'EXR', 'UDR', 'CPT',
            
            # Utilities
            'NEE', 'SO', 'DUK', 'AEP', 'SRE', 'D', 'EXC', 'XEL', 'WEC', 'AWK',
            'PPL', 'ES', 'FE', 'ETR', 'AES', 'LNT', 'NI',
            
            # Communication Services
            'META', 'GOOGL', 'GOOG', 'NFLX', 'DIS', 'CMCSA', 'VZ', 'T', 'TMUS',
            'CHTR', 'ATVI', 'EA', 'TTWO', 'NWSA', 'NWS', 'FOXA', 'FOX',
            
            # Mid/Small Cap (includes MANH)
            'MANH', 'POOL', 'ODFL', 'WST', 'MPWR', 'ENPH', 'ALGN', 'MKTX', 'CDAY',
            'PAYC', 'FTNT', 'ANSS', 'CDNS', 'SNPS', 'KLAC', 'LRCX', 'AMAT', 'MCHP'
        ]
        
        earnings_data = []
        start_dt = datetime.strptime(from_date, '%Y-%m-%d')
        end_dt = datetime.strptime(to_date, '%Y-%m-%d')
        
        for symbol in major_symbols:
            try:
                # Earnings surprises API (available in Starter)
                symbol_data = self._make_request(f'earnings-surprises/{symbol}')
                
                if symbol_data and isinstance(symbol_data, list):
                    for earning in symbol_data:
                        try:
                            earning_date = datetime.strptime(earning.get('date', ''), '%Y-%m-%d')
                            if start_dt <= earning_date <= end_dt:
                                # Convert to earnings-calendar format
                                converted = {
                                    'symbol': symbol,
                                    'date': earning.get('date'),
                                    'epsActual': earning.get('actualEarningResult'),
                                    'epsEstimate': earning.get('estimatedEarning'),
                                    'time': None,  # Not available in Starter
                                    'revenueActual': None,  # Not available in earnings-surprises
                                    'revenueEstimate': None,  # Not available in earnings-surprises
                                    'fiscalDateEnding': earning.get('date'),
                                    'updatedFromDate': earning.get('date')
                                }
                                earnings_data.append(converted)
                                logger.debug(f"Added {symbol} earnings for {earning.get('date')}")
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Date parsing error for {symbol}: {e}")
                            continue
                            
            except Exception as e:
                logger.warning(f"Failed to get earnings for {symbol}: {e}")
                continue
        
        # Filter to US market only (for alternative method)
        if us_only:
            us_earnings = []
            for earning in earnings_data:
                symbol = earning.get('symbol', '')
                # Target only US market symbols (S&P symbols, etc.)
                if symbol and not any(x in symbol for x in ['.TO', '.L', '.PA', '.AX', '.DE', '.HK']):
                    us_earnings.append(earning)
            earnings_data = us_earnings
            logger.info(f"Filtered to {len(earnings_data)} US market earnings records using alternative method")
        
        # Sort by date
        earnings_data.sort(key=lambda x: x.get('date', ''))
        logger.info(f"Retrieved {len(earnings_data)} earnings records using alternative method")
        
        return earnings_data
    
    
    
    def get_company_profile(self, symbol: str) -> Optional[Dict]:
        """
        Retrieve company profile
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Company information
        """
        logger.debug(f"Fetching company profile for {symbol}")
        
        data = None
        for sym in self._symbol_variants(symbol):
            # v3 endpoint (recommended)
            original_base = self.base_url
            self.base_url = self.alt_base_url
            endpoint = f'profile/{sym}'
            data = self._make_request(endpoint)
            self.base_url = original_base

            # Try stable endpoint as fallback
            if not data:
                endpoint = f'profile/{sym}'
                data = self._make_request(endpoint)

            if data:
                logger.debug(f"Successfully fetched profile for {sym}")
                break
        
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
        
        logger.warning(f"Failed to fetch company profile for {symbol} using all available endpoints")
        return None
    
    def process_earnings_data(self, earnings_data: List[Dict]) -> pd.DataFrame:
        """
        Convert FMP earnings data to standard format
        
        Args:
            earnings_data: FMP earnings data
        
        Returns:
            Standardized DataFrame
        """
        if not earnings_data:
            return pd.DataFrame()
        
        processed_data = []
        
        for earning in earnings_data:
            try:
                # Processing based on FMP data structure
                processed_earning = {
                    'code': earning.get('symbol', '') + '.US',  # .US suffix for compatibility
                    'report_date': earning.get('date', ''),
                    'date': earning.get('date', ''),  # Actual earnings date
                    'before_after_market': self._parse_timing(earning.get('time', '')),
                    'currency': 'USD',  # FMP is mainly USD data
                    'actual': self._safe_float(earning.get('epsActual')),
                    'estimate': self._safe_float(earning.get('epsEstimated')),  # FMP uses 'epsEstimated'
                    'difference': 0,  # Calculate later
                    'percent': 0,     # Calculate later
                    'revenue_actual': self._safe_float(earning.get('revenueActual')),
                    'revenue_estimate': self._safe_float(earning.get('revenueEstimate')),
                    'updated_from_date': earning.get('updatedFromDate', ''),
                    'fiscal_date_ending': earning.get('fiscalDateEnding', ''),
                    'data_source': 'FMP'
                }
                
                # Calculate surprise rate
                if processed_earning['actual'] is not None and processed_earning['estimate'] is not None:
                    if processed_earning['estimate'] != 0:
                        processed_earning['difference'] = processed_earning['actual'] - processed_earning['estimate']
                        processed_earning['percent'] = (processed_earning['difference'] / abs(processed_earning['estimate'])) * 100
                
                processed_data.append(processed_earning)
                
            except Exception as e:
                logger.warning(f"Error processing earning data: {e}")
                continue
        
        df = pd.DataFrame(processed_data)
        
        if not df.empty:
            # Sort by date
            df = df.sort_values('report_date')
            logger.info(f"Processed {len(df)} earnings records")
        
        return df
    
    def _parse_timing(self, time_str: str) -> str:
        """
        Convert FMP time information to Before/AfterMarket format
        
        Args:
            time_str: FMP time string
        
        Returns:
            Before/AfterMarket
        """
        if not time_str:
            return None
        
        time_lower = time_str.lower()
        
        if any(keyword in time_lower for keyword in ['before', 'pre', 'bmo']):
            return 'BeforeMarket'
        elif any(keyword in time_lower for keyword in ['after', 'post', 'amc']):
            return 'AfterMarket'
        else:
            return None
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """
        Safe float conversion
        
        Args:
            value: Value to convert
        
        Returns:
            Float value or None
        """
        if value is None or value == '':
            return None
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def get_historical_price_data(self, symbol: str, from_date: str, to_date: str) -> Optional[List[Dict]]:
        """
        Retrieve historical price data from FMP

        For FMP, symbols containing `.` such as Berkshire Hathaway Class B stocks
        (e.g., ``BF.B`` or ``BRK.B``) use dash notation (``BF-B`` / ``BRK-B``).
        Therefore, when making API requests, alternative symbols are automatically
        tried to handle unexpected format responses or retrieval failures.

        Args:
            symbol: Stock symbol (e.g., "AAPL", "BRK.B")
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            Stock price data list (None if retrieval failed)
        """

        # Prepare symbol variations
        symbol_variants = [symbol]
        if '.' in symbol:
            # Alternative notation for FMP ( . -> - )
            symbol_variants.append(symbol.replace('.', '-'))

        params = {
            'from': from_date,
            'to': to_date
        }

        # Try each variation
        for sym in symbol_variants:
            logger.debug(f"Fetching historical price data for {sym} from {from_date} to {to_date}")

            # Generate endpoint combinations on the fly
            endpoints_to_try = [
                # Stable API endpoints
                ('stable', f'historical-price-full/{sym}'),
                ('stable', f'historical-chart/1day/{sym}'),
                ('stable', f'historical/{sym}'),
                # API v3 endpoints
                ('v3', f'historical-price-full/{sym}'),
                ('v3', f'historical-chart/1day/{sym}'),
                ('v3', f'historical-daily-prices/{sym}'),
            ]

            data = None

            for api_version, endpoint in endpoints_to_try:
                base_url = self.base_url if api_version == 'stable' else self.alt_base_url
                logger.debug(f"Trying {api_version} endpoint: {endpoint}")

                # Temporarily override base URL for this request
                original_base_url = self.base_url
                self.base_url = base_url

                # Execute at maximum performance
                data = self._make_request(endpoint, params, max_retries=3)

                # Restore original base URL
                self.base_url = original_base_url

                if data is not None:
                    logger.debug(f"Successfully fetched data using: {api_version}/{endpoint}")
                    break  # stop trying endpoints
                else:
                    logger.debug(f"Endpoint failed: {api_version}/{endpoint}")

            # If data is successfully retrieved, check format and return
            if data is not None:
                if isinstance(data, dict):
                    # Standard format with 'historical' field
                    if 'historical' in data:
                        return data['historical']
                    # Alternative format with direct data
                    elif 'results' in data:
                        return data['results']
                    # Chart format (single dictionary)
                    elif 'date' in data:
                        return [data]
                elif isinstance(data, list):
                    return data

                # If unexpected format, log and move to next variation
                logger.warning(f"Unexpected data format for {sym}: {type(data)}")

        # Failed with all variations and endpoints
        logger.warning(f"Failed to fetch historical price data for any variant of {symbol}")
        return None
    
    def get_sp500_constituents(self) -> List[str]:
        """
        Retrieve S&P 500 constituent symbols
        
        Returns:
            List of stock symbols
        """
        logger.debug("Fetching S&P 500 constituents")
        
        data = self._make_request('sp500_constituent')
        
        if data is None:
            logger.warning("Failed to fetch S&P 500 constituents")
            return []
        
        # Extract symbols from constituent data
        symbols = []
        if isinstance(data, list):
            symbols = [item.get('symbol', '') for item in data if item.get('symbol')]
        
        logger.info(f"Retrieved {len(symbols)} S&P 500 symbols")
        return symbols
    
    
    
    
    def get_mid_small_cap_symbols(self, min_market_cap: float = 1e9, max_market_cap: float = 50e9) -> List[str]:
        """
        Retrieve mid/small cap stocks based on market capitalization
        
        Args:
            min_market_cap: Minimum market cap (default: $1B)
            max_market_cap: Maximum market cap (default: $50B)
        
        Returns:
            List of mid/small cap stock symbols
        """
        logger.info(f"Fetching mid/small cap stocks (${min_market_cap/1e9:.1f}B - ${max_market_cap/1e9:.1f}B)")
        
        # Use FMP stock screener
        params = {
            'marketCapMoreThan': int(min_market_cap),
            'marketCapLowerThan': int(max_market_cap),
            'limit': 3000  # Set a large limit
        }
        
        # Try different endpoints
        endpoints_to_try = [
            'stock_screener',  # Correct endpoint name
            'screener',        # Alternative endpoint 
            'stock-screener'   # Original endpoint
        ]
        
        data = None
        for endpoint in endpoints_to_try:
            data = self._make_request(endpoint, params)
            if data is not None:
                logger.debug(f"Successfully used endpoint: {endpoint}")
                break
        
        if data is None:
            logger.warning("Stock screener API not available, using fallback method")
            # Fallback: Use market cap filtering in earnings data processing
            return self._get_mid_small_cap_fallback(min_market_cap, max_market_cap)
        
        # Extract only US market symbols
        us_symbols = []
        if isinstance(data, list):
            for stock in data:
                symbol = stock.get('symbol', '')
                exchange = stock.get('exchangeShortName', '')
                country = stock.get('country', '')
                
                # Select only US market symbols
                if (exchange in ['NASDAQ', 'NYSE', 'AMEX'] or country == 'US') and symbol:
                    # Exclude uncommon symbol types
                    if not any(x in symbol for x in ['.', '-', '^', '=']):
                        us_symbols.append(symbol)
        
        logger.info(f"Retrieved {len(us_symbols)} mid/small cap US stocks")
        return us_symbols[:2000]  # Limit to practical number
    
    def _get_mid_small_cap_fallback(self, min_market_cap: float, max_market_cap: float) -> List[str]:
        """
        Alternative method when stock screener is not available
        Use popular mid/small cap stock list
        """
        logger.info("Using curated mid/small cap stock list as fallback")
        
        # Popular mid/small cap stock list (matching market cap range)
        mid_small_cap_stocks = [
            # Regional Banks (typically $2-20B market cap)
            'OZK', 'ZION', 'PNFP', 'FHN', 'SNV', 'FULT', 'CBSH', 'ONB', 'IBKR',
            'BKU', 'OFG', 'FFBC', 'COLB', 'BANC', 'FFIN', 'FBP', 'CUBI', 'ASB',
            'HFWA', 'PPBI', 'SSB', 'TCBI', 'NBHC', 'BANR', 'CVBF', 'UMBF',
            'LKFN', 'NWBI', 'HOPE', 'SBCF', 'WSFS', 'SFBS', 'HAFC', 'FBNC',
            'CFFN', 'ABCB', 'BHLB', 'STBA',
            
            # Mid-cap industrials and tech
            'CALM', 'AIR', 'AZZ', 'JEF', 'ACI', 'MSM', 'SMPL', 'GBX', 'UNF',
            'NEOG', 'WDFC', 'CNXC', 'IIIN', 'WBS', 'HWC', 'PRGS', 'AGYS',
            'AA', 'ALK', 'SLG', 'PLXS', 'SFNC', 'KNX', 'MANH', 'QRVO', 'WRLD',
            'ADNT', 'TRMK', 'NXT', 'AIT', 'VFC', 'SF', 'EXTR', 'WHR', 'GPI',
            'CCS', 'CALX', 'CPF', 'CACI', 'GATX', 'ORI', 'HZO', 'MRTN', 'SANM',
            'ELS', 'HLI', 'RNR', 'RNST', 'CVLT', 'FLEX', 'NFG', 'LBRT', 'VIRT',
            'DLB', 'BHE', 'OSK', 'VIAV', 'ATGE', 'BC', 'SXI', 'OLN', 'PMT',
            'SXC', 'DT', 'CRS', 'ABG', 'NTCT', 'CFR', 'CVCO', 'STEL', 'HTH',
            'SKYW', 'CSWI', 'FHI', 'BOOT', 'BFH', 'ALGM', 'TMP', 'ALV', 'VSTS',
            'RBC', 'JHG', 'ARCB', 'PIPR', 'CR', 'NLY', 'EAT'
        ]
        
        logger.info(f"Using {len(mid_small_cap_stocks)} curated mid/small cap symbols")
        return mid_small_cap_stocks
    
    def get_api_usage_stats(self) -> Dict:
        """
        Retrieve API usage statistics
        
        Returns:
            Usage statistics information
        """
        now = datetime.now()
        recent_calls_minute = [
            ts for ts in self.call_timestamps 
            if (now - ts).total_seconds() < 60
        ]
        recent_calls_second = [
            ts for ts in self.call_timestamps 
            if (now - ts).total_seconds() < 1
        ]
        
        return {
            'calls_last_minute': len(recent_calls_minute),
            'calls_last_second': len(recent_calls_second),
            'calls_per_minute_limit': self.calls_per_minute,
            'calls_per_second_limit': self.calls_per_second,
            'remaining_calls_minute': max(0, self.calls_per_minute - len(recent_calls_minute)),
            'remaining_calls_second': max(0, self.calls_per_second - len(recent_calls_second)),
            'api_key_set': bool(self.api_key),
            'base_url': self.base_url,
            'min_request_interval': self.min_request_interval
        }


# ------------------------------------------------------------------
# Graceful fallback when no API key is available
# ------------------------------------------------------------------


class NullFMPDataFetcher:
    """Stub fetcher used when no FMP API key is configured.

    All methods mirror :class:`FMPDataFetcher` but return empty data / None so that
    the rest of the application can continue to run while skipping FMP-dependent
    analyses.
    """

    def __getattr__(self, item):
        # Any method returns a stub that logs and returns None/[]
        def _stub(*args, **kwargs):
            logger.debug(f"NullFMPDataFetcher: called {item} – returning empty result")
            return [] if item.startswith("get_") else None

        return _stub


