"""
patch_correlator_dict.py
Run from repo root: python patch_correlator_dict.py
"""

path = "correlators/correlator.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix rule_service_stopped_db_drop — win_snap is a dict not an object
old = "    stopped = [s for s in (win_snap.services or []) if s.get(\"state\") != \"Running\"]"
new = "    stopped = [s for s in (win_snap.get(\"services\") or [] if isinstance(win_snap, dict) else []) if s.get(\"state\") != \"Running\"]"

if old in content:
    content = content.replace(old, new)
    print("Fixed rule_service_stopped_db_drop")
else:
    # Try alternate spacing
    old2 = "    stopped = [s for s in (win_snap.services or []) if s.get('state') != 'Running']"
    if old2 in content:
        content = content.replace(old2, new.replace('"', "'"))
        print("Fixed rule_service_stopped_db_drop (single quotes)")
    else:
        print("Pattern not found — searching for win_snap.services:")
        for i, line in enumerate(content.splitlines(), 1):
            if "win_snap.services" in line:
                print(f"  line {i}: {line}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done — run: python control_plane.py --once")
