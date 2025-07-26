"""
ORB Hybrid Wrapper - 段階的移行戦略
既存のorb.pyと新しい依存性注入システムの橋渡し
"""

from orb_config import get_orb_config, ORBConfiguration
from orb_state_manager import TradingState, get_session_manager
from orb_global_refactor import ORBTradingEngine
from logging_config import get_logger

logger = get_logger(__name__)


class ORBHybridWrapper:
    """
    既存orb.pyとリファクタリング版の橋渡しクラス
    段階的移行を可能にする
    """
    
    def __init__(self, config: ORBConfiguration = None):
        self.config = config or get_orb_config()
        self.modern_engine = ORBTradingEngine(self.config)
        self.session_manager = get_session_manager(self.config)
    
    def start_trading_modern(self, symbol: str, **kwargs):
        """
        完全リファクタリング版の実行
        
        推奨: 新しい取引実行はこちらを使用
        """
        logger.info(f"Using modern engine for {symbol}")
        return self.modern_engine.start_trading_session(symbol, **kwargs)
    
    def start_trading_legacy_compatible(self, symbol: str, **kwargs):
        """
        レガシー互換モード
        
        既存コードからの移行期間中に使用
        """
        logger.info(f"Using legacy-compatible mode for {symbol}")
        
        # 引数をレガシー形式に変換
        import sys
        sys.argv = [
            'orb.py', symbol,
            '--pos_size', str(kwargs.get('position_size', 'auto')),
            '--range', str(kwargs.get('opening_range', 5)),
            '--swing', str(kwargs.get('is_swing', False)),
            '--dynamic_rate', str(kwargs.get('dynamic_rate', True)),
            '--test_mode', str(kwargs.get('test_mode', False)),
            '--test_date', str(kwargs.get('test_date', '2023-12-06')),
            '--ema_trail', str(kwargs.get('ema_trail', False)),
            '--daily_log', str(kwargs.get('daily_log', False)),
            '--trend_check', str(kwargs.get('trend_check', True))
        ]
        
        # レガシーエンジンの実行（現在の部分修正済みorb.py）
        try:
            from orb import start_trading
            return start_trading(self.config)
        except Exception as e:
            logger.error(f"Legacy mode failed: {e}")
            # フォールバックとして現代版を使用
            logger.info("Falling back to modern engine")
            return self.modern_engine.start_trading_session(symbol, **kwargs)
    
    def compare_engines(self, symbol: str, **kwargs):
        """
        両エンジンの結果を比較（検証用）
        """
        logger.info(f"Comparing engines for {symbol}")
        
        try:
            # モダンエンジン実行
            modern_result = self.start_trading_modern(symbol, **kwargs)
            
            # レガシー互換モード実行  
            legacy_result = self.start_trading_legacy_compatible(symbol, **kwargs)
            
            # 結果比較
            comparison = {
                'symbol': symbol,
                'modern_result': modern_result,
                'legacy_result': legacy_result,
                'difference': abs(modern_result - legacy_result) if modern_result and legacy_result else None,
                'recommendation': 'modern' if modern_result else 'legacy'
            }
            
            logger.info(f"Engine comparison: {comparison}")
            return comparison
            
        except Exception as e:
            logger.error(f"Engine comparison failed: {e}")
            return None


def main():
    """メイン実行関数 - 移行期間中の推奨使用方法"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ORB Hybrid Trading System")
    parser.add_argument('symbol', help='Trading symbol')
    parser.add_argument('--mode', choices=['modern', 'legacy', 'compare'], 
                       default='modern', help='Execution mode')
    parser.add_argument('--pos_size', default='auto', help='Position size')
    parser.add_argument('--range', type=int, default=5, help='Opening range')
    parser.add_argument('--swing', type=bool, default=False, help='Swing mode')
    parser.add_argument('--test_mode', type=bool, default=False, help='Test mode')
    
    args = parser.parse_args()
    
    # ハイブリッドラッパーの初期化
    wrapper = ORBHybridWrapper()
    
    trading_params = {
        'position_size': args.pos_size,
        'opening_range': args.range,
        'is_swing': args.swing,
        'test_mode': args.test_mode
    }
    
    if args.mode == 'modern':
        print("🚀 Using Modern Engine (Recommended)")
        result = wrapper.start_trading_modern(args.symbol, **trading_params)
        print(f"Result: {result}")
        
    elif args.mode == 'legacy':
        print("🔄 Using Legacy Compatible Mode")
        result = wrapper.start_trading_legacy_compatible(args.symbol, **trading_params)
        print(f"Result: {result}")
        
    elif args.mode == 'compare':
        print("⚖️  Comparing Both Engines")
        comparison = wrapper.compare_engines(args.symbol, **trading_params)
        if comparison:
            print(f"Modern: {comparison['modern_result']}")
            print(f"Legacy: {comparison['legacy_result']}")
            print(f"Difference: {comparison['difference']}")
            print(f"Recommendation: {comparison['recommendation']}")


if __name__ == '__main__':
    main()


# 使用例とマイグレーションガイド
"""
=== 段階的移行ガイド ===

1. 【即座に使用可能】モダンエンジン:
   python orb_hybrid_wrapper.py AAPL --mode modern

2. 【互換性確認】比較モード:
   python orb_hybrid_wrapper.py AAPL --mode compare

3. 【緊急時】レガシー互換:
   python orb_hybrid_wrapper.py AAPL --mode legacy

=== コード移行戦略 ===

# 新しいコード（推奨）:
from orb_hybrid_wrapper import ORBHybridWrapper
wrapper = ORBHybridWrapper()
result = wrapper.start_trading_modern("AAPL", test_mode=True)

# 既存コード（移行期間中）:
from orb_hybrid_wrapper import ORBHybridWrapper  
wrapper = ORBHybridWrapper()
result = wrapper.start_trading_legacy_compatible("AAPL", test_mode=True)

# 段階的移行:
try:
    result = wrapper.start_trading_modern(symbol, **params)
except Exception:
    result = wrapper.start_trading_legacy_compatible(symbol, **params)
"""