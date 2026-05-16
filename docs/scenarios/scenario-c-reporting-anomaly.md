# Scenario C — Reporting Anomaly

**Platform:** Vorsa Observability Control Plane  
**Environment:** northvale-council  
**Scenario Type:** Business data anomaly — application logic layer  
**Severity:** WARNING  
**Health Score:** 97 → 72  
**Duration:** ~2 hours (data quality issue, not infrastructure failure)  

---

## Overview

At 08:05 UTC, the Vorsa reporting checks detected duplicate visit IDs in `statdb`
and carryover visit totals from the previous business day that had not been cleared
during the nightly reset. Infrastructure remained fully healthy — all services
running, PostgreSQL at 2.8%, HTTP responding at 228ms. This is a pure data quality
incident at the Qmatic application layer.

This scenario demonstrates the depth of Qmatic-specific operational intelligence
in Vorsa — detecting business-level anomalies that no generic infrastructure
monitoring tool would surface. The incident had no visible infrastructure signature:
no alarms, no latency, no service stops. Only a platform that understands Qmatic
data semantics could have caught it.

---

## Timeline

| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| 07:00:00 | Nightly statistics reset expected | ACTIVITY | info |
| 07:00:00 | Reset did not complete — carryover persists | REPORTING | — |
| 08:00:00 | Business hours begin | SCHEDULE | info |
| 08:05:11 | Vorsa reporting check detects duplicate visit IDs | REPORTING | warning |
| 08:05:11 | Carryover visit count detected: 847 visits from previous day | REPORTING | warning |
| 08:05:11 | Duplicate visit ID count: 23 | REPORTING | warning |
| 08:05:14 | Correlation engine evaluates reporting_anomaly pattern | CORRELATOR | — |
| 08:05:14 | **SEV-2 declared** — `reporting_anomaly_with_db_pressure` conf=68% | INCIDENT | warning |
| 08:05:14 | RCA artifact generated | RCA | — |
| 08:15:00 | Qmatic support notified — statdb nightly reset reviewed | OPERATIONS | — |
| 09:45:00 | Manual statdb reset executed by Qmatic administrator | OPERATIONS | — |
| 09:47:00 | Duplicate visit count: 23 → 0 | REPORTING | ok |
| 09:47:00 | Carryover count: 847 → 0 | REPORTING | ok |
| 09:50:00 | Health score recovered: 72 → 95 | HEALTH | ok |

---

## Signal Chain

```
Nightly statdb reset did not complete (07:00 UTC)
        │
        ├── Carryover visits persisting into new business day
        │         expected:  0 carryover visits at 08:00
        │         actual:    847 visits from 2026-05-14
        │
        ├── Duplicate visit IDs in statdb
        │         23 visit records with duplicate primary keys
        │         visit_id collision between day boundaries
        │
        └── Reporting totals inflated
                  today's delivered count:  includes yesterday's 847
                  KPI dashboards:           overstated by ~40%
                  Power BI / Tableau:       incorrect data ingested
```

---

## Correlation Engine Output

**Rule fired:** `reporting_anomaly_with_db_pressure`  
**Confidence:** 68%  
**Severity:** WARNING  
**Suppressed:** No  

**Evidence collected:**

| Source | Signal | Value | Severity |
|---|---|---|---|
| REPORTING | duplicate_visit_ids | 23 duplicates detected | warning |
| REPORTING | carryover_visits | 847 visits from previous day | warning |
| REPORTING | statdb_reset_status | reset not confirmed | warning |
| POSTGRES | statdb_jdbc | 16 connections (normal) | ok |
| ACTIVITY | business_hours | active | info |

**Confidence scoring breakdown:**

| Factor | Score |
|---|---|
| Signal severity (3× warning signals) | +15 |
| Evidence count (5 correlated signals) | +25 |
| Recency (all signals same poll cycle) | +20 |
| Recurrence (first occurrence today) | +0 |
| Business hours context (anomaly during business hours) | +8 |
| **Total** | **68%** |

> Note: This is a data quality incident. Infrastructure signals are healthy.
> The confidence reflects anomaly strength, not infrastructure degradation.

---

## Topology Impact

```
Client Channels
        │  [normal]
        ▼
  API Gateway ✓
        │
        ▼
  Orchestra Core ✓
  Appointment Eng ✓
  Messaging Eng ✓
        │
        ▼
  Operational DB ✓    Statistics DB ⚠  ← data quality issue
  qp_central: 17      statdb: 16
  qp_agent: 9         847 carryover visits
                      23 duplicate IDs
        │                   │ ETL
  Kiosks ✓  Counter ✓       ▼
  Displays ✓           BI / Reports ⚠  ← receiving bad data
```
`⚠` = data quality issue  `✓` = healthy


## Dashboard State

**Health score:** 72 (DEGRADED)  
**Incidents:** 1 active (WARNING)  
**PG pool:** 2.8% (normal)  
**HTTP latency:** 228ms (normal)  
**Server memory:** 57.5% (normal)  
**QMATIC:** 3/3 services running  
**Anomaly:** Reporting data quality issue — duplicate visits, carryover totals  

---

## Why This Matters

This scenario is operationally significant for several reasons:

1. **Invisible to infrastructure monitoring** — No generic monitoring tool (Datadog,
   Prometheus, Grafana) would detect this. Connection pools are normal, services
   are running, HTTP is fast. Only a platform that understands Qmatic data semantics
   can surface this.

2. **Real business impact** — KPI dashboards are overstating delivered visits by ~40%.
   Management reports for the day will be incorrect. Power BI / Tableau will ingest
   bad data into historical trend analysis.

3. **Compliance implications** — Northvale Council may have SLA or reporting
   obligations based on citizen service metrics. Incorrect data could affect
   contract compliance reporting.

4. **Silent corruption** — Without Vorsa, this would go undetected until someone
   noticed the inflated KPI numbers — potentially hours or days later.

---

## RCA Summary

The Qmatic nightly statistics reset job failed to complete at 07:00 UTC. The most
likely cause is a scheduling conflict or a long-running query that held a lock on
`statdb` during the reset window, preventing the cleanup procedure from completing.
As a result, 847 visit records from the previous business day persisted into the
new day's statistics, and 23 visit IDs were duplicated at the day boundary.

**Resolution:** Manual statdb reset executed by the Qmatic administrator at 09:45 UTC.
All duplicate records cleared and carryover counts reset to 0.

---

## Runbook Reference

→ Qmatic statdb reset procedure (contact Qmatic support for documentation)  
→ [`runbooks/zero-activity-business-hours.md`](../../runbooks/zero-activity-business-hours.md)

---

## Prevention Recommendations

1. **Monitor nightly reset completion** — Add a Vorsa check that verifies the
   statdb reset job completed by 07:30 UTC each morning.

2. **Alert on carryover detection** — The current Vorsa check fires during the
   first poll after business hours begin. Earlier detection (07:00–07:30) would
   allow correction before the business day starts.

3. **Duplicate visit ID alerting** — Set threshold at 0 (any duplicate is an
   anomaly). Current threshold is 3 — the 23 detected today could have been
   caught earlier.

4. **statdb schema mapping** — Complete the statdb schema mapping in Vorsa
   (`reporting_checks.enabled: true`) to enable full reporting anomaly detection.

---

## Files Generated

| File | Description |
|---|---|
| `incidents/INC-2026-0516-003-reporting-anomaly.md` | Full RCA incident artifact |
| `dashboard/scenarios/reporting-anomaly-state.json` | Dashboard snapshot |
