"""
ClawSwarm Node Health Scorer - Phase 2

Computes a health score (0-100) for each node based on:
  - Heartbeat recency (weight: 30)
  - Task success rate (weight: 25)
  - CPU/memory load (weight: 20)
  - Response time (weight: 15)
  - Error rate (weight: 10)

Health levels:
  - 80-100: HEALTHY (accept all tasks)
  - 60-79:  DEGRADED (accept low-priority tasks only)
  - 40-59:  WARNING (accept nothing, alert)
  - 0-39:   CRITICAL (trigger circuit breaker)
"""

import time
import math
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


# ── Health Levels ────────────────────────────────────────────────────

class HealthLevel:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    WARNING = "warning"
    CRITICAL = "critical"


# ── Weights ──────────────────────────────────────────────────────────

WEIGHTS = {
    "heartbeat": 30,
    "success_rate": 25,
    "load": 20,
    "response_time": 15,
    "error_rate": 10,
}


# ── Scoring Functions ────────────────────────────────────────────────

def _score_heartbeat(last_heartbeat_ts: Optional[float], now: Optional[float] = None) -> float:
    """Score based on how recent the last heartbeat was.
    0-30s: 100, 30-60s: 80, 60-120s: 50, >120s: 10, None: 0
    """
    if not last_heartbeat_ts:
        return 0.0
    now = now or time.time()
    age = now - last_heartbeat_ts
    if age <= 30:
        return 100.0
    elif age <= 60:
        return 80.0 - (age - 30) / 30 * 30
    elif age <= 120:
        return 50.0 - (age - 60) / 60 * 40
    else:
        return max(0.0, 10.0 - (age - 120) / 60 * 10)


def _score_success_rate(successful: int, failed: int) -> float:
    """Score based on task success rate. 100% success = 100, 0% = 0."""
    total = successful + failed
    if total == 0:
        return 80.0  # No data = neutral positive
    rate = successful / total
    return rate * 100.0


def _score_load(cpu_percent: Optional[float] = None, memory_percent: Optional[float] = None) -> float:
    """Score based on CPU and memory. Lower = better. Average of both."""
    scores = []
    if cpu_percent is not None:
        scores.append(max(0.0, 100.0 - cpu_percent))
    if memory_percent is not None:
        scores.append(max(0.0, 100.0 - memory_percent))
    if not scores:
        return 80.0  # No data = neutral
    return sum(scores) / len(scores)


def _score_response_time(avg_response_ms: Optional[float] = None) -> float:
    """Score based on average response time. <500ms=100, >5000ms=10."""
    if avg_response_ms is None:
        return 80.0
    if avg_response_ms <= 500:
        return 100.0
    elif avg_response_ms <= 2000:
        return 100.0 - (avg_response_ms - 500) / 1500 * 50
    elif avg_response_ms <= 5000:
        return 50.0 - (avg_response_ms - 2000) / 3000 * 30
    else:
        return max(0.0, 20.0 - (avg_response_ms - 5000) / 5000 * 10)


def _score_error_rate(recent_errors: int, recent_total: int) -> float:
    """Score based on recent error rate. 0% = 100, >50% = 0."""
    if recent_total == 0:
        return 80.0
    rate = recent_errors / recent_total
    if rate <= 0.05:
        return 100.0
    elif rate <= 0.2:
        return 100.0 - rate * 200
    else:
        return max(0.0, 60.0 - rate * 120)


# ── Main Scorer ──────────────────────────────────────────────────────

@dataclass
class HealthReport:
    """Health score report for a node."""
    node_id: str
    score: float
    level: str
    breakdown: Dict[str, float] = field(default_factory=dict)
    recommendation: str = ""
    should_accept_tasks: bool = True
    max_priority: int = 10  # Only accept tasks with priority <= this


def compute_health(
    node_id: str,
    last_heartbeat_ts: Optional[float] = None,
    successful_tasks: int = 0,
    failed_tasks: int = 0,
    cpu_percent: Optional[float] = None,
    memory_percent: Optional[float] = None,
    avg_response_ms: Optional[float] = None,
    recent_errors: int = 0,
    recent_total: int = 0,
) -> HealthReport:
    """
    Compute a weighted health score for a node.

    Returns HealthReport with score (0-100), level, and breakdown.
    """
    now = time.time()
    breakdown = {
        "heartbeat": _score_heartbeat(last_heartbeat_ts, now),
        "success_rate": _score_success_rate(successful_tasks, failed_tasks),
        "load": _score_load(cpu_percent, memory_percent),
        "response_time": _score_response_time(avg_response_ms),
        "error_rate": _score_error_rate(recent_errors, recent_total),
    }

    # Weighted average
    score = sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS) / sum(WEIGHTS.values())
    score = round(score, 1)

    # Determine level
    if score >= 80:
        level = HealthLevel.HEALTHY
        recommendation = "Node is healthy, accept all tasks."
        should_accept = True
        max_pri = 10
    elif score >= 60:
        level = HealthLevel.DEGRADED
        recommendation = "Node is degraded, accept low-priority tasks only."
        should_accept = True
        max_pri = 5
    elif score >= 40:
        level = HealthLevel.WARNING
        recommendation = "Node has warnings. Monitor closely, limit new tasks."
        should_accept = False
        max_pri = 0
    else:
        level = HealthLevel.CRITICAL
        recommendation = "Node is critical. Circuit breaker recommended. Reject all tasks."
        should_accept = False
        max_pri = 0

    return HealthReport(
        node_id=node_id,
        score=score,
        level=level,
        breakdown=breakdown,
        recommendation=recommendation,
        should_accept_tasks=should_accept,
        max_priority=max_pri,
    )


def should_circuit_break(report: HealthReport) -> bool:
    """Decide if circuit breaker should trip."""
    return report.level == HealthLevel.CRITICAL


def get_sorted_nodes(reports: list) -> list:
    """
    Sort node health reports by score (highest first).
    Used by scheduler for best-node selection.
    """
    return sorted(reports, key=lambda r: r.score, reverse=True)
