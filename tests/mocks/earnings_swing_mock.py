def get_mid_small_cap_symbols(limit: int = 100):
    """テスト用：簡易的な中小型株リストを返すモック関数"""
    return ['AAPL', 'GOOGL', 'MSFT', 'TSLA'][:limit]


def get_historical_data(symbol: str, start_date: str = None, end_date: str = None):
    """テスト用：固定の株価データ DataFrame を返すモック関数"""
    import pandas as pd
    data = {
        'Date': ['2023-01-01', '2023-01-02'],
        'Open': [100.0, 101.0],
        'High': [105.0, 106.0],
        'Low': [95.0, 96.0],
        'Close': [102.0, 103.0],
        'Volume': [1000000, 900000]
    }
    return pd.DataFrame(data)


def calculate_rsi(symbol: str, period: int = 14):
    """テスト用：ダミーの RSI 値を返す"""
    return 50.0  # ニュートラル値


def calculate_sma(symbol: str, period: int = 20):
    """テスト用：ダミーの SMA 値を返す"""
    return 100.0


def sleep_until_open(minutes_before: int = 30):
    """テスト用：市場オープンまで待機するダミー関数（何もしない）"""
    print(f"[MOCK] Waiting until market opens (minus {minutes_before} minutes)")
    return 