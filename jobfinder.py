#!/usr/bin/env python3
"""DMV job finder: pull jobs from company ATS feeds, keep DMV (Reston or closer) + US-remote roles,
filter by title/salary, score against resume profile, and write data/jobs.json, jobs.csv, report.html.

Usage:  python3 jobfinder.py            # full refresh
        python3 jobfinder.py --only Leidos,Anduril
"""
import argparse, concurrent.futures as cf, csv, datetime as dt, html, json, os, re, sys, time
import osdeps
import urllib.request, urllib.error

import paths
HERE, DATA = paths.APP, paths.DATA
UA = "Mozilla/5.0 (dmv-jobfinder personal job search)"
CFG = paths.load_config()

import copy
import people
BASE_CFG = copy.deepcopy(CFG)

def person_cfg(pid):
    """Config for one person: base config + their settings + keywords from their approved resume profile."""
    c = copy.deepcopy(BASE_CFG)
    st = people.settings(pid)
    c["salary_floor"] = int(st["salary_floor"])
    c["salary_target"] = int(st["salary_target"]) if st.get("salary_target") else None
    c["seniority"] = {"mine": st["seniority_mine"], "band": st["seniority_band"]}
    pr = people.prefs(pid)
    per = pr["claude.per_update"] if pr["claude.auto_rate"] else 0
    c["ai"]["max_new_per_run"] = per
    c["funnel"] = {"haiku": pr["claude.haiku_per_night"] if pr["claude.auto_rate"] else 0,
                   "sonnet_pct": pr["claude.sonnet_pct"] if pr["claude.auto_rate"] else 0,
                   "opus_top": pr["claude.opus_top"] if pr["claude.auto_rate"] else 0, "sonnet_max": 2000}
    c["pivot"]["max_new_per_run"] = per
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
            if k and not any(x in (" " + k + " ") for x in c["title_exclude"]):
                inc.add(k)
        c["title_include"] = sorted(inc)
        for k in prof.get("fit_keywords", []):
            c["fit_keywords"].setdefault(k.lower().strip(), 8)
    return c, prof, st

def use_cfg(c):
    CFG.clear(); CFG.update(copy.deepcopy(c))

def fetch_cfg(cfgs):
    """Loose filter for the shared fetch: anything any person could want."""
    c = copy.deepcopy(BASE_CFG)
    if cfgs:
        c["title_include"] = sorted(set().union(*(x["title_include"] for x in cfgs)))
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
        if any(x in t for x in CFG["title_exclude"] if not any(a in t for a in allow if x in a or a in x)):
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
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=30) as r:
                return json.loads(r.read())
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
    return re.sub(r"[ \t\xa0]+", " ", s).strip()

# ---------------------------------------------------------------- classification
NON_US = ["canada", "toronto", "vancouver", "montreal", "united kingdom", " uk", "uk ", "london", "ireland", "dublin",
          "germany", "berlin", "munich", "france", "paris", "spain", "madrid", "netherlands", "amsterdam", "poland",
          "india", "bangalore", "bengaluru", "hyderabad", "pune", "singapore", "japan", "tokyo", "australia", "sydney",
          "brazil", "mexico", "argentina", "colombia", "israel", "tel aviv", "emea", "apac", "europe", "latam",
          "korea", "taiwan", "philippines", "costa rica", "romania", "portugal", "sweden", "denmark", "switzerland",
          "italy", "czech", "serbia", "ukraine", "new zealand", "south africa", "uae", "dubai", "saudi", "qatar"]
REMOTE_WORDS = ["remote", "anywhere", "virtual", "telework", "work from home", "wfh"]

def near(loc):
    """Is this location inside anyone's search area (the current CFG): a home radius, or the DC-area list."""
    if CFG.get("legacy_area", True) and is_close(loc):
        return True
    if CFG.get("homes"):
        import geo
        return any(geo.within([loc], h, r)[0] for h, r in CFG["homes"])
    return False

def is_close(loc):
    l = " " + loc.lower() + " "
    if any(p in l for p in CFG["close_places"]):
        return True
    has_va = bool(re.search(r"\bva\b|virginia", l))
    return has_va and any(re.search(r"\b" + p + r"\b", l) for p in CFG["close_places_need_va"])

def is_remote_us(loc):
    l = " " + loc.lower() + " "
    if not any(w in l for w in REMOTE_WORDS):
        return False
    return not any(c in l for c in NON_US)

US_STATES = ("alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
             "kentucky|louisiana|maine|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
             "new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|"
             "tennessee|texas|utah|vermont|west virginia|wisconsin|wyoming")
ELSEWHERE = re.compile(r"\b(" + US_STATES + r")\b|,\s*(?!dc\b|va\b|md\b)[a-z]{2}\b(?:\s|$|,)", re.I)

def looks_local_unnamed(loc):
    """A location label that names no other state or country ("Main Campus", "125 E St NW 1st Floor")."""
    l = (loc or "").strip().lower()
    return bool(l) and not ELSEWHERE.search(l) and not any(c in l for c in NON_US) and "remote" not in l

def classify(job):
    """Returns 'remote' / 'dmv' / None. Sets job['dmv_locations']."""
    locs = job["locations"]
    close = [l for l in locs if near(l)]
    job["dmv_locations"] = close
    wp = job.get("workplace") or ""
    remote = wp == "remote" and not any(any(c in l.lower() for c in NON_US) for l in locs if l) \
        or any(is_remote_us(l) for l in locs)
    if wp == "remote" and locs and all(any(c in l.lower() for c in NON_US) for l in locs):
        remote = False
    if not remote and not close:
        bare_us = any(re.fullmatch(r"\s*(us|usa|u\.s\.|united states( of america)?|dragos usa)\s*", l.lower()) for l in locs)
        d = job.get("desc", "").lower()
        if bare_us and (job.get("tier") == "remote_first" or re.search(
                r"fully remote|remote[- ]first|100% remote|remote position|remote role|work remotely|remote within the (us|united states)|remote \(us\)|this role is remote|remote, us", d)):
            remote = True
    if remote:
        job["workplace"] = "remote"
        return "remote"
    if close:
        return "dmv"
    if job.get("tier") == "dmv_hq" and locs and all(looks_local_unnamed(l) for l in locs if l):
        job["dmv_locations"] = [f"{l} (DC area)" for l in locs if l][:3]
        return "dmv"
    return None

def title_ok(title):
    t = " " + title.lower() + " "
    if any(x in t for x in CFG["title_exclude"]):
        return False
    if any(re.search(rx, title.lower().strip()) for rx in CFG["title_exclude_regex"]):
        return False
    return any(x in t for x in CFG["title_include"])

def pivot_title_ok(title):
    """Wider title filter for AI companies: adds go-to-market, policy, threat intel and trust & safety titles."""
    pv = CFG.get("pivot", {})
    t = " " + title.lower() + " "
    allow = pv.get("title_allow", [])
    if any(x in t for x in CFG["title_exclude"] if not any(a in t for a in allow if x in a or a in x)):
        return False
    if any(re.search(rx, title.lower().strip()) for rx in CFG["title_exclude_regex"]):
        return False
    return any(x in t for x in CFG["title_include"] + pv.get("title_extra", []))

MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{2,3}(?:\.\d+)?\s?[kK]|\d{2,3})"
RANGE_RE = re.compile(MONEY + r"\s*(?:USD|usd)?\s*(?:-|–|—|to)\s*" + MONEY + r"(\s*(?:/|per)\s*(?:hr|hour))?")

def money(s):
    s = s.replace(",", "").replace(" ", "")
    if s[-1] in "kK":
        return float(s[:-1]) * 1000
    return float(s)

FROM_TO_RE = re.compile(r"from\s+" + MONEY + r"(?:/year)?[^$]{0,80}?(?:up )?to\s+" + MONEY, re.I)

def parse_salary(text):
    best = None
    for m in FROM_TO_RE.finditer(text or ""):
        lo, hi = money(m.group(1)), money(m.group(2))
        if 30000 <= lo <= hi <= 2_000_000 and (best is None or hi > best[1]):
            best = (lo, hi, m.group(0).strip()[:80])
    for m in RANGE_RE.finditer(text or ""):
        lo, hi = money(m.group(1)), money(m.group(2))
        if m.group(3) or hi < 400:  # hourly
            lo, hi = lo * 2080, hi * 2080
        if hi < 1000:  # bare numbers like "$120 - 180" meaning k
            lo, hi = lo * 1000, hi * 1000
        if not (30000 <= lo <= hi <= 2_000_000):
            continue
        if best is None or hi > best[1]:
            best = (lo, hi, m.group(0).strip())
    return best

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
    m = job["ai_fit"] if job.get("ai_fit") is not None else 50
    job["score"] = round(math.sqrt(max(0, job["appeal"]) * max(0, m)))

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
        job["salary_min"] = job["salary_max"] = None
        job["salary_text"] = ""
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
IC_MANAGER = r"(?:product|program|project|account|success|partner|partnership|relationship|case|community|portfolio|delivery|release|marketing|channel|alliance|territory|solutions?|implementation|deployment|engagement|technical program|technical account|technical product|risk|compliance|vendor|contract|grants?|data|knowledge|content|campaign|brand|events?|office|facility|property|operations program)"
LEVEL_NAMES = {2: "Mid-level", 3: "Senior", 4: "Lead / Manager", 5: "Principal / Sr. Manager", 6: "Director", 7: "VP / Executive"}
def title_level(title):
    t = " " + re.sub(r"[^a-z0-9/&+ ]", " ", title.lower()) + " "
    t = re.sub(r"\s+", " ", t)
    if re.search(r" (vp|svp|evp|vice president|chief|cto|ciso|cio|coo|distinguished|fellow) ", t) or re.search(r" (senior|sr) director ", t):
        return 7
    if re.search(r" (director|head of|head) ", t) or re.search(r" (senior|sr) principal ", t):
        return 6
    if re.search(r" (principal|group manager|group product manager|senior staff|sr staff|senior manager|sr manager|senior engineering manager) ", t) or re.search(r" (v|level 5) ", t):
        return 5
    if re.search(r" (staff|lead|tech lead|team lead|supervisor|iv|level 4) ", t):
        return 4
    m = re.search(r" (\w+ )?(\w+ )?manager ", t)
    if m and not re.search(IC_MANAGER + r" manager ", t):
        return 4  # people manager (engineering manager, manager of X, ...)
    if re.search(r" (senior|sr|iii|level 3) ", t):
        return 3
    if re.search(r" (mid|ii|level 2) ", t):
        return 2
    m = re.search(r" ([1-6]) $", t)  # "Full-stack Engineer 4"
    if m:
        return max(2, min(6, int(m.group(1))))
    return None
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years|yrs)", re.I)
def years_required(text):
    best = None
    for m in YEARS.finditer(text or ""):
        ctx = text[m.end(): m.end() + 60].lower()
        pre = text[max(0, m.start() - 40): m.start()].lower()
        if "experience" not in ctx and "experience" not in pre:
            continue
        y = int(m.group(1))
        if re.search(r"prefer|nice to have|bonus|plus\b|desired|ideal", text[max(0, m.start() - 200): m.start()].lower()):
            continue  # preferred qualifications overstate the bar
        if 1 <= y <= 20 and (best is None or y > best):  # the main (largest) required minimum
            best = y
    return best
def years_level(y):
    if y is None: return None
    return 2 if y <= 3 else 3 if y <= 6 else 4 if y <= 9 else 5 if y <= 13 else 6
def seniority(title, text):
    lv = title_level(title)
    if lv is not None:
        return lv, "title"
    y = years_required(text)
    return years_level(y), ("years" if y is not None else "")

TRAVEL_QOL = {"heavy": -20, "moderate": -10, "some": -5, "light": -3, "none": 0, "": 0}

def enrich(job, text):
    """Everything derived from the posting text, after salary parsing."""
    band(job)
    if not job.get("workplace"):
        job["workplace"] = workplace_from_text(text)
    job["clearance"] = clearance(text)
    job["scif"] = bool(re.search(r"\bscif\b", (text or "").lower()))
    job["travel"], job["travel_pct"], job["travel_text"] = travel(text)
    job["level"], job["level_src"] = seniority(job["title"], text)
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
        pay = 50 + (mid - floor) / 2000
        if target and mid >= target:
            pay += 10
    if job.get("wide_band"):
        pay -= 5
    wp = {"remote": 100, "hybrid": 75, "onsite": 55}.get(job.get("workplace") or "", 60)
    nm = job.get("near_miles")
    if nm is not None and job.get("workplace") != "remote" and nm > 20:
        wp -= min(20, (nm - 20) / 1.5)
    L, sen = job.get("level"), CFG.get("seniority") or {}
    band, mine = sen.get("band") or [3, 5], sen.get("mine") or 4
    lvl = 75 if L is None else 100 if L == mine else 85 if band[0] <= L <= band[1] else 55
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

# ---------------------------------------------------------------- fetchers (each yields normalized dicts)
def J(company, title, url, locations, workplace="", salary=None, desc="", posted="", dept="", jid=""):
    return {"company": company["name"], "sector": company.get("sector", ""), "tier": company.get("tier", ""),
            "title": (title or "").strip(), "url": url, "locations": list(dict.fromkeys(l.strip() for l in locations if l and l.strip())),
            "workplace": workplace, "salary": salary, "desc": desc, "posted": posted, "dept": dept,
            "id": f'{company["name"]}::{jid or url}'}

def f_greenhouse(c):
    d = http_json(f'https://boards-api.greenhouse.io/v1/boards/{c["token"]}/jobs?content=true')
    for j in d.get("jobs", []):
        locs = [(j.get("location") or {}).get("name", "")]
        locs += [o.get("location") or o.get("name") for o in j.get("offices", [])]
        locs = [p.strip() for l in locs if l for p in re.split(r"\s*[|;]\s*", l)]
        desc = strip_html(j.get("content"))
        wp = ""
        for m in j.get("metadata") or []:
            v = str(m.get("value") or "").lower()
            if "remote" in v: wp = "remote"
            elif "hybrid" in v: wp = "hybrid"
            elif "on-site" in v or "onsite" in v or "in office" in v: wp = "onsite"
        yield J(c, j.get("title"), j.get("absolute_url"), locs, wp, None, desc,
                (j.get("first_published") or j.get("updated_at") or "")[:10],
                ", ".join(x["name"] for x in j.get("departments", [])), j.get("id"))

def f_lever(c):
    d = http_json(f'https://api.lever.co/v0/postings/{c["token"]}?mode=json')
    for j in d:
        cat = j.get("categories", {})
        locs = cat.get("allLocations") or [cat.get("location", "")]
        if j.get("country") and j["country"] != "US":
            locs = [f'{l} ({j["country"]}) europe' for l in locs]  # "europe" = non-US marker for classify()
        wp = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(j.get("workplaceType") or "", "")
        desc = " ".join([j.get("descriptionPlain") or j.get("descriptionBodyPlain") or "", j.get("additionalPlain") or ""] +
                        [strip_html(x.get("content")) for x in j.get("lists", [])])
        sal = None
        sr = j.get("salaryRange")
        if sr and sr.get("max") and (sr.get("currency") in (None, "USD")):
            mult = 2080 if sr.get("interval", "").startswith("per-hour") else 1
            sal = (sr["min"] * mult, sr["max"] * mult, "listed range")
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

def _wd_location_facets(facets):
    """Walk Workday facet tree; return {facetParameter: [ids]} for DMV/remote location values."""
    out = {}
    def walk(fs):
        for f in fs or []:
            param = f.get("facetParameter", "")
            vals = f.get("values") or []
            if vals and isinstance(vals[0], dict) and "facetParameter" in vals[0]:
                walk(vals); continue
            if "remote" in param.lower():
                ids = [v["id"] for v in vals if "remote" in v.get("descriptor", "").lower()]
                if ids:
                    out[param] = ids
            elif "location" in param.lower() and "country" not in param.lower():
                ids = [v["id"] for v in vals if near(v.get("descriptor", "")) or is_remote_us(v.get("descriptor", ""))]
                if ids:
                    out[param] = ids
    walk(facets)
    return out

def f_workday(c):
    base = f'https://{c["host"]}' if c.get("host") else f'https://{c["tenant"]}.{c["wd"]}.myworkdayjobs.com'
    api = f'{base}/wday/cxs/{c["tenant"]}/{c["site"]}'
    first = http_json(api + "/jobs", {"limit": 20, "offset": 0, "searchText": c.get("search", ""), "appliedFacets": {}})
    facets = _wd_location_facets(first.get("facets"))
    postings, seen = [], set()
    # Workday ORs values within a facet; query each location facet separately and merge.
    queries = [{k: v} for k, v in facets.items()] or [{}]
    # A DC-headquartered employer whose location labels we can't read ("Main Campus") gets its full list;
    # classify() then keeps anything that doesn't name another state or country.
    if c.get("tier") == "dmv_hq" and (not any("location" in k.lower() for k in facets) or first.get("total", 0) <= 600):
        queries = [{}]
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
            if off >= min(total, 2000) or not d.get("jobPostings"):
                break
    # Prefilter by title before fetching details.
    postings = [p for p in postings if title_ok(p.get("title", ""))]

    def detail(p):
        try:
            d = http_json(api + p["externalPath"]).get("jobPostingInfo", {})
        except Exception:
            d = {}
        locs = [d.get("location") or p.get("locationsText", "")] + (d.get("additionalLocations") or [])
        desc = strip_html(d.get("jobDescription", ""))
        rt = (d.get("remoteType") or p.get("remoteType") or "").lower()
        wp = "remote" if "remote" in rt else "hybrid" if "hybrid" in rt else "onsite" if ("site" in rt or "office" in rt) else ""
        return J(c, p.get("title"), f'{base}/en-US/{c["site"]}{p["externalPath"]}', locs, wp, None, desc,
                 d.get("startDate", "") or "", "", p["externalPath"])
    with cf.ThreadPoolExecutor(6) as ex:
        yield from ex.map(detail, postings)

FETCHERS = {"greenhouse": f_greenhouse, "lever": f_lever, "ashby": f_ashby,
            "smartrecruiters": f_smartrecruiters, "workday": f_workday}
def load_extra():
    if os.path.exists(os.path.join(HERE, "extra_fetchers.py")):
        sys.path.insert(0, HERE)
        import extra_fetchers
        FETCHERS.update(extra_fetchers.FETCHERS)
    if os.path.exists(os.path.join(HERE, "smb_fetchers.py")):
        import smb_fetchers
        FETCHERS.update(smb_fetchers.FETCHERS)

# ---------------------------------------------------------------- pipeline
def process(c):
    t0 = time.time()
    raw = kept = 0
    out = []
    try:
        for j in FETCHERS[c["ats"]](c):
            raw += 1
            cur_ok = title_ok(j["title"])
            ai_ok = any(target_ok(st, c.get("ai_track"), j["title"]) for st in CFG.get("targets", []))
            if not (cur_ok or ai_ok):
                continue
            j["tracks"] = (["current"] if cur_ok else []) + (["ai"] if ai_ok else [])
            j["ai_track"] = c.get("ai_track", "")
            where = classify(j)
            if not where:
                continue
            text = j["desc"]
            if not j["salary"]:
                j["salary"] = parse_salary(text)
            if j["salary"]:
                j["salary_min"], j["salary_max"], j["salary_text"] = round(j["salary"][0]), round(j["salary"][1]), j["salary"][2]
            else:
                j["salary_min"] = j["salary_max"] = None; j["salary_text"] = ""
            del j["salary"]
            if j["salary_max"] is not None and j["salary_max"] < CFG["salary_floor"] and not CFG["keep_below_floor"]:
                continue
            if j["salary_max"] is None and not CFG["keep_unlisted_salary"]:
                continue
            enrich(j, text)
            if j["salary_max"] is None and not CFG["keep_unlisted_salary"]:
                continue
            score(j)
            j["snippet"] = text[:600]
            out.append(j); kept += 1
        status = "ok"
    except Exception as e:
        status = f"error: {type(e).__name__}: {e}"[:200]
    return {"company": c["name"], "ats": c["ats"], "tier": c.get("tier"), "sector": c.get("sector"),
            "raw_jobs": raw, "matched": kept, "status": status, "secs": round(time.time() - t0, 1)}, out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company names")
    ap.add_argument("--rescore", action="store_true", help="recompute scores from saved data without fetching")
    ap.add_argument("--rerate", metavar="PID", help="have Claude re-rate this person's jobs rated with older info (no fetching)")
    ap.add_argument("--n", type=int, default=300, help="how many jobs --rerate may send to Claude")
    args = ap.parse_args()
    people.ensure_migrated(BASE_CFG)
    if args.rescore:
        return rescore()
    if args.rerate:
        return rerate(args.rerate, args.n)
    use_cfg(fetch_cfg([person_cfg(pid)[0] for pid in people.ids()]))
    load_extra()
    companies = paths.load_companies()
    if args.only:
        want = {x.strip().lower() for x in args.only.split(",")}
        companies = [c for c in companies if c["name"].lower() in want]
    if not companies:
        print("No companies to check yet: add some to the company list, then run the update again.", flush=True)
        return 0
    os.makedirs(DATA, exist_ok=True)
    seen_path = os.path.join(DATA, "seen.json")
    seen = json.load(open(seen_path)) if os.path.exists(seen_path) else {}
    today = dt.date.today().isoformat()

    summaries, jobs = [], []
    # Workday tenants share one per-IP rate limit, so they get their own small lane; everything else runs wide.
    with cf.ThreadPoolExecutor(12) as fast, cf.ThreadPoolExecutor(4) as slow:
        futs = {(slow if c["ats"] == "workday" else fast).submit(process, c): c
                for c in companies if c["ats"] in FETCHERS}
        for n, f in enumerate(cf.as_completed(futs), 1):
            s, js = f.result()
            summaries.append(s); jobs.extend(js)
            print(f'{s["company"]:<24} {s["ats"]:<15} raw={s["raw_jobs"]:<5} matched={s["matched"]:<4} {s["status"]} ({s["secs"]}s)', flush=True)
            print(f"PROGRESS fetch {n}/{len(futs)}", flush=True)

    # dedupe on (company, title, url)
    uniq = {}
    for j in jobs:
        uniq.setdefault((j["company"], j["title"], j["url"]), j)
    jobs = list(uniq.values())
    # full descriptions live in their own file (used by tailoring), not in the page
    desc_path = os.path.join(DATA, "descriptions.json")
    descs = json.load(open(desc_path)) if args.only and os.path.exists(desc_path) else {}
    descs.update({j["id"]: (j.get("desc") or "")[:12000] for j in jobs})
    json.dump(descs, open(desc_path, "w"))
    for j in jobs:
        j["first_seen"] = seen.setdefault(j["id"], today)
        j["new"] = j["first_seen"] == today
    json.dump(seen, open(seen_path, "w"))
    if not args.only:
        import target
        target.write_market(jobs)
    only = {c["name"] for c in companies} if args.only else None
    for pid in people.ids():
        build_person(pid, jobs, summaries, only)
    print(f"\n{len(jobs)} jobs fetched from {len(summaries)} companies; boards built for {len(people.ids())} profile(s)")

CSV_COLS = ["req_status", "score", "pv_score", "pv_label", "pv_now", "pv_later", "ai_label", "ai_asis", "ai_fit", "ai_reason", "ai_tailor",
            "fit_score", "comp_score", "qol_score", "company", "title", "level", "workplace", "dmv_locations", "locations",
            "salary_min", "salary_max", "salary_mid", "wide_band", "travel", "travel_pct", "clearance", "scif", "posted",
            "first_seen", "sector", "url"]

LIST_SHORT = {"tech": "Tech & AI", "ops": "Business & corporate", "nonprofit": "Nonprofit & mission-driven"}

def company_lists_payload(pid, jobs, sets, watch):
    """Which of this person's company lists each company on the board belongs to (for the Company list filter)."""
    own = f"own-{pid}"
    names = {j["company"] for j in jobs}
    by_co = {}
    for n in names:
        s = sets.get(n, {"tech"}) & watch
        by_co[n] = sorted("own" if x in (own, "all") else x for x in s)
    used = sorted({x for v in by_co.values() for x in v}, key=lambda x: list(LIST_SHORT).index(x) if x in LIST_SHORT else 99)
    return {"options": [{"id": x, "label": LIST_SHORT.get(x, "Added by you")} for x in used], "by_company": by_co}

def company_sets_map():
    try:
        return {c["name"]: set(c.get("sets") or ["tech"]) for c in paths.load_companies()}
    except Exception:
        return {}

def select_for_person(pool):
    """Apply the current person's company lists, title filter and pay floor (CFG is theirs) to the shared pool; returns copies."""
    out = []
    watch, sets = people.company_sets(), company_sets_map()
    for j0 in pool:
        if not (sets.get(j0["company"], {"tech"}) & watch):
            continue
        cur_ok = title_ok(j0["title"])
        ai_ok = any(target_ok(st, j0.get("ai_track"), j0["title"]) for st in CFG.get("targets", []))
        if not (cur_ok or ai_ok):
            continue
        if j0.get("salary_max") is not None and j0["salary_max"] < CFG["salary_floor"] and not CFG["keep_below_floor"]:
            continue
        # The shared pool covers everyone's areas; keep only what's inside this person's.
        locs = j0.get("locations") or []
        mine = [l for l in locs if near(l)]
        dc_fallback = bool(j0.get("dmv_locations")) and all(str(l).endswith("(DC area)") for l in j0["dmv_locations"]) \
            and (CFG.get("legacy_area", True) or any(__import__("geo").within(["Washington, DC"], h, r + 10)[0] for h, r in CFG.get("homes", [])))
        remote = j0.get("workplace") == "remote"
        if not (mine or dc_fallback or (remote and CFG.get("remote_ok", True))):
            continue
        wps = CFG.get("workplaces") or ["onsite", "hybrid", "remote"]
        if j0.get("workplace") and j0["workplace"] not in wps and not (j0["workplace"] == "remote" and mine):
            continue
        j = dict(j0)
        if not dc_fallback:
            j["dmv_locations"] = mine
        j["tracks"] = (["current"] if cur_ok else []) + (["ai"] if ai_ok else [])
        for k in [k for k in j if k.startswith(("ai_", "pv_"))]:
            if k != "ai_track":
                del j[k]
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
    try:
        m = json.load(open(people.pdir("marks.json", pid=pid)))
        return {k for k, v in m.items() if v in ("saved", "applied")}
    except Exception:
        return set()

def eligible_for_claude(j):
    """Skip jobs the person can't or won't pursue: unmet hard requirements, or levels well outside their band."""
    if j.get("req_status") == "unmet":
        return False
    L, band = j.get("level"), (CFG.get("seniority") or {}).get("band") or [3, 5]
    return L is None or band[0] - 1 <= L <= band[1] + 1

def score_person(jobs, prof, new_claude=True, refresh=False):
    """Appeal for every job, then Match from Claude: the Haiku -> Sonnet -> Opus funnel (cache only if not new_claude)."""
    import ai_score, pivot
    for j in jobs:
        score(j)
    ok = [j for j in jobs if j.get("req_status") != "unmet"]
    unmet = [j for j in jobs if j.get("req_status") == "unmet"]
    if prof:
        budgets = CFG.get("funnel") or {}
        if not new_claude:
            budgets = {"haiku": 0, "sonnet_pct": 0, "opus_top": 0}
        ai_status = ai_score.run_funnel(jobs, budgets, refresh=refresh, saved=saved_ids(), eligible=eligible_for_claude,
                                        log=lambda m: print(m, flush=True))
    else:
        ai_status = "no_profile"
    for j in jobs:
        combine(j)
    pv_status = ""
    if CFG["pivot_enabled"] and prof:
        cap = ({"refresh_stale": True} if refresh else {}) if new_claude else {"max_new_per_run": 0}
        pv_status = pivot.score_jobs([j for j in ok if "ai" in j["tracks"]], {**CFG["pivot"], **cap}, log=lambda m: print(m, flush=True))
        pu = [j for j in unmet if "ai" in j["tracks"]]
        if pu:
            pivot.score_jobs(pu, {**CFG["pivot"], "max_new_per_run": 0}, log=lambda m: None)
    return ai_status, pv_status

def merge_company_facts():
    """Combine researched company facts (data/company_facts/part*.json) into data/company_facts.json."""
    import glob
    out = {}
    for f in sorted(glob.glob(os.path.join(DATA, "company_facts", "part*.json"))):
        try:
            out.update(json.load(open(f)))
        except Exception as e:
            print(f"skipping {os.path.basename(f)}: {e}", flush=True)
    for f in sorted(glob.glob(os.path.join(DATA, "company_facts", "gd*.json"))):
        if os.path.basename(f).startswith("gdtodo"):
            continue
        try:
            for co, g in json.load(open(f)).items():
                out.setdefault(co, {}).update(g)  # Glassdoor ratings, looked up once by hand-style search
        except Exception as e:
            print(f"skipping {os.path.basename(f)}: {e}", flush=True)
    if out:
        json.dump(out, open(os.path.join(DATA, "company_facts.json"), "w"), indent=1)
    return out

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
    return info

def ratings_summary(jobs):
    """How fresh Claude's ratings are among the jobs a person would actually look at (top 500 by score)."""
    top = sorted((j for j in jobs if j.get("req_status") != "unmet"), key=lambda j: -j["score"])[:500]
    return {"top": len(top), "rated": sum(1 for j in top if j.get("ai_fit") is not None),
            "stale": sum(1 for j in top if j.get("ai_stale")), "unrated": sum(1 for j in top if j.get("ai_fit") is None),
            "stale_all": sum(1 for j in jobs if j.get("ai_stale"))}

def write_person(pid, jobs, summaries, prof, st, ai_status, pv_status):
    import collections, report
    for j in jobs:
        j.pop("desc", None)
    jobs.sort(key=lambda j: -j["score"])
    per_co = collections.Counter(j["company"] for j in jobs)
    watch, sets = people.company_sets(pid), company_sets_map()
    sums = [dict(s, matched=per_co.get(s["company"], 0)) for s in summaries if sets.get(s["company"], {"tech"}) & watch]
    payload = {"generated": dt.datetime.now().isoformat(timespec="minutes"), "salary_floor": CFG["salary_floor"],
               "ai_status": ai_status, "pivot_status": pv_status, "pivot_name": CFG["pivot"]["name"],
               "pivot_enabled": CFG["pivot_enabled"], "seniority": CFG["seniority"],
               "target_name": st.get("target_name") or "Target", "target_summary": st.get("target_summary") or st.get("target_text", ""),
               "ai_scored": sum(1 for j in jobs if j.get("ai_fit") is not None),
               "person": {"id": pid, "name": people.name(pid)}, "people": people.load_index(),
               "current": {"base": st.get("current_base"), "label": st.get("current_label") or ""},
               "profile": {"name": prof.get("name"), "file": prof.get("_source_file"), "approved": prof.get("_approved")} if prof else None,
               "companies": sorted(sums, key=lambda s: s["company"]), "company_info": company_info(jobs),
               "lists": company_lists_payload(pid, jobs, sets, watch), "ratings": ratings_summary(jobs), "jobs": jobs}
    json.dump(payload, open(people.pdir("jobs.json", pid=pid), "w"), indent=1)
    with open(people.pdir("jobs.csv", pid=pid), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore"); w.writeheader()
        for j in jobs:
            w.writerow({**j, "dmv_locations": "; ".join(j["dmv_locations"]), "locations": "; ".join(j["locations"])})
    report.build(payload, people.pdir("report.html", pid=pid))
    print(f"{people.name(pid)}: {len(jobs)} jobs on the board", flush=True)

def build_person(pid, pool, summaries, only=None):
    pc, prof, st = person_cfg(pid)
    use_cfg(pc)
    people.set_current(pid, process_wide=True)
    print(f"--- {people.name(pid)}", flush=True)
    jobs = select_for_person(pool)
    apply_requirements(pid, jobs)
    ai_status, pv_status = score_person(jobs, prof)
    prev_path = people.pdir("jobs.json", pid=pid)
    if only and os.path.exists(prev_path):
        # partial refresh: keep this person's other companies from last time (cached scores only)
        prev = json.load(open(prev_path))
        descs = load_descriptions()
        old = [dict(j, desc=descs.get(j["id"], "")) for j in prev["jobs"] if j["company"] not in only]
        watch, sets = people.company_sets(pid), company_sets_map()
        old = [j for j in old if sets.get(j["company"], {"tech"}) & watch]  # drop lists this person no longer watches
        for j in old:
            j["new"] = False
        apply_requirements(pid, old)
        score_person(old, prof, new_claude=False)
        jobs += old
        summaries = [s for s in prev["companies"] if s["company"] not in only] + summaries
    write_person(pid, jobs, summaries, prof, st, ai_status, pv_status)

def load_descriptions():
    """Full posting text by job id ({} before the first update has run)."""
    try:
        return json.load(open(os.path.join(DATA, "descriptions.json")))
    except FileNotFoundError:
        return {}

def rerate(pid, n):
    """Separate from fetching: re-rate this person's best jobs whose Claude rating was made with older info."""
    import ai_score, pivot
    descs = load_descriptions()
    pc, prof, st = person_cfg(pid)
    use_cfg(pc)
    people.set_current(pid, process_wide=True)
    if not prof:
        print("No approved resume profile yet.", flush=True); return 1
    if not os.path.exists(people.pdir("jobs.json", pid=pid)):
        print("No jobs on this board yet: run an update first.", flush=True); return 0
    prev = json.load(open(people.pdir("jobs.json", pid=pid)))
    jobs = prev["jobs"]
    for j in jobs:
        j["desc"] = descs.get(j["id"]) or j.get("snippet", "")
        j.setdefault("tracks", ["current"])
    apply_requirements(pid, jobs)
    for j in jobs:
        score(j)
    print(f"Re-rating {people.name(pid)}'s jobs with the latest info (Haiku check, then Sonnet and Opus for the best)", flush=True)
    ai_status, pv_status = score_person(jobs, prof, new_claude=True, refresh=True)
    write_person(pid, jobs, prev["companies"], prof, st, ai_status, pv_status)
    print("done", flush=True)

def rescore():
    """Re-derive levels, pay, travel and scores for every profile from saved data (no fetching, no new Claude calls)."""
    descs = load_descriptions()
    for pid in people.ids():
        path = people.pdir("jobs.json", pid=pid)
        if not os.path.exists(path):
            continue
        pc, prof, st = person_cfg(pid)
        use_cfg(pc)
        people.set_current(pid, process_wide=True)
        prev = json.load(open(path))
        jobs = prev["jobs"]
        for j in jobs:
            text = descs.get(j["id"]) or j.get("snippet", "")
            enrich(j, text)
            j["desc"] = text
            j.setdefault("tracks", ["current"])
        apply_requirements(pid, jobs)
        ai_status, pv_status = score_person(jobs, prof, new_claude=False)
        write_person(pid, jobs, prev["companies"], prof, st, prev.get("ai_status", ai_status), prev.get("pivot_status", pv_status))

if __name__ == "__main__":
    osdeps.ensure_utf8()
    main()
