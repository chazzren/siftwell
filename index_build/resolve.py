"""Employers from public lists, tied to their careers sites without an LLM or a paid API.

Big local employers (hospitals, colleges, school districts, cities and counties) rarely show up in the Common Crawl
index under their job system, so they are looked up by name instead:

  lists     every US health system (AHRQ Compendium of U.S. Health Systems: name, headquarters, the states and bed
            counts of its hospitals; a hospital of a local system is found through the system, one of a multi-state
            system keeps its own entry), every US hospital (CMS Hospital General Information: name, city, state), every college and university
            (IPEDS institutional directory: name, city, state, web address, size), every public school district
            (NCES Common Core of Data, LEA directory: name, city, state, web address, number of schools) and the
            cities, counties and states that run a .gov site (CISA's list of .gov domains: domain, organisation, city,
            state). All are U.S. federal government data (public domain; AHRQ asks for attribution); only names,
            places, web addresses and sizes are used (the .gov list's security-contact column and IPEDS' chief-officer
            columns are never read) and none of the files is republished.
  resolve   an employer's home page (its web address from the list, or for a hospital a few guesses made from its
            name, accepted only when the page names the employer and its state or city) -> the "Careers" / "Jobs" link
            on it -> one more page at most -> the same detection company_add uses when a person pastes a careers
            link (a known job system linked from the page, SuccessFactors / Taleo, Radancy / Eightfold / Avature,
            AppliTrack / SchoolSpring / Jobvite, or the site's own JobPosting pages).

Polite: every request goes through net (robots.txt, one honest User-Agent, about one request a second per site, at
most OWN_SITE_MAX pages per site per build); a guessed domain is checked by a DNS lookup before any page is asked
for; each employer costs a handful of requests. Results are cached in the builder's state (_state/resolve.json.gz) so
an employer is looked at again only after RECHECK_DAYS, and every run is time-boxed and budgeted. The boards found are
added with the employer's name, its state and the list entry it came from (build.Tenants.add_listed); the reading step
then learns where they hire like any other board.

Test hooks (tests only): SIFTWELL_LISTS_DIR=<folder> reads the lists from files there instead of downloading them
(ahrq_systems.csv, ahrq_linkage.csv, cms.csv, ipeds.zip, nces.zip, dotgov.csv); SIFTWELL_RESOLVE_DNS=0 skips the DNS
check; resolve.fetch and resolve.DETECTORS can be replaced (scripts/test_coverage.py serves recorded pages,
scripts/fixtures_resolve/)."""
import concurrent.futures as cf, csv, datetime as dt, html as _html, io, json, os, re, socket, threading, time, \
    urllib.parse, zipfile

from . import net, systems

RECHECK_DAYS = {"hit": 120, "miss": 60, "nohome": 90, "err": 14}
MAX_PAGES = 10           # pages one employer may cost (home page, careers pages, one level below, careers./jobs. guesses)
GUESS_GETS = 6           # guessed home pages actually opened (after the DNS check) for one hospital
EMP_SECS = 120           # time one employer may take (a slow site gets the rest at its next look-up)
THREADS = 24             # employers looked up side by side (each on its own site)

SOURCES = {
    "cms": {"label": "Hospitals (CMS Hospital General Information)",
            "meta": "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/xubh-q36u",
            "terms": "U.S. federal government data (Centers for Medicare & Medicaid Services), public domain"},
    "ahrq": {"label": "Health systems (AHRQ Compendium of U.S. Health Systems)",
             "urls": ["https://www.ahrq.gov/sites/default/files/wysiwyg/chsp/compendium/chsp-compendium-{year}.csv",
                      "https://www.ahrq.gov/sites/default/files/wysiwyg/chsp/compendium/chsp-hospital-linkage-{year}.csv"],
             "terms": "U.S. federal government data (Agency for Healthcare Research and Quality), free to use with "
                      "attribution; only system names, places and bed counts are used"},
    "ipeds": {"label": "Colleges and universities (IPEDS, NCES)",
              "url": "https://nces.ed.gov/ipeds/datacenter/data/HD{year}.zip",
              "terms": "U.S. federal government data (National Center for Education Statistics), public domain"},
    "nces": {"label": "School districts (NCES Common Core of Data)",
             "urls": ["https://nces.ed.gov/ccd/Data/zip/ccd_lea_029_2324_w_1a_073124.zip",
                      "https://nces.ed.gov/ccd/Data/zip/ccd_lea_029_2223_w_1a_083023.zip"],
             "terms": "U.S. federal government data (National Center for Education Statistics), public domain"},
    "dotgov": {"label": "Cities, counties and states (CISA .gov domain list)",
               "url": "https://raw.githubusercontent.com/cisagov/dotgov-data/main/current-full.csv",
               "terms": "U.S. federal government data (CISA), public domain (CC0)"},
}
STATE_NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
               "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
               "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
               "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
               "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
               "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
               "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
               "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
               "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
               "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico"}


def log(*a):
    print(*a, flush=True)


def today():
    return dt.date.today().isoformat()


def _days_since(d):
    try:
        return (dt.date.today() - dt.date.fromisoformat(str(d)[:10])).days
    except Exception:
        return 10 ** 6


# ---------------------------------------------------------------- the lists
def _local(name):
    d = os.environ.get("SIFTWELL_LISTS_DIR")
    if d:
        p = os.path.join(d, name)
        return open(p, "rb").read() if os.path.exists(p) else b""
    return None


def _download(url, cap=60_000_000):
    return net.get(url, timeout=300, cap=cap, tries=3)


def _site(web):
    """'www.aamu.edu/' -> 'https://www.aamu.edu/'; '' when it isn't a web address."""
    w = str(web or "").strip()
    if not w or " " in w or "." not in w:
        return ""
    if not re.match(r"https?://", w, re.I):
        w = "https://" + w
    sp = urllib.parse.urlsplit(w)
    host = sp.netloc.lower().split("@")[-1].split(":")[0]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host):
        return ""
    return f"https://{host}{sp.path if sp.path not in ('', '/') else '/'}"


def cms_hospitals(states=None):
    """[entity] for every hospital registered with Medicare (federal VA / defence hospitals left out: their jobs are
    on USAJOBS, which the postings step reads)."""
    raw = _local("cms.csv")
    if raw is None:
        meta = json.loads(_download(SOURCES["cms"]["meta"], 2_000_000).decode("utf-8"))
        url = next(d["downloadURL"] for d in meta.get("distribution") or [] if str(d.get("downloadURL", "")).endswith(".csv"))
        raw = _download(url)
    # a hospital of a local health system with several hospitals is found through the system (its jobs are on the
    # system's site); a hospital of a multi-state system keeps its own entry (Mount Carmel's jobs page, not Trinity's)
    a = _ahrq() or {}
    covered = {h["ccn"] for h in a.get("hospitals", []) if h["sys_n"] >= 2 and len((a["systems"].get(h["sys"]) or {}).get("states") or {}) == 1}
    out = []
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))):
        st = (r.get("State") or "").strip().upper()
        if states and st not in states:
            continue
        own = (r.get("Hospital Ownership") or "").lower()
        if "veterans" in own or "defense" in own or "tribal" in own:
            continue
        kind = (r.get("Hospital Type") or "").lower()
        w = 3 if ("acute" in kind or "children" in kind) else 1
        ccn = (r.get("Facility ID") or "").strip()
        if ccn in covered:
            continue            # (one hospital of a health system with several: the system is looked up instead)
        out.append({"id": "cms:" + ccn, "src": "cms", "name": (r.get("Facility Name") or "").strip(),
                    "city": (r.get("City/Town") or "").strip().title(), "state": st, "web": "", "kind": "hospital", "w": w})
    return [e for e in out if e["name"] and e["id"] != "cms:"]


_AHRQ_CACHE = {}
_AHRQ_LOCK = threading.Lock()


def _ahrq():
    """{"systems": {id: {...}}, "hospitals": [{ccn, sys, sys_n, state, beds}]} from the AHRQ Compendium (newest year
    published), or None when it can't be had. Loaded once per run (the hospital list uses it too)."""
    with _AHRQ_LOCK:
        if "v" in _AHRQ_CACHE:
            return _AHRQ_CACHE["v"]
        sysraw, linkraw = _local("ahrq_systems.csv"), _local("ahrq_linkage.csv")
        if sysraw is None:
            y = dt.date.today().year
            for year in range(y - 1, y - 6, -1):
                try:
                    sysraw = _download(SOURCES["ahrq"]["urls"][0].format(year=year), 20_000_000)
                    linkraw = _download(SOURCES["ahrq"]["urls"][1].format(year=year), 40_000_000)
                    break
                except Exception:
                    sysraw = linkraw = None
        v = None
        if sysraw and linkraw:
            systems_ = {}
            for r in csv.DictReader(io.StringIO(sysraw.decode("latin-1"))):
                sid = (r.get("health_sys_id") or "").strip()
                if sid:
                    systems_[sid] = {"name": (r.get("health_sys_name") or "").strip(), "city": (r.get("health_sys_city") or "").strip(),
                                     "state": (r.get("health_sys_state") or "").strip().upper(), "states": {}}
            hosp = []
            for r in csv.DictReader(io.StringIO(linkraw.decode("latin-1"))):
                sid = (r.get("health_sys_id") or "").strip()
                st = (r.get("hospital_state") or "").strip().upper()
                try:
                    beds = int(float(r.get("hos_beds") or 0))
                except ValueError:
                    beds = 0
                if sid in systems_:
                    sy = systems_[sid]["states"]
                    sy[st] = sy.get(st, 0) + beds
                hosp.append({"ccn": (r.get("ccn") or "").strip(), "sys": sid, "state": st, "beds": beds})
            n = {}
            for h in hosp:
                n[h["sys"]] = n.get(h["sys"], 0) + 1
            for h in hosp:
                h["sys_n"] = n.get(h["sys"], 0) if h["sys"] else 0
            v = {"systems": systems_, "hospitals": hosp}
        _AHRQ_CACHE["v"] = v
        return v


def ahrq_systems(states=None):
    """[entity] for every health system with a hospital in these states (its headquarters' city and state are what
    its home page is checked against; "w": its beds in these states)."""
    a = _ahrq()
    if not a:
        raise ValueError("the AHRQ Compendium could not be read")
    out = []
    for sid, sy in a["systems"].items():
        beds = sum(b for s_, b in sy["states"].items() if not states or s_ in states)
        if not sy["name"] or (states and not any(s_ in states for s_ in sy["states"])):
            continue
        out.append({"id": "ahrq:" + sid, "src": "ahrq", "name": sy["name"], "city": sy["city"].title(), "state": sy["state"],
                    "web": "", "kind": "system", "w": beds, "states": sorted(s_ for s_ in sy["states"] if not states or s_ in states)})
    return out


def ipeds(states=None):
    """[entity] for degree-granting colleges and universities with 1,000 students or more (IPEDS INSTSIZE >= 2)."""
    raw = _local("ipeds.zip")
    if raw is None:
        y = dt.date.today().year
        for year in (y - 1, y - 2, y - 3, y - 4):
            try:
                raw = _download(SOURCES["ipeds"]["url"].format(year=year))
                break
            except Exception:
                continue
    if not raw:
        return []
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv") and "_rv" not in n.lower())
    out = []
    for r in csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="latin-1")):
        r = {k.strip().lstrip("﻿").lstrip("ï»¿"): v for k, v in r.items() if k}
        st = (r.get("STABBR") or "").strip().upper()
        if states and st not in states:
            continue
        try:
            size = int(r.get("INSTSIZE") or -1)
        except ValueError:
            size = -1
        if str(r.get("CYACTIVE", "1")).strip() != "1" or str(r.get("DEGGRANT", "1")).strip() != "1" or size < 2:
            continue
        out.append({"id": "ipeds:" + r.get("UNITID", "").strip(), "src": "ipeds", "name": (r.get("INSTNM") or "").strip(),
                    "city": (r.get("CITY") or "").strip(), "state": st, "web": _site(r.get("WEBADDR")), "kind": "college", "w": size})
    return [e for e in out if e["name"]]


def nces_districts(states=None):
    """[entity] for open public school districts and education service agencies with two schools or more."""
    raw = _local("nces.zip")
    if raw is None:
        urls = [os.environ["SIFTWELL_NCES_LEA_URL"]] if os.environ.get("SIFTWELL_NCES_LEA_URL") else SOURCES["nces"]["urls"]
        for u in urls:
            try:
                raw = _download(u)
                break
            except Exception:
                continue
    if not raw:
        return []
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    out = []
    for r in csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="latin-1")):
        st = (r.get("ST") or "").strip().upper()
        if states and st not in states:
            continue
        try:
            n = int(r.get("OPERATIONAL_SCHOOLS") or 0)
        except ValueError:
            n = 0
        if (r.get("LEA_TYPE") or "").strip() not in ("1", "2", "4") or (r.get("SY_STATUS") or "").strip() in ("2", "6", "7") or n < 2:
            continue
        out.append({"id": "nces:" + (r.get("LEAID") or "").strip(), "src": "nces", "name": (r.get("LEA_NAME") or "").strip(),
                    "city": (r.get("LCITY") or "").strip().title(), "state": st, "web": _site(r.get("WEBSITE")), "kind": "district", "w": n})
    return [e for e in out if e["name"]]


_GOV_MAIN = re.compile(r"(?i)^(?:(?:the )?(?:city|town|village|borough|township|municipality|county|parish|consolidated government) of .+|"
                       r".+ (?:county|parish|borough|township|city|town|village)(?: (?:board of )?(?:commissioners?|government|council|administration))?(?:,? \w+)?)$")
_GOV_SUB = re.compile(r"(?i)\b(?:police|sheriff|fire|ems|911|court|courts|clerk|auditor|treasurer|recorder|coroner|prosecutor|elections?|"
                      r"library|health|engineer|veterans?|child|children|family|job and family|jfs|dd|developmental|parks?|water|"
                      r"sewer|utilit\w+|airport|transit|housing|museum|school|tourism|visitors?|ema|emergency|data (?:center|processing)|"
                      r"telecommunications|facilities|board of (?!commissioners)|department|dept|office|commission(?!ers)|authority|"
                      r"district|zoo|golf|cemetery|animal|senior|workforce|economic|port|probate|juvenile|municipal court|mayor's court)\b")


def dotgov(states=None):
    """[entity] for each city, town, village, township and county with a .gov site (its main government, not its
    courts or departments), and each state's own portal."""
    raw = _local("dotgov.csv")
    if raw is None:
        raw = _download(SOURCES["dotgov"]["url"])
    best = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))):
        typ = (r.get("Domain type") or "").strip()
        st = (r.get("State") or "").strip().upper()
        dom = (r.get("Domain name") or "").strip().lower()
        org = re.sub(r"\s+", " ", (r.get("Organization name") or "").strip())
        if not dom or len(st) != 2 or (states and st not in states):
            continue
        if typ in ("City", "County"):
            if not _GOV_MAIN.match(org) or _GOV_SUB.search(org):
                continue
            key = (typ, st, re.sub(r"[^a-z]", "", re.sub(r"(?i)\b(?:the|city|town|village|of|county|board|commissioners?|government|"
                                                           r"council|administration|" + re.escape(st.lower()) + "|" + re.escape(STATE_NAMES.get(st, "x").lower()) + r")\b", "", org.lower())))
            kind = typ.lower()
        elif typ == "State or territory":
            sn = re.sub(r"[^a-z]", "", STATE_NAMES.get(st, "").lower())
            if dom.rsplit(".", 1)[0] not in (sn, st.lower()):
                continue
            key, kind, org = ("State", st, ""), "state", f"State of {STATE_NAMES.get(st, st)}"
        else:
            continue
        cur = best.get(key)
        if cur is None or len(dom) < len(cur[0]):
            best[key] = (dom, org, (r.get("City") or "").strip().title(), st, kind)
    out = []
    for dom, org, city, st, kind in best.values():
        name = org
        m = re.match(r"(?i)^(.+? (?:county|parish))\b", org)
        if kind == "county" and m and not org.lower().startswith(("county of", "parish of")):
            name = m.group(1)
        name = " ".join(w if (w.isupper() and len(w) <= 4) or not w.isupper() else w.capitalize() for w in name.split())
        out.append({"id": "gov:" + dom, "src": "dotgov", "name": name, "city": city, "state": st, "web": f"https://{dom}/",
                    "kind": kind, "w": 3 if kind in ("state", "county") else 2})
    return out


LISTS = {"ahrq": ahrq_systems, "cms": cms_hospitals, "ipeds": ipeds, "nces": nces_districts, "dotgov": dotgov}


def entities(states=None, sources=None, log=log):
    """Every employer of the lists (in these states), biggest first within each list."""
    out = []
    for sid in sources or LISTS:
        try:
            got = LISTS[sid](set(states) if states else None)
        except Exception as e:
            log(f"  lists: {sid} unavailable ({type(e).__name__}: {str(e)[:80]})")
            continue
        log(f"  lists: {SOURCES[sid]['label']}: {len(got)} employers" + (f" in {','.join(sorted(states))}" if states and len(states) < 8 else ""))
        out.extend(got)
    return out


# ---------------------------------------------------------------- names and pages
_STOP = {"the", "of", "and", "at", "in", "for", "inc", "llc", "hospital", "hospitals", "medical", "center", "centre", "centers",
         "health", "healthcare", "system", "systems", "regional", "community", "general", "clinic", "campus", "corp", "company",
         "care", "services", "service", "memorial", "district", "school", "schools", "city", "local", "public", "county",
         "village", "exempted", "university", "college", "institute", "behavioral", "rehabilitation", "rehab", "specialty",
         "surgical", "surgery", "acute", "long", "term", "ltach", "facility", "inpatient", "network", "partners", "llp",
         "town", "township", "state", "dba", "a", "an"}
_ABBR = {"st": "saint", "mt": "mount", "ft": "fort", "ctr": "center", "hosp": "hospital", "med": "medical", "univ": "university",
         "&": "and"}


def name_tokens(name):
    """The distinctive words of an employer's name ("MOUNT CARMEL EAST HOSPITAL" -> mount, carmel, east)."""
    words = re.findall(r"[a-z0-9&]+", str(name or "").lower().replace("'", "").replace("’", ""))
    words = [_ABBR.get(w, w) for w in words]
    return [w for w in words if w not in _STOP and len(w) >= 2]


def _visible(page):
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", (page or "")[:600_000])
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t))


def site_name(page):
    """The employer's own name for its site: og:site_name, else the page title without its generic parts."""
    import names
    for rx in (r'<meta[^>]+property=["\']og:site_name["\'][^>]*content=["\']([^"\']{2,90})', r'<meta[^>]+content=["\']([^"\']{2,90})["\'][^>]*property=["\']og:site_name',
               r"<title[^>]*>(.*?)</title>"):
        m = re.search(rx, page or "", re.S | re.I)
        if m:
            n = names.name_from_title(m.group(1))
            n = re.sub(r"(?i)\.(?:com|org|net|edu|gov|us)$", "", n or "").strip()
            if n and not names.poor(n) and len(n) <= 70:
                return n.strip()
    return ""


def page_names_it(page, ent):
    """Does a guessed home page belong to this employer? Its title / site name carries the distinctive words of the
    employer's name (the first two, or the only one), a hospital's says it is about health care, and the page
    mentions the employer's city or state (a health system: any state it has hospitals in). Returns a score (0: no):
    5 for the city, 2 for the employer's state, 1 for each other state of a system, so of two namesakes ("Trinity
    Health" in Michigan and in North Dakota) the one that fits best wins."""
    toks = name_tokens(ent["name"])
    if not toks:
        return 0
    head = ""
    for rx in (r"<title[^>]*>(.*?)</title>", r'<meta[^>]+property=["\']og:(?:site_name|title)["\'][^>]*content=["\']([^"\']+)'):
        for m in re.finditer(rx, page or "", re.S | re.I):
            head += " " + m.group(1)
    have = set(name_tokens(_html.unescape(head))) | set(re.findall(r"[a-z0-9]+", _html.unescape(head).lower().replace("'", "")))
    need = toks[:2]
    if not all(t in have or any(t in h and len(t) >= 4 for h in have) for t in need):
        return 0
    kw = _KIND_WORDS.get(ent.get("kind"))
    if kw:          # (a hospital's site says so in its title or description: "Kettering Foundation" is not Kettering Health)
        desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']+)', page or "", re.I)
        if not re.search(r"(?i)\b(?:" + kw + r")", head + " " + (desc.group(1) if desc else "")):
            return 0
    text = _visible(page)[:60000]
    score = 0
    if ent.get("city") and re.search(r"(?i)\b" + re.escape(ent["city"]) + r"\b", text):
        score += 5
    for st in dict.fromkeys([ent.get("state") or ""] + list(ent.get("states") or [])):    # (a system: any state it has hospitals in)
        sn = STATE_NAMES.get(st, "")
        if (sn and re.search(r"\b" + re.escape(sn) + r"\b", text)) or (st and re.search(r",\s*" + st + r"\b", text)):
            score += 2 if st == ent.get("state") else 1
    return score


_NAME_NOISE = {"the", "of", "and", "inc", "llc", "corp", "corporation", "company", "co", "dba", "a", "an", "at"}


def guesses(ent):
    """Home addresses to try for an employer the list gives no web address for (hospitals, health systems): its name
    run together and hyphenated ("kettering health" -> ketteringhealth, kettering-health), then its distinctive words
    alone and with a usual ending ("mountcarmel" + "health"), on .org and .com."""
    words = [_ABBR.get(w, w) for w in re.findall(r"[a-z0-9]+", str(ent.get("name") or "").lower().replace("'", "").replace("’", ""))]
    words = [w for w in words if w not in _NAME_NOISE]
    toks = [t for t in name_tokens(ent["name"]) if t.isalnum()]
    if not toks or not words:
        return []
    out = []

    def put(base, tails=("",)):
        if 3 <= len(base) <= 40:
            for tail in tails:
                for tld in (".org", ".com"):
                    out.append(base + tail + tld)
    put("".join(words))
    if 2 <= len(words) <= 4:
        put("-".join(words))
    if len(words) >= 3:
        put("".join(words[:2]))
        put("-".join(words[:2]))
    tails = ("", "health", "hospital", "healthcare", "medical") if ent.get("kind") in ("hospital", "system") else ("",)
    for k in (2, 3):
        if len(toks) >= k:
            put("".join(toks[:k]), tails)
    if len(toks) == 1 or len(toks[0]) >= 8:
        put(toks[0], tails)
    return list(dict.fromkeys(out))[:28]


_KIND_WORDS = {"hospital": r"hospital|health|medical|patient|clinic|care|physician",
               "system": r"hospital|health|medical|patient|clinic|care|physician"}


def _resolves(host):
    if os.environ.get("SIFTWELL_RESOLVE_DNS") == "0":
        return True
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except (OSError, UnicodeError):
        return False


def _dns_any(hosts):
    """The hosts (in order) that have an address, checked side by side (a DNS lookup each, no page is asked for)."""
    if not hosts:
        return []
    with cf.ThreadPoolExecutor(min(8, len(hosts))) as ex:
        ok = list(ex.map(_resolves, hosts))
    return [h for h, k in zip(hosts, ok) if k]


def registrable(host):
    """'careers.ohiohealth.com' -> 'ohiohealth.com' (two labels; three for a few public suffixes)."""
    labs = str(host or "").lower().split(":")[0].strip(".").split(".")
    if len(labs) >= 4 and labs[-1] == "us" and len(labs[-2]) == 2:
        return ".".join(labs[-4:])          # (olentangy.k12.oh.us, columbus.ci.oh.us)
    if len(labs) >= 3 and (labs[-2] in ("co", "com", "org", "net", "gov", "edu", "k12", "ac") or (labs[-1] == "us" and len(labs[-2]) == 2)):
        return ".".join(labs[-3:])
    return ".".join(labs[-2:])


_CAREER_TEXT = re.compile(r"(?i)^\W*(?:careers?(?: (?:at|with) .{1,40}| opportunities| center| & jobs| and jobs)?|jobs?(?: (?:at|with) .{1,40}| openings| opportunities| board| search)?|"
                          r"employment(?: opportunities)?|job (?:openings|opportunities|postings|listings)|current (?:openings|opportunities|vacancies|job openings)|"
                          r"work (?:with|for|at) us|join (?:our|the) team|join us|human resources|vacancies|now hiring|we'?re hiring|"
                          r"open positions|view (?:all )?(?:jobs|openings|positions)|search (?:all )?(?:jobs|openings|positions)|"
                          r"apply (?:now|online|today)|see (?:all )?(?:jobs|openings)|job search|find (?:a|your) (?:job|career))\W*$")
_CAREER_HREF = re.compile(r"(?i)(?:^|[/.\-_])(?:careers?|jobs?|employment|job-?openings|opportunities|vacancies|human-?resources|hr|join-?(?:our-?)?team|work-?(?:with|for)-?us)(?:[/?#.\-_]|$)")
_DEEPER_TEXT = re.compile(r"(?i)\b(?:search|view|see|browse|find|apply|current|open|all)\b.{0,25}\b(?:jobs?|openings|positions|opportunities|vacancies|careers?)\b|"
                          r"\b(?:job (?:openings|search|board|postings|listings)|employment opportunities|career opportunities|apply online)\b")


def links(page, base):
    """[(absolute url, anchor text)] of a page's links."""
    out = []
    # (bounded: an anchor's text is looked for within 600 characters, so a page full of unclosed tags stays cheap)
    for m in re.finditer(r"(?is)<a\b[^>]{0,600}?\bhref\s*=\s*([\"'])([^\"'<>]{1,2000})\1[^>]{0,600}>(.{0,600}?)</a>", (page or "")[:2_000_000]):
        href = _html.unescape(m.group(2)).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        txt = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))).strip()
        title = re.search(r'(?i)\b(?:title|aria-label)\s*=\s*["\']([^"\']{2,60})', m.group(0))
        try:
            u = urllib.parse.urljoin(base, href)
        except ValueError:
            continue
        if u.startswith(("http://", "https://")):
            out.append((u.split("#")[0], txt[:80] or (title.group(1) if title else "")))
    return out


# what company_add.detect runs on a careers page that links to no known job system, in its order (tests replace it)
DETECTORS = (lambda u, p: __import__("ats_sap_taleo").detect_page(u, p),
             lambda u, p: __import__("ats_more").detect(u, p),
             lambda u, p: __import__("ats_public").detect(u, p),
             lambda u, p: __import__("jsonld_fetcher").detect_config(u, p))


def detect_page(url, page):
    """A job-board config for a careers page: a known job system linked from it (an employer's own page names its
    board on purpose, so a Workday site called "Jobs" counts: systems.parse not strict), else the detection company_add
    runs on a pasted link (SuccessFactors / Taleo pages, Radancy / Eightfold / Avature, AppliTrack / SchoolSpring /
    Jobvite, the site's own JobPosting pages). None when nothing readable is there."""
    import netsafe
    seen = set()
    cands = [url] + [m.group(0) for m in re.finditer(r"https?://[^\s\"'<>\\)]{4,600}", (page or "")[:2_000_000])]
    for u in cands:
        u = _html.unescape(u)
        if u in seen:
            continue
        seen.add(u)
        c = systems.parse(u, strict=False)
        if c:
            return c
    for probe in DETECTORS:
        if _over_time():
            break               # (this employer has had its time: the slower checks are left for its next look-up)
        try:
            cfg = probe(url, page)
        except Exception:
            cfg = None
        if cfg:
            cfg, _ = netsafe.clean_config(cfg)
            if cfg:
                return cfg
    return None


class _Budget:
    def __init__(self, n):
        self.n = n

    def take(self):
        if self.n <= 0:
            return False
        self.n -= 1
        return True


_tl = threading.local()


def _over_time():
    return time.time() > getattr(_tl, "until", float("inf"))


def _get(url, budget, timeout=20):
    """(text, final url) of a page within this employer's page budget and time, or (None, None)."""
    if _over_time() or not budget.take():
        return None, None
    try:
        return fetch(url, timeout)
    except Exception:
        return None, None


def fetch(url, timeout=20):
    """(text, final url) of a page through the builder's polite http (tests replace it with recorded pages)."""
    return net.get_page(url, tries=1, timeout=timeout, cap=3_000_000)


def find_home(ent, budget):
    """(home page text, its final address, how it was found: "list" / "guess") or (None, None, None)."""
    if ent.get("web"):
        page, final = _get(ent["web"], budget)
        if page is None and ent["web"].startswith("https://"):
            page, final = _get("http://" + ent["web"][8:], budget)
        if page is None and "://www." not in ent["web"]:
            page, final = _get(ent["web"].replace("://", "://www.", 1), budget)
        return (page, final, "list") if page else (None, None, None)
    tried, best = 0, None
    for host in _dns_any(guesses(ent)):
        for h in (host, "www." + host):
            if tried >= GUESS_GETS:
                break
            if h.startswith("www.") and not _resolves(h):
                continue
            tried += 1
            page, final = _get(f"https://{h}/", budget)
            sc = page_names_it(page, ent) if page else 0
            if sc and (best is None or sc > best[0]):
                best = (sc, page, final)
            if page:
                break       # (the site answered: its www. twin is the same site)
        if tried >= GUESS_GETS or (best and best[0] >= 5):
            break
    return (best[1], best[2], "guess") if best else (None, None, None)


def careers_links(page, base):
    """Links on a page that lead to its jobs, best first: anchor text that says so, then an address that does."""
    home = registrable(urllib.parse.urlsplit(base).netloc)
    scored = []
    for u, txt in links(page, base):
        sp = urllib.parse.urlsplit(u)
        if sp.path.lower().endswith((".pdf", ".doc", ".docx", ".jpg", ".png")):
            continue
        same = registrable(sp.netloc) == home
        s = 0
        if _CAREER_TEXT.match(txt or ""):
            s += 4
        if _CAREER_HREF.search(sp.netloc.split(".")[0] + "/" + sp.path):
            s += 2
        if not s:
            continue
        if re.search(r"(?i)\b(?:physician|provider|volunteer|student|nursing school|residency|fellowship|alumni|faculty development)\b", txt or ""):
            s -= 2
        scored.append((-(s + (1 if same else 0)), len(scored), u))
    scored.sort()
    return list(dict.fromkeys(u for _, _, u in scored))


def resolve(ent):
    """{"s": "hit" / "miss" / "nohome", "c": config or None, "h": home address, "u": careers page, "n": the name to use,
    "how": "list" / "guess"} for one employer."""
    budget = _Budget(MAX_PAGES)
    _tl.until = time.time() + EMP_SECS
    page, home, how = find_home(ent, budget)
    if not page:
        return {"s": "nohome"}
    out = {"s": "miss", "h": home, "how": how, "n": display_name(ent, page)}
    cfg = detect_links_only(page, home)
    if cfg:
        return dict(out, s="hit", c=cfg, u=home)
    tried = {home}
    for u in careers_links(page, home)[:3]:
        if u in tried:
            continue
        tried.add(u)
        c = systems.parse(u, strict=False)
        if c:
            return dict(out, s="hit", c=c, u=u)
        p2, f2 = _get(u, budget)
        if not p2:
            continue
        cfg = detect_page(f2 or u, p2)
        if cfg:
            return dict(out, s="hit", c=cfg, u=f2 or u)
        for u3 in [x for x, t in links(p2, f2 or u) if _DEEPER_TEXT.search(t or "")][:2]:
            if u3 in tried:
                continue
            tried.add(u3)
            c = systems.parse(u3, strict=False)
            if c:
                return dict(out, s="hit", c=c, u=u3)
            p3, f3 = _get(u3, budget)
            if p3:
                cfg = detect_page(f3 or u3, p3)
                if cfg:
                    return dict(out, s="hit", c=cfg, u=f3 or u3)
    dom = registrable(urllib.parse.urlsplit(home).netloc)
    for h in _dns_any([f"careers.{dom}", f"jobs.{dom}"]):
        u = f"https://{h}/"
        if u in tried:
            continue
        p, f = _get(u, budget)
        if p:
            cfg = detect_page(f or u, p)
            if cfg:
                return dict(out, s="hit", c=cfg, u=f or u)
    return out


def detect_links_only(page, base):
    """A known job system linked straight from the home page (no other detection: a home page's own JobPosting
    markup or embedded widgets are judged on its careers page)."""
    for u, txt in links(page, base):
        if _CAREER_TEXT.match(txt or "") or _CAREER_HREF.search(urllib.parse.urlsplit(u).path):
            c = systems.parse(u, strict=False)
            if c:
                return c
    return None


def display_name(ent, page):
    """The name the board gets from this employer: a college's IPEDS name and a government's own name as listed; a
    hospital's or district's own site name when it carries the employer's words ("Mount Carmel Health System"), else
    the listed name written the way people write it."""
    import names
    listed = ent["name"]
    if ent["src"] in ("ipeds", "dotgov"):
        return listed[:60]
    sn = site_name(page)
    toks = set(name_tokens(listed))
    if sn and toks & set(name_tokens(sn)) and not names.poor(sn):
        return sn[:60]
    n = listed
    if n.isupper():
        n = " ".join(w if len(w) <= 3 and not re.search(r"[AEIOU]", w) else w.capitalize() for w in n.split())
        n = re.sub(r"\b(Of|And|The|At|For)\b", lambda m: m.group(1).lower(), n)
        n = n[:1].upper() + n[1:]
    if ent["src"] == "nces" and not re.search(r"(?i)\b(school|schools|district|academy|education|educational|learning|esc|isd|usd|unified|consolidated)\b", n):
        n += " Schools"
    return n[:60]


# ---------------------------------------------------------------- the pass
def run(T, st, states=None, sources=None, budget=4000, deadline=None, threads=THREADS, log=log, ents=None, save=None):
    """Look up the lists' employers (never-checked ones first, biggest first) and add the boards found to T. The
    results live in st["resolve"] ({entity id: {...}}), so a later run carries on and a hit is kept between runs.
    save(): called every 200 lookups (the builder writes its state then, so a run that is stopped keeps its work).
    Returns the per-list statistics (also logged)."""
    cache = st.setdefault("resolve", {})
    ents = ents if ents is not None else entities(states, sources, log)
    stats = {}
    for e in ents:
        s = stats.setdefault(e["src"], {"employers": 0, "checked": 0, "home": 0, "hit": 0, "known_hits": 0, "systems": {}})
        s["employers"] += 1
        r = cache.get(e["id"])
        if r and r.get("s") == "hit" and r.get("c"):
            _add(T, e, r)
            s["known_hits"] += 1

    def due(e):
        r = cache.get(e["id"])
        return r is None or _days_since(r.get("d")) >= RECHECK_DAYS.get(r.get("s"), 30)
    todo = [e for e in ents if due(e)]
    todo.sort(key=lambda e: (e["id"] in cache, -int(e.get("w") or 0), e["state"], e["id"]))
    todo = todo[:max(0, int(budget))]
    lock = threading.Lock()
    done = [0]

    def one(e):
        if deadline is not None and time.time() > deadline:
            return e, None
        try:
            r = resolve(e)
        except Exception as ex:
            r = {"s": "err", "e": f"{type(ex).__name__}"}
        return e, r
    t0 = time.time()
    ex = cf.ThreadPoolExecutor(max(1, threads))
    futs = [ex.submit(one, e) for e in todo]
    # (in the order they finish: one slow site holds nothing up; past the time box, what still runs is left behind)
    wait = None if deadline is None else max(60.0, deadline - time.time() + 300)
    try:
        for f in cf.as_completed(futs, timeout=wait):
            e, r = f.result()
            if r is None:
                continue
            r["d"] = today()
            s = stats[e["src"]]
            with lock:
                prev = cache.get(e["id"]) or {}
                if r["s"] in ("err", "nohome", "miss") and prev.get("s") == "hit" and prev.get("c"):
                    r = dict(prev, d=today(), last=r["s"])    # (a site that didn't answer today keeps its board)
                cache[e["id"]] = r
                done[0] += 1
            s["checked"] += 1
            s["home"] += bool(r.get("h"))
            if r.get("s") == "hit" and r.get("c"):
                s["hit"] += 1
                a = r["c"].get("ats", "?")
                s["systems"][a] = s["systems"].get(a, 0) + 1
                _add(T, e, r)
            if done[0] % 250 == 0:
                log(f"  resolve: {done[0]} of {len(todo)} employers looked up ({round((time.time() - t0) / 60, 1)} min)")
            if save is not None and done[0] % 200 == 0:
                with lock:
                    save()
    except cf.TimeoutError:
        log(f"  resolve: time is up; {sum(not f.done() for f in futs)} lookups on slow sites are left for the next run")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    for sid, s in stats.items():
        known = sum(1 for e in ents if e["src"] == sid and (cache.get(e["id"]) or {}).get("s") == "hit")
        seen = sum(1 for e in ents if e["src"] == sid and e["id"] in cache)
        s["resolved_total"], s["looked_up_total"] = known, seen
        log(f"  resolve {SOURCES[sid]['label']}: {s['checked']} looked up this run ({s['home']} home pages, {s['hit']} job boards: "
            f"{s['systems']}); all runs: {known} of {seen} looked up have a readable job board ({round(100 * known / max(1, seen))}%), "
            f"{s['employers']} on the list")
    return stats


def _add(T, e, r):
    import netsafe
    cfg, _ = netsafe.clean_config(dict(r["c"]))
    if cfg:
        for st in e.get("states") or [e["state"]]:
            T.add_listed(cfg, "res", r.get("n") or e["name"], st, e["id"])
