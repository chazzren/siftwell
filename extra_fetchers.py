"""Fetchers for non-standard career sites (Amazon, Phenom, Oracle HCM, iCIMS Jibe, ClearCompany, Rippling,
iCIMS classic, UKG/UltiPro, Paylocity, ADP Workforce Now)."""
import json, re, sys, html as _html, urllib.request, concurrent.futures as cf
from jobfinder import http_json, strip_html, J, over_budget, budget_stop
import jobtext
import netsafe

def household_homes(whole_if_legacy=False):
    """[((lat, lon, label), radius miles)]: every profile's home area, the same union the Workday location facets use.
    During a fetch that's jobfinder's CFG["homes"]; elsewhere (e.g. checking a new company) it is read from the profiles."""
    cfg = getattr(_jf(), "CFG", None) or {}
    if whole_if_legacy and cfg.get("homes") and cfg.get("legacy_area"):
        return []   # someone in the household still uses the older fixed area: read big boards whole, as before
    homes = list(cfg.get("homes") or [])
    if not homes:
        try:
            import geo, people
            for pid in people.ids():
                z = str(people.settings(pid).get("home_zip") or "").strip()
                if z:
                    try:
                        homes.append((geo.geocode_home(z), float(people.settings(pid).get("radius_miles") or 35)))
                    except Exception:
                        pass
        except Exception:
            pass
    out = {}
    for h, r in homes:
        k = (round(h[0], 2), round(h[1], 2))
        out[k] = (h, max(r, out[k][1]) if k in out else r)
    return list(out.values())


def amazon_searches(c):
    """Amazon search parameters: the company's own normalized_location list if it has one; else one search per home
    area (lat/lon + radius) plus US remote ("Virtual Location") jobs, or just the remote search when no home is set."""
    if c.get("locations"):
        return [({"normalized_location[]": loc}, None) for loc in c["locations"]]
    out = [({"latitude": f"{h[0]:.4f}", "longitude": f"{h[1]:.4f}", "radius": f"{max(8, round(r * 1.609))}km", "loc_query": str(h[2])[:80]}, None)
           for h, r in household_homes()]
    out.append(({"base_query": "virtual location", "normalized_country_code[]": "USA"}, "virtual"))
    return out


def f_amazon(c):
    import urllib.parse
    seen = set()
    for params, must in amazon_searches(c):
        off = 0
        while True:
            q = "https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode({"offset": off, "result_limit": 100, "sort": "recent", **params})
            d = http_json(q)
            for j in d.get("jobs", []):
                if j["id"] in seen:
                    continue
                if must and must not in json.dumps([j.get("location"), j.get("locations"), j.get("normalized_location")]).lower():
                    continue  # (the remote search is a text search: keep only jobs at a "Virtual Location")
                seen.add(j["id"])
                locs = []
                for l in j.get("locations") or []:
                    try:
                        locs.append(json.loads(l).get("normalizedLocation", ""))
                    except Exception:
                        pass
                locs = locs or [j.get("normalized_location", "")]
                wp = "remote" if must or "virtual" in str(j.get("location") or "").lower() else ""
                desc = strip_html(" ".join(j.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications")))
                yield J(c, j.get("title"), "https://www.amazon.jobs" + j.get("job_path", ""), locs, wp, None, desc,
                        j.get("posted_date", ""), j.get("job_category", ""), j["id"])
            off += 100
            if off >= min(d.get("hits", 0), 3000):
                if d.get("hits", 0) > 3000:
                    c["_truncated"] = f"Amazon search stops at 3000 of {d.get('hits')}"
                break
            if not d.get("jobs"):
                c["_truncated"] = f"empty page at {off - 100} of {d.get('hits', 0)}"
                break

def f_phenom(c):
    off = 0
    while True:
        body = {"ddoKey": "refineSearch", "refNum": c["refnum"], "from": off, "size": 50, "jobs": True, "counts": True,
                "lang": "en_us", "deviceType": "desktop", "country": "us", "pageName": "search-results", "siteType": "external",
                "keywords": "", "global": True, "selected_fields": {}, "all_fields": [], "locationData": {}, "sortBy": "",
                "subsearch": "", "clearAll": False, "jdsource": "facets", "isSliderEnable": False, "pageId": "page20"}
        d = http_json(c["url"], body)["refineSearch"]
        jobs = d["data"]["jobs"]
        for j in jobs:
            locs = j.get("multi_location") or [j.get("location", "")]
            url = f'{c["url"].rsplit("/", 1)[0]}/us/en/job/{j.get("jobId")}'
            yield J(c, j.get("title"), url, locs, "", None, j.get("descriptionTeaser", ""),
                    (j.get("postedDate") or "")[:10], j.get("category", ""), j.get("jobId"))
        off += 50
        if off >= d.get("totalHits", 0):
            break
        if over_budget(c):
            budget_stop(c, f"listing postings ({off} of {d.get('totalHits', 0)})")
            break
        if not jobs:
            c["_truncated"] = f"empty page at {off - 50} of {d.get('totalHits', 0)}"
            break

ORACLE_ALL_MAX = 1500    # an Oracle board with more postings than this is searched by place instead of read whole

def oracle_searches(c, total):
    """How to read an Oracle board: whole when it is small; a big one (Dollar General lists 90,000 postings, JPMorgan
    and Albertsons thousands) by place: one search around each home (radius + 10 miles) plus the board's own Remote
    workplace type. Returns [(finder suffix, label)]; [("", "")] = everything."""
    if total <= ORACLE_ALL_MAX or c.get("all"):
        return [("", "")]
    homes = household_homes(True)
    if not homes:
        return [("", "")]
    out = [(f",latitude={h[0]:.4f},longitude={h[1]:.4f},radius={int(r) + 10},radiusUnit=MI", str(h[2])[:40]) for h, r in homes]
    out.append((",selectedWorkplaceTypesFacet=ORA_REMOTE", "remote"))
    return out

def f_oracle(c):
    root = (f'{c["base"]}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true'
            f'&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={c["site"]}')
    first = http_json(f"{root},limit=25,offset=0,sortBy=POSTING_DATES_DESC")
    total = (first.get("items") or [{}])[0].get("TotalJobsCount", 0)
    seen = set()
    for extra, label in oracle_searches(c, total):
        off = 0
        while True:
            d = first if (not extra and off == 0) else http_json(f"{root}{extra},limit=25,offset={off},sortBy=POSTING_DATES_DESC")
            item = d["items"][0]
            reqs = item.get("requisitionList", [])
            for r in reqs:
                if r["Id"] in seen:
                    continue
                seen.add(r["Id"])
                locs = [r.get("PrimaryLocation", "")] + [s.get("Name", "") for s in r.get("secondaryLocations") or []]
                wp = {"ORA_HYBRID": "hybrid", "ORA_REMOTE": "remote", "ORA_ON_SITE": "onsite"}.get(r.get("WorkplaceTypeCode") or "", "")
                yield J(c, r.get("Title"), f'{c["base"]}/en/sites/{c["site"]}/job/{r["Id"]}', locs, wp, None,
                        (r.get("ShortDescriptionStr") or ""), r.get("PostedDate", ""), "", r["Id"])
            off += 25
            if off >= item.get("TotalJobsCount", 0):
                break
            if not reqs:
                c["_truncated"] = f"empty page at {off - 25} of {item.get('TotalJobsCount', 0)}"
                break
            if over_budget(c):
                budget_stop(c, f"listing postings ({off} of {item.get('TotalJobsCount', 0)}{' near ' + label if label else ''})")
                return

JIBE_ALL_MAX = 1500      # a Jibe board with more postings than this is searched by place instead of read whole

def home_place(h):
    """"Columbus, OH" for a home (lat, lon, label): what a job site's own location search understands."""
    import geo
    label = str(h[2]) if len(h) > 2 else ""
    m = re.search(r"\((.+)\)", label)
    if not m and re.search(r",\s*[A-Z]{2}$", label):
        return label
    city = m.group(1).split(",")[0].strip() if m else label.split(",")[0].strip()
    st = geo.state_at(h[0], h[1])
    return f"{city}, {st}" if city and st and not city.isdigit() else None

def jibe_searches(c, total):
    """How to read a Jibe board: whole when it is small; a big one (Costco lists 19,000 postings) by place, one search
    around each home (radius + 10 miles). Returns the extra query parameters of each search; [{}] = everything."""
    if total <= JIBE_ALL_MAX or c.get("all"):
        return [{}]
    out = []
    for h, r in household_homes(True):
        place = home_place(h)
        if not place:
            return [{}]
        out.append({"location": place, "stretch": int(r) + 10, "stretchUnit": "MILES"})
    return out or [{}]

def f_jibe(c):
    import urllib.parse
    first = http_json(f'{c["base"]}/api/jobs?page=1&limit=100')
    seen = set()
    for extra in jibe_searches(c, first.get("totalCount", 0)):
        page = 1
        while True:
            d = first if (not extra and page == 1) else http_json(f'{c["base"]}/api/jobs?' + urllib.parse.urlencode({"page": page, "limit": 100, **extra}))
            new = 0
            for w in d.get("jobs", []):
                j = w.get("data", {})
                if j.get("slug") in seen:
                    continue
                seen.add(j.get("slug")); new += 1
                locs = [j.get("full_location") or j.get("location_name") or ", ".join(filter(None, [j.get("city"), j.get("state")]))]
                desc = strip_html(j.get("description", ""))
                yield J(c, j.get("title"), f'{c["base"]}/jobs/{j.get("slug")}', locs, "", None, desc,
                        (j.get("posted_date") or "")[:10], "", j.get("slug"))
            if page * 100 >= d.get("totalCount", 0) or not d.get("jobs"):
                break
            if over_budget(c):
                budget_stop(c, f"listing postings ({page * 100} of {d.get('totalCount', 0)})")
                return
            page += 1

def f_clearcompany(c):
    d = http_json(c["url"])
    for j in d.get("results", []):
        desc = strip_html(j.get("description", ""))
        wp = "remote" if jobtext.remote_label(j.get("location")) else ""
        url = j.get("url") or j.get("applyUrl") or c.get("board", "")
        yield J(c, j.get("positionTitle"), url, [j.get("location", "")], wp, None, desc,
                (j.get("postedDate") or "")[:10], j.get("departmentName", ""), j.get("id"))

def f_rippling(c):
    d = http_json(f'https://api.rippling.com/platform/api/ats/v1/board/{c["token"]}/jobs')
    for j in d:
        loc = (j.get("workLocation") or {}).get("label", "")
        yield J(c, j.get("name"), j.get("url"), [loc], "remote" if jobtext.remote_label(loc) else "", None, "",
                "", (j.get("department") or {}).get("label", ""), j.get("uuid"))


def _jf():
    """The running jobfinder module (it may be __main__), for the live title filter."""
    m = sys.modules.get("__main__")
    if m is not None and hasattr(m, "title_ok") and hasattr(m, "CFG"):
        return m
    import jobfinder
    return jobfinder

def wanted(c, title):
    """Same title test the pipeline applies; used to skip detail fetches for jobs that would be dropped anyway."""
    jf = _jf()
    if over_budget(c):
        budget_stop(c, listed=True)
        return False   # (this employer's time is used up: the posting is stored from its list row, the text comes next time)
    if str(c.get("name") or "").startswith("Employer") and c.get("_name_sample", 0) < 6:
        # a board known only by a code ("Employer in Columbus OH (ADP 0330de)"): read a few postings whatever their
        # titles, so the employer's real name can be learned from them (names.learn)
        c["_name_sample"] = c.get("_name_sample", 0) + 1
        return True
    try:
        return jf.title_ok(title) or any(jf.target_ok(st, c.get("ai_track"), title) for st in jf.CFG.get("targets", []))
    except Exception:
        return True

def http_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"})
    for i in range(3):
        try:
            with netsafe.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except netsafe.UnsafeURL:
            raise
        except Exception:
            if i == 2:
                raise

def _icims_loc(s):
    """'US-TX-Austin' -> 'Austin, TX'; 'US-OH-Columbus | US-OH-Dayton' handled by the caller."""
    s = _html.unescape(s).strip()
    m = re.match(r"^(?:US|USA)-([A-Z]{2})-(.+)$", s)
    return f"{m.group(2).strip()}, {m.group(1)}" if m else s

def _icims_workplace(card):
    """The workplace an iCIMS job card states in its header fields ("Work Location: In Person", "Remote: No",
    "Location Type: Hybrid", "Workplace Type: Remote"); "" when the card has no such field."""
    for m in re.finditer(r'field-label">\s*([^<]{2,40}?)\s*</span>\s*(?:</dt>\s*<dd[^>]*>\s*)?<span[^>]*>\s*([^<]{1,60}?)\s*</span>', card, re.S):
        label, val = m.group(1).strip().lower(), _html.unescape(m.group(2)).strip()
        if re.fullmatch(r"remote(?:\s*(?:work|eligible|status|option))?\??", label):
            v = val.lower()
            return "remote" if v in ("yes", "y", "true", "remote", "fully remote") else "hybrid" if "hybrid" in v or "partial" in v \
                else "onsite" if v in ("no", "n", "false", "none", "on-site", "onsite") else jobtext.workplace_label("remote " + val, typed=True)
        if re.fullmatch(r"(?:work\s*(?:place|location)(?:\s*type)?|workplace|location type|work type|work arrangement|work model|work style)", label):
            wp = jobtext.workplace_label(val, typed=True)
            if wp:
                return wp
    return ""

def f_icims(c):
    base = c["base"].rstrip("/")
    rows, pr = [], 0
    while pr < 60:
        h = http_text(f"{base}/jobs/search?ss=1&in_iframe=1&pr={pr}")
        cards = re.split(r'<li class="iCIMS_JobCardItem', h)[1:]
        if not cards:
            # older template: table rows
            cards = re.split(r'<div class="row"[^>]*>\s*<div class="col-xs-12 title"', h)[1:]
        new = 0
        for card in cards:
            m = re.search(r'href="(https?://[^"]+/jobs/(\d+)/[^"]*)"[^>]*>(?:.|\n)*?<h3[^>]*>\s*(.*?)\s*</h3>', card)
            if not m:
                continue
            url, jid, title = m.group(1).split("?")[0], m.group(2), _html.unescape(re.sub(r"\s+", " ", m.group(3)))
            title = re.sub(r"\s*\((?:Job ID|Req(?:uisition)? ?#?)[^)]*\)\s*$", "", title, flags=re.I).strip()
            locs = []
            # ("Location", "Locations", "Job Locations": the label differs by board)
            for lm in re.finditer(r'field-label">\s*(?:Job\s+)?Location[^<]*</span>\s*</dt>\s*<dd[^>]*>\s*<span[^>]*>\s*(.*?)\s*</span>', card, re.S):
                locs += [_icims_loc(x) for x in re.split(r"\s*\|\s*|\s*;\s*", strip_html(lm.group(1))) if x.strip()]
            if any(r[1] == jid for r in rows):
                continue
            rows.append((url, jid, title, locs, _icims_workplace(card))); new += 1
        m = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", strip_html(h))
        if not new or not m or int(m.group(1)) >= int(m.group(2)):
            break
        if over_budget(c):
            budget_stop(c, f"listing postings (page {m.group(1)} of {m.group(2)})")
            break
        pr += 1

    def detail(r):
        url, jid, title, locs, wp = r
        locs = list(locs)
        desc, posted = "", ""
        if wanted(c, title):
            try:
                h = http_text(url + "?in_iframe=1")
                m = re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
                if m:
                    d = json.loads(m.group(1))
                    desc = strip_html(d.get("description", ""))
                    posted = (d.get("datePosted") or "")[:10]
                    if not locs:
                        for jl in d.get("jobLocation") or []:
                            a = jl.get("address") or {}
                            locs.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion")) if x))
                    # iCIMS marks every posting TELECOMMUTE, in-person jobs with a street address included: the
                    # board's own "Work Location" / "Remote" field decides, then a posting with no street address
                    if not wp and jobtext.telecommute(d):
                        wp = "remote"
            except Exception:
                pass
        if not wp and any(jobtext.remote_label(l) for l in locs):
            wp = "remote"
        return J(c, title, url, locs, wp, None, desc, posted, "", jid)
    with cf.ThreadPoolExecutor(6) as ex:
        yield from ex.map(detail, rows)

UKG_BODY = {"opportunitySearch": {"Top": 100, "Skip": 0, "QueryString": "", "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}], "Filters": []},
            "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [], "Skills": [], "hasNoLicenses": False, "SkippedSkills": []}}

def f_ukg(c):
    root = f'https://{c.get("host") or "recruiting.ultipro.com"}/{c["tenant"]}/JobBoard/{c["board"]}'
    ops, skip = [], 0
    while skip < 3000:
        body = json.loads(json.dumps(UKG_BODY)); body["opportunitySearch"]["Skip"] = skip
        d = http_json(f"{root}/JobBoardView/LoadSearchResults", body)
        got = d.get("opportunities") or []
        ops += got
        skip += 100
        if len(got) < 100:
            break
        if over_budget(c):
            budget_stop(c, f"listing postings ({skip} of {d.get('totalCount') or '?'})")
            break

    def loc_of(l):
        a = l.get("Address") or {}
        city, st = a.get("City"), (a.get("State") or {}).get("Code")
        name = l.get("LocalizedName") or ""
        parts = [x for x in (city, st) if x]
        return (", ".join(parts) + (f" ({name})" if name and jobtext.remote_label(name) else "")) if parts else name

    def detail(o):
        title = o.get("Title", "")
        locs = [loc_of(l) for l in o.get("Locations") or []]
        url = f'{root}/OpportunityDetail?opportunityId={o["Id"]}'
        desc = strip_html(o.get("BriefDescription") or "")
        if wanted(c, title):
            try:
                h = http_text(url)
                m = re.search(r"CandidateOpportunityDetail\((\{.*?\})\);?\s*\n", h, re.S)
                if m:
                    d = json.loads(m.group(1))
                    desc = strip_html(d.get("Description") or "") or desc
            except Exception:
                pass
        wp = "remote" if any(jobtext.remote_label(l) for l in locs) else ""
        return J(c, title, url, locs, wp, None, desc, (o.get("PostedDate") or "")[:10], o.get("JobCategoryName") or "", o["Id"])
    with cf.ThreadPoolExecutor(6) as ex:
        yield from ex.map(detail, ops)

def f_paylocity(c):
    """Paylocity's JSON feed is often empty; the public board page embeds every job in window.pageData."""
    h = http_text(f'https://recruiting.paylocity.com/recruiting/jobs/All/{c["id"]}')
    m = re.search(r"window\.pageData\s*=\s*(\{.*?\});\s*\n", h, re.S)
    jobs = [j for j in (json.loads(m.group(1)).get("Jobs") or []) if not j.get("IsInternal")] if m else []
    tm = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I)
    if tm:
        c["_board_title"] = _html.unescape(re.sub(r"\s+", " ", tm.group(1))).strip()[:120]   # (names.learn reads it)

    def detail(j):
        jl = j.get("JobLocation") or {}
        loc = ", ".join(x for x in (jl.get("City"), jl.get("State")) if x) or j.get("LocationName", "")
        wp = "remote" if j.get("IsRemote") else ""
        url = f'https://recruiting.paylocity.com/Recruiting/Jobs/Details/{j["JobId"]}'
        title = re.sub(r",?\s*\(\d+\)\s*", " ", j.get("JobTitle") or "").strip()
        desc = strip_html(j.get("Description") or "")
        if wanted(c, title):
            try:
                d = http_text(url)
                mm = re.search(r'<script type="application/ld\+json">(.*?)</script>', d, re.S)
                if mm:
                    desc = strip_html(json.loads(mm.group(1)).get("description", "")) or desc
                else:
                    mm = re.search(r'<div class="job-preview-details">(.*?)<div class="job-preview-footer', d, re.S)
                    desc = strip_html(mm.group(1)) if mm else desc
            except Exception:
                pass
        return J(c, title, url, [loc], wp, None, desc, (j.get("PublishedDate") or "")[:10], j.get("HiringDepartment") or "", j["JobId"])
    with cf.ThreadPoolExecutor(6) as ex:
        yield from ex.map(detail, jobs)

def f_adp(c):
    base = "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
    skip = 0
    while skip < 2000:
        d = http_json(f'{base}?cid={c["cid"]}&lang=en_US&$top=100&$skip={skip}')
        reqs = d.get("jobRequisitions") or []
        for r in reqs:
            title = r.get("requisitionTitle") or ""
            locs = []
            for l in r.get("requisitionLocations") or []:
                a = l.get("address") or {}
                sub = (a.get("countrySubdivisionLevel1") or {}).get("codeValue")
                locs.append(", ".join(x for x in (a.get("cityName"), sub) if x) or (l.get("nameCode") or {}).get("shortName", ""))
            rid = r.get("itemID") or r.get("requisitionID") or ""
            url = f'https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={c["cid"]}&jobId={rid}'
            desc = ""
            if wanted(c, title):
                try:
                    dd = http_json(f'{base}/{rid}?cid={c["cid"]}&lang=en_US')
                    desc = strip_html(dd.get("requisitionDescription") or "")
                except Exception:
                    pass
            wp = "remote" if any(jobtext.remote_label(l) for l in locs) else ""
            yield J(c, title, url, locs, wp, None, desc, (r.get("postDate") or "")[:10], "", rid)
        skip += 100
        if len(reqs) < 100:
            break
        if over_budget(c):
            budget_stop(c, f"listing postings ({skip})")
            break

FETCHERS = {"icims": f_icims, "ukg": f_ukg, "paylocity": f_paylocity, "adp": f_adp, "amazon": f_amazon, "phenom": f_phenom, "oracle": f_oracle, "jibe": f_jibe,
            "clearcompany": f_clearcompany, "rippling": f_rippling}

import jsonld_fetcher
FETCHERS.update(jsonld_fetcher.FETCHERS)  # custom careers sites that publish schema.org JobPosting data
