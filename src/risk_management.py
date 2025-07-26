"""
リスク管理モジュール

取引システムの実現損益計算とリスク基準チェック機能を提供します。
FIFO方式による正確な損益計算とパフォーマンス指標の生成を行います。
"""

import os
import json
import argparse
import re
from typing import Dict, List, Optional, Tuple, Union, Any, Deque
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from dotenv import load_dotenv
import strategy_allocation
from api_clients import get_alpaca_client, AlpacaClient
from config import risk_config
from logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)

# 設定定数
PNL_LOG_FILE: str = risk_config.PNL_LOG_FILE
PNL_CRITERIA: float = risk_config.PNL_CRITERIA
PNL_CHECK_PERIOD: int = risk_config.PNL_CHECK_PERIOD
DEFAULT_ACCOUNT: str = 'live'

# PnL計算設定定数
DEFAULT_PORTFOLIO_VALUE: float = 100000.0
JSON_INDENT: int = risk_config.JSON_INDENT
PAGE_SIZE: int = risk_config.PAGE_SIZE
PNL_HISTORY_MULTIPLIER: int = risk_config.PNL_HISTORY_MULTIPLIER
TRADE_VALUE_MULTIPLIER: float = risk_config.TRADE_VALUE_MULTIPLIER
PARETO_RATIO: float = risk_config.PARETO_RATIO

# パフォーマンス統計計算定数
DEFAULT_PRECISION_DIGITS: int = 4
PERCENTAGE_PRECISION_DIGITS: int = 2
TOP_PERFORMERS_PERCENTAGE: float = 0.2  # Pareto 80/20 rule
MIN_TRADES_FOR_STATS: int = 1
INFINITE_RATIO_THRESHOLD: float = 0.0001

# セキュリティ・バリデーション定数
VALID_ACCOUNT_TYPES: set = {'live', 'paper', 'paper_short'}
MAX_DAYS_LOOKBACK: int = 365
MIN_DAYS_LOOKBACK: int = 1
MAX_PNL_RATE_THRESHOLD: float = 1.0  # 100%
MIN_PNL_RATE_THRESHOLD: float = -1.0  # -100%
SYMBOL_PATTERN: re.Pattern = re.compile(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$')
MAX_FILENAME_LENGTH: int = 255

# トレード結果の型定義
TradeResult = Dict[str, Union[str, float, datetime]]
PnLLogEntry = Dict[str, Union[float, int]]
FillActivity = Any  # Alpaca APIのFillオブジェクト


class SecurityError(Exception):
    """セキュリティ関連のエラー"""
    pass


class ValidationError(Exception):
    """入力検証エラー"""
    pass


def validate_account_type(account: str) -> None:
    """
    アカウント種別の検証
    
    Args:
        account: アカウント種別
        
    Raises:
        ValidationError: 無効なアカウント種別
    """
    if not isinstance(account, str):
        raise ValidationError(f"Account type must be string, got {type(account)}")
    
    if account not in VALID_ACCOUNT_TYPES:
        raise ValidationError(f"Invalid account type: {account}. Valid types: {VALID_ACCOUNT_TYPES}")


def validate_days_range(days: int) -> None:
    """
    日数範囲の検証
    
    Args:
        days: 分析期間（日数）
        
    Raises:
        ValidationError: 無効な日数範囲
    """
    if not isinstance(days, int):
        raise ValidationError(f"Days must be integer, got {type(days)}")
    
    if not (MIN_DAYS_LOOKBACK <= days <= MAX_DAYS_LOOKBACK):
        raise ValidationError(f"Days must be between {MIN_DAYS_LOOKBACK} and {MAX_DAYS_LOOKBACK}, got {days}")


def validate_pnl_rate(pnl_rate: float) -> None:
    """
    PnL基準値の検証
    
    Args:
        pnl_rate: PnL基準値
        
    Raises:
        ValidationError: 無効なPnL基準値
    """
    if not isinstance(pnl_rate, (int, float)):
        raise ValidationError(f"PnL rate must be numeric, got {type(pnl_rate)}")
    
    if not (MIN_PNL_RATE_THRESHOLD <= pnl_rate <= MAX_PNL_RATE_THRESHOLD):
        raise ValidationError(f"PnL rate must be between {MIN_PNL_RATE_THRESHOLD} and {MAX_PNL_RATE_THRESHOLD}, got {pnl_rate}")


def validate_symbol(symbol: str) -> None:
    """
    取引シンボルの検証
    
    Args:
        symbol: 取引シンボル
        
    Raises:
        ValidationError: 無効なシンボル形式
    """
    if not isinstance(symbol, str):
        raise ValidationError(f"Symbol must be string, got {type(symbol)}")
    
    if not symbol:
        raise ValidationError("Symbol cannot be empty")
    
    if not SYMBOL_PATTERN.match(symbol.upper()):
        raise ValidationError(f"Invalid symbol format: {symbol}. Must be 1-5 uppercase letters, optionally followed by '.XX'")


def validate_file_path(file_path: str) -> None:
    """
    ファイルパスのセキュリティ検証
    
    Args:
        file_path: ファイルパス
        
    Raises:
        SecurityError: セキュリティ上危険なパス
        ValidationError: 無効なファイルパス
    """
    if not isinstance(file_path, str):
        raise ValidationError(f"File path must be string, got {type(file_path)}")
    
    if not file_path:
        raise ValidationError("File path cannot be empty")
    
    if len(file_path) > MAX_FILENAME_LENGTH:
        raise ValidationError(f"File path too long: {len(file_path)} > {MAX_FILENAME_LENGTH}")
    
    # パストラバーサル攻撃の防止
    if '..' in file_path or file_path.startswith('/'):
        raise SecurityError(f"Potentially dangerous file path detected: {file_path}")
    
    # 危険な文字の検出
    dangerous_chars = ['<', '>', '|', '&', ';', '`', '$']
    if any(char in file_path for char in dangerous_chars):
        raise SecurityError(f"Dangerous characters detected in file path: {file_path}")


def sanitize_log_data(data: Any) -> Any:
    """
    ログデータのサニタイゼーション
    
    Args:
        data: サニタイズ対象データ
        
    Returns:
        サニタイズされたデータ
    """
    if isinstance(data, dict):
        return {k: sanitize_log_data(v) for k, v in data.items() if isinstance(k, str)}
    elif isinstance(data, list):
        return [sanitize_log_data(item) for item in data]
    elif isinstance(data, str):
        # 危険な文字列の除去
        return re.sub(r'[<>"\';]', '', data)
    elif isinstance(data, (int, float)):
        # 数値の範囲チェック
        if abs(data) > 1e10:  # 極端に大きな値の制限
            logger.warning(f"Extremely large numeric value detected: {data}")
            return 0.0
        return data
    else:
        return data


def read_log() -> Dict[str, PnLLogEntry]:
    """
    PnLログファイルを読み込み
    
    Returns:
        ログデータの辞書（日付をキー、PnL情報を値とする）
        
    Raises:
        SecurityError: セキュリティ上危険なファイルパス
        ValidationError: 無効なファイルパス
    """
    # ファイルパスのセキュリティ検証
    validate_file_path(PNL_LOG_FILE)
    
    if os.path.exists(PNL_LOG_FILE):
        try:
            with open(PNL_LOG_FILE, 'r', encoding='utf-8') as file:
                raw_data = json.load(file)
                # データのサニタイゼーション
                sanitized_data = sanitize_log_data(raw_data)
                logger.debug(f"PnL log file loaded and sanitized: {PNL_LOG_FILE}")
                return sanitized_data
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in PnL log file: {e}")
            raise
        except IOError as e:
            logger.error(f"I/O error reading PnL log file: {e}")
            raise
    return {}


def write_log(log_data: Dict[str, PnLLogEntry]) -> None:
    """
    PnLログファイルに書き込み
    
    Args:
        log_data: 保存するログデータ
        
    Raises:
        SecurityError: セキュリティ上危険なファイルパス
        ValidationError: 無効なログデータ
        IOError: ファイル書き込みエラー
    """
    # ファイルパスのセキュリティ検証
    validate_file_path(PNL_LOG_FILE)
    
    # ログデータのサニタイゼーション
    sanitized_data = sanitize_log_data(log_data)
    
    try:
        with open(PNL_LOG_FILE, 'w', encoding='utf-8') as file:
            json.dump(sanitized_data, file, indent=JSON_INDENT, ensure_ascii=False)
        logger.debug(f"PnL log file updated successfully: {PNL_LOG_FILE}")
    except IOError as e:
        logger.error(f"I/O error writing PnL log file: {e}")
        raise


def get_account_info(alpaca_client: AlpacaClient) -> Tuple[float, float]:
    """
    アカウント情報を取得し、ポートフォリオ価値と取引用資金を計算
    
    Args:
        alpaca_client: Alpacaクライアント
        
    Returns:
        (ポートフォリオ総額, 取引用資金額)のタプル
        
    Raises:
        Exception: アカウント情報取得エラー
    """
    try:
        account = alpaca_client.get_account()
        portfolio_value = float(account.portfolio_value)
        logger.info(f"Portfolio value retrieved: ${portfolio_value:,.2f}")
        
        # 戦略配分を取得して取引用資金を計算
        allocation = strategy_allocation.get_strategy_allocation(alpaca_client.api)
        total_trade_value = portfolio_value * (1 - allocation['strategy5'])
        logger.info(f"Trading capital calculated: ${total_trade_value:,.2f} (allocation: {allocation})")
        
        return portfolio_value, total_trade_value
        
    except (AttributeError, ValueError, KeyError) as e:
        logger.error(f"Account info parsing error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve account information: {e}")
        raise


def get_trading_activities(
    alpaca_client: AlpacaClient,
    start_date: datetime,
    end_date: datetime
) -> List[FillActivity]:
    """
    指定期間の取引活動データを取得
    
    Args:
        alpaca_client: Alpacaクライアント
        start_date: 開始日時
        end_date: 終了日時
        
    Returns:
        取引活動のリスト
    """
    activities = []
    page_token = None
    
    try:
        while True:
            try:
                response = alpaca_client.api.get_activities(
                    activity_types='FILL',
                    after=start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    until=end_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    page_token=page_token,
                    direction='asc',
                    page_size=PAGE_SIZE
                )
                
                if not response:
                    break
                
                activities.extend(response)
                
                if len(response) < PAGE_SIZE:
                    break
                else:
                    page_token = response[-1].id
                    
            except (AttributeError, KeyError) as e:
                logger.error(f"Activities API response parsing error (token: {page_token}): {e}")
                raise
            except Exception as e:
                logger.error(f"Activities API call failed (token: {page_token}): {e}")
                raise
                
    except Exception as e:
        logger.error(f"Failed to initialize activities retrieval: {e}")
        raise
        
    logger.info(f"Retrieved {len(activities)} trading activities")
    return activities


def calculate_fifo_pnl(
    fills_by_symbol: Dict[str, List[FillActivity]],
    start_date: datetime
) -> Tuple[float, List[TradeResult], Dict[str, Union[int, float]]]:
    """
    FIFO方式で実現損益を計算
    
    Args:
        fills_by_symbol: シンボル別の取引データ
        start_date: PnL計算開始日
        
    Returns:
        (総実現損益, トレード結果リスト, 統計指標辞書)のタプル
    """
    realized_pnl = 0.0
    trade_results = []
    all_pnls = []
    
    # 統計用変数
    winning_trades = 0
    losing_trades = 0
    total_profit = 0.0
    total_loss = 0.0
    cumulative_pnl = 0.0
    max_cumulative_pnl = 0.0
    max_drawdown = 0.0
    
    for symbol, fills in fills_by_symbol.items():
        # 取引時間でソート
        fills.sort(key=lambda x: x.transaction_time)
        
        # 買い注文のキュー（FIFO用）
        buy_queue: Deque[Dict[str, Union[int, float, datetime]]] = deque()
        
        for fill in fills:
            qty = int(fill.qty)
            price = float(fill.price)
            side = fill.side.lower()
            transaction_time = fill.transaction_time
            
            if side == 'buy':
                buy_queue.append({
                    'qty': qty,
                    'price': price,
                    'time': transaction_time
                })
                
            elif side == 'sell':
                if transaction_time >= start_date:
                    # 指定期間内の売り注文のみPnL計算
                    remaining_qty = qty
                    
                    while remaining_qty > 0 and buy_queue:
                        buy_fill = buy_queue[0]
                        buy_qty = int(buy_fill['qty'])
                        buy_price = float(buy_fill['price'])
                        
                        matched_qty = min(remaining_qty, buy_qty)
                        pnl = matched_qty * (price - buy_price)
                        realized_pnl += pnl
                        
                        # トレード結果を記録
                        trade_results.append({
                            'symbol': symbol,
                            'pnl': pnl,
                            'time': transaction_time,
                            'qty': matched_qty,
                            'buy_price': buy_price,
                            'sell_price': price
                        })
                        
                        all_pnls.append(pnl)
                        
                        # 累積PnLとドローダウン計算
                        cumulative_pnl += pnl
                        if cumulative_pnl > max_cumulative_pnl:
                            max_cumulative_pnl = cumulative_pnl
                        
                        current_drawdown = max_cumulative_pnl - cumulative_pnl
                        if current_drawdown > max_drawdown:
                            max_drawdown = current_drawdown
                        
                        # 勝ち負け統計
                        if pnl > 0:
                            winning_trades += 1
                            total_profit += pnl
                        else:
                            losing_trades += 1
                            total_loss += abs(pnl)
                        
                        logger.debug(f"{symbol}: PnL={pnl:.2f}, 累積={realized_pnl:.2f}")
                        
                        remaining_qty -= matched_qty
                        buy_fill['qty'] = buy_qty - matched_qty
                        
                        if buy_fill['qty'] == 0:
                            buy_queue.popleft()
                    
                    if remaining_qty > 0:
                        logger.warning(f"{symbol}: 買い注文を上回る売却 ({remaining_qty}株)")
                else:
                    # 期間外の売り注文は買いキューのみ更新
                    _update_buy_queue_for_historical_sell(buy_queue, qty)
    
    # 統計指標を計算
    stats = _calculate_performance_stats(
        winning_trades, losing_trades, total_profit, total_loss,
        all_pnls, max_drawdown
    )
    
    return realized_pnl, trade_results, stats


def _update_buy_queue_for_historical_sell(
    buy_queue: Deque[Dict[str, Union[int, float, datetime]]],
    sell_qty: int
) -> None:
    """
    過去の売り注文に対する買いキューの更新
    
    Args:
        buy_queue: 買い注文のキュー
        sell_qty: 売り数量
    """
    remaining_qty = sell_qty
    
    while remaining_qty > 0 and buy_queue:
        buy_fill = buy_queue[0]
        buy_qty = int(buy_fill['qty'])
        
        matched_qty = min(remaining_qty, buy_qty)
        remaining_qty -= matched_qty
        buy_fill['qty'] = buy_qty - matched_qty
        
        if buy_fill['qty'] == 0:
            buy_queue.popleft()


def _calculate_performance_stats(
    winning_trades: int,
    losing_trades: int,
    total_profit: float,
    total_loss: float,
    all_pnls: List[float],
    max_drawdown: float
) -> Dict[str, Union[int, float]]:
    """
    パフォーマンス統計指標を計算
    
    Args:
        winning_trades: 勝ちトレード数
        losing_trades: 負けトレード数
        total_profit: 総利益
        total_loss: 総損失
        all_pnls: 全PnLリスト
        max_drawdown: 最大ドローダウン
        
    Returns:
        統計指標の辞書
    """
    total_trades = winning_trades + losing_trades
    
    # 基本指標
    win_rate = winning_trades / total_trades if total_trades > MIN_TRADES_FOR_STATS else 0.0
    profit_factor = total_profit / total_loss if total_loss > INFINITE_RATIO_THRESHOLD else float('inf')
    avg_pnl = sum(all_pnls) / len(all_pnls) if len(all_pnls) > 0 else 0.0
    
    # 期待値計算
    avg_win = total_profit / winning_trades if winning_trades > 0 else 0.0
    avg_loss = total_loss / losing_trades if losing_trades > 0 else 0.0
    expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    # Calmar Ratio
    calmar_ratio = total_profit / max_drawdown if max_drawdown > INFINITE_RATIO_THRESHOLD else float('inf')
    
    # Pareto Ratio (上位20%のトレードの利益比率)
    winning_pnls = sorted([p for p in all_pnls if p > 0], reverse=True)
    top_performers_count = max(MIN_TRADES_FOR_STATS, int(len(winning_pnls) * TOP_PERFORMERS_PERCENTAGE))
    top_performers_profit = sum(winning_pnls[:top_performers_count])
    pareto_ratio = top_performers_profit / total_profit if total_profit > INFINITE_RATIO_THRESHOLD else 0.0
    
    return {
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_pnl': avg_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'expected_value': expected_value,
        'max_drawdown': max_drawdown,
        'calmar_ratio': calmar_ratio,
        'pareto_ratio': pareto_ratio
    }


def check_pnl(
    days: int = PNL_CHECK_PERIOD,
    account: str = DEFAULT_ACCOUNT
) -> float:
    """
    指定期間の実現損益率を計算
    
    Args:
        days: 計算期間（日数）
        account: アカウント種別
        
    Returns:
        実現損益率（小数点形式、例: 0.05 = 5%）
        
    Raises:
        ValidationError: 無効な入力パラメータ
        SecurityError: セキュリティ検証失敗
        Exception: API呼び出しエラー
    """
    # 入力検証
    validate_days_range(days)
    validate_account_type(account)
    # ログファイルを読み込み
    log_data = read_log()
    
    # 日付範囲の定義
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    history_start_date = end_date - timedelta(days=days * PNL_HISTORY_MULTIPLIER)
    
    date_str = end_date.strftime("%Y-%m-%d")
    
    # 既存ログの確認
    if date_str in log_data:
        logger.info(f"既存ログを使用: {log_data[date_str]['realized_pnl']:.2%}")
        return float(log_data[date_str]['realized_pnl'])
    
    # APIクライアント初期化
    alpaca_client = get_alpaca_client(account)
    
    # アカウント情報取得
    portfolio_value, total_trade_value = get_account_info(alpaca_client)
    
    # 取引活動データ取得
    activities = get_trading_activities(alpaca_client, history_start_date, end_date)
    
    # シンボル別に取引データを整理
    fills_by_symbol = defaultdict(list)
    for activity in activities:
        fills_by_symbol[activity.symbol].append(activity)
    
    # FIFO方式でPnL計算
    realized_pnl, trade_results, stats = calculate_fifo_pnl(fills_by_symbol, start_date)
    
    # 損益率計算（取引用資金に対する比率）
    pnl_percentage = realized_pnl / total_trade_value if total_trade_value > INFINITE_RATIO_THRESHOLD else 0.0
    
    # ログエントリー作成
    log_entry = {
        'realized_pnl': round(pnl_percentage, DEFAULT_PRECISION_DIGITS),
        'absolute_pnl': round(realized_pnl, PERCENTAGE_PRECISION_DIGITS),
        'total_trade_value': round(total_trade_value, PERCENTAGE_PRECISION_DIGITS),
        **{k: round(v, DEFAULT_PRECISION_DIGITS) if isinstance(v, float) else v for k, v in stats.items()}
    }
    
    # ログ保存
    log_data[date_str] = log_entry
    write_log(log_data)
    
    # 結果表示
    logger.info(f"実現損益率: {pnl_percentage:.2%}")
    logger.info(f"勝率: {stats['win_rate']:.2%}, PF: {stats['profit_factor']:.2f}")
    logger.info(f"総トレード数: {stats['total_trades']}, 期待値: {stats['expected_value']:.2f}")
    logger.info(f"最大DD: {stats['max_drawdown']:.2f}, Calmar比: {stats['calmar_ratio']:.2f}")
    
    return pnl_percentage


def check_pnl_criteria(
    days: int = PNL_CHECK_PERIOD,
    pnl_rate: float = PNL_CRITERIA,
    account: str = DEFAULT_ACCOUNT
) -> bool:
    """
    PnL基準チェック - 取引継続可否を判定
    
    Args:
        days: 計算期間（日数）
        pnl_rate: 基準損益率（小数点形式）
        account: アカウント種別
        
    Returns:
        基準を満たす場合True、満たさない場合False
    """
    try:
        # 入力検証
        validate_days_range(days)
        validate_pnl_rate(pnl_rate)
        validate_account_type(account)
        
        current_pnl = check_pnl(days, account)
        is_criteria_met = current_pnl > pnl_rate
        
        logger.info(f"PnL criteria check: {current_pnl:.2%} > {pnl_rate:.2%} = {is_criteria_met}")
        
        if not is_criteria_met:
            logger.warning(f"PnL criteria not met - trading halt recommended (current: {current_pnl:.2%}, threshold: {pnl_rate:.2%})")
        
        return is_criteria_met
        
    except (ValidationError, SecurityError) as e:
        logger.error(f"Input validation failed in PnL criteria check: {e}")
        # 入力検証エラー時は保守的に取引停止
        return False
    except Exception as e:
        logger.error(f"PnL criteria check failed: {e}")
        # その他のエラー時は保守的に取引停止
        return False


def get_pnl_summary(
    days: int = PNL_CHECK_PERIOD,
    account: str = DEFAULT_ACCOUNT
) -> Dict[str, Union[float, int, bool]]:
    """
    PnL分析サマリーを取得
    
    Args:
        days: 分析期間（日数）
        account: アカウント種別
        
    Returns:
        PnL分析結果の辞書
    """
    try:
        # 入力検証
        validate_days_range(days)
        validate_account_type(account)
        
        log_data = read_log()
        current_pnl = check_pnl(days, account)
        
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current_data = log_data.get(date_str, {})
        
        return {
            'pnl_percentage': current_pnl,
            'meets_criteria': current_pnl > PNL_CRITERIA,
            'days_analyzed': days,
            'criteria_threshold': PNL_CRITERIA,
            **current_data
        }
        
    except (ValidationError, SecurityError) as e:
        logger.error(f"Input validation failed in PnL summary: {e}")
        return {
            'pnl_percentage': 0.0,
            'meets_criteria': False,
            'days_analyzed': days,
            'criteria_threshold': PNL_CRITERIA,
            'validation_error': str(e)
        }
    except Exception as e:
        logger.error(f"PnL summary retrieval error: {e}")
        return {
            'pnl_percentage': 0.0,
            'meets_criteria': False,
            'days_analyzed': days,
            'criteria_threshold': PNL_CRITERIA,
            'error': str(e)
        }


def main():
    """CLIエントリーポイント"""
    parser = argparse.ArgumentParser(
        description='リスク管理 - PnL計算と基準チェック'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=PNL_CHECK_PERIOD,
        help=f'分析期間（日数、デフォルト: {PNL_CHECK_PERIOD}）'
    )
    parser.add_argument(
        '--account',
        default=DEFAULT_ACCOUNT,
        choices=['live', 'paper', 'paper_short'],
        help='アカウント種別'
    )
    parser.add_argument(
        '--criteria',
        type=float,
        default=PNL_CRITERIA,
        help=f'PnL基準値（デフォルト: {PNL_CRITERIA:.2%}）'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='詳細サマリーを表示'
    )
    
    args = parser.parse_args()
    
    try:
        if args.summary:
            # 詳細サマリー表示
            summary = get_pnl_summary(args.days, args.account)
            
            print(f"\n=== PnL分析サマリー ===")
            print(f"アカウント: {args.account}")
            print(f"分析期間: {summary['days_analyzed']}日")
            print(f"実現損益率: {summary['pnl_percentage']:.2%}")
            print(f"基準値: {summary['criteria_threshold']:.2%}")
            print(f"基準達成: {'✅' if summary['meets_criteria'] else '❌'}")
            
            if 'total_trades' in summary:
                print(f"\n=== トレード統計 ===")
                print(f"総トレード数: {summary['total_trades']}")
                print(f"勝率: {summary.get('win_rate', 0):.2%}")
                print(f"プロフィットファクター: {summary.get('profit_factor', 0):.2f}")
                print(f"期待値: {summary.get('expected_value', 0):.2f}")
                print(f"最大ドローダウン: {summary.get('max_drawdown', 0):.2f}")
        else:
            # 基準チェックのみ
            result = check_pnl_criteria(args.days, args.criteria, args.account)
            print(f"\nPnL基準チェック結果: {'合格' if result else '不合格'}")
        
        return 0
        
    except Exception as e:
        print(f"エラー: {e}")
        logger.error(f"CLI実行エラー: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    exit(main())