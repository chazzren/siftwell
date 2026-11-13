#!/usr/bin/env python3
"""Siftwell job finder: pull jobs from company ATS feeds, keep roles near the person (home radius) + US-remote roles,
filter by title/salary, score against resume profile, and write data/jobs.json, jobs.csv, report.html.

Usage:  python3 jobfinder.py            # full refresh
        python3 jobfinder.py --only Leidos,Anduril
"""
import argparse, concurrent.futures as cf, csv, datetime as dt, html, json, os, re, sys, time
import osdeps
import urllib.request, urllib.error

import paths
HERE, DATA = paths.APP, paths.DATA
UA = "Mozilla/5.0 (Siftwell personal job search)"
CFG = paths.load_config()

import copy
import people
import jobtext
BASE_CFG = copy.deepcopy(CFG)

def _user_cfg():
    """The household's own DATA/config.json as written (no shipped defaults), or {}."""
    try:
        d = json.load(open(paths.CONFIG, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}
USER_CFG = _user_cfg()

# What config.default.json used to ship. Nothing new gets these: a title filter now comes only from the person's own
# job titles. Profiles from before that rule (settings "title_rule": "builtin") keep them, unless the household's own
# config.json sets the list itself, so their boards show the same jobs as before.
LEGACY_TITLE_INCLUDE = ["engineer", "developer", "architect", "analyst", "scientist", "designer", "manager", "director",
                        "head of", "lead", "principal", "staff", "senior", "consultant", "specialist", "advisor",
                        "strategist", "coordinator", "administrator", "officer", "associate", "representative", "nurse",
                        "teacher", "accountant", "operations", "program", "project", "product", "marketing", "sales",
                        "customer", "support", "finance", "chief"]
LEGACY_TITLE_EXCLUDE = ["intern", "internship", "co-op", "new grad"]
LEGACY_SENIOR_WORDS = ["senior", "sr.", "sr ", "staff", "principal", "lead", "manager", "director", "head", "architect"]

def rate_limits(pr, auto=True):
    """This person's per-run rating limits from their Settings, never above ai_score.RUN_LIMITS. auto: an automatic
    run (after an update, the nightly re-rate), which does nothing when they turned automatic rating off."""
    import ai_score
    L = ai_score.RUN_LIMITS
    on = bool(pr["claude.auto_rate"]) or not auto
    n = lambda k, cap: max(0, min(cap, int(pr[k] or 0))) if on else 0
    return {"haiku": n("claude.haiku_per_night", L["haiku"]), "sonnet_pct": n("claude.sonnet_pct", 100),
            "sonnet_max": L["sonnet"] if on else 0, "opus_top": n("claude.opus_top", 1000),
            "opus_max": L["opus"] if on else 0, "target": n("claude.per_update", L["target"])}

def person_cfg(pid):
    """Config for one person: base config + their settings + keywords from their approved resume profile."""
    c = copy.deepcopy(BASE_CFG)
    st = people.settings(pid)
    c["salary_floor"] = int(st.get("salary_floor") or 0)
    c["salary_target"] = int(st["salary_target"]) if st.get("salary_target") else None
    c["seniority"] = {"mine": st.get("seniority_mine"), "band": st.get("seniority_band") or [1, 7]}
    pr = people.prefs(pid)
    lim = rate_limits(pr)
    c["ai"]["max_new_per_run"] = lim["target"]
    c["funnel"] = {k: lim[k] for k in ("haiku", "sonnet_pct", "sonnet_max", "opus_top", "opus_max")}
    c["pivot"]["max_new_per_run"] = lim["target"]
    if st.get("title_rule") == "builtin":  # a profile from before "only your own job titles": same words as it had
        if "title_include" not in USER_CFG:
            c["title_include"] = sorted(set(c["title_include"]) | set(LEGACY_TITLE_INCLUDE))
        if "title_exclude" not in USER_CFG:
            c["title_exclude"] = list(dict.fromkeys(c["title_exclude"] + LEGACY_TITLE_EXCLUDE))
        if "senior_title_words" not in USER_CFG:
            c["senior_title_words"] = list(LEGACY_SENIOR_WORDS)
    c["pivot_enabled"] = people.target_on(st)
    c["targets"] = [st] if c["pivot_enabled"] else []
    # Where to look: a home ZIP + radius when the person has set one; otherwise the original DC-area place list.
    c["homes"], c["legacy_area"] = [], True
    if st.get("home_zip"):
        try:
            import geo
            h = geo.geocode_home(str(st["home_zip"]))
            if h:
                c["homes"], c["legacy_area"] = [(h, float(st.get("radius_miles") or 35))], False
        except Exception as e:
            print(f"home location '{st['home_zip']}' not understood ({e}); using the DC-area list", flush=True)
    c["remote_ok"] = bool(st.get("remote_us", True)) and "remote" in (st.get("workplaces") or ["remote"])
    c["workplaces"] = st.get("workplaces") or ["onsite", "hybrid", "remote"]
    try:
        prof = json.load(open(people.pdir("profile.json", pid=pid)))
    except Exception:
        prof = None
    if prof:
        inc = set(c["title_include"])
        for k in prof.get("title_keywords", []) + [r.lower() for r in prof.get("target_roles", [])]:
            k = k.lower().strip()
            if k and not excluded_words(k, c["title_exclude"]):
                inc.add(k)
        c["title_include"] = sorted(inc)
        for k in prof.get("fit_keywords", []):
            c["fit_keywords"].setdefault(k.lower().strip(), 8)
    # The what-to-look-for sheet (lookfor.py) feeds the title filter the way the person's own titles do, as whole
    # words: other names for their job and related roles pass too. A profile still on the earlier built-in word list
    # keeps exactly the filter it had; only titles the person adds to the sheet themselves are added to it.
    c["title_words"] = []
    try:
        import lookfor
        sheet = lookfor.ensure(pid, prof)
        c["title_words"] = [w for w in lookfor.title_phrases(sheet, own_only=st.get("title_rule") == "builtin")
                            if not excluded_words(w, c["title_exclude"])]
    except Exception as e:
        print(f"what-to-look-for sheet skipped for {pid}: {type(e).__name__}: {e}", flush=True)
    if st.get("title_rule") != "builtin":
        # very short title words ("RN", "PA", "IT") only make sense as whole words: anywhere-in-the-title matching
        # would let "rn" pass Intern, Journeyman and Government
        short = [w for w in c["title_include"] if len(w.strip()) <= 3]
        if short:
            c["title_include"] = [w for w in c["title_include"] if w not in short]
            c["title_words"] = sorted(set(c["title_words"]) | {w.strip() for w in short if w.strip()})
    return c, prof, st

def use_cfg(c):
    CFG.clear(); CFG.update(copy.deepcopy(c))

def fetch_cfg(cfgs):
    """Loose filter for the shared fetch: anything any person could want."""
    c = copy.deepcopy(BASE_CFG)
    if cfgs:
        # someone with no title words takes every title, so the shared fetch must too (an empty list passes everything)
        named = sorted(set().union(*(x["title_include"] for x in cfgs)))
        words = sorted(set().union(*(x.get("title_words") or [] for x in cfgs)))
        open_any = any(not x["title_include"] and not x.get("title_words") for x in cfgs)
        c["title_include"], c["title_words"] = ([], []) if open_any else (named, words)
        # The titles somebody actually names (their own title words or their what-to-look-for sheet), whether or not
        # someone else takes every title: Workday full text is fetched up front only for these (fetch_wanted).
        c["fetch_include"], c["fetch_words"] = named, words
        c["title_exclude"] = [w for w in cfgs[0]["title_exclude"] if all(w in x["title_exclude"] for x in cfgs)]
        c["salary_floor"] = min(x["salary_floor"] for x in cfgs)
        c["pivot_enabled"] = any(x.get("pivot_enabled") for x in cfgs)
        c["targets"] = [t for x in cfgs for t in x.get("targets", [])]
        c["homes"] = [h for x in cfgs for h in x.get("homes", [])]
        c["legacy_area"] = any(x.get("legacy_area", True) for x in cfgs)
    return c

def target_title_ok(st, title):
    """Does this title fit a person's target? Open targets take anything that isn't junk (internships, trades...)."""
    t = " " + title.lower() + " "
    if st.get("target_any_title"):
        allow = CFG.get("pivot", {}).get("title_allow", [])
        if any(not any(a in t for a in allow if x in a or a in x) for x in excluded_words(title, CFG["title_exclude"])):
            return False
        return not any(re.search(rx, title.lower().strip()) for rx in CFG["title_exclude_regex"])
    kws = st.get("target_keywords") or []
    if kws:
        return any(k in t for k in kws) and not any(re.search(rx, title.lower().strip()) for rx in CFG["title_exclude_regex"])
    return bool(st.get("target_scope") == "ai") and pivot_title_ok(title)  # not interpreted yet: old AI-pivot filter

def target_ok(st, ai_track, title):
    if st.get("target_scope") == "ai" and not ai_track:
        return False
    return target_title_ok(st, title)


# ---------------------------------------------------------------- http
import threading
_WD_SEM = threading.Semaphore(4)  # Workday shares one rate limit per IP across tenants

def http_json(url, body=None, tries=6):
    if "myworkdayjobs.com" in url:
        with _WD_SEM:
            r = _http_json(url, body, tries)
            time.sleep(0.15)
            return r
    return _http_json(url, body, tries)

def _http_json(url, body=None, tries=6):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    if data:
        hdr["Content-Type"] = "application/json"
    import netsafe
    for i in range(tries):
        try:
            with netsafe.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=30) as r:
                return json.loads(r.read())
        except netsafe.UnsafeURL:
            raise  # (refused: not worth retrying)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                ra = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(ra) if ra and ra.isdigit() else min(30, 3 * 2 ** i)); continue
            raise
        except Exception:
            if i < tries - 1:
                time.sleep(1.5 * (i + 1)); continue
            raise

def strip_html(s):
    if not s:
        return ""
    s = html.unescape(html.unescape(s))
    s = re.sub(r"<(br|/p|/div|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return jobtext.clean_text(re.sub(r"[ \t\xa0]+", " ", s))   # (runs of blank lines become one)

# ---------------------------------------------------------------- classification
NON_US = ["canada", "toronto", "vancouver", "montreal", "united kingdom", " uk", "uk ", "london", "ireland", "dublin",
          "germany", "berlin", "munich", "france", "paris", "spain", "madrid", "netherlands", "amsterdam", "poland",
          "india", "bangalore", "bengaluru", "hyderabad", "pune", "singapore", "japan", "tokyo", "australia", "sydney",
          "brazil", "mexico", "argentina", "colombia", "israel", "tel aviv", "emea", "apac", "europe", "latam",
          "korea", "taiwan", "philippines", "costa rica", "romania", "portugal", "sweden", "denmark", "switzerland",
          "italy", "czech", "serbia", "ukraine", "new zealand", "south africa", "uae", "dubai", "saudi", "qatar"]
REMOTE_WORDS = ["remote", "anywhere", "virtual", "telework", "work from home", "wfh"]

def is_foreign(loc, states=None):
    """Does this location label name a place outside the US? Whole words, and a town with its own US state is US:
    "Dublin, Ireland" yes; "Dublin, OH", "Indianapolis, IN", "Paris, TX", "New Mexico" no; "Utrecht, UT" (no such town
    in Utah) yes. states: the US states the employer is known to hire in, which settle a foreign city written alone
    ("Dublin" at an Ohio employer). (NON_US above is kept for readers that import it; geo holds the full list.)"""
    import geo
    return geo.looks_foreign(loc, states)

def near(loc, states=None):
    """Is this location inside anyone's search area (the current CFG): a home radius, or the DC-area list.
    states: the states there is evidence for when the label is a bare city name ("Columbus"); see bare_support()."""
    if CFG.get("legacy_area", True) and is_close(loc):
        return True
    if CFG.get("homes"):
        import geo
        return any(geo.within([loc], h, r, states=states)[0] for h, r in CFG["homes"])
    return False

class EmployerPlaces:
    """Where each employer is known to hire, for placing a bare city name ("Columbus", "Columbus Healthcare Center"):
    the places its other postings name with their state, and the places and states the employer directory lists.
    Built lazily, one employer at a time."""
    def __init__(self, pool, places=None):
        self.locs, self.dir, self.done, self._dir_st = {}, places or {}, {}, None
        for j in pool:
            self.locs.setdefault(j["company"], set()).update(l for l in (j.get("locations") or []) if l)

    def dir_states(self):
        if self._dir_st is None:
            try:
                import catalog
                self._dir_st = catalog.dir_states_map()
            except Exception:
                self._dir_st = {}
        return self._dir_st

    def of(self, company):
        """({place name key: {states}}, {states}) for one employer."""
        got = self.done.get(company)
        if got is None:
            import geo
            city, sts = {}, set()
            for l in self.locs.get(company, ()):
                for nm, st in geo.place_states(l):
                    sts.add(st)
                    if nm:
                        city.setdefault(nm, set()).add(st)
            sts.update((self.dir.get(company) or {}).get("states") or [])
            sts.update(self.dir_states().get(company) or [])
            got = self.done[company] = (city, sts)
        return got

_BARE = {}

def bare_support(loc, job, emp):
    """The states a location label's bare city names may be placed in, or None when the label has none (then nothing
    changes). A bare name ("Columbus" exists in Ohio, Georgia, Indiana...) is accepted only with support, in order:
    one state the posting itself names (its text or its other location labels), one state where this employer's
    other postings (or the directory) put a town of that name, one state the employer is known to hire in.
    When nothing points at any of the namesakes (no state that has a town of this name is named by the posting, by
    the employer's other postings or by the directory), every namesake is allowed: the caller only looks inside the
    person's own area, so the name counts when a town of that name is there ("Bowie" at an employer otherwise seen
    in Florida and Pennsylvania, for someone near Bowie, MD) and does nothing otherwise.
    With evidence for a namesake elsewhere, or for several namesakes at once, the name is placed there or stays
    unplaced (an empty set; the posting is then treated like any other posting that names no place): "Columbus" at
    an employer known in Georgia never lands on an Ohio board."""
    import geo
    names_ = _BARE.get(loc)
    if names_ is None:
        if len(_BARE) > 200000:
            _BARE.clear()
        names_ = _BARE[loc] = geo.bare_names(loc)
    if not names_:
        return None
    own = set(job.get("loc_st") or [])
    for l in job.get("locations") or []:
        if l and l != loc:
            own.update(st for _, st in geo.place_states(l))
    out = set()
    for name, opts in names_:
        cand = set(opts)
        mine = own & cand
        if len(mine) == 1:
            out |= mine
            continue
        city, sts = emp.of(job["company"])
        pool_ = mine or cand
        same = city.get(geo._key(name), set()) & pool_
        if len(same) == 1:
            out |= same
        elif not same and len(sts & pool_) == 1:
            out |= sts & pool_
        elif not (own | sts) & cand:
            out |= cand
    return out

def is_close(loc):
    l = " " + loc.lower() + " "
    if any(p in l for p in CFG["close_places"]):
        return True
    has_va = bool(re.search(r"\bva\b|virginia", l))
    return has_va and any(re.search(r"\b" + p + r"\b", l) for p in CFG["close_places_need_va"])

def is_remote_us(loc):
    """A location label that says the job is remote and names no other country ("Remote", "US - Remote"; never
    "Not Remote", "Remote: No", "Remote, Poland", "Remote, PL")."""
    if not jobtext.remote_label(loc):
        return False
    return not is_foreign(loc) and not jobtext.foreign_remote(loc)

# ---- title excludes are whole words: "intern" drops "Marketing Intern" and "Summer Interns", never "Internal Auditor",
# "Internal Medicine" or "International Sales Manager". A plural "s"/"es" still counts, and an entry ending in "*" is a
# word beginning ("recruit*" also drops Recruiter and Recruiting).
# One exception keeps older households working: entries hand-written in a DATA/config.json from before this rule are
# matched the old way (anywhere in the title, their spaces kept), because such lists rely on it ("recruit", "tax ").
# Only the words Siftwell itself ever shipped (WORD_EXCLUDES) are whole words there. Add "title_match": "word" to that
# config.json to use whole words for everything.
WORD_EXCLUDES = {"intern", "interns", "internship", "internships", "co-op", "co-ops", "new grad", "new grads"}
OLD_EXCLUDE_MATCH = "title_exclude" in USER_CFG and USER_CFG.get("title_match") != "word"
_EXCL_RX = {}

def _excl_rx(word):
    rx = _EXCL_RX.get(word)
    if rx is None:
        w = word.strip().lower()
        stem = w.endswith("*")
        w = w.rstrip("*").strip()
        body = r"\s+".join(re.escape(p) for p in w.split())
        if w == "new grad":
            body += r"(?:uate)?"   # "New Graduate" was always covered by this entry
        rx = _EXCL_RX[word] = re.compile(r"(?<![a-z0-9])" + body + (r"" if stem else r"(?:e?s)?(?![a-z0-9])")) if w else False
    return rx

def excluded_words(title, words=None):
    """The exclude entries that this title trips (empty list: the title is fine)."""
    words = CFG["title_exclude"] if words is None else words
    low = (title or "").lower()
    padded = " " + low + " "
    out = []
    for x in words:
        if OLD_EXCLUDE_MATCH and x.strip().lower() not in WORD_EXCLUDES:
            hit = x in padded
        else:
            rx = _excl_rx(x)
            hit = bool(rx and rx.search(low))
        if hit:
            out.append(x)
    return out

US_STATES = ("alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
             "kentucky|louisiana|maine|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
             "new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|"
             "tennessee|texas|utah|vermont|west virginia|wisconsin|wyoming")
ELSEWHERE = re.compile(r"\b(" + US_STATES + r")\b|,\s*(?!dc\b|va\b|md\b)[a-z]{2}\b(?:\s|$|,)", re.I)

def looks_local_unnamed(loc):
    """A location label that names no other state or country ("Main Campus", "125 E St NW 1st Floor")."""
    l = (loc or "").strip().lower()
    return bool(l) and not ELSEWHERE.search(l) and not is_foreign(loc) and "remote" not in l

def _names_foreign(l):
    import geo
    fn = getattr(geo, "looks_foreign", None)
    if fn:
        return bool(fn(l))
    return bool(geo.FOREIGN_CODES.search(l or "")) or any(c in " " + (l or "").lower() + " " for c in NON_US)

def vague_location(l, emp_states=()):
    """A posting location that names no place Siftwell can put on a map: empty, "Main Office", "Headquarters",
    "Statewide", "Multiple Locations - OH". A state only counts when it is one the employer is known to hire in
    (emp_states); remote and foreign labels are never vague."""
    l = (l or "").strip()
    if not l:
        return True
    low = " " + l.lower() + " "
    if jobtext.remote_label(l) or _names_foreign(l):
        return False
    import geo
    hits = [h for h in geo.locate_all(l) if h.kind != "bare"]   # (a bare city name nobody could place names no place)
    if any(h.kind != "state" for h in hits):
        return False
    if hits:   # state only: fine when the employer hires in that state
        return all(geo.STATE_WORDS.get(h.label.lower(), h.label) in emp_states for h in hits)
    return True

def employer_all_near(info, homes):
    """True when every place the directory knows the employer hires is within some home's radius (then a posting that
    names no place is almost surely local). info: a catalog.places_map() entry."""
    import geo
    if not info or not homes or not info.get("places") or not info.get("all"):
        return False
    return all(any(geo.miles(h[0], h[1], p[0], p[1]) <= r for h, r in homes) for p in info["places"])

def title_ok(title):
    """The title filter: no excluded word, and one of the person's own title words. With no title words at all (no
    job titles on their profile yet), every title passes: there is no built-in vocabulary."""
    t = " " + title.lower() + " "
    if excluded_words(title):
        return False
    if any(re.search(rx, title.lower().strip()) for rx in CFG["title_exclude_regex"]):
        return False
    return _named(t, CFG["title_include"], CFG.get("title_words"), open_ok=True)

_TW = {"src": None, "rx": None}

def _words_rx(words):
    """The whole-word pattern for the sheet's title phrases (compiled once per list)."""
    if _TW["src"] is not words:
        import lookfor
        _TW["src"], _TW["rx"] = words, lookfor.phrase_regex(words or [])
    return _TW["rx"]

def _named(padded_title, include, words, open_ok=False):
    """Is this title (lower case, padded with spaces) named by the title words (anywhere in the title, as always) or
    the sheet's phrases (whole words)? With neither list: open_ok (no titles given = every title passes)."""
    if not include and not words:
        return open_ok
    if any(x in padded_title for x in include):
        return True
    rx = _words_rx(words) if words else None
    return bool(rx and rx.search(padded_title))

def pivot_title_ok(title):
    """Wider title filter for AI companies: adds go-to-market, policy, threat intel and trust & safety titles."""
    pv = CFG.get("pivot", {})
    t = " " + title.lower() + " "
    allow = pv.get("title_allow", [])
    if any(not any(a in t for a in allow if x in a or a in x) for x in excluded_words(title)):
        return False
    if any(re.search(rx, title.lower().strip()) for rx in CFG["title_exclude_regex"]):
        return False
    return _named(t, CFG["title_include"] + (pv.get("title_extra", []) if CFG["title_include"] or CFG.get("title_words") else []),
                  CFG.get("title_words"), open_ok=True)

def parse_salary(text):
    """The posting's base pay as (low, high, the words it was read from, unit, low in that unit, high in that unit),
    low and high per year (hourly pay at 2,080 hours) so every job compares on one scale. None when the text states
    no pay. See jobtext.parse_pay for what counts (hourly, single values) and what doesn't (bonuses, 401k)."""
    p = jobtext.parse_pay(text)
    if not p:
        return None
    return (p["lo"] * jobtext.PER_YEAR[p["unit"]], p["hi"] * jobtext.PER_YEAR[p["unit"]], p["text"], p["unit"], p["lo"], p["hi"])

CLEAR_PATTERNS = [
    ("TS/SCI + poly", r"(ts\s*/\s*sci|top secret/sci|top secret / sci)[^.\n]{0,60}(poly|polygraph)"),
    ("TS/SCI", r"ts\s*/\s*sci|top secret/sci|top secret / sci|\bsci\b eligib"),
    ("Top Secret", r"top secret"),
    ("Secret", r"\bsecret clearance|\bactive secret|\bsecret\b(?: security)? clearance|clearance level:? secret"),
    ("Public Trust", r"public trust"),
    ("Clearance (unspecified)", r"security clearance|clearance required|cleared"),
]
def clearance(text):
    t = (text or "").lower()
    for label, rx in CLEAR_PATTERNS:
        if re.search(rx, t):
            return label
    return ""

def workplace_from_text(text):
    t = (text or "").lower()
    if re.search(r"\bscif\b", t):
        return "onsite"
    if re.search(r"\bhybrid\b", t):
        return "hybrid"
    if re.search(r"\b(on-site|onsite|in-office|in office)\b", t):
        return "onsite"
    return ""

def combine(job):
    """Best bets: high on both Appeal and Match (geometric mean, so one weak side pulls it down)."""
    import math
    if "appeal" not in job:
        appeal(job)
    m = job["ai_fit"] if job.get("ai_fit") is not None else unrated_match(job)
    job["score"] = round(math.sqrt(max(0, job["appeal"]) * max(0, m)))

def unrated_match(job):
    """What stands in for Match in Best bets until Claude has rated a job: its free Relevance (lookfor.py), scaled to
    20-55 (UNRATED_MIN - UNRATED_MAX). The board still shows no Match for it: this number only places it.

    The rule: a job nobody has rated never outranks a rated job that is both well matched (Match 70 or more) and
    reasonably appealing (Appeal 80 or more). Best bets is sqrt(Appeal x Match), so the best an unrated job can do is
    sqrt(100 x 55) = 74, and the weakest such rated job scores sqrt(80 x 70) = 75. Below that line a very relevant
    unrated job may sit above a rated one that Claude found a poor match, which is the point of showing it. A job
    that has nothing to do with the person's work sinks (20). No sheet yet (Relevance unknown): 50, as before."""
    rel = job.get("rel")
    return 50 if rel is None else UNRATED_MIN + rel * (UNRATED_MAX - UNRATED_MIN) / 100

UNRATED_MIN, UNRATED_MAX = 20, 55

def board_order(j):
    """Best bets order, the same in every version: the score, then the better Match (an unrated job after rated ones),
    then the better Appeal, then the job id. Ties never depend on the order listings happened to arrive in."""
    m = j.get("ai_fit")
    return (-j["score"], -(m if m is not None else -1), -j.get("appeal", 0), str(j["id"]))

# ---------------------------------------------------------------- salary bands
WIDE_BAND_RATIO = 1.6   # top / bottom at or above this: the band spans several levels, so the top means little
JUNK_BAND_RATIO = 4.0   # above this the parse is almost surely wrong (e.g. "$20 to $200")

def band(job):
    """Adds salary_mid (what pay is scored on), wide_band, and drops nonsense ranges."""
    lo, hi = job.get("salary_min"), job.get("salary_max")
    job["wide_band"] = False
    job["salary_mid"] = None
    if lo is None or hi is None:
        return
    if lo <= 0 or hi / lo > JUNK_BAND_RATIO:
        job["salary_min"] = job["salary_max"] = job["pay_min"] = job["pay_max"] = None
        job["salary_text"] = job["pay_unit"] = ""
        return
    job["salary_mid"] = round((lo + hi) / 2)
    job["wide_band"] = hi / lo >= WIDE_BAND_RATIO

# ---------------------------------------------------------------- travel
TRAVEL_NOISE = re.compile(r"commut|travel (?:stipend|reimburse|insurance|assistance|allowance|perks?|the world|benefit)"
                          r"|intra-office travel|team travel|business travel accident|travel(?:ling)? the world|time travel|travel nurse", re.I)
TRAVEL_NONE = re.compile(r"\bno travel\b|travel(?: required| requirements?)?\s*[:\-–]\s*(?:none|no\b|not required|0\s?%)|\b0\s?% travel|travel is not required|no travel required", re.I)
TRAVEL_HEAVY = re.compile(r"travel[- ]intensive|extensive travel|frequent travel|significant travel|heavy travel|travel (?:extensively|frequently)|multi-week deployments|majority of (?:the )?time traveling", re.I)
TRAVEL_SOME = re.compile(r"(?:willing(?:ness)?|able|ability|required|requires?|expected|may need|must be able|excited) to travel|travel (?:is |will be |may be )?required|travel (?:to|as) (?:client|customer|needed|required)|occasional travel|some travel|domestic travel|international travel|travel up to|travel requirements?", re.I)
PCT = re.compile(r"(\d{1,3})\s?%(?:\s?(?:-|–|to)\s?(\d{1,3})\s?%)?|(\d{1,3})\s?(?:-|–|to)\s?(\d{1,3})\s?%")

def travel(text):
    """Returns (level, pct, phrase). level: '' (not mentioned), none, light, moderate, heavy, some (amount not stated)."""
    t = re.sub(r":[ \t]*\n\s*", ": ", text or "")  # "Travel Required:\nUp to 10%" -> one line
    best_pct, phrase, saw_some, heavy, none = None, "", False, False, False
    for m in re.finditer(r"[^.\n;]{0,90}\btravel[^.\n;]{0,90}", t, re.I):
        seg = m.group(0)
        if TRAVEL_NOISE.search(seg):
            continue
        if TRAVEL_NONE.search(seg):
            none = True; phrase = phrase or seg.strip(); continue
        if TRAVEL_HEAVY.search(seg):
            heavy = True; phrase = seg.strip()
        for pm in PCT.finditer(seg):
            nums = [int(x) for x in pm.groups() if x]
            v = max(nums)
            if 0 < v <= 100 and (best_pct is None or v > best_pct):
                best_pct, phrase = v, seg.strip()
        if TRAVEL_SOME.search(seg):
            saw_some = True; phrase = phrase or seg.strip()
    phrase = re.sub(r"\s+", " ", phrase)[:160]
    if best_pct is not None:
        lvl = "heavy" if best_pct >= 25 else "moderate" if best_pct > 10 else "light"
        if heavy and lvl != "heavy":
            lvl = "heavy"
        return lvl, best_pct, phrase
    if heavy:
        return "heavy", None, phrase
    if saw_some:
        return "some", None, phrase
    if none:
        return "none", 0, phrase
    return "", None, ""

# ---------------------------------------------------------------- seniority
# (the level readers live in jobtext.py; these names are kept for the modules that use them from here)
IC_MANAGER, LEVEL_NAMES = jobtext.IC_MANAGER, jobtext.LEVEL_NAMES
title_level, years_required, years_level, seniority, YEARS = (jobtext.title_level, jobtext.years_required, jobtext.years_level,
                                                             jobtext.seniority, jobtext.YEARS)

TRAVEL_QOL = {"heavy": -20, "moderate": -10, "some": -5, "light": -3, "none": 0, "": 0}

def enrich(job, text):
    """Everything derived from the posting text, after salary parsing."""
    band(job)
    if not job.get("workplace"):
        job["workplace"] = workplace_from_text(text)
    job["clearance"] = clearance(text)
    job["scif"] = bool(re.search(r"\bscif\b", (text or "").lower()))
    job["travel"], job["travel_pct"], job["travel_text"] = travel(text)
    job["level"], job["level_src"] = jobtext.seniority(job["title"], text)
    try:
        import requirements
        job["req"] = requirements.parse(text or "", job["title"])
    except Exception:
        job["req"] = None

def score(job):
    text = (job["title"] + " " + job["title"] + " " + job.get("desc", "")).lower()
    fit = sum(w for k, w in CFG["fit_keywords"].items() if k in text)
    if any(w in (" " + job["title"].lower() + " ") for w in CFG["senior_title_words"]):
        fit += 10
    if job["clearance"] == "TS/SCI + poly":
        fit -= 15
    fit = max(0, min(100, fit))
    # Pay is scored on the middle of the band (what an offer usually lands near), not the top.
    mid = job.get("salary_mid")
    comp = 50 if mid is None else max(0, min(100, 50 + (mid - CFG["salary_floor"]) / 2000))
    if job.get("wide_band"):
        comp -= 5  # the posting tells you little; small nudge below an equally-centred honest band
    qol = {"remote": 100, "hybrid": 70, "": 55, "onsite": 40}.get(job.get("workplace") or "", 55)
    if job["clearance"] in ("TS/SCI + poly", "TS/SCI", "Top Secret"):
        qol -= 15  # usually SCIF / on-site
    qol += TRAVEL_QOL.get(job.get("travel", ""), 0)
    job["fit_score"], job["comp_score"], job["qol_score"] = round(fit), round(max(0, comp)), round(max(0, qol))
    appeal(job)
    combine(job)

_FACTS = {}
def company_facts():
    if not _FACTS:
        try:
            _FACTS.update(json.load(open(os.path.join(DATA, "company_facts.json"))))
        except Exception:
            _FACTS["__none__"] = {}
    return _FACTS

def appeal(job):
    """Appeal: how well the job gives this person what they want, from facts alone (no Claude, so every job gets one).
    40% pay vs floor/target, 20% workplace & distance, 15% level, 15% company, 10% travel/clearance burden."""
    mid, floor = job.get("salary_mid"), CFG["salary_floor"]
    target = CFG.get("salary_target") or None
    if mid is None:
        pay = 50
    else:
        # With a pay floor: every $2,000 above it is a point (unchanged). With no floor that rule tops out near
        # $100k and calls every hourly job poor, so pay is placed within the spread of pay on this person's own
        # board instead: the middle of their board is 50, the best-paid jobs they see are near 100.
        pay = 50 + (mid - floor) / 2000 if floor > 0 else pay_rank(mid)
        if target and mid >= target:
            pay += 10
    if job.get("wide_band"):
        pay -= 5
    wp = {"remote": 100, "hybrid": 75, "onsite": 55}.get(job.get("workplace") or "", 60)
    nm = job.get("near_miles")
    if nm is not None and job.get("workplace") != "remote" and nm > 20:
        wp -= min(20, (nm - 20) / 1.5)
    L, sen = job.get("level"), CFG.get("seniority") or {}
    band, mine = sen.get("band") or [1, 7], sen.get("mine")
    # (no level chosen yet: every level counts the same)
    lvl = 75 if L is None or not mine else 100 if L == mine else 85 if band[0] <= L <= band[1] else 55
    c = company_facts().get(job["company"]) or {}
    g, n = c.get("gd_rating"), c.get("gd_reviews") or 100
    if g is None:
        comp = 65
    else:
        w = (g * n + 3.7 * 50) / (n + 50)
        comp = 40 + (w - 3.0) * 40
    lay = (c.get("layoffs") or "").lower()
    if lay and not lay.startswith(("none", "no ")):
        comp -= 10
    burden = 100 + TRAVEL_QOL.get(job.get("travel", ""), 0) * 2
    if job["clearance"] in ("TS/SCI + poly", "TS/SCI", "Top Secret"):
        burden -= 25
    clip = lambda v: max(0, min(100, v))
    parts = {"pay": round(clip(pay)), "place": round(clip(wp)), "level": round(clip(lvl)), "company": round(clip(comp)), "burden": round(clip(burden))}
    job["appeal_parts"] = parts
    job["appeal"] = round(0.40 * parts["pay"] + 0.20 * parts["place"] + 0.15 * parts["level"] + 0.15 * parts["company"] + 0.10 * parts["burden"])

# Used when a board lists pay on too few jobs to have a spread of its own: rough US full-time pay, 10th to 95th percentile.
US_PAY_SPREAD = [30000, 36000, 42000, 48000, 55000, 62000, 72000, 85000, 105000, 135000, 170000]
MIN_SPREAD = 12   # jobs with pay listed before a board's own spread is used

def set_pay_spread(jobs):
    """Remember the spread of pay on the current person's board (CFG is theirs) for the Appeal pay part."""
    mids = sorted(j["salary_mid"] for j in jobs if j.get("salary_mid"))
    CFG["pay_spread"] = mids if len(mids) >= MIN_SPREAD else list(US_PAY_SPREAD)

def pay_rank(mid):
    """0-100: where this pay sits in the spread (the share of jobs paying less, ties counted half)."""
    import bisect
    sp = CFG.get("pay_spread") or US_PAY_SPREAD
    return 100 * (bisect.bisect_left(sp, mid) + bisect.bisect_right(sp, mid)) / (2 * len(sp))

# ---------------------------------------------------------------- fetchers (each yields normalized dicts)
def J(company, title, url, locations, workplace="", salary=None, desc="", posted="", dept="", jid=""):
    # The id starts with the name the company had when its first posting was stored ("idp", kept by
    # catalog.rename_company), so giving a company a better display name never changes a listing's id: ratings,
    # saved marks and first-seen dates are all keyed by it.
    return {"company": company["name"], "sector": company.get("sector", ""), "tier": company.get("tier", ""),
            "title": jobtext.clean_title(title), "url": url, "locations": list(dict.fromkeys(l.strip() for l in locations if l and l.strip())),
            "workplace": workplace, "salary": salary, "desc": desc, "posted": posted, "dept": dept,
            "id": f'{company.get("idp") or company["name"]}::{jid or url}'}

def f_greenhouse(c):
    d = http_json(f'https://boards-api.greenhouse.io/v1/boards/{c["token"]}/jobs?content=true')
    for j in d.get("jobs", []):
        locs = [(j.get("location") or {}).get("name", "")]
        locs += [o.get("location") or o.get("name") for o in j.get("offices", [])]
        locs = [p.strip() for l in locs if l for p in re.split(r"\s*[|;]\s*", l)]
        desc = strip_html(j.get("content"))
        wp = ""
        for m in j.get("metadata") or []:
            v = str(m.get("value") or "")
            if len(v) <= 60 and re.search(r"remote|hybrid|on-?site|in[- ]office", v, re.I):
                wp = jobtext.workplace_label(v) or wp
        yield J(c, j.get("title"), j.get("absolute_url"), locs, wp, None, desc,
                (j.get("first_published") or j.get("updated_at") or "")[:10],
                ", ".join(x["name"] for x in j.get("departments", [])), j.get("id"))

def f_lever(c):
    d = http_json(f'https://api.lever.co/v0/postings/{c["token"]}?mode=json')
    for j in d:
        cat = j.get("categories", {})
        locs = cat.get("allLocations") or [cat.get("location", "")]
        if j.get("country") and j["country"] != "US":
            locs = [f'{l} ({j["country"]}) europe' for l in locs]  # "europe" = non-US marker for prepare_listing()
        wp = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(j.get("workplaceType") or "", "")
        desc = " ".join([j.get("descriptionPlain") or j.get("descriptionBodyPlain") or "", j.get("additionalPlain") or ""] +
                        [strip_html(x.get("content")) for x in j.get("lists", [])])
        sal = None
        sr = j.get("salaryRange")
        if sr and sr.get("max") and (sr.get("currency") in (None, "USD")):
            hourly = sr.get("interval", "").startswith("per-hour")
            mult = 2080 if hourly else 1
            sal = (sr["min"] * mult, sr["max"] * mult, "listed range") + (("hour", sr["min"], sr["max"]) if hourly else ())
        posted = dt.datetime.fromtimestamp(j["createdAt"] / 1000).strftime("%Y-%m-%d") if j.get("createdAt") else ""
        yield J(c, j.get("text"), j.get("hostedUrl"), locs, wp, sal, desc, posted, cat.get("team", ""), j.get("id"))

def f_ashby(c):
    d = http_json(f'https://api.ashbyhq.com/posting-api/job-board/{c["token"]}?includeCompensation=true')
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        country = addr.get("addressCountry", "")
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        if country and country not in ("United States", "USA", "US"):
            locs = [l + f" ({country}) europe" for l in locs]
        wpt = (j.get("workplaceType") or "").lower()
        wp = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}.get(wpt, "")
        if not wp and j.get("isRemote"):
            wp = "remote"
        sal = None
        comp = j.get("compensation") or {}
        for t in comp.get("summaryComponents") or []:
            if t.get("compensationType") == "Salary" and t.get("maxValue") and t.get("currencyCode", "USD") == "USD":
                sal = (t.get("minValue") or t["maxValue"], t["maxValue"], comp.get("compensationTierSummary", ""))
        if not sal and comp.get("scrapeableCompensationSalarySummary"):
            sal = parse_salary(comp["scrapeableCompensationSalarySummary"])
        yield J(c, j.get("title"), j.get("jobUrl"), locs, wp, sal, j.get("descriptionPlain") or "",
                (j.get("publishedAt") or "")[:10], j.get("department", ""), j.get("id"))

def f_smartrecruiters(c):
    off = 0
    while True:
        d = http_json(f'https://api.smartrecruiters.com/v1/companies/{c.get("token") or c["id"]}/postings?limit=100&offset={off}')
        for j in d.get("content", []):
            loc = j.get("location", {})
            locs = [loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))]
            wp = "remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else "")
            if loc.get("country") and loc["country"].lower() not in ("us", "usa"):
                locs = [l + " europe" for l in locs]
            yield J(c, j.get("name"), f'https://jobs.smartrecruiters.com/{c.get("token") or c["id"]}/{j["id"]}', locs, wp, None, "",
                    (j.get("releasedDate") or "")[:10], (j.get("department") or {}).get("label", ""), j.get("id"))
        off += 100
        if off >= d.get("totalFound", 0):
            break
        if over_budget(c):
            budget_stop(c, f"listing postings ({off} of {d.get('totalFound', 0)})")
            break

WD_UNNAMED_VALUES = 25   # unnamed location-facet values ("Main Campus", "Building 5") also queried for a local employer
WD_UNNAMED_JOBS = 600    # ... while their postings add up to no more than this

def _wd_location_facets(facets, unnamed=False):
    """Walk Workday facet tree; return {facetParameter: [ids]} for local/remote location values. unnamed=True (an
    employer known to hire only near someone here): values that name no place at all ("Main Campus", "Building 5")
    are included too, biggest first within the caps above; select_for_person() then decides per person."""
    out = {}
    def walk(fs):
        for f in fs or []:
            param = f.get("facetParameter", "")
            vals = f.get("values") or []
            if vals and isinstance(vals[0], dict) and "facetParameter" in vals[0]:
                walk(vals); continue
            if "remote" in param.lower():
                # only the values that mean remote: "Remote work is not available" and "Office Worker (NOT Remote)"
                # are this facet's on-site values
                ids = [v["id"] for v in vals if jobtext.workplace_label(v.get("descriptor", ""), typed=True) == "remote"]
                if ids:
                    out[param] = ids
            elif "location" in param.lower() and "country" not in param.lower():
                ids = [v["id"] for v in vals if near(v.get("descriptor", "")) or is_remote_us(v.get("descriptor", ""))]
                if unnamed:
                    have, n = set(ids), 0
                    extra = [v for v in vals if v.get("id") not in have and v.get("descriptor") and vague_location(v["descriptor"])]
                    extra.sort(key=lambda v: -int(v.get("count") or 0))
                    for v in extra[:WD_UNNAMED_VALUES]:
                        n += int(v.get("count") or 0)
                        if n > WD_UNNAMED_JOBS:
                            break
                        ids.append(v["id"])
                if ids:
                    out[param] = ids
    walk(facets)
    return out

WD_CAP = 2000  # Workday's job search stops paging here
WD_RECHECK_DAYS = 7  # a Workday posting whose text is stored is read again once in this many days

def fetch_wanted(c, title):
    """Does anyone's list name this title: their own title words, their what-to-look-for sheet, or their target?
    (CFG is the union of everyone's during a fetch.) Only used to decide which Workday postings get a per-posting
    detail request up front; every posting is stored either way. A profile with no titles at all (every title passes
    its filter) no longer makes the fetch ask for the full text of every posting: those are stored as "lazy" rows
    (title, place, link) and get their text when someone opens the job or it is about to be rated (lazy_text)."""
    try:
        if "fetch_include" not in CFG:
            ok = title_ok(title)
        else:
            low = title.lower()
            ok = (_named(" " + low + " ", CFG["fetch_include"], CFG.get("fetch_words")) and not excluded_words(title)
                  and not any(re.search(rx, low.strip()) for rx in CFG["title_exclude_regex"]))
        return ok or any(target_ok(st, c.get("ai_track"), title) for st in CFG.get("targets", []))
    except Exception:
        return True

def _wd_api(c):
    base = f'https://{c["host"]}' if c.get("host") else f'https://{c["tenant"]}.{c["wd"]}.myworkdayjobs.com'
    return base, f'{base}/wday/cxs/{c["tenant"]}/{c["site"]}'

def lazy_text(jid):
    """The full text of one posting. A "lazy" Workday row (stored at fetch time without its text because nobody's
    titles named it) is fetched now, parsed like any other posting and stored complete, so the next board rebuild has
    its pay, level and requirements too. Returns the text ("" if it can't be had)."""
    import catalog
    with catalog.db() as con:
        r = con.execute("SELECT company, data, desc, first_seen, last_seen, partial FROM listings WHERE id=?", (jid,)).fetchone()
    if not r:
        return ""
    if not r["partial"] or (r["desc"] or "").strip():
        return r["desc"] or ""
    old = json.loads(r["data"])
    if old.get("lazy") != "workday":
        return ""
    c = next((x for x in catalog.companies() if x["name"] == r["company"] and x.get("ats") == "workday"), None)
    path = jid.split("::", 1)[1] if "::" in jid else ""
    if not c or not path.startswith("/"):
        return ""
    try:
        import netsafe
        netsafe.check_config(c)
        base, api = _wd_api(c)
        d = http_json(api + path, tries=2).get("jobPostingInfo", {})
    except Exception:
        return ""
    desc = strip_html(d.get("jobDescription", ""))
    if not desc:
        return ""
    locs = [d.get("location") or ""] + (d.get("additionalLocations") or [])
    if not any(locs):
        locs = old.get("locations") or []
    wp = jobtext.workplace_label(d.get("remoteType"), typed=True) or (old.get("base_wp") or "")
    j = J(c, old.get("title") or d.get("title"), old.get("url") or f'{base}/en-US/{c["site"]}{path}', locs, wp, None, desc,
          d.get("startDate", "") or old.get("posted", ""), "", path)
    p = prepare_listing(j, c)
    if p is None:   # (the full posting names only places outside the US: keep the row as it was)
        return desc
    with catalog.db() as con:
        catalog.put_listing(con, p, first_seen=r["first_seen"], last_seen=r["last_seen"], partial=False)
    return desc

def ensure_text(jobs, log=None):
    """Before rating: fetch the text of any lazy rows among these jobs (a few at a time) and put it on the job."""
    lazy = [j for j in jobs if j.get("lazy") and not (j.get("desc") or "").strip()]
    if not lazy:
        return 0
    if log:
        log(f"Fetching the full text of {len(lazy)} posting(s) before rating them...")
    def one(j):
        try:
            j["desc"] = lazy_text(j["id"]) or j.get("desc") or ""
        except Exception:
            pass
        return bool(j.get("desc"))
    with cf.ThreadPoolExecutor(4) as ex:
        return sum(ex.map(one, lazy))

def f_workday(c):
    base = f'https://{c["host"]}' if c.get("host") else f'https://{c["tenant"]}.{c["wd"]}.myworkdayjobs.com'
    api = f'{base}/wday/cxs/{c["tenant"]}/{c["site"]}'
    first = http_json(api + "/jobs", {"limit": 20, "offset": 0, "searchText": c.get("search", ""), "appliedFacets": {}})
    # An employer that hires only near someone here (a DC-headquartered one in the original list, or one whose every
    # directory place is inside a home radius): its unnamed location labels are worth reading too.
    d_ = c.get("dir") or {}
    local_emp = c.get("tier") == "dmv_hq" or employer_all_near({"places": d_.get("p"), "all": d_.get("all")}, CFG.get("homes") or [])
    facets = _wd_location_facets(first.get("facets"), unnamed=local_emp)
    postings, seen = [], set()
    # Workday ORs values within a facet; query each location facet separately and merge.
    queries = [{k: v} for k, v in facets.items()] or [{}]
    # A DC-headquartered employer whose location labels we can't read ("Main Campus") gets its full list;
    # select_for_person() then keeps anything that doesn't name another state or country.
    if local_emp and (not any("location" in k.lower() for k in facets) or first.get("total", 0) <= 600):
        queries = [{}]
    # Known limitation: the location facets above are still chosen from everyone's search areas (near() over the
    # union of homes + remote), because big tenants post tens of thousands of jobs and Workday stops paging at 2000,
    # so an unfiltered query would miss the local ones. The catalog therefore holds every posting *in those facets*
    # (any title), not everything the employer posts in the US; a new person's area is picked up on the next fetch.
    truncated = []
    for applied in queries:
        off, total = 0, None
        while True:
            d = http_json(api + "/jobs", {"limit": 20, "offset": off, "searchText": c.get("search", ""), "appliedFacets": applied})
            if total is None:
                total = d.get("total", 0)
            for p in d.get("jobPostings", []):
                if p.get("externalPath") and p["externalPath"] not in seen:
                    seen.add(p["externalPath"]); postings.append(p)
            off += 20
            if off >= min(total, WD_CAP):
                if total > WD_CAP:
                    truncated.append(f"Workday stops at {WD_CAP} of {total}")
                break
            if over_budget(c):
                budget_stop(c, f"listing postings ({off} of {total})")
                truncated.append(c["_truncated"])
                break
            if not d.get("jobPostings"):
                truncated.append(f"empty page at {off - 20} of {total}")
                break
    if truncated:
        c["_truncated"] = "; ".join(dict.fromkeys(truncated))[:200]

    # Every posting gets a catalog row. Full text costs one request each (and Workday rate-limits per IP), so it is
    # fetched only for titles someone's filters could want; the rest are stored as partial rows (title, location,
    # link) and get their text on a later fetch once someone's filters want them.
    # A posting whose text is already stored isn't asked for again on every update (that was one request per posting
    # per day, most of a daily update's time): it is re-read one day a week (each posting has its own day), which is
    # when an edited posting is noticed. process() keeps the stored text and the row is left as it is.
    try:
        import catalog
        # (a row whose stored hash was cleared by reparse_stored() is read again: its workplace needs the board's word)
        have = {k for k, v in catalog.known(c["name"]).items() if v[2] and not v[1] and v[0]}
    except Exception:
        have = set()
    day = dt.date.today().toordinal() % WD_RECHECK_DAYS
    def detail(p):
        want = fetch_wanted(c, p.get("title", "")) and not over_budget(c)   # (budget spent: stored from its list row)
        d, failed = {}, False
        jid_ = f'{c.get("idp") or c["name"]}::{p["externalPath"]}'
        if want and jid_ in have and __import__("zlib").crc32(jid_.encode()) % WD_RECHECK_DAYS != day:
            j = J(c, p.get("title"), f'{base}/en-US/{c["site"]}{p["externalPath"]}', [p.get("locationsText", "")], "", None, "", "", "", p["externalPath"])
            return j
        if want:
            try:
                d = http_json(api + p["externalPath"]).get("jobPostingInfo", {})
            except Exception:
                failed = True
        locs = [d.get("location") or p.get("locationsText", "")] + (d.get("additionalLocations") or [])
        desc = strip_html(d.get("jobDescription", ""))
        wp = jobtext.workplace_label(d.get("remoteType") or p.get("remoteType"), typed=True)
        j = J(c, p.get("title"), f'{base}/en-US/{c["site"]}{p["externalPath"]}', locs, wp, None, desc,
              d.get("startDate", "") or "", "", p["externalPath"])
        if not want or failed:
            j["_partial"] = True  # no full text this time (process() keeps any text stored earlier)
        if not want:
            j["lazy"] = "workday"  # nobody's titles name it: shown from its title, text fetched when wanted (lazy_text)
        return j
    with cf.ThreadPoolExecutor(6) as ex:
        yield from ex.map(detail, postings)
    if over_budget(c):
        budget_stop(c, listed=True)   # (every posting was listed; the texts left out are read by the next fetch)

FETCHERS = {"greenhouse": f_greenhouse, "lever": f_lever, "ashby": f_ashby,
            "smartrecruiters": f_smartrecruiters, "workday": f_workday}
def load_extra():
    # (import by name, never by "is the .py file on disk": an installed build keeps its modules inside the bundle)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    for mod in ("extra_fetchers", "smb_fetchers", "ats_sap_taleo", "ats_more", "ats_public"):
        try:
            FETCHERS.update(__import__(mod).FETCHERS)
        except ImportError:
            pass
    import directory   # job snapshots from the Siftwell employer directory (USAJOBS ...), read from its cached files
    FETCHERS.update(directory.FETCHERS)

# ---------------------------------------------------------------- pipeline
BARE_US = re.compile(r"\s*(us|usa|u\.s\.|united states( of america)?|dragos usa)\s*")
REMOTE_DESC = re.compile(r"fully remote|remote[- ]first|100% remote|remote position|remote role|work remotely|remote within the (us|united states)|remote \(us\)|this role is remote|remote, us")

# More ways a posting says it is remote, and ways it says it is not. Only used when stored listings are read again
# (reparse_one), to decide whether a "remote" flag from a job system that earlier versions misread is kept.
REMOTE_SAID = re.compile(r"#li-?remote|location\s*:\s*remote|full[- ]time remote|eligible for (?:full[- ]time |100% )?remote|remote[- ]eligible|"
                         r"remote (?:position|role|job|opportunity)|open to (?:considering )?(?:u\.?s\.?[- ])?remote|home[- ]based|work(?:ing|s)? from home|"
                         r"work[- ]at[- ]home")
ONSITE_SAID = re.compile(r"#li-?(?:onsite|on-site|hybrid)|(?:full[- ]time|fully|100%) on-?site|\ban? on-?site (?:position|role|job)|not (?:a )?remote|"
                         r"no remote|(?:position|role|job) is (?:hybrid|on-?site)|\ba? hybrid (?:position|role|job)\b")
_NO_PLACE = re.compile(r"(?:[\s,;/|-]*(?:unavailable|n/?a|tbd|none))*[\s,;/|-]*", re.I)
_HOME_LABEL = re.compile(r"\s*(?:home|home office)\s*(?:,\s*[A-Za-z]{2})?\s*", re.I)   # iCIMS "Home, TX": works from home in Texas


def names_us(l, states=None):
    """Does a location label name the US, a US state or a US place ("United States", "Remote - US", "US-VA-REMOTE",
    "Remote, Minnesota, USA", "Remote - WI", "Reston, VA")? Plain "Remote" and foreign labels don't."""
    if not l or is_foreign(l, states) or jobtext.foreign_remote(l):
        return False
    if BARE_US.fullmatch(l.lower()) or re.search(r"(?<![A-Za-z])(?:US|USA|U\.S\.A?\.?)(?![A-Za-z])", l.replace("_", " ")) \
            or re.search(r"united states", l, re.I):
        return True
    import geo
    return any(h.kind != "bare" for h in geo.locate_all(l))


def set_pay(j, sal):
    """Store a posting's pay. sal: (low per year, high per year, words[, unit, low in that unit, high in that unit])
    or None. salary_min / salary_max / salary_mid are always per year (hourly at 2,080 hours), so the pay floor, the
    Highest pay sort and Appeal compare every job on one scale; pay_unit / pay_min / pay_max keep what the posting
    said, so an hourly job is shown as hourly."""
    if not sal:
        j["salary_min"] = j["salary_max"] = j["pay_min"] = j["pay_max"] = None
        j["salary_text"] = j["pay_unit"] = ""
        return
    unit = sal[3] if len(sal) > 5 and sal[3] in jobtext.PER_YEAR else "year"
    per = jobtext.PER_YEAR[unit]
    j["salary_min"], j["salary_max"], j["salary_text"] = round(sal[0]), round(sal[1]), sal[2]
    j["pay_unit"] = unit
    j["pay_min"], j["pay_max"] = (round(sal[4], 2), round(sal[5], 2)) if len(sal) > 5 else (round(sal[0] / per, 2), round(sal[1] / per, 2))

def prepare_listing(j, c):
    """Parse one fetched posting for the catalog. Nothing here depends on who is looking: whether it is near someone,
    pays enough or has a fitting title is decided per person in select_for_person(). Returns None for postings
    outside the US (and not remote-US), which no one can use."""
    import geo
    locs = j["locations"]
    base = j.get("workplace") or ""
    base0 = base
    states = employer_us_states(c)      # settles a foreign city written alone ("Dublin" at an Ohio employer)
    nonus = lambda l: is_foreign(l, states) or jobtext.foreign_remote(l)
    j.pop("_maybe", None)
    foreign_loc = [l for l in locs if l and nonus(l)]
    us_loc = [l for l in locs if l and names_us(l, states)]
    # A posting with a foreign place and no US one is not a US job, whatever else its labels say ("Athens, Attica" +
    # "Remote"). One that names both ("Tysons Corner, Virginia; Fredericton, Canada") is kept.
    if foreign_loc and not us_loc:
        # (only a foreign city written alone stood in the way: process() asks again once it knows the employer's states)
        j["_maybe"] = all(geo.where(l) == "maybe" for l in foreign_loc)
        return None
    strict = base == "remote" and not foreign_loc or any(is_remote_us(l) for l in locs)
    # "Customer Success Manager - Belfast, UK" listed at "Remote": the title says where the job really is. Not when a
    # location label names the US ("Area Director of Sales - Asia" at "United States", "(Canada Territory)" at "Remote,
    # Minnesota, USA", "... - Americas, EMEA" at "Remote-US"): then the title names the market, not the workplace.
    tp = jobtext.title_place(j.get("title"))
    if tp and nonus(tp) and not any(l and not nonus(l) and (names_us(l) or not jobtext.remote_label(l)) for l in locs):
        return None
    text = j.get("desc") or ""
    title = j.get("title") or ""
    # No US place on the posting: its own words decide. Written in another language, or its title or text puts the
    # job in another country ("based in Toronto", "remote within Canada", pay in euros) with nothing saying US: out.
    # ("AI Training Experts - Kansas, US" at "Remote": the title says where, and it is the US)
    said_us = jobtext.text_us(text) or bool(tp and geo.where(tp) == "us")
    rem = [l for l in locs if l and jobtext.remote_label(l)]
    if not us_loc:
        abroad = lambda s: is_foreign(s) and not re.search(r"united states|\bU\.?S\.?A?\b", s)
        if jobtext.non_english(title, text):
            return None
        # (only a remote posting: "Managing Editor, Asia" at an office with no label is a job at that office)
        if (base == "remote" or rem) and not said_us and (geo.names_foreign(title) or jobtext.text_abroad(text, abroad)):
            return None
    # Remote for real? A label can say remote while the work is done in person (in-home visits, a clinic).
    veto = jobtext.remote_veto(title, text) if (strict or base == "remote") else ""
    if veto:
        strict, base = False, ("" if base == "remote" else base)
        j["workplace"] = base
    # "OH - Work from home", "Remote - Texas": remote, for people who live in that state
    bound = [jobtext.remote_state(l) for l in rem]
    remote_st = sorted(set(bound)) if strict and rem and all(bound) else []
    bare = not veto and any(BARE_US.fullmatch(l.lower()) for l in locs) and (c.get("tier") == "remote_first" or bool(REMOTE_DESC.search(text.lower())))
    unnamed = c.get("tier") == "dmv_hq" and bool(locs) and all(looks_local_unnamed(l) for l in locs if l)
    j.update(ai_track=c.get("ai_track", ""), base_wp=base0, remote_strict=bool(strict), remote_bare=bool(bare),
             local_unnamed=unnamed, pv=jobtext.PARSE_VERSION, remote_st=remote_st, remote_veto=veto,
             geo="us" if (us_loc or (said_us and not foreign_loc) or (not foreign_loc and any(_us_city(l) for l in locs if l))) else "")
    # pay: what the board itself listed, else the posting's text, else its title ("Line Cook - $17/hour")
    set_pay(j, j.pop("salary", None) or parse_salary(text) or parse_salary(j.get("title") or ""))
    # the states the posting names, for placing a bare city name ("Columbus" + "a current Georgia license")
    # (the employer's own name is taken out first: "Georgia-Pacific" and "Texas Roadhouse" name no place)
    co = (j.get("company") or "").strip()
    named = (j.get("title") or "") + "\n" + text
    if len(co) >= 4 and jobtext.text_states(co):
        named = re.sub(re.escape(co), " ", named, flags=re.I)
    j["loc_st"] = jobtext.text_states(named)
    enrich(j, text)  # also fills workplace from the text when the board didn't say
    if veto and not j.get("workplace"):
        j["workplace"] = "onsite"
    j["snippet"] = text[:600]
    return j

_CODED = re.compile(r"\d{3,}|^\s*US\s*[-_]|^[A-Z]{2}\s*[-_]\s*\S|_")

def nice_place(label):
    """A job-system location code as a place a person reads: "US-OH-Columbus" and "01088 - Columbus Victorian Village
    Selec" -> "Columbus, OH". Labels that already read fine are left alone ("" is returned: the page shows the label)."""
    if not label or not _CODED.search(label):
        return ""
    try:
        import geo
        hs = [h for h in geo.locate_all(label, weak=True) if h.kind in ("place", "alias", "county", "bare") and "," in h.label]
        return hs[0].label if hs else ""
    except Exception:
        return ""

def _us_city(l):
    """A label that is a US city written without its state ("Arlington", "St. Louis"): good enough to count the
    posting as a US one when working out whether an employer hires mostly abroad."""
    import geo
    if geo.where(l) != "" or geo._foreign()["shared"].search(geo._key(l)):      # ("Birmingham", "Cambridge": could be either)
        return False
    return any(h.kind in ("bare", "place", "alias", "metro", "zip", "county") for h in geo.locate_all(l, weak=True))

def employer_us_states(c):
    """The US states an employer is known to hire in: the directory's, and the ones its postings name with a town
    (c["_us_st"], filled by process() and reparse_stored())."""
    st = set(c.get("_us_st") or ())
    st.update((c.get("dir") or {}).get("st") or [])
    return st

def note_states(c, locs):
    """Remember the states a kept posting names with a town or alone (for employer_us_states)."""
    import geo
    for l in locs or []:
        if l:
            c.setdefault("_us_st", set()).update(st for _, st in geo.place_states(l))

# ---------------------------------------------------------------- one slow employer must not hold a whole fetch
# Each employer gets a time budget and a posting budget per fetch. A reader that pages (Workday, Oracle, UKG, iCIMS,
# SmartRecruiters...) asks over_budget(c) between pages and stops listing; per-posting detail requests are skipped
# once the budget is spent (those postings are stored from their list row and filled in by the next fetch). What was
# read is kept, the company is marked "capped" (nothing is closed) and the fetch moves on.
# The budget: --budget SECS on the command line, else env SIFTWELL_FETCH_BUDGET, else FETCH_BUDGET_SECS; 0 = none.
FETCH_BUDGET_SECS = 240
# A regular Find new jobs (no --budget, no SIFTWELL_FETCH_BUDGET) gives every employer QUICK_BUDGET_SECS first, so one
# slow job site never holds the count at "269 of 271" for minutes; the few that ran out are then read again together
# with the full FETCH_BUDGET_SECS (the run says which ones, and Stop keeps everything found so far). The staged first
# check does the same with its own numbers (first_search CHUNK_BUDGET / SLOW_BUDGET).
QUICK_BUDGET_SECS = 60
FETCH_BUDGET_GRACE = 45      # after the budget, a reader that doesn't ask over_budget() is cut off this much later (at most budget / 4)
FETCH_MAX_POSTINGS = 8000    # postings read from one employer in one fetch
_BUDGET = {"secs": None}

def fetch_budget():
    if _BUDGET["secs"] is not None:
        return _BUDGET["secs"]
    try:
        return max(0, int(os.environ.get("SIFTWELL_FETCH_BUDGET") or FETCH_BUDGET_SECS))
    except ValueError:
        return FETCH_BUDGET_SECS

def over_budget(c):
    """Has this employer's fetch used up its time? (False when no budget is set: checking a new company, tests.)"""
    d = c.get("_deadline")
    return bool(d) and time.time() > d

def budget_stop(c, where="", listed=False):
    """Note that a reader stopped early for its budget. listed=False: it stopped while listing postings, so the list
    is incomplete and the company is marked "capped" (nothing is closed). listed=True: every posting was listed and
    only some full texts were left for next time, so the fetch still counts as complete."""
    if not listed and not c.get("_truncated"):
        c["_truncated"] = f"time budget of {int(c.get('_budget') or 0)}s used up{(' ' + where) if where else ''}; the rest is read next time"
    c["_budget_hit"] = True

def process(c, budget=None):
    """Fetch one company. Postings whose title and text are unchanged since the last fetch aren't parsed again.
    budget: seconds this employer may take (default fetch_budget(); 0 = no limit)."""
    import catalog
    t0 = time.time()
    raw = 0
    out = []
    n_foreign, maybe = 0, []
    c.pop("_truncated", None)
    c.pop("_budget_hit", None)
    budget = fetch_budget() if budget is None else budget
    if budget:
        c["_deadline"], c["_budget"] = t0 + budget, budget
    try:
        import netsafe
        netsafe.check_config(c)  # (a malformed or unsafe board config is never fetched)
        known = catalog.known(c["name"])
        try:        # the states its stored postings name: they settle a foreign city written alone ("Dublin")
            c["_us_st"] = catalog.company_states(c["name"])
        except Exception:
            c["_us_st"] = set()
        gen = FETCHERS[c["ats"]](c)
        try:
            for j in gen:
                raw += 1
                k = known.get(j["id"])  # (hash, partial, has_text)
                if not (j.get("desc") or "").strip() and k and k[2]:
                    # the fetcher skipped or failed the full text this time: keep the text stored earlier
                    j["desc"] = catalog.description(j["id"])
                    j.pop("_partial", None)
                    j.pop("lazy", None)
                if k and not k[1] and k[0] == catalog.listing_hash(j["title"], j.get("desc")):
                    out.append({"id": j["id"], "_unchanged": True})
                else:
                    p = prepare_listing(j, c)
                    if p:
                        out.append(p)
                        note_states(c, p.get("locations"))
                    elif j.get("_maybe"):
                        maybe.append(j)     # "Dublin" alone: decided below, once every posting's states are known
                    else:
                        n_foreign += 1
                if raw >= FETCH_MAX_POSTINGS:
                    c["_truncated"] = c.get("_truncated") or f"stopped at {FETCH_MAX_POSTINGS} postings; the rest is read next time"
                    c["_budget_hit"] = True
                    break
                if budget and time.time() > c["_deadline"] + min(FETCH_BUDGET_GRACE, budget / 4):
                    budget_stop(c, f"after {raw} postings")
                    break
        finally:
            close = getattr(gen, "close", None)
            if close:
                close()
        for j in maybe:
            p = prepare_listing(j, c)
            if p:
                out.append(p)
            else:
                n_foreign += 1
        status = "ok"
    except Exception as e:
        status = f"error: {type(e).__name__}: {e}"[:200]
    c.pop("_deadline", None)
    c.pop("_budget", None)
    c.pop("_us_st", None)
    return {"company": c["name"], "ats": c["ats"], "tier": c.get("tier"), "sector": c.get("sector"),
            "raw_jobs": raw, "matched": len(out), "status": status, "secs": round(time.time() - t0, 1), "foreign": n_foreign,
            "truncated": c.pop("_truncated", None), "budget_hit": bool(c.pop("_budget_hit", False)),
            "board_title": c.pop("_board_title", None)}, out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company names")
    ap.add_argument("--only-file", help="a JSON list of company names (for lists too long for --only: one profile's own employers)")
    ap.add_argument("--no-rate", action="store_true", help="fetch only: rebuild the boards without Claude rating (the staged first check rates once, at the end)")
    ap.add_argument("--no-boards", action="store_true", help="fetch only: don't rebuild the boards after this fetch (a later one will)")
    ap.add_argument("--boards-every", type=int, default=0, metavar="SECS", help="fetch only: also rebuild the boards (no Claude) while the fetch runs, the first time after about a minute and then every SECS, so jobs show up before slow boards finish")
    ap.add_argument("--budget", type=int, default=None, metavar="SECS", help="fetch only: the most time one employer may take (default %d; 0 = no limit). An employer that runs out is marked 'capped', keeps what was read and is finished by a later fetch" % FETCH_BUDGET_SECS)
    ap.add_argument("--rescore", action="store_true", help="re-parse every open listing from its saved text, then rebuild boards (no fetching)")
    ap.add_argument("--recompute", nargs="*", metavar="PID", help="rebuild these people's boards (everyone if none given) from the catalog; no fetching, no Claude")
    ap.add_argument("--rerate", metavar="PID", help="have Claude rate this person's unrated listings and redo ones rated with older info (no fetching)")
    ap.add_argument("--n", type=int, default=300, help="(kept for compatibility; budgets come from the person's settings)")
    # Re-rate panel options (with --rerate). Without --tiers, --rerate does the classic run (settings' budgets).
    ap.add_argument("--tiers", help="comma-separated: haiku,sonnet,opus (all three = the full re-rate)")
    ap.add_argument("--force", action="store_true", help="rate the picked jobs again even if their ratings are current")
    ap.add_argument("--sonnet-pct", type=int, help="Sonnet looks at the top X%% of the rated jobs (1-100), at most 100 a run")
    ap.add_argument("--opus-top", type=int, help="Opus looks at the top Y rated jobs (1-2000), at most 50 new a run, plus saved ones")
    ap.add_argument("--no-target", action="store_true", help="don't rate for the Target tab alongside")
    ap.add_argument("--ids-file", help="JSON list of job ids: Haiku only checks these (the automatic check of new jobs)")
    args = ap.parse_args()
    import catalog, joblock
    people.ensure_migrated(BASE_CFG)
    catalog.migrate()
    kind = "rescore" if args.rescore else "recompute" if args.recompute is not None else "rerate" if args.rerate else "fetch"
    # one background job at a time per data folder (the server takes the lock for its own subprocesses)
    with joblock.hold(kind, on_wait=lambda k: print(f"Waiting for the running {k} to finish...", flush=True)):
        if args.rescore:
            return rescore()
        if args.recompute is not None:
            return run_recompute(args.recompute)
        if args.rerate:
            return rerate(args.rerate, args.n, rate_opts(args.rerate, args))
        return fetch(args)

def fetch(args):
    import catalog
    use_cfg(fetch_cfg([person_cfg(pid)[0] for pid in people.ids()]))  # decides which postings get their full text fetched
    load_extra()
    if getattr(args, "budget", None) is not None:
        _BUDGET["secs"] = max(0, int(args.budget))
    two_pass = getattr(args, "budget", None) is None and not os.environ.get("SIFTWELL_FETCH_BUDGET")
    reparse_stored()   # (one time after an update that reads postings better: stored listings are read again first)
    companies = catalog.companies(include_paused=False)
    if getattr(args, "only_file", None):
        with open(args.only_file, encoding="utf-8") as fh:
            names = [str(x) for x in json.load(fh)]
        want = {x.strip().lower() for x in names}
        companies = [c for c in companies if c["name"].lower() in want]
        args.only = f"{len(companies)} employers ({os.path.basename(args.only_file)})"   # (what the run history shows)
    elif args.only:
        want = {x.strip().lower() for x in args.only.split(",")}
        companies = [c for c in companies if c["name"].lower() in want]
    if not companies:
        print("No companies to check yet: add some to the company list, then run the update again.", flush=True)
        return 0
    rid = catalog.start_run("fetch", details={"only": args.only})
    totals = {"new": 0, "changed": 0, "reopened": 0, "closed": 0, "unchanged": 0}
    errors, flagged, n_ok, futs, boards, status, facts, over = [], [], 0, {}, None, "error", None, []
    # --boards-every: boards from what is in the catalog so far, about a minute in and then every SECS, in a child
    # process (this one's filters are the fetch's, shared by its threads; the job lock is inherited). The fetch
    # threads keep going meanwhile, so jobs show up while slow boards are still being read.
    mid_stop, mid_thread, every = threading.Event(), None, int(getattr(args, "boards_every", 0) or 0)
    def mid_boards():
        wait = min(every, 60)
        while not mid_stop.wait(wait):
            wait = every
            try:
                import frozen
                osdeps.run_hidden(frozen.command("jobfinder", "--recompute"), cwd=HERE, capture_output=True, timeout=900)
            except Exception as e:
                print(f"(couldn't rebuild the boards mid-fetch: {type(e).__name__})", flush=True)
    if every and len(companies) > 1:
        mid_thread = threading.Thread(target=mid_boards, daemon=True)
        mid_thread.start()
    def one_pass(cos, budget, phase, last):
        """Read these companies (budget: seconds each, None = the default). Returns the ones that ran out of time.
        last: this is the final word on them; otherwise a company that ran out is left for the next pass (it is not
        counted or flagged yet)."""
        nonlocal n_ok
        again = []
        # Workday tenants share one per-IP rate limit, so they get their own small lane; everything else runs wide.
        with cf.ThreadPoolExecutor(12) as fast, cf.ThreadPoolExecutor(4) as slow:
            fs = {(slow if c["ats"] == "workday" else fast).submit(process, c, budget): c for c in cos}
            for n, f in enumerate(cf.as_completed(fs), 1):
                try:
                    s, js = f.result()
                    with catalog.db() as con:
                        counts = catalog.record_fetch(s["company"], s, js, con)
                    if s["status"] == "ok":   # (a code or placeholder name -> the employer's real one, from its postings)
                        s["company"] = learn_company_name(s["company"], s.get("board_title"))
                except Exception as e:
                    s = {"company": fs[f]["name"], "ats": fs[f]["ats"], "raw_jobs": 0, "matched": 0, "secs": 0,
                         "status": f"error: saving failed: {type(e).__name__}: {e}"[:200]}
                    counts = {k: 0 for k in totals}
                for k in totals:
                    totals[k] += counts[k]
                retry = bool(s.get("budget_hit")) and not last and s["status"] == "ok"
                if retry:
                    again.append(s["company"])
                elif s["status"] == "ok":
                    n_ok += 1
                    if counts.get("status") not in (None, "ok"):
                        flagged.append({"company": s["company"], "status": counts["status"]})
                else:
                    errors.append({"company": s["company"], "error": s["status"]})
                note = ""
                if s.get("budget_hit") and last:
                    over.append(s["company"])
                if retry:
                    note = " [ran out of time: read again at the end of this run]"
                elif counts.get("status") not in (None, "ok", "error"):
                    note = f' [{counts["status"]}: missing postings kept open{"; " + s["truncated"] if s.get("truncated") else ""}]'
                print(f'{s["company"]:<24} {s["ats"]:<15} raw={s["raw_jobs"]:<5} kept={s["matched"]:<4} new={counts["new"]:<4} closed={counts["closed"]:<4} {s["status"]}{note} ({s["secs"]}s)', flush=True)
                print(f"PROGRESS {phase} {n}/{len(fs)}", flush=True)
        return again

    try:
        todo = [c for c in companies if c["ats"] in FETCHERS]
        futs = {c["name"]: c for c in todo}
        slow_names = one_pass(todo, QUICK_BUDGET_SECS if two_pass else None, "fetch", last=not two_pass)
        if slow_names:
            # the few that ran out of time: together, with the full budget. What the first pass read is in the catalog.
            print("SLOW " + json.dumps(sorted(slow_names)), flush=True)
            print(f"PROGRESS slow 0/{len(slow_names)}", flush=True)
            want_slow = set(slow_names)
            one_pass([c for c in catalog.companies(include_paused=False) if c["name"] in want_slow and c["ats"] in FETCHERS],
                     FETCH_BUDGET_SECS, "slow", last=True)
        mid_stop.set()
        if mid_thread:
            mid_thread.join(900)
        if over:   # (one line a caller can read: these ran out of their time budget and are finished by a later fetch)
            print("OVER_BUDGET " + json.dumps(sorted(over)), flush=True)
        if not args.only:
            catalog.set_meta("last_full_fetch", dt.date.today().isoformat())
        pool = catalog.open_listings(lazy=True)
        if not args.only:
            import target
            target.write_market(pool)
        print(f"\nCatalog: {len(pool)} open listings; this run {totals['new']} new, {totals['closed']} closed, "
              f"{totals['changed']} changed, {totals['reopened']} back again, {len(errors)} companies failed, "
              f"{len(flagged)} kept open (suspect or incomplete fetch)", flush=True)
        quiet = bool(getattr(args, "no_rate", False) or getattr(args, "no_boards", False))
        boards = {} if getattr(args, "no_boards", False) else recompute(None, rate=not quiet, pool=pool)
        if not args.only and not quiet:  # last: Claude looks up facts for companies that need them (capped in Settings, Claude usage)
            facts, fboards = research_company_facts()
            for p in _failed(fboards):
                boards[p] = fboards[p]
        status = "ok" if not (errors or _failed(boards)) else "partial"
    finally:
        mid_stop.set()
        catalog.finish_run(rid, status=status, companies=len(futs), fetched=n_ok,
                           new=totals["new"], closed=totals["closed"], changed=totals["changed"], reopened=totals["reopened"],
                           errors=(errors + flagged + [{"person": p, "error": boards[p]["error"]} for p in _failed(boards)])[:200],
                           details={"boards": boards, **({"facts": facts} if facts else {}), **({"over_budget": sorted(over)} if over else {})})
    print(f"boards rebuilt for {len(boards) - len(_failed(boards))} profile(s)", flush=True)
    return 3 if _failed(boards) else 0

CSV_COLS = ["req_status", "score", "pv_score", "pv_label", "pv_now", "pv_later", "ai_label", "ai_asis", "ai_fit", "ai_reason", "ai_tailor",
            "fit_score", "comp_score", "qol_score", "company", "title", "level", "workplace", "dmv_locations", "locations",
            "pay", "salary_min", "salary_max", "salary_mid", "wide_band", "travel", "travel_pct", "clearance", "scif", "posted",
            "first_seen", "sector", "url"]
# what the columns are called in jobs.csv (the keys above are internal names from when Siftwell knew one area only)
CSV_HEAD = {"dmv_locations": "locations_near_you", "locations": "all_locations", "pv_score": "target_score", "pv_label": "target_label",
            "pv_now": "target_now", "pv_later": "target_after_prep", "ai_label": "match_label", "ai_asis": "match_as_is", "ai_fit": "match",
            "ai_reason": "match_reason", "ai_tailor": "tailoring_tips", "req_status": "requirements", "pay": "pay_as_posted",
            "salary_min": "pay_per_year_min", "salary_max": "pay_per_year_max", "salary_mid": "pay_per_year_mid"}

def company_sets_map():
    import catalog
    try:
        return catalog.sets_map()
    except Exception:
        return {}

def select_for_person(pool, sets=None):
    """The current person's filters (CFG is theirs) over catalog listings: their employers, title, pay floor, area/remote
    and workplace. Returns copies with this person's view of workplace, nearby locations and tracks."""
    out = []
    watch, sets = people.company_sets(), sets if sets is not None else company_sets_map()
    wps = CFG.get("workplaces") or ["onsite", "hybrid", "remote"]
    homes = CFG.get("homes", [])
    dc_ok = CFG.get("legacy_area", True) or (bool(homes) and any(__import__("geo").within(["Washington, DC"], h, r + 10)[0] for h, r in homes))
    targets = CFG.get("targets", [])
    places = {}
    try:
        import catalog
        places = catalog.places_map()
    except Exception:
        pass
    emp_near = {}
    emp_places = EmployerPlaces(pool, places)
    try:        # employers that hire almost only abroad: only their postings with a US place are shown
        abroad = catalog.foreign_employers()
    except Exception:
        abroad = set()
    import geo
    home_states = {geo.home_state(h) for h, _ in homes} - {None}
    for j0 in pool:
        if not (sets.get(j0["company"], set()) & watch):
            continue
        if j0["company"] in abroad and j0.get("geo") != "us":
            continue
        cur_ok = title_ok(j0["title"])
        ai_ok = any(target_ok(st, j0.get("ai_track"), j0["title"]) for st in targets)
        if not (cur_ok or ai_ok):
            continue
        smax = j0.get("salary_max")
        if smax is not None and smax < CFG["salary_floor"] and not CFG["keep_below_floor"]:
            continue
        if smax is None and not CFG["keep_unlisted_salary"]:
            continue
        locs = j0.get("locations") or []
        # a bare city name ("Columbus", "Columbus Healthcare Center") counts only in a state there is support for
        mine = [l for l in locs if near(l, bare_support(l, j0, emp_places) if homes else None)]
        remote = bool(j0.get("remote_strict") or (j0.get("remote_bare") and not mine))
        # "OH - Work from home", "Remote - Texas": remote for people whose home is in that state (with no home set,
        # as before: shown)
        rst = j0.get("remote_st") or []
        elsewhere = bool(remote and rst and home_states and not (set(rst) & home_states))
        if elsewhere:
            remote = False
        dc_fallback = not remote and not mine and bool(j0.get("local_unnamed")) and dc_ok
        vague_near = None   # employer-places rule: no readable place on the posting, and everywhere the employer hires is nearby
        if not (mine or remote or dc_fallback) and j0["company"] in places:
            info = places[j0["company"]]
            if j0["company"] not in emp_near:
                emp_near[j0["company"]] = employer_all_near(info, homes)
            if emp_near[j0["company"]] and all(vague_location(l, info["states"]) for l in (locs or [""])):
                lab = info.get("label") or ""
                vague_near = [(f"{l} (near {lab})" if lab else l) if l else (f"Near {lab}" if lab else "") for l in (locs or [""])][:3]
        if not (mine or dc_fallback or vague_near is not None or (remote and CFG.get("remote_ok", True))):
            continue
        wp = "remote" if remote else (j0.get("workplace") or "")
        if elsewhere and wp == "remote":
            wp = ""     # (remote, but only for another state's residents: for this person it is a job at its place)
        if wp and wp not in wps and not (wp == "remote" and mine):
            continue
        j = dict(j0)
        j["workplace"] = wp
        # "Remote (Ohio)": the person's own state when they have a home; else the states (a long list as a count)
        shown = [s for s in rst if s in home_states] or (rst if len(rst) <= 3 else [])
        j["remote_in"] = "" if not (remote and rst) else \
            (", ".join(geo.STATES[s].title() for s in shown if s in geo.STATES) + (" only" if not home_states and len(rst) == 1 else "")
             if shown else f"{len(rst)} states")
        j["where"] = nice_place(mine[0]) if (mine and not dc_fallback and vague_near is None) else ""
        j["dmv_locations"] = [f"{l} (DC area)" for l in locs if l][:3] if dc_fallback else [x for x in (vague_near or []) if x] if vague_near is not None else mine
        j["tracks"] = (["current"] if cur_ok else []) + (["ai"] if ai_ok else [])
        out.append(j)
    return out

def apply_requirements(pid, jobs):
    """Check each job's degree/license requirements against the person's confirmed (or extracted) highlights."""
    try:
        import highlights, requirements
        hl = highlights.get(pid)
    except Exception:
        hl = None
    for j in jobs:
        if "req" not in j:
            try:
                import requirements
                j["req"] = requirements.parse(j.get("desc", ""), j["title"])
            except Exception:
                j["req"] = None
        if hl:
            r = requirements.check(j.get("req"), hl)
            j["req_status"], j["req_chips"], j["req_soft"], j["req_reasons"] = r["status"], r["chips"], r.get("soft", []), r["reasons"]
        else:
            j["req_status"], j["req_chips"], j["req_soft"], j["req_reasons"] = "ok", [], [], []

def saved_ids(pid=None):
    """Ids of the jobs the person saved or applied to, the most recently marked first (marks.json keeps the order
    they were marked in; a job marked again moves to the end)."""
    try:
        m = json.load(open(people.pdir("marks.json", pid=pid)))
        return [k for k, v in reversed(list(m.items())) if v in ("saved", "applied")]
    except Exception:
        return []

NIGHT_ENV = "SIFTWELL_NIGHT"   # set (to one id) by the scheduled update for its fetch and for the re-rate that follows it

def night_budgets(pid, budgets, target_n):
    """One budget for a scheduled night. The night has two steps, each its own process: the update (which rates new
    jobs) and the re-rate after it (which redoes ratings made with older info). Each used to get a full run's limits,
    so a night could do 500 + 500 quick checks. With NIGHT_ENV set, the second step only gets what the first left:
    returns (budgets, Target limit) minus what this night already used for this person (kept in the catalog's notes
    under night:<pid>). Without NIGHT_ENV (every run a person starts): unchanged."""
    nid = os.environ.get(NIGHT_ENV)
    if not nid:
        return budgets, target_n
    import catalog
    used = catalog.get_meta(f"night:{pid}") or {}
    if used.get("id") != nid:
        return budgets, target_n
    import ai_score
    L = ai_score.RUN_LIMITS
    left = lambda key, limit, tier: max(0, min(L[limit], int(budgets.get(key, L[limit]) or 0)) - int(used.get(tier) or 0))
    b = dict(budgets, haiku=left("haiku", "haiku", "haiku"), sonnet_max=left("sonnet_max", "sonnet", "sonnet"),
             opus_max=left("opus_max", "opus", "opus"), saved_max=max(0, L["saved"] - int(used.get("saved") or 0)))
    print(f"Tonight's rating budget, after the update's share: {b['haiku']} quick checks, {b['sonnet_max']} second looks, "
          f"{b['opus_max']} careful ratings left", flush=True)
    return b, max(0, int(target_n or 0) - int(used.get("target") or 0))

def night_spent(pid, timings):
    """Add what this step rated to the night's tally (only during a scheduled night)."""
    nid = os.environ.get(NIGHT_ENV)
    if not nid:
        return
    import catalog
    used = catalog.get_meta(f"night:{pid}") or {}
    if used.get("id") != nid:
        used = {"id": nid}
    for t in timings:
        n = int(t.get("rated", t.get("jobs", 0)) or 0)
        if t.get("tier") == "opus":      # the first 50 are the run's own, anything above came from the saved jobs
            own = min(n, max(0, 50 - int(used.get("opus") or 0)))
            used["opus"] = int(used.get("opus") or 0) + own
            used["saved"] = int(used.get("saved") or 0) + n - own
        elif t.get("tier") in ("haiku", "sonnet", "target"):
            used[t["tier"]] = int(used.get(t["tier"]) or 0) + n
    catalog.set_meta(f"night:{pid}", used)

def eligible_for_claude(j):
    """Skip jobs the person can't or won't pursue: unmet hard requirements, levels well outside their band, or a
    title that nothing on their what-to-look-for list names (those are not on the board)."""
    if j.get("req_status") == "unmet" or j.get("off_list"):
        return False
    L, band = j.get("level"), (CFG.get("seniority") or {}).get("band") or [1, 7]
    return L is None or band[0] - 1 <= L <= band[1] + 1

def score_person(jobs, prof, new_claude=True, refresh=False, opts=None):
    """Appeal for every job, then Match from Claude: the Haiku -> Sonnet -> Opus funnel (cache only if not new_claude).
    When rating, the Target (pivot) ratings run at the same time as the funnel, on copies; both caches are then
    applied in the original order, so the result is the same as running them one after the other.
    opts: a Re-rate panel run (see rate_opts): which tiers, budgets, force, ranking, only these job ids, Target or not."""
    import ai_score, pivot, threading
    opts = opts or {}
    for j in jobs:
        score(j)
    ok = [j for j in jobs if j.get("req_status") != "unmet"]
    unmet = [j for j in jobs if j.get("req_status") == "unmet"]
    pv_run, pv_thread = {"status": ""}, None
    budgets = CFG.get("funnel") or {}
    target_n = {**CFG["pivot"], **opts.get("pivot", {})}.get("max_new_per_run", 0)
    automatic = new_claude and "budgets" not in opts     # an update or the classic re-rate (not a Re-rate panel run)
    if automatic and prof:
        budgets, target_n = night_budgets(people.current(), budgets, target_n)
    if CFG["pivot_enabled"] and prof and new_claude and opts.get("target", True):
        cfg_pv = {**CFG["pivot"], **({"refresh_stale": True} if refresh else {}), **opts.get("pivot", {}), "max_new_per_run": target_n}
        copies = [dict(j) for j in ok if "ai" in j["tracks"]]
        pid = people.current()
        def run_pivot():
            people.set_current(pid)
            t0 = time.time()
            try:
                pv_run["status"] = pivot.score_jobs(copies, cfg_pv, log=lambda m: print(m, flush=True))
            except Exception as e:
                pv_run["status"] = "partial"
                print(f"Target rating failed: {type(e).__name__}: {e}", flush=True)
            print(f"TIMING target total {time.time() - t0:.1f}s", flush=True)
        pv_thread = threading.Thread(target=run_pivot, daemon=True)
        pv_thread.start()
    try:
        if prof:
            if not new_claude:
                budgets = {"haiku": 0, "sonnet_pct": 0, "sonnet_max": 0, "opus_top": 0, "opus_max": 0}
            extra = {k: opts[k] for k in ("tiers", "force", "pick", "only_ids") if k in opts} if new_claude else {}
            if new_claude and "budgets" in opts:
                budgets = opts["budgets"]
            ai_status = ai_score.run_funnel(jobs, budgets, refresh=refresh, saved=saved_ids(), eligible=eligible_for_claude,
                                            log=lambda m: print(m, flush=True), prepare=ensure_text,
                                            explore=ai_score.EXPLORE_SHARE if automatic else 0.0, **extra)
        else:
            ai_status = "no_profile"
        for j in jobs:
            combine(j)
    finally:
        if pv_thread:
            pv_thread.join()  # never leave the Target ratings running (and writing their cache) past an error here
        if automatic and prof:
            try:
                night_spent(people.current(), ai_score.TIMINGS)
            except Exception as e:
                print(f"night budget not noted: {type(e).__name__}: {e}", flush=True)
    pv_status = ""
    if CFG["pivot_enabled"] and prof:
        applied = pivot.score_jobs([j for j in ok if "ai" in j["tracks"]], {**CFG["pivot"], "max_new_per_run": 0,
                                   **({"refresh_stale": True} if refresh else {})}, log=lambda m: None)
        pv_status = pv_run["status"] if new_claude else applied
        pu = [j for j in unmet if "ai" in j["tracks"]]
        if pu:
            pivot.score_jobs(pu, {**CFG["pivot"], "max_new_per_run": 0}, log=lambda m: None)
    return ai_status, pv_status

def merge_company_facts():
    """Combine company facts into data/company_facts.json: hand-researched ones (company_facts/part*.json, Glassdoor
    gd*.json) and the ones Claude looked up (company_facts/auto.json). Hand facts always win (company_research.merge)."""
    import company_research
    out = company_research.merge()
    _FACTS.clear()  # (Appeal reads the new facts from here on)
    return out

def research_company_facts():
    """Update's last step: Claude looks up facts for the companies that need them most (company_research.run), then
    every board is rebuilt from the catalog (no network) so Appeal and the Companies view use the new facts."""
    import company_research
    try:
        res = company_research.run(log=lambda m: print(m, flush=True),
                                   progress=lambda d, t: print(f"PROGRESS facts {d}/{t}", flush=True))
    except Exception as e:  # (run() doesn't raise; belt and braces: never fail the update over company facts)
        print(f"Company facts skipped: {type(e).__name__}: {e}", flush=True)
        return {"status": "error", "saved": 0, "failed": 0}, None
    boards = None
    if res.get("saved"):
        merge_company_facts()
        boards = recompute(None)
    return res, boards

def company_info(jobs):
    """Researched facts plus live hiring stats (from this person's board) for each company on it."""
    import statistics
    try:
        facts = json.load(open(os.path.join(DATA, "company_facts.json")))
    except Exception:
        facts = {}
    week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    by = {}
    for j in jobs:
        by.setdefault(j["company"], []).append(j)
    info = {}
    for co, js in by.items():
        mids = [j["salary_mid"] for j in js if j.get("salary_mid")]
        info[co] = {**facts.get(co, {}),
                    "open": len(js), "new_week": sum(1 for j in js if (j.get("first_seen") or "") >= week_ago),
                    "median_mid": round(statistics.median(mids)) if mids else None}
        hourly = [j for j in js if j.get("salary_mid") and j.get("pay_unit") == "hour"]
        if mids and 2 * len(hourly) > len(mids):     # an employer that mostly posts hourly pay: say it per hour
            info[co]["median_hr"] = round(statistics.median(j["salary_mid"] for j in hourly) / jobtext.HOURS_PER_YEAR, 2)
    return info

def ratings_summary(jobs):
    """How fresh Claude's ratings are among the jobs a person would actually look at (top 500 by score)."""
    top = sorted((j for j in jobs if j.get("req_status") != "unmet"), key=lambda j: -j["score"])[:500]
    return {"top": len(top), "rated": sum(1 for j in top if j.get("ai_fit") is not None),
            "stale": sum(1 for j in top if j.get("ai_stale")), "unrated": sum(1 for j in top if j.get("ai_fit") is None),
            "stale_all": sum(1 for j in jobs if j.get("ai_stale"))}

BOARD_HIDDEN = ("desc", "base_wp", "remote_strict", "remote_bare", "local_unnamed", "last_seen", "rel_x")

def _claude_ready():
    try:
        import claude_cli
        return bool(claude_cli.claude_ready())
    except Exception:
        return True  # can't tell: don't show the "connect Claude" prompts

def _has_relevance(pid, jobs):
    """Does this person have a what-to-look-for sheet (so jobs get a Relevance)? Asked of the sheet, not of the jobs:
    a board that is still empty (the first search has only just started) must already say yes, or the page opens
    sorted "Most appealing" and keeps saying so while the jobs that then arrive are in relevance order."""
    if any(j.get("rel") is not None for j in jobs):
        return True
    try:
        import lookfor
        return not lookfor.is_empty(lookfor.load(pid))
    except Exception:
        return False

def write_person(pid, jobs, summaries, prof, st, ai_status, pv_status):
    import ai_score, collections, report
    for j in jobs:
        for k in BOARD_HIDDEN:  # catalog bookkeeping the page doesn't use
            j.pop(k, None)
    jobs.sort(key=board_order)
    try:        # two job boards of one employer ("McKesson", "McKesson (2)") are shown and filtered under one name
        import catalog, names
        gm = names.group_map(catalog.companies())
        for j in jobs:
            g = gm.get(j["company"]) or names.group_name(j["company"])
            if g and g != j["company"]:
                j["co"] = g
    except Exception as e:
        print(f"(company names not grouped: {type(e).__name__}: {e})", flush=True)
    # titles nothing on the person's list names: kept apart ("N hidden because their titles aren't on your list · Show")
    off = [j for j in jobs if j.get("off_list") and "ai" not in (j.get("tracks") or [])]
    jobs[:] = [j for j in jobs if not j.get("off_list") or "ai" in (j.get("tracks") or [])]
    per_co =collections.Counter(j["company"] for j in jobs)
    watch, sets = people.company_sets(pid), company_sets_map()
    sums = [dict(s, matched=per_co.get(s["company"], 0)) for s in summaries if sets.get(s["company"], set()) & watch]
    payload = {"generated": dt.datetime.now().isoformat(timespec="minutes"), "salary_floor": CFG["salary_floor"],
               "ai_status": ai_status, "pivot_status": pv_status, "pivot_name": CFG["pivot"]["name"],
               "claude_ready": _claude_ready(), "ai_scope": st.get("target_scope") == "ai", "has_relevance": _has_relevance(pid, jobs),
               "rel_v": __import__("lookfor").BUILD,   # (the server rebuilds a board whose Relevance an earlier version made)
               "pivot_enabled": CFG["pivot_enabled"], "seniority": CFG["seniority"], "travel_max": st.get("travel_max") or "any",
               "target_name": st.get("target_name") or "Target", "target_summary": st.get("target_summary") or st.get("target_text", ""),
               "ai_scored": sum(1 for j in jobs if j.get("ai_fit") is not None),
               "person": {"id": pid, "name": people.name(pid)}, "people": people.load_index(),
               "current": {"base": st.get("current_base"), "label": st.get("current_label") or ""},
               "profile": {"name": prof.get("name"), "file": prof.get("_source_file"), "approved": prof.get("_approved")} if prof else None,
               "companies": sorted(sums, key=lambda s: s["company"]), "company_info": company_info(jobs),
               "ratings": ratings_summary(jobs),
               "rate_batch": {t: v["batch_size"] for t, v in ai_score.TIER_RUN.items()},
               "rate_limits": dict(ai_score.RUN_LIMITS), "jobs": jobs, "off_jobs": off}
    import io
    paths.dump_json_atomic(people.pdir("jobs.json", pid=pid), payload, indent=1)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=CSV_COLS, extrasaction="ignore")
    w.writerow({k: CSV_HEAD.get(k, k) for k in CSV_COLS})   # (plain column names in the file people open)
    for j in jobs:
        w.writerow({**j, "dmv_locations": "; ".join(j["dmv_locations"]), "locations": "; ".join(j["locations"]),
                    "pay": jobtext.pay_label(j.get("pay_min"), j.get("pay_max"), j.get("pay_unit")) if j.get("pay_min") is not None else ""})
    paths.write_atomic(people.pdir("jobs.csv", pid=pid), buf.getvalue(), newline="")
    report.build(payload, people.pdir("report.html", pid=pid))  # (written atomically too)
    print(f"{people.name(pid)}: {len(jobs)} jobs on the board", flush=True)

def company_summaries():
    """One row per company in the catalog for the board's Companies tab (matched is filled in per board)."""
    import catalog
    out = []
    for c in catalog.companies(include_paused=False):
        f = c["_fetch"]
        status = "ok" if f["status"] == "ok" else (f["error"] or "not fetched yet")
        out.append({"company": c["name"], "ats": c["ats"], "tier": c.get("tier"), "sector": c.get("sector"),
                    "raw_jobs": f["raw"] or 0, "matched": 0, "status": status, "secs": f["secs"] or 0})
    return out

def _kept_status(pid, prof=None):
    """Last Claude status shown on a board (kept when a rebuild doesn't call Claude, so a sign-in banner stays put).
    No approved profile: "no_profile". A kept "cli_logged_out" is checked again (cheap `claude auth status`), so
    signing in clears the banner on the next rebuild without waiting for a rating run."""
    import catalog
    if not prof:
        return ["no_profile", ""]
    st = catalog.get_meta(f"board_status:{pid}")
    if st is None:
        try:
            prev = json.load(open(people.pdir("jobs.json", pid=pid)))
            st = [prev.get("ai_status") or "ok", prev.get("pivot_status") or ""]
        except Exception:
            st = ["ok", ""]
    if st[0] in ("no_profile",):
        st = ["ok", st[1]]
    away = ("cli_logged_out", "no_claude")
    if any(x in st for x in away):
        try:
            import claude_cli
            if claude_cli.claude_ready():
                st = ["ok" if st[0] in away else st[0], "ok" if st[1] in away else st[1]]
                catalog.set_meta(f"board_status:{pid}", st)
        except Exception:
            pass
    return st

def new_unrated(pid, jobs):
    """(ids, first): jobs Claude would rate that just came onto this board (not on the board it replaces) and have no
    rating at all: the automatic Haiku check rates these. first is True when this person has no board yet, so every
    passing unrated job counts as new (the check still stops at the per-run Haiku cap). Uses ai_rs/ai_fit set by
    score_person, so call after it."""
    first = False
    try:
        prev = {j["id"] for j in json.load(open(people.pdir("jobs.json", pid=pid))).get("jobs", [])}
    except FileNotFoundError:
        prev, first = set(), True  # first board for this person (e.g. setup just finished)
    except Exception:
        return [], False  # can't tell what's new: don't guess
    return [j["id"] for j in jobs if j["id"] not in prev and (j.get("ai_rs") or "f")[0] == "-" and j.get("ai_fit") is None
            and not j.get("off_list")], first

def recompute(pids=None, rate=False, refresh=False, pool=None, opts=None):
    """Rebuild boards from the catalog: each person's filters over every open listing, requirements, Appeal and
    cached Claude ratings. rate=True also runs the Claude funnel over passing listings that are unrated
    (refresh=True: also ones rated with older info). Without rate it makes no network calls.
    One person's failure doesn't stop the others: their board is left as it was and the error is reported.
    Returns {pid: {"jobs": n, "unrated": n, "secs": s} or {"error": "..."}}."""
    import catalog, ai_score, traceback
    pids = [p for p in (pids or people.ids()) if p]
    if pool is None:
        reparse_stored()   # (one time after an update that reads postings better; no network, no Claude)
    pool = pool if pool is not None else catalog.open_listings(lazy=True)
    since = catalog.get_meta("last_full_fetch") or ""
    import lookfor
    sets = company_sets_map()
    summaries = company_summaries()
    out = {}
    for pid in pids:
        if not people.exists(pid):
            continue
        t0 = time.time()
        try:
            ai_score.TIMINGS.clear()
            pc, prof, st = person_cfg(pid)
            use_cfg(pc)
            people.set_current(pid, process_wide=True)
            jobs = select_for_person(pool, sets)
            descs = catalog.descriptions(j["id"] for j in jobs)
            for j in jobs:
                j["desc"] = descs.get(j["id"]) or j.get("snippet", "")
                j["new"] = bool(since) and (j.get("first_seen") or "") >= since
            apply_requirements(pid, jobs)
            set_pay_spread(jobs)
            # free, plain code: every job gets a Relevance (None with no sheet); fit: skills most postings mention count less
            relevance = lookfor.scorer(pid, prof).fit(jobs)
            for j in jobs:
                relevance.score(j)
            mark_off_list(jobs, relevance, st)
            if rate:
                print(f"--- {people.name(pid)}: {len(jobs)} listings pass their filters", flush=True)
            ai_status, pv_status = score_person(jobs, prof, new_claude=rate, refresh=refresh, opts=opts)
            # Relevance learns from the Match ratings now on the board (no Claude call; never part of a rating key):
            # when what it learned changed, every job is scored again and Best bets re-placed
            try:
                if lookfor.learn_from_claude(pid, jobs):
                    relevance = lookfor.scorer(pid, prof).fit(jobs)
                    for j in jobs:
                        relevance.score(j)
                        combine(j)
            except Exception as e:
                print(f"(Relevance did not learn from the ratings: {type(e).__name__}: {e})", flush=True)
            if rate:
                catalog.set_meta(f"board_status:{pid}", [ai_status, pv_status])
            else:
                ai_status, pv_status = _kept_status(pid, prof)
                fresh_ids, first = new_unrated(pid, jobs) if prof else ([], False)
                if fresh_ids:  # the server queues a quick Haiku check of just these (if the person allows it)
                    print("NEW_UNRATED " + json.dumps({"pid": pid, "ids": fresh_ids, "first": first}), flush=True)
            unrated = sum(1 for j in jobs if j.get("ai_fit") is None and not j.get("off_list"))
            write_person(pid, jobs, summaries, prof, st, ai_status, pv_status)   # (takes the off-list jobs out of `jobs`)
            out[pid] = {"jobs": len(jobs), "unrated": unrated, "secs": round(time.time() - t0, 1)}
            if rate:
                out[pid]["timings"] = list(ai_score.TIMINGS)
        except Exception as e:
            out[pid] = {"error": f"{type(e).__name__}: {e}"[:300], "secs": round(time.time() - t0, 1)}
            print(f"board rebuild failed for {pid} (kept the previous board): {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
    return out

def mark_off_list(jobs, relevance, st):
    """The title filter of a profile that goes by its own titles is its what-to-look-for sheet: a job whose title
    nothing on the sheet names (no entry matches; at most it shares everyday words with one) is not on the board and
    is never rated. Marked "off_list" here; write_person() keeps those apart (the page offers "N hidden ... Show", so
    nothing vanishes silently). A job that is there for the Target tab stays, on that tab only. Nothing is marked for
    a profile on the earlier built-in word list, or while the sheet is empty (then every title passes, as before)."""
    if (st or {}).get("title_rule") == "builtin" or getattr(relevance, "empty", True):
        return 0
    n = 0
    for j in jobs:
        ts = relevance.title_score(j.get("title") or "")
        if ts[0] and ts[6]:             # (an entry learned from Claude's ratings only re-orders: it is not the person's list)
            continue
        if "ai" in (j.get("tracks") or []):
            j["tracks"] = ["ai"]        # (stays for the Target tab; the page keeps it off the main list)
        j["off_list"] = True
        n += 1
    return n

def _failed(boards):
    return sorted(p for p, v in (boards or {}).items() if isinstance(v, dict) and v.get("error"))

def run_recompute(pids, kind="recompute"):
    """--recompute: rebuild boards with no fetching and no Claude. The run is always finished; exit code 3 and a
    RECOMPUTE_FAILED line name the people whose boards couldn't be rebuilt."""
    import catalog
    rid = catalog.start_run(kind, details={"people": pids or "all"})
    out, status = None, "error"
    try:
        out = recompute(pids or None)
        status = "partial" if _failed(out) else "ok"
    finally:
        catalog.finish_run(rid, status, errors=[{"person": p, "error": out[p]["error"]} for p in _failed(out)] or None,
                           details={"boards": out})
    if _failed(out):
        print("RECOMPUTE_FAILED " + ",".join(_failed(out)), flush=True)
        return 3
    return 0

TIER_NAMES = {"haiku": "Quick check (Haiku)", "sonnet": "Careful look (Sonnet)", "opus": "Best judgment (Opus)"}

def rate_opts(pid, args):
    """Re-rate panel options from the command line, or None for the classic re-rate. Budgets come from the run's own
    values (X%, top Y) or the person's settings, whether or not automatic rating is on: the person asked for this run."""
    if not args.tiers and not args.ids_file:
        return None
    import ai_score
    L = ai_score.RUN_LIMITS
    pr = people.prefs(pid)
    lim = rate_limits(pr, auto=False)   # the person asked for this run: their limits apply even with automatic rating off
    tiers = [t for t in ("haiku", "sonnet", "opus") if t in (args.tiers or "haiku").split(",")]
    if not tiers:
        raise SystemExit("--tiers needs haiku, sonnet and/or opus")
    pct = max(1, min(100, args.sonnet_pct if args.sonnet_pct is not None else (lim["sonnet_pct"] or 15)))
    top = max(1, min(2000, args.opus_top if args.opus_top is not None else (lim["opus_top"] or L["opus"])))
    full = len(tiers) == 3
    # Every run has the same fixed limits (ai_score.RUN_LIMITS), single-model runs included: a run that would rate
    # more stops at the limit, and pressing it again (or "Rate more" on the board) does the next batch.
    o = {"tiers": tiers, "force": bool(args.force) and not full, "pick": "funnel" if full else "best",
         "budgets": {"haiku": lim["haiku"] or L["haiku"], "sonnet_pct": pct, "sonnet_max": L["sonnet"], "opus_top": top,
                     "opus_max": L["opus"]},
         "target": not args.no_target, "pivot": {"max_new_per_run": lim["target"] or L["target"]}}
    if args.ids_file:
        # the automatic check of new jobs: Haiku only, only these jobs, only unrated ones, at most RUN_LIMITS["quick"]
        o.update(tiers=["haiku"], force=False, target=False, only_ids=set(json.load(open(args.ids_file))))
        o["budgets"]["haiku"] = min(int(pr["claude.haiku_per_night"]), L["quick"])
    return o

def rerate(pid, n=None, opts=None):
    """Separate from fetching: rebuild this person's board from the catalog, then have Claude rate passing listings
    that are unrated or were rated with older info. opts (rate_opts): a Re-rate panel run instead of the classic one."""
    import catalog
    if not people.exists(pid):
        print("No such profile.", flush=True); return 1
    if not person_cfg(pid)[1]:
        print("No approved resume profile yet.", flush=True); return 1
    rid = catalog.start_run("rerate", details={"person": pid, **({"tiers": opts["tiers"], "force": opts["force"]} if opts else {})})
    if opts is None or len(opts["tiers"]) == 3:
        print(f"Rating {people.name(pid)}'s jobs: a quick check first, then a closer look at the best ones", flush=True)
    elif opts.get("only_ids") is not None:
        import ai_score
        n_new, n_run = len(opts["only_ids"]), min(len(opts["only_ids"]), ai_score.RUN_LIMITS["quick"], int(opts["budgets"]["haiku"]))
        print(f"Quick check of {n_run} new jobs on {people.name(pid)}'s board (Haiku)" if n_run >= n_new else
              f"Quick check of the {n_run} most relevant of {n_new:,} new jobs on {people.name(pid)}'s board (Haiku)", flush=True)
    else:
        print(f"{' + '.join(TIER_NAMES[t] for t in opts['tiers'])} for {people.name(pid)}"
              f"{' (fresh look at every pick)' if opts['force'] else ' (only ratings that need it)'}", flush=True)
    out, status = None, "error"
    try:
        out = recompute([pid], rate=True, refresh=True, opts=opts)
        status = "error" if _failed(out) else "ok"
    finally:
        catalog.finish_run(rid, status, errors=[{"person": p, "error": out[p]["error"]} for p in _failed(out)] or None,
                           details={"boards": out})
    if _failed(out):
        print(f"Re-rating failed: {out[pid]['error']}", flush=True)
        return 3
    print("done", flush=True)
    return 0

# Job systems whose "remote" flag earlier versions read wrongly (Workday's "Office Worker (NOT Remote)" and "Remote work is
# not available"; schema.org TELECOMMUTE on in-person iCIMS jobs): a stored "remote" from them is kept only when the
# posting itself says so, and the row is read again from the board at the next fetch.
UNSURE_REMOTE_ATS = {"workday", "icims", "jsonld", "jazzhr", "breezy", "paylocity"}

def reparse_one(old, text, c):
    """One stored listing parsed again from its saved text with today's rules. Returns (listing or None, recheck):
    None when the posting turns out to be outside the US; recheck when its workplace needs the board's word again.
    The id, the first-seen date and everything Claude said about it are untouched."""
    j = dict(old)
    j["title"] = jobtext.clean_title(old.get("title"))
    text = jobtext.clean_text(text)
    locs = old.get("locations") or []
    base, recheck = old.get("base_wp", old.get("workplace", "")) or "", False
    if base == "remote":
        low = text.lower()
        said = (any(jobtext.remote_label(l) for l in locs) or jobtext.workplace_label(j["title"]) == "remote"
                or bool(REMOTE_DESC.search(low)))
        if any(l and jobtext.workplace_label(l) == "onsite" and not jobtext.remote_label(l) and "remote" in l.lower() for l in locs):
            base = "onsite"          # "Not Remote", "Remote: No"
        elif (c.get("ats") or "") in UNSURE_REMOTE_ATS and not said and int(old.get("pv") or 1) < 2:
            # (only rows stored before the fix: later ones were read correctly)
            # A real remote job must not leave the board while it waits for the next fetch: the flag is kept when the
            # posting says remote in other words ("Location: Remote - Houston, TX", "#LI-Remote", "eligible for full
            # time remote work", a "Home, TX" label) or names no place at all (the misread flags were all on jobs at a
            # named site), unless it also says on-site or hybrid in so many words. Either way the board is asked again.
            recheck = True
            weak = (bool(REMOTE_SAID.search(low)) or any(_HOME_LABEL.fullmatch(l or "") for l in locs)
                    or all(_NO_PLACE.fullmatch(l or "") for l in locs))
            if not weak or ONSITE_SAID.search(low):
                base = ""
    j["workplace"] = base
    # pay the board itself listed (not words from the text) is kept as it is; everything else is read again
    flat = lambda x: " ".join(str(x or "").split())
    kept = None
    if old.get("salary_max") is not None and old.get("salary_min") is not None and old.get("salary_text") \
            and flat(old["salary_text"]) not in flat(text) and flat(old["salary_text"]) not in flat(old.get("title")):
        kept = (old["salary_min"], old["salary_max"], old["salary_text"])
        if old.get("pay_unit") and old.get("pay_min") is not None:
            kept += (old["pay_unit"], old["pay_min"], old.get("pay_max") or old["pay_min"])
    j["desc"], j["salary"] = text, kept
    return prepare_listing(j, c), recheck

def reparse_stored(force=False, log=lambda m: print(m, flush=True)):
    """Read every open stored listing again from its saved text when the parsing rules are newer than the ones it
    was stored with (jobtext.PARSE_VERSION): pay (hourly, single values), level, remote / not remote, foreign remote
    jobs, the states its text names, blank lines, requisition codes in titles. No fetching and no Claude; listing ids
    don't change, so ratings, saved jobs and first-seen dates stay. Runs once (catalog meta "parse_version"); a run
    that is cut short picks up where it stopped. Returns how many listings were read again."""
    import catalog
    if not force and catalog.get_meta("parse_version") == jobtext.PARSE_VERSION:
        return 0
    mark = f'%"pv": {jobtext.PARSE_VERSION}%'
    with catalog.db() as con:
        q = "SELECT id FROM listings WHERE closed_at IS NULL" + ("" if force else " AND data NOT LIKE ?")
        ids = [r[0] for r in con.execute(q, () if force else (mark,))]
    if not ids:
        catalog.set_meta("parse_version", jobtext.PARSE_VERSION)
        return 0
    log(f"Reading {len(ids):,} saved postings again with the improved pay, level and location rules (one time; nothing is fetched and no ratings change)...")
    cos = {c["name"]: c for c in catalog.companies()}
    n = closed = 0
    gone = {}       # company -> postings closed as outside the US (for the employer-level "hires mostly abroad" mark)
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        with catalog.db() as con:
            rows = con.execute("SELECT id, company, data, desc, first_seen, last_seen, partial FROM listings WHERE id IN (%s)"
                               % ",".join("?" * len(chunk)), chunk).fetchall()
        parsed = []
        for r in rows:
            try:
                old = json.loads(r["data"])
                c = cos.get(old.get("company")) or {"name": old.get("company") or "", "ats": ""}
                if "_us_st" not in c:       # the states this employer's stored postings name (settles "Dublin" alone)
                    try:
                        c["_us_st"] = catalog.company_states(c["name"])
                    except Exception:
                        c["_us_st"] = set()
                new, recheck = reparse_one(old, r["desc"] or old.get("snippet", ""), c)
            except Exception as e:   # (one odd row never stops the rest; it is left as it was)
                log(f"  couldn't re-read {r['id'][:80]}: {type(e).__name__}: {e}")
                continue
            parsed.append((r, new, recheck))
        with catalog.db() as con:
            for r, new, recheck in parsed:
                if new is None:
                    con.execute("UPDATE listings SET closed_at=? WHERE id=?", (catalog.today(), r["id"]))
                    closed += 1
                    gone[r["company"]] = gone.get(r["company"], 0) + 1
                    continue
                new["id"] = r["id"]
                catalog.put_listing(con, new, first_seen=r["first_seen"], last_seen=r["last_seen"], partial=bool(r["partial"]))
                if recheck:
                    con.execute("UPDATE listings SET desc_hash='' WHERE id=?", (r["id"],))
        n += len(parsed)
    try:
        catalog.note_foreign(gone)
    except Exception as e:
        log(f"  (couldn't note which employers hire mostly abroad: {type(e).__name__}: {e})")
    catalog.set_meta("parse_version", jobtext.PARSE_VERSION)
    log(f"Done: {n:,} postings read again" + (f", {closed:,} closed (outside the US)" if closed else "") + ".")
    return n

def rescore():
    """Re-parse every open listing from its saved text (after a parsing change), then rebuild every board.
    No fetching, no new Claude calls. Writes go in short transactions so the server can keep reading."""
    import catalog
    rid = catalog.start_run("rescore")
    n, out, status = 0, None, "error"
    try:
        n = reparse_stored(force=True)
        out = recompute(None)
        status = "partial" if _failed(out) else "ok"
    finally:
        catalog.finish_run(rid, status, fetched=n, details={"boards": out})
    return 3 if _failed(out) else 0

def learn_company_name(name, board_title=None):
    """After a company's fetch: when its name is a board code, a placeholder or a run-together address, learn the
    employer's real name from its postings (names.learn) and rename it. Listing ids don't change. Never raises;
    returns the name the company has now."""
    try:
        import names
        return names.learn(name, board_title) or name
    except Exception as e:
        print(f"(couldn't work out a better name for {name}: {type(e).__name__}: {e})", flush=True)
        return name

if __name__ == "__main__":
    osdeps.ensure_utf8()
    sys.exit(main() or 0)
