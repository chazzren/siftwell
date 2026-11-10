"""Read custom careers sites that publish schema.org JobPosting data (JSON-LD or microdata), the markup Google Jobs reads.

Company config: {"ats": "jsonld", "list_url": <careers page>, "sitemap": <sitemap url>, "path_re": <regex on sitemap URL paths>,
                 "link_prefix": <path prefix of job links found on list_url>}  (any of the three sources may be present)
detect_config(url, page) finds that config for a careers link no known job system matches; f_jsonld(c) is the fetcher."""
import gzip, io, html as _html, json, os, re, time, hashlib, threading, urllib.request, urllib.error, urllib.parse
import netsafe
import concurrent.futures as cf
from html.parser import HTMLParser
from urllib import robotparser

UA = "Mozilla/5.0 (Siftwell personal job search)"
MAX_PAGES = 300        # job pages fetched per company per run
WORKERS = 4
DELAY = 0.25           # seconds each worker waits after a request
MAX_BYTES = 3_000_000
TIMEOUT = 25

# ---------------------------------------------------------------- parsing
_LD = re.compile(r"<script\b[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script\s*>", re.I | re.S)

def _types(o):
    t = o.get("@type")
    return [t] if isinstance(t, str) else [x for x in (t or []) if isinstance(x, str)]

def _is_job(o):
    return isinstance(o, dict) and any(t.rsplit("/", 1)[-1] == "JobPosting" for t in _types(o))

def _walk(o, out, depth=0):
    if depth > 8:
        return
    if isinstance(o, list):
        for x in o:
            _walk(x, out, depth + 1)
    elif isinstance(o, dict):
        if _is_job(o):
            out.append(o)
            return
        for k in ("@graph", "itemListElement", "item", "mainEntity", "mainEntityOfPage", "hasPart", "jobPostings"):
            if k in o:
                _walk(o[k], out, depth + 1)

def jsonld_postings(page):
    out = []
    for m in _LD.finditer(page or ""):
        raw = _html.unescape(m.group(1).strip()) if "&quot;" in m.group(1) else m.group(1).strip()
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw).strip()
        try:
            data = json.loads(raw, strict=False)
        except Exception:
            continue
        _walk(data, out)
    return out

_VOID = {"meta", "link", "img", "br", "hr", "input", "source", "area", "base", "col", "embed", "param", "track", "wbr"}

class _Micro(HTMLParser):
    """Collects microdata items whose itemtype is a JobPosting (nested itemscopes become nested dicts)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []   # frames: {tag, prop, obj, text}
        self.found = []

    def _value(self, tag, a):
        if tag == "meta":
            return a.get("content", "")
        if tag in ("a", "link", "area"):
            return a.get("href", "")
        if tag in ("img", "source"):
            return a.get("src", "")
        if tag in ("time", "data") and ("datetime" in a or "value" in a):
            return a.get("datetime") or a.get("value")
        return None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        prop, scope = a.get("itemprop"), "itemscope" in a
        obj = None
        if scope:
            obj = {"@type": (a.get("itemtype") or "").rsplit("/", 1)[-1]}
        parent = next((f["obj"] for f in reversed(self.stack) if f["obj"] is not None), None)
        if tag in _VOID:
            if prop and parent is not None:
                v = self._value(tag, a)
                if v is not None:
                    self._put(parent, prop, v)
            return
        val = self._value(tag, a) if prop else None
        self.stack.append({"tag": tag, "prop": prop, "obj": obj, "val": val, "text": []})
        if scope and obj["@type"] == "JobPosting" and not prop:
            self.found.append(obj)

    @staticmethod
    def _put(obj, prop, v):
        if prop in obj:
            if not isinstance(obj[prop], list):
                obj[prop] = [obj[prop]]
            obj[prop].append(v)
        else:
            obj[prop] = v

    def handle_data(self, data):
        for f in self.stack:
            if f["prop"] or f["obj"] is not None:
                f["text"].append(data)

    def handle_endtag(self, tag):
        idx = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]["tag"] == tag), None)
        if idx is None:
            return
        while len(self.stack) > idx:
            f = self.stack.pop()
            if f["prop"]:
                parent = next((g["obj"] for g in reversed(self.stack) if g["obj"] is not None), None)
                if parent is not None:
                    if f["obj"] is not None:
                        self._put(parent, f["prop"], f["obj"])
                    else:
                        v = f["val"] if f["val"] is not None else re.sub(r"\s+", " ", "".join(f["text"])).strip()
                        if f["prop"] == "description" and f["val"] is None:
                            v = "".join(f["text"]).strip()
                        self._put(parent, f["prop"], v)

def microdata_postings(page):
    if "itemscope" not in (page or "") or "JobPosting" not in page:
        return []
    p = _Micro()
    try:
        p.feed(page)
        p.close()
    except Exception:
        pass
    return [o for o in p.found if o.get("title") or o.get("name")]

def postings_in(page):
    return jsonld_postings(page) or microdata_postings(page)

# ---------------------------------------------------------------- field normalisation
_US = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america", "america"}
_STATE_FULL = {}

def _s(v):
    """Text of a schema.org value (string, {"name": ...}, list)."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return _s(v.get("name") or v.get("@id") or v.get("value") or "")
    if isinstance(v, list):
        return ", ".join(x for x in (_s(i) for i in v) if x)
    return "" if v is None else str(v)

def _country(a):
    return _s(a.get("addressCountry")) if isinstance(a, dict) else ""

def _is_us_country(c):
    c = (c or "").strip().lower().rstrip(".")
    return not c or c in _US or c in {x.rstrip(".") for x in _US}

def _place(p):
    """(label, country) for one jobLocation item."""
    if isinstance(p, str):
        return p.strip(), ""
    if not isinstance(p, dict):
        return "", ""
    a = p.get("address", p)
    if isinstance(a, str):
        return a.strip(), ""
    if not isinstance(a, dict):
        return _s(p.get("name")), ""
    city, reg = _s(a.get("addressLocality")), _s(a.get("addressRegion"))
    country = _country(a)
    if len(reg) > 2 and _is_us_country(country):
        reg = _STATE_ABBR.get(reg.lower(), reg)
    label = ", ".join(x for x in (city, reg) if x)
    if label and not _is_us_country(country):
        label += ", " + country
    return label or _s(p.get("name")), country

_STATE_ABBR = {n.lower(): a for n, a in (
    ("Alabama", "AL"), ("Alaska", "AK"), ("Arizona", "AZ"), ("Arkansas", "AR"), ("California", "CA"), ("Colorado", "CO"),
    ("Connecticut", "CT"), ("Delaware", "DE"), ("District of Columbia", "DC"), ("Florida", "FL"), ("Georgia", "GA"),
    ("Hawaii", "HI"), ("Idaho", "ID"), ("Illinois", "IL"), ("Indiana", "IN"), ("Iowa", "IA"), ("Kansas", "KS"),
    ("Kentucky", "KY"), ("Louisiana", "LA"), ("Maine", "ME"), ("Maryland", "MD"), ("Massachusetts", "MA"),
    ("Michigan", "MI"), ("Minnesota", "MN"), ("Mississippi", "MS"), ("Missouri", "MO"), ("Montana", "MT"),
    ("Nebraska", "NE"), ("Nevada", "NV"), ("New Hampshire", "NH"), ("New Jersey", "NJ"), ("New Mexico", "NM"),
    ("New York", "NY"), ("North Carolina", "NC"), ("North Dakota", "ND"), ("Ohio", "OH"), ("Oklahoma", "OK"),
    ("Oregon", "OR"), ("Pennsylvania", "PA"), ("Rhode Island", "RI"), ("South Carolina", "SC"), ("South Dakota", "SD"),
    ("Tennessee", "TN"), ("Texas", "TX"), ("Utah", "UT"), ("Vermont", "VT"), ("Virginia", "VA"), ("Washington", "WA"),
    ("West Virginia", "WV"), ("Wisconsin", "WI"), ("Wyoming", "WY"))}

_UNIT = {"HOUR": 2080, "DAY": 260, "WEEK": 52, "MONTH": 12, "YEAR": 1, "ANNUM": 1, "ANNUAL": 1}

def _num(v):
    try:
        return float(re.sub(r"[^0-9.]", "", str(v))) if v not in (None, "") else None
    except ValueError:
        return None

def salary_of(bs):
    """baseSalary -> (annual min, annual max, text) or None. Handles min/max, single value, hourly/weekly/monthly units."""
    if isinstance(bs, list):
        bs = next((b for b in bs if b), None)
    if not isinstance(bs, dict):
        return None
    cur = _s(bs.get("currency")) or "USD"
    val = bs.get("value", bs)
    if not isinstance(val, dict):
        val = {"value": val}
    lo, hi, one = _num(val.get("minValue")), _num(val.get("maxValue")), _num(val.get("value"))
    unit = (_s(val.get("unitText") or bs.get("unitText")) or "YEAR").upper().rstrip("S")
    mult = _UNIT.get(unit)
    if mult is None:
        mult = 1 if (lo or one or 0) >= 1000 else (2080 if (hi or one or 0) < 400 else 1)
    lo = lo if lo is not None else one
    hi = hi if hi is not None else (one if one is not None else lo)
    lo = lo if lo is not None else hi
    if lo is None or cur.upper() not in ("USD", "$", "US$"):
        return None
    a, b = round(lo * mult), round(hi * mult)
    if a > b:
        a, b = b, a
    if not (20000 <= a and b <= 2_000_000):
        return None
    unit_word = {"HOUR": "/hr", "DAY": "/day", "WEEK": "/wk", "MONTH": "/mo"}.get(unit, "")
    raw = (f"${lo:,.2f}".rstrip("0").rstrip(".") if unit_word else f"${lo:,.0f}")
    if hi != lo:
        raw += " - " + (f"${hi:,.2f}".rstrip("0").rstrip(".") if unit_word else f"${hi:,.0f}")
    return a, b, (raw + unit_word)[:80]

def _tag_text(s):
    if not s:
        return ""
    s = _html.unescape(_html.unescape(str(s)))
    s = re.sub(r"<(br|/p|/div|/li|/h\d|/ul|/ol|/tr)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r" ?\n ?", "\n", s)).strip()

def normalize(o, page_url=""):
    """One JobPosting dict -> plain fields, or None if it's outside the US / has no title."""
    title = _s(o.get("title") or o.get("name"))
    if not title:
        return None
    locs, countries = [], []
    jl = o.get("jobLocation")
    for p in (jl if isinstance(jl, list) else [jl] if jl else []):
        lab, ctry = _place(p)
        if lab:
            locs.append(lab)
        if ctry:
            countries.append(ctry)
    remote = _s(o.get("jobLocationType")).upper().endswith("TELECOMMUTE")
    alr = o.get("applicantLocationRequirements")
    req = [x for x in (alr if isinstance(alr, list) else [alr] if alr else []) if x]
    req_names = [_s(x) for x in req]
    if remote:
        if req and not any(_is_us_country(n) or n.lower() in _STATE_ABBR or n.upper() in _STATE_ABBR.values() for n in req_names):
            return None  # remote, but only for other countries
        if not locs:
            locs = ["Remote, US"]
    elif locs and countries and len(countries) >= len(locs) and not any(_is_us_country(c) for c in countries):
        return None
    elif not locs and not countries and req_names and not any(_is_us_country(n) for n in req_names):
        return None
    org = o.get("hiringOrganization")
    et = o.get("employmentType")
    ident = o.get("identifier")
    ident = _s(ident.get("value") if isinstance(ident, dict) else ident)
    url = _s(o.get("url")) or page_url
    if page_url and url and not re.match(r"https?://", url):
        url = urllib.parse.urljoin(page_url, url)
    return {"title": title, "url": url or page_url, "locations": locs, "workplace": "remote" if remote else "",
            "salary": salary_of(o.get("baseSalary")), "posted": (_s(o.get("datePosted")) or "")[:10],
            "desc": _tag_text(o.get("description")),
            "employment_type": ", ".join(_s(x) for x in (et if isinstance(et, list) else [et]) if x) if et else "",
            "org": _s(org.get("name") if isinstance(org, dict) else org),
            "ident": ident, "dept": _s(o.get("occupationalCategory") or o.get("industry"))[:80]}

# ---------------------------------------------------------------- http
class _Gone(Exception):
    pass

def _open(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml,*/*;q=0.8",
                                               "Accept-Encoding": "gzip", **(headers or {})})
    for i in range(3):
        try:
            with netsafe.urlopen(req, timeout=TIMEOUT) as r:  # (public http/https only, redirects re-checked)
                raw = r.read(MAX_BYTES)
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_BYTES * 4)
                ctype = r.headers.get_content_charset() or "utf-8"
                return raw.decode(ctype, "replace"), r.headers, r.geturl()
        except urllib.error.HTTPError as e:
            if e.code == 304:
                raise
            if e.code in (429, 500, 502, 503) and i < 2:
                ra = e.headers.get("Retry-After") if e.headers else None
                time.sleep(min(20, float(ra) if ra and ra.isdigit() else 3 * 2 ** i))
                continue
            raise
        except urllib.error.URLError:
            if i < 2:
                time.sleep(1.5 * (i + 1))
                continue
            raise

def get_text(url, headers=None):
    return _open(url, headers)[0]

_robots = {}
_robots_lock = threading.Lock()

def robots(url):
    """(RobotFileParser or None, [sitemap urls]) for the url's site; cached per run."""
    p = urllib.parse.urlsplit(url)
    root = f"{p.scheme}://{p.netloc}"
    with _robots_lock:
        if root in _robots:
            return _robots[root]
    rp, sitemaps = None, []
    try:
        txt = get_text(root + "/robots.txt")
        rp = robotparser.RobotFileParser()
        rp.parse(txt.splitlines())
        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt)
    except Exception:
        pass
    with _robots_lock:
        _robots[root] = (rp, sitemaps)
    return rp, sitemaps

def allowed(url):
    rp, _ = robots(url)
    try:
        return rp is None or rp.can_fetch(UA, url) and rp.can_fetch("*", url)
    except Exception:
        return True

# ---------------------------------------------------------------- sitemaps and links
_LOC = re.compile(r"<url>\s*<loc>\s*([^<\s]+)\s*</loc>(?:.*?<lastmod>\s*([^<\s]+)\s*</lastmod>)?(?:.*?)</url>|<sitemap>\s*<loc>\s*([^<\s]+)\s*</loc>", re.S | re.I)

def read_sitemap(url, want_re=None, depth=0, budget=None):
    """[(url, lastmod)] from a sitemap or sitemap index (child sitemaps whose URL matches want_re are tried first)."""
    budget = budget if budget is not None else [8]
    out = []
    if budget[0] <= 0 or not allowed(url):
        return out
    budget[0] -= 1
    try:
        txt = get_text(url)
    except Exception:
        return out
    kids, items = [], []
    for m in _LOC.finditer(txt):
        if m.group(3):
            kids.append(_html.unescape(m.group(3)))
        elif m.group(1):
            items.append((_html.unescape(m.group(1)), (m.group(2) or "")))
    if kids and depth < 2:
        # only child sitemaps that look job-related (an index can hold millions of product pages)
        kids = [k for k in kids if re.search(r"job|career|position|opening|vacanc|posting|page", k, re.I)
                and not re.search(r"product|pdp|image|video|blog|news", k, re.I)]
        for k in kids:
            if budget[0] <= 0:
                break
            out += read_sitemap(k, want_re, depth + 1, budget)
            if want_re and any(want_re.search(urllib.parse.urlsplit(u).path) for u, _ in out) and re.search(r"job|career|position|opening|vacanc", k, re.I):
                break
    return out + items

_JOBISH = re.compile(r"/(jobs?|careers?|positions?|openings?|vacanc\w*|opportunit\w*|requisitions?|postings?|employment|work-with-us|join)(/|-|$)", re.I)

def job_links(page, base):
    """Same-site links that look like job detail pages: {path prefix: [urls]}."""
    host = urllib.parse.urlsplit(base).netloc.lower().removeprefix("www.")
    groups = {}
    for m in re.finditer(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)", page or "", re.I):
        u = urllib.parse.urljoin(base, _html.unescape(m.group(1)).strip())
        p = urllib.parse.urlsplit(u)
        if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != host:
            continue
        path = p.path
        if not _JOBISH.search(path) or re.search(r"\.(pdf|jpe?g|png|css|js|zip)$", path, re.I):
            continue
        segs = [s for s in path.split("/") if s]
        if len(segs) < 2:
            continue
        prefix = "/" + "/".join(segs[:-1]) + "/"
        u = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))
        groups.setdefault(prefix, [])
        if u not in groups[prefix]:
            groups[prefix].append(u)
    return groups

# ---------------------------------------------------------------- detection
def detect_config(url, page, final_url=None):
    """Look for JobPosting data for a careers link that matches no known job system.
    Returns (config dict, sample listing count) or None. Costs about a dozen small requests."""
    base = final_url or url
    cfg = {"ats": "jsonld"}
    sp = urllib.parse.urlsplit(base)
    root = f"{sp.scheme}://{sp.netloc}"
    on_page = [n for n in (normalize(o, base) for o in postings_in(page)) if n]
    found = bool(on_page)
    if found:
        cfg["list_url"] = base
    # linked job pages
    groups = job_links(page, base)
    best = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for prefix, urls in best[:3]:
        if len(urls) < 2 and found:
            continue
        ok = 0
        for u in urls[:2]:
            try:
                if allowed(u) and any(normalize(o, u) for o in postings_in(get_text(u))):
                    ok += 1
            except Exception:
                pass
            time.sleep(DELAY)
        if ok:
            cfg["list_url"] = base
            cfg["link_prefix"] = prefix
            found = True
            break
    # sitemap entries under the careers path
    _, smaps = robots(base)
    path = sp.path.rstrip("/")
    path_re = re.escape(path) + r"/." if path else r"/(jobs?|careers?|positions?|openings?|vacanc\w*)/."
    want = re.compile(path_re, re.I)
    for sm in (smaps[:3] or [root + "/sitemap.xml"]):
        ents = [u for u, _ in read_sitemap(sm, want)]
        hits = [u for u in ents if want.search(urllib.parse.urlsplit(u).path) and u.rstrip("/") != base.rstrip("/")]
        if not hits and path:
            want2 = re.compile(r"/(jobs?|careers?|positions?|openings?|vacanc\w*)/.", re.I)
            hits = [u for u in ents if want2.search(urllib.parse.urlsplit(u).path)]
            if hits:
                path_re = want2.pattern
        if not hits:
            continue
        ok = 0
        for u in hits[:3]:
            try:
                if allowed(u) and any(normalize(o, u) for o in postings_in(get_text(u))):
                    ok += 1
            except Exception:
                pass
            time.sleep(DELAY)
        if ok:
            cfg["sitemap"] = sm
            cfg["path_re"] = path_re
            found = True
            break
    if not found:
        return None
    if cfg.get("sitemap") and cfg.get("link_prefix"):
        cfg.pop("link_prefix")  # the sitemap is the more complete source (and a prefix may be a one-off slug)
    if "list_url" not in cfg:
        cfg["list_url"] = base
    return cfg

# ---------------------------------------------------------------- fetcher
def _cache_path(name):
    import paths
    return os.path.join(paths.DATA, "jsonld_cache", hashlib.sha1(name.encode()).hexdigest()[:16] + ".json")

def _load_cache(name):
    try:
        with open(_cache_path(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(name, cache):
    try:
        p = _cache_path(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(p + ".tmp", p)
    except Exception:
        pass

def collect_urls(c):
    """{url: lastmod} of job pages from the sitemap and listing page, plus postings read straight off the listing page."""
    urls, inline = {}, []
    want = re.compile(c["path_re"], re.I) if c.get("path_re") else None
    if c.get("sitemap"):
        for u, lm in read_sitemap(c["sitemap"], want):
            if (not want or want.search(urllib.parse.urlsplit(u).path)) and u.rstrip("/") != (c.get("list_url") or "").rstrip("/"):
                urls.setdefault(u, lm)
    lu = c.get("list_url")
    if lu and allowed(lu):
        try:
            page = get_text(lu)
        except Exception:
            page = ""
            if not urls:
                raise
        for o in postings_in(page):
            n = normalize(o, lu)
            if n:
                inline.append(n)
                if n["url"] and n["url"].rstrip("/") != lu.rstrip("/") and not n["desc"]:
                    urls.setdefault(n["url"], "")
        pre = c.get("link_prefix")
        if pre:
            for u in job_links(page, lu).get(pre, []):
                urls.setdefault(u, "")
    return urls, inline

def fetch_postings(c, cap=None, sample=False):
    """Yield normalized postings (dicts) for one company config; sets c['_truncated'] when the page cap was hit."""
    cap = cap or MAX_PAGES
    name = c.get("name", "check")
    urls, inline = collect_urls(c)
    cache = {} if sample else _load_cache(name)
    new_cache = {}
    c["_url_count"] = len(urls)
    order = sorted(urls, key=lambda u: urls[u], reverse=True)  # newest lastmod first when capped
    if len(order) > cap:
        c["_truncated"] = f"capped at {cap} of {len(order)} job pages"
        order = order[:cap]

    def one(u):
        old = cache.get(u)
        lm = urls.get(u) or ""
        if old and lm and old.get("lm") == lm:
            return u, old
        hdr = {}
        if old and old.get("etag"):
            hdr["If-None-Match"] = old["etag"]
        if old and old.get("last_modified"):
            hdr["If-Modified-Since"] = old["last_modified"]
        try:
            if not allowed(u):
                return u, None
            txt, h, final = _open(u, hdr)
        except urllib.error.HTTPError as e:
            time.sleep(DELAY)
            if e.code == 304 and old:
                return u, old
            if e.code in (404, 410):
                return u, {"posts": [], "lm": lm}
            return u, {"error": True, "old": old}
        except Exception:
            return u, {"error": True, "old": old}
        time.sleep(DELAY)
        posts = [n for n in (normalize(o, u) for o in postings_in(txt)) if n]
        if len(posts) == 1:
            posts[0]["url"] = u
        return u, {"posts": posts, "lm": lm, "etag": h.get("ETag", ""), "last_modified": h.get("Last-Modified", "")}

    failed = 0
    seen = set()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for u, ent in ex.map(one, order):
            if ent and ent.get("error"):
                failed += 1
                ent = ent.get("old")
            if not ent:
                continue
            new_cache[u] = ent
            for p in ent.get("posts", []):
                key = p["ident"] or p["url"]
                if key not in seen:
                    seen.add(key)
                    yield p
    for p in inline:  # listing-page entries with no page of their own
        key = p["ident"] or p["url"]
        if key not in seen:
            seen.add(key)
            yield p
    if failed:
        note = f"{failed} of {len(order)} job pages failed to load"
        c["_truncated"] = (c["_truncated"] + "; " if c.get("_truncated") else "") + note
    if not sample:
        if c.get("_truncated"):
            for u, e in cache.items():  # keep what we didn't reach so the next run can still skip unchanged pages
                new_cache.setdefault(u, e)
        _save_cache(name, new_cache)

def f_jsonld(c):
    from jobfinder import J
    for p in fetch_postings(c):
        yield J(c, p["title"], p["url"], p["locations"], p["workplace"], p["salary"], p["desc"], p["posted"],
                p["dept"], p["ident"] or p["url"]) | {"employment_type": p["employment_type"], "org": p["org"]}

FETCHERS = {"jsonld": f_jsonld}
