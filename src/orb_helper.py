"""
ORB Helper Utilities
リファクタリングされたORBシステムで使用されるヘルパー関数群
"""

import gc
import time
import psutil
import pandas as pd
from typing import Dict, Any, Optional
from logging_config import get_logger
from config import system_config

logger = get_logger(__name__)


def _wait_for_order_cancellation(alpaca_client, order_id: str, max_wait_time: int, delay: float) -> bool:
    """
    注文のキャンセル完了を待機する
    
    Args:
        alpaca_client: Alpacaクライアント
        order_id: 注文ID
        max_wait_time: 最大待機時間
        delay: 待機間隔
        
    Returns:
        bool: キャンセルが完了したかどうか
    """
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            order = alpaca_client.api.get_order(order_id)
            
            # 最終状態の判定
            if order.status in ('canceled', 'filled', 'expired', 'replaced'):
                logger.info(f"Order {order_id} reached final status: {order.status}")
                return True
            elif order.status == 'partially_filled':
                # 部分約定の場合は残り数量の状態を確認
                if order.filled_qty == order.qty:
                    logger.info(f"Order {order_id} fully filled: {order.filled_qty}/{order.qty}")
                    return True
                else:
                    logger.info(f"Order {order_id} partially filled: {order.filled_qty}/{order.qty}")
            elif order.status in ('pending_cancel', 'pending_replace'):
                logger.debug(f"Order {order_id} in transition state: {order.status}")
            else:
                logger.warning(f"Order {order_id} in unexpected state: {order.status}")
                
        except Exception as e:
            logger.error(f"Error checking order {order_id} status: {e}")
            return False
            
        time.sleep(delay)
        
    logger.warning(f"Timeout waiting for order {order_id} cancellation")
    return False


def log_memory_if_high(threshold_percent: float = 80.0) -> bool:
    """
    メモリ使用量が閾値を超えた場合にログ出力
    
    Args:
        threshold_percent: 警告を出すメモリ使用率の閾値
        
    Returns:
        bool: 閾値を超えた場合True
    """
    try:
        memory_info = psutil.virtual_memory()
        memory_percent = memory_info.percent
        
        if memory_percent > threshold_percent:
            logger.warning(
                f"High memory usage detected: {memory_percent:.1f}% "
                f"(Available: {memory_info.available / (1024**3):.1f}GB)"
            )
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Failed to check memory usage: {e}")
        return False


def cleanup_large_dataframes() -> int:
    """
    大きなDataFrameオブジェクトをクリーンアップ
    
    Returns:
        int: クリーンアップされたオブジェクト数
    """
    try:
        # メモリ使用量が高い場合のみ実行
        if not log_memory_if_high(70.0):
            return 0
        
        cleaned_count = 0
        
        # すべてのオブジェクトをチェック
        for obj in gc.get_objects():
            try:
                if isinstance(obj, pd.DataFrame) and len(obj) > system_config.LARGE_DATAFRAME_THRESHOLD:
                    # DataFrameのメモリ使用量を推定
                    memory_usage = obj.memory_usage(deep=True).sum()
                    
                    if memory_usage > system_config.DATAFRAME_MEMORY_THRESHOLD:
                        # 参照カウントが低い場合のみクリーンアップ
                        import sys
                        if sys.getrefcount(obj) <= 3:  # 通常の参照カウント
                            del obj
                            cleaned_count += 1
                            
            except Exception:
                continue  # オブジェクト処理でエラーが発生した場合は無視
        
        # ガベージコレクションを実行
        if cleaned_count > 0:
            gc.collect()
            logger.info(f"Cleaned up {cleaned_count} large DataFrames")
        
        return cleaned_count
        
    except Exception as e:
        logger.error(f"Failed to cleanup DataFrames: {e}")
        return 0


def validate_trading_parameters(params: Dict[str, Any]) -> bool:
    """
    取引パラメータの妥当性をチェック
    
    Args:
        params: 取引パラメータの辞書
        
    Returns:
        bool: 妥当な場合True
    """
    try:
        required_fields = ['symbol', 'position_size', 'opening_range']
        
        # 必須フィールドのチェック
        for field in required_fields:
            if field not in params:
                logger.error(f"Missing required parameter: {field}")
                return False
        
        # 値の範囲チェック
        if params['position_size'] <= 0:
            logger.error(f"Invalid position_size: {params['position_size']}")
            return False
        
        if params['opening_range'] < 0 or params['opening_range'] > 60:
            logger.error(f"Invalid opening_range: {params['opening_range']} (must be 0-60)")
            return False
        
        # シンボルの妥当性チェック
        symbol = params['symbol']
        if not symbol or not isinstance(symbol, str) or len(symbol) > 10:
            logger.error(f"Invalid symbol: {symbol}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error validating trading parameters: {e}")
        return False


def calculate_position_metrics(entry_price: float, exit_price: float, 
                             quantity: int, slippage_rate: float = 0.001) -> Dict[str, float]:
    """
    ポジションのメトリクスを計算
    
    Args:
        entry_price: エントリー価格
        exit_price: 決済価格
        quantity: 数量
        slippage_rate: スリッページ率
        
    Returns:
        Dict: メトリクス辞書 (profit, return_pct, slippage_cost)
    """
    try:
        # スリッページを考慮した実際の価格
        actual_entry_price = entry_price * (1 + slippage_rate)
        actual_exit_price = exit_price * (1 - slippage_rate)
        
        # 利益計算
        profit = (actual_exit_price - actual_entry_price) * quantity
        
        # リターン率計算
        return_pct = (actual_exit_price / actual_entry_price - 1) * 100
        
        # スリッページコスト
        slippage_cost = (entry_price * slippage_rate + exit_price * slippage_rate) * quantity
        
        return {
            'profit': profit,
            'return_pct': return_pct,
            'slippage_cost': slippage_cost,
            'actual_entry_price': actual_entry_price,
            'actual_exit_price': actual_exit_price
        }
        
    except Exception as e:
        logger.error(f"Error calculating position metrics: {e}")
        return {
            'profit': 0.0,
            'return_pct': 0.0,
            'slippage_cost': 0.0,
            'actual_entry_price': entry_price,
            'actual_exit_price': exit_price
        }


def format_trading_summary(order_status: Dict[str, Any], symbol: str) -> str:
    """
    取引サマリーをフォーマット
    
    Args:
        order_status: 注文ステータス辞書
        symbol: 銘柄シンボル
        
    Returns:
        str: フォーマットされたサマリー
    """
    try:
        summary_lines = [f"=== Trading Summary for {symbol} ==="]
        total_profit = 0.0
        
        for order_key in ['order1', 'order2', 'order3']:
            if order_key in order_status:
                order_data = order_status[order_key]
                
                if order_data.get('exit_price', 0) != 0:
                    metrics = calculate_position_metrics(
                        order_data['entry_price'],
                        order_data['exit_price'],
                        order_data['qty']
                    )
                    
                    total_profit += metrics['profit']
                    
                    summary_lines.append(
                        f"{order_key}: Entry={order_data['entry_price']:.2f}, "
                        f"Exit={order_data['exit_price']:.2f}, "
                        f"Qty={order_data['qty']}, "
                        f"Profit=${metrics['profit']:.2f} ({metrics['return_pct']:.2f}%)"
                    )
                else:
                    summary_lines.append(f"{order_key}: Still holding (swing position)")
        
        summary_lines.append(f"Total Profit: ${total_profit:.2f}")
        summary_lines.append("=" * 50)
        
        return "\n".join(summary_lines)
        
    except Exception as e:
        logger.error(f"Error formatting trading summary: {e}")
        return f"Error generating summary for {symbol}"


def safe_float_conversion(value: Any, default: float = 0.0) -> float:
    """
    安全にfloat型に変換
    
    Args:
        value: 変換する値
        default: 変換に失敗した場合のデフォルト値
        
    Returns:
        float: 変換された値
    """
    try:
        if value is None or value == '':
            return default
        
        if isinstance(value, str):
            # パーセント記号や通貨記号を除去
            cleaned_value = value.replace('%', '').replace('$', '').replace(',', '').strip()
            return float(cleaned_value)
        
        return float(value)
        
    except (ValueError, TypeError):
        logger.debug(f"Failed to convert '{value}' to float, using default {default}")
        return default