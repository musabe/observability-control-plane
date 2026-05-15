"""
correlators/health_score.py
----------------------------
Calculates a real health score (0-100) for each environment
based on collected signals and active incidents.

Score starts at 100 and penalties are subtracted.
Confidence scales incident penalties — a 51% confidence warning
applies half the penalty of a 95% confidence warning.

Labels:
  90-100 → HEALTHY
  60-89  → DEGRADED
  0-59   → CRITICAL
"""

import logging

logger = logging.getLogger(__name__)


# ── Label mapping ─────────────────────────────────────────────────────────────

def score_to_label(score: int) -> str:
    if score >= 90:
        return "HEALTHY"
    if score >= 60:
        return "DEGRADED"
    return "CRITICAL"


def score_to_severity(score: int) -> str:
    if score >= 90:
        return "ok"
    if score >= 60:
        return "warning"
    return "critical"


# ── Penalty calculator ────────────────────────────────────────────────────────

def calculate_health_score(
    incidents: list,
    suppressed_warnings: list,
    pg_snap=None,
    http_snap=None,
    win_snap: dict = None,
) -> tuple[int, str, str]:
    """
    Calculate health score from real signal data.

    Returns:
        (score, label, severity)
        e.g. (87, "DEGRADED", "warning")
    """
    score = 100
    reasons = []

    # ── Active incidents ──────────────────────────────────────────────────────
    for inc in incidents:
        confidence = inc.get("confidence", 80) if isinstance(inc, dict) else getattr(inc, "confidence", 80)
        severity = inc.get("severity", "warning") if isinstance(inc, dict) else getattr(inc, "severity", "warning")
        confidence_factor = confidence / 100.0

        if severity == "critical":
            penalty = int(40 * confidence_factor)
        else:
            penalty = int(20 * confidence_factor)

        score -= penalty
        reasons.append(f"incident({severity}) -{penalty}")

    # ── Suppressed warnings ───────────────────────────────────────────────────
    for w in (suppressed_warnings or []):
        score -= 5
        reasons.append("suppressed_warning -5")

    # ── PostgreSQL signals ────────────────────────────────────────────────────
    if pg_snap:
        if not pg_snap.available:
            score -= 30
            reasons.append("pg_unavailable -30")
        else:
            conn_pct = pg_snap.connection_pct
            if conn_pct >= 90:
                score -= 20
                reasons.append(f"pg_connections({conn_pct:.0f}%) -20")
            elif conn_pct >= 75:
                score -= 10
                reasons.append(f"pg_connections({conn_pct:.0f}%) -10")

            if len(pg_snap.blocked_queries) > 0:
                score -= 10
                reasons.append(f"blocked_queries({len(pg_snap.blocked_queries)}) -10")

            if len(pg_snap.long_running_queries) > 0:
                score -= 5
                reasons.append(f"long_queries({len(pg_snap.long_running_queries)}) -5")

    # ── HTTP signals ──────────────────────────────────────────────────────────
    if http_snap:
        if not http_snap.all_reachable:
            score -= 25
            reasons.append("http_unreachable -25")
        elif http_snap.overall_severity == "critical":
            score -= 15
            reasons.append("http_critical_latency -15")
        elif http_snap.overall_severity == "warning":
            score -= 10
            reasons.append("http_warning_latency -10")

    # ── Windows / service signals ─────────────────────────────────────────────
    if win_snap and isinstance(win_snap, dict) and win_snap.get("available"):
        mem_pct = win_snap.get("memory_used_pct", 0)
        if mem_pct >= 90:
            score -= 15
            reasons.append(f"server_memory({mem_pct:.0f}%) -15")
        elif mem_pct >= 80:
            score -= 8
            reasons.append(f"server_memory({mem_pct:.0f}%) -8")

        services = win_snap.get("services", [])
        stopped = [s for s in services if s.get("state") != "Running"]
        for s in stopped:
            score -= 15
            reasons.append(f"service_stopped({s.get('display_name','?')}) -15")

    # ── Floor / ceiling ───────────────────────────────────────────────────────
    score = max(0, min(100, score))
    label = score_to_label(score)
    severity = score_to_severity(score)

    logger.debug("Health score: %d (%s) — %s", score, label, ", ".join(reasons) or "no penalties")

    return score, label, severity
