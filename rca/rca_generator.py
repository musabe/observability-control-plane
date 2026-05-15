"""
rca/rca_generator.py
---------------------
Generates RCA-style incident summaries from correlated incidents.
Outputs:
  - Structured dict (for the dashboard)
  - Markdown file (saved to incidents/ directory)
  - JSONL log entry (for alert_log)

The summaries are engineering-readable, not customer-facing.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SEVERITY_ICONS = {
    "ok":       "✓",
    "warning":  "⚠",
    "critical": "✗",
}

SEVERITY_LABELS = {
    "ok":       "OK",
    "warning":  "WARNING",
    "critical": "CRITICAL",
}


# ── Output types ──────────────────────────────────────────────────────────────

@dataclass
class RCASummary:
    environment: str
    incident_type: str
    title: str
    severity: str
    generated_at: datetime
    evidence: list[dict] = field(default_factory=list)
    likely_cause: str = ""
    recommended_actions: list[str] = field(default_factory=list)
    postgres_snapshot: Optional[dict] = None
    markdown: str = ""

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "incident_type": self.incident_type,
            "title": self.title,
            "severity": self.severity,
            "generated_at": self.generated_at.isoformat(),
            "evidence": self.evidence,
            "likely_cause": self.likely_cause,
            "recommended_actions": self.recommended_actions,
        }


# ── Generator ─────────────────────────────────────────────────────────────────

class RCAGenerator:

    def __init__(self, output_dir: str = "incidents"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, incident, pg_snap=None) -> RCASummary:
        """
        Generate an RCA summary from a CorrelatedIncident.
        Optionally enriches with raw PostgreSQL snapshot data.
        """
        now = datetime.now(timezone.utc)

        # Build postgres context if available
        pg_context = None
        if pg_snap and pg_snap.available:
            pg_context = {
                "connection_pct": round(pg_snap.connection_pct, 1),
                "active_connections": pg_snap.active_connections,
                "max_connections": pg_snap.max_connections,
                "long_running_queries": len(pg_snap.long_running_queries),
                "blocked_queries": len(pg_snap.blocked_queries),
                "cache_hit_ratio": round(pg_snap.cache_hit_ratio * 100, 1),
                "db_size_mb": round(pg_snap.db_size_mb, 1),
            }

        summary = RCASummary(
            environment=incident.environment,
            incident_type=incident.incident_type,
            title=incident.title,
            severity=incident.severity,
            generated_at=now,
            evidence=[e if isinstance(e, dict) else {
                "source": e.source,
                "signal": e.signal,
                "value": e.value,
                "severity": e.severity,
            } for e in incident.evidence],
            likely_cause=incident.likely_cause,
            recommended_actions=incident.recommended_actions,
            postgres_snapshot=pg_context,
        )

        summary.markdown = self._render_markdown(summary, pg_snap)
        return summary

    def _render_markdown(self, summary: RCASummary, pg_snap=None) -> str:
        icon = SEVERITY_ICONS.get(summary.severity, "?")
        label = SEVERITY_LABELS.get(summary.severity, summary.severity.upper())
        ts = summary.generated_at.strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"# {icon} Incident: {summary.title}",
            "",
            f"**Severity:** {label}  ",
            f"**Environment:** {summary.environment}  ",
            f"**Generated:** {ts}  ",
            f"**Type:** `{summary.incident_type}`  ",
            "",
            "---",
            "",
            "## Evidence",
            "",
        ]

        for ev in summary.evidence:
            sev_icon = SEVERITY_ICONS.get(ev.get("severity", ""), "·")
            lines.append(
                f"- {sev_icon} **{ev['source'].upper()}** — "
                f"{ev['signal']}: `{ev['value']}`"
            )

        if summary.postgres_snapshot:
            pg = summary.postgres_snapshot
            lines += [
                "",
                "### PostgreSQL Detail",
                "",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| Connection pool | {pg['connection_pct']}% ({pg['active_connections']}/{pg['max_connections']}) |",
                f"| Long-running queries | {pg['long_running_queries']} |",
                f"| Blocked queries | {pg['blocked_queries']} |",
                f"| Cache hit ratio | {pg['cache_hit_ratio']}% |",
                f"| Database size | {pg['db_size_mb']} MB |",
            ]

            if pg_snap and pg_snap.long_running_queries:
                lines += ["", "**Longest queries:**", ""]
                for q in pg_snap.long_running_queries[:3]:
                    lines.append(
                        f"- PID {q.pid} — {q.duration_seconds:.0f}s — "
                        f"`{q.query_preview[:80]}...`"
                    )

        lines += [
            "",
            "---",
            "",
            "## Likely Cause",
            "",
            summary.likely_cause,
            "",
            "---",
            "",
            "## Recommended Actions",
            "",
        ]

        for i, action in enumerate(summary.recommended_actions, 1):
            lines.append(f"{i}. {action}")

        lines += [
            "",
            "---",
            "",
            f"*Generated by observability-control-plane / rca_generator.py*",
        ]

        return "\n".join(lines)

    def save_markdown(self, summary: RCASummary) -> str:
        """Save RCA markdown to incidents/ directory. Returns file path."""
        ts = summary.generated_at.strftime("%Y%m%d_%H%M%S")
        safe_env = summary.environment.replace("-", "_")
        filename = f"{ts}_{safe_env}_{summary.incident_type}.md"
        filepath = self.output_dir / filename
        filepath.write_text(summary.markdown, encoding="utf-8")
        logger.info("RCA saved: %s", filepath)
        return str(filepath)

    def log_alert(self, summary: RCASummary, alert_log: str = "logs/alerts.jsonl") -> None:
        """Append alert entry to JSONL log."""
        Path(alert_log).parent.mkdir(parents=True, exist_ok=True)
        with open(alert_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary.to_dict()) + "\n")
