"""
重複定数削除スクリプト
全ファイルの重複したTZ_NY、ALPACA_ACCOUNTを共通定数に置換
"""

import os
import re
import sys
from pathlib import Path

# プロジェクトルートを設定
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# 重複パターンと置換ルールの定義
DUPLICATE_PATTERNS = [
    {
        'pattern': r'TZ_NY = ZoneInfo\(["\']US/Eastern["\']\)',
        'replacement': 'TZ_NY = TIMEZONE.NY  # Migrated from common_constants',
        'import_needed': 'from common_constants import TIMEZONE'
    },
    {
        'pattern': r'TZ_UTC = ZoneInfo\(["\']UTC["\']\)',
        'replacement': 'TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants',
        'import_needed': 'from common_constants import TIMEZONE'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']live["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants',
        'import_needed': 'from common_constants import ACCOUNT'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']paper["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper")  # Migrated from common_constants',
        'import_needed': 'from common_constants import ACCOUNT'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']paper_short["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper_short")  # Migrated from common_constants',
        'import_needed': 'from common_constants import ACCOUNT'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']paper2["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper2")  # Migrated from common_constants',
        'import_needed': 'from common_constants import ACCOUNT'
    }
]

# ZoneInfoインポートの削除パターン
ZONINFO_IMPORT_PATTERNS = [
    r'from zoneinfo import ZoneInfo\n',
    r'import zoneinfo\n',
    r', ZoneInfo',
    r'ZoneInfo, ',
    r'ZoneInfo\n'
]


def find_files_with_duplicates():
    """重複定数を含むファイルを検索"""
    files_with_duplicates = set()
    
    for pattern_info in DUPLICATE_PATTERNS:
        pattern = pattern_info['pattern']
        
        for py_file in SRC_DIR.glob("*.py"):
            if py_file.name in ['common_constants.py', '__init__.py']:
                continue
                
            try:
                content = py_file.read_text(encoding='utf-8')
                if re.search(pattern, content):
                    files_with_duplicates.add(py_file)
                    print(f"Found duplicate in {py_file.name}: {pattern}")
            except Exception as e:
                print(f"Error reading {py_file}: {e}")
    
    return list(files_with_duplicates)


def add_common_imports(content: str, needed_imports: set) -> str:
    """必要な共通インポートを追加"""
    lines = content.split('\n')
    import_section_end = 0
    
    # インポートセクションの終了位置を見つける
    for i, line in enumerate(lines):
        if (line.strip() and 
            not line.startswith('import ') and 
            not line.startswith('from ') and
            not line.startswith('#') and
            not line.strip() == ''):
            import_section_end = i
            break
    
    # 既存のcommon_constantsインポートをチェック
    has_common_constants_import = any(
        'from common_constants import' in line or 'import common_constants' in line
        for line in lines[:import_section_end]
    )
    
    if not has_common_constants_import and needed_imports:
        # 新しいインポートを追加
        import_line = f"from common_constants import {', '.join(sorted(needed_imports))}"
        lines.insert(import_section_end, import_line)
    
    return '\n'.join(lines)


def remove_zoninfo_imports(content: str) -> str:
    """不要なZoneInfoインポートを削除"""
    for pattern in ZONINFO_IMPORT_PATTERNS:
        content = re.sub(pattern, '', content)
    
    # 空行の連続を整理
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    return content


def migrate_file(file_path: Path) -> dict:
    """ファイルの重複定数を移行"""
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        needed_imports = set()
        changes_made = []
        
        # 各パターンに対して置換を実行
        for pattern_info in DUPLICATE_PATTERNS:
            pattern = pattern_info['pattern']
            replacement = pattern_info['replacement']
            import_needed = pattern_info['import_needed'].split()[-1]  # TIMEZONE, ACCOUNT等を抽出
            
            if re.search(pattern, content):
                content = re.sub(pattern, replacement, content)
                needed_imports.add(import_needed)
                changes_made.append(f"Replaced: {pattern}")
        
        # 必要なインポートを追加
        if needed_imports:
            content = add_common_imports(content, needed_imports)
        
        # ZoneInfoインポートを削除
        content = remove_zoninfo_imports(content)
        
        # ファイルが変更された場合のみ書き込み
        if content != original_content:
            # バックアップ作成
            backup_path = file_path.with_suffix('.py.backup')
            backup_path.write_text(original_content, encoding='utf-8')
            
            # 更新されたコンテンツを書き込み
            file_path.write_text(content, encoding='utf-8')
            
            return {
                'file': file_path.name,
                'status': 'success',
                'changes': changes_made,
                'backup_created': str(backup_path),
                'imports_added': list(needed_imports)
            }
        else:
            return {
                'file': file_path.name,
                'status': 'no_changes',
                'changes': [],
                'backup_created': None,
                'imports_added': []
            }
            
    except Exception as e:
        return {
            'file': file_path.name,
            'status': 'error',
            'error': str(e),
            'changes': [],
            'backup_created': None,
            'imports_added': []
        }


def generate_migration_report(results: list) -> str:
    """移行レポートを生成"""
    report = ["=== Duplicate Constants Migration Report ===\n"]
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    no_change_count = sum(1 for r in results if r['status'] == 'no_changes')
    error_count = sum(1 for r in results if r['status'] == 'error')
    
    report.append(f"Total files processed: {len(results)}")
    report.append(f"Successfully migrated: {success_count}")
    report.append(f"No changes needed: {no_change_count}")
    report.append(f"Errors encountered: {error_count}")
    report.append("")
    
    # 成功した移行の詳細
    if success_count > 0:
        report.append("=== Successfully Migrated Files ===")
        for result in results:
            if result['status'] == 'success':
                report.append(f"\n📄 {result['file']}")
                report.append(f"   Backup: {result['backup_created']}")
                report.append(f"   Imports added: {result['imports_added']}")
                for change in result['changes']:
                    report.append(f"   ✅ {change}")
    
    # エラーの詳細
    if error_count > 0:
        report.append("\n=== Errors ===")
        for result in results:
            if result['status'] == 'error':
                report.append(f"\n❌ {result['file']}: {result['error']}")
    
    report.append("\n=== Next Steps ===")
    report.append("1. Test the migrated files to ensure functionality")
    report.append("2. Run the test suite to verify compatibility")
    report.append("3. Remove backup files after verification")
    report.append("4. Update any remaining hardcoded constants manually")
    
    return "\n".join(report)


def main():
    """メイン処理"""
    print("🔍 Searching for files with duplicate constants...")
    
    # 重複を含むファイルを検索
    files_to_migrate = find_files_with_duplicates()
    
    if not files_to_migrate:
        print("✅ No duplicate constants found!")
        return
    
    print(f"\n📁 Found {len(files_to_migrate)} files with duplicates:")
    for file_path in files_to_migrate:
        print(f"   - {file_path.name}")
    
    # ユーザー確認
    response = input(f"\n🤔 Proceed with migration? (y/N): ").strip().lower()
    if response != 'y':
        print("Migration cancelled.")
        return
    
    print("\n🚀 Starting migration...")
    
    # 各ファイルを移行
    results = []
    for file_path in files_to_migrate:
        print(f"Processing {file_path.name}...", end=" ")
        result = migrate_file(file_path)
        results.append(result)
        
        if result['status'] == 'success':
            print("✅")
        elif result['status'] == 'no_changes':
            print("➖")
        else:
            print("❌")
    
    # レポート生成
    report = generate_migration_report(results)
    print(f"\n{report}")
    
    # レポートをファイルに保存
    report_path = PROJECT_ROOT / "migration_report.txt"
    report_path.write_text(report, encoding='utf-8')
    print(f"\n📄 Detailed report saved to: {report_path}")


if __name__ == "__main__":
    main()


# 手動実行の場合の使用例
"""
# 全ファイルの重複を自動修正
python scripts/deduplicate_constants.py

# 特定ファイルのみ修正（スクリプト修正版）
from deduplicate_constants import migrate_file
from pathlib import Path

result = migrate_file(Path("src/earnings_swing.py"))
print(result)
"""