# Job Board - one-time setup on Windows 11.
# Run from this folder in PowerShell:   powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
# Re-running it is safe: it skips anything already done.

$ErrorActionPreference = "Stop"
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $App
function Say($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "   $m" -ForegroundColor Yellow }

# 1-2. Python 3.12+ in a private .venv, plus packages.
# Prefers uv (no system Python needed); falls back to py/python, then winget.
Say "Setting up Python and the app's packages"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) { $uv = Get-Item "$env:USERPROFILE\.local\bin\uv.exe" -ErrorAction SilentlyContinue }
$venvOk = $false
if (Test-Path ".venv\Scripts\python.exe") {
    $v = & .\.venv\Scripts\python.exe -c "import sys;print(sys.version_info[:2]>=(3,12))" 2>$null
    $venvOk = ($v -eq "True")
}
if ($uv) {
    $uvExe = if ($uv.Source) { $uv.Source } else { $uv.FullName }
    if (-not $venvOk) { & $uvExe venv --managed-python --python 3.12 .venv }
    & $uvExe pip install --quiet --python .\.venv\Scripts\python.exe -r requirements.txt
} else {
    if (-not $venvOk) {
        $py = $null
        foreach ($c in @("py -3.12", "py -3", "python")) {
            try {
                $v = & cmd /c "$c -c ""import sys;print(sys.version_info[:2]>=(3,12))"" 2>nul"
                if ($v -eq "True") { $py = $c; break }
            } catch {}
        }
        if (-not $py) {
            Warn "Python 3.12 not found. Installing it with winget (you may see a prompt)..."
            winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
            $py = "py -3.12"
        }
        Write-Host "   Using: $py"
        cmd /c "$py -m venv .venv"
    }
    & .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
}
Write-Host "   Done."

# 3. Apps the board uses (you sign in to these yourself)
Say "Checking Claude Code, Codex and a browser for PDFs"
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) { $claude = Get-Item "$env:USERPROFILE\.local\bin\claude.exe" -ErrorAction SilentlyContinue }
if ($claude) { Write-Host "   Claude Code: found" } else {
    Warn "Claude Code is not installed. Install it (see README_WINDOWS.md), then run:  claude   and sign in with your Claude account."
}
$codex = Get-Command codex -ErrorAction SilentlyContinue
if ($codex) { Write-Host "   Codex: found" } else {
    Warn "Codex is not installed (only needed for Astra resume reviews). See README_WINDOWS.md."
}
$edge = Test-Path "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
$chrome = (Test-Path "$env:ProgramFiles\Google\Chrome\Application\chrome.exe") -or (Test-Path "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
if ($edge -or $chrome) { Write-Host "   PDF browser: found" } else { Warn "Neither Edge nor Chrome found; resume PDFs won't build." }

# 4. Let phones and other computers on the home network reach the board
Say "Allowing port 8766 on the home network"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    if (-not (Get-NetFirewallRule -DisplayName "Job Board (8766)" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "Job Board (8766)" -Direction Inbound -Protocol TCP -LocalPort 8766 -Profile Private -Action Allow | Out-Null
    }
    Write-Host "   Firewall rule in place (private networks only)."
} else {
    Warn "Skipped: needs an administrator PowerShell. Re-run this script as administrator once,"
    Warn "or click 'Allow' on private networks when Windows asks the first time the server starts."
}

# 5. Start the server automatically when you sign in, and wake the PC for the 5:30 AM update
Say "Setting up automatic start"
$pyw = Join-Path $App ".venv\Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-X utf8 server.py" -WorkingDirectory $App
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Job Board server" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Runs the job board web server (http://127.0.0.1:8766)." -Force | Out-Null
$wakeAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c exit"
$wakeTrigger = New-ScheduledTaskTrigger -Daily -At 5:25am
$wakeSettings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Job Board wake for nightly update" -Action $wakeAction -Trigger $wakeTrigger -Settings $wakeSettings `
    -Description "Wakes the PC at 5:25 AM so the 5:30 AM job-listing update runs (the server keeps it awake until done)." -Force | Out-Null
Write-Host "   The server now starts when you sign in, and the PC wakes at 5:25 AM (if plugged in and sleeping)."

# 6. Start it now
# Your data (profiles, access key, logs) lives outside the app folder; JOBBOARD_DATA overrides the location.
$DataDir = if ($env:JOBBOARD_DATA) { $env:JOBBOARD_DATA } else { Join-Path $env:APPDATA "JobBoard" }
Say "Starting the job board"
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like "*server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName "Job Board server"
Start-Sleep -Seconds 4
try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8766/" -TimeoutSec 10 | Out-Null; Write-Host "   Running." }
catch { Warn "It didn't answer yet. Check server.log in $DataDir, or run start_server.cmd to see errors." }

$key = (Get-Content (Join-Path $DataDir "access_key") -Raw).Trim()
# The home-network address: the connected adapter with a default gateway (skips VPN tunnels and virtual adapters)
$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1).IPv4Address.IPAddress
if (-not $ip) { $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" -and $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress }
Say "All set"
Write-Host "   On this PC:          http://127.0.0.1:8766"
Write-Host "   Phones / other PCs:  http://${ip}:8766/?k=$key"
Write-Host "   (Keep that second link private; it contains the access key.)"
