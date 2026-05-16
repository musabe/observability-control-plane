"""
integrations/qmatic/qmatic_postgres_checks.py
----------------------------------------------
Qmatic-specific PostgreSQL checks.
Queries Qmatic application tables to detect operational anomalies.

These are SEPARATE from the generic postgres_collector which only reads
pg_stat_* system views. These queries touch Qmatic schema tables directly.

Read-only. All queries use SELECT only.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ServiceConnectionSnapshot:
    environment: str
    collected_at: datetime
    connections_by_db: dict = field(default_factory=dict)
    missing_services: list = field(default_factory=list)
    severity: str = "ok"


@dataclass
class QueueActivitySnapshot:
    environment: str
    collected_at: datetime
    total_visits_today: int = 0
    delivered_visits_today: int = 0
    waiting_visits_now: int = 0
    no_show_visits_today: int = 0
    avg_wait_time_seconds: float = 0.0
    active_branches: int = 0
    active_service_points: int = 0


@dataclass
class ReportingAnomalyResult:
    environment: str
    collected_at: datetime
    duplicate_visit_ids: list = field(default_factory=list)
    suspected_carryover_counts: list = field(default_factory=list)
    missing_expected_activity: bool = False
    anomalies_found: int = 0


@dataclass
class LongJobResult:
    environment: str
    collected_at: datetime
    long_report_jobs: list = field(default_factory=list)
    stuck_queue_jobs: list = field(default_factory=list)


# ── Queries ───────────────────────────────────────────────────────────────────
# NOTE: Table and column names are representative of Qmatic Orchestra schema.
# Adjust to match the exact schema version in the target environment.

_Q_SERVICE_CONNECTIONS = """
SELECT
    datname,
    count(*) AS jdbc_connections
FROM pg_stat_activity
WHERE application_name = 'PostgreSQL JDBC Driver'
GROUP BY datname
ORDER BY jdbc_connections DESC;
"""

_Q_QUEUE_ACTIVITY = """
SELECT
    COUNT(*)                                                    AS total_visits,
    COUNT(*) FILTER (WHERE status = 'CALLED')                  AS delivered_visits,
    COUNT(*) FILTER (WHERE status IN ('WAITING', 'CALLED'))    AS waiting_now,
    COUNT(*) FILTER (WHERE status = 'NOSHOW')                  AS no_shows,
    AVG(EXTRACT(EPOCH FROM (called_time - arrival_time)))
        FILTER (WHERE called_time IS NOT NULL)                  AS avg_wait_seconds
FROM visit
WHERE DATE(arrival_time) = CURRENT_DATE
  AND arrival_time >= NOW() - INTERVAL '24 hours';
"""

_Q_ACTIVE_BRANCHES = """
SELECT
    COUNT(DISTINCT branch_id)        AS active_branches,
    COUNT(DISTINCT service_point_id) AS active_service_points
FROM visit
WHERE DATE(arrival_time) = CURRENT_DATE
  AND arrival_time >= NOW() - INTERVAL '8 hours';
"""

_Q_DUPLICATE_VISITS = """
SELECT
    visit_id,
    COUNT(*) AS occurrence_count,
    MIN(arrival_time) AS first_seen,
    MAX(arrival_time) AS last_seen
FROM visit
WHERE DATE(arrival_time) = CURRENT_DATE
GROUP BY visit_id
HAVING COUNT(*) > %(threshold)s
ORDER BY occurrence_count DESC
LIMIT 20;
"""

_Q_CARRYOVER_DETECTION = """
-- Detect visits where arrival_time is yesterday but updated today
-- Symptom of midnight rollover / counting bug
SELECT
    id,
    visit_id,
    arrival_time,
    updated_at,
    status
FROM visit
WHERE DATE(arrival_time) < CURRENT_DATE
  AND DATE(updated_at) = CURRENT_DATE
  AND status IN ('WAITING', 'CALLED')
ORDER BY arrival_time
LIMIT 50;
"""

_Q_LONG_REPORT_JOBS = """
-- Detect long-running or stuck reporting/statistics jobs
SELECT
    id,
    job_type,
    started_at,
    EXTRACT(EPOCH FROM (NOW() - started_at)) AS duration_seconds,
    status,
    branch_id
FROM scheduled_job
WHERE status IN ('RUNNING', 'PENDING')
  AND started_at < NOW() - INTERVAL '%(threshold_minutes)s minutes'
ORDER BY started_at
LIMIT 20;
"""


# ── Collector ─────────────────────────────────────────────────────────────────

class QmaticPostgresChecks:
    """
    Runs Qmatic-domain SQL checks against the application database.
    Requires a read-only database user with SELECT on:
      - visit
      - scheduled_job
    """

    def __init__(self, env_name: str, pg_config):
        self.env_name = env_name
        self.cfg = pg_config

    def _connect(self):
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise RuntimeError("psycopg2 not installed")

        conn = psycopg2.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            dbname=self.cfg.database,
            user=self.cfg.username,
            password=self.cfg.password,
            connect_timeout=self.cfg.connect_timeout_seconds,
            options="-c default_transaction_read_only=on",
        )
        return conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # ── Public collectors ──────────────────────────────────────────────────

    def collect_service_connections(self) -> ServiceConnectionSnapshot:
        """
        Tracks JDBC connections per database.
        Detects which Qmatic services have gone silent (0 connections).
        """
        result = ServiceConnectionSnapshot(
            environment=self.env_name,
            collected_at=datetime.now(timezone.utc),
        )
        conn = cur = None
        try:
            conn, cur = self._connect()
            cur.execute(_Q_SERVICE_CONNECTIONS)
            rows = cur.fetchall()
            result.connections_by_db = {
                r["datname"]: int(r["jdbc_connections"]) for r in rows
            }
            monitored = getattr(self.cfg, "monitored_databases", [])
            # Always check all monitored DBs — even if not in results (0 connections)
            for db in monitored:
                if result.connections_by_db.get(db, 0) == 0:
                    result.missing_services.append(db)
            # Also add any monitored DB not appearing in results at all
            for db in monitored:
                if db not in result.connections_by_db:
                    result.connections_by_db[db] = 0
            if result.missing_services:
                result.severity = "critical"
        except Exception as exc:
            logger.error("[%s] service_connections failed: %s", self.env_name, exc)
        finally:
            if conn:
                conn.close()
        return result

    def collect_queue_activity(self) -> QueueActivitySnapshot:
        snap = QueueActivitySnapshot(
            environment=self.env_name,
            collected_at=datetime.now(timezone.utc),
        )
        conn = cur = None
        try:
            conn, cur = self._connect()

            cur.execute(_Q_QUEUE_ACTIVITY)
            row = cur.fetchone()
            if row:
                snap.total_visits_today = int(row["total_visits"] or 0)
                snap.delivered_visits_today = int(row["delivered_visits"] or 0)
                snap.waiting_visits_now = int(row["waiting_now"] or 0)
                snap.no_show_visits_today = int(row["no_shows"] or 0)
                snap.avg_wait_time_seconds = float(row["avg_wait_seconds"] or 0)

            cur.execute(_Q_ACTIVE_BRANCHES)
            row = cur.fetchone()
            if row:
                snap.active_branches = int(row["active_branches"] or 0)
                snap.active_service_points = int(row["active_service_points"] or 0)

        except Exception as exc:
            logger.error("[%s] queue_activity collection failed: %s", self.env_name, exc)
        finally:
            if conn:
                conn.close()

        return snap

    def collect_reporting_anomalies(self, duplicate_threshold: int = 3) -> ReportingAnomalyResult:
        result = ReportingAnomalyResult(
            environment=self.env_name,
            collected_at=datetime.now(timezone.utc),
        )
        conn = cur = None
        try:
            conn, cur = self._connect()

            cur.execute(_Q_DUPLICATE_VISITS, {"threshold": duplicate_threshold})
            result.duplicate_visit_ids = [dict(r) for r in cur.fetchall()]

            cur.execute(_Q_CARRYOVER_DETECTION)
            result.suspected_carryover_counts = [dict(r) for r in cur.fetchall()]

            result.anomalies_found = (
                len(result.duplicate_visit_ids) +
                len(result.suspected_carryover_counts)
            )

        except Exception as exc:
            logger.error("[%s] reporting_anomalies collection failed: %s", self.env_name, exc)
        finally:
            if conn:
                conn.close()

        return result

    def collect_long_jobs(self, threshold_minutes: int = 30) -> LongJobResult:
        result = LongJobResult(
            environment=self.env_name,
            collected_at=datetime.now(timezone.utc),
        )
        conn = cur = None
        try:
            conn, cur = self._connect()
            cur.execute(
                _Q_LONG_REPORT_JOBS,
                {"threshold_minutes": threshold_minutes},
            )
            rows = cur.fetchall()
            for r in rows:
                job = dict(r)
                if "report" in (job.get("job_type") or "").lower():
                    result.long_report_jobs.append(job)
                else:
                    result.stuck_queue_jobs.append(job)

        except Exception as exc:
            logger.error("[%s] long_jobs collection failed: %s", self.env_name, exc)
        finally:
            if conn:
                conn.close()

        return result
