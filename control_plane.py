"""
control_plane.py
----------------
Main entry point for the observability control plane.
Loads all configured environments and runs a continuous poll loop:

  For each environment:
    1. Collect PostgreSQL health      (collectors/postgres_collector.py)
    2. Collect HTTP health            (collectors/http_collector.py)
    3. Run Qmatic DB checks           (integrations/qmatic/qmatic_postgres_checks.py)
    4. Detect activity anomalies      (integrations/qmatic/qmatic_activity_checks.py)
    5. Detect reporting anomalies     (integrations/qmatic/qmatic_reporting_checks.py)
    6. Correlate signals              (correlators/correlator.py)
    7. Generate RCA for each incident (rca/rca_generator.py)
    8. Write state for dashboard

Usage:
  python control_plane.py
  python control_plane.py --config config/environments.yaml --once
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Local imports ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config.loader import load_environments
from collectors.postgres_collector import PostgresCollector
from collectors.http_collector import HttpCollector
from collectors.windows_collector import WindowsCollector
from integrations.qmatic.qmatic_postgres_checks import QmaticPostgresChecks
from integrations.qmatic.qmatic_activity_checks import QmaticActivityDetector
from integrations.qmatic.qmatic_reporting_checks import QmaticReportingDetector
from correlators.correlator import CorrelationEngine, CorrelatedIncident
from correlators.health_score import calculate_health_score
from rca.rca_generator import RCAGenerator

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("control_plane")


# ── State file ────────────────────────────────────────────────────────────────

STATE_FILE = Path("dashboard/state.json")

def _write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ── Per-environment poll ──────────────────────────────────────────────────────

def poll_environment(env, correlator: CorrelationEngine, rca: RCAGenerator) -> dict:
    env_state = {
        "name": env.name,
        "description": env.description,
        "polled_at": datetime.now(timezone.utc).isoformat(),
        "postgres": None,
        "http": None,
        "activity": None,
        "reporting": None,
        "incidents": [],
        "overall_severity": "ok",
    }

    pg_snap = None
    http_snap = None
    activity_result = None
    reporting_result = None

    # ── 1. PostgreSQL health ──────────────────────────────────────────────
    if env.postgres:
        try:
            collector = PostgresCollector(env.name, env.postgres)
            pg_snap = collector.collect()
            env_state["postgres"] = {
                "available": pg_snap.available,
                "severity": pg_snap.severity,
                "connection_pct": round(pg_snap.connection_pct, 1),
                "active_connections": pg_snap.active_connections,
                "max_connections": pg_snap.max_connections,
                "long_running_queries": len(pg_snap.long_running_queries),
                "blocked_queries": len(pg_snap.blocked_queries),
                "error": pg_snap.error,
            }
            logger.info("[%s] PG: %s  connections=%.0f%%  long_queries=%d",
                        env.name, pg_snap.severity.upper(),
                        pg_snap.connection_pct, len(pg_snap.long_running_queries))
        except Exception as exc:
            logger.error("[%s] PostgreSQL collection error: %s", env.name, exc)

    # ── 2. HTTP health ────────────────────────────────────────────────────
    if env.http_checks:
        try:
            collector = HttpCollector(env.name, env.http_checks)
            http_snap = collector.collect()
            env_state["http"] = {
                "overall_severity": http_snap.overall_severity,
                "all_reachable": http_snap.all_reachable,
                "checks": [
                    {
                        "name": c.name,
                        "severity": c.severity,
                        "latency_ms": round(c.latency_ms, 1),
                        "status_code": c.status_code,
                        "reachable": c.reachable,
                    }
                    for c in http_snap.checks
                ],
            }
            logger.info("[%s] HTTP: %s", env.name, http_snap.overall_severity.upper())
        except Exception as exc:
            logger.error("[%s] HTTP collection error: %s", env.name, exc)

    # ── 2b. Windows memory + service checks ─────────────────────────────
    if env.windows_host:
        try:
            win_collector = WindowsCollector(env.name, env.windows_host, env.windows_config)
            win_snap = win_collector.collect()
            env_state["windows"] = {
                "available": win_snap.available,
                "severity": win_snap.severity,
                "memory_severity": win_snap.memory_severity,
                "total_memory_mb": win_snap.total_memory_mb,
                "free_memory_mb": win_snap.free_memory_mb,
                "used_memory_mb": win_snap.used_memory_mb,
                "memory_used_pct": win_snap.memory_used_pct,
                "qmatic_total_memory_mb": win_snap.qmatic_total_memory_mb,
                "jvm_heap_max_mb": win_snap.jvm_heap_max_mb,
                "jvm_heap_source": win_snap.jvm_heap_source,
                "services": [
                    {
                        "name": s.name,
                        "display_name": s.display_name,
                        "state": s.state,
                        "memory_mb": s.memory_mb,
                        "xmx_mb": s.xmx_mb,
                        "heap_used_pct": s.heap_used_pct,
                        "heap_severity": s.heap_severity,
                    }
                    for s in win_snap.services
                ],
                "error": win_snap.error,
            }
        except Exception as exc:
            logger.error("[%s] Windows collection error: %s", env.name, exc)

    # ── 3. Qmatic DB checks ───────────────────────────────────────────────
    qmatic_checks = None
    queue_activity = None
    reporting_snap = None

    if env.postgres:
        try:
            qmatic_checks = QmaticPostgresChecks(env.name, env.postgres)
            svc_snap = qmatic_checks.collect_service_connections()
            env_state["services"] = {
                "connections_by_db": svc_snap.connections_by_db,
                "missing_services": svc_snap.missing_services,
                "severity": svc_snap.severity,
            }
            if svc_snap.missing_services:
                logger.warning("[%s] Missing JDBC connections: %s",
                               env.name, svc_snap.missing_services)
            else:
                logger.info("[%s] Services: %s",
                            env.name, svc_snap.connections_by_db)
            if env.reporting.enabled:
                queue_activity = qmatic_checks.collect_queue_activity()
            if env.reporting.enabled:
                reporting_snap = qmatic_checks.collect_reporting_anomalies(
                duplicate_threshold=env.reporting.duplicate_visit_threshold
            )
        except Exception as exc:
            logger.error("[%s] Qmatic DB checks error: %s", env.name, exc)

    # ── 4. Activity anomaly detection ─────────────────────────────────────
    if queue_activity is not None:
        try:
            detector = QmaticActivityDetector(env)
            activity_result = detector.check(queue_activity)
            env_state["activity"] = {
                "is_business_hours": activity_result.is_business_hours,
                "severity": activity_result.severity,
                "anomaly_count": len(activity_result.anomalies),
                "total_visits_today": queue_activity.total_visits_today,
                "delivered_visits_today": queue_activity.delivered_visits_today,
                "waiting_visits_now": queue_activity.waiting_visits_now,
                "active_branches": queue_activity.active_branches,
            }
            if activity_result.anomalies:
                logger.warning("[%s] Activity anomalies: %d detected",
                               env.name, len(activity_result.anomalies))
        except Exception as exc:
            logger.error("[%s] Activity detection error: %s", env.name, exc)

    # ── 5. Reporting anomaly detection ────────────────────────────────────
    if reporting_snap is not None:
        try:
            rep_detector = QmaticReportingDetector(env)
            reporting_result = rep_detector.check(reporting_snap)
            env_state["reporting"] = {
                "severity": reporting_result.severity,
                "anomaly_count": len(reporting_result.anomalies),
            }
            if reporting_result.anomalies:
                logger.warning("[%s] Reporting anomalies: %d detected",
                               env.name, len(reporting_result.anomalies))
        except Exception as exc:
            logger.error("[%s] Reporting detection error: %s", env.name, exc)

    # ── 6. Correlate ──────────────────────────────────────────────────────
    # Build win_snap and svc_snap dicts for correlator
    _win_for_corr = env_state.get("windows") if env_state.get("windows") else None
    _svc_for_corr = env_state.get("services") if env_state.get("services") else None

    active_incidents, suppressed_warnings = correlator.correlate(
        env,
        pg_snap=pg_snap,
        http_snap=http_snap,
        activity_result=activity_result,
        reporting_result=reporting_result,
        win_snap=_win_for_corr,
        svc_snap=_svc_for_corr,
    )
    incidents = active_incidents

    # ── 7. Generate RCA ───────────────────────────────────────────────────
    incident_summaries = []
    for incident in active_incidents:
        summary = rca.generate(incident, pg_snap=pg_snap)
        filepath = rca.save_markdown(summary)
        rca.log_alert(summary)
        incident_summaries.append({
            **summary.to_dict(),
            "confidence": incident.confidence,
            "rca_file": filepath,
        })
        logger.warning(
            "[%s] INCIDENT: %s [%s] confidence=%d%%",
            env.name, incident.title,
            incident.severity.upper(), incident.confidence)

    suppressed_summaries = []
    for inc in suppressed_warnings:
        suppressed_summaries.append({
            "incident_type": inc.incident_type,
            "title": inc.title,
            "severity": inc.severity,
            "confidence": inc.confidence,
            "suppressed": True,
            "correlated_at": inc.correlated_at.isoformat(),
        })
        logger.info(
            "[%s] SUPPRESSED (conf=%d%%): %s",
            env.name, inc.confidence, inc.title)

    env_state["incidents"] = incident_summaries
    env_state["suppressed_warnings"] = suppressed_summaries

    # ── 8. Health score + overall severity ───────────────────────────────────
    health_score, health_label, overall_severity = calculate_health_score(
        incidents=incident_summaries,
        suppressed_warnings=suppressed_summaries,
        pg_snap=pg_snap,
        http_snap=http_snap,
        win_snap=env_state.get("windows"),
    )
    env_state["health_score"] = health_score
    env_state["health_label"] = health_label
    env_state["overall_severity"] = overall_severity
    logger.info("[%s] Health: %d (%s)", env.name, health_score, health_label)

    return env_state


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(config_path: str, poll_once: bool = False) -> None:
    environments = load_environments(config_path)
    if not environments:
        logger.error("No enabled environments found in %s", config_path)
        sys.exit(1)

    logger.info("Loaded %d environment(s): %s",
                len(environments), [e.name for e in environments])

    correlator = CorrelationEngine()
    rca = RCAGenerator(output_dir="incidents")

    _running = True

    def _shutdown(sig, frame):
        nonlocal _running
        logger.info("Shutdown signal received")
        _running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while _running:
        poll_start = time.monotonic()
        state = {
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "environments": [],
        }

        for env in environments:
            logger.info("Polling environment: %s", env.name)
            env_state = poll_environment(env, correlator, rca)
            state["environments"].append(env_state)

        _write_state(state)
        logger.info("State written to %s", STATE_FILE)

        if poll_once:
            break

        elapsed = time.monotonic() - poll_start
        sleep_for = max(0, 60 - elapsed)
        logger.info("Sleeping %.0fs until next poll", sleep_for)
        time.sleep(sleep_for)

    logger.info("Control plane stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Observability Control Plane")
    parser.add_argument("--config", default="config/environments.yaml", help="Config file path")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    args = parser.parse_args()
    run(config_path=args.config, poll_once=args.once)


if __name__ == "__main__":
    main()

