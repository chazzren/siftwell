# Siftwell launcher for Windows. Used by "Start Siftwell.cmd" and "Stop Siftwell.cmd".
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\launcher.ps1          start Siftwell and open its window
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\launcher.ps1 -Stop    stop the Siftwell started from this folder
#
# Siftwell opens in its own window (app_window.py: pywebview with the Edge WebView2 that Windows 11 includes). Closing the
# window stops Siftwell, unless "Keep Siftwell available to my phone when the window is closed" is on, or the window
# was opened on a server that was already running (for example the start-at-sign-in one). If the window can't be used
# (pywebview missing, no WebView2) Siftwell opens in the web browser instead and says so.
#
# Nothing is written into the app folder, so it can be deleted and replaced by a newer download at any time:
#   - Python runtime (uv, Python, package cache, virtualenv): %LOCALAPPDATA%\Siftwell\runtime (per computer, rebuilt
#     from the internet if missing; reused by every copy of the app folder, so a new download starts at once).
#   - Your data plus the remembered port and the server's pid: %APPDATA%\JobBoard (JOBBOARD_DATA overrides it).
#     These locations must match paths.py.
# Nothing is written outside your user profile and no admin rights are needed.
# An older install's <app>\.venv still works as a fallback if the runtime can't be set up (it's never deleted).
#
# Optional environment variables (mainly for testing):
#   SIFTWELL_PORT=8790        use this port instead of the remembered one / 8766
#   SIFTWELL_RUNTIME=<dir>    keep the Python runtime here instead of %LOCALAPPDATA%\Siftwell\runtime
#   SIFTWELL_NO_BROWSER=1     don't open the Siftwell window (or a browser)
#   SIFTWELL_NO_PAUSE=1       don't wait a few seconds after Stop
# Exit code 0 = fine; anything else = the .cmd keeps the window open so the message can be read.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less files in the legacy code page.

param([switch]$Stop)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow in 5.1 with the progress bar on

function Full-Path($p) {
    # Like Python's os.path.abspath(os.path.expanduser(p)), as paths.py does.
    if ($p -eq "~") { $p = $HOME } elseif ($p -match '^~[\\/]') { $p = Join-Path $HOME $p.Substring(2) }
    return [IO.Path]::GetFullPath($p).TrimEnd("\")
}

$App    = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path.TrimEnd("\")
$DataDir = if ($env:JOBBOARD_DATA) { Full-Path $env:JOBBOARD_DATA } else { Join-Path $env:APPDATA "JobBoard" }
if ($env:JOBBOARD_DATA) { $env:JOBBOARD_DATA = $DataDir }   # the server resolves it from another folder
$Rt     = if ($env:SIFTWELL_RUNTIME) { Full-Path $env:SIFTWELL_RUNTIME } else { Join-Path $env:LOCALAPPDATA "Siftwell\runtime" }
$UvDir  = Join-Path $Rt "uv"
$UvExe  = Join-Path $UvDir "uv.exe"
$Venv   = Join-Path $Rt "venv"
$Py     = Join-Path $Venv "Scripts\python.exe"
$Pyw    = Join-Path $Venv "Scripts\pythonw.exe"
$Req    = Join-Path $App "requirements.txt"
$Stamp  = Join-Path $Rt "requirements.sha256"
$SetupLog = Join-Path $Rt "setup.log"
$PortFile = Join-Path $DataDir "port"
$PidFile  = Join-Path $DataDir "server.pid"
$WinPidFile = Join-Path $DataDir "window.pid"   # written by app_window.py
$AppWindow  = Join-Path $App "app_window.py"
$ErrLog   = Join-Path $DataDir "start-error.log"
$LegacyPortFile = Join-Path $App ".siftwell\port"        # older launchers kept the port here
$LegacyPy  = Join-Path $App ".venv\Scripts\python.exe"   # older launchers' environment
$LegacyPyw = Join-Path $App ".venv\Scripts\pythonw.exe"
$DefaultPort = 8766
$FallbackPorts = 8767..8775

# Keep uv and its downloads in the runtime folder.
$env:UV_INSTALL_DIR        = $UvDir
$env:UV_UNMANAGED_INSTALL  = $UvDir          # no install receipt elsewhere, no PATH change
$env:UV_NO_MODIFY_PATH     = "1"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Rt "python"
$env:UV_PYTHON_BIN_DIR     = Join-Path $Rt "python-bin"
$env:UV_CACHE_DIR          = Join-Path $Rt "cache"
$env:UV_NO_CONFIG          = "1"             # ignore any uv.toml the user may have
$env:PYTHONUTF8            = "1"
$env:PYTHONPYCACHEPREFIX   = Join-Path $Rt "pycache"   # compiled .pyc files stay out of the app folder
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

function Test-OwnProcess($p) {
    # A Siftwell server started from THIS folder. Two ways to qualify:
    #  1. The executable is a Python from the runtime folder or this app's .venv, and this folder's server.py (or
    #     getting_started.py --serve, the start-at-sign-in entry) is the script it runs (python flags like -X utf8 ok).
    #  2. Any other Python, but the command line is exactly "<python> [-X utf8] <app>\server.py [port]" or
    #     "<python> [-X utf8] <app>\getting_started.py --serve", nothing else.
    # An editor, or `python -c "...server.py..."` that merely mentions the path, is never matched (or killed).
    if (-not $p -or -not $p.CommandLine) { return $false }
    $cl = $p.CommandLine
    $srv = [regex]::Escape($App + "\server.py")
    $gs  = [regex]::Escape($App + "\getting_started.py")
    $exe = [string]$p.ExecutablePath
    $inRt = $exe -and ($exe.StartsWith($Rt + "\", [StringComparison]::OrdinalIgnoreCase) -or
                       $exe.StartsWith((Join-Path $App ".venv") + "\", [StringComparison]::OrdinalIgnoreCase))
    $pyexe = '(?:"(?:[^"]*[\x5c/])?pythonw?[\d.]*(?:\.exe)?"|(?:\S*[\x5c/])?pythonw?[\d.]*(?:\.exe)?)'
    if ($inRt) { $lead = '^\s*("[^"]*"|\S+)\s+(?:-X\s+\S+\s+|-[BEIOsSuvx]+\s+)*' }
    else       { $lead = '^\s*' + $pyexe + '\s+(?:-X\s+utf8\s+)?' }
    return ($cl -match ($lead + '"?' + $srv + '"?(\s+\d+)?\s*$') -or $cl -match ($lead + '"?' + $gs + '"?\s+--serve\s*$'))
}

function Test-PidFileServer($p) {
    # DATA/server.pid names a Siftwell server of ours when that process is a live Python running a script called
    # server.py (or getting_started.py --serve), with the path written absolute or relative. Older installs (the
    # "Job Board server" scheduled task) start "<base python>\pythonw.exe -X utf8 server.py": relative path, base
    # interpreter, nothing in the command line pointing at this folder. A relative path can't be checked against this
    # folder (the pid file is ours), but an absolute one that points into another app folder is not ours to stop.
    # Anything else (an editor, `python -c "...server.py..."`, a non-Python process) is refused.
    if (-not $p -or -not $p.CommandLine) { return $false }
    if ([string]$p.Name -notmatch '^pythonw?[\d.]*\.exe$') { return $false }
    $lead = '^\s*(?:"[^"]*"|\S+)\s+(?:-X\s+\S+\s+|-[BEIOsSuvx]+\s+)*'
    $m = [regex]::Match($p.CommandLine, $lead + '(?:"([^"]*[\x5c/])?(server\.py)"|(\S*[\x5c/])?(server\.py))(?:\s+\d+)?\s*$')
    $g = [regex]::Match($p.CommandLine, $lead + '(?:"([^"]*[\x5c/])?(getting_started\.py)"|(\S*[\x5c/])?(getting_started\.py))\s+--serve\s*$')
    $hit = if ($m.Success) { $m } elseif ($g.Success) { $g } else { $null }
    if (-not $hit) { return $false }
    $dir = if ($hit.Groups[1].Success) { $hit.Groups[1].Value } elseif ($hit.Groups[3].Success) { $hit.Groups[3].Value } else { "" }
    if ($dir -and $dir -match '^(?:[A-Za-z]:|[\x5c/]{2})') {
        # absolute: must be this app folder
        return ($dir.TrimEnd('\', '/') -ieq $App)
    }
    return $true
}

function Stop-AppWindow {
    # The Siftwell window of this folder (pid in DATA\window.pid), so it doesn't sit there pointing at a stopped server.
    if (-not (Test-Path $WinPidFile)) { return $false }
    $stopped = $false
    $p = (Get-Content $WinPidFile -Raw -ErrorAction SilentlyContinue)
    if ($p -and $p.Trim() -match '^\d+$') {
        $w = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $p.Trim()) -ErrorAction SilentlyContinue
        if ($w -and $w.CommandLine -and ([string]$w.Name -match '^pythonw?[\d.]*\.exe$') -and
            $w.CommandLine.IndexOf($AppWindow, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            try { cmd.exe /c "taskkill /PID $($p.Trim()) /T /F >nul 2>&1" } catch {}
            $stopped = $true
        }
    }
    Remove-Item $WinPidFile -Force -ErrorAction SilentlyContinue
    return $stopped
}

function Get-OwnServers {
    @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue | Where-Object { Test-OwnProcess $_ })
}

function Read-Port {
    # Like paths.read_port: only 1024-65535 count (anything else is ignored).
    if ($env:SIFTWELL_PORT -match '^\d+$' -and [int64]$env:SIFTWELL_PORT -ge 1024 -and [int64]$env:SIFTWELL_PORT -le 65535) { return [int]$env:SIFTWELL_PORT }
    foreach ($f in @($PortFile, $LegacyPortFile)) {
        if (Test-Path $f) {
            $p = (Get-Content $f -Raw -ErrorAction SilentlyContinue)
            if ($p -and $p.Trim() -match '^\d+$' -and [int64]$p.Trim() -ge 1024 -and [int64]$p.Trim() -le 65535) { return [int]$p.Trim() }
        }
    }
    return $DefaultPort
}

function Test-HasWebview($exe) {
    # Is the pywebview package installed for this Python? (find_spec only looks; nothing is imported.)
    try {
        $null = & $exe -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('webview') else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-WindowPython {
    # pythonw.exe of an environment that has pywebview (the runtime first, then an older install's .venv), or $null.
    foreach ($pair in @(@($Py, $Pyw), @($LegacyPy, $LegacyPyw))) {
        if ((Test-Path $pair[1]) -and (Test-PyOk $pair[0]) -and (Test-HasWebview $pair[0])) { return $pair[1] }
    }
    return $null
}

function Open-Board($port, $ownsServer) {
    # Opens the Siftwell window (closing it stops the server when $ownsServer, i.e. we just started it for this window),
    # else the browser, saying so.
    $url = "http://127.0.0.1:$port/"
    if ($env:SIFTWELL_NO_BROWSER) { Say "Siftwell is running at $url"; return }
    $wp = Find-WindowPython
    if ($wp) {
        Say "Opening the Siftwell window"
        $env:SIFTWELL_PORT = [string]$port     # the window uses the same port as this launcher
        $a = "-X utf8 `"" + $AppWindow + "`""
        if ($ownsServer) { $a += " --owns-server" }
        $null = Start-Process -FilePath $wp -ArgumentList $a -WorkingDirectory $App -PassThru
        return
    }
    Say "Siftwell's own window isn't available on this computer (it needs the pywebview package and Microsoft Edge WebView2),"
    Say "so Siftwell opens in your web browser instead. It keeps running until you double-click 'Stop Siftwell'."
    Say "Opening $url"
    Start-Process $url
}

function Run-Quiet($exe, [string]$argLine) {
    # Runs a program with its output going to setup.log; returns the exit code.
    # (Start-Process instead of '&' so Windows PowerShell 5.1 doesn't turn progress text on stderr into errors.)
    $out = "$SetupLog.out"; $err = "$SetupLog.err"
    $p = Start-Process -FilePath $exe -ArgumentList $argLine -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err -WorkingDirectory $Rt
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

function Test-PyOk($exe) {
    if (-not (Test-Path $exe)) { return $false }
    try {
        $v = & $exe -c "import sys;print(sys.version_info[:2]>=(3,12))" 2>$null
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
    $hadWindow = Stop-AppWindow
    $procs = Get-OwnServers
    $ids = @($procs | ForEach-Object { [int]$_.ProcessId })
    if (Test-Path $PidFile) {
        $p = (Get-Content $PidFile -Raw -ErrorAction SilentlyContinue)
        if ($p -and $p.Trim() -match '^\d+$') {
            # Only trust the pid file if that process is still a Siftwell server (see Test-PidFileServer).
            $pp = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $p.Trim()) -ErrorAction SilentlyContinue
            if ((Test-OwnProcess $pp) -or (Test-PidFileServer $pp)) { $ids += [int]$p.Trim() }
            elseif (-not $pp) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }   # stale
        }
    }
    $ids = @($ids | Sort-Object -Unique)
    if ($ids.Count -eq 0) {
        if ($hadWindow) { Say "The Siftwell window was closed." } else { Say "Siftwell isn't running (from this folder)." }
    } else {
        foreach ($id in $ids) {
            # /T also ends anything the server started (for example a running job update).
            try { cmd.exe /c "taskkill /PID $id /T /F >nul 2>&1" } catch {}
        }
        Start-Sleep -Milliseconds 500
        $left = @($ids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        if ((Get-OwnServers).Count -gt 0 -or $left.Count -gt 0) { Fail "Some Siftwell processes are still running." "Try again, or restart the computer." }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Say "Siftwell has stopped. Double-click 'Start Siftwell' to start it again."
    }
    if (-not $env:SIFTWELL_NO_PAUSE) { Start-Sleep -Seconds 3 }
    exit 0
}

# ---------------------------------------------------------------- start

$Host.UI.RawUI.WindowTitle = "Siftwell"
$port = Read-Port

# One-time setup (or repair) of the runtime: uv, Python, packages (pywebview for the window included). Skipped when the
# runtime is already there and requirements.txt hasn't changed since it was set up (any copy of the app folder shares it).
$netHint = "Please check that this computer is connected to the internet, then double-click 'Start Siftwell' again.`r`nDetails are in: $SetupLog"

function Setup-Runtime {
    # Returns "" on success, else a short message (details in setup.log).
    if ($script:needUv -or $script:needVenv) {
        Say "Setting up Siftwell. This happens once and takes a couple of minutes..."
        Say ""
    } elseif ($script:needPkgs) {
        Say "Updating Siftwell's components..."
    }
    if ($script:needUv -or $script:needVenv -or $script:needPkgs) {
        Set-Content -Path $SetupLog -Value ("Siftwell setup " + (Get-Date -Format s) + " for " + $App) -Encoding ASCII
    }
    if ($script:needUv) {
        Step "Downloading the installer tool (uv)"
        New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
        $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $cmd = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; " +
               "`$ProgressPreference='SilentlyContinue'; irm https://astral.sh/uv/install.ps1 | iex"
        $code = Run-Quiet $ps ("-NoProfile -ExecutionPolicy Bypass -Command `"" + $cmd + "`"")
        if ($code -ne 0 -or -not (Test-UvOk)) { return "Downloading uv failed." }
    }
    if ($script:needVenv) {
        Step "Downloading Python 3.12 and creating Siftwell's private environment"
        $code = Run-Quiet $UvExe ("venv --quiet --clear --managed-python --python 3.12 `"" + $Venv + "`"")
        if ($code -ne 0 -or -not (Test-PyOk $Py)) { return "Setting up Python failed." }
        Remove-Item $Stamp -Force -ErrorAction SilentlyContinue
    }
    if ($script:needPkgs) {
        Step "Installing Siftwell's packages"
        $code = Run-Quiet $UvExe ("pip install --quiet --python `"" + $Py + "`" -r `"" + $Req + "`"")
        if ($code -ne 0) { return "Installing packages failed." }
        Set-Content -Path $Stamp -Value $script:hash -Encoding ASCII
        Step "Done"
        Say ""
    }
    return ""
}

function Ensure-Runtime {
    # Returns "" when the runtime is ready, else a short message.
    New-Item -ItemType Directory -Force -Path $Rt | Out-Null
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $script:needUv   = -not (Test-UvOk)
    $script:needVenv = -not (Test-PyOk $Py)
    $script:hash     = Get-ReqHash
    $oldHash  = if (Test-Path $Stamp) { (Get-Content $Stamp -Raw).Trim() } else { "" }
    $script:needPkgs = $script:needVenv -or ($script:hash -ne $oldHash)
    return (Setup-Runtime)
}

# 1. Already running? Open its window.
if (Test-Siftwell $port) {
    $problem = Ensure-Runtime
    if ($problem) { Show-LogTail $SetupLog 4; Say ""; Say "Couldn't finish updating Siftwell's components ($problem)." }
    Open-Board $port $false
    exit 0
}

# 1b. Started from this folder but not answering yet (e.g. double-clicked twice)? Wait for it.
$own = Get-OwnServers
if ($own.Count -gt 0) {
    $m = [regex]::Match(($own[0].CommandLine), 'server\.py"?\s+(\d+)')
    if ($m.Success) { $port = [int]$m.Groups[1].Value }
    Say "Siftwell is starting up..."
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Siftwell $port) {
            $problem = Ensure-Runtime
            if ($problem) { Show-LogTail $SetupLog 4; Say ""; Say "Couldn't finish updating Siftwell's components ($problem)." }
            Open-Board $port $false
            exit 0
        }
        Start-Sleep -Seconds 1
    }
    Fail "Siftwell is running but not answering on port $port." "Double-click 'Stop Siftwell', then 'Start Siftwell' again."
}

# 2. Set up the runtime (fatal if it can't be done and there is no older environment to use).
$problem = Ensure-Runtime
if ($problem) {
    if (Test-PyOk $LegacyPy) {
        # An older install's environment inside the app folder still works: use it this time.
        Show-LogTail $SetupLog 4
        Say ""
        Say "Couldn't finish setting up ($problem); using the older Python environment in this folder for now."
        $Py = $LegacyPy; $Pyw = $LegacyPyw
    } else {
        Show-LogTail $SetupLog 8
        Fail $problem $netHint
    }
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
if (-not $env:SIFTWELL_PORT) { Set-Content -Path $PortFile -Value $port -Encoding ASCII }   # a one-off SIFTWELL_PORT is never remembered

# 4. Start the server in the background (pythonw: no window). The Siftwell window below owns it: closing that window
#    stops it, unless "keep available to my phone" is on.
Say "Starting Siftwell..."
$server = Join-Path $App "server.py"
$proc = Start-Process -FilePath $Pyw -ArgumentList ("-X utf8 `"" + $server + "`" " + $port) -WorkingDirectory $App -PassThru
Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII

# 5. Wait until it answers, then open the Siftwell window.
for ($i = 0; $i -lt 60; $i++) {
    if (Test-Siftwell $port) {
        Open-Board $port $true
        exit 0
    }
    if ($proc.HasExited -and (Get-OwnServers).Count -eq 0) { break }
    Start-Sleep -Seconds 1
}
if ($proc.HasExited) {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    # pythonw has nowhere to print an early crash, so run it once more with console Python to capture the error.
    $d = Start-Process -FilePath $Py -ArgumentList ("-X utf8 `"" + $server + "`" " + $port) -WorkingDirectory $App `
        -NoNewWindow -PassThru -RedirectStandardOutput "$ErrLog.out" -RedirectStandardError $ErrLog
    if (-not $d.WaitForExit(20000)) { try { cmd.exe /c "taskkill /PID $($d.Id) /T /F >nul 2>&1" } catch {} ; Start-Sleep -Milliseconds 500 }
    if (Test-Path "$ErrLog.out") { Get-Content "$ErrLog.out" | Add-Content $ErrLog; Remove-Item "$ErrLog.out" -Force -ErrorAction SilentlyContinue }
    Show-LogTail $ErrLog 15
    Fail "Siftwell stopped right after starting." "The lines above may say why (also saved in $ErrLog and server.log in $DataDir)."
}
Show-LogTail (Join-Path $DataDir "server.log") 15
Fail "Siftwell did not answer within a minute." "It may still be starting. Wait a moment and double-click 'Start Siftwell' again.`r`nLog: $(Join-Path $DataDir 'server.log')"
