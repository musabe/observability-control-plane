"""
patch_runps.py
Run from repo root: python patch_runps.py
"""

path = "collectors/windows_collector.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '["powershell", "-NonInteractive", "-NoProfile", "-Command", script]'
new = '["powershell", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue; " + script]'

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done")
else:
    print("Pattern not found — checking current _run_ps:")
    start = content.find("def _run_ps")
    print(content[start:start+300])
