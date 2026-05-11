# Runbook: Database connection pool exhaustion

**Incident type:** DB exhaustion
**Severity:** P1 — Critical
**SLO impact:** DB service availability, API gateway degradation

---

## Symptoms

- `DBPoolExhaustion` alert firing
- `db_service_pool_acquired_connections / total > 0.9`
- API requests returning 500 with "connection pool exhausted"
- Queue worker failing to process events (downstream of DB)

## Immediate actions (< 5 minutes)

1. **Confirm the alert is real**
   ```bash
   curl http://localhost:8081/health
   # Look for pool stats in response
   ```

2. **Check current pool state via Prometheus**
   ```promql
   db_service_pool_acquired_connections
   db_service_pool_idle_connections
   db_service_pool_total_connections
   ```

3. **Identify long-running queries holding connections**
   ```sql
   SELECT pid, now() - query_start AS duration, query, state
   FROM pg_stat_activity
   WHERE state = 'active'
   ORDER BY duration DESC
   LIMIT 10;
   ```

4. **If fault injection is active, reset it**
   ```bash
   curl -X POST http://localhost:8081/fault/reset
   ```

## Root cause investigation (< 30 minutes)

- Check for connection leaks: queries that started but never committed
- Review `pg_stat_activity` for idle-in-transaction sessions
- Check if pool `max_conns` is undersized for current load
- Look for missing `defer conn.Close()` in application code

## Remediation

**Short-term (immediate relief):**
```sql
-- Terminate idle connections older than 10 minutes
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
  AND query_start < NOW() - INTERVAL '10 minutes';
```

**Medium-term:**
- Increase pool `max_conns` in db-service config
- Add connection timeout to prevent indefinite holds
- Implement connection health checks

**Long-term:**
- Add PgBouncer as a connection pooler
- Review application connection lifecycle
- Add pool utilisation to capacity planning

## Escalation

- If queries cannot be terminated: restart db-service container
- If PostgreSQL itself is unresponsive: escalate to DBA on-call
- If data loss is suspected: escalate to P0

## Related alerts

- `SlowQueries` — often precedes exhaustion
- `DBErrors` — follows exhaustion if not resolved
- `HighErrorRate` on api-gateway — downstream impact
