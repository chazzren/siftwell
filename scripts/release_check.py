#!/usr/bin/env python3
"""Pre-release checks for Siftwell. Stdlib only (Python 3.12). Exit code 1 on any failure.

    python scripts/release_check.py            # CI mode: only tracked files; missing launchers are errors
    python scripts/release_check.py --local    # also sees untracked files; missing launchers are warnings

Checks: (1) every .py compiles, (2) page scripts pass `node --check`,
(3) leak scan of tracked files, (4) required files exist,
(5) nothing writes into the app folder (user data and runtime live outside it; see paths.py),
(6) Claude rating fingerprints/cache keys depend only on the person's data, not on prompt/model/schema text.
Extra private regexes (one per line) come from the LEAK_PATTERNS environment variable. A release must have them:
with --require-leak-patterns (the release workflow) an empty LEAK_PATTERNS is an error, not a warning.
"""
import argparse
import ast
import importlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- Easy-to-edit lists -------------------------------------------------------------------------
REQUIRED_FILES = ["README.md", "LICENSE", "requirements.txt", "server.py", "app_window.py", "tray.py", "VERSION", "frozen.py", "appupdate.py",
                  "installer/siftwell.iss", "installer/siftwell.spec", "installer/siftwell-mac.spec", "installer/build_mac.sh", "installer/smoke_mac.sh",
                  "assets/brand/siftwell-mark.svg", "assets/brand/siftwell-mark-mono.svg", "assets/brand/siftwell-logo.svg",
                  "assets/brand/siftwell-logo-dark.svg", "assets/brand/favicon-16.png", "assets/brand/favicon-32.png",
                  "assets/brand/favicon-48.png", "assets/brand/apple-touch-icon.png", "assets/brand/siftwell.ico",
                  "assets/brand/siftwell.icns", "assets/onet/onet.json.gz", "assets/onet/NOTICE.txt",
                  "assets/directory/seed.json.gz", "index_build/__init__.py", "index_build/local.py", "localdir.py"]
LAUNCHER_FILES = ["Start Siftwell.cmd", "Start Siftwell.command", "tools/launcher.ps1"]  # warning with --local
PAGE_MODULES = ["report", "settings_page", "profile_page", "manual_profile", "setup_page", "welcome_page", "getting_started", "catalog_page", "backup", "autoupdate", "appupdate", "directory"]  # missing = skipped
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

# Writes into the app folder that are allowed (file, function): the one-time move of a pre-DATA install's data/.
APP_WRITE_ALLOW = {("paths.py", "migrate")}
APP_WRITE_SKIP_PREFIXES = ["scripts/", ".github/"]  # dev-only tools, not shipped in the release ZIP
# ------------------------------------------------------------------------------------------------

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


def _repo_slug():
    """This repository's own "owner/name" (public by definition: it's the repo's address)."""
    slug = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not slug:
        try:
            url = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"], capture_output=True,
                                 text=True, timeout=10).stdout.strip()
            m = re.search(r"github\.com[:/]+([^/]+/[^/.]+)", url)
            slug = m.group(1) if m else ""
        except Exception:
            slug = ""
    return slug


def _allowed_spans(line, phrases):
    """Character ranges of allow-listed public phrases in a line (case-insensitive)."""
    spans, low = [], line.lower()
    for p in phrases:
        start = 0
        while p and (i := low.find(p, start)) >= 0:
            spans.append((i, i + len(p)))
            start = i + 1
    return spans


def check_leaks(files, require_private=False):
    rules = list(LEAK_RULES)
    # Public phrases a private pattern may legitimately match: the repo's own owner/name (its address) and the
    # company names in scripts/leak_allow.txt (e.g. an employer that shares a first name with someone).
    phrases = []
    slug = _repo_slug()
    if slug:
        phrases.append(slug.lower())
        owner, _, name = slug.lower().partition("/")
        phrases.append(f"io.github.{owner}.{name}")   # the Mac app's bundle id is built from the same public address
    allow_file = os.path.join(ROOT, "scripts", "leak_allow.txt")
    if os.path.isfile(allow_file):
        with open(allow_file, encoding="utf-8") as fh:
            phrases += [l.strip().lower() for l in fh if l.strip() and not l.lstrip().startswith("#")]
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
                spans = _allowed_spans(line, phrases) if phrases else []
                for label, rx in rules:
                    for m in rx.finditer(line):
                        text = m.group(0)
                        if label == "email address" and any(a in text.lower() for a in EMAIL_ALLOW):
                            continue
                        if label.startswith("private pattern") and any(a <= m.start() and m.end() <= b for a, b in spans):
                            continue  # inside the repo's own address or an allow-listed public company name
                        hits += 1
                        errors.append(f"leak: {f}:{n}: {label}: {mask(text)}")
    print(f"[leaks] {scanned} text files scanned with {len(rules)} rules "
          f"({extra} private pattern(s) from LEAK_PATTERNS), {hits} finding(s)")
    if not extra:
        (errors if require_private else warnings).append(
            "LEAK_PATTERNS is empty: personal-name checks were NOT run" +
            (" (a release needs them: set the LEAK_PATTERNS repository secret)" if require_private else ""))


def check_required(files, local):
    have = set(files)
    for f in REQUIRED_FILES:
        if f not in have:
            errors.append(f"required file missing: {f}")
    for f in LAUNCHER_FILES:
        if f not in have:
            (warnings if local else errors).append(f"launcher missing: {f}")
    print(f"[files] checked {len(REQUIRED_FILES)} required files and {len(LAUNCHER_FILES)} launchers")


# ---- (5) nothing writes into the app folder ---------------------------------------------------------------------
APP_ROOTS = {"APP", "HERE", "ASSETS", "PACKS", "CONFIG_DEFAULT", "LEGACY_RUN_DIR", "OLD", "__file__"}
WRITE_FUNCS = {  # dotted call name -> index of the path argument
    "os.makedirs": 0, "os.mkdir": 0, "os.rename": 1, "os.replace": 1, "os.remove": 0, "os.unlink": 0, "os.rmdir": 0,
    "shutil.copy": 1, "shutil.copy2": 1, "shutil.copyfile": 1, "shutil.copytree": 1, "shutil.move": 1, "shutil.rmtree": 0,
    "paths.write_atomic": 0, "paths.dump_json_atomic": 0, "write_atomic": 0, "dump_json_atomic": 0,
    "tempfile.mkstemp": None, "tempfile.mkdtemp": None, "tempfile.TemporaryDirectory": None, "tempfile.NamedTemporaryFile": None,
}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _names(node):
    """Names and dotted attributes used anywhere in an expression (paths.APP counts as APP)."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _walk_no_funcs(node):
    """ast.walk that doesn't descend into function bodies (module-level statements only)."""
    todo = [node]
    while todo:
        n = todo.pop()
        yield n
        for c in ast.iter_child_nodes(n):
            if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                todo.append(c)


def _app_tainted(nodes, base):
    """Names assigned (in these nodes) from expressions involving the app folder, on top of `base`; to a fixed point."""
    tainted = set(base)
    assigns = []
    for n in nodes:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) and len(t.elts) == len(n.value.elts):
                    pairs = zip(t.elts, n.value.elts)  # HERE, DATA = paths.APP, paths.DATA
                else:
                    pairs = [(t, n.value)]
                for tt, val in pairs:
                    for e in ast.walk(tt):
                        if isinstance(e, ast.Name):
                            assigns.append((e.id, val))
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and isinstance(n.target, ast.Name) and n.value is not None:
            assigns.append((n.target.id, n.value))
    changed = True
    while changed:
        changed = False
        for name, val in assigns:
            if name not in tainted and _names(val) & tainted:
                # reading a file's *contents* (open(...).read(), json.load) is data, not a path
                if any(isinstance(c, ast.Call) and _dotted(c.func) in ("open", "json.load", "json.loads") for c in ast.walk(val)):
                    continue
                tainted.add(name)
                changed = True
    return tainted


def _open_mode(call):
    mode = None
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return mode if isinstance(mode, str) else "r"


def check_no_app_writes(files):
    """Static scan: write-type calls whose path comes from the app folder (APP/HERE/__file__ and names derived from
    them). Reads are fine. Launcher scripts are scanned for writes under the app folder too."""
    found, scanned = [], 0
    for f in files:
        if not f.endswith(".py") or any(f.startswith(p) for p in APP_WRITE_SKIP_PREFIXES):
            continue
        full = os.path.join(ROOT, f)
        if not os.path.isfile(full):
            continue
        try:
            tree = ast.parse(open(full, encoding="utf-8").read())
        except SyntaxError:
            continue  # reported by the compile check
        scanned += 1
        module_taint = _app_tainted(_walk_no_funcs(tree), APP_ROOTS)
        funcs, scope = {}, {}  # node id -> outermost function name / that function's tainted names
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(fn) not in funcs:
                t = _app_tainted(ast.walk(fn), module_taint)
                for n in ast.walk(fn):
                    funcs.setdefault(id(n), fn.name)
                    scope.setdefault(id(n), t)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = _dotted(call.func)
            targets = []
            if name in ("open", "io.open", "os.open") and call.args:
                mode = _open_mode(call)
                if name == "os.open" or any(c in mode for c in "wax+"):
                    if name == "os.open":
                        flags = _names(call.args[1]) if len(call.args) > 1 else set()
                        if not flags & {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"}:
                            continue
                    targets.append(call.args[0])
            elif name.endswith((".write_text", ".write_bytes", ".mkdir", ".touch", ".unlink")) and isinstance(call.func, ast.Attribute):
                targets.append(call.func.value)
            elif name in WRITE_FUNCS:
                i = WRITE_FUNCS[name]
                if i is None:
                    targets += [kw.value for kw in call.keywords if kw.arg in ("dir", "prefix")]
                elif len(call.args) > i:
                    targets.append(call.args[i])
            for t in targets:
                if _names(t) & scope.get(id(call), module_taint):
                    fn = funcs.get(id(call), "<module>")
                    if (f, fn) in APP_WRITE_ALLOW:
                        continue
                    found.append(f"{f}:{call.lineno} ({fn}): {name}(...) writes under the app folder")
    # launchers: no variable built from the app folder may be written to, and no redirect/mkdir under it
    # (rx_def finds "name = <path built from {v}>"; applied until no new names turn up, so $Sift = Join-Path $App ...
    #  then $PortFile = Join-Path $Sift ... are both caught)
    for f, root, rx_def, rx_write in (
            ("tools/launcher.ps1", "App", r"^\s*\$(\w+)\s*=\s*.*Join-Path\s+\$(?:{v})\b",
             r"(?:(?:Set-Content|Add-Content|Out-File|New-Item|Copy-Item|Move-Item)\b[^|;]*?"
             r"(?:-Path|-FilePath|-LiteralPath|-Destination)\s+|-Redirect\w+\s+)\"?\$({v})\b"),
            ("Start Siftwell.command", "APP", r'^\s*(\w+)="\$\{{?(?:{v})\}}?/', r'(?:>|mkdir|touch|cp|mv)\s[^\n]*"?\$({v})\b'),
            ("Stop Siftwell.command", "APP", r'^\s*(\w+)="\$\{{?(?:{v})\}}?/', r'(?:>|mkdir|touch|cp|mv)\s[^\n]*"?\$({v})\b')):
        full = os.path.join(ROOT, f)
        if f not in files or not os.path.isfile(full):
            continue
        text = open(full, encoding="utf-8", errors="replace").read()
        scanned += 1
        names = {root}  # writing to the app folder itself counts too
        while True:
            v = "|".join(re.escape(n) for n in sorted(names))
            more = {m.group(1) for m in re.finditer(rx_def.format(v=v), text, re.M)} - names
            if not more:
                break
            names |= more
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            m = re.search(rx_write.format(v=v), line)
            if m:
                found.append(f"{f}:{n}: writes to ${m.group(1)} (inside the app folder)")
    for x in found:
        errors.append("app-folder write: " + x)
    print(f"[app-writes] {scanned} files scanned, {len(found)} write(s) into the app folder")


# ---- (6) rating fingerprints ignore prompt/model/schema text -------------------------------------------------
FP_TEST = r"""
import json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.getcwd())
D = os.environ["JOBBOARD_DATA"]
os.makedirs(os.path.join(D, "people", "pat"), exist_ok=True)
def w(rel, obj):
    with open(os.path.join(D, rel), "w", encoding="utf-8") as f:
        json.dump(obj, f)
w("people.json", [{"id": "pat", "name": "Pat"}])
prof = {"name": "Pat", "summary": "Operations lead with ten years in logistics.", "location": "Springfield",
        "years_experience": 10, "clearances": [], "education": ["BS Business"], "certifications": ["PMP"],
        "skills": ["Excel", "Scheduling"], "languages": ["English"],
        "experience": [{"employer": "Acme", "title": "Ops Lead", "dates": "2016-2026", "highlights": ["Ran a 20-person team"]}],
        "reframings": [{"angle": "Program management", "target_titles": ["Program Manager"], "evidence": ["Ran a 20-person team"]}],
        "hard_limits": ["No CPA"], "target_roles": ["Program Manager"], "title_keywords": ["program"], "fit_keywords": ["logistics"],
        "notes": "Some SQL."}
import resume
prof["_hash"] = resume.profile_hash(prof)
w("people/pat/profile.json", prof)
w("people/pat/facts.json", [{"id": "f1", "requirement": "Salesforce administration", "level": "some", "answer": "used it daily",
                             "polished": "Used Salesforce daily"}])
w("people/pat/highlights.json", {"extracted": {"degrees": [{"level": "bachelor", "field": "Business"}], "licenses": [],
                                 "years_experience": 10, "management": {"direct_reports": 20}}, "edits": {}, "confirmed": None})
w("people/pat/settings.json", {"goals": "Higher pay, short commute.", "target_text": "Program manager at a logistics firm",
                               "prep_text": "Evening course", "target_scope": "all", "salary_floor": 120000})
import people, ai_score, pivot, interview
people.set_current("pat", process_wide=True)
def snap():
    f = ai_score.fingerprints()
    inf = ai_score.info()
    return {k: f[k] for k in ("phash", "fp", "hl", "pfp")} | {"info_fp": inf["fp"], "info_hl": inf["hl"],
            "pivot_key": pivot.cache_keys(f, people.settings_strict(), people.read_saved_strict())[0]}
base = snap()
# 1. every prompt-side thing changes; fingerprints must not
ai_score.SYSTEM = "COMPLETELY NEW SYSTEM PROMPT " + ai_score.SYSTEM
pivot.SYSTEM_TMPL = "NEW PIVOT PROMPT " + pivot.SYSTEM_TMPL
ai_score.SCHEMA = {"type": "object"}; pivot.SCHEMA = {"type": "object"}
ai_score.MODELS = {k: "some-future-model" for k in ai_score.MODELS}
_pt, _ft = resume.profile_text, interview.facts_text
resume.profile_text = lambda p, g="": "REWORDED PROMPT HEADER\n" + _pt(p, g).replace("Hard limits", "Never claim")
interview.facts_text = lambda facts=None: "Reworded answers intro\n" + _ft(facts)
after = snap()
assert after == base, ("fingerprints changed when only prompt text changed", base, after)
# 2. whitespace / key order in the person's data must not matter
p2 = json.load(open(os.path.join(D, "people/pat/profile.json"), encoding="utf-8"))
p2 = dict(reversed(list(p2.items())))
p2["summary"] = "  Operations lead with   ten years in logistics. "
del p2["_hash"]
assert resume.profile_hash(p2) == base["phash"], "profile key depends on whitespace or key order"
# 3. a real data change must change the fingerprint
p3 = dict(prof, summary="Completely different summary")
assert ai_score.fingerprints(p3)["fp"] != base["fp"], "fingerprint ignores the resume summary"
# 3b. job titles are a board filter: changing them must not change any fingerprint or key (nor orphan any rating)
p_titles = dict(prof, target_roles=["Chief of Staff", "Operations Director", "Program Manager"])
ft = ai_score.fingerprints(p_titles)
for k in ("phash", "fp", "hl", "hl_old", "pfp", "pfp_old"):
    assert ft[k] == ai_score.fingerprints(prof)[k], "changing target_roles changed fingerprint/key " + k
assert resume.profile_hash(p_titles) == resume.profile_hash(prof), "profile hash depends on job titles"
assert pivot.cache_keys(ft, people.settings_strict(), people.read_saved_strict())[0] == base["pivot_key"], \
    "changing target_roles changed the Target key"
resume.edit_active({"target_roles": ["Chief of Staff", "Operations Director"]})
assert snap() == base, "saving new job titles changed a fingerprint/key"
w("people/pat/profile.json", prof)
# ...and ratings stored under the key older versions made (which included the titles) are adopted, not lost
old_key = resume.profile_hash_v1(prof)
assert old_key != base["phash"] and old_key in ai_score.profile_keys(dict(prof, _hash=old_key))[1], "old key not adopted"
by = {old_key: {"j1": {"opus": {"fp": "x"}}}}
ai_score.adopt(by, base["phash"], ai_score.profile_keys(dict(prof, _hash=old_key))[1])
assert by == {base["phash"]: {"j1": {"opus": {"fp": "x"}}}}, "ratings under the old key were not adopted"
# 4. goals, notes, an answers edit and a highlights edit must each change the fingerprint they feed
assert ai_score.fingerprints(dict(prof, notes="Some SQL and Python."))["fp"] != base["fp"], "fingerprint ignores notes"
sp = os.path.join(D, "people/pat/settings.json")
fp_path = os.path.join(D, "people/pat/facts.json")
hp = os.path.join(D, "people/pat/highlights.json")
settings0 = json.load(open(sp, encoding="utf-8"))
w("people/pat/settings.json", dict(settings0, goals="Fully remote, any pay."))
g = ai_score.fingerprints()
assert g["fp"] != base["fp"] and g["pfp"] != base["pfp"], "fingerprint ignores goals"
w("people/pat/settings.json", settings0)
facts0 = json.load(open(fp_path, encoding="utf-8"))
w("people/pat/facts.json", [dict(facts0[0], answer="used it daily for five years", level="yes")])
g = ai_score.fingerprints()
assert g["pfp"] != base["pfp"], "Target fingerprint ignores an answers edit"
w("people/pat/facts.json", facts0)
hl0 = json.load(open(hp, encoding="utf-8"))
w("people/pat/highlights.json", dict(hl0, edits={"years_experience": 12}))
g = ai_score.fingerprints()
assert g["hl"] != base["hl"] and g["pfp"] != base["pfp"], "fingerprint ignores a highlights edit"
w("people/pat/highlights.json", hl0)
assert snap() == base, "restoring the data did not restore the fingerprints"
# 5. a failed settings read must never produce a new Target key, rating run or cache write
import paths, claude_cli
with open(sp, "w", encoding="utf-8") as fh:
    fh.write('{"goals": "Higher pay, sho')   # partial file, as a non-atomic save would leave
paths.load_json_cache.__defaults__ = (1, 0)  # no waiting in the test
try:
    people.settings_strict()
    raise AssertionError("a partial settings file was read as if it were fine")
except paths.CacheUnreadable:
    pass
job = {"id": "j1", "title": "Program Manager", "company": "Acme", "locations": ["Springfield"], "tracks": ["ai"], "desc": "x",
       "fit_score": 50, "comp_score": 50, "qol_score": 50}
st = pivot.score_jobs([job], {"model": "m", "max_new_per_run": 5})
assert st == "settings_unreadable", st
assert not os.path.exists(pivot.CACHE), "Target run wrote a cache although settings were unreadable"
assert not os.path.exists(os.path.join(D, claude_cli.FORBID_LOG)), "Target run tried to call Claude with unreadable settings"
w("people/pat/settings.json", settings0)
assert snap() == base
print(json.dumps({"ok": True, "format": [ai_score.RATING_FORMAT, pivot.RATING_FORMAT]}))
"""


def check_fingerprints():
    if not all(os.path.exists(os.path.join(ROOT, m)) for m in ("ai_score.py", "pivot.py", "resume.py")):
        print("[fingerprints] modules not present, skipped")
        return
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, JOBBOARD_DATA=os.path.join(tmp, "data"), SIFTWELL_FORBID_CLAUDE="1",
                   SIFTWELL_RUNTIME=os.path.join(tmp, "runtime"), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", FP_TEST], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=120)
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        errors.append("fingerprints: " + " | ".join(msg[-3:]))
        print("[fingerprints] FAILED")
        return
    print("[fingerprints] ai_score/pivot fingerprints unchanged by prompt/model/schema edits; data changes still count")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="include untracked files; missing launchers are warnings")
    ap.add_argument("--require-leak-patterns", action="store_true",
                    help="fail when LEAK_PATTERNS is empty (the release workflow passes this; local runs only warn)")
    args = ap.parse_args()
    files = list_files(args.local)
    check_required(files, args.local)
    check_compile(files)
    check_js()
    check_leaks(files, args.require_leak_patterns and not args.local)
    check_no_app_writes(files)
    check_fingerprints()
    print()
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:  ", e)
    print(f"\nRelease check {'FAILED' if errors else 'passed'}: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
