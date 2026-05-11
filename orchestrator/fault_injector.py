#!/usr/bin/env python3
"""
Fault injector — trigger and reset all 8 incident types via the Go service APIs.

Usage:
    python orchestrator/fault_injector.py trigger db-exhaustion
    python orchestrator/fault_injector.py trigger api-latency --ms 500
    python orchestrator/fault_injector.py trigger auth-failures --pct 30
    python orchestrator/fault_injector.py trigger queue-lag --ms 3000
    python orchestrator/fault_injector.py trigger webhook-retries
    python orchestrator/fault_injector.py trigger memory-pressure
    python orchestrator/fault_injector.py trigger broken-tls
    python orchestrator/fault_injector.py trigger rate-limiting --rps 5
    python orchestrator/fault_injector.py reset all
    python orchestrator/fault_injector.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests

# ── Service base URLs ─────────────────────────────────────────────────────────

SERVICES = {
    "api-gateway":    "http://localhost:8080",
    "db-service":     "http://localhost:8081",
    "queue-worker":   "http://localhost:8082",
    "background-job": "http://localhost:8083",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post(url: str, params: dict | None = None) -> dict:
    try:
        resp = requests.post(url, params=params, timeout=5)
        return resp.json()
    except requests.RequestException as exc:
        return {"error": str(exc)}


def _get(url: str) -> dict:
    try:
        resp = requests.get(url, timeout=5)
        return resp.json()
    except requests.RequestException as exc:
        return {"error": str(exc)}


def _log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    colours = {"INFO": "\033[36m", "WARN": "\033[33m", "OK": "\033[32m", "ERR": "\033[31m"}
    reset = "\033[0m"
    colour = colours.get(level, "")
    print(f"[{ts}] {colour}{level:4}{reset}  {msg}")


def _print_result(incident: str, result: dict) -> None:
    if "error" in result:
        _log(f"{incident}: {result['error']}", "ERR")
    else:
        _log(f"{incident}: {json.dumps(result)}", "OK")


# ── Incident triggers ─────────────────────────────────────────────────────────

def trigger_db_exhaustion(args: argparse.Namespace) -> None:
    _log("Triggering DB connection pool exhaustion...")
    result = _post(f"{SERVICES['db-service']}/fault/exhaust", {"enable": "true"})
    _print_result("db-exhaustion", result)
    _log("Pool exhaustion active — watch Prometheus: db_service_pool_acquired_connections", "WARN")
    _log("Reset with: python fault_injector.py reset db-exhaustion")


def trigger_api_latency(args: argparse.Namespace) -> None:
    ms = getattr(args, "ms", 500)
    _log(f"Injecting {ms}ms latency into all API gateway requests...")
    result = _post(f"{SERVICES['api-gateway']}/fault/latency", {"ms": ms})
    _print_result("api-latency", result)
    _log(f"Latency active — watch: api_gateway_request_duration_seconds p99", "WARN")


def trigger_auth_failures(args: argparse.Namespace) -> None:
    pct = getattr(args, "pct", 25)
    _log(f"Injecting {pct}% auth failure rate...")
    result = _post(f"{SERVICES['api-gateway']}/fault/auth", {"pct": pct})
    _print_result("auth-failures", result)
    _log(f"Auth failures active — watch: api_gateway_auth_failures_total", "WARN")


def trigger_queue_lag(args: argparse.Namespace) -> None:
    ms = getattr(args, "ms", 3000)
    _log(f"Injecting {ms}ms processing lag into queue worker...")
    result = _post(f"{SERVICES['queue-worker']}/fault/lag", {"ms": ms})
    _print_result("queue-lag", result)
    _log("Queue lag active — watch: queue_worker_queue_depth", "WARN")


def trigger_webhook_retries(args: argparse.Namespace) -> None:
    _log("Forcing all webhook deliveries to fail (will trigger retries)...")
    result = _post(f"{SERVICES['queue-worker']}/fault/webhook", {"fail": "true"})
    _print_result("webhook-retries", result)
    _log("Webhook failures active — watch: queue_worker_webhook_deliveries_total", "WARN")


def trigger_memory_pressure(args: argparse.Namespace) -> None:
    _log("Allocating ~256MB memory ballast in background-job service...")
    result = _post(f"{SERVICES['background-job']}/fault/memory", {"enable": "true"})
    _print_result("memory-pressure", result)
    _log("Memory pressure active — watch: background_job_memory_bytes", "WARN")


def trigger_broken_tls(args: argparse.Namespace) -> None:
    _log("Signalling broken TLS state in api-gateway...")
    result = _post(f"{SERVICES['api-gateway']}/fault/tls", {"broken": "true"})
    _print_result("broken-tls", result)
    _log("TLS fault active — check api-gateway logs for TLS warnings", "WARN")


def trigger_rate_limiting(args: argparse.Namespace) -> None:
    rps = getattr(args, "rps", 5)
    _log(f"Enabling rate limiting at {rps} requests/sec...")
    result = _post(f"{SERVICES['api-gateway']}/fault/rate-limit", {"rps": rps})
    _print_result("rate-limiting", result)
    _log(f"Rate limiting active at {rps} rps — watch: api_gateway_rate_limited_total", "WARN")


# ── Reset ─────────────────────────────────────────────────────────────────────

RESET_TARGETS = {
    "db-exhaustion":   (SERVICES["db-service"],     "/fault/reset"),
    "api-latency":     (SERVICES["api-gateway"],    "/fault/reset"),
    "auth-failures":   (SERVICES["api-gateway"],    "/fault/reset"),
    "rate-limiting":   (SERVICES["api-gateway"],    "/fault/reset"),
    "broken-tls":      (SERVICES["api-gateway"],    "/fault/reset"),
    "queue-lag":       (SERVICES["queue-worker"],   "/fault/reset"),
    "webhook-retries": (SERVICES["queue-worker"],   "/fault/reset"),
    "memory-pressure": (SERVICES["background-job"], "/fault/reset"),
}


def reset_incident(target: str) -> None:
    if target == "all":
        seen = set()
        for incident, (base, path) in RESET_TARGETS.items():
            key = base + path
            if key not in seen:
                seen.add(key)
                result = _post(f"{base}{path}")
                _log(f"Reset {base}: {result}", "OK")
    elif target in RESET_TARGETS:
        base, path = RESET_TARGETS[target]
        result = _post(f"{base}{path}")
        _log(f"Reset {target}: {result}", "OK")
    else:
        _log(f"Unknown reset target: {target}", "ERR")
        sys.exit(1)


# ── Status ────────────────────────────────────────────────────────────────────

def show_status() -> None:
    _log("Checking service health and active faults...\n")
    for name, base in SERVICES.items():
        health = _get(f"{base}/health")
        status = "✔" if "error" not in health else "✘"
        print(f"  {status}  {name:20} {base}")
        if "error" in health:
            print(f"       Error: {health['error']}")

    print()
    _log("API gateway fault state:")
    state = _get(f"{SERVICES['api-gateway']}/api/v1/status")
    for k, v in state.items():
        indicator = " ⚠" if v and v != 0 and v is not False else ""
        print(f"  {k:30} {v}{indicator}")


# ── Dispatch ──────────────────────────────────────────────────────────────────

TRIGGERS = {
    "db-exhaustion":   trigger_db_exhaustion,
    "api-latency":     trigger_api_latency,
    "auth-failures":   trigger_auth_failures,
    "queue-lag":       trigger_queue_lag,
    "webhook-retries": trigger_webhook_retries,
    "memory-pressure": trigger_memory_pressure,
    "broken-tls":      trigger_broken_tls,
    "rate-limiting":   trigger_rate_limiting,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fault injector for observability-control-plane",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # trigger
    t = sub.add_parser("trigger", help="Trigger an incident type")
    t.add_argument("incident", choices=list(TRIGGERS), help="Incident type to trigger")
    t.add_argument("--ms",  type=int, default=500, help="Latency/lag in milliseconds")
    t.add_argument("--pct", type=int, default=25,  help="Failure percentage (0-100)")
    t.add_argument("--rps", type=int, default=5,   help="Rate limit in requests/sec")

    # reset
    r = sub.add_parser("reset", help="Reset faults")
    r.add_argument("target", choices=list(RESET_TARGETS) + ["all"])

    # status
    sub.add_parser("status", help="Show service health and active faults")

    args = parser.parse_args()

    if args.command == "trigger":
        _log(f"=== Triggering: {args.incident} ===")
        TRIGGERS[args.incident](args)
    elif args.command == "reset":
        _log(f"=== Resetting: {args.target} ===")
        reset_incident(args.target)
    elif args.command == "status":
        show_status()


if __name__ == "__main__":
    main()
