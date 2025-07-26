# 自動株式取引システム (Automated Stock Trading System)

## 概要

このプロジェクトは、Alpaca Trading APIを使用した自動株式取引システムです。決算発表、テクニカル分析、ニュース分析などに基づく複数の取引戦略を実装しています。

## 主要機能

### 取引戦略
- **決算スイング取引** (`earnings_swing.py`) - 決算発表後の価格変動を狙った取引
- **決算ショート取引** (`earnings_swing_short.py`) - 決算後の下落を狙った空売り戦略  
- **出来高ブレイクアウト** (`relative_volume_trade.py`) - 異常出来高での取引
- **オープニングレンジブレイクアウト** (`orb.py`, `orb_short.py`) - 寄り付き後の価格ブレイクアウト戦略
- **トレンド反転戦略** (`trend_reversion_*.py`) - 平均回帰を狙った取引

### 分析ツール
- **ニュース分析** (`news_analysis.py`) - OpenAI APIを使用したニュース感情分析
- **業界パフォーマンス分析** (`industry_performance.py`) - 業界別の株価パフォーマンス追跡
- **セクター分析** (`uptrend_count_sector.py`) - セクター別のトレンド分析

### リスク管理
- **PnL基準チェック** (`risk_management.py`) - 30日間の損益に基づくリスク制御
- **戦略配分** (`strategy_allocation.py`) - 口座残高に基づく動的なポジションサイズ計算
- **高配当銘柄管理** (`dividend_portfolio_management.py`) - 長期保有銘柄の除外リスト

## セットアップ

### 1. 環境構築
```bash
# 仮想環境の作成・有効化
mkvirtualenv alpaca
workon alpaca

# 必要なパッケージのインストール
pip install alpaca-trade-api pandas requests gspread oauth2client python-dotenv openai yfinance
```

### 2. API キーの設定
`.env`ファイルを作成し、以下のAPI キーを設定：

```env
# Alpaca Trading API Keys
ALPACA_API_KEY_LIVE=あなたのライブAPIキー
ALPACA_SECRET_KEY_LIVE=あなたのライブシークレットキー
ALPACA_API_KEY_PAPER=あなたのペーパーAPIキー  
ALPACA_SECRET_KEY_PAPER=あなたのペーパーシークレットキー

# External APIs
FINVIZ_API_KEY=あなたのFinviz Eliteキー
OPENAI_API_KEY=あなたのOpenAI APIキー
ALPHA_VANTAGE_API_KEY=あなたのAlpha Vantageキー
EODHD_API_KEY=あなたのEODHD APIキー
```

### 3. Google Sheets認証
Google Sheets APIの認証ファイルを`config/`ディレクトリに配置してください。

## 使用方法

### 基本的な取引戦略の実行
```bash
# 決算後スイング取引
python src/earnings_swing.py

# 出来高ブレイクアウト取引
python src/relative_volume_trade.py

# 手動でのORB取引
python src/orb.py AAPL --swing True --pos_size 1000
```

### 分析ツールの実行
```bash
# ニュース感情分析
python src/news_analysis.py TSLA

# セクター分析
python src/uptrend_count_sector.py
```

## プロジェクト構造

```
├── src/                        # ソースコード
│   ├── api_clients.py         # API共通クライアント
│   ├── earnings_swing.py      # 決算スイング戦略
│   ├── orb.py                 # ORB取引エンジン
│   ├── risk_management.py     # リスク管理
│   ├── strategy_allocation.py # 戦略配分
│   ├── news_analysis.py       # ニュース分析
│   └── uptrend_stocks.py      # 上昇トレンド銘柄特定
├── config/                     # 認証ファイル
│   └── spreadsheetautomation-*.json
├── docs/                       # 設計ドキュメント
│   ├── earnings_swing_design.md
│   └── orb_design.md
├── reports/                    # 生成されるレポート
└── pnl_log.json               # PnL履歴データ
```

## リスク管理機能

- **30日間PnL監視**: 過去30日間の損益が-6%を下回ると取引を停止
- **動的ポジションサイズ**: 口座残高と戦略配分に基づく自動計算
- **高配当銘柄除外**: 長期保有銘柄との重複を防止

## データソース

- **Alpaca Markets**: 市場データ、取引実行
- **Finviz Elite**: 株式スクリーニング
- **Google Sheets**: 手動取引指示、データ管理
- **OpenAI**: ニュース感情分析
- **Alpha Vantage**: 追加市場データ
- **EODHD**: 時価総額データ

## 注意事項

⚠️ **重要**: このシステムは自動的に実際の取引を行います。使用前に必ず：

1. ペーパートレーディングで十分にテストしてください
2. リスク管理設定を確認してください  
3. API制限と取引コストを理解してください
4. 法的要件と規制を遵守してください

## ライセンス

このプロジェクトは個人使用を目的としています。商用利用前には適切なライセンス確認を行ってください。

## 免責事項

このソフトウェアは投資アドバイスを提供するものではありません。取引には損失のリスクが伴います。使用者の責任でご利用ください。