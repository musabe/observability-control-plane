# Runbook: Queue lag / consumer backlog

**Incident type:** Queue lag
**Severity:** P2 — High
**SLO impact:** Queue processing throughput SLO

---

## Symptoms

- `QueueLagHigh` or `ConsumerPaused` alert firing
- `queue_worker_queue_depth > 100`
- Events not being processed, order confirmations delayed
- Webhook deliveries backing up

## Immediate actions (< 5 minutes)

1. **Check queue state**
   ```bash
   curl http://localhost:8082/health
   # Check queue_depth and processed_total
   ```

2. **Check RabbitMQ management UI**
   - Open http://localhost:15672 (guest/guest)
   - Check the `orders` queue message count and delivery rate

3. **Reset fault injection if active**
   ```bash
   curl -X POST http://localhost:8082/fault/reset
   ```

4. **Check consumer metrics**
   ```promql
   queue_worker_consumer_paused
   queue_worker_fault_lag_ms
   rate(queue_worker_messages_processed_total[5m])
   ```

## Root cause investigation

- Is the consumer paused (fault injection)?
- Is processing lag injected?
- Is the downstream webhook failing, causing retries?
- Is the DB service slow, causing message processing to block?

## Remediation

**Immediate:** Reset any active faults
**If consumer is healthy but slow:** Scale queue-worker horizontally
**If webhook is failing:** Check target URL, disable webhook delivery temporarily
**If DB is blocking:** Follow `db-exhaustion.md`

## Escalation

- Queue depth > 1000 for > 10 minutes: P1 escalation
- Messages older than 1 hour: data loss risk, escalate immediately
