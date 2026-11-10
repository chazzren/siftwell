"""Household profiles. Each person has their own folder under DATA/people/<id>/ holding their resume profile,
answers, tailored resumes, marks, settings and their scored board. Job fetching is shared.

The "current person" is per thread (the server sets it per request and per background job) with a
process-wide fallback (the updater sets it while it works through each person)."""
import json, os, re, threading

import paths
HERE, DATA = paths.APP, paths.DATA
ROOT = os.path.join(DATA, "people")
INDEX = os.path.join(DATA, "people.json")

_local = threading.local()
_default = {"id": None}

DEFAULT_SETTINGS = {
    # Setup-flow answers (setup_done / setup_step are deliberately NOT here: save_settings writes every default,
    # and a written setup_done=False would send existing profiles back through setup).
    "home_zip": "", "radius_miles": 35, "workplaces": ["onsite", "hybrid", "remote"], "remote_us": True,
    "salary_target": None, "travel_max": "any", "skip_employers": [], "skip_industries": [], "direction": "",
    "salary_floor": 150000,
    "current_base": None,
    "current_label": "",
    "seniority_mine": 4,
    "seniority_band": [3, 5],
    "goals": "",
    "pivot_ai": False,          # legacy; a non-empty target_text turns the target tab on
    "target_text": "",          # the person's own words
    "target_scope": "all",      # "ai" = AI companies only, "all" = every tracked company
    "prep_text": "",            # what they're willing to do to get there
    "target_name": "",          # derived by Claude: tab label
    "target_any_title": False,  # derived: target open to any role
    "target_keywords": [],      # derived: title filter
    "target_summary": "",       # derived: one-line restatement
    "company_sets": ["tech"],   # which company lists this profile watches; own additions use "own-<id>"
}

COMPANY_SETS = {"tech": "Tech & AI", "ops": "Business & corporate (finance, consulting, health, large companies and HQs)",
                "nonprofit": "Nonprofit, associations & mission-driven (aging, health, development, think tanks, foundations, universities)"}

def company_sets(pid=None):
    """Lists this profile watches, always including its own additions and anything added for everyone."""
    pid = pid or current()
    return set(settings(pid).get("company_sets") or ["tech"]) | {f"own-{pid}", "all"}

# ---- app preferences (per profile). Each entry: default value and the allowed values (or a (min, max) range).
PREF_SCHEMA = {
    "resume.length": ("2", ["1", "2", "any"]),
    "resume.style": ("classic", ["classic", "modern", "compact"]),
    "resume.density": ("comfortable", ["comfortable", "compact"]),
    "resume.paper": ("letter", ["letter", "a4"]),
    "resume.summary": (True, [True, False]),
    "resume.skills": (True, [True, False]),
    "resume.additional": (True, [True, False]),
    "resume.education_first": (False, [True, False]),
    "resume.clearance": ("past", ["past", "active", "hide"]),
    "resume.functional_titles": ("paren", ["paren", "line", "hide"]),
    "resume.contact_location": (True, [True, False]),
    "resume.contact_phone": (True, [True, False]),
    "resume.contact_email": (True, [True, False]),
    "resume.contact_linkedin": (True, [True, False]),
    "tailor.style": ("balanced", ["light", "balanced", "strong"]),
    "tailor.questions": ("always", ["always", "gaps", "never"]),
    "tailor.bullets_recent": (5, (2, 8)),
    "tailor.bullets_older": (3, (1, 6)),
    "review.enabled": (True, [True, False]),
    "review.threshold": (80, (60, 95)),
    "review.max_rounds": (2, (1, 4)),
    "review.ask_facts": (True, [True, False]),
    "claude.per_update": (300, (0, 1000)),
    "claude.opus_top": (300, (0, 1000)),
    "claude.sonnet_pct": (15, (0, 50)),
    "claude.haiku_per_night": (4000, (0, 20000)),
    "claude.auto_rerate": (True, [True, False]),
    "claude.auto_rate": (True, [True, False]),
    "display.start_tab": ("jobs", ["jobs", "pivot", "tailored", "companies"]),
    "display.sort": ("score", ["score", "odds", "odds_later", "pay", "gd", "new"]),
    "display.level": ("near", ["near", "mine", "above", "below", "all"]),
    "display.clearance": ("secret", ["all", "none", "nopoly", "secret"]),
    "display.theme": ("system", ["system", "light", "dark"]),
}

def prefs(pid=None):
    """Current preferences, defaults filled in."""
    saved = settings(pid).get("prefs") or {}
    return {k: saved.get(k, d) for k, (d, _) in PREF_SCHEMA.items()}

def clean_prefs(new):
    """Keep only known keys with allowed values (numbers clamped to their range)."""
    out = {}
    for k, v in (new or {}).items():
        if k not in PREF_SCHEMA:
            continue
        d, allowed = PREF_SCHEMA[k]
        if isinstance(allowed, tuple):
            try:
                out[k] = max(allowed[0], min(allowed[1], int(v)))
            except (TypeError, ValueError):
                continue
        elif v in allowed and type(v) is type(d):
            out[k] = v
    return out

def save_prefs(new, pid=None):
    merged = {**prefs(pid), **clean_prefs(new)}
    s = settings(pid)
    s["prefs"] = merged
    _write_settings(s, pid)
    return merged

def target_on(s):
    return bool((s.get("target_text") or "").strip())

def load_index():
    try:
        return json.load(open(INDEX))
    except Exception:
        return []

def save_index(people):
    os.makedirs(DATA, exist_ok=True)
    json.dump(people, open(INDEX, "w"), indent=1)

def ids():
    return [p["id"] for p in load_index()]

def exists(pid):
    return pid in ids()

def first():
    p = load_index()
    return p[0]["id"] if p else None

def set_current(pid, process_wide=False):
    if process_wide:
        _default["id"] = pid
    _local.pid = pid

def current():
    """Current person's id, or None before any profiles exist (legacy single-user layout)."""
    return getattr(_local, "pid", None) or _default["id"] or first()

def pdir(*parts, pid=None):
    pid = pid or current()
    if not pid:
        raise LookupError("No profile yet: add a person first.")
    d = os.path.join(ROOT, pid)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, *parts)

def settings(pid=None):
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.load(open(pdir("settings.json", pid=pid))))
    except Exception:
        pass
    return s

def read_saved_strict(pid=None):
    """The person's saved settings.json exactly as stored (no defaults). A missing file -> None; one that can't be read
    or parsed (a save in progress, a damaged file) -> retried briefly, then paths.CacheUnreadable. Use it wherever a
    cache key or fingerprint is derived from settings: never derive one from a failed read."""
    d = paths.load_json_cache(pdir("settings.json", pid=pid))
    if d is not None and not isinstance(d, dict):
        raise paths.CacheUnreadable("settings.json is not a settings object; left it untouched.")
    return d

def settings_strict(pid=None, missing_ok=False):
    """settings(), but an unreadable file raises paths.CacheUnreadable instead of silently giving defaults. A missing
    file raises too unless missing_ok (a profile that never saved anything simply has the defaults)."""
    d = read_saved_strict(pid)
    if d is None:
        if not missing_ok:
            raise paths.CacheUnreadable("settings.json is missing; left it alone.")
        d = {}
    return {**DEFAULT_SETTINGS, **d}

def _write_settings(s, pid=None):
    paths.dump_json_atomic(pdir("settings.json", pid=pid), s, indent=1)

def save_settings(new, pid=None):
    s = settings(pid)
    for k in DEFAULT_SETTINGS:
        if k in new:
            s[k] = new[k]
    _write_settings(s, pid)
    return s

def add(name):
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("Give the profile a name.")
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "person"
    pid, n, taken = base, 2, set(ids())
    while pid in taken:
        pid, n = f"{base}-{n}", n + 1
    people = load_index() + [{"id": pid, "name": name}]
    save_index(people)
    pdir(pid=pid)
    return pid

def rename(pid, name):
    people = load_index()
    for p in people:
        if p["id"] == pid:
            p["name"] = (name or p["name"]).strip()[:40]
    save_index(people)

def remove(pid):
    """Take a profile off the board. Its folder moves to data/people_removed/ (not deleted), so it can be restored."""
    import shutil, time
    save_index([p for p in load_index() if p["id"] != pid])
    src = os.path.join(ROOT, pid)
    if os.path.isdir(src):
        dest_root = os.path.join(DATA, "people_removed")
        os.makedirs(dest_root, exist_ok=True)
        shutil.move(src, os.path.join(dest_root, f"{pid}-{time.strftime('%Y%m%d-%H%M%S')}"))
    if _default["id"] == pid:
        _default["id"] = None

def name(pid=None):
    pid = pid or current()
    return next((p["name"] for p in load_index() if p["id"] == pid), pid)

LEGACY = ["profile.json", "profile_draft.json", "facts.json", "questions", "tailored", "resumes", "marks.json", "jobs.json"]

def ensure_migrated(base_cfg=None):
    """Very old single-user layout (resume files loose in DATA, no people.json): move them into a profile.
    A fresh install has none of those files and simply starts with no profiles (the board shows a welcome page)."""
    if os.path.exists(INDEX) or not any(os.path.exists(os.path.join(DATA, f)) for f in LEGACY):
        return
    import shutil
    try:
        full = json.load(open(os.path.join(DATA, "profile.json"))).get("name") or ""
    except Exception:
        full = ""
    pid = add(full.split()[0] if full else "Me")
    for f in LEGACY:
        src = os.path.join(DATA, f)
        if os.path.exists(src):
            shutil.move(src, pdir(f, pid=pid))
    cfg = base_cfg or paths.load_config()
    sen = cfg.get("seniority", {})
    save_settings({"salary_floor": cfg.get("salary_floor") or DEFAULT_SETTINGS["salary_floor"],
                   "seniority_mine": sen.get("mine", 4), "seniority_band": sen.get("band", [3, 5]),
                   "goals": cfg.get("goals", "")}, pid=pid)
