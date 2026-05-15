"""
debug_windows.py
Run from repo root: python debug_windows.py
"""

import subprocess
import os

user = os.environ.get("OBS_WMI_USER_CXM_TEST_LOCAL", "Administrator")
pwd = os.environ.get("OBS_WMI_PASSWORD_CXM_TEST_LOCAL", "")
host = "192.168.68.114"

if not pwd:
    print("ERROR: OBS_WMI_PASSWORD_CXM_TEST_LOCAL not set")
    exit(1)

# ── Get service PIDs ──────────────────────────────────────────────────────────
ps_services = f"""
$password = New-Object System.Security.SecureString
"{pwd}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)
$svcs = Get-WmiObject -ComputerName {host} -Credential $cred -Class Win32_Service -Filter "Name LIKE '%qmatic%' OR Name LIKE '%qp%'" |
    Where-Object {{ $_.Name -notlike '*postgres*' -and $_.Name -notlike '*PostgreSQL*' }}
foreach ($s in $svcs) {{
    Write-Output "SVC|$($s.Name)|$($s.DisplayName)|$($s.State)|$($s.ProcessId)"
}}
"""

print("=== Services ===")
result = subprocess.run(
    ["powershell", "-NonInteractive", "-NoProfile", "-Command", ps_services],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr[:200] if result.stderr else "none")

# Parse PIDs
running_pids = []
for line in result.stdout.strip().splitlines():
    if line.startswith("SVC|"):
        parts = line.split("|")
        print(f"  name={parts[1]} display={parts[2]} state={parts[3]} pid={parts[4]}")
        if parts[4].strip().isdigit() and int(parts[4]) > 0:
            running_pids.append(int(parts[4]))

print(f"\nRunning PIDs: {running_pids}")

if not running_pids:
    print("No running PIDs found — services may all be stopped")
    exit(0)

# ── Get process memory for each PID ──────────────────────────────────────────
pid_list = ", ".join(str(p) for p in running_pids)

ps_memory = f"""
$password = New-Object System.Security.SecureString
"{pwd}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)
$pids = @({pid_list})
foreach ($pid in $pids) {{
    if ($pid -gt 0) {{
        $proc = Get-WmiObject -ComputerName {host} -Credential $cred -Class Win32_Process -Filter "ProcessId = $pid"
        if ($proc) {{
            Write-Output "PROC|$pid|$($proc.Name)|$($proc.WorkingSetSize)"
        }} else {{
            Write-Output "PROC|$pid|NOT_FOUND|0"
        }}
    }}
}}
"""

print("\n=== Process Memory ===")
result2 = subprocess.run(
    ["powershell", "-NonInteractive", "-NoProfile", "-Command", ps_memory],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result2.stdout)
print("STDERR:", result2.stderr[:200] if result2.stderr else "none")

for line in result2.stdout.strip().splitlines():
    if line.startswith("PROC|"):
        parts = line.split("|")
        mem_mb = round(float(parts[3]) / 1048576, 1) if parts[3].strip().isdigit() else 0
        print(f"  pid={parts[1]} name={parts[2]} memory={mem_mb}MB raw={parts[3]}")
