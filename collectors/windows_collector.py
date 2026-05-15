"""
collectors/windows_collector.py
--------------------------------
Collects Windows service state and memory usage from remote Qmatic servers
using PowerShell + WMI over the network.

Requires:
  - WMI access to the remote host (Windows Admin credentials)
  - PowerShell available on the local machine
  - Environment variables for credentials:
      OBS_WMI_USER_{ENV_NAME_UPPER_SNAKE}
      OBS_WMI_PASSWORD_{ENV_NAME_UPPER_SNAKE}

Collected data:
  - Total / free / used physical memory on the server
  - All Qmatic Windows services (name, display name, state, PID)
  - Memory (working set) per running Qmatic service process
"""

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_float(val, default=0.0):
    try:
        return float(str(val).strip()) if str(val).strip() else default
    except (ValueError, TypeError):
        return default



# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class WindowsService:
    name: str
    display_name: str
    state: str              # Running | Stopped | ...
    pid: int
    memory_mb: float = 0.0  # working set in MB (0 if stopped)


@dataclass
class WindowsMemorySnapshot:
    environment: str
    host: str
    collected_at: datetime
    available: bool = False
    error: Optional[str] = None

    # Server memory
    total_memory_mb: float = 0.0
    free_memory_mb: float = 0.0
    used_memory_mb: float = 0.0
    memory_used_pct: float = 0.0

    # Qmatic services
    services: list = field(default_factory=list)
    qmatic_total_memory_mb: float = 0.0

    # Severity
    severity: str = "ok"

    def compute_severity(self, memory_warning_pct: float = 80.0,
                         memory_critical_pct: float = 90.0) -> None:
        stopped = [s for s in self.services if s.state != "Running"]
        if (self.memory_used_pct >= memory_critical_pct
                or len(stopped) == len(self.services)):
            self.severity = "critical"
        elif self.memory_used_pct >= memory_warning_pct or stopped:
            self.severity = "warning"
        else:
            self.severity = "ok"


# ── PowerShell script templates ───────────────────────────────────────────────

_PS_SERVICES = r"""
$password = New-Object System.Security.SecureString
"{password}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)
$services = Get-WmiObject -ComputerName {host} -Credential $cred `
    -Class Win32_Service `
    -Filter "Name LIKE '%qmatic%' OR Name LIKE '%qp%' OR Name LIKE '%orchestra%'" |
    Where-Object {{ $_.Name -notlike '*postgres*' -and $_.Name -notlike '*PostgreSQL*' }}

foreach ($svc in $services) {{
    Write-Output "SVC|$($svc.Name)|$($svc.DisplayName)|$($svc.State)|$($svc.ProcessId)"
}}
"""

_PS_MEMORY = r"""
$password = New-Object System.Security.SecureString
"{password}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)
$os = Get-WmiObject -ComputerName {host} -Credential $cred -Class Win32_OperatingSystem
Write-Output "MEM|$($os.TotalVisibleMemorySize)|$($os.FreePhysicalMemory)"
"""

_PS_PROCESS_MEMORY = r"""
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
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _env_key(env_name: str, prefix: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]", "_", env_name).upper()
    return f"{prefix}_{safe}"


def _run_ps(script: str) -> tuple[bool, str, str]:
    """Run a PowerShell script and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "PowerShell timeout after 30s"
    except Exception as exc:
        return False, "", str(exc)


# ── Collector ─────────────────────────────────────────────────────────────────

class WindowsCollector:
    """
    Collects Windows service state and memory from a remote Qmatic server.
    Uses PowerShell WMI remoting with stored credentials.
    """

    def __init__(self, env_name: str, host: str):
        self.env_name = env_name
        self.host = host
        self.user = os.environ.get(_env_key(env_name, "OBS_WMI_USER"), "Administrator")
        self.password = os.environ.get(_env_key(env_name, "OBS_WMI_PASSWORD"), "")

    def collect(self) -> WindowsMemorySnapshot:
        snap = WindowsMemorySnapshot(
            environment=self.env_name,
            host=self.host,
            collected_at=datetime.now(timezone.utc),
        )

        if not self.password:
            snap.error = f"No WMI password — set OBS_WMI_PASSWORD_{self.env_name.upper().replace('-','_')}"
            logger.warning("[%s] %s", self.env_name, snap.error)
            return snap

        # ── 1. Get server memory ───────────────────────────────────────────
        ps = _PS_MEMORY.format(
            host=self.host,
            user=self.user,
            password=self.password,
        )
        ok, stdout, stderr = _run_ps(ps)
        if not ok or not stdout.strip():
            snap.error = stderr.strip() or "Failed to collect memory"
            logger.error("[%s] Windows memory collection failed: %s", self.env_name, snap.error)
            return snap

        for line in stdout.strip().splitlines():
            if line.startswith("MEM|"):
                parts = line.split("|")
                if len(parts) == 3:
                    total_kb = _safe_float(parts[1])
                    free_kb = _safe_float(parts[2])
                    snap.total_memory_mb = round(total_kb / 1024, 1)
                    snap.free_memory_mb = round(free_kb / 1024, 1)
                    snap.used_memory_mb = round(snap.total_memory_mb - snap.free_memory_mb, 1)
                    snap.memory_used_pct = round(
                        snap.used_memory_mb / snap.total_memory_mb * 100, 1
                    ) if snap.total_memory_mb > 0 else 0.0

        # ── 2. Get Qmatic services ─────────────────────────────────────────
        ps = _PS_SERVICES.format(
            host=self.host,
            user=self.user,
            password=self.password,
        )
        ok, stdout, stderr = _run_ps(ps)
        if not ok:
            snap.error = stderr.strip()
            logger.error("[%s] Windows service collection failed: %s", self.env_name, snap.error)
            return snap

        services = []
        running_pids = []
        for line in stdout.strip().splitlines():
            if line.startswith("SVC|"):
                parts = line.split("|")
                if len(parts) == 5:
                    pid = int(parts[4]) if parts[4].isdigit() else 0
                    svc = WindowsService(
                        name=parts[1],
                        display_name=parts[2],
                        state=parts[3],
                        pid=pid,
                    )
                    services.append(svc)
                    if pid > 0:
                        running_pids.append(pid)

        # ── 3. Get memory per running process ──────────────────────────────
        if running_pids:
            pid_list = ", ".join(str(p) for p in running_pids)
            ps = _PS_PROCESS_MEMORY.format(
                host=self.host,
                user=self.user,
                password=self.password,
                pids=pid_list,
            )
            ok, stdout, stderr = _run_ps(ps)
            if ok:
                pid_memory = {}
                for line in stdout.strip().splitlines():
                    if line.startswith("PROC|"):
                        parts = line.split("|")
                        if len(parts) == 3:
                            pid_memory[int(parts[1])] = round(
                                _safe_float(parts[2]) / 1048576, 1
                            )  # bytes → MB

                for svc in services:
                    if svc.pid in pid_memory:
                        svc.memory_mb = pid_memory[svc.pid]

        snap.services = services
        snap.qmatic_total_memory_mb = round(
            sum(s.memory_mb for s in services), 1
        )
        snap.available = True
        snap.compute_severity()

        logger.info(
            "[%s] Windows: memory=%.1f%% qmatic_mem=%.0fMB services=%s",
            self.env_name,
            snap.memory_used_pct,
            snap.qmatic_total_memory_mb,
            {s.display_name: s.state for s in services},
        )

        return snap
