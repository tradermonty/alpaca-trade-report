import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from scipy.stats import linregress
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
from api_clients import get_alpaca_client

load_dotenv()

# import matplotlib
# matplotlib.use('TkAgg')

TZ_NY = ZoneInfo("US/Eastern")
TZ_UTC = ZoneInfo('UTC')

def calculate_slope(series, window=5):
    slopes = [np.nan]*window
    for i in range(window, len(series)):
        y = series[i-window:i]
        x = np.arange(window)
        slope, _, _, _, _ = linregress(x, y)
        slopes.append(slope)
    return slopes


# 市場指標を取得するための関数
def get_market_indicator(api, symbol='SPY', limit=200):
    # Alpaca APIを使用してデータを取得
    current_time = datetime.now().astimezone(TZ_NY)
    start_dt = current_time - timedelta(days=200)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = current_time.strftime("%Y-%m-%d")

    bars = api.get_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), start=start_date, end=end_date).df
    data = bars.copy()
    data = data.sort_index()
    data['MA50'] = data['close'].rolling(window=50).mean()
    data['MA200'] = data['close'].rolling(window=200).mean()
    return data


# def determine_market_trend(data, threshold=0.1):
#     # 50日移動平均線の傾きを計算（より長いウィンドウサイズを使用）
#     data['MA50_Slope'] = calculate_slope(data['MA50'], window=5)

#     # ヒステリシスを導入したトレンド判定
#     data['Trend'] = ''
#     current_trend = 'neutral'
#     for i in range(1, len(data)):
#         slope = data['MA50_Slope'].iloc[i]
#         if current_trend in ['neutral', 'bear'] and slope > threshold:
#             current_trend = 'bull'
#         elif current_trend in ['neutral', 'bull'] and slope < -threshold:
#             current_trend = 'bear'
#         data.at[data.index[i], 'Trend'] = current_trend

#     # デバッグ用の出力を追加
#     print(f"Latest MA50 slope: {data['MA50_Slope'].iloc[-1]:.4f}")
#     print(f"Threshold used: {threshold}")

#     return data['Trend'].iloc[-1]

def determine_market_trend(data, threshold=0.1):
    # 50日移動平均線の傾きを計算
    data['MA50_Slope'] = calculate_slope(data['MA50'], window=10)  # windowを10に短縮してより早期に変化を検出
    
    # 傾きの移動平均を計算して、適度にノイズを減らす
    data['MA50_Slope_Smooth'] = data['MA50_Slope'].rolling(window=3).mean()  # 平滑化期間を3日に短縮

    # ヒステリシスを導入したトレンド判定
    data['Trend'] = ''
    current_trend = 'neutral'
    trend_duration = 0  # トレンドの継続期間をカウント
    
    for i in range(1, len(data)):
        slope = data['MA50_Slope_Smooth'].iloc[i] if not pd.isna(data['MA50_Slope_Smooth'].iloc[i]) else 0
        
        # トレンド継続期間に基づいて閾値を調整
        duration_factor = min(1.0, trend_duration / 10)  # 最大10日で安定
        adjusted_threshold = threshold * (1 - duration_factor * 0.2)  # トレンドが続くほど閾値を下げる（係数を0.2に調整）
        
        if current_trend == 'bull':
            if slope < -threshold:  # 下向きトレンドへの変更の閾値を基準値と同じに（より早く反応）
                current_trend = 'bear'
                trend_duration = 0
            else:
                trend_duration += 1
        elif current_trend == 'bear':
            if slope > threshold * 1.3:  # 上向きトレンドへの変更の閾値を1.3倍に緩和
                current_trend = 'bull'
                trend_duration = 0
            else:
                trend_duration += 1
        else:  # neutral
            if slope > threshold * 0.8:  # 上昇トレンドの判定をより敏感に
                current_trend = 'bull'
                trend_duration = 0
            elif slope < -threshold * 0.7:  # 下落トレンドの判定をさらに敏感に
                current_trend = 'bear'
                trend_duration = 0
            
        data.at[data.index[i], 'Trend'] = current_trend

    return data['Trend'].iloc[-1]  # 最新のトレンド値のみを返す


# アセットアロケーションの調整
def adjust_asset_allocation(market_trend):
    allocation = {}
    if market_trend == 'bull':
        allocation = {
            'strategy1': 0.50,  # 決算スイングトレード
            'strategy2': 0.10,  # 平均回帰スイングトレード（個別銘柄）
            'strategy3': 0.10,  # 平均回帰スイングトレード（ETF）
            'strategy4': 0.20,  # 平均回帰スイングトレード（インバースETF）
            'strategy5': 0.85,  # 高配当投資
            'strategy6': 0.40,  # 決算スイングトレード（ショート）
        }
    elif market_trend == 'bear':
        allocation = {
            'strategy1': 0.40,  # 決算スイングトレード（ロング）
            'strategy2': 0.10,  # 平均回帰スイングトレード（個別銘柄）
            'strategy3': 0.10,  # 平均回帰スイングトレード（ETF）
            'strategy4': 0.20,  # 平均回帰スイングトレード（インバースETF）
            'strategy5': 0.60,   # 高配当投資
            'strategy6': 0.60,  # 決算スイングトレード（ショート）
        }
    else:
        # 中立相場の場合
        allocation = {
            'strategy1': 0.50,  # 決算スイングトレード（ロング）
            'strategy2': 0.10,  # 平均回帰スイングトレード（個別銘柄）
            'strategy3': 0.10,  # 平均回帰スイングトレード（ETF）
            'strategy4': 0.20,  # 平均回帰スイングトレード（インバースETF）
            'strategy5': 0.50,   # 高配当投資
            'strategy6': 0.50,  # 決算スイングトレード（ショート）
        }
    return allocation


def get_strategy_allocation(api):
    # 市場指標を取得
    market_data = get_market_indicator(api)
    # 強気・弱気相場を判定
    market_trend = determine_market_trend(market_data, threshold=0.1)
    print(f"current market trend: {market_trend}")
    # アセットアロケーションを調整
    allocation = adjust_asset_allocation(market_trend)

    return allocation


def get_target_value(strategy, account='live'):
    # API クライアント初期化
    alpaca_client = get_alpaca_client(account)
    api = alpaca_client.api  # 後方互換性のため

    allocation = get_strategy_allocation(api)

    portfolio_value = float(api.get_account().portfolio_value)
    target_value = portfolio_value * allocation[strategy.lower()]

    return target_value


# def plot_market_trend(data):
#     import matplotlib.pyplot as plt
#     import matplotlib.dates as mdates
#
#     fig, ax = plt.subplots(figsize=(15, 7))
#     ax.plot(data.index, data['close'], label='S&P500 終値', color='black', linewidth=1)
#     ax.plot(data.index, data['MA50'], label='50日移動平均線', color='blue', linewidth=1)
#
#     # 強気・弱気の期間を塗り分け
#     bullish = data['Trend'] == 'bull'
#     bearish = data['Trend'] == 'bear'
#
#     ax.fill_between(data.index, ax.get_ylim()[0], ax.get_ylim()[1], where=bullish, facecolor='green', alpha=0.1)
#     ax.fill_between(data.index, ax.get_ylim()[0], ax.get_ylim()[1], where=bearish, facecolor='red', alpha=0.1)
#
#     # グラフの設定
#     ax.xaxis.set_major_locator(mdates.YearLocator())
#     ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
#     plt.xticks(rotation=45)
#     ax.set_title('S&P500 and 50 days MA')
#     ax.set_xlabel('Date')
#     ax.set_ylabel('Price')
#     ax.legend()
#     plt.tight_layout()
#     plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('--account', default='live')
    args = vars(ap.parse_args())

    print(get_target_value('Strategy6', account=args['account']))
