# Scenario D — API Degradation

**Platform:** Vorsa Observability Control Plane  
**Environment:** northvale-council  
**Scenario Type:** Application layer degradation — HTTP / API tier  
**Severity:** WARNING  
**Health Score:** 97 → 75  
**Duration:** ~22 minutes  

---

## Overview

At 14:22 UTC, citizen-facing API response times climbed from a baseline of 228ms
to 2,847ms — just below the critical threshold of 3,000ms. Unlike Scenario A
(infrastructure crash) and Scenario B (database pressure), the underlying
infrastructure showed no anomalies: PostgreSQL connection pool at 3.1%, all
services running, server memory at 57%. The Vorsa correlation engine correctly
identified this as an isolated application-layer issue and fired the
`app_layer_issue` rule — "API latency elevated, infrastructure healthy."

This scenario demonstrates the platform's ability to distinguish between
infrastructure-driven degradation and application-tier degradation. A less
sophisticated monitoring system would generate no alert here (infrastructure
is fine), or generate the wrong alert (misattributing the cause to the database).

---

## Timeline

| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| 14:22:08 | HTTP latency climbs above warning threshold | HTTP | warning |
| 14:22:08 | qmatic-login response: 2847ms | HTTP | warning |
| 14:22:08 | PostgreSQL: OK — 3.1%, 0 long queries | POSTGRES | ok |
| 14:22:08 | All Qmatic services: running normally | WINDOWS | ok |
| 14:22:11 | Correlation engine evaluates all 8 rules | CORRELATOR | — |
| 14:22:11 | `app_layer_issue` pattern matched | CORRELATOR | — |
| 14:22:11 | **SEV-2 declared** — `app_layer_issue` confidence=75% | INCIDENT | warning |
| 14:22:11 | RCA artifact generated | RCA | — |
| 14:28:00 | Qmatic Platform service restarted by administrator | WINDOWS | — |
| 14:31:00 | HTTP latency recovering — 1,240ms | HTTP | warning |
| 14:39:00 | HTTP latency normalised — 231ms | HTTP | ok |
| 14:44:00 | Health score recovered: 75 → 97 | HEALTH | ok |

---

## Signal Chain

```
API latency spike — application layer only
        │
        ├── HTTP: 228ms → 2847ms
        │         threshold: 1500ms warning, 3000ms critical
        │         status: HTTP 200 (not erroring — just slow)
        │
        ├── PostgreSQL: healthy
        │         connection_pct:    3.1% (normal)
        │         long_running_queries: 0
        │         blocked_queries:   0
        │
        ├── Windows services: all running
        │         Web Booking:  Running 284MB heap=7%
        │         Platform:     Running 3268MB heap=80%
        │         API Gateway:  Running 338MB heap=8%
        │
        └── JDBC connections: normal
                  qp_central:  17
                  statdb:      16
                  qp_agent:     9
                  total:       45
```

**Key diagnostic insight:** Infrastructure signals are healthy.
The latency is originating in the application layer — either the
API Gateway, Orchestra Central, or the Web Booking front-end.

---

## Correlation Engine Output

**Rule fired:** `app_layer_issue`  
**Confidence:** 75%  
**Severity:** WARNING  
**Suppressed:** No  

**Evidence collected:**

| Source | Signal | Value | Severity |
|---|---|---|---|
| HTTP | api_latency_ms | 2847ms | warning |
| HTTP | latency_vs_threshold | 190% of warning threshold | warning |
| POSTGRES | availability | OK | ok |
| POSTGRES | connection_pct | 3.1% | ok |
| WINDOWS | services_running | 3/3 | ok |
| SERVICES | total_jdbc | 45 (normal) | ok |

**Confidence scoring breakdown:**

| Factor | Score |
|---|---|
| Signal severity (1× warning, 5× ok/healthy) | +10 |
| Evidence count (6 signals — infrastructure healthy) | +25 |
| Recency (signals same poll cycle) | +20 |
| Recurrence (seen 2× in last 24h) | +12 |
| Business hours context (afternoon peak) | +8 |
| **Total** | **75%** |

> The `app_layer_issue` rule is specifically designed to fire when HTTP is
> degraded but infrastructure is healthy. High infrastructure health evidence
> actually increases confidence in this rule — it eliminates other causes.

---

## Topology Impact

```
Internet / Mobile · HTTPS
        │  [latency: 2847ms ↑↑]
        ▼
  API Gateway ◑  ← Running but slow
        │  [request processing delay]
        ▼
Orchestra Central ◑  ← Running, application thread pressure
   ┌────┼────┐
   ▼    ▼    ▼
Web   Counter  Kiosk
Book◑  Apps○  Systems○
[slow]        [unaffected]
        │
        ▼
 PostgreSQL ✓  ← Healthy — 3.1% pool
   ┌────┼────┐
   ▼    ▼    ▼
qp_central✓ statdb✓ qp_agent✓
17 JDBC    16 JDBC  9 JDBC
        │
        ▼
Reporting / BI ✓  ← Unaffected
```

`◑` = degraded  `○` = healthy, minor impact  `✓` = fully healthy

**Key difference from Scenario A/B:** Only the top of the stack is affected.
Database and service layers are completely healthy. The issue is isolated to
the HTTP/application tier.

---

## Dashboard State

**Health score:** 75 (DEGRADED)  
**Incidents:** 1 active (WARNING)  
**PG pool:** 3.1% (normal)  
**HTTP latency:** 2847ms (warning — near critical)  
**Server memory:** 57.5% (normal)  
**QMATIC:** 3/3 services running  
**Long queries:** 0  
**Blocked queries:** 0  

---

## RCA Summary

The API latency spike originated in the application tier, not the infrastructure
layer. The most likely cause is thread pool exhaustion in the Qmatic API Gateway
or Orchestra Central — the Platform JVM was at 80% heap (3268MB/4096MB), which
can cause garbage collection pauses that manifest as latency spikes. A Platform
service restart resolved the issue within 17 minutes.

**Likely cause:** JVM garbage collection pause (GC pause storm) in the Qmatic
Platform service. Heap at 80% → GC running frequently → application threads
paused during GC → HTTP requests queuing → elevated latency.

**Resolution:** Qmatic Platform service restarted. Latency recovered within
11 minutes. No data loss.

---

## Runbook Reference

→ [`runbooks/api-latency.md`](../../runbooks/api-latency.md)

---

## Prevention Recommendations

1. **JVM heap tuning** — Platform heap consistently at 80% (3268MB/4096MB).
   Consider reducing `-Xmn1540m` (young gen) to give GC more headroom, or
   increase `-Xmx` if server RAM allows.

2. **GC logging** — Add JVM GC logging to detect pause storms before they
   cause latency spikes:
   ```
   -Xlog:gc*:file=C:/qmatic/logs/gc.log:time,uptime:filecount=5,filesize=10m
   ```

3. **API health endpoint** — Add the Qmatic API health endpoint to the Vorsa
   HTTP checks for deeper application-layer visibility.

4. **Connection pool monitoring** — Add thread pool utilisation metrics from
   the Qmatic API Gateway to differentiate GC pauses from thread exhaustion.

---

## Files Generated

| File | Description |
|---|---|
| `incidents/INC-2026-0516-004-api-degradation.md` | Full RCA incident artifact |
| `dashboard/scenarios/api-degradation-state.json` | Dashboard snapshot |
