import os
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from dotenv import load_dotenv
import strategy_allocation
from api_clients import get_alpaca_client
from config import risk_config
from logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)

# 設定値は config.py から取得
PNL_LOG_FILE = risk_config.PNL_LOG_FILE
PNL_CRITERIA = risk_config.PNL_CRITERIA
PNL_CHECK_PERIOD = risk_config.PNL_CHECK_PERIOD

ALPACA_ACCOUNT = 'live'

# API クライアント初期化
alpaca_client = get_alpaca_client(ALPACA_ACCOUNT)
api = alpaca_client.api  # 後方互換性のため


def read_log():
    if os.path.exists(PNL_LOG_FILE):
        with open(PNL_LOG_FILE, 'r') as file:
            return json.load(file)
    return {}

def write_log(log_data):
    with open(PNL_LOG_FILE, 'w') as file:
        json.dump(log_data, file, indent=risk_config.JSON_INDENT)


def check_pnl(days=risk_config.PNL_CHECK_PERIOD):
    # ログファイルを読み込む
    log_data = read_log()

    # 過去30日間の日付範囲を定義
    end_date = datetime.now(timezone.utc)  # UTCタイムゾーンを設定
    start_date = end_date - timedelta(days=days)
    
    # 取引履歴を取得する期間（過去の購入も含めるため、3倍の期間を取得）
    history_start_date = end_date - timedelta(days=days * risk_config.PNL_HISTORY_MULTIPLIER)

    # end_date = datetime.strptime("2024-08-27", "%Y-%m-%d")
    # start_date = datetime.strptime("2024-08-26", "%Y-%m-%d")

    # end_dateを文字列に変換してログファイルと比較
    date_str = end_date.strftime("%Y-%m-%d")

    # ログファイルに同じ日付があれば、それを返す
    if date_str in log_data:
        print(f"既存のログを使用: {log_data[date_str]['realized_pnl']}")
        pnl_percentage = log_data[date_str]['realized_pnl']
        return pnl_percentage

    # アカウント情報を取得
    try:
        account = alpaca_client.get_account()
        portfolio_value = float(account.portfolio_value)
        logger.info(f"Retrieved account info: portfolio_value={portfolio_value}")
        
        allocation = strategy_allocation.get_strategy_allocation(alpaca_client.api)
        total_trade_value = portfolio_value * (1 - allocation['strategy5'])
        logger.info(f"Calculated total trade value: {total_trade_value} (allocation: {allocation})")
        
    except Exception as e:
        logger.error(f"Failed to get account information: {str(e)}")
        # アカウント情報取得に失敗した場合は、デフォルト値で処理を継続
        # ただし、これは重要な問題なので警告を出す
        logger.warning("Using default values due to account access failure")
        portfolio_value = 100000.0  # デフォルト値
        total_trade_value = 100000.0

    # すべてのトレード活動を取得（より長い期間から取得）
    activities = []
    page_token = None

    try:
        while True:
            try:
                response = alpaca_client.api.get_activities(
                    activity_types='FILL',
                    after=history_start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),  # 正しいフォーマットに変換
                    until=end_date.strftime('%Y-%m-%dT%H:%M:%SZ'),  # 正しいフォーマットに変換
                    # date = "2024-08-26",
                    page_token=page_token,
                    direction='asc',  # 時系列順に取得
                    page_size=risk_config.PAGE_SIZE  # 最大ページサイズ
                )

                if not response:
                    break

                activities.extend(response)

                # レスポンスが満杯でない場合、これ以上のページはない
                if len(response) < risk_config.PAGE_SIZE:
                    break
                else:
                    # 次のページを取得するために最終活動のIDを使用
                    page_token = response[-1].id
                    
            except Exception as e:
                logger.error(f"Failed to get activities page (token: {page_token}): {str(e)}")
                # ページ取得に失敗した場合は、取得できた分で処理を続行
                break
                
    except Exception as e:
        logger.error(f"Failed to initialize activities retrieval: {str(e)}")
        # アクティビティ取得に完全に失敗した場合は、空のリストで継続
        activities = []

    # シンボルごとにフィルを整理
    fills_by_symbol = defaultdict(list)

    for activity in activities:
        fills_by_symbol[activity.symbol].append(activity)

    # FIFO方式で実現損益を計算
    realized_pnl = 0.0
    
    # トレード指標計算用の変数
    winning_trades = 0
    losing_trades = 0
    total_profit = 0.0
    total_loss = 0.0
    trade_results = []  # 各トレードの結果を保存
    all_pnls = []  # すべてのトレードのPnLを記録
    cumulative_pnl = 0.0
    max_cumulative_pnl = 0.0
    max_drawdown = 0.0

    for symbol, fills in fills_by_symbol.items():
        # 取引時間でソート
        fills.sort(key=lambda x: x.transaction_time)

        # 買い注文のキューを初期化
        buy_queue = deque()

        for fill in fills:
            qty = int(fill.qty)
            price = float(fill.price)
            side = fill.side.lower()  # 'buy'または'sell'
            # transaction_timeはすでにdatetimeオブジェクトなので変換は不要
            transaction_time = fill.transaction_time

            if side == 'buy':
                # 買い注文をキューに追加
                buy_queue.append({'qty': qty, 'price': price, 'time': transaction_time})

            elif side == 'sell':
                # 売り注文の取引時間が指定期間内かチェック
                if transaction_time >= start_date:
                    # 売り注文をFIFO方式で買い注文とマッチング
                    remaining_qty = qty
                    while remaining_qty > 0 and buy_queue:
                        buy_fill = buy_queue[0]
                        buy_qty = buy_fill['qty']
                        buy_price = buy_fill['price']

                        matched_qty = min(remaining_qty, buy_qty)
                        pnl = matched_qty * (price - buy_price)
                        realized_pnl += pnl
                        
                        # 各トレードの結果を記録
                        trade_results.append({
                            'symbol': symbol,
                            'pnl': pnl,
                            'time': transaction_time
                        })
                        
                        # PnL統計用のデータを収集
                        all_pnls.append(pnl)
                        
                        # 累積PnLとドローダウン計算
                        cumulative_pnl += pnl
                        if cumulative_pnl > max_cumulative_pnl:
                            max_cumulative_pnl = cumulative_pnl
                        
                        current_drawdown = max_cumulative_pnl - cumulative_pnl
                        if current_drawdown > max_drawdown:
                            max_drawdown = current_drawdown
                        
                        if pnl > 0:
                            winning_trades += 1
                            total_profit += pnl
                        else:
                            losing_trades += 1
                            total_loss += abs(pnl)
                            
                        print(symbol, pnl, realized_pnl, fill.transaction_time)

                        remaining_qty -= matched_qty
                        buy_fill['qty'] -= matched_qty

                        if buy_fill['qty'] == 0:
                            buy_queue.popleft()
                        else:
                            buy_queue[0] = buy_fill  # キュー内の数量を更新

                    if remaining_qty > 0:
                        # 買い注文より多く売った場合の警告
                        print(f"警告: シンボル{symbol}で購入した株数以上を売却しています")
                        # 必要に応じてショートポジションを処理
                else:
                    # 指定期間外の売り注文は買い注文キューのみ更新
                    remaining_qty = qty
                    while remaining_qty > 0 and buy_queue:
                        buy_fill = buy_queue[0]
                        buy_qty = buy_fill['qty']

                        matched_qty = min(remaining_qty, buy_qty)
                        remaining_qty -= matched_qty
                        buy_fill['qty'] -= matched_qty

                        if buy_fill['qty'] == 0:
                            buy_queue.popleft()
                        else:
                            buy_queue[0] = buy_fill

    # 基本指標の計算
    total_trades = winning_trades + losing_trades
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
    
    # 追加指標の計算
    avg_pnl = sum(all_pnls) / len(all_pnls) if all_pnls else 0
    
    # 1トレードあたりの平均取引金額を計算
    avg_trade_value = total_trade_value / total_trades if total_trades > 0 else 0
    
    # Expected Value (期待値) = Win Rate * 平均利益 - (1 - Win Rate) * 平均損失
    avg_win = total_profit / winning_trades if winning_trades > 0 else 0
    avg_loss = total_loss / losing_trades if losing_trades > 0 else 0
    expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    # 平均損益率を計算 - 異なる方法で計算して区別する
    # 平均取引サイズに対する平均利益と損失の比率
    avg_win_pct = avg_win / (avg_trade_value * risk_config.TRADE_VALUE_MULTIPLIER) if winning_trades > 0 and avg_trade_value > 0 else 0
    avg_loss_pct = avg_loss / (avg_trade_value * risk_config.TRADE_VALUE_MULTIPLIER) if losing_trades > 0 and avg_trade_value > 0 else 0
    
    # 平均損益率 = 勝率 × 平均勝ち率 - (1-勝率) × 平均負け率
    avg_pnl_ratio = (win_rate * avg_win_pct) - ((1 - win_rate) * avg_loss_pct)
    
    # Max Drawdownを比率として計算
    max_drawdown_ratio = max_drawdown / total_trade_value if total_trade_value > 0 else 0
    
    # Calmar Ratio = 年間収益率 / 最大ドローダウン
    # 簡易版: 期間の収益率 / 最大ドローダウン
    calmar_ratio = realized_pnl / max_drawdown if max_drawdown > 0 else float('inf')
    
    # Pareto Ratio (80/20の法則) = 上位20%のトレードの利益 / 全体の利益
    sorted_pnls = sorted([p for p in all_pnls if p > 0], reverse=True)
    top_20_percent = sorted_pnls[:max(1, int(len(sorted_pnls) * risk_config.PARETO_RATIO))]
    pareto_ratio = sum(top_20_percent) / total_profit if total_profit > 0 else 0

    # 高配当投資を除くトレード用資金に対して損益率を計算
    pnl_percentage = (realized_pnl / total_trade_value)

    # 実現損益と各種指標をログファイルに保存
    log_data[date_str] = {
        'realized_pnl': round(pnl_percentage, 2),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'total_trades': total_trades,
        'avg_pnl_ratio': round(avg_pnl_ratio, 2),
        'max_drawdown': round(max_drawdown, 2),
        'max_drawdown_ratio': round(max_drawdown_ratio, 2),
        'expected_value': round(expected_value, 2),
        'calmar_ratio': round(calmar_ratio, 2),
        'pareto_ratio': round(pareto_ratio, 2)
    }
    write_log(log_data)

    print(f"P&L rate: {pnl_percentage:.2%}")
    print(f"Win rate: {win_rate:.2%}, Profit Factor: {profit_factor:.2f}")
    print(f"Total Trades: {total_trades}, Avg. PnL: {avg_pnl_ratio:.2%}")
    print(f"Max Drawdown: {max_drawdown_ratio:.2%}, Expected Value: {expected_value:.2f}")
    print(f"Calmar Ratio: {calmar_ratio:.2f}, Pareto Ratio: {pareto_ratio:.2f}")

    return pnl_percentage


def check_pnl_criteria(days=PNL_CHECK_PERIOD, pnl_rate=PNL_CRITERIA):
    return check_pnl(days) > pnl_rate




if __name__ == '__main__':
    print(check_pnl_criteria(pnl_rate=PNL_CRITERIA))
