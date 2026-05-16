---
title: Vorsa Documentation
category: readme
status: stable
owner: vorsa
last_updated: 2026-05-16
---

# Vorsa — Documentation

> Operational intelligence and incident correlation platform for enterprise Qmatic environments.

---

## Documentation Structure

```
docs/
├── architecture/
│   └── overview.md                  Platform architecture — all components
│
├── scenarios/
│   ├── scenario-a-postgres-outage.md
│   ├── scenario-b-jdbc-saturation.md
│   ├── scenario-c-reporting-anomaly.md
│   ├── scenario-d-api-degradation.md
│   └── scenario-e-jvm-memory-pressure.md
│
├── templates/
│   ├── architecture-template.md
│   ├── incident-template.md
│   ├── runbook-template.md
│   ├── scenario-template.md
│   ├── service-template.md
│   └── readme-template.md
│
└── standards/
    ├── markdown-style-guide.md
    ├── terminology.md
    └── visual-language.md
```

---

## Architecture Documentation

| Document | Description |
|---|---|
| [`architecture/overview.md`](architecture/overview.md) | Complete platform architecture — 12 sections covering all components, flows, and models |

---

## Incident Scenarios

Five operational scenarios demonstrating the platform's detection and correlation capabilities:

| Scenario | Incident Type | Severity | Health | Key Capability |
|---|---|---|---|---|
| [A — PostgreSQL Outage](scenarios/scenario-a-postgres-outage.md) | `db_unavailable` | SEV-1 | 12 | Full cascade detection, 2 correlated incidents |
| [B — JDBC Saturation](scenarios/scenario-b-jdbc-saturation.md) | `db_saturation_api_cascade` | SEV-2 | 58 | Gradual pressure, confidence downgrade |
| [C — Reporting Anomaly](scenarios/scenario-c-reporting-anomaly.md) | `reporting_anomaly` | SEV-2 | 72 | Data quality — infra fully healthy |
| [D — API Degradation](scenarios/scenario-d-api-degradation.md) | `app_layer_issue` | SEV-2 | 75 | App-layer isolation, GC hypothesis |
| [E — JVM Memory Pressure](scenarios/scenario-e-jvm-memory-pressure.md) | `memory_pressure_api_cascade` | SEV-1 | 18 | Multi-poll progression, 8-min lead time |

---

## Standards

| Document | Description |
|---|---|
| [`standards/markdown-style-guide.md`](standards/markdown-style-guide.md) | Document structure, heading hierarchy, callouts, code blocks |
| [`standards/terminology.md`](standards/terminology.md) | Canonical operational vocabulary |
| [`standards/visual-language.md`](standards/visual-language.md) | Diagrams, tables, topology conventions |

---

## Templates

| Template | Use for |
|---|---|
| [`templates/architecture-template.md`](templates/architecture-template.md) | Component and collector documentation |
| [`templates/incident-template.md`](templates/incident-template.md) | Incident records and RCA artifacts |
| [`templates/runbook-template.md`](templates/runbook-template.md) | Operational runbooks |
| [`templates/scenario-template.md`](templates/scenario-template.md) | Incident scenario documentation |
| [`templates/service-template.md`](templates/service-template.md) | Qmatic service reference pages |
| [`templates/readme-template.md`](templates/readme-template.md) | Repository README files |

---

## Using the Templates

1. Copy the relevant template to the target location
2. Replace all `[placeholders]` with operational content
3. Remove unused sections
4. Update frontmatter (`title`, `last_updated`)
5. Verify against the [Markdown Style Guide](standards/markdown-style-guide.md)
6. Verify terminology against [Terminology Standard](standards/terminology.md)

---

| Field | Value |
|---|---|
| **Platform** | Vorsa Observability Control Plane v2.0 |
| **Status** | stable |
| **Last updated** | 2026-05-16 |
