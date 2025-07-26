"""
API健全性監視ツール
サーキットブレーカーの状態を監視し、レポートを生成
"""

import json
from datetime import datetime
from typing import Dict, List
from logging_config import get_logger
from circuit_breaker import get_all_circuit_breaker_status, CircuitBreakerState

logger = get_logger(__name__)


def get_api_health_report() -> Dict:
    """
    すべてのAPIの健全性レポートを生成
    
    Returns:
        健全性レポートの辞書
    """
    circuit_breaker_statuses = get_all_circuit_breaker_status()
    
    # 全体的な健全性の判定
    healthy_apis = [cb for cb in circuit_breaker_statuses if cb['state'] == CircuitBreakerState.CLOSED.value]
    degraded_apis = [cb for cb in circuit_breaker_statuses if cb['state'] == CircuitBreakerState.HALF_OPEN.value]
    failed_apis = [cb for cb in circuit_breaker_statuses if cb['state'] == CircuitBreakerState.OPEN.value]
    
    overall_status = "HEALTHY"
    if failed_apis:
        overall_status = "CRITICAL"
    elif degraded_apis:
        overall_status = "DEGRADED"
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'overall_status': overall_status,
        'summary': {
            'total_apis': len(circuit_breaker_statuses),
            'healthy': len(healthy_apis),
            'degraded': len(degraded_apis),
            'failed': len(failed_apis)
        },
        'circuit_breakers': circuit_breaker_statuses,
        'recommendations': _generate_recommendations(circuit_breaker_statuses)
    }
    
    return report


def _generate_recommendations(statuses: List[Dict]) -> List[str]:
    """
    サーキットブレーカーの状態に基づいて推奨事項を生成
    
    Args:
        statuses: サーキットブレーカーの状態リスト
        
    Returns:
        推奨事項のリスト
    """
    recommendations = []
    
    for status in statuses:
        name = status['name']
        state = status['state']
        failure_count = status['failure_count']
        
        if state == CircuitBreakerState.OPEN.value:
            time_until_reset = status.get('time_until_reset', 0)
            recommendations.append(
                f"🔴 {name}: API接続が失敗しています。"
                f"約{time_until_reset:.1f}秒後に自動復旧を試行します。"
            )
            
            if failure_count >= 10:
                recommendations.append(
                    f"⚠️ {name}: 失敗回数が多すぎます({failure_count}回)。"
                    "API キーやネットワーク設定を確認してください。"
                )
                
        elif state == CircuitBreakerState.HALF_OPEN.value:
            recommendations.append(
                f"🟡 {name}: 復旧テスト中です。次のリクエストで状態が決まります。"
            )
            
        elif failure_count > 0:
            recommendations.append(
                f"🟢 {name}: 正常ですが、最近{failure_count}回の失敗がありました。"
            )
    
    if not any(status['state'] != CircuitBreakerState.CLOSED.value for status in statuses):
        recommendations.append("✅ すべてのAPIが正常に動作しています。")
    
    return recommendations


def log_api_health_report():
    """API健全性レポートをログに出力"""
    report = get_api_health_report()
    
    logger.info(f"API Health Report - Overall Status: {report['overall_status']}")
    logger.info(f"Summary: {report['summary']['healthy']}/{report['summary']['total_apis']} APIs healthy")
    
    for recommendation in report['recommendations']:
        if recommendation.startswith('🔴'):
            logger.error(recommendation)
        elif recommendation.startswith('🟡'):
            logger.warning(recommendation)
        elif recommendation.startswith('⚠️'):
            logger.warning(recommendation)
        else:
            logger.info(recommendation)


def save_api_health_report(filename: str = None):
    """
    API健全性レポートをファイルに保存
    
    Args:
        filename: 保存先ファイル名（指定しない場合は日時ベース）
    """
    if filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'api_health_report_{timestamp}.json'
    
    report = get_api_health_report()
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"API health report saved to {filename}")
    except Exception as e:
        logger.error(f"Failed to save API health report: {e}")


def check_critical_apis() -> bool:
    """
    重要なAPIが利用可能かチェック
    
    Returns:
        すべての重要なAPIが利用可能な場合はTrue
    """
    report = get_api_health_report()
    
    # 失敗しているAPIがある場合はFalse
    if report['summary']['failed'] > 0:
        logger.error("Critical APIs are unavailable!")
        return False
    
    # 劣化状態のAPIがある場合は警告
    if report['summary']['degraded'] > 0:
        logger.warning("Some APIs are in degraded state")
    
    return True


if __name__ == '__main__':
    # スタンドアロンでの実行時はレポートを表示
    log_api_health_report()
    save_api_health_report()