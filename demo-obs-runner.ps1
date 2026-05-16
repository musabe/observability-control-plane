# demo-obs-runner.ps1
# ============================================================
# Vorsa Demo — OBS Automated Recording Controller
# Uses OBS WebSocket to start/stop recording and auto-refresh
# the browser source — no manual clicks needed.
#
# SETUP (one time):
#   OBS → Tools → WebSocket Server Settings
#     ✓ Enable WebSocket server
#     Port: 4455
#     ✓ Enable authentication
#     Password: vorsa-demo
#
#   OBS Scene: "Vorsa-Dashboard"
#     Source type: Browser
#     URL:    http://localhost:8888/dashboard/index.html
#     Width:  1920
#     Height: 1080
#     CSS:    body { background-color: rgba(0,0,0,0); margin: 0; overflow: hidden; zoom: 0.9; }
#     Source name: "Vorsa-Dashboard" (must match $OBS_SOURCE below)
#
# USAGE:
#   Terminal 1: python control_plane.py
#   Terminal 2: python -m http.server 8888
#   Terminal 3: cd C:\Vorsa\platform\observability-control-plane
#               .\demo-obs-runner.ps1
# ============================================================

# ── Configuration ─────────────────────────────────────────────────────────────
$OBS_HOST     = "localhost"
$OBS_PORT     = 4455
$OBS_PASSWORD = "vorsa-demo"          # match OBS WebSocket settings
$OBS_SCENE    = "Vorsa-Dashboard"     # OBS scene name
$OBS_SOURCE   = "Vorsa-Dashboard"     # OBS browser source name (inside the scene)

$BASE         = "C:\Vorsa\platform\observability-control-plane"
$DASHBOARD    = "$BASE\dashboard"
$SCENARIOS    = "$DASHBOARD\scenarios"

# Timing (seconds) — adjust to match your narration pace
$T_HEALTHY    = 32    # healthy state display
$T_AFTER_REF1 = 3     # settle time after outage refresh
$T_CRITICAL   = 52    # critical state display
$T_AFTER_REF2 = 3     # settle time after recovery refresh
$T_RECOVERY   = 26    # recovery state display
$T_CLOSING    = 8     # closing hold on healthy dashboard

# ── OBS WebSocket implementation ──────────────────────────────────────────────

function New-ObsWebSocket {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $uri = [System.Uri]"ws://${OBS_HOST}:${OBS_PORT}"
    $ct  = [System.Threading.CancellationToken]::None
    $task = $ws.ConnectAsync($uri, $ct)
    $task.Wait(5000) | Out-Null
    if ($ws.State -ne "Open") { throw "Could not connect to OBS WebSocket" }
    return $ws
}

function Send-ObsMessage {
    param($ws, [hashtable]$msg)
    $json  = $msg | ConvertTo-Json -Compress -Depth 10
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $seg   = [System.ArraySegment[byte]]::new($bytes)
    $ws.SendAsync($seg,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [System.Threading.CancellationToken]::None).Wait()
}

function Receive-ObsMessage {
    param($ws, [int]$timeoutMs = 8000)
    $buf = [byte[]]::new(65536)
    $seg = [System.ArraySegment[byte]]::new($buf)
    $cts = New-Object System.Threading.CancellationTokenSource
    $cts.CancelAfter($timeoutMs)
    try {
        $result = $ws.ReceiveAsync($seg, $cts.Token).Result
        $json   = [System.Text.Encoding]::UTF8.GetString($buf, 0, $result.Count)
        return $json | ConvertFrom-Json
    } catch {
        throw "OBS WebSocket receive timeout — is OBS still running?"
    }
}

function Connect-ObsAuth {
    param($ws, [string]$password)

    # op=0 Hello
    $hello = Receive-ObsMessage $ws
    if ($hello.op -ne 0) { throw "Expected Hello (op=0) from OBS, got op=$($hello.op)" }

    $challenge  = $hello.d.authentication.challenge
    $salt       = $hello.d.authentication.salt
    $rpcVersion = $hello.d.rpcVersion

    # SHA256( SHA256(password + salt)_base64 + challenge )
    $sha = [System.Security.Cryptography.SHA256]::Create()

    $step1bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($password + $salt))
    $step1b64   = [Convert]::ToBase64String($step1bytes)
    $step2bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($step1b64 + $challenge))
    $authString = [Convert]::ToBase64String($step2bytes)

    # op=1 Identify
    Send-ObsMessage $ws @{
        op = 1
        d  = @{
            rpcVersion         = $rpcVersion
            authentication     = $authString
            eventSubscriptions = 0
        }
    }

    # op=2 Identified
    $identified = Receive-ObsMessage $ws
    if ($identified.op -ne 2) {
        throw "OBS authentication failed — check password matches OBS WebSocket settings"
    }
    return $true
}

function Invoke-ObsRequest {
    param($ws, [string]$type, [hashtable]$data = @{})
    $id = [System.Guid]::NewGuid().ToString()
    Send-ObsMessage $ws @{
        op = 6
        d  = @{
            requestType = $type
            requestId   = $id
            requestData = $data
        }
    }
    return Receive-ObsMessage $ws
}

function Refresh-ObsBrowserSource {
    param($ws, [string]$sourceName)
    # Triggers "Refresh cache of current page" inside OBS browser source
    Invoke-ObsRequest $ws "PressInputPropertiesButton" @{
        inputName    = $sourceName
        propertyName = "refreshnocache"
    } | Out-Null
    Start-Sleep -Milliseconds 1200
}

# ── UI helpers ────────────────────────────────────────────────────────────────

function Write-Header {
    param([string]$msg, [string]$color = "Cyan")
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host ""
    Write-Host "  [$ts] $msg" -ForegroundColor $color
}

function Write-Info {
    param([string]$msg)
    Write-Host "          $msg" -ForegroundColor Gray
}

function Wait-Countdown {
    param([int]$seconds, [string]$label)
    $total = $seconds
    for ($i = $seconds; $i -gt 0; $i--) {
        $done = $total - $i
        $pct  = [Math]::Floor($done / $total * 30)
        $bar  = ("$([char]9608)" * $pct).PadRight(30, "$([char]9617)")
        Write-Host "`r  [$bar] ${i}s — $label  " -NoNewline -ForegroundColor Yellow
        Start-Sleep -Seconds 1
    }
    $full = "$([char]9608)" * 30
    Write-Host "`r  [$full] done — $label  " -ForegroundColor Green
}

# ── Preflight ─────────────────────────────────────────────────────────────────

Clear-Host
Write-Host ""
Write-Host "  +===================================================+" -ForegroundColor Cyan
Write-Host "  |   Vorsa -- OBS Automated Demo Recording          |" -ForegroundColor Cyan
Write-Host "  |   northvale-council / PostgreSQL Outage Scenario |" -ForegroundColor Cyan
Write-Host "  +===================================================+" -ForegroundColor Cyan
Write-Host ""

# Verify scenario files exist
if (-not (Test-Path "$SCENARIOS\postgres-outage-state.json")) {
    Write-Host "  ERROR: Missing $SCENARIOS\postgres-outage-state.json" -ForegroundColor Red
    Write-Host "  Run the scenario setup first." -ForegroundColor Gray
    exit 1
}

Write-Host "  Pre-flight checklist:" -ForegroundColor White
Write-Host "    [ ] OBS open -- scene '$OBS_SCENE' selected" -ForegroundColor Gray
Write-Host "    [ ] OBS WebSocket: port $OBS_PORT, password '$OBS_PASSWORD'" -ForegroundColor Gray
Write-Host "    [ ] Browser source URL: http://localhost:8888/dashboard/index.html" -ForegroundColor Gray
Write-Host "    [ ] Browser source name in OBS: '$OBS_SOURCE'" -ForegroundColor Gray
Write-Host "    [ ] Dashboard showing HEALTHY (health >= 95, all green)" -ForegroundColor Gray
Write-Host "    [ ] python control_plane.py running in Terminal 1" -ForegroundColor Gray
Write-Host "    [ ] python -m http.server 8888 running in Terminal 2" -ForegroundColor Gray
Write-Host ""
Read-Host "  Press ENTER when all checks are complete"

# ── Connect to OBS ────────────────────────────────────────────────────────────

Write-Header "Connecting to OBS WebSocket on port $OBS_PORT..." "Yellow"
try {
    $ws = New-ObsWebSocket
    Connect-ObsAuth $ws $OBS_PASSWORD | Out-Null
    Write-Host "  Connected and authenticated." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Fix checklist:" -ForegroundColor White
    Write-Host "    - OBS is running" -ForegroundColor Gray
    Write-Host "    - Tools > WebSocket Server Settings > Enable WebSocket server" -ForegroundColor Gray
    Write-Host "    - Port: $OBS_PORT" -ForegroundColor Gray
    Write-Host "    - Password: $OBS_PASSWORD" -ForegroundColor Gray
    exit 1
}

# Switch to demo scene
Invoke-ObsRequest $ws "SetCurrentProgramScene" @{ sceneName = $OBS_SCENE } | Out-Null
Write-Host "  Scene set: '$OBS_SCENE'" -ForegroundColor Green

# ── Start recording ───────────────────────────────────────────────────────────

Write-Header "Starting OBS recording..." "Yellow"
Invoke-ObsRequest $ws "StartRecord" | Out-Null
Start-Sleep -Seconds 2
Write-Host "  Recording started." -ForegroundColor Green

$totalSecs = $T_HEALTHY + $T_AFTER_REF1 + $T_CRITICAL + $T_AFTER_REF2 + $T_RECOVERY + $T_CLOSING
Write-Host ""
Write-Host "  Demo sequence:" -ForegroundColor DarkCyan
Write-Host "    Phase 1 - Healthy state      $T_HEALTHY s" -ForegroundColor DarkCyan
Write-Host "    Phase 2 - Outage scenario    $T_CRITICAL s" -ForegroundColor DarkCyan
Write-Host "    Phase 3 - Recovery           $T_RECOVERY s" -ForegroundColor DarkCyan
Write-Host "    Total approx:                $totalSecs s (~$([Math]::Ceiling($totalSecs/60))m $(($totalSecs % 60))s)" -ForegroundColor DarkCyan

# ── PHASE 1: HEALTHY STATE ────────────────────────────────────────────────────

Write-Header "PHASE 1 -- HEALTHY STATE" "Green"
Write-Info "Move mouse slowly across:"
Write-Info "  health bar > JDBC grid > service topology > correlation timeline"
Write-Host ""

Wait-Countdown $T_HEALTHY "Healthy state"

# ── LOAD OUTAGE SCENARIO ──────────────────────────────────────────────────────

Write-Header "Loading PostgreSQL outage scenario..." "Yellow"
Copy-Item "$SCENARIOS\postgres-outage-state.json" "$DASHBOARD\state.json" -Force
Write-Info "state.json updated -- refreshing OBS browser source..."
Refresh-ObsBrowserSource $ws $OBS_SOURCE
Write-Host "  Browser source refreshed." -ForegroundColor Green

Wait-Countdown $T_AFTER_REF1 "Dashboard settling"

# ── PHASE 2: CRITICAL STATE ───────────────────────────────────────────────────

Write-Header "PHASE 2 -- CRITICAL STATE" "Red"
Write-Info "Move mouse across:"
Write-Info "  health=12 CRITICAL > PG offline > HTTP timeout"
Write-Info "  services stopped > JDBC all zeros > topology red nodes"
Write-Info "  2 incident cards with confidence badges (91% / 88%)"
Write-Host ""

Wait-Countdown $T_CRITICAL "Critical state"

# ── RECOVERY POLL ─────────────────────────────────────────────────────────────

Write-Header "Running live recovery poll..." "Yellow"
Push-Location $BASE
$pollOutput = python control_plane.py --once 2>&1
Pop-Location

$healthLine = $pollOutput | Where-Object { $_ -match "\[northvale-council\] Health:" } | Select-Object -Last 1
if ($healthLine) {
    Write-Host "  $($healthLine.ToString().Trim())" -ForegroundColor Green
} else {
    Write-Host "  Poll complete." -ForegroundColor Green
}

Write-Info "Refreshing OBS browser source..."
Refresh-ObsBrowserSource $ws $OBS_SOURCE
Write-Host "  Browser source refreshed." -ForegroundColor Green

Wait-Countdown $T_AFTER_REF2 "Dashboard settling"

# ── PHASE 3: RECOVERY ────────────────────────────────────────────────────────

Write-Header "PHASE 3 -- RECOVERY" "Green"
Write-Info "Move mouse across:"
Write-Info "  health climbing to 97-100 > 0 incidents > JDBC restored > all topology green"
Write-Host ""

Wait-Countdown $T_RECOVERY "Recovery state"

# ── CLOSING SHOT ─────────────────────────────────────────────────────────────

Write-Header "CLOSING SHOT -- hold on healthy dashboard" "Cyan"
Wait-Countdown $T_CLOSING "Closing"

# ── STOP RECORDING ───────────────────────────────────────────────────────────

Write-Header "Stopping OBS recording..." "Yellow"
$stopResult = Invoke-ObsRequest $ws "StopRecord"
Start-Sleep -Seconds 1

$ws.CloseAsync(
    [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
    "Done",
    [System.Threading.CancellationToken]::None
).Wait()

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  +===================================================+" -ForegroundColor Green
Write-Host "  |   Recording complete.                             |" -ForegroundColor Green
Write-Host "  +===================================================+" -ForegroundColor Green
Write-Host ""

$outputFile = $stopResult.d.responseData.outputPath
if ($outputFile) {
    Write-Host "  Saved to: $outputFile" -ForegroundColor Cyan
} else {
    Write-Host "  Check OBS output folder for recording." -ForegroundColor Gray
    Write-Host "  Default: C:\Users\$env:USERNAME\Videos\" -ForegroundColor Gray
}

Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. ElevenLabs > Text to Speech > paste narration-script.txt > download MP3" -ForegroundColor Gray
Write-Host "    2. ElevenLabs Studio > Add voiceover > upload recording + MP3" -ForegroundColor Gray
Write-Host "    3. Align audio using pause markers as sync points" -ForegroundColor Gray
Write-Host "    4. Export MP4" -ForegroundColor Gray
Write-Host ""
Write-Host "  Narration: docs\demo\narration-script.txt" -ForegroundColor Gray
Write-Host ""
