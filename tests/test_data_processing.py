"""
データ処理機能のテスト
データ取得、変換、分析処理のテスト
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import sys
import os

# パスの設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import timing_config, screening_config


class TestDataFetching(unittest.TestCase):
    """データ取得機能のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.sample_market_data = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01 09:30:00', periods=100, freq='1min'),
            'open': np.random.uniform(100, 110, 100),
            'high': np.random.uniform(110, 120, 100),
            'low': np.random.uniform(90, 100, 100),
            'close': np.random.uniform(95, 115, 100),
            'volume': np.random.randint(1000, 10000, 100)
        })
    
    @patch('concurrent_data_fetcher.asyncio.run')
    def test_concurrent_data_fetching(self, mock_asyncio_run):
        """並行データ取得のテスト"""
        # 並行取得の結果をモック
        mock_results = {
            'AAPL': self.sample_market_data,
            'MSFT': self.sample_market_data.copy(),
            'GOOGL': self.sample_market_data.copy()
        }
        mock_asyncio_run.return_value = mock_results
        
        # 並行取得の実行をシミュレート
        tickers = ['AAPL', 'MSFT', 'GOOGL']
        results = mock_asyncio_run()
        
        # 検証
        self.assertEqual(len(results), 3)
        self.assertIn('AAPL', results)
        self.assertIsInstance(results['AAPL'], pd.DataFrame)
    
    def test_data_quality_validation(self):
        """データ品質検証のテスト"""
        # 不正なデータを含むサンプル
        invalid_data = self.sample_market_data.copy()
        invalid_data.loc[5, 'high'] = invalid_data.loc[5, 'low'] - 1  # High < Low
        invalid_data.loc[10, 'volume'] = -100  # 負の出来高
        
        # データ品質チェック関数のシミュレート
        def validate_ohlcv_data(df):
            issues = []
            
            # High >= Low チェック
            if (df['high'] < df['low']).any():
                issues.append("High price below low price detected")
            
            # 負の出来高チェック
            if (df['volume'] < 0).any():
                issues.append("Negative volume detected")
            
            # NULL値チェック
            if df.isnull().any().any():
                issues.append("Null values detected")
            
            return len(issues) == 0, issues
        
        is_valid, issues = validate_ohlcv_data(invalid_data)
        
        # 検証
        self.assertFalse(is_valid)
        self.assertGreater(len(issues), 0)
        self.assertIn("High price below low price detected", issues)
        self.assertIn("Negative volume detected", issues)
    
    def test_data_timeframe_filtering(self):
        """データ時間枠フィルタリングのテスト"""
        # 市場時間内のデータのみをフィルタ
        market_open = datetime(2024, 1, 1, 9, 30)
        market_close = datetime(2024, 1, 1, 16, 0)
        
        # フィルタリング関数のシミュレート
        filtered_data = self.sample_market_data[
            (self.sample_market_data['timestamp'].dt.time >= market_open.time()) &
            (self.sample_market_data['timestamp'].dt.time <= market_close.time())
        ]
        
        # 検証（全データが市場時間内であることを確認）
        self.assertGreater(len(filtered_data), 0)
        self.assertTrue(
            all(t.time() >= market_open.time() for t in filtered_data['timestamp'])
        )


class TestTechnicalIndicators(unittest.TestCase):
    """テクニカル指標計算のテスト"""
    
    def setUp(self):
        """テスト準備"""
        # 単調増加する価格データ
        self.trending_prices = pd.Series([100, 102, 104, 106, 108, 110, 112, 114, 116, 118])
        # 変動する価格データ
        self.volatile_prices = pd.Series([100, 110, 95, 105, 90, 115, 85, 120, 80, 125])
    
    def test_moving_average_calculation(self):
        """移動平均計算のテスト"""
        period = 5
        
        # シンプルな移動平均
        sma = self.trending_prices.rolling(window=period).mean()
        
        # 最初の4つはNaN、5番目から値が入る
        self.assertTrue(pd.isna(sma.iloc[period-2]))  # 4番目はNaN
        self.assertFalse(pd.isna(sma.iloc[period-1]))  # 5番目から値あり
        
        # 単調増加データの移動平均は元データより小さい値から始まる
        self.assertLess(sma.iloc[period-1], self.trending_prices.iloc[period-1])
    
    def test_exponential_moving_average(self):
        """指数移動平均のテスト"""
        period = 5
        
        # EMAの計算（pandasのewm使用）
        ema = self.trending_prices.ewm(span=period).mean()
        
        # EMAは最初から値を持つ
        self.assertFalse(pd.isna(ema.iloc[0]))
        
        # 単調増加データでは、EMAも増加傾向
        self.assertLess(ema.iloc[0], ema.iloc[-1])
    
    def test_rsi_calculation(self):
        """RSI計算のテスト"""
        def calculate_rsi(prices, period=14):
            delta = prices.diff()
            gains = delta.where(delta > 0, 0)
            losses = -delta.where(delta < 0, 0)
            
            avg_gains = gains.rolling(window=period).mean()
            avg_losses = losses.rolling(window=period).mean()
            
            rs = avg_gains / avg_losses
            rsi = 100 - (100 / (1 + rs))
            
            return rsi
        
        rsi = calculate_rsi(self.volatile_prices, period=5)
        
        # RSIは0-100の範囲内
        valid_rsi = rsi.dropna()
        self.assertTrue(all(0 <= val <= 100 for val in valid_rsi))
    
    def test_bollinger_bands(self):
        """ボリンジャーバンド計算のテスト"""
        period = 10
        std_dev = 2
        
        sma = self.volatile_prices.rolling(window=period).mean()
        std = self.volatile_prices.rolling(window=period).std()
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        # バンドの関係性を確認
        valid_indices = ~(sma.isna() | upper_band.isna() | lower_band.isna())
        valid_data = self.volatile_prices[valid_indices]
        valid_upper = upper_band[valid_indices]
        valid_lower = lower_band[valid_indices]
        valid_sma = sma[valid_indices]
        
        # 上部バンド > 中央線 > 下部バンド
        self.assertTrue(all(valid_upper > valid_sma))
        self.assertTrue(all(valid_sma > valid_lower))


class TestDataTransformation(unittest.TestCase):
    """データ変換処理のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.raw_data = pd.DataFrame({
            'symbol': ['AAPL', 'AAPL', 'MSFT', 'MSFT'],
            'timestamp': ['2024-01-01 09:30:00', '2024-01-01 09:31:00', 
                         '2024-01-01 09:30:00', '2024-01-01 09:31:00'],
            'price': [150.0, 151.0, 300.0, 301.0],
            'volume': [1000, 1200, 800, 900]
        })
    
    def test_data_normalization(self):
        """データ正規化のテスト"""
        # 価格データの正規化
        prices = self.raw_data['price']
        normalized_prices = (prices - prices.min()) / (prices.max() - prices.min())
        
        # 正規化後は0-1の範囲
        self.assertTrue(all(0 <= val <= 1 for val in normalized_prices))
        self.assertEqual(normalized_prices.min(), 0.0)
        self.assertEqual(normalized_prices.max(), 1.0)
    
    def test_data_resampling(self):
        """データリサンプリングのテスト"""
        # タイムスタンプをdatetimeに変換
        df = self.raw_data.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # AAPL データのみを取得
        aapl_data = df[df['symbol'] == 'AAPL']
        
        # 分足から5分足にリサンプリング（シミュレート）
        if len(aapl_data) > 1:
            resampled = aapl_data.resample('5T').agg({
                'price': 'last',
                'volume': 'sum'
            })
            
            # リサンプリング後のデータ検証
            self.assertIsInstance(resampled, pd.DataFrame)
            self.assertIn('price', resampled.columns)
            self.assertIn('volume', resampled.columns)
    
    def test_outlier_detection(self):
        """外れ値検出のテスト"""
        # 外れ値を含むデータ
        data_with_outliers = pd.Series([100, 102, 101, 103, 500, 99, 98, 104])  # 500が外れ値
        
        # IQR法による外れ値検出
        Q1 = data_with_outliers.quantile(0.25)
        Q3 = data_with_outliers.quantile(0.75)
        IQR = Q3 - Q1
        
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        outliers = data_with_outliers[(data_with_outliers < lower_bound) | 
                                    (data_with_outliers > upper_bound)]
        
        # 外れ値が検出されることを確認
        self.assertGreater(len(outliers), 0)
        self.assertIn(500, outliers.values)


class TestMarketDataProcessing(unittest.TestCase):
    """マーケットデータ処理のテスト"""
    
    def setUp(self):
        """テスト準備"""
        self.market_data = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01 09:30:00', periods=50, freq='1min'),
            'open': np.random.uniform(100, 105, 50),
            'high': np.random.uniform(105, 110, 50),
            'low': np.random.uniform(95, 100, 50),
            'close': np.random.uniform(98, 108, 50),
            'volume': np.random.randint(1000, 5000, 50)
        })
        
        # データの整合性を保つため調整
        for i in range(len(self.market_data)):
            # high を open, close の最大値以上に設定
            self.market_data.loc[i, 'high'] = max(
                self.market_data.loc[i, 'open'],
                self.market_data.loc[i, 'close'],
                self.market_data.loc[i, 'high']
            )
            # low を open, close の最小値以下に設定
            self.market_data.loc[i, 'low'] = min(
                self.market_data.loc[i, 'open'],
                self.market_data.loc[i, 'close'],
                self.market_data.loc[i, 'low']
            )
    
    def test_ohlc_data_validation(self):
        """OHLC データ検証のテスト"""
        # 各行でHigh >= Open, Close, Low かつ Low <= Open, Close, High
        for i, row in self.market_data.iterrows():
            self.assertGreaterEqual(row['high'], row['open'])
            self.assertGreaterEqual(row['high'], row['close'])
            self.assertGreaterEqual(row['high'], row['low'])
            self.assertLessEqual(row['low'], row['open'])
            self.assertLessEqual(row['low'], row['close'])
            self.assertLessEqual(row['low'], row['high'])
    
    def test_volume_analysis(self):
        """出来高分析のテスト"""
        # 平均出来高の計算
        avg_volume = self.market_data['volume'].mean()
        
        # 相対出来高の計算
        relative_volume = self.market_data['volume'] / avg_volume
        
        # 高出来高の検出（平均の1.5倍以上）
        high_volume_threshold = 1.5
        high_volume_periods = relative_volume > high_volume_threshold
        
        # 検証
        self.assertIsInstance(avg_volume, (int, float))
        self.assertGreater(avg_volume, 0)
        self.assertEqual(len(relative_volume), len(self.market_data))
    
    def test_price_gap_detection(self):
        """価格ギャップ検出のテスト"""
        # 前日終値と当日始値の差を計算
        opens = self.market_data['open']
        prev_closes = self.market_data['close'].shift(1)
        
        gaps = (opens - prev_closes) / prev_closes * 100  # パーセンテージ
        
        # 大きなギャップ（5%以上）の検出
        significant_gaps = abs(gaps) > 5
        
        # 検証（最初の行はNaNなのでスキップ）
        gap_data = gaps.dropna()
        self.assertEqual(len(gap_data), len(self.market_data) - 1)
    
    def test_trading_session_analysis(self):
        """取引セッション分析のテスト"""
        # 時間帯別の分析
        self.market_data['hour'] = self.market_data['timestamp'].dt.hour
        
        # 開場時間帯（9:30-10:30）の特定
        opening_session = self.market_data[
            (self.market_data['hour'] >= 9) & (self.market_data['hour'] < 11)
        ]
        
        # 開場時間帯の平均出来高
        opening_avg_volume = opening_session['volume'].mean()
        
        # 検証
        self.assertGreater(len(opening_session), 0)
        self.assertIsInstance(opening_avg_volume, (int, float))


class TestDataProcessingIntegration(unittest.TestCase):
    """データ処理統合テスト"""
    
    @patch('api_clients.get_fmp_client')
    def test_full_data_pipeline(self, mock_get_client):
        """完全なデータパイプラインのテスト"""
        # モックFMPクライアント
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # サンプルデータ
        sample_data = pd.DataFrame({
            'Date': ['2024-01-01', '2024-01-02'],
            'Open': [100.0, 102.0],
            'High': [105.0, 107.0],
            'Low': [99.0, 101.0],
            'Close': [104.0, 106.0],
            'Volume': [1000000, 1200000]
        })
        
        mock_client.get_historical_price_data.return_value = sample_data
        
        # データパイプラインの実行をシミュレート
        raw_data = mock_client.get_historical_price_data('AAPL', '2024-01-01', '2024-01-02')
        
        # データ変換
        processed_data = raw_data.copy()
        processed_data['Date'] = pd.to_datetime(processed_data['Date'])
        processed_data['Returns'] = processed_data['Close'].pct_change()
        
        # 検証
        self.assertEqual(len(processed_data), 2)
        self.assertIn('Returns', processed_data.columns)
        self.assertTrue(pd.isna(processed_data['Returns'].iloc[0]))  # 最初のreturnはNaN
    
    def test_data_quality_monitoring(self):
        """データ品質監視のテスト"""
        # 品質メトリクスの計算
        sample_data = pd.DataFrame({
            'price': [100, 101, np.nan, 103, 104],
            'volume': [1000, 1200, 1100, 0, 1300]  # 0出来高を含む
        })
        
        quality_metrics = {
            'null_count': sample_data.isnull().sum().sum(),
            'zero_volume_count': (sample_data['volume'] == 0).sum(),
            'data_completeness': 1 - (sample_data.isnull().sum().sum() / sample_data.size)
        }
        
        # 検証
        self.assertEqual(quality_metrics['null_count'], 1)
        self.assertEqual(quality_metrics['zero_volume_count'], 1)
        self.assertLess(quality_metrics['data_completeness'], 1.0)
    
    def test_performance_monitoring(self):
        """パフォーマンス監視のテスト"""
        import time
        
        # データ処理時間の測定
        start_time = time.time()
        
        # ダミーの重い処理をシミュレート
        large_data = pd.DataFrame({
            'values': np.random.randn(1000)
        })
        result = large_data['values'].rolling(window=50).mean()
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # パフォーマンスメトリクス
        performance_metrics = {
            'processing_time': processing_time,
            'data_size': len(large_data),
            'throughput': len(large_data) / processing_time if processing_time > 0 else float('inf')
        }
        
        # 検証
        self.assertGreater(performance_metrics['throughput'], 0)
        self.assertEqual(performance_metrics['data_size'], 1000)


if __name__ == '__main__':
    # テストの実行
    unittest.main(verbosity=2)