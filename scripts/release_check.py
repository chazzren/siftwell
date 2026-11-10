#!/usr/bin/env python3
"""Pre-release checks for Siftwell. Stdlib only (Python 3.12). Exit code 1 on any failure.

    python scripts/release_check.py            # CI mode: only tracked files; missing launchers are errors
    python scripts/release_check.py --local    # also sees untracked files; missing launchers are warnings

Checks: (1) every .py compiles, (2) page scripts pass `node --check`,
(3) leak scan of tracked files, (4) required files exist.
Extra private regexes (one per line) come from the LEAK_PATTERNS environment variable.
"""
import argparse
import importlib
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- Easy-to-edit lists -------------------------------------------------------------------------
REQUIRED_FILES = ["README.md", "LICENSE", "requirements.txt", "server.py", "VERSION"]
LAUNCHER_FILES = ["Start Siftwell.cmd", "Start Siftwell.command", "tools/launcher.ps1"]  # warning with --local
PAGE_MODULES = ["report", "settings_page", "setup_page", "welcome_page", "getting_started"]  # missing = skipped
LEAK_SKIP_PREFIXES = ["assets/geo/"]
EMAIL_ALLOW = ["noreply@anthropic.com", "@users.noreply.github.com", "@example.com", "@example.org",
               "@example.net", "@test.com", "@localhost"]
# ------------------------------------------------------------------------------------------------

LEAK_RULES = [
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("phone number", re.compile(r"(?<![\w.])(?:\+?1[ .-])?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w-])")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("secret in assignment", re.compile(
        r"(?i)(?:secret|token|passw(?:or)?d|api[_-]?key|access[_-]?key|auth)\w*[\"']?\s*[:=]\s*[\"']"
        r"(?=[A-Za-z0-9+/=_-]*\d)[A-Za-z0-9+/=_-]{32,}[\"']")),  # must contain a digit (skips plain slugs)
]

errors, warnings = [], []


def mask(s):
    if len(s) <= 6:
        return s[0] + "***"
    return s[:2] + "*" * min(len(s) - 4, 12) + s[-2:]


def list_files(local):
    cmd = ["git", "ls-files", "-z"]
    if local:  # also include new files that are not committed or ignored yet
        cmd += ["--cached", "--others", "--exclude-standard"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=True).stdout
    return sorted({p for p in out.decode("utf-8", "replace").split("\0") if p})


def is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(8192)
    except OSError:
        return True


def check_compile(files):
    py = [f for f in files if f.endswith(".py") and os.path.isfile(os.path.join(ROOT, f))]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(py):
            try:
                py_compile.compile(os.path.join(ROOT, f), cfile=os.path.join(tmp, f"{i}.pyc"), doraise=True)
            except (py_compile.PyCompileError, OSError) as e:
                bad += 1
                errors.append(f"compile: {f}: {str(e).strip().splitlines()[-1]}")
    print(f"[compile] {len(py) - bad}/{len(py)} .py files compile")


def extract_scripts(mod):
    """Yield (label, js) for every inline <script> block found in str attributes of a page module."""
    for name in dir(mod):
        val = getattr(mod, name)
        if not isinstance(val, str) or "<script" not in val:
            continue
        for n, m in enumerate(re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", val, re.S | re.I)):
            js = re.sub(r"__[A-Z][A-Z0-9_]*__", "null", m.group(1))  # template placeholders like __BOOT__
            if js.strip():
                yield f"{mod.__name__}.{name}[{n}]", js


def check_js():
    node = shutil.which("node")
    if not node:
        errors.append("js: `node` not found on PATH")
        print("[js] node not found")
        return
    sys.path.insert(0, ROOT)
    old = os.environ.get("JOBBOARD_DATA")
    checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["JOBBOARD_DATA"] = os.path.join(tmp, "data")  # importing paths.py may migrate data
        for modname in PAGE_MODULES:
            if not os.path.exists(os.path.join(ROOT, modname + ".py")):
                print(f"[js] {modname}.py not present, skipped")
                continue
            try:
                mod = importlib.import_module(modname)
            except Exception as e:  # noqa: BLE001
                errors.append(f"js: cannot import {modname}: {type(e).__name__}: {e}")
                continue
            for label, js in extract_scripts(mod):
                path = os.path.join(tmp, f"s{checked}.js")
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(js)
                r = subprocess.run([node, "--check", path], capture_output=True, text=True)
                checked += 1
                if r.returncode:
                    msg = r.stderr.strip().splitlines() or ["syntax error"]
                    errors.append(f"js: {label}: " + " | ".join(msg[:4]))
    if old is None:
        os.environ.pop("JOBBOARD_DATA", None)
    else:
        os.environ["JOBBOARD_DATA"] = old
    if checked == 0:
        errors.append("js: no page scripts were found to check")
    print(f"[js] {checked} page script(s) checked with node --check")


def check_leaks(files):
    rules = list(LEAK_RULES)
    for i, line in enumerate((os.environ.get("LEAK_PATTERNS") or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rules.append((f"private pattern #{i + 1}", re.compile(line, re.I)))
        except re.error as e:
            errors.append(f"leak: LEAK_PATTERNS line {i + 1} is not a valid regex: {e}")
    extra = len(rules) - len(LEAK_RULES)
    scanned = hits = 0
    for f in files:
        if f.startswith("data/") or "/data/" in f:
            errors.append(f"leak: {f}: file under data/ must not be tracked")
            hits += 1
        if any(f.startswith(p) for p in LEAK_SKIP_PREFIXES):
            continue
        full = os.path.join(ROOT, f)
        if not os.path.isfile(full) or is_binary(full):
            continue
        scanned += 1
        with open(full, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                for label, rx in rules:
                    for m in rx.finditer(line):
                        text = m.group(0)
                        if label == "email address" and any(a in text.lower() for a in EMAIL_ALLOW):
                            continue
                        hits += 1
                        errors.append(f"leak: {f}:{n}: {label}: {mask(text)}")
    print(f"[leaks] {scanned} text files scanned with {len(rules)} rules "
          f"({extra} private pattern(s) from LEAK_PATTERNS), {hits} finding(s)")
    if not extra:
        warnings.append("LEAK_PATTERNS is empty: personal-name checks were NOT run")


def check_required(files, local):
    have = set(files)
    for f in REQUIRED_FILES:
        if f not in have:
            errors.append(f"required file missing: {f}")
    for f in LAUNCHER_FILES:
        if f not in have:
            (warnings if local else errors).append(f"launcher missing: {f}")
    print(f"[files] checked {len(REQUIRED_FILES)} required files and {len(LAUNCHER_FILES)} launchers")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="include untracked files; missing launchers are warnings")
    args = ap.parse_args()
    files = list_files(args.local)
    check_required(files, args.local)
    check_compile(files)
    check_js()
    check_leaks(files)
    print()
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:  ", e)
    print(f"\nRelease check {'FAILED' if errors else 'passed'}: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
