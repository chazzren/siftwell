# Siftwell launcher for Windows. Used by "Start Siftwell.cmd" and "Stop Siftwell.cmd".
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\launcher.ps1          start (or open) Siftwell
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\launcher.ps1 -Stop    stop the Siftwell started from this folder
#
# Everything it installs (uv, Python, the package cache) goes into the hidden .siftwell folder next to the app,
# plus the usual .venv. Nothing is written to your user profile and no admin rights are needed.
# Your own data (profiles, resumes, logs) stays in %APPDATA%\JobBoard as before (JOBBOARD_DATA overrides it).
#
# Optional environment variables (mainly for testing):
#   SIFTWELL_PORT=8790        use this port instead of the remembered one / 8766
#   SIFTWELL_NO_BROWSER=1     don't open a browser window
#   SIFTWELL_NO_PAUSE=1       don't wait a few seconds after Stop
# Exit code 0 = fine; anything else = the .cmd keeps the window open so the message can be read.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less files in the legacy code page.

param([switch]$Stop)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow in 5.1 with the progress bar on

$App    = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path.TrimEnd("\")
$Sift   = Join-Path $App ".siftwell"
$UvDir  = Join-Path $Sift "uv"
$UvExe  = Join-Path $UvDir "uv.exe"
$Venv   = Join-Path $App ".venv"
$Py     = Join-Path $Venv "Scripts\python.exe"
$Pyw    = Join-Path $Venv "Scripts\pythonw.exe"
$Req    = Join-Path $App "requirements.txt"
$Stamp  = Join-Path $Sift "requirements.sha256"
$PortFile = Join-Path $Sift "port"
$PidFile  = Join-Path $Sift "server.pid"
$SetupLog = Join-Path $Sift "setup.log"
$DefaultPort = 8766
$FallbackPorts = 8767..8775
$DataDir = if ($env:JOBBOARD_DATA) { $env:JOBBOARD_DATA } else { Join-Path $env:APPDATA "JobBoard" }

# Keep uv and its downloads inside the app folder.
$env:UV_INSTALL_DIR        = $UvDir
$env:UV_UNMANAGED_INSTALL  = $UvDir          # no install receipt in %LOCALAPPDATA%, no PATH change
$env:UV_NO_MODIFY_PATH     = "1"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Sift "python"
$env:UV_PYTHON_BIN_DIR     = Join-Path $Sift "python-bin"
$env:UV_CACHE_DIR          = Join-Path $Sift "cache"
$env:UV_NO_CONFIG          = "1"             # ignore any uv.toml the user may have
$env:PYTHONUTF8            = "1"
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue

function Say($m)  { Write-Host $m }
function Step($m) { Write-Host "  - $m" }
function Fail($msg, $hint) {
    Write-Host ""
    Write-Host "Sorry, Siftwell could not start." -ForegroundColor Red
    Write-Host $msg -ForegroundColor Red
    if ($hint) { Write-Host ""; Write-Host $hint -ForegroundColor Yellow }
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------- helpers

function Get-Url($port, $path) {
    # Returns @{ Code = <int or 0>; Body = <string> }. Never throws.
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}{1}" -f $port, $path) -TimeoutSec 4 -MaximumRedirection 5
        return @{ Code = [int]$r.StatusCode; Body = [string]$r.Content }
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($resp) {
            $body = ""
            try { $body = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } catch {}
            return @{ Code = [int]$resp.StatusCode; Body = $body }
        }
        return @{ Code = 0; Body = "" }
    } catch {
        return @{ Code = 0; Body = "" }
    }
}

function Test-Siftwell($port) {
    # True if a Siftwell (Job Board) server answers on this port.
    $s = Get-Url $port "/api/status"
    if ($s.Code -eq 200 -and $s.Body -match '"schedule"' -and $s.Body -match '"recomputing"') { return $true }
    $r = Get-Url $port "/"
    if ($r.Code -gt 0 -and $r.Body -match 'Job Board|Siftwell') { return $true }
    return $false
}

function Test-PortFree($port) {
    # The server binds 0.0.0.0 with exclusive use, so test the same way.
    try {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $port)
        $l.ExclusiveAddressUse = $true
        $l.Start(); $l.Stop()
        return $true
    } catch { return $false }
}

function Get-OwnServers {
    # Siftwell server processes started from THIS folder: python(w) whose exe lives under the app folder
    # (.venv or .siftwell\python) and whose command line runs server.py. Other Pythons are never matched.
    $prefix = $App + "\"
    @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -and
        $_.CommandLine -and $_.CommandLine -match 'server\.py'
    })
}

function Read-Port {
    if ($env:SIFTWELL_PORT -match '^\d+$') { return [int]$env:SIFTWELL_PORT }
    if (Test-Path $PortFile) {
        $p = (Get-Content $PortFile -Raw -ErrorAction SilentlyContinue)
        if ($p -and $p.Trim() -match '^\d+$') { return [int]$p.Trim() }
    }
    return $DefaultPort
}

function Open-Board($port) {
    $url = "http://127.0.0.1:$port/"
    if ($env:SIFTWELL_NO_BROWSER) { Say "Siftwell is running at $url"; return }
    Say "Opening $url"
    Start-Process $url
}

function Run-Quiet($exe, [string]$argLine) {
    # Runs a program with its output going to setup.log; returns the exit code.
    # (Start-Process instead of '&' so Windows PowerShell 5.1 doesn't turn progress text on stderr into errors.)
    $out = "$SetupLog.out"; $err = "$SetupLog.err"
    $p = Start-Process -FilePath $exe -ArgumentList $argLine -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err -WorkingDirectory $App
    $null = $p.Handle   # keeps ExitCode available after exit
    $p.WaitForExit()
    $code = $p.ExitCode
    Add-Content -Path $SetupLog -Value ("`r`n> $exe $argLine  (exit $code)")
    foreach ($f in @($out, $err)) {
        if (Test-Path $f) { Get-Content $f | Add-Content -Path $SetupLog; Remove-Item $f -Force }
    }
    return $code
}

function Show-LogTail($path, $n) {
    if (Test-Path $path) {
        Write-Host ""
        Write-Host "Last lines of ${path}:" -ForegroundColor DarkGray
        Get-Content $path -Tail $n | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
}

function Test-VenvOk {
    if (-not (Test-Path $Py)) { return $false }
    try {
        $v = & $Py -c "import sys;print(sys.version_info[:2]>=(3,12))" 2>$null
        return ($v -eq "True")
    } catch { return $false }
}

function Test-UvOk {
    if (-not (Test-Path $UvExe)) { return $false }
    try { $null = & $UvExe --version 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

function Get-ReqHash { (Get-FileHash -Algorithm SHA256 -Path $Req).Hash }

# ---------------------------------------------------------------- stop

if ($Stop) {
    $procs = Get-OwnServers
    $ids = @($procs | ForEach-Object { [int]$_.ProcessId })
    if (Test-Path $PidFile) {
        $p = (Get-Content $PidFile -Raw -ErrorAction SilentlyContinue)
        if ($p -and $p.Trim() -match '^\d+$') {
            # Only trust the pid file if that process is still one of ours.
            $pp = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $p.Trim()) -ErrorAction SilentlyContinue
            if ($pp -and $pp.ExecutablePath -and $pp.ExecutablePath.StartsWith($App + "\", [StringComparison]::OrdinalIgnoreCase)) {
                $ids += [int]$p.Trim()
            }
        }
    }
    $ids = @($ids | Sort-Object -Unique)
    if ($ids.Count -eq 0) {
        Say "Siftwell isn't running (from this folder)."
    } else {
        foreach ($id in $ids) {
            # /T also ends anything the server started (for example a running job update).
            try { cmd.exe /c "taskkill /PID $id /T /F >nul 2>&1" } catch {}
        }
        Start-Sleep -Milliseconds 500
        if ((Get-OwnServers).Count -gt 0) { Fail "Some Siftwell processes are still running." "Try again, or restart the computer." }
        Say "Siftwell has stopped. Double-click 'Start Siftwell' to start it again."
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    if (-not $env:SIFTWELL_NO_PAUSE) { Start-Sleep -Seconds 3 }
    exit 0
}

# ---------------------------------------------------------------- start

$Host.UI.RawUI.WindowTitle = "Siftwell"
$port = Read-Port

# 1. Already running? Just open it.
if (Test-Siftwell $port) {
    Open-Board $port
    exit 0
}

# 1b. Started from this folder but not answering yet (e.g. double-clicked twice)? Wait for it.
$own = Get-OwnServers
if ($own.Count -gt 0) {
    $m = [regex]::Match(($own[0].CommandLine), 'server\.py"?\s+(\d+)')
    if ($m.Success) { $port = [int]$m.Groups[1].Value }
    Say "Siftwell is starting up..."
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Siftwell $port) { Open-Board $port; exit 0 }
        Start-Sleep -Seconds 1
    }
    Fail "Siftwell is running but not answering on port $port." "Double-click 'Stop Siftwell', then 'Start Siftwell' again."
}

# 2. One-time setup (or repair): uv, Python, packages.
New-Item -ItemType Directory -Force -Path $Sift | Out-Null
try { (Get-Item $Sift -Force).Attributes = (Get-Item $Sift -Force).Attributes -bor [IO.FileAttributes]::Hidden } catch {}

$needUv   = -not (Test-UvOk)
$needVenv = -not (Test-VenvOk)
$hash     = Get-ReqHash
$oldHash  = if (Test-Path $Stamp) { (Get-Content $Stamp -Raw).Trim() } else { "" }
$needPkgs = $needVenv -or ($hash -ne $oldHash)
$netHint  = "Please check that this computer is connected to the internet, then double-click 'Start Siftwell' again.`r`nDetails are in: $SetupLog"

if ($needUv -or $needVenv) {
    Say "Setting up Siftwell. This happens once and takes a couple of minutes..."
    Say ""
} elseif ($needPkgs) {
    Say "Updating Siftwell's components..."
}
if ($needUv -or $needVenv -or $needPkgs) {
    Set-Content -Path $SetupLog -Value ("Siftwell setup " + (Get-Date -Format s)) -Encoding ASCII
}

if ($needUv) {
    Step "Downloading the installer tool (uv)"
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $cmd = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; " +
           "`$ProgressPreference='SilentlyContinue'; irm https://astral.sh/uv/install.ps1 | iex"
    $code = Run-Quiet $ps ("-NoProfile -ExecutionPolicy Bypass -Command `"" + $cmd + "`"")
    if ($code -ne 0 -or -not (Test-UvOk)) { Show-LogTail $SetupLog 8; Fail "Downloading uv failed." $netHint }
}

if ($needVenv) {
    Step "Downloading Python 3.12 and creating Siftwell's private environment"
    $code = Run-Quiet $UvExe ("venv --quiet --clear --managed-python --python 3.12 `"" + $Venv + "`"")
    if ($code -ne 0 -or -not (Test-VenvOk)) { Show-LogTail $SetupLog 8; Fail "Setting up Python failed." $netHint }
    Remove-Item $Stamp -Force -ErrorAction SilentlyContinue
}

if ($needPkgs) {
    Step "Installing Siftwell's packages"
    $code = Run-Quiet $UvExe ("pip install --quiet --python `"" + $Py + "`" -r `"" + $Req + "`"")
    if ($code -ne 0) { Show-LogTail $SetupLog 8; Fail "Installing packages failed." $netHint }
    Set-Content -Path $Stamp -Value $hash -Encoding ASCII
    Step "Done"
    Say ""
}

# 3. Pick a port: the remembered one (default 8766), else the first free one in 8767-8775.
if (-not (Test-PortFree $port)) {
    $busy = $port
    $port = $null
    foreach ($p in (@($DefaultPort) + $FallbackPorts)) {
        if ($p -ne $busy -and (Test-PortFree $p)) { $port = $p; break }
    }
    if (-not $port) { Fail "Ports $DefaultPort to $($FallbackPorts[-1]) are all in use by other programs." "Close some programs or restart the computer, then try again." }
    Say "Port $busy is used by another program, so Siftwell will use port $port."
}
Set-Content -Path $PortFile -Value $port -Encoding ASCII

# 4. Start the server in the background (pythonw: no window; it keeps running after this window closes).
Say "Starting Siftwell..."
$server = Join-Path $App "server.py"
$proc = Start-Process -FilePath $Pyw -ArgumentList ("-X utf8 `"" + $server + "`" " + $port) -WorkingDirectory $App -PassThru
Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII

# 5. Wait until it answers, then open the browser.
for ($i = 0; $i -lt 60; $i++) {
    if (Test-Siftwell $port) {
        Open-Board $port
        exit 0
    }
    if ($proc.HasExited -and (Get-OwnServers).Count -eq 0) { break }
    Start-Sleep -Seconds 1
}
if ($proc.HasExited) {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    # pythonw has nowhere to print an early crash, so run it once more with console Python to capture the error.
    $errLog = Join-Path $Sift "start-error.log"
    $d = Start-Process -FilePath $Py -ArgumentList ("-X utf8 `"" + $server + "`" " + $port) -WorkingDirectory $App `
        -NoNewWindow -PassThru -RedirectStandardOutput "$errLog.out" -RedirectStandardError $errLog
    if (-not $d.WaitForExit(20000)) { try { cmd.exe /c "taskkill /PID $($d.Id) /T /F >nul 2>&1" } catch {} ; Start-Sleep -Milliseconds 500 }
    if (Test-Path "$errLog.out") { Get-Content "$errLog.out" | Add-Content $errLog; Remove-Item "$errLog.out" -Force -ErrorAction SilentlyContinue }
    Show-LogTail $errLog 15
    Fail "Siftwell stopped right after starting." "The lines above may say why (also saved in $errLog and server.log in $DataDir)."
}
Show-LogTail (Join-Path $DataDir "server.log") 15
Fail "Siftwell did not answer within a minute." "It may still be starting. Wait a moment and double-click 'Start Siftwell' again.`r`nLog: $(Join-Path $DataDir 'server.log')"
