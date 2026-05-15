"""
patch_control_plane.py
Run from repo root: python patch_control_plane.py
"""

path = "control_plane.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

if "collect_service_connections" in content:
    print("Already patched — nothing to do")
else:
    old = "            queue_activity = qmatic_checks.collect_queue_activity()"
    new = (
        "            svc_snap = qmatic_checks.collect_service_connections()\n"
        "            env_state[\"services\"] = {\n"
        "                \"connections_by_db\": svc_snap.connections_by_db,\n"
        "                \"missing_services\": svc_snap.missing_services,\n"
        "                \"severity\": svc_snap.severity,\n"
        "            }\n"
        "            if svc_snap.missing_services:\n"
        "                logger.warning(\"[%s] Missing JDBC connections: %s\",\n"
        "                               env.name, svc_snap.missing_services)\n"
        "            else:\n"
        "                logger.info(\"[%s] Services: %s\",\n"
        "                            env.name, svc_snap.connections_by_db)\n"
        "            queue_activity = qmatic_checks.collect_queue_activity()"
    )
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done — control_plane.py patched")

print("Run: python control_plane.py --once")
