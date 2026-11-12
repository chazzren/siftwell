"""Small wrapper around the Claude Code CLI (`claude -p`), which runs on the user's Claude subscription."""
import json, os, shutil, subprocess, time
import osdeps

import paths
WORK = paths.data("claude_work")  # empty cwd so no project files / CLAUDE.md get picked up

# Which model does what. Ratings pick their own (ai_score.MODELS, pivot). For everything else: the big model only where
# judgment about a whole career is needed (reading a resume into a profile, tailoring, target suggestions); the middle
# one for careful but narrow writing (polishing an answer, asking questions, transcribing a scan); the small one for
# sorting and labelling (de-duplicating questions, naming a target, other job titles).
OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"

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

# ---------------------------------------------------------------- lean calls
# Every Siftwell call is one self-contained question: its own system prompt, a JSON schema, no conversation. Nothing
# from the person's Claude Code set-up belongs in it, and anything that slips in is paid for on every call (their
# skills list, slash commands, plugins, MCP servers and CLAUDE.md files can add tens of thousands of tokens).
# LEAN_FLAGS turns all of that off, as far as the installed Claude Code knows the flag (older versions simply don't
# get it: lean_args reads `claude --help` once). Sign-in is untouched: none of these flags changes where the
# credentials come from. Deliberately NOT used: --bare (it refuses the subscription sign-in) and --setting-sources
# (some people's sign-in lives in their user settings: an API-key helper, a provider switch).
LEAN_FLAGS = ("--safe-mode",                 # no CLAUDE.md, skills, plugins, hooks, MCP servers, custom commands or agents
              "--disable-slash-commands",    # no skills / slash-command list in the prompt
              "--strict-mcp-config",         # no MCP servers (none are passed)
              "--no-chrome")                 # no browser integration
_LEAN = {}

def lean_args(p=None):
    """The LEAN_FLAGS this Claude Code supports (cached per installed file)."""
    p = p or path()
    if not p:
        return []
    try:
        key = (p, os.path.getmtime(p))
    except OSError:
        key = (p, 0)
    if key not in _LEAN:
        try:
            r = osdeps.run_hidden([*osdeps.cmd(p), "--help"], capture_output=True, text=True, timeout=30, env=child_env(),
                                  encoding="utf-8", errors="replace")
            text = r.stdout or ""
        except Exception:
            text = ""
        _LEAN.clear()
        _LEAN[key] = [f for f in LEAN_FLAGS if (f + " ") in text or (f + "\n") in text or (f + ",") in text]
    return list(_LEAN[key])

def _lean_refused(p, stdout, stderr):
    """True (once) when this Claude Code turned a lean flag down although its help lists it: the flags are dropped
    for this run of Siftwell and the caller asks again without them. A refused command line never reaches Claude, so
    this costs nothing."""
    text = ((stderr or "") + " " + (stdout or ""))[:2000].lower()
    if not any(w in text for w in ("unknown option", "error: option", "invalid option", "unknown argument")):
        return False
    had = lean_args(p)
    for k in list(_LEAN):
        _LEAN[k] = []
    return bool(had)

# Variables a running Claude Code session hands to its children. If Siftwell is started from inside one (a terminal in
# the Claude app, an agent), its own `claude -p` calls must not inherit them: they would run as part of that session
# (its tools, its mode, its sign-in) instead of as the small stand-alone calls they are. Sign-in and provider settings
# (ANTHROPIC_*, CLAUDE_CODE_USE_*, CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CONFIG_DIR, proxies) are kept.
_KEEP_ENV = ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_", "CLAUDE_CODE_API_KEY", "CLAUDE_CODE_SKIP_",
             "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_GIT_BASH_PATH")

def child_env():
    env = {}
    for k, v in os.environ.items():
        u = k.upper()
        if (u.startswith("CLAUDE") or u.startswith("MCP_")) and not u.startswith(_KEEP_ENV) and u not in (TEST_EXE_ENV, STUB_ENV, PRETEND_ENV):
            continue
        env[k] = v
    return env

def command(p, model, effort, system, schema, tools=None, read_dir=None):
    """The one command line every Siftwell request to Claude uses (Match ratings included): print mode, the given
    system prompt and JSON schema, no session saved, the lean flags, and no tools unless the feature needs them
    (read_dir: the Read tool inside that folder, for scanned resumes; tools: e.g. web search for company facts)."""
    cmd = [*osdeps.cmd(p), "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--json-schema", json.dumps(schema), "--output-format", "json", "--no-session-persistence", *lean_args(p)]
    if read_dir:
        cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", read_dir, "--permission-mode", "dontAsk"]
    elif tools:
        cmd += ["--tools", ",".join(tools), "--allowedTools", ",".join(tools), "--permission-mode", "dontAsk"]
    else:
        cmd += ["--tools", ""]
    return cmd

def logged_in():
    p = path()
    if not p:
        return False
    try:
        r = osdeps.run_hidden([*osdeps.cmd(p), "auth", "status"], capture_output=True, text=True, timeout=30, env=child_env())
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
    cmd = command(p, model, effort, system, schema, tools=tools, read_dir=read_dir)
    def failed(why):     # a call that brought nothing back still shows in Settings (it may have used tokens)
        claude_usage.record(feature, model, {}, jobs, error=why)
    if cancel is None:
        try:
            r = osdeps.run_hidden(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=WORK, env=child_env(),
                                  encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            failed("timed out")
            raise CLIError(f"Claude took longer than {max(1, timeout // 60)} minutes")
        stdout, stderr = r.stdout, r.stderr
    else:
        import time
        proc = osdeps.popen_hidden(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", cwd=WORK, env=child_env())
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
                        failed("stopped")
                        raise CLICancelled()
                    failed("timed out")
                    raise CLIError(f"Claude took longer than {timeout // 60} minutes")
    try:
        out = json.loads(stdout)
        if not isinstance(out, dict):
            raise ValueError("not an object")
    except Exception:
        if _lean_refused(p, stdout, stderr):
            return run_json(system, prompt, schema, model=model, effort=effort, read_dir=read_dir, timeout=timeout, tools=tools,
                            cancel=cancel, feature=feature, jobs=jobs)
        failed("no readable answer")
        raise CLIError((stderr or stdout or "no output")[:300])
    if isinstance(out.get("usage"), dict):
        claude_usage.record(feature, model, out["usage"], jobs,   # real tokens, so Settings can show what was used
                            error="Claude reported an error" if out.get("is_error") else None)
    else:
        failed("no usage reported")
    if out.get("is_error"):
        txt = str(out.get("result", ""))
        if any(w in txt.lower() for w in ("log in", "login", "authenticat", "/login")):
            raise CLIAuthError(txt[:300])
        raise CLIError(txt[:300])
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result") or "{}")
    return data
