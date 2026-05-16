"""
correlators/correlator.py
--------------------------
Correlation engine with real confidence scoring.

Each rule returns a CorrelatedIncident with a confidence score.
The engine applies severity adjustment and suppression based on confidence.

Confidence thresholds:
  < 50%  → suppressed (timeline warning only, no incident/RCA)
  50-79% → warning (even if pattern is critical)
  >= 80% → full severity as detected

Phase 2 rules added:
  - service_stopped_db_drop       : service stopped + JDBC connections dropped
  - memory_pressure_api_cascade   : high JVM memory + API latency spike
  - silent_service_failure        : JDBC connections to DB dropped to 0
  - platform_wide_outage          : multiple services stopped
  - db_saturation_forming         : PG connections trending up (proactive)
  - app_layer_issue               : HTTP slow but DB + services healthy
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from correlators.confidence import (
    calculate_confidence,
    adjust_severity,
    should_suppress,
    append_history,
)

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    source: str
    signal: str
    value: str
    severity: str


@dataclass
class CorrelatedIncident:
    environment: str
    incident_type: str
    title: str
    severity: str
    correlated_at: datetime
    confidence: int = 0
    suppressed: bool = False
    evidence: list[Evidence] = field(default_factory=list)
    likely_cause: str = ""
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "incident_type": self.incident_type,
            "title": self.title,
            "severity": self.severity,
            "confidence": self.confidence,
            "suppressed": self.suppressed,
            "correlated_at": self.correlated_at.isoformat(),
            "evidence": [
                {"source": e.source, "signal": e.signal,
                 "value": e.value, "severity": e.severity}
                for e in self.evidence
            ],
            "likely_cause": self.likely_cause,
            "recommended_actions": self.recommended_actions,
        }


# ── Rule registry ─────────────────────────────────────────────────────────────

_RULES: list[Callable] = []

def correlation_rule(fn: Callable) -> Callable:
    _RULES.append(fn)
    return fn


# ── Helper ────────────────────────────────────────────────────────────────────

def _is_biz_hours(env) -> bool:
    try:
        from integrations.qmatic.qmatic_activity_checks import _is_business_hours
        return _is_business_hours(env.business_hours, env.timezone)
    except Exception:
        return True  # assume business hours if check fails


# ── Phase 1 rules (updated with confidence) ───────────────────────────────────

@correlation_rule
def rule_db_unavailable(env, pg_snap, http_snap, activity_result,
                        reporting_result, win_snap, svc_snap):
    if pg_snap is None or pg_snap.available:
        return None

    evidence = [
        Evidence("postgres", "availability", "UNREACHABLE", "critical"),
        Evidence("postgres", "error", pg_snap.error or "unknown", "critical"),
    ]
    if http_snap and not http_snap.all_reachable:
        evidence.append(Evidence("http", "reachable", "false", "critical"))

    confidence = calculate_confidence(
        "db_unavailable", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="db_unavailable",
        title="PostgreSQL database unavailable",
        severity=adjust_severity("critical", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "The PostgreSQL database is not responding. "
            "All Qmatic operations will fail until connectivity is restored."
        ),
        recommended_actions=[
            "Verify PostgreSQL service is running on the database host",
            "Check network connectivity between application and database",
            "Review PostgreSQL logs for crash or OOM events",
            "Check disk space on the database server",
        ],
    )


@correlation_rule
def rule_db_saturation_api_cascade(env, pg_snap, http_snap, activity_result,
                                   reporting_result, win_snap, svc_snap):
    if pg_snap is None or http_snap is None:
        return None

    high_connections = pg_snap.connection_pct >= 75
    api_slow = http_snap.overall_severity in ("warning", "critical")

    if not (high_connections and api_slow):
        return None

    slow_checks = [c for c in http_snap.checks if c.severity in ("warning", "critical")]
    worst_latency = max((c.latency_ms for c in slow_checks), default=0)

    evidence = [
        Evidence("postgres", "connection_pool_pct",
                 f"{pg_snap.connection_pct:.1f}%", pg_snap.severity),
        Evidence("http", "api_latency_ms",
                 f"{worst_latency:.0f}ms", http_snap.overall_severity),
        Evidence("postgres", "long_running_queries",
                 str(len(pg_snap.long_running_queries)), "warning"),
    ]

    confidence = calculate_confidence(
        "db_saturation_api_cascade", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    raw_sev = "critical" if pg_snap.connection_pct >= 90 else "warning"
    return CorrelatedIncident(
        environment=env.name,
        incident_type="db_saturation_api_cascade",
        title="Database saturation causing API latency degradation",
        severity=adjust_severity(raw_sev, confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "Database connection pool saturation is causing query queuing "
            "which cascades into elevated API response times."
        ),
        recommended_actions=[
            "Review pg_stat_activity for blocking queries",
            "Check application connection pool configuration",
            "Identify any long-running reporting or stats jobs",
            "Verify Qmatic background schedulers are not looping",
        ],
    )


@correlation_rule
def rule_zero_activity_business_hours(env, pg_snap, http_snap, activity_result,
                                      reporting_result, win_snap, svc_snap):
    if activity_result is None or not activity_result.is_business_hours:
        return None

    zero_activity = any(
        a.anomaly_type == "zero_activity" for a in activity_result.anomalies
    )
    if not zero_activity:
        return None

    app_reachable = http_snap is not None and http_snap.all_reachable
    db_ok = pg_snap is not None and pg_snap.available

    evidence = [
        Evidence("activity", "delivered_visits_today", "0", "critical"),
        Evidence("http", "app_reachable",
                 str(app_reachable), "ok" if app_reachable else "critical"),
        Evidence("postgres", "db_available",
                 str(db_ok), "ok" if db_ok else "critical"),
    ]

    confidence = calculate_confidence(
        "zero_activity_business_hours", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=True,
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="zero_activity_business_hours",
        title="No queue activity during business hours",
        severity=adjust_severity("critical", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "No visits recorded during business hours despite the system "
            "appearing operational."
        ),
        recommended_actions=[
            "Verify branch is open and terminals are online in Qmatic admin",
            "Check Qmatic licence status",
            "Confirm service point staff are logged in",
            "Review Qmatic application logs for errors",
        ],
    )


@correlation_rule
def rule_reporting_anomaly_db_pressure(env, pg_snap, http_snap, activity_result,
                                       reporting_result, win_snap, svc_snap):
    if reporting_result is None or pg_snap is None:
        return None

    has_reporting_anomaly = reporting_result.severity in ("warning", "critical")
    has_long_queries = len(pg_snap.long_running_queries) > 0

    if not (has_reporting_anomaly and has_long_queries):
        return None

    worst_duration = max(
        (q.duration_seconds for q in pg_snap.long_running_queries), default=0
    )

    evidence = [
        Evidence("reporting", "anomalies_found",
                 str(len(reporting_result.anomalies)), "warning"),
        Evidence("postgres", "long_running_queries",
                 f"{len(pg_snap.long_running_queries)} queries", "warning"),
        Evidence("postgres", "worst_query_duration",
                 f"{worst_duration:.0f}s", "warning"),
    ]

    confidence = calculate_confidence(
        "reporting_anomaly_with_db_pressure", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="reporting_anomaly_with_db_pressure",
        title="Reporting anomalies correlated with long-running DB queries",
        severity=adjust_severity("warning", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "A statistics or reporting job is running longer than expected "
            "and may be producing duplicate or incorrect visit counts."
        ),
        recommended_actions=[
            "Identify and terminate the long-running statistics query",
            "Review Qmatic scheduled job logs for errors",
            "Check if carryover counts indicate a midnight rollover issue",
        ],
    )


# ── Phase 2 rules ─────────────────────────────────────────────────────────────

@correlation_rule
def rule_service_stopped_db_drop(env, pg_snap, http_snap, activity_result,
                                 reporting_result, win_snap, svc_snap):
    """
    Qmatic service stopped AND JDBC connections to its database dropped.
    High-confidence signal of a service crash.
    """
    if win_snap is None or svc_snap is None:
        return None

    stopped = [s for s in (win_snap.get("services") or [] if isinstance(win_snap, dict) else []) if s.get("state") != "Running"]
    missing_jdbc = svc_snap.get("missing_services", []) if isinstance(svc_snap, dict) else []

    if not stopped or not missing_jdbc:
        return None

    evidence = [
        Evidence("windows", "stopped_services",
                 ", ".join(s["display_name"] for s in stopped), "critical"),
        Evidence("services", "missing_jdbc",
                 ", ".join(missing_jdbc), "critical"),
    ]
    if pg_snap:
        evidence.append(Evidence("postgres", "connection_pct",
                                 f"{pg_snap.connection_pct:.1f}%", pg_snap.severity))

    confidence = calculate_confidence(
        "service_stopped_db_drop", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="service_stopped_db_drop",
        title=f"Qmatic service crash detected — {stopped[0]['display_name']}",
        severity=adjust_severity("critical", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "A Qmatic Windows service has stopped and its database connections "
            "have dropped to zero, indicating a service crash or forced stop."
        ),
        recommended_actions=[
            f"Check Windows Event Log for {stopped[0]['name']} crash details",
            "Review Qmatic application logs for Java exceptions",
            "Attempt service restart if safe to do so",
            "Check available disk space and JVM heap settings",
        ],
    )


@correlation_rule
def rule_memory_pressure_api_cascade(env, pg_snap, http_snap, activity_result,
                                     reporting_result, win_snap, svc_snap):
    """
    High Qmatic JVM memory + API latency spike.
    Suggests JVM GC pressure causing response time degradation.
    """
    if win_snap is None or http_snap is None:
        return None

    if not isinstance(win_snap, dict):
        return None

    total_mb = win_snap.get("total_memory_mb", 0)
    qmatic_mb = win_snap.get("qmatic_total_memory_mb", 0)
    api_slow = http_snap.overall_severity in ("warning", "critical")

    if total_mb == 0 or not api_slow:
        return None

    qmatic_mem_pct = (qmatic_mb / total_mb) * 100 if total_mb > 0 else 0
    if qmatic_mem_pct < 60:
        return None

    slow_checks = [c for c in http_snap.checks if c.severity in ("warning", "critical")]
    worst_latency = max((c.latency_ms for c in slow_checks), default=0)

    evidence = [
        Evidence("windows", "qmatic_memory_pct",
                 f"{qmatic_mem_pct:.1f}%", "warning"),
        Evidence("windows", "qmatic_memory_mb",
                 f"{qmatic_mb:.0f}MB", "warning"),
        Evidence("http", "api_latency_ms",
                 f"{worst_latency:.0f}ms", http_snap.overall_severity),
    ]

    confidence = calculate_confidence(
        "memory_pressure_api_cascade", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="memory_pressure_api_cascade",
        title="JVM memory pressure causing API latency degradation",
        severity=adjust_severity("warning", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "Qmatic JVM processes are consuming a high percentage of available "
            "server memory. Garbage collection pressure may be causing API "
            "response time degradation."
        ),
        recommended_actions=[
            "Review Qmatic JVM heap settings (-Xmx configuration)",
            "Check for memory leaks in Qmatic application logs",
            "Consider restarting the Qmatic Platform service during low-traffic window",
            "Monitor GC logs if available",
        ],
    )


@correlation_rule
def rule_silent_service_failure(env, pg_snap, http_snap, activity_result,
                                reporting_result, win_snap, svc_snap):
    """
    JDBC connections to a monitored database dropped to 0 but service shows running.
    Silent failure — service is running but not connected to DB.
    """
    if win_snap is None or svc_snap is None:
        return None

    missing_jdbc = []
    if isinstance(svc_snap, dict):
        missing_jdbc = svc_snap.get("missing_services", [])
    
    if not missing_jdbc:
        return None

    # Check if the service appears to be running (makes it more concerning)
    running_services = []
    if isinstance(win_snap, dict) and win_snap.get("services"):
        running_services = [s["display_name"] for s in win_snap["services"]
                           if s.get("state") == "Running"]

    evidence = [
        Evidence("services", "missing_jdbc",
                 ", ".join(missing_jdbc), "warning"),
        Evidence("services", "running_services",
                 f"{len(running_services)} running", "ok"),
    ]
    if pg_snap:
        evidence.append(Evidence("postgres", "availability",
                                 "online" if pg_snap.available else "offline",
                                 "ok" if pg_snap.available else "critical"))

    confidence = calculate_confidence(
        "silent_service_failure", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="silent_service_failure",
        title=f"Silent DB disconnection — {', '.join(missing_jdbc)}",
        severity=adjust_severity("warning", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "One or more monitored databases have zero JDBC connections despite "
            "the Qmatic service appearing to run. This may indicate a connection "
            "pool exhaustion, DB restart, or silent application error."
        ),
        recommended_actions=[
            f"Check pg_stat_activity for connections to {', '.join(missing_jdbc)}",
            "Review Qmatic application logs for JDBC connection errors",
            "Verify the database is accepting connections",
            "Consider restarting the affected Qmatic service",
        ],
    )


@correlation_rule
def rule_app_layer_issue(env, pg_snap, http_snap, activity_result,
                         reporting_result, win_snap, svc_snap):
    """
    HTTP slow but DB healthy and services running.
    Isolated application-layer issue — not infrastructure.
    """
    if http_snap is None or pg_snap is None:
        return None

    api_slow = http_snap.overall_severity in ("warning", "critical")
    db_healthy = pg_snap.available and pg_snap.severity == "ok"
    services_ok = True
    if isinstance(win_snap, dict) and win_snap.get("services"):
        stopped = [s for s in win_snap["services"] if s.get("state") != "Running"]
        services_ok = len(stopped) == 0

    if not (api_slow and db_healthy and services_ok):
        return None

    slow_checks = [c for c in http_snap.checks if c.severity in ("warning", "critical")]
    worst_latency = max((c.latency_ms for c in slow_checks), default=0)

    evidence = [
        Evidence("http", "api_latency_ms",
                 f"{worst_latency:.0f}ms", http_snap.overall_severity),
        Evidence("postgres", "db_healthy", "ok", "ok"),
        Evidence("windows", "services_healthy", "all running", "ok"),
    ]

    confidence = calculate_confidence(
        "app_layer_issue", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="app_layer_issue",
        title="API latency elevated — infrastructure healthy",
        severity=adjust_severity("warning", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            "API response times are elevated but database and services are healthy. "
            "The issue is likely isolated to the application layer — "
            "possible thread pool exhaustion, slow application logic, or network issue."
        ),
        recommended_actions=[
            "Review Qmatic application thread pool configuration",
            "Check for slow application logic in Qmatic logs",
            "Verify network path between monitoring host and application",
            "Check if a recent deployment introduced a regression",
        ],
    )


@correlation_rule
def rule_qmatic_service_stopped(env, pg_snap, http_snap, activity_result,
                                reporting_result, win_snap, svc_snap):
    """
    One or more Qmatic Windows services are stopped.
    Fires regardless of JDBC state — service down is always an incident.
    """
    if win_snap is None:
        return None

    services = win_snap.get("services", []) if isinstance(win_snap, dict) else []
    stopped = [s for s in services if s.get("state") != "Running"]

    if not stopped:
        return None

    stopped_names = [s.get("display_name", s.get("name", "unknown")) for s in stopped]

    evidence = [
        Evidence("windows", "stopped_services",
                 ", ".join(stopped_names), "critical"),
        Evidence("windows", "running_services",
                 f"{len(services)-len(stopped)}/{len(services)}", "warning"),
    ]

    # Add JDBC evidence if available
    if isinstance(svc_snap, dict) and svc_snap.get("missing_services"):
        evidence.append(Evidence("services", "missing_jdbc",
                                 ", ".join(svc_snap["missing_services"]), "critical"))

    confidence = calculate_confidence(
        "qmatic_service_stopped", evidence, env.name,
        pg_snap=pg_snap, http_snap=http_snap,
        is_business_hours=_is_biz_hours(env),
    )

    return CorrelatedIncident(
        environment=env.name,
        incident_type="qmatic_service_stopped",
        title=f"Qmatic service stopped — {', '.join(stopped_names)}",
        severity=adjust_severity("critical", confidence),
        correlated_at=datetime.now(timezone.utc),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        evidence=evidence,
        likely_cause=(
            f"{len(stopped)} Qmatic service(s) are not running. "
            "This will impact customers using the affected modules. "
            "Check Windows Event Log for crash details or manual stop."
        ),
        recommended_actions=[
            f"Check Windows Event Log for {stopped_names[0]} stop/crash reason",
            "Review Qmatic application logs for Java exceptions or OOM errors",
            "Verify disk space and available system memory",
            "Attempt service restart if safe: Services → right-click → Start",
            "Check if this was a planned maintenance stop",
        ],
    )


# ── Engine ────────────────────────────────────────────────────────────────────

class CorrelationEngine:
    """
    Runs all registered correlation rules against a snapshot bundle.
    Returns active incidents (confidence >= 50) and suppressed warnings.
    """

    def correlate(
        self,
        env,
        pg_snap=None,
        http_snap=None,
        activity_result=None,
        reporting_result=None,
        win_snap=None,
        svc_snap=None,
    ) -> tuple[list[CorrelatedIncident], list[CorrelatedIncident]]:
        """
        Returns (active_incidents, suppressed_warnings).
        active_incidents: confidence >= 50, shown as incidents + RCA
        suppressed_warnings: confidence < 50, shown in timeline only
        """
        active = []
        suppressed = []

        for rule in _RULES:
            try:
                incident = rule(
                    env, pg_snap, http_snap, activity_result,
                    reporting_result, win_snap, svc_snap,
                )
                if incident is None:
                    continue

                logger.info(
                    "[%s] %s: %s (confidence=%d%%, severity=%s, suppressed=%s)",
                    env.name, incident.incident_type, incident.title,
                    incident.confidence, incident.severity, incident.suppressed,
                )

                if incident.suppressed:
                    suppressed.append(incident)
                else:
                    active.append(incident)
                    append_history(incident.to_dict())

            except Exception as exc:
                logger.error("Correlation rule %s failed: %s",
                             rule.__name__, exc)

        return active, suppressed
