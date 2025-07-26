"""
実行監視とリソース管理モジュール
並列処理の監視、リソース使用量の追跡、パフォーマンスメトリクスの収集
"""

import asyncio
import psutil
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from logging_config import get_logger
from config import system_config
import json

logger = get_logger(__name__)


@dataclass
class SystemMetrics:
    """システムメトリクスを格納するデータクラス"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    active_processes: int
    load_average: List[float]  # 1分、5分、15分平均
    available_memory_mb: float


@dataclass
class ExecutionMetrics:
    """実行メトリクスを格納するデータクラス"""
    start_time: datetime
    end_time: Optional[datetime]
    total_processes: int
    completed_processes: int
    failed_processes: int
    average_execution_time: float
    max_execution_time: float
    min_execution_time: float
    concurrent_peak: int
    resource_usage_peak: SystemMetrics


class ExecutionMonitor:
    """
    実行監視クラス
    システムリソースと実行状況をリアルタイムで監視
    """
    
    def __init__(self, monitoring_interval: float = 5.0):
        """
        Args:
            monitoring_interval: 監視間隔（秒）
        """
        self.monitoring_interval = monitoring_interval
        self.is_monitoring = False
        self.system_metrics_history: List[SystemMetrics] = []
        self.execution_metrics: Optional[ExecutionMetrics] = None
        self.active_processes: Dict[str, psutil.Process] = {}
        self.max_concurrent_reached = 0
        
        logger.info(f"ExecutionMonitor initialized with interval={monitoring_interval}s")
    
    async def start_monitoring(self):
        """監視を開始"""
        if self.is_monitoring:
            logger.warning("Monitoring is already running")
            return
        
        self.is_monitoring = True
        logger.info("Starting execution monitoring")
        
        # バックグラウンドタスクを開始
        monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        return monitoring_task
    
    async def stop_monitoring(self):
        """監視を停止"""
        self.is_monitoring = False
        logger.info("Stopping execution monitoring")
    
    async def _monitoring_loop(self):
        """監視ループのメイン処理"""
        while self.is_monitoring:
            try:
                # システムメトリクスを収集
                metrics = self._collect_system_metrics()
                self.system_metrics_history.append(metrics)
                
                # 履歴サイズを制限（最新の1000件まで）
                if len(self.system_metrics_history) > 1000:
                    self.system_metrics_history = self.system_metrics_history[-1000:]
                
                # リソース使用量をログ出力（高使用率の場合のみ）
                if metrics.cpu_percent > 80 or metrics.memory_percent > 80:
                    logger.warning(
                        f"High resource usage detected - "
                        f"CPU: {metrics.cpu_percent:.1f}%, "
                        f"Memory: {metrics.memory_percent:.1f}%, "
                        f"Active processes: {metrics.active_processes}"
                    )
                
                # 並行実行数をチェック
                current_concurrent = len(self.active_processes)
                if current_concurrent > self.max_concurrent_reached:
                    self.max_concurrent_reached = current_concurrent
                
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.monitoring_interval)
    
    def _collect_system_metrics(self) -> SystemMetrics:
        """システムメトリクスを収集"""
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # メモリ使用率
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            available_memory_mb = memory.available / (1024 * 1024)
            
            # ディスク使用率
            disk = psutil.disk_usage('/')
            disk_usage_percent = disk.percent
            
            # プロセス数
            active_processes = len(psutil.pids())
            
            # ロードアベレージ（Unix系のみ）
            try:
                load_average = list(psutil.getloadavg())
            except AttributeError:
                # Windowsの場合はCPU使用率で代用
                load_average = [cpu_percent / 100, cpu_percent / 100, cpu_percent / 100]
            
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                disk_usage_percent=disk_usage_percent,
                active_processes=active_processes,
                load_average=load_average,
                available_memory_mb=available_memory_mb
            )
            
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            # フォールバック値を返す
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=0.0,
                memory_percent=0.0,
                disk_usage_percent=0.0,
                active_processes=0,
                load_average=[0.0, 0.0, 0.0],
                available_memory_mb=0.0
            )
    
    def register_process(self, symbol: str, pid: int):
        """プロセスを登録"""
        try:
            process = psutil.Process(pid)
            self.active_processes[symbol] = process
            logger.debug(f"Registered process for {symbol} (PID: {pid})")
        except psutil.NoSuchProcess:
            logger.warning(f"Process {pid} for {symbol} no longer exists")
    
    def unregister_process(self, symbol: str):
        """プロセスの登録を解除"""
        if symbol in self.active_processes:
            del self.active_processes[symbol]
            logger.debug(f"Unregistered process for {symbol}")
    
    def get_resource_usage_summary(self) -> Dict:
        """リソース使用量のサマリーを取得"""
        if not self.system_metrics_history:
            return {"error": "No metrics collected yet"}
        
        recent_metrics = self.system_metrics_history[-10:]  # 最新10件
        
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_memory = sum(m.memory_percent for m in recent_metrics) / len(recent_metrics)
        max_cpu = max(m.cpu_percent for m in recent_metrics)
        max_memory = max(m.memory_percent for m in recent_metrics)
        
        return {
            "monitoring_duration_minutes": len(self.system_metrics_history) * self.monitoring_interval / 60,
            "current_active_processes": len(self.active_processes),
            "max_concurrent_reached": self.max_concurrent_reached,
            "resource_usage": {
                "cpu": {
                    "current": recent_metrics[-1].cpu_percent if recent_metrics else 0,
                    "average": avg_cpu,
                    "peak": max_cpu
                },
                "memory": {
                    "current": recent_metrics[-1].memory_percent if recent_metrics else 0,
                    "average": avg_memory,
                    "peak": max_memory
                },
                "available_memory_mb": recent_metrics[-1].available_memory_mb if recent_metrics else 0
            },
            "load_average": recent_metrics[-1].load_average if recent_metrics else [0, 0, 0]
        }
    
    def check_resource_limits(self) -> Dict[str, bool]:
        """リソース制限のチェック"""
        if not self.system_metrics_history:
            return {"cpu_ok": True, "memory_ok": True, "can_start_new_process": True}
        
        latest = self.system_metrics_history[-1]
        
        cpu_ok = latest.cpu_percent < 90
        memory_ok = latest.memory_percent < 90
        memory_available = latest.available_memory_mb > 500  # 500MB以上の空きメモリ
        
        can_start_new_process = (
            cpu_ok and 
            memory_ok and 
            memory_available and 
            len(self.active_processes) < system_config.MAX_CONCURRENT_TRADES
        )
        
        return {
            "cpu_ok": cpu_ok,
            "memory_ok": memory_ok,
            "memory_available": memory_available,
            "can_start_new_process": can_start_new_process,
            "current_concurrent": len(self.active_processes),
            "max_concurrent_allowed": system_config.MAX_CONCURRENT_TRADES
        }
    
    def save_metrics_report(self, filename: str = None):
        """メトリクスレポートをファイルに保存"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'execution_metrics_{timestamp}.json'
        
        report = {
            "report_generated": datetime.now().isoformat(),
            "monitoring_summary": self.get_resource_usage_summary(),
            "system_metrics_history": [
                {
                    **asdict(metrics),
                    "timestamp": metrics.timestamp.isoformat()
                }
                for metrics in self.system_metrics_history[-100:]  # 最新100件
            ]
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"Metrics report saved to {filename}")
        except Exception as e:
            logger.error(f"Failed to save metrics report: {e}")


# グローバルモニターインスタンス
global_monitor = ExecutionMonitor()


async def monitor_execution(monitoring_enabled: bool = True):
    """
    実行監視のコンテキストマネージャー
    
    Args:
        monitoring_enabled: 監視を有効にするかどうか
    """
    if not monitoring_enabled:
        return
    
    monitoring_task = await global_monitor.start_monitoring()
    
    try:
        yield global_monitor
    finally:
        await global_monitor.stop_monitoring()
        if monitoring_task and not monitoring_task.done():
            monitoring_task.cancel()
            try:
                await monitoring_task
            except asyncio.CancelledError:
                pass


def get_execution_recommendations() -> List[str]:
    """
    現在のシステム状況に基づいて実行推奨事項を生成
    
    Returns:
        推奨事項のリスト
    """
    recommendations = []
    
    resource_status = global_monitor.check_resource_limits()
    
    if not resource_status["cpu_ok"]:
        recommendations.append("⚠️ CPU使用率が高いです。並列実行数を減らすことを検討してください。")
    
    if not resource_status["memory_ok"]:
        recommendations.append("⚠️ メモリ使用率が高いです。不要なプロセスを終了するか、実行を遅らせてください。")
    
    if not resource_status["memory_available"]:
        recommendations.append("🔴 利用可能メモリが不足しています。実行を停止することを推奨します。")
    
    if not resource_status["can_start_new_process"]:
        recommendations.append(f"🛑 新しいプロセスを開始できません。現在の並列数: {resource_status['current_concurrent']}")
    
    if len(recommendations) == 0:
        recommendations.append("✅ システムリソースは正常範囲内です。")
    
    return recommendations