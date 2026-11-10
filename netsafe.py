"""Outbound-request safety: every request Siftwell makes to an employer's site (or a link Claude or a share file
supplied) goes through here, so a crafted link or company config can't make Siftwell read local files or reach
machines on the home network (routers, NAS boxes, this computer's own services).

Rules (checked before the request, again for every redirect, and once more on the address actually connected to):
  - only http:// and https:// (never file://, ftp://, data: ...), no user:password@ in the link
  - only ports 80 and 443
  - the host must resolve to public internet addresses only: loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7),
    link-local (169.254/16, fe80::/10), carrier-grade NAT, multicast, reserved and unspecified addresses are refused,
    including IPv4 addresses wrapped in IPv6 (::ffff:127.0.0.1, 6to4, Teredo, NAT64)

Also here: clean_link() for links shown on pages (http/https only) and clean_config() / check_config() which
validate a company's job-board config per job system (used when importing a share file and before every fetch)."""
import http.client
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_PORTS = {80, 443}


class UnsafeURL(ValueError):
    """The link isn't allowed (bad scheme, port or address). Not worth retrying."""


# ---------------------------------------------------------------- addresses
def _ip_ok(ip):
    """True when this address is a public internet address."""
    try:
        a = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return False
    if a.version == 6:
        inner = a.ipv4_mapped or a.sixtofour or (a.teredo[1] if a.teredo else None)
        if inner is None and a in ipaddress.ip_network("64:ff9b::/96"):  # NAT64
            inner = ipaddress.ip_address(int(a) & 0xFFFFFFFF)
        if inner is not None and not _ip_ok(inner):
            return False
    return a.is_global and not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved
                                or a.is_unspecified)


def _resolve(host, port):
    """Every address this host resolves to; raises UnsafeURL if any of them isn't public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise urllib.error.URLError(e)
    if not infos:
        raise urllib.error.URLError(f"{host} has no address")
    bad = [i[4][0] for i in infos if not _ip_ok(i[4][0])]
    if bad:
        raise UnsafeURL(f"{host} points to a local or private address ({bad[0]}), which Siftwell won't contact")
    return infos


def _split(url):
    """(scheme, host, port) after the static checks (no DNS). Raises UnsafeURL."""
    if not isinstance(url, str) or not url or len(url) > 4000 or re.search(r"[\x00-\x20\x7f]", url):
        raise UnsafeURL("That link isn't a valid web address.")
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError:
        raise UnsafeURL("That link isn't a valid web address.")
    scheme = p.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeURL("Only http:// and https:// links are allowed.")
    if p.username is not None or p.password is not None or "@" in p.netloc:
        raise UnsafeURL("Links with a user name or password in them aren't allowed.")
    host = (p.hostname or "").rstrip(".")
    if not host:
        raise UnsafeURL("That link has no web site in it.")
    port = port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeURL(f"Siftwell only contacts web sites on the standard ports (not port {port}).")
    try:
        lit = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        lit = None
    if lit is not None:
        if not _ip_ok(lit):
            raise UnsafeURL("That link points to a local or private address, which Siftwell won't contact.")
    elif re.fullmatch(r"[0-9.]+|0x[0-9a-fx.]+", host.lower()):
        raise UnsafeURL("That link isn't a valid web address.")  # (numeric shorthands like 2130706433 = 127.0.0.1)
    else:
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
            raise UnsafeURL("That link points to this computer or the local network, which Siftwell won't contact.")
    return scheme, host, port


def check_url(url, resolve=True):
    """Raise UnsafeURL unless url is an http(s) link to a public host on port 80/443. resolve=False skips DNS
    (for validating stored configs without network access). Returns the url."""
    _, host, port = _split(url)
    if resolve:
        _resolve(host, port)
    return url


def is_public_url(url, resolve=False):
    try:
        check_url(url, resolve)
        return True
    except (UnsafeURL, urllib.error.URLError):
        return False


# ---------------------------------------------------------------- connections that check the address they connect to
def _safe_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *a, **k):
    host, port = address
    if port not in ALLOWED_PORTS:
        raise UnsafeURL(f"Siftwell only contacts web sites on the standard ports (not port {port}).")
    err = None
    for family, socktype, proto, _, sa in _resolve(host, port):
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            if not _ip_ok(sock.getpeername()[0]):  # (belt and braces: the address actually reached)
                raise UnsafeURL("Connected to a local or private address; refused.")
            return sock
        except UnsafeURL:
            if sock is not None:
                sock.close()
            raise
        except OSError as e:
            err = e
            if sock is not None:
                sock.close()
    raise err or OSError(f"couldn't connect to {host}")


def _proxied(req):
    return bool(getattr(req, "_tunnel_host", None)) or req.has_proxy()


class _SafeHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = _safe_create_connection


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = _safe_create_connection


def _precheck(req):
    """Static checks; through a configured proxy the proxy itself is contacted, so the target is resolved and
    checked here instead of at connect time. Returns whether a proxy is used."""
    proxied = _proxied(req)
    check_url(req.full_url, resolve=proxied)
    return proxied


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(http.client.HTTPConnection if _precheck(req) else _SafeHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(http.client.HTTPSConnection if _precheck(req) else _SafeHTTPSConnection, req,
                            context=self._context)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 8

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        check_url(newurl, resolve=False)  # (raises: the redirect isn't followed; the address is checked on connect)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _SafeOpener(urllib.request.OpenerDirector):
    def open(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        check_url(fullurl.full_url if isinstance(fullurl, urllib.request.Request) else fullurl, resolve=False)
        return super().open(fullurl, data, timeout)


def build_opener(*handlers):
    """Like urllib.request.build_opener, but only http/https (no file:, ftp:, data:), with every request, redirect
    and connection checked. Extra handlers (e.g. an HTTPCookieProcessor) are added."""
    op = _SafeOpener()
    for h in (urllib.request.ProxyHandler(), urllib.request.UnknownHandler(), _SafeHTTPHandler(), _SafeHTTPSHandler(),
              urllib.request.HTTPDefaultErrorHandler(), _SafeRedirectHandler(), urllib.request.HTTPErrorProcessor(), *handlers):
        op.add_handler(h)
    return op


_OPENER = build_opener()


def urlopen(req, data=None, timeout=30, opener=None):
    """urllib.request.urlopen with the checks above. req: a URL or a urllib.request.Request."""
    if not isinstance(req, urllib.request.Request):
        req = urllib.request.Request(req)
    return (opener or _OPENER).open(req, data, timeout)


# ---------------------------------------------------------------- links shown on pages
def clean_link(url):
    """url if it's an http(s) link, else "" (javascript:, data:, file: ... are dropped). For links rendered on pages."""
    if not isinstance(url, str):
        return ""
    u = url.strip()
    if len(u) > 4000 or not re.match(r"https?://[^\s/?#]", u, re.I) or re.search(r"[\x00-\x1f\x7f\s]", u):
        return ""
    return u


def clean_text(s, limit=200):
    """One line of plain text: control characters and line breaks become spaces, trimmed to limit."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", " ", str(s or "")).strip()[:limit].strip()


# ---------------------------------------------------------------- company job-board configs
SLUG = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ALNUM = r"[A-Za-z0-9]{1,64}"


def _https_origin(v):
    """https://host (optionally with a path for some systems): a public-looking web address."""
    return isinstance(v, str) and is_public_url(v) and v.lower().startswith(("https://", "http://"))


def _origin_only(v):
    if not _https_origin(v):
        return False
    p = urllib.parse.urlsplit(v)
    return p.path in ("", "/") and not p.query and not p.fragment


def _rx(pattern):
    r = re.compile(pattern)
    return lambda v: isinstance(v, str) and bool(r.fullmatch(v))


def _str(limit):
    return lambda v: isinstance(v, str) and len(v) <= limit and not re.search(r"[\x00-\x1f\x7f]", v)


def _regex(v):
    if not (isinstance(v, str) and len(v) <= 300):
        return False
    try:
        re.compile(v)
        return True
    except re.error:
        return False


def _str_list(v):
    return isinstance(v, list) and len(v) <= 20 and all(isinstance(x, str) and 0 < len(x) <= 100 and not re.search(r"[\x00-\x1f\x7f]", x) for x in v)


TOKEN = _rx(SLUG)
# Per job system: {key: (validator, required)}. Keys not listed are dropped; a bad value rejects the company.
CONFIG_RULES = {
    "greenhouse": {"token": (TOKEN, True)},
    "lever": {"token": (TOKEN, True)},
    "ashby": {"token": (_rx(r"[A-Za-z0-9][A-Za-z0-9_.%-]{0,99}"), True)},
    "smartrecruiters": {"token": (TOKEN, False), "id": (TOKEN, False)},
    "workday": {"tenant": (TOKEN, True), "wd": (_rx(r"wd\d{1,3}"), True), "site": (TOKEN, True),
                "host": (_rx(r"[a-z0-9][a-z0-9.-]{0,120}\.(myworkdayjobs|myworkdaysite)\.com"), False), "search": (_str(100), False)},
    "icims": {"base": (_rx(r"https://[a-z0-9][a-z0-9-]{0,80}\.icims\.com"), True)},
    "ukg": {"host": (_rx(r"recruiting2?\.ultipro\.com|[a-z0-9][a-z0-9-]{0,80}\.rec\.pro\.ukg\.net"), False),
            "tenant": (_rx(ALNUM), True), "board": (_rx(UUID), True)},
    "oracle": {"base": (_origin_only, True), "site": (TOKEN, True)},   # (oraclecloud.com or the employer's own domain)
    "paylocity": {"id": (_rx(UUID), True)},
    "adp": {"cid": (_rx(UUID), True)},
    "rippling": {"token": (TOKEN, True)},
    "workable": {"token": (TOKEN, True)},
    "bamboohr": {"token": (TOKEN, True)},
    "jazzhr": {"token": (TOKEN, True)},
    "breezy": {"token": (TOKEN, True)},
    "recruitee": {"token": (TOKEN, True)},
    "paycom": {"key": (_rx(r"[A-Fa-f0-9]{32}"), True)},
    "saashr": {"host": (_rx(r"secure\d{0,3}\.saashr\.com"), True), "cid": (_rx(r"\d{1,12}"), True)},
    "dayforce": {"ns": (_rx(ALNUM), True), "board": (_rx(ALNUM), False)},
    "radancy": {"base": (_origin_only, True)},
    "eightfold": {"host": (_rx(r"[a-z0-9][a-z0-9.-]{0,120}\.[a-z]{2,24}"), True), "domain": (_rx(r"[a-z0-9][a-z0-9.-]{0,120}\.[a-z]{2,24}"), True)},
    "avature": {"base": (_origin_only, True), "portal": (_rx(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}"), True)},
    "amazon": {"locations": (_str_list, False)},
    "phenom": {"url": (_https_origin, True), "refnum": (_rx(ALNUM), True)},
    "jibe": {"base": (_origin_only, True)},
    "clearcompany": {"url": (_rx(r"https://careers-api\.clearcompany\.com/v1/" + UUID), True), "board": (_https_origin, False)},
    "jsonld": {"list_url": (_https_origin, False), "sitemap": (_https_origin, False), "path_re": (_regex, False),
               "link_prefix": (_rx(r"/[^\s\x00-\x1f]{0,300}"), False)},
}
COMMON_RULES = {"verified_total": (lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10**7, False),
                "verified_at": (_rx(r"\d{4}-\d{2}-\d{2}(T[0-9:]{8}Z?)?"), False)}
NEEDS_ONE = {"smartrecruiters": ("token", "id"), "jsonld": ("list_url", "sitemap")}
META_KEYS = ("name", "tier", "sector", "size", "ai_track", "sets", "added_by")


def clean_config(c):
    """Validate a company's job-board config. Returns ({"ats": ..., valid keys...}, None) or (None, reason).
    Unknown keys are dropped; a missing or malformed value rejects it. Meta keys (name, tier, ...) are not touched
    or returned here."""
    if not isinstance(c, dict):
        return None, "not a company"
    ats = c.get("ats")
    rules = CONFIG_RULES.get(ats) if isinstance(ats, str) else None
    if rules is None:
        return None, f"unsupported job system {str(ats)[:30]!r}"
    out = {"ats": ats}
    for k, (ok, required) in {**rules, **COMMON_RULES}.items():
        if k not in c or c[k] in (None, ""):
            if required:
                return None, f"{ats} config is missing {k}"
            continue
        if not ok(c[k]):
            return None, f"{ats} config has a bad {k}"
        out[k] = c[k]
    need = NEEDS_ONE.get(ats)
    if need and not any(k in out for k in need):
        return None, f"{ats} config needs one of {', '.join(need)}"
    return out, None


def check_config(c):
    """Raise UnsafeURL with the reason when a company's config isn't valid (before a fetch)."""
    _, why = clean_config(c)
    if why:
        raise UnsafeURL(f"company config refused: {why}")
