"""
fmp_data_fetcher.py の動作検証テスト

FMP APIクライアントの機能テスト
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json
import requests

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fmp_data_fetcher import FMPDataFetcher


class TestFMPDataFetcherInitialization:
    """FMPDataFetcherの初期化テスト"""
    
    @patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'})
    def test_init_with_api_key(self):
        """APIキー付きでの初期化テスト"""
        fetcher = FMPDataFetcher()
        
        assert fetcher.api_key == 'test_api_key'
        assert fetcher.base_url == 'https://financialmodelingprep.com/api/v4'
        assert fetcher.alt_base_url == 'https://financialmodelingprep.com/api/v3'
        assert fetcher.session is not None
    
    def test_init_without_api_key(self):
        """APIキーなしでの初期化テスト"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="FMP_API_KEY is required"):
                FMPDataFetcher()
    
    @patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'})
    def test_custom_initialization(self):
        """カスタムパラメータでの初期化テスト"""
        fetcher = FMPDataFetcher(max_retries=5, timeout=30)
        
        assert fetcher.max_retries == 5
        assert fetcher.timeout == 30


class TestRateLimiting:
    """レート制限機能のテスト"""
    
    @pytest.fixture
    def fetcher(self):
        """テスト用FMPDataFetcherインスタンス"""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'}):
            return FMPDataFetcher()
    
    def test_rate_limit_check_normal(self, fetcher):
        """通常時のレート制限チェック"""
        # 初期状態では制限なし
        fetcher._rate_limit_check()
        
        # リクエスト回数を増やして制限チェック
        fetcher.request_count = 250  # 制限に近い値
        fetcher.last_reset_time = datetime.now()
        
        # 制限チェック実行（エラーなし）
        fetcher._rate_limit_check()
    
    @patch('time.sleep')
    def test_rate_limit_exceeded(self, mock_sleep, fetcher):
        """レート制限超過時のテスト"""
        # 制限超過状態をシミュレート
        fetcher.request_count = 350  # 制限を超える
        fetcher.last_reset_time = datetime.now()
        
        fetcher._rate_limit_check()
        
        # スリープが呼ばれることを確認
        mock_sleep.assert_called()


class TestAPIRequest:
    """API リクエスト機能のテスト"""
    
    @pytest.fixture
    def fetcher(self):
        """テスト用FMPDataFetcherインスタンス"""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'}):
            return FMPDataFetcher()
    
    @patch('requests.Session.get')
    def test_make_request_success(self, mock_get, fetcher):
        """API リクエスト成功テスト"""
        # モックレスポンス設定
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': 'test_data'}
        mock_get.return_value = mock_response
        
        # リクエスト実行
        result = fetcher._make_request('test-endpoint', {'param': 'value'})
        
        # 結果検証
        assert result == {'data': 'test_data'}
        mock_get.assert_called_once()
    
    @patch('requests.Session.get')
    def test_make_request_http_error(self, mock_get, fetcher):
        """HTTP エラー時のテスト"""
        # HTTPエラーのモック
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response
        
        # リクエスト実行
        result = fetcher._make_request('non-existent-endpoint')
        
        # エラー時はNoneが返されることを確認
        assert result is None
    
    @patch('requests.Session.get')
    def test_make_request_json_error(self, mock_get, fetcher):
        """JSON デコードエラー時のテスト"""
        # JSON デコードエラーのモック
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_get.return_value = mock_response
        
        # リクエスト実行
        result = fetcher._make_request('test-endpoint')
        
        # エラー時はNoneが返されることを確認
        assert result is None
    
    @patch('requests.Session.get')
    def test_make_request_with_retries(self, mock_get, fetcher):
        """リトライ機能のテスト"""
        # 最初の2回は失敗、3回目で成功するモック
        mock_response_fail = Mock()
        mock_response_fail.status_code = 500
        mock_response_fail.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {'data': 'success'}
        
        mock_get.side_effect = [
            mock_response_fail,
            mock_response_fail,
            mock_response_success
        ]
        
        # リクエスト実行
        result = fetcher._make_request('test-endpoint')
        
        # 成功データが返されることを確認
        assert result == {'data': 'success'}
        # 3回リクエストが実行されたことを確認
        assert mock_get.call_count == 3


class TestEarningsDataRetrieval:
    """決算データ取得機能のテスト"""
    
    @pytest.fixture
    def fetcher(self):
        """テスト用FMPDataFetcherインスタンス"""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'}):
            return FMPDataFetcher()
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_get_earnings_surprises_success(self, mock_request, fetcher):
        """決算サプライズデータ取得成功テスト"""
        # モックデータ設定
        mock_data = [
            {
                'date': '2023-01-15',
                'symbol': 'AAPL',
                'actualEarningResult': 1.20,
                'estimatedEarning': 1.15
            }
        ]
        mock_request.return_value = mock_data
        
        # メソッド実行
        result = fetcher.get_earnings_surprises('AAPL')
        
        # 結果検証
        assert result == mock_data
        mock_request.assert_called_once_with('earnings-surprises/AAPL', {'limit': 80})
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_get_earnings_surprises_no_data(self, mock_request, fetcher):
        """決算サプライズデータなし時のテスト"""
        mock_request.return_value = None
        
        # メソッド実行
        result = fetcher.get_earnings_surprises('INVALID_SYMBOL')
        
        # 結果検証
        assert result is None
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_get_earnings_calendar_success(self, mock_request, fetcher):
        """決算カレンダー取得成功テスト"""
        # モックデータ設定
        mock_data = [
            {
                'date': '2023-01-15',
                'symbol': 'AAPL',
                'epsActual': 1.20,
                'epsEstimate': 1.15,
                'time': 'amc'
            },
            {
                'date': '2023-01-16',
                'symbol': 'GOOGL',
                'epsActual': 1.05,
                'epsEstimate': 1.10,
                'time': 'bmo'
            }
        ]
        mock_request.return_value = mock_data
        
        # メソッド実行
        result = fetcher.get_earnings_calendar('2023-01-01', '2023-01-31')
        
        # 結果検証
        assert len(result) == 2
        assert result[0]['symbol'] == 'AAPL'
        assert result[1]['symbol'] == 'GOOGL'
    
    @patch.object(FMPDataFetcher, '_get_earnings_for_specific_symbols')
    def test_get_earnings_calendar_specific_symbols(self, mock_specific, fetcher):
        """特定銘柄での決算カレンダー取得テスト"""
        # モックデータ設定
        mock_data = [
            {
                'date': '2023-01-15',
                'symbol': 'AAPL',
                'epsActual': 1.20,
                'epsEstimate': 1.15
            }
        ]
        mock_specific.return_value = mock_data
        
        # メソッド実行
        result = fetcher.get_earnings_calendar(
            '2023-01-01', 
            '2023-01-31', 
            target_symbols=['AAPL']
        )
        
        # 結果検証
        assert result == mock_data
        mock_specific.assert_called_once()
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_get_earnings_calendar_date_chunking(self, mock_request, fetcher):
        """日付範囲の分割処理テスト"""
        # 90日を超える期間でテスト
        start_date = '2023-01-01'
        end_date = '2023-12-31'  # 364日間
        
        # モックデータ設定（複数回の呼び出しに対応）
        mock_request.return_value = [
            {'date': '2023-01-15', 'symbol': 'AAPL', 'epsActual': 1.20}
        ]
        
        # メソッド実行
        result = fetcher.get_earnings_calendar(start_date, end_date)
        
        # 複数回のAPIコールが実行されることを確認
        assert mock_request.call_count > 1


class TestSpecificSymbolEarnings:
    """特定銘柄決算データ取得のテスト"""
    
    @pytest.fixture
    def fetcher(self):
        """テスト用FMPDataFetcherインスタンス"""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'}):
            return FMPDataFetcher()
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_get_earnings_for_specific_symbols_success(self, mock_request, fetcher):
        """特定銘柄決算データ取得成功テスト"""
        # モックデータ設定
        def mock_response(endpoint, params):
            if 'AAPL' in endpoint:
                return [
                    {
                        'date': '2023-01-15',
                        'actualEarningResult': 1.20,
                        'estimatedEarning': 1.15
                    }
                ]
            return None
        
        mock_request.side_effect = mock_response
        
        # メソッド実行
        result = fetcher._get_earnings_for_specific_symbols(
            ['AAPL'], '2023-01-01', '2023-01-31'
        )
        
        # 結果検証
        assert len(result) == 1
        assert result[0]['symbol'] == 'AAPL'
        assert result[0]['epsActual'] == 1.20
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_get_earnings_for_specific_symbols_fallback(self, mock_request, fetcher):
        """フォールバック機能のテスト"""
        # 最初のエンドポイントは失敗、フォールバックで成功
        call_count = 0
        
        def mock_response(endpoint, params):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1 and 'earnings-surprises' in endpoint:
                return None  # 最初は失敗
            elif call_count == 2 and 'earning_calendar' in endpoint:
                return [
                    {
                        'date': '2023-01-15',
                        'eps': 1.20,
                        'epsEstimated': 1.15
                    }
                ]
            return None
        
        mock_request.side_effect = mock_response
        
        # メソッド実行
        result = fetcher._get_earnings_for_specific_symbols(
            ['AAPL'], '2023-01-01', '2023-01-31'
        )
        
        # フォールバックが動作することを確認
        assert len(result) == 1
        assert mock_request.call_count >= 2


class TestErrorHandlingAndEdgeCases:
    """エラーハンドリングとエッジケースのテスト"""
    
    @pytest.fixture
    def fetcher(self):
        """テスト用FMPDataFetcherインスタンス"""
        with patch.dict(os.environ, {'FMP_API_KEY': 'test_api_key'}):
            return FMPDataFetcher()
    
    def test_invalid_date_format(self, fetcher):
        """無効な日付フォーマットのテスト"""
        with pytest.raises(ValueError):
            fetcher.get_earnings_calendar('invalid-date', '2023-12-31')
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_empty_response_handling(self, mock_request, fetcher):
        """空のレスポンス処理テスト"""
        mock_request.return_value = []
        
        result = fetcher.get_earnings_calendar('2023-01-01', '2023-01-31')
        
        # 空のリストが返されることを確認
        assert result == []
    
    @patch.object(FMPDataFetcher, '_make_request')
    def test_malformed_data_handling(self, mock_request, fetcher):
        """不正な形式のデータ処理テスト"""
        # 日付フィールドが欠如したデータ
        mock_request.return_value = [
            {
                'symbol': 'AAPL',
                'epsActual': 1.20
                # 'date' フィールドなし
            }
        ]
        
        result = fetcher._get_earnings_for_specific_symbols(
            ['AAPL'], '2023-01-01', '2023-01-31'
        )
        
        # 不正なデータはフィルタリングされることを確認
        assert len(result) == 0


if __name__ == '__main__':
    # テスト実行
    pytest.main([
        __file__,
        '-v',
        '--tb=short',
        '--disable-warnings'
    ])