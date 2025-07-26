# テストスイート

この取引システムの包括的なテストスイートです。

## 構造

```
tests/
├── unit/                   # ユニットテスト
│   ├── test_api_clients.py        # APIクライアントのテスト
│   ├── test_earnings_swing.py     # 決算スイング戦略のテスト
│   ├── test_uptrend_stocks.py     # 上昇トレンド分析のテスト
│   ├── test_risk_management.py    # リスク管理のテスト
│   └── test_strategy_allocation.py # 戦略配分のテスト
├── integration/            # 統合テスト
│   ├── test_api_integration.py    # API統合テスト
│   └── test_trading_workflow.py   # 取引ワークフローテスト
├── conftest.py            # Pytest設定とフィクスチャ
└── README.md              # このファイル
```

## テストの実行

### 全てのテストを実行
```bash
pytest
```

### ユニットテストのみ実行
```bash
pytest tests/unit/
```

### 統合テストのみ実行
```bash
pytest tests/integration/
```

### 特定のテストファイルを実行
```bash
pytest tests/unit/test_api_clients.py
```

### 特定のテストクラスを実行
```bash
pytest tests/unit/test_api_clients.py::TestAlpacaClient
```

### 特定のテスト関数を実行
```bash
pytest tests/unit/test_api_clients.py::TestAlpacaClient::test_init_live_account
```

### マーカーでフィルタリング
```bash
# ユニットテストのみ
pytest -m unit

# 統合テストのみ  
pytest -m integration

# APIテストを除外
pytest -m "not api"
```

## テストカバレッジ

テストカバレッジを確認する場合：

```bash
# カバレッジ付きでテスト実行
pytest --cov=src --cov-report=html --cov-report=term-missing

# HTMLレポートを開く
open htmlcov/index.html
```

## テストデータとモック

### 環境変数のモック
全てのテストで`mock_env_vars`フィクスチャを使用して、必要な環境変数をモックしています。

### APIレスポンスのモック
- `mock_finviz_response`: Finvizスクリーナーのレスポンス
- `mock_fmp_response`: FMP APIのレスポンス
- `mock_alpaca_api`: Alpaca APIのモック

### サンプルデータ
- `sample_stock_data`: 株価データのサンプル

## テストのベストプラクティス

### ユニットテスト
- 各関数・メソッドを独立してテスト
- 外部依存をモックで置き換え
- エラーケースも含めてテスト

### 統合テスト
- 複数のコンポーネント間の連携をテスト
- 実際のAPIコールはモックし、データフローを検証
- エンドツーエンドのワークフローをテスト

### モック戦略
- 外部API呼び出しは常にモック
- ファイルI/Oもモックで置き換え
- 時間に依存する処理は固定値を使用

## 新しいテストの追加

### ユニットテスト追加の手順
1. `tests/unit/`に適切なテストファイルを作成
2. テストクラスを`Test`で開始
3. テストメソッドを`test_`で開始
4. 必要なフィクスチャを使用
5. アサーションで期待値を検証

### 統合テスト追加の手順
1. `tests/integration/`にテストファイルを作成
2. `@pytest.mark.integration`マーカーを追加
3. 複数コンポーネントの連携をテスト
4. リアルなデータフローを模擬

## 注意事項

- テストは本番環境のAPIを呼び出さない
- 実際のファイルを変更しない
- テスト用の環境変数を使用
- テスト実行時間を最小限に抑制

## 依存関係

テスト実行に必要なパッケージ：
- pytest
- pytest-cov (カバレッジレポート用)
- pandas
- requests
- python-dotenv

## CI/CD

GitHub Actionsやその他のCI/CDパイプラインでテストを自動実行する場合：

```yaml
# .github/workflows/test.yml の例
- name: Run tests
  run: |
    pytest --cov=src --cov-report=xml
    
- name: Upload coverage
  uses: codecov/codecov-action@v1
```