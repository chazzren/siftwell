#!/usr/bin/env python3
"""Test of the in-app updater (appupdate.py) against a local fake GitHub release server. No real installer is ever run.

    python scripts/test_updater.py <scratch dir> [app port] [fake release server port]     (your own test ports, 8800-8899)
    python scripts/test_updater.py <scratch dir> --serve <fake port> <scenario>              (just run the fake server)

Starts real Siftwell servers on scratch data with SIFTWELL_UPDATE_API pointing at the fake server, and checks:
  newer -> status says so, notes come through; same / older -> nothing; 404 / 403 / 429 / timeout -> silent, no error;
  /latest 404 but a pre-release in the list -> found; automatic check runs once after start and not when switched off;
  installed copy (SIFTWELL_UPDATE_RUNNER = a stub "installer" that writes a marker): download -> size + SHA256 verify ->
  launch with the silent flags -> the server exits; bad checksum / wrong size / failed download -> error shown and the
  server keeps running; ZIP copy -> no self-update, nothing downloaded.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REPO = "chazzren/siftwell"
STUB = b"MZ-fake-installer-bytes-" + b"x" * 5000
STUB_SHA = hashlib.sha256(STUB).hexdigest()
NOTES = "Fixes things.\n<img src=x onerror=alert(1)> & more"

CUR = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")).read().strip()  # the version under test
SC = {"mode": "newer", "version": "0.3.0", "digest": "good", "size": "good", "hits": []}


def release(version, prerelease=False, installer=True, port=0):
    assets = []
    if installer:
        size = len(STUB) if SC["size"] == "good" else len(STUB) + 7
        digest = "sha256:" + (STUB_SHA if SC["digest"] == "good" else "0" * 64)
        assets.append({"name": f"Siftwell-Setup-{version}.exe", "size": size, "digest": digest if SC["digest"] != "none" else None,
                       "browser_download_url": f"http://127.0.0.1:{port}/dl/Siftwell-Setup-{version}.exe"})
        assets.append({"name": f"Siftwell-Portable-{version}.zip", "size": 10,
                       "browser_download_url": f"http://127.0.0.1:{port}/dl/portable.zip"})
        assets.append({"name": f"Siftwell-{version}.zip", "size": 10, "browser_download_url": f"http://127.0.0.1:{port}/dl/zip"})
    return {"tag_name": "v" + version, "name": "Siftwell " + version, "body": NOTES, "draft": False, "prerelease": prerelease,
            "html_url": f"https://github.com/{REPO}/releases/tag/v{version}", "assets": assets}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        try:
            self.wfile.write(b)
        except OSError:
            pass

    def do_GET(self):
        port = self.server.server_address[1]
        SC["hits"].append(self.path)
        mode = SC["mode"]
        if self.path.startswith("/dl/"):
            if mode == "dl404":
                return self._json(404, {"message": "Not Found"})
            self.send_response(200)
            self.send_header("Content-Length", str(len(STUB)))
            self.end_headers()
            self.wfile.write(STUB)
            return
        if not self.path.startswith(f"/repos/{REPO}/releases"):
            return self._json(404, {})
        if mode == "hang":
            time.sleep(12)
            return self._json(200, {})
        if mode in ("404", "403", "429"):
            return self._json(int(mode), {"message": "x"})
        if mode == "prerelease_only":
            if self.path.endswith("/latest"):
                return self._json(404, {"message": "Not Found"})
            return self._json(200, [release("0.2.0", True, port=port), release("0.3.0", True, port=port), {"tag_name": "v9.9.9", "draft": True}])
        v = {"newer": SC["version"], "dl404": SC["version"], "same": CUR, "older": "0.0.9"}[mode]
        if self.path.endswith("/latest"):
            return self._json(200, release(v, port=port))
        return self._json(200, [release(v, port=port)])


results, started = [], []


def check(name, ok, extra=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (("  [" + str(extra)[:200] + "]") if extra and not ok else ""), flush=True)


def call(port, path, post=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if post is not None else "GET",
                                 data=json.dumps(post).encode() if post is not None else None,
                                 headers={"X-Jobboard": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return json.loads(r.read()).get("app") == "siftwell"
    except Exception:
        return False


def start_app(data, port, fake_port, runner=False, auto_state=None, **env):
    os.makedirs(data, exist_ok=True)
    if auto_state is not None:
        open(os.path.join(data, "app_update.json"), "w").write(json.dumps(auto_state))
    e = dict(os.environ, JOBBOARD_DATA=data, SIFTWELL_FORBID_CLAUDE="1", SIFTWELL_NO_SELFHEAL="1", PYTHONDONTWRITEBYTECODE="1",
             SIFTWELL_RUNTIME=os.path.join(os.path.dirname(data), "runtime"), SIFTWELL_UPDATE_API=f"http://127.0.0.1:{fake_port}",
             SIFTWELL_UPDATE_DELAY="1", STUB_MARKER=os.path.join(os.path.dirname(data), "marker.json"))
    e.pop("SIFTWELL_PORT", None)
    e.pop("SIFTWELL_UPDATE_RUNNER", None)
    if runner:
        e["SIFTWELL_UPDATE_RUNNER"] = f"{PY.replace(chr(92), '/')} {os.path.join(os.path.dirname(data), 'stub_installer.py').replace(chr(92), '/')}"
    e.update(env)
    p = subprocess.Popen([PY, "-X", "utf8", os.path.join(APP, "server.py"), str(port)], cwd=APP, env=e, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    started.append((p, data))
    for _ in range(80):
        if up(port):
            return p
        time.sleep(0.5)
    raise SystemExit("app server didn't start")


def stop_app(p, data):
    """Stop a server we started: by the pid it recorded (the real process) and by the Popen handle."""
    pids = [p.pid]
    try:
        pids.append(int(open(os.path.join(data, "server.pid")).read().strip()))
    except (OSError, ValueError):
        pass
    for pid in set(pids):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=NOWIN)
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def wait_for(fn, secs):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return None


def main():
    scratch = os.path.abspath(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == "--serve":
        SC["mode"] = sys.argv[4]
        srv = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[3])), Fake)
        print("fake release server on", sys.argv[3])
        srv.serve_forever()
    app_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8882
    fake_port = int(sys.argv[3]) if len(sys.argv) > 3 else 8883
    for pt in (app_port, fake_port, app_port + 2):
        if pt == 8766 or not 8800 <= pt <= 8899:
            raise SystemExit("use your own test ports (8800-8899), never 8766")
    os.makedirs(scratch, exist_ok=True)
    open(os.path.join(scratch, "stub_installer.py"), "w").write(
        "import hashlib, json, os, sys\n"
        "d = open(sys.argv[1], 'rb').read()\n"
        "json.dump({'argv': sys.argv[1:], 'sha': hashlib.sha256(d).hexdigest(), 'size': len(d)}, open(os.environ['STUB_MARKER'], 'w'))\n")
    fake = ThreadingHTTPServer(("127.0.0.1", fake_port), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    data = os.path.join(scratch, "data")
    cur = CUR
    try:
        # ---- check results
        SC["mode"] = "newer"
        app = start_app(data, app_port, fake_port)
        st = call(app_port, "/api/app-update")[1]
        check("status has the current version", st["current"] == open(os.path.join(APP, "VERSION")).read().strip() == cur, st)
        # automatic check right after start (DELAY=1)
        got = wait_for(lambda: call(app_port, "/api/app-update")[1]["newer"], 12)
        check("automatic check at start-up finds the newer version", bool(got))
        st = call(app_port, "/api/app-update")[1]
        check("newer: version and plain-text notes come through", st["latest"]["version"] == "0.3.0" and st["latest"]["notes"] == NOTES, st)
        check("ZIP copy: Update is not offered, link to the release page is", not st["can_install"] and st["release_page"].startswith("https://github.com/" + REPO), st)
        saved = json.load(open(os.path.join(data, "app_update.json")))
        check("next automatic check is about a day away", 80000 < saved["next_check"] - time.time() < 90000, saved)
        n = len(SC["hits"])
        wait_for(lambda: False, 3)
        check("no repeat request within the day", len(SC["hits"]) == n)
        s, d = call(app_port, "/api/app-update/dismiss", {"version": "0.3.0"})
        check("dismiss is remembered", d["dismissed"] is True and call(app_port, "/api/app-update")[1]["dismissed"] is True)
        s, d = call(app_port, "/api/app-update/install", {})
        dl = [h for h in SC["hits"] if h.startswith("/dl/")]
        check("ZIP copy: install is refused and nothing is downloaded", s == 409 and not dl and not os.path.exists(os.path.join(data, "_updates")), (s, d))
        s, d = call(app_port, "/api/app-update/auto", {"on": "yes"})
        check("auto setting needs a real on/off", s == 400)

        for mode, label in (("same", "same version"), ("older", "older version")):
            SC["mode"] = mode
            s, d = call(app_port, "/api/app-update/check", {})
            check(f"{label}: no update offered", d["newer"] is False and d["latest"] is None and d["result"] == "ok", d)
        for mode in ("404", "403", "429"):
            SC["mode"] = mode
            s, d = call(app_port, "/api/app-update/check", {})
            check(f"HTTP {mode}: silent (no update, no error)", s == 200 and d["newer"] is False and d["result"] == "unavailable", d)
        SC["mode"] = "prerelease_only"
        s, d = call(app_port, "/api/app-update/check", {})
        check("/latest 404 but a pre-release in the list: found (drafts ignored)", d["newer"] and d["latest"]["version"] == "0.3.0", d)
        SC["mode"] = "hang"
        t0 = time.time()
        s, d = call(app_port, "/api/app-update/check", {})
        check("timeout: silent, answered in about 8 seconds", s == 200 and d["result"] == "offline" and 6 < time.time() - t0 < 11, (d, time.time() - t0))
        s, d = call(app_port, "/api/app-update/auto", {"on": False})
        check("automatic checking can be switched off", d["auto"] is False)
        stop_app(app, data)
        started.clear()

        # ---- automatic checking off: no request at all
        SC["mode"] = "newer"
        SC["hits"].clear()
        app = start_app(os.path.join(scratch, "data-off"), app_port, fake_port, auto_state={"auto": False})
        wait_for(lambda: False, 5)
        check("setting off: no automatic request", not SC["hits"], SC["hits"])
        stop_app(app, os.path.join(scratch, "data-off"))
        started.clear()

        # ---- installed copy with a stub installer
        for case, expect in (("badsha", "checksum"), ("badsize", "incomplete"), ("dl404", "")):
            SC.update(mode="dl404" if case == "dl404" else "newer", digest="bad" if case == "badsha" else "good",
                      size="bad" if case == "badsize" else "good")
            dd = os.path.join(scratch, "data-" + case)
            app = start_app(dd, app_port, fake_port, runner=True)
            wait_for(lambda: call(app_port, "/api/app-update")[1]["newer"], 12) or call(app_port, "/api/app-update/check", {})
            if case == "dl404":
                SC["mode"] = "dl404"   # the release data came from "newer" above; now the download itself fails
            st = call(app_port, "/api/app-update")[1]
            check(f"{case}: installed copy offers Update", st["can_install"], st)
            s, d = call(app_port, "/api/app-update/install", {})
            res = wait_for(lambda: (call(app_port, "/api/app-update")[1]["install"]["phase"] == "failed") or None, 20)
            st = call(app_port, "/api/app-update")[1]
            check(f"{case}: error is shown, nothing launched", res and st["install"]["error"] and expect in st["install"]["error"]
                  and not os.path.exists(os.path.join(scratch, "marker.json")), st["install"])
            check(f"{case}: current version keeps running", up(app_port) and app.poll() is None)
            check(f"{case}: no half-downloaded file left", not [f for f in os.listdir(os.path.join(dd, "_updates")) if f.endswith(".part")])
            stop_app(app, dd)
            started.clear()
            wait_for(lambda: not up(app_port), 10)

        SC.update(mode="newer", digest="good", size="good")
        for variant in ("with checksum", "no checksum (size only)"):
            if variant != "with checksum":
                SC["digest"] = "none"
            marker = os.path.join(scratch, "marker.json")
            if os.path.exists(marker):
                os.remove(marker)
            dd = os.path.join(scratch, "data-ok-" + variant[:4].strip())
            app = start_app(dd, app_port, fake_port, runner=True)
            wait_for(lambda: call(app_port, "/api/app-update")[1]["newer"], 12) or call(app_port, "/api/app-update/check", {})
            s, d = call(app_port, "/api/app-update/install", {})
            check(f"[{variant}] install accepted", s == 202 and d["ok"], d)
            wait_for(lambda: os.path.exists(marker), 20)
            check(f"[{variant}] download then silent launch of the installer", os.path.exists(marker))
            m = json.load(open(marker)) if os.path.exists(marker) else {"argv": [""]}
            fn = os.path.basename(m["argv"][0])
            check(f"[{variant}] installer file is Siftwell-Setup-0.3.0.exe in DATA/_updates", fn == "Siftwell-Setup-0.3.0.exe"
                  and os.path.dirname(os.path.abspath(m["argv"][0])) == os.path.abspath(os.path.join(dd, "_updates")), m)
            check(f"[{variant}] bytes verified (sha256 of what was launched = release asset)", m.get("sha") == STUB_SHA and m.get("size") == len(STUB), m)
            check(f"[{variant}] silent flags incl. relaunch", m["argv"][1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/NORESTART", "/RELAUNCH"], m)
            gone = wait_for(lambda: not up(app_port), 15)
            check(f"[{variant}] Siftwell exits so the installer can replace files", bool(gone))
            stop_app(app, dd)
            started.clear()
            wait_for(lambda: not up(app_port), 10)
    finally:
        for p, d in started:
            stop_app(p, d)
        time.sleep(1)
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
