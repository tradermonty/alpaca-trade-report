"""
命名規則統一分析スクリプト
コードベース全体の命名規則を分析し、不統一な箇所を特定
"""

import os
import re
import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

@dataclass
class NamingIssue:
    """命名規則の問題"""
    file_path: str
    issue_type: str
    current_name: str
    suggested_name: str
    line_number: int = 0
    context: str = ""

@dataclass
class NamingStats:
    """命名統計"""
    snake_case_vars: Set[str]
    upper_case_vars: Set[str]
    camel_case_vars: Set[str]
    abbreviations: Set[str]
    descriptive_names: Set[str]

class NamingAnalyzer:
    def __init__(self):
        self.issues: List[NamingIssue] = []
        self.stats = NamingStats(
            snake_case_vars=set(),
            upper_case_vars=set(),
            camel_case_vars=set(), 
            abbreviations=set(),
            descriptive_names=set()
        )
        
        # 既知の略語とその展開形
        self.abbreviation_map = {
            'orb': 'opening_range_breakout',
            'ema': 'exponential_moving_average',
            'api': 'application_programming_interface',
            'url': 'uniform_resource_locator',
            'tz': 'timezone',
            'utc': 'coordinated_universal_time',
            'ny': 'new_york',
            'pnl': 'profit_and_loss',
            'etf': 'exchange_traded_fund',
            'csv': 'comma_separated_values',
            'json': 'javascript_object_notation',
            'http': 'hypertext_transfer_protocol',
            'ssl': 'secure_sockets_layer',
            'id': 'identifier',
            'df': 'dataframe',
            'dt': 'datetime'
        }

    def is_snake_case(self, name: str) -> bool:
        """snake_case判定"""
        return bool(re.match(r'^[a-z]+(_[a-z0-9]+)*$', name))
    
    def is_upper_case(self, name: str) -> bool:
        """UPPER_CASE判定"""
        return bool(re.match(r'^[A-Z]+(_[A-Z0-9]+)*$', name))
    
    def is_camel_case(self, name: str) -> bool:
        """camelCase判定"""
        return bool(re.match(r'^[a-z]+([A-Z][a-z0-9]*)*$', name))
    
    def is_pascal_case(self, name: str) -> bool:
        """PascalCase判定"""
        return bool(re.match(r'^[A-Z][a-z0-9]*([A-Z][a-z0-9]*)*$', name))
    
    def contains_abbreviation(self, name: str) -> bool:
        """略語を含むかチェック"""
        name_lower = name.lower()
        for abbrev in self.abbreviation_map.keys():
            if abbrev in name_lower:
                return True
        return False
    
    def suggest_expanded_name(self, name: str) -> str:
        """略語を展開した名前を提案"""
        suggested = name.lower()
        
        for abbrev, expansion in self.abbreviation_map.items():
            if abbrev in suggested:
                suggested = suggested.replace(abbrev, expansion)
        
        # snake_case形式に変換
        return suggested
    
    def analyze_variable_name(self, name: str, file_path: str, line_num: int = 0, context: str = ""):
        """変数名を分析"""
        # 統計収集
        if self.is_snake_case(name):
            self.stats.snake_case_vars.add(name)
        elif self.is_upper_case(name):
            self.stats.upper_case_vars.add(name)
        elif self.is_camel_case(name):
            self.stats.camel_case_vars.add(name)
        
        if self.contains_abbreviation(name):
            self.stats.abbreviations.add(name)
        else:
            self.stats.descriptive_names.add(name)
        
        # 問題検出
        issues = []
        
        # 1. 変数と定数の命名規則混在チェック
        if name.isupper() and len(name.split('_')) == 1:
            # 単語の定数は許可されるが、複合語は要チェック
            pass
        elif name.isupper() and not self.is_upper_case(name):
            issues.append(NamingIssue(
                file_path, "inconsistent_case", name, 
                name.upper(), line_num, context
            ))
        elif not name.isupper() and not self.is_snake_case(name) and not self.is_camel_case(name):
            issues.append(NamingIssue(
                file_path, "invalid_format", name,
                self._to_snake_case(name), line_num, context
            ))
        
        # 2. 略語使用チェック
        if self.contains_abbreviation(name):
            expanded = self.suggest_expanded_name(name)
            if expanded != name.lower():
                issues.append(NamingIssue(
                    file_path, "abbreviation_usage", name,
                    expanded, line_num, context
                ))
        
        # 3. 混在した命名スタイル
        if self.is_camel_case(name) and file_path.endswith('.py'):
            # Pythonでは通常snake_caseを使用
            issues.append(NamingIssue(
                file_path, "style_inconsistency", name,
                self._to_snake_case(name), line_num, context
            ))
        
        self.issues.extend(issues)
    
    def _to_snake_case(self, name: str) -> str:
        """camelCaseをsnake_caseに変換"""
        # キャメルケースをスネークケースに変換
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    def analyze_file(self, file_path: Path):
        """ファイルを分析"""
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # 変数代入の検出
            for line_num, line in enumerate(content.split('\n'), 1):
                line = line.strip()
                
                # 変数代入パターン
                var_assignment = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=', line)
                if var_assignment:
                    var_name = var_assignment.group(1)
                    self.analyze_variable_name(var_name, str(file_path), line_num, line)
                
                # 関数定義パターン
                func_def = re.match(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)', line)
                if func_def:
                    func_name = func_def.group(1)
                    self.analyze_variable_name(func_name, str(file_path), line_num, line)
                
                # クラス定義パターン
                class_def = re.match(r'^class\s+([a-zA-Z_][a-zA-Z0-9_]*)', line)
                if class_def:
                    class_name = class_def.group(1)
                    if not self.is_pascal_case(class_name):
                        self.issues.append(NamingIssue(
                            str(file_path), "class_naming", class_name,
                            self._to_pascal_case(class_name), line_num, line
                        ))
            
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
    
    def _to_pascal_case(self, name: str) -> str:
        """snake_caseをPascalCaseに変換"""
        return ''.join(word.capitalize() for word in name.split('_'))
    
    def analyze_directory(self, directory: Path):
        """ディレクトリ内のPythonファイルを分析"""
        for py_file in directory.glob("*.py"):
            if py_file.name.startswith('__'):
                continue
            print(f"Analyzing {py_file.name}...")
            self.analyze_file(py_file)
    
    def generate_report(self) -> str:
        """分析レポートを生成"""
        report = ["=== 命名規則分析レポート ===\n"]
        
        # 統計情報
        report.append("== 命名スタイル統計 ==")
        report.append(f"snake_case変数: {len(self.stats.snake_case_vars)}個")
        report.append(f"UPPER_CASE定数: {len(self.stats.upper_case_vars)}個")
        report.append(f"camelCase変数: {len(self.stats.camel_case_vars)}個")
        report.append(f"略語使用: {len(self.stats.abbreviations)}個")
        report.append(f"説明的名前: {len(self.stats.descriptive_names)}個")
        report.append("")
        
        # 問題の分類と集計
        issue_types = {}
        for issue in self.issues:
            if issue.issue_type not in issue_types:
                issue_types[issue.issue_type] = []
            issue_types[issue.issue_type].append(issue)
        
        # 各問題タイプの詳細
        for issue_type, issues in issue_types.items():
            report.append(f"== {issue_type.replace('_', ' ').title()} ({len(issues)}件) ==")
            for issue in issues[:10]:  # 最初の10件のみ表示
                file_name = Path(issue.file_path).name
                report.append(f"  📄 {file_name}:{issue.line_number}")
                report.append(f"     現在: {issue.current_name}")
                report.append(f"     提案: {issue.suggested_name}")
                if issue.context:
                    report.append(f"     文脈: {issue.context[:50]}...")
                report.append("")
            
            if len(issues) > 10:
                report.append(f"     ...他 {len(issues) - 10}件")
                report.append("")
        
        # 修正の優先度
        report.append("== 修正優先度 ==")
        report.append("1. 高: style_inconsistency (Pythonの慣例違反)")
        report.append("2. 中: abbreviation_usage (可読性向上)")
        report.append("3. 低: inconsistent_case (軽微な不統一)")
        report.append("")
        
        # 推奨アクション
        report.append("== 推奨アクション ==")
        report.append("1. camelCaseをsnake_caseに統一")
        report.append("2. 略語を説明的な名前に展開")
        report.append("3. 定数は UPPER_CASE に統一")
        report.append("4. クラス名は PascalCase に統一")
        
        return "\n".join(report)

def main():
    """メイン処理"""
    print("🔍 Analyzing naming conventions...")
    
    analyzer = NamingAnalyzer()
    analyzer.analyze_directory(SRC_DIR)
    
    # レポート生成
    report = analyzer.generate_report()
    print(f"\n{report}")
    
    # レポートをファイルに保存
    report_path = PROJECT_ROOT / "naming_convention_report.txt"
    report_path.write_text(report, encoding='utf-8')
    print(f"\n📄 詳細レポートを保存: {report_path}")
    
    # 修正スクリプトの提案
    print("\n🔧 自動修正スクリプトの作成を推奨します:")
    print("   - camelCase → snake_case 変換")
    print("   - 略語展開 (orb → opening_range_breakout)")
    print("   - 定数の UPPER_CASE 統一")

if __name__ == "__main__":
    main()