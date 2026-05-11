# Runbook: API latency spike

**Incident type:** API latency
**Severity:** P2 — High (P1 if p99 > 2s)
**SLO impact:** API gateway p99 latency SLO breach

---

## Symptoms

- `HighAPILatency` alert firing
- `histogram_quantile(0.99, ...) > 0.5` seconds
- Users reporting slow responses
- Downstream services timing out

## Immediate actions (< 5 minutes)

1. **Check current latency percentiles**
   ```promql
   histogram_quantile(0.50, rate(api_gateway_request_duration_seconds_bucket[5m]))
   histogram_quantile(0.95, rate(api_gateway_request_duration_seconds_bucket[5m]))
   histogram_quantile(0.99, rate(api_gateway_request_duration_seconds_bucket[5m]))
   ```

2. **Check if fault injection is active**
   ```bash
   curl http://localhost:8080/api/v1/status
   # Look for fault_latency_ms > 0
   ```

3. **Reset fault injection if active**
   ```bash
   curl -X POST http://localhost:8080/fault/reset
   ```

4. **Check which paths are slowest**
   ```promql
   topk(5, histogram_quantile(0.99,
     rate(api_gateway_request_duration_seconds_bucket[5m])
   ) by (path))
   ```

## Root cause investigation

- Is the latency uniform across all paths or specific to one route?
- Is the DB service responding slowly? Check `db_service_query_duration_seconds`
- Is RabbitMQ backing up? Check `queue_worker_queue_depth`
- Is there a downstream dependency timeout?

## Remediation

**If DB is slow:** Follow `db-exhaustion.md` runbook
**If queue is backing up:** Follow `queue-lag.md` runbook
**If it's a code path issue:** Roll back the last deployment

## Escalation

- p99 > 1s for > 5 minutes: escalate to P1
- p99 > 2s: page on-call, consider traffic shedding
