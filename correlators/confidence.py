"""
correlators/confidence.py
--------------------------
Confidence scoring engine for Vorsa correlation rules.

Each correlated incident receives a confidence score 0-100 based on:
  - Signal severity strength         (0-30)
  - Number of correlated signals     (0-25)
  - Signal recency                   (0-20)
  - Historical recurrence            (0-15)
  - Business hours context           (0-10)

Confidence drives:
  - Severity downgrade (critical → warning if < 80%)
  - Suppression (< 50% → timeline warning only, no incident/RCA)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("dashboard/incident_history.jsonl")
HISTORY_LOOKBACK_HOURS = 24


# ── History management ────────────────────────────────────────────────────────

def load_recent_history(env_name: str, incident_type: str) -> list[dict]:
    """Return incidents of this type for this env in the last 24 hours."""
    if not HISTORY_FILE.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HISTORY_LOOKBACK_HOURS)
    matches = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if (entry.get("environment") == env_name
                            and entry.get("incident_type") == incident_type):
                        ts_str = entry.get("correlated_at", "")
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts >= cutoff:
                            matches.append(entry)
                except Exception:
                    continue
    except Exception as exc:
        logger.warning("Could not load incident history: %s", exc)
    return matches


def append_history(incident_dict: dict) -> None:
    """Append a correlated incident to the history log."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(incident_dict, default=str) + "\n")
    except Exception as exc:
        logger.warning("Could not append incident history: %s", exc)


# ── Scoring components ────────────────────────────────────────────────────────

def _signal_severity_score(evidence: list) -> int:
    """
    Score based on the worst signal severity in the evidence list.
    critical = 30, warning = 15, ok = 0
    """
    severities = [e.severity if hasattr(e, "severity") else e.get("severity", "ok")
                  for e in evidence]
    if "critical" in severities:
        return 30
    if "warning" in severities:
        return 15
    return 0


def _evidence_count_score(evidence: list) -> int:
    """
    Score based on number of correlated signals.
    1 signal = 8, 2 = 16, 3+ = 25
    """
    n = len(evidence)
    if n >= 3:
        return 25
    if n == 2:
        return 16
    if n == 1:
        return 8
    return 0


def _recency_score(pg_snap=None, http_snap=None) -> int:
    """
    Score based on how recent the signals are.
    All from current poll = 20, partial = 10, stale = 0
    """
    now = datetime.now(timezone.utc)
    ages = []
    if pg_snap and hasattr(pg_snap, "collected_at") and pg_snap.collected_at:
        ct = pg_snap.collected_at
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        ages.append((now - ct).total_seconds())
    if http_snap and hasattr(http_snap, "collected_at") and http_snap.collected_at:
        ct = http_snap.collected_at
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        ages.append((now - ct).total_seconds())

    if not ages:
        return 10  # no timestamps to compare — assume recent
    max_age = max(ages)
    if max_age <= 120:   # within 2 minutes
        return 20
    if max_age <= 300:   # within 5 minutes
        return 10
    return 0


def _recurrence_score(env_name: str, incident_type: str) -> int:
    """
    Score based on whether this pattern has been seen before in last 24h.
    Seen before = 15 (pattern is confirmed), first time = 0
    """
    history = load_recent_history(env_name, incident_type)
    return 15 if history else 0


def _business_hours_score(is_business_hours: bool) -> int:
    """
    Anomalies during business hours are more significant.
    During hours = 10, outside = 0
    """
    return 10 if is_business_hours else 0


# ── Main confidence calculator ────────────────────────────────────────────────

def calculate_confidence(
    incident_type: str,
    evidence: list,
    env_name: str,
    pg_snap=None,
    http_snap=None,
    is_business_hours: bool = True,
) -> int:
    """
    Calculate confidence score 0-100 for a correlated incident.
    """
    score = 0
    score += _signal_severity_score(evidence)
    score += _evidence_count_score(evidence)
    score += _recency_score(pg_snap, http_snap)
    score += _recurrence_score(env_name, incident_type)
    score += _business_hours_score(is_business_hours)

    final = min(score, 100)

    logger.debug(
        "[%s] Confidence for %s: %d "
        "(severity=%d evidence=%d recency=%d recurrence=%d biz_hours=%d)",
        env_name, incident_type, final,
        _signal_severity_score(evidence),
        _evidence_count_score(evidence),
        _recency_score(pg_snap, http_snap),
        _recurrence_score(env_name, incident_type),
        _business_hours_score(is_business_hours),
    )

    return final


# ── Severity adjuster ─────────────────────────────────────────────────────────

def adjust_severity(raw_severity: str, confidence: int) -> str:
    """
    Downgrade severity based on confidence:
    - critical + confidence < 80% → warning
    - warning + confidence < 50% → suppress (caller handles)
    """
    if raw_severity == "critical" and confidence < 80:
        return "warning"
    return raw_severity


def should_suppress(confidence: int) -> bool:
    """
    Suppress incident (timeline only) if confidence < 50%.
    """
    return confidence < 50
