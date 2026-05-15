"""
patch_java_memory.py
Run from repo root: python patch_java_memory.py

Fixes the Windows service memory collector to read from the Java child
process instead of the prunsrv.exe wrapper.

Strategy:
  1. Get service PIDs (prunsrv.exe wrapper PIDs)
  2. Find java.exe processes whose ParentProcessId matches a wrapper PID
  3. Read WorkingSetSize from the java.exe process instead
  4. Fall back to the wrapper PID if no Java child found
"""

path = "collectors/windows_collector.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── Replace _PS_PROCESS_MEMORY with Java-aware version ────────────────────────

OLD_QUERY = r"""_PS_PROCESS_MEMORY = r"""
NEW_QUERY = r"""_PS_PROCESS_MEMORY = r"""

# Find and replace the entire _PS_PROCESS_MEMORY block
old_block = '''_Q_LONG_REPORT_JOBS''' # marker — we'll find the actual block

# Locate _PS_PROCESS_MEMORY
start = content.find('_PS_PROCESS_MEMORY = r"""')
if start == -1:
    print("ERROR: Could not find _PS_PROCESS_MEMORY in file")
    exit(1)

end = content.find('"""', start + 24)  # find closing triple quote
end += 3  # include the closing """

old_ps_block = content[start:end]

new_ps_block = '''_PS_PROCESS_MEMORY = r"""
$password = New-Object System.Security.SecureString
"{password}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)

$procIds = @({pids})

foreach ($procId in $procIds) {{
    if ($procId -gt 0) {{
        $proc = Get-WmiObject -ComputerName {host} -Credential $cred `
            -Class Win32_Process -Filter "ProcessId = $procId"
        if ($proc) {{
            $memBytes = $proc.WorkingSetSize
            $procName = $proc.Name

            if ($procName -like "*prunsrv*" -or $memBytes -lt 10485760) {{
                $javaChild = Get-WmiObject -ComputerName {host} -Credential $cred `
                    -Class Win32_Process -Filter "Name = 'java.exe' AND ParentProcessId = $procId"
                if ($javaChild) {{
                    $memBytes = ($javaChild | Measure-Object -Property WorkingSetSize -Sum).Sum
                }}
            }}
            Write-Output "PROC|$procId|$memBytes"
        }} else {{
            Write-Output "PROC|$procId|0"
        }}
    }}
}}
"""'''

content = content.replace(old_ps_block, new_ps_block)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done — Windows collector updated to follow Java child processes")
print("Run: python control_plane.py --once")
