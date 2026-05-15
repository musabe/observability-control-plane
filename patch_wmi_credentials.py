"""
patch_wmi_credentials.py
Run from repo root: python patch_wmi_credentials.py
Replaces ConvertTo-SecureString approach with System.Net.NetworkCredential
which works without the PowerShell.Security module.
"""

path = "collectors/windows_collector.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── New credential block that avoids ConvertTo-SecureString ───────────────────
OLD_CRED = '''\
$cred = New-Object System.Management.Automation.PSCredential(
    "{user}",
    (ConvertTo-SecureString "{password}" -AsPlainText -Force)
)'''

NEW_CRED = '''\
$password = New-Object System.Security.SecureString
"{password}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)'''

count = content.count(OLD_CRED)
if count > 0:
    content = content.replace(OLD_CRED, NEW_CRED)
    print(f"Replaced {count} credential block(s)")
else:
    print("Old credential pattern not found — checking current PS scripts:")
    start = content.find("_PS_SERVICES")
    print(content[start:start+400])

# Also revert the Import-Module prefix we added earlier
content = content.replace(
    '"Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue; " + script',
    'script'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done — run: python control_plane.py --once")
