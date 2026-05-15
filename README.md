# observability-control-plane

Operational intelligence and reliability platform for hosted Qmatic environments.

Detects operational degradation before customers report it. Correlates signals across
PostgreSQL health, HTTP availability, and Qmatic queue activity. Generates RCA-style
incident summaries with actionable remediation steps.

---

## Architecture

```
observability-control-plane/
│
├── control_plane.py                  ← main poll loop
│
├── config/
│   ├── environments.yaml             ← environment definitions (YAML)
│   └── loader.py                     ← config loader + secret injection
│
├── collectors/
│   ├── postgres_collector.py         ← pg_stat_* system view collector
│   └── http_collector.py             ← HTTP latency + reachability checks
│
├── detectors/                        ← (generic detector base, future use)
│
├── correlators/
│   └── correlator.py                 ← multi-signal correlation engine
│
├── rca/
│   └── rca_generator.py              ← structured incident + markdown RCA output
│
├── integrations/
│   └── qmatic/
│       ├── qmatic_postgres_checks.py ← Qmatic application table queries
│       ├── qmatic_activity_checks.py ← zero activity, stale windows, drops
│       └── qmatic_reporting_checks.py← duplicate visits, carryover, anomalies
│
├── runbooks/
│   ├── db-connection-exhaustion.md
│   └── zero-activity-business-hours.md
│
├── incidents/
│   └── templates/
│       └── sample-rca-critical.md    ← example generated RCA
│
├── dashboards/
│   └── state.json                    ← written by control_plane.py each cycle
│
├── requirements.txt
└── README.md
```

---

## Design principles

- **Domain-aware**: Qmatic is a first-class integration, not a generic target
- **Read-only first**: all database access uses SELECT only, read-only user
- **Modular**: collectors, detectors, correlators are independently testable
- **Decoupled**: the generic platform architecture is not tightly coupled to Qmatic
- **Operational**: outputs are engineering-readable, not customer-facing
- **Minimal dependencies**: psycopg2, httpx, pyyaml — that's it

---

## Quick start

```bash
pip install -r requirements.txt

# Set DB passwords as environment variables
export OBS_DB_PASSWORD_CXM_CLIENT_ALPHA=yourpassword
export OBS_DB_PASSWORD_CXM_CLIENT_BETA=yourpassword

# Single poll cycle (useful for testing)
python control_plane.py --once

# Continuous polling (60s interval)
python control_plane.py
```

---

## Configuration

Environments are defined in `config/environments.yaml`.

Database passwords are **never** stored in YAML. Set them as environment variables:
```
OBS_DB_PASSWORD_{ENV_NAME_UPPER_SNAKE}
```

Example: environment named `cxm-client-alpha` → `OBS_DB_PASSWORD_CXM_CLIENT_ALPHA`

---

## Correlation rules

The correlator detects compound failure patterns:

| Rule | Signals | Severity |
|------|---------|----------|
| `db_saturation_api_cascade` | PG connections > 75% + HTTP latency elevated | warning/critical |
| `zero_activity_business_hours` | Zero delivered visits during business hours | critical |
| `reporting_anomaly_with_db_pressure` | Duplicate visit IDs + long-running queries | warning |
| `db_unavailable` | PostgreSQL unreachable | critical |

Add new rules by defining a function decorated with `@correlation_rule` in `correlators/correlator.py`.

---

## Output

Each poll cycle writes:
- `dashboard/state.json` — current state for all environments
- `incidents/<timestamp>_<env>_<type>.md` — RCA markdown per incident
- `logs/alerts.jsonl` — JSONL log of all alerts

---

## Database permissions

The read-only database user needs:

```sql
-- System views (generic postgres collector)
GRANT pg_read_all_stats TO readonly_user;
GRANT pg_monitor TO readonly_user;

-- Qmatic application tables (qmatic integration)
GRANT SELECT ON visit TO readonly_user;
GRANT SELECT ON scheduled_job TO readonly_user;
GRANT SELECT ON branch TO readonly_user;
GRANT SELECT ON service_point TO readonly_user;
```

---

## Adding a new environment

1. Add an entry to `config/environments.yaml`
2. Set the password environment variable
3. Restart `control_plane.py`

No code changes required.

---

## Future phases

**Phase 2 — Alerting integration**
- PagerDuty / OpsGenie webhook on critical incidents
- Slack notification on warning → critical transitions
- Email digest for daily operational summary

**Phase 3 — Historical trending**
- SQLite or PostgreSQL backend for control plane state
- 7-day visit volume trending per environment
- Connection pool utilisation heatmap

**Phase 4 — AI-assisted RCA**
- Pass correlated incident + evidence to Claude API
- Generate natural-language RCA narrative with confidence level
- Suggest likely root cause from historical incident patterns

**Phase 5 — Self-service dashboard**
- Serve `dashboard/state.json` via a lightweight FastAPI endpoint
- Browser-based operational dashboard (real data, not mock)
- Per-environment drill-down with historical incident list

---

## Related

- `connector-support-toolkit` — validates PostgreSQL, Redis, RabbitMQ configuration
  before deployment (runs before this platform takes over for runtime monitoring)
