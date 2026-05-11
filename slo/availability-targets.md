# Availability targets

## Service-level objectives

| Service | SLO | Error budget (30d) | Measurement |
|---|---|---|---|
| API gateway — p99 latency | 99.9% requests < 500ms | 43.8 minutes | Prometheus histogram |
| API gateway — availability | 99.95% success rate | 21.9 minutes | HTTP 2xx / total |
| DB service — availability | 99.95% query success | 21.9 minutes | Query success rate |
| Queue processing — throughput | 99.5% messages processed | 3.6 hours | Consumer ack rate |
| Webhook delivery | 99% delivery success | 7.2 hours | Delivery success rate |
| Background jobs | 99% job success | 7.2 hours | Job completion rate |

## Error budget policy

**Fast burn (1h window, 14.4x burn rate)**
- Consumes 2% of monthly budget in 1 hour
- Action: page on-call immediately, open P1 incident

**Slow burn (6h window, 6x burn rate)**
- Consumes 5% of monthly budget in 6 hours
- Action: create P2 ticket, investigate within 4 hours

**Budget exhausted**
- Freeze all non-critical deployments
- Mandatory post-mortem before resuming releases
- Review SLO targets with stakeholders

## Incident severity mapping

| Condition | Severity | Response time |
|---|---|---|
| SLO breach + fast burn | P1 — Critical | 15 minutes |
| SLO breach + slow burn | P2 — High | 4 hours |
| Error budget < 20% remaining | P3 — Medium | Next business day |
| Alert firing but SLO intact | P4 — Low | Weekly review |

## Links

- Prometheus alerting rules: `config/alerting-rules.yml`
- SLO definitions: `slo/*.yaml`
- Runbooks: `runbooks/`
- Incident records: `incidents/`
