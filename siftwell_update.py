#!/usr/bin/env python3
"""Headless automatic update: what the OS job from "Even when Siftwell is closed" runs (see autoupdate.py).

    python -X utf8 siftwell_update.py [--force]

No window, no tray. If a Siftwell server is already running here (ping), it asks that server to run the scheduled update
through its API (so the progress shows in the app) and exits. Otherwise it does the same work server.scheduler does:
fetch listings with jobfinder.py, then re-rate each person who has "Re-rate overnight when my info changes" on, respecting
the job lock (jobfinder.py waits for it) and Claude availability (no re-rate when Claude isn't installed, signed in, or
is blocked by SIFTWELL_FORBID_CLAUDE=1), then exits. Output goes to DATA/update.log (a fetch) and one line per step to
DATA/actions.log. Does nothing unless the setting is "Even when Siftwell is closed" (--force overrides, for testing)."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

APP = os.path.dirname(os.path.abspath(__file__))
if __name__ == "__main__":
    sys.path.insert(0, APP)
    sys.dont_write_bytecode = True
    import paths as _paths
    sys.dont_write_bytecode = False
    if not os.environ.get("PYTHONPYCACHEPREFIX"):  # keep compiled .pyc files out of the app folder
        os.environ["PYTHONPYCACHEPREFIX"] = os.path.join(_paths.RUNTIME, "pycache")
        sys.pycache_prefix = os.environ["PYTHONPYCACHEPREFIX"]

import osdeps
import paths

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if osdeps.WINDOWS else 0


def note(msg, detail=""):
    """One line to actions.log (and stdout, which is nowhere under pythonw)."""
    try:
        print(msg + (f" ({detail})" if detail else ""), flush=True)
    except Exception:
        pass
    import actionlog
    actionlog.log("automatic update: " + msg, None, None, detail)


def server_port():
    """The port of a running Siftwell for this data folder, or None."""
    port = paths.read_port()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=4) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return port if d.get("app") == "siftwell" and d.get("data") in (None, paths.data_id()) else None
    except Exception:
        return None


def delegate(port):
    """Ask the running server to do it. Returns an exit code."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/update/scheduled", data=b"{}", method="POST",
                                 headers={"X-Jobboard": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        note("asked the running Siftwell to run the update", f"port {port}")
        return 0
    except urllib.error.HTTPError as e:
        if e.code == 409:
            note("the running Siftwell is already busy with an update or re-rate; nothing more to do")
            return 0
        note("the running Siftwell refused the request", f"HTTP {e.code}")
        return 1
    except Exception as e:
        note("couldn't reach the running Siftwell", f"{type(e).__name__}")
        return 1


def claude_ok():
    """Only a yes when Claude can really be used: not blocked, installed and signed in."""
    if os.environ.get("SIFTWELL_FORBID_CLAUDE") == "1":
        return False
    try:
        import claude_cli
        return bool(claude_cli.path()) and claude_cli.logged_in()
    except Exception:
        return False


def run_here():
    """No server running: fetch, then re-rate, in this process's children. Returns an exit code."""
    import people
    py = sys.executable
    jf = os.path.join(APP, "jobfinder.py")
    log_path = os.path.join(paths.DATA, "update.log")
    os.makedirs(paths.DATA, exist_ok=True)
    osdeps.keep_awake(True)
    note("started (Siftwell isn't open; running the update here)")
    try:
        import datetime as _dt
        # the update and the re-rate after it are one rating run as far as the limits go (jobfinder.night_budgets)
        env = {**os.environ, "SIFTWELL_NIGHT": _dt.datetime.now().strftime("%Y%m%dT%H%M%S")}
        with open(log_path, "w", encoding="utf-8") as log:
            rc = subprocess.call([py, "-X", "utf8", jf], cwd=APP, stdout=log, stderr=subprocess.STDOUT, creationflags=NOWIN, env=env)
        note("update finished" if rc in (0, 3) else "update stopped", f"exit {rc}")
        if rc not in (0, 3):
            return rc
        todo = []
        for pid in people.ids():
            try:
                p = people.prefs(pid)
                if p.get("claude.auto_rerate", True):
                    todo.append((pid, int(p.get("claude.per_update") or 300)))
            except Exception as e:
                note("couldn't read settings", f"{pid}: {type(e).__name__}")
        if todo and not claude_ok():
            note("re-rate skipped: Claude isn't available (not installed, signed out, or blocked)")
            return 0
        for pid, n in todo:
            with open(os.path.join(paths.DATA, f"rerate-{pid}.log"), "w", encoding="utf-8") as log:
                rr = subprocess.call([py, "-X", "utf8", jf, "--rerate", pid, "--n", str(n)], cwd=APP, stdout=log,
                                     stderr=subprocess.STDOUT, creationflags=NOWIN, env=env)
            note("re-rate finished" if rr == 0 else "re-rate failed", f"{pid}, exit {rr}")
        return 0
    except Exception as e:
        note("failed", f"{type(e).__name__}: {str(e)[:120]}")
        return 1
    finally:
        osdeps.keep_awake(False)


def main(argv):
    if sys.stdout is None or sys.stderr is None:   # pythonw: no console
        sys.stdout = sys.stderr = open(os.devnull, "w")
    import autoupdate
    mode = autoupdate.get()["mode"]
    if mode != "closed" and "--force" not in argv:
        note("skipped: automatic updates are set to " + {"off": "Off", "running": "While Siftwell is running"}.get(mode, mode))
        return 0
    port = server_port()
    if port:
        return delegate(port)
    return run_here()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
