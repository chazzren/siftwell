"""Small wrapper around the Claude Code CLI (`claude -p`), which runs on the user's Claude subscription."""
import json, os, shutil, subprocess
import osdeps

import paths
WORK = paths.data("claude_work")  # empty cwd so no project files / CLAUDE.md get picked up

class CLIAuthError(Exception):
    pass

class CLIError(Exception):
    pass

def path():
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

def run_json(system, prompt, schema, model="claude-opus-5-5", effort="low", read_dir=None, timeout=600):
    """Run one headless Claude turn that must return JSON matching `schema`.
    read_dir: if set, Claude may use the Read tool inside that directory (for PDFs / images)."""
    p = path()
    if not p:
        raise CLIError("Claude Code is not installed")
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
