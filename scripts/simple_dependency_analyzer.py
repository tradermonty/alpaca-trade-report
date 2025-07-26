"""
簡易依存関係分析スクリプト (外部依存なし)
循環依存リスクを特定し、インターフェース解決策を提案
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

@dataclass
class ImportInfo:
    """インポート情報"""
    from_module: str
    to_module: str
    import_type: str
    imported_items: List[str]
    line_number: int

class SimpleDependencyAnalyzer:
    def __init__(self):
        self.imports: List[ImportInfo] = []
        self.local_modules: Set[str] = set()
        
    def scan_local_modules(self):
        """ローカルモジュール一覧を取得"""
        for py_file in SRC_DIR.glob("*.py"):
            if not py_file.name.startswith('__'):
                self.local_modules.add(py_file.stem)
    
    def analyze_file(self, file_path: Path) -> List[ImportInfo]:
        """ファイルのインポート情報を分析"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            file_imports = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in self.local_modules:
                            import_info = ImportInfo(
                                from_module=file_path.stem,
                                to_module=alias.name,
                                import_type='import',
                                imported_items=[alias.name],
                                line_number=node.lineno
                            )
                            file_imports.append(import_info)
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module in self.local_modules:
                        imported_items = [alias.name for alias in node.names]
                        import_info = ImportInfo(
                            from_module=file_path.stem,
                            to_module=node.module,
                            import_type='from_import',
                            imported_items=imported_items,
                            line_number=node.lineno
                        )
                        file_imports.append(import_info)
            
            return file_imports
            
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
            return []
    
    def build_dependency_map(self) -> Dict[str, Set[str]]:
        """依存関係マップを構築"""
        dependency_map = defaultdict(set)
        
        for py_file in SRC_DIR.glob("*.py"):
            if py_file.name.startswith('__'):
                continue
                
            file_imports = self.analyze_file(py_file)
            self.imports.extend(file_imports)
            
            for import_info in file_imports:
                dependency_map[import_info.from_module].add(import_info.to_module)
        
        return dict(dependency_map)
    
    def find_circular_dependencies_simple(self, dependency_map: Dict[str, Set[str]]) -> List[List[str]]:
        """簡易循環依存検出"""
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]):
            if node in rec_stack:
                # 循環を検出
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return
            
            if node in visited:
                return
            
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in dependency_map.get(node, []):
                dfs(neighbor, path.copy())
            
            rec_stack.remove(node)
        
        for module in dependency_map:
            if module not in visited:
                dfs(module, [])
        
        return cycles
    
    def analyze_orb_dependencies(self) -> Dict[str, List[Dict]]:
        """orb.py関連の依存関係を詳細分析"""
        orb_analysis = {
            'imports_from_orb': [],
            'risky_imports': [],
            'potential_cycles': []
        }
        
        for import_info in self.imports:
            # orb.pyからのインポート
            if import_info.to_module == 'orb':
                orb_analysis['imports_from_orb'].append({
                    'from': import_info.from_module,
                    'items': import_info.imported_items,
                    'line': import_info.line_number,
                    'type': import_info.import_type
                })
                
                # リスクの高いインポート（グローバル状態）
                risky_items = [item for item in import_info.imported_items 
                             if item in ['api', 'order_status', 'test_mode', 'test_datetime', 
                                       'TZ_NY', 'TZ_UTC', 'ALPACA_ACCOUNT']]
                if risky_items:
                    orb_analysis['risky_imports'].append({
                        'from': import_info.from_module,
                        'risky_items': risky_items,
                        'line': import_info.line_number
                    })
                
                # 潜在的な循環依存（orb_*ファイル）
                if import_info.from_module.startswith('orb_'):
                    orb_analysis['potential_cycles'].append({
                        'from': import_info.from_module,
                        'items': import_info.imported_items,
                        'severity': 'high' if 'orb_refactored' in import_info.from_module else 'medium'
                    })
        
        return orb_analysis
    
    def generate_interface_solution(self) -> str:
        """インターフェース分離による解決策を生成"""
        return '''"""
取引機能の抽象インターフェース
循環依存を解決するためのインターフェース分離パターン
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TradingData:
    """取引データの標準形式"""
    symbol: str
    price: float
    timestamp: datetime
    volume: int

@dataclass
class OrderInfo:
    """注文情報の標準形式"""
    order_id: str
    symbol: str
    status: str
    filled_qty: float
    avg_fill_price: Optional[float] = None

class TradingInterface(ABC):
    """取引機能の抽象インターフェース"""
    
    @abstractmethod
    def is_uptrend(self, symbol: str) -> bool:
        """アップトレンド判定"""
        pass
    
    @abstractmethod
    def is_above_ema(self, symbol: str, period: int = 21) -> bool:
        """EMA上方判定"""
        pass
    
    @abstractmethod
    def is_below_ema(self, symbol: str, period: int = 21) -> bool:
        """EMA下方判定"""
        pass
    
    @abstractmethod
    def get_opening_range(self, symbol: str, minutes: int) -> Tuple[float, float]:
        """オープニングレンジ取得"""
        pass
    
    @abstractmethod
    def is_opening_range_break(self, symbol: str, high: float, low: float) -> bool:
        """オープニングレンジブレイク判定"""
        pass

class OrderManagementInterface(ABC):
    """注文管理の抽象インターフェース"""
    
    @abstractmethod
    def submit_bracket_orders(self, symbol: str, qty: float, 
                            entry_price: float, stop_price: float, 
                            target_price: float) -> Dict[str, str]:
        """ブラケット注文送信"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderInfo:
        """注文状況取得"""
        pass
    
    @abstractmethod
    def cancel_and_close_position(self, symbol: str) -> bool:
        """ポジションクローズ"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """ポジション取得"""
        pass

class MarketDataInterface(ABC):
    """マーケットデータの抽象インターフェース"""
    
    @abstractmethod
    def get_latest_close(self, symbol: str) -> float:
        """最新終値取得"""
        pass
    
    @abstractmethod
    def get_stop_price(self, symbol: str, entry_price: float, 
                      stop_rate: float) -> float:
        """ストップ価格計算"""
        pass
    
    @abstractmethod
    def get_profit_target(self, symbol: str, entry_price: float,
                         profit_rate: float) -> float:
        """利益目標価格計算"""
        pass

class TimeManagementInterface(ABC):
    """時間管理の抽象インターフェース"""
    
    @abstractmethod
    def is_entry_period(self) -> bool:
        """エントリー期間判定"""
        pass
    
    @abstractmethod
    def is_closing_time(self) -> bool:
        """クローズ時間判定"""
        pass

# 実装例: 既存のorb.py機能をラップするアダプター
class ORBAdapter(TradingInterface, OrderManagementInterface, 
                MarketDataInterface, TimeManagementInterface):
    """orb.pyの機能をインターフェース経由で提供するアダプター"""
    
    def __init__(self):
        # 遅延インポートで循環依存を回避
        self._orb_module = None
    
    @property
    def orb(self):
        """遅延インポートでorb.pyにアクセス"""
        if self._orb_module is None:
            import orb
            self._orb_module = orb
        return self._orb_module
    
    def is_uptrend(self, symbol: str) -> bool:
        return self.orb.is_uptrend(symbol)
    
    def is_above_ema(self, symbol: str, period: int = 21) -> bool:
        return self.orb.is_above_ema(symbol)
    
    def is_below_ema(self, symbol: str, period: int = 21) -> bool:
        return self.orb.is_below_ema(symbol)
    
    def get_opening_range(self, symbol: str, minutes: int) -> Tuple[float, float]:
        return self.orb.get_opening_range(symbol, minutes)
    
    def is_opening_range_break(self, symbol: str, high: float, low: float) -> bool:
        return self.orb.is_opening_range_break(symbol, high, low)
    
    def submit_bracket_orders(self, symbol: str, qty: float, 
                            entry_price: float, stop_price: float, 
                            target_price: float) -> Dict[str, str]:
        return self.orb.submit_bracket_orders(symbol, qty, entry_price, 
                                            stop_price, target_price)
    
    def get_order_status(self, order_id: str) -> OrderInfo:
        # グローバル変数order_statusを安全にアクセス
        status_dict = getattr(self.orb, 'order_status', {}).get(order_id, {})
        return OrderInfo(
            order_id=order_id,
            symbol=status_dict.get('symbol', ''),
            status=status_dict.get('status', ''),
            filled_qty=status_dict.get('filled_qty', 0.0),
            avg_fill_price=status_dict.get('avg_fill_price')
        )
    
    def cancel_and_close_position(self, symbol: str) -> bool:
        return self.orb.cancel_and_close_position(symbol)
    
    def get_positions(self) -> List[Dict[str, Any]]:
        return self.orb.api.list_positions()
    
    def get_latest_close(self, symbol: str) -> float:
        return self.orb.get_latest_close(symbol)
    
    def get_stop_price(self, symbol: str, entry_price: float, 
                      stop_rate: float) -> float:
        return self.orb.get_stop_price(symbol, entry_price, stop_rate)
    
    def get_profit_target(self, symbol: str, entry_price: float,
                         profit_rate: float) -> float:
        return self.orb.get_profit_target(symbol, entry_price, profit_rate)
    
    def is_entry_period(self) -> bool:
        return self.orb.is_entry_period()
    
    def is_closing_time(self) -> bool:
        return self.orb.is_closing_time()

# 使用例: orb_refactored.pyでの利用
class RefactoredORBStrategy:
    """リファクタリング版ORB戦略（循環依存なし）"""
    
    def __init__(self, adapter: ORBAdapter):
        self.adapter = adapter
    
    def execute_strategy(self, symbol: str, position_size: float) -> bool:
        """戦略実行（インターフェース経由）"""
        # 直接インポートではなく、インターフェース経由でアクセス
        if not self.adapter.is_uptrend(symbol):
            return False
        
        if not self.adapter.is_entry_period():
            return False
        
        high, low = self.adapter.get_opening_range(symbol, 30)
        
        if self.adapter.is_opening_range_break(symbol, high, low):
            entry_price = high + 0.01
            stop_price = self.adapter.get_stop_price(symbol, entry_price, 0.03)
            target_price = self.adapter.get_profit_target(symbol, entry_price, 0.06)
            
            orders = self.adapter.submit_bracket_orders(
                symbol, position_size, entry_price, stop_price, target_price
            )
            return bool(orders)
        
        return False

# 依存性注入コンテナ
class TradingServiceContainer:
    """取引サービスコンテナ"""
    
    def __init__(self):
        self._adapter = None
    
    @property
    def orb_adapter(self) -> ORBAdapter:
        """ORBアダプターのシングルトン取得"""
        if self._adapter is None:
            self._adapter = ORBAdapter()
        return self._adapter
    
    def create_orb_strategy(self) -> RefactoredORBStrategy:
        """ORB戦略インスタンスを作成"""
        return RefactoredORBStrategy(self.orb_adapter)

# グローバルコンテナ（必要に応じて）
_container = TradingServiceContainer()

def get_orb_strategy() -> RefactoredORBStrategy:
    """ORB戦略を取得（ファクトリー関数）"""
    return _container.create_orb_strategy()
'''
    
    def generate_migration_guide(self) -> str:
        """移行ガイドを生成"""
        return '''# 循環依存解決のための移行ガイド

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
'''
    
    def generate_report(self) -> str:
        """分析レポートを生成"""
        dependency_map = self.build_dependency_map()
        cycles = self.find_circular_dependencies_simple(dependency_map)
        orb_analysis = self.analyze_orb_dependencies()
        
        report = ["=== 依存関係分析レポート ===\n"]
        
        # 基本統計
        report.append("== 基本統計 ==")
        report.append(f"分析対象モジュール数: {len(self.local_modules)}")
        report.append(f"総インポート数: {len(self.imports)}")
        report.append(f"依存関係数: {sum(len(deps) for deps in dependency_map.values())}")
        report.append(f"検出された循環依存: {len(cycles)}")
        report.append("")
        
        # 循環依存の詳細
        if cycles:
            report.append("== 🚨 検出された循環依存 ==")
            for i, cycle in enumerate(cycles, 1):
                cycle_str = " → ".join(cycle)
                severity = "高" if any("orb" in module for module in cycle) else "低"
                report.append(f"#{i} (重要度: {severity}): {cycle_str}")
            report.append("")
        
        # orb.py関連の分析
        report.append("== 🎯 orb.py 依存関係分析 ==")
        
        if orb_analysis['imports_from_orb']:
            report.append("=== orb.py からインポートしているファイル ===")
            for imp in orb_analysis['imports_from_orb']:
                items = ", ".join(imp['items'][:5])
                if len(imp['items']) > 5:
                    items += "..."
                report.append(f"  📄 {imp['from']}.py (line {imp['line']}): {items}")
            report.append("")
        
        if orb_analysis['risky_imports']:
            report.append("=== 🚨 リスクの高いインポート (グローバル状態) ===")
            for imp in orb_analysis['risky_imports']:
                items = ", ".join(imp['risky_items'])
                report.append(f"  ⚠️  {imp['from']}.py (line {imp['line']}): {items}")
            report.append("")
        
        if orb_analysis['potential_cycles']:
            report.append("=== ⚡ 潜在的な循環依存リスク ===")
            for cycle in orb_analysis['potential_cycles']:
                items = ", ".join(cycle['items'][:3])
                if len(cycle['items']) > 3:
                    items += "..."
                report.append(f"  🔄 {cycle['from']}.py ({cycle['severity']}): {items}")
            report.append("")
        
        # 依存関係マップ
        report.append("== 📊 依存関係マップ ==")
        for module, deps in dependency_map.items():
            if deps:
                deps_str = ", ".join(sorted(deps))
                report.append(f"  {module} → {deps_str}")
        report.append("")
        
        # 推奨アクション
        report.append("== 📋 推奨アクション ==")
        report.append("1. 🚨 **高優先度**: orb_refactored.py の直接インポート削除")
        report.append("2. 🔧 **中優先度**: インターフェース分離パターンの実装")
        report.append("3. 🏗️ **低優先度**: 依存性注入コンテナの導入")
        report.append("4. 🧹 **継続的**: グローバル状態の段階的排除")
        report.append("")
        
        # 次のステップ
        report.append("== 🚀 次のステップ ==")
        report.append("1. trading_interfaces.py の作成と実装")
        report.append("2. ORBAdapter の実装とテスト")
        report.append("3. orb_refactored.py の段階的修正")
        report.append("4. 循環依存の完全解消")
        
        return "\n".join(report)

def main():
    """メイン処理"""
    print("🔍 Analyzing module dependencies (simple version)...")
    
    analyzer = SimpleDependencyAnalyzer()
    analyzer.scan_local_modules()
    
    # レポート生成
    report = analyzer.generate_report()
    print(f"\n{report}")
    
    # インターフェース解決策を生成
    interface_solution = analyzer.generate_interface_solution()
    interface_path = PROJECT_ROOT / "src" / "trading_interfaces.py"
    interface_path.write_text(interface_solution, encoding='utf-8')
    print(f"\n📄 インターフェース解決策を保存: {interface_path}")
    
    # 移行ガイドを生成
    migration_guide = analyzer.generate_migration_guide()
    guide_path = PROJECT_ROOT / "circular_dependency_migration_guide.md"
    guide_path.write_text(migration_guide, encoding='utf-8')
    print(f"📋 移行ガイドを保存: {guide_path}")
    
    # レポートを保存
    report_path = PROJECT_ROOT / "dependency_analysis_report.txt"
    report_path.write_text(report, encoding='utf-8')
    print(f"📊 詳細レポートを保存: {report_path}")
    
    print("\n✅ 依存関係分析が完了しました！")
    print("\n🎯 最優先タスク:")
    print("  1. src/trading_interfaces.py を確認")
    print("  2. orb_refactored.py の直接インポートを修正")
    print("  3. 循環依存リスクの解消")

if __name__ == "__main__":
    main()