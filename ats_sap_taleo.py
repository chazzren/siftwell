"""Fetchers for SAP SuccessFactors career sites (Recruiting Marketing, "jobs2web") and Oracle Taleo career sections.

SuccessFactors (ats "successfactors", config {"base": "https://jobs.example.com"}): the company's own career site
(a custom domain, or jobs.sap.com style) publishes /sitemap.xml. On most sites that file is a Google-for-Jobs RSS feed
with every open posting and its full text (one request); on some it is a plain list of links, so the site's own public
search pages (/search/?q=&startrow=N, 25 rows a page) are read instead and the posting page is fetched for the text.
robots.txt on these sites only disallows /services/ (the RSS service), /applybutton/ etc.; neither of those is used.

Taleo (ats "taleo", config {"host": "x.taleo.net", "section": "<career section>"}): the career section's own search
page. Newer sections load jobs from /careersection/rest/jobboard/searchjobs (JSON, 25 a page; the page names its
"portal" number); older ones render the first page into the HTML and page with the same form post the page's own
script sends. Posting text comes from jobdetail.ftl (only for titles somebody's filters could want).

Nothing here logs in, solves anything or goes round a block: a site that refuses (403/429 and the like) is reported
as an error, and every request goes through netsafe. Requests are polite: at most 2 at a time per fetch and a short pause
between them."""
import concurrent.futures as cf
import datetime as dt
import gzip
import html as _html
import http.cookiejar
import io
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import netsafe

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 (Siftwell personal job board)"
PAUSE = 0.25            # seconds between requests to one site
SF_CAP = 3000           # most postings read through the search pages (the RSS feed has no cap)
TALEO_CAP = 2000
MAX_BYTES = 80_000_000

STATES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
          "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
          "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
          "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
          "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
          "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
          "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
          "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
          "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR"}
CODES = set(STATES.values())
US_WORDS = {"us", "usa", "u.s.", "united states", "united states of america"}


def _jf():
    import extra_fetchers
    return extra_fetchers


def _strip(s):
    import jobfinder
    return jobfinder.strip_html(s)


def _job(c, title, url, locs, wp, desc, posted, dept, jid):
    import jobfinder
    return jobfinder.J(c, title, url, locs, wp, None, desc, posted, dept, jid)


# ---------------------------------------------------------------- requests
_lock = threading.Lock()
_last = {}


def _polite(host):
    with _lock:
        wait = _last.get(host, 0) + PAUSE - time.time()
        _last[host] = time.time() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def _open(url, data=None, headers=None, opener=None, timeout=45, tries=3):
    """GET (or POST when data is given) through netsafe; gzip understood; 429/5xx retried with a pause (Retry-After
    honoured). Returns (bytes, final_url)."""
    host = urllib.parse.urlsplit(url).netloc
    hdr = {"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})}
    for i in range(tries):
        _polite(host)
        try:
            req = urllib.request.Request(url, data=data, headers=hdr)
            with netsafe.urlopen(req, timeout=timeout, opener=opener) as r:
                raw = r.read(MAX_BYTES)
                if r.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_BYTES)
                return raw, r.geturl()
        except netsafe.UnsafeURL:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                ra = e.headers.get("Retry-After") if e.headers else None
                time.sleep(min(30, float(ra)) if ra and ra.isdigit() else 3 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, OSError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _text(url, **kw):
    raw, final = _open(url, **kw)
    return raw.decode("utf-8", "replace"), final


# ---------------------------------------------------------------- locations
def _is_zip(s):
    return bool(re.fullmatch(r"\d{4,5}(-\d{4})?|[A-Z]\d[A-Z] ?\d[A-Z]\d", s.strip()))


def sf_location(label, bare_states=False):
    """SuccessFactors: 'Spencer, IN, US, 47460' / 'Penang, MY' / 'Remote, US' -> 'Spencer, IN' (US) or a label
    with the ' europe' non-US marker (jobfinder.prepare_listing() drops those unless they're remote-US). The country
    is what says "US": a bare 'Asbach, DE' is Germany, not Delaware. Only when a whole site never names a country
    (bare_states) are 'Dallas, TX' style labels read as US states."""
    parts = [p.strip() for p in (label or "").split(",") if p.strip()]
    while parts and _is_zip(parts[-1]):
        parts.pop()
    if not parts:
        return ""
    last = parts[-1].lower()
    if last in US_WORDS:
        parts.pop()
        if len(parts) >= 2 and parts[-1].upper() in CODES:
            return f"{', '.join(parts[:-1])}, {parts[-1].upper()}"
        if len(parts) >= 2 and parts[-1].lower() in STATES:
            return f"{', '.join(parts[:-1])}, {STATES[parts[-1].lower()]}"
        return ", ".join(parts)
    if bare_states and len(parts) >= 2 and parts[-1].upper() in CODES and parts[-1].isupper():
        return f"{', '.join(parts[:-1])}, {parts[-1]}"       # 'Dallas, TX' (no country given anywhere on this site)
    if len(parts) >= 2 and parts[-1].lower() in STATES:
        return f"{', '.join(parts[:-1])}, {STATES[parts[-1].lower()]}"
    if re.fullmatch(r"remote|virtual|home office|work from home|anywhere", last):
        return ", ".join(parts)
    return f"{', '.join(parts)} europe"                     # a country code or name that isn't the US


def taleo_location(label):
    """Taleo: 'US-NY-Buffalo', 'OH-Fairfield', 'USA-Texas-Midland', 'Kansas-Topeka', 'Multiple Locations'."""
    s = _html.unescape(label or "").strip()
    if not s or "-" not in s:
        return s
    toks = [t.strip() for t in s.split("-") if t.strip()]
    if toks and toks[0].lower() in US_WORDS:
        toks = toks[1:]
        us = True
    else:
        us = False
    if len(toks) >= 3 and re.fullmatch(r"[A-Z]{2}", toks[0]) and re.fullmatch(r"[A-Z]{2}", toks[1]) and not us:
        st, city = None, None                            # 'CA-ON-Toronto': country, province, city (not California)
    elif toks and (toks[0].upper() in CODES and len(toks[0]) == 2):
        st, city = toks[0].upper(), "-".join(toks[1:])
    elif toks and toks[0].lower() in STATES:
        st, city = STATES[toks[0].lower()], "-".join(toks[1:])
    else:
        st, city = None, None
    if st:
        return f"{city}, {st}" if city else st
    if us:
        return "-".join(toks)
    return f"{s} europe"                                   # first part isn't a US state: some other country


def taleo_locations(raw):
    """A list cell ('["OH-Fairfield"]', a JSON list) or a legacy 'Kansas-Topeka, Missouri-Kansas City' string."""
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            items = [str(x) for x in json.loads(raw)]
        except ValueError:
            items = [raw]
    elif isinstance(raw, list):
        items = [str(x) for x in raw]
    else:
        items = re.split(r",\s*(?=[A-Za-z. ]+-)|\s*[|;]\s*", str(raw or ""))
    out = []
    for x in items:
        x = taleo_location(x)
        if x and x.lower() != "multiple locations" and x not in out:
            out.append(x)
    return out


def _iso(s):
    """'Nov 9, 2026' / 'Tue Nov 10 08:00:00 UTC 2026' / '2026-11-09...' -> '2026-11-09'."""
    s = (s or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    for rx, fmt in ((r"[A-Z][a-z]{2} \d{1,2}, \d{4}", "%b %d, %Y"), (r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2} [\d:]+ [A-Z]+ \d{4}", None)):
        m = re.search(rx, s)
        if m:
            try:
                if fmt:
                    return dt.datetime.strptime(m.group(0), fmt).strftime("%Y-%m-%d")
                p = m.group(0).split()
                return dt.datetime.strptime(f"{p[1]} {p[2]} {p[5]}", "%b %d %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
    return ""


def _remote(locs, title=""):
    import jobtext   # ("Not Remote" / "Non-Remote" labels and "Remote Sensing" titles are not remote work)
    return "remote" if any(jobtext.remote_label(l) for l in locs) or jobtext.workplace_label(title) == "remote" else ""


# ---------------------------------------------------------------- SuccessFactors
GNS = "{http://base.google.com/ns/1.0}"


def sf_feed_items(raw):
    """Postings from a SuccessFactors Google-Jobs RSS feed: dicts with title, link, id, location, function, employer, desc."""
    out = []
    for _, el in ET.iterparse(io.BytesIO(raw), events=("end",)):
        if el.tag != "item":
            continue
        g = lambda t: (el.findtext(GNS + t) or "").strip()
        out.append({"title": (el.findtext("title") or "").strip(), "link": (el.findtext("link") or "").strip(),
                    "id": g("id") or (el.findtext("guid") or "").strip(), "location": g("location"), "function": g("job_function"),
                    "employer": g("employer"), "desc": el.findtext("description") or ""})
        el.clear()
    return out


def _clean_title(title, loc):
    """'Technician (Kemmerer, WY, US, 83101)': the location label SuccessFactors appends to the title is dropped."""
    m = re.match(r"^(.*\S)\s*\(([^()]*)\)\s*$", title)
    if m and loc and m.group(2).strip().lower() == loc.strip().lower():
        return m.group(1)
    return title


def _sf_site_ok(base):
    netsafe.check_url(base, resolve=False)


def sf_search_rows(page):
    """Rows of a SuccessFactors /search/ results page: (url path, title, location label, iso date) and the total."""
    rows = []
    for card in re.split(r'<tr class="data-row"', page)[1:]:
        m = re.search(r'<a[^>]*href="([^"]*/job/[^"]+)"[^>]*class="jobTitle-link"[^>]*>(.*?)</a>', card, re.S) or \
            re.search(r'<a[^>]*class="jobTitle-link"[^>]*href="([^"]*/job/[^"]+)"[^>]*>(.*?)</a>', card, re.S)
        if not m:
            continue
        lm = re.search(r'<span class="jobLocation">\s*(.*?)\s*</span>', card, re.S)
        dm = re.search(r'class="jobDate[^"]*">\s*([^<]*?)\s*<', card) or re.search(r'class="colDate[^"]*"[^>]*>\s*(?:<span[^>]*>)?\s*([^<]*?)\s*<', card)
        rows.append((_html.unescape(m.group(1)), re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip(),
                     re.sub(r"\s+", " ", _html.unescape(lm.group(1))).strip() if lm else "", _iso(dm.group(1)) if dm else ""))
    tm = re.search(r"(?:Results?|Showing)\s+[\d,]+\s*(?:to|-|&ndash;|–)\s*[\d,]+\s+of\s+([\d,]+)", re.sub(r"<[^>]+>", " ", page), re.I)
    return rows, int(tm.group(1).replace(",", "")) if tm else None


def sf_detail(page):
    """(description text, iso date posted, [locations]) from a posting page's schema.org markup."""
    i = page.find('itemprop="description"')
    desc = ""
    if i >= 0:
        seg = page[page.find(">", i) + 1:]
        cut = [seg.find(x) for x in ('<div class="joblayouttoken', '<div class="jobColumnTwo', '<div class="applylink', '<div class="jobFooter', "</article>") if seg.find(x) > 0]
        desc = _strip(seg[:min(cut)] if cut else seg[:60000])
    dm = re.search(r'itemprop="datePosted"[^>]*content="([^"]*)"', page)
    am = re.search(r'itemprop="addressLocality"[^>]*content="([^"]*)"', page)
    rm = re.search(r'itemprop="addressRegion"[^>]*content="([^"]*)"', page)
    cm = re.search(r'itemprop="addressCountry"[^>]*content="([^"]*)"', page)
    loc = ", ".join(x for x in (am and am.group(1), rm and rm.group(1), cm and cm.group(1)) if x)
    return desc, _iso(dm.group(1)) if dm else "", [sf_location(loc)] if loc else []


def sf_count(base):
    """(open postings, employer name) for a site: from the feed when it has one (a single, gzip-compressed request),
    else from the site's own search page. Raises when neither gives a number."""
    try:
        raw, _ = _open(f"{base}/sitemap.xml")
        if raw.lstrip()[:200].lower().find(b"<rss") >= 0:
            n = raw.count(b"<item>")
            em = re.search(rb"<g:employer>\s*([^<]{2,80}?)\s*</g:employer>", raw)
            if n:
                return n, _html.unescape(em.group(1).decode("utf-8", "replace")) if em else None
    except urllib.error.HTTPError as e:
        if e.code not in (404, 410):
            raise
    page, _ = _text(f"{base}/search/?q=&sortColumn=referencedate&sortDirection=desc")
    rows, total = sf_search_rows(page)
    if total is None:
        if not rows:
            raise ValueError("no job count on the SuccessFactors search page")
        total = len(rows)
    return total, None


def f_successfactors(c, sample=False):
    base = c["base"].rstrip("/")
    _sf_site_ok(base)
    feed = None
    try:
        raw, _ = _open(f"{base}/sitemap.xml")
        if raw.lstrip()[:200].lower().find(b"<rss") >= 0:
            feed = raw
    except netsafe.UnsafeURL:
        raise
    except urllib.error.HTTPError as e:
        if e.code not in (404, 410):
            raise
    if feed is not None:
        items = sf_feed_items(feed)
        if not items:
            raise ValueError("the SuccessFactors feed has no postings")
        bare = not any(re.search(r",\s*(US|USA)\b", it["location"]) for it in items)
        for it in items:
            loc = sf_location(it["location"], bare)
            locs = [loc] if loc else []
            yield _job(c, _clean_title(it["title"], it["location"]), it["link"], locs, _remote(locs, it["title"]), _strip(it["desc"]),
                       "", it["function"], it["id"] or it["link"])
            if sample:
                return
        return
    # no feed: the site's public search pages (+ each posting page for the text)
    rows, total, start = [], None, 0
    while start < SF_CAP:
        page, _ = _text(f"{base}/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow={start}")
        got, t = sf_search_rows(page)
        if total is None:
            total = t
        if not got:
            if total and start < total:
                c["_truncated"] = f"empty page at {start} of {total}"
            break
        rows += got
        start += len(got)
        if sample or (total is not None and start >= total):
            break
    else:
        c["_truncated"] = f"stopped at {SF_CAP} of {total}"
    seen = set()
    rows = [r for r in rows if not (r[0] in seen or seen.add(r[0]))]
    wanted = _jf().wanted
    bare = not any(re.search(r",\s*(US|USA)\b", r[2]) for r in rows)

    def detail(r):
        path, title, loc, posted = r
        url = urllib.parse.urljoin(base + "/", path)
        jid = re.search(r"/(\d+)/?(?:\?|$)", path)
        desc, locs, wp = "", [sf_location(loc, bare)] if loc else [], ""
        failed = False
        if not sample and wanted(c, title):
            try:
                desc, dposted, dlocs = sf_detail(_text(url)[0])
                posted = posted or dposted
                locs = locs or dlocs
            except netsafe.UnsafeURL:
                raise
            except Exception:
                failed = True
        j = _job(c, title, url, locs, _remote(locs, title), desc, posted, "", jid.group(1) if jid else path)
        if (not desc) and not sample:
            j["_partial"] = True      # no text this time (process() keeps any stored earlier; a later fetch fills it in)
        return j
    with cf.ThreadPoolExecutor(2) as ex:
        yield from ex.map(detail, rows)


# ---------------------------------------------------------------- Taleo
TALEO_REST_BODY = {
    "multilineEnabled": False, "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
    "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
    "filterSelectionParam": {"searchFilterSelections": [{"id": i, "selectedValues": []} for i in
                                                        ("POSTING_DATE", "LOCATION", "JOB_FIELD", "JOB_TYPE", "JOB_SCHEDULE", "JOB_LEVEL")]},
    "advancedSearchFiltersSelectionParam": {"searchFilterSelections": [{"id": i, "selectedValues": []} for i in
                                                                       ("ORGANIZATION", "LOCATION", "JOB_FIELD", "JOB_NUMBER", "URGENT_JOB",
                                                                        "EMPLOYEE_STATUS", "STUDY_LEVEL", "WILL_TRAVEL", "JOB_SHIFT")]},
    "pageNo": 1}


def _fill_items(arr):
    """The quoted values of one api.fillList(...) array on a Taleo page, url-decoded."""
    return [urllib.parse.unquote(x) for x in re.findall(r"'((?:[^'\\]|\\.)*)'", arr)]


def _legacy_row(items, i):
    """One list row starting at items[i] (the internal job id, which every legacy layout repeats along the row):
    (contest no, title, location label, iso date, index after the row) or None. The columns differ per career section
    (contest no before or after the title), so the title is the text that appears twice right after the id."""
    a = items[i]
    win = items[i + 1:i + 14]
    title = next((t for k, t in enumerate(win) if t not in ("true", "false", "") and not re.fullmatch(r"\d+", t) and t in win[k + 1:]), None)
    if title is None:
        return None
    p1 = win.index(title)
    if p1 > 1:
        return None
    p2 = p1 + 1 + win[p1 + 1:].index(title)
    reqno = win[0] if p1 == 1 and re.fullmatch(r"[A-Za-z0-9_]{2,20}", win[0]) and win[0] != a else None
    j = i + 1 + p2 + 1
    while j < len(items) and items[j] == a:
        j += 1
    if reqno is None and j < len(items) and re.fullmatch(r"[A-Za-z0-9_]{2,20}", items[j]):
        reqno, j = items[j], j + 1
    if reqno is None or j >= len(items):
        return None
    loc = items[j]
    date = next((_iso(x) for x in items[j + 1:j + 12] if re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", x)), "")
    return reqno, title, loc, date, j + 1


def taleo_legacy_rows(page):
    """(rows [(contest no, title, [locations], iso date)], total) from an older career section's list page."""
    rows = []
    for m in re.finditer(r"api\.fillList\('requisitionListInterface',\s*'listRequisition',\s*\[(.*?)\]\);", page, re.S):
        items = _fill_items(m.group(1))
        i = 0
        while i < len(items) - 4:
            if re.fullmatch(r"\d{3,}", items[i]):
                r = _legacy_row(items, i)
                if r:
                    rows.append((r[0], r[1], taleo_locations(r[2]), r[3]))
                    i = r[4]
                    continue
            i += 1
    tm = re.search(r"\((\d[\d,]*) jobs? found\)", page)
    return rows, int(tm.group(1).replace(",", "")) if tm else None


def taleo_rest_rows(d):
    """(rows, total) from a searchjobs JSON answer. Column order differs per career section, so the response's own
    linkedColumn (the title) and locationsColumns tell where things are."""
    if not isinstance(d, dict) or d.get("careerSectionUnAvailable"):
        raise ValueError("this Taleo career section isn't available")
    rows = []
    for r in d.get("requisitionList") or []:
        col = r.get("column") or []
        li = r.get("linkedColumn")
        title = col[li] if isinstance(li, int) and li < len(col) else ""
        locs = []
        for k in r.get("locationsColumns") or []:
            if k < len(col):
                locs += taleo_locations(col[k])
        date = next((_iso(x) for x in col if isinstance(x, str) and re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", x)), "")
        if r.get("contestNo") and title:
            rows.append((str(r["contestNo"]), _html.unescape(title), locs, date))
    pg = d.get("pagingData") or {}
    return rows, pg.get("totalCount")


def taleo_detail(page):
    """(description text, [location]) from jobdetail.ftl's descRequisition list."""
    m = re.search(r"api\.fillList\('requisitionDescriptionInterface',\s*'descRequisition',\s*\[(.*?)\]\);", page, re.S)
    if not m:
        return "", []
    items = _fill_items(m.group(1))
    k = next((i for i, x in enumerate(items) if x.startswith("!*!")), None)
    if k is None:
        return "", []
    loc = items[k - 1] if k >= 1 else ""
    texts = []
    for x in items:
        if x.startswith("!*!") and x not in texts:
            texts.append(x)
    return _strip("\n".join(t[3:] for t in texts)), (taleo_locations(loc) if re.fullmatch(r"(?:[A-Za-z.]+-)+[A-Za-z .'-]+", loc) else [])


def _taleo_opener():
    return netsafe.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def taleo_list(c, sample=False):
    """All rows of a career section: (rows, total). Sets c["_truncated"] when it stops early."""
    host, section = c["host"], c["section"]
    base = f"https://{host}/careersection/{urllib.parse.quote(section)}"
    op = _taleo_opener()
    page, _ = _text(f"{base}/jobsearch.ftl?lang=en", opener=op)
    pm = re.search(r"portal=(\d{5,})", page)
    rows, total = [], None
    if pm:                                               # faceted career section: JSON search
        n = 0
        while True:
            n += 1
            body = json.loads(json.dumps(TALEO_REST_BODY))
            body["pageNo"] = n
            raw, _ = _open(f"https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={pm.group(1)}",
                           data=json.dumps(body).encode(), opener=op,
                           headers={"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                                    "Referer": f"{base}/jobsearch.ftl?lang=en", "tz": "GMT-05:00", "tzname": "America/New_York"})
            got, t = taleo_rest_rows(json.loads(raw))
            total = t if t is not None else total
            if not got:
                if total and len(rows) < total:
                    c["_truncated"] = f"empty page {n} at {len(rows)} of {total}"
                break
            rows += got
            if sample or (total is not None and len(rows) >= total):
                break
            if len(rows) >= TALEO_CAP:
                c["_truncated"] = f"Taleo list stopped at {TALEO_CAP} of {total}"
                break
        return rows, total
    # older career section: the page's own pager is a form post. (The list that comes with the first GET is in a
    # different order from the pager's pages, so every page is read through the pager, page 1 included.)
    got, total = taleo_legacy_rows(page)
    if "ftlform" not in page and not got:
        raise ValueError("no job list found on the Taleo page")
    if sample:
        return got, total
    hidden = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', page):
        nm, vm = re.search(r'name="([^"]*)"', m.group(0)), re.search(r'value="([^"]*)"', m.group(0))
        if nm:
            hidden[nm.group(1)] = _html.unescape(vm.group(1)) if vm else ""
    n, seen = 0, set()
    while len(rows) < TALEO_CAP and (total is None or len(rows) < total):
        n += 1
        fields = dict(hidden, ftlcompid="rlPager", ftlcompclass="PagerComponent", ftlinterfaceid="requisitionListInterface",
                      ftlpageid="reqListBasicPage")
        fields["rlPager.currentPage"] = str(n)
        raw, _ = _open(f"{base}/jobsearch.ftl?lang=en", data=urllib.parse.urlencode(fields).encode(), opener=op,
                       headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": f"{base}/jobsearch.ftl?lang=en"})
        got, t = taleo_legacy_rows(raw.decode("utf-8", "replace"))
        total = t if t is not None else total
        new = [r for r in got if r[0] not in seen]
        if not new:
            break
        seen.update(r[0] for r in new)
        rows += new
    if total and len(rows) < total:
        c["_truncated"] = f"read {len(rows)} of {total}"
    return rows, total


def f_taleo(c, sample=False):
    host, section = c["host"], c["section"]
    base = f"https://{host}/careersection/{urllib.parse.quote(section)}"
    rows, total = taleo_list(c, sample)
    wanted = _jf().wanted
    op = _taleo_opener()

    def detail(r):
        no, title, locs, posted = r
        url = f"{base}/jobdetail.ftl?job={urllib.parse.quote(no)}&lang=en"
        desc = ""
        if not sample and wanted(c, title):
            try:
                desc, dlocs = taleo_detail(_text(url, opener=op)[0])
                if dlocs and not locs:      # ('Multiple Locations' in the list: the posting names them)
                    locs = dlocs
            except netsafe.UnsafeURL:
                raise
            except Exception:
                pass
        j = _job(c, title, url, locs, _remote(locs, title), desc, posted, "", no)
        if not desc and not sample:
            j["_partial"] = True
        return j
    with cf.ThreadPoolExecutor(2) as ex:
        yield from ex.map(detail, rows)


# ---------------------------------------------------------------- adding a company
SF_PAGE = re.compile(r"/platform/js/j2w/|j2w\.(?:TC|Agent|Search)\b|data-careersite-propertyid")
TALEO_URL = re.compile(r"https?://((?:[a-z0-9-]+\.)?[a-z0-9-]+\.taleo\.net)/careersection/(?!rest/|theme/|sitemap)([A-Za-z0-9_.-]+)/", re.I)
TALEO_BAD_HOSTS = {"www.taleo.net", "tbe.taleo.net"}


def match_taleo(text):
    for m in TALEO_URL.finditer(text):
        if m.group(1).lower() in TALEO_BAD_HOSTS or m.group(2).lower() in ("jobdetail.ftl", "jobsearch.ftl"):
            continue
        return {"ats": "taleo", "host": m.group(1).lower(), "section": m.group(2)}
    return None


def detect_page(url, page):
    """Config for a company's own careers page that runs SuccessFactors Recruiting Marketing (its pages load the
    platform's j2w scripts), judged from the page text; the site root of that page is the base."""
    t = match_taleo(page)
    if t:
        return t
    if SF_PAGE.search(page):
        p = urllib.parse.urlsplit(url)
        if p.scheme in ("http", "https") and p.hostname:
            return {"ats": "successfactors", "base": f"https://{p.hostname}"}
    return None


def verify(c):
    """(open job count, suggested name) from the live site; raises when it can't be read."""
    if c["ats"] == "successfactors":
        return sf_count(c["base"].rstrip("/"))
    rows, total = taleo_list(dict(c, name="check"), sample=True)
    return (total if total is not None else len(rows)), None


FETCHERS = {"successfactors": f_successfactors, "taleo": f_taleo}
