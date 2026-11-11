"""Readers for job systems that public employers (school districts, hospitals, small governments) use: AppliTrack
(Frontline Recruiting & Hiring), SchoolSpring and Jobvite. No LLM, no login, public pages and feeds only.

It reuses ats_more's polite http (netsafe: public http/https hosts only; robots.txt checked first, longest matching rule
wins; paced requests; at most 2 at once per company; 401/403/429 are not worked around).

Config fields per "ats":

  applitrack   slug   - the district's path on www.applitrack.com (https://www.applitrack.com/<slug>/onlineapp/).
               place  - optional "City, ST" of the district (AppliTrack lists school names, not towns).
               feed: GET /<slug>/onlineapp/jobpostings/Output.asp?all=1 (the embeddable job list: a JavaScript file of
               document.write("...") calls holding every opening with its full text, one request).
  schoolspring sub    - the district's SchoolSpring subdomain (<sub>.schoolspring.com).
               feed: GET api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch?domainName=<sub>.schoolspring.com (JSON,
               100 per page); GET api.schoolspring.com/api/Jobs/<id> for the text, pay and employer.
  jobvite      slug   - https://jobs.jobvite.com/<slug>/jobs (HTML list by category; posting pages carry the text).

Not read, on purpose: NEOGOV / GovernmentJobs.com and PeopleAdmin forbid every crawler in their robots.txt, so they are
reported as unsupported instead of being worked around."""
import html as _html, re, time, urllib.parse, datetime
import ats_more
from ats_more import fetch, get_json, _pool, _wanted, us_label, us_locations
from jobfinder import J, strip_html

SS_PAGE = 100
SS_RETRY_WAIT = 3
SS_CAP = 3000       # SchoolSpring postings per run
AT_CAP = 20_000_000  # AppliTrack list bytes (a big district's list holds every job's text)


def _clean(s):
    return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()


def _us(labels):
    locs, outside = us_locations(labels)
    return locs, outside


# ---------------------------------------------------------------- AppliTrack (Frontline Recruiting & Hiring)
def at_list_url(slug):
    return f"https://www.applitrack.com/{slug}/onlineapp/jobpostings/Output.asp?all=1"


def at_job_url(slug, jid):
    return f"https://www.applitrack.com/{slug}/onlineapp/default.aspx?AppliTrackJobId={jid}&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1"


def _js_unescape(s):
    return s.replace("\\'", "'").replace('\\"', '"').replace("\\/", "/").replace("\\\\", "\\")


def _us_date(s):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return ""
    try:
        return datetime.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return ""


def at_parse(text):
    """[{id, title, type, posted, loc, desc}] from an Output.asp file."""
    t = _js_unescape(text)
    out = []
    for blk in t.split("<table class='title'")[1:]:
        m = re.search(r"JobID:\s*(\d+)", blk)
        if not m:
            continue
        tm = re.search(r"<td id='wrapword'[^>]*>(.*?)</td>", blk, re.S)

        def field(label):
            f = re.search(r"<span class=['\"]label['\"]\s*>\s*" + label + r"\s*:?\s*</span>\s*<br\s*/?>\s*(?:&nbsp;)*\s*<span class=['\"]normal['\"]>(.*?)</span>", blk, re.S)
            return _clean(re.sub(r"<[^>]+>", " ", f.group(1))) if f else ""
        d = re.search(r"id='DescriptionText" + m.group(1) + r"_'[^>]*>(.*?)<br\s*/><img", blk, re.S)
        out.append({"id": m.group(1), "title": _clean(re.sub(r"<[^>]+>", " ", tm.group(1))) if tm else "",
                    "type": field("Position Type"), "posted": _us_date(field("Date Posted")),
                    "loc": field("Location"), "desc": strip_html(d.group(1)) if d else ""})
    return out


def f_applitrack(c):
    text = fetch(at_list_url(c["slug"]), cap=AT_CAP)[0]
    place = c.get("place") or ""
    for p in at_parse(text):
        if not p["title"]:
            continue
        labels = [place] if place else []
        # a school's own name is no address; but "Frederick, MD" style text in the Location field is kept
        if p["loc"] and re.search(r",\s*[A-Z]{2}\b", p["loc"]):
            labels = [p["loc"]]
        locs, outside = _us(labels)
        if outside:
            continue
        desc = p["desc"]
        if p["loc"] and p["loc"].lower() not in ("various locations", "district wide", "districtwide"):
            desc = f"Location: {p['loc']}\n{desc}" if desc else f"Location: {p['loc']}"
        yield J(c, p["title"], at_job_url(c["slug"], p["id"]), locs, ats_more._wp(p["title"]), None, desc,
                p["posted"], p["type"], p["id"])


def applitrack_count(c):
    ps = at_parse(fetch(at_list_url(c["slug"]), cap=AT_CAP)[0])
    name = None
    try:
        t = re.search(r"<title>(.*?)</title>", fetch(f"https://www.applitrack.com/{c['slug']}/onlineapp/default.aspx")[0], re.S)
        name = re.sub(r"\s*[-|]\s*(Frontline|AppliTrack).*$", "", _clean(t.group(1)), flags=re.I) if t else None
    except Exception:
        pass
    return len(ps), name or None


# ---------------------------------------------------------------- SchoolSpring
SS_API = "https://api.schoolspring.com/api/Jobs"


def ss_list_url(sub, page):
    return (f"{SS_API}/GetPagedJobsWithSearch?domainName={sub}.schoolspring.com&keyword=&location=&category=&gradelevel=&jobtype="
            f"&organization=&swLat=&swLon=&neLat=&neLon=&page={page}&size={SS_PAGE}&sortDateAscending=false")


def ss_pages(c):
    seen = set()
    for page in range(1, SS_CAP // SS_PAGE + 2):
        d = get_json(ss_list_url(c["sub"], page))
        rows = ((d or {}).get("value") or {}).get("jobsList") or []
        for _ in range(2 if page == 1 and not rows else 0):   # (the API now and then answers an empty first page for a board that has jobs)
            time.sleep(SS_RETRY_WAIT)
            d = get_json(ss_list_url(c["sub"], page))
            rows = ((d or {}).get("value") or {}).get("jobsList") or []
            if rows:
                break
        new = [r for r in rows if r.get("jobId") not in seen]
        for r in new:
            seen.add(r.get("jobId"))
        yield from new
        if len(rows) < SS_PAGE or not new or len(seen) >= SS_CAP:
            return


def ss_detail(jid, sub):
    d = get_json(f"{SS_API}/{jid}?domainName={sub}.schoolspring.com")
    return (d or {}).get("value") or {}


def ss_location(s):
    """"Gillette, Wyoming" -> "Gillette, WY"; "n/a, Oregon" -> "Oregon"."""
    s = re.sub(r"^\s*(n/?a|none|null)\s*,\s*", "", s or "", flags=re.I)
    return us_label(s) or ""


def f_schoolspring(c):
    rows = list(ss_pages(c))

    def one(r):
        jid = r["jobId"]
        title = _html.unescape(r.get("title") or "")
        locs = [ss_location(r.get("location"))]
        d, desc, failed = {}, "", False
        want = _wanted(c, title)
        if want:
            try:
                d = ss_detail(jid, c["sub"])
            except Exception:
                failed = True
        info = d.get("jobInfo") or {}
        if info:
            for jl in d.get("jobLocations") or []:
                locs.append(ss_location(jl.get("displayLocation")))
            desc = strip_html(info.get("jobDescription") or "")
            if info.get("payMin") and info.get("payDisplay"):
                lo, hi = info.get("payMin"), info.get("payMax") or info.get("payMin")
                unit = (info.get("salaryCode") or "").replace("Per ", "per ").strip()
                desc = f"Pay: ${lo:,.2f} - ${hi:,.2f} {unit}\n{desc}".strip()
        locs = [l for l in dict.fromkeys(locs) if l]
        url = f"https://{c['sub']}.schoolspring.com/jobs?jobid={jid}"
        j = J(c, title, url, locs, ats_more._wp(title), None, desc, (r.get("displayDate") or "")[:10],
              r.get("employer") or info.get("displayEmployer") or "", str(jid))
        if not want or failed:
            j["_partial"] = True
        return j
    yield from _pool(one, rows)


def schoolspring_count(c):
    first = list(ss_pages(dict(c, name="check")))
    n = len(first)
    name = None
    if first:
        try:
            name = (ss_detail(first[0]["jobId"], c["sub"]).get("jobInfo") or {}).get("employerName")
        except Exception:
            pass
    return n, (name or "").title() or None


# ---------------------------------------------------------------- Jobvite
def _long_date(s):
    """"June 18, 2025" -> "2025-06-18" ("" when it isn't one)."""
    try:
        return datetime.datetime.strptime(_clean(s), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def jv_url(slug):
    return f"https://jobs.jobvite.com/{slug}/jobs"


def jv_parse(h, slug):
    """[{id, title, loc, dept}] from the Jobvite list page (jobs grouped under h3 headings)."""
    out, dept = [], ""
    pos = 0
    rx = re.compile(r"<h3[^>]*>(.*?)</h3>|<td class=\"jv-job-list-name\">\s*<a href=\"(/" + re.escape(slug) + r"/job/([A-Za-z0-9]+))\"[^>]*>(.*?)</a>\s*</td>\s*(?:<td class=\"jv-posting-date\">(.*?)</td>\s*)?<td class=\"jv-job-list-location\">(.*?)</td>", re.S | re.I)
    for m in rx.finditer(h):
        if m.group(1) is not None:
            dept = _clean(re.sub(r"<[^>]+>", " ", m.group(1)))
            continue
        out.append({"id": m.group(3), "title": _clean(re.sub(r"<[^>]+>", " ", m.group(4))),
                    "posted": _long_date(m.group(5)),
                    "loc": _clean(re.sub(r"<[^>]+>", " ", m.group(6))).replace(" ,", ","), "dept": dept})
    return out


def jv_detail(h):
    """(description text, "City, State" labels) from a posting page."""
    d = re.search(r'<div class="jv-job-detail-description"[^>]*>(.*?)<div class="jv-job-detail-bottom-actions">', h, re.S)
    m = re.search(r'<p class="jv-job-detail-meta">(.*?)</p>', h, re.S)
    locs = []
    if m:
        parts = re.split(r"<span[^>]*jv-inline-separator[^>]*></span>", m.group(1))
        if len(parts) > 1:
            locs = [_clean(re.sub(r"<[^>]+>", " ", p)) for p in parts[1:]]
    return strip_html(d.group(1)) if d else "", locs


def f_jobvite(c):
    slug = c["slug"]
    rows = jv_parse(fetch(jv_url(slug))[0], slug)

    def one(r):
        title = r["title"]
        desc, failed = "", False
        want = _wanted(c, title)
        if want:
            try:
                desc = jv_detail(fetch(f"https://jobs.jobvite.com/{slug}/job/{r['id']}")[0])[0]
            except Exception:
                failed = True
        locs, outside = _us([r["loc"]])
        if outside:
            return None
        j = J(c, title, f"https://jobs.jobvite.com/{slug}/job/{r['id']}", locs, ats_more._wp(title + " " + r["loc"]), None, desc, r.get("posted", ""), r["dept"], r["id"])
        if not want or failed:
            j["_partial"] = True
        return j
    for j in _pool(one, rows):
        if j:
            yield j


def jobvite_count(c):
    h = fetch(jv_url(c["slug"]))[0]
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    name = re.sub(r"\s*(Careers|Jobs|Current Career Opportunities)\s*$", "", _clean(t.group(1)), flags=re.I) if t else None
    return len(jv_parse(h, c["slug"])), (name if name and name.lower() != "current career opportunities" else None)


# ---------------------------------------------------------------- detection from a careers link
_AT_RX = re.compile(r"(?:https?:)?//(?:www\.)?applitrack\.com/([A-Za-z0-9_.-]+)/onlineapp", re.I)
_SS_RX = re.compile(r"(?:https?:)?//([a-z0-9][a-z0-9-]*)\.schoolspring\.com", re.I)
_JV_RX = re.compile(r"(?:https?:)?//jobs\.jobvite\.com/(?:careers/)?([A-Za-z0-9_.-]+)", re.I)
_SS_SKIP = {"www", "api", "app", "employer", "admin", "help", "blog", "cdn", "images"}
_JV_SKIP = {"careers", "support", "api", "www", "js", "css", "images", "static", "__assets__"}
_STREET = {"street", "st", "ave", "avenue", "road", "rd", "blvd", "boulevard", "drive", "dr", "lane", "ln", "way", "hwy", "highway", "suite", "ste", "box", "pkwy", "parkway", "court", "ct", "circle", "place", "pl", "plaza", "center", "building"}
_PLACE = re.compile(r"\b([A-Z][A-Za-z.' -]{2,40}),\s*([A-Z]{2})\s+\d{5}\b")


def _place_from(page):
    """"City, ST" from the first "... City, ST 12345" address in a page (the longest 1-3 word city the gazetteer knows)."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page or "", flags=re.S | re.I)
    t = _clean(re.sub(r"<[^>]+>", " ", t))
    m = _PLACE.search(t)
    if not m:
        return ""
    words = m.group(1).split()
    for i in range(len(words) - 1, -1, -1):   # the city comes after the street ("... South East Street Frederick")
        if words[i].lower().strip(".") in _STREET:
            words = words[i + 1:]
            break
    try:
        import geo
    except Exception:
        return ""
    for n in (3, 2, 1):
        if len(words) >= n:
            city = " ".join(words[-n:])
            if geo.locate(f"{city}, {m.group(2)}"):
                return f"{city}, {m.group(2)}"
    return ""


def detect(url, page=""):
    """A config for a careers link (and its page text) when it belongs to one of these systems, else None."""
    for text in (url, page or ""):
        m = _AT_RX.search(text)
        if m:
            cfg = {"ats": "applitrack", "slug": m.group(1)}
            try:
                p = _place_from(fetch(f"https://www.applitrack.com/{m.group(1)}/onlineapp/default.aspx")[0])
            except Exception:
                p = ""
            if p:
                cfg["place"] = p
            return cfg
        m = _SS_RX.search(text)
        if m and m.group(1).lower() not in _SS_SKIP:
            return {"ats": "schoolspring", "sub": m.group(1).lower()}
        m = _JV_RX.search(text)
        if m and m.group(1).lower() not in _JV_SKIP:
            return {"ats": "jobvite", "slug": m.group(1)}
    return None


def verify(c):
    """(job count, suggested name) from the live feed, or raise."""
    return {"applitrack": applitrack_count, "schoolspring": schoolspring_count, "jobvite": jobvite_count}[c["ats"]](dict(c, name="check"))


FETCHERS = {"applitrack": f_applitrack, "schoolspring": f_schoolspring, "jobvite": f_jobvite}
