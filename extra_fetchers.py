"""Fetchers for non-standard career sites (Amazon, Phenom, Oracle HCM, iCIMS Jibe, ClearCompany, Rippling,
iCIMS classic, UKG/UltiPro, Paylocity, ADP Workforce Now)."""
import json, re, sys, html as _html, urllib.request, concurrent.futures as cf
from jobfinder import http_json, strip_html, J
import netsafe

def household_homes():
    """[((lat, lon, label), radius miles)]: every profile's home area, the same union the Workday location facets use.
    During a fetch that's jobfinder's CFG["homes"]; elsewhere (e.g. checking a new company) it is read from the profiles."""
    homes = list((getattr(_jf(), "CFG", None) or {}).get("homes") or [])
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
        if not jobs:
            c["_truncated"] = f"empty page at {off - 50} of {d.get('totalHits', 0)}"
            break

def f_oracle(c):
    off = 0
    while True:
        d = http_json(f'{c["base"]}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true'
                      f'&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={c["site"]},limit=25,offset={off},sortBy=POSTING_DATES_DESC')
        item = d["items"][0]
        reqs = item.get("requisitionList", [])
        for r in reqs:
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

def f_jibe(c):
    page = 1
    while True:
        d = http_json(f'{c["base"]}/api/jobs?page={page}&limit=100')
        for w in d.get("jobs", []):
            j = w.get("data", {})
            locs = [j.get("full_location") or j.get("location_name") or ", ".join(filter(None, [j.get("city"), j.get("state")]))]
            desc = strip_html(j.get("description", ""))
            yield J(c, j.get("title"), f'{c["base"]}/jobs/{j.get("slug")}', locs, "", None, desc,
                    (j.get("posted_date") or "")[:10], "", j.get("slug"))
        if page * 100 >= d.get("totalCount", 0):
            break
        page += 1

def f_clearcompany(c):
    d = http_json(c["url"])
    for j in d.get("results", []):
        desc = strip_html(j.get("description", ""))
        wp = "remote" if "remote" in (j.get("location") or "").lower() else ""
        url = j.get("url") or j.get("applyUrl") or c.get("board", "")
        yield J(c, j.get("positionTitle"), url, [j.get("location", "")], wp, None, desc,
                (j.get("postedDate") or "")[:10], j.get("departmentName", ""), j.get("id"))

def f_rippling(c):
    d = http_json(f'https://api.rippling.com/platform/api/ats/v1/board/{c["token"]}/jobs')
    for j in d:
        loc = (j.get("workLocation") or {}).get("label", "")
        yield J(c, j.get("name"), j.get("url"), [loc], "remote" if "remote" in loc.lower() else "", None, "",
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
            for lm in re.finditer(r'field-label">\s*Location[^<]*</span>\s*</dt>\s*<dd[^>]*>\s*<span[^>]*>\s*(.*?)\s*</span>', card, re.S):
                locs += [_icims_loc(x) for x in re.split(r"\s*\|\s*|\s*;\s*", strip_html(lm.group(1))) if x.strip()]
            if any(r[1] == jid for r in rows):
                continue
            rows.append((url, jid, title, locs)); new += 1
        m = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", strip_html(h))
        if not new or not m or int(m.group(1)) >= int(m.group(2)):
            break
        pr += 1

    def detail(r):
        url, jid, title, locs = r
        desc, posted, wp = "", "", ""
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
                    if (d.get("jobLocationType") or "").upper() == "TELECOMMUTE":
                        wp = "remote"
            except Exception:
                pass
        if not wp and any("remote" in (l or "").lower() for l in locs):
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

    def loc_of(l):
        a = l.get("Address") or {}
        city, st = a.get("City"), (a.get("State") or {}).get("Code")
        name = l.get("LocalizedName") or ""
        parts = [x for x in (city, st) if x]
        return (", ".join(parts) + (f" ({name})" if name and "remote" in name.lower() else "")) if parts else name

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
        wp = "remote" if any("remote" in (l or "").lower() for l in locs) else ""
        return J(c, title, url, locs, wp, None, desc, (o.get("PostedDate") or "")[:10], o.get("JobCategoryName") or "", o["Id"])
    with cf.ThreadPoolExecutor(6) as ex:
        yield from ex.map(detail, ops)

def f_paylocity(c):
    """Paylocity's JSON feed is often empty; the public board page embeds every job in window.pageData."""
    h = http_text(f'https://recruiting.paylocity.com/recruiting/jobs/All/{c["id"]}')
    m = re.search(r"window\.pageData\s*=\s*(\{.*?\});\s*\n", h, re.S)
    jobs = [j for j in (json.loads(m.group(1)).get("Jobs") or []) if not j.get("IsInternal")] if m else []

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
            wp = "remote" if any("remote" in (l or "").lower() for l in locs) else ""
            yield J(c, title, url, locs, wp, None, desc, (r.get("postDate") or "")[:10], "", rid)
        skip += 100
        if len(reqs) < 100:
            break

FETCHERS = {"icims": f_icims, "ukg": f_ukg, "paylocity": f_paylocity, "adp": f_adp, "amazon": f_amazon, "phenom": f_phenom, "oracle": f_oracle, "jibe": f_jibe,
            "clearcompany": f_clearcompany, "rippling": f_rippling}

import jsonld_fetcher
FETCHERS.update(jsonld_fetcher.FETCHERS)  # custom careers sites that publish schema.org JobPosting data
