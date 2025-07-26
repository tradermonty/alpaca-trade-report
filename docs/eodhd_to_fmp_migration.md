# EODHD → FMP 移行設計書

## 目的
- 既存コードベースから **EODHD** API への依存を完全に排除し、Financial Modeling Prep (**FMP**) API に統一する。
- 決算カレンダー精度向上・機能拡張と、クレジット制限の緩和を図る。

---

## 影響範囲
| モジュール | 変更概要 |
|-----------|-----------|
| `src/api_clients.py` | `EODHDClient` / `get_eodhd_client` を削除し、`FMPDataFetcher` ラッパー (`get_fmp_client`) を追加。|
| `src/concurrent_data_fetcher.py` | `get_eodhd_client` → `get_fmp_client` へ置換。`_get_historical_data_async` 内のメソッド呼び出し変更。|
| `src/earnings_swing.py` | `get_eodhd_client` インポート削除。`get_mid_small_cap_symbols`, `get_historical_data` を FMP版に置換。|
| `src/fmp_data_fetcher.py` | 追加済み。シングルトン利用のため軽量 wrapper が必要。|
| `src/circuit_breaker.py` | `eodhd_circuit_breaker` → `fmp_circuit_breaker` にリネーム（定数・ログ出力も）。|
| `src/config.py` | `EODHD_*` リトライ設定を `FMP_*` 名にリプレース。|
| **テスト** (`tests/*`) | モック・フィクスチャを EODHD 依存から FMP へ変更。|

> grep による EODHD 参照箇所
> - api_clients.py (定義)
> - concurrent_data_fetcher.py
> - earnings_swing.py
> - circuit_breaker.py
> - config.py
> - その他コメント・ドキュメント

---

## 実装ステップ
1. **api_clients.py**
   - `from fmp_data_fetcher import FMPDataFetcher` を追加。
   - シングルトン関数 `get_fmp_client()` を実装。
   - 既存 `get_eodhd_client` を段階的に `DeprecationWarning` → 削除。

2. **concurrent_data_fetcher.py**
   - 依存注入ポイントを `fmp_client = get_fmp_client()` に変更。
   - `_get_historical_data_async` 呼び出しを `fmp_client.get_historical_price_data()` に。
   - パラメータ互換性の差異を吸収（例: シンボル末尾 `.US` 付与不要）。

3. **earnings_swing.py**
   - `get_mid_small_cap_symbols` : `fmp_client.get_mid_small_cap_symbols()` を使用。
   - `get_historical_data` : `fmp_client.get_historical_price_data()` に。
   - 冒頭の `get_eodhd_client` インポート・変数削除。

4. **circuit_breaker.py**
   - `eodhd_circuit_breaker` を `fmp_circuit_breaker` へ改名。
   - マッピング辞書を更新。

5. **config.py**
   - 以下をリネーム
     ```python
     EODHD_MAX_RETRIES  -> FMP_MAX_RETRIES
     EODHD_RETRY_DELAY  -> FMP_RETRY_DELAY
     ```

6. **環境変数 / .env**
   - `EODHD_API_KEY` を削除 or 非推奨コメント。
   - `FMP_API_KEY` を必須に。

7. **tests/**
   - `get_eodhd_client` モックを `get_fmp_client` に置換。
   - EODHD 固有レスポンス（Components 等）のモックデータを FMP 形式に更新。

8. **ドキュメント更新**
   - `docs/api_integration_documentation.md` を FMP API 使用例に書き換え。
   - README バッジ・使用例修正。

---

## リスク & 移行プラン
| リスク | 対応策 |
|--------|--------|
| メソッド仕様差異によるバグ | `fmp_data_fetcher` に **EODHD と同名メソッド互換層**を実装し、段階的リファクタリング。|
| レートリミット超過 (FMP も 1–3k calls/min) | `FMPDataFetcher` に既に実装済みの 
  レートリミット機構を活用し、呼び出し側ではスリープを削除。|
| API キー漏洩 | `.env` 管理・CI Secrets 登録を徹底。|
| テスト失敗 | 既存テストを `pytest -k "not eodhd"` でスキップ → 対応後復帰。|

---

## タイムライン（案）
| 期限 | 作業 |
|-----|-----|
| Day 0 | 設計書レビュー・承認 |
| Day 1 | api_clients.py シングルトン切り替え・テスト修正 |
| Day 2 | concurrent_data_fetcher / earnings_swing 置換 |
| Day 3 | circuit_breaker / config 移行, テスト全復帰 |
| Day 4 | 不具合修正, ドキュメント最終更新 |

---

## 参考
- FMP API ドキュメント: https://financialmodelingprep.com/developer/docs
- `fmp_data_fetcher.py` 実装例 