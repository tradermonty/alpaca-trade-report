"""
命名規則統一修正スクリプト
最も問題の多い略語と命名スタイルを修正
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# 修正する略語マッピング（最も問題となるもののみ）
CRITICAL_ABBREVIATION_FIXES = {
    # 変数レベル（頻出かつ重要）
    'test_datetime': 'test_datetime',  # 既に適切
    'test_mode': 'test_mode',         # 既に適切
    'TZ_NY': 'TIMEZONE_NY',           # 定数として統一
    'TZ_UTC': 'TIMEZONE_UTC',         # 定数として統一
    
    # ファイル名レベル（重要度高）
    'orb.py': 'opening_range_breakout.py',
    'orb_': 'opening_range_breakout_',
    
    # 関数・クラス名（中程度の修正）
    'get_orb_': 'get_opening_range_breakout_',
    'ORB': 'OPENING_RANGE_BREAKOUT',
}

# 段階的修正計画
PHASE_1_FIXES = {
    # 最優先: 定数の統一（UPPER_CASE）
    'test_datetime': 'TEST_DATETIME',  # グローバル変数を定数として扱う場合
    'test_mode': 'TEST_MODE',          # グローバル変数を定数として扱う場合
}

PHASE_2_FIXES = {
    # ファイル名の略語展開（リファクタリング後）
    'orb': 'opening_range_breakout',
}

PHASE_3_FIXES = {
    # 関数名・変数名の統一
    'TZ_NY': 'TIMEZONE_NY',
    'TZ_UTC': 'TIMEZONE_UTC',
}

def analyze_naming_issues():
    """現在の命名問題を分析"""
    print("=== 命名規則問題の分析 ===")
    
    issues = {
        "snake_case_vs_UPPER_CASE": [],
        "abbreviation_usage": [],
        "file_naming": []
    }
    
    # snake_case vs UPPER_CASE の混在検出
    for py_file in SRC_DIR.glob("*.py"):
        content = py_file.read_text(encoding='utf-8')
        
        # test_datetime と test_mode の使用パターンを検出
        for line_num, line in enumerate(content.split('\n'), 1):
            if 'test_datetime' in line and not line.strip().startswith('#'):
                issues["snake_case_vs_UPPER_CASE"].append({
                    'file': py_file.name,
                    'line': line_num,
                    'content': line.strip(),
                    'issue': 'test_datetime should be TEST_DATETIME (constant)'
                })
            
            if 'test_mode' in line and not line.strip().startswith('#'):
                issues["snake_case_vs_UPPER_CASE"].append({
                    'file': py_file.name,
                    'line': line_num,
                    'content': line.strip(),
                    'issue': 'test_mode should be TEST_MODE (constant)'
                })
    
    # 略語使用の検出
    for py_file in SRC_DIR.glob("*orb*.py"):
        issues["abbreviation_usage"].append({
            'file': py_file.name,
            'suggestion': py_file.name.replace('orb', 'opening_range_breakout'),
            'issue': 'File name uses abbreviation "orb"'
        })
    
    # ファイル命名の検出
    naming_patterns = {
        'earnings_swing.py': 'descriptive',
        'orb.py': 'abbreviation',
        'api_clients.py': 'mixed',
        'config.py': 'simple'
    }
    
    for file_name, pattern in naming_patterns.items():
        if (SRC_DIR / file_name).exists():
            issues["file_naming"].append({
                'file': file_name,
                'pattern': pattern,
                'issue': f'Naming pattern: {pattern}'
            })
    
    return issues

def create_phase1_fixes():
    """Phase 1: 定数の UPPER_CASE 統一"""
    print("\n🔧 Phase 1: 定数の UPPER_CASE 統一")
    
    # test_datetime と test_mode をグローバル定数として扱う
    target_files = [
        'earnings_swing.py',
        'orb.py', 
        'relative_volume_trade.py',
        'dividend_portfolio_management.py'
    ]
    
    fixes_applied = 0
    
    for filename in target_files:
        file_path = SRC_DIR / filename
        if not file_path.exists():
            continue
            
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        
        # グローバル変数の定数化（選択的）
        # test_mode = False → TEST_MODE = False (グローバルスコープのみ)
        content = re.sub(
            r'^test_mode = (True|False)$',
            r'TEST_MODE = \1  # Migrated to constant naming',
            content,
            flags=re.MULTILINE
        )
        
        # test_datetime の定数化
        content = re.sub(
            r'^test_datetime = ',
            r'TEST_DATETIME = ',
            content,
            flags=re.MULTILINE
        )
        
        if content != original_content:
            file_path.write_text(content, encoding='utf-8')
            fixes_applied += 1
            print(f"  ✅ {filename} - グローバル変数を定数化")
    
    print(f"  Modified {fixes_applied} files")

def create_phase2_fixes():
    """Phase 2: タイムゾーン定数の統一"""
    print("\n🔧 Phase 2: タイムゾーン定数の統一")
    
    # common_constants.py を更新してより明確な命名にする
    common_constants_path = SRC_DIR / "common_constants.py"
    if common_constants_path.exists():
        content = common_constants_path.read_text(encoding='utf-8')
        
        # より明確な定数名への変更提案をコメントで追加
        updated_content = content + """

# 命名規則統一の提案:
# 将来的な改善案（後方互換性を保ちながら段階的に移行）

@dataclass
class ImprovedTimeZoneConfig:
    \"\"\"改善されたタイムゾーン設定（明示的命名）\"\"\"
    NEW_YORK: ZoneInfo = ZoneInfo("US/Eastern")
    COORDINATED_UNIVERSAL_TIME: ZoneInfo = ZoneInfo("UTC")
    TOKYO: ZoneInfo = ZoneInfo("Asia/Tokyo")
    LONDON: ZoneInfo = ZoneInfo("Europe/London")

# 段階的移行のためのエイリアス
# IMPROVED_TIMEZONE = ImprovedTimeZoneConfig()

# 使用例:
# current_time = datetime.now(IMPROVED_TIMEZONE.NEW_YORK)  # より明示的
# current_time = datetime.now(TIMEZONE.NY)                 # 現在の方式（短縮形）
"""
        
        common_constants_path.write_text(updated_content, encoding='utf-8')
        print("  ✅ common_constants.py - 改善案を追加")

def create_naming_standards_guide():
    """命名規則ガイドの作成"""
    guide_content = """# 命名規則統一ガイド

## 現在の問題点

### 1. 変数と定数の命名スタイル混在
- **問題**: `test_datetime` (snake_case) vs `TZ_NY` (UPPER_CASE)
- **解決**: グローバル定数は UPPER_CASE、ローカル変数は snake_case

### 2. 略語の不統一な使用
- **問題**: `orb` (abbreviation) vs `earnings_swing` (descriptive)
- **解決**: 略語辞書を作成し、説明的な名前を推奨

### 3. ファイル命名の不統一
- **問題**: 混在した命名パターン
- **解決**: 統一されたファイル命名規則

## 推奨される命名規則

### 定数 (Constants)
```python
# ✅ 推奨
TEST_MODE = False
TIMEZONE_NEW_YORK = ZoneInfo("US/Eastern")
OPENING_RANGE_BREAKOUT_ENTRY_PERIOD = 120

# ❌ 非推奨
test_mode = False
TZ_NY = ZoneInfo("US/Eastern")
orb_entry_period = 120
```

### 変数 (Variables)
```python
# ✅ 推奨
current_datetime = datetime.now()
earnings_surprise_threshold = 0.05
opening_range_breakout_strategy = ORBStrategy()

# ❌ 非推奨
currentDateTime = datetime.now()
eps_threshold = 0.05
orb_strategy = ORBStrategy()
```

### ファイル名 (File Names)
```python
# ✅ 推奨
opening_range_breakout.py           # 説明的
earnings_swing_strategy.py          # 説明的
exponential_moving_average_calc.py  # 説明的

# ❌ 非推奨
orb.py              # 略語
ema_calc.py         # 略語
swing.py            # 曖昧
```

### クラス名 (Class Names)
```python
# ✅ 推奨
class OpeningRangeBreakoutStrategy:
class EarningsSwingTrader:
class RiskManagementEngine:

# ❌ 非推奨
class ORBStrategy:
class earnings_swing_trader:
class risk_mgmt:
```

## 略語展開辞書

| 略語 | 展開形 | 使用推奨 |
|------|--------|----------|
| orb  | opening_range_breakout | 新規コードでは展開形を使用 |
| ema  | exponential_moving_average | 一般的なため略語も許可 |
| api  | application_programming_interface | 一般的なため略語も許可 |
| url  | uniform_resource_locator | 一般的なため略語も許可 |
| tz   | timezone | 展開形を推奨 |
| pnl  | profit_and_loss | 金融業界標準のため略語も許可 |
| etf  | exchange_traded_fund | 金融業界標準のため略語も許可 |

## 段階的移行計画

### Phase 1: 定数の統一 (即座に実行可能)
- グローバル変数を UPPER_CASE 定数に変更
- `test_mode` → `TEST_MODE`
- `test_datetime` → `TEST_DATETIME`

### Phase 2: タイムゾーン定数の改善 (後方互換性保持)
- `TZ_NY` → `TIMEZONE_NY` または `TIMEZONE.NEW_YORK`
- 段階的移行でエイリアスを維持

### Phase 3: ファイル名の統一 (大規模リファクタリング)
- `orb.py` → `opening_range_breakout.py`
- インポート文の更新が必要

## 実装優先度

1. **高優先度**: 定数の UPPER_CASE 統一
2. **中優先度**: タイムゾーン命名の改善
3. **低優先度**: ファイル名の略語展開

## 自動化ツール

- `naming_convention_analysis.py`: 問題箇所の検出
- `naming_convention_fixer.py`: 自動修正（Phase 1のみ）
- 手動修正: Phase 2, 3 は慎重な手動実装を推奨
"""

    guide_path = PROJECT_ROOT / "naming_convention_guide.md"
    guide_path.write_text(guide_content, encoding='utf-8')
    print(f"📖 命名規則ガイドを作成: {guide_path}")

def main():
    """メイン処理"""
    print("🎯 命名規則統一修正を開始...")
    
    # 1. 現在の問題分析
    issues = analyze_naming_issues()
    
    print(f"\n📊 検出された問題:")
    print(f"  - snake_case vs UPPER_CASE: {len(issues['snake_case_vs_UPPER_CASE'])}件")
    print(f"  - 略語使用: {len(issues['abbreviation_usage'])}件")
    print(f"  - ファイル命名: {len(issues['file_naming'])}件")
    
    # 2. Phase 1: 安全な修正（定数の統一）
    create_phase1_fixes()
    
    # 3. Phase 2: タイムゾーン定数の改善提案
    create_phase2_fixes()
    
    # 4. ガイドライン作成
    create_naming_standards_guide()
    
    print("\n✅ 命名規則統一が完了しました！")
    print("\n📋 実行された修正:")
    print("  ✅ グローバル変数の定数化 (TEST_MODE, TEST_DATETIME)")
    print("  ✅ タイムゾーン定数の改善提案を追加")
    print("  ✅ 命名規則ガイドを作成")
    
    print("\n🚨 手動確認が必要な項目:")
    print("  - test_datetime/test_mode の使用箇所の動作確認")
    print("  - インポート文の更新確認")
    print("  - テストの実行")
    
    print("\n📚 次のステップ:")
    print("  1. naming_convention_guide.md を確認")
    print("  2. 修正されたファイルのテスト実行")
    print("  3. Phase 2, 3 の手動実装を検討")

if __name__ == "__main__":
    main()