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
    "directory_zip": "", "directory_radius": None,   # no home ZIP: where the employer directory looks (directory.area); not a job filter
    "salary_target": None, "travel_max": "any", "skip_employers": [], "skip_industries": [], "direction": "",
    "salary_floor": 0,          # lowest base pay to show; 0 = no floor (the default for new profiles)
    "current_base": None,
    "current_label": "",
    "seniority_mine": None,     # 1 (entry level) to 7; None = not chosen yet, so every level shows
    "seniority_band": [1, 7],
    "goals": "",
    "pivot_ai": False,          # legacy; a non-empty target_text turns the target tab on
    "target_text": "",          # the person's own words
    "target_scope": "all",      # "ai" = AI companies only, "all" = every tracked company
    "prep_text": "",            # what they're willing to do to get there
    "target_name": "",          # derived by Claude: tab label
    "target_any_title": False,  # derived: target open to any role
    "target_keywords": [],      # derived: title filter
    "target_summary": "",       # derived: one-line restatement
    "title_rule": "own",        # which job titles pass: "own" = only the person's own job titles (none given: every
                                # title); "builtin" = profiles from before that rule keep the old built-in word list
}

# Profiles made before these defaults changed keep what they had. A settings file always held every default of its
# day, so a key that is missing from the file (or a file that is missing) means "the old default", never the new one.
# New profiles get today's defaults written out by add().
LEGACY_MISSING = {"salary_floor": 150000, "seniority_mine": 4, "seniority_band": [3, 5], "title_rule": "builtin"}

def _with_defaults(saved):
    s = dict(DEFAULT_SETTINGS)
    s.update({k: (list(v) if isinstance(v, list) else v) for k, v in LEGACY_MISSING.items() if k not in saved})
    s.update(saved)
    return s

# The shared category lists of earlier versions ("tech" / "ops" / "nonprofit") are gone. catalog.move_lists() moved
# every company a profile watched through one onto that profile's own list, once; only that migration still reads
# these names (and a profile's old "company_sets" setting). People see one thing: "Your employers".
LEGACY_COMPANY_SETS = ("tech", "ops", "nonprofit")

def company_sets(pid=None):
    """The employers this profile watches ("Your employers"), as the catalog's list ids: the ones it added or was
    given (own-<id>), the ones found near it (near-<id>), and the ones added for everyone in the household (all)."""
    pid = pid or current()
    return {f"own-{pid}", f"near-{pid}", "all"}

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
    # Rating limits (Settings, Claude usage). Every one is per run, and ai_score.RUN_LIMITS caps them whatever is saved
    # here: an older, larger saved value simply means "as many as allowed". The key names are historical.
    "claude.per_update": (50, (0, 50)),          # Target-tab ratings per run
    "claude.opus_top": (50, (0, 1000)),          # how many of the best jobs get the most careful rating (50 new per run)
    "claude.sonnet_pct": (15, (0, 50)),          # share of quick-checked jobs that get a second look (100 per run)
    "claude.haiku_per_night": (500, (0, 500)),   # quick checks per RUN (the key's name is from an earlier version and is
                                                 # kept so nobody's setting is lost; a scheduled night counts as one run)
    "claude.auto_rerate": (True, [True, False]),
    "claude.auto_rate": (True, [True, False]),
    "claude.facts_per_update": (10, (0, 200)),   # shared facts: an update uses the highest value any profile sets
    "display.start_tab": ("jobs", ["jobs", "pivot", "tailored", "companies"]),
    "display.sort": ("score", ["score", "relevant", "appeal", "odds", "odds_later", "pay", "gd", "new"]),
    # (display.level, the board's old Seniority filter default, is gone: "Your level" in the board's My search decides it.)
    "display.clearance": ("secret", ["all", "none", "nopoly", "secret"]),
    "display.theme": ("system", ["system", "light", "dark"]),
}

def prefs(pid=None):
    """Current preferences, defaults filled in."""
    saved = settings(pid).get("prefs") or {}
    out = {}
    for k, (d, allowed) in PREF_SCHEMA.items():
        v = saved.get(k, d)
        if isinstance(allowed, tuple):  # a number saved under an older, wider range now means the most that's allowed
            try:
                v = max(allowed[0], min(allowed[1], int(v)))
            except (TypeError, ValueError):
                v = d
        out[k] = v
    return out

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
    try:
        saved = json.load(open(pdir("settings.json", pid=pid)))
    except Exception:
        saved = {}
    return _with_defaults(saved if isinstance(saved, dict) else {})

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
    return _with_defaults(d)

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
    # A new profile starts from today's defaults, written out in full: no pay floor, no level chosen, titles filtered
    # only by the person's own job titles (see LEGACY_MISSING).
    try:
        if not os.path.exists(pdir("settings.json", pid=pid)):
            _write_settings(json.loads(json.dumps(DEFAULT_SETTINGS)), pid)
    except Exception:
        pass
    # New profiles start with no clearance filter (the "secret" default in PREF_SCHEMA is kept only so existing
    # profiles that never saved this preference don't change behaviour). The same goes for questions before tailoring:
    # a new profile is asked only when the posting has real gaps ("gaps"); existing profiles keep what they had.
    try:
        save_prefs({"display.clearance": "all", "tailor.questions": "gaps"}, pid=pid)
    except Exception:
        pass
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
    save_settings({"salary_floor": cfg.get("salary_floor") or LEGACY_MISSING["salary_floor"],
                   "seniority_mine": sen.get("mine", 4), "seniority_band": sen.get("band", [3, 5]),
                   "goals": cfg.get("goals", ""), "title_rule": "builtin"}, pid=pid)
