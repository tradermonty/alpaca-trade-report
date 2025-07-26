# Python 3.11 仮想環境セットアップ

## 環境情報
- Python: 3.11.12
- 仮想環境: venv
- 場所: `./venv/`

## セットアップ手順

### 1. 仮想環境の作成と有効化
```bash
# 環境作成（初回のみ）
python3.11 -m venv venv

# 環境有効化
source venv/bin/activate
```

### 2. 依存関係のインストール
```bash
# 通常の依存関係
pip install -r requirements.txt

# TA-Lib（テクニカル分析ライブラリ）
brew install ta-lib  # システムライブラリ
pip install TA-Lib   # Pythonパッケージ
```

## インストール済みライブラリ

### 主要ライブラリ
- **Trading APIs**: alpaca-trade-api (3.2.0)
- **Data Analysis**: pandas (2.3.1), numpy (1.26.4)
- **Technical Analysis**: talib (0.6.4), pandas-ta (0.3.14b0)
- **Visualization**: matplotlib (3.10.3), plotly (6.2.0)
- **Google Sheets**: gspread (6.2.1), oauth2client (4.1.3)
- **AI/NLP**: openai (1.97.1)
- **Testing**: pytest (8.4.1), pytest-asyncio, pytest-mock
- **Code Quality**: black (25.1.0), flake8 (7.3.0), mypy (1.17.0)

### バージョン制約の理由
- `numpy>=1.24.0,<2.0.0`: pandas-taとの互換性のため
- `urllib3>=1.25.0,<2.0.0`: alpaca-trade-apiとの互換性のため

## 使用方法

```bash
# 環境有効化
source venv/bin/activate

# スクリプト実行例
python src/earnings_swing.py
python src/risk_management.py --summary

# 環境無効化
deactivate
```

## トラブルシューティング

### TA-Libインストールエラー
```bash
# macOSの場合
brew install ta-lib
pip install TA-Lib
```

### NumPy互換性エラー
pandas-taはNumPy 2.x系と互換性がないため、1.x系を使用。

### 依存関係競合
requirements.txtで適切なバージョン制約を設定済み。

## 環境確認

```bash
source venv/bin/activate
python -c "import pandas_ta, talib, numpy as np; print('All libraries loaded successfully')"
```