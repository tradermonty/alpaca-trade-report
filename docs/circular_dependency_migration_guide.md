# 循環依存解決のための移行ガイド

## 現在の問題

### 検出された循環依存リスク
1. **orb_refactored.py → orb.py**
   - 直接インポート: `from orb import (api, order_status, is_uptrend, ...)`
   - リスク: 将来的にorb.pyがorb_refactored.pyを参照する可能性

2. **グローバル状態への依存**
   - `order_status` (グローバル辞書)
   - `api` (グローバルAPIクライアント)
   - `test_mode`, `test_datetime` (テスト用グローバル変数)

## 解決策の実装手順

### Step 1: インターフェースファイルの作成
```bash
# trading_interfaces.py を src/ ディレクトリに作成
cp trading_interfaces.py src/
```

### Step 2: orb_refactored.py の修正
#### Before (現在):
```python
from orb import (
    api, order_status, is_uptrend, is_above_ema, get_opening_range, 
    is_opening_range_break, submit_bracket_orders, get_stop_price, 
    get_profit_target, is_closing_time, get_latest_close, 
    cancel_and_close_position, cancel_and_close_all_position, 
    is_below_ema, print_order_status, is_entry_period
)
```

#### After (修正後):
```python
from trading_interfaces import (
    TradingInterface, OrderManagementInterface, 
    MarketDataInterface, TimeManagementInterface,
    ORBAdapter, get_orb_strategy
)

class ORBRefactoredStrategy:
    def __init__(self):
        self.adapter = ORBAdapter()
    
    def start_trading(self, symbol: str, position_size: float, **kwargs):
        # インターフェース経由でのみアクセス
        if not self.adapter.is_uptrend(symbol):
            return False
        # ... 以下同様
```

### Step 3: テストコードの更新
```python
# tests/test_orb_refactored.py
def test_orb_strategy():
    from trading_interfaces import ORBAdapter
    
    # モックアダプターを使用
    mock_adapter = MockORBAdapter()
    strategy = ORBRefactoredStrategy()
    strategy.adapter = mock_adapter
    
    # テスト実行
    result = strategy.execute_strategy("AAPL", 100)
    assert result == expected_result
```

### Step 4: 段階的移行
1. **Phase 1**: インターフェース導入（1-2日）
   - trading_interfaces.py 作成
   - ORBAdapter 実装
   - 基本テスト

2. **Phase 2**: orb_refactored.py 修正（1日）
   - 直接インポートをアダプター経由に変更
   - 既存機能のテスト確認

3. **Phase 3**: グローバル状態の完全排除（2-3日）
   - order_status をサービスクラスに移行
   - test_mode/test_datetime の依存性注入
   - 全体テストの実行

## 期待される効果

### 即座の効果
- ✅ 循環依存リスクの解消
- ✅ テスタビリティの向上
- ✅ モック化の容易さ

### 中長期的効果
- 🔄 コードの再利用性向上
- 🛡️ 堅牢性の向上
- 🚀 新機能追加の容易さ

## リスク管理

### 低リスク項目
- インターフェース定義
- アダプターパターンの実装
- 既存コードとの並行運用

### 中リスク項目
- orb_refactored.py の修正
- テストコードの更新
- 一時的な性能影響

### 高リスク項目
- orb.py の大幅修正
- グローバル状態の完全排除
- 本番環境への適用

## 実装チェックリスト

- [ ] trading_interfaces.py の作成
- [ ] ORBAdapter の実装とテスト
- [ ] orb_refactored.py の修正
- [ ] 既存テストの通過確認
- [ ] 新しいテストの追加
- [ ] ドキュメントの更新
- [ ] コードレビューの実施
- [ ] 本番環境での動作確認

## トラブルシューティング

### 問題: インポートエラー
```python
# 解決策: 遅延インポートの使用
def get_orb_function():
    import orb
    return orb.some_function
```

### 問題: 性能影響
```python
# 解決策: キャッシュの実装
class CachedORBAdapter(ORBAdapter):
    def __init__(self):
        super().__init__()
        self._cache = {}
```

### 問題: テスト実行時の問題
```python
# 解決策: テスト用アダプターの作成
class TestORBAdapter(ORBAdapter):
    def __init__(self, mock_responses=None):
        self.mock_responses = mock_responses or {}
```
