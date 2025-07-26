# グローバル変数完全排除ガイド

## 🎯 **目的**
Stock Trading System全体からグローバル変数を完全に排除し、依存性注入パターンによる保守性の高いアーキテクチャに移行する。

## 📊 **現状分析**

### **グローバル変数使用状況**
```bash
# 発見されたグローバル変数使用箇所
global test_datetime        # 15ファイルで使用
global order_status         # 2ファイルで重要な状態
global test_mode            # 5ファイルで使用
global POSITION_SIZE        # 取引サイズの管理
global opening_range        # 取引レンジ設定
```

### **問題の深刻度**
| ファイル | グローバル変数数 | 深刻度 | 影響範囲 |
|---------|----------------|--------|---------|
| `orb.py` | 8個 | 🔴 Critical | Core trading logic |
| `orb_short.py` | 10個 | 🔴 Critical | Short trading strategy |
| `earnings_swing.py` | 3個 | 🟡 Medium | Earnings strategy |
| その他 | 2-3個 | 🟢 Low | Support functions |

## 🚀 **段階的移行戦略**

### **Phase 1: 状態管理基盤の構築** ✅ 完了
```python
# 作成済みファイル:
# - orb_state_manager.py: TradingState, TradingSessionManager
# - orb_global_refactor.py: ORBTradingEngine (完全リファクタリング版)
```

### **Phase 2: 重要モジュールの移行** 🔄 進行中

#### **2.1 orb.pyの段階的移行**

**Step 1: 関数レベルでの移行**
```python
# Before: グローバル変数使用
def get_latest_close(symbol):
    global test_datetime
    if test_mode:
        # test_datetimeを直接使用
        
# After: 状態注入
def get_latest_close(symbol: str, state: TradingState) -> float:
    current_dt = state.get_current_datetime()
    if state.test_mode:
        # 状態から取得
```

**Step 2: クラス化による状態管理**
```python
# 既存の関数をクラスメソッドに変換
class ORBLegacyWrapper:
    def __init__(self, config: ORBConfiguration):
        self.config = config
        self.state = TradingState(config=config)
    
    def get_latest_close(self, symbol: str) -> float:
        # リファクタリングされたロジック
        return self._get_latest_close_impl(symbol, self.state)
```

#### **2.2 互換性レイヤーの実装**
```python
# 既存コードとの互換性を保つラッパー
class CompatibilityLayer:
    """レガシーコードとの互換性を保つラッパークラス"""
    
    _global_state = None
    
    @classmethod
    def get_global_state(cls) -> TradingState:
        if cls._global_state is None:
            cls._global_state = TradingState()
        return cls._global_state
    
    @classmethod
    def get_latest_close_legacy(cls, symbol: str) -> float:
        """レガシー関数の互換ラッパー"""
        state = cls.get_global_state()
        engine = ORBTradingEngine()
        return engine.get_latest_close(symbol, state)

# レガシーコードから段階的に移行
get_latest_close = CompatibilityLayer.get_latest_close_legacy
```

### **Phase 3: 全ファイルの統一** 🔮 計画中

#### **3.1 共通状態管理パターンの適用**
```python
# すべての戦略ファイルで統一されたパターン
class BaseStrategy:
    def __init__(self, config: ORBConfiguration):
        self.config = config
        self.session_manager = get_session_manager(config)
        
    def execute_strategy(self, symbol: str, **params):
        state = self.session_manager.create_session(symbol, **params)
        # 戦略固有のロジック
```

#### **3.2 設定の一元化**
```python
# 重複している設定値の統一
# Before: 各ファイルで個別定義
# TZ_NY = ZoneInfo("US/Eastern")  # 15箇所で重複
# ALPACA_ACCOUNT = 'live'         # 8箇所で重複

# After: 設定から取得
config = get_orb_config()
timezone = config.market.ny_timezone
account = config.system.default_account
```

## 🔧 **具体的な実装手順**

### **手順1: 既存コードの安全な移行**

```python
# 1. ラッパークラスの作成
class ORBMigrationWrapper:
    def __init__(self):
        self.config = get_orb_config()
        self.engine = ORBTradingEngine(self.config)
        self.current_state = None
    
    def start_trading_legacy(self):
        """既存のstart_trading()関数をラップ"""
        # 引数解析（既存ロジック維持）
        args = self._parse_legacy_arguments()
        
        # 新しいエンジンで実行
        return self.engine.start_trading_session(
            args['symbol'], **args
        )
    
    def _parse_legacy_arguments(self):
        """既存の引数解析ロジックを移植"""
        # argparse ロジックをそのまま移植
        pass

# 2. 段階的な関数置換
# orb.pyに追加:
_migration_wrapper = ORBMigrationWrapper()

def start_trading():
    """Legacy function - now delegates to refactored engine"""
    return _migration_wrapper.start_trading_legacy()
```

### **手順2: テストカバレッジの確保**

```python
# 移行前後のテスト
class TestGlobalVariableMigration:
    def test_legacy_vs_refactored_equivalence(self):
        """レガシー版とリファクタリング版の等価性テスト"""
        symbol = "AAPL"
        
        # レガシー実行
        legacy_result = run_legacy_orb(symbol)
        
        # リファクタリング版実行
        engine = ORBTradingEngine()
        refactored_result = engine.start_trading_session(symbol)
        
        # 結果の比較
        assert abs(legacy_result - refactored_result) < 0.01
    
    def test_state_isolation(self):
        """状態の分離テスト"""
        engine = ORBTradingEngine()
        
        # 複数セッションの並行実行
        session1 = engine.create_trading_session("AAPL")
        session2 = engine.create_trading_session("TSLA")
        
        # 状態の独立性確認
        assert session1.symbol != session2.symbol
        assert session1.order_status != session2.order_status
```

### **手順3: パフォーマンス検証**

```python
# メモリ使用量の比較
class PerformanceComparison:
    def benchmark_memory_usage(self):
        """メモリ使用量ベンチマーク"""
        
        # Before: グローバル変数使用
        memory_before = self.measure_memory_usage_legacy()
        
        # After: 状態管理クラス使用
        memory_after = self.measure_memory_usage_refactored()
        
        improvement = (memory_before - memory_after) / memory_before
        logger.info(f"Memory improvement: {improvement:.1%}")
```

## 📈 **移行のメリット**

### **1. テスト可能性の向上**
```python
# Before: テストできない
def test_get_latest_close():
    # グローバル変数のため、状態を制御できない
    global test_datetime, test_mode
    # テストが困難

# After: 完全にテスト可能
def test_get_latest_close():
    config = get_orb_config()
    engine = ORBTradingEngine(config)
    state = TradingState(test_mode=True, test_datetime=specific_time)
    
    result = engine.get_latest_close("AAPL", state)
    assert result > 0
```

### **2. 並行実行の安全性**
```python
# Before: 並行実行不可能
# グローバル変数の競合により、複数シンボルの同時取引が危険

# After: 安全な並行実行
async def parallel_trading():
    engine = ORBTradingEngine()
    
    tasks = [
        engine.start_trading_session("AAPL"),
        engine.start_trading_session("TSLA"), 
        engine.start_trading_session("MSFT")
    ]
    
    results = await asyncio.gather(*tasks)
    return results
```

### **3. デバッグ性の向上**
```python
# Before: デバッグ困難
# グローバル変数の変更タイミングが不明確

# After: 明確な状態追跡
def debug_trading_session(symbol: str):
    engine = ORBTradingEngine()
    state = engine.create_trading_session(symbol)
    
    # 任意の時点での状態確認
    debug_info = state.to_dict()
    logger.debug(f"Trading state: {debug_info}")
    
    # 状態変更の明確な追跡
    state.update_order('order1', entry_price=150.0)
    logger.debug(f"Order updated: {state.get_order_info('order1')}")
```

## ⚠️ **移行時の注意点**

### **1. 既存動作の保証**
```python
# 移行中は必ず互換性テストを実行
class MigrationValidation:
    def validate_backward_compatibility(self):
        """後方互換性の検証"""
        test_cases = [
            ("AAPL", {"range": 5, "swing": False}),
            ("TSLA", {"range": 10, "swing": True}),
        ]
        
        for symbol, params in test_cases:
            legacy_result = self.run_legacy(symbol, params)
            new_result = self.run_refactored(symbol, params)
            
            assert self.are_equivalent(legacy_result, new_result)
```

### **2. メモリリークの防止**
```python
# セッション管理の適切な実装
class MemoryManagement:
    def __init__(self):
        self.session_manager = get_session_manager()
    
    def cleanup_completed_sessions(self):
        """完了セッションの定期クリーンアップ"""
        self.session_manager.cleanup_completed_sessions()
        
    def monitor_memory_usage(self):
        """メモリ使用量の監視"""
        status = self.session_manager.get_system_status()
        if status['active_sessions'] > 10:
            logger.warning("Too many active sessions, consider cleanup")
```

## 🎯 **移行完了の成功指標**

### **定量的指標**
- [ ] グローバル変数の使用箇所: **0箇所** (現在: 47箇所)
- [ ] テストカバレッジ: **95%以上** (現在: 65%)
- [ ] メモリ使用量: **30%削減** 
- [ ] 並行実行可能数: **制限なし** (現在: 1セッションのみ)

### **定性的指標**
- [ ] 新機能追加時のコード変更箇所が明確
- [ ] デバッグ時の状態追跡が容易
- [ ] ユニットテストの作成が簡単
- [ ] コードレビューでの理解が早い

## 📋 **移行チェックリスト**

### **Phase 1: 基盤構築** ✅
- [x] TradingState クラスの実装
- [x] TradingSessionManager の実装  
- [x] ORBTradingEngine の実装
- [x] 設定管理システムの統合

### **Phase 2: 重要モジュール移行** 🔄
- [ ] orb.py の段階的移行
- [ ] orb_short.py の移行
- [ ] テスト追加と検証
- [ ] パフォーマンス測定

### **Phase 3: 全体統一** 🔮
- [ ] earnings_swing.py 等の移行
- [ ] 共通パターンの適用
- [ ] ドキュメント更新
- [ ] 最終テストと検証

## 🚀 **次のアクション**

1. **即座に実行**:
   - `orb_state_manager.py` と `orb_global_refactor.py` の統合テスト
   - 既存 `orb.py` への互換性レイヤー追加

2. **今週中に完了**:
   - `orb.py` の主要関数のリファクタリング
   - 並行実行テストの実装

3. **来週までに**:
   - 全グローバル変数の洗い出しと移行計画
   - パフォーマンステストの実装

**このガイドに従って段階的に移行することで、システムの安定性を保ちながらグローバル変数を完全に排除し、保守性の高いアーキテクチャを実現できます。** 🎯