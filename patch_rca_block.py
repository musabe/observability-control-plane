"""
patch_rca_block.py
Run from repo root: python patch_rca_block.py
"""

path = "control_plane.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the RCA section (line 234 = index 233)
# Replace lines 234-247 (indices 233-246) with new block
new_block = [
    "    incident_summaries = []\n",
    "    for incident in active_incidents:\n",
    "        summary = rca.generate(incident, pg_snap=pg_snap)\n",
    "        filepath = rca.save_markdown(summary)\n",
    "        rca.log_alert(summary)\n",
    "        incident_summaries.append({\n",
    "            **summary.to_dict(),\n",
    '            "confidence": incident.confidence,\n',
    '            "rca_file": filepath,\n',
    "        })\n",
    "        logger.warning(\n",
    '            "[%s] INCIDENT: %s [%s] confidence=%d%%",\n',
    "            env.name, incident.title,\n",
    "            incident.severity.upper(), incident.confidence)\n",
    "\n",
    "    suppressed_summaries = []\n",
    "    for inc in suppressed_warnings:\n",
    "        suppressed_summaries.append({\n",
    '            "incident_type": inc.incident_type,\n',
    '            "title": inc.title,\n',
    '            "severity": inc.severity,\n',
    '            "confidence": inc.confidence,\n',
    '            "suppressed": True,\n',
    '            "correlated_at": inc.correlated_at.isoformat(),\n',
    "        })\n",
    "        logger.info(\n",
    '            "[%s] SUPPRESSED (conf=%d%%): %s",\n',
    "            env.name, inc.confidence, inc.title)\n",
    "\n",
    '    env_state["incidents"] = incident_summaries\n',
    '    env_state["suppressed_warnings"] = suppressed_summaries\n',
]

# Replace from index 234 (line 235) to index 246 (line 247 inclusive)
new_lines = lines[:234] + new_block + lines[247:]

with open(path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Done — run: python control_plane.py --once")
