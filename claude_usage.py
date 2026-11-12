"""What Siftwell actually asked Claude for: one line per Claude call in DATA/claude_usage.jsonl.

Each line: {"t": ISO time, "feature": plain-language feature, "model": model id, "in": input tokens, "out": output
tokens, "cache_read": n, "cache_write": n, "jobs": jobs in the batch or null} (plus "stub": true for test answers).
No prompt text and nothing personal is written. Settings (Claude usage) shows today / the last 7 days by feature;
showing it reads this file only and never calls Claude."""
import datetime as dt
import json, os, sys, threading

import paths

FILE = "claude_usage.jsonl"
_lock = threading.Lock()
KEEP_DAYS = 120          # older lines are dropped when the file grows past MAX_BYTES
MAX_BYTES = 4_000_000

# module that asked -> what the person sees in Settings
FEATURES = {
    "ai_score": "Match ratings", "pivot": "Target ratings", "resume": "Reading your resume", "highlights": "Resume highlights",
    "tailor": "Tailored resumes", "interview": "Questions about your experience", "target": "Target suggestions",
    "nlsearch": "Search", "employer_finder": "Finding employers", "company_research": "Company facts",
    "requirements": "Job requirements", "manual_profile": "Your profile", "lookfor": "What to look for",
}


def path():
    return paths.data(FILE)


def feature_from_caller(depth=2):
    """Plain feature name for the module that called Claude (looked up from the call stack)."""
    try:
        mod = (sys._getframe(depth).f_globals.get("__name__") or "").rsplit(".", 1)[-1]
    except Exception:
        return "Other"
    return FEATURES.get(mod, "Other")


def _n(u, *keys):
    for k in keys:
        v = (u or {}).get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def record(feature, model, usage, jobs=None, stub=False):
    """Append one line. usage: the "usage" object from `claude -p --output-format json` (or the API's usage)."""
    u = usage if isinstance(usage, dict) else {}
    row = {"t": dt.datetime.now().isoformat(timespec="seconds"), "feature": str(feature or "Other")[:60],
           "model": str(model or "")[:60], "in": _n(u, "input_tokens"), "out": _n(u, "output_tokens"),
           "cache_read": _n(u, "cache_read_input_tokens"), "cache_write": _n(u, "cache_creation_input_tokens"),
           "jobs": int(jobs) if isinstance(jobs, int) else None}
    if stub:
        row["stub"] = True
    try:
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        with _lock:
            _trim()
            with open(path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except OSError:
        pass   # usage notes must never break a rating or a tailoring


def _trim():
    try:
        if os.path.getsize(path()) < MAX_BYTES:
            return
    except OSError:
        return
    cut = (dt.datetime.now() - dt.timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    keep = [ln for ln in _lines() if (ln.get("t") or "") >= cut]
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for ln in keep:
            f.write(json.dumps(ln) + "\n")
    os.replace(tmp, path())


def _lines():
    try:
        with open(path(), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    yield d
    except OSError:
        return


def summary(now=None):
    """{"today": {...}, "week": {...}} where each is {"calls", "in", "out", "cache_read", "cache_write", "jobs",
    "features": [{"feature", "calls", "tokens", "jobs"}, ...] (biggest first)}. Tokens = input + output + cache."""
    now = now or dt.datetime.now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week0 = day0 - dt.timedelta(days=6)
    out = {}
    for name, since in (("today", day0), ("week", week0)):
        s = since.isoformat(timespec="seconds")
        tot = {"calls": 0, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "jobs": 0}
        feats = {}
        for d in _lines():
            if (d.get("t") or "") < s:
                continue
            tok = sum(int(d.get(k) or 0) for k in ("in", "out", "cache_read", "cache_write"))
            tot["calls"] += 1
            for k in ("in", "out", "cache_read", "cache_write"):
                tot[k] += int(d.get(k) or 0)
            tot["jobs"] += int(d.get("jobs") or 0)
            f = feats.setdefault(d.get("feature") or "Other", {"feature": d.get("feature") or "Other", "calls": 0, "tokens": 0, "jobs": 0})
            f["calls"] += 1; f["tokens"] += tok; f["jobs"] += int(d.get("jobs") or 0)
        tot["features"] = sorted(feats.values(), key=lambda f: (-f["tokens"], -f["calls"], f["feature"]))
        out[name] = tot
    return out
