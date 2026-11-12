"""First-run setup flow for a profile: one question per screen, resumable.

The page (setup_page.py) talks to three routes the server wires to these functions:
  GET  /api/setup         -> get_state(pid, ingest=ps(pid)["resume"])
  POST /api/setup/step    -> save_step(pid, step, data)
  POST /api/setup/finish  -> finish(pid)

Answers are written straight into the profile's settings.json. Existing keys are reused where they exist
(salary_floor, current_base, seniority_mine, seniority_band, target_text, target_scope, and the
display.clearance pref); the new keys live in SETUP_DEFAULTS. people.save_settings() only writes keys listed in
people.DEFAULT_SETTINGS, so this module writes settings.json itself (people.settings() keeps unknown keys, so
later saves from the My profile page preserve them)."""
import json, os, re, statistics

import catalog
import people

STEPS = ["welcome", "resume", "highlights", "where", "pay", "level", "direction", "dealbreakers", "companies",
         "questions", "board"]
OPTIONAL = {"questions"}           # page shows Skip; resume can also be skipped but later steps get thinner
NEEDS_CLAUDE = {"questions"}       # left out altogether while Claude isn't connected (the screen could only say so)

RADII = [10, 25, 35, 50, 75]
WORKPLACES = ["onsite", "hybrid", "remote"]
TRAVEL = ["none", "light", "moderate", "any"]   # matches jobfinder travel levels (none/light/moderate/heavy)
DIRECTIONS = ["keep", "specific", "unsure"]
CLEARANCE = people.PREF_SCHEMA["display.clearance"][1]   # ["all", "none", "nopoly", "secret"]

SETUP_DEFAULTS = {
    "home_zip": "",
    "radius_miles": 35,
    "workplaces": ["onsite", "hybrid", "remote"],
    "remote_us": True,
    "salary_target": None,
    "travel_max": "any",
    "skip_employers": [],
    "skip_industries": [],
    "direction": "",
    "setup_done": False,
    "setup_step": "welcome",
    "search_started": "",   # when Start my job search first ran for this profile (first_search.py); empty = never
}

INDUSTRY_IDEAS = ["Defense & weapons", "Government contracting", "Gambling", "Tobacco & vaping", "Crypto",
                  "Staffing agencies", "Oil & gas", "Payday lending", "Adtech"]


class SetupError(ValueError):
    """Bad input for a step. str(e) is a friendly sentence; .field names the input it belongs to."""
    def __init__(self, msg, field=None):
        super().__init__(msg)
        self.field = field


# ------------------------------------------------------------------ storage
def _path(pid):
    return people.pdir("settings.json", pid=pid)

def _raw(pid):
    try:
        return json.load(open(_path(pid)))
    except Exception:
        return {}

def _settings(pid):
    try:
        raw = json.load(open(_path(pid)))
    except Exception:
        raw = {}
    return {**SETUP_DEFAULTS, **people._with_defaults(raw if isinstance(raw, dict) else {})}

def _write(pid, updates):
    try:
        raw = json.load(open(_path(pid)))
    except Exception:
        raw = {}
    raw.update(updates)
    tmp = _path(pid) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(raw, f, indent=1)
    os.replace(tmp, _path(pid))
    return raw

def _profiles(pid):
    """(active, draft) resume profiles for this person, without the raw resume text."""
    def load(fn):
        try:
            p = json.load(open(people.pdir(fn, pid=pid)))
            p.pop("_resume_text", None)
            return p
        except Exception:
            return None
    return load("profile.json"), load("profile_draft.json")


# ------------------------------------------------------------------ derived bits
def _levels():
    try:
        import jobfinder
        return jobfinder.LEVEL_NAMES
    except Exception:
        return {1: "Entry level", 2: "Mid-level", 3: "Senior", 4: "Lead / Manager", 5: "Principal / Sr. Manager", 6: "Director", 7: "VP / Executive"}

def infer_level(prof):
    """The level (1-7) the person's own job title states, for the hint on the Level screen: "Senior Accountant",
    "Nurse Manager", "Apprentice Electrician". None when the title states no level: years of experience alone are not
    enough to suggest one (six years as a staff nurse is not "Senior"), so then there is no hint at all.
    Nothing is pre-selected from it."""
    if not prof:
        return None
    try:
        import jobfinder
        tl = jobfinder.title_level
    except Exception:
        return None
    titles = []
    try:
        import lookfor
        titles.append(lookfor._auto_recent(prof))     # the title they typed, else their most recent job
    except Exception:
        pass
    exp = prof.get("experience") or []
    titles.append(exp[0].get("title", "") if exp else "")
    for title in titles:
        level = tl(title) if title else None
        if level:
            level = max(1, min(7, level))
            return {"level": level, "name": _levels()[level], "why": f"your most recent title, “{title}”"}
    return None

def current_employer(prof):
    exp = (prof or {}).get("experience") or []
    emp = (exp[0].get("employer") or "").strip() if exp else ""
    dates = (exp[0].get("dates") or "").lower() if exp else ""
    return emp if emp and ("present" in dates or "current" in dates or "now" in dates) else ""

def highlights(prof):
    """The 'Here's what I read' cards. Data-driven: if the profile carries its own "highlights" list
    (cards shaped like the ones below) it is used as-is; otherwise cards come from the extraction fields."""
    if not prof:
        return {"name": "", "summary": "", "cards": []}
    if isinstance(prof.get("highlights"), list) and prof["highlights"]:
        cards = prof["highlights"]
    else:
        cards = []
        exp = prof.get("experience") or []
        y = prof.get("years_experience")
        if isinstance(y, int) and y > 0:
            sub = f"{exp[0].get('title', '')} at {exp[0].get('employer', '')}" if exp else ""
            cards.append({"id": "years", "label": "Experience", "icon": "clock", "value": f"{y} years", "detail": sub})
        for key, label, icon in (("education", "Education", "cap"), ("certifications", "Certifications", "badge"),
                                 ("clearances", "Clearances", "shield")):
            items = [str(x) for x in (prof.get(key) or []) if str(x).strip()]
            if items:
                cards.append({"id": key, "label": label, "icon": icon, "items": items[:6]})
        skills = [str(x) for x in (prof.get("skills") or []) if str(x).strip()]
        if skills:
            cards.append({"id": "skills", "label": "Skills", "icon": "spark", "chips": skills[:14],
                          "more": max(0, len(skills) - 14)})
    name = prof.get("name") or ""
    if name.lower().startswith("not stated"):
        name = ""
    return {"name": name, "summary": prof.get("summary", ""), "cards": cards}

def _pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)

def market_hint(prof, level=None, market_path=None):
    """Pay for similar openings in the shared job pool: titles matching the profile's title keywords,
    near their level. None when there's too little data."""
    try:
        import target
        rows = json.load(open(market_path or target.MARKET))
    except Exception:
        return None
    kws = [k.lower() for k in ((prof or {}).get("title_keywords") or []) if len(k) >= 3]
    if not kws:
        return None
    hits = [r for r in rows if r.get("m") and any(k in r["t"].lower() for k in kws)]
    near = [r for r in hits if level and r.get("l") and abs(r["l"] - level) <= 1]
    pool, basis = (near, "near your level") if len(near) >= 8 else (hits, "at all levels")
    if len(pool) < 8:
        return None
    mids = [r["m"] for r in pool]
    rnd = lambda x: int(round(x / 1000.0)) * 1000
    return {"median": rnd(statistics.median(mids)), "p25": rnd(_pct(mids, .25)), "p75": rnd(_pct(mids, .75)),
            "n": len(pool), "basis": f"{len(pool)} openings with pay listed, roles like yours {basis}"}

def recent_title(pid):
    """The person's most recent job title as their what-to-look-for sheet has it (from the resume or typed)."""
    try:
        import lookfor
        return lookfor.ensure(pid).get("recent") or ""
    except Exception:
        return ""


# ------------------------------------------------------------------ state
def _band_offsets(mine, band):
    lo, hi = (band or [mine - 1, mine + 1])[:2]
    offs = [o for o in (-1, 0, 1) if lo <= mine + o <= hi]
    return offs or [0]

def _claude_ready():
    try:
        import claude_cli
        return bool(claude_cli.claude_ready())
    except Exception:
        return True

def get_state(pid, ingest=None):
    """Everything the page needs to render any step. ingest is server.ps(pid)["resume"] (running/error)."""
    s = _settings(pid)
    raw = _raw(pid)
    pr = people.prefs(pid)
    active, draft = _profiles(pid)
    prof = draft or active
    ingest = ingest or {}
    if ingest.get("running"):
        rstatus = "reading"
    elif draft:
        rstatus = "draft"
    elif active:
        rstatus = "active"
    else:
        rstatus = "none"
    guess = infer_level(prof)
    mine = int(s["seniority_mine"]) if s.get("seniority_mine") else None   # None: not chosen (every level shows)
    step = s.get("setup_step") if s.get("setup_step") in STEPS else "welcome"
    ready = _claude_ready()
    if step not in steps_for(ready):       # stopped on a step that is left out now: carry on at the one after it
        step = next_step(step, ready)
    emp = current_employer(prof)
    direction = s.get("direction") or ("specific" if (s.get("target_text") or "").strip() else "")
    return {
        "pid": pid,
        "name": people.name(pid),
        "step": step,
        "done": bool(s.get("setup_done")),
        "steps": STEPS,
        "active_steps": steps_for(ready),
        "optional": sorted(OPTIONAL),
        "theme": pr.get("display.theme", "system"),
        "resume": {"status": rstatus, "error": ingest.get("error"),
                   "file": (prof or {}).get("_source_file", ""), "manual": bool((prof or {}).get("_manual"))},
        "claude": {"ready": ready},
        "highlights": highlights(prof),
        "inferred": {"level": guess, "current_employer": emp},
        "market": market_hint(prof, mine or (guess or {}).get("level")),
        "levels": {str(k): v for k, v in _levels().items()},
        "industry_ideas": INDUSTRY_IDEAS,
        "values": {
            "name": people.name(pid),
            "home_zip": s.get("home_zip") or "",
            "radius_miles": s.get("radius_miles") or 35,
            "workplaces": s.get("workplaces") or list(WORKPLACES),
            "remote_us": bool(s.get("remote_us")),
            "current_base": s.get("current_base"),
            "salary_floor": s.get("salary_floor") or None,
            "salary_target": s.get("salary_target"),
            "seniority_mine": mine,
            "band": _band_offsets(mine, s.get("seniority_band")) if mine else [-1, 0, 1],
            "direction": direction,
            "target_text": s.get("target_text") or "",
            "target_scope": s.get("target_scope") or "all",
            "clearance": pr.get("display.clearance", "secret"),
            "travel_max": s.get("travel_max") or "any",
            "skip_employers": raw["skip_employers"] if "skip_employers" in raw else ([emp] if emp else []),
            "skip_industries": s.get("skip_industries") or [],
            "recent_title": recent_title(pid),
            "level_saved": STEPS.index(step) > STEPS.index("level") or bool(s.get("setup_done")),
        },
    }


# ------------------------------------------------------------------ validation
def _int(v, field, lo, hi, label, optional=False):
    if v in (None, ""):
        if optional:
            return None
        raise SetupError(f"Enter {label}.", field)
    try:
        n = int(round(float(str(v).replace(",", "").replace("$", "").strip())))
    except (TypeError, ValueError):
        raise SetupError(f"Use numbers only for {label}.", field)
    if n < lo or n > hi:
        raise SetupError(f"{label[0].upper() + label[1:]} should be between ${lo:,} and ${hi:,}.", field)
    return n

def _money(v, field, label, optional=False):
    """Accepts dollars (150000) or thousands (150 -> 150000)."""
    if v not in (None, ""):
        try:
            f = float(str(v).replace(",", "").replace("$", "").replace("k", "").strip())
            if 0 < f < 2000:
                v = f * 1000
        except ValueError:
            pass
    return _int(v, field, 20000, 2_000_000, label, optional)

def _strlist(v, field, max_items=30, max_len=80):
    if isinstance(v, str):
        v = re.split(r"[\n,;]", v)
    if not isinstance(v, list):
        raise SetupError("Expected a list.", field)
    out, seen = [], set()
    for x in v:
        x = re.sub(r"\s+", " ", str(x)).strip()[:max_len]
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:max_items]

def _bool(v):
    return v is True or str(v).lower() in ("1", "true", "yes", "on")

def validate(step, data):
    """Clean one step's answers. Returns (settings_updates, extra) where extra holds non-settings actions
    ({"name": ...}, {"prefs": {...}}, {"approve_draft": True}). Raises SetupError on bad input."""
    d = data or {}
    if step not in STEPS:
        raise SetupError("Unknown step.")
    up, extra = {}, {}
    if step == "welcome":
        name = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()
        if not name:
            raise SetupError("Tell us what to call you.", "name")
        if len(name) > 40:
            raise SetupError("Keep the name under 40 characters.", "name")
        extra["name"] = name
    elif step == "resume":
        pass  # the upload itself goes through /api/resume; this just records progress (or a skip)
    elif step == "highlights":
        extra["approve_draft"] = True
    elif step == "where":
        if d.get("skipped"):
            return {}, extra   # Skip for now: nothing is saved (the last screen asks for the ZIP if it is still missing)
        z = str(d.get("home_zip") or "").strip()
        if z and not re.fullmatch(r"\d{5}", z):
            raise SetupError("ZIP codes are five digits.", "home_zip")
        try:
            r = int(d.get("radius_miles", 35))
        except (TypeError, ValueError):
            raise SetupError("Pick a distance.", "radius_miles")
        if r not in RADII:
            r = min(RADII, key=lambda x: abs(x - r))
        wp = [w for w in WORKPLACES if w in (d.get("workplaces") or [])]
        if not wp:
            raise SetupError("Pick at least one way of working.", "workplaces")
        if not z and wp != ["remote"]:
            raise SetupError("Add your ZIP so we can measure commutes, or choose remote only.", "home_zip")
        up = {"home_zip": z, "radius_miles": r, "workplaces": wp,
              "remote_us": _bool(d.get("remote_us")) and "remote" in wp}
    elif step == "pay":
        cur = _money(d.get("current_base"), "current_base", "your current base", optional=True)
        floor = _money(d.get("salary_floor"), "salary_floor", "the lowest base you'd take", optional=True)
        floor = max(30000, min(1_000_000, floor)) if floor else 0   # blank: no floor, every job shows
        tgt = _money(d.get("salary_target"), "salary_target", "your target", optional=True)
        if tgt is not None and tgt < floor:
            raise SetupError("Your target should be at or above your floor.", "salary_target")
        up = {"current_base": cur, "salary_floor": floor, "salary_target": tgt}
    elif step == "level":
        if "recent_title" in d:   # asked on the same screen: the most recent job title (the what-to-look-for sheet)
            extra["recent_title"] = re.sub(r"\s+", " ", str(d.get("recent_title") or "")).strip()[:80]
        if d.get("seniority_mine") in ("any", None, "", 0, "0"):   # "Show me every level"
            return {"seniority_mine": None, "seniority_band": [1, 7]}, extra
        try:
            m = max(1, min(7, int(d.get("seniority_mine"))))
        except (TypeError, ValueError):
            raise SetupError("Pick your level, or choose to see every level.", "seniority_mine")
        offs = sorted({int(o) for o in (d.get("band") or []) if str(o).lstrip("-").isdigit() and int(o) in (-1, 0, 1)})
        if not offs:
            raise SetupError("Pick at least one band of jobs to see.", "band")
        lo, hi = max(1, m + min(offs)), min(7, m + max(offs))
        if lo > hi:
            lo = hi = m
        up = {"seniority_mine": m, "seniority_band": [lo, hi]}
    elif step == "direction":
        dr = d.get("direction")
        if dr not in DIRECTIONS:
            raise SetupError("Choose one of the options.", "direction")
        text = str(d.get("target_text") or "").strip()[:2000]
        scope = "ai" if d.get("target_scope") == "ai" else "all"
        if dr == "keep":
            text, scope = "", "all"
        elif not text:
            raise SetupError("Describe what you're aiming for." if dr == "specific" else "Pick one of the suggestions, or describe your own.", "target_text")
        up = {"direction": dr, "target_text": text, "target_scope": scope}
    elif step == "dealbreakers":
        clr = d.get("clearance", "secret")
        if clr not in CLEARANCE:
            raise SetupError("Pick a clearance option.", "clearance")
        tr = d.get("travel_max", "any")
        if tr not in TRAVEL:
            raise SetupError("Pick how much travel is OK.", "travel_max")
        up = {"travel_max": tr, "skip_employers": _strlist(d.get("skip_employers") or [], "skip_employers"),
              "skip_industries": _strlist(d.get("skip_industries") or [], "skip_industries")}
        extra["prefs"] = {"display.clearance": clr}
    elif step == "companies":
        pass  # nothing to choose: employers come from the directory near the person, their own additions and Claude
    elif step in ("questions", "board"):
        pass  # answers go through /api/answers
    return up, extra

def steps_for(claude_ready):
    """The steps this person goes through: every step, minus the ones that need Claude while it isn't connected."""
    return [s for s in STEPS if claude_ready or s not in NEEDS_CLAUDE]

def next_step(step, claude_ready=None):
    live = steps_for(_claude_ready() if claude_ready is None else claude_ready)
    return next((s for s in STEPS[STEPS.index(step) + 1:] if s in live), STEPS[-1])

def save_step(pid, step, data):
    """Validate and save one step; moves the resume point to the following step. Returns the fresh state.
    Raises SetupError (a ValueError) with a friendly message and .field."""
    people.set_current(pid)
    up, extra = validate(step, data)
    if "name" in extra:
        people.rename(pid, extra["name"])
    if extra.get("prefs"):
        people.save_prefs(extra["prefs"], pid=pid)
    if extra.get("approve_draft"):
        _, draft = _profiles(pid)
        if draft:
            import resume
            resume.approve({})
    if "recent_title" in extra and extra["recent_title"] != recent_title(pid):
        import lookfor
        lookfor.edit(pid, {"recent": extra["recent_title"]})
    s = _settings(pid)
    # Don't move the resume point backwards when someone goes Back and re-saves an earlier screen.
    nxt = next_step(step)
    cur = s.get("setup_step") if s.get("setup_step") in STEPS else "welcome"
    up["setup_step"] = nxt if STEPS.index(nxt) > STEPS.index(cur) or s.get("setup_done") else cur
    _write(pid, up)
    return get_state(pid)

def goto(pid, step):
    """Record where the person is (Back / jumping via the dots) without validating anything."""
    if step not in STEPS:
        raise SetupError("Unknown step.")
    _write(pid, {"setup_step": step})

def goals_text(s):
    """Plain sentence summary of the setup answers, appended to the free-text goals Claude reads when scoring."""
    bits = []
    wp = s.get("workplaces") or []
    if wp:
        where = "/".join({"onsite": "on-site", "hybrid": "hybrid", "remote": "remote"}[w] for w in wp)
        commute = f" within {s.get('radius_miles')} miles of ZIP {s['home_zip']}" if s.get("home_zip") and wp != ["remote"] else ""
        bits.append(f"Open to {where} work{commute}" + (", remote anywhere in the US" if s.get("remote_us") else "") + ".")
    if s.get("salary_target") and s.get("salary_floor"):
        bits.append(f"Target base ${s['salary_target']:,}; floor ${s['salary_floor']:,}.")
    elif s.get("salary_target"):
        bits.append(f"Target base ${s['salary_target']:,}.")
    if s.get("travel_max") and s["travel_max"] != "any":
        bits.append({"none": "Wants no travel.", "light": "Light travel at most (under ~10%).",
                     "moderate": "Travel up to ~25% at most."}[s["travel_max"]])
    if s.get("skip_employers"):
        bits.append("Skip these employers: " + ", ".join(s["skip_employers"]) + ".")
    if s.get("skip_industries"):
        bits.append("Not interested in: " + ", ".join(s["skip_industries"]) + ".")
    return " ".join(bits)

def finish(pid):
    """Mark setup done and tell the server what to start. Returns
    {"ok", "kick": {"interpret_target": bool, "update": bool}, "settings": {...}}."""
    people.set_current(pid)
    s = _settings(pid)
    _, draft = _profiles(pid)
    if draft:
        import resume
        resume.approve({})
    active, _ = _profiles(pid)
    summary = goals_text(s)
    goals = s.get("goals") or ""
    marker = "Setup answers: "
    goals = re.sub(re.escape(marker) + r".*$", "", goals, flags=re.S).rstrip()
    if summary:
        goals = (goals + "\n\n" if goals else "") + marker + summary
    raw = _write(pid, {"setup_done": True, "setup_step": "board", "goals": goals,
                       "pivot_ai": bool((s.get("target_text") or "").strip())})
    return {"ok": True, "has_profile": bool(active),
            "kick": {"interpret_target": bool((s.get("target_text") or "").strip()), "update": True},
            "settings": {**SETUP_DEFAULTS, **people._with_defaults(raw)}}

def start(pid):
    """Call right after people.add(): marks the new profile as needing setup."""
    _write(pid, {"setup_done": False, "setup_step": "welcome"})

def needs_setup(pid):
    """True when / should send this profile to /setup: a profile created after start(), not yet finished.
    Profiles from before the setup flow (no setup_done key) count as set up once they have a resume profile."""
    raw = _raw(pid)
    if "setup_done" in raw:
        return not raw["setup_done"]
    return not os.path.exists(people.pdir("profile.json", pid=pid))
