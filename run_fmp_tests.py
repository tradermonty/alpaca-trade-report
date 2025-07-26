#!/usr/bin/env python3
"""
FMP API テスト実行スクリプト
更新されたテストコードを実行してFMP統合をテスト
"""

import subprocess
import sys
import os
from pathlib import Path

def run_tests():
    """FMP関連のテストを実行"""
    
    print("🧪 FMP API テスト実行中...")
    print("=" * 50)
    
    # テスト対象ファイル
    test_files = [
        "tests/test_api_clients.py",
        "tests/unit/test_api_clients.py", 
        "tests/integration/test_api_integration.py"
    ]
    
    # プロジェクトルートに移動
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    # 環境変数の設定
    test_env = os.environ.copy()
    test_env.update({
        'FMP_API_KEY': 'test_dummy_key',
        'ALPACA_API_KEY': 'test_alpaca_key',
        'ALPACA_SECRET_KEY': 'test_alpaca_secret',
        'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets'
    })
    
    success_count = 0
    total_count = 0
    
    for test_file in test_files:
        test_path = project_root / test_file
        
        if not test_path.exists():
            print(f"⚠️  テストファイルが見つかりません: {test_file}")
            continue
            
        total_count += 1
        print(f"\n📋 実行中: {test_file}")
        print("-" * 40)
        
        try:
            # pytestまたはunittest実行
            if test_file.endswith('.py'):
                cmd = [sys.executable, '-m', 'pytest', str(test_path), '-v']
            else:
                cmd = [sys.executable, str(test_path)]
                
            result = subprocess.run(
                cmd,
                env=test_env,
                capture_output=True,
                text=True,
                timeout=120  # 2分でタイムアウト
            )
            
            if result.returncode == 0:
                print(f"✅ PASS: {test_file}")
                success_count += 1
            else:
                print(f"❌ FAIL: {test_file}")
                print("--- STDOUT ---")
                print(result.stdout)
                print("--- STDERR ---")  
                print(result.stderr)
                
        except subprocess.TimeoutExpired:
            print(f"⏰ TIMEOUT: {test_file}")
        except Exception as e:
            print(f"💥 ERROR: {test_file} - {e}")
    
    # 結果サマリー
    print("\n" + "=" * 50)
    print("📊 テスト結果サマリー")
    print("=" * 50)
    print(f"実行: {total_count}件")
    print(f"成功: {success_count}件")
    print(f"失敗: {total_count - success_count}件")
    
    if success_count == total_count:
        print("\n🎉 すべてのテストが成功しました！")
        return True
    else:
        print(f"\n⚠️  {total_count - success_count}件のテストが失敗しました")
        return False

def check_dependencies():
    """必要な依存関係をチェック"""
    print("🔍 依存関係チェック中...")
    
    required_packages = [
        'pytest',
        'pandas', 
        'requests',
        'python-dotenv'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ 不足しているパッケージ: {', '.join(missing_packages)}")
        print("以下のコマンドで不足パッケージをインストールしてください:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    print("✅ すべての依存関係が満たされています")
    return True

def main():
    """メイン実行関数"""
    print("FMP API テストランナー")
    print("=" * 50)
    
    # 依存関係チェック
    if not check_dependencies():
        sys.exit(1)
    
    # テスト実行
    success = run_tests()
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()