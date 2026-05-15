"""
patch_service_monitor.py
Run from repo root: python patch_service_monitor.py
"""

from datetime import timezone

# ── New code to inject ────────────────────────────────────────────────────────

NEW_DATACLASS = """
@dataclass
class ServiceConnectionSnapshot:
    environment: str
    collected_at: object
    connections_by_db: dict = field(default_factory=dict)
    missing_services: list = field(default_factory=list)
    severity: str = "ok"

"""

NEW_QUERY = """
_Q_SERVICE_CONNECTIONS = \"\"\"
SELECT
    datname,
    count(*) AS jdbc_connections
FROM pg_stat_activity
WHERE application_name = 'PostgreSQL JDBC Driver'
GROUP BY datname
ORDER BY jdbc_connections DESC;
\"\"\"

"""

NEW_METHOD = """
    def collect_service_connections(self):
        from dataclasses import field as _field
        result = ServiceConnectionSnapshot(
            environment=self.env_name,
            collected_at=__import__('datetime').datetime.now(
                __import__('datetime').timezone.utc
            ),
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
            for db in monitored:
                if result.connections_by_db.get(db, 0) == 0:
                    result.missing_services.append(db)
            if result.missing_services:
                result.severity = "critical"
        except Exception as exc:
            logger.error("[%s] service_connections failed: %s", self.env_name, exc)
        finally:
            if conn:
                conn.close()
        return result

"""

# ── Patch qmatic_postgres_checks.py ──────────────────────────────────────────

path = "integrations/qmatic/qmatic_postgres_checks.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add dataclass before QueueActivitySnapshot
if "ServiceConnectionSnapshot" not in content:
    content = content.replace(
        "@dataclass\nclass QueueActivitySnapshot:",
        NEW_DATACLASS + "@dataclass\nclass QueueActivitySnapshot:"
    )
    print("Added ServiceConnectionSnapshot dataclass")
else:
    print("ServiceConnectionSnapshot already exists — skipping")

# 2. Add query before _Q_QUEUE_ACTIVITY
if "_Q_SERVICE_CONNECTIONS" not in content:
    content = content.replace(
        "_Q_QUEUE_ACTIVITY",
        NEW_QUERY + "_Q_QUEUE_ACTIVITY"
    )
    print("Added _Q_SERVICE_CONNECTIONS query")
else:
    print("_Q_SERVICE_CONNECTIONS already exists — skipping")

# 3. Add method before collect_long_jobs
if "collect_service_connections" not in content:
    content = content.replace(
        "    def collect_long_jobs",
        NEW_METHOD + "    def collect_long_jobs"
    )
    print("Added collect_service_connections method")
else:
    print("collect_service_connections already exists — skipping")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done patching", path)

# ── Patch control_plane.py ────────────────────────────────────────────────────

path2 = "control_plane.py"
with open(path2, "r", encoding="utf-8") as f:
    content2 = f.read()

if "collect_service_connections" not in content2:
    old = "            queue_activity = qmatic_checks.collect_queue_activity()"
    new = """            svc_snap = qmatic_checks.collect_service_connections()
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
            queue_activity = qmatic_checks.collect_queue_activity()"""
    content2 = content2.replace(old, new)
    print("Added service collection to control_plane.py")
else:
    print("control_plane.py already patched — skipping")

with open(path2, "w", encoding="utf-8") as f:
    f.write(content2)

print("Done patching", path2)
print("\nAll done — run: python control_plane.py --once")
