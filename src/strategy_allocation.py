"""
戦略アロケーション管理モジュール

市場トレンドに基づいて各取引戦略への資金配分を動的に調整します。
"""

import argparse
import re
from typing import Dict, Optional, Union, List, Tuple
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from scipy.stats import linregress
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client
import alpaca_trade_api as tradeapi
from logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)

# タイムゾーン定数
TZ_NY: ZoneInfo = ZoneInfo("US/Eastern")
TZ_UTC: ZoneInfo = ZoneInfo('UTC')

# 市場分析パラメータ定数
DEFAULT_MARKET_LOOKBACK_DAYS: int = 200
DEFAULT_MA_SHORT_PERIOD: int = 50
DEFAULT_MA_LONG_PERIOD: int = 200
DEFAULT_SLOPE_WINDOW: int = 10
DEFAULT_SLOPE_SMOOTH_WINDOW: int = 3
DEFAULT_TREND_THRESHOLD: float = 0.1
DEFAULT_TREND_STABILITY_DAYS: int = 10

# 戦略名定数
STRATEGY_EARNINGS_LONG: str = 'strategy1'
STRATEGY_REVERSION_STOCK: str = 'strategy2'
STRATEGY_REVERSION_ETF: str = 'strategy3'
STRATEGY_REVERSION_INVERSE: str = 'strategy4'
STRATEGY_DIVIDEND: str = 'strategy5'
STRATEGY_EARNINGS_SHORT: str = 'strategy6'

# セキュリティ・バリデーション定数
VALID_ACCOUNT_TYPES: set = {'live', 'paper', 'paper_short'}
VALID_STRATEGY_NAMES: set = {
    'strategy1', 'strategy2', 'strategy3', 'strategy4', 'strategy5', 'strategy6'
}
SYMBOL_PATTERN: re.Pattern = re.compile(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$')
MAX_LOOKBACK_DAYS: int = 1000
MIN_LOOKBACK_DAYS: int = 10
MAX_PORTFOLIO_VALUE: float = 1e12  # 1兆ドル制限
MIN_PORTFOLIO_VALUE: float = 1000.0  # 最小ポートフォリオ値


class ValidationError(Exception):
    """入力検証エラー"""
    pass


class SecurityError(Exception):
    """セキュリティ関連のエラー"""
    pass


def validate_strategy_name(strategy: str) -> None:
    """
    戦略名の検証
    
    Args:
        strategy: 戦略名
        
    Raises:
        ValidationError: 無効な戦略名
    """
    if not isinstance(strategy, str):
        raise ValidationError(f"Strategy name must be string, got {type(strategy)}")
    
    if not strategy:
        raise ValidationError("Strategy name cannot be empty")
    
    strategy_lower = strategy.lower()
    if strategy_lower not in VALID_STRATEGY_NAMES:
        raise ValidationError(f"Invalid strategy name: {strategy}. Valid strategies: {VALID_STRATEGY_NAMES}")


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


def validate_lookback_days(days: int) -> None:
    """
    ルックバック期間の検証
    
    Args:
        days: ルックバック日数
        
    Raises:
        ValidationError: 無効な日数範囲
    """
    if not isinstance(days, int):
        raise ValidationError(f"Lookback days must be integer, got {type(days)}")
    
    if not (MIN_LOOKBACK_DAYS <= days <= MAX_LOOKBACK_DAYS):
        raise ValidationError(f"Lookback days must be between {MIN_LOOKBACK_DAYS} and {MAX_LOOKBACK_DAYS}, got {days}")


def validate_portfolio_value(value: Optional[float]) -> None:
    """
    ポートフォリオ価値の検証
    
    Args:
        value: ポートフォリオ価値
        
    Raises:
        ValidationError: 無効なポートフォリオ価値
    """
    if value is None:
        return  # None は許可（API から取得）
    
    if not isinstance(value, (int, float)):
        raise ValidationError(f"Portfolio value must be numeric, got {type(value)}")
    
    if not (MIN_PORTFOLIO_VALUE <= value <= MAX_PORTFOLIO_VALUE):
        raise ValidationError(f"Portfolio value must be between ${MIN_PORTFOLIO_VALUE:,.2f} and ${MAX_PORTFOLIO_VALUE:,.2f}, got ${value:,.2f}")


def calculate_slope(series: pd.Series, window: int = DEFAULT_SLOPE_WINDOW) -> List[float]:
    """
    時系列データの線形回帰傾きを計算
    
    Args:
        series: 分析対象の時系列データ
        window: 回帰計算に使用する期間（デフォルト: 10）
        
    Returns:
        各時点での傾きのリスト（初期値はNaN）
    """
    slopes = [np.nan] * window
    
    for i in range(window, len(series)):
        y = series[i-window:i]
        x = np.arange(window)
        
        try:
            slope, _, _, _, _ = linregress(x, y)
            slopes.append(slope)
        except Exception as e:
            logger.warning(f"傾き計算エラー at position {i}: {e}")
            slopes.append(np.nan)
    
    return slopes


def get_market_indicator(
    api: tradeapi.REST,
    symbol: str = 'SPY',
    limit: int = DEFAULT_MARKET_LOOKBACK_DAYS
) -> pd.DataFrame:
    """
    市場指標データを取得し、移動平均を計算
    
    Args:
        api: Alpaca APIクライアント
        symbol: 市場指標シンボル（デフォルト: SPY）
        limit: 取得日数（デフォルト: 200日）
        
    Returns:
        移動平均を含む市場データのDataFrame
        
    Raises:
        ValidationError: 無効な入力パラメータ
        Exception: API呼び出しエラー
    """
    # 入力検証
    validate_symbol(symbol)
    validate_lookback_days(limit)
    
    try:
        current_time = datetime.now().astimezone(TZ_NY)
        start_dt = current_time - timedelta(days=limit)
        
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = current_time.strftime("%Y-%m-%d")
        
        logger.info(f"市場データ取得: {symbol} ({start_date} - {end_date})")
        
        bars = api.get_bars(
            symbol,
            TimeFrame(1, TimeFrameUnit.Day),
            start=start_date,
            end=end_date
        ).df
        
        data = bars.copy()
        data = data.sort_index()
        
        # 移動平均の計算
        data['MA50'] = data['close'].rolling(window=DEFAULT_MA_SHORT_PERIOD).mean()
        data['MA200'] = data['close'].rolling(window=DEFAULT_MA_LONG_PERIOD).mean()
        
        logger.info(f"市場データ取得完了: {len(data)}日分")
        return data
        
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"市場データ取得エラー: {e}")
        raise


def determine_market_trend(
    data: pd.DataFrame,
    threshold: float = DEFAULT_TREND_THRESHOLD
) -> str:
    """
    市場トレンドを判定（強気・弱気・中立）
    
    Args:
        data: 市場データ（MA50, MA200を含む）
        threshold: トレンド判定の閾値（デフォルト: 0.1）
        
    Returns:
        'bull', 'bear', または 'neutral'
    """
    # 50日移動平均線の傾きを計算
    data['MA50_Slope'] = calculate_slope(data['MA50'], window=DEFAULT_SLOPE_WINDOW)
    
    # 傾きの移動平均を計算して、適度にノイズを減らす
    data['MA50_Slope_Smooth'] = data['MA50_Slope'].rolling(
        window=DEFAULT_SLOPE_SMOOTH_WINDOW
    ).mean()

    # ヒステリシスを導入したトレンド判定
    data['Trend'] = ''
    current_trend = 'neutral'
    trend_duration = 0  # トレンドの継続期間をカウント
    
    for i in range(1, len(data)):
        slope = data['MA50_Slope_Smooth'].iloc[i] if not pd.isna(data['MA50_Slope_Smooth'].iloc[i]) else 0
        
        # トレンド継続期間に基づいて閾値を調整
        duration_factor = min(1.0, trend_duration / DEFAULT_TREND_STABILITY_DAYS)
        adjusted_threshold = threshold * (1 - duration_factor * 0.2)
        
        if current_trend == 'bull':
            if slope < -threshold:  # 下向きトレンドへの変更
                current_trend = 'bear'
                trend_duration = 0
                logger.info(f"トレンド変更: bull -> bear (slope: {slope:.4f})")
            else:
                trend_duration += 1
                
        elif current_trend == 'bear':
            if slope > threshold * 1.3:  # 上向きトレンドへの変更（やや保守的）
                current_trend = 'bull'
                trend_duration = 0
                logger.info(f"トレンド変更: bear -> bull (slope: {slope:.4f})")
            else:
                trend_duration += 1
                
        else:  # neutral
            if slope > threshold * 0.8:  # 上昇トレンドの判定をより敏感に
                current_trend = 'bull'
                trend_duration = 0
                logger.info(f"トレンド変更: neutral -> bull (slope: {slope:.4f})")
            elif slope < -threshold * 0.7:  # 下落トレンドの判定をより敏感に
                current_trend = 'bear'
                trend_duration = 0
                logger.info(f"トレンド変更: neutral -> bear (slope: {slope:.4f})")
            
        data.at[data.index[i], 'Trend'] = current_trend

    return data['Trend'].iloc[-1]  # 最新のトレンド値のみを返す


def adjust_asset_allocation(market_trend: str) -> Dict[str, float]:
    """
    市場トレンドに基づいて戦略別の資金配分を決定
    
    Args:
        market_trend: 市場トレンド ('bull', 'bear', 'neutral')
        
    Returns:
        戦略名をキー、配分比率を値とする辞書
        
    Raises:
        ValueError: 無効な市場トレンドが指定された場合
    """
    allocation_map = {
        'bull': {
            STRATEGY_EARNINGS_LONG: 0.50,    # 決算スイングトレード（ロング）
            STRATEGY_REVERSION_STOCK: 0.10,  # 平均回帰スイングトレード（個別銘柄）
            STRATEGY_REVERSION_ETF: 0.10,    # 平均回帰スイングトレード（ETF）
            STRATEGY_REVERSION_INVERSE: 0.20, # 平均回帰スイングトレード（インバースETF）
            STRATEGY_DIVIDEND: 0.85,         # 高配当投資
            STRATEGY_EARNINGS_SHORT: 0.40,   # 決算スイングトレード（ショート）
        },
        'bear': {
            STRATEGY_EARNINGS_LONG: 0.40,    # 決算スイングトレード（ロング）
            STRATEGY_REVERSION_STOCK: 0.10,  # 平均回帰スイングトレード（個別銘柄）
            STRATEGY_REVERSION_ETF: 0.10,    # 平均回帰スイングトレード（ETF）
            STRATEGY_REVERSION_INVERSE: 0.20, # 平均回帰スイングトレード（インバースETF）
            STRATEGY_DIVIDEND: 0.60,         # 高配当投資
            STRATEGY_EARNINGS_SHORT: 0.60,   # 決算スイングトレード（ショート）
        },
        'neutral': {
            STRATEGY_EARNINGS_LONG: 0.50,    # 決算スイングトレード（ロング）
            STRATEGY_REVERSION_STOCK: 0.10,  # 平均回帰スイングトレード（個別銘柄）
            STRATEGY_REVERSION_ETF: 0.10,    # 平均回帰スイングトレード（ETF）
            STRATEGY_REVERSION_INVERSE: 0.20, # 平均回帰スイングトレード（インバースETF）
            STRATEGY_DIVIDEND: 0.50,         # 高配当投資
            STRATEGY_EARNINGS_SHORT: 0.50,   # 決算スイングトレード（ショート）
        }
    }
    
    if market_trend not in allocation_map:
        raise ValueError(f"無効な市場トレンド: {market_trend}")
    
    allocation = allocation_map[market_trend]
    logger.info(f"資金配分調整 ({market_trend}相場): {allocation}")
    
    return allocation


def get_strategy_allocation(api: Optional[tradeapi.REST] = None) -> Dict[str, float]:
    """
    現在の市場状況に基づいて戦略別の資金配分を取得
    
    Args:
        api: Alpaca APIクライアント（省略時は新規作成）
        
    Returns:
        戦略名をキー、配分比率を値とする辞書
        
    Raises:
        Exception: API呼び出しまたはデータ分析エラー
    """
    try:
        if api is None:
            alpaca_client = get_alpaca_client('live')
            api = alpaca_client.api
        
        # 市場指標を取得
        market_data = get_market_indicator(api)
        
        # 強気・弱気相場を判定
        market_trend = determine_market_trend(market_data, threshold=DEFAULT_TREND_THRESHOLD)
        logger.info(f"現在の市場トレンド: {market_trend}")
        
        # アセットアロケーションを調整
        allocation = adjust_asset_allocation(market_trend)
        
        return allocation
        
    except Exception as e:
        logger.error(f"戦略配分取得エラー: {e}")
        raise


def get_target_value(
    strategy: str,
    account: str = 'live',
    portfolio_value: Optional[float] = None
) -> float:
    """
    指定された戦略の目標投資額を計算
    
    Args:
        strategy: 戦略名（'strategy1'～'strategy6' または大文字小文字不問）
        account: アカウント種別（'live', 'paper', 'paper_short'）
        portfolio_value: ポートフォリオ総額（省略時はAPIから取得）
        
    Returns:
        目標投資額（USD）
        
    Raises:
        ValidationError: 無効な入力パラメータ
        Exception: API呼び出しエラー
    """
    # 入力検証
    validate_strategy_name(strategy)
    validate_account_type(account)
    validate_portfolio_value(portfolio_value)
    
    try:
        # API クライアント初期化
        alpaca_client = get_alpaca_client(account)
        api = alpaca_client.api
        
        # 戦略配分を取得
        allocation = get_strategy_allocation(api)
        
        # ポートフォリオ価値を取得
        if portfolio_value is None:
            account_info = api.get_account()
            portfolio_value = float(account_info.portfolio_value)
            # 取得後のポートフォリオ価値も検証
            validate_portfolio_value(portfolio_value)
            logger.info(f"ポートフォリオ総額: ${portfolio_value:,.2f}")
        
        # 戦略名を正規化
        strategy_key = strategy.lower()
        if strategy_key not in allocation:
            raise ValidationError(f"無効な戦略名: {strategy}")
        
        # 目標投資額を計算
        target_value = portfolio_value * allocation[strategy_key]
        logger.info(f"戦略 {strategy} の目標投資額: ${target_value:,.2f} "
                   f"(配分比率: {allocation[strategy_key]:.1%})")
        
        return target_value
        
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"目標投資額計算エラー: {e}")
        raise


def get_allocation_summary(account: str = 'live') -> Dict[str, Dict[str, float]]:
    """
    全戦略の配分サマリーを取得
    
    Args:
        account: アカウント種別
        
    Returns:
        {
            'portfolio_value': float,
            'market_trend': str,
            'allocations': {
                'strategy1': {'ratio': float, 'amount': float},
                ...
            }
        }
    """
    # 入力検証
    validate_account_type(account)
    
    try:
        alpaca_client = get_alpaca_client(account)
        api = alpaca_client.api
        
        # ポートフォリオ情報を取得
        account_info = api.get_account()
        portfolio_value = float(account_info.portfolio_value)
        validate_portfolio_value(portfolio_value)
        
        # 市場データと配分を取得
        market_data = get_market_indicator(api)
        market_trend = determine_market_trend(market_data)
        allocation = get_strategy_allocation(api)
        
        # サマリーを構築
        summary = {
            'portfolio_value': portfolio_value,
            'market_trend': market_trend,
            'allocations': {}
        }
        
        for strategy, ratio in allocation.items():
            summary['allocations'][strategy] = {
                'ratio': ratio,
                'amount': portfolio_value * ratio
            }
        
        return summary
        
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"配分サマリー取得エラー: {e}")
        raise


def main():
    """CLIエントリーポイント"""
    parser = argparse.ArgumentParser(
        description='戦略アロケーション管理ツール'
    )
    parser.add_argument(
        '--account',
        default='live',
        choices=['live', 'paper', 'paper_short'],
        help='アカウント種別'
    )
    parser.add_argument(
        '--strategy',
        help='特定戦略の目標投資額を表示（省略時は全戦略のサマリー）'
    )
    
    args = parser.parse_args()
    
    try:
        if args.strategy:
            # 特定戦略の目標投資額を表示
            target_value = get_target_value(args.strategy, account=args.account)
            logger.info("戦略 %s の目標投資額: $%s", args.strategy, f"{target_value:,.2f}")
        else:
            # 全戦略のサマリーを表示
            summary = get_allocation_summary(account=args.account)
            
            logger.info("=== 戦略アロケーションサマリー ===")
            logger.info("ポートフォリオ総額: $%s", f"{summary['portfolio_value']:,.2f}")
            logger.info("市場トレンド: %s", summary['market_trend'])
            logger.info("戦略別配分:")
            
            for strategy, info in summary['allocations'].items():
                logger.info("  %s: %.1f%% ($%s)", strategy, info['ratio']*100, f"{info['amount']:,.2f}")
                
    except Exception as e:
        logger.error("エラー: %s", e)
        logger.error(f"CLI実行エラー: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())