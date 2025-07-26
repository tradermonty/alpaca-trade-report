#!/usr/bin/env python3
"""
alpaca_trade_report_fmp.py 動作検証スクリプト

実際のFMP APIを使用してalpaca_trade_report_fmp.pyの動作を検証します。
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

# プロジェクトルートをPythonパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / 'src'))

# 環境変数読み込み
load_dotenv()

def check_environment():
    """環境変数の確認"""
    required_vars = ['FMP_API_KEY', 'ALPACA_API_KEY', 'ALPACA_SECRET_KEY']
    
    print("🔍 環境変数の確認...")
    for var in required_vars:
        value = os.getenv(var)
        if value:
            masked_value = value[:4] + '*' * (len(value) - 8) + value[-4:]
            print(f"  ✅ {var}: {masked_value}")
        else:
            print(f"  ❌ {var}: 未設定")
            return False
    return True


def test_fmp_data_fetcher():
    """FMPDataFetcher単体テスト"""
    print("\n📊 FMPDataFetcher の動作テスト...")
    
    try:
        from fmp_data_fetcher import FMPDataFetcher
        
        # インスタンス作成
        fetcher = FMPDataFetcher()
        print(f"  ✅ FMPDataFetcher インスタンス作成成功")
        
        # 決算サプライズデータ取得テスト
        print("  📈 決算サプライズデータ取得テスト (AAPL)...")
        earnings_data = fetcher.get_earnings_surprises('AAPL', limit=5)
        
        if earnings_data:
            print(f"  ✅ データ取得成功: {len(earnings_data)}件")
            if len(earnings_data) > 0:
                latest = earnings_data[0]
                print(f"      最新データ: {latest.get('date', 'N/A')} - EPS: {latest.get('actualEarningResult', 'N/A')}")
        else:
            print("  ⚠️ データ取得できませんでした")
        
        # 決算カレンダー取得テスト（短期間）
        print("  📅 決算カレンダー取得テスト...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        calendar_data = fetcher.get_earnings_calendar(
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d'),
            target_symbols=['AAPL', 'MSFT'],
            us_only=True
        )
        
        print(f"  ✅ 決算カレンダー取得成功: {len(calendar_data) if calendar_data else 0}件")
        
        return True
        
    except Exception as e:
        print(f"  ❌ エラー: {str(e)}")
        return False


def test_trade_report_basic():
    """TradeReport基本機能テスト"""
    print("\n📋 TradeReport 基本機能テスト...")
    
    try:
        from alpaca_trade_report_fmp import TradeReport
        
        # 短期間でのレポート作成
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        print(f"  📅 対象期間: {start_date.strftime('%Y-%m-%d')} ～ {end_date.strftime('%Y-%m-%d')}")
        
        # TradeReportインスタンス作成
        report = TradeReport(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            initial_capital=50000,
            stop_loss=5,
            risk_limit=8,
            language='ja'
        )
        print("  ✅ TradeReport インスタンス作成成功")
        
        # ETF判定テスト
        print("  🔍 ETF判定機能テスト...")
        test_symbols = ['AAPL', 'TQQQ', 'SPY', 'MSFT', 'QQQ']
        for symbol in test_symbols:
            is_etf = report._is_etf(symbol)
            print(f"      {symbol}: {'ETF' if is_etf else '株式'}")
        
        # 決算データ取得テスト
        print("  📊 決算データ取得テスト...")
        earnings_data = report.get_earnings_data()
        
        if earnings_data:
            print(f"  ✅ 決算データ取得成功: {len(earnings_data)}件")
            
            # データの内容確認
            if len(earnings_data) > 0:
                sample = earnings_data[0]
                print(f"      サンプルデータ: {sample.get('symbol', 'N/A')} - {sample.get('date', 'N/A')}")
        else:
            print("  ⚠️ 期間内に決算データが見つかりませんでした")
        
        return True
        
    except Exception as e:
        print(f"  ❌ エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_metrics_calculation():
    """指標計算機能テスト"""
    print("\n📊 指標計算機能テスト...")
    
    try:
        from alpaca_trade_report_fmp import TradeReport
        
        # TradeReportインスタンス作成
        report = TradeReport("2023-01-01", "2023-01-31")
        
        # サンプル取引データを追加
        sample_trades = [
            {
                'Symbol': 'AAPL',
                'Entry Date': '2023-01-10',
                'Exit Date': '2023-01-15',
                'Entry Price': 150.00,
                'Exit Price': 158.00,
                'Shares': 100,
                'Profit/Loss': 800.00,
                'Exit Reason': 'Take Profit'
            },
            {
                'Symbol': 'MSFT',
                'Entry Date': '2023-01-12',
                'Exit Date': '2023-01-18',
                'Entry Price': 250.00,
                'Exit Price': 245.00,
                'Shares': 50,
                'Profit/Loss': -250.00,
                'Exit Reason': 'Stop Loss'
            },
            {
                'Symbol': 'GOOGL',
                'Entry Date': '2023-01-20',
                'Exit Date': '2023-01-25',
                'Entry Price': 100.00,
                'Exit Price': 108.00,
                'Shares': 75,
                'Profit/Loss': 600.00,
                'Exit Reason': 'Take Profit'
            }
        ]
        
        report.trades = sample_trades
        print(f"  📈 サンプル取引データ: {len(sample_trades)}件")
        
        # 指標計算
        metrics = report.calculate_metrics()
        
        print("  ✅ 計算結果:")
        print(f"      総取引数: {metrics.get('total_trades', 0)}")
        print(f"      勝率: {metrics.get('win_rate', 0):.1f}%")
        print(f"      総利益: ${metrics.get('total_profit', 0):,.2f}")
        print(f"      総損失: ${metrics.get('total_loss', 0):,.2f}")
        print(f"      純利益: ${metrics.get('net_profit', 0):,.2f}")
        print(f"      プロフィットファクター: {metrics.get('profit_factor', 0):.2f}")
        print(f"      最大ドローダウン: ${metrics.get('max_drawdown', 0):,.2f}")
        print(f"      シャープレシオ: {metrics.get('sharpe_ratio', 0):.2f}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ エラー: {str(e)}")
        return False


def test_html_report_generation():
    """HTMLレポート生成テスト"""
    print("\n🌐 HTMLレポート生成テスト...")
    
    try:
        from alpaca_trade_report_fmp import TradeReport
        
        # TradeReportインスタンス作成
        report = TradeReport("2023-01-01", "2023-01-31", language='ja')
        
        # サンプルデータ追加
        report.trades = [
            {
                'Symbol': 'AAPL',
                'Entry Date': '2023-01-10',
                'Exit Date': '2023-01-15',
                'Entry Price': 150.00,
                'Exit Price': 158.00,
                'Shares': 100,
                'Profit/Loss': 800.00,
                'Exit Reason': 'Take Profit'
            }
        ]
        
        # エクイティカーブデータ追加
        import pandas as pd
        dates = pd.date_range('2023-01-01', '2023-01-31', freq='D')
        equity_data = []
        capital = 50000
        
        for i, date in enumerate(dates):
            # ランダムな日次変動をシミュレート
            daily_change = (i % 3 - 1) * 100  # -100, 0, +100の繰り返し
            capital += daily_change
            equity_data.append({
                'Date': date.strftime('%Y-%m-%d'),
                'Equity': capital
            })
        
        report.equity_curve = equity_data
        
        # HTMLレポート生成
        print("  🔄 HTMLレポート生成中...")
        report_file = report.generate_html_report()
        
        if report_file and os.path.exists(report_file):
            file_size = os.path.getsize(report_file) / 1024  # KB
            print(f"  ✅ HTMLレポート生成成功")
            print(f"      ファイル: {report_file}")
            print(f"      サイズ: {file_size:.1f} KB")
            
            # ブラウザで開くかの確認
            user_input = input("  🌐 ブラウザで開きますか？ (y/N): ").lower()
            if user_input == 'y':
                import webbrowser
                webbrowser.open(f'file://{os.path.abspath(report_file)}')
                print("  🚀 ブラウザで開きました")
        else:
            print("  ❌ HTMLレポート生成に失敗しました")
            return False
        
        return True
        
    except Exception as e:
        print(f"  ❌ エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def run_unit_tests():
    """ユニットテスト実行"""
    print("\n🧪 ユニットテスト実行...")
    
    try:
        import subprocess
        import sys
        
        # pytest実行
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            'tests/test_alpaca_trade_report_fmp.py',
            'tests/test_fmp_data_fetcher.py',
            '-v', '--tb=short'
        ], capture_output=True, text=True, cwd=project_root)
        
        print("  📋 テスト結果:")
        if result.stdout:
            print(result.stdout)
        
        if result.stderr:
            print("  ⚠️ エラー出力:")
            print(result.stderr)
        
        if result.returncode == 0:
            print("  ✅ 全てのユニットテストが成功しました")
            return True
        else:
            print("  ❌ 一部のユニットテストが失敗しました")
            return False
            
    except Exception as e:
        print(f"  ❌ ユニットテスト実行エラー: {str(e)}")
        return False


def main():
    """メイン実行関数"""
    print("=" * 60)
    print("🚀 alpaca_trade_report_fmp.py 動作検証")
    print("=" * 60)
    
    # 環境変数確認
    if not check_environment():
        print("\n❌ 必要な環境変数が設定されていません")
        print("   .envファイルを確認してください")
        return False
    
    # テスト実行
    tests = [
        ("FMPDataFetcher動作テスト", test_fmp_data_fetcher),
        ("TradeReport基本機能テスト", test_trade_report_basic),
        ("指標計算機能テスト", test_metrics_calculation),
        ("HTMLレポート生成テスト", test_html_report_generation),
        ("ユニットテスト実行", run_unit_tests)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'=' * 20} {test_name} {'=' * 20}")
        try:
            results[test_name] = test_func()
        except KeyboardInterrupt:
            print("\n⏹️ ユーザーによって中断されました")
            break
        except Exception as e:
            print(f"❌ 予期しないエラー: {str(e)}")
            results[test_name] = False
    
    # 結果サマリー
    print("\n" + "=" * 60)
    print("📊 テスト結果サマリー")
    print("=" * 60)
    
    passed = 0
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} {test_name}")
        if result:
            passed += 1
    
    total = len(results)
    print(f"\n🎯 結果: {passed}/{total} テスト成功 ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 全てのテストが成功しました！")
        return True
    else:
        print("⚠️  一部のテストが失敗しています")
        return False


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️ プログラムが中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 致命的エラー: {str(e)}")
        sys.exit(1)