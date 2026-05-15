"""
collectors/http_collector.py
-----------------------------
HTTP health collector for Qmatic application endpoints.
Measures: reachability, latency, HTTP status validation.
All checks are read-only GET requests with configurable timeouts.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class HttpCheckResult:
    name: str
    url: str
    checked_at: datetime
    reachable: bool
    status_code: Optional[int]
    latency_ms: float
    expected_status: int
    severity: str           # ok | warning | critical | unreachable
    error: Optional[str]

    @property
    def status_ok(self) -> bool:
        return self.status_code == self.expected_status

    @property
    def summary(self) -> str:
        if not self.reachable:
            return f"UNREACHABLE  {self.name}  ({self.error})"
        icon = {"ok": "✓", "warning": "⚠", "critical": "✗"}.get(self.severity, "?")
        return f"{icon}  {self.name}  HTTP {self.status_code}  {self.latency_ms:.0f}ms"


@dataclass
class HttpCollectionResult:
    environment: str
    collected_at: datetime
    checks: list[HttpCheckResult]

    @property
    def overall_severity(self) -> str:
        severities = [c.severity for c in self.checks]
        if "critical" in severities or "unreachable" in severities:
            return "critical"
        if "warning" in severities:
            return "warning"
        return "ok"

    @property
    def all_reachable(self) -> bool:
        return all(c.reachable for c in self.checks)


# ── Collector ─────────────────────────────────────────────────────────────────

class HttpCollector:
    def __init__(self, env_name: str, http_checks: list):
        self.env_name = env_name
        self.checks = http_checks

    def _check_one(self, check) -> HttpCheckResult:
        start = time.monotonic()
        result = HttpCheckResult(
            name=check.name,
            url=check.url,
            checked_at=datetime.now(timezone.utc),
            reachable=False,
            status_code=None,
            latency_ms=0.0,
            expected_status=check.expected_status,
            severity="critical",
            error=None,
        )

        try:
            with httpx.Client(timeout=check.timeout_seconds, follow_redirects=True) as client:
                response = client.get(check.url)
            elapsed_ms = (time.monotonic() - start) * 1000

            result.reachable = True
            result.status_code = response.status_code
            result.latency_ms = elapsed_ms

            # Determine severity
            status_ok = response.status_code == check.expected_status
            if not status_ok or elapsed_ms >= check.critical_latency_ms:
                result.severity = "critical"
            elif elapsed_ms >= check.warning_latency_ms:
                result.severity = "warning"
            else:
                result.severity = "ok"

        except httpx.TimeoutException:
            result.error = f"Timeout after {check.timeout_seconds}s"
            result.severity = "critical"
            logger.warning("[%s] %s timed out", self.env_name, check.name)

        except Exception as exc:
            result.error = str(exc)
            result.severity = "critical"
            logger.warning("[%s] %s failed: %s", self.env_name, check.name, exc)

        return result

    def collect(self) -> HttpCollectionResult:
        results = [self._check_one(chk) for chk in self.checks]
        return HttpCollectionResult(
            environment=self.env_name,
            collected_at=datetime.now(timezone.utc),
            checks=results,
        )
