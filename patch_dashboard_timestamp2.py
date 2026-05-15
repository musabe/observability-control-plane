"""
patch_dashboard_timestamp2.py
Run from repo root: python patch_dashboard_timestamp2.py
"""

path = "dashboard/index.html"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = "  const normalized = iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z');"
new = "  const normalized = iso.replace(' ', 'T').replace('+00:00', 'Z');"

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done")
else:
    print("Pattern not found — current fmtTime:")
    start = content.find("function fmtTime")
    print(content[start:start+300])
