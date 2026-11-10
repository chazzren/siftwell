"""The "Get started" checklist (GET /getting-started) and its actions, so setup happens in the browser, not a terminal.

Required checks (counted, drive the banner): a browser for resume PDFs.
Optional (listed apart, never counted): Claude Code installed and signed in (an optional upgrade: Siftwell works without it),
start at sign-in, phone access, Codex for Astra.
server.py only routes here (handle_get / handle_post / ping) and asks bind_host() which address to listen on.

Phone access is a saved setting, DATA/network.json {"lan": bool, "keep": bool}; "keep" (default off) means the server keeps
running headless after the Siftwell window (app_window.py) is closed, so phones can still reach it.
Phone access (lan) New installs listen on this computer only (127.0.0.1);
an install that already had profiles when this setting first appeared keeps LAN access on (bind_host() records that choice
on the first start). Changing it needs a restart: restart_now() starts a replacement that waits for the port to free.
"""
import os
import sys

if __name__ == "__main__" and "--serve" in sys.argv:
    # Login launcher: `pythonw -X utf8 getting_started.py --serve` reads DATA/port (default 8766; an older launcher's
    # <app>/.siftwell/port is copied over once) at run time and runs server.py on it, so the start-at-sign-in entry
    # never holds a stale port.
    _app = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _app)
    sys.dont_write_bytecode = True
    import paths as _paths
    sys.dont_write_bytecode = False
    if not os.environ.get("PYTHONPYCACHEPREFIX"):  # keep compiled .pyc files out of the app folder (as the launchers do)
        os.environ["PYTHONPYCACHEPREFIX"] = os.path.join(_paths.RUNTIME, "pycache")
        sys.pycache_prefix = os.environ["PYTHONPYCACHEPREFIX"]
    _port = _paths.read_port()
    os.chdir(_app)
    sys.argv = [os.path.join(_app, "server.py"), str(_port)]
    import runpy
    runpy.run_path(sys.argv[0], run_name="__main__")
    sys.exit(0)

import html
import json
import re
import socket
import subprocess
import threading
import time

import frozen
import osdeps
import paths
import people
import report

def _read_version():
    """The release number from the VERSION file next to the app ("dev" when it's missing), e.g. "0.1.0"."""
    try:
        with open(os.path.join(paths.APP, "VERSION"), encoding="utf-8") as f:
            return f.read().strip().splitlines()[0].strip() or "dev"
    except (OSError, IndexError):
        return "dev"


VERSION = _read_version()
NETWORK = os.path.join(paths.DATA, "network.json")
APP = paths.APP
TASK_NAME = "Job Board server"                       # scheduled task made by older installs (starts the server at sign-in)
WAKE_TASK = "Job Board wake for nightly update"      # older installs' 05:25 wake-up task; harmless, never touched
MAC_LABEL = "com.siftwell.server"
CTX = {"port": 8766, "token": "", "busy": lambda: False, "bound_lan": False}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if osdeps.WINDOWS else 0


def configure(port, token, busy):
    """busy() returns a short reason string while work a restart would kill is running, else ''."""
    CTX.update(port=port, token=token, busy=busy)


def _pid_alive(pid):
    try:
        if osdeps.WINDOWS:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def note_started():
    """Call after the port is bound: record our pid in DATA/server.pid unless that file names another live process."""
    pf = paths.PID_FILE
    try:
        old = int(open(pf).read().strip())
    except (OSError, ValueError):
        old = 0
    if old and old != os.getpid() and _pid_alive(old):
        return
    try:
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        with open(pf, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


_slow = {}


def _cached(key, fn, ttl=30):
    """Slow checks (subprocesses, network lookups) are reused for ttl seconds; status(fresh=True) clears them."""
    hit = _slow.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _slow[key] = (time.time(), v)
    return v


# ---------------------------------------------------------------- phone access (network.json)
def lan_enabled():
    try:
        return bool(json.load(open(NETWORK, encoding="utf-8")).get("lan"))
    except Exception:
        return os.path.exists(people.INDEX)       # no setting yet: keep LAN on for installs that already have profiles


def bind_host():
    """Address to listen on. First call on an install without the setting writes it, so existing households stay on."""
    if not os.path.exists(NETWORK):
        try:
            save_network(os.path.exists(people.INDEX))
        except OSError:
            pass
    on = lan_enabled()
    CTX["bound_lan"] = on
    return "0.0.0.0" if on else "127.0.0.1"


def _read_network():
    try:
        d = json.load(open(NETWORK, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_network(d):
    os.makedirs(paths.DATA, exist_ok=True)
    tmp = NETWORK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, NETWORK)


def save_network(on):
    d = _read_network()
    d["lan"] = bool(on)
    _write_network(d)


def keep_available():
    """True when the server should keep running (headless) after the Siftwell window is closed. Default off."""
    return bool(_read_network().get("keep"))


def save_keep(on):
    d = _read_network()
    d.setdefault("lan", lan_enabled())     # never lose the phone-access choice when the file is first written here
    d["keep"] = bool(on)
    _write_network(d)


def _private(ip):
    p = ip.split(".")
    try:
        a, b = int(p[0]), int(p[1])
    except (ValueError, IndexError):
        return False
    return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def lan_ip():
    """This computer's address on the home network (UDP-socket trick; nothing is sent). Prefers private ranges."""
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        found += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    found = [ip for ip in found if ip and not ip.startswith(("127.", "169.254.", "0."))]
    for ip in found:
        if _private(ip):
            return ip
    return found[0] if found else None


# ---------------------------------------------------------------- start at login
def _app_python():
    """The interpreter a start-at-sign-in entry should use, without a console window: the launcher's runtime venv
    (paths.RUNTIME, outside the app folder), else an older install's <app>/.venv, else whatever runs us now."""
    if frozen.FROZEN:
        return sys.executable          # the installed Siftwell.exe (started with --server)
    for p in (paths.runtime_python(windowed=True), paths.legacy_python(windowed=True)):
        if p:
            return p
    if osdeps.WINDOWS:
        p = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        return p if os.path.exists(p) else sys.executable
    return sys.executable


def _win_lnk():
    if os.environ.get("SIFTWELL_TEST_LNK"):   # tests only: a stand-in shortcut path, so the real one is never touched
        return os.environ["SIFTWELL_TEST_LNK"]
    # A portable copy uses its own shortcut name, so it never shows or removes the installed copy's entry.
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming"),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
                        "Siftwell (portable).lnk" if paths.PORTABLE else "Siftwell.lnk")


def _mac_plist():
    return os.path.expanduser(f"~/Library/LaunchAgents/{MAC_LABEL}.plist")


def _linux_desktop():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart", "siftwell.desktop")


_DENIED = ("access is denied", "0x80070005", "permissiondenied", "unauthorizedaccess")


def _test_tasks():
    """Tests only: SIFTWELL_TEST_TASKS=<json file> stands in for the Windows scheduled tasks, so the real ones are never
    touched. {"tasks": {"<name>": {"enabled": bool, "state": "Running", "wd": ..., "exe": ..., "args": ...}},
    "deny": bool (changing a task without admin is refused), "uac": "ok" | "declined", "calls": [...]}."""
    p = os.environ.get("SIFTWELL_TEST_TASKS")
    if not p:
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"tasks": {}}


def _test_save(d):
    with open(os.environ["SIFTWELL_TEST_TASKS"], "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def _ps(script, timeout=30):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _task_query(name):
    """A scheduled task as {state, enabled, wd, exe, args}, or {} when it doesn't exist. Read-only."""
    if not osdeps.WINDOWS:
        return {}
    t = _test_tasks()
    if t is not None:
        x = (t.get("tasks") or {}).get(name)
        if not x:
            return {}
        en = bool(x.get("enabled", True))
        return {"state": (x.get("state") or "Ready") if en else "Disabled", "enabled": en,
                "wd": x.get("wd") or "", "exe": x.get("exe") or "", "args": x.get("args") or ""}
    try:
        ps = (f"$t=Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; "
              "if($t){@{state=[string]$t.State;enabled=[bool]$t.Settings.Enabled;wd=[string]$t.Actions[0].WorkingDirectory;"
              "exe=[string]$t.Actions[0].Execute;args=[string]$t.Actions[0].Arguments}|ConvertTo-Json -Compress}")
        _rc, out = _ps(ps)
        d = json.loads(out) if out else {}
    except Exception:
        return {}
    if d:
        # A disabled task that is still running (e.g. the one running this server) reports State "Running",
        # so use the real Enabled flag; fall back to the state only if it's missing.
        d["enabled"] = bool(d["enabled"]) if "enabled" in d else d.get("state") != "Disabled"
    return d


def _task_info():
    """The older setup's "Job Board server" task: {} when absent, else {state, enabled, wd, exe, args}. Cached."""
    return _cached("task", lambda: _task_query(TASK_NAME))


def _task_exists():
    return bool(_task_info())


def _task_enabled():
    t = _task_info()
    return bool(t) and bool(t.get("enabled", True))


def _wake_exists():
    return bool(_cached("wake", lambda: _task_query(WAKE_TASK)))


def _task_set(enabled, elevated=False):
    """Enable or disable the legacy "Job Board server" task (never deletes it). Returns "ok", "denied" (Windows wants
    administrator permission), "declined" (the person said no to the permission prompt) or "failed: <why>"."""
    verb = "Enable" if enabled else "Disable"
    t = _test_tasks()
    if t is not None:
        x = (t.get("tasks") or {}).get(TASK_NAME)
        t.setdefault("calls", []).append({"op": verb.lower(), "elevated": bool(elevated)})
        if not x:
            res = "failed: no such task"
        elif elevated:
            res = "declined" if t.get("uac") == "declined" else "ok"
        elif t.get("deny"):
            res = "denied"
        else:
            res = "ok"
        if res == "ok":
            x["enabled"] = bool(enabled)
        _test_save(t)
        return res
    cmd = f"{verb}-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop | Out-Null"
    try:
        if not elevated:
            rc, out = _ps(cmd)
            if rc == 0:
                return "ok"
            return "denied" if any(m in out.lower() for m in _DENIED) else "failed: " + out[:160]
        import base64
        enc = base64.b64encode(f"try{{{cmd};exit 0}}catch{{exit 1}}".encode("utf-16-le")).decode()
        outer = ("try{$p=Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
                 f"-ArgumentList '-NoProfile','-EncodedCommand','{enc}'; exit $p.ExitCode}}catch{{exit 1223}}")
        rc, out = _ps(outer, timeout=180)   # waits while the person answers the Windows permission prompt
        return "ok" if rc == 0 else "declined" if rc == 1223 else "failed: the task could not be changed"
    except Exception as e:
        return "failed: " + str(e)[:160]


def task_managed():
    """True when this server is (very likely) the one the scheduled task runs: the task is enabled and Running, its
    working folder is this app, and it uses our port (it passes none, so 8766). Restarting from inside it is unreliable.
    A disabled task isn't managing startup, so a restart works."""
    t = _task_info()
    if not t or not t.get("enabled", True) or t.get("state") != "Running":
        return False
    same = os.path.normcase(os.path.abspath(t.get("wd") or "")) == os.path.normcase(os.path.abspath(APP))
    port = CTX["port"]
    return same and (port == 8766 or str(port) in (t.get("args") or ""))


def startup_state():
    """{"on", "via", ...}: via is shortcut / task / launchagent / autostart. On Windows "task" means the older
    "Job Board server" task exists and "task_enabled" that it is still turned on (a disabled one starts nothing);
    "own" is our Startup shortcut; "legacy_dir" the folder the older task points at; "wake" the older 5:25 wake task."""
    if osdeps.WINDOWS:
        lnk, task, active = os.path.exists(_win_lnk()), _task_exists(), _task_enabled()
        if paths.PORTABLE:      # the older scheduled tasks belong to an installed copy; a portable copy ignores them
            task = active = False
        return {"on": lnk or active, "via": "shortcut" if lnk else "task" if active else None, "task": task,
                "task_enabled": active, "own": lnk, "legacy_dir": (_task_info().get("wd") or "") if task else "",
                "wake": _wake_exists() and not paths.PORTABLE}
    if osdeps.MAC:
        own = os.path.exists(_mac_plist())
        return {"on": own, "via": "launchagent" if own else None, "task": False, "task_enabled": False, "own": own}
    own = os.path.exists(_linux_desktop())
    return {"on": own, "via": "autostart" if own else None, "task": False, "task_enabled": False, "own": own}


def switch_startup(elevated=False, h=None):
    """Move sign-in startup from the older "Job Board server" task to our own Startup shortcut (Windows). The task is
    turned off first and the shortcut made after, so a failure never leaves both starting a server. Doesn't stop the
    running server. Returns "ok" or what _task_set returned."""
    if not osdeps.WINDOWS:
        raise RuntimeError("This only applies to Windows.")
    _slow.clear()
    res = "ok"
    if _task_enabled():
        res = _task_set(False, elevated)
        _slow.clear()
        if res == "ok" and _task_enabled():
            res = "failed: the task is still on"
        if res != "ok":
            return res
    try:
        set_startup(True)        # (re)writes the shortcut for this app folder
    except Exception as e:
        if _task_exists():
            _task_set(True, elevated)   # put things back as they were
        _slow.clear()
        return "failed: " + str(e)[:160]
    _slow.clear()
    return "ok"


def unswitch_startup(elevated=False, h=None):
    """Undo switch_startup: remove our shortcut, turn the older task back on. Never leaves both on."""
    if not osdeps.WINDOWS:
        raise RuntimeError("This only applies to Windows.")
    _slow.clear()
    had = os.path.exists(_win_lnk())
    if had:
        set_startup(False, "undo switch", h)
    if _task_exists() and not _task_enabled():
        res = _task_set(True, elevated)
        _slow.clear()
        if res == "ok" and not _task_enabled():
            res = "failed: the task is still off"
        if res != "ok":
            if had:
                try:
                    set_startup(True)
                except Exception:
                    pass
            _slow.clear()
            return res
    _slow.clear()
    return "ok"


def _launcher():
    return os.path.join(APP, "getting_started.py")


def _win_args():
    if frozen.FROZEN:
        return "--server"
    return f'-X utf8 "{_launcher()}" --serve'


def _mac_args(py):
    if frozen.FROZEN:
        return [py, "--server"]
    return [py, "-X", "utf8", _launcher(), "--serve"]


def _entry_dir():
    """Working folder of the start-at-sign-in entry: the app folder, or the install folder of the installed program."""
    return os.path.dirname(sys.executable) if frozen.FROZEN else APP


def _linux_entry(py):
    def q(s):
        for ch in ("\\", '"', "`", "$"):
            s = s.replace(ch, "\\" + ch)
        return '"' + s.replace("%", "%%") + '"'
    return ("[Desktop Entry]\nType=Application\nName=Siftwell\nComment=Start the Siftwell job board\n"
            f"Exec={q(py)} {'--server' if frozen.FROZEN else '-X utf8 ' + q(_launcher()) + ' --serve'}\nPath={_entry_dir()}\nTerminal=false\n"
            "X-GNOME-Autostart-enabled=true\n")


def _write_mac_plist(py, reload=True):
    import plistlib
    pl = _mac_plist()
    os.makedirs(os.path.dirname(pl), exist_ok=True)
    with open(pl, "wb") as f:
        plistlib.dump({"Label": MAC_LABEL, "ProgramArguments": _mac_args(py),
                       "WorkingDirectory": _entry_dir(), "RunAtLoad": True, "KeepAlive": False,
                       "StandardOutPath": os.path.join(paths.data(), "server.log"),
                       "StandardErrorPath": os.path.join(paths.data(), "server.log")}, f)
    if reload:
        subprocess.run(["launchctl", "unload", pl], capture_output=True, timeout=30)
        # loading starts a second copy now; it exits at once because the port is taken, and it runs at the next sign-in
        subprocess.run(["launchctl", "load", "-w", pl], capture_output=True, timeout=30)


def _record(action, detail=""):
    import actionlog
    actionlog.log(action, None, None, detail)


def set_startup(on, why="", h=None):
    """Turn the start-at-sign-in entry on or off. Only ever called for an explicit user action (the Get started
    switch, Switch / Undo) or to rewrite an entry that is already on (heal_startup); every removal is written to
    DATA/actions.log. `why` says which action asked. A server running on test data (JOBBOARD_DATA or SIFTWELL_RUNTIME
    set) never touches the real entry unless SIFTWELL_TEST_LNK points the Windows shortcut somewhere else."""
    if (os.environ.get("JOBBOARD_DATA") or os.environ.get("SIFTWELL_RUNTIME")) and not os.environ.get("SIFTWELL_TEST_LNK"):
        raise RuntimeError("This server is running on test data, so it won't change the real start-at-sign-in entry.")
    py = _app_python()
    if osdeps.WINDOWS:
        lnk = _win_lnk()
        if not on:
            if os.path.exists(lnk):
                import actionlog
                actionlog.log("start-at-sign-in shortcut removed", None, h, why or "unspecified")
                os.remove(lnk)
            return
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SW_LNK);"
                  "$s.TargetPath=$env:SW_EXE;$s.Arguments=$env:SW_ARGS;$s.WorkingDirectory=$env:SW_DIR;"
                  "$s.Description='Siftwell';$s.Save()")
        env = dict(os.environ, SW_LNK=lnk, SW_EXE=py, SW_DIR=_entry_dir(), SW_ARGS=_win_args())
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], env=env,
                           capture_output=True, text=True, timeout=60, creationflags=NOWIN)
        if r.returncode != 0 or not os.path.exists(lnk):
            raise RuntimeError("Couldn't create the startup shortcut. " + (r.stderr or "").strip()[:200])
    elif osdeps.MAC:
        pl = _mac_plist()
        if not on:
            if os.path.exists(pl):
                _record("start-at-sign-in entry removed", why or "unspecified")
                # If launchd started this server, unloading would stop it mid-answer; removing the file is enough then.
                if os.environ.get("XPC_SERVICE_NAME") != MAC_LABEL:
                    subprocess.run(["launchctl", "unload", pl], capture_output=True, timeout=30)
                os.remove(pl)
            return
        _write_mac_plist(py)
    else:
        df = _linux_desktop()
        if not on:
            if os.path.exists(df):
                _record("start-at-sign-in entry removed", why or "unspecified")
                os.remove(df)
            return
        os.makedirs(os.path.dirname(df), exist_ok=True)
        with open(df, "w", encoding="utf-8") as f:
            f.write(_linux_entry(py))


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a or ".")) == os.path.normcase(os.path.normpath(b or "."))


def _under(path, folder):
    try:
        a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def heal_startup(log=print):
    """Called on every server start. If start-at-sign-in is on (our own Startup shortcut / LaunchAgent / autostart
    entry, never the older "Job Board server" scheduled task), make sure it points at THIS app folder and the current
    runtime; rewrite it when it doesn't (for example after the app folder was deleted and a new release downloaded
    somewhere else). Returns "ok", "fixed", "off", "skipped" or "failed: ...".

    Skipped when JOBBOARD_DATA is set: a start-at-sign-in entry always runs with the default data folder, so a test
    or portable server using other data must not take it over. Also skipped when SIFTWELL_RUNTIME is set (a dev or test
    copy), when SIFTWELL_NO_SELFHEAL=1, and unless this server runs on the launcher's runtime Python or the legacy
    <app>/.venv (a stray interpreter must never become the sign-in shortcut)."""
    if paths.PORTABLE or os.environ.get("JOBBOARD_DATA") or os.environ.get("SIFTWELL_NO_SELFHEAL") or os.environ.get("SIFTWELL_RUNTIME"):
        return "skipped"      # (portable: never creates or repairs anything outside its own folder)
    if not (frozen.FROZEN or _under(sys.executable, paths.RUNTIME) or _under(sys.executable, os.path.join(APP, ".venv"))):
        return "skipped"
    py = _app_python()
    try:
        if osdeps.WINDOWS:
            lnk = _win_lnk()
            if not os.path.exists(lnk):
                return "off"
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SW_LNK);"
                  "@{t=[string]$s.TargetPath;a=[string]$s.Arguments;w=[string]$s.WorkingDirectory}|ConvertTo-Json -Compress")
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                               env=dict(os.environ, SW_LNK=lnk), capture_output=True, text=True, timeout=60, creationflags=NOWIN)
            cur = json.loads(r.stdout) if r.stdout.strip() else {}
            ok = (_same_path(cur.get("t"), py) and _same_path(cur.get("w"), _entry_dir())
                  and os.path.normcase(" ".join((cur.get("a") or "").split())) == os.path.normcase(" ".join(_win_args().split())))
        elif osdeps.MAC:
            import plistlib
            pl = _mac_plist()
            if not os.path.exists(pl):
                return "off"
            with open(pl, "rb") as f:
                cur = plistlib.load(f)
            ok = cur.get("ProgramArguments") == _mac_args(py) and _same_path(cur.get("WorkingDirectory"), _entry_dir())
        else:
            df = _linux_desktop()
            if not os.path.exists(df):
                return "off"
            with open(df, encoding="utf-8") as f:
                ok = f.read() == _linux_entry(py)
        if ok:
            return "ok"
        if osdeps.MAC:
            _write_mac_plist(py, reload=False)  # launchd reads it at the next sign-in; reloading now would start a 2nd copy
        else:
            set_startup(True)
        log(f"Start at sign-in pointed at an old location; updated it to {APP}")
        return "fixed"
    except Exception as e:  # never stop the server over this
        log(f"Couldn't check the start-at-sign-in entry: {type(e).__name__}: {str(e)[:150]}")
        return f"failed: {type(e).__name__}"


def heal_overnight_job(log=print):
    """The OS-level automatic-update job ("Even when Siftwell is closed": Windows task / LaunchAgent / crontab line, see
    autoupdate.py): on every start make sure it points at APP and the current runtime, the same way heal_startup() does,
    or remove a leftover one when the setting is something else. Never touch the older "Job Board wake for nightly
    update" scheduled task (it doesn't reference the app folder); the older "Job Board server" task is only ever
    turned off or on from the Get started page (switch_startup / unswitch_startup)."""
    import autoupdate
    return "skipped" if paths.PORTABLE else autoupdate.heal(log)


def heal_entries(log=print):
    """Both self-heal checks; server start runs this in a background thread."""
    return {"startup": heal_startup(log), "overnight": heal_overnight_job(log)}


# ---------------------------------------------------------------- install Claude Code (background)
INSTALL = {"running": False, "lines": [], "exit": None, "started": None, "finished": None, "found": None}
_ilock = threading.Lock()
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def install_command():
    test = os.environ.get("SIFTWELL_TEST_INSTALL_CMD")
    if test:
        return test, True
    if osdeps.WINDOWS:
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://claude.ai/install.ps1 | iex"], False
    return ["bash", "-c", "curl -fsSL --max-time 540 https://claude.ai/install.sh | bash"], False


def _kill_tree(p):
    try:
        if osdeps.WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=15, creationflags=NOWIN)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _run_install():
    import claude_cli
    cmd, shell = install_command()
    limit = float(os.environ.get("SIFTWELL_TEST_INSTALL_TIMEOUT") or 600)
    timed_out = []
    try:
        p = subprocess.Popen(cmd, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=NOWIN, start_new_session=not osdeps.WINDOWS)
        def stop():
            timed_out.append(1)
            _kill_tree(p)
        dog = threading.Timer(limit, stop)
        dog.daemon = True
        dog.start()
        for raw in iter(p.stdout.readline, b""):
            line = _ANSI.sub("", raw.decode("utf-8", "replace")).replace("\r", "").strip()
            if line:
                with _ilock:
                    INSTALL["lines"] = (INSTALL["lines"] + [line])[-60:]
        p.wait()
        dog.cancel()
        code = p.returncode
        if timed_out:
            code = -1
            with _ilock:
                INSTALL["lines"] = (INSTALL["lines"] + ["Stopped: the installer was taking too long. Check your internet connection and try again."])[-60:]
    except Exception as e:
        code = -1
        with _ilock:
            INSTALL["lines"] = (INSTALL["lines"] + ["Couldn't run the installer: " + str(e)[:200]])[-60:]
    _status_cache.clear()
    _slow.clear()
    with _ilock:
        claude_cli.invalidate()
        INSTALL.update(running=False, exit=code, finished=time.time(), found=bool(claude_cli.path()))


def start_install():
    with _ilock:
        if INSTALL["running"]:
            return False
        INSTALL.update(running=True, lines=[], exit=None, started=time.time(), finished=None, found=None)
    threading.Thread(target=_run_install, daemon=True).start()
    return True


def install_state():
    with _ilock:
        return dict(INSTALL, lines=list(INSTALL["lines"]), elapsed=int((INSTALL["finished"] or time.time()) - INSTALL["started"]) if INSTALL["started"] else 0)


# ---------------------------------------------------------------- restart
_WAITER = r"""
import os, socket, subprocess, sys, time
port, log, pidf = int(sys.argv[1]), sys.argv[2], sys.argv[3]
cmd = sys.argv[4:]
end = time.time() + 90
while time.time() < end:
    s = socket.socket(); s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port)); s.close(); time.sleep(0.4)
    except OSError:
        break
flags = 0
if os.name == "nt":
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
f = open(log, "ab")
p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=f, stderr=f, creationflags=flags,
                     start_new_session=(os.name != "nt"), cwd=os.environ.get("SIFTWELL_WAITER_CWD") or os.path.dirname(cmd[-2]))
try:
    os.makedirs(os.path.dirname(pidf), exist_ok=True)
    open(pidf, "w").write(str(p.pid))
except OSError:
    pass
"""


def restart_now():
    """Start a replacement server that waits for this one's port to free. Raises if it can't be started; the caller
    answers the browser and then calls exit_soon()."""
    if task_managed():
        raise RuntimeError("Siftwell is run by the Windows scheduled task \"Job Board server\", which can't be restarted from "
                           "here. Sign out of Windows and back in (or restart the computer) to apply this change.")
    py = sys.executable
    cmd = frozen.command("server", CTX["port"], utf8=True)
    flags = 0
    if osdeps.WINDOWS:
        flags = NOWIN | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    waiter = frozen.command("waiter", CTX["port"], os.path.join(paths.data(), "server.log"), paths.PID_FILE, *cmd) if frozen.FROZEN \
        else [py, "-X", "utf8", "-c", _WAITER, str(CTX["port"]), os.path.join(paths.data(), "server.log"), paths.PID_FILE, *cmd]
    subprocess.Popen(waiter, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, start_new_session=not osdeps.WINDOWS, cwd=APP,
                     env=dict(os.environ, SIFTWELL_WAITER_CWD=APP) if frozen.FROZEN else None)


def exit_soon():
    threading.Timer(0.8, lambda: os._exit(0)).start()


# ---------------------------------------------------------------- status
_status_cache = {}


def _signed_in(installed, fresh):
    import claude_cli
    if not installed:
        return False
    hit = _status_cache.get("login")
    if hit and not fresh and time.time() - hit[0] < 30:
        return hit[1]
    v = claude_cli.logged_in()
    _status_cache["login"] = (time.time(), v)
    return v


def status(fresh=False):
    import claude_cli
    if fresh:
        _slow.clear()
        claude_cli.invalidate()
    port = CTX["port"]
    cpath = claude_cli.path()
    signed = _signed_in(bool(cpath), fresh)
    chrome = _cached("chrome", osdeps.chrome_path)
    st = startup_state()
    lan = lan_enabled()
    keep = keep_available()
    ip = _cached("ip", lan_ip) if lan else None
    url = f"http://{ip}:{port}/?k={CTX['token']}" if lan and ip else None
    codex = _cached("codex", lambda: osdeps.find_exe("codex"))
    items = [
        {"id": "claude", "title": "Claude Code installed", "done": bool(cpath), "optional": True, "group": "claude"},
        {"id": "signin", "title": "Signed in to Claude", "done": bool(signed), "optional": True, "group": "claude"},
        {"id": "browser", "title": "Browser for resume PDFs", "done": bool(chrome), "optional": False},
        {"id": "startup", "title": "Start Siftwell when I sign in", "done": st["on"], "optional": True},
        {"id": "phone", "title": "Use Siftwell on my phone", "done": lan, "optional": True},
        {"id": "keep", "title": "Keep Siftwell available to my phone when the window is closed", "done": keep, "optional": True},
        {"id": "astra", "title": "Astra resume reviews", "done": bool(codex), "optional": True},
    ]
    req = [i for i in items if not i["optional"]]
    done = sum(1 for i in req if i["done"])
    return {
        "items": items, "done": done, "total": len(req), "complete": done == len(req),
        "missing": [i["id"] for i in req if not i["done"]],
        "port": port, "windows": osdeps.WINDOWS, "mac": osdeps.MAC, "portable": paths.PORTABLE,
        "claude": {"installed": bool(cpath), "signed_in": bool(signed)},
        "browser": {"found": bool(chrome), "name": "Edge" if chrome and "edge" in chrome.lower() else "Chrome" if chrome else ""},
        "startup": st,
        "phone": {"on": lan, "bound": CTX["bound_lan"], "restart_needed": lan != CTX["bound_lan"], "restart_manual": lan != CTX["bound_lan"] and task_managed(), "ip": ip, "url": url, "port": port},
        "keep": {"on": keep},
        "astra": {"found": bool(codex)},
        "install": install_state(),
    }


# ---------------------------------------------------------------- routes
ASSET_FILES = {  # exact-match allowlist: URL path -> (file under assets/, content type)
    "/assets/vendor/qrcode.js": ("vendor/qrcode.js", "application/javascript"),
    "/assets/brand/siftwell-mark.svg": ("brand/siftwell-mark.svg", "image/svg+xml"),
    "/assets/brand/favicon-16.png": ("brand/favicon-16.png", "image/png"),
    "/assets/brand/favicon-32.png": ("brand/favicon-32.png", "image/png"),
    "/assets/brand/apple-touch-icon.png": ("brand/apple-touch-icon.png", "image/png"),
}
GET_PATHS = ("/getting-started", "/api/setup-status", "/api/getting-started/install", *ASSET_FILES)


def ping():
    return {"app": "siftwell", "version": VERSION, "port": CTX["port"], "data": paths.data_id()}


def handle_get(h, path, pid, query=""):
    if path in ASSET_FILES:
        name, ctype = ASSET_FILES[path]
        data = open(os.path.join(paths.ASSETS, *name.split("/")), "rb").read()
        h._send(200, data, ctype, cache="max-age=86400")
        return True
    if path == "/getting-started":
        if pid is not None:  # the checklist lives in Settings now; old links and bookmarks land there
            h.send_response(303); h.send_header("Location", "/settings#get-started"); h.end_headers()
        else:  # no profile yet (fresh install): Settings isn't available, so show the checklist on its own
            h._send(200, render_html(), "text/html")
        return True
    if path == "/api/setup-status":
        h._send(200, status(fresh="fresh=1" in query))
        return True
    if path == "/api/getting-started/install":
        h._send(200, install_state())
        return True
    return False


def handle_post(h, path, body):
    if not path.startswith("/api/getting-started/"):
        return False
    act = path.rsplit("/", 1)[1]
    try:
        if act == "install":
            if os.environ.get("SIFTWELL_TEST_INSTALL_CMD") is None:
                import claude_cli
                if claude_cli.path():
                    return h._send(200, {"ok": True, "already": True}) or True
            start_install()
            h._send(202, {"ok": True})
        elif act == "startup":
            if not isinstance(body.get("on"), bool):   # a missing or odd value must never be read as "turn off"
                return h._send(400, {"error": "Say whether to turn it on or off."}) or True
            on = body["on"]
            if on and osdeps.WINDOWS and _task_enabled():
                return h._send(409, {"error": "An older setup already starts Siftwell at sign-in. Use Switch to the new startup instead, "
                                              "so two copies never start."}) or True
            h._act("start at sign-in turned " + ("on" if on else "off"))
            set_startup(on, "toggle on the Get started page", h)
            _slow.clear()
            h._send(200, status(fresh=True))
        elif act in ("switch", "unswitch"):
            if not osdeps.WINDOWS:
                return h._send(400, {"error": "This only applies to Windows."}) or True
            el = bool(body.get("elevated"))
            undo = act == "unswitch"
            h._act("switch startup: " + ("undo" if undo else "switch"))
            res = (unswitch_startup if undo else switch_startup)(el, h)
            if res == "ok":
                msg = ("Undone. The older setup starts Siftwell at sign-in again." if undo else
                       "Done. Siftwell keeps running now, and the new startup takes over the next time you sign in to Windows.")
            elif res == "denied":
                msg = "Windows needs administrator permission to change that task."
            elif res == "declined":
                msg = "The administrator permission prompt was declined, so nothing was changed."
            else:
                msg = "Couldn't change the older task. " + res.split(": ", 1)[-1]
            h._send(200, dict(status(fresh=True), switch={"state": res if res in ("ok", "denied", "declined") else "failed",
                                                          "op": "undo" if undo else "switch", "message": msg}))
        elif act == "network":
            save_network(bool(body.get("on")))
            h._send(200, status())
        elif act == "keep":
            save_keep(bool(body.get("on")))
            h._send(200, status())
        elif act == "restart":
            why = CTX["busy"]() or (install_state()["running"] and "Claude Code is installing")
            if why:
                return h._send(409, {"error": f"{why}. Restarting now would stop it. Try again when it finishes."}) or True
            h._act("restart")
            try:
                restart_now()
            except Exception as e:
                print("restart failed:", e, flush=True)
                return h._send(500, {"error": str(e)[:300] or "Couldn't restart Siftwell."}) or True
            h._send(200, {"ok": True})
            h.wfile.flush()
            exit_soon()
        else:
            return False
    except Exception as e:
        h._send(500, {"error": str(e)[:300]})
    return True


# ---------------------------------------------------------------- page
# The checklist lives in Settings (settings_page.py reuses PANE_HTML, CSS and CHECKLIST_JS). Only a fresh install with
# no profile yet gets it as a standalone page, because Settings needs a profile.
def render_html() -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
            report.HEAD.replace("<title>Siftwell</title>", "<title>Get started · Siftwell</title>") + CSS + "</head><body>" + BODY +
            '<script src="/assets/vendor/qrcode.js"></script>\n' + SCRIPT + "</body></html>")


CSS = """<style>
.gs{max-width:760px}
.gsum{margin:16px 0 4px;display:flex;flex-direction:column;gap:8px}
.gsum b{font-size:18px}
.gsbar{height:8px;border-radius:99px;background:var(--bar);overflow:hidden}
.gsbar i{display:block;height:100%;background:var(--good);width:0;transition:width .3s}
.gsrun{color:var(--muted);font-size:13px;margin:4px 0 0}
.gsopt{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:26px 0 0}
.gsoptp{margin:2px 0 0;color:var(--muted);font-size:13px}
.gsfoot{margin-top:20px;word-break:break-all}
.gsl{list-style:none;margin:16px 0 0;padding:0;display:flex;flex-direction:column;gap:10px}
.gsr{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:grid;grid-template-columns:28px minmax(0,1fr);gap:4px 12px}
.gsst{width:24px;height:24px;border-radius:50%;border:2px solid var(--line);display:grid;place-items:center;font-size:14px;font-weight:700;color:var(--muted);margin-top:1px}
.gsr.done .gsst{background:var(--good);border-color:var(--good);color:var(--surface)}
.gsr h2{margin:0;font-size:15px;font-weight:600}
.gsr h2 .opt{font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:99px;padding:1px 7px;margin-left:6px;vertical-align:1px}
.gsr p{margin:2px 0 0;color:var(--muted);font-size:13.5px}
.gsb{grid-column:2;min-width:0;display:flex;flex-direction:column;gap:8px;margin-top:6px;align-items:flex-start}
.gsb:empty{display:none}
.gsrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.gsb input[type=text]{flex:1 1 220px;min-width:0;height:var(--h);border:1px solid var(--line);border-radius:var(--r);padding:0 10px;background:var(--bg);color:var(--ink);font:inherit}
.gslog{width:100%;margin:0;max-height:160px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:12px/1.4 var(--mono);white-space:pre-wrap;word-break:break-word}
.gsmsg{font-size:13px;color:var(--muted)}
.gsmsg.err{color:var(--bad)}
.gsmsg.ok{color:var(--good)}
.gslink{width:100%;font:12.5px var(--mono);word-break:break-all;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;user-select:all}
.gsqr{width:200px;max-width:100%;border-radius:8px;border:1px solid var(--line);background:#fff;padding:0}
.gsqr svg{display:block;width:100%;height:auto}
.gsw{display:flex;align-items:center;gap:10px}
.gswarn{background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:8px 12px;font-size:13px;width:100%}
.gs details{width:100%}
.gs summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:13.5px}
.gs ol.steps{margin:8px 0 0;padding-left:20px;font-size:13.5px}
.gs ol.steps li{margin:3px 0}
.gs ol.clsteps{margin:0;padding-left:20px;font-size:13.5px;width:100%}
.gs ol.clsteps li{margin:5px 0}
.sw{appearance:none;-webkit-appearance:none;width:44px;height:26px;border-radius:999px;background:var(--bar);position:relative;cursor:pointer;margin:0;flex:none;transition:background .15s}
.sw::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:var(--surface);box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
.sw:checked{background:var(--accent)}
.sw:checked::after{transform:translateX(18px)}
.sw:disabled{opacity:.5;cursor:default}
</style>
"""

PANE_HTML = """<div class="gs">
  <div class="gsum"><b id="sumText">Checking this computer…</b><div class="gsbar" aria-hidden="true"><i id="sumBar"></i></div>
    <p class="gsrun" id="runLine"></p></div>
  <ul class="gsl" id="list"></ul>
  <h3 class="gsopt">Claude (optional)</h3>
  <p class="gsoptp">Optional: connect Claude to unlock Match ratings, resume reading and tailoring. Siftwell works without it.</p>
  <ul class="gsl" id="listClaude"></ul>
  <h3 class="gsopt">Other options</h3>
  <p class="gsoptp">Nice to have. These never count toward setup.</p>
  <ul class="gsl" id="listOpt"></ul>
  <p class="gsoptp gsfoot">Your information stays on this computer: your resume, profiles, saved jobs and ratings live in a folder on this PC, not in the cloud. Your data folder: <code>""" + html.escape(paths.DATA) + """</code></p>
</div>"""

BODY = """<div class="wrap">
<header class="top">
  <div class="brandline">
    """ + report.MARK + """<h1>Get started</h1>
  </div>
</header>
<main>
""" + PANE_HTML + """
</main>
</div>
"""

# The checklist's JS, shared by the standalone page and Settings. The host script must define $, esc, H and onStatus(status)
# (called each time /api/setup-status arrives) before this code, and call load(false) after it.
CHECKLIST_JS = r"""const api = (m, u, b) => fetch(u, {method: m, headers: m === "POST" ? H : undefined, body: b ? JSON.stringify(b) : undefined})
  .then(r => r.json().then(d => { if (!r.ok) throw Object.assign(new Error(d.error || "Something went wrong."), {data: d}); return d; }));
let S = null;
const ui = {msg: {}, login: null, loginMsg: "", restarting: false, busy: {}};
const say = (k, t, cls) => { ui.msg[k] = t ? {t, cls: cls || ""} : null; };
const msgHtml = k => ui.msg[k] ? `<span class="gsmsg ${ui.msg[k].cls}" role="status">${esc(ui.msg[k].t)}</span>` : "";

// ---- rows: [id, title, optional] -> {desc, body}
function rowClaude(){
  const i = S.install, c = S.claude;
  let desc = c.installed ? "Claude Code is on this computer. Siftwell uses it to rate jobs, read resumes and tailor them on your Claude plan." : "Optional. Claude Code (free to install) lets Siftwell rate jobs, read resumes and tailor them with your Claude plan. Siftwell works without it.";
  let body = "";
  if (i.running) {
    body = `<div class="gsmsg">Installing… ${i.elapsed}s. This can take a minute or two.</div><pre class="gslog" id="ilog">${esc(i.lines.join("\n"))}</pre>`;
  } else if (!c.installed) {
    body = `<div class="gsrow"><button class="btn primary" type="button" data-act="install">${i.exit != null ? "Try again" : "Install Claude Code"}</button></div>`;
    if (i.exit != null) body += `<span class="gsmsg err">${i.found === false && i.exit === 0 ? "The installer finished but Claude Code still isn't found." : "The installer stopped with an error (code " + i.exit + ")."} Try again, or see the log below.</span><pre class="gslog">${esc(i.lines.join("\n"))}</pre>`;
  } else if (i.exit === 0) {
    body = `<span class="gsmsg ok">Installed.</span>`;
  }
  return {desc, body: body + msgHtml("claude")};
}
function rowSignin(){
  const c = S.claude;
  if (c.signed_in) return {desc: "You're signed in, so ratings and tailoring will work.", body: ""};
  const desc = c.installed ? "Sign in with your Claude account (a paid Claude plan is needed). A sign-in page opens in a new tab." : "Install Claude Code first, then sign in.";
  if (!c.installed) return {desc, body: ""};
  if (ui.login) return {desc, body: `<ol class="clsteps">
      <li><a class="btn sm primary" href="${esc(ui.login)}" target="_blank" rel="noopener">Open the Claude sign-in page</a> and sign in with your Claude account.</li>
      <li>Copy the code the page shows, paste it here, and finish.<div class="gsrow" style="margin-top:6px;width:100%"><input type="text" id="clcode" placeholder="Paste the code" aria-label="Sign-in code" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="btn sm primary" type="button" data-act="code">Finish sign-in</button><button class="btn sm" type="button" data-act="cancel">Cancel</button></div></li>
    </ol><span class="gsmsg ${ui.loginMsg ? "err" : ""}" role="status">${esc(ui.loginMsg)}</span>`};
  return {desc, body: `<div class="gsrow"><button class="btn primary" type="button" data-act="start" ${ui.busy.login ? "disabled" : ""}>${ui.busy.login ? "Starting…" : "Sign in to Claude"}</button></div>` + msgHtml("signin")};
}
function rowBrowser(){
  const b = S.browser;
  if (b.found) return {desc: `${b.name} was found. Siftwell uses it to turn resumes into PDFs.`, body: ""};
  const mac = S.mac;
  return {desc: "Siftwell needs Google Chrome or Microsoft Edge to make resume PDFs. Install one, then come back and re-check.",
    body: `<div class="gsrow"><a class="btn" href="https://www.google.com/chrome/" target="_blank" rel="noopener">Get Google Chrome</a>${S.windows ? "" : mac ? "" : `<a class="btn" href="https://www.microsoft.com/edge" target="_blank" rel="noopener">Get Microsoft Edge</a>`}<button class="btn ghost" type="button" data-act="recheck">Re-check</button></div>
    <span class="gsmsg">${S.windows ? "Windows already includes Edge; if this still shows, reinstall it from microsoft.com/edge." : ""}</span>`};
}
function taskSteps(enable){
  return `<ol class="steps"><li>Open the Start menu, type <b>Task Scheduler</b> and open it.</li><li>Click <b>Task Scheduler Library</b> on the left.</li><li>Right-click <b>Job Board server</b> in the list and choose <b>${enable ? "Enable" : "Disable"}</b>.</li><li>Come back to this page and press <b>Re-check</b>${enable ? "" : ", then turn on the switch here"}.</li></ol><button class="btn sm ghost" type="button" data-act="recheck">Re-check</button>`;
}
function rowStartup(){
  const s = S.startup, sw = ui.sw, b = ui.busy.startup;
  const pnote = S.portable ? `<span class="gsmsg">This adds something to this computer (outside the Siftwell folder).</span>` : "";
  const wake = s.wake ? `<span class="gsmsg">Your PC wakes at 5:25 for the nightly update. That still works.</span>` : "";
  if (S.windows && s.task_enabled) {
    const dir = s.legacy_dir ? s.legacy_dir : "an older folder";
    const desc = `Your Siftwell starts through an older setup that points at ${dir}. Switch so it keeps working if you move or delete that folder.`;
    let body = "";
    if (s.own) body += `<div class="gswarn">The older setup and the new startup are both turned on, so Siftwell may try to start twice when you sign in. Press Switch to turn the older one off.</div>`;
    body += `<div class="gsrow"><button class="btn primary" type="button" data-act="switch" ${b ? "disabled" : ""}>${b ? "Switching…" : "Switch to the new startup"}</button></div>`
      + `<span class="gsmsg">Siftwell keeps running right now. The new startup takes over the next time you sign in to Windows. The older task is turned off, not deleted.</span>`;
    if (sw && sw.op === "switch" && sw.state === "denied") body += `<div class="gswarn">Windows needs administrator permission to turn off that older task. <button class="btn sm primary" type="button" data-act="switch-admin" ${b ? "disabled" : ""}>Allow (asks for administrator permission)</button></div><details><summary>Or turn it off by hand</summary>${taskSteps(false)}</details>`;
    else if (sw && sw.op === "switch" && sw.state === "declined") body += `<div class="gsmsg err">The administrator permission prompt was declined, so nothing was changed. You can turn the older task off by hand instead:</div>${taskSteps(false)}`;
    else if (sw && sw.op === "switch" && sw.state === "failed") body += `<div class="gsmsg err">${esc(sw.message)}</div>${taskSteps(false)}`;
    return {desc, body: body + pnote + wake + msgHtml("startup")};
  }
  let desc = "Siftwell starts by itself when you sign in to this computer, so the board is always ready.";
  if (s.on) desc = "On. Siftwell will start the next time you sign in to this computer.";
  let body = `<label class="gsw"><input type="checkbox" class="sw" role="switch" id="swStartup" ${s.on ? "checked" : ""} ${b ? "disabled" : ""}><span>${s.on ? "On" : "Off"}</span></label>`;
  if (S.windows && s.task && s.own) {
    desc = "On, through the new startup. The older \"Job Board server\" task is turned off.";
    body += `<div class="gsrow"><button class="btn sm ghost" type="button" data-act="undo" ${b ? "disabled" : ""}>Undo (go back to the older setup)</button></div>`;
    if (sw && sw.op === "undo" && sw.state === "denied") body += `<div class="gswarn">Windows needs administrator permission to turn that older task back on. <button class="btn sm primary" type="button" data-act="undo-admin" ${b ? "disabled" : ""}>Allow (asks for administrator permission)</button></div><details><summary>Or turn it on by hand</summary>${taskSteps(true)}</details>`;
    else if (sw && sw.op === "undo" && (sw.state === "declined" || sw.state === "failed")) body += `<div class="gsmsg err">${esc(sw.message)}</div>${taskSteps(true)}`;
  }
  return {desc, body: body + pnote + wake + msgHtml("startup")};
}
function rowPhone(){
  const p = S.phone;
  let desc = p.on ? "Phones and tablets on your home Wi-Fi can open Siftwell." : "Right now only this computer can open Siftwell. Turn this on to use it from phones on your home Wi-Fi.";
  let body = `<label class="gsw"><input type="checkbox" class="sw" role="switch" id="swPhone" ${p.on ? "checked" : ""} ${ui.busy.phone || ui.restarting ? "disabled" : ""}><span>${p.on ? "On" : "Off"}</span></label>`;
  if (p.restart_needed && p.restart_manual) body += `<div class="gswarn">This change takes effect after you sign out of Windows and back in (or restart the computer). Siftwell is started by a Windows scheduled task here, so it can't restart itself.</div>`;
  else if (p.restart_needed) body += `<div class="gswarn">Restart Siftwell to apply this change. <button class="btn sm primary" type="button" data-act="restart" ${ui.restarting ? "disabled" : ""}>${ui.restarting ? "Restarting…" : "Restart now"}</button></div>`;
  if (p.on) {
    if (p.url) body += `<div class="gsmsg">On your phone, open this link (anyone with it can use Siftwell on your network, so keep it private):</div><div class="gslink" id="phoneLink">${esc(p.url)}</div><div class="gsqr" id="qr" aria-label="QR code for the phone link" role="img"></div>`
      + `<span class="gsmsg">${S.windows ? "The first time, Windows asks whether to allow Siftwell on your network. Choose Allow access on private networks. " : ""}Your phone must be on the same Wi-Fi as this computer.</span>`;
    else body += `<span class="gsmsg err">Couldn't find this computer's address on your network. Connect to Wi-Fi and re-check.</span><button class="btn ghost" type="button" data-act="recheck">Re-check</button>`;
  }
  return {desc, body: body + msgHtml("phone")};
}
function rowKeep(){
  const k = S.keep, p = S.phone;
  let desc = "When this is on, Siftwell keeps running in the background after you close its window, with no window or icon showing, until you turn this off, double-click Stop Siftwell, or restart your computer. It uses a little memory and stays reachable on your home network so your phone can open it. A Siftwell icon appears in the system tray (near the clock) while it runs in the background; right-click it to open or stop Siftwell.";
  let body = `<label class="gsw"><input type="checkbox" class="sw" role="switch" id="swKeep" ${k.on ? "checked" : ""} ${ui.busy.keep ? "disabled" : ""}><span>${k.on ? "On" : "Off"}</span></label>`;
  if (k.on) body += `<span class="gsmsg">Siftwell is running in the background. Turn this off to have it stop when you close the window.</span>`;
  if (k.on && !p.on) body += `<span class="gsmsg">Phone access above is off, so only this computer can open Siftwell while it runs in the background.</span>`;
  return {desc, body: body + msgHtml("keep")};
}
function rowAstra(){
  const a = S.astra;
  if (a.found) return {desc: "Codex is installed. Run `codex login` once with ChatGPT if you haven't, and Astra can grade tailored resumes.", body: ""};
  return {desc: "Astra is a second opinion on tailored resumes, using ChatGPT through the Codex app. Siftwell works fine without it.",
    body: `<details><summary>How to set up</summary><ol class="steps">
      <li>Install Node.js (the LTS version) from <a href="https://nodejs.org/" target="_blank" rel="noopener">nodejs.org</a>.</li>
      <li>Open a terminal and run <code>npm install -g @openai/codex</code>.</li>
      <li>Run <code>codex login</code> and sign in with your ChatGPT account.</li>
      <li>Come back here and re-check.</li></ol></details><button class="btn ghost" type="button" data-act="recheck">Re-check</button>`};
}
const ROWS = {claude: rowClaude, signin: rowSignin, browser: rowBrowser, startup: rowStartup, phone: rowPhone, keep: rowKeep, astra: rowAstra};

function drawQR(){
  const el = $("qr"); if (!el || !S.phone.url || typeof qrcode !== "function") return;
  try {
    const q = qrcode(0, "M"); q.addData(S.phone.url); q.make();
    const n = q.getModuleCount(), m = 3; let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) d += `M${c + m} ${r + m}h1v1h-1z`;
    el.innerHTML = `<svg viewBox="0 0 ${n + 2 * m} ${n + 2 * m}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  } catch(e) { el.textContent = "Couldn't draw the QR code. Use the link above."; }
}

function render(only){
  if (!S) return;
  const req = S.items.filter(i => !i.optional);
  $("sumText").textContent = S.complete ? "All set. Siftwell is ready to use." : `${S.done} of ${S.total} done`;
  $("sumBar").style.width = Math.round(S.done / S.total * 100) + "%";
  $("runLine").textContent = `Siftwell is running on port ${S.port} on this computer.`;
  const list = $("list");
  S.items.forEach(it => {
    if (only && only !== it.id) return;
    if (it.id === "signin" && ui.login && !only) return;  // keep a half-typed sign-in code
    let li = $("row-" + it.id);
    if (!li) { li = document.createElement("li"); li.id = "row-" + it.id; (it.group === "claude" ? $("listClaude") : it.optional ? $("listOpt") : list).appendChild(li); }
    const r = ROWS[it.id]();
    li.className = "gsr" + (it.done ? " done" : "");
    li.innerHTML = `<span class="gsst" aria-hidden="true">${it.done ? "✓" : "○"}</span><div><h2>${esc(it.title)}${it.optional ? '' : ""}<span class="vh">${it.done ? " (done)" : " (not done)"}</span></h2><p>${esc(r.desc)}</p></div><div class="gsb">${r.body}</div>`;
  });
  drawQR();
}
function load(fresh){
  return api("GET", "/api/setup-status" + (fresh ? "?fresh=1" : "")).then(d => { S = d; onStatus(d); render(); if (d.install.running) pollInstall(); })
    .catch(e => { $("sumText").textContent = "Couldn't check this computer."; $("runLine").textContent = e instanceof TypeError ? "Is Siftwell still running?" : e.message; });
}
let polling = false;
function pollInstall(){
  if (polling) return; polling = true;
  const tick = () => api("GET", "/api/getting-started/install").then(d => {
    S.install = d;
    if (d.running) { render("claude"); setTimeout(tick, 1200); return; }
    polling = false;
    load(true);  // re-check everything at the end
  }).catch(() => { polling = false; });
  tick();
}

// ---- actions
const clPost = body => fetch("/api/claude/login", {method: "POST", headers: H, body: JSON.stringify(body)}).then(r => r.json().then(d => ({ok: r.ok, d})));
document.addEventListener("click", e => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const act = b.dataset.act;
  if (act === "install") { b.disabled = true; say("claude", ""); api("POST", "/api/getting-started/install", {}).then(d => { if (d.already) return load(true); S.install = Object.assign(S.install, {running: true, lines: [], exit: null, elapsed: 0}); render("claude"); pollInstall(); }).catch(err => { say("claude", err.message, "err"); render("claude"); }); }
  if (act === "recheck") load(true);
  if (act === "start") {
    ui.busy.login = true; say("signin", ""); render("signin");
    clPost({action: "start"}).then(({ok, d}) => { if (!ok) throw new Error(d.error || "Couldn't start sign-in."); ui.login = d.url; ui.loginMsg = ""; })
      .catch(err => say("signin", err.message, "err")).finally(() => { ui.busy.login = false; render("signin"); });
  }
  if (act === "code") {
    const code = ($("clcode") || {}).value || "";
    if (!code.trim()) { ui.loginMsg = "Paste the code from the sign-in page first."; render("signin"); return; }
    b.disabled = true; b.textContent = "Checking…";
    clPost({action: "code", code}).then(({ok, d}) => {
      if (!ok) throw Object.assign(new Error(d.error || "Sign-in didn't go through."), {expired: !!d.expired});
      ui.login = null; ui.loginMsg = ""; load(true);
    }).catch(err => { ui.loginMsg = err.message; if (err.expired) ui.login = null; render("signin"); });
  }
  if (act === "cancel") { clPost({action: "cancel"}); ui.login = null; ui.loginMsg = ""; render("signin"); }
  if (act === "restart") restart();
  if (act === "switch" || act === "switch-admin" || act === "undo" || act === "undo-admin") {
    const undo = act.startsWith("undo"), admin = act.endsWith("admin");
    ui.busy.startup = true; ui.sw = null; say("startup", ""); render("startup");
    api("POST", "/api/getting-started/" + (undo ? "unswitch" : "switch"), {elevated: admin})
      .then(d => { S = d; const r = d.switch || {}; if (r.state === "ok") say("startup", r.message, "ok"); else ui.sw = r; })
      .catch(err => say("startup", err.message, "err")).finally(() => { ui.busy.startup = false; render(); });
  }
});
document.addEventListener("change", e => {
  const el = e.target;
  if (el.id === "swStartup" || el.id === "swPhone" || el.id === "swKeep") {
    const k = el.id === "swStartup" ? "startup" : el.id === "swKeep" ? "keep" : "phone", on = el.checked;
    ui.busy[k] = true; say(k, ""); render(k);
    api("POST", "/api/getting-started/" + (k === "phone" ? "network" : k), {on})
      .then(d => { S = d; say(k, k === "phone" ? "" : (on ? "Turned on." : "Turned off."), "ok"); })
      .catch(err => say(k, err.message, "err")).finally(() => { ui.busy[k] = false; render(); });
  }
});
function restart(){
  ui.restarting = true; render("phone");
  api("POST", "/api/getting-started/restart", {}).then(() => {
    const t0 = Date.now();
    const wait = () => {
      if (Date.now() - t0 > 90000) { ui.restarting = false; say("phone", "Siftwell didn't come back. Start it again from its icon.", "err"); return render("phone"); }
      fetch("/api/ping", {cache: "no-store"}).then(r => r.json()).then(d => { if (d.app === "siftwell" && Date.now() - t0 > 2500) { ui.restarting = false; load(true); } else setTimeout(wait, 1000); }).catch(() => setTimeout(wait, 1000));
    };
    setTimeout(wait, 1500);
  }).catch(err => { ui.restarting = false; say("phone", err.message, "err"); render("phone"); });
}
"""

SCRIPT = r"""<script>
(function(){
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const onStatus = () => {};
""" + CHECKLIST_JS + """
load(false);
})();
</script>
"""
