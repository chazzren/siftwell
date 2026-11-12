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

TEST_EXE_ENV = "SIFTWELL_TEST_CLAUDE_EXE"  # tests only: a stand-in `claude` (a fake that answers `auth status` and
                                            # `auth login`); when set, only that file counts, never the real Claude Code

def pretend_none():
    return os.environ.get(PRETEND_ENV) == "1" and not os.environ.get(TEST_EXE_ENV)

def path():
    test = os.environ.get(TEST_EXE_ENV)
    if test:
        return test if os.path.isfile(test) else None
    if pretend_none():
        return None
    return osdeps.find_exe("claude")

def logged_in():
    p = path()
    if not p:
        return False
    try:
        r = osdeps.run_hidden([*osdeps.cmd(p), "auth", "status"], capture_output=True, text=True, timeout=30)
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

class CLICancelled(Exception):
    """run_json(cancel=...) was told to stop; the claude process was ended."""

STUB_ENV = "SIFTWELL_CLAUDE_STUB"  # tests: path to a JSON file answered instead of calling Claude (see _stub)

def _stub(prompt, cancel=None):
    """Test hook: with SIFTWELL_CLAUDE_STUB=<file.json> set, run_json returns canned JSON and never calls Claude.
    The file holds the answer itself, or {"_delay": seconds, "_by_prompt": [[substring, answer], ...], "_default": answer}
    (the first substring found in the prompt picks the answer; with no match and no "_default", None: the call goes on
    as usual, so SIFTWELL_FORBID_CLAUDE=1 still blocks it)."""
    import time
    with open(os.environ[STUB_ENV], encoding="utf-8") as f:
        d = json.load(f)
    if not (isinstance(d, dict) and ("_by_prompt" in d or "_default" in d)):
        return d
    for sub, ans in d.get("_by_prompt") or []:
        if sub in prompt:
            break
    else:
        return d.get("_default")
    t_end = time.time() + float(d.get("_delay") or 0)
    while time.time() < t_end:
        if cancel is not None and cancel.is_set():
            raise CLICancelled()
        time.sleep(0.2)
    return ans

def _kill(proc):
    """End a claude process and everything it started (on Windows it may run under cmd /c)."""
    try:
        if osdeps.WINDOWS:
            osdeps.run_hidden(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=20)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def run_json(system, prompt, schema, model="claude-opus-5-5", effort="low", read_dir=None, timeout=600, tools=None, cancel=None,
             feature=None, jobs=None):
    """Run one headless Claude turn that must return JSON matching `schema`.
    read_dir: if set, Claude may use the Read tool inside that directory (for PDFs / images).
    tools: built-in tools Claude may use without asking (e.g. ["WebSearch", "WebFetch"]).
    cancel: a threading.Event; when set, the claude process is ended and CLICancelled is raised.
    feature / jobs: for the usage log (claude_usage.py); feature defaults to the calling module's plain name."""
    import claude_usage
    feature = feature or claude_usage.feature_from_caller(2)
    if os.environ.get(STUB_ENV):
        canned = _stub(prompt, cancel)
        if canned is not None:
            claude_usage.record(feature, model, {}, jobs, stub=True)
            return canned
    forbid_check(f"claude_cli.run_json model={model}")
    p = path()
    if not p:
        raise CLIError("Claude isn't connected. " + NOT_READY_MSG)
    os.makedirs(WORK, exist_ok=True)
    cmd = [*osdeps.cmd(p), "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--json-schema", json.dumps(schema), "--output-format", "json", "--no-session-persistence"]
    if read_dir:
        cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", read_dir, "--permission-mode", "dontAsk"]
    elif tools:
        cmd += ["--tools", ",".join(tools), "--allowedTools", ",".join(tools), "--permission-mode", "dontAsk"]
    else:
        cmd += ["--tools", ""]
    if cancel is None:
        r = osdeps.run_hidden(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=WORK)
        stdout, stderr = r.stdout, r.stderr
    else:
        import time
        proc = osdeps.popen_hidden(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", cwd=WORK)
        deadline, inp = time.time() + timeout, prompt
        while True:
            try:
                stdout, stderr = proc.communicate(input=inp, timeout=2)
                break
            except subprocess.TimeoutExpired:
                inp = None  # (input can only be sent once)
                if cancel.is_set() or time.time() > deadline:
                    _kill(proc)
                    try:
                        proc.communicate(timeout=20)
                    except Exception:
                        pass
                    if cancel.is_set():
                        raise CLICancelled()
                    raise CLIError(f"Claude took longer than {timeout // 60} minutes")
    try:
        out = json.loads(stdout)
    except Exception:
        raise CLIError((stderr or stdout or "no output")[:300])
    if isinstance(out, dict) and isinstance(out.get("usage"), dict):
        claude_usage.record(feature, model, out["usage"], jobs)   # real tokens, so Settings can show what was used
    if out.get("is_error"):
        txt = str(out.get("result", ""))
        if any(w in txt.lower() for w in ("log in", "login", "authenticat", "/login")):
            raise CLIAuthError(txt[:300])
        raise CLIError(txt[:300])
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result") or "{}")
    return data
