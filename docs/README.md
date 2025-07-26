# 株式自動取引システム - 技術文書

## 文書構成

本システムの包括的な技術文書は以下のファイルで構成されています：

### 1. [取引戦略詳細](./trading_strategies_documentation.md)
- **5つの主要取引戦略**の詳細な実装解説
- **Earnings Swing Strategy**: 決算後の価格変動を捉える戦略
- **Opening Range Breakout (ORB)**: 市場開始後のブレイクアウト戦略  
- **Trend Reversion Strategy**: 過売り銘柄の反発を狙う逆張り戦略
- **Relative Volume Trade**: 出来高急増銘柄のモメンタム戦略
- **Uptrend Stocks Strategy**: 中長期トレンド継続戦略

### 2. [リスク管理システム](./risk_management_documentation.md)
- **多層防御アプローチ**によるリスク制御
- **PnL基準管理**: 30日ローリング損益による取引制御
- **ポジションサイジング**: 戦略別資金配分とボラティリティ調整
- **相関リスク管理**: セクター集中・銘柄相関の制御
- **ドローダウン制御**: リアルタイム監視と緊急停止機能

### 3. [API統合システム](./api_integration_documentation.md)
- **4つの外部APIの統合**と信頼性保証
- **Alpaca Trading API**: 取引執行・アカウント管理
- **EODHD API**: 市場データ・企業基本情報
- **Finviz Elite API**: 高度な株式スクリーニング
- **Google Sheets API**: 外部制御・監視機能

## システム概要

### アーキテクチャ特徴
- **マイクロサービス型設計**: 各戦略とコンポーネントの独立性
- **サーキットブレーカーパターン**: API障害時の自動フェイルオーバー
- **並行処理**: 複数戦略の同時実行と効率的なリソース利用
- **イベント駆動**: リアルタイム市場データに基づく自動実行

### 技術スタック
- **Python 3.9+**: メイン開発言語
- **Pandas**: データ分析・処理
- **AsyncIO**: 非同期処理・並行実行
- **Alpaca Trade API**: 証券取引API
- **Google Cloud APIs**: 外部統合・監視

### セキュリティ機能
- **環境変数管理**: API認証情報の安全な管理
- **多段階認証**: 重要操作の確認機制
- **監査ログ**: 全取引・操作の完全な記録
- **アクセス制御**: 機能別権限管理

## パフォーマンス指標

### バックテスト結果（参考値）
- **年間リターン**: 15-25% (市場環境による)
- **最大ドローダウン**: <12%
- **シャープレシオ**: 1.2-1.8
- **勝率**: 55-65% (戦略により変動)

### システム性能
- **レイテンシ**: <500ms (注文執行)
- **可用性**: 99.5%+ (API統合含む)
- **同時処理**: 最大20銘柄の並行取引
- **データ処理**: 1日あたり100万件以上の価格データ

## 運用要件

### 最小システム要件
- **CPU**: 4コア以上
- **RAM**: 8GB以上  
- **ストレージ**: 50GB以上（ログ・データ保存用）
- **ネットワーク**: 安定したインターネット接続

### 必要なAPIアクセス
1. **Alpaca Trading Account** (Live + Paper)
2. **EODHD Premium Subscription**
3. **Finviz Elite Membership**  
4. **Google Cloud Platform Account**

### 環境変数設定
```bash
# Trading API
ALPACA_API_KEY_LIVE=your_live_key
ALPACA_SECRET_KEY_LIVE=your_live_secret
ALPACA_API_KEY_PAPER=your_paper_key
ALPACA_SECRET_KEY_PAPER=your_paper_secret

# Data Providers
EODHD_API_KEY=your_eodhd_key
FINVIZ_API_KEY=your_finviz_key

# External Services
GOOGLE_SHEETS_CREDENTIALS_PATH=path/to/credentials.json
GMAIL_APP_PASSWORD=your_app_password
```

## インストール・セットアップ

### 1. 依存関係インストール
```bash
pip install -r requirements.txt
```

### 2. 環境設定
```bash
cp .env.sample .env
# .envファイルにAPIキーを設定
```

### 3. 設定カスタマイズ
```python
# src/config.py で戦略パラメータを調整
trading_config.MAX_STOP_RATE = 0.06  # ストップロス率
trading_config.POSITION_DIVIDER = 5   # ポジション分割数
```

### 4. テスト実行
```bash
python3 run_tests.py  # 基本機能テスト
python3 -m pytest tests/ -v  # 完全テストスイート
```

### 5. 本番稼働
```bash
# 戦略別実行
python3 src/earnings_swing.py       # 決算スイング戦略
python3 src/relative_volume_trade.py # 出来高戦略
python3 src/trend_reversion_stock.py # 逆張り戦略

# 監視・メンテナンス
python3 src/uptrend_stocks.py       # 市場分析・監視
python3 src/risk_management.py      # リスク状況確認
```

## 監視・保守

### 日次チェック項目
- [ ] PnL基準: 30日損益が-6%以内
- [ ] API接続: 全外部サービスの正常動作
- [ ] ポジション: 想定範囲内の建玉数・規模
- [ ] ログ: エラー・警告メッセージの確認

### 週次メンテナンス
- [ ] パフォーマンス分析: 戦略別損益レビュー
- [ ] リスク分析: ドローダウン・相関の検証
- [ ] データ整合性: 取引記録・ログの検証
- [ ] 設定最適化: 市場環境に応じたパラメータ調整

### 月次レビュー
- [ ] 戦略評価: 各戦略のリスク・リターン分析
- [ ] システム最適化: パフォーマンス改善の検討
- [ ] 新機能検討: 市場環境変化への対応
- [ ] セキュリティ監査: アクセスログ・認証状況の確認

## トラブルシューティング

### 一般的な問題と解決策

#### API接続エラー
```bash
# 接続状況確認
python3 -c "from src.api_clients import *; print('APIs OK')"

# サーキットブレーカー状態確認
python3 src/api_health_check.py
```

#### 取引実行エラー  
```bash
# アカウント状態確認
python3 -c "from src.api_clients import get_alpaca_client; print(get_alpaca_client('live').get_account())"

# PnL基準確認
python3 -c "from src.risk_management import check_pnl_criteria; print(check_pnl_criteria())"
```

#### データ取得エラー
```bash
# データソース状態確認
python3 src/data_quality_check.py

# キャッシュクリア
rm -rf .cache/
```

## サポート・コミュニティ

### 開発・改善への貢献
1. **Issue報告**: GitHub Issues での不具合・改善要望報告
2. **Pull Request**: 新機能・修正の提案
3. **文書改善**: 技術文書・README の改善提案
4. **テスト追加**: 新しいテストケース・シナリオの追加

### 免責事項
本システムは教育・研究目的で開発されています。実際の取引には十分な検証とリスク管理が必要です。投資損失については一切の責任を負いません。

---

**最終更新**: 2024年7月
**バージョン**: v2.0
**メンテナンス**: 継続的更新・改善中