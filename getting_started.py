"""The "Get started" checklist (GET /getting-started) and its actions, so setup happens in the browser, not a terminal.

Required checks (counted, drive the banner): Claude Code installed, signed in, a browser for resume PDFs.
Optional (listed apart, never counted): start at sign-in, phone access, Codex for Astra.
server.py only routes here (handle_get / handle_post / ping) and asks bind_host() which address to listen on.

Phone access is a saved setting, DATA/network.json {"lan": bool}. New installs listen on this computer only (127.0.0.1);
an install that already had profiles when this setting first appeared keeps LAN access on (bind_host() records that choice
on the first start). Changing it needs a restart: restart_now() starts a replacement that waits for the port to free.
"""
import os
import sys

if __name__ == "__main__" and "--serve" in sys.argv:
    # Login launcher: `pythonw -X utf8 getting_started.py --serve` reads <app>/.siftwell/port (default 8766) at run
    # time and runs server.py on it, so the start-at-sign-in entry never holds a stale port.
    _app = os.path.dirname(os.path.abspath(__file__))
    try:
        _port = int(open(os.path.join(_app, ".siftwell", "port")).read().strip())
    except (OSError, ValueError):
        _port = 8766
    try:
        os.makedirs(os.path.join(_app, ".siftwell"), exist_ok=True)
        open(os.path.join(_app, ".siftwell", "server.pid"), "w").write(str(os.getpid()))
    except OSError:
        pass
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

import osdeps
import paths
import people
import report

VERSION = "1"
NETWORK = os.path.join(paths.DATA, "network.json")
APP = paths.APP
RUN_DIR = os.path.join(APP, ".siftwell")           # launcher runtime folder (port, server.pid)
TASK_NAME = "Job Board server"                       # scheduled task made by the older setup_windows.ps1
MAC_LABEL = "com.siftwell.server"
CTX = {"port": 8766, "token": "", "busy": lambda: False, "bound_lan": False}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if osdeps.WINDOWS else 0


def configure(port, token, busy):
    CTX.update(port=port, token=token, busy=busy)


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


def save_network(on):
    os.makedirs(paths.DATA, exist_ok=True)
    json.dump({"lan": bool(on)}, open(NETWORK, "w", encoding="utf-8"))


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
    """The app's own interpreter without a console window."""
    if osdeps.WINDOWS:
        for p in (os.path.join(APP, ".venv", "Scripts", "pythonw.exe"),
                  os.path.join(os.path.dirname(sys.executable), "pythonw.exe")):
            if os.path.exists(p):
                return p
        return sys.executable
    p = os.path.join(APP, ".venv", "bin", "python")
    return p if os.path.exists(p) else sys.executable


def _win_lnk():
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming"),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Siftwell.lnk")


def _mac_plist():
    return os.path.expanduser(f"~/Library/LaunchAgents/{MAC_LABEL}.plist")


def _linux_desktop():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart", "siftwell.desktop")


def _task_exists():
    if not osdeps.WINDOWS:
        return False
    try:
        return subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, timeout=15,
                              creationflags=NOWIN).returncode == 0
    except Exception:
        return False


def startup_state():
    """{"on", "via", "task"}: via is shortcut / task / launchagent / autostart."""
    if osdeps.WINDOWS:
        lnk, task = os.path.exists(_win_lnk()), _task_exists()
        return {"on": lnk or task, "via": "shortcut" if lnk else "task" if task else None, "task": task, "own": lnk}
    if osdeps.MAC:
        own = os.path.exists(_mac_plist())
        return {"on": own, "via": "launchagent" if own else None, "task": False, "own": own}
    own = os.path.exists(_linux_desktop())
    return {"on": own, "via": "autostart" if own else None, "task": False, "own": own}


def set_startup(on):
    py = _app_python()
    launcher = os.path.join(APP, "getting_started.py")
    if osdeps.WINDOWS:
        lnk = _win_lnk()
        if not on:
            if os.path.exists(lnk):
                os.remove(lnk)
            return
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SW_LNK);"
                  "$s.TargetPath=$env:SW_EXE;$s.Arguments=$env:SW_ARGS;$s.WorkingDirectory=$env:SW_DIR;"
                  "$s.Description='Siftwell';$s.Save()")
        env = dict(os.environ, SW_LNK=lnk, SW_EXE=py, SW_DIR=APP,
                   SW_ARGS=f'-X utf8 "{launcher}" --serve')
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], env=env,
                           capture_output=True, text=True, timeout=60, creationflags=NOWIN)
        if r.returncode != 0 or not os.path.exists(lnk):
            raise RuntimeError("Couldn't create the startup shortcut. " + (r.stderr or "").strip()[:200])
    elif osdeps.MAC:
        import plistlib
        pl = _mac_plist()
        if not on:
            if os.path.exists(pl):
                # If launchd started this server, unloading would stop it mid-answer; removing the file is enough then.
                if os.environ.get("XPC_SERVICE_NAME") != MAC_LABEL:
                    subprocess.run(["launchctl", "unload", pl], capture_output=True, timeout=30)
                os.remove(pl)
            return
        os.makedirs(os.path.dirname(pl), exist_ok=True)
        with open(pl, "wb") as f:
            plistlib.dump({"Label": MAC_LABEL, "ProgramArguments": [py, "-X", "utf8", launcher, "--serve"],
                           "WorkingDirectory": APP, "RunAtLoad": True, "KeepAlive": False,
                           "StandardOutPath": os.path.join(paths.data(), "server.log"),
                           "StandardErrorPath": os.path.join(paths.data(), "server.log")}, f)
        subprocess.run(["launchctl", "unload", pl], capture_output=True, timeout=30)
        # loading starts a second copy now; it exits at once because the port is taken, and it runs at the next sign-in
        subprocess.run(["launchctl", "load", "-w", pl], capture_output=True, timeout=30)
    else:
        df = _linux_desktop()
        if not on:
            if os.path.exists(df):
                os.remove(df)
            return
        os.makedirs(os.path.dirname(df), exist_ok=True)
        q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'
        with open(df, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Siftwell\nComment=Start the Siftwell job board\n"
                    f"Exec={q(py)} -X utf8 {q(launcher)} --serve\nPath={APP}\nTerminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n")


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
    return ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"], False


def _run_install():
    import claude_cli
    cmd, shell = install_command()
    try:
        p = subprocess.Popen(cmd, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=NOWIN)
        for raw in iter(p.stdout.readline, b""):
            line = _ANSI.sub("", raw.decode("utf-8", "replace")).replace("\r", "").strip()
            if line:
                with _ilock:
                    INSTALL["lines"] = (INSTALL["lines"] + [line])[-60:]
        p.wait()
        code = p.returncode
    except Exception as e:
        code = -1
        with _ilock:
            INSTALL["lines"] = (INSTALL["lines"] + ["Couldn't run the installer: " + str(e)[:200]])[-60:]
    _status_cache.clear()
    with _ilock:
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
                     start_new_session=(os.name != "nt"), cwd=os.path.dirname(cmd[-2]))
try:
    os.makedirs(os.path.dirname(pidf), exist_ok=True)
    open(pidf, "w").write(str(p.pid))
except OSError:
    pass
"""


def restart_now():
    """Start a replacement server that waits for this one's port to free, then exit this process."""
    py = sys.executable
    server = os.path.join(APP, "server.py")
    cmd = [py, "-X", "utf8", server, str(CTX["port"])]
    flags = 0
    if osdeps.WINDOWS:
        flags = NOWIN | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([py, "-X", "utf8", "-c", _WAITER, str(CTX["port"]), os.path.join(paths.data(), "server.log"),
                      os.path.join(RUN_DIR, "server.pid"), *cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=not osdeps.WINDOWS, cwd=APP)
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
    port = CTX["port"]
    cpath = claude_cli.path()
    signed = _signed_in(bool(cpath), fresh)
    chrome = osdeps.chrome_path()
    st = startup_state()
    lan = lan_enabled()
    ip = lan_ip() if lan else None
    url = f"http://{ip}:{port}/?k={CTX['token']}" if lan and ip else None
    codex = osdeps.find_exe("codex")
    items = [
        {"id": "claude", "title": "Claude Code installed", "done": bool(cpath), "optional": False},
        {"id": "signin", "title": "Signed in to Claude", "done": bool(signed), "optional": False},
        {"id": "browser", "title": "Browser for resume PDFs", "done": bool(chrome), "optional": False},
        {"id": "startup", "title": "Start Siftwell when I sign in", "done": st["on"], "optional": True},
        {"id": "phone", "title": "Use Siftwell on my phone", "done": lan, "optional": True},
        {"id": "astra", "title": "Astra resume reviews", "done": bool(codex), "optional": True},
    ]
    req = [i for i in items if not i["optional"]]
    done = sum(1 for i in req if i["done"])
    return {
        "items": items, "done": done, "total": len(req), "complete": done == len(req),
        "port": port, "windows": osdeps.WINDOWS, "mac": osdeps.MAC,
        "claude": {"installed": bool(cpath), "signed_in": bool(signed)},
        "browser": {"found": bool(chrome), "name": "Edge" if chrome and "edge" in chrome.lower() else "Chrome" if chrome else ""},
        "startup": st,
        "phone": {"on": lan, "bound": CTX["bound_lan"], "restart_needed": lan != CTX["bound_lan"], "ip": ip, "url": url, "port": port},
        "astra": {"found": bool(codex)},
        "install": install_state(),
    }


# ---------------------------------------------------------------- routes
ASSET_FILES = {"/assets/vendor/qrcode.js": ("qrcode.js", "application/javascript")}
GET_PATHS = ("/getting-started", "/api/setup-status", "/api/getting-started/install", *ASSET_FILES)


def ping():
    return {"app": "siftwell", "version": VERSION, "port": CTX["port"]}


def handle_get(h, path, pid, query=""):
    if path in ASSET_FILES:
        name, ctype = ASSET_FILES[path]
        data = open(os.path.join(paths.ASSETS, "vendor", name), "rb").read()
        h.send_response(200)
        h.send_header("Content-Type", ctype + "; charset=utf-8")
        h.send_header("Cache-Control", "max-age=86400")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return True
    if path == "/getting-started":
        h._send(200, render_html(pid), "text/html")
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
            set_startup(bool(body.get("on")))
            h._send(200, status())
        elif act == "network":
            save_network(bool(body.get("on")))
            h._send(200, status())
        elif act == "restart":
            if CTX["busy"]():
                return h._send(409, {"error": "An update is running. Restarting now would stop it. Try again when it finishes."}) or True
            h._send(200, {"ok": True})
            h.wfile.flush()
            restart_now()
        else:
            return False
    except Exception as e:
        h._send(500, {"error": str(e)[:300]})
    return True


# ---------------------------------------------------------------- page
def render_html(pid=None) -> str:
    named = pid is not None
    name = html.escape(people.name(pid)) if named else ""
    theme = None
    if named:
        try:
            theme = people.prefs(pid).get("display.theme")
        except Exception:
            theme = None
    tools = report.TOOLS if named else ""
    head = report.HEAD.replace("<title>Job Board</title>", "<title>Get started</title>")
    body = BODY.replace("__TOOLS__", f'<div class="tools" id="tools">\n{tools}  </div>' if named else "")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            "<script>(function(){var t=" + json.dumps(theme) +
            ';if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;})();</script>' +
            head + CSS + "</head><body>" + body + '<script src="/assets/vendor/qrcode.js"></script>\n' +
            "<script>window.__NAMED__=" + json.dumps(named) + ";</script>\n" + SCRIPT + "</body></html>")


CSS = """<style>
.gs{max-width:760px}
.gsum{margin:16px 0 4px;display:flex;flex-direction:column;gap:8px}
.gsum b{font-size:18px}
.gsbar{height:8px;border-radius:99px;background:var(--bar);overflow:hidden}
.gsbar i{display:block;height:100%;background:var(--good);width:0;transition:width .3s}
.gsrun{color:var(--muted);font-size:13px;margin:4px 0 0}
.gsopt{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:26px 0 0}
.gsoptp{margin:2px 0 0;color:var(--muted);font-size:13px}
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

BODY = """<div class="wrap">
<header class="top">
  <div class="brandline">
    <h1>Get started</h1>
  </div>
__TOOLS__
</header>
<main class="gs">
  <div class="gsum"><b id="sumText">Checking this computer…</b><div class="gsbar" aria-hidden="true"><i id="sumBar"></i></div>
    <p class="gsrun" id="runLine"></p></div>
  <ul class="gsl" id="list"></ul>
  <h2 class="gsopt">Optional</h2>
  <p class="gsoptp">Nice to have. These never count toward setup.</p>
  <ul class="gsl" id="listOpt"></ul>
</main>
</div>
"""

SCRIPT = r"""<script>
(function(){
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const api = (m, u, b) => fetch(u, {method: m, headers: m === "POST" ? H : undefined, body: b ? JSON.stringify(b) : undefined})
  .then(r => r.json().then(d => { if (!r.ok) throw Object.assign(new Error(d.error || "Something went wrong."), {data: d}); return d; }));
let S = null;
const ui = {msg: {}, login: null, loginMsg: "", restarting: false, busy: {}};
const say = (k, t, cls) => { ui.msg[k] = t ? {t, cls: cls || ""} : null; };
const msgHtml = k => ui.msg[k] ? `<span class="gsmsg ${ui.msg[k].cls}" role="status">${esc(ui.msg[k].t)}</span>` : "";

// ---- rows: [id, title, optional] -> {desc, body}
function rowClaude(){
  const i = S.install, c = S.claude;
  let desc = c.installed ? "Claude Code is on this computer. Siftwell uses it to rate jobs and tailor resumes on your Claude plan." : "Siftwell uses Claude Code (free to install) to rate jobs and tailor resumes with your Claude plan.";
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
function rowStartup(){
  const s = S.startup;
  let desc = "Siftwell starts by itself when you sign in to this computer, so the board is always ready.";
  let body = "";
  if (s.task && !s.own) desc = "Already on: an older Siftwell setup made a scheduled task named \"Job Board server\" that starts it at sign-in. Nothing to do here.";
  else if (s.task && s.own) desc = "On. (An older setup's scheduled task \"Job Board server\" is also present and is left alone.)";
  else if (s.on) desc = "On. Siftwell will start the next time you sign in to this computer.";
  const locked = s.task && !s.own;
  body = `<label class="gsw"><input type="checkbox" class="sw" role="switch" id="swStartup" ${s.on ? "checked" : ""} ${locked || ui.busy.startup ? "disabled" : ""}><span>${s.on ? "On" : "Off"}</span></label>`;
  return {desc, body: body + msgHtml("startup")};
}
function rowPhone(){
  const p = S.phone;
  let desc = p.on ? "Phones and tablets on your home Wi-Fi can open Siftwell." : "Right now only this computer can open Siftwell. Turn this on to use it from phones on your home Wi-Fi.";
  let body = `<label class="gsw"><input type="checkbox" class="sw" role="switch" id="swPhone" ${p.on ? "checked" : ""} ${ui.busy.phone || ui.restarting ? "disabled" : ""}><span>${p.on ? "On" : "Off"}</span></label>`;
  if (p.restart_needed) body += `<div class="gswarn">Restart Siftwell to apply this change. <button class="btn sm primary" type="button" data-act="restart" ${ui.restarting ? "disabled" : ""}>${ui.restarting ? "Restarting…" : "Restart now"}</button></div>`;
  if (p.on) {
    if (p.url) body += `<div class="gsmsg">On your phone, open this link (anyone with it can use Siftwell on your network, so keep it private):</div><div class="gslink" id="phoneLink">${esc(p.url)}</div><div class="gsqr" id="qr" aria-label="QR code for the phone link" role="img"></div>`
      + `<span class="gsmsg">${S.windows ? "The first time, Windows asks whether to allow Siftwell on your network. Choose Allow access on private networks. " : ""}Your phone must be on the same Wi-Fi as this computer.</span>`;
    else body += `<span class="gsmsg err">Couldn't find this computer's address on your network. Connect to Wi-Fi and re-check.</span><button class="btn ghost" type="button" data-act="recheck">Re-check</button>`;
  }
  return {desc, body: body + msgHtml("phone")};
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
const ROWS = {claude: rowClaude, signin: rowSignin, browser: rowBrowser, startup: rowStartup, phone: rowPhone, astra: rowAstra};

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
    if (!li) { li = document.createElement("li"); li.id = "row-" + it.id; (it.optional ? $("listOpt") : list).appendChild(li); }
    const r = ROWS[it.id]();
    li.className = "gsr" + (it.done ? " done" : "");
    li.innerHTML = `<span class="gsst" aria-hidden="true">${it.done ? "✓" : "○"}</span><div><h2>${esc(it.title)}${it.optional ? '' : ""}<span class="vh">${it.done ? " (done)" : " (not done)"}</span></h2><p>${esc(r.desc)}</p></div><div class="gsb">${r.body}</div>`;
  });
  drawQR();
}
function load(fresh){
  return api("GET", "/api/setup-status" + (fresh ? "?fresh=1" : "")).then(d => { S = d; render(); if (d.install.running) pollInstall(); })
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
});
document.addEventListener("change", e => {
  const el = e.target;
  if (el.id === "swStartup" || el.id === "swPhone") {
    const k = el.id === "swStartup" ? "startup" : "phone", on = el.checked;
    ui.busy[k] = true; say(k, ""); render(k);
    api("POST", "/api/getting-started/" + (k === "phone" ? "network" : "startup"), {on})
      .then(d => { S = d; say(k, k === "startup" ? (on ? "Turned on." : "Turned off.") : "", "ok"); })
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

// ---- header (only when there is a profile): Update / Re-rate hand off to the board; profile menu
if (window.__NAMED__ && $("tools")) {
  const toBoard = run => { try { if (run) sessionStorage.setItem(run[0], run[1]); } catch(e) {} location.href = "/#jobs"; };
  $("updateBtn").addEventListener("click", () => toBoard(["jb.run", "update"]));
  $("rerateBtn").addEventListener("click", () => toBoard(["jb.run", "rerate"]));
  let curPerson = "";
  fetch("/api/people").then(r => r.json()).then(d => {
    curPerson = d.current;
    const me = d.people.find(p => p.id === d.current) || {};
    $("avName").textContent = me.name || "Profile"; $("avInit").textContent = (me.name || "?").trim()[0].toUpperCase();
    $("amPeople").innerHTML = `<div class="who">Profiles</div>` + d.people.map(p => `<button role="menuitem" data-person="${esc(p.id)}" aria-current="${p.id === d.current}">${esc(p.name)}</button>`).join("") + `<button role="menuitem" data-person="__add">Add a person</button>`;
  }).catch(() => {});
  $("avatarBtn").addEventListener("click", e => { e.stopPropagation(); const h = $("amenu").hidden; $("amenu").hidden = !h; $("avatarBtn").setAttribute("aria-expanded", h); });
  document.addEventListener("click", e => { if (!e.target.closest(".menuWrap")) { $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false"); } });
  $("amenu").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false");
    if (b.id === "resumeBtn") return toBoard(["jb.openResume", "1"]);
    const v = b.dataset.person; if (!v) return;
    if (v === "__add") return toBoard(["jb.run", "addPerson"]);
    if (v === curPerson) return;
    fetch("/api/person", {method: "POST", headers: H, body: JSON.stringify({id: v})}).then(() => location.reload());
  });
}
load(false);
})();
</script>
"""
