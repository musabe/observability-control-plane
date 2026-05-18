---
title: Service Level Objectives — northvale-council
category: slo
status: stable
owner: vorsa
last_updated: 2026-05-17
---

# Service Level Objectives
## northvale-council — Northvale Council Citizen Services

> Operational reliability targets for the Qmatic Orchestra platform.
> Measured and tracked automatically by the Vorsa control plane.

---

## SLO Summary

| SLO | Target | Measurement | Window |
|---|---|---|---|
| Platform Availability | 99.5% | Time outside CRITICAL health state | 30 days |
| API Latency | p95 < 500ms | HTTP collector — qmatic-login | 24 hours |
| PostgreSQL Saturation | < 75% pool | PG connection_pct | per poll |
| Incident Detection | < 60 seconds | Poll cycle interval | per incident |
| SEV-1 MTTR | < 15 minutes | Incident open → health recovered | per incident |
| SEV-2 MTTR | < 30 minutes | Incident open → health recovered | per incident |
| Poll Reliability | > 99% | Successful polls / total polls | 24 hours |

---

## SLO Definitions

### 1. Platform Availability

**Target:** 99.5% per 30-day window
**Error budget:** 3 hours 36 minutes per month

Availability is measured as the percentage of poll cycles where
`health_label` is not `CRITICAL`. A CRITICAL state lasting one poll
cycle (60 seconds) consumes 60 seconds of error budget.

```
availability_pct = (total_polls - critical_polls) / total_polls * 100
error_budget_remaining = (allowed_critical_seconds - actual_critical_seconds)
                         / allowed_critical_seconds * 100
```

**Allowed critical time per month:** 3h 36m (99.5% of 30 days)

| Label | Counts against SLO |
|---|---|
| HEALTHY | No |
| DEGRADED | No |
| CRITICAL | Yes |

---

### 2. API Latency

**Target:** p95 < 500ms over 24 hours
**Warning threshold:** > 1500ms (configured in environments.yaml)
**Critical threshold:** > 3000ms

Measured from `http.checks[0].latency_ms` each poll cycle.
Latency budget is the gap between current p95 and the 500ms target.

```
latency_budget_used_pct = current_latency / 500 * 100
```

---

### 3. PostgreSQL Pool Saturation

**Target:** < 75% connection pool utilisation
**Threshold:** 75% warning, 90% critical (configurable per environment)

Measured from `postgres.connection_pct` each poll cycle.
Saturation above 75% triggers the `db_saturation_api_cascade` rule.

```
saturation_headroom_pct = 75 - current_connection_pct
```

---

### 4. Incident Detection Latency (MTTD)

**Target:** < 60 seconds
**Actual:** Always ≤ 60 seconds (one poll cycle)

Vorsa detects incidents within one poll cycle of the failure occurring.
The poll interval is configurable (default 60 seconds).
This SLO is structural — detection latency cannot exceed the poll interval.

---

### 5. Mean Time to Resolve (MTTR)

**SEV-1 target:** < 15 minutes
**SEV-2 target:** < 30 minutes

Measured from incident `generated_at` to the poll cycle where
`health_label` returns to `HEALTHY` or `DEGRADED`.

Historical MTTR from incident registry:

| Incident | Severity | MTTR |
|---|---|---|
| INC-2026-0514-001 db_unavailable | SEV-1 | 7m 14s ✓ |
| INC-2026-0515-002 jdbc_saturation | SEV-2 | 9m 38s ✓ |
| INC-2026-0516-003 reporting_anomaly | SEV-2 | 1h 44m ✗ |
| INC-2026-0516-004 api_degradation | SEV-2 | 21m 49s ✗ |
| INC-2026-0516-005 jvm_memory_pressure | SEV-1 | 33m 57s ✗ |

> Note: INC-003 and INC-004 exceeded SEV-2 MTTR target.
> INC-005 exceeded SEV-1 target — an 8-minute warning was available
> but not acted upon, resulting in avoidable cascade.

---

### 6. Poll Reliability

**Target:** > 99% successful polls per 24 hours
**Measurement:** Polls where all collectors return `available: true`

A failed poll (collector timeout or auth failure) does not consume
availability error budget but is tracked separately.

---

## Error Budget Policy

| Budget Remaining | Action |
|---|---|
| > 50% | Normal operations |
| 25–50% | Review open prevention actions |
| 10–25% | Freeze non-critical changes |
| < 10% | Incident review required before any changes |
| 0% | Full incident review + remediation plan required |

---

## SLO Review Cadence

| Review | Frequency | Owner |
|---|---|---|
| SLO dashboard check | Every poll (automated) | Vorsa |
| Weekly SLO review | Monday morning | Platform team |
| Monthly SLO report | 1st of month | Platform team |
| SLO target review | Quarterly | Platform + customer |

---

## Related

- [`incidents/INCIDENT-REGISTRY.md`](../../incidents/INCIDENT-REGISTRY.md)
- [`docs/architecture/overview.md`](../architecture/overview.md)
- [`config/environments.yaml`](../../config/environments.yaml)

---

| Field | Value |
|---|---|
| **Environment** | northvale-council |
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Status** | stable |
| **Last updated** | 2026-05-17 |
