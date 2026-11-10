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
sys.dont_write_bytecode = False

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
TITLE = "Siftwell"
DEFAULT_SIZE = (1280, 860)
MIN_SIZE = (520, 480)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

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


def fetch(url, timeout=3, cookie=None):
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def server_up(port):
    try:
        return json.loads(fetch(f"http://127.0.0.1:{port}/api/ping")).get("app") == "siftwell"
    except Exception:
        return False


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
            return r.stdout.strip().lower().startswith('"python')
        r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=15)
        return "python" in r.stdout.lower()
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


def listener_pid(port):
    """Who is listening on this TCP port (fallback when the pid file is missing)."""
    try:
        if WINDOWS:
            r = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=20, creationflags=NOWIN)
            for line in (r.stdout or "").splitlines():
                p = line.split()
                if len(p) >= 5 and p[3] == "LISTENING" and p[1].rsplit(":", 1)[-1] == str(port):
                    return int(p[4])
        else:
            r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=20)
            if r.stdout.strip():
                return int(r.stdout.split()[0])
    except Exception:
        pass
    return 0


def server_python():
    """Interpreter for the server: the one running this window (pythonw next to it on Windows, so no console)."""
    exe = sys.executable
    if WINDOWS:
        d, n = os.path.split(exe)
        if n.lower() == "python.exe" and os.path.exists(os.path.join(d, "pythonw.exe")):
            return os.path.join(d, "pythonw.exe")
    return exe


def start_server(port):
    """Start server.py detached from this window, so it can outlive it (keep-available). Returns the Popen."""
    cmd = [server_python(), "-X", "utf8", os.path.join(APP, "server.py"), str(port)]
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


def stop_server(port, proc=None):
    """Stop the Siftwell server (and what it started) on `port`: the pid in DATA/server.pid if that is a live Python,
    else whoever listens on the port if that is a Python running server.py, else the process we started."""
    pids = []
    try:
        pids.append(int(open(paths.PID_FILE).read().strip()))
    except (OSError, ValueError):
        pass
    lp = listener_pid(port)
    if lp:
        pids.append(lp)
    if proc is not None:
        pids.append(proc.pid)
    done = set()
    for pid in pids:
        if pid in done or pid == os.getpid():
            continue
        done.add(pid)
        if _pid_alive(pid) and _is_python_proc(pid):
            log(f"stopping server pid {pid}")
            kill_tree(pid)
    end = time.time() + 8
    while time.time() < end and server_up(port):
        time.sleep(0.3)
    try:
        if not _pid_alive(int(open(paths.PID_FILE).read().strip())):
            os.remove(paths.PID_FILE)
    except (OSError, ValueError):
        pass
    gone = not server_up(port)
    log("server stopped" if gone else "server still answering after stop")
    return gone


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
                    if buf.value == TITLE:
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
    port = get_port()
    url = f"http://127.0.0.1:{port}/"

    if _focus_existing():
        return 0

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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Siftwell.Desktop")   # own taskbar button
        except Exception:
            pass

    geom = load_geometry()
    state = {"max": False, "min": False, "geom": dict(geom)}
    api = Api()
    window = webview.create_window(
        TITLE, url, js_api=api, width=geom["width"], height=geom["height"], x=geom["x"], y=geom["y"],
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

    def on_loaded(*_):
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
        code = main()
    except SystemExit as e:
        code = e.code or 0
    except BaseException as e:   # pythonw has nowhere to show a crash
        import traceback
        log("crashed: " + traceback.format_exc())
        code = 1
    sys.exit(code)
