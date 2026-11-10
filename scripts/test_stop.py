#!/usr/bin/env python3
"""Safety test for "Stop Siftwell": Stop may only end a process recorded in THIS data folder's pid file and verified to be
this app folder's Siftwell. It must never stop "whatever listens on the port" or an unrelated process.

    python scripts/test_stop.py <scratch dir> [port1 port2]       (ports: your own test ports, default 8880 8881)

Starts real test servers (own scratch data, SIFTWELL_FORBID_CLAUDE=1) and dummy processes, runs the shared stop
(app_window.stop_server_report) and tools/launcher.ps1 -Stop (Windows) against scratch data, and checks:
  1. no pid file: nothing stops (a server that is running, started some other way, stays up)
  2. recorded pid: only that server stops, the other one stays
  3. pid file pointing at an unrelated live process (reused pid): it is not stopped
  4. a process that only mentions the server path in its arguments: not stopped
  5. a process newer than its pid file (reused pid after a restart): not stopped
Only processes this script started are ever killed, by pid, and the scratch folder is deleted at the end.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
WIN = sys.platform == "win32"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
started = []      # Popen objects we own
results = []


def check(name, ok, extra=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (("  [" + extra + "]") if extra and not ok else ""), flush=True)


def up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return json.loads(r.read()).get("app") == "siftwell"
    except Exception:
        return False


def alive(p):
    return p.poll() is None


def env_for(data, **extra):
    e = dict(os.environ, JOBBOARD_DATA=data, SIFTWELL_FORBID_CLAUDE="1", SIFTWELL_NO_SELFHEAL="1",
             SIFTWELL_RUNTIME=os.path.join(os.path.dirname(data), "runtime"), PYTHONDONTWRITEBYTECODE="1")
    e.pop("SIFTWELL_PORT", None)
    e.update(extra)
    return e


def start_server(data, port, record):
    """A real test server; with record=False its pid file goes to a throw-away folder instead of `data`."""
    os.makedirs(data, exist_ok=True)
    d = data if record else data + "-elsewhere"
    os.makedirs(d, exist_ok=True)
    p = subprocess.Popen([PY, "-X", "utf8", os.path.join(APP, "server.py"), str(port)], cwd=APP, env=env_for(d),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    started.append(p)
    for _ in range(60):
        if up(port):
            return p
        time.sleep(0.5)
    raise SystemExit(f"test server on {port} didn't start")


def wait_pidfile(data):
    pf = os.path.join(data, "server.pid")
    for _ in range(40):
        try:
            return int(open(pf).read().strip())
        except (OSError, ValueError):
            time.sleep(0.25)
    raise SystemExit("server didn't write its pid file")


def py_stop(data, port=None):
    code = f"import app_window as aw; print(aw.stop_server_report({port!r}))"
    r = subprocess.run([PY, "-X", "utf8", "-c", code], cwd=APP, env=env_for(data), capture_output=True, text=True, timeout=180)
    return (r.stdout + r.stderr).strip()


def ps_stop(data):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(APP, "tools", "launcher.ps1"), "-Stop"],
                       cwd=APP, env=env_for(data, SIFTWELL_NO_PAUSE="1"), capture_output=True, text=True, timeout=180)
    return (r.stdout + r.stderr).strip()


def dummy(*extra):
    p = subprocess.Popen([PY, "-c", "import time; time.sleep(600)", *extra], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    started.append(p)
    time.sleep(0.5)
    return p


def pidfile(data, pid, age=0):
    os.makedirs(data, exist_ok=True)
    f = os.path.join(data, "server.pid")
    with open(f, "w") as fh:
        fh.write(str(pid))
    if age:
        t = time.time() - age
        os.utime(f, (t, t))
    return f


def cleanup(scratch):
    for p in started:
        if p.poll() is None:
            try:
                if WIN:
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=NOWIN)
                else:
                    p.kill()
            except Exception:
                pass
    # real servers write their own pid (the child of the launcher stub when started through a venv): stop those by pid too
    for d in os.listdir(scratch) if os.path.isdir(scratch) else []:
        f = os.path.join(scratch, d, "server.pid")
        if os.path.exists(f):
            try:
                pid = int(open(f).read().strip())
                if pid in OWN_PIDS and WIN:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=NOWIN)
            except Exception:
                pass
    time.sleep(1)
    shutil.rmtree(scratch, ignore_errors=True)


OWN_PIDS = set()


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    scratch = os.path.abspath(sys.argv[1])
    pa = int(sys.argv[2]) if len(sys.argv) > 2 else 8880
    pb = int(sys.argv[3]) if len(sys.argv) > 3 else 8881
    for pt in (pa, pb):
        if pt == 8766 or not 8800 <= pt <= 8899:
            raise SystemExit("use your own test ports (8800-8899), never 8766")
    os.makedirs(scratch, exist_ok=True)
    try:
        # B: a running Siftwell that is NOT recorded in any data folder we stop from
        b = start_server(os.path.join(scratch, "dataB"), pb, record=False)
        OWN_PIDS.add(b.pid)
        a = start_server(os.path.join(scratch, "dataA"), pa, record=True)
        pida = wait_pidfile(os.path.join(scratch, "dataA"))
        OWN_PIDS.add(pida)
        OWN_PIDS.add(a.pid)

        # 1. no pid file
        empty = os.path.join(scratch, "empty")
        os.makedirs(empty, exist_ok=True)
        out = py_stop(empty)
        check("1a no pid file: python stop reports not running", "isn't running" in out and "restart your computer" in out, out)
        check("1a no pid file: both servers still up", up(pa) and up(pb))
        out = py_stop(empty, pa)
        check("1b no pid file, port known: says it can't end it", "wasn't started from this copy" in out, out)
        check("1b both servers still up", up(pa) and up(pb))
        if WIN:
            out = ps_stop(empty)
            check("1c no pid file: launcher.ps1 -Stop reports not running", "isn't running" in out, out)
            check("1c both servers still up", up(pa) and up(pb))

        # 2. recorded pid: only A stops
        out = py_stop(os.path.join(scratch, "dataA"))
        check("2 recorded server stops", "has stopped" in out and not up(pa), out)
        check("2 the unrecorded server is untouched", up(pb))
        check("2 pid file removed", not os.path.exists(os.path.join(scratch, "dataA", "server.pid")))

        # 3. pid file naming an unrelated live process
        d3 = os.path.join(scratch, "data3")
        s = dummy()
        pidfile(d3, s.pid)
        out = py_stop(d3)
        check("3 python stop: unrelated process (reused pid) refused", alive(s) and "nothing was stopped" in out, out)
        if WIN:
            out = ps_stop(d3)
            check("3 launcher.ps1 -Stop: unrelated process refused", alive(s) and "left alone" in out, out)

        # 4. a process that merely mentions the server path
        d4 = os.path.join(scratch, "data4")
        s4 = dummy(os.path.join(APP, "server.py"))
        pidfile(d4, s4.pid)
        out = py_stop(d4)
        check("4 python stop: process that only mentions server.py refused", alive(s4), out)
        if WIN:
            out = ps_stop(d4)
            check("4 launcher.ps1 -Stop: same, refused", alive(s4), out)

        # 5. a real server whose pid file is OLDER than the process (pid reused after the file was written)
        d5 = os.path.join(scratch, "data5")
        e = start_server(d5, pa, record=True)
        pide = wait_pidfile(d5)
        OWN_PIDS.update({pide, e.pid})
        pidfile(d5, pide, age=3600)
        out = py_stop(d5)
        check("5 python stop: process newer than its pid file refused", up(pa) and "nothing was stopped" in out, out)
        if WIN:
            out = ps_stop(d5)
            check("5 launcher.ps1 -Stop: same, refused", up(pa) and "left alone" in out, out)
        check("5 other server still up", up(pb))
        # ... and the same server stops when the pid file is current
        pidfile(d5, pide)
        if WIN:
            out = ps_stop(d5)
            check("5 launcher.ps1 -Stop stops the verified server", not up(pa) and "has stopped" in out, out)
            e2 = start_server(os.path.join(scratch, "data6"), pa, record=True)
            OWN_PIDS.update({wait_pidfile(os.path.join(scratch, "data6")), e2.pid})
            out = py_stop(os.path.join(scratch, "data6"))
            check("5 python stop stops the verified server again", not up(pa), out)
        check("final: the unrecorded server was never touched", up(pb))
    finally:
        cleanup(scratch)
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
