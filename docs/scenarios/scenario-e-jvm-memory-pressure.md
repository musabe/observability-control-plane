# Scenario E — JVM Memory Pressure

**Platform:** Vorsa Observability Control Plane  
**Environment:** northvale-council  
**Scenario Type:** JVM memory exhaustion — gradual onset to service crash  
**Severity:** WARNING → CRITICAL  
**Health Score:** 97 → 82 → 61 → 18  
**Duration:** ~35 minutes (gradual degradation to OOM crash)  

---

## Overview

The Qmatic Platform JVM heap climbed steadily during a high-volume afternoon
appointment processing window, from its baseline of 80% to 97% over 35 minutes.
Vorsa detected the `memory_pressure_api_cascade` pattern at the 89% threshold,
generating a WARNING incident with 8 minutes of lead time before the eventual
OOM crash. The Platform service terminated at 15:47 UTC with an OutOfMemoryError,
taking the Web Booking and API Gateway services with it as JDBC connections
collapsed.

This scenario is the only one across the five that shows a **multi-poll progression**
— the platform detecting a worsening trend before the eventual failure, giving
operators a window to act.

---

## Timeline

| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| 15:00:00 | Afternoon appointment processing peak begins | ACTIVITY | info |
| 15:12:00 | Platform heap: 83% (3401MB/4096MB) | WINDOWS | ok |
| 15:21:00 | Platform heap: 89% (3645MB/4096MB) | WINDOWS | warning |
| 15:21:03 | HTTP latency climbing — 892ms | HTTP | ok |
| 15:21:03 | `memory_pressure_api_cascade` pattern matched | CORRELATOR | — |
| 15:21:03 | **SEV-2 declared** — confidence=71% | INCIDENT | warning |
| 15:21:03 | RCA artifact generated — 8 min lead time | RCA | — |
| 15:28:00 | Platform heap: 94% (3850MB/4096MB) | WINDOWS | critical |
| 15:28:00 | HTTP latency: 1,640ms — GC pauses increasing | HTTP | warning |
| 15:35:00 | Platform heap: 97% (3972MB/4096MB) | WINDOWS | critical |
| 15:35:00 | HTTP latency: 2,940ms — near critical | HTTP | warning |
| 15:47:12 | **Platform JVM OOM crash** — OutOfMemoryError | WINDOWS | critical |
| 15:47:12 | JDBC connections collapse — all databases → 0 | SERVICES | critical |
| 15:47:15 | Web Booking stopped | WINDOWS | critical |
| 15:47:18 | API Gateway stopped | WINDOWS | critical |
| 15:47:20 | HTTP: timeout | HTTP | critical |
| 15:47:22 | **SEV-1 escalated** — `db_unavailable` + `qmatic_service_stopped` | INCIDENT | critical |
| 15:52:00 | Platform service restarted (fresh JVM) | WINDOWS | — |
| 15:53:30 | JDBC connections re-established | SERVICES | ok |
| 15:55:00 | Full recovery — health 18 → 95 | HEALTH | ok |

---

## Multi-Poll Progression

This is a 3-phase incident showing Vorsa tracking degradation across multiple
poll cycles:

### Phase 1 — Warning (15:21 UTC) — Health: 82
```
Platform heap:   89% (3645MB)  ← WARNING threshold crossed
HTTP latency:    892ms          ← elevated but below threshold
PG pool:         4.2%           ← normal
Services:        3/3 running    ← all healthy
Rule fired:      memory_pressure_api_cascade (confidence=71%)
```

### Phase 2 — Accelerating (15:35 UTC) — Health: 61
```
Platform heap:   97% (3972MB)  ← CRITICAL — near ceiling
HTTP latency:    2940ms         ← near critical threshold
PG pool:         5.8%           ← slight elevation
Services:        3/3 running    ← still running
Rule escalated:  memory_pressure_api_cascade (confidence=84% → CRITICAL)
```

### Phase 3 — Crash (15:47 UTC) — Health: 18
```
Platform heap:   OOM crash      ← service terminated
HTTP latency:    timeout        ← unreachable
PG pool:         0%             ← all JDBC dropped
Services:        1/3 running    ← only Platform ghost process
Rules fired:     db_unavailable (91%) + qmatic_service_stopped (88%)
```

---

## Signal Chain

```
Appointment processing peak — high object allocation rate
        │
        ├── JVM heap climbing (no GC headroom)
        │         15:12: 83% → GC running but keeping up
        │         15:21: 89% → GC struggling, pauses increasing
        │         15:28: 94% → GC spending 80%+ time collecting
        │         15:35: 97% → GC unable to free enough memory
        │         15:47: OOM → JVM crash
        │
        ├── HTTP latency escalating (GC pause correlation)
        │         baseline: 228ms
        │         15:21:   892ms  (GC pauses ~200ms each)
        │         15:28: 1,640ms  (GC pauses ~800ms each)
        │         15:35: 2,940ms  (GC pauses ~2s each)
        │         15:47: timeout  (service dead)
        │
        └── JDBC collapse (post-crash)
                  qp_central: 17 → 0
                  statdb:     16 → 0
                  qp_agent:    9 → 0
                  all 5:        0
```

---

## Correlation Engine Output

### Phase 1 — 15:21 UTC
**Rule fired:** `memory_pressure_api_cascade`  
**Confidence:** 71%  
**Severity:** WARNING  

| Source | Signal | Value | Severity |
|---|---|---|---|
| WINDOWS | platform_heap_pct | 89% (threshold: 80%) | warning |
| WINDOWS | platform_heap_mb | 3645MB / 4096MB | warning |
| HTTP | api_latency_ms | 892ms | ok |
| POSTGRES | connection_pct | 4.2% | ok |

### Phase 2 — 15:35 UTC (escalation)
**Rule fired:** `memory_pressure_api_cascade`  
**Confidence:** 84%  
**Severity:** CRITICAL (confidence ≥ 80% → no downgrade)  

| Source | Signal | Value | Severity |
|---|---|---|---|
| WINDOWS | platform_heap_pct | 97% (threshold: 90% critical) | critical |
| WINDOWS | platform_heap_mb | 3972MB / 4096MB | critical |
| HTTP | api_latency_ms | 2940ms | warning |
| POSTGRES | connection_pct | 5.8% | ok |

### Phase 3 — 15:47 UTC (post-crash)
**Rules fired:** `db_unavailable` (91%) + `qmatic_service_stopped` (88%)

---

## Topology Impact

### Phase 1 (Warning)
```
API Gateway ○ → Orchestra Central ◑ → PostgreSQL ✓
                    ↑ JVM 89% heap
```

### Phase 3 (Crash)
```
Internet / Mobile · HTTPS
        │  [timeout]
        ▼
  API Gateway ●  STOPPED
        │
        ▼
Orchestra Central ●  OOM CRASH
   ┌────┼────┐
   ▼    ▼    ▼
Web●  Counter● Kiosk●
        │  [all JDBC → 0]
        ▼
 PostgreSQL ◑  running but no connections
   ┌────┼────┐
   ▼    ▼    ▼
qp_central● statdb● qp_agent●
0 JDBC     0 JDBC   0 JDBC
```

---

## RCA Summary

The Qmatic Platform JVM experienced an OutOfMemoryError after 35 minutes of
gradual heap exhaustion during an afternoon appointment processing peak. The
JVM was configured with a fixed heap of 4096MB (`-Xmx4096m -Xms4096m`) with no
room to grow. High object allocation during bulk appointment processing outpaced
GC's ability to reclaim memory.

Vorsa detected the degradation at 89% heap (8 minutes before the OOM crash)
and generated a WARNING incident with specific remediation guidance — restart
the Platform service or increase heap. The warning was not acted upon in time.

**Resolution:** Platform service restarted (fresh JVM, heap cleared). Full
recovery within 8 minutes.

---

## Runbook Reference

→ [`runbooks/api-latency.md`](../../runbooks/api-latency.md)

---

## Prevention Recommendations

1. **Act on WARNING incidents immediately** — The 8-minute lead time Vorsa
   provided was sufficient to restart the service before the OOM crash. A
   proactive restart avoids the full cascade.

2. **Lower JVM heap warning threshold to 75%** — Gives more lead time:
   ```yaml
   windows:
     thresholds:
       jvm_heap_warning_pct: 75
       jvm_heap_critical_pct: 85
   ```

3. **Add OOM heap dump** to JAVA_OPTS for post-mortem analysis:
   ```
   -XX:+HeapDumpOnOutOfMemoryError
   -XX:HeapDumpPath=C:/qmatic/logs/heapdump.hprof
   ```

4. **Increase server RAM and JVM heap** — Server has 12GB RAM at 57% usage.
   Increasing `-Xmx4096m` to `-Xmx6144m` would provide 50% more headroom.

5. **Configure Windows Service Recovery** — Auto-restart on crash with 1 minute
   delay, eliminating the need for manual intervention.

---

## Files Generated

| File | Description |
|---|---|
| `incidents/INC-2026-0516-005-jvm-memory-pressure.md` | Full RCA incident artifact |
| `dashboard/scenarios/jvm-memory-warning-state.json` | Dashboard snapshot — Phase 1 (warning) |
| `dashboard/scenarios/jvm-memory-critical-state.json` | Dashboard snapshot — Phase 3 (crash) |
