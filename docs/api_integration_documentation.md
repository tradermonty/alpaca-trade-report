# API統合システム詳細ドキュメント

## 概要

本システムは複数の外部APIを統合して、リアルタイム市場データ、取引執行、基本的分析、外部制御機能を提供します。各APIクライアントは独立したエラーハンドリング、リトライロジック、フェイルオーバー機能を持ち、システム全体の可用性を保証します。

---

## 1. Alpaca Trading API統合

### 基本構成
```python
class AlpacaClient:
    """Alpaca Trading APIの統合クライアント"""
    
    def __init__(self, account_type='live'):
        self.account_type = account_type
        self.api = self._setup_api()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=retry_config.ALPACA_MAX_RETRIES,
            timeout=60
        )
        
    def _setup_api(self):
        """API認証とクライアント初期化"""
        if self.account_type == 'live':
            api_key = os.getenv('ALPACA_API_KEY_LIVE')
            secret_key = os.getenv('ALPACA_SECRET_KEY_LIVE')
            base_url = 'https://api.alpaca.markets'
        elif self.account_type == 'paper':
            api_key = os.getenv('ALPACA_API_KEY_PAPER')
            secret_key = os.getenv('ALPACA_SECRET_KEY_PAPER')
            base_url = 'https://paper-api.alpaca.markets'
        else:  # paper_short
            api_key = os.getenv('ALPACA_API_KEY_PAPER_SHORT')
            secret_key = os.getenv('ALPACA_SECRET_KEY_PAPER_SHORT')
            base_url = 'https://paper-api.alpaca.markets'
            
        return tradeapi.REST(api_key, secret_key, base_url, api_version='v2')
```

### 取引執行機能

#### 注文送信
```python
def submit_order(self, **order_params):
    """
    注文送信（リトライ・サーキットブレーカー付き）
    
    Args:
        **order_params: 注文パラメータ
            - symbol: 銘柄シンボル
            - qty: 数量
            - side: 'buy' または 'sell'
            - type: 'market', 'limit', 'stop' など
            - time_in_force: 'day', 'gtc' など
            - limit_price: 指値価格（type='limit'の場合）
            - stop_price: ストップ価格（type='stop'の場合）
    
    Returns:
        Order: 注文オブジェクト
    """
    @self.circuit_breaker
    def _submit_with_retry():
        for attempt in range(retry_config.ALPACA_MAX_RETRIES):
            try:
                # パラメータ検証
                self._validate_order_params(order_params)
                
                # 注文送信
                order = self.api.submit_order(**order_params)
                
                logger.info(f"注文送信成功: {order.symbol} {order.side} {order.qty}株 "
                           f"@ {order.limit_price or 'market'}")
                return order
                
            except tradeapi.rest.APIError as e:
                if self._is_retryable_error(e):
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(f"注文送信リトライ {attempt+1}/{retry_config.ALPACA_MAX_RETRIES}: "
                                 f"{e} (待機{wait_time}秒)")
                    time.sleep(wait_time)
                else:
                    logger.error(f"注文送信エラー（リトライ不可）: {e}")
                    raise
            except Exception as e:
                logger.error(f"注文送信予期しないエラー: {e}")
                raise
        
        raise TradingError("注文送信: 最大リトライ回数を超過")
    
    return _submit_with_retry()

def _validate_order_params(self, params):
    """注文パラメータの妥当性検証"""
    required_fields = ['symbol', 'qty', 'side', 'type', 'time_in_force']
    
    for field in required_fields:
        if field not in params:
            raise ValueError(f"必須パラメータ不足: {field}")
    
    # 数量検証
    try:
        qty = int(params['qty'])
        if qty <= 0:
            raise ValueError("数量は正の整数である必要があります")
    except (ValueError, TypeError):
        raise ValueError("数量は有効な整数である必要があります")
    
    # サイド検証
    if params['side'] not in ['buy', 'sell']:
        raise ValueError("sideは'buy'または'sell'である必要があります")
    
    # 指値注文の価格検証
    if params['type'] == 'limit' and 'limit_price' not in params:
        raise ValueError("指値注文には限界価格が必要です")
```

#### ブラケット注文
```python
def submit_bracket_order(self, symbol, qty, side, entry_price, stop_price, profit_price):
    """
    ブラケット注文（親注文 + 利確 + 損切り）
    
    Args:
        symbol: 銘柄シンボル
        qty: 数量
        side: 'buy' または 'sell'
        entry_price: エントリー価格
        stop_price: ストップロス価格
        profit_price: 利確価格
    
    Returns:
        dict: {'parent': 親注文, 'stop': 損切り注文, 'profit': 利確注文}
    """
    try:
        # 親注文送信
        parent_order = self.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type='limit',
            time_in_force='day',
            limit_price=entry_price
        )
        
        # エグジット方向決定
        exit_side = 'sell' if side == 'buy' else 'buy'
        
        # ストップロス注文（条件付き）
        stop_type = 'stop' if side == 'buy' else 'stop'
        stop_order = self.submit_order(
            symbol=symbol,
            qty=qty,
            side=exit_side,
            type=stop_type,
            time_in_force='day',
            stop_price=stop_price,
            parent_order_id=parent_order.id
        )
        
        # 利確注文（条件付き）
        profit_order = self.submit_order(
            symbol=symbol,
            qty=qty,
            side=exit_side,
            type='limit',
            time_in_force='day',
            limit_price=profit_price,
            parent_order_id=parent_order.id
        )
        
        logger.info(f"ブラケット注文完了: {symbol} エントリー@{entry_price} "
                   f"ストップ@{stop_price} 利確@{profit_price}")
        
        return {
            'parent': parent_order,
            'stop': stop_order,
            'profit': profit_order
        }
        
    except Exception as e:
        logger.error(f"ブラケット注文エラー {symbol}: {e}")
        # 部分的に作成された注文のクリーンアップ
        self._cleanup_partial_bracket_order(symbol)
        raise
```

### データ取得機能

#### 市場データ取得
```python
def get_bars(self, symbol, timeframe, start=None, end=None, limit=None, page_token=None):
    """
    価格バーデータ取得
    
    Args:
        symbol: 銘柄シンボル
        timeframe: 時間軸（TimeFrame.Minute, TimeFrame.Day等）
        start: 開始日時
        end: 終了日時
        limit: 取得件数制限
        page_token: ページネーショントークン
    
    Returns:
        list: バーデータリスト
    """
    @self.circuit_breaker
    def _get_bars_with_retry():
        for attempt in range(retry_config.ALPACA_MAX_RETRIES):
            try:
                bars = self.api.get_bars(
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    limit=limit,
                    page_token=page_token
                )
                
                logger.debug(f"バーデータ取得成功: {symbol} {len(bars)}件")
                return bars
                
            except tradeapi.rest.APIError as e:
                if e.code == 40410000:  # データなし
                    logger.warning(f"データなし: {symbol}")
                    return []
                elif self._is_retryable_error(e):
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(f"バーデータ取得リトライ {attempt+1}: {e} (待機{wait_time}秒)")
                    time.sleep(wait_time)
                else:
                    logger.error(f"バーデータ取得エラー: {e}")
                    raise
            except Exception as e:
                logger.error(f"バーデータ取得予期しないエラー: {e}")
                raise
        
        raise TradingError("バーデータ取得: 最大リトライ回数を超過")
    
    return _get_bars_with_retry()
```

---

## 2. EODHD API統合

### データプロバイダー機能
```python
class EODHDClient:
    """EODHD API統合クライアント（市場データ・基本情報）"""
    
    def __init__(self):
        self.api_key = os.getenv('EODHD_API_KEY')
        self.base_url = 'https://eodhd.com/api'
        self.session = self._create_session()
        
    def _create_session(self):
        """HTTPセッション作成（コネクションプーリング付き）"""
        session = requests.Session()
        
        # コネクションプーリング設定
        adapter = HTTPAdapter(
            pool_connections=system_config.CONNECTION_POOL_SIZE,
            pool_maxsize=system_config.CONNECTION_POOL_SIZE,
            max_retries=Retry(
                total=retry_config.EODHD_MAX_RETRIES,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504, 429]
            )
        )
        
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        return session
```

### 市場キャップデータ取得
```python
def get_market_cap_data(self, index_code='MID.INDX'):
    """
    市場キャップインデックス構成銘柄取得
    
    Args:
        index_code: インデックスコード（MID.INDX=Mid Cap, SMALL.INDX=Small Cap）
    
    Returns:
        list: 銘柄シンボルリスト
    """
    try:
        endpoint = f"{self.base_url}/fundamentals/{index_code}"
        params = {
            'api_token': self.api_key,
            'fmt': 'json'
        }
        
        response = self.session.get(endpoint, params=params, timeout=retry_config.HTTP_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        # 構成銘柄抽出
        if 'Components' in data:
            symbols = [comp['Code'] for comp in data['Components']]
            logger.info(f"{index_code} 構成銘柄数: {len(symbols)}")
            return symbols
        else:
            logger.warning(f"{index_code}: 構成銘柄データなし")
            return []
            
    except requests.exceptions.RequestException as e:
        logger.error(f"市場キャップデータ取得エラー {index_code}: {e}")
        return []
    except Exception as e:
        logger.error(f"市場キャップデータ処理エラー {index_code}: {e}")
        return []
```

### 履歴データ取得
```python
def get_historical_data(self, symbol, start_date, end_date, period='d'):
    """
    株価履歴データ取得
    
    Args:
        symbol: 銘柄シンボル（例: 'AAPL.US'）
        start_date: 開始日（YYYY-MM-DD）
        end_date: 終了日（YYYY-MM-DD）
        period: 期間（'d'=日次, 'w'=週次, 'm'=月次）
    
    Returns:
        pd.DataFrame: OHLCV データフレーム
    """
    try:
        endpoint = f"{self.base_url}/eod/{symbol}"
        params = {
            'api_token': self.api_key,
            'from': start_date,
            'to': end_date,
            'period': period,
            'fmt': 'json'
        }
        
        response = self.session.get(endpoint, params=params, timeout=retry_config.HTTP_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            logger.warning(f"履歴データなし: {symbol}")
            return pd.DataFrame()
        
        # DataFrameに変換
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # 数値型に変換
        numeric_columns = ['open', 'high', 'low', 'close', 'adjusted_close', 'volume']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        logger.info(f"履歴データ取得成功: {symbol} {len(df)}日分")
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"履歴データ取得エラー {symbol}: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"履歴データ処理エラー {symbol}: {e}")
        return pd.DataFrame()
```

---

## 3. Finviz Elite API統合

### スクリーニング機能
```python
class FinvizClient:
    """Finviz Elite APIクライアント（株式スクリーニング）"""
    
    def __init__(self):
        self.api_key = os.getenv('FINVIZ_API_KEY')
        self.base_url = 'https://elite.finviz.com/export.ashx'
        self.session = self._create_session()
        
    def build_screener_url(self, filters, columns=None, order=None):
        """
        スクリーナーURL構築
        
        Args:
            filters: フィルター辞書
            columns: 表示列リスト
            order: ソート順
        
        Returns:
            str: スクリーナーURL
        """
        params = {'auth': self.api_key}
        
        # フィルター適用
        for key, value in filters.items():
            params[f'f'] = f"{params.get('f', '')},{key}_{value}"
        
        # 列指定
        if columns:
            params['c'] = ','.join(map(str, columns))
        
        # ソート順指定
        if order:
            params['o'] = order
        
        url = f"{self.base_url}?" + "&".join([f"{k}={v}" for k, v in params.items()])
        logger.debug(f"スクリーナーURL構築: {url}")
        
        return url
```

### データ取得・解析
```python
def get_screener_data(self, url):
    """
    スクリーナーデータ取得・CSV解析
    
    Args:
        url: スクリーナーURL
    
    Returns:
        pd.DataFrame: スクリーニング結果
    """
    for attempt in range(retry_config.FINVIZ_MAX_RETRIES):
        try:
            response = self.session.get(url, timeout=retry_config.HTTP_TIMEOUT)
            response.raise_for_status()
            
            # CSV解析
            df = pd.read_csv(io.StringIO(response.text))
            
            # データクリーニング
            df = self._clean_screener_data(df)
            
            logger.info(f"スクリーナーデータ取得成功: {len(df)}銘柄")
            return df
            
        except requests.exceptions.RequestException as e:
            if response.status_code == 429:  # レート制限
                wait_time = self._calculate_rate_limit_wait(attempt)
                logger.warning(f"Finvizレート制限: {wait_time}秒待機")
                time.sleep(wait_time)
            else:
                logger.error(f"Finvizデータ取得エラー: {e}")
                if attempt == retry_config.FINVIZ_MAX_RETRIES - 1:
                    raise
                time.sleep(2 ** attempt)  # 指数バックオフ
        except Exception as e:
            logger.error(f"Finvizデータ処理エラー: {e}")
            raise
    
    raise TradingError("Finvizデータ取得: 最大リトライ回数を超過")

def _clean_screener_data(self, df):
    """スクリーナーデータのクリーニング"""
    if df.empty:
        return df
    
    # 基本的なクリーニング
    df = df.dropna(subset=['Ticker'])  # ティッカーが空の行を削除
    df['Ticker'] = df['Ticker'].str.upper()  # ティッカーを大文字に統一
    
    # 数値列の変換
    numeric_columns = ['Price', 'Change', 'Volume', 'Market Cap']
    for col in numeric_columns:
        if col in df.columns:
            df[col] = self._convert_to_numeric(df[col])
    
    # パーセンテージ列の変換
    percentage_columns = ['Change %', 'EPS surprise %']
    for col in percentage_columns:
        if col in df.columns:
            df[col] = df[col].str.replace('%', '').astype(float) / 100
    
    return df

def _convert_to_numeric(self, series):
    """文字列の数値を数値型に変換（K, M, B接尾辞対応）"""
    def convert_value(val):
        if pd.isna(val) or val == '-':
            return np.nan
        
        val = str(val).replace(',', '')
        
        if val.endswith('K'):
            return float(val[:-1]) * 1000
        elif val.endswith('M'):
            return float(val[:-1]) * 1000000
        elif val.endswith('B'):
            return float(val[:-1]) * 1000000000
        else:
            try:
                return float(val)
            except ValueError:
                return np.nan
    
    return series.apply(convert_value)
```

---

## 4. Google Sheets API統合

### 外部制御システム
```python
class GoogleSheetsClient:
    """Google Sheets API統合（外部制御・監視）"""
    
    def __init__(self):
        self.credentials_path = os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH')
        self.gc = self._authenticate()
        
    def _authenticate(self):
        """Google Sheets API認証"""
        try:
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                self.credentials_path, scope
            )
            
            return gspread.authorize(creds)
            
        except Exception as e:
            logger.error(f"Google Sheets認証エラー: {e}")
            raise
```

### 手動取引コマンド処理
```python
def process_trade_commands(self):
    """
    Google Sheetsからの手動取引コマンド処理
    
    シート構成:
    | Timestamp | Symbol | Action | Quantity | Price | Status |
    """
    try:
        # 取引コマンドシートを開く
        sheet = self.gc.open("trade_commands").sheet1
        
        # 未処理コマンド取得
        records = sheet.get_all_records()
        pending_commands = [r for r in records if r.get('Status') == 'PENDING']
        
        logger.info(f"未処理コマンド数: {len(pending_commands)}")
        
        for i, command in enumerate(pending_commands):
            try:
                result = self._execute_trade_command(command)
                
                # ステータス更新
                row_num = records.index(command) + 2  # ヘッダー行を考慮
                sheet.update(f'F{row_num}', 'COMPLETED' if result else 'FAILED')
                
                logger.info(f"コマンド実行完了: {command['Symbol']} {command['Action']}")
                
            except Exception as e:
                logger.error(f"コマンド実行エラー: {e}")
                # エラーステータス更新
                row_num = records.index(command) + 2
                sheet.update(f'F{row_num}', f'ERROR: {str(e)[:50]}')
                
    except Exception as e:
        logger.error(f"取引コマンド処理エラー: {e}")

def _execute_trade_command(self, command):
    """個別取引コマンド実行"""
    symbol = command['Symbol']
    action = command['Action'].upper()
    quantity = int(command['Quantity'])
    price = float(command['Price']) if command['Price'] else None
    
    # Alpacaクライアント取得
    alpaca_client = get_alpaca_client('live')
    
    # 注文パラメータ構築
    order_params = {
        'symbol': symbol,
        'qty': quantity,
        'side': 'buy' if action == 'BUY' else 'sell',
        'time_in_force': 'day'
    }
    
    if price:
        order_params['type'] = 'limit'
        order_params['limit_price'] = price
    else:
        order_params['type'] = 'market'
    
    # 注文実行
    order = alpaca_client.submit_order(**order_params)
    
    return order is not None
```

### ポートフォリオ監視データ更新
```python
def update_portfolio_monitoring(self):
    """ポートフォリオ監視データをGoogle Sheetsに更新"""
    try:
        # 監視シートを開く
        sheet = self.gc.open("portfolio_monitoring").sheet1
        
        # 現在のポジション取得
        alpaca_client = get_alpaca_client('live')
        positions = alpaca_client.get_positions()
        account = alpaca_client.get_account()
        
        # データ準備
        portfolio_data = []
        portfolio_data.append(['更新時刻', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        portfolio_data.append(['総資産', f"${float(account.portfolio_value):,.2f}"])
        portfolio_data.append(['現金', f"${float(account.cash):,.2f}"])
        portfolio_data.append(['買付余力', f"${float(account.buying_power):,.2f}"])
        portfolio_data.append([])  # 空行
        portfolio_data.append(['シンボル', '数量', '平均価格', '現在価格', '未実現損益', '損益率'])
        
        for position in positions:
            portfolio_data.append([
                position.symbol,
                int(position.qty),
                f"${float(position.avg_entry_price):.2f}",
                f"${float(position.current_price):.2f}",
                f"${float(position.unrealized_pl):,.2f}",
                f"{float(position.unrealized_plpc) * 100:.1f}%"
            ])
        
        # シート更新
        sheet.clear()
        sheet.update('A1', portfolio_data)
        
        logger.info("ポートフォリオ監視データ更新完了")
        
    except Exception as e:
        logger.error(f"ポートフォリオ監視データ更新エラー: {e}")
```

---

## 5. API統合エラーハンドリング

### サーキットブレーカーパターン
```python
class CircuitBreaker:
    """API呼び出しのサーキットブレーカー"""
    
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        
    def __call__(self, func):
        """デコレーターとして使用"""
        def wrapper(*args, **kwargs):
            if self.state == 'OPEN':
                if self._should_attempt_reset():
                    self.state = 'HALF_OPEN'
                else:
                    raise CircuitBreakerError("サーキットブレーカー開放中")
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
                
            except Exception as e:
                self._on_failure()
                raise
                
        return wrapper
    
    def _on_success(self):
        """成功時の処理"""
        self.failure_count = 0
        self.state = 'CLOSED'
        
    def _on_failure(self):
        """失敗時の処理"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(f"サーキットブレーカー開放: 失敗回数 {self.failure_count}")
    
    def _should_attempt_reset(self):
        """リセット試行判定"""
        return (time.time() - self.last_failure_time) >= self.timeout
```

### 統合監視システム
```python
class APIHealthMonitor:
    """API統合ヘルスモニタリング"""
    
    def __init__(self):
        self.api_status = {
            'alpaca': {'status': 'unknown', 'last_check': None, 'response_time': None},
            'eodhd': {'status': 'unknown', 'last_check': None, 'response_time': None},
            'finviz': {'status': 'unknown', 'last_check': None, 'response_time': None},
            'google_sheets': {'status': 'unknown', 'last_check': None, 'response_time': None}
        }
        
    def check_all_apis(self):
        """全API健康状態チェック"""
        results = {}
        
        for api_name in self.api_status.keys():
            try:
                start_time = time.time()
                status = self._check_api_health(api_name)
                response_time = time.time() - start_time
                
                self.api_status[api_name].update({
                    'status': 'healthy' if status else 'unhealthy',
                    'last_check': datetime.now(),
                    'response_time': response_time
                })
                
                results[api_name] = self.api_status[api_name]
                
            except Exception as e:
                self.api_status[api_name].update({
                    'status': 'error',
                    'last_check': datetime.now(),
                    'error': str(e)
                })
                results[api_name] = self.api_status[api_name]
        
        # 異常検出時のアラート
        unhealthy_apis = [name for name, status in results.items() 
                         if status['status'] != 'healthy']
        
        if unhealthy_apis:
            self._send_health_alert(unhealthy_apis)
        
        return results
    
    def _check_api_health(self, api_name):
        """個別API健康状態チェック"""
        if api_name == 'alpaca':
            client = get_alpaca_client('live')
            account = client.get_account()
            return account is not None
            
        elif api_name == 'eodhd':
            client = get_eodhd_client()
            # 軽量なAPIコール実行
            result = client.get_market_cap_data('MID.INDX')
            return len(result) > 0
            
        elif api_name == 'finviz':
            client = get_finviz_client()
            # 最小限のスクリーニング実行
            url = client.build_screener_url({'sh_price': 'o10'})
            data = client.get_screener_data(url)
            return len(data) > 0
            
        elif api_name == 'google_sheets':
            client = GoogleSheetsClient()
            sheets = client.gc.list_spreadsheet_files()
            return len(sheets) >= 0
        
        return False
```

このAPI統合システムは、外部サービスの可用性とパフォーマンスを監視しながら、堅牢で信頼性の高いデータ取得・取引執行を実現します。各APIクライアントは独立してテスト・デプロイ可能で、システム全体の保守性を保証します。