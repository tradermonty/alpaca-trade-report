"""
API呼び出しを共通化するクライアントクラス
AlpacaとEODHDのAPI呼び出しを統一し、エラーハンドリングとリトライロジックを提供
"""

import os
import time
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import alpaca_trade_api as tradeapi
from alpaca_trade_api.common import URL
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from dotenv import load_dotenv
import logging

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class AlpacaClient:
    """Alpaca Trading APIの共通クライアント"""
    
    def __init__(self, account_type: str = 'live'):
        """
        Args:
            account_type: 'live', 'paper', 'paper_short'のいずれか
        """
        self.account_type = account_type
        self._api = None
        self._setup_api()
    
    def _setup_api(self):
        """API接続の設定"""
        if self.account_type == 'live':
            base_url = URL('https://api.alpaca.markets')
            api_key = os.getenv('ALPACA_API_KEY_LIVE')
            secret_key = os.getenv('ALPACA_SECRET_KEY_LIVE')
        elif self.account_type == 'paper_short':
            base_url = URL('https://paper-api.alpaca.markets')
            api_key = os.getenv('ALPACA_API_KEY_PAPER_SHORT')
            secret_key = os.getenv('ALPACA_SECRET_KEY_PAPER_SHORT')
        else:  # paper
            base_url = URL('https://paper-api.alpaca.markets')
            api_key = os.getenv('ALPACA_API_KEY_PAPER')
            secret_key = os.getenv('ALPACA_SECRET_KEY_PAPER')
        
        if not api_key or not secret_key:
            raise ValueError(f"API keys not found for account type: {self.account_type}")
        
        self._api = tradeapi.REST(api_key, secret_key, base_url, api_version='v2')
        logger.info(f"Alpaca API initialized for {self.account_type} account")
    
    @property
    def api(self):
        """Alpaca APIインスタンスを取得"""
        return self._api
    
    def get_account(self):
        """アカウント情報を取得"""
        try:
            return self._api.get_account()
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            raise
    
    def get_positions(self):
        """ポジション情報を取得"""
        try:
            return self._api.list_positions()
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            raise
    
    def get_orders(self, status: str = 'all', limit: int = 500):
        """注文履歴を取得"""
        try:
            return self._api.list_orders(status=status, limit=limit)
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            raise
    
    def get_portfolio_history(self, period: str = '1M', timeframe: str = '1D'):
        """ポートフォリオ履歴を取得"""
        try:
            return self._api.get_portfolio_history(period=period, timeframe=timeframe)
        except Exception as e:
            logger.error(f"Error getting portfolio history: {e}")
            raise
    
    def get_calendar(self, start: str = None, end: str = None):
        """マーケットカレンダーを取得"""
        try:
            return self._api.get_calendar(start=start, end=end)
        except Exception as e:
            logger.error(f"Error getting calendar: {e}")
            raise
    
    def get_bars(self, symbol: str, timeframe: TimeFrame, start: str = None, end: str = None, limit: int = None):
        """バーデータを取得"""
        try:
            return self._api.get_bars(symbol, timeframe, start=start, end=end, limit=limit)
        except Exception as e:
            logger.error(f"Error getting bars for {symbol}: {e}")
            raise
    
    def submit_order(self, symbol: str, qty: int, side: str, type: str = 'market', 
                    time_in_force: str = 'day', **kwargs):
        """注文を送信"""
        try:
            return self._api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=type,
                time_in_force=time_in_force,
                **kwargs
            )
        except Exception as e:
            logger.error(f"Error submitting order for {symbol}: {e}")
            raise
    
    def cancel_order(self, order_id: str):
        """注文をキャンセル"""
        try:
            return self._api.cancel_order(order_id)
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            raise
    
    def close_position(self, symbol: str, qty: str = None, percentage: str = None):
        """ポジションをクローズ"""
        try:
            return self._api.close_position(symbol, qty=qty, percentage=percentage)
        except Exception as e:
            logger.error(f"Error closing position for {symbol}: {e}")
            raise


class EODHDClient:
    """EODHD APIの共通クライアント"""
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Args:
            max_retries: 最大リトライ回数
            retry_delay: リトライ間隔（秒）
        """
        self.api_key = os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY not found in environment variables")
        
        self.base_url = 'https://eodhd.com/api'
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        logger.info("EODHD API client initialized")
    
    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        APIリクエストを実行（リトライロジック付き）
        
        Args:
            endpoint: APIエンドポイント
            params: リクエストパラメータ
            
        Returns:
            APIレスポンスのJSONデータ
        """
        if params is None:
            params = {}
        
        params['api_token'] = self.api_key
        params['fmt'] = 'json'
        
        url = f"{self.base_url}/{endpoint}"
        
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (2 ** attempt)
                        logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise requests.exceptions.RequestException(f"Rate limit exceeded after {self.max_retries} retries")
                else:
                    response.raise_for_status()
                    
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Request failed (attempt {attempt + 1}): {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {self.max_retries + 1} attempts: {e}")
                    raise
        
        raise requests.exceptions.RequestException(f"Request failed after {self.max_retries + 1} attempts")
    
    def get_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """
        基本データを取得
        
        Args:
            symbol: 銘柄シンボル
            
        Returns:
            基本データ
        """
        try:
            endpoint = f"fundamentals/{symbol}"
            return self._make_request(endpoint)
        except Exception as e:
            logger.error(f"Error getting fundamentals for {symbol}: {e}")
            raise
    
    def get_market_cap_data(self, index_symbol: str) -> Dict[str, Any]:
        """
        市場指数の時価総額データを取得
        
        Args:
            index_symbol: 指数シンボル (例: 'MID.INDX', 'SML.INDX')
            
        Returns:
            時価総額データ
        """
        try:
            endpoint = f"fundamentals/{index_symbol}"
            return self._make_request(endpoint)
        except Exception as e:
            logger.error(f"Error getting market cap data for {index_symbol}: {e}")
            raise
    
    def get_earnings_data(self, symbol: str, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        """
        決算データを取得
        
        Args:
            symbol: 銘柄シンボル
            from_date: 開始日 (YYYY-MM-DD)
            to_date: 終了日 (YYYY-MM-DD)
            
        Returns:
            決算データのリスト
        """
        try:
            params = {}
            if from_date:
                params['from'] = from_date
            if to_date:
                params['to'] = to_date
            
            endpoint = f"calendar/earnings"
            params['symbols'] = symbol
            
            response = self._make_request(endpoint, params)
            return response if isinstance(response, list) else [response]
        except Exception as e:
            logger.error(f"Error getting earnings data for {symbol}: {e}")
            raise
    
    def get_historical_data(self, symbol: str, from_date: str, to_date: str, period: str = 'd') -> List[Dict[str, Any]]:
        """
        履歴データを取得
        
        Args:
            symbol: 銘柄シンボル
            from_date: 開始日 (YYYY-MM-DD)
            to_date: 終了日 (YYYY-MM-DD)  
            period: 期間 ('d': 日次, 'w': 週次, 'm': 月次)
            
        Returns:
            履歴データのリスト
        """
        try:
            params = {
                'from': from_date,
                'to': to_date,
                'period': period
            }
            
            endpoint = f"eod/{symbol}"
            response = self._make_request(endpoint, params)
            return response if isinstance(response, list) else [response]
        except Exception as e:
            logger.error(f"Error getting historical data for {symbol}: {e}")
            raise


# シングルトンインスタンス（オプション）
_alpaca_clients = {}
_eodhd_client = None


def get_alpaca_client(account_type: str = 'live') -> AlpacaClient:
    """Alpacaクライアントのシングルトンインスタンスを取得"""
    global _alpaca_clients
    if account_type not in _alpaca_clients:
        _alpaca_clients[account_type] = AlpacaClient(account_type)
    return _alpaca_clients[account_type]


def get_eodhd_client() -> EODHDClient:
    """EODHDクライアントのシングルトンインスタンスを取得"""
    global _eodhd_client
    if _eodhd_client is None:
        _eodhd_client = EODHDClient()
    return _eodhd_client