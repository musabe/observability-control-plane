"""
patch_phase2_correlation.py
Run from repo root: python patch_phase2_correlation.py

Updates control_plane.py to:
1. Pass win_snap and svc_snap to correlator
2. Handle (active, suppressed) tuple return from correlator
3. Add suppressed warnings to timeline in state.json
4. Include confidence in incident output
"""

path = "control_plane.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── 1. Update correlator import ───────────────────────────────────────────────
old_import = "from correlators.correlator import CorrelationEngine"
new_import = "from correlators.correlator import CorrelationEngine, CorrelatedIncident"

if old_import in content:
    content = content.replace(old_import, new_import)
    print("Updated correlator import")

# ── 2. Update correlate() call to pass win_snap and svc_snap ─────────────────
old_correlate = """    incidents = correlator.correlate(
        env,
        pg_snap=pg_snap,
        http_snap=http_snap,
        activity_result=activity_result,
        reporting_result=reporting_result,
    )"""

new_correlate = """    # Build win_snap and svc_snap dicts for correlator
    _win_for_corr = env_state.get("windows") if env_state.get("windows") else None
    _svc_for_corr = env_state.get("services") if env_state.get("services") else None

    active_incidents, suppressed_warnings = correlator.correlate(
        env,
        pg_snap=pg_snap,
        http_snap=http_snap,
        activity_result=activity_result,
        reporting_result=reporting_result,
        win_snap=_win_for_corr,
        svc_snap=_svc_for_corr,
    )
    incidents = active_incidents"""

if old_correlate in content:
    content = content.replace(old_correlate, new_correlate)
    print("Updated correlate() call")
else:
    print("WARNING: Could not find correlate() call — check manually")

# ── 3. Update RCA generation to include confidence and suppressed warnings ────
old_rca = """    # ── 7. Generate RCA ───────────────────────────────────────────────────────
    incident_summaries = []
    for incident in incidents:
        summary = rca.generate(incident, pg_snap=pg_snap)
        filepath = rca.save_markdown(summary)
        rca.log_alert(summary)
        incident_summaries.append({
            **summary.to_dict(),
            "rca_file": filepath,
        })
        logger.warning("[%s] INCIDENT: %s [%s]",
                       env.name, incident.title, incident.severity.upper())

    env_state["incidents"] = incident_summaries"""

new_rca = """    # ── 7. Generate RCA ───────────────────────────────────────────────────────
    incident_summaries = []
    for incident in active_incidents:
        summary = rca.generate(incident, pg_snap=pg_snap)
        filepath = rca.save_markdown(summary)
        rca.log_alert(summary)
        incident_summaries.append({
            **summary.to_dict(),
            "confidence": incident.confidence,
            "rca_file": filepath,
        })
        logger.warning("[%s] INCIDENT: %s [%s] confidence=%d%%",
                       env.name, incident.title,
                       incident.severity.upper(), incident.confidence)

    # Add suppressed warnings to timeline only
    suppressed_summaries = []
    for inc in suppressed_warnings:
        suppressed_summaries.append({
            "incident_type": inc.incident_type,
            "title": inc.title,
            "severity": inc.severity,
            "confidence": inc.confidence,
            "suppressed": True,
            "correlated_at": inc.correlated_at.isoformat(),
            "evidence": [e.__dict__ for e in inc.evidence],
        })
        logger.info("[%s] SUPPRESSED (conf=%d%%): %s",
                    env.name, inc.confidence, inc.title)

    env_state["incidents"] = incident_summaries
    env_state["suppressed_warnings"] = suppressed_summaries"""

if old_rca in content:
    content = content.replace(old_rca, new_rca)
    print("Updated RCA generation block")
else:
    print("WARNING: Could not find RCA block — check manually")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("\nDone — run: python control_plane.py --once")
