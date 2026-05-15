"""
patch_health_score.py
Run from repo root: python patch_health_score.py
"""

path = "control_plane.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── 1. Add import ─────────────────────────────────────────────────────────────
old_import = "from correlators.correlator import CorrelationEngine, CorrelatedIncident"
new_import = (
    "from correlators.correlator import CorrelationEngine, CorrelatedIncident\n"
    "from correlators.health_score import calculate_health_score"
)

if old_import in content:
    content = content.replace(old_import, new_import)
    print("Added health_score import")
else:
    print("WARNING: Could not find correlator import")

# ── 2. Replace overall_severity block with real health score ──────────────────
old_severity = '''    # ── 8. Overall severity ───────────────────────────────────────────────
    severities = []
    if pg_snap:
        severities.append(pg_snap.severity)
    if http_snap:
        severities.append(http_snap.overall_severity)
    if activity_result:
        severities.append(activity_result.severity)
    if reporting_result:
        severities.append(reporting_result.severity)
    for inc in incidents:
        severities.append(inc.severity)

    if "critical" in severities:
        env_state["overall_severity"] = "critical"
    elif "warning" in severities:
        env_state["overall_severity"] = "warning"
    else:
        env_state["overall_severity"] = "ok"'''

new_severity = '''    # ── 8. Health score + overall severity ───────────────────────────────────
    health_score, health_label, overall_severity = calculate_health_score(
        incidents=incident_summaries,
        suppressed_warnings=suppressed_summaries,
        pg_snap=pg_snap,
        http_snap=http_snap,
        win_snap=env_state.get("windows"),
    )
    env_state["health_score"] = health_score
    env_state["health_label"] = health_label
    env_state["overall_severity"] = overall_severity
    logger.info("[%s] Health: %d (%s)", env.name, health_score, health_label)'''

if old_severity in content:
    content = content.replace(old_severity, new_severity)
    print("Replaced overall_severity block with health score")
else:
    print("WARNING: Could not find overall_severity block — searching...")
    for i, line in enumerate(content.splitlines(), 1):
        if "Overall severity" in line or "overall_severity" in line:
            print(f"  line {i}: {line.strip()}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("\nDone — run: python control_plane.py --once")
