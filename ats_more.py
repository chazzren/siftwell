"""Readers for three more job systems: Radancy (TalentBrew), Eightfold AI and Avature.

Every request goes through netsafe (public http/https hosts only), checks the site's robots.txt first (longest matching
rule wins, the way search engines read it), waits between requests and never runs more than 2 at once per company. A site
that answers 401/403/429 is not worked around: the company just reports an error.

Config fields per "ats":

  radancy    base   - https://jobs.example.com (a TalentBrew career site: it loads "tbcdn.talentbrew.com" files and
                      lists jobs at /search-jobs and /job/<place>/<title>/<org id>/<job id>).
                      feed: GET {base}/search-jobs/results?... (JSON whose "results" holds the list as HTML, 100 per
                      page, filtered to the site's "United States" country facet); a posting page carries schema.org
                      JobPosting data (description, date, pay). Some sites forbid /search-jobs/ in robots.txt: then the
                      sitemap's /job/ pages are read instead (jsonld_fetcher).
  eightfold  host, domain - career site on Eightfold AI: host is {company}.eightfold.ai or the company's own
                      careers domain, domain is the company's Eightfold domain (e.g. nvidia.com; shown in the career
                      page's own settings). feed: GET https://{host}/api/pcsx/search?domain=..&location=United+States
                      &start=N (10 per page); detail GET /api/pcsx/position_details?position_id=..&domain=..
  avature    base, portal - Avature portal, e.g. https://koch.avature.net with portal "careers" (the path before
                      /SearchJobs; may start with a locale such as en_US/careers). feed: the HTML job list at
                      {base}/{portal}/SearchJobs/?jobOffset=N (the page size is the site's own, often 6 to 12);
                      detail page /{portal}/JobDetail/<slug>/<id> for the description.

Full text costs one request per job, so it is fetched only for titles someone's filters could want (the rest are stored
as partial rows, like Workday). Locations are turned into "City, ST" and jobs outside the US are dropped here."""
import gzip, io, json, re, sys, time, threading, datetime, html as _html, urllib.parse, urllib.request, urllib.error
import concurrent.futures as cf
import netsafe
from jobfinder import J, strip_html, NON_US

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
GAP = 0.3             # seconds between requests to the same site
WORKERS = 2           # at most this many requests at once for one company
LIST_PAGES = 150      # list pages per run (Avature / Radancy)
EF_CAP = 2000         # Eightfold postings per run (10 per request)
SITEMAP_CAP = 1500    # posting pages per run when a Radancy site only offers its sitemap


class Blocked(Exception):
    """robots.txt forbids the address (nothing was requested)."""


# ---------------------------------------------------------------- polite http
_pace_lock = threading.Lock()
_next_ok = {}


def _pace(host):
    with _pace_lock:
        now = time.time()
        t = max(now, _next_ok.get(host, 0))
        _next_ok[host] = t + GAP
    if t > now:
        time.sleep(t - now)


def fetch(url, headers=None, robots=True, tries=3, cap=4_000_000):
    """(text, final url). Raises Blocked, netsafe.UnsafeURL or urllib errors (403 and the like are not retried)."""
    if robots and not robots_ok(url):
        raise Blocked(f"robots.txt forbids {urllib.parse.urlsplit(url).path[:60]}")
    host = urllib.parse.urlsplit(url).netloc.lower()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,application/xml,*/*;q=0.8",
                                               "Accept-Encoding": "gzip", **(headers or {})})
    for i in range(tries):
        _pace(host)
        try:
            with netsafe.urlopen(req, timeout=30) as r:
                raw = r.read(cap)
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(cap * 3)
                return raw.decode(r.headers.get_content_charset() or "utf-8", "replace"), r.geturl()
        except netsafe.UnsafeURL:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                ra = e.headers.get("Retry-After") if e.headers else None
                time.sleep(min(30, float(ra) if ra and ra.isdigit() else 3 * 2 ** i))
                continue
            raise
        except (urllib.error.URLError, OSError):
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def get_json(url, **kw):
    return json.loads(fetch(url, headers={"Accept": "application/json"}, **kw)[0])


# ---------------------------------------------------------------- robots.txt (longest matching rule wins; Allow wins ties)
_robots = {}
_robots_lock = threading.Lock()


def parse_robots(text, agent="siftwell"):
    """[(is_allow, pattern)] for our group (our own name, else '*')."""
    groups, cur, seen_rule = [], None, False
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if cur is None or seen_rule:
                cur, seen_rule = {"agents": [], "rules": []}, False
                groups.append(cur)
            cur["agents"].append(v.lower())
        elif k in ("allow", "disallow") and cur is not None:
            seen_rule = True
            if v:
                cur["rules"].append((k == "allow", v))
    for want in (agent, "*"):
        rules = [r for g in groups if want in g["agents"] for r in g["rules"]]
        if rules or any(want in g["agents"] for g in groups):
            return rules
    return []


def _pat(p):
    rx = re.escape(p).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.compile(rx)


def rules_allow(rules, path_query):
    best, allow = -1, True
    for ok, p in rules:
        if _pat(p).match(path_query) and (len(p) > best or (len(p) == best and ok)):
            best, allow = len(p), ok
    return allow


def robots_ok(url):
    sp = urllib.parse.urlsplit(url)
    root = f"{sp.scheme}://{sp.netloc}"
    with _robots_lock:
        ent = _robots.get(root)
        if ent and time.time() - ent[0] < 3600:
            rules = ent[1]
        else:
            rules = None
    if rules is None:
        try:
            rules = parse_robots(fetch(root + "/robots.txt", robots=False, tries=2, cap=500_000)[0])
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                rules = []        # (no robots.txt: no restrictions)
            else:
                raise Blocked(f"robots.txt unavailable (HTTP {e.code})")
        except netsafe.UnsafeURL:
            raise
        except Exception:
            raise Blocked("robots.txt unavailable")
        with _robots_lock:
            _robots[root] = (time.time(), rules)
    return rules_allow(rules, (sp.path or "/") + (("?" + sp.query) if sp.query else ""))


# ---------------------------------------------------------------- locations (US only)
_US_NAMES = {"us", "usa", "u.s", "u.s.a", "united states", "united states of america", "america"}
_STATES = None


def _states():
    global _STATES
    if _STATES is None:
        import jsonld_fetcher
        names = dict(jsonld_fetcher._STATE_ABBR)
        _STATES = (names, set(names.values()))
    return _STATES


def _state(s):
    names, abbrs = _states()
    s = (s or "").strip().rstrip(".")
    if s.upper() in abbrs and (len(s) == 2):
        return s.upper()
    return names.get(s.lower())


_NONUS_RX = re.compile(r"\b(?:" + "|".join(re.escape(x.strip()) for x in NON_US if x.strip()) + r")\b", re.I)


def us_label(s):
    """One location label -> "City, ST" (or a US-looking label as given), or None when it is outside the US."""
    s = re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip(" ,;|")
    if not s:
        return None
    m = re.match(r"^(?:US|USA|United States(?: of America)?)\s*[-/]\s*([A-Za-z .]+?)\s*[-/]\s*(.+)$", s)
    if m and _state(m.group(1)):
        return f"{m.group(2).strip()}, {_state(m.group(1))}"
    parts = [p.strip() for p in s.split(",") if p.strip()]
    country_us = False
    if len(parts) > 1 and parts[-1].lower().rstrip(".") in _US_NAMES:
        parts.pop()
        country_us = True
    elif len(parts) > 2 and parts[0].lower().rstrip(".") in _US_NAMES and _state(parts[1]):   # "US, CA, Santa Clara"
        return f"{', '.join(parts[2:])}, {_state(parts[1])}"
    if len(parts) == 1:
        if parts[0].lower().rstrip(".") in _US_NAMES:
            return "United States"
        w = parts[0]
        if _state(w) or country_us:
            return w
        if _NONUS_RX.search(w):
            return None
        if re.search(r"remote|virtual|anywhere|work from home|telecommut|\bhome\b", w, re.I):
            return w
        try:   # a bare place name: keep it only if the offline US gazetteer knows it (so "Atlanta" yes, "ChengDu" no)
            import geo
            return w if geo.locate(w) else None
        except Exception:
            return w
    st = _state(parts[-1])
    if st:
        city = parts[0].title() if parts[0].isupper() and len(parts[0]) > 3 else parts[0]
        return f"{city}, {st}"
    if country_us:
        return ", ".join(parts)
    return None   # "City, Region" where the region isn't a US state: a place abroad


def us_locations(labels):
    """(labels as "City, ST", outside_only): outside_only is True when there were locations and none is in the US."""
    labels = [l for l in labels if l and str(l).strip()]
    out = []
    for l in labels:
        u = us_label(l)
        if u and u not in out:
            out.append(u)
    return out, bool(labels) and not out


def _wp(s):
    s = (s or "").lower()
    return "remote" if "remote" in s or "telecommut" in s else "hybrid" if "hybrid" in s else "onsite" if "onsite" in s or "on-site" in s else ""


def _wanted(c, title):
    from extra_fetchers import wanted
    return wanted(c, title)


def _pool(fn, items):
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        yield from ex.map(fn, items)


def _label(host_or_domain):
    """A readable company name from a host name: careers.keurigdrpepper.com -> Keurigdrpepper."""
    parts = [p for p in re.sub(r":\d+$", "", host_or_domain.lower()).split(".") if p]
    if len(parts) >= 2 and parts[-2] in ("co", "com", "org", "net", "gov") and len(parts) >= 3:
        core = parts[-3]
    else:
        core = parts[-2] if len(parts) >= 2 else parts[0]
    if core in ("eightfold", "avature", "talentbrew"):
        core = parts[0]
    return core.replace("-", " ").title()


# ================================================================ Radancy / TalentBrew
def tb_results_url(base, page, per=100, facet=None):
    q = [("CurrentPage", page), ("RecordsPerPage", per), ("Distance", 50), ("RadiusUnitType", 0), ("ShowRadius", "False"),
         ("SearchResultsModuleName", "Search Results"), ("SearchFiltersModuleName", "Search Filters"),
         ("SortCriteria", 0), ("SortDirection", 0), ("SearchType", 5)]
    if facet:
        q += [("ActiveFacetID", facet), ("FacetFilters[0].ID", facet), ("FacetFilters[0].FacetType", 2), ("FacetFilters[0].IsApplied", "true")]
    return base + "/search-jobs/results?" + urllib.parse.urlencode(q)


def tb_us_facet(filters_html):
    """The id of the "United States" country facet, or None."""
    for m in re.finditer(r'data-facet-type="2"[^>]*?data-id="(\d+)"[^>]*?data-display="([^"]*)"', filters_html or ""):
        if _html.unescape(m.group(2)).strip().lower() in _US_NAMES:
            return m.group(1)
    return None


_TB_A = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)


def tb_cards(results_html):
    """[{id, href, title, loc, dept}] from one page of a TalentBrew result list (any template that links each job with
    /job/... and data-job-id)."""
    h = results_html or ""
    hits, seen = [], set()
    for m in _TB_A.finditer(h):
        attrs = m.group(1)
        jid = re.search(r'data-job-id="(\d+)"', attrs)
        href = re.search(r'href="([^"]*/job/[^"]*)"', attrs)
        if not (jid and href) or jid.group(1) in seen:
            continue
        seen.add(jid.group(1))
        hits.append((m.start(), m.end(), jid.group(1), _html.unescape(href.group(1)), m.group(2)))
    out = []
    for i, (st, en, jid, href, inner) in enumerate(hits):
        chunk = h[en:hits[i + 1][0] if i + 1 < len(hits) else len(h)]
        title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        loc = re.search(r'class="[^"]*job-location[^"]*"[^>]*>(.*?)</', chunk, re.S)
        loc = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", loc.group(1)))).strip() if loc else ""
        dept = re.search(r'class="[^"]*facet-item[^"]*"[^>]*>\s*(?:[^:<]{1,40}:)?\s*([^<]+)', chunk)
        out.append({"id": jid, "href": href.split("#")[0], "title": title, "loc": loc,
                    "dept": re.sub(r"\s+", " ", _html.unescape(dept.group(1))).strip() if dept else ""})
    return out


def tb_total(results_html):
    m = re.search(r'data-total-results="(\d+)"', results_html or "")
    return int(m.group(1)) if m else None


def tb_page(base, page, per=100, facet=None):
    d = json.loads(fetch(tb_results_url(base, page, per, facet), headers={"Accept": "application/json"})[0])
    return d.get("results") or "", d.get("filters") or ""


def tb_can_search(base):
    try:
        return robots_ok(base + "/search-jobs/results?CurrentPage=1")
    except Blocked:
        return False


def f_radancy(c):
    base = c["base"].rstrip("/")
    if not tb_can_search(base):
        yield from _radancy_sitemap(c)
        return
    first, filters = tb_page(base, 1, 100)
    facet = tb_us_facet(filters)
    if facet:
        first, _ = tb_page(base, 1, 100, facet)
    total = tb_total(first)
    cards, seen, page, html_ = [], set(), 1, first
    while True:
        new = [x for x in tb_cards(html_) if x["id"] not in seen]
        for x in new:
            seen.add(x["id"])
            cards.append(x)
        if not new or (total is not None and len(seen) >= total):
            break
        if page >= LIST_PAGES:
            c["_truncated"] = f"stopped after {page} pages: {len(seen)} of {total}"
            break
        page += 1
        html_, _ = tb_page(base, page, 100, facet)
    if total and len(seen) < total and not c.get("_truncated"):
        c["_truncated"] = f"empty page at {len(seen)} of {total}"
    from jsonld_fetcher import normalize, postings_in

    def one(x):
        url = urllib.parse.urljoin(base + "/", x["href"])
        locs, outside = us_locations(re.split(r"\s*[|;]\s*", x["loc"]) if x["loc"] else [])
        multi = (not x["loc"]) or bool(re.search(r"multiple|various|locations", x["loc"], re.I))
        if outside:
            return None
        title, d, partial = x["title"], {}, False
        if _wanted(c, title) or multi:
            try:
                page = fetch(url)[0]
                n = next((n for n in (normalize(o, url) for o in postings_in(page)) if n), None)
                if n:
                    d = n
                else:
                    partial = True
            except Exception:
                partial = True
        else:
            partial = True
        if d.get("locations"):
            dl, _ = us_locations(d["locations"])
            if multi and d["locations"] and not dl:
                return None
            locs = dl or locs
        j = J(c, title, url, locs, d.get("workplace", ""), d.get("salary"), d.get("desc", ""), d.get("posted", ""), x["dept"], x["id"])
        if partial:
            j["_partial"] = True
        return j
    for j in _pool(one, cards):
        if j:
            yield j


_TB_US = "6252001"   # (geonames id of the United States, the first part of a posting page's job-location-ids)


def tb_page_job(h, url):
    """One posting page -> {title, url, locations, workplace, salary, desc, posted, dept, id} or None (outside the US)."""
    from jsonld_fetcher import normalize, postings_in
    n = next((n for n in (normalize(o, url) for o in postings_in(h)) if n), None)
    if not n:
        return None
    ids = re.search(r'<meta name="job-location-ids" content="([^"]*)"', h)
    if ids and ids.group(1).strip():
        if not any(x.strip().startswith(_TB_US) for x in re.split(r"[,;|]", ids.group(1))):
            return None
    labels = [re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m))).strip()
              for m in re.findall(r'class="[^"]*\bjob-location\b[^"]*"[^>]*>([^<]*)<', h)]
    labels = [l for l in labels if l] or n["locations"]
    locs, outside = us_locations(labels)
    if outside:
        return None
    jid = re.sub(r"\D", "", url.rstrip("/").rsplit("/", 1)[-1]) or n["ident"] or url
    return {"title": n["title"], "url": url, "locations": locs, "workplace": n["workplace"], "salary": n["salary"],
            "desc": n["desc"], "posted": n["posted"], "dept": n["dept"], "id": jid}


def _radancy_sitemap(c):
    """For a site whose robots.txt forbids /search-jobs/: its sitemap lists every posting page (all countries); each
    page is read for its JobPosting data. Pages whose sitemap date is unchanged are not fetched again."""
    import jsonld_fetcher as jf
    base = c["base"].rstrip("/")
    ents = {}
    for u, lm in jf.read_sitemap(base + "/sitemap.xml", re.compile(r"/job/")):
        if re.search(r"/job/", urllib.parse.urlsplit(u).path) and re.search(r"/\d+/?$", u):
            ents.setdefault(u, lm or "")
    if not ents:
        raise ValueError("no job pages in the sitemap")
    order = sorted(ents, key=lambda u: ents[u], reverse=True)
    if len(order) > SITEMAP_CAP:
        c["_truncated"] = f"sitemap capped at {SITEMAP_CAP} of {len(order)} job pages"
        order = order[:SITEMAP_CAP]
    cname = (c.get("name") or "check") + "#radancy"
    cache = {} if c.get("name") in (None, "check") else jf._load_cache(cname)
    new_cache, failed = {}, 0

    def one(u):
        old = cache.get(u)
        if old and ents[u] and old.get("lm") == ents[u]:
            return u, old
        try:
            return u, {"lm": ents[u], "job": tb_page_job(fetch(u)[0], u)}
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return u, {"lm": ents[u], "job": None}
            return u, {"error": True, "old": old}
        except (Blocked, netsafe.UnsafeURL):
            raise
        except Exception:
            return u, {"error": True, "old": old}

    for u, ent in _pool(one, order):
        if ent.get("error"):
            failed += 1
            ent = ent.get("old")
        if not ent:
            continue
        new_cache[u] = ent
        j = ent.get("job")
        if j:
            sal = tuple(j["salary"]) if j.get("salary") else None
            yield J(c, j["title"], j["url"], j["locations"], j["workplace"], sal, j["desc"], j["posted"], j["dept"], j["id"])
    if failed:
        c["_truncated"] = ((c["_truncated"] + "; ") if c.get("_truncated") else "") + f"{failed} of {len(order)} job pages failed to load"
    if c.get("name") not in (None, "check"):
        for u, e in cache.items():
            new_cache.setdefault(u, e)
        jf._save_cache(cname, new_cache)


def radancy_count(c):
    """(US open jobs or a sitemap sample count, suggested name) with a couple of requests."""
    base = c["base"].rstrip("/")
    name = _label(urllib.parse.urlsplit(base).netloc)
    if not tb_can_search(base):
        import jsonld_fetcher as jf
        urls = [u for u, _ in jf.read_sitemap(base + "/sitemap.xml", re.compile(r"/job/")) if re.search(r"/job/.*/\d+/?$", u)]
        if not urls:
            raise ValueError("no job pages found")
        if not jf.postings_in(fetch(urls[0])[0]):
            raise ValueError("job pages carry no job data")
        return len(set(urls)), name   # (every country: the sitemap doesn't say which postings are in the US)
    first, filters = tb_page(base, 1, 1)
    facet = tb_us_facet(filters)
    if facet:
        first, _ = tb_page(base, 1, 1, facet)
    n = tb_total(first)
    if n is None:
        raise ValueError("no result list")
    return n, name


# ================================================================ Eightfold AI
_ef_mode = {}   # (host, domain) -> "pcsx" or "v2": which of the site's two public job APIs answered


def _ef_pcsx_url(c, start):
    q = {"domain": c["domain"], "query": "", "location": "United States", "start": start, "sort_by": "timestamp", "hl": "en"}
    return f"https://{c['host']}/api/pcsx/search?" + urllib.parse.urlencode(q)


def _ef_v2_url(c, start):
    q = {"domain": c["domain"], "start": start, "num": 10, "location": "United States", "sort_by": "timestamp"}
    return f"https://{c['host']}/api/apply/v2/jobs?" + urllib.parse.urlencode(q)


def _ef_flex(*vals):
    s = " ".join(str(v or "") for v in vals).lower()
    return "remote" if "remote" in s else "hybrid" if "hybrid" in s else "onsite" if "onsite" in s else ""


def ef_page(c, start):
    """([position dicts: id, name, locs, std, ts, dept, wp], total or None) for one page of the US list. Tries the
    current API (/api/pcsx/search); a site that refuses it (403/404) may still serve the older /api/apply/v2/jobs."""
    key = (c["host"], c["domain"])
    modes = [_ef_mode[key]] if key in _ef_mode else ["pcsx", "v2"]
    err = None
    for m in modes:
        try:
            if m == "pcsx":
                d = get_json(_ef_pcsx_url(c, start))
                data = d.get("data") or {}
                if d.get("status") not in (200, None) or "positions" not in data:
                    raise ValueError(f"Eightfold answered {d.get('status')}")
                pos = [{"id": p.get("id"), "name": p.get("name") or "", "locs": p.get("locations") or [],
                        "std": p.get("standardizedLocations") or [], "ts": p.get("postedTs") or p.get("creationTs"),
                        "dept": p.get("department") or "", "wp": _ef_flex(p.get("workLocationOption"), p.get("locationFlexibility"))}
                       for p in data["positions"] if p.get("id")]
                total = data.get("count")
            else:
                d = get_json(_ef_v2_url(c, start))
                if "positions" not in d:
                    raise ValueError("no position list")
                pos = [{"id": p.get("id"), "name": p.get("name") or p.get("posting_name") or "",
                        "locs": p.get("locations") or ([p["location"]] if p.get("location") else []), "std": [],
                        "ts": p.get("t_create") or p.get("t_update"), "dept": p.get("department") or "",
                        "wp": _ef_flex(p.get("work_location_option"), p.get("location_flexibility"))}
                       for p in d["positions"] if p.get("id")]
                total = d.get("count")
            _ef_mode[key] = m
            return pos, total
        except (urllib.error.HTTPError, ValueError, KeyError, TypeError) as e:
            err = e
            if key in _ef_mode or (isinstance(e, urllib.error.HTTPError) and e.code not in (403, 404)):
                raise
    raise err


def ef_detail(c, pid):
    if _ef_mode.get((c["host"], c["domain"])) == "v2":
        d = get_json(f"https://{c['host']}/api/apply/v2/jobs/{pid}?" + urllib.parse.urlencode({"domain": c["domain"]}))
        return strip_html(d.get("job_description") or "")
    q = urllib.parse.urlencode({"position_id": pid, "domain": c["domain"], "hl": "en"})
    d = get_json(f"https://{c['host']}/api/pcsx/position_details?{q}")
    return strip_html((d.get("data") or {}).get("jobDescription") or "")


def _ef_std_label(s):
    """Eightfold's standardized place: "City, ST, US" / "Taipei City,TW": the last part is a 2-letter country code."""
    parts = [x.strip() for x in (s or "").split(",") if x.strip()]
    if len(parts) > 1 and re.fullmatch(r"[A-Za-z]{2}", parts[-1]):
        return us_label(", ".join(parts[:-1]) + ", United States") if parts[-1].upper() == "US" else None
    return us_label(s)


def ef_location_labels(p):
    out = []
    locs, std = p.get("locs") or [], p.get("std") or []
    for i, orig in enumerate(locs):
        a = us_label(orig)
        b = _ef_std_label(std[i]) if i < len(std) else None
        if a and ("," in a or "remote" in a.lower()):
            out.append(a)
        elif b:
            out.append(b)
        elif a:
            out.append(a)
    return list(dict.fromkeys(out))


def f_eightfold(c):
    positions, seen, start, total = [], set(), 0, None
    while True:
        got, t = ef_page(c, start)
        total = t if t is not None else total
        new = [p for p in got if p["id"] not in seen]
        for p in new:
            seen.add(p["id"])
            positions.append(p)
        start += len(got)
        if not got or not new or (total is not None and start >= total):
            break
        if len(positions) >= EF_CAP:
            c["_truncated"] = f"Eightfold list stops at {EF_CAP} of {total}"
            break
    if total and len(positions) < total and not c.get("_truncated"):
        c["_truncated"] = f"empty page at {len(positions)} of {total}"

    def one(p):
        locs = ef_location_labels(p)
        if p["locs"] and not locs:
            return None   # (only places abroad)
        desc, partial = "", True
        if _wanted(c, p["name"]):
            try:
                desc = ef_detail(c, p["id"])
                partial = not desc
            except Exception:
                partial = True
        try:
            posted = datetime.datetime.fromtimestamp(int(p["ts"]), datetime.timezone.utc).date().isoformat() if p["ts"] else ""
        except (ValueError, OSError, OverflowError, TypeError):
            posted = ""
        j = J(c, p["name"], f"https://{c['host']}/careers/job/{p['id']}", locs, p["wp"], None, desc, posted, p["dept"], p["id"])
        if partial:
            j["_partial"] = True
        return j
    for j in _pool(one, positions):
        if j:
            yield j


def eightfold_count(c):
    pos, total = ef_page(c, 0)
    if not pos and not total:
        raise ValueError("no positions")
    return int(total if total is not None else len(pos)), _label(c["host"])


def ef_domain(page):
    m = re.search(r'(?:&#34;|&quot;|")domain(?:&#34;|&quot;|")\s*:\s*(?:&#34;|&quot;|")([a-z0-9][a-z0-9.-]{1,80}\.[a-z]{2,})(?:&#34;|&quot;|")', page or "", re.I)
    return m.group(1).lower() if m else None


# ================================================================ Avature
_AV_SKIP = {"portal", "static", "images", "css", "js", "scripts", "pub", "common", "api", "resources"}
_AV_LOC = r"(?:[a-z]{2}_[A-Z]{2}/)?"


def av_list_url(c, off=0):
    return f"{c['base'].rstrip('/')}/{c['portal']}/SearchJobs/?jobRecordsPerPage=100&jobOffset={off}"


def av_cards(h):
    """[{id, url, title, loc}] from one Avature SearchJobs page."""
    h = h or ""
    parts = re.split(r'<article\b[^>]*class="[^"]*article--result[^"]*"', h)
    chunks = parts[1:] if len(parts) > 1 else []
    if not chunks:   # (other template: one block per job link)
        starts = [m.start() for m in re.finditer(r'<a\b[^>]*href="[^"]*/JobDetail/', h)]
        chunks = [h[s:(starts[i + 1] if i + 1 < len(starts) else len(h))] for i, s in enumerate(starts)]
    out, seen = [], set()
    for ch in chunks:
        ch = ch.split("</article>")[0]
        m = None
        for m in re.finditer(r'<a\b([^>]*href="([^"]*/JobDetail/[^"]*/(\d+))[^"]*"[^>]*)>(.*?)</a>', ch, re.S):
            title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(4)))).strip()
            if title and not re.fullmatch(r"(apply|save|share|view|view job)", title, re.I):
                break
        else:
            m = None
        if not m:
            continue
        jid = m.group(3)
        if jid in seen:
            continue
        seen.add(jid)
        loc = ""
        lm = re.search(r'class="[^"]*(?:list-item-location|location)[^"]*"[^>]*>(.*?)</(?:span|div|li|p)>', ch, re.S | re.I)
        if lm:
            loc = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", lm.group(1)))).strip()
        if not loc:
            fm = re.search(r'field__label">\s*Locations?(?:\(s\))?:?\s*</div>\s*<div[^>]*field__value">(.*?)</div>', ch, re.S | re.I)
            if fm:
                loc = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fm.group(1)))).strip()
        out.append({"id": jid, "url": _html.unescape(m.group(2)), "title": title, "loc": loc})
    return out


def av_next(h):
    """Offset of the next page, or None."""
    m = re.search(r'paginationNextLink[^>]*href="[^"]*[?&;](?:amp;)?jobOffset=(\d+)', h or "") or \
        re.search(r'href="[^"]*[?&;](?:amp;)?jobOffset=(\d+)[^"]*"[^>]*class="[^"]*paginationNextLink', h or "")
    return int(m.group(1)) if m else None


def av_detail(h):
    """(location labels, description) from an Avature JobDetail page."""
    h = re.sub(r"<(script|style|svg)\b.*?</\1>", "", h or "", flags=re.S | re.I)
    segs = re.split(r'(?=<div[^>]*class="[^"]*article__content__view__field(?:\s|")[^"]*")', h)
    locs, longest = [], []
    for s in segs[1:]:
        s = s.split("</article>")[0]
        lab = re.search(r'field__label">(.*?)</div>', s, re.S)
        val = re.search(r'field__value">(.*)', s, re.S)
        label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", lab.group(1))).strip() if lab else ""
        raw = (val.group(1) if val else s)
        text = strip_html(re.sub(r"</?(?:div|article|section)\b[^>]*>", "\n", raw)).strip()
        if re.match(r"locations?", label, re.I):
            locs += [x.strip() for x in re.split(r"\s*[|;\n]\s*", text) if x.strip()]
        elif len(text) > 100:
            longest.append((label + "\n" if label else "") + text)
    return list(dict.fromkeys(locs)), "\n".join(dict.fromkeys(longest))


def f_avature(c):
    base = c["base"].rstrip("/")
    cards, seen, off, pages = [], set(), 0, 0
    while True:
        h = fetch(av_list_url(c, off))[0]
        pages += 1
        new = [x for x in av_cards(h) if x["id"] not in seen]
        for x in new:
            seen.add(x["id"])
            cards.append(x)
        nxt = av_next(h)
        if not new or nxt is None or nxt <= off:
            break
        if pages >= LIST_PAGES:
            c["_truncated"] = f"stopped after {pages} list pages ({len(cards)} jobs); the site has more"
            break
        off = nxt

    def one(x):
        locs, outside = us_locations(re.split(r"\s*[|;]\s*", x["loc"]) if x["loc"] else [])
        if outside:
            return None
        title, desc, partial = x["title"], "", True
        url = urllib.parse.urljoin(base + "/", x["url"])
        if _wanted(c, title) or not x["loc"]:
            try:
                dl, desc = av_detail(fetch(url)[0])
                partial = not desc
                if dl:
                    l2, out2 = us_locations(dl)
                    if out2 and not locs:
                        return None
                    locs = l2 or locs
            except Exception:
                partial = True
        j = J(c, title, url, locs, "", None, desc, "", "", x["id"])
        if partial:
            j["_partial"] = True
        return j
    for j in _pool(one, cards):
        if j:
            yield j


def avature_count(c):
    """(US jobs on the first few list pages, suggested name)."""
    n, off, seen = 0, 0, set()
    for _ in range(4):
        h = fetch(av_list_url(c, off))[0]
        cards = [x for x in av_cards(h) if x["id"] not in seen]
        if not cards:
            break
        for x in cards:
            seen.add(x["id"])
            if not x["loc"] or not us_locations(re.split(r"\s*[|;]\s*", x["loc"]))[1]:
                n += 1
        nxt = av_next(h)
        if nxt is None or n >= 30:
            break
        off = nxt
    if not seen:
        raise ValueError("no job list")
    return n, _label(urllib.parse.urlsplit(c["base"]).netloc)


# ================================================================ detection (used by company_add)
_AV_RX = re.compile(r"https?://([a-z0-9-]+\.avature\.net)/(" + _AV_LOC + r"[A-Za-z0-9_-]+)/(?:SearchJobs|JobDetail|Login|Register|JobAlerts|SaveJob|ForgotPassword)\b", re.I)
_AV_ROOT = re.compile(r"https?://([a-z0-9-]+\.avature\.net)/(" + _AV_LOC + r"[A-Za-z0-9_-]+)(?:[/?#]|$)", re.I)
_EF_HOST = re.compile(r"https?://([a-z0-9-]+\.eightfold\.ai)\b", re.I)
_EF_LINK = re.compile(r"https?://([a-z0-9.-]+)/careers\?[^\"'\s<>]*(?:start=\d+|sort_by=|domain=)", re.I)


def _norm_portal(p):
    return re.sub(r"^[a-z]{2}_[A-Z]{2}/", "", p)


def detect_avature(url, page):
    for text in (url, page or ""):
        m = _AV_RX.search(text)
        if not m and text is url:
            m = _AV_ROOT.search(text)
            if m and (m.group(2).lower() in _AV_SKIP or m.group(1).lower().startswith("recruiting360.")):
                m = None
        if m:
            cfg = {"ats": "avature", "base": "https://" + m.group(1).lower(), "portal": _norm_portal(m.group(2))}
            return cfg
    return None


def detect_eightfold(url, page):
    sp = urllib.parse.urlsplit(url)
    host = None
    if sp.netloc.lower().endswith(".eightfold.ai"):
        host = sp.netloc.lower()
    elif page and ("static.vscdn.net" in page or "pcsx-data" in page) and ef_domain(page):
        host = sp.netloc.lower()
    domain = (urllib.parse.parse_qs(sp.query).get("domain") or [None])[0] or ef_domain(page)
    if host and domain:
        return {"ats": "eightfold", "host": host, "domain": domain.lower()}
    cand = None
    if page:
        m = _EF_HOST.search(page) or _EF_LINK.search(page)
        cand = m.group(1).lower() if m else None
    if not cand or cand == sp.netloc.lower():
        return None
    try:   # a corporate page linking to the career site: read that page for its domain
        p2 = fetch(f"https://{cand}/careers")[0]
    except Exception:
        return None
    d2 = ef_domain(p2)
    return {"ats": "eightfold", "host": cand, "domain": d2} if d2 else None


def detect_radancy(url, page):
    if page and "tbcdn.talentbrew.com" in page:
        sp = urllib.parse.urlsplit(url)
        return {"ats": "radancy", "base": f"{sp.scheme}://{sp.netloc.lower()}"}
    return None


def detect(url, page=""):
    """A config for a careers link (and its page text) when it belongs to one of these systems, else None. The
    caller verifies it with verify()."""
    found = []
    for fn in (detect_avature, detect_eightfold, detect_radancy):
        try:
            cfg = fn(url, page)
        except Exception:
            cfg = None
        if cfg:
            found.append(cfg)
    if len(found) > 1:   # (e.g. a Radancy site that also links to an Eightfold talent hub: take the one that answers)
        for cfg in found:
            try:
                if verify(cfg)[0]:
                    return cfg
            except Exception:
                pass
    return found[0] if found else None


def verify(c):
    """(job count, suggested name) from the live feed, or raise."""
    return {"radancy": radancy_count, "eightfold": eightfold_count, "avature": avature_count}[c["ats"]](dict(c, name="check"))


FETCHERS = {"radancy": f_radancy, "eightfold": f_eightfold, "avature": f_avature}
