# トラブルシューティングガイド

## よくある問題と解決策

### 1. API接続エラー

#### 症状
```
ConnectionError: Failed to connect to Alpaca API
```

#### 原因と解決策

**原因1: APIキーの設定ミス**
```bash
# .envファイルを確認
cat .env | grep ALPACA_API_KEY
```
**解決策**: 正しいAPIキーを設定

**原因2: ネットワーク問題**
```bash
# 接続テスト
curl -H "APCA-API-KEY-ID: your_key" https://api.alpaca.markets/v2/account
```
**解決策**: ネットワーク環境を確認

**原因3: API制限に達している**
```python
# レート制限チェック
import time
time.sleep(1)  # 1秒待機してリトライ
```

### 2. 注文実行エラー

#### 症状
```
TradingError: Order rejected: insufficient buying power
```

#### 診断手順
1. **アカウント残高確認**
```python
from api_clients import get_alpaca_client

client = get_alpaca_client('live')
account = client.api.get_account()
print(f"Buying power: {account.buying_power}")
```

2. **ポジション確認**
```python
positions = client.api.list_positions()
for pos in positions:
    print(f"{pos.symbol}: {pos.qty} shares")
```

3. **注文履歴確認**
```python
orders = client.api.list_orders(status='all', limit=10)
for order in orders:
    print(f"{order.symbol}: {order.status}")
```

#### 解決策
- **残高不足**: ポジションサイズを調整
- **重複注文**: 既存注文をキャンセル
- **市場時間外**: 取引時間を確認

### 3. データ取得エラー

#### 症状
```
ValueError: No data available for symbol AAPL
```

#### 診断コマンド
```python
# データ可用性チェック
from api_clients import get_fmp_client

client = get_fmp_client()
try:
    data = client.get_historical_price_data("AAPL", "2023-12-01", "2023-12-06")
    print(f"Data points: {len(data)}")
except Exception as e:
    print(f"Error: {e}")
```

#### 解決策
1. **銘柄シンボル確認**: 正しい形式で入力
2. **日付範囲調整**: 市場営業日を指定
3. **API制限確認**: 使用量制限を確認

### 4. 設定エラー

#### 症状
```
ConfigurationError: Invalid configuration file
```

#### 設定ファイル検証
```python
# 設定検証スクリプト
from orb_config import get_orb_config

try:
    config = get_orb_config()
    print("✅ Configuration loaded successfully")
    print(f"Position size rate: {config.trading.position_size_rate}")
except Exception as e:
    print(f"❌ Configuration error: {e}")
```

#### よくある設定ミス
- **型エラー**: 数値を文字列で設定
- **範囲エラー**: 無効な値の設定
- **ファイルパス**: 相対パスの問題

### 5. メモリ・パフォーマンス問題

#### 症状
- プロセスが遅い
- メモリ使用量が多い
- タイムアウトエラー

#### 診断ツール
```python
import psutil
import time

# メモリ使用量監視
def monitor_memory():
    process = psutil.Process()
    print(f"Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB")

# 実行時間測定
start_time = time.time()
# ... 処理 ...
print(f"Execution time: {time.time() - start_time:.2f} seconds")
```

#### 最適化方法
1. **並列処理制限**
```python
# 同時実行数を制限
max_concurrent = 3  # デフォルト値を使用
```

2. **データキャッシュ**
```python
# キャッシュ設定
cache_duration = 300  # 5分間キャッシュ
```

3. **ガベージコレクション**
```python
import gc
gc.collect()  # 明示的なメモリ解放
```

### 6. ログ・デバッグ問題

#### ログレベル調整
```python
import logging

# デバッグモード有効化
logging.getLogger().setLevel(logging.DEBUG)
```

#### 詳細ログの確認
```bash
# ログファイル確認
tail -f logs/trading.log

# エラーログの抽出
grep -i error logs/trading.log | tail -20
```

#### デバッグ用設定
```python
# config.py でデバッグ設定
DEBUG_MODE = True
VERBOSE_LOGGING = True
```

### 7. テスト環境問題

#### テストモード確認
```python
# テスト実行
python -c "
from orb_refactored import ORBRefactoredStrategy
strategy = ORBRefactoredStrategy()
result = strategy.start_trading(
    symbol='AAPL', 
    test_mode=True, 
    test_date='2023-12-06'
)
print(f'Test result: {result}')
"
```

#### 模擬データ生成
```python
# テスト用データ作成
from datetime import datetime, timedelta
import pandas as pd

test_data = pd.DataFrame({
    'timestamp': pd.date_range(
        start=datetime.now() - timedelta(days=30),
        end=datetime.now(),
        freq='1H'
    ),
    'price': [150 + i*0.1 for i in range(720)]
})
```

## 緊急対応手順

### 1. 全ポジション強制クローズ
```python
from api_clients import get_alpaca_client

client = get_alpaca_client('live')
positions = client.api.list_positions()

for position in positions:
    try:
        client.api.close_position(position.symbol)
        print(f"✅ Closed position: {position.symbol}")
    except Exception as e:
        print(f"❌ Failed to close {position.symbol}: {e}")
```

### 2. 全注文キャンセル
```python
orders = client.api.list_orders(status='open')
for order in orders:
    try:
        client.api.cancel_order(order.id)
        print(f"✅ Cancelled order: {order.id}")
    except Exception as e:
        print(f"❌ Failed to cancel {order.id}: {e}")
```

### 3. システム停止
```python
# 緊急停止フラグ設定
import sys
import signal

def emergency_stop(signum, frame):
    print("🚨 Emergency stop activated")
    # クリーンアップ処理
    sys.exit(1)

signal.signal(signal.SIGINT, emergency_stop)
```

## サポート・連絡先

### ログ収集
問題報告時には以下の情報を含めてください：

1. **エラーメッセージ**: 完全なスタックトレース
2. **実行環境**: Python版、OS、メモリ使用量
3. **設定情報**: アカウント種別、取引設定
4. **ログファイル**: 関連する時間帯のログ

### 自動診断スクリプト
```bash
# システム診断実行
python scripts/system_diagnostics.py --full-check
```

### 開発者向けデバッグ
```python
# 詳細デバッグモード
import os
os.environ['DEBUG'] = '1'
os.environ['VERBOSE'] = '1'

# プロファイリング
import cProfile
cProfile.run('strategy.start_trading("AAPL")')
```
