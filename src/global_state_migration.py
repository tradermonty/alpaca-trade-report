#!/usr/bin/env python3
"""
グローバル状態変数マイグレーション
既存のグローバル変数を状態管理システムに移行するスクリプト
"""

import os
import re
import shutil
from pathlib import Path
from typing import List, Dict, Tuple
from logging_config import get_logger

logger = get_logger(__name__)


class GlobalStateMigrator:
    """グローバル変数を状態管理システムに移行するクラス"""
    
    def __init__(self, src_directory: str = "src"):
        self.src_dir = Path(src_directory)
        self.backup_dir = Path("backup_before_migration")
        
        # 移行対象のグローバル変数パターン
        self.global_patterns = {
            'test_mode': {
                'pattern': r'^test_mode\s*=\s*(True|False)',
                'replacement': 'from state_manager import is_test_mode, set_test_mode\n# test_mode = is_test_mode()  # Migrated to state manager',
                'import_addition': 'from state_manager import is_test_mode, set_test_mode'
            },
            'alpaca_account': {
                'pattern': r'^ALPACA_ACCOUNT\s*=\s*[\'"](\w+)[\'"]',
                'replacement': 'from state_manager import get_current_account, set_current_account\n# ALPACA_ACCOUNT = get_current_account()  # Migrated to state manager',
                'import_addition': 'from state_manager import get_current_account, set_current_account'
            },
            'api_clients': {
                'pattern': r'^(\w+_client)\s*=\s*get_(\w+)_client\(',
                'replacement': r'# \1 = get_\2_client()  # Migrated to lazy initialization',
                'import_addition': None
            }
        }
        
        # 使用箇所の置き換えパターン
        self.usage_patterns = {
            'test_mode_check': {
                'pattern': r'\btest_mode\b',
                'replacement': 'is_test_mode()',
                'context_filter': lambda line: 'if' in line or 'and' in line or 'or' in line
            },
            'test_mode_assignment': {
                'pattern': r'test_mode\s*=\s*(True|False)',
                'replacement': r'set_test_mode(\1)',
                'context_filter': None
            },
            'alpaca_account_usage': {
                'pattern': r'\bALPACA_ACCOUNT\b',
                'replacement': 'get_current_account()',
                'context_filter': None
            }
        }
    
    def create_backup(self) -> bool:
        """移行前にバックアップを作成"""
        try:
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)
            
            shutil.copytree(self.src_dir, self.backup_dir)
            logger.info(f"バックアップ作成完了: {self.backup_dir}")
            return True
            
        except Exception as e:
            logger.error(f"バックアップ作成エラー: {e}")
            return False
    
    def analyze_global_variables(self) -> Dict[str, List[Tuple[str, int, str]]]:
        """グローバル変数の使用箇所を分析"""
        global_usage = {}
        
        for pattern_name, pattern_info in self.global_patterns.items():
            global_usage[pattern_name] = []
            
            for py_file in self.src_dir.glob("*.py"):
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    for line_num, line in enumerate(lines, 1):
                        if re.search(pattern_info['pattern'], line, re.MULTILINE):
                            global_usage[pattern_name].append((
                                str(py_file),
                                line_num,
                                line.strip()
                            ))
                            
                except Exception as e:
                    logger.error(f"ファイル分析エラー {py_file}: {e}")
        
        return global_usage
    
    def migrate_file(self, file_path: Path) -> bool:
        """個別ファイルのマイグレーション"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
            
            modified = False
            new_lines = []
            imports_to_add = set()
            
            # 行ごとに処理
            for line in lines:
                new_line = line
                
                # グローバル変数定義の置き換え
                for pattern_name, pattern_info in self.global_patterns.items():
                    if re.search(pattern_info['pattern'], line):
                        new_line = f"# {line}  # Migrated to state manager"
                        if pattern_info['import_addition']:
                            imports_to_add.add(pattern_info['import_addition'])
                        modified = True
                
                # 使用箇所の置き換え
                for usage_name, usage_info in self.usage_patterns.items():
                    if usage_info['context_filter'] is None or usage_info['context_filter'](line):
                        if re.search(usage_info['pattern'], line):
                            new_line = re.sub(usage_info['pattern'], usage_info['replacement'], new_line)
                            modified = True
                
                new_lines.append(new_line)
            
            # インポート文の追加
            if imports_to_add:
                # 既存のインポート文の後に追加
                import_insertion_point = 0
                for i, line in enumerate(new_lines):
                    if line.startswith('import ') or line.startswith('from '):
                        import_insertion_point = i + 1
                
                # 重複チェック
                existing_imports = '\n'.join(new_lines[:import_insertion_point + 5])
                for import_stmt in imports_to_add:
                    if import_stmt not in existing_imports:
                        new_lines.insert(import_insertion_point, import_stmt)
                        import_insertion_point += 1
                        modified = True
            
            # ファイルを更新
            if modified:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(new_lines))
                
                logger.info(f"マイグレーション完了: {file_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"ファイルマイグレーションエラー {file_path}: {e}")
            return False
    
    def migrate_all_files(self) -> Dict[str, bool]:
        """全ファイルのマイグレーション実行"""
        results = {}
        
        target_files = [
            'orb.py',
            'earnings_swing.py', 
            'relative_volume_trade.py',
            'dividend_portfolio_management.py',
            'maintain_swing.py',
            'orb_short.py',
            'earnings_swing_short.py',
            'trend_reversion_stock.py',
            'uptrend_stocks.py',
            'risk_management.py'
        ]
        
        for filename in target_files:
            file_path = self.src_dir / filename
            if file_path.exists():
                results[filename] = self.migrate_file(file_path)
            else:
                logger.warning(f"ファイルが見つかりません: {file_path}")
                results[filename] = False
        
        return results
    
    def create_migration_wrapper(self) -> None:
        """既存コードとの互換性を保つラッパー関数を作成"""
        wrapper_content = '''"""
既存コードとの互換性を保つためのラッパー関数
グローバル変数の段階的移行をサポート
"""

from state_manager import (
    get_state_manager, 
    is_test_mode, 
    set_test_mode,
    get_current_account,
    set_current_account,
    is_trading_enabled
)

# 互換性のためのグローバル変数（非推奨）
def get_test_mode():
    """test_mode の取得（非推奨：is_test_mode() を使用）"""
    import warnings
    warnings.warn("get_test_mode() は非推奨です。is_test_mode() を使用してください。", 
                  DeprecationWarning, stacklevel=2)
    return is_test_mode()

def get_alpaca_account():
    """ALPACA_ACCOUNT の取得（非推奨：get_current_account() を使用）"""
    import warnings
    warnings.warn("get_alpaca_account() は非推奨です。get_current_account() を使用してください。", 
                  DeprecationWarning, stacklevel=2)
    return get_current_account()

# モジュールレベルの互換変数
class CompatibilityGlobals:
    """後方互換性のためのプロパティクラス"""
    
    @property
    def test_mode(self):
        import warnings
        warnings.warn("グローバル変数 test_mode は非推奨です。is_test_mode() を使用してください。", 
                      DeprecationWarning, stacklevel=2)
        return is_test_mode()
    
    @test_mode.setter
    def test_mode(self, value):
        import warnings
        warnings.warn("グローバル変数 test_mode は非推奨です。set_test_mode() を使用してください。", 
                      DeprecationWarning, stacklevel=2)
        set_test_mode(value)
    
    @property
    def ALPACA_ACCOUNT(self):
        import warnings
        warnings.warn("グローバル変数 ALPACA_ACCOUNT は非推奨です。get_current_account() を使用してください。", 
                      DeprecationWarning, stacklevel=2)
        return get_current_account()
    
    @ALPACA_ACCOUNT.setter
    def ALPACA_ACCOUNT(self, value):
        import warnings
        warnings.warn("グローバル変数 ALPACA_ACCOUNT は非推奨です。set_current_account() を使用してください。", 
                      DeprecationWarning, stacklevel=2)
        set_current_account(value)

# 互換性インスタンス
_compat = CompatibilityGlobals()

# よく使用される変数のショートカット
test_mode = _compat.test_mode
ALPACA_ACCOUNT = _compat.ALPACA_ACCOUNT
'''
        
        wrapper_path = self.src_dir / 'global_compat.py'
        with open(wrapper_path, 'w', encoding='utf-8') as f:
            f.write(wrapper_content)
        
        logger.info(f"互換性ラッパー作成: {wrapper_path}")
    
    def generate_migration_report(self, analysis: Dict, results: Dict) -> str:
        """マイグレーション結果レポートを生成"""
        report = ["# グローバル状態変数マイグレーション レポート\n"]
        
        report.append("## 分析結果\n")
        for pattern_name, occurrences in analysis.items():
            report.append(f"### {pattern_name}")
            report.append(f"検出数: {len(occurrences)}")
            for file_path, line_num, content in occurrences:
                report.append(f"- {file_path}:{line_num} `{content}`")
            report.append("")
        
        report.append("## マイグレーション結果\n")
        successful = sum(1 for success in results.values() if success)
        total = len(results)
        
        report.append(f"成功: {successful}/{total} ファイル\n")
        
        for filename, success in results.items():
            status = "✅" if success else "❌"
            report.append(f"{status} {filename}")
        
        report.append("\n## 次のステップ\n")
        report.append("1. テスト実行: `python3 run_tests.py`")
        report.append("2. 動作確認: 各戦略の個別実行テスト")
        report.append("3. 互換性確認: 既存のインポート文の確認")
        report.append("4. 段階的削除: 非推奨警告の確認後、互換性コードの削除")
        
        return '\n'.join(report)
    
    def run_full_migration(self) -> bool:
        """完全なマイグレーション実行"""
        logger.info("グローバル状態変数マイグレーション開始")
        
        # 1. バックアップ作成
        if not self.create_backup():
            logger.error("バックアップ作成に失敗。マイグレーション中止。")
            return False
        
        # 2. 現状分析
        logger.info("グローバル変数使用箇所を分析中...")
        analysis = self.analyze_global_variables()
        
        # 3. マイグレーション実行
        logger.info("ファイルマイグレーション実行中...")
        results = self.migrate_all_files()
        
        # 4. 互換性ラッパー作成
        logger.info("互換性ラッパー作成中...")
        self.create_migration_wrapper()
        
        # 5. レポート生成
        report = self.generate_migration_report(analysis, results)
        report_path = Path("migration_report.md")
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"マイグレーションレポート生成: {report_path}")
        
        # 6. 結果サマリー
        successful_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        logger.info(f"マイグレーション完了: {successful_count}/{total_count} ファイル成功")
        
        if successful_count == total_count:
            logger.info("✅ 全ファイルのマイグレーションに成功しました")
            return True
        else:
            logger.warning(f"⚠️  {total_count - successful_count} ファイルのマイグレーションに失敗")
            logger.info("詳細は migration_report.md を確認してください")
            return False


def main():
    """メイン実行関数"""
    print("グローバル状態変数マイグレーション")
    print("=" * 40)
    
    migrator = GlobalStateMigrator()
    
    # 確認プロンプト
    response = input("マイグレーションを実行しますか？ [y/N]: ")
    if response.lower() not in ['y', 'yes']:
        print("マイグレーションをキャンセルしました。")
        return
    
    # マイグレーション実行
    success = migrator.run_full_migration()
    
    if success:
        print("\n✅ マイグレーション完了!")
        print("次のコマンドでテストを実行してください:")
        print("python3 run_tests.py")
    else:
        print("\n❌ マイグレーションが完全には完了しませんでした。")
        print("migration_report.md で詳細を確認してください。")


if __name__ == '__main__':
    main()