"""
中央集約的なログ設定
すべてのモジュールで統一されたログ設定を使用
"""

import logging
import logging.handlers
import os
from datetime import datetime
from config import system_config


def setup_logging(
    log_level: str = None,
    log_file: str = None,
    log_to_console: bool = True,
    log_to_file: bool = True
):
    """
    プロジェクト全体のログ設定を初期化
    
    Args:
        log_level: ログレベル (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: ログファイルのパス
        log_to_console: コンソールへの出力を有効にするか
        log_to_file: ファイルへの出力を有効にするか
    """
    # 環境変数からログレベルを取得（デフォルトはINFO）
    if log_level is None:
        log_level = os.getenv('LOG_LEVEL', 'INFO')
    
    # ログファイルのパスを設定（デフォルトは logs/app_YYYYMMDD.log）
    if log_file is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"app_{datetime.now().strftime('%Y%m%d')}.log")
    
    # ルートロガーの設定
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 既存のハンドラーをクリア
    root_logger.handlers.clear()
    
    # フォーマッターの設定
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # コンソールハンドラーの設定
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # ファイルハンドラーの設定（ローテーション付き）
    if log_to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=system_config.LOG_FILE_MAX_BYTES,  # 10MB
            backupCount=system_config.LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 外部ライブラリのログレベルを調整
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('alpaca_trade_api').setLevel(logging.WARNING)
    
    # 初期化完了メッセージ
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Level: {log_level}, File: {log_file if log_to_file else 'None'}")


def get_logger(name: str) -> logging.Logger:
    """
    モジュール用のロガーを取得
    
    Args:
        name: モジュール名（通常は __name__）
        
    Returns:
        設定済みのロガー
    """
    return logging.getLogger(name)


# デフォルト設定で初期化
setup_logging()