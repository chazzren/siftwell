"""Sources that give job postings rather than readable employer feeds. Each returns
[{"t": title, "o": organisation, "u": link to the original posting, "l": [location labels], "w": "remote"|"",
  "pay": [min, max] or None, "d": "YYYY-MM-DD", "x": short summary}] for the whole US; build.py buckets them by state.

  usajobs       USAJOBS Search API (federal jobs). Needs USAJOBS_API_KEY + USAJOBS_EMAIL (free at developer.usajobs.gov);
                it runs the moment those two repository secrets exist, nothing else to switch on. The key stays in the
                builder: it is never written to the index. One search returns at most 10,000 postings, so the pull goes
                state by state (LocationName=<state>, 500 a page, every page), plus one pass for remote jobs, and merges
                by announcement: every public posting in every state, a few hundred paced requests a week, well inside
                the API's terms (identify yourself with the e-mail header, don't hammer it). OPM: public data may be
                redistributed; attribution encouraged. The app names USAJOBS and links every posting to its official
                announcement (the source's note is added to each posting, and Settings -> Employer directory lists it).
  careeronestop CareerOneStop Jobs API (U.S. Department of Labor, listings from the National Labor Exchange).
                DISABLED BY DEFAULT, even when its keys exist: its terms require CareerOneStop's logo, linked to
                CareerOneStop, next to the data, and Siftwell doesn't show a logo yet, and whether its listings may be
                redistributed in a public index is unresolved. To turn it on once that is settled: set
                CAREERONESTOP_ENABLE=1 next to CAREERONESTOP_TOKEN + CAREERONESTOP_USERID. Don't enable it before.
  schoolspring  SchoolSpring's nationwide job search (the same public API the app's SchoolSpring reader uses, asked
                for www.schoolspring.com instead of one district): every school posting with its school or district,
                town and state. No key. robots.txt allows it (www: nothing disallowed; the API host has none). Only
                title, employer, place, date and the link to the posting are kept. Time-boxed and paced.
  hn            Hacker News "Ask HN: Who is hiring?" (latest monthly thread) through the public Algolia HN API; no key.
                Only the company, the role line, places and a link to the comment are kept (no comment text).
  muse          The Muse public jobs API. Its old public endpoint answers 404 now (checked 2026-11); kept so it starts
                working again by itself if the API comes back, and skipped otherwise.
Every source is skipped cleanly (an empty list and a log line) when its key is missing or it fails."""
import datetime as dt, html, os, re, urllib.parse

from . import net


def _env(*names):
    vals = [os.environ.get(n, "").strip() for n in names]
    return vals if all(vals) else None


US_PAGE = 500            # USAJOBS: results per page (the API's maximum)
US_QUERY_MAX = 10_000    # ... and the most one search will page through
US_STATES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|"
             "Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|"
             "Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|"
             "Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|"
             "Washington|West Virginia|Wisconsin|Wyoming|Puerto Rico").split("|")


def _usajobs_item(it, remote=False):
    m = it.get("MatchedObjectDescriptor") or {}
    locs = []
    for p in m.get("PositionLocation") or []:
        nm = p.get("LocationName") or ""
        if "anywhere" in nm.lower() or "remote" in nm.lower():
            remote = True
        elif nm:
            locs.append(nm)
    pay = None
    for r in m.get("PositionRemuneration") or []:
        try:
            lo, hi = float(r.get("MinimumRange") or 0), float(r.get("MaximumRange") or 0)
            k = 2080 if (r.get("RateIntervalCode") or "").upper() in ("PH", "PER HOUR") else 1
            if hi:
                pay = [round(lo * k), round(hi * k)]
        except ValueError:
            pass
    return {"t": m.get("PositionTitle", ""), "o": m.get("OrganizationName") or m.get("DepartmentName") or "",
            "u": m.get("PositionURI", ""), "l": locs, "w": "remote" if remote else "", "pay": pay,
            "d": (m.get("PublicationStartDate") or "")[:10],
            "x": ((m.get("UserArea") or {}).get("Details") or {}).get("JobSummary", "")[:400]}


def usajobs(log=print, states=None, get=None):
    """Every public USAJOBS posting: one search per state (and one for remote jobs), every page, merged by
    announcement link. A state with more than US_QUERY_MAX postings is read from both ends (oldest and newest first).
    get: the JSON fetcher (tests pass a fake)."""
    import urllib.parse
    keys = _env("USAJOBS_API_KEY", "USAJOBS_EMAIL")
    if not keys:
        log("  USAJobs: skipped (no USAJOBS_API_KEY / USAJOBS_EMAIL secret)")
        return []
    key, email = keys
    hdr = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
    get = get or (lambda url: net.get_json(url, headers=hdr, robots=False, timeout=90))
    out, short, failed = {}, [], 0

    def pull(query, remote=False, direction=""):
        page, n = 1, 0
        while (page - 1) * US_PAGE < US_QUERY_MAX:
            url = f"https://data.usajobs.gov/api/search?ResultsPerPage={US_PAGE}&Page={page}&WhoMayApply=public&{query}{direction}"
            d = get(url)
            res = d.get("SearchResult") or {}
            items = res.get("SearchResultItems") or []
            for it in items:
                j = _usajobs_item(it, remote)
                if not j["u"]:
                    continue
                prev = out.get(j["u"])
                if prev is None:
                    out[j["u"]] = j
                elif remote and not prev["w"]:
                    prev["w"] = "remote"
            n = int(res.get("SearchResultCountAll") or 0)
            if not items or page * US_PAGE >= n:
                break
            page += 1
        return n

    for st in (states or US_STATES):
        try:
            q = "LocationName=" + urllib.parse.quote(st)
            n = pull(q)
            if n > US_QUERY_MAX:     # more than one search can page through: read the list from the other end too
                pull(q, direction="&SortField=opendate&SortDirection=asc")
                pull(q, direction="&SortField=opendate&SortDirection=desc")
                if n > 2 * US_QUERY_MAX:
                    short.append(f"{st} ({n})")
        except Exception as e:
            failed += 1
            log(f"  USAJobs {st}: {type(e).__name__}")
            if failed >= 5 and not out:
                break               # (a bad key or the API is down: don't knock 52 times)
    try:
        pull("RemoteIndicator=True", remote=True)
    except Exception as e:
        log(f"  USAJobs remote: {type(e).__name__}")
    log(f"  USAJobs: {len(out)} postings" + (f"; more than the API pages through in {', '.join(short)}" if short else "")
        + (f"; {failed} state searches failed" if failed else ""))
    return list(out.values())


SS_URL = ("https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch?domainName=www.schoolspring.com&keyword=&location=&category="
          "&gradelevel=&jobtype=&organization=&swLat=&swLon=&neLat=&neLon=&page={page}&size=100&sortDateAscending=false")


def schoolspring(log=print, max_pages=1500, minutes=25, get=None):
    """School jobs nationwide from SchoolSpring's public search (see the module docstring)."""
    import time
    get = get or (lambda url: net.get_json(url, timeout=60, tries=2))
    out, seen, t0, page = [], set(), time.time(), 1
    while page <= max_pages and time.time() - t0 < minutes * 60:
        try:
            d = get(SS_URL.format(page=page))
        except Exception as e:
            log(f"  SchoolSpring page {page}: {type(e).__name__}")
            break
        rows = ((d or {}).get("value") or {}).get("jobsList") or []
        new = 0
        for r in rows:
            jid = r.get("jobId")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            new += 1
            loc = str(r.get("location") or "").strip()
            out.append({"t": str(r.get("title") or "").strip(), "o": str(r.get("employer") or "").strip(),
                        "u": f"https://www.schoolspring.com/jobs?jobid={jid}", "l": [loc] if loc else [], "w": "",
                        "pay": None, "d": str(r.get("displayDate") or "")[:10], "x": ""})
        if len(rows) < 100 or not new:
            break
        page += 1
    log(f"  SchoolSpring: {len(out)} postings ({page} pages)")
    return out


def careeronestop(states, log=print, per_state=500):
    if os.environ.get("CAREERONESTOP_ENABLE", "").strip() != "1":
        log("  CareerOneStop: off (disabled by default until its logo/redistribution terms are settled; see postings.py)")
        return []
    keys = _env("CAREERONESTOP_TOKEN", "CAREERONESTOP_USERID")
    if not keys:
        log("  CareerOneStop: skipped (no CAREERONESTOP_TOKEN / CAREERONESTOP_USERID secret)")
        return []
    token, uid = keys
    out = []
    for st in states:
        try:
            # /v2/jobsearch/{userId}/{keyword}/{location}/{radius}/{sortColumns}/{sortOrder}/{startRecord}/{pageSize}/{days}
            url = f"https://api.careeronestop.org/v2/jobsearch/{urllib.parse.quote(uid)}/0/{st}/0/DatePosted/DESC/0/{per_state}/7"
            d = net.get_json(url, headers={"Authorization": f"Bearer {token}"}, robots=False, timeout=90)
        except Exception as e:
            log(f"  CareerOneStop {st}: {type(e).__name__}")
            continue
        for j in d.get("Jobs") or []:
            out.append({"t": j.get("JobTitle", ""), "o": j.get("Company", ""), "u": j.get("URL", ""),
                        "l": [j.get("Location", "")], "w": "", "pay": None, "d": str(j.get("DatePosted", ""))[:10], "x": ""})
    log(f"  CareerOneStop: {len(out)} postings")
    return out


def hn(log=print):
    """Latest 'Ask HN: Who is hiring?' thread. Also returns the job-board links found in it (for tenant discovery)."""
    try:
        d = net.get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10", robots=False)
        story = next(h for h in d.get("hits", []) if "who is hiring" in (h.get("title") or "").lower())
        item = net.get_json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}", robots=False, timeout=120)
    except Exception as e:
        log(f"  HN who is hiring: skipped ({type(e).__name__})")
        return [], []
    import geo
    out, links = [], []
    when = (story.get("created_at") or "")[:10]
    for c in item.get("children") or []:
        txt = c.get("text") or ""
        if not txt or c.get("author") is None:
            continue
        links += [html.unescape(u) for u in re.findall(r'href="([^"]+)"', txt)]
        first = html.unescape(re.sub(r"<[^>]+>", " ", re.split(r"<p>", txt, 1)[0])).strip()
        parts = [p.strip() for p in re.split(r"\s+[|•]\s+|\s+-\s+(?=[A-Z])", first) if p.strip()]
        if len(parts) < 2 or len(parts[0]) > 60:
            continue
        remote = bool(re.search(r"\bremote\b", first, re.I)) and not re.search(r"no remote|not remote|remote: no", first, re.I)
        locs = [p for p in parts[1:] if any(h.kind != "state" for h in geo.locate_all(p)) and len(p) < 80]
        role = next((p for p in parts[1:] if p not in locs and not re.search(r"remote|onsite|on-site|hybrid|full[- ]time|part[- ]time|\$|visa|https?:", p, re.I)), "")
        if not (locs or remote):
            continue
        out.append({"t": role[:120] or "Several roles", "o": parts[0][:60], "u": f"https://news.ycombinator.com/item?id={c.get('id')}",
                    "l": locs[:4], "w": "remote" if remote else "", "pay": None, "d": when, "x": ""})
    log(f"  HN who is hiring ({story.get('title', '')[:40]}): {len(out)} postings, {len(links)} links")
    return out, links


def muse(log=print, pages=20):
    out = []
    for page in range(pages):
        try:
            d = net.get_json(f"https://www.themuse.com/api/public/jobs?page={page}", robots=False, tries=1)
        except Exception as e:
            if page == 0:
                log(f"  The Muse: skipped ({type(e).__name__}; the public API is unavailable)")
            break
        for j in d.get("results") or []:
            locs = [l.get("name", "") for l in j.get("locations") or []]
            remote = any("remote" in l.lower() or "flexible" in l.lower() for l in locs)
            out.append({"t": j.get("name", ""), "o": (j.get("company") or {}).get("name", ""),
                        "u": (j.get("refs") or {}).get("landing_page", ""), "l": [l for l in locs if "remote" not in l.lower()],
                        "w": "remote" if remote else "", "pay": None, "d": (j.get("publication_date") or "")[:10], "x": ""})
        if page + 1 >= int(d.get("page_count") or 0):
            break
    if out:
        log(f"  The Muse: {len(out)} postings")
    return out


SOURCES = {  # id -> (label shown in the app, attribution)
    "usajobs": ("Federal jobs (USAJOBS)", {"name": "USAJOBS", "link": "https://www.usajobs.gov/",
                "note": "From USAJOBS (U.S. Office of Personnel Management). Siftwell is not operated or endorsed by OPM. Apply through the official announcement."}),
    "careeronestop": ("Jobs from CareerOneStop", {"name": "CareerOneStop", "link": "https://www.careeronestop.org/",
                      "note": "Job listings from CareerOneStop, sponsored by the U.S. Department of Labor.", "logo_required": True}),
    "schoolspring": ("School jobs (SchoolSpring)", {"name": "SchoolSpring", "link": "https://www.schoolspring.com/",
                     "note": "From SchoolSpring's public job search. Apply through the original posting."}),
    "hn": ("Hacker News: Who is hiring", {"name": "Hacker News", "link": "https://news.ycombinator.com/",
           "note": "From the monthly Ask HN: Who is hiring? thread. Each job links to the original comment."}),
    "muse": ("Jobs from The Muse", {"name": "The Muse", "link": "https://www.themuse.com/"}),
}


def today():
    return dt.date.today().isoformat()
