"""Add a company from a careers-page link: detect its job-posting system, confirm the feed works, save it."""
import json, os, re, threading, urllib.request

import people

import catalog
import netsafe
import paths
HERE = paths.APP
UA = {"User-Agent": "Mozilla/5.0 (personal job board)"}
_lock = threading.Lock()

PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("workday", re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("icims", re.compile(r"(https://[a-z0-9-]+\.icims\.com)")),
    ("ukg", re.compile(r"(recruiting2?\.ultipro\.com)/([A-Za-z0-9]+)/JobBoard/([0-9a-fA-F-]{36})")),
    ("oracle", re.compile(r"(https://[a-z0-9-]+\.fa\.[a-z0-9-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/([A-Za-z0-9_]+)")),
    ("paylocity", re.compile(r"recruiting\.paylocity\.com/recruiting/jobs/(?:All|Details/\d+)/([0-9a-fA-F-]{36})", re.I)),
    ("adp", re.compile(r"workforcenow\.adp\.com/[^\s\"']*?[?&]cid=([0-9a-fA-F-]{36})")),
    ("ukg", re.compile(r"([a-z0-9-]+\.rec\.pro\.ukg\.net)/([A-Za-z0-9]+)/JobBoard/([0-9a-fA-F-]{36})")),
    ("rippling", re.compile(r"ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/(?!j/|api/)([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"(?:^|[/\"'\s=@])([a-z0-9-]+)\.workable\.com", re.I)),
    ("bamboohr", re.compile(r"(?:^|[/\"'\s=@])([a-z0-9-]+)\.bamboohr\.com", re.I)),
    ("jazzhr", re.compile(r"(?:^|[/\"'\s=@])([a-z0-9-]+)\.applytojob\.com", re.I)),
    ("breezy", re.compile(r"(?:^|[/\"'\s=@])([a-z0-9-]+)\.breezy\.hr", re.I)),
    ("recruitee", re.compile(r"(?:^|[/\"'\s=@])([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("paycom", re.compile(r"paycomonline\.net/v4/ats/web\.php/(?:jobs\?clientkey=|portal/)([A-F0-9]{32})")),
    ("saashr", re.compile(r"(secure\d*\.saashr\.com)/ta/(\d+)\.careers", re.I)),
    ("dayforce", re.compile(r"jobs\.dayforcehcm\.com/(?:[a-z]{2}-[A-Z]{2}/)?([a-zA-Z0-9]+)/([A-Za-z0-9]+)")),
]
BAD_TOKENS = {"www", "app", "api", "apply", "assets", "static", "cdn", "help", "support", "jobs", "careers", "widget", "embed", "j"}

def _get(url, data=None, timeout=45, cap=40_000_000):
    req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"} if data else {})})
    with netsafe.urlopen(req, timeout=timeout) as r:  # (http/https to public hosts only, redirects re-checked)
        return r.read(cap)

def _match(text):
    for ats, rx in PATTERNS:
        m = rx.search(text)
        if m:
            if ats == "workday":
                if m.group(3).lower() in ("wday", "cxs"):
                    continue
                return {"ats": "workday", "tenant": m.group(1), "wd": m.group(2), "site": m.group(3)}
            if ats == "icims":
                if re.match(r"https://(www|cdn\d*|images|provider|login)\.", m.group(1)):
                    continue
                return {"ats": "icims", "base": m.group(1)}
            if ats == "ukg":
                return {"ats": "ukg", "host": m.group(1), "tenant": m.group(2), "board": m.group(3)}
            if ats == "oracle":
                return {"ats": "oracle", "base": m.group(1), "site": m.group(2)}
            if ats == "paylocity":
                return {"ats": "paylocity", "id": m.group(1)}
            if ats == "adp":
                return {"ats": "adp", "cid": m.group(1)}
            if ats in ("workable", "bamboohr", "jazzhr", "breezy", "recruitee", "rippling"):
                if m.group(1).lower() in BAD_TOKENS:
                    continue
                return {"ats": ats, "token": m.group(1)}
            if ats == "paycom":
                return {"ats": "paycom", "key": m.group(1)}
            if ats == "saashr":
                return {"ats": "saashr", "host": m.group(1), "cid": m.group(2)}
            if ats == "dayforce":
                return {"ats": "dayforce", "ns": m.group(1), "board": m.group(2)}
            return {"ats": ats, "token": m.group(1)}
    return None

def detect(url):
    """Return ATS fields for a careers link, looking inside the page if the link itself isn't a job board."""
    url = (url or "").strip()[:2000]
    if not re.match(r"https?://", url, re.I):
        if re.match(r"[a-z][a-z0-9+.-]*:(?!\d)", url, re.I):  # file:, javascript:, ftp: ... (but not host:port)
            raise ValueError("Paste a web link that starts with https:// (or http://).")
        url = "https://" + url
    try:
        netsafe.check_url(url, resolve=False)
    except netsafe.UnsafeURL as e:
        raise ValueError(str(e))
    found = _match(url)
    if not found:
        try:
            page = _get(url, timeout=20, cap=3_000_000).decode("utf-8", "replace")
        except netsafe.UnsafeURL as e:
            raise ValueError(f"Couldn't open that page: {e}")
        except Exception as e:
            raise ValueError(f"Couldn't open that page ({type(e).__name__}).")
        found = _match(page)
        if not found:
            try:
                import jsonld_fetcher
                found = jsonld_fetcher.detect_config(url, page)
            except Exception:
                found = None
    if not found:
        raise ValueError("Couldn't find a supported job board on that page, and the site doesn't publish standard job data Siftwell can read. Supported: Greenhouse, Lever, Ashby, Workday, "
                         "SmartRecruiters, iCIMS, UKG, Oracle, Paylocity, ADP, Workable, BambooHR, JazzHR, Breezy, Recruitee, Paycom, Dayforce, Rippling, and custom careers sites that publish standard job data. Tip: open the company's job list and paste the link from the address bar.")
    cfg, why = netsafe.clean_config(found)
    if cfg is None:
        raise ValueError(f"Found a job board on that page, but its settings look wrong ({why}).")
    return cfg

def verify(c):
    """Return (job count, suggested name) from the live feed, or raise."""
    a = c["ats"]
    try:
        netsafe.check_config(c)
    except netsafe.UnsafeURL as e:
        raise ValueError(str(e))
    try:
        if a == "greenhouse":
            jobs = json.loads(_get(f"https://boards-api.greenhouse.io/v1/boards/{c['token']}/jobs"))["jobs"]
            try:
                name = json.loads(_get(f"https://boards-api.greenhouse.io/v1/boards/{c['token']}")).get("name")
            except Exception:
                name = None
            return len(jobs), name
        if a == "lever":
            return len(json.loads(_get(f"https://api.lever.co/v0/postings/{c['token']}?mode=json&limit=100"))), None
        if a == "ashby":
            return len(json.loads(_get(f"https://api.ashbyhq.com/posting-api/job-board/{c['token']}"))["jobs"]), None
        if a == "smartrecruiters":
            return json.loads(_get(f"https://api.smartrecruiters.com/v1/companies/{c.get('token') or c.get('id')}/postings?limit=1")).get("totalFound", 0), None
        if a == "workday":
            body = json.dumps({"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).encode()
            d = json.loads(_get(f"https://{c['tenant']}.{c['wd']}.myworkdayjobs.com/wday/cxs/{c['tenant']}/{c['site']}/jobs", body))
            return d.get("total", 0), None
        if a in ("icims", "ukg", "oracle", "paylocity", "adp", "rippling", "workable", "bamboohr", "jazzhr", "breezy",
                 "recruitee", "paycom", "saashr", "dayforce", "phenom", "jibe", "amazon", "clearcompany"):
            import sys
            sys.path.insert(0, HERE)
            import extra_fetchers, smb_fetchers
            fx = {**extra_fetchers.FETCHERS, **smb_fetchers.FETCHERS}
            n = 0
            for _ in fx[a](dict(c, name="check")):
                n += 1
                if n >= 400:
                    break
            return n, None
        if a == "jsonld":
            import sys
            sys.path.insert(0, HERE)
            import jsonld_fetcher
            cc = dict(c, name="check")
            posts = list(jsonld_fetcher.fetch_postings(cc, cap=8, sample=True))
            if not posts:
                raise ValueError("no JobPosting found")
            return max(len(posts), cc.get("_url_count", 0)), next((p["org"] for p in posts if p["org"]), None)
    except netsafe.UnsafeURL as e:
        raise ValueError(f"Found a {a} board, but Siftwell won't contact it: {e}")
    except Exception as e:
        raise ValueError(f"Found a {a} board, but its job feed didn't respond ({type(e).__name__}).")
    raise ValueError("Unsupported job board.")

def default_name(c, suggested=None, name=""):
    """The name a new company gets: the one typed, else the board's own name, else one made from its config."""
    if c["ats"] == "jsonld" and not suggested:
        import urllib.parse
        h = urllib.parse.urlsplit(c.get("list_url") or c.get("sitemap") or "").netloc.lower().removeprefix("www.").split(":")[0]
        suggested = h.rsplit(".", 1)[0].split(".")[-1] if "." in h else h
    ident = c.get("token") or c.get("tenant") or c.get("ns") or c.get("cid") or c.get("key") or c.get("id") or re.sub(r"^https://|\..*$", "", c.get("base", "")).replace("careers-", "")
    # (no commas: an update for named companies takes a comma-separated list)
    return (name or suggested or str(ident).replace("-", " ").replace("_", " ").title()).replace(",", "").strip()[:60]

def save_found(c, nm, set_id, pid, sector="Added by you"):
    """Save a detected board as a company in list set_id, or add that list to the company already using this board.
    Returns (entry, existing)."""
    with _lock:
        cos = catalog.companies()
        same = next((x for x in cos if x["ats"] == c["ats"] and all(x.get(k) == v for k, v in c.items())), None)
        if same:
            sets = set(same.get("sets") or ["tech"])
            sets.add(set_id)
            same["sets"] = sorted(sets)
            entry = same
        else:
            if any(x["name"].lower() == nm.lower() for x in cos):
                nm = f"{nm} ({c['ats']})"
            entry = {"name": nm, "tier": "dmv_office", "sector": sector, **c, "sets": [set_id], "added_by": pid}
        catalog.save_company(entry)
    return entry, bool(same)

def add(url, name="", scope="me", target_set=None):
    """target_set: the company list to put it in (default: "all" for scope "all", else the person's own additions)."""
    c = detect(url)
    total, suggested = verify(c)
    if not total:
        raise ValueError("That job board is reachable but has no open jobs right now.")
    pid = people.current()
    nm = default_name(c, suggested, name)
    entry, same = save_found(c, nm, target_set or ("all" if scope == "all" else f"own-{pid}"), pid)
    return {"name": entry["name"], "ats": c["ats"], "open_jobs": total, "existing": same}

def own(pid=None):
    pid = pid or people.current()
    return [{"name": c["name"], "ats": c["ats"], "everyone": "all" in (c.get("sets") or [])}
            for c in catalog.companies() if f"own-{pid}" in (c.get("sets") or []) or c.get("added_by") == pid]
