"""Polite HTTP for the directory builder.

Every request: an honest User-Agent naming the project, robots.txt checked first (longest matching rule wins, our own
group if a site names us, else "*"; Crawl-delay honoured), at most one request at a time per host with a gap between
them, 429/5xx retried with back-off (Retry-After honoured), 401/403 never worked around. Public http/https hosts only
(netsafe), except the sources a test points at a local server through an env override (see build.py)."""
import gzip, io, json, threading, time, urllib.error, urllib.parse, urllib.request

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
