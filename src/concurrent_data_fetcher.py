"""
株価データ取得の並行処理ユーティリティ
earnings_swing.pyでのパフォーマンスボトルネック解消のための並行API呼び出し実装
"""

import asyncio
import aiohttp
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import requests
from logging_config import get_logger
from config import system_config, timing_config
from api_clients import get_eodhd_client

logger = get_logger(__name__)


async def _get_price_filtered_tickers_concurrent(
    tickers: List[str], 
    start_date: str, 
    end_date: str,
    min_price_change: float = 0.0
) -> List[str]:
    """
    複数銘柄の株価データを並行取得し、価格変動率でフィルタリング
    
    Args:
        tickers: 銘柄リスト
        start_date: 開始日（YYYY-MM-DD）
        end_date: 終了日（YYYY-MM-DD）
        min_price_change: 最小価格変動率（%）
        
    Returns:
        フィルタリング条件を満たす銘柄リスト
    """
    logger.info(f"Starting concurrent price data fetching for {len(tickers)} tickers")
    
    # セマフォでAPI呼び出し数を制限
    semaphore = asyncio.Semaphore(system_config.MAX_CONCURRENT_API_CALLS)
    
    # EODHDクライアントを取得
    eodhd_client = get_eodhd_client()
    
    # 並行処理でデータ取得
    tasks = []
    for ticker in tickers:
        task = _fetch_and_filter_ticker_data(
            semaphore, eodhd_client, ticker, start_date, end_date, min_price_change
        )
        tasks.append(task)
    
    # 全タスクを並行実行
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 成功した銘柄のみを抽出
    filtered_tickers = []
    successful_count = 0
    error_count = 0
    
    for ticker, result in zip(tickers, results):
        if isinstance(result, Exception):
            logger.error(f"Error processing {ticker}: {result}")
            error_count += 1
        elif result is True:  # 条件を満たした場合
            filtered_tickers.append(ticker)
            successful_count += 1
        else:  # 条件を満たさなかった場合
            successful_count += 1
    
    logger.info(f"Concurrent processing completed: {successful_count} successful, "
                f"{error_count} errors, {len(filtered_tickers)} tickers passed filter")
    
    return filtered_tickers


async def _fetch_and_filter_ticker_data(
    semaphore: asyncio.Semaphore,
    eodhd_client,
    ticker: str,
    start_date: str,
    end_date: str,
    min_price_change: float
) -> bool:
    """
    単一銘柄の株価データを取得し、価格変動率をチェック
    
    Args:
        semaphore: 並行数制限用セマフォ
        eodhd_client: EODHDクライアント
        ticker: 銘柄シンボル
        start_date: 開始日
        end_date: 終了日
        min_price_change: 最小価格変動率
        
    Returns:
        フィルタリング条件を満たすかどうか
    """
    async with semaphore:  # 並行数を制限
        try:
            # 非同期でデータ取得（実際の処理は同期的だが、セマフォで制御）
            await asyncio.sleep(0)  # 他のタスクに制御を譲る
            
            # 株価データの取得
            price_data = await _get_historical_data_async(eodhd_client, ticker, start_date, end_date)
            
            if price_data is None or len(price_data) < timing_config.MIN_TRADING_DAYS:
                logger.warning(f"{ticker}: 十分な株価データがありません")
                return False

            # 20日間の価格変動率を計算
            price_change = _calculate_price_change(price_data, timing_config.PRICE_CHANGE_PERIOD)
            logger.debug(f"{ticker}: {timing_config.PRICE_CHANGE_PERIOD}日間の価格変動率 = {price_change:.2f}%")

            # 変動率が条件以上の銘柄のみを対象とする
            if price_change >= min_price_change:
                return True
            else:
                logger.debug(f"{ticker}: 価格変動率が{min_price_change}%未満のため除外")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"{ticker}の株価データ取得中にネットワークエラー: {e}")
            return False
        except pd.errors.EmptyDataError as e:
            logger.error(f"{ticker}の株価データが空です: {e}")
            return False
        except Exception as e:
            logger.error(f"{ticker}の株価データ取得中に予期しないエラー: {e}", exc_info=True)
            return False


async def _get_historical_data_async(eodhd_client, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    非同期で株価データを取得（実際は同期処理だが非同期コンテキスト内で実行）
    
    Args:
        eodhd_client: EODHDクライアント
        symbol: 銘柄シンボル
        start_date: 開始日
        end_date: 終了日
        
    Returns:
        株価データのDataFrame
    """
    try:
        # 実際のデータ取得は同期的だが、非同期コンテキストで実行
        loop = asyncio.get_event_loop()
        price_data = await loop.run_in_executor(
            None, 
            eodhd_client.get_historical_data, 
            f"{symbol}.US", 
            start_date, 
            end_date
        )
        
        if price_data and not price_data.empty:
            return price_data
        else:
            return None
            
    except Exception as e:
        logger.error(f"Error fetching historical data for {symbol}: {e}")
        return None


def _calculate_price_change(df: pd.DataFrame, days: int = 20) -> float:
    """
    指定日数の価格変動率を計算
    
    Args:
        df: 株価データのDataFrame
        days: 計算期間（日数）
        
    Returns:
        価格変動率（%）
    """
    try:
        if len(df) < days:
            return 0.0
            
        # 最新の終値と指定日前の終値を比較
        latest_price = df['Close'].iloc[-1]
        price_n_days_ago = df['Close'].iloc[-days]
        
        return ((latest_price - price_n_days_ago) / price_n_days_ago) * 100
        
    except Exception as e:
        logger.error(f"Error calculating price change: {e}")
        return 0.0


# 従来の同期関数との互換性のためのラッパー
def get_price_filtered_tickers_sync(tickers: List[str], start_date: str, end_date: str) -> List[str]:
    """
    同期的インターフェースで並行処理を実行
    
    Args:
        tickers: 銘柄リスト
        start_date: 開始日
        end_date: 終了日
        
    Returns:
        フィルタリングされた銘柄リスト
    """
    return asyncio.run(_get_price_filtered_tickers_concurrent(tickers, start_date, end_date))