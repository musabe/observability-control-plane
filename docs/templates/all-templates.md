<!-- ============================================================ -->
<!-- TEMPLATE 1: ARCHITECTURE TEMPLATE                           -->
<!-- Save as: docs/templates/architecture-template.md           -->
<!-- ============================================================ -->

---
title: [Component Name] Architecture
category: architecture
status: stable | draft
owner: vorsa
last_updated: YYYY-MM-DD
---

# [Component Name]

> [One-line operational summary of what this component does.]

---

## Purpose

[Why this component exists. What operational problem it solves.
What would be missing without it. 2-3 sentences maximum.]

---

## Architecture Context

[Where this component sits in the platform. Which components feed into it
and which components it feeds. Reference the topology diagram if relevant.]

```
[upstream component]
        │
        ▼
[this component]
        │
        ▼
[downstream component]
```

---

## Scope

**Monitors / collects from:**
- [system or service]
- [system or service]

**Feeds into:**
- [downstream component]
- [downstream component]

**Does not cover:**
- [explicit exclusions to prevent confusion]

---

## Operational Flow

[Step-by-step description of how the component operates during a poll cycle.]

1. [Step one]
2. [Step two]
3. [Step three]

**Failure handling:**
[What happens when this component fails. Does it block other collectors?
What appears in state.json?]

---

## Configuration

```yaml
# environments.yaml excerpt
[relevant_section]:
  [key]: [value]
  thresholds:
    [threshold_key]: [value]
```

**Required environment variables:**
```
[ENV_VAR_NAME]: [description]
```

---

## Output Schema

```json
{
  "available": true,
  "severity": "ok | warning | critical",
  "[field]": "[value]"
}
```

---

## Related Components

| Component | Relationship |
|---|---|
| [component] | [feeds into / fed by / peer] |

---

| Field | Value |
|---|---|
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Status** | stable |
| **Last updated** | YYYY-MM-DD |

---
---

<!-- ============================================================ -->
<!-- TEMPLATE 2: INCIDENT TEMPLATE                               -->
<!-- Save as: docs/templates/incident-template.md               -->
<!-- ============================================================ -->

---
title: INC-YYYY-MMDD-NNN — [Incident Title]
category: incident
severity: critical | warning
status: resolved | open
owner: vorsa
last_updated: YYYY-MM-DD
---

# INC-YYYY-MMDD-NNN — [Incident Title]

> [One-line summary of what failed, what was impacted, and how it was resolved.]

---

## Incident Header

| Field | Value |
|---|---|
| **Incident ID** | INC-YYYY-MMDD-NNN |
| **Environment** | [environment name] |
| **Opened** | YYYY-MM-DD HH:MM:SS UTC |
| **Resolved** | YYYY-MM-DD HH:MM:SS UTC |
| **Duration** | Xm Ys |
| **Severity** | SEV-1 / CRITICAL or SEV-2 / WARNING |
| **Detection method** | Automated — Vorsa correlation engine |
| **Incident type** | `[correlation_rule_name]` |
| **Confidence** | XX% |
| **Health score** | XX / 100 |
| **MTTR** | Xm Ys |

---

## Executive Summary

[2-4 sentences. What failed, when, what was the impact, how was it resolved.
Do not use casual language. Do not say "things broke".]

---

## Affected Systems

| System | Status During Incident | Business Impact |
|---|---|---|
| [system] | [Unavailable / Degraded / Unaffected] | [impact description] |

---

## Detection & Correlation

**Correlated signals:**

```
HH:MM:SS UTC  [signal description]  ([source])
HH:MM:SS UTC  [signal description]  ([source])
HH:MM:SS UTC  Correlation fired ([rule_name], conf=XX%)
```

**Evidence:**

| Source | Signal | Value | Severity |
|---|---|---|---|
| [SOURCE] | [signal_name] | [value] | [severity] |

**Confidence breakdown:**

| Factor | Score |
|---|---|
| Signal severity | XX/30 |
| Evidence count | XX/25 |
| Recency | XX/20 |
| Recurrence | XX/15 |
| Business hours | XX/10 |
| **Total** | **XX/100** |

---

## Root Cause

**[Confirmed / Most probable]:** [Root cause statement]

**Causal chain:**

```
[Root cause]
    ↓
[Secondary effect]
    ↓
[Terminal effect / outage]
```

---

## Timeline

| Time (UTC) | Event | Actor |
|---|---|---|
| HH:MM:SS | [event] | System / Vorsa / Engineer |

---

## Operational Impact

**[Affected service]:** [Impact description]

---

## Remediation

**Immediate actions taken:**
1. [Action]
2. [Action]

**Prevention actions required:**

| Action | Priority | Owner | Due |
|---|---|---|---|
| [action] | HIGH | [owner] | [timeframe] |

---

## Post-Incident Review

**What went well:**
- [item]

**What could be improved:**
- [item]

**Recurrence risk:** HIGH / MEDIUM / LOW — [rationale]

---

## Fingerprint

```
id:           INC-YYYY-MMDD-NNN
type:         [incident_type]
fingerprint:  [type]::[key_signals]
confidence:   XX%
mttr:         Xm Ys
auto_detected: true
```

---

| Field | Value |
|---|---|
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Environment** | [environment] |
| **Status** | resolved |
| **Last updated** | YYYY-MM-DD |

---
---

<!-- ============================================================ -->
<!-- TEMPLATE 3: RUNBOOK TEMPLATE                                -->
<!-- Save as: docs/templates/runbook-template.md                -->
<!-- ============================================================ -->

---
title: Runbook — [Incident Type / Component]
category: runbook
severity: critical | warning
status: stable
owner: vorsa
last_updated: YYYY-MM-DD
---

# Runbook — [Incident Type]

> [One-line summary: what this runbook addresses and when to use it.]

---

## Applies To

**Incident type:** `[correlation_rule_name]`  
**Environments:** [All Qmatic hosted environments / specific environment]  
**Severity:** SEV-1 / CRITICAL or SEV-2 / WARNING  
**Response time target:** < X minutes to first action

---

## Detection

Vorsa generates a `[incident_type]` incident when:

- [Condition 1]
- [Condition 2]

**Confidence threshold for SEV-1:** ≥ 80%

> [!WARNING]
> [Any critical operational note before starting remediation]

---

## Immediate Actions (0–5 minutes)

### Step 1 — [Action title]

[Instruction]

```powershell
# Command if applicable
```

### Step 2 — [Action title]

[Instruction]

---

## Recovery Actions (5–15 minutes)

### Step 3 — [Action title]

[Instruction]

### Step 4 — Confirm full recovery in Vorsa

All of the following must be true before closing the incident:

- [ ] Health score ≥ 90 (HEALTHY)
- [ ] [signal]: [expected value]
- [ ] 0 active incidents in Vorsa

---

## Escalation

### Escalate immediately if:

- [Condition requiring escalation]

### Escalation path:

1. On-call engineer → [next tier]
2. [next tier] → [final escalation]

---

## Prevention Configuration

```yaml
# environments.yaml
[relevant_section]:
  thresholds:
    [threshold]: [recommended_value]
```

---

## Related

- [`incidents/`](../incidents/) — historical incident records
- [`docs/scenarios/`](../scenarios/) — scenario demonstrations
- [Related runbook](./related-runbook.md)

---

| Field | Value |
|---|---|
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Incident type** | `[type]` |
| **Status** | stable |
| **Last updated** | YYYY-MM-DD |

---
---

<!-- ============================================================ -->
<!-- TEMPLATE 4: SCENARIO TEMPLATE                               -->
<!-- Save as: docs/templates/scenario-template.md               -->
<!-- ============================================================ -->

---
title: Scenario [X] — [Scenario Title]
category: incident-scenarios
severity: critical | warning
status: stable
owner: vorsa
last_updated: YYYY-MM-DD
---

# Scenario [X] — [Scenario Title]

> [One-line operational summary: what fails, what the platform detects, what the resolution is.]

---

## Overview

**Scenario type:** [Infrastructure failure / Application degradation / Data quality anomaly]  
**Severity:** [SEV-1 CRITICAL / SEV-2 WARNING]  
**Health score:** [start] → [end]  
**Duration:** ~[X] minutes  
**Correlation rule:** `[rule_name]`  
**Confidence:** [XX]%

[2-3 sentences describing what this scenario demonstrates. Why it is operationally
significant. What a generic monitoring tool would and would not detect.]

---

## Timeline

| Time (UTC) | Event | Signal | Severity |
|---|---|---|---|
| HH:MM:SS | [event] | [SOURCE] | [severity] |
| HH:MM:SS | **[SEV-X declared]** — `[rule_name]` confidence=XX% | INCIDENT | [severity] |

---

## Signal Chain

```
[Root cause signal]
        │
        ├── [Secondary signal A]
        │         [detail]
        │
        └── [Secondary signal B / outcome]
```

---

## Correlation Engine Output

**Rule fired:** `[rule_name]`  
**Confidence:** XX%  
**Severity:** [WARNING / CRITICAL]

| Source | Signal | Value | Severity |
|---|---|---|---|
| [SOURCE] | [signal] | [value] | [severity] |

---

## Topology Impact

```
[Topology diagram showing affected nodes with symbols]
✓ = healthy  ◑ = degraded  ● = failed
```

---

## Dashboard State

| Metric | Value |
|---|---|
| Health score | XX (HEALTHY / DEGRADED / CRITICAL) |
| Active incidents | X |
| PG pool | X% |
| HTTP latency | Xms |

---

## RCA Summary

[2-3 sentences: what caused the incident, what signals confirmed it,
how it was resolved.]

---

## Preview

Load this scenario in the dashboard:

```powershell
Copy-Item dashboard\scenarios\[scenario-name]-state.json dashboard\state.json -Force
```

---

## Files

| File | Description |
|---|---|
| `incidents/INC-YYYY-MMDD-NNN-[type].md` | RCA incident artifact |
| `dashboard/scenarios/[name]-state.json` | Dashboard snapshot |
| `runbooks/[runbook].md` | Operational runbook |

---

| Field | Value |
|---|---|
| **Scenario** | [X] of 5 |
| **Rule** | `[rule_name]` |
| **Status** | stable |
| **Last updated** | YYYY-MM-DD |

---
---

<!-- ============================================================ -->
<!-- TEMPLATE 5: SERVICE TEMPLATE                                -->
<!-- Save as: docs/templates/service-template.md                -->
<!-- ============================================================ -->

---
title: [Service Name] — Service Reference
category: architecture
status: stable
owner: vorsa
last_updated: YYYY-MM-DD
---

# [Service Name]

> [One-line description of the service's operational role.]

---

## Service Identity

| Field | Value |
|---|---|
| **Windows service name** | `[ServiceName]` |
| **Display name** | [Display Name] |
| **Process** | `[process.exe]` |
| **Port** | [port] |
| **JVM heap** | `-Xmx[N]m -Xms[N]m` |
| **Role** | [External access / Core orchestration / Citizen interface] |

---

## Dependencies

**Depends on:**
- [dependency] — [reason]

**Depended on by:**
- [downstream] — [reason]

---

## Monitored Signals

| Signal | Collector | Threshold | Action |
|---|---|---|---|
| Service state | Windows/WMI | `Running` required | `qmatic_service_stopped` rule |
| JVM heap % | Windows/WMI | 80% warning / 90% critical | `memory_pressure_api_cascade` |
| Memory (working set) | Windows/WMI | Informational | Health score |

---

## Failure Modes

| Failure | Cause | Detection | Impact |
|---|---|---|---|
| OOM crash | Heap exhaustion | `qmatic_service_stopped` | Cascade to dependencies |
| Slow start | GC pressure | `app_layer_issue` | Latency elevation |
| Hang | Thread deadlock | HTTP timeout | Booking unavailable |

---

## Operational Commands

**Check service status:**
```powershell
Get-Service -Name "[ServiceName]"
```

**Restart service:**
```powershell
Restart-Service -Name "[ServiceName]"
```

**Check JVM heap:**
```powershell
Get-WmiObject Win32_Process -Filter "Name='java.exe'" |
  Select-Object ProcessId, @{N='Xmx';E={
    if($_.CommandLine -match '-Xmx(\S+)'){$matches[1]}
  }}
```

---

| Field | Value |
|---|---|
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Status** | stable |
| **Last updated** | YYYY-MM-DD |

---
---

<!-- ============================================================ -->
<!-- TEMPLATE 6: README TEMPLATE                                 -->
<!-- Save as: docs/templates/readme-template.md                 -->
<!-- ============================================================ -->

---
title: [Repository Name]
category: readme
status: stable
owner: vorsa
last_updated: YYYY-MM-DD
---

# [Repository / Platform Name]

> [One-line positioning statement. What the platform does. Who it is for.]

---

## Platform Summary

[2-3 sentences. What this platform is. What operational problem it solves.
Who operates it. What makes it distinct from generic monitoring tools.]

---

## Operational Purpose

[Why this platform exists. What gap it fills. What the alternative is without it.]

> [!NOTE]
> [Key differentiator — what this platform detects that generic tools cannot]

---

## Architecture Overview

```
[High-level architecture diagram]
```

[Brief explanation of the diagram — 2-3 sentences.]

---

## Core Components

| Component | Purpose |
|---|---|
| `[component]` | [description] |

---

## Incident Workflows

[How incidents are detected, correlated, and resolved using this platform.
Reference the correlation engine and confidence scoring.]

---

## Scenario Demonstrations

| Scenario | Type | Rule | Severity |
|---|---|---|---|
| [Scenario A] | [type] | `[rule]` | SEV-1 |

---

## Telemetry & Correlation

[Which signals are collected and how they are correlated.]

---

## RCA Generation

[How incident artifacts are generated and where they are stored.]

---

## Runbooks

- [`runbooks/[name].md`](runbooks/name.md) — [description]

---

## Screenshots

[Screenshot section with brief captions]

---

## Operational Philosophy

[What the platform prioritises. Design principles. What it intentionally does not do.]

---

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | [description] | complete |
| Phase 2 | [description] | in progress |

---

| Field | Value |
|---|---|
| **Platform** | [Platform name and version] |
| **Status** | stable |
| **Last updated** | YYYY-MM-DD |
