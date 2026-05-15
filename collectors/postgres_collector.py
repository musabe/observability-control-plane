"""
collectors/postgres_collector.py
---------------------------------
Read-only PostgreSQL health collector.
Connects with a read-only user and collects:
  - Connection pool utilisation
  - Long-running queries
  - Blocked / waiting queries
  - Database availability
  - Basic DB-level stats

All queries use pg_stat_* system views — no application tables are read here.
Application-level Qmatic checks live in integrations/qmatic/.
"""

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None  # allow import without driver for unit tests

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class LongRunningQuery:
    pid: int
    duration_seconds: float
    state: str
    query_preview: str          # first 120 chars, safe for logging
    wait_event: Optional[str]


@dataclass
class BlockedQuery:
    pid: int
    duration_seconds: float
    blocking_pid: int
    query_preview: str


@dataclass
class PostgresSnapshot:
    environment: str
    collected_at: datetime
    available: bool
    error: Optional[str]

    # Connection stats
    active_connections: int = 0
    max_connections: int = 0
    connection_pct: float = 0.0

    # Query health
    long_running_queries: list[LongRunningQuery] = field(default_factory=list)
    blocked_queries: list[BlockedQuery] = field(default_factory=list)

    # DB stats
    db_size_mb: float = 0.0
    transactions_per_second: float = 0.0
    cache_hit_ratio: float = 0.0

    # Derived severity
    severity: str = "ok"        # ok | warning | critical

    def compute_severity(self, thresholds: dict) -> None:
        warn_pct = thresholds.get("connection_pct_warning", 75)
        crit_pct = thresholds.get("connection_pct_critical", 90)
        long_q_s = thresholds.get("long_query_seconds", 30)

        if (self.connection_pct >= crit_pct
                or any(q.duration_seconds > long_q_s * 2 for q in self.long_running_queries)
                or len(self.blocked_queries) >= 3):
            self.severity = "critical"
        elif (self.connection_pct >= warn_pct
              or self.long_running_queries
              or self.blocked_queries):
            self.severity = "warning"
        else:
            self.severity = "ok"


# ── Queries ───────────────────────────────────────────────────────────────────

_Q_CONNECTIONS = """
SELECT
    count(*) FILTER (WHERE state IS NOT NULL)          AS active_connections,
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections
FROM pg_stat_activity;
"""

_Q_LONG_RUNNING = """
SELECT
    pid,
    EXTRACT(EPOCH FROM (now() - query_start))::float AS duration_seconds,
    state,
    left(query, 120)                                  AS query_preview,
    wait_event
FROM pg_stat_activity
WHERE datname = current_database()
  AND state NOT IN ('idle', 'idle in transaction (aborted)')
  AND query_start IS NOT NULL
  AND EXTRACT(EPOCH FROM (now() - query_start)) > %(threshold_seconds)s
ORDER BY duration_seconds DESC
LIMIT 20;
"""

_Q_BLOCKED = """
SELECT
    blocked.pid,
    EXTRACT(EPOCH FROM (now() - blocked.query_start))::float AS duration_seconds,
    blocking.pid                                              AS blocking_pid,
    left(blocked.query, 120)                                  AS query_preview
FROM pg_stat_activity AS blocked
JOIN pg_stat_activity AS blocking
    ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
WHERE blocked.datname = current_database()
LIMIT 20;
"""

_Q_DB_STATS = """
SELECT
    pg_database_size(current_database()) / 1048576.0  AS size_mb,
    blks_hit::float / NULLIF(blks_hit + blks_read, 0) AS cache_hit_ratio,
    xact_commit + xact_rollback                        AS total_transactions
FROM pg_stat_database
WHERE datname = current_database();
"""


# ── Collector ─────────────────────────────────────────────────────────────────

class PostgresCollector:
    def __init__(self, env_name: str, pg_config):
        self.env_name = env_name
        self.cfg = pg_config
        self._prev_transactions: Optional[int] = None
        self._prev_ts: Optional[float] = None

    def _connect(self):
        if psycopg2 is None:
            raise RuntimeError("psycopg2 not installed")
        return psycopg2.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            dbname=self.cfg.database,
            user=self.cfg.username,
            password=self.cfg.password,
            connect_timeout=self.cfg.connect_timeout_seconds,
            options="-c default_transaction_read_only=on",
        )

    def collect(self) -> PostgresSnapshot:
        snap = PostgresSnapshot(
            environment=self.env_name,
            collected_at=datetime.now(timezone.utc),
            available=False,
            error=None,
        )

        conn = None
        try:
            conn = self._connect()
            snap.available = True
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            # Connections
            cur.execute(_Q_CONNECTIONS)
            row = cur.fetchone()
            snap.active_connections = row["active_connections"] or 0
            snap.max_connections = row["max_connections"] or 1
            snap.connection_pct = (snap.active_connections / snap.max_connections) * 100

            # Long-running queries
            threshold = self.cfg.thresholds.get("long_query_seconds", 30)
            cur.execute(_Q_LONG_RUNNING, {"threshold_seconds": threshold})
            snap.long_running_queries = [
                LongRunningQuery(
                    pid=r["pid"],
                    duration_seconds=r["duration_seconds"],
                    state=r["state"],
                    query_preview=r["query_preview"],
                    wait_event=r["wait_event"],
                )
                for r in cur.fetchall()
            ]

            # Blocked queries
            cur.execute(_Q_BLOCKED)
            snap.blocked_queries = [
                BlockedQuery(
                    pid=r["pid"],
                    duration_seconds=r["duration_seconds"],
                    blocking_pid=r["blocking_pid"],
                    query_preview=r["query_preview"],
                )
                for r in cur.fetchall()
            ]

            # DB stats
            cur.execute(_Q_DB_STATS)
            row = cur.fetchone()
            snap.db_size_mb = float(row["size_mb"] or 0)
            snap.cache_hit_ratio = float(row["cache_hit_ratio"] or 0)
            total_tx = row["total_transactions"] or 0

            now = time.monotonic()
            if self._prev_transactions is not None and self._prev_ts is not None:
                elapsed = now - self._prev_ts
                if elapsed > 0:
                    snap.transactions_per_second = (total_tx - self._prev_transactions) / elapsed
            self._prev_transactions = total_tx
            self._prev_ts = now

            snap.compute_severity(self.cfg.thresholds)

        except Exception as exc:
            snap.error = str(exc)
            snap.severity = "critical"
            logger.error("[%s] PostgreSQL collection failed: %s", self.env_name, exc)

        finally:
            if conn:
                conn.close()

        return snap

