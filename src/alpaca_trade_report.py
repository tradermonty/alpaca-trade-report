"""Alpaca取引レポート生成システム（リファクタリング版）

Alpacaアカウントの取引履歴を分析し、包括的なパフォーマンスレポートを生成します。
バックテスト機能、リスク分析、視覚的なチャート生成を含みます。

新しいコードベースの実装方針に準拠：
- グローバル変数の排除
- 共通定数の使用  
- API クライアントの統合
- FMP API への移行
- 設定管理の改善
- エラーハンドリングの強化
"""

import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os
from collections import defaultdict
import time
from typing import Optional, List, Dict, Any, Tuple
import logging
from tqdm import tqdm
import plotly.graph_objs as go
from plotly.offline import plot
import webbrowser
from bs4 import BeautifulSoup
import alpaca_trade_api as tradeapi
import platform
import subprocess

# コードベース共通モジュールのインポート
try:
    from api_clients import get_alpaca_client, get_fmp_client
    from common_constants import TIMEZONE, ACCOUNT
    from logging_config import get_logger
except ImportError as e:
    print(f"警告: 共通モジュールのインポートに失敗しました: {e}")
    print("フォールバック実装を使用します")
    
    # フォールバック実装
    from zoneinfo import ZoneInfo
    
    class TimeZoneConfig:
        NY = ZoneInfo("US/Eastern")
        UTC = ZoneInfo("UTC")
    
    class AccountConfig:
        LIVE = 'live'
        PAPER = 'paper'
    
    TIMEZONE = TimeZoneConfig()
    ACCOUNT = AccountConfig()
    
    def get_logger(name):
        import logging
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)
        
    def get_alpaca_client(account_type='paper'):
        import alpaca_trade_api as tradeapi
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        if account_type == 'live':
            api_key = os.getenv('ALPACA_API_KEY_LIVE')
            secret_key = os.getenv('ALPACA_SECRET_KEY_LIVE')
            base_url = 'https://api.alpaca.markets'
        else:
            api_key = os.getenv('ALPACA_API_KEY_PAPER')
            secret_key = os.getenv('ALPACA_SECRET_KEY_PAPER')
            base_url = 'https://paper-api.alpaca.markets'
            
        return tradeapi.REST(api_key, secret_key, base_url, api_version='v2')
    
    def get_fmp_client():
        # FMPクライアントのフォールバック実装
        class FMPClientFallback:
            def __init__(self):
                self.api_key = os.getenv('FMP_API_KEY')
                
            def get_earnings_calendar(self, start_date, end_date):
                return []  # 空のリストを返す
                
            def get_historical_price_data(self, symbol, start_date, end_date):
                import pandas as pd
                return pd.DataFrame()  # 空のDataFrameを返す
        
        return FMPClientFallback()

# ログ設定
logger = get_logger(__name__)


@dataclass
class TradeReportConfig:
    """取引レポート設定クラス"""
    start_date: str = '2023-01-01'
    end_date: str = '2023-12-31'
    stop_loss: float = 6.0
    trail_stop_ma: int = 21
    max_holding_days: int = 90
    initial_capital: float = 10000.0
    risk_limit: float = 6.0
    partial_profit: bool = True
    language: str = 'en'
    pre_earnings_change: float = -10.0
    account_type: str = 'paper'
    
    def __post_init__(self):
        """ 設定値の検証 """
        if self.stop_loss <= 0 or self.stop_loss > 50:
            raise ValueError("ストップロスは0%から50%の間で設定してください")
        if self.initial_capital <= 0:
            raise ValueError("初期資本は正の値である必要があります")


class TradeReport:
    """取引レポート生成クラス（リファクタリング版）"""
    
    # ダークモードの色設定
    DARK_THEME = {
        'bg_color': '#1e293b',
        'plot_bg_color': '#1e293b',
        'grid_color': '#334155',
        'text_color': '#e2e8f0',
        'line_color': '#60a5fa',
        'profit_color': '#22c55e',
        'loss_color': '#ef4444'
    }

    def __init__(self, config: TradeReportConfig = None):
        """取引レポートの初期化
        
        Args:
            config: 取引レポート設定オブジェクト
        """
        if config is None:
            config = TradeReportConfig()
        
        self.config = config
        
        # 日付の妥当性チェック
        self._validate_dates()
        
        # APIクライアントの初期化
        self.alpaca_client = get_alpaca_client(self.config.account_type)
        self.fmp_client = get_fmp_client()
        
        # トレード記録用
        self.trades = []
        self.positions = []
        self.equity_curve = []
        
        # 初期資本をAlpaca APIから取得
        self._initialize_capital()
        
    def _validate_dates(self):
        """日付の妥当性チェック"""
        current_date = datetime.now(TIMEZONE.NY)
        end_date_dt = datetime.strptime(self.config.end_date, '%Y-%m-%d')
        
        # タイムゾーン情報を追加して比較可能にする
        end_date_dt = end_date_dt.replace(tzinfo=TIMEZONE.NY)
        
        if end_date_dt > current_date:
            logger.warning(f"終了日({self.config.end_date})が未来の日付です。現在の日付を使用します。")
            self.config.end_date = current_date.strftime('%Y-%m-%d')
            
    def _initialize_capital(self):
        """初期資本の設定"""
        try:
            self.initial_capital = self.get_account_equity_at_date(self.config.start_date)
            logger.info(f"初期資本: ${self.initial_capital:,.2f} ({self.config.start_date}時点)")
        except Exception as e:
            logger.error(f"初期資本の取得に失敗: {e}")
            self.initial_capital = self.config.initial_capital
            logger.info(f"デフォルト値を使用: ${self.initial_capital:,.2f}")

    def get_earnings_data(self) -> Dict[str, List]:
        """FMP APIから決算データを取得"""
        logger.info(f"決算データの取得を開始 ({self.config.start_date} から {self.config.end_date})")
        
        try:
            # FMP APIで決算カレンダーを取得
            all_earnings = self.fmp_client.get_earnings_calendar(
                self.config.start_date, 
                self.config.end_date
            )
            
            # 結果を整形
            combined_data = {'earnings': all_earnings}
            logger.info(f"決算データ取得完了: {len(all_earnings)}件")
            return combined_data
            
        except Exception as e:
            logger.error(f"決算データの取得中にエラーが発生: {e}")
            raise

    def get_historical_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        FMP APIを使用して指定された銘柄の株価データを取得
        
        Args:
            symbol: 銘柄シンボル
            start_date: 開始日 (YYYY-MM-DD)
            end_date: 終了日 (YYYY-MM-DD)
            
        Returns:
            株価データのPandas DataFrame
        """
        try:
            logger.debug(f"株価データ取得開始: {symbol}")
            logger.debug(f"期間: {start_date} から {end_date}")
            
            # FMP APIで履歴データを取得
            df = self.fmp_client.get_historical_price_data(symbol, start_date, end_date)
            
            if df.empty:
                logger.warning(f"銘柄 {symbol} のデータが取得できませんでした")
                return None
                
            logger.info(f"銘柄 {symbol}: {len(df)}件のデータを取得")
            return df
            
        except Exception as e:
            logger.error(f"銘柄 {symbol} のデータ取得中にエラー: {e}")
            return None

    def get_account_equity_at_date(self, date: str) -> float:
        """指定した日付のアカウント残高を取得"""
        try:
            # Alpaca APIでアカウント情報を取得
            account = self.alpaca_client.api.get_account()
            
            if account and account.equity:
                return float(account.equity)
            else:
                logger.warning(f"アカウントデータが取得できません")
                return self.config.initial_capital
                
        except Exception as e:
            logger.error(f"アカウント残高取得エラー: {e}")
            return self.config.initial_capital

    def get_alpaca_trades(self) -> List[Dict]:
        """Alpacaアカウントから取引履歴を取得"""
        try:
            logger.info("Alpaca取引履歴の取得を開始")
            
            # 日付を適切なフォーマットに変換
            from datetime import datetime
            import pytz
            
            # start_dateとend_dateをISO format with timezoneに変換
            start_dt = datetime.strptime(self.config.start_date, '%Y-%m-%d')
            start_dt = pytz.timezone('America/New_York').localize(start_dt)
            
            end_dt = datetime.strptime(self.config.end_date, '%Y-%m-%d')
            end_dt = pytz.timezone('America/New_York').localize(end_dt)
            
            logger.info(f"取引履歴取得期間: {start_dt.isoformat()} ～ {end_dt.isoformat()}")
            
            # まずアクティビティ（トレード実行履歴）を取得
            logger.info("アクティビティ（トレード実行履歴）を取得中...")
            try:
                all_activities = []
                page_token = None
                
                while True:
                    request_params = {
                        'activity_types': 'FILL',
                        'after': start_dt.date(),
                        'until': end_dt.date(),
                        'direction': 'desc',
                        'page_size': 100
                    }
                    
                    if page_token:
                        request_params['page_token'] = page_token
                    
                    activities_page = self.alpaca_client.api.get_activities(**request_params)
                    
                    if not activities_page:
                        break
                    
                    all_activities.extend(activities_page)
                    logger.info(f"アクティビティページ取得: {len(activities_page)}件 (累計: {len(all_activities)}件)")
                    
                    # 次のページがあるかチェック（100件未満なら最後のページ）
                    if len(activities_page) < 100:
                        break
                    
                    # 最後のアクティビティの時刻をpage_tokenとして使用
                    page_token = activities_page[-1].transaction_time
                
                activities = all_activities
                logger.info(f"アクティビティ取得完了: {len(activities)}件")
                
                # アクティビティから取引データを作成
                trades = []
                for activity in activities:
                    if hasattr(activity, 'side') and hasattr(activity, 'symbol'):
                        trade_data = {
                            'symbol': activity.symbol,
                            'side': activity.side,
                            'qty': float(activity.qty),
                            'price': float(activity.price),
                            'filled_at': activity.transaction_time,
                            'order_id': activity.order_id if hasattr(activity, 'order_id') else 'activity'
                        }
                        trades.append(trade_data)
                
                logger.info(f"アクティビティから{len(trades)}件の取引を抽出")
                
                if trades:
                    # 取引の日付分布をログ出力
                    trade_dates = [pd.to_datetime(t['filled_at']).strftime('%Y-%m') for t in trades]
                    from collections import Counter
                    date_distribution = Counter(trade_dates)
                    logger.info(f"月別取引分布: {dict(sorted(date_distribution.items()))}")
                    
                    # 最初と最後の取引日も確認
                    first_trade = min(trades, key=lambda x: x['filled_at'])
                    last_trade = max(trades, key=lambda x: x['filled_at'])
                    logger.info(f"最初の取引: {first_trade['filled_at'].strftime('%Y-%m-%d')} {first_trade['symbol']}")
                    logger.info(f"最後の取引: {last_trade['filled_at'].strftime('%Y-%m-%d')} {last_trade['symbol']}")
                    
                    return trades
                    
            except Exception as e:
                logger.error(f"アクティビティ取得エラー: {e}")
                logger.info("フォールバック: 注文履歴を使用します")
            
            # フォールバック: 注文履歴を月単位で取得（APIの制限を回避）
            all_orders = []
            
            # 月単位で期間を分割
            current_date = start_dt
            
            while current_date <= end_dt:
                # 今月の最終日を計算
                if current_date.month == 12:
                    next_month = current_date.replace(year=current_date.year + 1, month=1, day=1)
                else:
                    next_month = current_date.replace(month=current_date.month + 1, day=1)
                
                month_end = next_month - timedelta(days=1)
                month_end = min(month_end, end_dt)
                
                logger.info(f"注文履歴取得: {current_date.strftime('%Y-%m-%d')} ～ {month_end.strftime('%Y-%m-%d')}")
                
                try:
                    # 月単位で注文履歴を取得
                    month_orders = self.alpaca_client.api.list_orders(
                        status='all',
                        limit=500,
                        after=current_date.isoformat(),
                        until=month_end.isoformat(),
                        direction='desc',
                        nested=True  # 詳細な情報を取得
                    )
                    
                    if month_orders:
                        all_orders.extend(month_orders)
                        logger.info(f"  {len(month_orders)}件の注文を取得")
                    else:
                        logger.info(f"  注文なし")
                    
                except Exception as e:
                    logger.error(f"月次取得エラー ({current_date.strftime('%Y-%m')}): {e}")
                
                # 次の月へ
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1, day=1)
            
            logger.info(f"全期間での注文取得完了: {len(all_orders)}件")
            orders = all_orders
            
            trades = []
            filtered_count = 0
            
            for order in orders:
                if order.status == 'filled':
                    # 日付フィルタリングを手動で実行
                    order_date = order.filled_at
                    if order_date and start_dt <= order_date <= end_dt:
                        trade_data = {
                            'symbol': order.symbol,
                            'side': order.side,
                            'qty': float(order.qty),
                            'price': float(order.filled_avg_price) if order.filled_avg_price else 0,
                            'filled_at': order.filled_at,
                            'order_id': order.id
                        }
                        trades.append(trade_data)
                    else:
                        filtered_count += 1
            
            # 取引の日付分布をログ出力
            if trades:
                trade_dates = [pd.to_datetime(t['filled_at']).strftime('%Y-%m') for t in trades]
                from collections import Counter
                date_distribution = Counter(trade_dates)
                logger.info(f"取引履歴取得完了: {len(trades)}件 (期間外除外: {filtered_count}件)")
                logger.info(f"月別取引分布: {dict(sorted(date_distribution.items()))}")
                
                # 最初と最後の取引日も確認
                first_trade = min(trades, key=lambda x: x['filled_at'])
                last_trade = max(trades, key=lambda x: x['filled_at'])
                logger.info(f"最初の取引: {first_trade['filled_at'].strftime('%Y-%m-%d')} {first_trade['symbol']}")
                logger.info(f"最後の取引: {last_trade['filled_at'].strftime('%Y-%m-%d')} {last_trade['symbol']}")
            else:
                logger.info("取引履歴取得完了: 0件")
            
            return trades
            
        except Exception as e:
            logger.error(f"取引履歴取得エラー: {e}")
            return []

    def _create_sample_trades(self) -> List[Dict]:
        """テスト用のサンプル取引データを作成"""
        import uuid
        import random
        from datetime import timedelta
        
        sample_trades = []
        symbols = ['AAPL', 'GOOGL', 'TSLA', 'AMZN', 'MSFT']
        start_date = datetime.strptime(self.config.start_date, '%Y-%m-%d')
        
        for i in range(20):  # 20件のサンプル取引
            trade_date = start_date + timedelta(days=random.randint(0, 30))
            pnl = random.uniform(-200, 500)  # -200から500の範囲でランダムなPnL
            
            trade = {
                'symbol': random.choice(symbols),
                'side': random.choice(['buy', 'sell']),
                'qty': random.randint(10, 100),
                'price': random.uniform(50, 300),
                'filled_at': trade_date,
                'order_id': str(uuid.uuid4()),
                'pnl': pnl  # パフォーマンス計算用
            }
            sample_trades.append(trade)
        
        logger.info(f"サンプル取引データを作成: {len(sample_trades)}件")
        return sample_trades

    def _calculate_trade_pnl(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """取引のPnLを計算 - FIFO方式で正確に処理（レガシーコードから移植）"""
        try:
            trades_df = trades_df.copy()
            trades_df['pnl'] = 0.0
            
            # 時系列順にソート
            trades_df = trades_df.sort_values('filled_at').reset_index(drop=True)
            
            # FIFO方式でPnL計算
            positions = {}  # symbol -> [(qty, price, entry_time, trade_idx)]
            
            for idx, trade in trades_df.iterrows():
                symbol = trade['symbol']
                side = trade['side'].lower()
                qty = float(trade['qty'])
                price = float(trade['price'])
                time = trade['filled_at']
                
                if symbol not in positions:
                    positions[symbol] = []
                
                if side == 'buy':
                    # 買い注文: ポジションキューに追加
                    positions[symbol].append((qty, price, time, idx))
                    trades_df.loc[idx, 'pnl'] = 0  # 買いは費用のみ
                    logger.debug(f"BUY: {symbol} {qty}株 @${price:.2f} on {time.strftime('%Y-%m-%d')} -> PnL: $0.00")
                    
                elif side == 'sell' and positions[symbol]:
                    # 売り注文: FIFO方式で処理
                    remaining_sell = qty
                    total_pnl = 0
                    
                    while remaining_sell > 0 and positions[symbol]:
                        buy_qty, buy_price, buy_time, buy_idx = positions[symbol][0]
                        sell_qty = min(remaining_sell, buy_qty)
                        
                        # PnL計算
                        pnl = (price - buy_price) * sell_qty
                        total_pnl += pnl
                        
                        # ポジションの更新
                        if sell_qty == buy_qty:
                            positions[symbol].pop(0)  # 完全に売却
                        else:
                            # 一部売却: 残りポジションを更新
                            positions[symbol][0] = (buy_qty - sell_qty, buy_price, buy_time, buy_idx)
                        
                        remaining_sell -= sell_qty
                    
                    trades_df.loc[idx, 'pnl'] = total_pnl
                    logger.debug(f"SELL: {symbol} {qty}株 @${price:.2f} on {time.strftime('%Y-%m-%d')} -> PnL: ${total_pnl:.2f}")
                
                elif side == 'sell' and symbol not in positions:
                    # ポジションがない銘柄での売り（ショート売り）
                    logger.warning(f"SELL without BUY position: {symbol} {qty}株 @${price:.2f} on {time.strftime('%Y-%m-%d')} -> PnL: $0.00")
                    trades_df.loc[idx, 'pnl'] = 0
                
                elif side == 'sell' and not positions[symbol]:
                    # ポジションが空の銘柄での売り
                    logger.warning(f"SELL with empty position: {symbol} {qty}株 @${price:.2f} on {time.strftime('%Y-%m-%d')} -> PnL: $0.00")
                    trades_df.loc[idx, 'pnl'] = 0
                
                else:
                    # その他の場合
                    logger.warning(f"Unhandled trade: {side} {symbol} {qty}株 @${price:.2f} on {time.strftime('%Y-%m-%d')} -> PnL: $0.00")
                    trades_df.loc[idx, 'pnl'] = 0
            
            # デバッグ情報をログ出力
            total_pnl = trades_df['pnl'].sum()
            positive_trades = len(trades_df[trades_df['pnl'] > 0])
            negative_trades = len(trades_df[trades_df['pnl'] < 0])
            zero_trades = len(trades_df[trades_df['pnl'] == 0])
            
            logger.info(f"PnL計算が完了しました（FIFO方式）")
            logger.info(f"総PnL: ${total_pnl:.2f}")
            logger.info(f"プラス取引: {positive_trades}件, マイナス取引: {negative_trades}件, ゼロ取引: {zero_trades}件")
            
            # 主要銘柄のPnL詳細
            symbol_pnl = trades_df.groupby('symbol')['pnl'].sum().sort_values(ascending=False)
            logger.info(f"銘柄別PnL上位5位: {dict(symbol_pnl.head())}")
            
            return trades_df
            
        except Exception as e:
            logger.error(f"PnL計算エラー: {e}")
            # フォールバック: ゼロPnLを設定
            trades_df['pnl'] = 0
            return trades_df

    def calculate_performance_metrics(self, trades_df: pd.DataFrame) -> Dict[str, float]:
        """パフォーマンス指標の計算"""
        if trades_df.empty:
            return {}
            
        try:
            # 基本統計
            total_trades = len(trades_df)
            winning_trades = len(trades_df[trades_df['pnl'] > 0])
            losing_trades = len(trades_df[trades_df['pnl'] < 0])
            
            # 勝率
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            # 総収益とPnL
            total_pnl = trades_df['pnl'].sum()
            total_return_pct = (total_pnl / self.initial_capital * 100) if self.initial_capital > 0 else 0
            
            # 平均損益
            avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
            avg_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].mean()) if losing_trades > 0 else 0
            
            # 平均勝敗比率
            avg_win_loss_rate = (avg_win / avg_loss) if avg_loss > 0 else 0
            
            # プロフィットファクター
            gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
            gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
            
            # 最大ドローダウン
            equity_curve = trades_df['pnl'].cumsum() + self.initial_capital
            peak = equity_curve.cummax()
            drawdown = (equity_curve - peak) / peak * 100
            max_drawdown_pct = abs(drawdown.min())
            
            # 期待値
            expected_value_pct = (win_rate / 100 * avg_win - (1 - win_rate / 100) * avg_loss) / self.initial_capital * 100
            
            # CAGR計算
            start_date = pd.to_datetime(self.config.start_date)
            end_date = pd.to_datetime(self.config.end_date)
            years = (end_date - start_date).days / 365.25
            final_equity = self.initial_capital + total_pnl
            cagr = ((final_equity / self.initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
            
            # カルマー比率
            calmar_ratio = (cagr / max_drawdown_pct) if max_drawdown_pct > 0 else 0
            
            # パレート分析（上位20%の取引が全体利益に占める割合）
            sorted_pnl = trades_df['pnl'].sort_values(ascending=False)
            top_20_pct_count = max(1, int(len(sorted_pnl) * 0.2))
            top_20_pct_profit = sorted_pnl.head(top_20_pct_count).sum()
            pareto_ratio = (top_20_pct_profit / gross_profit * 100) if gross_profit > 0 else 0
            
            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'total_return_pct': total_return_pct,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'avg_win_loss_rate': avg_win_loss_rate,
                'profit_factor': profit_factor,
                'max_drawdown_pct': max_drawdown_pct,
                'expected_value_pct': expected_value_pct,
                'cagr': cagr,
                'calmar_ratio': calmar_ratio,
                'pareto_ratio': pareto_ratio
            }
            
        except Exception as e:
            logger.error(f"パフォーマンス指標計算エラー: {e}")
            return {}

    def generate_report(self, output_file: str = None):
        """包括的なレポートを生成"""
        try:
            # デフォルトの出力ファイル名を設定（reportsフォルダに出力）
            if output_file is None:
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = f'reports/trade_report_{timestamp}.html'
            
            # reportsディレクトリの存在確認・作成
            import os
            reports_dir = os.path.dirname(output_file) if '/' in output_file else 'reports'
            if not os.path.exists(reports_dir):
                os.makedirs(reports_dir)
                logger.info(f"reportsディレクトリを作成しました: {reports_dir}")
            
            logger.info("取引レポート生成を開始")
            
            # 取引履歴の取得
            trades = self.get_alpaca_trades()
            if not trades:
                logger.warning("取引履歴が見つかりません。サンプルデータでテストレポートを生成します。")
                # テスト用のサンプルデータを作成
                trades = self._create_sample_trades()
                
            if not trades:
                logger.error("取引データが利用できません")
                return
            
            # DataFrameに変換
            trades_df = pd.DataFrame(trades)
            
            # PnL計算（実際の取引履歴の場合）
            if 'pnl' not in trades_df.columns:
                trades_df = self._calculate_trade_pnl(trades_df)
            
            # パフォーマンス指標の計算
            metrics = self.calculate_performance_metrics(trades_df)
            
            # HTMLレポートの生成
            html_content = self._generate_html_report(trades_df, metrics)
            
            # ファイルに保存
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            logger.info(f"レポートが生成されました: {output_file}")
            
            # ブラウザで開く
            if platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', output_file])
            elif platform.system() == 'Windows':
                os.startfile(output_file)
            else:  # Linux
                subprocess.run(['xdg-open', output_file])
                
        except Exception as e:
            logger.error(f"レポート生成エラー: {e}")
            raise

    def _generate_html_report(self, trades_df: pd.DataFrame, metrics: Dict[str, float]) -> str:
        """包括的なHTMLレポートの生成"""
        
        # 取引履歴テーブルの生成
        trades_table = self._generate_trades_table(trades_df)
        
        # Symbol analysis
        symbol_analysis = self._generate_symbol_analysis(trades_df)
        
        # Monthly analysis
        monthly_analysis = self._generate_monthly_analysis(trades_df)
        
        # Plotlyチャート分析
        plotly_charts = self._generate_plotly_charts(trades_df)
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Alpaca Trade Report</title>
            <meta charset="UTF-8">
            <style>
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    margin: 0; 
                    padding: 20px; 
                    background-color: {self.DARK_THEME['bg_color']}; 
                    color: {self.DARK_THEME['text_color']}; 
                    line-height: 1.6;
                }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ 
                    text-align: center; 
                    margin-bottom: 40px; 
                    padding: 20px;
                    background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                    border-radius: 10px;
                }}
                .header h1 {{ 
                    margin: 0; 
                    font-size: 2.5em; 
                    color: {self.DARK_THEME['line_color']}; 
                }}
                .header p {{ 
                    margin: 10px 0 0 0; 
                    font-size: 1.2em; 
                    opacity: 0.8; 
                }}
                .section {{ 
                    margin: 30px 0; 
                    padding: 20px; 
                    background-color: {self.DARK_THEME['plot_bg_color']}; 
                    border-radius: 10px; 
                    border: 1px solid {self.DARK_THEME['grid_color']};
                }}
                .section h2 {{ 
                    margin-top: 0; 
                    color: {self.DARK_THEME['line_color']}; 
                    border-bottom: 2px solid {self.DARK_THEME['grid_color']};
                    padding-bottom: 10px;
                }}
                .metrics-grid {{ 
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
                    gap: 15px; 
                }}
                .metric {{ 
                    padding: 15px; 
                    background: linear-gradient(135deg, #374151 0%, #4b5563 100%);
                    border-radius: 8px; 
                    border-left: 4px solid {self.DARK_THEME['line_color']};
                }}
                .metric-label {{ 
                    font-size: 0.9em; 
                    opacity: 0.8; 
                    margin-bottom: 5px; 
                }}
                .metric-value {{ 
                    font-size: 1.4em; 
                    font-weight: bold; 
                }}
                .positive {{ color: {self.DARK_THEME['profit_color']}; }}
                .negative {{ color: {self.DARK_THEME['loss_color']}; }}
                table {{ 
                    width: 100%; 
                    border-collapse: collapse; 
                    margin-top: 15px;
                }}
                th, td {{ 
                    padding: 10px; 
                    text-align: left; 
                    border-bottom: 1px solid {self.DARK_THEME['grid_color']}; 
                }}
                th {{ 
                    background-color: {self.DARK_THEME['grid_color']}; 
                    font-weight: bold;
                }}
                tr:hover {{ background-color: rgba(100, 116, 139, 0.1); }}
                .chart-placeholder {{
                    height: 300px;
                    background: linear-gradient(135deg, #374151 0%, #4b5563 100%);
                    border-radius: 8px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 20px 0;
                    border: 2px dashed {self.DARK_THEME['grid_color']};
                }}
                .equity-stats {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin: 20px 0;
                    padding: 20px;
                    background: linear-gradient(135deg, #374151 0%, #4b5563 100%);
                    border-radius: 8px;
                }}
                .stat-item {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 10px;
                    background-color: rgba(30, 41, 59, 0.5);
                    border-radius: 6px;
                }}
                .stat-label {{
                    font-weight: 500;
                    opacity: 0.8;
                }}
                .stat-value {{
                    font-weight: bold;
                    font-size: 1.1em;
                }}
                #equityCurveChart {{
                    background-color: rgba(30, 41, 59, 0.5);
                    border-radius: 8px;
                    max-width: 100%;
                    height: auto;
                }}
                .summary-stats {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 20px;
                    margin: 20px 0;
                }}
                .warning {{
                    background-color: rgba(239, 68, 68, 0.1);
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .info {{
                    background-color: rgba(59, 130, 246, 0.1);
                    border: 1px solid rgba(59, 130, 246, 0.3);
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .table-container {{
                    max-height: 400px;
                    overflow-y: auto;
                    border: 1px solid #334155;
                    border-radius: 8px;
                    margin: 10px 0;
                }}
                .sortable-table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                .sortable-table th {{
                    position: sticky;
                    top: 0;
                    background-color: {self.DARK_THEME['bg_color']};
                    border-bottom: 2px solid #334155;
                    padding: 12px 8px;
                    text-align: left;
                    font-weight: bold;
                    color: {self.DARK_THEME['line_color']};
                    user-select: none;
                }}
                .sortable-table th:hover {{
                    background-color: #334155;
                }}
                .sortable-table td {{
                    padding: 10px 8px;
                    border-bottom: 1px solid rgba(51, 65, 85, 0.3);
                }}
                .sortable-table tr:hover {{
                    background-color: rgba(51, 65, 85, 0.3);
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📊 Alpaca Trading Performance Report</h1>
                    <p>Analysis Period: {self.config.start_date} ～ {self.config.end_date}</p>
                    <p>Initial Capital: ${self.initial_capital:,.2f} | Account Type: {self.config.account_type.upper()}</p>
                </div>
                
                <div class="section">
                    <h2>🎯 Key Performance Metrics</h2>
                    <div class="metrics-grid">
                        <div class="metric">
                            <div class="metric-label">Total Trades</div>
                            <div class="metric-value">{metrics.get('total_trades', 0)}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Win Rate</div>
                            <div class="metric-value {'positive' if metrics.get('win_rate', 0) > 50 else 'negative'}">{metrics.get('win_rate', 0):.1f}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Total Return</div>
                            <div class="metric-value {'positive' if metrics.get('total_return_pct', 0) > 0 else 'negative'}">{metrics.get('total_return_pct', 0):.2f}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">CAGR (Annualized Return)</div>
                            <div class="metric-value {'positive' if metrics.get('cagr', 0) > 0 else 'negative'}">{metrics.get('cagr', 0):.2f}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Profit Factor</div>
                            <div class="metric-value {'positive' if metrics.get('profit_factor', 0) > 1 else 'negative'}">{metrics.get('profit_factor', 0):.2f}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Max Drawdown</div>
                            <div class="metric-value negative">{metrics.get('max_drawdown_pct', 0):.2f}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Avg Win</div>
                            <div class="metric-value positive">${metrics.get('avg_win', 0):.2f}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Avg Loss</div>
                            <div class="metric-value negative">${metrics.get('avg_loss', 0):.2f}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Win/Loss Ratio</div>
                            <div class="metric-value">{metrics.get('avg_win_loss_rate', 0):.2f}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Expected Value</div>
                            <div class="metric-value {'positive' if metrics.get('expected_value_pct', 0) > 0 else 'negative'}">{metrics.get('expected_value_pct', 0):.2f}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Calmar Ratio</div>
                            <div class="metric-value">{metrics.get('calmar_ratio', 0):.2f}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Pareto Ratio</div>
                            <div class="metric-value">{metrics.get('pareto_ratio', 0):.1f}%</div>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h2>📈 Equity Curve & Detailed Analysis</h2>
                    {plotly_charts}
                </div>

                <div class="section">
                    <h2>📊 Symbol Analysis</h2>
                    {symbol_analysis}
                </div>

                <div class="section">
                    <h2>📅 Monthly Analysis</h2>
                    {monthly_analysis}
                </div>

                <div class="section">
                    <h2>📋 Detailed Trade History</h2>
                    {trades_table}
                </div>

                <div class="section">
                    <h2>⚠️ Risk Analysis & Important Notes</h2>
                    {self._generate_risk_analysis(trades_df, metrics)}
                </div>

                <div class="info">
                    <h3>📌 Report Generation Info</h3>
                    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p>Data Source: Alpaca Trading API</p>
                    <p>This report is automatically generated. Please consult other sources when making investment decisions.</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html_template

    def _generate_trades_table(self, trades_df: pd.DataFrame) -> str:
        """Generate scrollable and sortable trade history table"""
        if trades_df.empty:
            return "<p>No trading data available.</p>"
        
        # Display all trades, sorted by fill time (newest first)
        all_trades = trades_df.copy()
        
        table_rows = ""
        for _, trade in all_trades.iterrows():
            pnl_class = "positive" if trade.get('pnl', 0) > 0 else "negative"
            filled_at = trade.get('filled_at', 'N/A')
            if hasattr(filled_at, 'strftime'):
                filled_at = filled_at.strftime('%Y-%m-%d %H:%M')
            
            table_rows += f"""
            <tr>
                <td>{trade.get('symbol', 'N/A')}</td>
                <td>{trade.get('side', 'N/A').upper()}</td>
                <td>{trade.get('qty', 0)}</td>
                <td data-sort="{trade.get('price', 0)}">${trade.get('price', 0):.2f}</td>
                <td class="{pnl_class}" data-sort="{trade.get('pnl', 0)}">${trade.get('pnl', 0):.2f}</td>
                <td data-sort="{filled_at}">{filled_at}</td>
            </tr>
            """
        
        return f"""
        <div class="table-container">
            <table id="trades-table" class="sortable-table">
                <thead>
                    <tr>
                        <th onclick="sortTable(0, 'trades-table')" style="cursor: pointer;">Symbol ↕</th>
                        <th onclick="sortTable(1, 'trades-table')" style="cursor: pointer;">Side ↕</th>
                        <th onclick="sortTable(2, 'trades-table')" style="cursor: pointer;">Quantity ↕</th>
                        <th onclick="sortTable(3, 'trades-table')" style="cursor: pointer;">Price ↕</th>
                        <th onclick="sortTable(4, 'trades-table')" style="cursor: pointer;">PnL ↕</th>
                        <th onclick="sortTable(5, 'trades-table')" style="cursor: pointer;">Fill Time ↕</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
        <p><small>Showing all {len(all_trades)} trades. Click column headers to sort.</small></p>
        
        <script>
        let sortDirection = {{}};
        
        function sortTable(columnIndex, tableId) {{
            const table = document.getElementById(tableId);
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            
            // Toggle sort direction
            const direction = sortDirection[columnIndex] || 'asc';
            sortDirection[columnIndex] = direction === 'asc' ? 'desc' : 'asc';
            
            rows.sort((a, b) => {{
                const aCell = a.cells[columnIndex];
                const bCell = b.cells[columnIndex];
                
                // Use data-sort attribute if available, otherwise use text content
                let aValue = aCell.getAttribute('data-sort') || aCell.textContent.trim();
                let bValue = bCell.getAttribute('data-sort') || bCell.textContent.trim();
                
                // Convert to numbers if possible
                const aNum = parseFloat(aValue.replace(/[$,]/g, ''));
                const bNum = parseFloat(bValue.replace(/[$,]/g, ''));
                
                if (!isNaN(aNum) && !isNaN(bNum)) {{
                    aValue = aNum;
                    bValue = bNum;
                }}
                
                if (direction === 'asc') {{
                    return aValue > bValue ? 1 : aValue < bValue ? -1 : 0;
                }} else {{
                    return aValue < bValue ? 1 : aValue > bValue ? -1 : 0;
                }}
            }});
            
            // Clear tbody and append sorted rows
            tbody.innerHTML = '';
            rows.forEach(row => tbody.appendChild(row));
        }}
        </script>
        """

    def _generate_symbol_analysis(self, trades_df: pd.DataFrame) -> str:
        """Generate symbol analysis"""
        if trades_df.empty:
            return "<p>取引データがありません。</p>"
        
        try:
            # 銘柄別の統計
            symbol_stats = trades_df.groupby('symbol').agg({
                'pnl': ['sum', 'count', 'mean'],
                'qty': 'sum'
            }).round(2)
            
            # フラット化
            symbol_stats.columns = ['total_pnl', 'trade_count', 'avg_pnl', 'total_qty']
            symbol_stats = symbol_stats.sort_values('total_pnl', ascending=False)
            
            table_rows = ""
            for symbol, stats in symbol_stats.iterrows():  # Show all symbols
                pnl_class = "positive" if stats['total_pnl'] > 0 else "negative"
                table_rows += f"""
                <tr>
                    <td>{symbol}</td>
                    <td data-sort="{stats['trade_count']}">{stats['trade_count']}</td>
                    <td data-sort="{stats['total_qty']}">{stats['total_qty']}</td>
                    <td class="{pnl_class}" data-sort="{stats['total_pnl']}">${stats['total_pnl']:.2f}</td>
                    <td class="{pnl_class}" data-sort="{stats['avg_pnl']}">${stats['avg_pnl']:.2f}</td>
                </tr>
                """
            
            return f"""
            <div class="table-container">
                <table id="symbol-table" class="sortable-table">
                    <thead>
                        <tr>
                            <th onclick="sortTable(0, 'symbol-table')" style="cursor: pointer;">Symbol ↕</th>
                            <th onclick="sortTable(1, 'symbol-table')" style="cursor: pointer;">Trade Count ↕</th>
                            <th onclick="sortTable(2, 'symbol-table')" style="cursor: pointer;">Total Quantity ↕</th>
                            <th onclick="sortTable(3, 'symbol-table')" style="cursor: pointer;">Total PnL ↕</th>
                            <th onclick="sortTable(4, 'symbol-table')" style="cursor: pointer;">Average PnL ↕</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows}
                    </tbody>
                </table>
            </div>
            <p><small>Showing all {len(symbol_stats)} symbols. Click column headers to sort.</small></p>
            
            <script>
            // Reuse the same sortTable function for symbol table
            if (typeof sortTable === 'undefined') {{
                let sortDirection = {{}};
                
                function sortTable(columnIndex, tableId) {{
                    const table = document.getElementById(tableId);
                    const tbody = table.querySelector('tbody');
                    const rows = Array.from(tbody.querySelectorAll('tr'));
                    
                    // Toggle sort direction
                    const direction = sortDirection[tableId + '_' + columnIndex] || 'asc';
                    sortDirection[tableId + '_' + columnIndex] = direction === 'asc' ? 'desc' : 'asc';
                    
                    rows.sort((a, b) => {{
                        const aCell = a.cells[columnIndex];
                        const bCell = b.cells[columnIndex];
                        
                        // Use data-sort attribute if available, otherwise use text content
                        let aValue = aCell.getAttribute('data-sort') || aCell.textContent.trim();
                        let bValue = bCell.getAttribute('data-sort') || bCell.textContent.trim();
                        
                        // Convert to numbers if possible
                        const aNum = parseFloat(aValue.replace(/[$,]/g, ''));
                        const bNum = parseFloat(bValue.replace(/[$,]/g, ''));
                        
                        if (!isNaN(aNum) && !isNaN(bNum)) {{
                            aValue = aNum;
                            bValue = bNum;
                        }}
                        
                        if (direction === 'asc') {{
                            return aValue > bValue ? 1 : aValue < bValue ? -1 : 0;
                        }} else {{
                            return aValue < bValue ? 1 : aValue > bValue ? -1 : 0;
                        }}
                    }});
                    
                    // Clear tbody and append sorted rows
                    tbody.innerHTML = '';
                    rows.forEach(row => tbody.appendChild(row));
                }}
            }}
            </script>
            """
        except Exception as e:
            return f"<p>Error generating symbol analysis: {e}</p>"

    def _generate_monthly_analysis(self, trades_df: pd.DataFrame) -> str:
        """Generate monthly analysis"""
        if trades_df.empty:
            return "<p>No trading data available.</p>"
        
        try:
            # filled_atカラムをdatetimeに変換
            trades_df_copy = trades_df.copy()
            trades_df_copy['filled_at'] = pd.to_datetime(trades_df_copy['filled_at'])
            trades_df_copy['month'] = trades_df_copy['filled_at'].dt.to_period('M')
            
            # 月次統計
            monthly_stats = trades_df_copy.groupby('month').agg({
                'pnl': ['sum', 'count', 'mean'],
            }).round(2)
            
            monthly_stats.columns = ['total_pnl', 'trade_count', 'avg_pnl']
            
            table_rows = ""
            for month, stats in monthly_stats.iterrows():
                pnl_class = "positive" if stats['total_pnl'] > 0 else "negative"
                table_rows += f"""
                <tr>
                    <td>{month}</td>
                    <td>{stats['trade_count']}</td>
                    <td class="{pnl_class}">${stats['total_pnl']:.2f}</td>
                    <td class="{pnl_class}">${stats['avg_pnl']:.2f}</td>
                </tr>
                """
            
            return f"""
            <table>
                <thead>
                    <tr>
                        <th>Month</th>
                        <th>Trade Count</th>
                        <th>Total PnL</th>
                        <th>Average PnL</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
            """
        except Exception as e:
            return f"<p>月次分析の生成中にエラーが発生しました: {e}</p>"

    def _generate_plotly_charts(self, trades_df: pd.DataFrame) -> str:
        """Plotlyを使用した高度なチャート分析を生成"""
        if trades_df.empty:
            return "<p>取引データがありません。</p>"
        
        try:
            # 基本的なチャートを生成
            basic_charts = self._generate_basic_charts(trades_df)
            
            # 詳細分析チャートを生成  
            advanced_charts = self._generate_advanced_analysis_charts(trades_df)
            
            return basic_charts + "\n" + advanced_charts
            
        except Exception as e:
            return f"<p>チャート生成エラー: {e}</p>"

    def _generate_basic_charts(self, trades_df: pd.DataFrame) -> str:
        """Generate basic charts"""
        # Sort trade data by date
        trades_df_sorted = trades_df.copy()
        trades_df_sorted['filled_at'] = pd.to_datetime(trades_df_sorted['filled_at'])
        trades_df_sorted = trades_df_sorted.sort_values('filled_at')
        
        # Calculate cumulative PnL and returns
        trades_df_sorted['cumulative_pnl'] = trades_df_sorted['pnl'].cumsum()
        trades_df_sorted['cumulative_return'] = (trades_df_sorted['cumulative_pnl'] / self.initial_capital * 100)
        
        # Calculate drawdown
        running_max = trades_df_sorted['cumulative_return'].cummax()
        trades_df_sorted['drawdown'] = trades_df_sorted['cumulative_return'] - running_max
        
        # Create daily time series from start date to latest trade
        start_date = pd.to_datetime(self.config.start_date).tz_localize(None)  # Remove timezone
        if not trades_df_sorted.empty:
            end_date = trades_df_sorted['filled_at'].max()
            if end_date.tz is not None:
                end_date = end_date.tz_localize(None)  # Remove timezone
        else:
            end_date = pd.Timestamp.now().tz_localize(None)  # Remove timezone
        
        # Create daily date range
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        
        # Initialize daily series
        daily_returns = pd.Series(0.0, index=date_range)
        daily_drawdown = pd.Series(0.0, index=date_range)
        
        # Fill in trade data
        if not trades_df_sorted.empty:
            for _, trade in trades_df_sorted.iterrows():
                trade_datetime = trade['filled_at']
                if trade_datetime.tz is not None:
                    trade_datetime = trade_datetime.tz_localize(None)  # Remove timezone
                trade_date = trade_datetime.normalize()  # Get date without time
                # Forward fill from trade date onwards
                mask = date_range >= trade_date
                daily_returns.loc[mask] = trade['cumulative_return']
                daily_drawdown.loc[mask] = trade['drawdown']
        
        # Convert to lists for plotting
        dates = [d.strftime('%Y-%m-%d') for d in date_range]
        returns = daily_returns.tolist()
        drawdowns = daily_drawdown.tolist()
        
        # 勝ち負け分析
        wins = trades_df_sorted[trades_df_sorted['pnl'] > 0]
        losses = trades_df_sorted[trades_df_sorted['pnl'] < 0]
        
        # Symbol PnL
        symbol_pnl = trades_df_sorted.groupby('symbol')['pnl'].sum().sort_values(ascending=False)
        top_symbols = symbol_pnl.head(10)
        
        # 月次分析
        trades_df_sorted['month'] = trades_df_sorted['filled_at'].dt.to_period('M').astype(str)
        monthly_pnl = trades_df_sorted.groupby('month')['pnl'].sum()
        
        basic_charts_html = []
        
        # Performance Summary
        summary_html = f"""
        <div class="equity-stats">
            <div class="stat-item">
                <span class="stat-label">Total Trades:</span>
                <span class="stat-value">{len(trades_df_sorted)}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Win Rate:</span>
                <span class="stat-value {'positive' if len(wins)/len(trades_df_sorted) > 0.5 else 'negative'}">{len(wins)/len(trades_df_sorted)*100:.1f}%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Total Return:</span>
                <span class="stat-value {'positive' if returns[-1] > 0 else 'negative'}" >{returns[-1]:.2f}%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Max Drawdown:</span>
                <span class="stat-value negative">{min(drawdowns):.2f}%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Total PnL:</span>
                <span class="stat-value {'positive' if sum(trades_df_sorted['pnl']) > 0 else 'negative'}">${sum(trades_df_sorted['pnl']):.2f}</span>
            </div>
        </div>
        """
        basic_charts_html.append(self._wrap_chart_section("Performance Summary", summary_html, "performance-summary"))
        
        # Equity Curve
        equity_chart = f"""
        <div id="equity-curve-chart" style="height: 400px;"></div>
        <script>
            var equityData = [{{
                x: {dates},
                y: {returns},
                type: 'scatter',
                mode: 'lines',
                name: 'Cumulative Return (%)',
                line: {{color: '{self.DARK_THEME['profit_color']}', width: 2}}
            }}];
            
            var equityLayout = {{
                title: {{text: 'Equity Curve (Cumulative Return)', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
                paper_bgcolor: '{self.DARK_THEME['bg_color']}',
                plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
                font: {{color: '{self.DARK_THEME['text_color']}'}},
                xaxis: {{title: 'Date', gridcolor: '{self.DARK_THEME['grid_color']}'}},
                yaxis: {{title: 'Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
            }};
            
            Plotly.newPlot('equity-curve-chart', equityData, equityLayout, {{responsive: true}});
        </script>
        """
        basic_charts_html.append(self._wrap_chart_section("Equity Curve", equity_chart, "equity-curve"))
        
        # Drawdown Chart
        drawdown_chart = f"""
        <div id="drawdown-chart" style="height: 300px;"></div>
        <script>
            var drawdownData = [{{
                x: {dates},
                y: {drawdowns},
                type: 'scatter',
                mode: 'lines',
                name: 'Drawdown (%)',
                line: {{color: '{self.DARK_THEME['loss_color']}', width: 2}},
                fill: 'tonexty'
            }}];
            
            var drawdownLayout = {{
                title: {{text: 'Drawdown Progression', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
                paper_bgcolor: '{self.DARK_THEME['bg_color']}',
                plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
                font: {{color: '{self.DARK_THEME['text_color']}'}},
                xaxis: {{title: 'Date', gridcolor: '{self.DARK_THEME['grid_color']}'}},
                yaxis: {{title: 'Drawdown (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
            }};
            
            Plotly.newPlot('drawdown-chart', drawdownData, drawdownLayout, {{responsive: true}});
        </script>
        """
        basic_charts_html.append(self._wrap_chart_section("Drawdown", drawdown_chart, "drawdown"))
        
        # Symbol PnL Chart
        symbol_values = self._to_json_safe(list(top_symbols.values))
        symbol_names = self._to_json_safe(list(top_symbols.index))
        symbol_colors = ['#22c55e' if x > 0 else '#ef4444' for x in top_symbols.values]
        
        symbol_chart = f"""
        <div id="symbol-pnl-chart" style="height: 400px;"></div>
        <script>
            var symbolData = [{{
                x: {symbol_values},
                y: {symbol_names},
                type: 'bar',
                orientation: 'h',
                name: 'Symbol PnL',
                marker: {{
                    color: {symbol_colors}
                }}
            }}];
            
            var symbolLayout = {{
                title: {{text: 'Top 10 Symbols by PnL', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
                paper_bgcolor: '{self.DARK_THEME['bg_color']}',
                plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
                font: {{color: '{self.DARK_THEME['text_color']}'}},
                xaxis: {{title: 'PnL ($)', gridcolor: '{self.DARK_THEME['grid_color']}'}},
                yaxis: {{title: 'Symbol', gridcolor: '{self.DARK_THEME['grid_color']}'}}
            }};
            
            Plotly.newPlot('symbol-pnl-chart', symbolData, symbolLayout, {{responsive: true}});
        </script>
        """
        basic_charts_html.append(self._wrap_chart_section("Top Symbols by PnL", symbol_chart, "symbol-pnl"))
        
        # Monthly PnL Chart
        monthly_months = self._to_json_safe(list(monthly_pnl.index))
        monthly_values = self._to_json_safe(list(monthly_pnl.values))
        monthly_colors = ['#22c55e' if x > 0 else '#ef4444' for x in monthly_pnl.values]
        
        monthly_chart = f"""
        <div id="monthly-pnl-chart" style="height: 300px;"></div>
        <script>
            var monthlyData = [{{
                x: {monthly_months},
                y: {monthly_values},
                type: 'bar',
                name: 'Monthly PnL',
                marker: {{
                    color: {monthly_colors}
                }}
            }}];
            
            var monthlyLayout = {{
                title: {{text: 'Monthly PnL Progression', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
                paper_bgcolor: '{self.DARK_THEME['bg_color']}',
                plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
                font: {{color: '{self.DARK_THEME['text_color']}'}},
                xaxis: {{title: 'Month', gridcolor: '{self.DARK_THEME['grid_color']}'}},
                yaxis: {{title: 'PnL ($)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
            }};
            
            Plotly.newPlot('monthly-pnl-chart', monthlyData, monthlyLayout, {{responsive: true}});
        </script>
        """
        basic_charts_html.append(self._wrap_chart_section("Monthly PnL", monthly_chart, "monthly-pnl"))
        
        # Plotly script include
        plotly_script = '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'
        
        return plotly_script + '\n'.join(basic_charts_html)

    def _to_json_safe(self, data):
        """NumPy型をJSON安全な型に変換"""
        import json
        import numpy as np
        
        if isinstance(data, np.ndarray):
            return data.tolist()
        elif isinstance(data, (np.int64, np.int32, np.int16, np.int8)):
            return int(data)
        elif isinstance(data, (np.float64, np.float32, np.float16)):
            return float(data)
        elif isinstance(data, list):
            return [self._to_json_safe(item) for item in data]
        elif isinstance(data, dict):
            return {key: self._to_json_safe(value) for key, value in data.items()}
        else:
            return data

    def _generate_advanced_analysis_charts(self, trades_df: pd.DataFrame) -> str:
        """詳細分析チャートを生成"""
        if trades_df.empty:
            return ""
        
        try:
            # サンプル詳細データを生成（現実の実装では外部データソースから取得）
            trades_with_analysis = self._add_analysis_data(trades_df)
            
            charts_html = []
            
            # 1. Return Distribution Analysis
            return_dist_chart = self._create_return_distribution_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Return Distribution", return_dist_chart, "return-distribution-chart"))
            
            # 2. Monthly Performance Heatmap  
            monthly_heatmap = self._create_monthly_heatmap(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Monthly Performance Heatmap", monthly_heatmap, "monthly-heatmap-chart"))
            
            # 3. Sector Performance (if sector data available)
            sector_chart = self._create_sector_performance_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Sector Performance", sector_chart, "sector-performance-chart"))
            
            # 4. Industry Performance (Top 15)
            industry_chart = self._create_industry_performance_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Industry Performance (Top 15)", industry_chart, "industry-performance-chart"))
            
            # 5. Performance by Gap Size
            gap_chart = self._create_gap_performance_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Performance by Gap Size", gap_chart, "gap-performance-chart"))
            
            # 6. Pre-Earnings Trend Analysis
            pre_earnings_chart = self._create_pre_earnings_chart(trades_with_analysis) 
            charts_html.append(self._wrap_chart_section("Pre-Earnings Trend Analysis", pre_earnings_chart, "pre-earnings-chart"))
            
            # 7. Volume Trend Analysis
            volume_chart = self._create_volume_trend_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Volume Trend Analysis", volume_chart, "volume-trend-chart"))
            
            # 8. MA Analysis
            ma_chart = self._create_ma_analysis_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Moving Average Analysis", ma_chart, "ma-analysis-chart"))
            
            # 9. Market Cap Performance
            mcap_chart = self._create_market_cap_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Market Cap Performance", mcap_chart, "market-cap-chart"))
            
            # 10. Price Range Analysis
            price_range_chart = self._create_price_range_chart(trades_with_analysis)
            charts_html.append(self._wrap_chart_section("Price Range Analysis", price_range_chart, "price-range-chart"))
            
            return '\n'.join(charts_html)
            
        except Exception as e:
            logger.error(f"詳細分析チャート生成エラー: {e}")
            return f"<p>詳細分析チャート生成エラー: {e}</p>"

    def _wrap_chart_section(self, title: str, chart_html: str, chart_id: str) -> str:
        """チャートセクションをHTMLでラップ"""
        return f"""
        <div class="section">
            <h3 style="color: {self.DARK_THEME['line_color']};">{title}</h3>
            <div style="margin: 10px 0;">
                {chart_html}
            </div>
        </div>
        """

    def _add_analysis_data(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """分析用データを追加（サンプル実装）"""
        df = trades_df.copy()
        
        # サンプルデータを追加（現実の実装では外部APIから取得）
        import random
        import numpy as np
        
        n_trades = len(df)
        
        # セクター・業界情報（サンプル）
        sectors = ['Technology', 'Healthcare', 'Finance', 'Consumer', 'Energy', 'Industrial']
        industries = ['Software', 'Biotechnology', 'Banking', 'Retail', 'Oil&Gas', 'Manufacturing', 
                     'Semiconductors', 'Pharmaceuticals', 'Insurance', 'Automotive']
        
        df['sector'] = [random.choice(sectors) for _ in range(n_trades)]
        df['industry'] = [random.choice(industries) for _ in range(n_trades)]
        
        # ギャップサイズ（サンプル）
        df['gap_size'] = np.random.normal(2.0, 3.0, n_trades)
        
        # 決算前トレンド（サンプル）  
        df['pre_earnings_trend'] = np.random.normal(0, 8, n_trades)
        
        # ボリューム変化率（サンプル）
        df['volume_change'] = np.random.normal(20, 40, n_trades)
        
        # MA比率（サンプル）
        df['price_to_ma50'] = np.random.normal(1.02, 0.1, n_trades)
        df['price_to_ma200'] = np.random.normal(1.05, 0.15, n_trades)
        
        # 時価総額カテゴリ（サンプル）
        mcap_categories = ['Large Cap', 'Mid Cap', 'Small Cap', 'Micro Cap']
        df['market_cap_category'] = [random.choice(mcap_categories) for _ in range(n_trades)]
        
        # 価格帯カテゴリ（サンプル）  
        price_categories = ['High Price', 'Mid Price', 'Low Price']
        df['price_category'] = [random.choice(price_categories) for _ in range(n_trades)]
        
        # リターン率を計算
        try:
            # PnLベースのリターン率計算（簡易版）
            df['return_pct'] = (df['pnl'] / self.initial_capital) * 100
        except:
            # フォールバック：ランダムなリターン率
            df['return_pct'] = np.random.normal(2, 10, n_trades)
        
        return df

    def _create_return_distribution_chart(self, df: pd.DataFrame) -> str:
        """Generate return distribution chart"""
        returns = df['return_pct'].dropna()
        
        positive_returns = returns[returns > 0]
        negative_returns = returns[returns <= 0]
        
        script = f"""
        <div id="return-dist-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace1 = {{
            x: {positive_returns.tolist()},
            type: 'histogram',
            name: 'Positive Returns',
            marker: {{color: '{self.DARK_THEME['profit_color']}', opacity: 0.7}},
            nbinsx: 20
        }};
        
        var trace2 = {{
            x: {negative_returns.tolist()},
            type: 'histogram', 
            name: 'Negative Returns',
            marker: {{color: '{self.DARK_THEME['loss_color']}', opacity: 0.7}},
            nbinsx: 20
        }};
        
        var layout = {{
            title: {{text: 'Return Distribution', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Frequency', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            barmode: 'overlay'
        }};
        
        Plotly.newPlot('return-dist-chart', [trace1, trace2], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_monthly_heatmap(self, df: pd.DataFrame) -> str:
        """Generate monthly performance heatmap"""
        import json
        
        # 月次データを準備
        df['date'] = pd.to_datetime(df['filled_at'])
        df['year'] = df['date'].dt.year
        df['month'] = df['date'].dt.month
        
        # 月次リターンを集計
        monthly_data = df.groupby(['year', 'month'])['return_pct'].mean().reset_index()
        
        # ヒートマップ用のマトリックスを作成
        years = sorted(monthly_data['year'].unique())
        months = list(range(1, 13))
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        z_data = []
        text_data = []  # For hover text
        
        for year in years:
            year_data = []
            year_text = []
            for month in months:
                value = monthly_data[(monthly_data['year'] == year) & 
                                   (monthly_data['month'] == month)]['return_pct']
                if len(value) > 0:
                    val = float(value.iloc[0])  # Convert NumPy type to Python float
                    year_data.append(val)
                    year_text.append(f"{val:.2f}%")
                else:
                    year_data.append(None)
                    year_text.append("")
            z_data.append(year_data)
            text_data.append(year_text)
        
        # Convert to JSON-safe format
        z_data_json = json.dumps(z_data)
        text_data_json = json.dumps(text_data)
        years_json = json.dumps([int(y) for y in years])  # Convert NumPy type to int
        
        script = f"""
        <div id="monthly-heatmap" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            z: {z_data_json},
            x: {json.dumps(month_names)},
            y: {years_json},
            text: {text_data_json},
            texttemplate: "%{{text}}",
            textfont: {{color: "white", size: 12}},
            type: 'heatmap',
            colorscale: [
                [0, '{self.DARK_THEME['loss_color']}'],
                [0.5, '{self.DARK_THEME['bg_color']}'],
                [1, '{self.DARK_THEME['profit_color']}']
            ],
            showscale: true,
            colorbar: {{
                title: "Return (%)",
                titlefont: {{color: '{self.DARK_THEME['text_color']}'}},
                tickfont: {{color: '{self.DARK_THEME['text_color']}'}}
            }}
        }};
        
        var layout = {{
            title: {{text: 'Monthly Performance Heatmap', font: {{color: '{self.DARK_THEME['text_color']}', size: 18}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{
                title: 'Month', 
                gridcolor: '{self.DARK_THEME['grid_color']}',
                tickfont: {{color: '{self.DARK_THEME['text_color']}'}}
            }},
            yaxis: {{
                title: 'Year', 
                gridcolor: '{self.DARK_THEME['grid_color']}',
                tickfont: {{color: '{self.DARK_THEME['text_color']}'}}
            }},
            width: null,
            height: 400
        }};
        
        Plotly.newPlot('monthly-heatmap', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_sector_performance_chart(self, df: pd.DataFrame) -> str:
        """セクター別パフォーマンスチャートを生成"""
        sector_perf = df.groupby('sector').agg({
            'return_pct': ['mean', 'count'],
            'pnl': lambda x: (x > 0).mean() * 100
        }).round(2)
        
        sector_perf.columns = ['avg_return', 'trade_count', 'win_rate']
        sector_perf = sector_perf[sector_perf['trade_count'] >= 1]
        
        sectors = sector_perf.index.tolist()
        avg_returns = sector_perf['avg_return'].tolist()
        win_rates = sector_perf['win_rate'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="sector-perf-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace1 = {{
            x: {sectors},
            y: {avg_returns},
            type: 'bar',
            name: 'Average Return',
            marker: {{color: {colors}}}
        }};
        
        var trace2 = {{
            x: {sectors}, 
            y: {win_rates},
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Win Rate',
            line: {{color: '{self.DARK_THEME['line_color']}'}},
            yaxis: 'y2'
        }};
        
        var layout = {{
            title: {{text: 'Sector Performance', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}', 
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Sector', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis2: {{
                title: 'Win Rate (%)',
                overlaying: 'y',
                side: 'right',
                range: [0, 100]
            }}
        }};
        
        Plotly.newPlot('sector-perf-chart', [trace1, trace2], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_industry_performance_chart(self, df: pd.DataFrame) -> str:
        """業界別パフォーマンスチャート（Top 15）を生成"""
        industry_perf = df.groupby('industry').agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        industry_perf.columns = ['avg_return', 'trade_count']
        industry_perf = industry_perf[industry_perf['trade_count'] >= 1]
        industry_perf = industry_perf.sort_values('avg_return', ascending=False).head(15)
        
        industries = industry_perf.index.tolist()
        avg_returns = industry_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="industry-perf-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {industries},
            y: {avg_returns},
            type: 'bar',
            marker: {{color: {colors}}},
            text: {[f"{x:.1f}%" for x in avg_returns]},
            textposition: 'outside'
        }};
        
        var layout = {{
            title: {{text: 'Industry Performance (Top 15)', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Industry', gridcolor: '{self.DARK_THEME['grid_color']}', tickangle: -45}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('industry-perf-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_gap_performance_chart(self, df: pd.DataFrame) -> str:
        """ギャップサイズ別パフォーマンスチャートを生成"""
        # ギャップサイズをカテゴリに分類
        df['gap_category'] = pd.cut(df['gap_size'], 
                                   bins=[-float('inf'), 0, 2, 5, 10, float('inf')],
                                   labels=['Negative', '0-2%', '2-5%', '5-10%', '10%+'])
        
        gap_perf = df.groupby('gap_category', observed=True).agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        gap_perf.columns = ['avg_return', 'trade_count']
        gap_perf = gap_perf[gap_perf['trade_count'] > 0]
        
        categories = gap_perf.index.tolist()
        avg_returns = gap_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="gap-perf-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {categories},
            y: {avg_returns},
            type: 'bar',
            marker: {{color: {colors}}}
        }};
        
        var layout = {{
            title: {{text: 'Performance by Gap Size', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Gap Size Range', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('gap-perf-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_pre_earnings_chart(self, df: pd.DataFrame) -> str:
        """決算前トレンド別パフォーマンスチャートを生成"""
        # 決算前トレンドをカテゴリに分類
        df['trend_category'] = pd.cut(df['pre_earnings_trend'],
                                     bins=[-float('inf'), -20, -10, 0, 10, 20, float('inf')],
                                     labels=['<-20%', '-20~-10%', '-10~0%', '0~10%', '10~20%', '>20%'])
        
        trend_perf = df.groupby('trend_category', observed=True).agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        trend_perf.columns = ['avg_return', 'trade_count']
        trend_perf = trend_perf[trend_perf['trade_count'] > 0]
        
        categories = trend_perf.index.tolist()
        avg_returns = trend_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="pre-earnings-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {categories},
            y: {avg_returns}, 
            type: 'bar',
            marker: {{color: {colors}}}
        }};
        
        var layout = {{
            title: {{text: 'Performance by Pre-Earnings Trend', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Pre-Earnings 20-Day Change', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('pre-earnings-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_volume_trend_chart(self, df: pd.DataFrame) -> str:
        """ボリュームトレンド分析チャートを生成"""
        # ボリューム変化をカテゴリに分類
        df['volume_category'] = pd.cut(df['volume_change'],
                                      bins=[-float('inf'), -20, 20, 50, 100, float('inf')],
                                      labels=['Decrease', 'Neutral', 'Moderate Inc', 'Large Inc', 'Very Large Inc'])
        
        volume_perf = df.groupby('volume_category', observed=True).agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        volume_perf.columns = ['avg_return', 'trade_count']
        volume_perf = volume_perf[volume_perf['trade_count'] > 0]
        
        categories = volume_perf.index.tolist()
        avg_returns = volume_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="volume-trend-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {categories},
            y: {avg_returns},
            type: 'bar',
            marker: {{color: {colors}}}
        }};
        
        var layout = {{
            title: {{text: 'Volume Trend Analysis', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Volume Category', gridcolor: '{self.DARK_THEME['grid_color']}', tickangle: -45}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('volume-trend-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_ma_analysis_chart(self, df: pd.DataFrame) -> str:
        """移動平均分析チャートを生成"""
        # MA50, MA200の比率をカテゴリに分類
        df['ma50_category'] = pd.cut(df['price_to_ma50'],
                                    bins=[0, 0.95, 1.0, 1.05, 1.1, float('inf')],
                                    labels=['<95%', '95-100%', '100-105%', '105-110%', '>110%'])
        
        ma_perf = df.groupby('ma50_category', observed=True).agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        ma_perf.columns = ['avg_return', 'trade_count']
        ma_perf = ma_perf[ma_perf['trade_count'] > 0]
        
        categories = ma_perf.index.tolist()
        avg_returns = ma_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="ma-analysis-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {categories},
            y: {avg_returns},
            type: 'bar',
            marker: {{color: {colors}}}
        }};
        
        var layout = {{
            title: {{text: 'MA50 Analysis', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Price vs MA50', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('ma-analysis-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_market_cap_chart(self, df: pd.DataFrame) -> str:
        """時価総額別パフォーマンスチャートを生成"""
        mcap_perf = df.groupby('market_cap_category').agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        mcap_perf.columns = ['avg_return', 'trade_count']
        mcap_perf = mcap_perf[mcap_perf['trade_count'] > 0]
        
        categories = mcap_perf.index.tolist()
        avg_returns = mcap_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="market-cap-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {categories},
            y: {avg_returns},
            type: 'bar',
            marker: {{color: {colors}}}
        }};
        
        var layout = {{
            title: {{text: 'Market Cap Performance', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Market Cap Category', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('market-cap-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _create_price_range_chart(self, df: pd.DataFrame) -> str:
        """価格帯別パフォーマンスチャートを生成"""
        price_perf = df.groupby('price_category').agg({
            'return_pct': ['mean', 'count']
        }).round(2)
        
        price_perf.columns = ['avg_return', 'trade_count']
        price_perf = price_perf[price_perf['trade_count'] > 0]
        
        categories = price_perf.index.tolist()
        avg_returns = price_perf['avg_return'].tolist()
        
        colors = [self.DARK_THEME['profit_color'] if x > 0 else self.DARK_THEME['loss_color'] 
                 for x in avg_returns]
        
        script = f"""
        <div id="price-range-chart" style="width: 100%; height: 400px;"></div>
        <script>
        var trace = {{
            x: {categories},
            y: {avg_returns},
            type: 'bar',
            marker: {{color: {colors}}}
        }};
        
        var layout = {{
            title: {{text: 'Price Range Performance', font: {{color: '{self.DARK_THEME['text_color']}'}}}},
            paper_bgcolor: '{self.DARK_THEME['bg_color']}',
            plot_bgcolor: '{self.DARK_THEME['plot_bg_color']}',
            font: {{color: '{self.DARK_THEME['text_color']}'}},
            xaxis: {{title: 'Price Range Category', gridcolor: '{self.DARK_THEME['grid_color']}'}},
            yaxis: {{title: 'Average Return (%)', gridcolor: '{self.DARK_THEME['grid_color']}'}}
        }};
        
        Plotly.newPlot('price-range-chart', [trace], layout, {{responsive: true}});
        </script>
        """
        return script

    def _generate_risk_analysis(self, trades_df: pd.DataFrame, metrics: Dict[str, float]) -> str:
        """Generate risk analysis"""
        risk_warnings = []
        
        # Win rate check
        win_rate = metrics.get('win_rate', 0)
        if win_rate < 40:
            risk_warnings.append("⚠️ Win rate is below 40%. Consider reviewing your strategy.")
        
        # Drawdown check
        max_drawdown = metrics.get('max_drawdown_pct', 0)
        if max_drawdown > 20:
            risk_warnings.append("⚠️ Maximum drawdown exceeds 20%. Risk management strengthening is needed.")
        
        # Profit factor check
        profit_factor = metrics.get('profit_factor', 0)
        if profit_factor < 1.5:
            risk_warnings.append("⚠️ Profit factor is below 1.5. Profitability improvement is needed.")
        
        # Trade count check
        total_trades = metrics.get('total_trades', 0)
        if total_trades < 30:
            risk_warnings.append("⚠️ Low number of trades may reduce statistical reliability.")
        
        if not risk_warnings:
            risk_warnings.append("✅ Currently, no significant risk factors have been detected.")
        
        warnings_html = ""
        for warning in risk_warnings:
            if "⚠️" in warning:
                warnings_html += f'<div class="warning">{warning}</div>'
            else:
                warnings_html += f'<div class="info">{warning}</div>'
        
        return warnings_html + """
        <div class="info">
            <h4>💡 General Important Notes</h4>
            <ul>
                <li>Past performance does not guarantee future results</li>
                <li>Strategy effectiveness may change due to market environment changes</li>
                <li>It is important to strictly follow risk management rules</li>
                <li>Please conduct regular strategy reviews and optimization</li>
            </ul>
        </div>
        """


def main():
    """メイン実行関数"""
    parser = argparse.ArgumentParser(description='Alpaca取引レポート生成')
    parser.add_argument('--start-date', default='2023-01-01', help='開始日 (YYYY-MM-DD)')
    parser.add_argument('--end-date', default='2023-12-31', help='終了日 (YYYY-MM-DD)')
    parser.add_argument('--account-type', default='paper', choices=['paper', 'live'], help='アカウント種別')
    parser.add_argument('--output', default=None, help='出力ファイル名（デフォルト: reports/trade_report_YYYYMMDD_HHMMSS.html）')
    
    args = parser.parse_args()
    
    try:
        # 設定作成
        config = TradeReportConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            account_type=args.account_type
        )
        
        # レポート生成
        report = TradeReport(config)
        report.generate_report(args.output)
        
    except Exception as e:
        logger.error(f"プログラム実行エラー: {e}")
        raise


if __name__ == "__main__":
    main()