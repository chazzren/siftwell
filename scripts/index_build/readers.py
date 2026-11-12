"""Read one job board's public feed and summarise where it hires: no job text is kept.

read(cfg) -> {"name": board's own name or None, "jobs": open postings, "remote": US-remote postings,
              "locs": {location label: postings}, "sample": True when only part of a big board was read}

Greenhouse, Lever, Ashby and Workday have light readers here (one or two requests per board: Greenhouse's list
without job text, Workday's location facets; a Workday board without city facets is sampled across its whole list).
Every other system uses the app's own reader from jobfinder.FETCHERS, stopped after CAP postings or GENERIC_SECS (so a
new system the app learns to read is covered without changes here). A board that was only partly read is marked
"sample": the directory publishes it as "maybe near" in every state where the sample saw it, and the app keeps it only
if its first full fetch finds jobs near the person.

workday_sites(tenant, wd): every career site of a Workday tenant, from the "Sitemap:" lines of its robots.txt (one GET).
board_name(cfg): the employer's name from its board page, for systems whose address is only a code (one GET)."""
import re, threading, time, urllib.parse

from . import net

CAP = 1000           # postings looked at per board through the app's readers (most boards are read whole)
GENERIC_SECS = 90    # time limit per board through the app's readers
WD_PAGES = 15        # Workday list pages (20 each) when the board has no city-level location facet, spread over the list
WD_LIST_MAX = 2000   # Workday stops paging here


class Skip(Exception):
    pass


def _nonus(label):
    import jobfinder
    l = " " + label.lower() + " "
    return any(c in l for c in jobfinder.NON_US)


def _remote(label, wp=""):
    l = label.lower()
    return ("remote" in l or "anywhere" in l or wp == "remote") and not _nonus(label)


def _summ(rows, name=None, sample=False):
    """rows: [(locations list, workplace, country)] -> summary."""
    locs, remote, jobs = {}, 0, 0
    for labels, wp, country in rows:
        if country and str(country).strip().lower() not in ("us", "usa", "united states", "united states of america", "u.s.", ""):
            continue
        labels = [l.strip() for l in labels if l and l.strip()]
        if labels and all(_nonus(l) for l in labels):
            continue
        jobs += 1
        if wp == "remote" or any(_remote(l) for l in labels):
            remote += 1
        for l in labels:
            if not _nonus(l) and "remote" not in l.lower():
                locs[l[:120]] = locs.get(l[:120], 0) + 1
    return {"name": name, "jobs": jobs, "remote": remote, "locs": locs, "sample": sample}


def greenhouse(c):
    t = urllib.parse.quote(c["token"])
    d = net.get_json(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs")
    rows = []
    for j in d.get("jobs", []):
        locs = [(j.get("location") or {}).get("name", "")]
        locs = [p.strip() for l in locs if l for p in re.split(r"\s*[|;]\s*", l)]
        rows.append((locs, "", ""))
    name = None
    if rows:
        try:
            name = net.get_json(f"https://boards-api.greenhouse.io/v1/boards/{t}").get("name")
        except Exception:
            pass
    return _summ(rows, name)


def lever(c):
    d = net.get_json(f"https://api.lever.co/v0/postings/{urllib.parse.quote(c['token'])}?mode=json")
    rows = []
    for j in d if isinstance(d, list) else []:
        cat = j.get("categories") or {}
        wp = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}.get(j.get("workplaceType") or "", "")
        rows.append((cat.get("allLocations") or [cat.get("location", "")], wp, j.get("country") or ""))
    return _summ(rows)


def ashby(c):
    d = net.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(c['token'])}")
    rows = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        wp = "remote" if (j.get("isRemote") or (j.get("workplaceType") or "").lower() == "remote") else ""
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        rows.append((locs, wp, country if country not in ("United States", "USA", "US") else ""))
    return _summ(rows)


def _wd_api(c):
    base = f'https://{c["host"]}' if c.get("host") else f'https://{c["tenant"]}.{c["wd"]}.myworkdayjobs.com'
    return base, f'{base}/wday/cxs/{c["tenant"]}/{c["site"]}'


def _wd_facets(facets):
    flat = []
    def walk(fs):
        for f in fs or []:
            vals = f.get("values") or []
            if vals and isinstance(vals[0], dict) and "facetParameter" in vals[0]:
                walk(vals)
            else:
                flat.append(f)
    walk(facets)
    return flat


def workday(c):
    base, api = _wd_api(c)
    first = net.get_json(api + "/jobs", {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}})
    if not net.robots_ok(base + f'/{c["site"]}'):
        raise net.Blocked("robots.txt forbids the career site")
    facets = _wd_facets(first.get("facets"))
    total = first.get("total", 0)
    country, cities, remote = None, None, 0
    for f in facets:
        p = f.get("facetParameter", "")
        pl = p.lower()
        if "country" in pl:
            country = (p, next((v for v in f.get("values", []) if "united states" in v.get("descriptor", "").lower()), None))
        elif pl in ("locations", "locationmaingroup", "location", "primarylocation") or ("location" in pl and not any(x in pl for x in ("country", "region", "state", "province", "hierarchy"))):
            if cities is None or len(f.get("values", [])) > len(cities):
                cities = f.get("values", [])
        elif "remote" in pl:
            remote = sum(v.get("count", 0) for v in f.get("values", []) if "remote" in v.get("descriptor", "").lower())
    us_total = country[1]["count"] if country and country[1] else (0 if country else total)
    name = None
    rows_summary = None
    if cities:
        locs = {}
        for v in cities:
            lab = v.get("descriptor", "")
            if lab and not _nonus(lab) and "remote" not in lab.lower():
                locs[lab[:120]] = v.get("count", 0)
        rows_summary = {"name": None, "jobs": us_total, "remote": remote, "locs": locs, "sample": False}
    sample_path = None
    if rows_summary is None or not rows_summary["locs"]:
        applied = {country[0]: [country[1]["id"]]} if country and country[1] else {}
        rows, n = [], us_total
        reach = min(n, WD_LIST_MAX)
        pages = max(1, min(WD_PAGES, -(-reach // 20)))
        # pages spread evenly over the whole list (not just the newest 200 postings), so every region shows up
        offsets = sorted({min(max(0, reach - 20), round(i * max(0, reach - 20) / max(1, pages - 1)) // 20 * 20) for i in range(pages)}) if pages > 1 else [0]
        for off in offsets:
            if off == 0 and not applied:
                page = first
            else:
                page = net.get_json(api + "/jobs", {"limit": 20, "offset": off, "searchText": "", "appliedFacets": applied})
            for p in page.get("jobPostings", []):
                rt = (p.get("remoteType") or "").lower()
                rows.append(([p.get("locationsText", "")], "remote" if "remote" in rt else "", ""))
                sample_path = sample_path or p.get("externalPath")
            if not page.get("jobPostings"):
                break
        s = _summ(rows, None, sample=n > len(rows))
        if s["sample"] and rows:     # scale the sample up to the board's US total
            k = n / max(1, len(rows))
            s["locs"] = {l: max(1, round(v * k)) for l, v in s["locs"].items()}
            s["remote"] = round(s["remote"] * k)
        s["jobs"] = n
        rows_summary = s
    else:
        sample_path = next((p.get("externalPath") for p in first.get("jobPostings", []) if p.get("externalPath")), None)
        if country and country[1]:      # (the name comes from a US posting: others name a foreign legal entity)
            try:
                us = net.get_json(api + "/jobs", {"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {country[0]: [country[1]["id"]]}})
                sample_path = next((p.get("externalPath") for p in us.get("jobPostings", []) if p.get("externalPath")), sample_path)
            except Exception:
                pass
    if sample_path and rows_summary["jobs"]:
        try:
            d = net.get_json(api + sample_path)
            name = ((d.get("hiringOrganization") or {}).get("name") or "").strip() or None
        except Exception:
            pass
    rows_summary["name"] = name
    return rows_summary


def workday_sites(tenant, wd):
    """Every career site of a Workday tenant, from its robots.txt ("Sitemap: https://<host>/<Site>/siteMap.xml").
    [] when it lists none; raises when the host can't be reached."""
    host = f"{tenant}.{wd}.myworkdayjobs.com"
    txt = net.get_text(f"https://{host}/robots.txt", robots=False, tries=2, timeout=25, cap=200_000)
    return parse_workday_robots(txt, host)


def parse_workday_robots(txt, host):
    from .systems import bad_workday_site
    out = []
    for m in re.finditer(r"(?im)^\s*Sitemap:\s*https?://([^/\s]+)/([A-Za-z0-9_-]+)/siteMap\.xml", txt or ""):
        if m.group(1).lower() == host.lower() and not bad_workday_site(m.group(2)) and m.group(2) not in out:
            out.append(m.group(2))
    return out


def workday_find_site(c):
    """A Workday tenant known only by its host (from a certificate): try the usual career-site names."""
    for site in ("External", "Careers", c["tenant"], c["tenant"] + "careers", "External_Careers", "en-US/External"):
        if "/" in site:
            continue
        cc = dict(c, site=site)
        try:
            d = net.get_json(_wd_api(cc)[1] + "/jobs", {"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}}, tries=1)
            if d.get("total", 0) > 0:
                return cc
        except Exception:
            continue
    return None


def jsonld(c):
    import jsonld_fetcher
    rows, name = [], None
    cc = dict(c, name="directory")
    for p in jsonld_fetcher.fetch_postings(cc, cap=40, sample=True):
        rows.append((p.get("locations") or [], p.get("workplace") or "", ""))
        name = name or p.get("org")
    s = _summ(rows, name, sample=cc.get("_url_count", 0) > len(rows))
    n = max(cc.get("_url_count", 0), len(rows))
    if s["sample"] and rows:
        k = n / len(rows)
        s["locs"] = {l: max(1, round(v * k)) for l, v in s["locs"].items()}
        s["jobs"], s["remote"] = round(s["jobs"] * k), round(s["remote"] * k)
    return s


def generic(c):
    import jobfinder
    if not jobfinder.FETCHERS.get("icims"):
        jobfinder.load_extra()
    fx = jobfinder.FETCHERS.get(c["ats"])
    if not fx:
        raise Skip(f"no reader for {c['ats']}")
    from .systems import careers_url
    u = careers_url(c)   # (the app's readers don't all check robots.txt: the builder checks the board's own address first)
    if u.startswith("http") and not net.robots_ok(u):
        raise net.Blocked("robots.txt forbids the job board")
    rows, err, sample = [], [], [False]
    def run():
        try:
            for j in fx(dict(c, name="directory")):
                rows.append((j.get("locations") or [], j.get("workplace") or "", ""))
                if len(rows) >= CAP:
                    sample[0] = True
                    break
        except Exception as e:
            err.append(e)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(GENERIC_SECS)
    if t.is_alive():
        sample[0] = True
    if err and not rows:
        raise err[0]
    return _summ(list(rows), None, sample=sample[0])


# ---------------------------------------------------------------- names for boards known only by a code
GENERIC_TITLE = re.compile(r"(?i)^(careers?( (page|site|center|portal|opportunities))?|jobs?|job (opportunities|openings|board|listings?|search)|"
                           r"current (openings|opportunities)|open (positions|roles|jobs)|recruit(ment|ing)|bamboohr|dayforce( jobs)?|home|apply|"
                           r"employment( opportunities)?|work (with|for) us|join (us|our team)|search( results| jobs)?|welcome|"
                           r"candidate (portal|experience)|external|ultipro|ukg( pro)?|paylocity|adp|workforce now|icims|taleo|"
                           r"error|page not found|not found|access denied|sign in|log ?in|untitled|loading(\.\.\.)?|.{0,2})$")


def name_from_title(title):
    """"Woodmans Inc - Job Opportunities" -> "Woodmans Inc"; "Careers at Acme" -> "Acme"; None for generic titles."""
    import html as _html
    t = re.sub(r"\s+", " ", _html.unescape(title or "")).strip()
    for part in re.split(r"\s+[-|\u2013\u2014:\u00b7]\s+|\s*\|\s*", t):
        part = part.strip(" -|:")
        part = re.sub(r"(?i)^(careers?|jobs?|job openings|job opportunities|opportunities|employment|work|current openings) (at|with|@|for)\s+", "", part)
        part = re.sub(r"(?i)\s+(careers?( (page|site|center|portal))?|jobs?|job (openings|opportunities|board)|career opportunities|employment)$", "", part).strip()
        if len(part) >= 2 and not GENERIC_TITLE.match(part) and len(part) <= 80:
            return part
    return None


def board_name(c):
    """The employer's name as its board page gives it (one GET; robots.txt is respected). None when the page doesn't
    say. Dayforce: the page's ClientName; UKG: the employer's own site linked from the header logo (its host name);
    everything else: the page title / og:title without the generic words."""
    from .systems import careers_url
    import company_add
    u = careers_url(c)
    if not u.startswith("http") or c.get("ats") in ("adp", "greenhouse", "lever", "ashby", "workday"):
        return None     # (ADP's page is an empty shell; the others have their own name sources)
    page = net.get_text(u, tries=1, timeout=25, cap=3_000_000)
    if c.get("ats") == "dayforce":
        m = re.search(r'ClientName\\?"\s*:\s*\\?"([^"\\]{2,80})', page)
        return m.group(1).strip() if m else None
    if c.get("ats") == "ukg":
        m = re.search(r"logoHref:\s*['\"](https?://[^'\"]+)['\"]", page)
        return (company_add.host_label({}, m.group(1)) or None) if m else None
    for rx in (r'<meta[^>]+property=["\']og:site_name["\'][^>]*content=["\']([^"\']+)', r"<title[^>]*>(.*?)</title>",
               r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)'):
        m = re.search(rx, page, re.S | re.I)
        n = name_from_title(m.group(1)) if m else None
        if n:
            return n
    return None


LIGHT = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday, "jsonld": jsonld}


def read(c):
    from .systems import BY_ID
    s = BY_ID.get(c.get("ats"))
    if s is not None and not s.read:
        raise Skip(f"{c['ats']} is not read by the directory (robots.txt)")
    fn = LIGHT.get(c["ats"], generic)
    t0 = time.time()
    out = fn(c)
    out["secs"] = round(time.time() - t0, 1)
    return out
