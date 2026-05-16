---
title: Visual Language Standard
category: standards
status: stable
owner: vorsa
last_updated: 2026-05-16
---

# Vorsa Visual Language Standard

> Structural and visual conventions for operational documentation.

---

## Purpose

Visual consistency across documentation enables engineers to navigate under
pressure. During an active incident, a familiar layout reduces time-to-action.

---

## Incident State Indicators

Use these symbols consistently in topology diagrams and signal chains:

| Symbol | Meaning |
|---|---|
| `✓` | Healthy — within normal parameters |
| `○` | Running but operationally impacted |
| `◑` | Degraded — elevated signals, service operational |
| `⚠` | Anomaly — data quality or configuration issue |
| `●` | Failed / unavailable |

**Example topology:**
```
API Gateway ◑  ← Running but slow (latency elevated)
      │
      ▼
PostgreSQL ●  ← Unavailable (connection refused)
```

---

## Signal Chain Diagrams

Signal chains show the causal sequence leading to a correlated incident.
Use indented `├──` and `└──` for branching, `│` for continuation.

```
Root cause signal
      │
      ├── Secondary signal A
      │         detail
      │
      ├── Secondary signal B
      │         detail
      │
      └── Terminal signal / outcome
```

---

## Metric Progression Tables

For multi-phase incidents, use a progression table:

```markdown
| Time (UTC) | Heap % | HTTP | Confidence | Severity |
|---|---|---|---|---|
| 15:21 | 89% | 892ms | 71% | WARNING |
| 15:35 | 97% | 2940ms | 91% | CRITICAL |
| 15:47 | OOM | timeout | 91% | CRITICAL |
```

---

## Topology Diagrams

Use the canonical Qmatic topology layout consistently:

```
Internet / Mobile · HTTPS
        │
        ▼
Qmatic API Gateway
        │
        ▼
Orchestra Central
   ┌────┼────┐
   ▼    ▼    ▼
Web   Counter  Kiosk
Booking Apps  Systems
        │
        ▼
PostgreSQL
   ┌────┼────┐
   ▼    ▼    ▼
qp_central statdb qp_agent
        │
        ▼
Reporting / BI
```

During incidents, annotate nodes with state and severity symbol:
```
PostgreSQL ●  ← connection refused
qp_central ●  ← 0 JDBC connections
```

---

## Confidence Score Display

Always display confidence scores as integer percentages with context:

```markdown
**Confidence:** 91%  
**Severity:** CRITICAL (confidence ≥ 80% — no downgrade)
```

For downgraded severity:
```markdown
**Confidence:** 73%  
**Severity:** WARNING (downgraded from CRITICAL — confidence < 80%)
```

---

## Evidence Tables

Standard evidence table format for all incident records:

```markdown
| Source | Signal | Value | Severity |
|---|---|---|---|
| POSTGRES | connection_pct | 82.0% | warning |
| HTTP | api_latency_ms | 1847ms | warning |
| WINDOWS | platform_heap_pct | 89% | critical |
```

Source labels are always uppercase: `POSTGRES`, `HTTP`, `WINDOWS`, `SERVICES`,
`REPORTING`, `ACTIVITY`.

---

## Timeline Format

Incident timelines use consistent column order:

```markdown
| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| 08:44:48 | JDBC connections drop to 0 | SERVICES | warning |
| 08:45:04 | SEV-1 declared — `db_unavailable` | INCIDENT | critical |
```

Highlight SEV declarations in bold:

```markdown
| 08:45:04 | **SEV-1 declared** — `db_unavailable` confidence=91% | INCIDENT | critical |
```

---

## Action Priority Labels

Use consistent priority labels in prevention/action tables:

| Label | Meaning |
|---|---|
| `CRITICAL` | Must be done before next business day |
| `HIGH` | Must be done this week |
| `MEDIUM` | This sprint / development cycle |
| `LOW` | Backlog / next quarter |

---

## Code Block Standards

**Configuration examples** — always use `yaml`:
````markdown
```yaml
thresholds:
  jvm_heap_warning_pct: 80
```
````

**SQL diagnostic queries** — always use `sql`:
````markdown
```sql
SELECT pid, now() - query_start AS duration
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC;
```
````

**PowerShell operational commands** — always use `powershell`:
````markdown
```powershell
Get-Service -Name "*qmatic*" | Select-Object Name, Status
```
````

**Log output** — always use plain code blocks (no language tag):
````markdown
```
2026-05-16 15:21:03  WARNING  [northvale-council] INCIDENT: JVM memory pressure
```
````

---

## Document Footer

End operational documents with a consistent footer:

```markdown
---

| Field | Value |
|---|---|
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Environment** | northvale-council |
| **Status** | stable |
| **Last updated** | 2026-05-16 |
```

---

## What to Avoid

| Avoid | Reason |
|---|---|
| Emoji in headings or body text | Reduces professional tone |
| `---` inside tables | Breaks GitHub rendering |
| Nested blockquotes | Visually noisy |
| Long paragraphs in runbooks | Operators need scannable steps |
| Generic placeholder text | Every example must be operationally believable |
| Inconsistent capitalization of signals | Always UPPERCASE source labels |
