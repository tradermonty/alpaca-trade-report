"""
共通定数定義モジュール
重複コードを排除し、一元管理する
"""

import os
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TimeZoneConfig:
    """タイムゾーン設定"""
    NY: ZoneInfo = ZoneInfo("US/Eastern")
    UTC: ZoneInfo = ZoneInfo("UTC")
    TOKYO: ZoneInfo = ZoneInfo("Asia/Tokyo")
    LONDON: ZoneInfo = ZoneInfo("Europe/London")


@dataclass
class AccountConfig:
    """アカウント設定"""
    # デフォルトアカウントタイプ（環境変数から取得可能）
    DEFAULT_ACCOUNT: str = os.getenv('DEFAULT_ALPACA_ACCOUNT', 'live')
    
    # 利用可能なアカウントタイプ
    LIVE: str = 'live'
    PAPER: str = 'paper'
    PAPER_SHORT: str = 'paper_short'
    PAPER2: str = 'paper2'
    
    @classmethod
    def get_account_type(cls, override: Optional[str] = None) -> str:
        """
        アカウントタイプを取得
        
        Args:
            override: 環境変数を上書きする値
            
        Returns:
            アカウントタイプ文字列
        """
        if override:
            return override
        
        # 環境変数から取得
        env_account = os.getenv('ALPACA_ACCOUNT_TYPE')
        if env_account:
            return env_account
            
        # デフォルト値を返す
        return cls.DEFAULT_ACCOUNT


@dataclass
class MarketHours:
    """マーケット時間設定"""
    # NYSE標準取引時間（東部時間）
    MARKET_OPEN_TIME: str = "09:30:00"
    MARKET_CLOSE_TIME: str = "16:00:00"
    PRE_MARKET_START: str = "04:00:00"
    AFTER_MARKET_END: str = "20:00:00"
    
    # 特殊な時間設定
    OPEN_TIME_BUFFER: str = "09:30:01"  # オープン後1秒
    CLOSE_TIME_BUFFER: int = 10  # クローズ前バッファ（分）


@dataclass
class DataPeriods:
    """データ期間設定"""
    # バーデータ期間
    MINUTE_1: str = "1Min"
    MINUTE_5: str = "5Min"
    MINUTE_15: str = "15Min"
    HOUR_1: str = "1Hour"
    DAY_1: str = "1Day"
    
    # データ取得期間
    LOOKBACK_DAYS_SHORT: int = 10
    LOOKBACK_DAYS_MEDIUM: int = 50
    LOOKBACK_DAYS_LONG: int = 200
    
    # テスト用デフォルト日付
    DEFAULT_TEST_DATE: str = "2023-12-06"


# シングルトンインスタンス
TIMEZONE = TimeZoneConfig()
ACCOUNT = AccountConfig()
MARKET = MarketHours()
PERIODS = DataPeriods()


# 後方互換性のための変数（非推奨、将来的に削除予定）
TZ_NY = TIMEZONE.NY
TZ_UTC = TIMEZONE.UTC
ALPACA_ACCOUNT = ACCOUNT.get_account_type()


def update_account_type(account_type: str):
    """
    アカウントタイプを動的に更新（テスト用）
    
    Args:
        account_type: 新しいアカウントタイプ
    """
    global ALPACA_ACCOUNT
    if account_type in [ACCOUNT.LIVE, ACCOUNT.PAPER, ACCOUNT.PAPER_SHORT, ACCOUNT.PAPER2]:
        ALPACA_ACCOUNT = account_type
        os.environ['ALPACA_ACCOUNT_TYPE'] = account_type
    else:
        raise ValueError(f"Invalid account type: {account_type}")


# 使用例とマイグレーションガイド
"""
=== Before (重複コード) ===
# 各ファイルで個別に定義
TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo("UTC")
ALPACA_ACCOUNT = 'live'

=== After (共通定数使用) ===
from common_constants import TIMEZONE, ACCOUNT, MARKET

# 推奨: 明示的な使用
current_time = datetime.now(TIMEZONE.NY)
account_type = ACCOUNT.get_account_type()
market_open = MARKET.MARKET_OPEN_TIME

# 移行期間中の後方互換性
from common_constants import TZ_NY, TZ_UTC, ALPACA_ACCOUNT
current_time = datetime.now(TZ_NY)  # 従来通り動作

=== 環境変数による設定 ===
# .envファイル
DEFAULT_ALPACA_ACCOUNT=paper
ALPACA_ACCOUNT_TYPE=paper

# コード内での動的変更
from common_constants import update_account_type
update_account_type('paper')  # テスト環境への切り替え
"""


if __name__ == "__main__":
    pass

# 命名規則統一の提案:
# 将来的な改善案（後方互換性を保ちながら段階的に移行）

@dataclass
class ImprovedTimeZoneConfig:
    """改善されたタイムゾーン設定（明示的命名）"""
    NEW_YORK: ZoneInfo = ZoneInfo("US/Eastern")
    COORDINATED_UNIVERSAL_TIME: ZoneInfo = ZoneInfo("UTC")
    TOKYO: ZoneInfo = ZoneInfo("Asia/Tokyo")
    LONDON: ZoneInfo = ZoneInfo("Europe/London")

# 段階的移行のためのエイリアス
# IMPROVED_TIMEZONE = ImprovedTimeZoneConfig()

# 使用例:
# current_time = datetime.now(IMPROVED_TIMEZONE.NEW_YORK)  # より明示的
# current_time = datetime.now(TIMEZONE.NY)                 # 現在の方式（短縮形）
