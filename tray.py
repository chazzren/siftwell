"""System-tray icon for a Siftwell that is running without its window (kept available for the phone, or started at
sign-in). Runs as a small helper process that the server starts (`tray.start_helper(port)`), so the tray has its own
main thread and message loop on both Windows and Mac. One per data folder (DATA/tray.pid).

    python tray.py <port>

  * The icon shows only while no Siftwell window is open (DATA/window.pid absent or dead, for a few seconds in a row);
    it hides when a window opens and comes back when the window closes and the server keeps running.
  * Left/double-click or "Open Siftwell": opens (or focuses) the window via app_window.py.
  * "Copy phone link": only when phone access is on; copies http://<LAN IP>:<port>/?k=<key>.
  * "Stop Siftwell": stops the server and what it started (app_window.stop_server, same as the Stop script) and exits.
  * The helper exits by itself when the server stops. Needs pystray (requirements.txt); without it nothing happens.
Mac code paths are written carefully but untested. Nothing is written into the app folder.
"""
import os
import subprocess
import sys
import time

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
sys.dont_write_bytecode = True
import paths  # noqa: E402
import app_window as aw  # noqa: E402
sys.dont_write_bytecode = False

TRAY_PID = os.path.join(paths.DATA, "tray.pid")
ICON_PNG = os.path.join(APP, "assets", "brand", "apple-touch-icon.png")
PORT_IN_USE = 0    # set by main(); passed to app_window so the window opens on the same port as this server
GRACE = 8         # seconds without a window before the icon appears (a window is about to open at normal start)
POLL = 2


def wanted():
    """Tests (scratch JOBBOARD_DATA / SIFTWELL_RUNTIME) don't get a tray unless SIFTWELL_TEST_TRAY=1; no tray on Linux."""
    if sys.platform not in ("win32", "darwin"):
        return False
    if (os.environ.get("JOBBOARD_DATA") or os.environ.get("SIFTWELL_RUNTIME")) and os.environ.get("SIFTWELL_TEST_TRAY") != "1":
        return False
    return True


def start_helper(port):
    """Called by the server at start-up. Spawns the helper (detached) unless one is already running."""
    if not wanted() or _helper_running():
        return None
    cmd = aw.frozen.command("tray", port, utf8=True, windowed=True)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
    if aw.WINDOWS:
        # Via `start`, so the helper is not a child of the server: the Stop script kills the server's whole process tree,
        # and a killed tray process would leave a ghost icon in the tray. As an orphan it sees the server is gone and
        # removes its own icon.
        cmd = ["cmd", "/c", "start", "", "/B"] + cmd
        kw.update(creationflags=aw.NOWIN)
    else:
        kw.update(start_new_session=True)
    try:
        return subprocess.Popen(cmd, **kw)
    except OSError as e:
        aw.log(f"tray: couldn't start the helper: {e}")
        return None


def _helper_running():
    try:
        pid = int(open(TRAY_PID).read().strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and aw._pid_alive(pid) and aw._is_python_proc(pid)


def window_open():
    try:
        pid = int(open(aw.LOCK).read().strip())
    except (OSError, ValueError):
        return False
    return aw._pid_alive(pid) and aw._is_python_proc(pid)


def phone_link(port):
    """http://<LAN IP>:<port>/?k=<key> when phone access is on, else None."""
    try:
        import getting_started
        if not getting_started.lan_enabled():
            return None
        ip = getting_started.lan_ip()
        token = ""
        try:
            token = open(paths.ACCESS_KEY, encoding="utf-8").read().strip()
        except OSError:
            pass
        return f"http://{ip}:{port}/?k={token}" if ip and token else None
    except Exception as e:
        aw.log(f"tray: phone link failed: {e}")
        return None


def copy_text(text):
    try:
        if aw.WINDOWS:
            subprocess.run(["clip"], input=text.encode("utf-16-le"), timeout=10, creationflags=aw.NOWIN)  # clip reads UTF-16 w/o BOM
        else:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=10)
        return True
    except Exception as e:
        aw.log(f"tray: copy failed: {e}")
        return False


def open_window():
    cmd = aw.frozen.command("window", utf8=True, windowed=True)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP,
              env=dict(os.environ, SIFTWELL_PORT=str(PORT_IN_USE)))
    if aw.WINDOWS:
        kw.update(creationflags=aw.NOWIN | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kw.update(start_new_session=True)
    try:
        subprocess.Popen(cmd, **kw)
    except OSError as e:
        aw.log(f"tray: couldn't open the window: {e}")


def main(port):
    global PORT_IN_USE
    PORT_IN_USE = port
    if not wanted() or _helper_running():
        return 0
    try:
        import pystray
        from PIL import Image
    except Exception as e:
        aw.log(f"tray: pystray isn't available: {e}")
        return 0
    try:
        os.makedirs(paths.DATA, exist_ok=True)
        with open(TRAY_PID, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    def stop_all(icon=None, item=None):
        aw.log("tray: Stop Siftwell")
        if icon is not None:
            icon.visible = False
            icon.stop()
        aw.stop_server(port)

    def copy_link(icon, item):
        u = phone_link(port)
        if u:
            copy_text(u)

    menu = pystray.Menu(
        pystray.MenuItem("Open Siftwell", lambda icon, item: open_window(), default=True),
        pystray.MenuItem("Copy phone link", copy_link, visible=lambda item: phone_link(port) is not None),
        pystray.MenuItem("Stop Siftwell", stop_all),
    )
    icon = pystray.Icon("Siftwell", Image.open(ICON_PNG), f"Siftwell is running (port {port})", menu)

    def watch(icon):
        none_since, down = None, 0
        while True:
            time.sleep(POLL)
            if aw.server_up(port):
                down = 0
            else:
                down += 1
                if down >= 3:
                    aw.log("tray: the server is gone; removing the icon")
                    icon.visible = False
                    icon.stop()
                    return
            if window_open():
                none_since = None
                if icon.visible:
                    icon.visible = False
                    aw.log("tray: window open; icon hidden")
            else:
                none_since = none_since or time.time()
                if time.time() - none_since >= GRACE and not icon.visible:
                    icon.visible = True
                    aw.log("tray: icon shown")

    icon.run(setup=lambda i: __import__("threading").Thread(target=watch, args=(i,), daemon=True).start())
    try:
        if int(open(TRAY_PID).read().strip()) == os.getpid():
            os.remove(TRAY_PID)
    except (OSError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    aw._no_std_streams()
    try:
        p = int(sys.argv[1]) if len(sys.argv) > 1 else paths.read_port()
        sys.exit(main(p))
    except SystemExit:
        raise
    except BaseException:
        import traceback
        aw.log("tray crashed: " + traceback.format_exc())
        sys.exit(1)
