# demo-obs-runner.ps1
# ============================================================
# Vorsa Demo — OBS Automated Recording with Narration Sync
#
# Cue points calibrated to generated narration MP3:
#   01:10 (70s)  — outage transition
#   03:16 (196s) — recovery transition
#   04:10 (252s) — end of recording
#
# OBS SETUP (one time):
#   1. Tools > WebSocket Server Settings
#      Port: 4455, Password: vorsa-demo, Enable: checked
#
#   2. Scene: "Vorsa-Dashboard"
#      Source 1 — Browser:
#        Name:   Vorsa-Dashboard
#        URL:    http://localhost:8888/dashboard/index.html
#        Width:  1920  Height: 1080
#        CSS:    body { background-color: rgba(0,0,0,0); margin: 0; overflow: hidden; zoom: 0.9; }
#      Source 2 — Audio Output Capture:
#        Name:   Desktop Audio
#        Device: Default
#
#   3. Settings > Audio > Desktop Audio: [your audio device]
#
# USAGE:
#   Terminal 1: python control_plane.py
#   Terminal 2: python -m http.server 8888
#   Terminal 3: .\demo-obs-runner.ps1
#            or .\demo-obs-runner.ps1 -NarrationMp3 "C:\path\to\narration.mp3"
# ============================================================

param(
    [string]$NarrationMp3 = "$PSScriptRoot\docs\demo\narration.mp3"
)

# ── Configuration ─────────────────────────────────────────────────────────────
$OBS_HOST     = "localhost"
$OBS_PORT     = 4455
$OBS_PASSWORD = "vorsa-demo"
$OBS_SCENE    = "Vorsa-Dashboard"
$OBS_SOURCE   = "Vorsa-Dashboard"

$BASE         = $PSScriptRoot
$DASHBOARD    = "$BASE\dashboard"
$SCENARIOS    = "$DASHBOARD\scenarios"

# Narration cue points — calibrated to your MP3
$CUE_OUTAGE   = 70     # 01:10 — "The most common and most impactful incident..."
$CUE_RECOVERY = 156    # 02:36 -- fires 40s before narration reaches recovery
$CUE_END      = 255    # 04:15 -- end of narration + 3s buffer

# ── OBS WebSocket ─────────────────────────────────────────────────────────────

function New-ObsWebSocket {
    $ws  = New-Object System.Net.WebSockets.ClientWebSocket
    $uri = [System.Uri]"ws://${OBS_HOST}:${OBS_PORT}"
    $ws.ConnectAsync($uri, [System.Threading.CancellationToken]::None).Wait(5000) | Out-Null
    if ($ws.State -ne "Open") { throw "Cannot connect to OBS WebSocket on port $OBS_PORT" }
    return $ws
}

function Send-ObsMessage { param($ws, [hashtable]$msg)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($msg | ConvertTo-Json -Compress -Depth 10))
    $ws.SendAsync([System.ArraySegment[byte]]::new($bytes),
        [System.Net.WebSockets.WebSocketMessageType]::Text, $true,
        [System.Threading.CancellationToken]::None).Wait()
}

function Receive-ObsMessage { param($ws, [int]$ms = 8000)
    $buf = [byte[]]::new(65536)
    $cts = New-Object System.Threading.CancellationTokenSource; $cts.CancelAfter($ms)
    $r   = $ws.ReceiveAsync([System.ArraySegment[byte]]::new($buf), $cts.Token).Result
    return [System.Text.Encoding]::UTF8.GetString($buf, 0, $r.Count) | ConvertFrom-Json
}

function Connect-ObsAuth { param($ws, [string]$pw)
    $h   = Receive-ObsMessage $ws
    if ($h.op -ne 0) { throw "Expected Hello from OBS" }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $b64 = { param($s) [Convert]::ToBase64String($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($s))) }
    $auth = & $b64 ((& $b64 ($pw + $h.d.authentication.salt)) + $h.d.authentication.challenge)
    Send-ObsMessage $ws @{ op=1; d=@{ rpcVersion=$h.d.rpcVersion; authentication=$auth; eventSubscriptions=0 } }
    $id = Receive-ObsMessage $ws
    if ($id.op -ne 2) { throw "OBS auth failed — check password matches OBS WebSocket settings" }
}

function Invoke-Obs { param($ws, [string]$type, [hashtable]$data=@{})
    Send-ObsMessage $ws @{ op=6; d=@{ requestType=$type; requestId=[guid]::NewGuid().ToString(); requestData=$data } }
    return Receive-ObsMessage $ws
}

function Refresh-Browser { param($ws)
    Invoke-Obs $ws "PressInputPropertiesButton" @{
        inputName    = $OBS_SOURCE
        propertyName = "refreshnocache"
    } | Out-Null
    Start-Sleep -Milliseconds 1200
}

# ── Audio ─────────────────────────────────────────────────────────────────────

function Start-NarrationAudio { param([string]$path)
    Add-Type -AssemblyName presentationCore
    $script:player = New-Object System.Windows.Media.MediaPlayer
    $script:player.Open([System.Uri]::new($path))
    $script:player.Play()
    $script:audioStart = Get-Date
}

function Get-AudioElapsed {
    return ((Get-Date) - $script:audioStart).TotalSeconds
}

function Wait-UntilCue { param([double]$cue, [string]$label)
    while ((Get-AudioElapsed) -lt $cue) {
        $elapsed   = Get-AudioElapsed
        $remaining = [Math]::Max(0, $cue - $elapsed)
        $pct       = [Math]::Min(30, [Math]::Floor($elapsed / $cue * 30))
        $bar       = ("$([char]9608)" * $pct).PadRight(30, "$([char]9617)")
        $elapsed_fmt   = "{0:mm\:ss}" -f [timespan]::fromseconds($elapsed)
        $remaining_fmt = "{0:mm\:ss}" -f [timespan]::fromseconds($remaining)
        Write-Host "`r  [$bar] $elapsed_fmt elapsed — ${remaining_fmt} until $label  " -NoNewline -ForegroundColor Yellow
        Start-Sleep -Milliseconds 250
    }
    $full = "$([char]9608)" * 30
    Write-Host "`r  [$full] CUE: $label                                    " -ForegroundColor Green
}

# ── UI ────────────────────────────────────────────────────────────────────────

function Write-Step { param([string]$msg, [string]$c = "Cyan")
    Write-Host "`n  [$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor $c
}

function Write-Info { param([string]$msg)
    Write-Host "          $msg" -ForegroundColor Gray
}

# ── Preflight ─────────────────────────────────────────────────────────────────

Clear-Host
Write-Host ""
Write-Host "  +=====================================================+" -ForegroundColor Cyan
Write-Host "  |   Vorsa -- OBS Demo Recording with Narration Sync  |" -ForegroundColor Cyan
Write-Host "  |   Total runtime: ~4m 12s                           |" -ForegroundColor Cyan
Write-Host "  +=====================================================+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Cue points:" -ForegroundColor White
Write-Host "    01:10 (70s)  -- Outage state loaded" -ForegroundColor Gray
Write-Host "    03:00 (180s) -- Recovery poll triggered" -ForegroundColor Gray
Write-Host "    04:15 (255s) -- Recording stops" -ForegroundColor Gray
Write-Host ""

# Check MP3
if (-not (Test-Path $NarrationMp3)) {
    Write-Host "  ERROR: Narration MP3 not found:" -ForegroundColor Red
    Write-Host "    $NarrationMp3" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Save your ElevenLabs MP3 to:" -ForegroundColor Gray
    Write-Host "    $PSScriptRoot\docs\demo\narration.mp3" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Or specify the path:" -ForegroundColor Gray
    Write-Host "    .\demo-obs-runner.ps1 -NarrationMp3 'C:\path\to\narration.mp3'" -ForegroundColor Yellow
    exit 1
}

Write-Host "  MP3 found: $NarrationMp3" -ForegroundColor Green
Write-Host ""
Write-Host "  Pre-flight checklist:" -ForegroundColor White
Write-Host "    [ ] OBS open -- scene '$OBS_SCENE' selected" -ForegroundColor Gray
Write-Host "    [ ] OBS WebSocket: port $OBS_PORT, password '$OBS_PASSWORD'" -ForegroundColor Gray
Write-Host "    [ ] OBS source '$OBS_SOURCE' is a Browser source" -ForegroundColor Gray
Write-Host "    [ ] OBS Desktop Audio capture enabled" -ForegroundColor Gray
Write-Host "    [ ] Dashboard showing HEALTHY (health >= 95)" -ForegroundColor Gray
Write-Host "    [ ] python control_plane.py running (Terminal 1)" -ForegroundColor Gray
Write-Host "    [ ] python -m http.server 8888 running (Terminal 2)" -ForegroundColor Gray
Write-Host "    [ ] System volume audible (OBS will capture it)" -ForegroundColor Gray
Write-Host ""
Read-Host "  Press ENTER to begin"

# ── Connect OBS ───────────────────────────────────────────────────────────────

Write-Step "Connecting to OBS..." "Yellow"
try {
    $ws = New-ObsWebSocket
    Connect-ObsAuth $ws $OBS_PASSWORD
    Write-Host "  Connected and authenticated." -ForegroundColor Green
} catch {
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Check OBS is running with WebSocket enabled on port $OBS_PORT." -ForegroundColor Gray
    exit 1
}

Invoke-Obs $ws "SetCurrentProgramScene" @{ sceneName=$OBS_SCENE } | Out-Null
Write-Host "  Scene set: '$OBS_SCENE'" -ForegroundColor Green

# ── Start OBS recording ───────────────────────────────────────────────────────

Write-Step "Starting OBS recording..." "Yellow"
Invoke-Obs $ws "StartRecord" | Out-Null
Start-Sleep -Seconds 1

# ── Start narration audio ─────────────────────────────────────────────────────

Write-Step "Starting narration..." "Yellow"
Start-NarrationAudio (Resolve-Path $NarrationMp3).Path
Write-Host "  Audio playing -- OBS capturing screen + audio together." -ForegroundColor Green

# ── PHASE 1: HEALTHY (0:00 - 1:10) ───────────────────────────────────────────

Write-Host ""
Write-Step "PHASE 1 -- HEALTHY STATE  (0:00 - 1:10)" "Green"
Write-Info "Move mouse: health bar > JDBC grid > topology > correlation timeline"
Write-Host ""

Wait-UntilCue $CUE_OUTAGE "outage transition at 01:10"

# ── LOAD OUTAGE (1:10) ────────────────────────────────────────────────────────

Write-Step "Loading outage scenario..." "Red"
Copy-Item "$SCENARIOS\postgres-outage-state.json" "$DASHBOARD\state.json" -Force
Refresh-Browser $ws
Write-Host "  Dashboard: CRITICAL state loaded." -ForegroundColor Red

# ── PHASE 2: CRITICAL (1:10 - 3:16) ──────────────────────────────────────────

Write-Step "PHASE 2 -- CRITICAL STATE  (1:10 - 3:00)" "Red"
Write-Info "Move mouse: health=12 > PG offline > HTTP timeout"
Write-Info "           > services stopped > JDBC all zeros"
Write-Info "           > topology red nodes > 2 incident cards"
Write-Host ""

Wait-UntilCue $CUE_RECOVERY "recovery transition at 03:00"

# ── RECOVERY (3:16) ───────────────────────────────────────────────────────────

Write-Step "Running recovery poll..." "Yellow"
Push-Location $BASE
$pollOut = python control_plane.py --once 2>&1
Pop-Location

$hl = $pollOut | Where-Object { $_ -match "Health:" } | Select-Object -Last 1
if ($hl) { Write-Host "  $($hl.ToString().Trim())" -ForegroundColor Green }
else { Write-Host "  Poll complete." -ForegroundColor Green }

Refresh-Browser $ws
Write-Host "  Dashboard: HEALTHY state restored." -ForegroundColor Green

# ── PHASE 3: RECOVERY (3:16 - 4:10) ─────────────────────────────────────────

Write-Step "PHASE 3 -- RECOVERY  (3:16 - 4:15)" "Green"
Write-Info "Move mouse: health climbing > 0 incidents > JDBC restored > all green"
Write-Host ""

Wait-UntilCue $CUE_END "end of recording at 04:15"

# ── STOP ──────────────────────────────────────────────────────────────────────

$script:player.Stop()
Write-Step "Stopping OBS recording..." "Yellow"
$stop = Invoke-Obs $ws "StopRecord"
Start-Sleep -Seconds 1
$ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "",
    [System.Threading.CancellationToken]::None).Wait()

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  +=====================================================+" -ForegroundColor Green
Write-Host "  |   Recording complete.                              |" -ForegroundColor Green
Write-Host "  |   Screen + narration captured in one take.        |" -ForegroundColor Green
Write-Host "  +=====================================================+" -ForegroundColor Green
Write-Host ""

$outFile = $stop.d.responseData.outputPath
if ($outFile) {
    Write-Host "  Saved to: $outFile" -ForegroundColor Cyan
} else {
    Write-Host "  Check OBS output folder: C:\Users\$env:USERNAME\Videos\" -ForegroundColor Gray
}
Write-Host ""
