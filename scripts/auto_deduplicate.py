"""
自動重複定数削除スクリプト（非インタラクティブ版）
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
        'import_needed': 'TIMEZONE'
    },
    {
        'pattern': r'TZ_UTC = ZoneInfo\(["\']UTC["\']\)',
        'replacement': 'TZ_UTC = TIMEZONE.UTC  # Migrated from common_constants',
        'import_needed': 'TIMEZONE'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']live["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type()  # Migrated from common_constants',
        'import_needed': 'ACCOUNT'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']paper["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper")  # Migrated from common_constants',
        'import_needed': 'ACCOUNT'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']paper_short["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper_short")  # Migrated from common_constants',
        'import_needed': 'ACCOUNT'
    },
    {
        'pattern': r'ALPACA_ACCOUNT = ["\']paper2["\']',
        'replacement': 'ALPACA_ACCOUNT = ACCOUNT.get_account_type(override="paper2")  # Migrated from common_constants',
        'import_needed': 'ACCOUNT'
    }
]


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
            import_needed = pattern_info['import_needed']
            
            if re.search(pattern, content):
                content = re.sub(pattern, replacement, content)
                needed_imports.add(import_needed)
                changes_made.append(f"Replaced: {pattern}")
        
        # 必要なインポートを追加
        if needed_imports:
            content = add_common_imports(content, needed_imports)
        
        # ZoneInfoインポートを削除（簡易版）
        if 'from zoneinfo import ZoneInfo' in content:
            content = content.replace('from zoneinfo import ZoneInfo\n', '')
            content = content.replace('from zoneinfo import ZoneInfo', '')
        
        # ファイルが変更された場合のみ書き込み
        if content != original_content:
            file_path.write_text(content, encoding='utf-8')
            
            return {
                'file': file_path.name,
                'status': 'success',
                'changes': changes_made,
                'imports_added': list(needed_imports)
            }
        else:
            return {
                'file': file_path.name,
                'status': 'no_changes',
                'changes': []
            }
            
    except Exception as e:
        return {
            'file': file_path.name,
            'status': 'error',
            'error': str(e),
            'changes': []
        }


def add_common_imports(content: str, needed_imports: set) -> str:
    """必要な共通インポートを追加"""
    lines = content.split('\n')
    
    # インポートセクションの終了位置を見つける
    import_section_end = 0
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


def main():
    """メイン処理（自動実行）"""
    print("🔍 Auto-migrating duplicate constants...")
    
    target_files = [
        "earnings_swing.py", "relative_volume_trade.py", "orb.py", 
        "orb_short.py", "dividend_portfolio_management.py", 
        "maintain_swing.py", "trend_reversion_etf.py",
        "trend_reversion_stock.py", "strategy_allocation.py",
        "uptrend_stocks.py", "uptrend_count_sector.py"
    ]
    
    results = []
    
    for filename in target_files:
        file_path = SRC_DIR / filename
        if file_path.exists():
            print(f"Processing {filename}...", end=" ")
            result = migrate_file(file_path)
            results.append(result)
            
            if result['status'] == 'success':
                print("✅")
            elif result['status'] == 'no_changes':
                print("➖")
            else:
                print(f"❌ {result.get('error', 'Unknown error')}")
        else:
            print(f"⚠️  {filename} not found")
    
    # 結果サマリー
    success_count = sum(1 for r in results if r['status'] == 'success')
    print(f"\n🎉 Migration completed!")
    print(f"   Successfully migrated: {success_count} files")
    print(f"   Total changes: {sum(len(r['changes']) for r in results)}")
    
    return results


if __name__ == "__main__":
    main()