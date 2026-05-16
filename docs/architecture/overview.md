# Vorsa — Operational Intelligence Platform
## Architecture Documentation

**Version:** 2.0  
**Environment target:** Hosted Qmatic Orchestra deployments  
**Last updated:** 2026-05-16  

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Collector Lifecycle](#2-collector-lifecycle)
3. [Signal Processing Flow](#3-signal-processing-flow)
4. [Correlation Engine](#4-correlation-engine)
5. [Confidence Scoring Model](#5-confidence-scoring-model)
6. [Incident Lifecycle](#6-incident-lifecycle)
7. [RCA Generation Pipeline](#7-rca-generation-pipeline)
8. [Health Scoring Model](#8-health-scoring-model)
9. [Topology Relationships](#9-topology-relationships)
10. [Configuration Model](#10-configuration-model)
11. [Operational Dependency Mapping](#11-operational-dependency-mapping)
12. [Dashboard Architecture](#12-dashboard-architecture)

---

## 1. Platform Overview

Vorsa is an operational intelligence platform purpose-built for hosted Qmatic
Orchestra environments. It bridges the gap between generic infrastructure
monitoring and Qmatic-specific operational knowledge — detecting failure patterns,
data anomalies, and service degradation that no generic tool can surface.

### Design principles

**Signal correlation over raw alerting**  
Vorsa does not alert on individual metrics. It correlates signals across
collectors to identify named incident patterns — `db_unavailable`,
`db_saturation_api_cascade`, `app_layer_issue` — with confidence scoring
that eliminates false positives.

**Confidence-weighted severity**  
Every incident carries a 0–100 confidence score. Low-confidence signals
are surfaced in the timeline but suppressed from incident generation.
Critical severity requires ≥ 80% confidence. This prevents alert fatigue
while maintaining sensitivity to real degradation.

**Qmatic-specific intelligence**  
Vorsa understands Qmatic data semantics — visit records, JDBC connection
patterns by database, statistics pipeline behaviour, business hours context.
This enables detection of data quality incidents (reporting anomalies) that
are completely invisible to infrastructure monitoring.

**Operational realism over feature breadth**  
The platform prioritises operational depth over feature count. Five
correlation rules with precise evidence models outperform fifty rules
that generate noise.

### Platform positioning

```
Generic monitoring tools:          Vorsa adds:
  CPU / memory / disk                Qmatic JDBC connection semantics
  Process up/down                    Visit record data quality checks
  HTTP status codes                  Business hours context
  Raw query counts                   Incident fingerprint matching
  Infrastructure topology            Qmatic service dependency awareness
                                     Confidence-weighted correlation
                                     RCA generation with remediation
```

---

## 2. Collector Lifecycle

Each poll cycle (default 60 seconds) executes all collectors in sequence
for every configured environment. Collectors are independent — a failure
in one does not block others.

```
control_plane.py (poll loop)
│
├── PostgresCollector.collect()
│     └── pg_stat_activity, pg_stat_database → PostgresSnapshot
│
├── HttpCollector.collect()
│     └── HTTP GET checks → HttpSnapshot
│
├── WindowsCollector.collect()
│     ├── Win32_OperatingSystem → memory metrics
│     ├── Win32_Service (filtered: Qmatic) → service state
│     ├── Win32_Process (child walk: prunsrv→cmd→java) → memory per service
│     └── Win32_Process.CommandLine (-Xmx parse) → JVM heap ceiling
│
└── QmaticChecks.collect()
      ├── qmatic_postgres_checks → JDBC per-DB, service connections
      ├── qmatic_activity_checks → visit counts, business hours
      └── qmatic_reporting_checks → duplicate IDs, carryover totals
```

### Collector failure handling

Each collector wraps its collection in a try/except. On failure:
- The snapshot is marked `available: false`
- The error message is stored in `snapshot.error`
- The control plane continues with remaining collectors
- The failed collector's absence is reflected in health scoring

### JVM heap detection — priority chain

The Windows collector uses a three-tier fallback for JVM heap ceiling:

```
Priority 1: WMI CommandLine parse
  Walk process tree: Service → prunsrv → cmd → java.exe
  Parse: -Xmx4096m from CommandLine
  Source label: "detected"

Priority 2: environments.yaml config
  qmatic_jvm_heap_max_mb: 4096
  Source label: "config"

Priority 3: Server total RAM
  Falls back to total server memory as ceiling
  Source label: "server_ram"
```

This handles environments where JAVA_OPTS is set via environment variable
(not visible to WMI CommandLine) — common in Qmatic Orchestra deployments.

---

## 3. Signal Processing Flow

```
Raw telemetry
     │
     ▼
┌─────────────────────────────────────────────────────┐
│                   Collectors                         │
│  PostgresSnapshot  HttpSnapshot  WindowsSnapshot     │
│  QmaticServiceSnap  ActivitySnap  ReportingSnap      │
└─────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────┐
│              env_state assembly                      │
│                                                      │
│  Snapshots serialised to dict for:                   │
│    • dashboard state.json output                     │
│    • correlation engine input                        │
│    • health score calculation                        │
└─────────────────────────────────────────────────────┘
     │
     ├──────────────────────────────────┐
     ▼                                  ▼
┌──────────────┐                ┌──────────────────┐
│  Correlator  │                │  Health Scorer   │
│  (8 rules)   │                │  (penalty model) │
└──────────────┘                └──────────────────┘
     │                                  │
     ▼                                  ▼
┌──────────────────────────────────────────────────────┐
│                  env_state output                     │
│                                                      │
│  incidents[]          suppressed_warnings[]          │
│  health_score         health_label                   │
│  overall_severity     [all collector snapshots]      │
└──────────────────────────────────────────────────────┘
     │
     ├── dashboard/state.json  (live dashboard)
     ├── incidents/*.md        (RCA artifacts)
     └── logs/alerts.jsonl     (alert log)
```

---

## 4. Correlation Engine

The correlation engine evaluates all rules against every poll cycle's
signal snapshot. Rules are independent — multiple rules can fire in the
same cycle.

### Rule catalogue

| Rule | Trigger condition | Primary signals |
|---|---|---|
| `db_unavailable` | PostgreSQL unreachable | PG availability, HTTP, JDBC |
| `db_saturation_api_cascade` | PG pool > 75% + HTTP elevated | PG pool, long queries, HTTP latency |
| `zero_activity_business_hours` | Zero visits during business hours | Activity counts, business hours |
| `reporting_anomaly_with_db_pressure` | Duplicate visits or carryover | Reporting checks, statdb JDBC |
| `service_stopped_db_drop` | Service stopped + JDBC dropped | Windows services, JDBC counts |
| `memory_pressure_api_cascade` | JVM heap > 80% + HTTP elevating | Windows heap %, HTTP latency |
| `silent_service_failure` | JDBC → 0, service running | JDBC counts, Windows services |
| `app_layer_issue` | HTTP slow, infra healthy | HTTP latency, PG ok, services ok |
| `qmatic_service_stopped` | Any Qmatic service not running | Windows service state |

### Rule anatomy

Each rule is a decorated function that:
1. Receives all collector snapshots as arguments
2. Evaluates its specific trigger condition
3. Collects evidence signals
4. Calls `calculate_confidence()` with the evidence set
5. Returns a `CorrelatedIncident` or `None`

```python
@correlation_rule
def rule_db_unavailable(env, pg_snap, http_snap, ...):
    if pg_snap and pg_snap.available:
        return None                          # not triggered

    evidence = [
        Evidence("postgres", "availability", "UNREACHABLE", "critical"),
        Evidence("http", "reachable", str(http_snap.all_reachable), ...),
    ]

    confidence = calculate_confidence(
        "db_unavailable", evidence, env.name, ...
    )

    return CorrelatedIncident(
        incident_type="db_unavailable",
        severity=adjust_severity("critical", confidence),
        confidence=confidence,
        suppressed=should_suppress(confidence),
        ...
    )
```

---

## 5. Confidence Scoring Model

Every correlation produces a 0–100 confidence score. The score gates
severity and suppression decisions.

### Scoring factors

| Factor | Weight | Description |
|---|---|---|
| Signal severity | 0–30 | Number and severity of critical/warning signals |
| Evidence count | 0–25 | More corroborating signals → higher confidence |
| Recency | 0–20 | All signals from same poll cycle = maximum recency |
| Recurrence | 0–15 | Pattern seen recently in incident history |
| Business hours | 0–10 | Anomalies during business hours weighted higher |
| **Maximum** | **100** | |

### Severity adjustment rules

```
confidence ≥ 80% + critical pattern → CRITICAL severity
confidence 50–79% + critical pattern → WARNING (downgraded)
confidence < 50%                     → SUPPRESSED (timeline only)
```

### Suppression behaviour

Suppressed incidents (confidence < 50%) are:
- Added to `suppressed_warnings[]` in state.json
- Shown in the dashboard correlation timeline (dimmed, marked `~`)
- Not written to incident RCA files
- Not logged to alerts.jsonl
- Still visible for operator awareness

This prevents alert fatigue while maintaining full signal transparency.

### Recurrence scoring

The incident history file (`dashboard/incident_history.jsonl`) is scanned
for the same `incident_type` in the last 24 hours. Each prior occurrence
adds up to 15 points to the recurrence score.

---

## 6. Incident Lifecycle

```
Poll cycle begins
      │
      ▼
Collectors run → snapshots assembled
      │
      ▼
Correlation engine evaluates all 9 rules
      │
      ├── No rules fire → state written, no incidents
      │
      └── Rules fire → for each fired rule:
            │
            ├── confidence < 50%  → suppressed_warning (timeline only)
            │
            └── confidence ≥ 50%  → active incident
                    │
                    ├── severity adjusted by confidence
                    │
                    ├── RCA generator → incidents/*.md
                    │
                    ├── Alert log → logs/alerts.jsonl
                    │
                    └── Incident history → dashboard/incident_history.jsonl
                            │
                            └── Used for recurrence scoring in future cycles
```

### Incident deduplication

Each poll cycle produces a fresh set of incidents. There is no deduplication
across cycles — if a condition persists, the incident is re-generated each
cycle. This is intentional: each RCA file represents a point-in-time snapshot
of the incident state, allowing post-incident timeline reconstruction.

### Incident retention

RCA files are written to `incidents/` and are never automatically deleted.
The `.gitignore` excludes `incidents/*.md` from version control — they are
operational artefacts, not source code.

---

## 7. RCA Generation Pipeline

```
CorrelatedIncident
      │
      ▼
RCAGenerator.generate(incident, pg_snap)
      │
      ├── Assembles IncidentSummary:
      │     title, severity, confidence
      │     likely_cause (from rule definition)
      │     recommended_actions (from rule definition)
      │     evidence[] (from correlation)
      │     fingerprint (incident_type + key signals)
      │
      ├── RCAGenerator.save_markdown(summary)
      │     → incidents/YYYYMMDD_HHMMSS_{env}_{type}.md
      │
      └── RCAGenerator.log_alert(summary)
            → logs/alerts.jsonl (JSONL append)
```

### RCA file naming

```
incidents/20260516_154722_northvale_council_memory_pressure_api_cascade.md
          │        │       │                 │
          date     time    environment       incident_type
```

### RCA content structure

Each generated RCA markdown file contains:
- Incident header (type, severity, confidence, timestamp)
- Likely cause narrative
- Evidence table (source, signal, value, severity)
- Recommended actions list
- Fingerprint hash

---

## 8. Health Scoring Model

Health score (0–100) is calculated from live signals each poll cycle using
a penalty-based model. Score starts at 100 and penalties are subtracted.

### Penalty table

| Condition | Penalty |
|---|---|
| Active incident — critical (100% confidence) | −40 |
| Active incident — warning | −20 |
| Suppressed warning | −5 each |
| PostgreSQL unavailable | −30 |
| PG connections ≥ 90% | −20 |
| PG connections ≥ 75% | −10 |
| HTTP unreachable | −25 |
| HTTP latency critical | −15 |
| HTTP latency warning | −10 |
| Windows service stopped | −15 each |
| Server memory ≥ 90% | −15 |
| Server memory ≥ 80% | −8 |
| JVM heap critical (per service) | −20 |
| JVM heap warning (per service) | −10 |
| Long-running queries | −5 |
| Blocked queries | −10 |

**Floor: 0. Ceiling: 100.**

Confidence scales incident penalties — a warning incident at 51% confidence
applies half the penalty of one at 95% confidence.

### Health labels

| Score | Label | Severity |
|---|---|---|
| 90–100 | HEALTHY | ok |
| 60–89 | DEGRADED | warning |
| 0–59 | CRITICAL | critical |

---

## 9. Topology Relationships

The Vorsa service topology reflects the real Qmatic Orchestra architecture,
rendered as a live dependency graph in the dashboard.

```
┌─────────────────────────┐
│     Client Channels     │
│  Web · Mobile · Kiosk   │
└────────────┬────────────┘
             │
  ┌──────────▼──────────┐
  │     API Gateway     │
  │  Auth · Routing     │
  │  REST Services      │
  └──────────┬──────────┘
             │
    ┌─────────┼─────────┐
    │         │         │
┌───▼────┐ ┌──▼──────┐ ┌▼────────┐
│Orchestra│ │Appoint- │ │Messaging│
│  Core  │ │ment Eng │ │ Engine  │
│Queue · │ │Booking ·│ │SMS ·    │
│Workflow│ │Calendar │ │Email    │
└───┬────┘ └──┬──────┘ └┬────────┘
    │         │          │
    └────┬────┘          │
         │               │
┌────────▼────────┐ ┌────▼──────────┐
│  Operational DB │ │ Statistics DB │
│  qp_central     │ │ statdb        │
│  qp_agent       │ │               │
└────────┬────────┘ └──────┬────────┘
         │                  │ ETL
  ┌──────┼──────┐           │
  ▼      ▼      ▼    ┌──────▼──────────┐
Kiosks Counter Disp  │ BI / Historical │
       App    lays   │ Reports         │
                     └─────────────────┘
```

### Database role mapping

| Database | Role | Primary consumers |
|---|---|---|
| qp_central | Core operational data | Orchestra Core, Appointment Engine |
| statdb | Statistics + event history | All engines → BI / Historical Reports |
| qp_agent | Agent and user mappings | Orchestra Core, Counter App |
| qp_calendar | Appointment scheduling | Appointment Engine |
| qp_app | System configuration | All engines (startup) |

### Topology during incidents

The dashboard topology SVG updates dynamically from `state.json`:
- Stopped services → red nodes with dashed arrows
- 0 JDBC connections → red database nodes
- Degraded heap → amber service nodes
- All healthy → green nodes

---

## 10. Configuration Model

All environment configuration lives in `config/environments.yaml`. No
code changes are required to add a new environment.

### Environment definition

```yaml
environments:
  - name: northvale-council          # used in logs, state.json, incident filenames
    type: qmatic
    enabled: true
    timezone: America/Toronto        # business hours evaluation

    business_hours:                  # per-day open/close windows
      monday:    ["08:00", "18:00"]
      saturday:  []                  # empty = closed

    windows:
      host: 192.168.68.114
      username: Administrator
      qmatic_jvm_heap_max_mb: 4096   # fallback if WMI can't read -Xmx
      thresholds:
        server_memory_warning_pct: 80
        server_memory_critical_pct: 90
        jvm_heap_warning_pct: 80
        jvm_heap_critical_pct: 90

    postgres:
      host: 192.168.68.114
      port: 5432
      database: qp_app               # connection database
      username: vorsa_readonly
      thresholds:
        connection_pct_warning:  75
        connection_pct_critical: 90
        long_query_seconds:      30
      monitored_databases:
        - qp_central
        - qp_app
        - qp_agent
        - qp_calendar
        - statdb

    http_checks:
      - name: qmatic-login
        url: http://192.168.68.114:8080/login.jsp
        warning_latency_ms: 1500
        critical_latency_ms: 3000

    reporting_checks:
      enabled: false                 # enable after statdb schema mapping
```

### Secret injection

Credentials are never stored in YAML. Environment variables follow the
naming convention:

```
OBS_DB_PASSWORD_{ENV_NAME_UPPER_SNAKE}
OBS_WMI_USER_{ENV_NAME_UPPER_SNAKE}
OBS_WMI_PASSWORD_{ENV_NAME_UPPER_SNAKE}
```

For `northvale-council`:
```
OBS_DB_PASSWORD_NORTHVALE_COUNCIL
OBS_WMI_USER_NORTHVALE_COUNCIL
OBS_WMI_PASSWORD_NORTHVALE_COUNCIL
```

---

## 11. Operational Dependency Mapping

Vorsa's signal dependencies — which collectors feed which correlation rules:

```
PostgresCollector ────────────────┐
                                   ├──► db_unavailable
HttpCollector ─────────────────────┤
                                   ├──► db_saturation_api_cascade
QmaticPostgresChecks ──────────────┤
                                   ├──► service_stopped_db_drop
WindowsCollector ──────────────────┤
                                   ├──► memory_pressure_api_cascade
QmaticActivityChecks ──────────────┤
                                   ├──► zero_activity_business_hours
QmaticReportingChecks ─────────────┤
                                   ├──► reporting_anomaly_with_db_pressure
                                   ├──► silent_service_failure
                                   ├──► app_layer_issue
                                   └──► qmatic_service_stopped
```

### Collector-to-rule dependency matrix

| Rule | Postgres | HTTP | Windows | JDBC | Activity | Reporting |
|---|---|---|---|---|---|---|
| `db_unavailable` | ✓ | ✓ | — | ✓ | — | — |
| `db_saturation_api_cascade` | ✓ | ✓ | — | ✓ | — | — |
| `zero_activity_business_hours` | — | — | — | — | ✓ | — |
| `reporting_anomaly` | ✓ | — | — | ✓ | — | ✓ |
| `service_stopped_db_drop` | — | — | ✓ | ✓ | — | — |
| `memory_pressure_api_cascade` | ✓ | ✓ | ✓ | — | — | — |
| `silent_service_failure` | — | — | ✓ | ✓ | — | — |
| `app_layer_issue` | ✓ | ✓ | ✓ | ✓ | — | — |
| `qmatic_service_stopped` | — | — | ✓ | ✓ | — | — |

---

## 12. Dashboard Architecture

The Vorsa dashboard is a single-file HTML application (`dashboard/index.html`)
that reads `dashboard/state.json` via `fetch()` every 60 seconds.

### Data flow

```
control_plane.py → state.json → index.html (fetch every 60s)
```

### State.json schema

```json
{
  "schema_version": "2.0",
  "polled_at": "ISO8601",
  "environments": [{
    "name": "string",
    "overall_severity": "ok|warning|critical",
    "health_score": 0-100,
    "health_label": "HEALTHY|DEGRADED|CRITICAL",
    "postgres": { ... PostgresSnapshot ... },
    "http": { ... HttpSnapshot ... },
    "windows": { ... WindowsSnapshot ... },
    "services": { ... QmaticServiceSnapshot ... },
    "incidents": [ ... CorrelatedIncident[] ... ],
    "suppressed_warnings": [ ... suppressed[] ... ]
  }]
}
```

### Serving the dashboard

```bash
# From repo root
python -m http.server 8888
# Open: http://localhost:8888/dashboard/index.html
```

### Scenario snapshots

Pre-built scenario state files live in `dashboard/scenarios/`:

```
dashboard/scenarios/
├── postgres-outage-state.json      # Scenario A — SEV-1, health=12
├── jdbc-saturation-state.json      # Scenario B — SEV-2, health=58
├── reporting-anomaly-state.json    # Scenario C — SEV-2, health=72
├── api-degradation-state.json      # Scenario D — SEV-2, health=75
├── jvm-memory-warning-state.json   # Scenario E Phase 1 — health=82
└── jvm-memory-critical-state.json  # Scenario E Phase 3 — SEV-1, health=18
```

To load a scenario:
```powershell
Copy-Item dashboard\scenarios\postgres-outage-state.json dashboard\state.json -Force
# Hard refresh browser
```

---

*Vorsa Observability Control Plane v2.0*  
*Architecture documentation — platform engineering*
