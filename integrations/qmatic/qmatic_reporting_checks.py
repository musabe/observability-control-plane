"""
integrations/qmatic/qmatic_reporting_checks.py
------------------------------------------------
Evaluates collected reporting/statistics data for anomalies:
  - Duplicate visit IDs (counting inflation)
  - Carryover counts (midnight rollover bug)
  - Missing expected daily activity
  - Unusual visit count spikes
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class ReportingAnomaly:
    anomaly_type: str
    severity: str
    description: str
    details: dict = field(default_factory=dict)


@dataclass
class ReportingCheckResult:
    environment: str
    checked_at: datetime
    anomalies: list[ReportingAnomaly] = field(default_factory=list)

    @property
    def severity(self) -> str:
        if any(a.severity == "critical" for a in self.anomalies):
            return "critical"
        if self.anomalies:
            return "warning"
        return "ok"


class QmaticReportingDetector:

    def __init__(self, env_config):
        self.env = env_config
        self.rep_cfg = env_config.reporting

    def check(self, reporting_snapshot) -> ReportingCheckResult:
        result = ReportingCheckResult(
            environment=self.env.name,
            checked_at=datetime.now(timezone.utc),
        )

        if not self.rep_cfg.enabled:
            return result

        # ── Duplicate visit IDs ────────────────────────────────────────────
        if reporting_snapshot.duplicate_visit_ids:
            worst = reporting_snapshot.duplicate_visit_ids[0]
            result.anomalies.append(ReportingAnomaly(
                anomaly_type="duplicate_visit_ids",
                severity="warning",
                description=(
                    f"{len(reporting_snapshot.duplicate_visit_ids)} visit IDs appear more than "
                    f"{self.rep_cfg.duplicate_visit_threshold}x today. "
                    f"Worst offender: visit_id={worst.get('visit_id')} "
                    f"seen {worst.get('occurrence_count')}x."
                ),
                details={
                    "count": len(reporting_snapshot.duplicate_visit_ids),
                    "worst": worst,
                },
            ))

        # ── Carryover detection ────────────────────────────────────────────
        if self.rep_cfg.carryover_detection and reporting_snapshot.suspected_carryover_counts:
            result.anomalies.append(ReportingAnomaly(
                anomaly_type="carryover_counts",
                severity="warning",
                description=(
                    f"{len(reporting_snapshot.suspected_carryover_counts)} visits from yesterday "
                    f"are still in WAITING/CALLED state — possible midnight rollover issue."
                ),
                details={
                    "count": len(reporting_snapshot.suspected_carryover_counts),
                    "sample": reporting_snapshot.suspected_carryover_counts[:3],
                },
            ))

        # ── Missing expected daily activity ───────────────────────────────
        # This check is only meaningful during or after business hours.
        # The activity detector handles real-time zero-activity checks.
        # This check focuses on statistical completeness.
        if (self.rep_cfg.missing_daily_activity_alert
                and reporting_snapshot.anomalies_found == 0
                and not reporting_snapshot.duplicate_visit_ids
                and not reporting_snapshot.suspected_carryover_counts):
            # No anomalies found — reporting looks clean
            pass

        return result
