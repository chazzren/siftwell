"""Siftwell's own desktop window: the existing web UI inside a native window (pywebview: Edge WebView2 on Windows,
WKWebView on a Mac), with no browser chrome and no tray icon. A normal taskbar app.

    python app_window.py                 open a window on the running Siftwell; start the server first if none is running
    python app_window.py --owns-server   same, but the launcher just started the server for this window

Closing the window:
  * the window started the server (or was told to with --owns-server): closing stops Siftwell (the server and anything it
    is running), unless "Keep Siftwell available to my phone when the window is closed" is on (DATA/network.json
    {"keep": true}); then the server keeps running headless and the next start just opens a window on it;
  * the window attached to a server that was already running (for example the one started at sign-in): closing only
    closes the window.
If a job (update, re-rate) is running when a stopping window is closed, it asks first.

If pywebview or the WebView2 runtime isn't available the page opens in the normal browser instead, with a one-time
message, and the server is left running (use "Stop Siftwell" to end it).

Links to other sites, and anything that wants a new window (target=_blank), open in the person's normal browser, never
inside this window. Downloads (resume PDF / Word) show the system "save as" dialog.
Window size and position are remembered in DATA/window.json. Nothing is written into the app folder.
Mac code paths are written carefully but untested.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
sys.dont_write_bytecode = True
import paths  # noqa: E402  (no side effects beyond path constants)
import frozen  # noqa: E402  (how to start another Siftwell process: from source or as the installed exe)
sys.dont_write_bytecode = False

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
TITLE = "Siftwell"
DEFAULT_SIZE = (1280, 860)
MIN_SIZE = (520, 480)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ICON_ICO = os.path.join(APP, "assets", "brand", "siftwell.ico")
ICON_PNG = os.path.join(APP, "assets", "brand", "icon-512.png")
APP_ID = "Siftwell.App"

LOG = os.path.join(paths.DATA, "window.log")
GEOM = os.path.join(paths.DATA, "window.json")
NETWORK = os.path.join(paths.DATA, "network.json")
LOCK = os.path.join(paths.DATA, "window.pid")
FALLBACK_SEEN = os.path.join(paths.DATA, "window-fallback.seen")
PROFILE = os.path.join(paths.DATA, "webview")      # WebView2 / WebKit site data (cookie for the chosen profile, theme)


# ---------------------------------------------------------------- small helpers
def log(msg):
    try:
        os.makedirs(paths.DATA, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200_000:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except OSError:
        pass


def _no_std_streams():
    """pythonw has no console: anything printed (including pywebview's own logging) goes to window.log instead."""
    if sys.stdout is None or sys.stderr is None:
        try:
            os.makedirs(paths.DATA, exist_ok=True)
            f = open(LOG, "a", encoding="utf-8", buffering=1)
            if sys.stdout is None:
                sys.stdout = f
            if sys.stderr is None:
                sys.stderr = f
        except OSError:
            pass


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def keep_available():
    """DATA/network.json {"keep": bool}, default off (written by Settings -> Get started)."""
    d = read_json(NETWORK, {})
    return bool(d.get("keep")) if isinstance(d, dict) else False


def get_port():
    p = os.environ.get("SIFTWELL_PORT", "")
    if p.isdigit() and 1024 <= int(p) <= 65535:
        return int(p)
    return paths.read_port()


def window_title(port):
    """"Siftwell", or "Siftwell (test copy, port 8767)" when this copy isn't on the normal port, so copies can be told apart."""
    return TITLE if port == paths.DEFAULT_PORT else f"{TITLE} (test copy, port {port})"


def fetch(url, timeout=3, cookie=None):
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ping(port):
    """The /api/ping answer of a Siftwell on this port (any data folder), or None."""
    try:
        d = json.loads(fetch(f"http://127.0.0.1:{port}/api/ping"))
        return d if isinstance(d, dict) and d.get("app") == "siftwell" else None
    except Exception:
        return None


def server_up(port):
    """A Siftwell that uses THIS data folder answers on the port (one without a data id is an older build of the same
    app: counted as ours). A Siftwell with another data folder, such as the main copy next to a test copy, is not ours."""
    d = ping(port)
    return bool(d) and d.get("data") in (None, paths.data_id())


def other_siftwell(port):
    d = ping(port)
    return bool(d) and d.get("data") not in (None, paths.data_id())


def choose_port(port):
    """-> (port, explain). Keeps `port` unless something that isn't this copy's Siftwell holds it (another copy's Siftwell
    or any other program); then the first free port of the fallback range (8767-8775), remembered in THIS data folder's
    port file. Never touches whatever holds the port. A Siftwell server of ours that is starting up counts as ours."""
    if server_up(port) or not (other_siftwell(port) or _port_in_use(port)):
        return port, ""
    pid = read_pid_file(paths.PID_FILE)
    if pid and verify_siftwell(pid, "server", paths.PID_FILE)[0]:
        return port, ""                    # our own server, still starting
    for p in [paths.default_port()] + paths.fallback_ports():
        if p != port and not _port_in_use(p):
            if not os.environ.get("SIFTWELL_PORT"):
                try:
                    os.makedirs(paths.DATA, exist_ok=True)
                    with open(paths.PORT_FILE, "w") as f:
                        f.write(str(p))
                except OSError:
                    pass
            return p, f"port {port} is taken by another {'Siftwell copy' if other_siftwell(port) else 'program'}; using port {p}"
    return None, f"port {port} is taken and so are the fallback ports"


def wait_server(port, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if server_up(port):
            return True
        time.sleep(0.5)
    return False


def message(text, ask=False):
    """A small native message box. With ask=True returns True for Yes. Never raises."""
    try:
        if WINDOWS:
            import ctypes
            # MB_YESNO|MB_ICONWARNING (0x24) or MB_OK|MB_ICONINFORMATION (0x40), MB_SETFOREGROUND 0x10000, MB_TOPMOST 0x40000
            r = ctypes.windll.user32.MessageBoxW(0, text, TITLE, (0x24 if ask else 0x40) | 0x10000 | 0x40000)
            return r == 6 if ask else True
        if MAC:
            esc = text.replace("\\", "\\\\").replace('"', '\\"')
            btns = '{"Cancel", "Close anyway"} default button "Cancel"' if ask else '{"OK"} default button "OK"'
            r = subprocess.run(["osascript", "-e", f'display dialog "{esc}" with title "{TITLE}" buttons {btns}'],
                               capture_output=True, text=True, timeout=600)
            return ("Close anyway" in (r.stdout or "")) if ask else True
    except Exception as e:
        log(f"message box failed: {e}")
    return True


# ---------------------------------------------------------------- processes
def _pid_alive(pid):
    try:
        if WINDOWS:
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


def _is_python_proc(pid):
    """True if pid is a live Python process (tasklist image name on Windows, ps command line elsewhere)."""
    try:
        if WINDOWS:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                               timeout=15, creationflags=NOWIN)
            return r.stdout.strip().lower().startswith(('"python', '"siftwell'))   # source run, or the installed Siftwell.exe
        r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=15)
        return "python" in r.stdout.lower() or "siftwell" in r.stdout.lower()
    except Exception:
        return False


def kill_tree(pid):
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=NOWIN)
        return
    subprocess.run(["pkill", "-TERM", "-P", str(pid)], capture_output=True, timeout=15)
    try:
        os.kill(pid, 15)
    except OSError:
        return
    for _ in range(20):
        if not _pid_alive(pid):
            return
        time.sleep(0.25)
    subprocess.run(["pkill", "-KILL", "-P", str(pid)], capture_output=True, timeout=15)
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def server_python():
    """Interpreter for the server: the one running this window (pythonw next to it on Windows, so no console)."""
    return frozen.interpreter(windowed=True)


def start_server(port):
    """Start server.py detached from this window, so it can outlive it (keep-available). Returns the Popen."""
    cmd = frozen.command("server", port, utf8=True, windowed=True)
    kw = dict(stdin=subprocess.DEVNULL, cwd=APP)
    if WINDOWS:
        kw.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  creationflags=NOWIN | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        lf = open(os.path.join(paths.data(), "launcher.log"), "ab")
        kw.update(stdout=lf, stderr=lf, start_new_session=True)
    p = subprocess.Popen(cmd, **kw)
    try:
        os.makedirs(paths.DATA, exist_ok=True)
        with open(paths.PID_FILE, "w") as f:       # same as the launchers: the pid they stop (its tree) later
            f.write(str(p.pid))
    except OSError:
        pass
    log(f"started server pid {p.pid} on port {port}")
    return p


def proc_info(pid):
    """What a live process is: {"exe", "cmd", "created"} (created = epoch seconds), or None if it isn't running. Used to
    check that a pid from a pid file is really Siftwell before anything is stopped."""
    try:
        if WINDOWS:
            ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                  f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; "
                  "if($p){[pscustomobject]@{exe=$p.ExecutablePath;cmd=$p.CommandLine;"
                  "created=([DateTimeOffset]$p.CreationDate).ToUnixTimeMilliseconds()} | ConvertTo-Json -Compress}")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               timeout=30, creationflags=NOWIN)
            out = (r.stdout or b"").decode("utf-8", "replace").strip()
            if not out:
                return None
            d = json.loads(out)
            return {"exe": d.get("exe") or "", "cmd": d.get("cmd") or "", "created": (d.get("created") or 0) / 1000.0}
        r = subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True, timeout=15)
        cmd = (r.stdout or "").strip()
        if not cmd:
            return None
        exe = cmd.split(" ")[0]
        if MAC:
            # `comm` is the full path of the program on a Mac, which may contain spaces (Siftwell.app in a folder
            # called "My Apps"); the first word of the command line would cut it short.
            c = subprocess.run(["ps", "-p", str(int(pid)), "-o", "comm="], capture_output=True, text=True, timeout=15)
            full = (c.stdout or "").strip()
            if full.startswith("/") and cmd.startswith(full):
                exe = full
        r = subprocess.run(["ps", "-p", str(int(pid)), "-o", "etime="], capture_output=True, text=True, timeout=15)
        created = 0.0
        m = re.fullmatch(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)", (r.stdout or "").strip())
        if m:
            dd, hh, mm, ss = (int(x or 0) for x in m.groups())
            created = time.time() - (((dd * 24 + hh) * 60 + mm) * 60 + ss)
        return {"exe": exe, "cmd": cmd, "created": created}
    except Exception as e:
        log(f"couldn't inspect pid {pid}: {e}")
        return None


def _norm_path(s):
    return os.path.normcase(str(s or "")).replace("/", os.sep)


def _runs_script(cmd, script, args_re=r"(\s+\d+)?"):
    """Does the command line run exactly `script` (an absolute path in this app folder) as
    `<python> [-X utf8 | -flags] <script> [args]`? Relative paths, other folders, `python -c "..." <script>` and an editor
    that merely mentions the path never match."""
    c = str(cmd or "").strip()
    if c.startswith('"'):
        end = c.find('"', 1)
        exe, rest = (c[1:end], c[end + 1:]) if end > 0 else ("", "")
    else:
        exe, _, rest = c.partition(" ")
        rest = " " + rest
    if not re.match(r"^pythonw?[\d.]*(\.exe)?$", re.split(r"[\\/]", exe)[-1].lower()):
        return False
    sc = re.escape(_norm_path(script))
    pat = r"^\s+(?:-X\s+\S+\s+|-[BEIOsSuvx]+\s+)*\"?" + sc + r"\"?" + args_re + r"\s*$"
    return re.match(pat, _norm_path(rest), re.I) is not None


KIND_SCRIPTS = {"server": (("server.py", r"(\s+\d+)?"), ("getting_started.py", r"\s+--serve")),
                "window": (("app_window.py", r"(\s+--owns-server)?"),), "tray": (("tray.py", r"(\s+\d+)?"),)}
KIND_FROZEN_MODES = {"server": ("--server",), "tray": ("--tray",), "window": ("", "--window", "--owns-server")}
PID_SLACK = 2.0   # seconds a process may be newer than its pid file (the pid is written just after the process starts)


def verify_siftwell(pid, kind, pidfile):
    """Is `pid` (read from this data folder's `pidfile`) really this copy's Siftwell `kind` ("server"/"window"/"tray")?
    Returns (ok, why). The process must be the same Siftwell.exe (installed) or a Python running this app folder's script
    (source), and must not have been created after the pid file was written (that would be a reused pid)."""
    info = proc_info(pid)
    if not info:
        return False, "not running"
    try:
        written = os.path.getmtime(pidfile)
    except OSError:
        written = 0
    if written and info["created"] and info["created"] > written + PID_SLACK:
        return False, "started after the pid file was written (reused pid)"
    if frozen.FROZEN:
        if _norm_path(os.path.abspath(info["exe"])) != _norm_path(os.path.abspath(sys.executable)):
            return False, "not this Siftwell.exe"
        rest = info["cmd"][len(info["exe"]):] if info["cmd"].startswith(info["exe"]) else " ".join(info["cmd"].split()[1:])
        mode = next((w for w in rest.split() if w.startswith("--")), "")
        return (mode in KIND_FROZEN_MODES[kind]), "different Siftwell mode"
    for script, args_re in KIND_SCRIPTS[kind]:
        if _runs_script(info["cmd"], os.path.join(APP, script), args_re):
            return True, ""
    return False, "not running this app folder's " + KIND_SCRIPTS[kind][0][0]


def read_pid_file(path):
    try:
        return int(open(path).read().strip())
    except (OSError, ValueError):
        return 0


def stop_recorded(kind, wait=8):
    """Stop the process recorded in this data folder's <kind>.pid ("server" / "window" / "tray"), and what it started,
    but only after verify_siftwell(). Never looks anything up by port. Returns "stopped", "none" (no pid file, or the
    process is gone: a stale file is removed) or "refused" (the pid belongs to something that isn't this Siftwell; left
    alone)."""
    pf = paths.PID_FILE if kind == "server" else os.path.join(paths.DATA, kind + ".pid")
    pid = read_pid_file(pf)
    if not pid or pid == os.getpid():
        return "none"
    ok, why = verify_siftwell(pid, kind, pf)
    if not ok:
        if why == "not running":
            try:
                os.remove(pf)
            except OSError:
                pass
            return "none"
        log(f"not stopping pid {pid} from {os.path.basename(pf)}: {why}")
        return "refused"
    log(f"stopping {kind} pid {pid}")
    kill_tree(pid)
    end = time.time() + wait
    while time.time() < end and _pid_alive(pid):
        time.sleep(0.25)
    if not _pid_alive(pid):
        try:
            os.remove(pf)
        except OSError:
            pass
    return "stopped"


def _port_in_use(port):
    """True if something already has this TCP port (a bind test: nothing connects to it)."""
    import socket
    sk = socket.socket()
    try:
        sk.bind(("0.0.0.0", int(port)))
        return False
    except OSError:
        return True
    finally:
        sk.close()


NOT_RUNNING_HINT = "If Siftwell was started some other way, restart your computer or sign out and back in."


def stop_server_report(port=None):
    """Stop this data folder's Siftwell server. Returns (ok: bool, message). Only the pid in DATA/server.pid is ever
    stopped (after verify_siftwell); a missing or stale pid file means "not running" and nothing is touched. `port`
    (when known) only words the message: it is never used to find a process."""
    r = stop_recorded("server")
    if r == "stopped":
        return True, "Siftwell has stopped."
    if r == "refused":
        return False, ("The program recorded as Siftwell's isn't Siftwell, so nothing was stopped. " + NOT_RUNNING_HINT)
    if port and ping(port):
        return False, (f"Siftwell is answering on port {port}, but it wasn't started from this copy, so Stop can't end it. "
                       + NOT_RUNNING_HINT)
    if port and _port_in_use(port):
        return True, f"Siftwell isn't running (from this copy); a different program is using port {port}. " + NOT_RUNNING_HINT
    return True, "Siftwell isn't running (from this copy). " + NOT_RUNNING_HINT


def stop_server(port=None, proc=None):
    """Stop the Siftwell server recorded in DATA/server.pid (and what it started). `proc` is ignored (kept for older
    callers): the pid file is the only record. Returns True when nothing of ours is left to stop."""
    ok, msg = stop_server_report(port)
    log("stop: " + msg)
    return ok


# ---------------------------------------------------------------- one window per data folder
def _focus_existing():
    """If a Siftwell window of this data folder is already open, bring it to the front and return True."""
    pid = 0
    try:
        pid = int(open(LOCK).read().strip())
    except (OSError, ValueError):
        pass
    if not pid or pid == os.getpid() or not _is_python_proc(pid):
        return False
    log(f"window already open (pid {pid})")
    try:
        if WINDOWS:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            found = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cb(hwnd, _):
                p = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                if p.value == pid and user32.IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(64)
                    user32.GetWindowTextW(hwnd, buf, 64)
                    if buf.value.startswith(TITLE):
                        found.append(hwnd)
                return True
            user32.EnumWindows(cb, 0)
            for hwnd in found:
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        elif MAC:
            subprocess.run(["osascript", "-e", f'tell application "System Events" to set frontmost of '
                            f'(first process whose unix id is {pid}) to true'], capture_output=True, timeout=15)
    except Exception as e:
        log(f"couldn't focus the open window: {e}")
    return True


def _write_lock():
    try:
        os.makedirs(paths.DATA, exist_ok=True)
        with open(LOCK, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _clear_lock():
    try:
        if int(open(LOCK).read().strip()) == os.getpid():
            os.remove(LOCK)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- window geometry
def load_geometry():
    g = read_json(GEOM, {})
    out = {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1], "x": None, "y": None, "maximized": False}
    if not isinstance(g, dict):
        return out
    try:
        w, h = int(g.get("width")), int(g.get("height"))
        if MIN_SIZE[0] <= w <= 10000 and MIN_SIZE[1] <= h <= 10000:
            out.update(width=w, height=h)
    except (TypeError, ValueError):
        pass
    try:
        x, y = int(g.get("x")), int(g.get("y"))
        if _on_a_screen(x, y):
            out.update(x=x, y=y)
    except (TypeError, ValueError):
        pass
    out["maximized"] = bool(g.get("maximized"))
    return out


def _on_a_screen(x, y):
    """Is the top-left corner of the saved window on a connected screen (a monitor may have been unplugged)?"""
    try:
        if WINDOWS:
            import ctypes
            u = ctypes.windll.user32
            left, top = u.GetSystemMetrics(76), u.GetSystemMetrics(77)          # virtual screen origin
            w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)               # and size
            return left - 20 <= x < left + w - 100 and top - 20 <= y < top + h - 100
    except Exception:
        pass
    return -5000 < x < 10000 and -100 < y < 10000


def save_geometry(g):
    try:
        os.makedirs(paths.DATA, exist_ok=True)
        tmp = GEOM + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(g, f)
        os.replace(tmp, GEOM)
    except OSError:
        pass


# ---------------------------------------------------------------- opening other sites in the normal browser
def open_external(url):
    """Open http(s)/mailto links in the person's normal browser. Anything else is ignored."""
    u = str(url or "")
    if u.lower().startswith(("http://", "https://", "mailto:")):
        log(f"external link: {u[:200]}")
        try:
            webbrowser.open(u)
            return True
        except Exception as e:
            log(f"couldn't open the browser: {e}")
    return False


class Api:
    """Exposed to the page as pywebview.api (only open_external)."""
    def open_external(self, url):
        return open_external(url)


# Every click on a link to another site (even without target=_blank) goes to the normal browser.
EXTERNAL_LINK_JS = r"""(function(){
  if (window.__swExt) return; window.__swExt = 1;
  document.addEventListener("click", function(e){
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null; if (!a) return;
    var u; try { u = new URL(a.href, location.href); } catch (_) { return; }
    if (u.protocol !== "http:" && u.protocol !== "https:" && u.protocol !== "mailto:") return;
    if (u.protocol !== "mailto:" && u.origin === location.origin) return;
    e.preventDefault();
    if (window.pywebview && pywebview.api) pywebview.api.open_external(u.href);
  }, true);
})();"""


def _busy_reason(port):
    """What would be lost if the server stopped now ('' when idle). Best effort, never raises."""
    base = f"http://127.0.0.1:{port}"
    try:
        s = json.loads(fetch(base + "/api/status"))
        if s.get("running"):
            return "job listings are being updated"
        if s.get("recomputing"):
            return "ratings are being recalculated"
    except Exception:
        return ""
    try:
        for p in (json.loads(fetch(base + "/api/people")).get("people") or []):
            r = json.loads(fetch(base + "/api/rerate", cookie=f"jb_person={p.get('id')}"))
            if r.get("running"):
                return "Claude is re-rating jobs"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- window / taskbar icon
def set_window_icon(window=None):
    """pywebview ignores icons on Windows, so send WM_SETICON (big + small) to our own top-level window. Returns True
    when both icons were sent. Mac: sets the Dock icon through AppKit when PyObjC is there (it is, with pywebview)."""
    try:
        if WINDOWS:
            import ctypes
            from ctypes import wintypes
            if not os.path.exists(ICON_ICO):
                return False
            user32 = ctypes.windll.user32
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            hwnds = []
            me = os.getpid()

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cb(hwnd, _):
                p = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                if p.value == me and user32.IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(64)
                    user32.GetWindowTextW(hwnd, buf, 64)
                    if buf.value.startswith(TITLE):
                        hwnds.append(hwnd)
                return True
            user32.EnumWindows(cb, 0)
            if not hwnds:
                return False
            # LR_LOADFROMFILE 0x10; IMAGE_ICON 1; WM_SETICON 0x80; ICON_SMALL 0, ICON_BIG 1
            big = user32.LoadImageW(None, ICON_ICO, 1, user32.GetSystemMetrics(11), user32.GetSystemMetrics(12), 0x10)   # SM_CXICON
            small = user32.LoadImageW(None, ICON_ICO, 1, user32.GetSystemMetrics(49), user32.GetSystemMetrics(50), 0x10)  # SM_CXSMICON
            if not big or not small:
                log("window icon: couldn't load the .ico")
                return False
            for h in hwnds:
                user32.SendMessageW(h, 0x80, 1, big)
                user32.SendMessageW(h, 0x80, 0, small)
            _ICONS.extend([big, small])      # keep the handles for the life of the process
            log(f"window icon set on {len(hwnds)} window(s)")
            return True
        if MAC and os.path.exists(ICON_PNG):
            from AppKit import NSApplication, NSImage
            img = NSImage.alloc().initWithContentsOfFile_(ICON_PNG)
            if img is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
                return True
    except Exception as e:
        log(f"couldn't set the window icon: {e}")
    return False


_ICONS = []


# ---------------------------------------------------------------- the window
def _fallback_to_browser(url, why):
    log(f"no window ({why}); opening the browser")
    open_external(url)
    if not os.path.exists(FALLBACK_SEEN):
        try:
            open(FALLBACK_SEEN, "w").write(time.strftime("%Y-%m-%d"))
        except OSError:
            pass
        message("Siftwell couldn't open its own window on this computer, so it opened in your web browser instead.\n\n"
                "Siftwell keeps running in the background. To stop it, use Stop Siftwell.")


def main(argv=None, ready=None):
    """Returns an exit code. `ready(window)` (tests) is called on a worker thread once the window exists."""
    argv = list(sys.argv[1:] if argv is None else argv)
    owns = "--owns-server" in argv
    _no_std_streams()
    bad = paths.data_problem()
    if bad:
        log("data folder not writable")
        message(bad)
        return 1
    port = get_port()

    if _focus_existing():
        return 0

    port, why = choose_port(port)
    if port is None:
        message("Siftwell couldn't find a free port. Close some programs or restart the computer, then try again.")
        return 1
    if why:
        log(why)
    url = f"http://127.0.0.1:{port}/"

    proc = None
    if not server_up(port):
        if not owns:
            owns = True
            proc = start_server(port)
        if not wait_server(port, 60):
            log("the server didn't answer within a minute")
            message("Siftwell didn't start. Details are in the data folder (server.log, window.log).")
            return 1

    try:
        import webview
        if webview.settings is not None:
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # target=_blank / window.open -> normal browser
    except Exception as e:
        _fallback_to_browser(url, f"pywebview is not available: {e}")
        return 0

    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)   # own taskbar button (and the funnel, not Python's icon)
        except Exception:
            pass

    geom = load_geometry()
    state = {"max": False, "min": False, "geom": dict(geom)}
    api = Api()
    window = webview.create_window(
        window_title(port), url, js_api=api, width=geom["width"], height=geom["height"], x=geom["x"], y=geom["y"],
        min_size=MIN_SIZE, maximized=geom["maximized"], text_select=True, zoomable=True, confirm_close=False)
    state["max"] = geom["maximized"]

    def remember(*_):
        if state["max"] or state["min"]:
            return
        try:
            state["geom"].update(width=int(window.width), height=int(window.height), x=int(window.x), y=int(window.y))
        except Exception:
            pass

    def on_max(*_):
        state["max"], state["min"] = True, False

    def on_min(*_):
        state["min"] = True

    def on_restore(*_):
        state["max"] = state["min"] = False
        remember()

    def on_shown(*_):
        set_window_icon(window)

    def on_loaded(*_):
        if not _ICONS:
            set_window_icon(window)
        try:
            window.evaluate_js(EXTERNAL_LINK_JS)
        except Exception as e:
            log(f"couldn't install the link handler: {e}")

    def on_closing(*_):
        remember()
        save_geometry(dict(state["geom"], maximized=bool(state["max"])))
        if owns and not keep_available():
            why = _busy_reason(port)
            if why and not message(f"Siftwell is busy: {why}.\n\nIf you close the window now, Siftwell stops and that work "
                                   "is lost. Close anyway?", ask=True):
                return False
        return True

    window.events.resized += remember
    window.events.moved += remember
    window.events.maximized += on_max
    window.events.minimized += on_min
    window.events.restored += on_restore
    window.events.shown += on_shown
    window.events.loaded += on_loaded
    window.events.closing += on_closing

    _write_lock()
    log(f"window opening on {url} (owns server: {owns}, keep available: {keep_available()})")
    kw = dict(private_mode=False, storage_path=PROFILE)
    if ready:
        kw.update(func=ready, args=(window,))
    try:
        os.makedirs(PROFILE, exist_ok=True)
        webview.start(gui="edgechromium" if WINDOWS else None, **kw)   # blocks until the window is closed
    except Exception as e:
        _clear_lock()
        _fallback_to_browser(url, f"the window couldn't start: {e}")
        return 0
    _clear_lock()
    log("window closed")

    if owns and not keep_available():
        stop_server(port, proc)
    elif owns:
        log("keep-available is on: leaving the server running")
    return 0


if __name__ == "__main__":
    try:
        code = frozen.dispatch()      # installed Siftwell.exe: --server / --jobfinder / --stop ...; None = open the window
        if code is None:
            code = main()
    except SystemExit as e:
        code = e.code or 0
    except BaseException as e:   # pythonw has nowhere to show a crash
        import traceback
        log("crashed: " + traceback.format_exc())
        code = 1
    sys.exit(code)
