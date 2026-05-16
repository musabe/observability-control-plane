# Scenario B — JDBC Pool Exhaustion

**Platform:** Vorsa Observability Control Plane  
**Environment:** northvale-council  
**Scenario Type:** Resource exhaustion — database connection layer  
**Severity:** WARNING → DEGRADED  
**Health Score:** 97 → 58 (degrading)  
**Duration:** ~45 minutes (gradual onset)  

---

## Overview

During the morning citizen services peak (09:15–10:00 UTC), the PostgreSQL connection
pool on the Qmatic Orchestra platform climbed steadily from 3% to 82% utilisation.
Eleven long-running queries — primarily from the statistics pipeline writing to statdb —
held connections open far beyond normal duration. This created a blocking chain that
slowed API response times from 228ms to 1847ms, triggering the `db_saturation_api_cascade`
correlation rule.

Unlike Scenario A (hard crash), this is a slow degradation scenario — the kind that
goes unnoticed until customers start reporting slow booking experiences. The Vorsa
correlation engine caught it at 82% pool utilisation, before saturation would have
caused complete service failure.

---

## Timeline

| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| 09:15:00 | Morning citizen services peak begins | ACTIVITY | info |
| 09:22:00 | PG connection pool reaches 40% | POSTGRES | ok |
| 09:31:00 | PG connection pool reaches 60% | POSTGRES | ok |
| 09:38:13 | HTTP latency spike detected — 1847ms | HTTP | warning |
| 09:38:16 | JDBC saturation threshold exceeded — 82% | POSTGRES | warning |
| 09:38:19 | statdb query latency > 18s — 11 long-running queries | POSTGRES | warning |
| 09:38:19 | 17 blocked queries detected | POSTGRES | warning |
| 09:38:21 | Correlation engine grouped related anomalies | CORRELATOR | — |
| 09:38:22 | **SEV-2 declared** — `db_saturation_api_cascade` confidence=73% | INCIDENT | warning |
| 09:38:22 | RCA artifact generated | RCA | — |
| 09:41:10 | Long-running statdb queries terminated by DBA | POSTGRES | — |
| 09:42:30 | Connection pool recovering — 54% | POSTGRES | warning |
| 09:44:00 | API latency recovering — 680ms | HTTP | warning |
| 09:47:15 | Connection pool normalised — 8% | POSTGRES | ok |
| 09:47:15 | API latency normalised — 231ms | HTTP | ok |
| 09:48:00 | Health score recovered: 58 → 94 | HEALTH | ok |

---

## Signal Chain

```
statdb statistics pipeline — long-running queries (18s+)
        │
        ├── Blocked queries accumulating (17 blocked)
        │         qp_central connections held
        │         statdb write locks contending
        │
        ├── Connection pool climbing
        │         03:00 UTC:  2.8%  (baseline)
        │         09:22 UTC: 40.0%  (peak onset)
        │         09:31 UTC: 60.0%  (warning territory)
        │         09:38 UTC: 82.0%  (threshold exceeded)
        │
        └── API latency escalating
                  baseline:    228ms
                  09:38 UTC: 1847ms  (warning threshold: 1500ms)
```

---

## Correlation Engine Output

**Rule fired:** `db_saturation_api_cascade`  
**Confidence:** 73%  
**Severity:** WARNING (downgraded from CRITICAL — confidence < 80%)  
**Suppressed:** No  

**Evidence collected:**

| Source | Signal | Value | Severity |
|---|---|---|---|
| POSTGRES | connection_pool_pct | 82.0% | warning |
| POSTGRES | long_running_queries | 11 queries (worst: 142s) | warning |
| POSTGRES | blocked_queries | 17 | warning |
| HTTP | api_latency_ms | 1847ms | warning |
| SERVICES | qp_central_jdbc | 42 connections | warning |
| SERVICES | statdb_jdbc | 38 connections | warning |

**Confidence scoring breakdown:**

| Factor | Score |
|---|---|
| Signal severity (6× warning signals) | +18 |
| Evidence count (6 correlated signals) | +25 |
| Recency (all signals same poll cycle) | +20 |
| Recurrence (seen 7× in last 24h) | +8 |
| Business hours context (peak hours) | +2 |
| **Total** | **73%** |

> Note: Confidence < 80% → severity downgraded from CRITICAL to WARNING.
> This is correct behaviour — the system is degraded but not failed.
> A hard crash would score 91%+.

---

## Topology Impact

```
Client Channels
        │  [latency elevated]
        ▼
  API Gateway ◑  ← Running but slow
        │
        ▼
  Orchestra Core ◑    ← DB pressure
  Appointment Eng ◑
  Messaging Eng ○
        │
        ▼
  Operational DB ◑    Statistics DB ◑
  qp_central: 42      statdb: 38
  (2.5× baseline)     (2.4× baseline)
        │
  Kiosks ○  Counter ○  Displays ○    BI / Reports ◑
```
`◑` = degraded  `○` = running, impacted


## Dashboard State

**Health score:** 58 (DEGRADED)  
**Incidents:** 1 active (WARNING)  
**PG pool:** 82% (1361/1660)  
**HTTP latency:** 1847ms  
**Long queries:** 11  
**Blocked queries:** 17  
**Server memory:** 78.2%  
**QMATIC:** 3/3 services running  

---

## RCA Summary

The Qmatic statistics pipeline generates batch write operations to `statdb` during
peak hours. On this morning, a combination of high citizen footfall and an
unoptimised reporting query caused 11 queries to exceed 30s execution time.
These held locks on `statdb` tables, creating a blocking chain that consumed
connections across `qp_central` as well. The connection pool climbed to 82%,
and the resulting lock contention introduced significant API latency (1847ms)
as Qmatic services waited for database responses.

**Likely cause:** Unoptimised statistics pipeline query during peak hours, combined
with above-average citizen footfall creating higher-than-normal concurrent load.

**Resolution:** DBA terminated the long-running statdb queries using
`SELECT pg_terminate_backend(pid)`. Connection pool recovered within 90 seconds.

---

## Runbook Reference

→ [`runbooks/db-connection-exhaustion.md`](../../runbooks/db-connection-exhaustion.md)

---

## Prevention Recommendations

1. **Query timeout** — Set `statement_timeout = 60s` in PostgreSQL for the
   reporting/statistics role to auto-terminate runaway queries.

2. **Connection pool limit per role** — Use `pg_hba.conf` or PgBouncer to
   limit statdb write connections to a maximum of 10 concurrent.

3. **Peak hours alerting** — Consider raising the warning threshold during
   09:00–12:00 to 90% (reducing noise) and lowering to 65% outside business hours.

4. **Separate reporting connection pool** — The statistics pipeline should use
   a dedicated connection pool isolated from the operational qp_central pool.

5. **Read replica** — Long-running reporting reads should be directed to a
   PostgreSQL read replica to avoid impacting operational traffic.

---

## Files Generated

| File | Description |
|---|---|
| `incidents/INC-2026-0515-002-jdbc-saturation.md` | Full RCA incident artifact |
| `dashboard/scenarios/jdbc-saturation-state.json` | Dashboard snapshot |
| `runbooks/db-connection-exhaustion.md` | Updated operational runbook |
