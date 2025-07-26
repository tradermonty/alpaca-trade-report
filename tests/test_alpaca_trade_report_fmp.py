"""
alpaca_trade_report_fmp.py の動作検証テスト

FMP APIを使用したトレードレポート生成機能のテスト
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import pandas as pd
import json
from pathlib import Path

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from alpaca_trade_report_fmp import TradeReport
from fmp_data_fetcher import FMPDataFetcher


class TestTradeReportInitialization:
    """TradeReportクラスの初期化テスト"""
    
    def test_init_valid_dates(self):
        """有効な日付での初期化テスト"""
        start_date = "2023-01-01"
        end_date = "2023-12-31"
        
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            report = TradeReport(start_date, end_date)
            
            assert report.start_date == start_date
            assert report.end_date == end_date
            assert report.stop_loss == 6
            assert report.initial_capital == 10000
            assert isinstance(report.fmp_fetcher, FMPDataFetcher)
    
    def test_init_future_end_date(self):
        """未来の終了日が現在日付に調整されることをテスト"""
        start_date = "2023-01-01"
        future_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            report = TradeReport(start_date, future_date)
            
            # 終了日が現在日付に調整されていることを確認
            current_date = datetime.now().strftime('%Y-%m-%d')
            assert report.end_date == current_date
    
    def test_init_custom_parameters(self):
        """カスタムパラメータでの初期化テスト"""
        start_date = "2023-01-01"
        end_date = "2023-12-31"
        
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            report = TradeReport(
                start_date=start_date,
                end_date=end_date,
                stop_loss=8,
                initial_capital=20000,
                risk_limit=10,
                language='ja'
            )
            
            assert report.stop_loss == 8
            assert report.initial_capital == 20000
            assert report.risk_limit == 10
            assert report.language == 'ja'


class TestETFDetection:
    """ETF判定機能のテスト"""
    
    @pytest.fixture
    def trade_report(self):
        """テスト用TradeReportインスタンス"""
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            return TradeReport("2023-01-01", "2023-12-31")
    
    def test_is_etf_leverage_etfs(self, trade_report):
        """レバレッジETFの判定テスト"""
        leverage_etfs = ['TQQQ', 'SQQQ', 'UPRO', 'SPXU', 'TNA', 'TZA']
        
        for etf in leverage_etfs:
            assert trade_report._is_etf(etf) == True, f"{etf} should be detected as ETF"
    
    def test_is_etf_major_etfs(self, trade_report):
        """主要ETFの判定テスト"""
        major_etfs = ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'XLF', 'XLK']
        
        for etf in major_etfs:
            assert trade_report._is_etf(etf) == True, f"{etf} should be detected as ETF"
    
    def test_is_etf_regular_stocks(self, trade_report):
        """通常株式の判定テスト（ETFではない）"""
        stocks = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
        
        for stock in stocks:
            assert trade_report._is_etf(stock) == False, f"{stock} should not be detected as ETF"


class TestEarningsDataProcessing:
    """決算データ処理のテスト"""
    
    @pytest.fixture
    def trade_report(self):
        """テスト用TradeReportインスタンス"""
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            return TradeReport("2023-01-01", "2023-12-31")
    
    @patch('alpaca_trade_report_fmp.FMPDataFetcher')
    def test_get_earnings_data_success(self, mock_fmp_fetcher, trade_report):
        """決算データ取得成功テスト"""
        # モックデータの設定
        mock_earnings_data = [
            {
                'date': '2023-01-15',
                'symbol': 'AAPL',
                'epsActual': 1.20,
                'epsEstimate': 1.15,
                'revenue': 123000000000,
                'revenueEstimated': 120000000000,
                'time': 'amc'
            },
            {
                'date': '2023-01-20',
                'symbol': 'GOOGL',
                'epsActual': 1.05,
                'epsEstimate': 1.10,
                'revenue': 68000000000,
                'revenueEstimated': 70000000000,
                'time': 'bmo'
            }
        ]
        
        # FMPDataFetcherのモック設定
        mock_instance = mock_fmp_fetcher.return_value
        mock_instance.get_earnings_calendar.return_value = mock_earnings_data
        
        trade_report.fmp_fetcher = mock_instance
        
        # メソッド実行
        result = trade_report.get_earnings_data()
        
        # 結果検証
        assert result is not None
        assert len(result) == 2
        assert result[0]['symbol'] == 'AAPL'
        assert result[1]['symbol'] == 'GOOGL'
    
    def test_filter_earnings_data(self, trade_report):
        """決算データフィルタリングテスト"""
        # テストデータ
        raw_data = [
            {
                'date': '2023-01-15',
                'symbol': 'AAPL',
                'epsActual': 1.20,
                'epsEstimate': 1.15,
                'revenue': 123000000000,
                'revenueEstimated': 120000000000,
                'time': 'amc'
            },
            {
                'date': '2023-01-20',
                'symbol': 'SPY',  # ETF - フィルタ対象
                'epsActual': 1.05,
                'epsEstimate': 1.10,
                'time': 'bmo'
            },
            {
                'date': '2023-01-25',
                'symbol': 'TSLA',
                'epsActual': None,  # 実績なし - フィルタ対象
                'epsEstimate': 0.85,
                'time': 'amc'
            }
        ]
        
        # フィルタリング実行
        filtered_data = trade_report.filter_earnings_data(raw_data)
        
        # 結果検証
        assert len(filtered_data) == 1  # AAPLのみ残る
        assert filtered_data[0]['symbol'] == 'AAPL'
    
    def test_determine_trade_date(self, trade_report):
        """取引日決定ロジックのテスト"""
        # After Market Close (amc) のテスト
        trade_date = trade_report.determine_trade_date('2023-01-15', 'amc')
        assert trade_date == '2023-01-16'  # 翌営業日
        
        # Before Market Open (bmo) のテスト
        trade_date = trade_report.determine_trade_date('2023-01-16', 'bmo')
        assert trade_date == '2023-01-16'  # 同日


class TestRiskManagement:
    """リスク管理機能のテスト"""
    
    @pytest.fixture
    def trade_report(self):
        """テスト用TradeReportインスタンス"""
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            return TradeReport("2023-01-01", "2023-12-31", risk_limit=6)
    
    def test_check_risk_management_under_limit(self, trade_report):
        """リスク限界以下での継続判定テスト"""
        current_date = "2023-06-01"
        current_capital = 9500  # 5%の損失（リスク限界6%以下）
        
        should_continue = trade_report.check_risk_management(current_date, current_capital)
        assert should_continue == True
    
    def test_check_risk_management_over_limit(self, trade_report):
        """リスク限界超過での停止判定テスト"""
        current_date = "2023-06-01"
        current_capital = 9200  # 8%の損失（リスク限界6%超過）
        
        should_continue = trade_report.check_risk_management(current_date, current_capital)
        assert should_continue == False


class TestPerformanceMetrics:
    """パフォーマンス指標計算のテスト"""
    
    @pytest.fixture
    def trade_report_with_trades(self):
        """取引データ付きTradeReportインスタンス"""
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            report = TradeReport("2023-01-01", "2023-12-31")
            
            # サンプル取引データ
            report.trades = [
                {
                    'Symbol': 'AAPL',
                    'Entry Date': '2023-01-16',
                    'Exit Date': '2023-01-20',
                    'Entry Price': 150.00,
                    'Exit Price': 155.00,
                    'Shares': 100,
                    'Profit/Loss': 500.00,
                    'Exit Reason': 'Take Profit'
                },
                {
                    'Symbol': 'GOOGL',
                    'Entry Date': '2023-02-01',
                    'Exit Date': '2023-02-05',
                    'Entry Price': 100.00,
                    'Exit Price': 95.00,
                    'Shares': 50,
                    'Profit/Loss': -250.00,
                    'Exit Reason': 'Stop Loss'
                }
            ]
            
            return report
    
    def test_calculate_metrics(self, trade_report_with_trades):
        """基本指標計算テスト"""
        metrics = trade_report_with_trades.calculate_metrics()
        
        # 基本指標の確認
        assert 'total_trades' in metrics
        assert 'winning_trades' in metrics
        assert 'losing_trades' in metrics
        assert 'win_rate' in metrics
        assert 'total_profit' in metrics
        assert 'total_loss' in metrics
        assert 'net_profit' in metrics
        
        # 計算結果の確認
        assert metrics['total_trades'] == 2
        assert metrics['winning_trades'] == 1
        assert metrics['losing_trades'] == 1
        assert metrics['win_rate'] == 50.0
        assert metrics['total_profit'] == 500.00
        assert metrics['total_loss'] == 250.00
        assert metrics['net_profit'] == 250.00


class TestIntegrationTests:
    """統合テスト"""
    
    @patch('alpaca_trade_report_fmp.FMPDataFetcher')
    @patch('builtins.open', create=True)
    def test_generate_html_report_integration(self, mock_open, mock_fmp_fetcher):
        """HTMLレポート生成の統合テスト"""
        
        with patch.dict(os.environ, {
            'FMP_API_KEY': 'test_fmp_key',
            'ALPACA_API_KEY': 'test_alpaca_key',
            'ALPACA_SECRET_KEY': 'test_alpaca_secret'
        }):
            # モック設定
            mock_earnings_data = [
                {
                    'date': '2023-01-15',
                    'symbol': 'AAPL',
                    'epsActual': 1.20,
                    'epsEstimate': 1.15,
                    'revenue': 123000000000,
                    'revenueEstimated': 120000000000,
                    'time': 'amc'
                }
            ]
            
            mock_instance = mock_fmp_fetcher.return_value
            mock_instance.get_earnings_calendar.return_value = mock_earnings_data
            
            # ファイル書き込みのモック
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file
            
            # TradeReportインスタンス作成
            report = TradeReport("2023-01-01", "2023-01-31")
            report.fmp_fetcher = mock_instance
            
            # サンプル取引データを追加
            report.trades = [
                {
                    'Symbol': 'AAPL',
                    'Entry Date': '2023-01-16',
                    'Exit Date': '2023-01-20',
                    'Entry Price': 150.00,
                    'Exit Price': 155.00,
                    'Shares': 100,
                    'Profit/Loss': 500.00,
                    'Exit Reason': 'Take Profit'
                }
            ]
            
            # HTMLレポート生成実行
            report_file = report.generate_html_report()
            
            # 結果検証
            assert report_file is not None
            assert 'trade_report_' in report_file
            assert report_file.endswith('.html')
            
            # ファイル書き込みが実行されたことを確認
            mock_open.assert_called()
            mock_file.write.assert_called()


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """テスト環境のセットアップ"""
    # テスト用の環境変数設定
    test_env = {
        'FMP_API_KEY': 'test_fmp_key_12345',
        'ALPACA_API_KEY': 'test_alpaca_key_12345',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret_12345',
        'ALPACA_API_URL': 'https://paper-api.alpaca.markets'
    }
    
    with patch.dict(os.environ, test_env):
        yield


class TestErrorHandling:
    """エラーハンドリングのテスト"""
    
    def test_missing_api_keys(self):
        """APIキー不足時のエラーハンドリング"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="ALPACA_API_KEY or ALPACA_SECRET_KEY is not set"):
                TradeReport("2023-01-01", "2023-12-31")
    
    def test_missing_fmp_api_key(self):
        """FMP APIキー不足時のエラーハンドリング"""
        with patch.dict(os.environ, {
            'ALPACA_API_KEY': 'test_key',
            'ALPACA_SECRET_KEY': 'test_secret'
        }, clear=True):
            with pytest.raises(ValueError, match="FMP_API_KEY is not set"):
                TradeReport("2023-01-01", "2023-12-31")


if __name__ == '__main__':
    # テスト実行
    pytest.main([
        __file__,
        '-v',
        '--tb=short',
        '--disable-warnings'
    ])