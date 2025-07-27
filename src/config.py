"""
設定管理モジュール
マジックナンバーや設定値を一元管理
"""

import os
from dataclasses import dataclass
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TradingConfig:
    """取引関連の設定"""
    # ストップロス関連
    MAX_STOP_RATE: float = 0.06  # 最大ストップ率 6%
    STOP_PROFIT_THRESHOLD: float = 0.12  # 利益確保のための閾値 12%
    UPTREND_THRESHOLD: float = 0.25  # アップトレンド閾値
    
    # ポジション管理
    POSITION_SIZE_RATE: float = 0.06  # ポジションサイズの基準 6%
    POSITION_DIVIDER: int = 5  # ポジション分割数
    
    # EMAベースのトレード
    EMA_PERIOD_SHORT: int = 21  # 短期EMA期間
    EMA_PERIOD_LONG: int = 200  # 長期EMA期間
    EMA_LOOKBACK_MULTIPLIER: int = 5  # EMA計算用のデータ取得期間乗数
    
    # 価格変動関連
    PRICE_CHANGE_THRESHOLD: float = 0.02  # 価格変動閾値 2%
    CROSSED_BELOW_EMA_THRESHOLD: float = 0.02  # EMA下抜け判定閾値 2%
    CROSSED_BELOW_EMA_DAYS: int = 2  # EMA下抜け判定日数
    
    # ORB設定
    ORB_LIMIT_RATE: float = 0.006
    ORB_SLIPAGE_RATE: float = 0.003
    ORB_STOP_RATE_1: float = 0.06    # 1st order stop rate
    ORB_PROFIT_RATE_1: float = 0.06  # 1st order profit rate
    ORB_STOP_RATE_2: float = 0.06    # 2nd order stop rate
    ORB_PROFIT_RATE_2: float = 0.12  # 2nd order profit rate
    ORB_STOP_RATE_3: float = 0.06    # 3rd order stop rate
    ORB_PROFIT_RATE_3: float = 0.30  # 3rd order profit rate
    ORB_ENTRY_PERIOD: int = 120      # Entry period in minutes
    
    # Trend Reversion設定
    TREND_REVERSION_NUMBER_STOCKS: int = 20
    TREND_REVERSION_LIMIT_RATE: float = 0.005
    TREND_REVERSION_STOP_RATE: float = 0.08   # 8% stop
    TREND_REVERSION_PROFIT_RATE: float = 0.40 # 40% profit
    
    # Relative Volume Trade設定
    RELATIVE_VOLUME_NUMBER_OF_STOCKS: int = 4
    RELATIVE_VOLUME_MINUTES_FROM_OPEN: int = 2


@dataclass
class TimingConfig:
    """時間関連の設定"""
    # 市場開始・終了関連
    DEFAULT_MINUTES_TO_OPEN: int = 2  # 市場開始前の待機時間（分）
    DEFAULT_MINUTES_TO_CLOSE: int = 1  # 市場終了前の待機時間（分）
    CLOSING_TIME_BUFFER: int = 2  # 終了時間のバッファ（分）
    DATA_LOOKBACK_MINUTES: int = 60  # データ取得時の遡り時間（分）
    
    # スリープ時間
    TEST_MODE_SLEEP: float = 1  # テストモード時のスリープ時間（秒）
    PRODUCTION_SLEEP_MINUTE: int = 60  # 本番モード時の分間隔スリープ（秒）
    PRODUCTION_SLEEP_SHORT: int = 1  # 本番モード時の短いスリープ（秒）
    PRODUCTION_SLEEP_MEDIUM: int = 30  # 本番モード時の中程度スリープ（秒）
    
    # データ取得関連
    DATA_LOOKBACK_DAYS: int = 25  # 株価データ取得の遡り日数
    MIN_TRADING_DAYS: int = 20    # 最小取引日数
    PRICE_CHANGE_PERIOD: int = 20 # 価格変動率計算期間
    HISTORICAL_DATA_MULTIPLIER: int = 400  # 履歴データ取得の日数乗数
    MA_CALCULATION_DAYS: int = 200  # 移動平均計算用の日数


@dataclass  
class RetryConfig:
    """リトライ関連の設定"""
    # API リトライ設定
    ALPACA_MAX_RETRIES: int = 3  # Alpaca APIの最大リトライ回数
    ALPACA_RETRY_DELAY: float = 1.0  # Alpaca APIのリトライ間隔（秒）
    
    # --- FMP API ---
    FMP_MAX_RETRIES: int = 3  # FMP APIの最大リトライ回数
    FMP_RETRY_DELAY: float = 1.0  # FMP APIのリトライ間隔（秒）

    # --- Finviz API ---
    FINVIZ_MAX_RETRIES: int = 5  # Finviz APIの最大リトライ回数
    FINVIZ_RETRY_DELAY: float = 1.0  # Finviz APIのリトライ間隔（秒）
    
    # 注文リトライ設定
    ORDER_MAX_RETRIES: int = 3  # 注文の最大リトライ回数
    ORDER_RETRY_DELAY: float = 0.5  # 注文リトライの間隔（秒）
    
    # HTTP timeout
    HTTP_TIMEOUT: int = 30  # HTTPリクエストのタイムアウト（秒）
    NEWS_API_TIMEOUT: int = 10  # ニュースAPIのタイムアウト（秒）
    
    # サーキットブレーカー設定
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5  # 失敗回数の閾値
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 60  # 復旧タイムアウト（秒）


@dataclass
class RiskManagementConfig:
    """リスク管理関連の設定"""
    # P&L関連
    PNL_CRITERIA: float = -0.06  # P&L基準 -6%
    PNL_CHECK_PERIOD: int = 30  # P&L確認期間（日）
    PNL_HISTORY_MULTIPLIER: int = 3  # 取引履歴取得期間の乗数

    # レバレッジ制御
    MAX_SWING_LEVERAGE: float = 1.5  # スイング許容最大レバレッジ（1.5倍）
    
    # ログファイル設定
    PNL_LOG_FILE: str = 'pnl_log.json'
    JSON_INDENT: int = 4  # JSONファイルのインデント
    
    # 取引統計
    PAGE_SIZE: int = 100  # APIページサイズ
    PARETO_RATIO: float = 0.2  # パレート比率 20%
    TRADE_VALUE_MULTIPLIER: int = 2  # 取引金額の計算乗数


@dataclass
class ScreeningConfig:
    """スクリーニング関連の設定"""
    # 銘柄数設定
    NUMBER_OF_STOCKS: int = 5  # 取引対象銘柄数
    RELATIVE_VOLUME_STOCKS: int = 4  # 相対出来高での銘柄数
    MAX_SCREENING_RESULTS: int = 20  # スクリーニング結果の最大数
    
    # 出来高・価格基準
    MIN_STOCK_PRICE: int = 10  # 最低株価 $10
    MIN_VOLUME: int = 200  # 最低出来高 200K株
    RELATIVE_VOLUME_THRESHOLD: float = 1.5  # 相対出来高の閾値
    
    # スコアリング基準
    EPS_SURPRISE_THRESHOLDS = [0.05, 0.08, 0.10, 0.30]  # EPS サプライズの閾値
    REVENUE_SURPRISE_THRESHOLDS = [0.02, 0.08, 0.15]  # 売上サプライズの閾値
    PRICE_CHANGE_THRESHOLDS = [0.01, 0.08]  # 株価変動の閾値
    RELATIVE_VOLUME_SCORE_THRESHOLDS = [1.0, 1.5, 2.0]  # 相対出来高スコアの閾値
    
    # ニュース分析
    NEWS_ARTICLE_PERIOD: int = 7  # ニュース記事取得期間（日）
    NEWS_CATEGORY_THRESHOLD: int = 5  # ニュースカテゴリの閾値


@dataclass
class SystemConfig:
    """システム関連の設定"""
    # ログ設定
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024  # ログファイルの最大サイズ 10MB
    LOG_BACKUP_COUNT: int = 5  # ログファイルのバックアップ数
    
    # フォルダ構成
    EARNINGS_FOLDER: str = 'earnings'  # 決算データフォルダ
    CONFIG_FOLDER: str = 'config'  # 設定フォルダ
    LOGS_FOLDER: str = 'logs'  # ログフォルダ
    
    # ファイル実行
    TRADE_LIVE_FILE: str = 'src/orb.py'  # 本番取引ファイル
    TRADE_PAPER_FILE: str = 'src/orb_paper.py'  # ペーパー取引ファイル
    
    # 並列処理設定
    MAX_CONCURRENT_TRADES: int = 3  # 同時実行可能な取引数
    MAX_CONCURRENT_API_CALLS: int = 10  # 最大同時API呼び出し数
    PROCESS_TIMEOUT: int = 1800  # プロセスタイムアウト（秒）30分
    SUBPROCESS_LOG_LEVEL: str = 'INFO'  # サブプロセスのログレベル
    
    # コネクションプール設定
    CONNECTION_POOL_SIZE: int = 10     # コネクションプールサイズ
    CONNECTION_POOL_MAXSIZE: int = 20  # 最大コネクション数
    
    # その他の数値定数
    EXPONENTIAL_BACKOFF_BASE: int = 2  # 指数バックオフの基数
    RATE_LIMIT_STATUS_CODE: int = 429  # レート制限のHTTPステータスコード
    SUCCESS_STATUS_CODE: int = 200  # 成功のHTTPステータスコード


# 設定インスタンスの作成
trading_config = TradingConfig()
timing_config = TimingConfig()
retry_config = RetryConfig()
risk_config = RiskManagementConfig()
screening_config = ScreeningConfig()
system_config = SystemConfig()


def get_config() -> Dict[str, Any]:
    """全設定を辞書形式で取得"""
    return {
        'trading': trading_config,
        'timing': timing_config,
        'retry': retry_config,
        'risk': risk_config,
        'screening': screening_config,
        'system': system_config
    }


def get_account_type() -> str:
    """環境変数からアカウントタイプを取得"""
    return os.getenv('ALPACA_ACCOUNT_TYPE', 'live')


def get_log_level() -> str:
    """環境変数からログレベルを取得"""
    return os.getenv('LOG_LEVEL', 'INFO')