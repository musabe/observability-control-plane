"""
patch_dashboard_timestamp.py
Run from repo root: python patch_dashboard_timestamp.py
"""

path = "dashboard/index.html"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));"""

new = """function fmtTime(iso) {
  if (!iso) return '—';
  const normalized = iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z');
  const d = new Date(normalized);"""

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done — timestamp fix applied")
else:
    print("Pattern not found — printing current fmtTime function:")
    start = content.find("function fmtTime")
    print(content[start:start+200])
