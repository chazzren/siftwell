"""Read one job board's public feed and summarise where it hires: no job text is kept.

read(cfg) -> {"name": board's own name or None, "jobs": open postings, "remote": US-remote postings,
              "locs": {location label: postings}, "sample": True when only part of a big board was read}

Greenhouse, Lever, Ashby and Workday have light readers here (one or two requests per board: Greenhouse's list
without job text, Workday's location facets). Every other system uses the app's own reader from jobfinder.FETCHERS,
stopped after CAP postings (so a new system the app learns to read is covered without changes here)."""
import re, threading, time, urllib.parse

from . import net

CAP = 150            # postings looked at per board through the app's readers (enough to see where it hires)
GENERIC_SECS = 90    # time limit per board through the app's readers
WD_PAGES = 10        # Workday list pages (20 each) when the board has no city-level location facet


class Skip(Exception):
    pass


def _nonus(label):
    import jobfinder
    return jobfinder.is_foreign(label)   # whole words; "Dublin, OH" and "Indianapolis, IN" stay in the US


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
        rows, off, n = [], 0, us_total
        page = first if not applied else None
        for _ in range(WD_PAGES):
            if page is None:
                page = net.get_json(api + "/jobs", {"limit": 20, "offset": off, "searchText": "", "appliedFacets": applied})
            for p in page.get("jobPostings", []):
                rt = (p.get("remoteType") or "").lower()
                rows.append(([p.get("locationsText", "")], "remote" if "remote" in rt else "", ""))
                sample_path = sample_path or p.get("externalPath")
            off += 20
            if off >= min(n, WD_PAGES * 20) or not page.get("jobPostings"):
                break
            page = None
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
