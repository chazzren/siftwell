"""Small wrapper around the Claude Code CLI (`claude -p`), which runs on the user's Claude subscription."""
import json, os, shutil, subprocess, time
import osdeps

import paths
WORK = paths.data("claude_work")  # empty cwd so no project files / CLAUDE.md get picked up

class CLIAuthError(Exception):
    pass

class CLIError(Exception):
    pass

class ClaudeForbidden(RuntimeError):
    """Raised instead of calling Claude while SIFTWELL_FORBID_CLAUDE=1 (tests that must not spend the user's plan)."""

FORBID_LOG = "forbidden_claude_calls.log"  # in DATA: one line per blocked call, so a test can count them

def forbid_check(what):
    """Call right before any request that spends Claude tokens (CLI `-p` or the API). With SIFTWELL_FORBID_CLAUDE=1 set,
    records the attempt in DATA/forbidden_claude_calls.log and raises ClaudeForbidden instead."""
    if os.environ.get("SIFTWELL_FORBID_CLAUDE") == "1":
        import datetime
        try:
            with open(paths.data(FORBID_LOG), "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}  {what}\n")
        except OSError:
            pass
        raise ClaudeForbidden(f"Claude call blocked by SIFTWELL_FORBID_CLAUDE: {what}")

def stop_requested():
    """True once the person pressed Stop on a rating run: the server creates the file named by SIFTWELL_STOP_FILE.
    Rating loops check it before each batch; batches already sent finish and are kept."""
    f = os.environ.get("SIFTWELL_STOP_FILE")
    return bool(f) and os.path.exists(f)

PRETEND_ENV = "SIFTWELL_PRETEND_NO_CLAUDE"   # =1: act as if Claude Code isn't installed (tests of the no-Claude experience)

def pretend_none():
    return os.environ.get(PRETEND_ENV) == "1"

def path():
    if pretend_none():
        return None
    return osdeps.find_exe("claude")

def logged_in():
    p = path()
    if not p:
        return False
    try:
        r = subprocess.run([*osdeps.cmd(p), "auth", "status"], capture_output=True, text=True, timeout=30)
        return bool(json.loads(r.stdout).get("loggedIn"))
    except Exception:
        return False

_ready_cache = {}
READY_TTL = 30  # seconds: `claude auth status` starts a process, so the answer is kept briefly

def invalidate():
    """Forget the cached answer (after installing or signing in)."""
    _ready_cache.clear()

def state(fresh=False):
    """"ready", "signed_out" (installed, not signed in) or "not_installed". Cached for READY_TTL seconds."""
    if pretend_none():
        return "not_installed"
    hit = _ready_cache.get("s")
    if hit and not fresh and time.time() - hit[0] < READY_TTL:
        return hit[1]
    if not path():
        v = "not_installed"
    else:
        v = "ready" if logged_in() else "signed_out"
    _ready_cache["s"] = (time.time(), v)
    return v

def claude_ready(fresh=False):
    """True when Claude Code is installed and signed in, so Claude features can run. Every Claude-dependent control
    checks this and, when it is False, explains how to connect Claude instead of failing."""
    return state(fresh) == "ready"

NOT_READY_MSG = "Connect Claude under Settings, then Get started. Siftwell works without it, but Match ratings, resume reading and tailoring need it."

def run_json(system, prompt, schema, model="claude-opus-5-5", effort="low", read_dir=None, timeout=600):
    """Run one headless Claude turn that must return JSON matching `schema`.
    read_dir: if set, Claude may use the Read tool inside that directory (for PDFs / images)."""
    forbid_check(f"claude_cli.run_json model={model}")
    p = path()
    if not p:
        raise CLIError("Claude isn't connected. " + NOT_READY_MSG)
    os.makedirs(WORK, exist_ok=True)
    cmd = [*osdeps.cmd(p), "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--json-schema", json.dumps(schema), "--output-format", "json", "--no-session-persistence"]
    if read_dir:
        cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", read_dir, "--permission-mode", "dontAsk"]
    else:
        cmd += ["--tools", ""]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=WORK)
    try:
        out = json.loads(r.stdout)
    except Exception:
        raise CLIError((r.stderr or r.stdout or "no output")[:300])
    if out.get("is_error"):
        txt = str(out.get("result", ""))
        if any(w in txt.lower() for w in ("log in", "login", "authenticat", "/login")):
            raise CLIAuthError(txt[:300])
        raise CLIError(txt[:300])
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result") or "{}")
    return data
