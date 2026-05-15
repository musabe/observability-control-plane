# Runbook: PostgreSQL Connection Pool Exhaustion

**Incident type:** `db_saturation_api_cascade` / `db_unavailable`  
**Severity:** Warning (>75%) → Critical (>90%)  
**Affects:** All Qmatic operations — visit recording, reporting, API responses

---

## Symptoms

- `connection_pct` > 75% in control plane dashboard
- API latency increasing (endpoints slow to respond)
- Qmatic application may display database errors
- Visits not being recorded despite system appearing online
- `pg_stat_activity` shows many idle-in-transaction connections

---

## Immediate Assessment (< 5 min)

```sql
-- 1. Connection count by state
SELECT state, count(*) 
FROM pg_stat_activity 
WHERE datname = 'qmatic'
GROUP BY state 
ORDER BY count DESC;

-- 2. Longest-running queries
SELECT pid, now() - query_start AS duration, state, left(query, 100)
FROM pg_stat_activity
WHERE datname = 'qmatic' AND state != 'idle'
ORDER BY query_start
LIMIT 10;

-- 3. Blocking queries
SELECT blocked.pid, blocking.pid AS blocking_pid, left(blocked.query, 100)
FROM pg_stat_activity blocked
JOIN pg_stat_activity blocking 
  ON blocking.pid = ANY(pg_blocking_pids(blocked.pid));
```

---

## Remediation Steps

### Step 1 — Identify the root cause

**A — Long-running reporting/statistics job:**
```sql
SELECT id, job_type, started_at, status
FROM scheduled_job
WHERE status = 'RUNNING' AND started_at < NOW() - INTERVAL '10 minutes'
ORDER BY started_at;
```
If found → proceed to Step 2A.

**B — Connection leak (idle connections accumulating):**
```sql
SELECT count(*), client_addr
FROM pg_stat_activity
WHERE state = 'idle' AND datname = 'qmatic'
GROUP BY client_addr
ORDER BY count DESC;
```
If a single host has many idle connections → application connection pool misconfiguration.

**C — Blocking query:**  
If blocking queries found in assessment → proceed to Step 2B.

---

### Step 2A — Terminate stuck reporting job

```sql
-- Identify the PID
SELECT pid, query_start, left(query, 200) 
FROM pg_stat_activity 
WHERE datname = 'qmatic' AND state NOT IN ('idle') 
ORDER BY query_start;

-- Terminate gracefully (sends cancel signal)
SELECT pg_cancel_backend(<pid>);

-- If cancel doesn't work after 30s, terminate
SELECT pg_terminate_backend(<pid>);
```

Then reset the job in Qmatic:
```sql
UPDATE scheduled_job SET status = 'PENDING', started_at = NULL
WHERE id = <job_id> AND status = 'RUNNING';
```

---

### Step 2B — Terminate blocking query

```sql
-- Cancel the blocking query first
SELECT pg_cancel_backend(<blocking_pid>);
```

Monitor connection count after — should drop within 60 seconds.

---

### Step 3 — Verify recovery

```sql
SELECT count(*), 
       (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max
FROM pg_stat_activity 
WHERE datname = 'qmatic';
```

Connection count should return to < 50% within 2–3 minutes of clearing the blocker.

---

## Prevention

- Configure `pgbouncer` or application-level connection pooling
- Set `statement_timeout` on the database to 300s for reporting users
- Schedule heavy reporting jobs outside business hours
- Monitor `pg_stat_activity` with alerting on connections > 70%

---

## Escalation

Escalate to P1 if:
- Connections at 100% and `pg_terminate_backend` fails
- Database process is consuming > 90% CPU for > 10 minutes
- PostgreSQL service cannot be reached at all

Contact: DBA on-call → Infrastructure team
