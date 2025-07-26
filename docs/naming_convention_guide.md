# 命名規則統一ガイド

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
