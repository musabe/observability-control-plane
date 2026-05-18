"""
correlators/metrics.py
-----------------------
Operational metrics and SLO tracking for Vorsa environments.

Responsibilities:
  - Calculate live SLO snapshot for state.json (current status)
  - Append metric samples to logs/metrics.jsonl (historical record)
  - Provide error budget calculations for dashboard display

Called once per poll cycle from control_plane.py after health scoring.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── SLO targets (can be overridden per environment in environments.yaml) ──────

SLO_AVAILABILITY_TARGET_PCT   = 99.5   # % uptime target (30-day window)
SLO_LATENCY_BUDGET_MS         = 500    # p95 API latency budget (ms)
SLO_PG_SATURATION_TARGET_PCT  = 75.0   # max connection pool %
SLO_MTTR_SEV1_MINUTES         = 15     # SEV-1 resolution target
SLO_MTTR_SEV2_MINUTES         = 30     # SEV-2 resolution target
SLO_POLL_RELIABILITY_TARGET   = 99.0   # % successful polls

# Error budget window
BUDGET_WINDOW_SECONDS = 30 * 24 * 3600  # 30 days
ALLOWED_CRITICAL_SECONDS = BUDGET_WINDOW_SECONDS * (1 - SLO_AVAILABILITY_TARGET_PCT / 100)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SloStatus:
    """Current SLO status for one environment — written to state.json."""

    environment: str
    calculated_at: str

    # Availability
    availability_pct: float = 100.0
    availability_target: float = SLO_AVAILABILITY_TARGET_PCT
    availability_status: str = "ok"          # ok | warning | breached

    # Error budget
    error_budget_remaining_pct: float = 100.0
    error_budget_consumed_seconds: float = 0.0
    error_budget_total_seconds: float = ALLOWED_CRITICAL_SECONDS

    # API latency
    latency_current_ms: float = 0.0
    latency_budget_ms: float = SLO_LATENCY_BUDGET_MS
    latency_used_pct: float = 0.0
    latency_status: str = "ok"

    # PostgreSQL saturation
    pg_current_pct: float = 0.0
    pg_target_pct: float = SLO_PG_SATURATION_TARGET_PCT
    pg_headroom_pct: float = 75.0
    pg_status: str = "ok"

    # Poll reliability
    poll_success_rate: float = 100.0
    poll_reliability_target: float = SLO_POLL_RELIABILITY_TARGET
    poll_status: str = "ok"

    # Incident metrics
    incidents_last_24h: int = 0
    mttr_avg_minutes: float = 0.0
    suppression_rate_pct: float = 0.0

    # Overall SLO health
    overall_status: str = "ok"           # ok | at_risk | breached


@dataclass
class MetricSample:
    """One metric sample appended to logs/metrics.jsonl."""
    environment: str
    sampled_at: str
    poll_cycle: int
    health_score: int
    health_label: str
    availability_pct: float
    error_budget_remaining_pct: float
    latency_ms: float
    pg_connection_pct: float
    server_memory_pct: float
    platform_heap_pct: float
    active_incidents: int
    suppressed_warnings: int
    total_jdbc: int
    poll_success: bool


# ── Metrics state (in-memory, per environment) ────────────────────────────────

_state: dict = {}   # env_name → {poll_count, critical_seconds, ...}


def _get_env_state(env_name: str) -> dict:
    if env_name not in _state:
        _state[env_name] = {
            "poll_count": 0,
            "poll_success_count": 0,
            "critical_poll_count": 0,
            "critical_seconds_accumulated": 0.0,
            "total_seconds_accumulated": 0.0,
            "latency_samples": [],
            "incident_mttr_samples": [],
            "suppressed_count": 0,
            "incident_count": 0,
        }
    return _state[env_name]


# ── Main calculation ──────────────────────────────────────────────────────────

def calculate_slo(
    env_name: str,
    env_state: dict,
    poll_interval_seconds: int = 60,
) -> SloStatus:
    """
    Calculate current SLO status from env_state dict.
    Updates in-memory accumulators.
    Returns SloStatus for state.json.
    """

    s = _get_env_state(env_name)
    now = datetime.now(timezone.utc)

    # ── Poll tracking ──────────────────────────────────────────────────────
    s["poll_count"] += 1
    s["total_seconds_accumulated"] += poll_interval_seconds

    pg      = env_state.get("postgres") or {}
    http    = env_state.get("http") or {}
    win     = env_state.get("windows") or {}
    svc     = env_state.get("services") or {}
    incs    = env_state.get("incidents") or []
    supp    = env_state.get("suppressed_warnings") or []

    # http dict uses all_reachable not available — handle both
    http_ok = (
        http.get("all_reachable", False) or
        http.get("available", False) or
        http.get("overall_severity", "critical") == "ok"
    )
    poll_success = (
        pg.get("available", False) and
        http_ok and
        win.get("available", False)
    )
    if poll_success:
        s["poll_success_count"] += 1

    # ── Availability ───────────────────────────────────────────────────────
    health_label = env_state.get("health_label", "HEALTHY")
    is_critical = health_label == "CRITICAL"
    if is_critical:
        s["critical_poll_count"] += 1
        s["critical_seconds_accumulated"] += poll_interval_seconds

    total_polls = s["poll_count"]
    critical_polls = s["critical_poll_count"]
    availability_pct = round(
        (total_polls - critical_polls) / total_polls * 100, 3
    ) if total_polls > 0 else 100.0

    # Error budget
    consumed_seconds = s["critical_seconds_accumulated"]
    budget_remaining_pct = round(
        max(0, (ALLOWED_CRITICAL_SECONDS - consumed_seconds) / ALLOWED_CRITICAL_SECONDS * 100), 2
    )

    avail_status = "ok"
    if availability_pct < SLO_AVAILABILITY_TARGET_PCT:
        avail_status = "breached"
    elif availability_pct < SLO_AVAILABILITY_TARGET_PCT + 0.3:
        avail_status = "at_risk"

    # ── API Latency ────────────────────────────────────────────────────────
    checks = http.get("checks") or []
    latency_ms = checks[0].get("latency_ms", 0) if checks else 0
    s["latency_samples"].append(latency_ms)
    if len(s["latency_samples"]) > 1440:   # keep 24h of samples
        s["latency_samples"].pop(0)

    latency_used_pct = round(latency_ms / SLO_LATENCY_BUDGET_MS * 100, 1)
    latency_status = "ok"
    if latency_ms >= SLO_LATENCY_BUDGET_MS:
        latency_status = "breached"
    elif latency_ms >= SLO_LATENCY_BUDGET_MS * 0.7:
        latency_status = "at_risk"

    # ── PostgreSQL saturation ──────────────────────────────────────────────
    pg_pct = pg.get("connection_pct", 0.0)
    pg_headroom = round(SLO_PG_SATURATION_TARGET_PCT - pg_pct, 1)
    pg_status = "ok"
    if pg_pct >= SLO_PG_SATURATION_TARGET_PCT:
        pg_status = "breached"
    elif pg_pct >= SLO_PG_SATURATION_TARGET_PCT * 0.85:
        pg_status = "at_risk"

    # ── Poll reliability ───────────────────────────────────────────────────
    poll_success_rate = round(
        s["poll_success_count"] / total_polls * 100, 2
    ) if total_polls > 0 else 100.0
    poll_status = "ok" if poll_success_rate >= SLO_POLL_RELIABILITY_TARGET else "at_risk"

    # ── Incident metrics ───────────────────────────────────────────────────
    s["incident_count"] += len(incs)
    s["suppressed_count"] += len(supp)
    total_signals = s["incident_count"] + s["suppressed_count"]
    suppression_rate = round(
        s["suppressed_count"] / total_signals * 100, 1
    ) if total_signals > 0 else 0.0

    # ── MTTR from incident history ─────────────────────────────────────────
    mttr_avg = _calculate_mttr_avg(env_name)

    # ── Overall SLO status ─────────────────────────────────────────────────
    statuses = [avail_status, latency_status, pg_status, poll_status]
    if "breached" in statuses:
        overall = "breached"
    elif "at_risk" in statuses:
        overall = "at_risk"
    else:
        overall = "ok"

    slo = SloStatus(
        environment=env_name,
        calculated_at=now.isoformat(),
        availability_pct=availability_pct,
        availability_target=SLO_AVAILABILITY_TARGET_PCT,
        availability_status=avail_status,
        error_budget_remaining_pct=budget_remaining_pct,
        error_budget_consumed_seconds=round(consumed_seconds, 1),
        error_budget_total_seconds=round(ALLOWED_CRITICAL_SECONDS, 1),
        latency_current_ms=latency_ms,
        latency_budget_ms=SLO_LATENCY_BUDGET_MS,
        latency_used_pct=latency_used_pct,
        latency_status=latency_status,
        pg_current_pct=round(pg_pct, 1),
        pg_target_pct=SLO_PG_SATURATION_TARGET_PCT,
        pg_headroom_pct=pg_headroom,
        pg_status=pg_status,
        poll_success_rate=poll_success_rate,
        poll_reliability_target=SLO_POLL_RELIABILITY_TARGET,
        poll_status=poll_status,
        incidents_last_24h=len(incs),
        mttr_avg_minutes=mttr_avg,
        suppression_rate_pct=suppression_rate,
        overall_status=overall,
    )

    logger.info(
        "[%s] SLO: avail=%.3f%% budget=%.1f%% latency=%dms pg=%.1f%% status=%s",
        env_name, availability_pct, budget_remaining_pct,
        latency_ms, pg_pct, overall.upper()
    )

    return slo


def _calculate_mttr_avg(env_name: str) -> float:
    """Read incident history and calculate average MTTR in minutes."""
    history_path = Path("dashboard/incident_history.jsonl")
    if not history_path.exists():
        return 0.0

    mttr_values = []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if record.get("environment") != env_name:
                        continue
                    mttr_s = record.get("mttr_seconds")
                    if mttr_s and mttr_s > 0:
                        mttr_values.append(mttr_s / 60)
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception:
        return 0.0

    return round(sum(mttr_values) / len(mttr_values), 1) if mttr_values else 0.0


# ── Metrics log writer ────────────────────────────────────────────────────────

def append_metric_sample(
    env_name: str,
    env_state: dict,
    slo: SloStatus,
    poll_interval_seconds: int = 60,
) -> None:
    """Append one metric sample to logs/metrics.jsonl."""

    pg   = env_state.get("postgres") or {}
    http = env_state.get("http") or {}
    win  = env_state.get("windows") or {}
    svc  = env_state.get("services") or {}
    incs = env_state.get("incidents") or []
    supp = env_state.get("suppressed_warnings") or []

    checks   = http.get("checks") or []
    latency  = checks[0].get("latency_ms", 0) if checks else 0

    svcs = win.get("services") or []
    platform_svc = next(
        (s for s in svcs if "Platform" in s.get("display_name", "")), None
    )
    heap_pct = platform_svc.get("heap_used_pct", 0) if platform_svc else 0

    jdbc = svc.get("connections_by_db") or {}
    total_jdbc = sum(jdbc.values())

    # http dict uses all_reachable not available — handle both
    http_ok = (
        http.get("all_reachable", False) or
        http.get("available", False) or
        http.get("overall_severity", "critical") == "ok"
    )
    poll_success = (
        pg.get("available", False) and
        http_ok and
        win.get("available", False)
    )

    sample = {
        "environment":              env_name,
        "sampled_at":               datetime.now(timezone.utc).isoformat(),
        "poll_interval_seconds":    poll_interval_seconds,
        "health_score":             env_state.get("health_score", 0),
        "health_label":             env_state.get("health_label", "UNKNOWN"),
        "availability_pct":         slo.availability_pct,
        "error_budget_remaining":     slo.error_budget_remaining_pct,
        "error_budget_remaining_pct":  slo.error_budget_remaining_pct,
        "latency_ms":               latency,
        "latency_used_pct":         slo.latency_used_pct,
        "pg_connection_pct":        round(pg.get("connection_pct", 0), 1),
        "pg_long_queries":          pg.get("long_running_queries", 0),
        "pg_blocked_queries":       pg.get("blocked_queries", 0),
        "server_memory_pct":        round(win.get("memory_used_pct", 0), 1),
        "platform_heap_pct":        round(heap_pct, 1),
        "active_incidents":         len(incs),
        "suppressed_warnings":      len(supp),
        "total_jdbc":               total_jdbc,
        "poll_success":             poll_success,
        "slo_overall":              slo.overall_status,
    }

    log_path = Path("logs/metrics.jsonl")
    log_path.parent.mkdir(exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(sample) + "\n")
