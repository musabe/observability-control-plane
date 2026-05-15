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
  - JVM -Xmx setting per java.exe process (auto-detected via WMI)
  - JVM heap usage % vs configured max heap

JVM heap ceiling priority:
  1. Auto-detected from java.exe CommandLine (-Xmx arg) via WMI
  2. qmatic_jvm_heap_max_mb from environments.yaml (fallback)
  3. Server total RAM (last resort)
"""

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class WindowsService:
    name: str
    display_name: str
    state: str
    pid: int
    memory_mb: float = 0.0
    xmx_mb: float = 0.0
    heap_used_pct: float = 0.0
    heap_severity: str = "ok"


@dataclass
class WindowsMemorySnapshot:
    environment: str
    host: str
    collected_at: datetime
    available: bool = False
    error: Optional[str] = None

    total_memory_mb: float = 0.0
    free_memory_mb: float = 0.0
    used_memory_mb: float = 0.0
    memory_used_pct: float = 0.0
    memory_severity: str = "ok"

    services: list = field(default_factory=list)
    qmatic_total_memory_mb: float = 0.0

    jvm_heap_max_mb: float = 0.0
    jvm_heap_source: str = "unknown"

    severity: str = "ok"

    def compute_severity(self, thresholds: dict) -> None:
        server_warn = thresholds.get("server_memory_warning_pct", 80)
        server_crit = thresholds.get("server_memory_critical_pct", 90)
        jvm_warn = thresholds.get("jvm_heap_warning_pct", 80)
        jvm_crit = thresholds.get("jvm_heap_critical_pct", 90)

        if self.memory_used_pct >= server_crit:
            self.memory_severity = "critical"
        elif self.memory_used_pct >= server_warn:
            self.memory_severity = "warning"
        else:
            self.memory_severity = "ok"

        for svc in self.services:
            if svc.heap_used_pct > 0:
                if svc.heap_used_pct >= jvm_crit:
                    svc.heap_severity = "critical"
                elif svc.heap_used_pct >= jvm_warn:
                    svc.heap_severity = "warning"
                else:
                    svc.heap_severity = "ok"

        stopped = [s for s in self.services if s.state != "Running"]
        severities = [self.memory_severity]
        severities += [s.heap_severity for s in self.services if s.heap_used_pct > 0]
        if stopped:
            severities.append("critical")

        if "critical" in severities:
            self.severity = "critical"
        elif "warning" in severities:
            self.severity = "warning"
        else:
            self.severity = "ok"


# ── PowerShell scripts ────────────────────────────────────────────────────────

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

_PS_JVM_XMX = r"""
$password = New-Object System.Security.SecureString
"{password}".ToCharArray() | ForEach-Object {{ $password.AppendChar($_) }}
$cred = New-Object System.Management.Automation.PSCredential("{user}", $password)
$allProcs = Get-WmiObject -ComputerName {host} -Credential $cred -Class Win32_Process
$procIds = @({pids})
foreach ($procId in $procIds) {{
    if ($procId -gt 0) {{
        $xmx = "none"
        $searchProcs = $allProcs | Where-Object {{ $_.ProcessId -eq $procId }}
        $level1 = $allProcs | Where-Object {{ $_.ParentProcessId -eq $procId }}
        foreach ($child in $level1) {{
            $searchProcs += $child
            $level2 = $allProcs | Where-Object {{ $_.ParentProcessId -eq $child.ProcessId }}
            foreach ($gc in $level2) {{ $searchProcs += $gc }}
        }}
        foreach ($p in $searchProcs) {{
            if ($p.CommandLine -match '-Xmx(\S+)') {{
                $xmx = $matches[1]
                break
            }}
        }}
        Write-Output "XMX|$procId|$xmx"
    }}
}}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(val, default=0.0) -> float:
    try:
        return float(str(val).strip()) if str(val).strip() else default
    except (ValueError, TypeError):
        return default


def _env_key(env_name: str, prefix: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]", "_", env_name).upper()
    return f"{prefix}_{safe}"


def _parse_xmx_to_mb(xmx_str: str) -> float:
    if not xmx_str or xmx_str.lower() == "none":
        return 0.0
    s = xmx_str.strip().lower()
    try:
        if s.endswith("g"):
            return float(s[:-1]) * 1024
        elif s.endswith("m"):
            return float(s[:-1])
        elif s.endswith("k"):
            return float(s[:-1]) / 1024
        else:
            return float(s) / 1048576
    except ValueError:
        return 0.0


def _run_ps(script: str) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-NoProfile",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "PowerShell timeout after 30s"
    except Exception as exc:
        return False, "", str(exc)


# ── Collector ─────────────────────────────────────────────────────────────────

class WindowsCollector:

    def __init__(self, env_name: str, host: str, win_config=None):
        self.env_name = env_name
        self.host = host
        self.win_config = win_config
        self.user = os.environ.get(_env_key(env_name, "OBS_WMI_USER"), "Administrator")
        self.password = os.environ.get(_env_key(env_name, "OBS_WMI_PASSWORD"), "")

    def _thresholds(self) -> dict:
        if self.win_config and isinstance(self.win_config, dict):
            return self.win_config.get("thresholds", {})
        return {}

    def _config_jvm_mb(self) -> float:
        if self.win_config and isinstance(self.win_config, dict):
            return float(self.win_config.get("qmatic_jvm_heap_max_mb", 0))
        return 0.0

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

        # Server memory
        ps = _PS_MEMORY.format(host=self.host, user=self.user, password=self.password)
        ok, stdout, stderr = _run_ps(ps)
        if not ok or not stdout.strip():
            snap.error = stderr.strip() or "Failed to collect memory"
            logger.error("[%s] Windows memory failed: %s", self.env_name, snap.error)
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

        # Services
        ps = _PS_SERVICES.format(host=self.host, user=self.user, password=self.password)
        ok, stdout, stderr = _run_ps(ps)
        if not ok:
            snap.error = stderr.strip()
            logger.error("[%s] Windows services failed: %s", self.env_name, snap.error)
            return snap

        services = []
        running_pids = []
        for line in stdout.strip().splitlines():
            if line.startswith("SVC|"):
                parts = line.split("|")
                if len(parts) == 5:
                    pid = int(parts[4]) if parts[4].isdigit() else 0
                    svc = WindowsService(
                        name=parts[1], display_name=parts[2],
                        state=parts[3], pid=pid,
                    )
                    services.append(svc)
                    if pid > 0:
                        running_pids.append(pid)

        # Process memory
        if running_pids:
            pid_list = ", ".join(str(p) for p in running_pids)
            ps = _PS_PROCESS_MEMORY.format(
                host=self.host, user=self.user,
                password=self.password, pids=pid_list,
            )
            ok, stdout, _ = _run_ps(ps)
            if ok:
                pid_memory = {}
                for line in stdout.strip().splitlines():
                    if line.startswith("PROC|"):
                        parts = line.split("|")
                        if len(parts) == 3:
                            pid_memory[int(parts[1])] = round(
                                _safe_float(parts[2]) / 1048576, 1
                            )
                for svc in services:
                    if svc.pid in pid_memory:
                        svc.memory_mb = pid_memory[svc.pid]

        # JVM -Xmx detection
        if running_pids:
            pid_list = ", ".join(str(p) for p in running_pids)
            ps = _PS_JVM_XMX.format(
                host=self.host, user=self.user,
                password=self.password, pids=pid_list,
            )
            ok, stdout, _ = _run_ps(ps)
            config_xmx = self._config_jvm_mb()

            if ok:
                pid_xmx = {}
                for line in stdout.strip().splitlines():
                    if line.startswith("XMX|"):
                        parts = line.split("|")
                        if len(parts) == 3:
                            pid_xmx[int(parts[1])] = _parse_xmx_to_mb(parts[2])

                for svc in services:
                    detected = pid_xmx.get(svc.pid, 0.0)
                    if detected > 0:
                        svc.xmx_mb = detected
                        snap.jvm_heap_source = "detected"
                    elif config_xmx > 0:
                        svc.xmx_mb = config_xmx
                        snap.jvm_heap_source = "config"
                    elif snap.total_memory_mb > 0:
                        svc.xmx_mb = snap.total_memory_mb
                        snap.jvm_heap_source = "server_ram"

                    if svc.xmx_mb > 0 and svc.memory_mb > 0:
                        svc.heap_used_pct = round(
                            (svc.memory_mb / svc.xmx_mb) * 100, 1
                        )

            detected_xmx = [s.xmx_mb for s in services if s.xmx_mb > 0]
            snap.jvm_heap_max_mb = max(detected_xmx) if detected_xmx else 0.0

        snap.services = services
        snap.qmatic_total_memory_mb = round(sum(s.memory_mb for s in services), 1)
        snap.available = True
        snap.compute_severity(self._thresholds())

        logger.info(
            "[%s] Windows: mem=%.1f%%(%s) qmatic=%.0fMB "
            "jvm_max=%.0fMB(src=%s) services=%s",
            self.env_name,
            snap.memory_used_pct, snap.memory_severity,
            snap.qmatic_total_memory_mb,
            snap.jvm_heap_max_mb, snap.jvm_heap_source,
            {s.display_name: f"{s.state} {s.memory_mb:.0f}MB heap={s.heap_used_pct:.0f}%"
             for s in snap.services},
        )

        return snap
