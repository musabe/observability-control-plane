# Runbook: Zero Queue Activity During Business Hours

**Incident type:** `zero_activity_business_hours`  
**Severity:** Critical  
**Affects:** Customer-facing queue operations — visits not being created or served

---

## Symptoms

- 0 delivered visits recorded during business hours
- 0 active service points in Qmatic
- Customers may be reporting inability to take a ticket
- Application may be reachable but non-functional

---

## Decision Tree

```
App reachable? (HTTP check)
├── NO  → Application is down → go to Section A
└── YES
    │
    └── DB available?
        ├── NO  → Database is down → go to Section B
        └── YES
            │
            └── Any long-running queries? (>30s)
                ├── YES → DB pressure blocking writes → go to Section C
                └── NO
                    │
                    └── Branches configured and open? → go to Section D
```

---

## Section A — Application Unreachable

1. SSH to application server
2. Check Qmatic service: `systemctl status qmatic-orchestrator`
3. Review application logs: `journalctl -u qmatic-orchestrator --since "30 min ago"`
4. Attempt restart if safe: `systemctl restart qmatic-orchestrator`
5. Verify network: confirm reverse proxy / load balancer is routing correctly

---

## Section B — Database Unavailable

1. SSH to database server
2. Check PostgreSQL: `systemctl status postgresql`
3. Review logs: `journalctl -u postgresql --since "30 min ago"` or `tail -100 /var/log/postgresql/postgresql-*.log`
4. Check disk space: `df -h` — PostgreSQL stops if disk is full
5. Attempt restart only if logs show a clean crash (not corruption)

---

## Section C — DB Pressure Blocking Visit Writes

Follow the [DB Connection Exhaustion runbook](./db-connection-exhaustion.md).

Key check: verify if any query is holding a lock on the `visit` table:

```sql
SELECT pid, mode, granted, left(query, 100)
FROM pg_locks l
JOIN pg_stat_activity a USING (pid)
WHERE relation = 'visit'::regclass;
```

---

## Section D — Qmatic Configuration Issue

1. Log into Qmatic admin console
2. Navigate to **Branches** — verify the branch is set to **Open** for today
3. Navigate to **Service Points** — verify service points are active
4. Check if staff are logged in at counters
5. Check Qmatic licence status (expired licence can silently disable operations)
6. Review Qmatic application logs for permission or configuration errors

---

## Verification

After remediation, verify via the control plane dashboard:
- `delivered_visits_today` increments within 5 minutes
- `active_branches` > 0
- `waiting_visits_now` reflects real customers

---

## Notes

- This incident almost always has a root cause even if the application appears healthy
- Check for recent deployments or configuration changes (last 24h)
- Check if the issue is branch-specific or platform-wide
