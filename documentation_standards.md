# ドキュメント品質標準

## 基本方針

### 言語使用ガイドライン
- **統一言語**: 日本語を基本とする
- **専門用語**: 英語併記を推奨 (例: "取引 (Trading)")
- **コメント**: 日本語で記述
- **変数名・関数名**: 英語 (snake_case)

### ドキュメント構造標準

#### 関数のドキュメント
```python
def calculate_position_size(symbol: str, account_value: float, risk_ratio: float = 0.02) -> float:
    """
    ポジションサイズを計算
    
    リスク管理に基づいて適切なポジションサイズを算出します。
    アカウント価値の一定割合をリスクとして設定し、ストップロス幅から
    ポジションサイズを決定します。
    
    Args:
        symbol (str): 取引銘柄シンボル
        account_value (float): アカウント総価値
        risk_ratio (float, optional): リスク比率. Defaults to 0.02 (2%).
    
    Returns:
        float: 計算されたポジションサイズ（株数）
    
    Raises:
        ValueError: symbol が無効な場合
        ZeroDivisionError: ストップロス幅が0の場合
    
    Example:
        >>> position_size = calculate_position_size("AAPL", 100000, 0.02)
        >>> print(f"Position size: {position_size}")
        Position size: 500.0
    
    Note:
        最小ポジションサイズは1株、最大はアカウント価値の50%に制限されます。
    """
```

#### クラスのドキュメント
```python
class TradingStrategy:
    """
    取引戦略の基底クラス
    
    全ての取引戦略クラスが継承すべき抽象基底クラスです。
    共通の取引ロジックと設定管理機能を提供し、
    具体的な戦略実装のためのインターフェースを定義します。
    
    Attributes:
        config (TradingConfig): 取引設定
        logger (Logger): ログ出力インスタンス
        is_active (bool): 戦略の有効状態
    
    Example:
        >>> class ORBStrategy(TradingStrategy):
        ...     def execute(self, symbol: str) -> bool:
        ...         return super().execute(symbol)
    """
```

## 品質基準

### 必須要素 (Required)
- [ ] **概要説明**: 機能の目的と動作を1-2文で説明
- [ ] **Args**: 全パラメータの型と説明
- [ ] **Returns**: 戻り値の型と意味
- [ ] **日本語記述**: 統一された日本語での説明

### 推奨要素 (Recommended)  
- [ ] **Raises**: 発生可能な例外
- [ ] **Example**: 使用例
- [ ] **Note**: 重要な注意事項
- [ ] **詳細説明**: アルゴリズムやビジネスロジックの説明

### 高品質要素 (High Quality)
- [ ] **背景説明**: なぜこの機能が必要か
- [ ] **制限事項**: 使用上の制約
- [ ] **関連機能**: 関連する他の機能への参照
- [ ] **性能特性**: 計算量やメモリ使用量

## ドキュメント品質評価基準

### スコア計算 (10点満点)
- **基本説明** (2点): 20文字以上の説明
- **複数行** (1点): 構造化された説明
- **Args記載** (2点): 全パラメータの説明
- **Returns記載** (2点): 戻り値の説明
- **例外記載** (1点): Raises セクション
- **使用例** (1点): Example セクション
- **構造化** (1点): 適切なフォーマット

### 品質レベル
- **優秀** (8-10点): 完全なドキュメント
- **良好** (6-7点): 基本要素を満たす
- **改善必要** (4-5点): 最低限の説明のみ
- **不十分** (0-3点): ドキュメント不足

## よくある問題と解決策

### 1. 言語混在
```python
# ❌ 悪い例
def get_data():
    """データを取得する function that fetches market data"""

# ✅ 良い例  
def get_data():
    """マーケットデータを取得"""
```

### 2. Args不足
```python
# ❌ 悪い例
def calculate(price, qty):
    """計算を実行"""

# ✅ 良い例
def calculate(price: float, qty: int) -> float:
    """
    取引金額を計算
    
    Args:
        price (float): 株価
        qty (int): 数量
    
    Returns:
        float: 合計金額
    """
```

### 3. 戻り値説明不足
```python
# ❌ 悪い例  
def is_valid():
    """妥当性をチェック"""
    return True

# ✅ 良い例
def is_valid() -> bool:
    """
    データの妥当性をチェック
    
    Returns:
        bool: 妥当な場合True、そうでなければFalse
    """
    return True
```

## 実装ガイドライン

### 段階的改善アプローチ
1. **Phase 1**: 未記載ドキュメントの追加
2. **Phase 2**: 言語統一 (日本語への統一)
3. **Phase 3**: Args/Returns の完全記載
4. **Phase 4**: 使用例と詳細説明の追加

### 自動化ツール
- `documentation_analyzer.py`: 品質分析
- `docstring_formatter.py`: 自動フォーマット
- `translation_helper.py`: 英語→日本語変換支援

### レビューチェックリスト
- [ ] 日本語で統一されているか
- [ ] 全パラメータが説明されているか  
- [ ] 戻り値の意味が明確か
- [ ] 例外処理が説明されているか
- [ ] 使用例が適切か
- [ ] 専門用語が適切に説明されているか
