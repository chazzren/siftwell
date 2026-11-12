"""Build the Siftwell employer directory (published on the repo's `index` branch; read by directory.py).

    python scripts/build_index.py --out <folder> [--states OH,CO,DC] [--limit N] [--minutes M] [--no-cc] [--no-ct] ...

Steps:
  1. Discover job-board tenants: the starter packs (packs/*.json), the Common Crawl URL index (cc.py) and certificate
     names (ct.py) for every system in systems.SYSTEMS, job-board links in the HN "Who is hiring" thread, and employer
     web domains from Web Data Commons (gov.wdc: a budget and a time box per run; the second weekly job in index.yml
     does nothing else, so the whole list is covered every week or two). Workday: a link that names no career site
     ("/robots.txt", "/en-US") is not a board; the tenant's robots.txt lists every career site it has, and each one
     becomes a board (workday_sites_pass, one GET per tenant every WD_SITES_DAYS). With --lca-file, DOL LCA employer
     names are tied to tenants by slug (hints only; nothing is probed).
  2. Read each tenant's public feed (readers.py; robots.txt, pacing, one honest User-Agent) to learn where it hires:
     locations (geocoded offline with geo.py), open jobs, US-remote jobs. A label that is one bare word matching a small
     town ("Green") only counts when the board also names that state properly. Boards known only by a code get their
     name from the board page (readers.board_name, once). Boards that fail three runs in a row rest for four weeks;
     empty boards are left out of the files.
  3. Job snapshots from sources that publish postings (postings.py: USAJOBS, SchoolSpring, HN, The Muse; CareerOneStop
     is off by default), bucketed by state.
  4. Write states/<ST>.json.gz, states/remote.json.gz, jobs/<ST>.json.gz, jobs/remote.json.gz and manifest.json
     (sizes, SHA-256, counts, sources and attribution). Every distinct career site of a tenant is its own entry (only
     exact mirrors and respellings of one board are merged). Builder state (what was read when) is kept in _state/ on
     the same branch, so a time-boxed run carries on where the last one stopped.

A state file entry: {"n": name ("" when only a code is known), "c": board config, "u": careers link, "j": open US jobs,
"r": US-remote jobs, "p": [[lat, lon, jobs, label] ...] (this state's places, at most PLACES_MAX), "s": date read,
"ps": every state it hires in (only when few), "pt": 1 when "p" was cut, "x": 1 when the board was only sampled,
"mb": 1 "maybe near" (sampled: the app adds it for people in this state and prunes it after the first fetch),
"k": "staffing" for staffing agencies}.

This package ships with the app (it is imported by name, also from inside an installed build): the same readers and
the same state files serve "Build my own directory" (local.py: the app reads the boards itself, starting from the
seed list in assets/directory, see seed.py). scripts/build_index.py is only the command line for the weekly build.

Only company names, job-system configs, careers links, places with job counts and dates are published: no people."""
import argparse, concurrent.futures as cf, datetime as dt, glob, gzip, hashlib, json, os, re, sys, threading, time

from . import net, systems, readers, cc, ct, gov, postings

# Boards read at once per job system. How fast a system is really asked is decided by net.PROVIDERS (requests per
# second and connections per provider); a lane wider than that only means its readers wait their turn.
LANES = {"greenhouse": 3, "lever": 1, "ashby": 3, "workday": 4, "jsonld": 6, "paylocity": 1, "workable": 1, "paycom": 1, "saashr": 1}
LANE_DEFAULT = 2        # every other system (each system has its own lane: its boards share hosts)
STALE_DAYS = 6          # a board read more recently than this isn't read again
KEEP_DAYS = 35          # a board unread this long (it kept failing) is left out of the files
REST_DAYS = 28          # after three failures in a row
PLACES_MAX = 150        # places per employer in one state file
PS_MAX = 8              # an entry lists the states it hires in only when there are this few (the app's "all nearby" rule)
WD_SITES_DAYS = 60      # a Workday tenant's robots.txt (its list of career sites) is read again after this long
TNAME_DAYS = 120        # a board page is asked for the employer's name again after this long
NAME_DETAILS = 2        # postings opened on a board known only by a code, to learn the employer's name
OPAQUE = {"paylocity", "ukg", "dayforce", "paycom", "saashr", "oracle", "adp"}   # systems whose address is only a code
STAFFING = re.compile(r"(?i)\b(staffing|recruit(?:ing|ers?|ment)|personnel|talent (?:solutions|partners|group)|workforce solutions|"
                      r"temp(?:orary)? (?:services|agency)|employment (?:agency|services|solutions|professionals)|headhunt\w*|"
                      r"search (?:group|partners|firm)|placement (?:services|group)|"
                      r"robert half|aerotek|adecco|randstad|kelly services|manpower\w*|insight global|teksystems|kforce|"
                      r"express employment|spherion|apex systems|actalent|aston carter|beacon hill|cybercoders|jobot|vaco|"
                      r"addison group|aya healthcare|trustaff|allegis|peopleready|labor ?finders|snelling|volt workforce)\b")
AGGREGATOR = re.compile(r"(?i)\b(job ?board|jobs? (?:in|near) |indeed|ziprecruiter|careerbuilder|monster\.com|glassdoor|simplyhired|"
                        r"jooble|talent\.com|lensa|jobcase|snagajob|joblist|careerjet|adzuna|neuvoo|jobrapido)\b")
ALL_STATES = sorted(set(__import__("directory").STATE_CODES))
README = """# Siftwell employer directory (generated)

This branch is written by the "Employer directory" GitHub Actions workflow (.github/workflows/index.yml) once a week,
as a single commit. Siftwell downloads the files here to find employers near you: whole state files only, so your exact
location is never sent anywhere. Nothing here is about people: company names, job-system settings, careers links,
places with job counts, and dates. Job snapshots link to the original postings and name their source.

Built {built}. {employers:,} employers with open jobs, {jobs:,} snapshot postings.
"""


def log(*a):
    print(*a, flush=True)


def today():
    return dt.date.today().isoformat()


def _days_since(d):
    try:
        return (dt.date.today() - dt.date.fromisoformat(d[:10])).days
    except Exception:
        return 10 ** 6


# ---------------------------------------------------------------- state
def load_json_gz(path, default):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json_gz(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    data = gzip.compress(raw, 9, mtime=0)
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return data


class Tenants:
    def __init__(self, path):
        self.path = path
        self.d = load_json_gz(path, {})
        self.lock = threading.Lock()
        self.new = {}

    def add(self, cfg, src, name=None, hint=None):
        if not cfg:
            return None
        k = systems.key(cfg)
        with self.lock:
            t = self.d.get(k)
            if t is None:
                t = self.d[k] = {"c": cfg, "src": [], "found": today()}
                self.new[src] = self.new.get(src, 0) + 1
            if src not in t["src"]:
                t["src"].append(src)
            if name and (src == "pack" or not t.get("pack_name")):
                t["pack_name" if src == "pack" else "gov_name"] = name
            if hint:
                t.setdefault("hints", [])
                if hint not in t["hints"]:
                    t["hints"].append(hint)
        return k

    def drop(self, k):
        with self.lock:
            self.d.pop(k, None)

    def save(self):
        save_json_gz(self.path, self.d)


# ---------------------------------------------------------------- discovery
def seed_packs(T):
    import paths
    n = 0
    for f in sorted(glob.glob(os.path.join(paths.PACKS, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in d.get("companies") or []:
            import netsafe
            cfg, _ = netsafe.clean_config(c)
            if cfg:   # (the pack's verification stamps aren't part of the board's identity)
                cfg = {k: v for k, v in cfg.items() if not k.startswith("verified_")}
            if cfg:
                T.add(cfg, "pack", c.get("name"))
                n += 1
    log(f"packs: {n} seed boards")


def discover_cc(T, crawls, cap, wd_extra=None, want=None, after=None):
    """Job boards from the Common Crawl URL index. want(prefix) -> False skips a prefix and after(prefix) is called
    when one was read through (the app's own, much smaller, discovery remembers what it did: local.py)."""
    for crawl in crawls:
        ix = cc.Index(crawl)
        for s in systems.SYSTEMS:
            if not s.read:
                continue
            for prefix in s.cc:
                if want is not None and not want(prefix):
                    continue
                n0 = len(T.d)
                try:
                    for u in ix.urls(prefix, cap, log):
                        c = systems.parse(u)
                        if c is None and s.id == "workday" and wd_extra is not None:
                            h = systems.workday_host(u)     # a link that names no career site: robots.txt will
                            if h:
                                wd_extra.add(h)
                        T.add(c, "cc")
                    if after is not None:
                        after(prefix)
                except Exception as e:
                    log(f"  cc {crawl} {prefix}: failed ({type(e).__name__}: {str(e)[:80]})")
                log(f"  cc {crawl} {s.id}: +{len(T.d) - n0} new boards")


def discover_ct(T, wd_extra):
    for s in systems.SYSTEMS:
        if not s.read:
            continue
        for dom in s.ct:
            n0, w0 = len(T.d), len(wd_extra)
            for h in ct.hosts(dom, log):
                c = systems.ct_host_config(s.id, h)
                if not c:
                    continue
                if s.id == "workday":
                    wd_extra.add((c["tenant"].lower(), c["wd"].lower()))   # (its sites come from its robots.txt)
                else:
                    T.add(c, "ct")
            log(f"  ct {dom}: +{len(T.d) - n0} new boards" + (f", {len(wd_extra) - w0} Workday hosts to look up" if s.id == "workday" else ""))


def workday_sites_pass(T, st, extra, budget, probe_budget=0):
    """Workday career sites from each tenant's robots.txt. Entries whose "site" isn't one (a crawler saw /robots.txt or
    a bare language code) are removed; every site a tenant lists becomes a board, spelled the way the tenant spells it;
    boards of that tenant that it doesn't list are dropped (they aren't public, or are respellings)."""
    cache = st.setdefault("wd_sites", {})    # "tenant.wd" -> [date, [sites]]
    hosts, removed = {}, 0
    for k in list(T.d):
        c = T.d[k]["c"]
        if c.get("ats") != "workday" or c.get("host"):
            continue
        h = f'{str(c.get("tenant", "")).lower()}.{str(c.get("wd", "")).lower()}'
        if systems.bad_workday_site(c.get("site", "")):
            T.drop(k)
            removed += 1
            hosts.setdefault(h, 0)
        else:
            hosts[h] = 1
    for t, w in extra or ():
        hosts.setdefault(f"{t}.{w}", 0)
    todo = [h for h in hosts if h not in cache or _days_since(cache[h][0]) >= WD_SITES_DAYS]
    todo.sort(key=lambda h: (hosts[h], h))       # tenants without a usable site first
    todo = todo[:budget]

    def one(h):
        t, w = h.split(".", 1)
        try:
            return h, readers.workday_sites(t, w)
        except Exception:
            return h, None

    found = failed = respelled = 0
    with cf.ThreadPoolExecutor(8) as ex:         # (one request per tenant, each on its own host)
        results = list(ex.map(one, todo))
    probes = []
    for h, sites in results:
        if sites is None:
            failed += 1
            cache[h] = [today(), []]
            continue
        cache[h] = [today(), sites]
        if not sites and not hosts[h]:
            probes.append(h)
    for h in probes[:probe_budget]:              # robots.txt lists no site: try the usual names (certificate finds)
        t, w = h.split(".", 1)
        cc_ = readers.workday_find_site({"ats": "workday", "tenant": t, "wd": w})
        if cc_:
            cache[h] = [today(), [cc_["site"]]]
    listed = {h: v[1] for h, v in cache.items() if v[1]}
    for k in list(T.d):
        c = T.d[k]["c"]
        if c.get("ats") != "workday" or c.get("host"):
            continue
        sites = listed.get(f'{str(c.get("tenant", "")).lower()}.{str(c.get("wd", "")).lower()}')
        if sites and c.get("site") not in sites and "pack" not in T.d[k]["src"]:
            T.drop(k)
            respelled += 1
    for h, sites in listed.items():
        t, w = h.split(".", 1)
        for s in sites:
            n0 = len(T.d)
            T.add({"ats": "workday", "tenant": t, "wd": w, "site": s}, "robots")
            found += len(T.d) - n0
    log(f"  Workday sites: {removed} entries that weren't career sites removed; {len(todo)} tenants' robots.txt read "
        f"({failed} unreachable), {found} boards added, {respelled} unlisted or respelled boards dropped")


def discover_names(T, names):
    """Tie employer names with a state (DOL LCA, when a file is given) to tenants already known, by slug: a hint for
    reading order and naming. Nothing is probed (the IRS-list slug probing found next to nothing and was removed)."""
    idx = {}
    for k, t in T.d.items():
        c = t["c"]
        for v in (c.get("token"), c.get("tenant")):
            if v:
                idx.setdefault(str(v).lower(), []).append(k)
    matched = 0
    for e in names:
        ks = [k for s in gov.slugs(e["name"]) for k in idx.get(s, [])]
        for k in ks[:2]:
            t = T.d[k]
            t.setdefault("gov_name", e["name"])
            h = "state:" + e["state"]
            t.setdefault("hints", [])
            if h not in t["hints"]:
                t["hints"].append(h)
        matched += bool(ks)
    log(f"  names: {len(names)} employers, {matched} matched a known board")


def discover_wdc(T, st, budget, deadline=None, threads=24):
    """Employer web domains with JobPosting markup (Web Data Commons): open each domain's careers page and keep the
    job board it uses. Every domain is its own host, so many are checked at once, each politely (robots.txt, pacing);
    the cursor in the builder's state carries on where the last run stopped, round and round the list."""
    doms = gov.wdc(log=log)
    if not doms:
        return
    cur = int(st.get("wdc_cursor", 0)) % max(1, len(doms))
    found = checked = 0

    def one(dn):
        try:
            return gov.resolve_domain(dn[0])
        except Exception:
            return None
    with cf.ThreadPoolExecutor(threads) as ex:
        while checked < budget and (deadline is None or time.time() < deadline):
            batch = doms[cur + checked:cur + checked + min(threads * 8, budget - checked)]
            if not batch:
                break
            for cfg in ex.map(one, batch):
                if cfg:
                    T.add(cfg, "wdc")
                    found += 1
            checked += len(batch)
            st["wdc_cursor"] = (cur + checked) % max(1, len(doms))
    if cur + checked >= len(doms):
        st["wdc_passes"] = int(st.get("wdc_passes", 0)) + 1
    log(f"  WDC: {checked} of {len(doms)} domains checked (from #{cur}), {found} readable job boards; "
        f"{st.get('wdc_passes', 0)} full passes so far")


# ---------------------------------------------------------------- reading
_GEO = {}


def place_of(label):
    """(lat, lon, state, label, weak) for a location label, or None (state-only, remote and foreign labels are None).
    weak: the label is a bare name that only matched a small town ("Green" -> Green, OH), with no state to confirm it."""
    if label in _GEO:
        return _GEO[label]
    import geo, directory
    r = None
    try:
        hs = [h for h in geo.locate_all(label) if h.kind != "state"]
        if hs:
            h = max(hs, key=lambda h: h.conf)
            m = re.search(r", ([A-Z]{2})$", h.label)
            stc = m.group(1) if m else directory.state_of(h.lat, h.lon)
            if stc:
                # (kind "bare": a city name with namesakes in other states, see geo.py)
                weak = h.kind in ("place", "bare") and h.conf <= 0.6 and not re.search(r",|\d{5}", label)
                r = (round(h.lat, 3), round(h.lon, 3), stc, h.label, weak)
    except Exception:
        r = None
    _GEO[label] = r
    return r


def board_places(locs, hints=(), staffing=False):
    """[[lat, lon, jobs, label, state]] for a board's {location label: postings}. A weak label (one bare word matching
    a small town) is kept only when the board names that state properly somewhere else (or a hint does), and never for
    a staffing agency (their boards carry client names and one-word labels)."""
    got = [(p, n) for p, n in ((place_of(lab), n) for lab, n in locs.items()) if p]
    sure = {p[2] for p, _ in got if not p[4]} | set(hints)
    places = {}
    for p, n in got:
        if p[4] and (staffing or p[2] not in sure):
            continue
        kk = (p[0], p[1])
        cur = places.get(kk)
        places[kk] = [p[0], p[1], (cur[2] if cur else 0) + n, p[3], p[2]]
    return list(places.values())


FOREIGN_ENTITY = re.compile(r"\b(Ltda|GmbH|S\.?A\.?S?|Pvt|Private Limited|B\.?V\.?|S\.?r\.?l|AG|K\.?K\.?|Pty|Sdn Bhd|"
                            r"India|Brasil|Brazil|Canada|Mexico|UK|U\.K\.|Ireland|Germany|France|Japan|China|Singapore|"
                            r"Australia|Philippines|Poland|de C\.?V\.?|S\. de R\.L\.)\b", re.I)
LEGAL = re.compile(r"[,\s]+(Inc\.?|Incorporated|LLC|L\.L\.C\.|LLP|Corp\.?|Corporation|Company|Co\.|Ltd\.?|Limited|N\.A\.|L\.?P\.?|P\.?C\.?|PLLC)(?:-Federal)?$", re.I)


def clean_name(n):
    """A posting's legal-entity name made presentable: '0101 The Huntington National Bank' -> 'The Huntington National
    Bank', '00100 LEIDOS, INC' -> 'Leidos'. None when it names a foreign entity or nothing is left."""
    import names
    n = re.sub(r"\s+", " ", str(n or "")).strip()
    if not n or n.upper() in ("UNAVAILABLE", "N/A", "NA", "NONE", "NULL"):
        return None
    # leading entity codes ("0101 ", "US101 ", "(5100) ", "AB3 ", an EIN), "d/b/a", "X, Department of": names.py, the
    # same rules the app applies after a fetch; real number-led names ("84 Lumber", "2020 Companies") are kept
    c = names.clean_display(n)
    if c == n and not re.match(r"(?:\d+(?:st|nd|rd|th)\b)", n) and n.split()[0] not in names._KEEP_NUM:
        c = re.sub(r"^(?:[A-Z]{1,3}\d{2,6}|0\d{1,5}|\d{3,6})\s*[-–:]?\s+(?=\S)", "", n)   # ("1001 Target Corporation" with nothing to compare)
    n = __import__("company_add").strip_code_prefix(c)
    if not n or FOREIGN_ENTITY.search(n):
        return None
    for _ in range(2):
        n = LEGAL.sub("", n).strip(" ,.-")
    if n.isupper() and len(re.sub(r"[^A-Z]", "", n)) > 5:
        n = " ".join(w if len(w) <= 3 and not re.search(r"[AEIOU]", w) else w.capitalize() for w in n.split())
    return n[:60] if len(n) >= 2 else None


def host_name(c):
    """Last resort: a name from the board's address (uhhospitals.taleo.net -> Uhhospitals)."""
    import urllib.parse
    v = str(c.get("host") or c.get("base") or c.get("list_url") or c.get("url") or c.get("sitemap") or "")
    h = urllib.parse.urlsplit(v if "//" in v else "https://" + v).netloc.lower()
    labs = [x for x in h.split(".") if x and x not in ("www", "careers", "career", "jobs", "job", "apply", "recruiting", "secure")]
    return (labs[0].replace("careers-", "").replace("-", " ").title() if labs else c.get("ats", "Employer").title())[:60]


def unwordy(n):
    """A one-word name that doesn't read like a word ("Chordsdp", "Pbssystems" is fine): five consonants in a row."""
    return " " not in n.strip() and bool(re.search(r"[bcdfghjklmnpqrstvwxz]{5}", n.lower()))


def ident_name(c):
    """The name made from the board's address alone ("" when that is only a code)."""
    import company_add
    n = company_add.default_name(c)
    return "" if (company_add.looks_like_code(n) or n.startswith("Employer")) else n


def best_name(t, bname=None):
    """A name people can read, best source first: the starter pack, the posting's employer field, a public employer
    list, the board page's title, the careers address. "" when only a code is known (the app then describes it)."""
    import company_add
    c = t["c"]
    # ("dname": what names.derive made of the board's own postings and page title the last time it was read)
    # ("seed_name": the name the shared directory last published for this board, when the app builds its own: seed.py)
    for n in (t.get("pack_name"), t.get("dname"), clean_name(bname if bname is not None else t.get("bname")), (t.get("seed_name") or "")[:60],
              (t.get("gov_name") or "")[:60], clean_name(t.get("tname")), ident_name(c), company_add.host_label(c, systems.careers_url(c))):
        n = company_add.readable_name(n or "", {}, "")
        if n:
            return n
    return ""


def wants_board_title(t, bname):
    """Should the board page be asked for the employer's name? Only when nothing better is known and the address is a
    code or doesn't read like a name, and not more than once every TNAME_DAYS."""
    if t.get("pack_name") or clean_name(bname) or t.get("gov_name") or t.get("seed_name"):
        return False
    if t.get("tname_at") and _days_since(t["tname_at"]) < TNAME_DAYS:
        return False
    n = ident_name(t["c"])
    return t["c"].get("ats") in OPAQUE or not n or unwordy(n) or bool(re.search(r"\d", n))


def pick_name(t, s):
    """The board's display name after a read. When the usual sources leave a code, a placeholder, a run-together
    address or a legal entity behind a code, names.derive() works the name out from what the read saw: the postings'
    text, the board page's title, the employer field (the app does the same after its own first fetch)."""
    s = s or {}
    t.pop("dname", None)
    n = best_name(t, s.get("name"))
    if t.get("pack_name"):
        return n
    try:
        import names
        raw = n or s.get("name") or ""
        d = names.derive(raw, t["c"], s.get("texts") or [], board_title=s.get("btitle") or t.get("tname"), employer=s.get("name"))
        if d and not names.poor(d, t["c"]):
            t["dname"] = d[:60]
            return best_name(t, s.get("name"))
    except Exception:
        pass
    return n


def lane(c):
    return c.get("ats") or "other"


def read_tenant(t, title_budget=None):
    """Read one board (readers.read) and record what was learnt on its tenant entry: places, open jobs, US-remote jobs,
    name, the date. Returns "ok" (it has jobs), "empty", "failed" (counted; three in a row and the board rests for
    REST_DAYS) or "skipped" (a system the directory doesn't read). title_budget: a one-item list, the board pages that
    may still be asked for the employer's name (None: never ask)."""
    # (a posting or two are opened only when nothing else names this employer: its text then does, names.derive)
    named = t.get("pack_name") or t.get("seed_name") or t.get("gov_name") or t.get("tname") or t.get("dname") or ident_name(t["c"])
    try:
        s = readers.read(dict(t["c"]), details=0 if named else NAME_DETAILS)
    except readers.Skip:
        return "skipped"
    except Exception as e:
        t["fail"] = int(t.get("fail", 0)) + 1
        t["err"] = f"{type(e).__name__}: {str(e)[:100]}"
        if t["fail"] >= 3:
            t["rest_until"] = (dt.date.today() + dt.timedelta(days=REST_DAYS)).isoformat()
        return "failed"
    if s["jobs"] and title_budget and title_budget[0] > 0 and wants_board_title(t, s.get("name")):
        title_budget[0] -= 1
        t["tname_at"] = today()
        try:
            tn = readers.board_name(dict(t["c"]))
            if tn:
                t["tname"] = tn[:80]
                t["_titled"] = True
        except Exception:
            pass
    name = pick_name(t, s)
    kind = "staffing" if STAFFING.search(name or "") else ""
    hints = [h.split(":", 1)[1] for h in t.get("hints", []) if ":" in h]
    t.update(read=today(), fail=0, jobs=s["jobs"], remote=s["remote"], places=board_places(s["locs"], hints, bool(kind)),
             sample=bool(s.get("sample")), name=name, bname=s.get("name"), secs=s.get("secs"), kind=kind)
    t.pop("err", None)
    t.pop("rest_until", None)
    return "ok" if s["jobs"] else "empty"


def read_all(T, args, deadline, want_states):
    reread = {s.strip() for s in (args.reread or "").split(",") if s.strip()}
    reread_st = {s.strip().upper() for s in (getattr(args, "reread_states", "") or "").split(",") if s.strip()}
    todo = []
    for k, t in T.d.items():
        if t.get("rest_until") and t["rest_until"] > today():
            continue
        s = systems.BY_ID.get(t["c"].get("ats"))
        if s is not None and not s.read:
            continue
        if t.get("read") and _days_since(t["read"]) < STALE_DAYS and t["c"].get("ats") not in reread \
                and not (reread_st and any(p[4] in reread_st for p in t.get("places") or [])):
            continue
        todo.append(k)

    def prio(k):
        t = T.d[k]
        hinted = any(h.split(":", 1)[1] in want_states for h in t.get("hints", [])) or \
            bool(reread_st and any(p[4] in reread_st for p in t.get("places") or []))
        return (0 if "pack" in t["src"] else 1 if hinted else 2, 0 if not t.get("read") else 1,
                {"workday": 0, "icims": 1, "greenhouse": 2}.get(t["c"]["ats"], 3), t.get("read") or "")
    todo.sort(key=prio)
    if args.limit:
        todo = todo[:args.limit]
    log(f"read: {len(todo)} boards to read (of {len(T.d)} known)")
    pools = {}
    for k in todo:
        ln = lane(T.d[k]["c"])
        if ln not in pools:
            pools[ln] = cf.ThreadPoolExecutor(LANES.get(ln, LANE_DEFAULT))
    stats = {"ok": 0, "empty": 0, "failed": 0, "skipped": 0, "late": 0, "titles": 0, "sampled": 0}
    done_n = [0]
    title_budget = [int(getattr(args, "titles", 4000) or 0)]

    def one(k):
        if time.time() > deadline:
            stats["late"] += 1
            return
        r = read_tenant(T.d[k], title_budget)
        stats[r] += 1
        if r in ("ok", "empty"):
            stats["titles"] += bool(T.d[k].pop("_titled", False))
            stats["sampled"] += bool(T.d[k].get("sample"))
            done_n[0] += 1
            if done_n[0] % 200 == 0:
                log(f"  read {done_n[0]} boards ({stats})")

    futs = [pools[lane(T.d[k]["c"])].submit(one, k) for k in todo]
    for f in cf.as_completed(futs):
        try:
            f.result()
        except Exception as e:
            log(f"  reader crashed: {type(e).__name__}: {e}")
    for p in pools.values():
        p.shutdown(wait=True)
    # a board found only by a name probe counts only if it hires in that employer's state
    dropped = 0
    for k in list(T.d):
        t = T.d[k]
        need = [h.split(":", 1)[1] for h in t.get("hints", []) if h.startswith("need:")]
        if need and t.get("read") and set(t["src"]) == {"gov"} and not any(p[4] in need for p in t.get("places") or []):
            del T.d[k]
            dropped += 1
    log(f"read: {stats}; {dropped} name-probe boards dropped (no jobs in that employer's state)")
    return stats


# ---------------------------------------------------------------- output
def entry(t, state=None, suffix=""):
    places = [[p[0], p[1], p[2], p[3]] for p in t.get("places") or [] if state is None or p[4] == state]
    places.sort(key=lambda p: -p[2])
    name = best_name(t)
    if name and suffix:
        m = re.fullmatch(r"board (\d+)", suffix)
        if m:   # a second board with no label of its own: say where it hires ("Hondros (Columbus OH #2)"), not "(board 2)"
            top = (places[0][3] if places else "").replace(",", "")
            suffix = f"{top} #{m.group(1)}" if top else f"#{m.group(1)}"
        name = f"{name[:60 - len(suffix) - 3]} ({suffix})"
    e = {"n": name, "c": {k: v for k, v in t["c"].items() if not k.startswith("verified_")}, "u": systems.careers_url(t["c"]), "j": int(t.get("jobs") or 0),
         "r": int(t.get("remote") or 0), "p": places[:PLACES_MAX], "s": t.get("read")}
    if len(places) > PLACES_MAX:
        e["pt"] = 1
    sts = sorted({p[4] for p in t.get("places") or []})
    if 0 < len(sts) <= PS_MAX:
        e["ps"] = sts
    if t.get("sample"):
        e["x"] = 1
        e["mb"] = 1     # only part of a big board was read: "maybe near" for everyone in a state it was seen in
    if t.get("kind") or STAFFING.search(name or ""):
        e["k"] = "staffing"
    return e


def distinct_boards(live):
    """{tenant key: name suffix} for the boards to publish. One entry per distinct career site: every Workday site,
    UKG board and Taleo section of a tenant is kept (10-39% of those systems' jobs sit on a tenant's second or third
    site). Merged: the same board under two spellings of its address, and exact mirrors (two sites of one tenant with
    the same number of jobs in the same places). A tenant's extra sites carry the site's name after the employer's."""
    import company_add
    best = {}
    for k, t in live.items():
        ident = systems.key(t["c"]).lower()
        if ident not in best or ("pack" in t["src"], int(t.get("jobs") or 0), k) > ("pack" in live[best[ident]]["src"], int(live[best[ident]].get("jobs") or 0), best[ident]):
            best[ident] = k
    groups = {}
    for k in best.values():
        c = live[k]["c"]
        tid = (c["ats"], str(c.get("tenant") or c.get("token") or c.get("slug") or c.get("sub") or c.get("base") or c.get("host") or k).lower(),
               str(c.get("wd") or ""))
        groups.setdefault(tid, []).append(k)
    out = {}
    for tid, ks in groups.items():
        ks.sort(key=lambda k: (-("pack" in live[k]["src"]), -int(live[k].get("jobs") or 0), k))
        seen, kept = set(), []
        for k in ks:
            t = live[k]
            sig = (int(t.get("jobs") or 0), tuple(sorted((p[0], p[1], p[2]) for p in t.get("places") or [])[:40]))
            if len(ks) > 1 and sig in seen:
                continue                    # an exact mirror of a site already kept
            seen.add(sig)
            kept.append(k)
        for i, k in enumerate(kept):
            c = live[k]["c"]
            lab = str(c.get("site") or c.get("section") or "").replace("_", " ").strip()
            out[k] = "" if i == 0 else (lab if lab and not company_add.looks_like_code(lab) else f"board {i + 1}")
    return out


def bucket_jobs(items, src):
    """{state or 'remote': [job]} with each job's geocoded places."""
    out = {}
    for j in items:
        if not j.get("u") or not j.get("t"):
            continue
        pts, sts = [], set()
        for lab in j.get("l") or []:
            p = place_of(lab)
            if p:
                pts.append([p[0], p[1]])
                sts.add(p[2])
        rec = {"src": src, "t": j["t"][:200], "o": (j.get("o") or "")[:100], "u": j["u"][:1000], "l": [l[:100] for l in (j.get("l") or [])[:6]],
               "p": pts[:6], "w": j.get("w") or "", "pay": j.get("pay"), "d": j.get("d") or "", "x": (j.get("x") or "")[:400]}
        for s in sts:
            out.setdefault(s, []).append(rec)
        if j.get("w") == "remote":
            out.setdefault("remote", []).append(rec)
    return out


def live_boards(T):
    """(live, by_state): the boards to publish (read within KEEP_DAYS, with open jobs, not a job board re-posting
    others' jobs; one per distinct career site, each carrying its name suffix as "_suffix") and the same boards per
    state they hire in. Call drop_suffixes(live) when done."""
    live = {k: t for k, t in T.d.items() if t.get("read") and _days_since(t["read"]) <= KEEP_DAYS and int(t.get("jobs") or 0) > 0}
    live = {k: t for k, t in live.items() if not AGGREGATOR.search(best_name(t) or "")}     # (job boards re-posting others' jobs)
    suffix = distinct_boards(live)
    live = {k: live[k] for k in suffix}
    same = {}
    for t in live.values():
        nm = best_name(t).lower()
        same[nm] = same.get(nm, 0) + 1
    for k, t in live.items():   # a board whose own name already tells it apart needs no suffix
        if suffix[k] and same.get(best_name(t).lower(), 0) == 1:
            suffix[k] = ""
    for k, t in live.items():
        t["_suffix"] = suffix[k]
    by_state = {}
    for t in live.values():
        for s in {p[4] for p in t.get("places") or []}:
            by_state.setdefault(s, []).append(t)
    return live, by_state


def drop_suffixes(live):
    for t in live.values():
        t.pop("_suffix", None)


def write_states(out, live, by_state, states, built, remote=True):
    """Write states/<ST>.json.gz for these states (and states/remote.json.gz) in the published format. Returns the
    manifest entries {name: {employers, bytes, sha256}}."""
    man = {}
    for st in states:
        emps = sorted((entry(t, st, t.get("_suffix", "")) for t in by_state.get(st, [])), key=lambda e: (-sum(p[2] for p in e["p"]), e["n"].lower()))
        data = save_json_gz(os.path.join(out, "states", f"{st}.json.gz"), {"v": 1, "state": st, "built": built, "employers": emps})
        man[st] = {"employers": len(emps), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if remote:
        rem = sorted(({k: v for k, v in (entry(t, None, t.get("_suffix", "")) | {"p": []}).items() if k not in ("pt", "ps", "mb")}
                      for t in live.values() if int(t.get("remote") or 0) > 0), key=lambda e: -e["r"])[:5000]
        data = save_json_gz(os.path.join(out, "states", "remote.json.gz"), {"v": 1, "state": "remote", "built": built, "employers": rem})
        man["remote"] = {"employers": len(rem), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return man


def write(out, T, jobs_by, want_states, stats, t0, prior_manifest, keep_jobs=False):
    man = {"v": 1, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "states": {}, "jobs": {},
           "sources": {}, "stats": stats}
    live, by_state = live_boards(T)
    man["states"] = write_states(out, live, by_state, want_states, man["built"])
    drop_suffixes(live)
    # the seed: every board the builder knows, with its last-known name and states, for people who build the directory
    # on their own computer (index_build/local.py); releases ship the latest one (scripts/refresh_seed.py)
    from . import seed
    data = seed.dumps(seed.make(T.d, man["built"][:10]))
    with open(os.path.join(out, seed.FILE), "wb") as f:
        f.write(data)
    man["seed"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "boards": seed.count(data)}
    njobs = 0
    for st in ([] if keep_jobs else list(want_states) + ["remote"]):
        items = jobs_by.get(st, [])
        if not items:
            continue
        data = save_json_gz(os.path.join(out, "jobs", f"{st}.json.gz"), {"v": 1, "state": st, "built": man["built"], "jobs": items})
        man["jobs"][st] = {"jobs": len(items), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        njobs += len(items)
    # states not built this run keep their earlier files (a --states sample run doesn't wipe the rest)
    for kind in ("states", "jobs"):
        for st, ent in ((prior_manifest or {}).get(kind) or {}).items():
            if st not in man[kind] and os.path.exists(os.path.join(out, kind, f"{st}.json.gz")) and \
                    (st not in want_states or (kind == "jobs" and keep_jobs)):
                man[kind][st] = ent
    if keep_jobs:       # (a run without the postings step keeps the earlier job snapshots and their sources)
        man["sources"] = dict((prior_manifest or {}).get("sources") or {})
        njobs = sum(int(v.get("jobs") or 0) for v in man["jobs"].values())
    for sid, (label, attr) in postings.SOURCES.items():
        if any(j["src"] == sid for js in jobs_by.values() for j in js):
            man["sources"][sid] = {"label": label, "attribution": attr}
    man["stats"].update(employers=len(live), boards_known=len(T.d), run_minutes=round((time.time() - t0) / 60, 1),
                        http=dict(net.STATS))
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, sort_keys=True)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.format(built=man["built"], employers=len(live), jobs=njobs))
    return man


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Siftwell employer directory.")
    ap.add_argument("--out", required=True, help="output folder (the index branch's working tree)")
    ap.add_argument("--states", default="", help="comma-separated state codes to write (default: all)")
    ap.add_argument("--limit", type=int, default=0, help="read at most this many boards this run")
    ap.add_argument("--minutes", type=float, default=300, help="stop starting new reads after this many minutes")
    ap.add_argument("--crawls", type=int, default=2, help="newest Common Crawl crawls to look through")
    ap.add_argument("--cc-blocks", type=int, default=400, help="Common Crawl index blocks per URL prefix, at most")
    ap.add_argument("--ct-probe", type=int, default=200, help="Workday tenants whose robots.txt lists no site: guess the usual site names for this many")
    ap.add_argument("--wd-sites", type=int, default=4000, help="Workday tenants whose robots.txt (list of career sites) is read this run")
    ap.add_argument("--wdc", type=int, default=4000, help="Web Data Commons domains to check this run, at most")
    ap.add_argument("--wdc-minutes", type=float, default=45, help="time box for the Web Data Commons pass")
    ap.add_argument("--titles", type=int, default=4000, help="board pages asked for the employer's name this run, at most")
    ap.add_argument("--lca-file", default=os.environ.get("DOL_LCA_FILE") or os.environ.get("DOL_LCA_URL") or "")
    ap.add_argument("--no-cc", action="store_true")
    ap.add_argument("--no-ct", action="store_true")
    ap.add_argument("--no-names", action="store_true", help="skip DOL LCA names (only used with --lca-file)")
    ap.add_argument("--no-wdc", action="store_true")
    ap.add_argument("--no-postings", action="store_true")
    ap.add_argument("--no-read", action="store_true", help="discover only")
    ap.add_argument("--reread", default="", help="comma-separated job systems to read again even if read this week")
    ap.add_argument("--reread-states", default="", help="read again (and first) the boards known to hire in these states")
    args = ap.parse_args(argv)
    net.install()       # every request, also the app readers', paced per provider (net.py: polite by design)
    t0 = time.time()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    want = [s.strip().upper() for s in args.states.split(",") if s.strip()] or ALL_STATES
    bad = [s for s in want if s not in ALL_STATES]
    if bad:
        ap.error(f"unknown state codes: {bad}")
    state_path = os.path.join(out, "_state", "builder.json.gz")
    st = load_json_gz(state_path, {})
    try:
        prior = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    except (OSError, ValueError):
        prior = None
    T = Tenants(os.path.join(out, "_state", "tenants.json.gz"))
    log(f"directory build: {len(T.d)} boards known from earlier runs; states {','.join(want) if len(want) < 10 else str(len(want)) + ' states'}")

    seed_packs(T)
    wd_extra = set()
    if not args.no_cc:
        crawls = cc.latest_crawls(args.crawls)
        log(f"Common Crawl: {crawls or 'unavailable'}")
        discover_cc(T, crawls, args.cc_blocks, wd_extra)
        T.save()
    if not args.no_ct:
        discover_ct(T, wd_extra)
        T.save()
    if args.wd_sites:
        workday_sites_pass(T, st, wd_extra, args.wd_sites, 0 if args.no_ct else args.ct_probe)
        T.save()
        save_json_gz(state_path, st)
    hn_items, hn_links = ([], []) if args.no_postings else postings.hn(log)
    for u in hn_links:
        T.add(systems.parse(u), "hn")
    if not args.no_names and args.lca_file:
        discover_names(T, gov.lca(args.lca_file, set(want), log=log)[:5000])
    if not args.no_wdc:
        discover_wdc(T, st, args.wdc, time.time() + args.wdc_minutes * 60)
        save_json_gz(state_path, st)
    log(f"discovery: {len(T.d)} boards known; new this run by source: {T.new}")
    T.save()
    stats = {"discovered_new": T.new}
    if not args.no_read:
        deadline = t0 + args.minutes * 60
        stats["read"] = read_all(T, args, deadline, set(want))
        T.save()
    jobs_by = {}
    if not args.no_postings:
        for sid, items in (("usajobs", postings.usajobs(log)), ("careeronestop", postings.careeronestop(want, log)),
                           ("schoolspring", postings.schoolspring(log)), ("hn", hn_items), ("muse", postings.muse(log))):
            for k, v in bucket_jobs(items, sid).items():
                jobs_by.setdefault(k, []).extend(v)
    save_json_gz(state_path, st)
    man = write(out, T, jobs_by, want, stats, t0, prior, keep_jobs=args.no_postings)
    log(f"done in {man['stats']['run_minutes']} min: {man['stats']['employers']} employers with jobs, "
        f"{sum(v['employers'] for k, v in man['states'].items() if k != 'remote')} state entries, "
        f"{sum(v['jobs'] for v in man['jobs'].values())} snapshot postings")
    return 0
