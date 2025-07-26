"""
並列処理実行管理モジュール
subprocess.Popenの代替として、asyncioとセマフォによる制御された並列実行を提供
"""

import asyncio
import subprocess
import time
from datetime import datetime
from typing import List, Dict, Optional, Union, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from logging_config import get_logger
from config import system_config

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    """実行結果を格納するデータクラス"""
    command: List[str]
    symbol: str
    return_code: int
    stdout: str
    stderr: str
    execution_time: float
    start_time: datetime
    end_time: datetime
    success: bool
    error_message: Optional[str] = None


class ParallelExecutor:
    """
    並列処理実行管理クラス
    同時実行数を制御し、ログを一元化してプロセスを管理
    """
    
    def __init__(self, max_concurrent: int = system_config.MAX_CONCURRENT_TRADES):
        """
        Args:
            max_concurrent: 最大同時実行数
        """
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.results: Dict[str, ExecutionResult] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info(f"ParallelExecutor initialized with max_concurrent={max_concurrent}")
    
    async def execute_trade_commands(
        self,
        trade_commands: Dict[str, List[str]],
        timeout: int = system_config.PROCESS_TIMEOUT,
        enable_monitoring: bool = True
    ) -> Dict[str, ExecutionResult]:
        """
        複数の取引コマンドを並列実行
        
        Args:
            trade_commands: {symbol: command_list} の辞書
            timeout: 各プロセスのタイムアウト（秒）
            enable_monitoring: 実行監視を有効にするかどうか
            
        Returns:
            実行結果の辞書
        """
        logger.info(f"Starting parallel execution of {len(trade_commands)} trade commands")
        
        # 監視を開始（オプション）
        monitor_task = None
        if enable_monitoring:
            try:
                from execution_monitor import global_monitor
                monitor_task = await global_monitor.start_monitoring()
                logger.info("Execution monitoring started")
            except ImportError:
                logger.warning("Execution monitor not available")
        
        try:
            # 全タスクを作成
            tasks = []
            for symbol, command in trade_commands.items():
                task = asyncio.create_task(
                    self._execute_single_command(symbol, command, timeout),
                    name=f"trade_{symbol}"
                )
                self.active_tasks[symbol] = task
                tasks.append(task)
            
            # 全タスクの完了を待機
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            logger.error(f"Error during parallel execution: {e}")
            
        finally:
            # アクティブタスクをクリア
            self.active_tasks.clear()
            
            # 監視を停止
            if monitor_task and enable_monitoring:
                try:
                    from execution_monitor import global_monitor
                    await global_monitor.stop_monitoring()
                    
                    # リソース使用量のサマリーをログ出力
                    summary = global_monitor.get_resource_usage_summary()
                    logger.info(f"Resource usage summary: {summary}")
                    
                except ImportError:
                    pass
        
        logger.info(f"Parallel execution completed. Results: {len(self.results)} processes")
        return self.results.copy()
    
    async def _execute_single_command(
        self,
        symbol: str,
        command: List[str],
        timeout: int
    ) -> ExecutionResult:
        """
        単一コマンドを実行（セマフォで同時実行数制御）
        
        Args:
            symbol: 銘柄シンボル
            command: 実行するコマンドリスト
            timeout: タイムアウト（秒）
            
        Returns:
            実行結果
        """
        async with self.semaphore:  # 同時実行数を制御
            logger.info(f"Starting execution for {symbol}: {' '.join(command)}")
            start_time = datetime.now()
            
            try:
                # サブプロセスを非同期で実行
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self._get_subprocess_env()
                )
                
                # タイムアウト付きで実行完了を待機
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )
                    
                    stdout = stdout_bytes.decode('utf-8', errors='replace')
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
                    return_code = process.returncode
                    
                except asyncio.TimeoutError:
                    logger.error(f"Command timeout for {symbol} after {timeout} seconds")
                    
                    # プロセスを強制終了
                    try:
                        process.kill()
                        await process.wait()
                    except Exception as kill_error:
                        logger.error(f"Failed to kill process for {symbol}: {kill_error}")
                    
                    # タイムアウト結果を作成
                    return self._create_timeout_result(symbol, command, start_time, timeout)
                
            except Exception as e:
                logger.error(f"Failed to start process for {symbol}: {e}")
                return self._create_error_result(symbol, command, start_time, str(e))
            
            # 実行結果を作成
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            success = return_code == 0
            error_message = stderr if not success and stderr else None
            
            result = ExecutionResult(
                command=command,
                symbol=symbol,
                return_code=return_code,
                stdout=stdout,
                stderr=stderr,
                execution_time=execution_time,
                start_time=start_time,
                end_time=end_time,
                success=success,
                error_message=error_message
            )
            
            # 結果を保存
            self.results[symbol] = result
            
            # ログ出力
            if success:
                logger.info(f"Successfully completed {symbol} in {execution_time:.2f}s")
                if stdout:
                    logger.debug(f"Output for {symbol}: {stdout[:500]}...")
            else:
                logger.error(f"Failed execution for {symbol} (code: {return_code}) in {execution_time:.2f}s")
                if stderr:
                    logger.error(f"Error for {symbol}: {stderr[:500]}...")
            
            return result
    
    def _get_subprocess_env(self) -> Dict[str, str]:
        """サブプロセス用の環境変数を取得"""
        import os
        env = os.environ.copy()
        
        # ログレベルを設定
        env['LOG_LEVEL'] = system_config.SUBPROCESS_LOG_LEVEL
        
        return env
    
    def _create_timeout_result(
        self,
        symbol: str,
        command: List[str],
        start_time: datetime,
        timeout: int
    ) -> ExecutionResult:
        """タイムアウト時の結果を作成"""
        end_time = datetime.now()
        
        result = ExecutionResult(
            command=command,
            symbol=symbol,
            return_code=-1,
            stdout="",
            stderr=f"Process timed out after {timeout} seconds",
            execution_time=timeout,
            start_time=start_time,
            end_time=end_time,
            success=False,
            error_message=f"Timeout after {timeout} seconds"
        )
        
        self.results[symbol] = result
        return result
    
    def _create_error_result(
        self,
        symbol: str,
        command: List[str],
        start_time: datetime,
        error_message: str
    ) -> ExecutionResult:
        """エラー時の結果を作成"""
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        result = ExecutionResult(
            command=command,
            symbol=symbol,
            return_code=-2,
            stdout="",
            stderr=error_message,
            execution_time=execution_time,
            start_time=start_time,
            end_time=end_time,
            success=False,
            error_message=error_message
        )
        
        self.results[symbol] = result
        return result
    
    async def cancel_all_tasks(self):
        """実行中のすべてのタスクをキャンセル"""
        if not self.active_tasks:
            return
        
        logger.warning(f"Cancelling {len(self.active_tasks)} active tasks")
        
        for symbol, task in self.active_tasks.items():
            if not task.done():
                logger.info(f"Cancelling task for {symbol}")
                task.cancel()
        
        # キャンセル完了を待機
        await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)
        self.active_tasks.clear()
    
    def get_execution_summary(self) -> Dict:
        """実行結果のサマリーを取得"""
        if not self.results:
            return {"total": 0, "successful": 0, "failed": 0, "success_rate": 0.0}
        
        total = len(self.results)
        successful = sum(1 for result in self.results.values() if result.success)
        failed = total - successful
        success_rate = successful / total if total > 0 else 0.0
        
        avg_execution_time = sum(result.execution_time for result in self.results.values()) / total
        
        return {
            "total": total,
            "successful": successful,
            "failed": failed,
            "success_rate": success_rate,
            "average_execution_time": avg_execution_time,
            "failed_symbols": [symbol for symbol, result in self.results.items() if not result.success]
        }


class TradeCommandBuilder:
    """取引コマンド生成ヘルパークラス"""
    
    @staticmethod
    def build_swing_trade_command(
        symbol: str,
        trade_file: str,
        position_size: Union[int, str],
        swing: bool = True,
        range_val: int = 0,
        dynamic_rate: bool = False,
        ema_trail: bool = False
    ) -> List[str]:
        """
        スイング取引用のコマンドを生成
        
        Args:
            symbol: 銘柄シンボル
            trade_file: 実行するPythonファイル
            position_size: ポジションサイズ
            swing: スイング取引フラグ
            range_val: レンジ値
            dynamic_rate: ダイナミックレートフラグ
            ema_trail: EMAトレールフラグ
            
        Returns:
            コマンドリスト
        """
        command = [
            'python3',
            trade_file,
            str(symbol),
            '--swing', str(swing),
            '--pos_size', str(position_size),
            '--range', str(range_val),
            '--dynamic_rate', str(dynamic_rate),
            '--ema_trail', str(ema_trail)
        ]
        
        return command


# 便利関数
async def execute_trades_parallel(
    symbols: List[str],
    trade_file: str,
    position_size: Union[int, str],
    max_concurrent: int = system_config.MAX_CONCURRENT_TRADES,
    **trade_kwargs
) -> Dict[str, ExecutionResult]:
    """
    複数銘柄の取引を並列実行
    
    Args:
        symbols: 銘柄シンボルのリスト
        trade_file: 実行するPythonファイル
        position_size: ポジションサイズ
        max_concurrent: 最大同時実行数
        **trade_kwargs: 取引パラメータ
        
    Returns:
        実行結果の辞書
    """
    executor = ParallelExecutor(max_concurrent=max_concurrent)
    
    # コマンドを生成
    trade_commands = {}
    for symbol in symbols:
        command = TradeCommandBuilder.build_swing_trade_command(
            symbol=symbol,
            trade_file=trade_file,
            position_size=position_size,
            **trade_kwargs
        )
        trade_commands[symbol] = command
    
    # 実行
    results = await executor.execute_trade_commands(trade_commands)
    
    # サマリーをログ出力
    summary = executor.get_execution_summary()
    logger.info(f"Trade execution summary: {summary}")
    
    return results