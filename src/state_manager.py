"""
状態管理システム
グローバル変数を置き換える集中型状態管理
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
import json
import os
from logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class SystemState:
    """システム全体の状態を管理するデータクラス"""
    
    # 実行モード
    test_mode: bool = False
    test_datetime: Optional[datetime] = None
    
    # アカウント設定
    current_account: str = 'live'
    
    # 実行状態
    trading_enabled: bool = True
    emergency_stop: bool = False
    
    # パフォーマンス監視
    api_call_count: Dict[str, int] = field(default_factory=dict)
    last_pnl_check: Optional[datetime] = None
    current_drawdown: float = 0.0
    
    # セッション情報
    session_start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_strategies: set = field(default_factory=set)
    
    # データキャッシュ
    market_data_cache: Dict[str, Any] = field(default_factory=dict)
    screener_cache: Dict[str, Any] = field(default_factory=dict)
    
    # 外部サービス状態
    api_health_status: Dict[str, str] = field(default_factory=lambda: {
        'alpaca': 'unknown',
        'fmp': 'unknown',  # FMPに移行済み
        'finviz': 'unknown',
        'google_sheets': 'unknown'
    })


class StateManager:
    """
    スレッドセーフな状態管理クラス
    システム全体の状態を一元管理し、グローバル変数を排除
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """シングルトンパターンの実装"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初期化（一度だけ実行される）"""
        if hasattr(self, '_initialized'):
            return
            
        self._state = SystemState()
        self._state_lock = threading.RLock()
        self._listeners: Dict[str, list] = {}
        self._persistence_file = 'system_state.json'
        self._initialized = True
        
        # 保存された状態の復元
        self._load_persistent_state()
        
        logger.info("状態管理システム初期化完了")
    
    def get_state(self) -> SystemState:
        """現在の状態を取得（読み取り専用コピー）"""
        with self._state_lock:
            # 深いコピーを返して外部からの変更を防ぐ
            import copy
            return copy.deepcopy(self._state)
    
    def update_state(self, **kwargs) -> None:
        """状態を更新"""
        with self._state_lock:
            old_values = {}
            
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    old_values[key] = getattr(self._state, key)
                    setattr(self._state, key, value)
                    logger.debug(f"状態更新: {key} = {value}")
                else:
                    # 動的な状態キーも許可（テスト用など）
                    if not hasattr(self._state, '_dynamic_state'):
                        self._state._dynamic_state = {}
                    old_values[key] = getattr(self._state, '_dynamic_state', {}).get(key)
                    self._state._dynamic_state[key] = value
                    logger.debug(f"動的状態更新: {key} = {value}")
            
            # リスナーに変更を通知
            self._notify_listeners(kwargs, old_values)
            
            # 重要な状態変更は永続化
            if any(key in ['trading_enabled', 'emergency_stop', 'current_account'] for key in kwargs):
                self._save_persistent_state()
    
    def get(self, key: str, default: Any = None) -> Any:
        """個別の状態値を取得"""
        with self._state_lock:
            # 標準的な状態属性をチェック
            if hasattr(self._state, key):
                return getattr(self._state, key)
            # 動的状態をチェック
            elif hasattr(self._state, '_dynamic_state') and key in self._state._dynamic_state:
                return self._state._dynamic_state[key]
            else:
                return default
    
    def set(self, key: str, value: Any) -> None:
        """個別の状態値を設定"""
        self.update_state(**{key: value})
    
    def increment_counter(self, counter_name: str, increment: int = 1) -> int:
        """カウンターをインクリメント"""
        with self._state_lock:
            if counter_name not in self._state.api_call_count:
                self._state.api_call_count[counter_name] = 0
            
            self._state.api_call_count[counter_name] += increment
            new_value = self._state.api_call_count[counter_name]
            
            logger.debug(f"カウンター更新: {counter_name} = {new_value}")
            return new_value
    
    def get_counter(self, counter_name: str) -> int:
        """カウンターの現在値を取得"""
        with self._state_lock:
            return self._state.api_call_count.get(counter_name, 0)
    
    def reset_counter(self, counter_name: str) -> None:
        """カウンターをリセット"""
        with self._state_lock:
            self._state.api_call_count[counter_name] = 0
            logger.debug(f"カウンターリセット: {counter_name}")
    
    def add_listener(self, event_pattern: str, callback: Callable) -> None:
        """状態変更リスナーを追加"""
        if event_pattern not in self._listeners:
            self._listeners[event_pattern] = []
        
        self._listeners[event_pattern].append(callback)
        logger.info(f"リスナー追加: {event_pattern}")
    
    def remove_listener(self, event_pattern: str, callback: Callable) -> None:
        """状態変更リスナーを削除"""
        if event_pattern in self._listeners:
            try:
                self._listeners[event_pattern].remove(callback)
                logger.info(f"リスナー削除: {event_pattern}")
            except ValueError:
                logger.warning(f"リスナーが見つかりません: {event_pattern}")
    
    def _notify_listeners(self, changes: Dict[str, Any], old_values: Dict[str, Any]) -> None:
        """登録されたリスナーに変更を通知"""
        for pattern, listeners in self._listeners.items():
            # パターンマッチング（简单な実装）
            matching_changes = {k: v for k, v in changes.items() if pattern == '*' or pattern in k}
            
            if matching_changes:
                for listener in listeners:
                    try:
                        listener(matching_changes, old_values)
                    except Exception as e:
                        logger.error(f"リスナー実行エラー {pattern}: {e}")
    
    def cache_data(self, key: str, data: Any, ttl_seconds: int = 300) -> None:
        """データをキャッシュに保存（TTL付き）"""
        with self._state_lock:
            cache_entry = {
                'data': data,
                'timestamp': time.time(),
                'ttl': ttl_seconds
            }
            
            if 'market_data' in key:
                self._state.market_data_cache[key] = cache_entry
            elif 'screener' in key:
                self._state.screener_cache[key] = cache_entry
            
            logger.debug(f"データキャッシュ: {key} (TTL: {ttl_seconds}秒)")
    
    def get_cached_data(self, key: str) -> Optional[Any]:
        """キャッシュからデータを取得"""
        with self._state_lock:
            cache_dict = None
            
            if 'market_data' in key:
                cache_dict = self._state.market_data_cache
            elif 'screener' in key:
                cache_dict = self._state.screener_cache
            
            if cache_dict and key in cache_dict:
                entry = cache_dict[key]
                
                # TTL確認
                if time.time() - entry['timestamp'] <= entry['ttl']:
                    logger.debug(f"キャッシュヒット: {key}")
                    return entry['data']
                else:
                    # 期限切れエントリを削除
                    del cache_dict[key]
                    logger.debug(f"キャッシュ期限切れ: {key}")
            
            logger.debug(f"キャッシュミス: {key}")
            return None
    
    def clear_cache(self, pattern: str = '*') -> None:
        """キャッシュをクリア"""
        with self._state_lock:
            if pattern == '*':
                self._state.market_data_cache.clear()
                self._state.screener_cache.clear()
                logger.info("全キャッシュをクリア")
            else:
                # パターンマッチしたキーを削除
                for cache_dict in [self._state.market_data_cache, self._state.screener_cache]:
                    keys_to_remove = [k for k in cache_dict.keys() if pattern in k]
                    for key in keys_to_remove:
                        del cache_dict[key]
                logger.info(f"キャッシュクリア: パターン '{pattern}'")
    
    def register_strategy(self, strategy_name: str) -> None:
        """戦略の実行を登録"""
        with self._state_lock:
            self._state.active_strategies.add(strategy_name)
            logger.info(f"戦略登録: {strategy_name}")
    
    def unregister_strategy(self, strategy_name: str) -> None:
        """戦略の実行を解除"""
        with self._state_lock:
            self._state.active_strategies.discard(strategy_name)
            logger.info(f"戦略解除: {strategy_name}")
    
    def is_strategy_active(self, strategy_name: str) -> bool:
        """戦略がアクティブかチェック"""
        with self._state_lock:
            return strategy_name in self._state.active_strategies
    
    def get_active_strategies(self) -> set:
        """アクティブな戦略一覧を取得"""
        with self._state_lock:
            return self._state.active_strategies.copy()
    
    def update_api_health(self, api_name: str, status: str) -> None:
        """API健康状態を更新"""
        with self._state_lock:
            self._state.api_health_status[api_name] = status
            logger.debug(f"API健康状態更新: {api_name} = {status}")
    
    def get_api_health(self, api_name: str = None) -> Dict[str, str]:
        """API健康状態を取得"""
        with self._state_lock:
            if api_name:
                return {api_name: self._state.api_health_status.get(api_name, 'unknown')}
            return self._state.api_health_status.copy()
    
    def emergency_stop(self, reason: str = "手動停止") -> None:
        """緊急停止を実行"""
        logger.critical(f"緊急停止実行: {reason}")
        
        self.update_state(
            emergency_stop=True,
            trading_enabled=False
        )
        
        # 全戦略を停止
        with self._state_lock:
            self._state.active_strategies.clear()
        
        # 緊急停止通知
        self._notify_listeners({'emergency_stop': True}, {'emergency_stop': False})
    
    def resume_trading(self, authorized_by: str = "system") -> None:
        """取引を再開"""
        logger.info(f"取引再開: 承認者 {authorized_by}")
        
        self.update_state(
            emergency_stop=False,
            trading_enabled=True
        )
    
    def get_system_summary(self) -> Dict[str, Any]:
        """システム状態のサマリーを取得"""
        with self._state_lock:
            uptime = datetime.now(timezone.utc) - self._state.session_start_time
            
            return {
                'uptime_seconds': uptime.total_seconds(),
                'trading_enabled': self._state.trading_enabled,
                'emergency_stop': self._state.emergency_stop,
                'test_mode': self._state.test_mode,
                'current_account': self._state.current_account,
                'active_strategies': list(self._state.active_strategies),
                'api_call_total': sum(self._state.api_call_count.values()),
                'api_health': self._state.api_health_status,
                'cache_entries': len(self._state.market_data_cache) + len(self._state.screener_cache),
                'current_drawdown': self._state.current_drawdown
            }
    
    def _save_persistent_state(self) -> None:
        """重要な状態を永続化"""
        try:
            persistent_data = {
                'trading_enabled': self._state.trading_enabled,
                'emergency_stop': self._state.emergency_stop,
                'current_account': self._state.current_account,
                'last_saved': datetime.now(timezone.utc).isoformat()
            }
            
            with open(self._persistence_file, 'w') as f:
                json.dump(persistent_data, f, indent=2)
                
            logger.debug("状態永続化完了")
            
        except Exception as e:
            logger.error(f"状態永続化エラー: {e}")
    
    def _load_persistent_state(self) -> None:
        """永続化された状態を復元"""
        try:
            if os.path.exists(self._persistence_file):
                with open(self._persistence_file, 'r') as f:
                    data = json.load(f)
                
                # 重要な状態のみ復元
                if 'trading_enabled' in data:
                    self._state.trading_enabled = data['trading_enabled']
                if 'emergency_stop' in data:
                    self._state.emergency_stop = data['emergency_stop']
                if 'current_account' in data:
                    self._state.current_account = data['current_account']
                
                logger.info("永続化状態を復元")
                
        except Exception as e:
            logger.error(f"状態復元エラー: {e}")


# グローバルな状態管理インスタンス（シングルトン）
state_manager = StateManager()


# 便利関数
def get_state_manager() -> StateManager:
    """状態管理インスタンスを取得"""
    return state_manager


def is_test_mode() -> bool:
    """テストモードかどうかを確認"""
    return state_manager.get('test_mode', False)


def set_test_mode(enabled: bool, test_datetime: datetime = None) -> None:
    """テストモードを設定"""
    updates = {'test_mode': enabled}
    if test_datetime:
        updates['test_datetime'] = test_datetime
    state_manager.update_state(**updates)


def is_trading_enabled() -> bool:
    """取引が有効かどうかを確認"""
    return state_manager.get('trading_enabled', True) and not state_manager.get('emergency_stop', False)


def get_current_account() -> str:
    """現在のアカウント種別を取得"""
    return state_manager.get('current_account', 'live')


def set_current_account(account_type: str) -> None:
    """現在のアカウント種別を設定"""
    if account_type in ['live', 'paper', 'paper_short']:
        state_manager.set('current_account', account_type)
    else:
        raise ValueError("無効なアカウント種別")


# 状態変更監視用デコレーター
def monitor_state_changes(event_pattern: str):
    """状態変更を監視するデコレーター"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            def state_change_handler(changes, old_values):
                logger.info(f"状態変更検出 {event_pattern}: {changes}")
                func(changes, old_values, *args, **kwargs)
            
            state_manager.add_listener(event_pattern, state_change_handler)
            return func
        return wrapper
    return decorator


# 使用例とマイグレーション補助
class GlobalStateReplacer:
    """
    既存のグローバル変数を段階的に置き換えるためのヘルパークラス
    """
    
    @staticmethod
    def replace_test_mode_variables():
        """各モジュールのtest_mode変数を状態管理に移行"""
        
        # 既存のtest_mode使用箇所を特定して置き換え
        modules_to_update = [
            'orb', 'earnings_swing', 'relative_volume_trade', 
            'dividend_portfolio_management', 'maintain_swing'
        ]
        
        for module_name in modules_to_update:
            try:
                # 動的インポートして変数を置き換え
                module = __import__(f'src.{module_name}', fromlist=[module_name])
                if hasattr(module, 'test_mode'):
                    # 既存の値を状態管理に移行
                    current_value = getattr(module, 'test_mode')
                    state_manager.set('test_mode', current_value)
                    
                    # モジュールの変数を状態管理への参照に置き換え
                    setattr(module, 'test_mode', lambda: is_test_mode())
                    
                    logger.info(f"{module_name}.test_mode を状態管理に移行")
                    
            except ImportError as e:
                logger.warning(f"モジュール {module_name} のインポートに失敗: {e}")
            except Exception as e:
                logger.error(f"モジュール {module_name} の移行に失敗: {e}")
    
    @staticmethod
    def create_compatibility_layer():
        """既存コードとの互換性を保つためのレイヤー"""
        
        # よく使用されるグローバル変数の互換関数
        globals()['get_test_mode'] = is_test_mode
        globals()['set_test_mode'] = set_test_mode
        globals()['get_trading_enabled'] = is_trading_enabled
        globals()['get_current_account'] = get_current_account
        
        logger.info("グローバル変数互換レイヤー作成完了")


if __name__ == '__main__':
    # テスト実行
    print("状態管理システムテスト")
    
    sm = get_state_manager()
    
    # 基本操作テスト
    print(f"初期状態: {sm.get_system_summary()}")
    
    # 状態更新テスト
    sm.update_state(test_mode=True, trading_enabled=False)
    print(f"更新後: {sm.get_system_summary()}")
    
    # カウンターテスト
    sm.increment_counter('api_calls')
    sm.increment_counter('api_calls', 5)
    print(f"API calls count: {sm.get_counter('api_calls')}")
    
    # キャッシュテスト
    sm.cache_data('market_data_AAPL', {'price': 150.0}, ttl_seconds=60)
    cached = sm.get_cached_data('market_data_AAPL')
    print(f"キャッシュデータ: {cached}")
    
    print("状態管理システムテスト完了")