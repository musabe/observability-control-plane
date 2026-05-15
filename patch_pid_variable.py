"""
patch_pid_variable.py
Run from repo root: python patch_pid_variable.py
"""

path = "collectors/windows_collector.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the _PS_PROCESS_MEMORY script — $pid is reserved in PowerShell
old = r"""$pids = @({pids})
foreach ($pid in $pids) {{
    if ($pid -gt 0) {{
        $proc = Get-WmiObject -ComputerName {host} -Credential $cred `
            -Class Win32_Process -Filter "ProcessId = $pid"
        if ($proc) {{
            Write-Output "PROC|$pid|$($proc.WorkingSetSize)"
        }}
    }}
}}"""

new = r"""$procIds = @({pids})
foreach ($procId in $procIds) {{
    if ($procId -gt 0) {{
        $proc = Get-WmiObject -ComputerName {host} -Credential $cred `
            -Class Win32_Process -Filter "ProcessId = $procId"
        if ($proc) {{
            Write-Output "PROC|$procId|$($proc.WorkingSetSize)"
        }}
    }}
}}"""

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Done — $pid renamed to $procId")
else:
    print("Pattern not found — checking _PS_PROCESS_MEMORY:")
    start = content.find("_PS_PROCESS_MEMORY")
    print(content[start:start+400])
