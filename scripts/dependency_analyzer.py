"""
依存関係と循環依存分析スクリプト
インポート構造を分析し、循環依存のリスクを特定
"""

import ast
import os
import networkx as nx
import matplotlib.pyplot as plt
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
    import_type: str  # 'from_import', 'import', 'relative'
    imported_items: List[str]
    line_number: int

@dataclass
class CircularDependency:
    """循環依存情報"""
    cycle: List[str]
    severity: str  # 'high', 'medium', 'low'
    description: str

class DependencyAnalyzer:
    def __init__(self):
        self.imports: List[ImportInfo] = []
        self.dependency_graph = nx.DiGraph()
        self.circular_dependencies: List[CircularDependency] = []
        
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
                        import_info = ImportInfo(
                            from_module=file_path.stem,
                            to_module=alias.name,
                            import_type='import',
                            imported_items=[alias.name],
                            line_number=node.lineno
                        )
                        file_imports.append(import_info)
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
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
    
    def build_dependency_graph(self):
        """依存関係グラフを構築"""
        for py_file in SRC_DIR.glob("*.py"):
            if py_file.name.startswith('__'):
                continue
                
            file_imports = self.analyze_file(py_file)
            self.imports.extend(file_imports)
            
            # グラフにノードとエッジを追加
            for import_info in file_imports:
                # ローカルモジュールのみを対象
                if import_info.to_module in [f.stem for f in SRC_DIR.glob("*.py")]:
                    self.dependency_graph.add_edge(
                        import_info.from_module, 
                        import_info.to_module,
                        import_info=import_info
                    )
    
    def find_circular_dependencies(self):
        """循環依存を検出"""
        try:
            cycles = list(nx.simple_cycles(self.dependency_graph))
            
            for cycle in cycles:
                severity = self._assess_cycle_severity(cycle)
                description = self._generate_cycle_description(cycle)
                
                circular_dep = CircularDependency(
                    cycle=cycle,
                    severity=severity,
                    description=description
                )
                self.circular_dependencies.append(circular_dep)
                
        except Exception as e:
            print(f"Error finding cycles: {e}")
    
    def _assess_cycle_severity(self, cycle: List[str]) -> str:
        """循環依存の深刻度を評価"""
        # orb.py関連の循環依存は高リスク
        if 'orb' in cycle or 'orb_refactored' in cycle:
            return 'high'
        
        # 長い循環は中リスク
        if len(cycle) > 3:
            return 'medium'
        
        return 'low'
    
    def _generate_cycle_description(self, cycle: List[str]) -> str:
        """循環依存の説明を生成"""
        cycle_str = " → ".join(cycle + [cycle[0]])
        
        # 具体的なインポート情報を収集
        details = []
        for i in range(len(cycle)):
            from_module = cycle[i]
            to_module = cycle[(i + 1) % len(cycle)]
            
            # 該当するインポート情報を検索
            for import_info in self.imports:
                if (import_info.from_module == from_module and 
                    import_info.to_module == to_module):
                    items = ", ".join(import_info.imported_items[:3])
                    if len(import_info.imported_items) > 3:
                        items += "..."
                    details.append(f"{from_module} imports {items} from {to_module}")
        
        return f"Cycle: {cycle_str}\nDetails:\n" + "\n".join(f"  - {d}" for d in details)
    
    def analyze_orb_dependencies(self) -> Dict[str, List[str]]:
        """orb.py関連の依存関係を詳細分析"""
        orb_analysis = {
            'imports_from_orb': [],
            'imports_to_orb': [],
            'risky_imports': []
        }
        
        for import_info in self.imports:
            # orb.pyからのインポート
            if import_info.to_module == 'orb':
                orb_analysis['imports_from_orb'].append({
                    'from': import_info.from_module,
                    'items': import_info.imported_items,
                    'line': import_info.line_number
                })
            
            # orb.pyへのインポート
            if import_info.from_module == 'orb':
                orb_analysis['imports_to_orb'].append({
                    'to': import_info.to_module,
                    'items': import_info.imported_items,
                    'line': import_info.line_number
                })
            
            # リスクの高いインポート（関数やグローバル変数）
            if (import_info.to_module == 'orb' and 
                any(item in ['api', 'order_status', 'test_mode', 'test_datetime'] 
                    for item in import_info.imported_items)):
                orb_analysis['risky_imports'].append({
                    'from': import_info.from_module,
                    'risky_items': [item for item in import_info.imported_items 
                                  if item in ['api', 'order_status', 'test_mode', 'test_datetime']],
                    'line': import_info.line_number
                })
        
        return orb_analysis
    
    def generate_interface_solution(self) -> str:
        """インターフェース分離による解決策を生成"""
        solution = """
# 循環依存解決のためのインターフェース設計

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

@dataclass
class TradingData:
    \"\"\"取引データの標準形式\"\"\"
    symbol: str
    price: float
    timestamp: datetime
    volume: int

@dataclass
class OrderInfo:
    \"\"\"注文情報の標準形式\"\"\"
    order_id: str
    symbol: str
    status: str
    filled_qty: float
    avg_fill_price: Optional[float] = None

class TradingInterface(ABC):
    \"\"\"取引機能の抽象インターフェース\"\"\"
    
    @abstractmethod
    def is_uptrend(self, symbol: str) -> bool:
        \"\"\"アップトレンド判定\"\"\"
        pass
    
    @abstractmethod
    def is_above_ema(self, symbol: str, period: int = 21) -> bool:
        \"\"\"EMA上方判定\"\"\"
        pass
    
    @abstractmethod
    def get_opening_range(self, symbol: str, minutes: int) -> Tuple[float, float]:
        \"\"\"オープニングレンジ取得\"\"\"
        pass
    
    @abstractmethod
    def submit_bracket_orders(self, symbol: str, qty: float, 
                            entry_price: float, stop_price: float, 
                            target_price: float) -> Dict[str, str]:
        \"\"\"ブラケット注文送信\"\"\"
        pass

class MarketDataInterface(ABC):
    \"\"\"マーケットデータの抽象インターフェース\"\"\"
    
    @abstractmethod
    def get_latest_price(self, symbol: str) -> float:
        \"\"\"最新価格取得\"\"\"
        pass
    
    @abstractmethod
    def get_historical_data(self, symbol: str, period: str) -> List[TradingData]:
        \"\"\"履歴データ取得\"\"\"
        pass

class OrderManagementInterface(ABC):
    \"\"\"注文管理の抽象インターフェース\"\"\"
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderInfo:
        \"\"\"注文状況取得\"\"\"
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        \"\"\"注文キャンセル\"\"\"
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        \"\"\"ポジション取得\"\"\"
        pass

# 実装例: orb.pyの機能をインターフェース経由で提供
class ORBTradingService:
    \"\"\"ORB取引サービス（依存性注入）\"\"\"
    
    def __init__(self, 
                 trading: TradingInterface,
                 market_data: MarketDataInterface,
                 order_mgmt: OrderManagementInterface):
        self.trading = trading
        self.market_data = market_data
        self.order_mgmt = order_mgmt
    
    def execute_orb_strategy(self, symbol: str, position_size: float) -> bool:
        \"\"\"ORB戦略の実行（循環依存なし）\"\"\"
        # インターフェース経由でのみアクセス
        if not self.trading.is_uptrend(symbol):
            return False
        
        high, low = self.trading.get_opening_range(symbol, 30)
        current_price = self.market_data.get_latest_price(symbol)
        
        if current_price > high:
            # ブレイクアウト検出
            stop_price = low
            target_price = current_price + (current_price - low) * 2
            
            orders = self.trading.submit_bracket_orders(
                symbol, position_size, current_price, stop_price, target_price
            )
            return bool(orders)
        
        return False

# 使用例:
# trading_service = ORBTradingService(
#     trading=ORBTradingImplementation(),
#     market_data=AlpacaMarketData(),
#     order_mgmt=AlpacaOrderManagement()
# )
"""
        return solution
    
    def generate_migration_plan(self) -> str:
        """段階的移行計画を生成"""
        plan = """
# 循環依存解決のための段階的移行計画

## Phase 1: インターフェース定義 (即座に実行可能)
1. trading_interfaces.py を作成
   - TradingInterface, MarketDataInterface, OrderManagementInterface
   - 標準データクラス (TradingData, OrderInfo)

2. 既存コードの影響評価
   - orb_refactored.py の import 文を分析
   - 使用されている関数のシグネチャを確認

## Phase 2: アダプターパターンの実装 (中リスク)
1. ORBAdapter クラスの作成
   ```python
   class ORBAdapter(TradingInterface):
       def __init__(self):
           # 既存のorb.pyの関数をラップ
           pass
       
       def is_uptrend(self, symbol: str) -> bool:
           from orb import is_uptrend as orb_is_uptrend
           return orb_is_uptrend(symbol)
   ```

2. 段階的移行
   - orb_refactored.py でアダプターを使用
   - 直接インポートを削除

## Phase 3: 完全な分離 (大規模リファクタリング)
1. orb.py の機能を複数のサービスクラスに分割
   - TradingService (is_uptrend, is_above_ema)
   - MarketDataService (get_opening_range, get_latest_close)
   - OrderService (submit_bracket_orders, cancel_orders)

2. 依存性注入コンテナの実装
   ```python
   class ServiceContainer:
       def __init__(self):
           self.trading = TradingService()
           self.market_data = MarketDataService()
           self.orders = OrderService()
   ```

## 優先度とリスク評価

### 高優先度 (即座に対応)
- orb_refactored.py → orb.py の直接インポート
- グローバル変数 (order_status, api) への依存

### 中優先度 (計画的な対応)
- 関数レベルの依存関係の整理
- テストコードの循環依存

### 低優先度 (将来的な改善)
- ファイル構造の再編成
- パッケージ分割

## 期待される効果
1. テスタビリティの向上
2. コードの再利用性向上  
3. 循環依存の完全解消
4. 保守性の大幅改善
"""
        return plan
    
    def visualize_dependencies(self, output_path: str = None):
        """依存関係グラフを可視化"""
        try:
            plt.figure(figsize=(12, 8))
            pos = nx.spring_layout(self.dependency_graph, k=1, iterations=50)
            
            # ノードの色分け
            node_colors = []
            for node in self.dependency_graph.nodes():
                if 'orb' in node:
                    node_colors.append('red')  # orb関連は赤
                elif any(node in cycle for cycle in [c.cycle for c in self.circular_dependencies]):
                    node_colors.append('orange')  # 循環依存は橙
                else:
                    node_colors.append('lightblue')  # その他は青
            
            nx.draw(self.dependency_graph, pos, 
                   node_color=node_colors,
                   node_size=1000,
                   with_labels=True,
                   font_size=8,
                   font_weight='bold',
                   arrows=True,
                   edge_color='gray',
                   arrowsize=20)
            
            plt.title("Module Dependency Graph\n(Red: ORB-related, Orange: Circular dependencies)")
            
            if output_path:
                plt.savefig(output_path, dpi=300, bbox_inches='tight')
                print(f"Dependency graph saved to: {output_path}")
            else:
                plt.show()
                
        except Exception as e:
            print(f"Error creating visualization: {e}")
    
    def generate_report(self) -> str:
        """分析レポートを生成"""
        report = ["=== 依存関係分析レポート ===\n"]
        
        # 基本統計
        report.append("== 基本統計 ==")
        report.append(f"分析対象ファイル数: {len(set(imp.from_module for imp in self.imports))}")
        report.append(f"総インポート数: {len(self.imports)}")
        report.append(f"依存関係エッジ数: {self.dependency_graph.number_of_edges()}")
        report.append(f"循環依存数: {len(self.circular_dependencies)}")
        report.append("")
        
        # 循環依存の詳細
        if self.circular_dependencies:
            report.append("== 🚨 検出された循環依存 ==")
            for i, cycle in enumerate(self.circular_dependencies, 1):
                report.append(f"=== 循環依存 #{i} (重要度: {cycle.severity.upper()}) ===")
                report.append(cycle.description)
                report.append("")
        
        # orb.py関連の分析
        orb_analysis = self.analyze_orb_dependencies()
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
            report.append("=== 🚨 リスクの高いインポート (グローバル変数・状態) ===")
            for imp in orb_analysis['risky_imports']:
                items = ", ".join(imp['risky_items'])
                report.append(f"  ⚠️  {imp['from']}.py (line {imp['line']}): {items}")
            report.append("")
        
        # 推奨アクション
        report.append("== 📋 推奨アクション ==")
        report.append("1. 高優先度: orb_refactored.py の直接インポートを削除")
        report.append("2. インターフェース分離パターンの実装")
        report.append("3. 依存性注入コンテナの導入")
        report.append("4. グローバル状態の完全な排除")
        
        return "\n".join(report)

def main():
    """メイン処理"""
    print("🔍 Analyzing module dependencies...")
    
    analyzer = DependencyAnalyzer()
    
    # 1. 依存関係グラフを構築
    analyzer.build_dependency_graph()
    
    # 2. 循環依存を検出
    analyzer.find_circular_dependencies()
    
    # 3. レポート生成
    report = analyzer.generate_report()
    print(f"\n{report}")
    
    # 4. インターフェース解決策を生成
    interface_solution = analyzer.generate_interface_solution()
    interface_path = PROJECT_ROOT / "trading_interfaces.py"
    interface_path.write_text(interface_solution, encoding='utf-8')
    print(f"\n📄 インターフェース解決策を保存: {interface_path}")
    
    # 5. 移行計画を生成
    migration_plan = analyzer.generate_migration_plan()
    plan_path = PROJECT_ROOT / "dependency_migration_plan.md"
    plan_path.write_text(migration_plan, encoding='utf-8')
    print(f"📋 移行計画を保存: {plan_path}")
    
    # 6. レポートを保存
    report_path = PROJECT_ROOT / "dependency_analysis_report.txt"
    report_path.write_text(report, encoding='utf-8')
    print(f"📊 詳細レポートを保存: {report_path}")
    
    # 7. 可視化（オプション）
    try:
        graph_path = PROJECT_ROOT / "dependency_graph.png"
        analyzer.visualize_dependencies(str(graph_path))
    except ImportError:
        print("📊 グラフ可視化をスキップ (matplotlib未インストール)")

if __name__ == "__main__":
    main()