"""Polite HTTP for the directory builder.

Every request is paced per PROVIDER (see "polite by design" below: about one request a second and one or two
connections for a shared multi-tenant system, whatever its host names), asks for gzip, and rests when told to.
On top of that, for the builder's own light readers: an honest User-Agent naming the project, robots.txt checked first (longest matching rule wins, our own
group if a site names us, else "*"; Crawl-delay honoured), at most one request at a time per host with a gap between
them, 429/5xx retried with back-off (Retry-After honoured), 401/403 never worked around. Public http/https hosts only
(netsafe), except the sources a test points at a local server through an env override (see build.py)."""
import gzip, http.client, io, json, threading, time, urllib.error, urllib.parse, urllib.request

import netsafe
from ats_more import parse_robots, rules_allow   # (the same robots.txt reading the app's own readers use)

UA = "Mozilla/5.0 (compatible; SiftwellDirectory/1.0; +https://github.com/{repo})"
GAP = 0.35                  # default seconds between requests to one host
HOST_GAP = {                # hosts that ask for more (robots.txt Crawl-delay is applied on top of this)
    "api.lever.co": 1.0, "crt.sh": 5.0, "index.commoncrawl.org": 2.0, "hn.algolia.com": 0.5,
    "data.usajobs.gov": 1.0, "api.careeronestop.org": 1.0,
}
STATS = {"requests": 0, "errors": 0, "robots_blocked": 0, "bytes": 0}


class Blocked(Exception):
    """robots.txt forbids it (nothing was requested)."""


_lock = threading.Lock()
_host_locks = {}
_next_ok = {}
_robots = {}
_robots_lock = threading.Lock()


def user_agent():
    try:
        import appupdate
        return UA.format(repo=appupdate.REPO)
    except Exception:
        return UA.format(repo="siftwell")


def _host_lock(host):
    with _lock:
        return _host_locks.setdefault(host, threading.Lock())


def _gap(host):
    g = HOST_GAP.get(host, GAP)
    ent = _robots.get(host)
    if ent and ent[2]:
        g = max(g, min(ent[2], 10.0))
    return g


def _raw(url, data=None, headers=None, timeout=40, cap=60_000_000, local_ok=False, rng=None):
    hdr = {"User-Agent": user_agent(), "Accept-Encoding": "gzip", **(headers or {})}
    if rng:
        hdr["Range"] = f"bytes={rng[0]}-{rng[1]}"
        hdr.pop("Accept-Encoding", None)
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode()
        hdr.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdr)
    opener = urllib.request.urlopen if local_ok else netsafe.urlopen
    with opener(req, timeout=timeout) as r:
        raw = r.read(cap)
        if not rng and (r.headers.get("Content-Encoding") == "gzip"):
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(cap * 4)
        STATS["bytes"] += len(raw)
        return raw, r.headers


def robots_ok(url, local_ok=False):
    sp = urllib.parse.urlsplit(url)
    host = sp.netloc.lower()
    with _robots_lock:
        ent = _robots.get(host)
    if ent is None:
        rules, delay = [], 0.0
        try:
            txt = _raw(f"{sp.scheme}://{sp.netloc}/robots.txt", timeout=20, cap=500_000, local_ok=local_ok)[0].decode("utf-8", "replace")
            rules = parse_robots(txt, "siftwelldirectory") or parse_robots(txt, "siftwell")
            delay = _crawl_delay(txt)
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                rules = [(False, "/")]          # robots.txt unavailable: stay away this run
        except Exception:
            rules = [(False, "/")]
        ent = (time.time(), rules, delay)
        with _robots_lock:
            _robots[host] = ent
    return rules_allow(ent[1], (sp.path or "/") + (("?" + sp.query) if sp.query else ""))


def _crawl_delay(txt):
    cur, delay = False, 0.0
    for line in txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if k.lower() == "user-agent":
            cur = v == "*" or "siftwell" in v.lower()
        elif k.lower() == "crawl-delay" and cur:
            try:
                delay = max(delay, float(v))
            except ValueError:
                pass
    return delay


def get(url, data=None, headers=None, timeout=40, cap=60_000_000, tries=4, robots=True, local_ok=False, rng=None):
    """Bytes of url (POST JSON when data is given). Raises Blocked, urllib.error.HTTPError (4xx), or the last error."""
    if robots and not robots_ok(url, local_ok):
        STATS["robots_blocked"] += 1
        raise Blocked(f"robots.txt forbids {url[:80]}")
    host = urllib.parse.urlsplit(url).netloc.lower()
    last = None
    for i in range(tries):
        with _host_lock(host):
            wait = _next_ok.get(host, 0) - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                STATS["requests"] += 1
                return _raw(url, data, headers, timeout, cap, local_ok, rng)[0]
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    STATS["errors"] += 1
                    raise
                ra = e.headers.get("Retry-After") if e.headers else None
                back = float(ra) if ra and ra.isdigit() else 3 * 2 ** i
                _next_ok[host] = time.time() + min(back, 60)
            except (urllib.error.URLError, OSError) as e:
                last = e
                _next_ok[host] = time.time() + 2 * (i + 1)
            else:
                pass
            finally:
                _next_ok[host] = max(_next_ok.get(host, 0), time.time() + _gap(host))
    STATS["errors"] += 1
    raise last


def get_json(url, data=None, headers=None, **kw):
    return json.loads(get(url, data, {"Accept": "application/json", **(headers or {})}, **kw).decode("utf-8", "replace"))


def get_text(url, **kw):
    return get(url, **kw).decode("utf-8", "replace")


# ---------------------------------------------------------------- polite by design: pacing per provider
# Every request a builder process makes (the light readers above AND the app's own job-system readers, which have
# their own http helpers) goes through netsafe's openers; install() wraps those, so one gate sees them all:
#   - a PROVIDER is one company's servers, whatever the host name: recruiting.paylocity.com, every
#     <tenant>.wd5.myworkdayjobs.com, boards-api.greenhouse.io and job-boards.greenhouse.io ... An employer's own
#     careers site is its own provider (its registrable domain).
#   - per provider: at most `rate` requests a second (evenly spaced) and `conn` at a time. The defaults are what a
#     careful person with a browser would do; they are deliberately far below what the servers could take, because
#     thousands of copies of Siftwell may run this from home connections. Speed comes from asking many DIFFERENT
#     providers side by side, never from asking one faster.
#   - an employer's own site (not a job system) is asked for at most OWN_SITE_MAX pages in one build; a reader that
#     wants more gets OverBudget and the board counts as sampled.
#   - 429 / 503 (Retry-After honoured) and dropped connections make the provider rest: 15 s, 30 s, 60 s ... up to
#     three minutes; everything waiting for it waits too. (index_build/local.py's breaker is the last resort after.)
#   - gzip is asked for on every request that didn't ask itself, and unpacked here, so callers notice nothing.
#   - STATS counts what really crossed the wire ("wire") and what it would have been without the gzip added here
#     ("plain"): the data-use line in Settings comes from that.
# The app's own job fetch (Find new jobs) is a different process and is not touched.
PROVIDERS = {   # domain suffix: (provider, requests per second, connections)
    "paylocity.com": ("paylocity", 1.0, 1), "ultipro.com": ("ukg", 1.0, 2), "ukg.net": ("ukg", 1.0, 2), "ukg.com": ("ukg", 1.0, 2),
    "adp.com": ("adp", 1.0, 2), "workable.com": ("workable", 0.4, 1), "bamboohr.com": ("bamboohr", 2.0, 2),
    "icims.com": ("icims", 2.0, 2), "myworkdayjobs.com": ("workday", 3.0, 4), "greenhouse.io": ("greenhouse", 3.0, 3),
    "lever.co": ("lever", 1.0, 1), "ashbyhq.com": ("ashby", 3.0, 3), "rippling.com": ("rippling", 3.0, 2),
    "dayforcehcm.com": ("dayforce", 2.0, 2), "applytojob.com": ("jazzhr", 2.0, 2), "recruitee.com": ("recruitee", 2.0, 2),
    "breezy.hr": ("breezy", 2.0, 2), "taleo.net": ("taleo", 1.0, 2), "paycomonline.net": ("paycom", 1.0, 1),
    "saashr.com": ("saashr", 1.0, 1), "smartrecruiters.com": ("smartrecruiters", 1.0, 1), "applitrack.com": ("applitrack", 1.0, 2),
    "schoolspring.com": ("schoolspring", 1.0, 2), "jobvite.com": ("jobvite", 1.0, 2), "oraclecloud.com": ("oracle", 2.0, 2),
    "successfactors.com": ("successfactors", 1.0, 2), "eightfold.ai": ("eightfold", 1.0, 2), "avature.net": ("avature", 1.0, 2),
    "commoncrawl.org": ("commoncrawl", 0.33, 1), "crt.sh": ("crtsh", 0.2, 1), "githubusercontent.com": ("github", 2.0, 2),
}
DEFAULT_PACE = (1.0, 2)         # an employer's own site (or any provider not listed)
OWN_SITE_MAX = 40               # ... and the most pages one build asks of it: it is one employer, not a job system
SYSTEM_PROVIDER = {"ukg": "ukg", "jazzhr": "jazzhr"}   # job system id -> provider, where the names differ
REST_FIRST, REST_MAX = 15.0, 180.0
MAX_BODY = 80_000_000
_PACE = {}
_pace_lock = threading.Lock()
_tls = threading.local()
_installed = [False]
STATS.update(wire=0, plain=0, all_requests=0, rests=0)
BY = {}                         # provider -> [requests, bytes on the wire, times it asked for a rest]


def provider_of(host):
    """(provider name, requests per second, connections) for a host."""
    host = (host or "").lower().split(":")[0]
    labels = host.split(".")
    for i in range(len(labels) - 1):
        hit = PROVIDERS.get(".".join(labels[i:]))
        if hit:
            return hit
    return (".".join(labels[-2:]) or "unknown",) + DEFAULT_PACE


def system_rate(ats):
    """Requests per second the provider behind a job system allows itself (for time estimates)."""
    name = SYSTEM_PROVIDER.get(ats, ats)
    for prov, rate, conn in PROVIDERS.values():
        if prov == name:
            return rate
    return DEFAULT_PACE[0]


class OverBudget(urllib.error.URLError):
    """This build has asked one employer's own site for enough pages (nothing was requested)."""


class _Pace:
    def __init__(self, name, rate, conn, budget=None):
        self.name, self.gap = name, 1.0 / rate
        self.budget = budget
        self.sem = threading.BoundedSemaphore(conn)
        self.lock = threading.Lock()
        self.next_ok = 0.0
        self.until = 0.0
        self.strikes = 0

    def wait_turn(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next_ok, self.until)
            self.next_ok = t + self.gap
        if t > now:
            time.sleep(t - now)

    def rest(self, seconds=None):
        """The provider said "slow down" (or hung up): nobody asks it again for a while."""
        with self.lock:
            self.strikes += 1
            wait = min(REST_MAX, max(seconds or 0.0, REST_FIRST * 2 ** (self.strikes - 1)))
            self.until = max(self.until, time.time() + wait)
            STATS["rests"] += 1
            BY.setdefault(self.name, [0, 0, 0])[2] += 1
        return wait

    def fine(self):
        if self.strikes:
            with self.lock:
                self.strikes = 0


def pace_for(host):
    name, rate, conn = provider_of(host)
    with _pace_lock:
        p = _PACE.get(name)
        if p is None:
            listed = any(v[0] == name for v in PROVIDERS.values())
            p = _PACE[name] = _Pace(name, rate, conn, None if listed else OWN_SITE_MAX)
        return p


def resting():
    """Names of the providers being left alone right now."""
    now = time.time()
    with _pace_lock:
        return sorted(p.name for p in _PACE.values() if p.until > now)


class _Body(io.BytesIO):
    """A finished response: the bytes, plus the bits of http.client.HTTPResponse the readers use."""
    def __init__(self, data, resp, headers):
        super().__init__(data)
        self.headers, self.msg = headers, headers
        self.status = self.code = getattr(resp, "status", None) or getattr(resp, "code", 200)
        self.url = resp.geturl() if hasattr(resp, "geturl") else getattr(resp, "url", "")
        self.reason = getattr(resp, "reason", "")

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def info(self):
        return self.headers


def _retry_after(e):
    try:
        ra = e.headers.get("Retry-After") if e.headers else None
        return float(ra) if ra and str(ra).strip().isdigit() else None
    except Exception:
        return None


def _paced_open(raw_open, req, data=None, timeout=30, *a, **kw):
    if getattr(_tls, "inside", False):          # (a redirect being followed inside a request already let through)
        return raw_open(req, data, timeout, *a, **kw)
    if not isinstance(req, urllib.request.Request):
        req = urllib.request.Request(req)
    host = urllib.parse.urlsplit(req.full_url).netloc
    if host.startswith(("127.", "localhost", "[::1]")):
        return raw_open(req, data, timeout, *a, **kw)       # (tests)
    p = pace_for(host)
    if p.budget is not None:
        with p.lock:
            if p.budget <= 0:
                raise OverBudget(f"{p.name}: enough pages asked of this site for one build")
            p.budget -= 1
    added = False
    if not req.has_header("Accept-encoding") and not req.has_header("Range"):
        req.add_header("Accept-encoding", "gzip")
        added = True
    with p.sem:
        p.wait_turn()
        _tls.inside = True
        try:
            STATS["all_requests"] += 1
            resp = raw_open(req, data, timeout, *a, **kw)
            body = resp.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise ValueError("response too large")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                p.rest(_retry_after(e))
            else:
                p.fine()
            raise
        except (http.client.RemoteDisconnected, ConnectionError) as e:
            p.rest(30.0)
            raise
        except urllib.error.URLError as e:
            if isinstance(e.reason, (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError)):
                p.rest(30.0)
            raise
        finally:
            _tls.inside = False
    p.fine()
    headers = resp.headers
    wire = len(body)
    STATS["wire"] += wire
    b = BY.setdefault(p.name, [0, 0, 0])
    b[0] += 1
    b[1] += wire
    if added and (headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            body = gzip.GzipFile(fileobj=io.BytesIO(body)).read(MAX_BODY * 4)
        except (OSError, EOFError):
            pass
        else:
            del headers["Content-Encoding"]
            del headers["Content-Length"]
    STATS["plain"] += len(body) if added else wire
    try:
        resp.close()
    except Exception:
        pass
    return _Body(body, resp, headers)


def _wrap(opener):
    if getattr(opener, "_siftwell_paced", False):
        return opener
    raw = opener.open
    opener.open = lambda req, data=None, timeout=30, *a, **kw: _paced_open(raw, req, data, timeout, *a, **kw)
    opener._siftwell_paced = True
    return opener


def install():
    """Put the gate in front of every request this process makes through netsafe (idempotent). Called by the two
    builder entry points (build.main, local.main) and by nothing else."""
    if _installed[0]:
        return
    _installed[0] = True
    make = netsafe.build_opener
    netsafe.build_opener = lambda *a, **kw: _wrap(make(*a, **kw))
    _wrap(netsafe._OPENER)
