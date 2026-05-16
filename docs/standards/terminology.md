---
title: Terminology Standard
category: standards
status: stable
owner: vorsa
last_updated: 2026-05-16
---

# Vorsa Terminology Standard

> Canonical operational vocabulary for the Vorsa platform ecosystem.

---

## Purpose

Consistent terminology across documentation, code, log messages, and dashboards
reduces ambiguity during incident response and reinforces the operational
intelligence positioning of the platform.

---

## Canonical Terms

### Platform Components

| Preferred | Avoid | Definition |
|---|---|---|
| **correlation engine** | rule engine, alerting system | The component evaluating signal patterns against named incident rules |
| **correlation rule** | alert rule, check | A named pattern definition evaluated against collector snapshots |
| **collector** | agent, probe, scraper | A module that gathers telemetry from a specific source |
| **snapshot** | reading, sample, datapoint | The structured output of a single collector run |
| **poll cycle** | scrape interval, check interval | One complete execution of all collectors for an environment |
| **environment** | customer, instance, site | A configured Qmatic deployment being monitored |
| **control plane** | main loop, orchestrator | The `control_plane.py` scheduler coordinating all collectors |

### Incident Terminology

| Preferred | Avoid | Definition |
|---|---|---|
| **incident** | alert, alarm, issue, problem | A correlated signal pattern meeting the confidence threshold |
| **degradation** | slowdown, performance issue | Service operating below normal operational parameters |
| **outage** | downtime, crash, failure | Complete service unavailability |
| **cascade** | knock-on effect, ripple | Secondary failures caused by a primary failure |
| **correlation** | grouping, linking | The association of multiple signals into a single named incident |
| **confidence score** | certainty, probability | 0–100 score representing signal evidence strength |
| **suppressed warning** | low-confidence alert, filtered alert | An incident below the confidence threshold, surfaced in timeline only |
| **fingerprint** | pattern, signature | A recurring incident pattern identified by type and signal combination |
| **MTTR** | fix time, resolution time | Mean time to resolve — from incident open to confirmed recovery |
| **MTTD** | detection time | Mean time to detect — from degradation onset to incident generation |
| **RCA artifact** | post-mortem, incident report | The generated incident record including evidence, cause, and remediation |
| **lead time** | advance warning, heads-up | Time between WARNING incident and actual failure |

### Telemetry Terminology

| Preferred | Avoid | Definition |
|---|---|---|
| **telemetry** | metrics, data, stats | Collected operational signals from platform components |
| **signal** | metric, data point | A single measured value from a collector |
| **evidence** | data, proof | A signal that contributes to incident confidence scoring |
| **severity** | priority, urgency | `ok` / `warning` / `critical` — the operational impact level |
| **threshold** | limit, cutoff | A configured boundary triggering severity change |
| **health score** | overall score, status | 0–100 calculated operational health of an environment |
| **health label** | status, state | `HEALTHY` / `DEGRADED` / `CRITICAL` — health score label |
| **connection pool** | DB connections, pool | PostgreSQL active connection utilisation |
| **JDBC connections** | DB connections, queries | Java database connectivity connections per database |
| **JVM heap** | Java memory, process memory | Java Virtual Machine heap memory utilisation |
| **heap ceiling** | max heap, max memory | Configured `-Xmx` JVM maximum heap size |

### Architecture Terminology

| Preferred | Avoid | Definition |
|---|---|---|
| **service topology** | service map, dependency diagram | Visual representation of Qmatic service relationships |
| **dependency chain** | dependency tree, call chain | The ordered sequence of service dependencies |
| **operational intelligence** | monitoring, alerting | The combination of telemetry correlation and Qmatic-specific knowledge |
| **anomaly detection** | anomaly checking | Detection of data quality or behavioural deviations from baseline |
| **business hours context** | working hours, office hours | Awareness of whether anomalies occur during citizen services operation |
| **incident lifecycle** | alert lifecycle, event flow | The end-to-end flow from signal detection to incident resolution |
| **signal chain** | event chain, failure chain | The sequence of signals leading to a correlated incident |

---

## Severity Vocabulary

Always use these exact terms for severity levels:

| Level | Label | Usage |
|---|---|---|
| `ok` | HEALTHY | All signals within normal parameters |
| `warning` | DEGRADED | Signals elevated but service operational |
| `critical` | CRITICAL | Service impaired or unavailable |

**SEV levels** (for incident records):

| Level | Meaning |
|---|---|
| SEV-1 | Complete service loss or cascading failure |
| SEV-2 | Partial degradation, service operational but impaired |
| SEV-3 | Minor anomaly, no citizen-facing impact |

---

## Phrases to Avoid

| Avoid | Use instead |
|---|---|
| "things broke" | "service degradation detected" |
| "the database is slow" | "database saturation threshold exceeded" |
| "something's wrong" | "correlation engine pattern matched" |
| "it crashed" | "service terminated — OOM / connection refused" |
| "alert fired" | "incident correlated" |
| "the dashboard shows" | "telemetry indicates" |
| "issue" | "incident" or "degradation" |
| "problem" | "incident" or "anomaly" |
| "fix" | "remediate" or "resolve" |
| "broken" | "degraded" or "unavailable" |
| "looks like" | state the evidence directly |

---

## Qmatic-Specific Terminology

| Term | Definition |
|---|---|
| **Orchestra Central** | The core Qmatic orchestration engine (Windows service: QP) |
| **API Gateway** | The Qmatic external request front door (Windows service: QP_API_GW) |
| **Web Booking** | Citizen-facing appointment booking module (Windows service: QmaticWebBooking) |
| **statdb** | Statistics database — receives ETL writes from Orchestra Central |
| **qp_central** | Primary operational database for queue and appointment management |
| **nightly reset** | Scheduled statdb cleanup job run at 07:00 UTC |
| **carryover visits** | Visit records persisting from previous business day after failed reset |
| **JAVA_OPTS** | Qmatic JVM launch parameters — includes `-Xmx`, `-Xms`, `-Xmn` |
| **prunsrv** | Apache Commons Daemon process — parent of Qmatic java.exe processes |
| **visit record** | A single citizen service interaction tracked in statdb |

---

## Units and Formatting

| Metric | Format | Example |
|---|---|---|
| Memory | MB or GB with unit | `3268MB` / `4.1GB` |
| Percentage | one decimal place + % | `82.0%` |
| Latency | integer ms | `1847ms` |
| Duration | `Xm Ys` or `Xh Ym` | `7m 14s` / `1h 44m` |
| Timestamps | UTC ISO 8601 | `2026-05-16T15:21:03+00:00` |
| Display time | `HH:MM:SS UTC` | `15:21:03 UTC` |
| Confidence | integer % | `91%` |
| Health score | integer 0–100 | `82` |
| Connections | integer | `1361 / 1660` |
