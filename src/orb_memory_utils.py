"""
ORB取引のメモリ効率化ユーティリティ
テストモードでの大量データ処理を最適化
"""

import pandas as pd
from logging_config import get_logger
import gc

logger = get_logger(__name__)


def _get_test_bars_5min(symbol: str, start_date: str, end_date: str, bars_5min: pd.DataFrame) -> pd.DataFrame:
    """
    テストモード用の5分足データを効率的に取得
    
    Args:
        symbol: 銘柄シンボル
        start_date: 開始日
        end_date: 終了日
        bars_5min: 事前に読み込まれた5分足データ
        
    Returns:
        フィルタリングされた5分足データ
    """
    try:
        if bars_5min is None or bars_5min.empty:
            logger.warning(f"No 5min bars data available for {symbol}")
            return pd.DataFrame()
        
        # 日付範囲でフィルタリング（メモリ効率を考慮）
        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date)
        
        # インデックスが日時の場合の処理
        if isinstance(bars_5min.index, pd.DatetimeIndex):
            filtered_bars = bars_5min[(bars_5min.index >= start_timestamp) & 
                                      (bars_5min.index <= end_timestamp)].copy()
        else:
            # タイムスタンプ列がある場合の処理
            if 'timestamp' in bars_5min.columns:
                filtered_bars = bars_5min[(bars_5min['timestamp'] >= start_timestamp) & 
                                          (bars_5min['timestamp'] <= end_timestamp)].copy()
            else:
                # フォールバック: 全データを返す
                filtered_bars = bars_5min.copy()
        
        logger.debug(f"Filtered 5min bars for {symbol}: {len(filtered_bars)} records")
        return filtered_bars
        
    except Exception as e:
        logger.error(f"Error filtering 5min bars for {symbol}: {e}")
        return pd.DataFrame()


def cleanup_large_dataframes(*dataframes):
    """
    大きなDataFrameのメモリを明示的にクリーンアップ
    
    Args:
        dataframes: クリーンアップするDataFrameのリスト
    """
    try:
        for df in dataframes:
            if isinstance(df, pd.DataFrame) and not df.empty:
                # DataFrameのメモリ使用量をログ出力
                memory_usage = df.memory_usage(deep=True).sum() / 1024 / 1024  # MB
                if memory_usage > 10:  # 10MB以上の場合のみログ出力
                    logger.info(f"Cleaning up DataFrame: {memory_usage:.2f} MB")
                
                # 明示的にメモリを解放
                del df
        
        # ガベージコレクションを強制実行
        gc.collect()
        
    except Exception as e:
        logger.error(f"Error during DataFrame cleanup: {e}")


def get_memory_usage_info() -> dict:
    """
    現在のメモリ使用量情報を取得
    
    Returns:
        メモリ使用量の辞書
    """
    try:
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        
        return {
            'rss_mb': memory_info.rss / 1024 / 1024,  # 物理メモリ使用量
            'vms_mb': memory_info.vms / 1024 / 1024,  # 仮想メモリ使用量
            'percent': process.memory_percent()       # メモリ使用率
        }
    except ImportError:
        logger.warning("psutil not available - memory monitoring disabled")
        return {}
    except Exception as e:
        logger.error(f"Error getting memory usage: {e}")
        return {}


def log_memory_if_high(threshold_mb: float = 500):
    """
    メモリ使用量が閾値を超えた場合にログ出力
    
    Args:
        threshold_mb: 警告を出すメモリ使用量の閾値（MB）
    """
    try:
        memory_info = get_memory_usage_info()
        if memory_info and memory_info.get('rss_mb', 0) > threshold_mb:
            logger.warning(f"High memory usage detected: {memory_info['rss_mb']:.2f} MB "
                          f"({memory_info['percent']:.1f}%)")
    except Exception as e:
        logger.error(f"Error checking memory usage: {e}")