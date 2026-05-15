"""
config/loader.py
----------------
Loads and validates environment configurations from environments.yaml.
Secrets (DB passwords) are injected from environment variables — never
stored in YAML.

Secret naming convention:
  OBS_DB_PASSWORD_{ENV_NAME_UPPER_SNAKE}
  e.g. cxm-client-alpha  →  OBS_DB_PASSWORD_CXM_CLIENT_ALPHA
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PostgresConfig:
    host: str
    port: int
    database: str
    username: str
    password: str
    connect_timeout_seconds: int = 5
    thresholds: dict = field(default_factory=dict)


@dataclass
class HttpCheck:
    name: str
    url: str
    expected_status: int = 200
    warning_latency_ms: int = 1500
    critical_latency_ms: int = 3000
    timeout_seconds: int = 10


@dataclass
class ActivityConfig:
    min_visits_per_hour_during_business: int = 5
    stale_window_minutes: int = 45
    abnormal_drop_pct: int = 60


@dataclass
class ReportingConfig:
    enabled: bool = True
    duplicate_visit_threshold: int = 3
    carryover_detection: bool = True
    missing_daily_activity_alert: bool = True


@dataclass
class EnvironmentConfig:
    name: str
    env_type: str
    enabled: bool
    timezone: str
    description: str
    business_hours: dict
    windows_host: Optional[str]
    windows_user: str
    windows_config: Optional[dict]
    postgres: Optional[PostgresConfig]
    http_checks: list[HttpCheck]
    activity: ActivityConfig
    reporting: ReportingConfig


# ── Loader ────────────────────────────────────────────────────────────────────

def _env_key(env_name: str) -> str:
    """Convert env name to secret env var key."""
    safe = re.sub(r"[^a-zA-Z0-9]", "_", env_name).upper()
    return f"OBS_DB_PASSWORD_{safe}"


def load_environments(config_path: str = "config/environments.yaml") -> list[EnvironmentConfig]:
    raw = yaml.safe_load(Path(config_path).read_text())
    environments = []

    for entry in raw.get("environments", []):
        if not entry.get("enabled", True):
            continue

        # Postgres
        pg_cfg = None
        if "postgres" in entry:
            pg = entry["postgres"]
            secret_key = _env_key(entry["name"])
            password = os.environ.get(secret_key, "")
            if not password:
                print(f"[WARN] No password found for {entry['name']} — set {secret_key}")
            pg_cfg = PostgresConfig(
                host=pg["host"],
                port=pg.get("port", 5432),
                database=pg["database"],
                username=pg["username"],
                password=password,
                connect_timeout_seconds=pg.get("connect_timeout_seconds", 5),
                thresholds=pg.get("thresholds", {}),
            )

        # HTTP checks
        http_checks = [
            HttpCheck(**{k: v for k, v in chk.items()})
            for chk in entry.get("http_checks", [])
        ]

        # Activity
        act_raw = entry.get("activity_checks", {})
        activity = ActivityConfig(
            min_visits_per_hour_during_business=act_raw.get("min_visits_per_hour_during_business", 5),
            stale_window_minutes=act_raw.get("stale_window_minutes", 45),
            abnormal_drop_pct=act_raw.get("abnormal_drop_pct", 60),
        )

        # Reporting
        rep_raw = entry.get("reporting_checks", {})
        reporting = ReportingConfig(
            enabled=rep_raw.get("enabled", True),
            duplicate_visit_threshold=rep_raw.get("duplicate_visit_threshold", 3),
            carryover_detection=rep_raw.get("carryover_detection", True),
            missing_daily_activity_alert=rep_raw.get("missing_daily_activity_alert", True),
        )

        windows_host = entry.get('windows', {}).get('host', None)
        windows_user = entry.get('windows', {}).get('username', 'Administrator')
        windows_config = entry.get('windows', None)

        environments.append(EnvironmentConfig(
            name=entry["name"],
            env_type=entry.get("type", "qmatic"),
            enabled=entry.get("enabled", True),
            timezone=entry.get("timezone", "UTC"),
            description=entry.get("description", ""),
            business_hours=entry.get("business_hours", {}),
            windows_host=windows_host,
            windows_user=windows_user,
            windows_config=windows_config,
            postgres=pg_cfg,
            http_checks=http_checks,
            activity=activity,
            reporting=reporting,
        ))

    return environments
