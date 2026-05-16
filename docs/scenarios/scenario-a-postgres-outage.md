# Scenario A — PostgreSQL Outage

**Platform:** Vorsa Observability Control Plane  
**Environment:** northvale-council  
**Scenario Type:** Infrastructure failure — database layer  
**Severity:** CRITICAL  
**Health Score:** 12 → 100 (recovery)  
**Duration:** ~18 minutes  

---

## Overview

The PostgreSQL database service stopped responding at 08:44 UTC, causing a cascading
failure across all Qmatic Orchestra services. The Vorsa correlation engine detected the
outage within one poll cycle (60 seconds), correlated three independent signal failures
into a single named incident, generated an RCA artifact, and provided actionable
remediation steps — before any customer-facing alert was raised.

---

## Timeline

| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| 08:44:48 | JDBC connections drop to 0 across all 5 databases | SERVICES | warning |
| 08:44:51 | HTTP endpoint unreachable — login.jsp timeout | HTTP | critical |
| 08:44:56 | Qmatic API Gateway stopped | WINDOWS | critical |
| 08:44:58 | Qmatic Web Booking stopped | WINDOWS | critical |
| 08:45:02 | PostgreSQL unreachable — connection refused | POSTGRES | critical |
| 08:45:04 | Correlation engine grouped 3 signal failures | CORRELATOR | — |
| 08:45:04 | **SEV-1 declared** — `db_unavailable` confidence=91% | INCIDENT | critical |
| 08:45:04 | RCA artifact generated | RCA | — |
| 08:51:15 | PostgreSQL service restarted | POSTGRES | — |
| 08:51:15 | Qmatic services restarting | WINDOWS | — |
| 08:51:30 | PostgreSQL accepting connections — pool at 3% | POSTGRES | ok |
| 08:51:44 | JDBC connections re-established across all databases | SERVICES | ok |
| 08:52:18 | All services healthy — health score 12 → 97 | HEALTH | ok |

---

## Signal Chain

```
PostgreSQL connection refused
        │
        ├── JDBC connections → 0 (all 5 databases)
        │         qp_central: 17 → 0
        │         statdb:     16 → 0
        │         qp_agent:    9 → 0
        │         qp_calendar: 2 → 0
        │         qp_app:      1 → 0
        │
        ├── HTTP endpoint → timeout
        │         login.jsp: 228ms → timeout (10s)
        │
        └── Windows services → stopped
                  Qmatic Web Booking:  Running → Stopped
                  Qmatic API Gateway:  Running → Stopped
                  Qmatic Platform:     Running (orphaned)
```

---

## Correlation Engine Output

**Rule fired:** `db_unavailable`  
**Confidence:** 91%  
**Severity:** CRITICAL  
**Suppressed:** No  

**Evidence collected:**

| Source | Signal | Value | Severity |
|---|---|---|---|
| POSTGRES | availability | UNREACHABLE | critical |
| POSTGRES | error | connection refused — timeout expired | critical |
| HTTP | app_reachable | false | critical |
| SERVICES | total_jdbc | 0 / 5 databases | critical |
| WINDOWS | stopped_services | Web Booking, API Gateway | critical |

**Confidence scoring breakdown:**

| Factor | Score |
|---|---|
| Signal severity (5× critical signals) | +30 |
| Evidence count (5 correlated signals) | +25 |
| Recency (all signals same poll cycle) | +20 |
| Recurrence (seen 3× in last 24h) | +14 |
| Business hours context | +2 |
| **Total** | **91%** |

---

## Topology Impact

```
Client Channels
        │  [timeout]
        ▼
  API Gateway ●  ← STOPPED
        │
        ▼
  Orchestra Core ●  ← OOM / cascade
  Appointment Eng ●
  Messaging Eng ●
        │
        ▼
  Operational DB ●  ← UNREACHABLE    Statistics DB ●
  qp_central: 0 JDBC                 statdb: 0 JDBC
  qp_agent:   0 JDBC
        │
  ┌─────┼─────┐
Kiosks● Ctr● Disp●                  BI / Reports ●
```
`●` = failed / unavailable


## Dashboard State

**Health score:** 12 (CRITICAL)  
**Incidents:** 2 active  
**PG pool:** 0% (unreachable)  
**HTTP latency:** — (timeout)  
**Server memory:** 62% (services freed heap on stop)  
**QMATIC:** 1/3 services running  

---

## RCA Summary

PostgreSQL service stopped responding at 08:44 UTC. The root cause was a connection
refusal at the database layer — all downstream Qmatic services lost their JDBC
connections simultaneously. The API Gateway and Web Booking services subsequently
crashed due to unhandled connection pool exhaustion. The Platform service continued
running but was unable to process requests.

**Likely cause:** PostgreSQL process terminated — either OOM kill, disk exhaustion,
or manual/unplanned service stop.

**Resolution:** PostgreSQL service restarted. JDBC connections recovered within 90
seconds. All Qmatic services resumed normal operation by 08:52 UTC.

---

## Runbook Reference

→ [`runbooks/postgres-outage.md`](../../runbooks/postgres-outage.md)

---

## Prevention Recommendations

1. Configure PostgreSQL `max_connections` alerting at 80% threshold
2. Enable OS-level memory alerting to detect pre-OOM conditions
3. Add disk space monitoring to the Vorsa Windows collector
4. Configure automatic PostgreSQL service restart on failure (Windows Service Recovery)
5. Add Vorsa Slack/PagerDuty alerting integration (Phase 3 roadmap)

---

## Files Generated

| File | Description |
|---|---|
| `incidents/INC-2026-0514-001-db-unavailable.md` | Full RCA incident artifact |
| `dashboard/scenarios/postgres-outage-state.json` | Dashboard snapshot |
| `runbooks/postgres-outage.md` | Operational runbook |
