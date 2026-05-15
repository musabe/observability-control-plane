"""
patch_java_memory2.py
Run from repo root: python patch_java_memory2.py

Fixes Java child process lookup to walk 2 levels:
prunsrv.exe → cmd.exe → java.exe
"""

path = "collectors/windows_collector.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

start = content.find('_PS_PROCESS_MEMORY = r"""')
if start == -1:
    print("ERROR: Could not find _PS_PROCESS_MEMORY")
    exit(1)

end = content.find('"""', start + 24)
end += 3
old_block = content[start:end]

new_block = '''_PS_PROCESS_MEMORY = r"""
$password = New-Object System.Security.SecureString
"{password}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)

$allProcs = Get-WmiObject -ComputerName {host} -Credential $cred -Class Win32_Process

$procIds = @({pids})

foreach ($procId in $procIds) {{
    if ($procId -gt 0) {{
        $proc = $allProcs | Where-Object {{ $_.ProcessId -eq $procId }}
        if ($proc) {{
            $memBytes = $proc.WorkingSetSize

            if ($proc.Name -like "*prunsrv*" -or $memBytes -lt 10485760) {{
                $level1 = $allProcs | Where-Object {{ $_.ParentProcessId -eq $procId }}
                foreach ($child in $level1) {{
                    $level2 = $allProcs | Where-Object {{ $_.ParentProcessId -eq $child.ProcessId -and $_.Name -eq "java.exe" }}
                    if ($level2) {{
                        $memBytes = ($level2 | Measure-Object -Property WorkingSetSize -Sum).Sum
                        break
                    }}
                    if ($child.Name -eq "java.exe") {{
                        $memBytes = $child.WorkingSetSize
                        break
                    }}
                }}
            }}
            Write-Output "PROC|$procId|$memBytes"
        }} else {{
            Write-Output "PROC|$procId|0"
        }}
    }}
}}
"""'''

content = content.replace(old_block, new_block)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done — 2-level Java process lookup applied")
print("Run: python control_plane.py --once")
