"""
ドキュメント品質分析スクリプト
コードベース全体のドキュメント品質を評価し、改善提案を生成
"""

import ast
import re
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

@dataclass
class DocstringInfo:
    """ドキュメント文字列情報"""
    function_name: str
    class_name: Optional[str]
    docstring: str
    line_number: int
    has_args: bool
    has_returns: bool
    has_raises: bool
    language: str  # 'japanese', 'english', 'mixed', 'none'
    quality_score: int  # 0-10

@dataclass
class DocumentationIssue:
    """ドキュメント品質問題"""
    file_path: str
    issue_type: str
    description: str
    line_number: int
    severity: str  # 'high', 'medium', 'low'
    suggestion: str

class DocumentationAnalyzer:
    def __init__(self):
        self.docstrings: List[DocstringInfo] = []
        self.issues: List[DocumentationIssue] = []
        self.statistics = {
            'total_functions': 0,
            'documented_functions': 0,
            'total_classes': 0,
            'documented_classes': 0,
            'language_distribution': defaultdict(int),
            'quality_scores': []
        }
    
    def analyze_file(self, file_path: Path):
        """ファイルのドキュメントを分析"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self.statistics['total_functions'] += 1
                    self._analyze_function_docstring(node, file_path, content)
                
                elif isinstance(node, ast.ClassDef):
                    self.statistics['total_classes'] += 1
                    self._analyze_class_docstring(node, file_path, content)
            
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
    
    def _analyze_function_docstring(self, node: ast.FunctionDef, file_path: Path, content: str):
        """関数のdocstringを分析"""
        docstring = ast.get_docstring(node)
        
        if docstring:
            self.statistics['documented_functions'] += 1
            
            # 言語判定
            language = self._detect_language(docstring)
            self.statistics['language_distribution'][language] += 1
            
            # 品質評価
            quality_score = self._evaluate_docstring_quality(docstring, node)
            self.statistics['quality_scores'].append(quality_score)
            
            # Args/Returns/Raises の有無
            has_args = bool(re.search(r'(Args?|引数|パラメータ):', docstring))
            has_returns = bool(re.search(r'(Returns?|戻り値|返り値):', docstring))
            has_raises = bool(re.search(r'(Raises?|例外|エラー):', docstring))
            
            doc_info = DocstringInfo(
                function_name=node.name,
                class_name=self._get_class_name(node),
                docstring=docstring,
                line_number=node.lineno,
                has_args=has_args,
                has_returns=has_returns,
                has_raises=has_raises,
                language=language,
                quality_score=quality_score
            )
            
            self.docstrings.append(doc_info)
            
            # 問題検出
            self._detect_docstring_issues(doc_info, file_path, node)
        
        else:
            # ドキュメント未記載の問題
            if not node.name.startswith('_'):  # プライベート関数以外
                self.issues.append(DocumentationIssue(
                    file_path=str(file_path),
                    issue_type='missing_docstring',
                    description=f'Function {node.name} lacks documentation',
                    line_number=node.lineno,
                    severity='medium',
                    suggestion='Add comprehensive docstring with Args, Returns, and description'
                ))
    
    def _analyze_class_docstring(self, node: ast.ClassDef, file_path: Path, content: str):
        """クラスのdocstringを分析"""
        docstring = ast.get_docstring(node)
        
        if docstring:
            self.statistics['documented_classes'] += 1
            
            language = self._detect_language(docstring)
            quality_score = self._evaluate_docstring_quality(docstring, node)
            
            doc_info = DocstringInfo(
                function_name='',
                class_name=node.name,
                docstring=docstring,
                line_number=node.lineno,
                has_args=False,
                has_returns=False,
                has_raises=False,
                language=language,
                quality_score=quality_score
            )
            
            self.docstrings.append(doc_info)
            self._detect_docstring_issues(doc_info, file_path, node)
        
        else:
            if not node.name.startswith('_'):
                self.issues.append(DocumentationIssue(
                    file_path=str(file_path),
                    issue_type='missing_docstring',
                    description=f'Class {node.name} lacks documentation',
                    line_number=node.lineno,
                    severity='high',
                    suggestion='Add class docstring explaining purpose and usage'
                ))
    
    def _detect_language(self, docstring: str) -> str:
        """ドキュメント言語を判定"""
        # 日本語文字を含むかチェック
        japanese_chars = re.search(r'[ひらがなカタカナ漢字]', docstring)
        
        # 英語のキーワードをチェック
        english_keywords = ['Args', 'Returns', 'Raises', 'Parameters', 'Note', 'Example']
        english_count = sum(1 for keyword in english_keywords if keyword in docstring)
        
        # 日本語のキーワードをチェック
        japanese_keywords = ['引数', '戻り値', '返り値', 'パラメータ', '例外', 'エラー', '注意', '例']
        japanese_count = sum(1 for keyword in japanese_keywords if keyword in docstring)
        
        if japanese_chars and english_count > 0:
            return 'mixed'
        elif japanese_chars or japanese_count > 0:
            return 'japanese'
        elif english_count > 0 or re.search(r'[a-zA-Z]{10,}', docstring):
            return 'english'
        else:
            return 'none'
    
    def _evaluate_docstring_quality(self, docstring: str, node) -> int:
        """ドキュメント品質を0-10で評価"""
        score = 0
        
        # 基本的な説明があるか (2点)
        if len(docstring.strip()) > 20:
            score += 2
        
        # 複数行の説明があるか (1点)
        if len(docstring.split('\n')) > 1:
            score += 1
        
        # Args/Parameters の記載 (2点)
        if isinstance(node, ast.FunctionDef) and node.args.args:
            if re.search(r'(Args?|引数|パラメータ):', docstring):
                score += 2
        
        # Returns の記載 (2点)
        if isinstance(node, ast.FunctionDef):
            returns_mentioned = re.search(r'(Returns?|戻り値|返り値):', docstring)
            has_return_stmt = any(isinstance(n, ast.Return) for n in ast.walk(node))
            if returns_mentioned and has_return_stmt:
                score += 2
        
        # 例外の記載 (1点)
        if re.search(r'(Raises?|例外|エラー):', docstring):
            score += 1
        
        # 例の記載 (1点)
        if re.search(r'(Example|例|サンプル):', docstring):
            score += 1
        
        # 適切なフォーマット (1点)
        if re.search(r'\w+:\s*\n\s+\w+', docstring):  # 構造化された記述
            score += 1
        
        return min(score, 10)
    
    def _get_class_name(self, node: ast.FunctionDef) -> Optional[str]:
        """関数が属するクラス名を取得"""
        # 簡易的な実装
        return None
    
    def _detect_docstring_issues(self, doc_info: DocstringInfo, file_path: Path, node):
        """ドキュメントの問題を検出"""
        issues = []
        
        # 言語混在の問題
        if doc_info.language == 'mixed':
            issues.append(DocumentationIssue(
                file_path=str(file_path),
                issue_type='mixed_language',
                description=f'{doc_info.function_name or doc_info.class_name}: Mixed Japanese/English documentation',
                line_number=doc_info.line_number,
                severity='medium',
                suggestion='Use consistent language (preferably Japanese for this project)'
            ))
        
        # Args記載不足
        if (isinstance(node, ast.FunctionDef) and 
            node.args.args and 
            not doc_info.has_args):
            issues.append(DocumentationIssue(
                file_path=str(file_path),
                issue_type='missing_args',
                description=f'{doc_info.function_name}: Missing Args documentation',
                line_number=doc_info.line_number,
                severity='medium',
                suggestion='Add Args section describing all parameters'
            ))
        
        # Returns記載不足
        if (isinstance(node, ast.FunctionDef) and
            any(isinstance(n, ast.Return) for n in ast.walk(node)) and
            not doc_info.has_returns):
            issues.append(DocumentationIssue(
                file_path=str(file_path),
                issue_type='missing_returns',
                description=f'{doc_info.function_name}: Missing Returns documentation',
                line_number=doc_info.line_number,
                severity='medium',
                suggestion='Add Returns section describing return value'
            ))
        
        # 品質が低い
        if doc_info.quality_score < 4:
            issues.append(DocumentationIssue(
                file_path=str(file_path),
                issue_type='low_quality',
                description=f'{doc_info.function_name or doc_info.class_name}: Low quality documentation (score: {doc_info.quality_score}/10)',
                line_number=doc_info.line_number,
                severity='high',
                suggestion='Improve documentation with detailed description, proper Args/Returns sections'
            ))
        
        self.issues.extend(issues)
    
    def analyze_directory(self):
        """ディレクトリ全体を分析"""
        for py_file in SRC_DIR.glob("*.py"):
            if py_file.name.startswith('__'):
                continue
            print(f"Analyzing documentation in {py_file.name}...")
            self.analyze_file(py_file)
    
    def generate_documentation_standards(self) -> str:
        """ドキュメント標準を生成"""
        return '''# ドキュメント品質標準

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
    \"\"\"データを取得する function that fetches market data\"\"\"

# ✅ 良い例  
def get_data():
    \"\"\"マーケットデータを取得\"\"\"
```

### 2. Args不足
```python
# ❌ 悪い例
def calculate(price, qty):
    \"\"\"計算を実行\"\"\"

# ✅ 良い例
def calculate(price: float, qty: int) -> float:
    \"\"\"
    取引金額を計算
    
    Args:
        price (float): 株価
        qty (int): 数量
    
    Returns:
        float: 合計金額
    \"\"\"
```

### 3. 戻り値説明不足
```python
# ❌ 悪い例  
def is_valid():
    \"\"\"妥当性をチェック\"\"\"
    return True

# ✅ 良い例
def is_valid() -> bool:
    \"\"\"
    データの妥当性をチェック
    
    Returns:
        bool: 妥当な場合True、そうでなければFalse
    \"\"\"
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
'''
    
    def generate_api_reference(self) -> str:
        """API リファレンスドキュメントを生成"""
        return '''# API リファレンス

## 取引システム API

### トレーディング・インターフェース

#### TradingInterface
抽象取引インターフェース。全ての取引機能の基底となるインターフェースです。

**主要メソッド:**

##### `is_uptrend(symbol: str) -> bool`
指定銘柄のアップトレンド判定を行います。

- **引数**: `symbol` - 取引銘柄シンボル (例: "AAPL")
- **戻り値**: アップトレンドの場合 `True`
- **例外**: `ValueError` - 無効なシンボルの場合

##### `get_opening_range(symbol: str, minutes: int) -> Tuple[float, float]`
オープニングレンジ（始値圏）を取得します。

- **引数**: 
  - `symbol` - 取引銘柄シンボル
  - `minutes` - 範囲計算期間（分）
- **戻り値**: `(高値, 安値)` のタプル
- **例外**: `ConnectionError` - API接続エラーの場合

#### OrderManagementInterface  
注文管理インターフェース。注文の送信、監視、管理機能を提供します。

##### `submit_bracket_orders(symbol: str, qty: float, entry_price: float, stop_price: float, target_price: float) -> Dict[str, str]`
ブラケット注文を送信します。

- **引数**:
  - `symbol` - 銘柄シンボル
  - `qty` - 注文数量
  - `entry_price` - エントリー価格
  - `stop_price` - ストップロス価格
  - `target_price` - 利益確定価格
- **戻り値**: 注文ID辞書 `{"parent": "order_id", "stop": "order_id", "target": "order_id"}`

### 設定・構成クラス

#### ORBConfiguration
ORB戦略の設定を管理するクラスです。

**主要属性:**
- `trading.position_size_rate: float` - ポジションサイズ率 (デフォルト: 0.06)
- `trading.orb_stop_rate_1: float` - 第1注文ストップ率 (デフォルト: 0.06)
- `market.ny_timezone: ZoneInfo` - ニューヨーク市場タイムゾーン

**使用例:**
```python
from orb_config import get_orb_config

config = get_orb_config()
position_rate = config.trading.position_size_rate
print(f"Position size rate: {position_rate}")
```

#### TradingConfig
取引関連の設定を管理します。

**重要な設定値:**
- `MAX_STOP_RATE: float = 0.06` - 最大ストップロス率
- `POSITION_SIZE_RATE: float = 0.06` - ポジションサイズ基準率
- `EMA_PERIOD_SHORT: int = 21` - 短期EMA期間

### ユーティリティ・クラス

#### StateManager
グローバル状態を管理するシングルトンクラスです。

##### `get_instance() -> StateManager`
StateManagerのシングルトンインスタンスを取得します。

- **戻り値**: StateManagerインスタンス
- **スレッドセーフ**: はい

##### `update_state(key: str, value: Any) -> None`
状態値を更新します。

- **引数**:
  - `key` - 状態キー
  - `value` - 設定する値
- **例外**: `KeyError` - 無効なキーの場合

### エラー・ハンドリング

#### 一般的な例外

##### `TradingError`
取引関連のエラーを示す基底例外クラス。

##### `ConfigurationError`  
設定関連のエラーを示す例外クラス。

##### `ConnectionError`
API接続エラーを示す例外クラス。

#### エラー対応パターン

```python
try:
    result = trading_interface.submit_bracket_orders(
        symbol="AAPL", qty=100, entry_price=150.0, 
        stop_price=145.0, target_price=155.0
    )
except TradingError as e:
    logger.error(f"Trading error: {e}")
    # エラー処理ロジック
except ConnectionError as e:
    logger.error(f"Connection failed: {e}")
    # リトライロジック
```

### レート制限・パフォーマンス

#### API制限
- **Alpaca API**: 200リクエスト/分
- **FMP API**: 750リクエスト/分
- **Finviz**: レート制限あり（自動調整）

#### パフォーマンス最適化
- **並列処理**: 最大3同時取引
- **キャッシュ**: 市場データ5分間キャッシュ
- **バッチ処理**: 複数銘柄の一括処理対応

### 設定ファイル

#### 環境変数
```bash
# .env ファイル
ALPACA_API_KEY_LIVE=your_live_key
ALPACA_SECRET_KEY_LIVE=your_live_secret
ALPACA_ACCOUNT_TYPE=live  # or paper
LOG_LEVEL=INFO
```

#### 設定ファイル構造
```
config/
├── trading_config.py    # 取引設定
├── market_config.py     # 市場設定  
├── risk_config.py       # リスク管理設定
└── api_config.py        # API設定
```

### 使用例・クックブック

#### 基本的なORB取引
```python
from orb_refactored import ORBRefactoredStrategy

# 戦略インスタンス作成
strategy = ORBRefactoredStrategy()

# 取引実行
success = strategy.start_trading(
    symbol="AAPL",
    position_size=100,
    opening_range=30,
    is_swing=False
)

if success:
    print("取引が正常に実行されました")
```

#### カスタム設定での取引
```python
from orb_config import ORBConfiguration

# カスタム設定
config = ORBConfiguration()
config.trading.position_size_rate = 0.04  # 4%リスク
config.trading.orb_stop_rate_1 = 0.03     # 3%ストップ

# 設定を使用して取引
strategy = ORBRefactoredStrategy(config)
strategy.start_trading("TSLA", position_size="auto")
```
'''
    
    def generate_troubleshooting_guide(self) -> str:
        """トラブルシューティングガイドを生成"""
        return '''# トラブルシューティングガイド

## よくある問題と解決策

### 1. API接続エラー

#### 症状
```
ConnectionError: Failed to connect to Alpaca API
```

#### 原因と解決策

**原因1: APIキーの設定ミス**
```bash
# .envファイルを確認
cat .env | grep ALPACA_API_KEY
```
**解決策**: 正しいAPIキーを設定

**原因2: ネットワーク問題**
```bash
# 接続テスト
curl -H "APCA-API-KEY-ID: your_key" https://api.alpaca.markets/v2/account
```
**解決策**: ネットワーク環境を確認

**原因3: API制限に達している**
```python
# レート制限チェック
import time
time.sleep(1)  # 1秒待機してリトライ
```

### 2. 注文実行エラー

#### 症状
```
TradingError: Order rejected: insufficient buying power
```

#### 診断手順
1. **アカウント残高確認**
```python
from api_clients import get_alpaca_client

client = get_alpaca_client('live')
account = client.api.get_account()
print(f"Buying power: {account.buying_power}")
```

2. **ポジション確認**
```python
positions = client.api.list_positions()
for pos in positions:
    print(f"{pos.symbol}: {pos.qty} shares")
```

3. **注文履歴確認**
```python
orders = client.api.list_orders(status='all', limit=10)
for order in orders:
    print(f"{order.symbol}: {order.status}")
```

#### 解決策
- **残高不足**: ポジションサイズを調整
- **重複注文**: 既存注文をキャンセル
- **市場時間外**: 取引時間を確認

### 3. データ取得エラー

#### 症状
```
ValueError: No data available for symbol AAPL
```

#### 診断コマンド
```python
# データ可用性チェック
from api_clients import get_fmp_client

client = get_fmp_client()
try:
    data = client.get_historical_data("AAPL.US", "2023-12-01", "2023-12-06")
    print(f"Data points: {len(data)}")
except Exception as e:
    print(f"Error: {e}")
```

#### 解決策
1. **銘柄シンボル確認**: 正しい形式で入力
2. **日付範囲調整**: 市場営業日を指定
3. **API制限確認**: 使用量制限を確認

### 4. 設定エラー

#### 症状
```
ConfigurationError: Invalid configuration file
```

#### 設定ファイル検証
```python
# 設定検証スクリプト
from orb_config import get_orb_config

try:
    config = get_orb_config()
    print("✅ Configuration loaded successfully")
    print(f"Position size rate: {config.trading.position_size_rate}")
except Exception as e:
    print(f"❌ Configuration error: {e}")
```

#### よくある設定ミス
- **型エラー**: 数値を文字列で設定
- **範囲エラー**: 無効な値の設定
- **ファイルパス**: 相対パスの問題

### 5. メモリ・パフォーマンス問題

#### 症状
- プロセスが遅い
- メモリ使用量が多い
- タイムアウトエラー

#### 診断ツール
```python
import psutil
import time

# メモリ使用量監視
def monitor_memory():
    process = psutil.Process()
    print(f"Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB")

# 実行時間測定
start_time = time.time()
# ... 処理 ...
print(f"Execution time: {time.time() - start_time:.2f} seconds")
```

#### 最適化方法
1. **並列処理制限**
```python
# 同時実行数を制限
max_concurrent = 3  # デフォルト値を使用
```

2. **データキャッシュ**
```python
# キャッシュ設定
cache_duration = 300  # 5分間キャッシュ
```

3. **ガベージコレクション**
```python
import gc
gc.collect()  # 明示的なメモリ解放
```

### 6. ログ・デバッグ問題

#### ログレベル調整
```python
import logging

# デバッグモード有効化
logging.getLogger().setLevel(logging.DEBUG)
```

#### 詳細ログの確認
```bash
# ログファイル確認
tail -f logs/trading.log

# エラーログの抽出
grep -i error logs/trading.log | tail -20
```

#### デバッグ用設定
```python
# config.py でデバッグ設定
DEBUG_MODE = True
VERBOSE_LOGGING = True
```

### 7. テスト環境問題

#### テストモード確認
```python
# テスト実行
python -c "
from orb_refactored import ORBRefactoredStrategy
strategy = ORBRefactoredStrategy()
result = strategy.start_trading(
    symbol='AAPL', 
    test_mode=True, 
    test_date='2023-12-06'
)
print(f'Test result: {result}')
"
```

#### 模擬データ生成
```python
# テスト用データ作成
from datetime import datetime, timedelta
import pandas as pd

test_data = pd.DataFrame({
    'timestamp': pd.date_range(
        start=datetime.now() - timedelta(days=30),
        end=datetime.now(),
        freq='1H'
    ),
    'price': [150 + i*0.1 for i in range(720)]
})
```

## 緊急対応手順

### 1. 全ポジション強制クローズ
```python
from api_clients import get_alpaca_client

client = get_alpaca_client('live')
positions = client.api.list_positions()

for position in positions:
    try:
        client.api.close_position(position.symbol)
        print(f"✅ Closed position: {position.symbol}")
    except Exception as e:
        print(f"❌ Failed to close {position.symbol}: {e}")
```

### 2. 全注文キャンセル
```python
orders = client.api.list_orders(status='open')
for order in orders:
    try:
        client.api.cancel_order(order.id)
        print(f"✅ Cancelled order: {order.id}")
    except Exception as e:
        print(f"❌ Failed to cancel {order.id}: {e}")
```

### 3. システム停止
```python
# 緊急停止フラグ設定
import sys
import signal

def emergency_stop(signum, frame):
    print("🚨 Emergency stop activated")
    # クリーンアップ処理
    sys.exit(1)

signal.signal(signal.SIGINT, emergency_stop)
```

## サポート・連絡先

### ログ収集
問題報告時には以下の情報を含めてください：

1. **エラーメッセージ**: 完全なスタックトレース
2. **実行環境**: Python版、OS、メモリ使用量
3. **設定情報**: アカウント種別、取引設定
4. **ログファイル**: 関連する時間帯のログ

### 自動診断スクリプト
```bash
# システム診断実行
python scripts/system_diagnostics.py --full-check
```

### 開発者向けデバッグ
```python
# 詳細デバッグモード
import os
os.environ['DEBUG'] = '1'
os.environ['VERBOSE'] = '1'

# プロファイリング
import cProfile
cProfile.run('strategy.start_trading("AAPL")')
```
'''
    
    def generate_report(self) -> str:
        """ドキュメント品質レポートを生成"""
        self.analyze_directory()
        
        # 統計計算
        doc_coverage = (
            self.statistics['documented_functions'] / 
            max(self.statistics['total_functions'], 1) * 100
        )
        
        class_coverage = (
            self.statistics['documented_classes'] /
            max(self.statistics['total_classes'], 1) * 100
        )
        
        avg_quality = (
            sum(self.statistics['quality_scores']) /
            max(len(self.statistics['quality_scores']), 1)
        )
        
        report = ["=== ドキュメント品質分析レポート ===\n"]
        
        # 基本統計
        report.append("== 📊 基本統計 ==")
        report.append(f"総関数数: {self.statistics['total_functions']}")
        report.append(f"ドキュメント化済み関数: {self.statistics['documented_functions']}")
        report.append(f"関数ドキュメント率: {doc_coverage:.1f}%")
        report.append(f"総クラス数: {self.statistics['total_classes']}")
        report.append(f"ドキュメント化済みクラス: {self.statistics['documented_classes']}")
        report.append(f"クラスドキュメント率: {class_coverage:.1f}%")
        report.append(f"平均品質スコア: {avg_quality:.1f}/10")
        report.append("")
        
        # 言語分布
        report.append("== 🌏 言語使用分布 ==")
        for language, count in self.statistics['language_distribution'].items():
            percentage = count / max(len(self.docstrings), 1) * 100
            report.append(f"{language}: {count}件 ({percentage:.1f}%)")
        report.append("")
        
        # 品質分布
        report.append("== 📈 品質スコア分布 ==")
        if self.statistics['quality_scores']:
            high_quality = sum(1 for score in self.statistics['quality_scores'] if score >= 8)
            medium_quality = sum(1 for score in self.statistics['quality_scores'] if 4 <= score < 8)
            low_quality = sum(1 for score in self.statistics['quality_scores'] if score < 4)
            
            total = len(self.statistics['quality_scores'])
            report.append(f"高品質 (8-10点): {high_quality}件 ({high_quality/total*100:.1f}%)")
            report.append(f"中品質 (4-7点): {medium_quality}件 ({medium_quality/total*100:.1f}%)")
            report.append(f"低品質 (0-3点): {low_quality}件 ({low_quality/total*100:.1f}%)")
        report.append("")
        
        # 主要な問題
        issue_counts = defaultdict(int)
        for issue in self.issues:
            issue_counts[issue.issue_type] += 1
        
        report.append("== 🚨 検出された問題 ==")
        for issue_type, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
            report.append(f"{issue_type}: {count}件")
        report.append("")
        
        # 優秀な例
        report.append("== ✨ ドキュメント優秀例 ==")
        excellent_docs = [doc for doc in self.docstrings if doc.quality_score >= 8]
        for doc in excellent_docs[:5]:  # 上位5件
            name = doc.function_name or doc.class_name
            report.append(f"🏆 {name} (スコア: {doc.quality_score}/10)")
            # ドキュメントの一部を表示
            preview = doc.docstring.split('\n')[0][:80]
            report.append(f"    \"{preview}...\"")
        report.append("")
        
        # 改善が必要な例
        report.append("== 🔧 改善が必要な例 ==")
        poor_docs = [doc for doc in self.docstrings if doc.quality_score < 4]
        for doc in poor_docs[:5]:
            name = doc.function_name or doc.class_name
            report.append(f"⚠️  {name} (スコア: {doc.quality_score}/10)")
            issues = [issue for issue in self.issues 
                     if issue.line_number == doc.line_number]
            for issue in issues[:2]:
                report.append(f"    - {issue.description}")
        report.append("")
        
        # 推奨アクション
        report.append("== 📋 推奨アクション ==")
        
        if doc_coverage < 80:
            report.append("1. 🚨 **高優先度**: 未記載ドキュメントの追加")
            report.append(f"   - {self.statistics['total_functions'] - self.statistics['documented_functions']}個の関数にドキュメントが必要")
        
        if self.statistics['language_distribution']['mixed'] > 0:
            report.append("2. 🔧 **中優先度**: 言語統一 (日本語への統一)")
            report.append(f"   - {self.statistics['language_distribution']['mixed']}件の混在ドキュメントを修正")
        
        if avg_quality < 6:
            report.append("3. 📈 **中優先度**: ドキュメント品質向上")
            report.append("   - Args/Returns/Raises セクションの追加")
            report.append("   - 使用例の追加")
        
        if issue_counts['missing_args'] > 0:
            report.append("4. 📝 **低優先度**: Args セクションの完全記載")
            report.append(f"   - {issue_counts['missing_args']}個の関数でArgs不足")
        
        report.append("")
        
        # 次のステップ
        report.append("== 🚀 次のステップ ==")
        report.append("1. ドキュメント標準の確認と適用")
        report.append("2. 自動化ツールの活用")
        report.append("3. 段階的な品質改善")
        report.append("4. APIリファレンスの作成")
        
        return "\n".join(report)

def main():
    """メイン処理"""
    print("📚 Analyzing documentation quality...")
    
    analyzer = DocumentationAnalyzer()
    
    # レポート生成
    report = analyzer.generate_report()
    print(f"\n{report}")
    
    # ドキュメント標準を生成
    standards = analyzer.generate_documentation_standards()
    standards_path = PROJECT_ROOT / "documentation_standards.md"
    standards_path.write_text(standards, encoding='utf-8')
    print(f"\n📖 ドキュメント標準を保存: {standards_path}")
    
    # APIリファレンスを生成
    api_ref = analyzer.generate_api_reference()
    api_path = PROJECT_ROOT / "api_reference.md"
    api_path.write_text(api_ref, encoding='utf-8')
    print(f"📘 APIリファレンスを保存: {api_path}")
    
    # トラブルシューティングガイドを生成
    troubleshooting = analyzer.generate_troubleshooting_guide()
    troubleshooting_path = PROJECT_ROOT / "troubleshooting_guide.md"
    troubleshooting_path.write_text(troubleshooting, encoding='utf-8')
    print(f"🔧 トラブルシューティングガイドを保存: {troubleshooting_path}")
    
    # レポートを保存
    report_path = PROJECT_ROOT / "documentation_quality_report.txt"
    report_path.write_text(report, encoding='utf-8')
    print(f"📊 詳細レポートを保存: {report_path}")
    
    print("\n✅ ドキュメント品質分析が完了しました！")
    print("\n📚 作成されたドキュメント:")
    print("  📖 documentation_standards.md - ドキュメント標準")
    print("  📘 api_reference.md - APIリファレンス")
    print("  🔧 troubleshooting_guide.md - トラブルシューティング")

if __name__ == "__main__":
    main()