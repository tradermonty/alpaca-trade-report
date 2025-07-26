# API リファレンス

## 取引システム API

### トレーディング・インターフェース

#### TradingInterface
抽象取引インターフェース。全ての取引機能の基底となるインターフェースです。

**主要メソッド:**

##### `is_uptrend(symbol: str) -> bool`
指定銘柄のアップトレンド判定を行います。

- **引数**: `symbol` - 取引銘柄シンボル (例: "AAPL")
- **戻り値**: アップトレンドの場合 `True`
- **例外**: `ValueError` - 無効なシンボルの場合

##### `get_opening_range(symbol: str, minutes: int) -> Tuple[float, float]`
オープニングレンジ（始値圏）を取得します。

- **引数**: 
  - `symbol` - 取引銘柄シンボル
  - `minutes` - 範囲計算期間（分）
- **戻り値**: `(高値, 安値)` のタプル
- **例外**: `ConnectionError` - API接続エラーの場合

#### OrderManagementInterface  
注文管理インターフェース。注文の送信、監視、管理機能を提供します。

##### `submit_bracket_orders(symbol: str, qty: float, entry_price: float, stop_price: float, target_price: float) -> Dict[str, str]`
ブラケット注文を送信します。

- **引数**:
  - `symbol` - 銘柄シンボル
  - `qty` - 注文数量
  - `entry_price` - エントリー価格
  - `stop_price` - ストップロス価格
  - `target_price` - 利益確定価格
- **戻り値**: 注文ID辞書 `{"parent": "order_id", "stop": "order_id", "target": "order_id"}`

### 設定・構成クラス

#### ORBConfiguration
ORB戦略の設定を管理するクラスです。

**主要属性:**
- `trading.position_size_rate: float` - ポジションサイズ率 (デフォルト: 0.06)
- `trading.orb_stop_rate_1: float` - 第1注文ストップ率 (デフォルト: 0.06)
- `market.ny_timezone: ZoneInfo` - ニューヨーク市場タイムゾーン

**使用例:**
```python
from orb_config import get_orb_config

config = get_orb_config()
position_rate = config.trading.position_size_rate
print(f"Position size rate: {position_rate}")
```

#### TradingConfig
取引関連の設定を管理します。

**重要な設定値:**
- `MAX_STOP_RATE: float = 0.06` - 最大ストップロス率
- `POSITION_SIZE_RATE: float = 0.06` - ポジションサイズ基準率
- `EMA_PERIOD_SHORT: int = 21` - 短期EMA期間

### ユーティリティ・クラス

#### StateManager
グローバル状態を管理するシングルトンクラスです。

##### `get_instance() -> StateManager`
StateManagerのシングルトンインスタンスを取得します。

- **戻り値**: StateManagerインスタンス
- **スレッドセーフ**: はい

##### `update_state(key: str, value: Any) -> None`
状態値を更新します。

- **引数**:
  - `key` - 状態キー
  - `value` - 設定する値
- **例外**: `KeyError` - 無効なキーの場合

### エラー・ハンドリング

#### 一般的な例外

##### `TradingError`
取引関連のエラーを示す基底例外クラス。

##### `ConfigurationError`  
設定関連のエラーを示す例外クラス。

##### `ConnectionError`
API接続エラーを示す例外クラス。

#### エラー対応パターン

```python
try:
    result = trading_interface.submit_bracket_orders(
        symbol="AAPL", qty=100, entry_price=150.0, 
        stop_price=145.0, target_price=155.0
    )
except TradingError as e:
    logger.error(f"Trading error: {e}")
    # エラー処理ロジック
except ConnectionError as e:
    logger.error(f"Connection failed: {e}")
    # リトライロジック
```

### レート制限・パフォーマンス

#### API制限
- **Alpaca API**: 200リクエスト/分
- **EODHD API**: 100,000リクエスト/日
- **Finviz**: レート制限あり（自動調整）

#### パフォーマンス最適化
- **並列処理**: 最大3同時取引
- **キャッシュ**: 市場データ5分間キャッシュ
- **バッチ処理**: 複数銘柄の一括処理対応

### 設定ファイル

#### 環境変数
```bash
# .env ファイル
ALPACA_API_KEY_LIVE=your_live_key
ALPACA_SECRET_KEY_LIVE=your_live_secret
ALPACA_ACCOUNT_TYPE=live  # or paper
LOG_LEVEL=INFO
```

#### 設定ファイル構造
```
config/
├── trading_config.py    # 取引設定
├── market_config.py     # 市場設定  
├── risk_config.py       # リスク管理設定
└── api_config.py        # API設定
```

### 使用例・クックブック

#### 基本的なORB取引
```python
from orb_refactored import ORBRefactoredStrategy

# 戦略インスタンス作成
strategy = ORBRefactoredStrategy()

# 取引実行
success = strategy.start_trading(
    symbol="AAPL",
    position_size=100,
    opening_range=30,
    is_swing=False
)

if success:
    print("取引が正常に実行されました")
```

#### カスタム設定での取引
```python
from orb_config import ORBConfiguration

# カスタム設定
config = ORBConfiguration()
config.trading.position_size_rate = 0.04  # 4%リスク
config.trading.orb_stop_rate_1 = 0.03     # 3%ストップ

# 設定を使用して取引
strategy = ORBRefactoredStrategy(config)
strategy.start_trading("TSLA", position_size="auto")
```
