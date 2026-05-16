# Runbook — PostgreSQL Outage

**Applies to:** Vorsa `db_unavailable` incident type  
**Environments:** All Qmatic hosted environments  
**Severity:** SEV-1 / CRITICAL  
**Response time target:** < 5 minutes to first action  

---

## Detection

Vorsa will automatically generate a `db_unavailable` incident when:

- PostgreSQL collector reports `available: false`
- JDBC connections drop to 0 across monitored databases
- HTTP endpoint becomes unreachable simultaneously

**Confidence threshold for SEV-1:** ≥ 80%

---

## Immediate Actions (0–5 minutes)

### Step 1 — Confirm the outage

Check the Vorsa dashboard:
- Health score < 60 (CRITICAL)
- PG pool: 0%
- All JDBC databases: 0 connections
- HTTP: timeout

Do NOT restart services yet — confirm PostgreSQL is actually down first.

### Step 2 — Check PostgreSQL service status

RDP to the Qmatic server and open **Services** (`services.msc`):

```
Look for: PostgreSQL
Expected state when healthy: Running
If stopped: note the "Log On As" account before starting
```

Or via PowerShell:
```powershell
Get-Service -Name "*postgres*" | Select-Object Name, Status, StartType
```

### Step 3 — Check Windows Event Log

Open **Event Viewer → Windows Logs → Application**:

Filter by source: `PostgreSQL`

Look for:
- `FATAL: could not write to file` → disk full
- `FATAL: out of memory` → OOM condition
- `LOG: database system is shut down` → clean shutdown
- `PANIC:` → crash / corruption (escalate immediately)

### Step 4 — Check disk space

```powershell
Get-PSDrive C | Select-Object Used, Free
# Also check Qmatic data drive if separate
```

PostgreSQL data directory: `C:/qmatic/orchestra/system/app/pgsql/data/`

**If disk is > 95% full:** Do NOT restart. Escalate to clear space first.

---

## Recovery Actions (5–15 minutes)

### Step 5 — Start PostgreSQL service

Via Services:
```
Right-click PostgreSQL → Start
```

Or via PowerShell:
```powershell
Start-Service -Name "postgresql*"
```

Wait 30 seconds then verify:
```powershell
Get-Service -Name "*postgres*"
# Expected: Status = Running
```

### Step 6 — Verify Qmatic services recover

Monitor the Vorsa dashboard. Within 90 seconds of PostgreSQL starting:

- JDBC connections should re-establish (`qp_central` first)
- HTTP endpoint should return HTTP 200
- Health score should climb from CRITICAL → DEGRADED → HEALTHY

If Qmatic services do not auto-recover within 3 minutes:

```
Services → Qmatic Platform → Restart
Services → Qmatic Web Booking → Start
Services → Qmatic API Gateway → Start
```

### Step 7 — Confirm full recovery in Vorsa

All of the following must be true before closing the incident:

- [ ] Health score ≥ 90 (HEALTHY)
- [ ] PG pool > 0%
- [ ] All 5 JDBC databases showing connections
- [ ] HTTP: HTTP 200
- [ ] All 3 Qmatic services: Running
- [ ] 0 active incidents in Vorsa

---

## Escalation

### Escalate immediately if:

- PostgreSQL does not start within 2 restart attempts
- Event Log shows `PANIC` or file corruption errors
- Disk space is critically low (< 2GB free)
- JDBC connections do not recover after PostgreSQL is running
- Data directory is missing or inaccessible

### Escalation path:

1. On-call engineer → Senior DBA
2. Senior DBA → Qmatic support (if database corruption suspected)
3. Qmatic support → Qmatic engineering (if schema corruption)

**Qmatic support:** https://support.qmatic.com  
**Reference:** Qmatic Orchestra PostgreSQL administration guide

---

## PostgreSQL Service Auto-Restart Configuration

To prevent future manual intervention, configure Windows Service Recovery:

```
Services → PostgreSQL → Properties → Recovery tab

First failure:   Restart the Service
                 Restart service after: 1 minute

Second failure:  Restart the Service
                 Restart service after: 2 minutes

Third failure:   Restart the Service
                 Restart service after: 5 minutes

Reset fail count after: 1 day
```

---

## Post-Incident

After resolution, update the incident record:

1. Document actual root cause (OOM / disk / manual / crash)
2. Note recovery time and actions taken
3. Submit prevention recommendation to platform team
4. Update Vorsa fingerprint database if new pattern detected

---

## Related Runbooks

- [`runbooks/db-connection-exhaustion.md`](db-connection-exhaustion.md)
- [`runbooks/zero-activity-business-hours.md`](zero-activity-business-hours.md)

---

*Maintained by: Platform Engineering*  
*Last updated: 2026-05-14*
