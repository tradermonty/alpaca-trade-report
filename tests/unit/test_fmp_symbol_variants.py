# 新規ファイル
import os
from unittest.mock import patch

import pytest

# テスト対象モジュールの import パス調整
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from fmp_data_fetcher import FMPDataFetcher


@pytest.fixture
@patch.dict(os.environ, {'FMP_API_KEY': 'dummy'})
def fetcher():
    """モック API キー付き FMPDataFetcher インスタンス"""
    return FMPDataFetcher()


def _mock_make_request(endpoint, params, max_retries=3):
    """シンボルに応じて異なるモックレスポンスを返すヘルパー"""
    # ダッシュ表記ならダミーのヒストリカルデータを返す
    if any(sym in endpoint for sym in ('BRK-B', 'BF-B')):
        return {
            'historical': [
                {
                    'date': params['from'],
                    'open': 100.0,
                    'close': 110.0,
                    'high': 115.0,
                    'low': 95.0,
                    'volume': 1000000,
                }
            ]
        }
    # ドット表記は失敗をシミュレート
    return None


@patch.object(FMPDataFetcher, '_make_request', side_effect=_mock_make_request)
def test_brk_b_symbol_handling(mock_request, fetcher):
    """BRK.B → BRK-B への自動フォールバックを検証"""
    result = fetcher.get_historical_price_data('BRK.B', '2023-01-01', '2023-01-10')
    assert result is not None
    assert isinstance(result, list)
    # ヒストリカルデータ1件が返る想定
    assert result[0]['date'] == '2023-01-01'
    # ドット表記で失敗 → ダッシュ表記で成功していること
    assert any('BRK-B' in call.args[0] for call in mock_request.call_args_list)


@patch.object(FMPDataFetcher, '_make_request', side_effect=_mock_make_request)
def test_bf_b_symbol_handling(mock_request, fetcher):
    """BF.B → BF-B への自動フォールバックを検証"""
    result = fetcher.get_historical_price_data('BF.B', '2023-02-01', '2023-02-05')
    assert result is not None
    assert len(result) == 1
    assert any('BF-B' in call.args[0] for call in mock_request.call_args_list) 