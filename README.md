# 🔭 Observability Control Plane

> Dockerized observability lab for detecting, correlating, and remediating production incidents across APIs, databases, queues, and background services.

![Language](https://img.shields.io/badge/language-Go%20%2B%20Python-blue?style=flat-square)
![Stack](https://img.shields.io/badge/stack-Prometheus%20%2B%20Grafana-orange?style=flat-square)
![Services](https://img.shields.io/badge/services-4%20Go%20microservices-teal?style=flat-square)
![Incidents](https://img.shields.io/badge/incident%20types-8-red?style=flat-square)
![Status](https://img.shields.io/badge/status-active-brightgreen?style=flat-square)

Part of the **operational engineering portfolio** alongside [connector-support-toolkit](https://github.com/musabe/connector-support-toolkit) — which validates readiness *before* data flows, while this diagnoses incidents *during* runtime.

---

## Overview

A production-like microservices environment with real traffic, real metrics, and a fault injection layer that can simulate the 8 most common production incident types on demand. Designed for:

- **Incident response practice** — trigger a real failure, diagnose it, remediate it
- **SRE portfolio demonstration** — shows full observability lifecycle end-to-end
- **Runbook validation** — prove your runbooks actually work against live failures

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Python Orchestrator                                             │
│  fault_injector.py · detector.py · correlator.py · rca_gen.py  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP fault injection APIs
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                       ▼
┌───────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│  api-gateway  │   │   db-service     │   │   queue-worker       │
│  (Go) :8080   │──▶│   (Go) :8081     │   │   (Go) :8082         │
│               │   │   PostgreSQL     │   │   RabbitMQ consumer  │
└───────┬───────┘   └──────────────────┘   └──────────────────────┘
        │ RabbitMQ                                      ▲
        └──────────────────────────────────────────────┘
        
┌───────────────────┐   ┌────────────────────┐
│  background-job   │   │  Prometheus :9090   │◀─ scrapes all services
│  (Go) :8083       │   │  Grafana :3000      │
│  Redis            │   └────────────────────┘
└───────────────────┘

Backing services: PostgreSQL · Redis · RabbitMQ
Exporters:        postgres-exporter · redis-exporter
```

---

## Quick start

```bash
# 1. Clone and start the full stack
git clone https://github.com/musabe/observability-control-plane
cd observability-control-plane
docker compose up -d

# 2. Verify all services are healthy
python orchestrator/fault_injector.py status

# 3. Open dashboards
open http://localhost:3000   # Grafana (admin/admin)
open http://localhost:9090   # Prometheus
open http://localhost:15672  # RabbitMQ management (guest/guest)
```

---

## Incident types

| # | Incident | Service | Trigger command |
|---|----------|---------|----------------|
| 001 | DB connection pool exhaustion | db-service | `trigger db-exhaustion` |
| 002 | Auth failures | api-gateway | `trigger auth-failures --pct 30` |
| 003 | API latency spike | api-gateway | `trigger api-latency --ms 500` |
| 004 | Webhook delivery retries | queue-worker | `trigger webhook-retries` |
| 005 | Queue consumer lag | queue-worker | `trigger queue-lag --ms 3000` |
| 006 | Memory pressure | background-job | `trigger memory-pressure` |
| 007 | Broken TLS | api-gateway | `trigger broken-tls` |
| 008 | Rate limiting | api-gateway | `trigger rate-limiting --rps 5` |

### Running an incident

```bash
# Install orchestrator dependencies
pip install -r orchestrator/requirements.txt

# Trigger an incident
python orchestrator/fault_injector.py trigger db-exhaustion

# Watch metrics in Grafana or Prometheus
# ...diagnose and remediate using the runbook...

# Reset all faults
python orchestrator/fault_injector.py reset all

# Check status
python orchestrator/fault_injector.py status
```

---

## Service endpoints

| Service | Port | Health | Metrics | Fault control |
|---------|------|--------|---------|---------------|
| api-gateway | 8080 | `/health` | `/metrics` | `/fault/*` |
| db-service | 8081 | `/health` | `/metrics` | `/fault/*` |
| queue-worker | 8082 | `/health` | `/metrics` | `/fault/*` |
| background-job | 8083 | `/health` | `/metrics` | `/fault/*` |
| Prometheus | 9090 | — | — | — |
| Grafana | 3000 | — | — | — |
| RabbitMQ UI | 15672 | — | — | — |

---

## SLOs

Defined in `slo/` — each with Prometheus queries, burn rate thresholds, and runbook links:

| SLO | Target | Error budget (30d) |
|-----|--------|--------------------|
| API p99 latency < 500ms | 99.9% | 43.8 minutes |
| API availability | 99.95% | 21.9 minutes |
| DB query success rate | 99.95% | 21.9 minutes |
| Queue processing throughput | 99.5% | 3.6 hours |

See [`slo/availability-targets.md`](slo/availability-targets.md) for full policy.

---

## Incidents

Captured evidence from real fault injection runs stored in `incidents/`:

```
incidents/
├── incident-001-db-exhaustion/
│   ├── timeline.md      ← minute-by-minute event log
│   ├── metrics.png      ← Grafana screenshot at peak
│   ├── logs.txt         ← service logs during incident
│   ├── rca.md           ← root cause analysis
│   └── remediation.md   ← what fixed it
```

---

## Runbooks

Operational runbooks in `runbooks/` covering detection, investigation, and remediation for each incident type. Each runbook includes:
- Prometheus queries to run during diagnosis
- Step-by-step remediation commands
- Escalation criteria

---

## Project structure

```
observability-control-plane/
├── services/
│   ├── api-gateway/       ← REST gateway, auth, rate limiting, TLS
│   ├── db-service/        ← PostgreSQL CRUD, connection pool
│   ├── queue-worker/      ← RabbitMQ consumer, webhook delivery
│   └── background-job/    ← Scheduled jobs, Redis caching
├── orchestrator/
│   ├── fault_injector.py  ← Trigger/reset all 8 incident types
│   ├── detector.py        ← Poll Prometheus, detect anomalies
│   ├── correlator.py      ← Link signals across services
│   └── rca_generator.py   ← Auto-generate RCA docs
├── incidents/             ← Captured incident evidence
├── slo/                   ← SLO definitions + error budget policy
├── runbooks/              ← Operational runbooks
├── dashboards/            ← Grafana dashboard JSON
├── config/
│   ├── prometheus.yml
│   └── alerting-rules.yml
└── docker-compose.yml
```

---

## Ecosystem

This project is part of a connected operational engineering portfolio:

| Project | Role |
|---------|------|
| [connector-support-toolkit](https://github.com/musabe/connector-support-toolkit) | Pre-flight readiness validation for data connectors |
| **observability-control-plane** | Runtime incident detection, diagnosis, and remediation |

---

## Author

**Mustapha Abella**
Senior Technical Support Engineer
Focused on API-driven SaaS, data integration, and developer-facing support

[github.com/musabe](https://github.com/musabe)
