"""
API呼び出しを共通化するクライアントクラス
AlpacaとEODHDのAPI呼び出しを統一し、エラーハンドリングとリトライロジックを提供
"""

import os
import time
import requests
import pandas as pd
import io
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import alpaca_trade_api as tradeapi
from alpaca_trade_api.common import URL
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from dotenv import load_dotenv
from logging_config import get_logger
from config import retry_config, system_config
from circuit_breaker import get_circuit_breaker, CircuitBreakerOpenException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = get_logger(__name__)

load_dotenv()


class AlpacaClient:
    """Alpaca Trading APIの共通クライアント"""
    
    def __init__(self, account_type: str = 'live', max_retries: int = retry_config.ALPACA_MAX_RETRIES):
        """
        Args:
            account_type: 'live', 'paper', 'paper_short'のいずれか
            max_retries: 最大リトライ回数
        """
        self.account_type = account_type
        self.max_retries = max_retries
        self.retry_delay = retry_config.ALPACA_RETRY_DELAY
        self.circuit_breaker = get_circuit_breaker('alpaca')
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
    
    def _execute_with_retry(self, operation, operation_name: str, *args, **kwargs):
        """
        指数バックオフ付きでAPIオペレーションを実行
        
        Args:
            operation: 実行する操作（関数）
            operation_name: 操作名（ログ用）
            *args, **kwargs: 操作に渡す引数
            
        Returns:
            操作の結果
        """
        try:
            # サーキットブレーカー経由で実行
            return self.circuit_breaker.call(self._execute_operation_with_retry, operation, operation_name, *args, **kwargs)
        except CircuitBreakerOpenException as e:
            logger.error(f"Alpaca API circuit breaker is open for {operation_name}: {e}")
            raise
    
    def _execute_operation_with_retry(self, operation, operation_name: str, *args, **kwargs):
        """リトライロジック付きで操作を実行"""
        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
                
            except tradeapi.rest.APIError as e:
                # レート制限またはサーバーエラーの場合のみリトライ
                if hasattr(e, 'status_code') and e.status_code in [429, 500, 502, 503, 504]:
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (system_config.EXPONENTIAL_BACKOFF_BASE ** attempt)
                        logger.warning(f"Alpaca API error ({e.status_code}) for {operation_name}, waiting {wait_time}s before retry {attempt + 1}")
                        time.sleep(wait_time)
                        continue
                logger.error(f"Alpaca API error for {operation_name}: {e}", exc_info=True)
                raise
                
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (system_config.EXPONENTIAL_BACKOFF_BASE ** attempt)
                    logger.warning(f"Network error for {operation_name} (attempt {attempt + 1}): {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Network error for {operation_name} after {self.max_retries + 1} attempts: {e}", exc_info=True)
                raise
                
            except Exception as e:
                logger.error(f"Unexpected error for {operation_name}: {e}", exc_info=True)
                raise
        
        raise requests.exceptions.RequestException(f"{operation_name} failed after {self.max_retries + 1} attempts")
    
    def get_account(self):
        """アカウント情報を取得"""
        return self._execute_with_retry(self._api.get_account, 'get_account')
    
    def get_positions(self):
        """ポジション情報を取得"""
        return self._execute_with_retry(self._api.list_positions, 'get_positions')
    
    def get_orders(self, status: str = 'all', limit: int = 500):
        """注文履歴を取得"""
        return self._execute_with_retry(self._api.list_orders, 'get_orders', status=status, limit=limit)
    
    def get_portfolio_history(self, period: str = '1M', timeframe: str = '1D'):
        """ポートフォリオ履歴を取得"""
        return self._execute_with_retry(self._api.get_portfolio_history, 'get_portfolio_history', period=period, timeframe=timeframe)
    
    def get_calendar(self, start: str = None, end: str = None):
        """マーケットカレンダーを取得"""
        return self._execute_with_retry(self._api.get_calendar, 'get_calendar', start=start, end=end)
    
    def get_bars(self, symbol: str, timeframe: TimeFrame, start: str = None, end: str = None, limit: int = None):
        """バーデータを取得"""
        return self._execute_with_retry(self._api.get_bars, f'get_bars for {symbol}', symbol, timeframe, start=start, end=end, limit=limit)
    
    def submit_order(self, symbol: str, qty: int, side: str, type: str = 'market', 
                    time_in_force: str = 'day', **kwargs):
        """注文を送信"""
        def _submit_order_operation():
            return self._api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=type,
                time_in_force=time_in_force,
                **kwargs
            )
        return self._execute_with_retry(_submit_order_operation, f'submit_order for {symbol}')
    
    def cancel_order(self, order_id: str):
        """注文をキャンセル"""
        return self._execute_with_retry(self._api.cancel_order, f'cancel_order {order_id}', order_id)
    
    def close_position(self, symbol: str, qty: str = None, percentage: str = None):
        """ポジションをクローズ"""
        return self._execute_with_retry(self._api.close_position, f'close_position for {symbol}', symbol, qty=qty, percentage=percentage)


class EODHDClient:
    """EODHD APIの共通クライアント（コネクションプーリング付き）"""
    
    def __init__(self, max_retries: int = retry_config.EODHD_MAX_RETRIES, retry_delay: float = retry_config.EODHD_RETRY_DELAY):
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
        self.circuit_breaker = get_circuit_breaker('eodhd')
        
        # セッションプールの設定
        self.session = self._create_session_with_pool()
        
        logger.info("EODHD API client initialized with connection pooling")
    
    def _create_session_with_pool(self) -> requests.Session:
        """
        コネクションプーリング付きのセッションを作成
        
        Returns:
            requests.Session: 設定済みセッション
        """
        session = requests.Session()
        
        # リトライ戦略の設定
        retry_strategy = Retry(
            total=self.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1,
            raise_on_status=False
        )
        
        # HTTPアダプターにコネクションプールを設定
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=system_config.CONNECTION_POOL_SIZE,  # プールサイズ
            pool_maxsize=system_config.CONNECTION_POOL_MAXSIZE,   # 最大コネクション数
            pool_block=True  # プールが満杯の時にブロック
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # タイムアウト設定
        session.timeout = retry_config.HTTP_TIMEOUT
        
        return session
    
    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        APIリクエストを実行（リトライロジック付き）
        
        Args:
            endpoint: APIエンドポイント
            params: リクエストパラメータ
            
        Returns:
            APIレスポンスのJSONデータ
        """
        try:
            return self.circuit_breaker.call(self._make_request_with_retry, endpoint, params)
        except CircuitBreakerOpenException as e:
            logger.error(f"EODHD API circuit breaker is open for {endpoint}: {e}")
            raise
    
    def _make_request_with_retry(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """セッションプールを使用してリトライロジック付きでリクエストを実行"""
        if params is None:
            params = {}
        
        params['api_token'] = self.api_key
        params['fmt'] = 'json'
        
        url = f"{self.base_url}/{endpoint}"
        
        for attempt in range(self.max_retries + 1):
            try:
                # セッションプールを使用してリクエスト実行
                response = self.session.get(url, params=params, timeout=retry_config.HTTP_TIMEOUT)
                
                if response.status_code == system_config.SUCCESS_STATUS_CODE:
                    return response.json()
                elif response.status_code == system_config.RATE_LIMIT_STATUS_CODE:  # Rate limit
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (system_config.EXPONENTIAL_BACKOFF_BASE ** attempt)
                        logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise requests.exceptions.RequestException(f"Rate limit exceeded after {self.max_retries} retries")
                else:
                    response.raise_for_status()
                    
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (system_config.EXPONENTIAL_BACKOFF_BASE ** attempt)
                    logger.warning(f"Request failed (attempt {attempt + 1}): {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {self.max_retries + 1} attempts: {e}")
                    raise
        
        raise requests.exceptions.RequestException(f"Request failed after {self.max_retries + 1} attempts")
    
    def close(self):
        """セッションとコネクションプールをクリーンアップ"""
        if hasattr(self, 'session'):
            self.session.close()
            logger.info("EODHD client session closed")
    
    def __enter__(self):
        """コンテキストマネージャーのエントリー"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャーの終了処理"""
        self.close()
    
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
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting fundamentals for {symbol}: {e}", exc_info=True)
            raise
        except ValueError as e:
            logger.error(f"Invalid response format for {symbol}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting fundamentals for {symbol}: {e}", exc_info=True)
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


class FinvizClient:
    """Finviz Elite APIの共通クライアント（コネクションプーリング付き）"""
    
    def __init__(self, max_retries: int = retry_config.FINVIZ_MAX_RETRIES, retry_delay: float = retry_config.FINVIZ_RETRY_DELAY):
        """
        Args:
            max_retries: 最大リトライ回数
            retry_delay: 初回リトライ待機時間（秒）
        """
        self.api_key = os.getenv('FINVIZ_API_KEY')
        if not self.api_key:
            raise ValueError("FINVIZ_API_KEY not found in environment variables")
        
        self.base_url = 'https://elite.finviz.com'
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.circuit_breaker = get_circuit_breaker('finviz')
        
        # セッションプールの設定
        self.session = self._create_session_with_pool()
        
        logger.info("Finviz API client initialized with connection pooling")
    
    def _create_session_with_pool(self) -> requests.Session:
        """
        コネクションプーリング付きのセッションを作成
        
        Returns:
            requests.Session: 設定済みセッション
        """
        session = requests.Session()
        
        # HTTPアダプターにコネクションプールを設定
        adapter = HTTPAdapter(
            pool_connections=system_config.CONNECTION_POOL_SIZE,  # プールサイズ
            pool_maxsize=system_config.CONNECTION_POOL_MAXSIZE,   # 最大コネクション数
            pool_block=True  # プールが満杯の時にブロック
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # タイムアウト設定
        session.timeout = retry_config.HTTP_TIMEOUT
        
        return session
    
    def _make_request(self, url: str) -> pd.DataFrame:
        """
        Finviz APIリクエストを実行（リトライロジック付き）
        
        Args:
            url: リクエストURL
            
        Returns:
            DataFrameとしてのレスポンスデータ
        """
        try:
            return self.circuit_breaker.call(self._make_request_with_retry, url)
        except CircuitBreakerOpenException as e:
            logger.error(f"Finviz API circuit breaker is open for request: {e}")
            raise
    
    def _make_request_with_retry(self, url: str) -> pd.DataFrame:
        """セッションプールを使用してリトライロジック付きでリクエストを実行"""
        for attempt in range(self.max_retries):
            try:
                # セッションプールを使用してリクエスト実行
                response = self.session.get(url, timeout=retry_config.HTTP_TIMEOUT)
                
                if response.status_code == system_config.SUCCESS_STATUS_CODE:
                    df = pd.read_csv(io.BytesIO(response.content), sep=",")
                    return df
                elif response.status_code == system_config.RATE_LIMIT_STATUS_CODE:  # Rate limit
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (system_config.EXPONENTIAL_BACKOFF_BASE ** attempt)
                        logger.warning(f"Finviz rate limit hit, waiting {wait_time}s before retry {attempt + 1}")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise requests.exceptions.RequestException(f"Rate limit exceeded after {self.max_retries} retries")
                else:
                    logger.error(f"Error fetching data from Finviz. Status code: {response.status_code}")
                    response.raise_for_status()
                    
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Finviz request failed (attempt {attempt + 1}): {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Finviz request failed after {self.max_retries} attempts: {e}")
                    raise
        
        raise requests.exceptions.RequestException(f"Finviz request failed after {self.max_retries} attempts")
    
    def close(self):
        """セッションとコネクションプールをクリーンアップ"""
        if hasattr(self, 'session'):
            self.session.close()
            logger.info("Finviz client session closed")
    
    def __enter__(self):
        """コンテキストマネージャーのエントリー"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャーの終了処理"""
        self.close()
    
    def get_stock_count(self, url: str) -> int:
        """
        指定されたスクリーナーURLから銘柄数を取得
        
        Args:
            url: FinvizスクリーナーのエクスポートURL
            
        Returns:
            銘柄数
        """
        try:
            df = self._make_request(url)
            return len(df)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting stock count from Finviz: {e}", exc_info=True)
            return 0
        except pd.errors.ParserError as e:
            logger.error(f"CSV parsing error from Finviz: {e}", exc_info=True)
            return 0
        except Exception as e:
            logger.error(f"Unexpected error getting stock count from Finviz: {e}", exc_info=True)
            return 0
    
    def get_screener_data(self, url: str) -> pd.DataFrame:
        """
        指定されたスクリーナーURLからデータを取得
        
        Args:
            url: FinvizスクリーナーのエクスポートURL
            
        Returns:
            スクリーナーデータのDataFrame
        """
        try:
            return self._make_request(url)
        except Exception as e:
            logger.error(f"Error getting screener data from Finviz: {e}")
            return pd.DataFrame()
    
    def build_screener_url(self, filters: Dict[str, str], columns: str = None, 
                          order: str = None, auth_key: str = None) -> str:
        """
        FinvizスクリーナーのエクスポートURLを構築
        
        Args:
            filters: フィルター条件の辞書
            columns: 表示列の指定
            order: ソート順
            auth_key: APIキー（指定しない場合は環境変数から取得）
            
        Returns:
            構築されたURL
        """
        if auth_key is None:
            auth_key = self.api_key
        
        # フィルターを文字列に変換
        filter_str = ','.join([f"{k}_{v}" if v else k for k, v in filters.items()])
        
        url = f"{self.base_url}/export.ashx?v=151&f={filter_str}&ft=4"
        
        if order:
            url += f"&o={order}"
        if columns:
            url += f"&c={columns}"
        
        url += f"&auth={auth_key}"
        
        return url
    
    def get_uptrend_screener_url(self, sector: str = None) -> str:
        """
        上昇トレンドスクリーナーのURLを取得
        
        Args:
            sector: セクターフィルター（例: "sec_technology"）
            
        Returns:
            上昇トレンドスクリーナーのURL
        """
        filters = {
            "cap": "microover",
            "sh_avgvol": "o100", 
            "sh_price": "o10",
            "ta_highlow52w": "a30h",
            "ta_perf2": "4wup",
            "ta_sma20": "pa",
            "ta_sma200": "pa",
            "ta_sma50": "sa200"
        }
        
        if sector:
            filters[sector] = ""
        
        columns = "0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77," \
                 "17,18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,36,37,38,39,40,41," \
                 "90,91,92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68," \
                 "70,80,83,76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109," \
                 "110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,105"
        
        return self.build_screener_url(filters, columns, order="-epsyoy1")
    
    def get_total_screener_url(self, sector: str = None) -> str:
        """
        全体スクリーナーのURLを取得
        
        Args:
            sector: セクターフィルター（例: "sec_technology"）
            
        Returns:
            全体スクリーナーのURL
        """
        filters = {
            "cap": "microover",
            "sh_avgvol": "o100",
            "sh_price": "o10"
        }
        
        if sector:
            filters[sector] = ""
        
        columns = "0,1,2,79,3,4,5,6,7,8,9,10,11,12,13,73,74,75,14,15,16,77,17," \
                 "18,19,20,21,23,22,82,78,127,128,24,25,85,26,27,28,29,30,31,84,32,33,34,35,36,37,38,39,40,41,90,91," \
                 "92,93,94,95,96,97,98,99,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,125,126,59,68,70,80,83," \
                 "76,60,61,62,63,64,67,89,69,81,86,87,88,65,66,71,72,103,100,101,104,102,106,107,108,109,110,111," \
                 "112,113,114,115,116,117,118,119,120,121,122,123,124,105"
        
        return self.build_screener_url(filters, columns, order="-epsyoy1")
    
    def get_news_data(self, symbols: List[str] = None, date_from: str = None, 
                     date_to: str = None) -> pd.DataFrame:
        """
        ニュースデータを取得
        
        Args:
            symbols: 銘柄シンボルのリスト
            date_from: 開始日 (YYYY-MM-DD)
            date_to: 終了日 (YYYY-MM-DD)
            
        Returns:
            ニュースデータのDataFrame
        """
        try:
            url = f"{self.base_url}/news_export.ashx?"
            
            params = []
            if symbols:
                params.append(f"t={','.join(symbols)}")
            if date_from:
                params.append(f"dtf={date_from}")
            if date_to:
                params.append(f"dtt={date_to}")
            
            params.append(f"auth={self.api_key}")
            
            full_url = url + "&".join(params)
            return self._make_request(full_url)
        except Exception as e:
            logger.error(f"Error getting news data from Finviz: {e}")
            return pd.DataFrame()


# シングルトンインスタンス（オプション）
_alpaca_clients = {}
_eodhd_client = None
_finviz_client = None


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


def get_finviz_client() -> FinvizClient:
    """Finvizクライアントのシングルトンインスタンスを取得"""
    global _finviz_client
    if _finviz_client is None:
        _finviz_client = FinvizClient()
    return _finviz_client