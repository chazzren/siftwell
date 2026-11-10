"""Automatic job updates: the one setting (DATA/schedule.json) and the OS-level job behind "Even when Siftwell is closed".

Modes: "off" (default for new installs), "running" (server.scheduler runs the update at `time` while Siftwell is open) and
"closed" (a user-level OS job runs siftwell_update.py at `time` even when Siftwell isn't open; the server's own scheduler
stays quiet so nothing runs twice). {"mode", "time": "HH:MM", "wake": bool}; "enabled" is kept in the file for older copies.

Defaults: schedule.json present -> mapped (enabled -> "running"); absent and the install already has profiles -> running
at 05:30 (the household as it was before this setting existed); absent and no profiles -> off. ensure_initialized() writes
that decision down on the first start, so adding the first profile later never turns updates on.

OS job (no administrator permission): Windows Task Scheduler task "Siftwell automatic update" for the current user (with
WakeToRun if chosen), a Mac LaunchAgent with StartCalendarInterval, a Linux user crontab line. Nothing real is created or
removed while JOBBOARD_DATA or SIFTWELL_RUNTIME is set, unless SIFTWELL_TEST_TASKS points at a stub file (the same JSON
file getting_started.py uses to stand in for the Windows tasks; Mac/Linux just skip). The older "Job Board wake for
nightly update" task is only ever looked at, never changed."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

import osdeps
import paths
import people

FILE = os.path.join(paths.DATA, "schedule.json")
MODES = ("off", "running", "closed")
DEFAULT_TIME = "05:30"
TASK_NAME = "Siftwell automatic update"
MAC_LABEL = "com.siftwell.update"
CRON_MARK = "# siftwell-automatic-update"
APP = paths.APP
RUNNER = os.path.join(APP, "siftwell_update.py")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if osdeps.WINDOWS else 0
_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def valid_time(t):
    return bool(_TIME.fullmatch(str(t)))


# ---------------------------------------------------------------- the setting
def _read():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return None


def get():
    """{"mode", "time", "wake"} (cheap: reads one small file)."""
    s = _read()
    if s is None:
        return {"mode": "running" if os.path.exists(people.INDEX) else "off", "time": DEFAULT_TIME, "wake": False}
    mode = s.get("mode")
    if mode not in MODES:
        mode = "running" if s.get("enabled", True) else "off"
    t = s.get("time")
    return {"mode": mode, "time": t if valid_time(t) else DEFAULT_TIME, "wake": bool(s.get("wake"))}


def _save(c):
    paths.dump_json_atomic(FILE, {"mode": c["mode"], "enabled": c["mode"] != "off", "time": c["time"], "wake": bool(c["wake"])})


def ensure_initialized():
    """Server start: write the decision down once when there is no schedule.json yet (see the module doc)."""
    if _read() is None:
        try:
            _save(get())
        except OSError:
            pass


def schedule():
    """What server.schedule() returns on every status poll: no subprocesses."""
    c = get()
    return dict(c, enabled=c["mode"] != "off")


def next_time(c=None):
    """The next time the update is due (any mode but off), for display."""
    c = c or get()
    if c["mode"] == "off":
        return None
    h, m = (int(x) for x in c["time"].split(":"))
    now = dt.datetime.now()
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + dt.timedelta(days=1)


def scheduler_next():
    """What server.scheduler waits for: only the "while Siftwell is running" mode (never when the OS job does it)."""
    c = get()
    return next_time(c) if c["mode"] == "running" else None


# ---------------------------------------------------------------- the OS job
def _stub():
    return os.environ.get("SIFTWELL_TEST_TASKS")


def _test_data():
    return bool(os.environ.get("JOBBOARD_DATA") or os.environ.get("SIFTWELL_RUNTIME"))


def _os_live():
    """False when OS-level changes must be skipped: test data without a stub (never touch the real machine)."""
    if _test_data() and not _stub():
        return False
    if _stub() and not osdeps.WINDOWS:
        return False      # the stub file stands in for Windows tasks only
    return True


def closed_supported():
    if osdeps.WINDOWS or osdeps.MAC:
        return True
    return bool(shutil.which("crontab"))


def _gs():
    import getting_started
    return getting_started


def _want(c):
    py = _gs()._app_python()
    return {"exe": py, "args": f'-X utf8 "{RUNNER}"', "wd": APP, "time": c["time"], "wake": bool(c["wake"]) and osdeps.WINDOWS}


def _same(a, b):
    n = lambda p: os.path.normcase(os.path.normpath(p or "."))
    return (n(a.get("exe")) == n(b.get("exe")) and n(a.get("wd")) == n(b.get("wd"))
            and " ".join((a.get("args") or "").split()).lower() == " ".join((b.get("args") or "").split()).lower()
            and a.get("time") == b.get("time") and bool(a.get("wake")) == bool(b.get("wake")))


# ---- Windows
def _ps(script, env=None, timeout=60):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       env=dict(os.environ, **(env or {})), capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _win_query():
    """{exe, args, wd, time, wake, enabled} or {} when the task doesn't exist."""
    if _stub():
        import getting_started as G
        x = ((G._test_tasks() or {}).get("tasks") or {}).get(TASK_NAME)
        return dict(x, wake=bool(x.get("wake")), enabled=bool(x.get("enabled", True))) if x else {}
    ps = ("$t=Get-ScheduledTask -TaskName $env:SW_NAME -ErrorAction SilentlyContinue; "
          "if($t){$b=[string]$t.Triggers[0].StartBoundary;@{enabled=[bool]$t.Settings.Enabled;exe=[string]$t.Actions[0].Execute;"
          "args=[string]$t.Actions[0].Arguments;wd=[string]$t.Actions[0].WorkingDirectory;wake=[bool]$t.Settings.WakeToRun;"
          "time=$(if($b.Length -ge 16){$b.Substring(11,5)}else{''})}|ConvertTo-Json -Compress}")
    try:
        rc, out = _ps(ps, {"SW_NAME": TASK_NAME})
        return json.loads(out) if out.startswith("{") else {}
    except Exception:
        return {}


WIN_REGISTER = ("$ErrorActionPreference='Stop';"
                "$a=New-ScheduledTaskAction -Execute $env:SW_EXE -Argument $env:SW_ARGS -WorkingDirectory $env:SW_DIR;"
                "$t=New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($env:SW_TIME,'HH:mm',[Globalization.CultureInfo]::InvariantCulture));"
                "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
                "-ExecutionTimeLimit (New-TimeSpan -Hours 8) @wakeArgs;"
                "$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited;"
                "Register-ScheduledTask -TaskName $env:SW_NAME -Action $a -Trigger $t -Settings $s -Principal $p "
                "-Description 'Siftwell automatic job update (made by Siftwell; change it in Settings)' -Force | Out-Null")


def _win_register(w):
    if _stub():
        import getting_started as G
        d = G._test_tasks() or {"tasks": {}}
        d.setdefault("tasks", {})[TASK_NAME] = {"enabled": True, "state": "Ready", "exe": w["exe"], "args": w["args"],
                                               "wd": w["wd"], "time": w["time"], "wake": w["wake"]}
        d.setdefault("calls", []).append({"op": "register", "task": TASK_NAME, "time": w["time"], "wake": w["wake"]})
        G._test_save(d)
        return
    script = ("$wakeArgs=@{};" + ("$wakeArgs.WakeToRun=$true;" if w["wake"] else "") + WIN_REGISTER)
    rc, out = _ps(script, {"SW_NAME": TASK_NAME, "SW_EXE": w["exe"], "SW_ARGS": w["args"], "SW_DIR": w["wd"], "SW_TIME": w["time"]})
    if rc != 0:
        raise RuntimeError(out[:240] or "Task Scheduler refused the task")


def _win_unregister():
    if _stub():
        import getting_started as G
        d = G._test_tasks() or {"tasks": {}}
        had = (d.get("tasks") or {}).pop(TASK_NAME, None)
        d.setdefault("calls", []).append({"op": "unregister", "task": TASK_NAME, "existed": bool(had)})
        G._test_save(d)
        return
    rc, out = _ps("Unregister-ScheduledTask -TaskName $env:SW_NAME -Confirm:$false -ErrorAction SilentlyContinue", {"SW_NAME": TASK_NAME})
    if _win_query():
        raise RuntimeError(out[:240] or "Task Scheduler wouldn't remove the task")


# ---- Mac
def _mac_plist():
    return os.path.expanduser(f"~/Library/LaunchAgents/{MAC_LABEL}.plist")


def _mac_query():
    import plistlib
    p = _mac_plist()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "rb") as f:
            d = plistlib.load(f)
        a = d.get("ProgramArguments") or []
        t = d.get("StartCalendarInterval") or {}
        return {"exe": a[0] if a else "", "args": " ".join(a[1:]), "wd": d.get("WorkingDirectory"), "wake": False,
                "time": "%02d:%02d" % (t.get("Hour", 0), t.get("Minute", 0))}
    except Exception:
        return {"exe": "?"}


def _mac_register(w):
    import plistlib
    p = _mac_plist()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    h, m = (int(x) for x in w["time"].split(":"))
    with open(p, "wb") as f:
        plistlib.dump({"Label": MAC_LABEL, "ProgramArguments": [w["exe"], "-X", "utf8", RUNNER], "WorkingDirectory": APP,
                       "StartCalendarInterval": {"Hour": h, "Minute": m}, "RunAtLoad": False,
                       "StandardOutPath": os.path.join(paths.data(), "update-launchd.log"),
                       "StandardErrorPath": os.path.join(paths.data(), "update-launchd.log")}, f)
    subprocess.run(["launchctl", "unload", p], capture_output=True, timeout=30)
    r = subprocess.run(["launchctl", "load", "-w", p], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "launchctl failed").strip()[:200])


def _mac_unregister():
    p = _mac_plist()
    if os.path.exists(p):
        subprocess.run(["launchctl", "unload", p], capture_output=True, timeout=30)
        os.remove(p)


# ---- Linux
def _cron_lines():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
    return [] if r.returncode != 0 else r.stdout.splitlines()


def _cron_put(lines):
    r = subprocess.run(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""), capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "crontab refused the change").strip()[:200])


def _linux_query():
    for ln in _cron_lines():
        if ln.rstrip().endswith(CRON_MARK):
            parts = ln.split(None, 5)
            try:
                return {"time": "%02d:%02d" % (int(parts[1]), int(parts[0])), "wake": False, "cmd": parts[5]}
            except (IndexError, ValueError):
                return {"time": "", "cmd": ln}
    return {}


def _linux_cmd(w):
    import shlex
    return f"cd {shlex.quote(APP)} && {shlex.quote(w['exe'])} -X utf8 {shlex.quote(RUNNER)} >/dev/null 2>&1 {CRON_MARK}"


def _linux_register(w):
    h, m = (int(x) for x in w["time"].split(":"))
    keep = [ln for ln in _cron_lines() if not ln.rstrip().endswith(CRON_MARK)]
    _cron_put(keep + [f"{m} {h} * * * {_linux_cmd(w)}"])


def _linux_unregister():
    if any(ln.rstrip().endswith(CRON_MARK) for ln in _cron_lines()):
        _cron_put([ln for ln in _cron_lines() if not ln.rstrip().endswith(CRON_MARK)])


def os_query():
    """The OS job as it is now ({} when none). Raises nothing."""
    try:
        return _win_query() if osdeps.WINDOWS else _mac_query() if osdeps.MAC else (_linux_query() if shutil.which("crontab") else {})
    except Exception:
        return {}


def _matches(q, w):
    if not q:
        return False
    if osdeps.WINDOWS or osdeps.MAC:
        return _same(q, w) and q.get("enabled", True)
    return q.get("time") == w["time"] and (q.get("cmd") or "") == _linux_cmd(w)


def os_install(c):
    if not _os_live():
        return "skipped"
    w = _want(c)
    if osdeps.WINDOWS:
        _win_register(w)
    elif osdeps.MAC:
        _mac_register(w)
    else:
        _linux_register(w)
    _record("OS update job set", f"{c['time']}" + (", wake" if w["wake"] else ""))
    return "ok"


def os_remove():
    if not _os_live():
        return "skipped"
    if osdeps.WINDOWS:
        _win_unregister()
    elif osdeps.MAC:
        _mac_unregister()
    else:
        _linux_unregister()
    _record("OS update job removed")
    return "ok"


def _record(action, detail=""):
    try:
        import actionlog
        actionlog.log("automatic updates: " + action, None, None, detail)
    except Exception:
        pass


# ---------------------------------------------------------------- change the setting
def apply(body):
    """Apply {"mode", "time", "wake"} (or the old {"enabled"}); returns status(). Raises ValueError with a message for the
    person. Ordering guarantees the two schedulers are never both active: moving to "closed" saves the setting (server
    scheduler goes quiet) before the OS job is made; leaving "closed" removes the OS job before saving."""
    cur = get()
    new = dict(cur)
    if "mode" in body:
        if body["mode"] not in MODES:
            raise ValueError("Choose Off, While Siftwell is running, or Even when Siftwell is closed.")
        new["mode"] = body["mode"]
    elif "enabled" in body:
        new["mode"] = ("running" if cur["mode"] == "off" else cur["mode"]) if body["enabled"] else "off"
    if "time" in body:
        if not valid_time(body["time"]):
            raise ValueError("Use a time like 05:30.")
        new["time"] = body["time"]
    if "wake" in body:
        new["wake"] = bool(body["wake"])
    if new["mode"] == "closed" and not closed_supported():
        raise ValueError("Running when Siftwell is closed isn't available on this computer (no crontab).")
    if new["mode"] == "closed":
        _save(new)
        try:
            os_install(new)
        except Exception as e:
            try:
                _save(cur)
            except OSError:
                pass
            raise ValueError("Couldn't set up the automatic job: " + str(e)[:200])
    else:
        if cur["mode"] == "closed":
            try:
                os_remove()
            except Exception as e:
                raise ValueError("Couldn't remove the automatic job, so nothing was changed: " + str(e)[:200])
        _save(new)
    if (new["mode"], new["time"]) != (cur["mode"], cur["time"]) or new["wake"] != cur["wake"] or _read() is None:
        import actionlog
        actionlog.log("settings saved", None, None, f"automatic updates: {new['mode']} {new['time']}" + (" wake" if new["wake"] else ""))
    return status()


def status():
    """Everything the two controls show (runs a PowerShell query on Windows, so not for every status poll)."""
    c = get()
    nr = next_time(c)
    out = dict(c, enabled=c["mode"] != "off", next_run=nr.isoformat(timespec="minutes") if nr else None,
               os="windows" if osdeps.WINDOWS else "mac" if osdeps.MAC else "linux",
               portable=paths.PORTABLE, closed_ok=closed_supported(), wake_ok=bool(osdeps.WINDOWS), legacy_wake=False, job=False, job_ok=False)
    try:
        if osdeps.WINDOWS:
            out["legacy_wake"] = bool(_gs()._wake_exists())
        if c["mode"] == "closed" and _os_live():
            q = os_query()
            out["job"], out["job_ok"] = bool(q), _matches(q, _want(c))
    except Exception:
        pass
    return out


def heal(log=print):
    """Server start: keep the OS job in line with the setting. "closed": make it point at THIS app folder and the current
    runtime (rewrite if not); any other mode: remove a leftover job (for example after restoring a backup made on
    another computer). Returns "off", "ok", "fixed", "skipped" or "failed: ...". Never raises."""
    try:
        if paths.PORTABLE:
            return "skipped"       # a portable copy never creates, repairs or removes anything outside its folder
        c = get()
        if not _os_live():
            return "skipped"
        if c["mode"] != "closed":
            if os_query():
                os_remove()
                log("Removed a leftover automatic update job (the setting isn't 'Even when Siftwell is closed').")
                return "fixed"
            return "off"
        if not _stub():
            g = _gs()
            if not (g._under(sys.executable, paths.RUNTIME) or g._under(sys.executable, os.path.join(APP, ".venv"))):
                return "skipped"
        if _matches(os_query(), _want(c)):
            return "ok"
        os_install(c)
        log("Automatic update job pointed somewhere else or was missing; rewrote it for " + APP)
        return "fixed"
    except Exception as e:
        log(f"Couldn't check the automatic update job: {type(e).__name__}: {str(e)[:150]}")
        return f"failed: {type(e).__name__}"


# ---------------------------------------------------------------- the control (Settings → Updates, Catalog → Runs)
PANE_HTML = """<style>#auTime{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;min-width:0}</style>
<section class="sgsec"><h3 class="sgtitle">Automatic job updates</h3><div class="sgroup" id="auBox">
<div class="srow"><div class="slab"><label for="auMode">Automatic job updates</label><small id="auNext">Loading…</small></div><div class="sctl"><select id="auMode">
<option value="off">Off</option><option value="running">While Siftwell is running</option><option value="closed">Even when Siftwell is closed</option></select></div></div>
<div class="srow" id="auTimeRow"><div class="slab"><label for="auTime">Time</label><small>Every day.</small></div><div class="sctl"><input type="time" id="auTime" class="tin"></div></div>
<div class="srow" id="auWakeRow" hidden><div class="slab"><label for="auWake">Wake my computer to run it</label><small id="auWakeHelp"></small></div><div class="sctl"><input type="checkbox" role="switch" class="sw" id="auWake"></div></div>
</div><p class="sfoot" id="auFoot"></p></section>"""

JS = r"""(function(){
const $ = id => document.getElementById(id); if (!$("auMode")) return;
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const pane = $("auBox").closest(".spane");
const say = (t, bad) => { const s = pane && pane.querySelector(".ssave"); if (!s) return; s.textContent = t; s.classList.toggle("err", !!bad); if (!bad && t) setTimeout(() => { if (s.textContent === t) s.textContent = ""; }, 2500); };
const when = iso => { const d = new Date(iso), t = new Date(), tm = d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  return (d.toDateString() === t.toDateString() ? "today " : "tomorrow ") + tm; };
const FOOT = {
  off: "Siftwell won't check for new jobs by itself. Use Update on the board, or Fetch everything now in Catalog.",
  running: "Siftwell checks every company at this time, but only while it is running (the Siftwell window is open, or it is kept available in the background).",
  closed: "Your computer starts a small background job at this time, even when Siftwell is closed (you must be signed in to your computer). If Siftwell is open it runs the update there so you can watch it; otherwise it runs quietly and stops. It never needs administrator permission."
};
function show(s){
  $("auMode").value = s.mode; $("auTime").value = s.time; $("auWake").checked = !!s.wake;
  $("auTimeRow").hidden = s.mode === "off";
  const o = $("auMode").querySelector('option[value="closed"]'); o.disabled = !s.closed_ok;
  $("auNext").textContent = s.mode === "off" ? "Off" : "Next: " + when(s.next_run);
  const wr = $("auWakeRow"); wr.hidden = !(s.wake_ok && s.mode !== "off");
  const w = $("auWake"); w.disabled = s.mode !== "closed";
  if (s.legacy_wake) {
    w.checked = s.mode === "closed" ? !!s.wake : true; w.disabled = true;
    $("auWakeHelp").textContent = "On: your computer already wakes early through the older \"Job Board wake for nightly update\" task, which Siftwell leaves as it is.";
  } else $("auWakeHelp").textContent = s.mode === "closed"
    ? "Needs the laptop plugged in and asleep, not shut down. A computer that is off won't wake."
    : "Available with \"Even when Siftwell is closed\". Needs the laptop plugged in and asleep, not shut down.";
  let f = FOOT[s.mode];
  if (s.mode === "closed" && s.job === false) f += " The job isn't set up yet; saving again will try once more.";
  if (s.mode === "closed" && s.job && !s.job_ok) f += " The job exists but doesn't match these settings; Siftwell fixes it the next time it starts.";
  if (s.portable) f += s.mode === "closed" ? " This adds something to this computer (outside the Siftwell folder)." : " Choosing \"Even when Siftwell is closed\" adds something to this computer (outside the Siftwell folder).";
  $("auFoot").textContent = f;
}
function load(){ return fetch("/api/schedule").then(r => r.json()).then(show).catch(() => { $("auNext").textContent = "Couldn't load. Check the connection."; }); }
function save(body){
  say("Saving…");
  return fetch("/api/schedule", {method: "POST", headers: H, body: JSON.stringify(body)}).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.error || "Couldn't save."); return d; }))
    .then(d => { show(d); say("Saved"); }).catch(err => { load(); say(err instanceof TypeError ? "Couldn't save. Check the connection." : err.message, true); });
}
$("auMode").addEventListener("change", () => save({mode: $("auMode").value}));
$("auTime").addEventListener("change", () => { if ($("auTime").value) save({time: $("auTime").value}); });
$("auWake").addEventListener("change", () => save({wake: $("auWake").checked}));
load();
})();"""
SCRIPT = "<script>" + JS + "</script>"
