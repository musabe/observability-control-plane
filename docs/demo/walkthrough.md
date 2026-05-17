---
title: Vorsa Platform — Demo Walkthrough
category: demo
status: stable
owner: vorsa
last_updated: 2026-05-16
---

# Vorsa — Operational Demo Walkthrough

> A 3-minute operational demonstration showing the platform detecting, correlating,
> and responding to a live Qmatic infrastructure incident.

---

## Demo Overview

| Field | Value |
|---|---|
| **Target duration** | 2 minutes 30 seconds — 3 minutes 30 seconds |
| **Scenario used** | Scenario A — PostgreSQL Outage (most visually compelling) |
| **Format** | Screen recording with narration |
| **Audience** | Technical reviewers, SRE teams, platform engineering interviews |
| **Platform state** | Live `northvale-council` environment |

---

## Pre-Demo Setup Checklist

Complete all steps before recording:

**Environment:**
- [ ] Qmatic services running — all 3 green
- [ ] PostgreSQL healthy — connection pool < 10%
- [ ] HTTP responding — HTTP 200
- [ ] `python control_plane.py` running in Terminal 1
- [ ] `python -m http.server 8888` running in Terminal 2
- [ ] Browser open at `http://localhost:8888/dashboard/index.html`
- [ ] Dashboard showing HEALTHY, health score ≥ 95

**Screen:**
- [ ] Browser fullscreen or near-fullscreen
- [ ] Terminal visible in a split pane (optional — shows log lines)
- [ ] Recording software ready (OBS, Loom, or Windows Game Bar)
- [ ] Resolution: 1920×1080 minimum
- [ ] Browser zoom: 90% (fits full dashboard)

**Scenario files ready:**
- [ ] `dashboard/scenarios/postgres-outage-state.json` in place
- [ ] Recovery state ready (healthy state.json)

---

## Scene-by-Scene Script

---

### Scene 1 — Healthy Environment (0:00 – 0:30)

**What to show:** Dashboard in HEALTHY state. All panels green.

**Narration:**

> "This is the Vorsa control plane — an operational intelligence platform
> built specifically for hosted Qmatic Orchestra environments.
>
> You're looking at the northvale-council environment — a live Qmatic
> deployment serving citizen services.
>
> Health score: 97. PostgreSQL connection pool at 2.8%. HTTP responding
> at 228 milliseconds. Three Qmatic services running. 45 JDBC connections
> across five databases. Everything nominal."

**Mouse actions:**
1. Point to health score (top left)
2. Sweep across the metric bar — incidents, PG pool, latency, memory, services
3. Point to HEALTHY badge (top right)
4. Scroll down briefly to show JDBC grid and correlation timeline

**Key point to land:**  
*"This is what operational baseline looks like. The platform polls every 60 seconds
and tracks this state continuously."*

---

### Scene 2 — Service Topology (0:30 – 0:50)

**What to show:** Scroll to the service topology panel.

**Narration:**

> "The service topology reflects the real Qmatic Orchestra architecture —
> Internet clients through the API Gateway, down through Orchestra Central
> to the Web Booking, Counter, and Kiosk modules, through JDBC to PostgreSQL,
> and into the reporting layer.
>
> Right now every node is green. The topology updates live — you'll see
> this change in a moment."

**Mouse actions:**
1. Point to Internet/Mobile at top
2. Trace down the topology — Gateway → Orchestra → sub-services → PostgreSQL → DBs
3. Point to qp_central (17 JDBC), statdb (16 JDBC)

**Key point to land:**  
*"The platform understands the dependency chain. When something fails,
you'll see exactly which part of the stack is affected."*

---

### Scene 3 — Failure Introduced (0:50 – 1:10)

**What to show:** Load the postgres-outage scenario state.json.

> [!NOTE]
> For a live demo: stop the PostgreSQL service and wait for the next poll.
> For a recorded demo: copy the scenario state.json.

**For recorded demo — run in terminal (off-screen or visible):**
```powershell
Copy-Item dashboard\scenarios\postgres-outage-state.json dashboard\state.json -Force
```
Then click **↺ refresh** in the dashboard.

**Narration (during the state change):**

> "I'm going to simulate a PostgreSQL service failure — the most common
> and most impactful incident in a Qmatic deployment.
>
> Watch what happens."

**Mouse actions:**
1. Click ↺ refresh button
2. Pause — let the dashboard update

---

### Scene 4 — Dashboard Reacts (1:10 – 1:40)

**What to show:** The full CRITICAL state — health 12, 2 incidents, red panels.

**Narration:**

> "The platform has detected a complete infrastructure failure.
>
> Health score has dropped from 97 to 12 — CRITICAL.
>
> PostgreSQL: offline. Connection pool: zero. HTTP: timeout. Qmatic services:
> two stopped, one orphaned.
>
> The JDBC grid shows all five databases at zero connections simultaneously —
> this is the signature of a database-layer failure, not an application issue."

**Mouse actions:**
1. Point to health score — 12 CRITICAL
2. Point to PG panel — 0.0%, offline badge
3. Point to HTTP panel — timeout, degraded badge
4. Point to Windows panel — Web Booking stopped, API Gateway stopped (red dots)
5. Point to JDBC grid — all databases at 0 (red)

**Key point to land:**  
*"Every signal degraded simultaneously. The question is: what caused it?"*

---

### Scene 5 — Correlation Engine (1:40 – 2:05)

**What to show:** Correlation timeline — 2 active incidents.

**Narration:**

> "The correlation engine has evaluated all nine rules and matched two patterns.
>
> First: `db_unavailable` — PostgreSQL is not responding. Confidence: 91%.
> That's five critical signals correlated in a single poll cycle — connection
> refused, HTTP timeout, all JDBC dropped, two services stopped.
>
> Second: `qmatic_service_stopped` — the cascade. Web Booking and API Gateway
> stopped as a direct consequence of losing the database layer. Confidence: 88%.
>
> Two rules. Two named incidents. One root cause."

**Mouse actions:**
1. Point to correlation timeline — "2 active" badge
2. Scroll through timeline events top to bottom
3. Point to the correlated incidents panel — two red incident cards

**Key point to land:**  
*"The confidence score is not a guess. It's calculated from signal severity,
evidence count, recency, and historical recurrence. 91% means five independent
signals all pointing to the same failure."*

---

### Scene 6 — RCA Artifact (2:05 – 2:25)

**What to show:** Incident card evidence and remediation actions.

**Narration:**

> "Each incident comes with a generated RCA artifact. Evidence is surfaced
> directly in the dashboard — availability unreachable, connection refused,
> HTTP unreachable — and specific remediation steps are provided.
>
> Verify PostgreSQL is running. Check network connectivity. Review PostgreSQL
> logs for crash or OOM events. Check disk space. Configure Windows Service
> Recovery for auto-restart.
>
> The on-call engineer doesn't need to diagnose from scratch. The platform
> has already done the correlation work."

**Mouse actions:**
1. Point to the first incident card — show evidence lines (POSTGRES, HTTP)
2. Point to remediation actions in Vorsa Intelligence panel
3. Point to the RCA file reference (if visible)

---

### Scene 7 — Topology Degraded (2:25 – 2:40)

**What to show:** Service topology panel with failed nodes.

**Narration:**

> "The service topology shows exactly where the failure propagated.
>
> API Gateway — stopped. Orchestra Central — stopped. Web Booking — stopped.
> PostgreSQL running but accepting no connections. All five database nodes:
> zero JDBC connections.
>
> The dependency chain is visible. The failure originated at the PostgreSQL
> layer and cascaded up through the application tier."

**Mouse actions:**
1. Point to topology — failed nodes in red
2. Trace the cascade from PostgreSQL upward
3. Note API Gateway still running — it survived (correct for this scenario)

---

### Scene 8 — Recovery (2:40 – 3:05)

**What to show:** Load healthy state.json — dashboard returns to green.

**For recorded demo:**
```powershell
python control_plane.py --once
# Or load healthy state directly
```
Click **↺ refresh**.

**Narration:**

> "PostgreSQL service has been restarted. Watch the platform track the recovery.
>
> Health score climbing. JDBC connections re-establishing. HTTP responding.
> Services back online.
>
> Back to 100 — HEALTHY. Zero incidents. The full incident lifecycle —
> detection, correlation, RCA, remediation, recovery — in under four minutes."

**Mouse actions:**
1. Click refresh — watch dashboard return to green
2. Point to health score climbing back to 97–100
3. Point to JDBC grid — databases back to normal counts
4. Point to 0 incidents
5. Point to correlation timeline — showing recovery events

---

### Scene 9 — Closing (3:05 – 3:20) — Optional

**What to show:** Brief pan across the healthy dashboard.

**Narration:**

> "Vorsa is not a generic monitoring dashboard. It understands Qmatic —
> the database schema, the service dependencies, the JDBC connection patterns,
> the business hours context.
>
> It detects infrastructure failures, application-layer degradation, and data
> quality anomalies that no generic tool can surface. And it generates
> actionable incident artifacts — automatically — within one 60-second poll cycle."

---

## Narration Timing Guide

| Scene | Duration | Cumulative |
|---|---|---|
| 1 — Healthy environment | 30s | 0:30 |
| 2 — Service topology | 20s | 0:50 |
| 3 — Failure introduced | 20s | 1:10 |
| 4 — Dashboard reacts | 30s | 1:40 |
| 5 — Correlation engine | 25s | 2:05 |
| 6 — RCA artifact | 20s | 2:25 |
| 7 — Topology degraded | 15s | 2:40 |
| 8 — Recovery | 25s | 3:05 |
| 9 — Closing (optional) | 15s | 3:20 |

**Target:** 2:45 – 3:05 without closing scene. 3:05 – 3:20 with closing.

---

## Key Phrases — Use These Exactly

These phrases communicate the right operational identity:

| Moment | Phrase |
|---|---|
| Opening | *"operational intelligence platform built specifically for hosted Qmatic environments"* |
| On confidence score | *"91% — five independent signals, all pointing to the same failure"* |
| On topology | *"the dependency chain is visible"* |
| On RCA | *"the on-call engineer doesn't need to diagnose from scratch"* |
| On recovery | *"the full incident lifecycle — detection, correlation, RCA, remediation, recovery"* |
| Closing | *"detects what no generic tool can surface"* |

---

## Phrases to Avoid

| Avoid | Use instead |
|---|---|
| "the dashboard shows an error" | "the correlation engine matched a pattern" |
| "things broke" | "PostgreSQL service failure" |
| "it caught the problem" | "the platform correlated five signals" |
| "monitoring tool" | "operational intelligence platform" |
| "it fired an alert" | "it generated a correlated incident" |

---

## Alternative Demo Scenarios

If the PostgreSQL outage demo is too intense for the audience, use these alternatives:

### Shorter (90 seconds) — Scenario D: API Degradation
Show healthy → latency spike → `app_layer_issue` rule → infrastructure healthy,
only HTTP degraded → confidence 75% → remediation guidance.
**Best for:** Demonstrating signal isolation and correlation intelligence.

### Business-focused (2 minutes) — Scenario C: Reporting Anomaly
Show healthy infrastructure → reporting anomaly incident → all infra green →
data quality issue only visible to Vorsa → remediation.
**Best for:** Business stakeholders, Qmatic administrators, support leads.

### Technical depth — Scenario E: JVM Memory Pressure
Show multi-poll progression — WARNING at 89% → CRITICAL at 97% → OOM crash
→ cascade → recovery. Highlight 8-minute lead time.
**Best for:** SRE interviews, platform engineering audiences.

---

## Recording Checklist

Before recording:
- [ ] Dashboard at healthy state (health ≥ 95)
- [ ] All panels green
- [ ] Scenario state.json files ready in `dashboard/scenarios/`
- [ ] Terminal split visible (optional — shows log lines for credibility)
- [ ] Microphone tested
- [ ] Recording software tested
- [ ] Browser notifications disabled
- [ ] Taskbar hidden (Windows: auto-hide)

During recording:
- [ ] Speak at measured pace — operational, not excited
- [ ] Mouse movements deliberate — point, pause, move
- [ ] Allow dashboard to fully update before narrating the new state
- [ ] Do not rush the correlation timeline section

After recording:
- [ ] Trim dead air at start and end
- [ ] Add chapter markers at each scene transition (optional)
- [ ] Export at 1920×1080 minimum

---

## Scene Transition Summary

```
HEALTHY (97)
    ↓  [state.json swap / service stop]
CRITICAL (12) — 2 incidents — correlation timeline active
    ↓  [service restart / state.json swap]
HEALTHY (100) — 0 incidents — recovery confirmed
```

Three acts. One complete operational story.

---

| Field | Value |
|---|---|
| **Demo scenario** | Scenario A — PostgreSQL Outage |
| **Target duration** | 2:45 – 3:20 |
| **Status** | stable |
| **Last updated** | 2026-05-16 |
