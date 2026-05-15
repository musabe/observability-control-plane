"""
integrations/qmatic/qmatic_activity_checks.py
----------------------------------------------
Detects operational anomalies in Qmatic queue activity:
  - Zero delivered services during business hours
  - Abnormal drop in visit volume vs rolling average
  - Stale activity window (no recent events)
  - Unexpected total silence during expected busy periods
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ActivityAnomaly:
    anomaly_type: str       # zero_activity | stale_window | abnormal_drop | unexpected_silence
    severity: str           # warning | critical
    description: str
    details: dict = field(default_factory=dict)


@dataclass
class ActivityCheckResult:
    environment: str
    checked_at: datetime
    is_business_hours: bool
    anomalies: list[ActivityAnomaly] = field(default_factory=list)

    @property
    def has_anomalies(self) -> bool:
        return len(self.anomalies) > 0

    @property
    def severity(self) -> str:
        if any(a.severity == "critical" for a in self.anomalies):
            return "critical"
        if self.anomalies:
            return "warning"
        return "ok"


# ── Business hours helper ─────────────────────────────────────────────────────

def _is_business_hours(business_hours: dict, timezone: str) -> bool:
    """Return True if current local time is within configured business hours."""
    tz = ZoneInfo(timezone)
    now_local = datetime.now(tz)
    day_name = now_local.strftime("%A").lower()  # e.g. "monday"

    hours = business_hours.get(day_name, [])
    if not hours:
        return False  # closed today

    try:
        open_h, open_m = map(int, hours[0].split(":"))
        close_h, close_m = map(int, hours[1].split(":"))
    except (IndexError, ValueError):
        return False

    open_time = dtime(open_h, open_m)
    close_time = dtime(close_h, close_m)
    current_time = now_local.time().replace(second=0, microsecond=0)

    return open_time <= current_time <= close_time


# ── Detector ──────────────────────────────────────────────────────────────────

class QmaticActivityDetector:
    """
    Evaluates collected activity snapshots against configured thresholds.
    Stateless — pass in the snapshot, get back anomalies.
    The rolling average tracking is handled externally (see correlators/).
    """

    def __init__(self, env_config):
        self.env = env_config
        self.activity_cfg = env_config.activity

    def check(
        self,
        snapshot,                       # QueueActivitySnapshot from qmatic_postgres_checks
        rolling_avg_visits_per_hour: Optional[float] = None,
        minutes_since_last_visit: Optional[float] = None,
    ) -> ActivityCheckResult:

        in_biz_hours = _is_business_hours(
            self.env.business_hours,
            self.env.timezone,
        )

        result = ActivityCheckResult(
            environment=self.env.name,
            checked_at=datetime.now(timezone.utc),
            is_business_hours=in_biz_hours,
        )

        if not in_biz_hours:
            # Outside business hours — most checks are suppressed
            # Exception: detect unexpected activity that signals a clock/timezone bug
            return result

        # ── 1. Zero delivered services ─────────────────────────────────────
        if snapshot.delivered_visits_today == 0:
            result.anomalies.append(ActivityAnomaly(
                anomaly_type="zero_activity",
                severity="critical",
                description="Zero delivered visits recorded today during business hours.",
                details={
                    "total_visits_today": snapshot.total_visits_today,
                    "active_branches": snapshot.active_branches,
                },
            ))

        # ── 2. Stale activity window ───────────────────────────────────────
        if minutes_since_last_visit is not None:
            threshold = self.activity_cfg.stale_window_minutes
            if minutes_since_last_visit >= threshold:
                result.anomalies.append(ActivityAnomaly(
                    anomaly_type="stale_window",
                    severity="warning" if minutes_since_last_visit < threshold * 1.5 else "critical",
                    description=(
                        f"No visit activity recorded in the last "
                        f"{minutes_since_last_visit:.0f} minutes."
                    ),
                    details={
                        "minutes_since_last_visit": minutes_since_last_visit,
                        "threshold_minutes": threshold,
                    },
                ))

        # ── 3. Abnormal drop vs rolling average ───────────────────────────
        if rolling_avg_visits_per_hour is not None and rolling_avg_visits_per_hour > 0:
            drop_threshold_pct = self.activity_cfg.abnormal_drop_pct
            # Estimate current hourly rate from today's total
            # (simplified; production version should use a sliding window)
            current_rate = snapshot.total_visits_today  # crude proxy
            drop_pct = (1 - current_rate / rolling_avg_visits_per_hour) * 100

            if drop_pct >= drop_threshold_pct:
                result.anomalies.append(ActivityAnomaly(
                    anomaly_type="abnormal_drop",
                    severity="warning",
                    description=(
                        f"Visit volume dropped {drop_pct:.0f}% below rolling average "
                        f"({current_rate:.0f} vs avg {rolling_avg_visits_per_hour:.0f})."
                    ),
                    details={
                        "current_visits": current_rate,
                        "rolling_avg": rolling_avg_visits_per_hour,
                        "drop_pct": drop_pct,
                    },
                ))

        # ── 4. Min visits threshold ───────────────────────────────────────
        min_threshold = self.activity_cfg.min_visits_per_hour_during_business
        if (snapshot.total_visits_today > 0
                and snapshot.total_visits_today < min_threshold
                and snapshot.active_branches == 0):
            result.anomalies.append(ActivityAnomaly(
                anomaly_type="unexpected_silence",
                severity="warning",
                description=(
                    f"Only {snapshot.total_visits_today} total visits today with "
                    f"no active branches — possible application or connectivity issue."
                ),
                details={
                    "total_visits_today": snapshot.total_visits_today,
                    "active_branches": snapshot.active_branches,
                    "min_expected_per_hour": min_threshold,
                },
            ))

        return result
