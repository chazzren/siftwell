"""Offline tests for ats_sap_taleo (SAP SuccessFactors + Taleo) with saved sample responses in scripts/fixtures_sap_taleo/.
Run: SIFTWELL_FORBID_CLAUDE=1 python -X utf8 scripts/test_sap_taleo.py"""
import json, os, sys, urllib.error, urllib.parse
os.environ.setdefault("SIFTWELL_FORBID_CLAUDE", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ats_sap_taleo as A
import company_add, extra_fetchers, netsafe

FX = os.path.join(HERE, "fixtures_sap_taleo")
def fx(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

extra_fetchers.wanted = lambda c, t: True      # (no job-filter config outside a running board: fetch every posting's text)
CO = {"name": "Example", "tier": "national", "sector": "Test"}
calls = []
def fake(routes):
    """Replace A._open with a router: routes = [(substring, fn(url, data) -> bytes | HTTPError)]."""
    def _open(url, data=None, headers=None, opener=None, timeout=45, tries=3):
        calls.append((url, data))
        for sub, fn in routes:
            if sub in url:
                r = fn(url, data)
                if isinstance(r, Exception):
                    raise r
                return r, url
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    A._open = _open

# ---- locations
check("SF US label", A.sf_location("Spencer, IN, US, 47460") == "Spencer, IN")
check("SF remote US", A.sf_location("Remote, US") == "Remote")
check("SF non-US marked", A.sf_location("Penang, MY") == "Penang, MY europe")
check("SF bare DE is Germany, not Delaware", A.sf_location("Asbach, DE").endswith("europe"))
check("SF bare states only when the site never names a country", A.sf_location("Dallas, TX", True) == "Dallas, TX" and A.sf_location("Dallas, TX").endswith("europe"))
check("SF US state name", A.sf_location("Austin, Texas, United States") == "Austin, TX")
check("Taleo ST-City", A.taleo_location("OH-Fairfield") == "Fairfield, OH")
check("Taleo US-ST-City", A.taleo_location("US-NY-Buffalo") == "Buffalo, NY")
check("Taleo USA-State-City", A.taleo_location("USA-Texas-Midland") == "Midland, TX")
check("Taleo State-City", A.taleo_location("Kansas-Topeka") == "Topeka, KS")
check("Taleo hyphenated city", A.taleo_location("US-NC-Winston-Salem") == "Winston-Salem, NC")
check("Taleo non-US marked", A.taleo_location("CA-ON-Toronto") == "CA-ON-Toronto europe")
check("Taleo multiple locations dropped", A.taleo_locations('["Multiple Locations"]') == [])
check("Taleo legacy multi list", A.taleo_locations("Kansas-Topeka, Missouri-Kansas City") == ["Topeka, KS", "Kansas City, MO"])
check("dates", A._iso("Nov 9, 2026") == "2026-11-09" and A._iso("Tue Nov 10 08:00:00 UTC 2026") == "2026-11-10" and A._iso("2026-03-04T10:00") == "2026-03-04")

# ---- SuccessFactors: RSS feed
c = dict(CO, ats="successfactors", base="https://jobs.example.com")
fake([("/sitemap.xml", lambda u, d: fx("sf_feed.xml"))])
jobs = list(A.f_successfactors(dict(c)))
check("feed: 4 postings", len(jobs) == 4)
j = jobs[0]
check("feed: title loses the appended location", j["title"] == "Field Technician")
check("feed: id Company::<id>, url", j["id"] == "Example::1444034200" and j["url"].startswith("https://jobs.example.com/job/"))
check("feed: location City, ST", j["locations"] == ["Kemmerer, WY"])
check("feed: text decoded, no markup", "Keep the plant running & safe." in j["desc"] and "<" not in j["desc"] and "&lt;" not in j["desc"])
check("feed: dept", j["dept"] == "Operations")
check("feed: remote", jobs[2]["workplace"] == "remote" and jobs[2]["locations"] == ["Remote"])
check("feed: non-US marked", jobs[1]["locations"] == ["Penang, MY europe"] and jobs[3]["locations"] == ["Asbach, DE europe"])
import jobfinder
kept = [x["title"] for x in jobs if jobfinder.prepare_listing(dict(x, salary=None), c)]
check("feed: US-only after prepare_listing (remote-US kept)", kept == ["Field Technician", "Remote Account Manager"])
p = jobfinder.prepare_listing(dict(jobs[0], salary=None), c)
check("feed: salary parsed from the text", p["salary_min"] == 52000 and p["salary_max"] == 68000)
check("verify via feed: count + employer", A.sf_count("https://jobs.example.com") == (4, "Example Corp"))

# ---- SuccessFactors: search pages (no feed)
def search(u, d):
    return fx("sf_search.html") if "startrow=0" in u else fx("sf_search2.html")
def job(u, d):
    return fx("sf_job.html")
fake([("/sitemap.xml", lambda u, d: urllib.error.HTTPError(u, 404, "nf", {}, None)), ("/search/", search), ("/job/", job)])
c2 = dict(CO, ats="successfactors", base="https://jobs.example.com")
jobs = list(A.f_successfactors(c2))
check("search: 3 rows over 2 pages", len(jobs) == 3 and not c2.get("_truncated"))
check("search: title/url/id/date/location", (jobs[0]["title"], jobs[0]["id"], jobs[0]["posted"], jobs[0]["locations"]) ==
      ("Senior Pricing Analyst - Aftermarket", "Example::1439264400", "2026-11-10", ["Maumee, OH"]))
check("search: html entity in title", jobs[1]["title"] == "Analista & Planejamento")
check("search: description from the posting page", jobs[0]["desc"].startswith("Example is a global leader.") and "SQL & Excel" in jobs[0]["desc"] and "Apply now" not in jobs[0]["desc"])
check("search: non-US marked", jobs[1]["locations"] == ["Sorocaba, BR europe"])
fake([("/sitemap.xml", lambda u, d: urllib.error.HTTPError(u, 404, "nf", {}, None)), ("/search/", search), ("/job/", lambda u, d: urllib.error.HTTPError(u, 500, "x", {}, None))])
A.PAUSE = 0
jobs = list(A.f_successfactors(dict(c2)))
check("search: a failed posting page leaves a partial row", all(x.get("_partial") for x in jobs) and len(jobs) == 3)
fake([("/sitemap.xml", lambda u, d: urllib.error.HTTPError(u, 404, "nf", {}, None)), ("/search/", lambda u, d: fx("sf_search.html") if "startrow=0" in u else b"<html></html>"), ("/job/", job)])
c3 = dict(c2)
jobs = list(A.f_successfactors(c3))
check("search: a page that comes back empty early signals partial (capped)", len(jobs) == 2 and "empty page" in (c3.get("_truncated") or ""))
fake([("/sitemap.xml", lambda u, d: urllib.error.HTTPError(u, 403, "forbidden", {}, None))])
try:
    list(A.f_successfactors(dict(c2)))
    check("a blocking site (403) is an error, not worked around", False)
except urllib.error.HTTPError:
    check("a blocking site (403) is an error, not worked around", len(calls) and True)

# ---- Taleo: REST (faceted) career section
t = dict(CO, ats="taleo", host="cinfin.taleo.net", section="ex")
def rest(u, d):
    body = json.loads(d)
    return fx("taleo_rest.json") if body["pageNo"] == 1 else b'{"requisitionList":[],"pagingData":{"totalCount":3}}'
fake([("/jobsearch.ftl", lambda u, d: fx("taleo_search_rest.html")), ("rest/jobboard/searchjobs", rest), ("jobdetail.ftl", lambda u, d: fx("taleo_detail.html"))])
calls.clear()
jobs = list(A.f_taleo(dict(t)))
check("taleo rest: 3 postings", len(jobs) == 3)
check("taleo rest: portal from the page used", any("portal=101430233" in u for u, _ in calls))
check("taleo rest: fields", (jobs[0]["title"], jobs[0]["id"], jobs[0]["locations"]) == ("Sales - Underwriting Assistant", "Example::2600957", ["Fairfield, OH"]))
check("taleo rest: url", jobs[0]["url"] == "https://cinfin.taleo.net/careersection/ex/jobdetail.ftl?job=2600957&lang=en")
check("taleo rest: html entity in title", jobs[1]["title"] == "Machinery & Equipment Field - Representative")
check("taleo rest: Multiple Locations filled in from the posting page", jobs[1]["locations"] == ["Buffalo, NY"])
check("taleo rest: posting text, entities decoded", "We're hiring & growing." in jobs[1]["desc"] and "Degree" in jobs[1]["desc"] and "<" not in jobs[1]["desc"])
check("taleo rest: salary parsed", jobfinder.prepare_listing(dict(jobs[1], salary=None), t)["salary_min"] == 65000)
check("taleo rest: non-US + US mix keeps the US place", jobfinder.prepare_listing(dict(jobs[2], salary=None), t) is not None)
rows, total = A.taleo_rest_rows(json.loads(fx("taleo_rest_epco.json")))
check("taleo rest: section-specific columns (title/location/date positions)", rows == [("000GCD", "Supervisor, Measurement (GC) (Permian/North Texas)", ["Midland, TX"], "2026-11-09")] and total == 1)
try:
    A.taleo_rest_rows({"requisitionList": None, "careerSectionUnAvailable": True})
    check("unavailable section raises", False)
except ValueError:
    check("unavailable section raises", True)
calls.clear()
c4 = dict(t)
fake([("/jobsearch.ftl", lambda u, d: fx("taleo_search_rest.html")),
      ("rest/jobboard/searchjobs", lambda u, d: b'{"requisitionList":[],"pagingData":{"totalCount":50},"careerSectionUnAvailable":false}')])
list(A.f_taleo(c4))
check("taleo rest: empty page before the total signals capped", "empty page" in (c4.get("_truncated") or ""))
check("taleo verify (rest)", (fake([("/jobsearch.ftl", lambda u, d: fx("taleo_search_rest.html")), ("rest/jobboard/searchjobs", rest)]), A.verify(dict(t)))[1] == (3, None))

# ---- Taleo: legacy career section (pager form post)
tl = dict(CO, ats="taleo", host="evergy.taleo.net", section="evergy_external_career_section")
def pager(u, d):
    f = urllib.parse.parse_qs(d.decode()) if d else {}
    n = f.get("rlPager.currentPage", ["1"])[0]
    assert f.get("ftlcompid") == ["rlPager"] and f.get("ftlinterfaceid") == ["requisitionListInterface"]
    return fx("taleo_legacy_a.html") if n == "1" else fx("taleo_legacy_b.html")
def legacy_get(u, d):
    return pager(u, d) if d else fx("taleo_legacy_a.html")
fake([("/jobsearch.ftl", legacy_get), ("jobdetail.ftl", lambda u, d: fx("taleo_detail.html"))])
calls.clear()
cl = dict(tl)
jobs = list(A.f_taleo(cl))
check("taleo legacy: 3 postings over 2 pager posts", len(jobs) == 3 and not cl.get("_truncated") and sum(1 for _, d in calls if d) == 2)
check("taleo legacy: fields", [(j["id"], j["title"], j["locations"], j["posted"]) for j in jobs][:2] == [
    ("Example::FOS00N7", "Process Improvement Analyst", ["Topeka, KS", "Kansas City, MO"], "2026-11-09"),
    ("Example::INF00DZ", "Application Developer - Oracle NMS", ["Kansas City, MO"], "2026-11-08")])
check("taleo legacy: 3rd job on page 2", jobs[2]["id"] == "Example::TRA010Z" and jobs[2]["locations"] == ["Topeka, KS"])
rows, total = A.taleo_legacy_rows(fx("taleo_legacy_epco.html").decode())
check("taleo legacy: other column layout (contest no before title)", rows == [
    ("000GCD", "Supervisor, Measurement (GC) (Permian/North Texas)", ["Midland, TX"], "2026-11-09"),
    ("000HAP", "Operator, Plant (Midland Basin)", ["Mont Belvieu, TX"], "2026-10-27")] and total == 2)
fake([("/jobsearch.ftl", legacy_get), ("jobdetail.ftl", lambda u, d: urllib.error.HTTPError(u, 500, "x", {}, None))])
jobs = list(A.f_taleo(dict(tl)))
check("taleo legacy: failed detail fetch -> partial row, still listed", len(jobs) == 3 and all(j.get("_partial") for j in jobs))
d, locs = A.taleo_detail(fx("taleo_detail.html").decode())
check("taleo detail: de-duplicated text and location", d.count("Make a difference") == 1 and locs == ["Buffalo, NY"])

# ---- detection and config validation
m = company_add._match("https://cinfin.taleo.net/careersection/ex/jobsearch.ftl?lang=en")
check("detect taleo URL", m == {"ats": "taleo", "host": "cinfin.taleo.net", "section": "ex"})
check("detect taleo URL (jobdetail)", company_add._match("https://epco.taleo.net/careersection/6/jobdetail.ftl?job=000GCD")["section"] == "6")
check("detect taleo: not the rest/theme paths", company_add._match("https://x.taleo.net/careersection/theme/182/1/en/app.css") is None)
check("detect taleo: not Taleo Business Edition", company_add._match("https://tbe.taleo.net/careersection/ex/jobsearch.ftl") is None)
page = '<script src="/platform/js/j2w/j2w.fallbacks.js"></script><a href="/talentcommunity/subscribe/">Join</a>'
check("detect SuccessFactors RMK page", A.detect_page("https://jobs.example.com/", page) == {"ats": "successfactors", "base": "https://jobs.example.com"})
check("a page that only links to a SuccessFactors apply site is not detected", A.detect_page("https://careers.example.com/en", '<a href="https://career2.successfactors.eu/x">apply</a>') is None)
check("careers page that links a Taleo section", A.detect_page("https://www.example.com/careers", '<a href="https://evergy.taleo.net/careersection/ext/jobsearch.ftl?lang=en">Jobs</a>')["host"] == "evergy.taleo.net")
for cfg, ok in [({"ats": "successfactors", "base": "https://jobs.example.com"}, True),
                ({"ats": "successfactors", "base": "https://jobs.example.com/path"}, False),
                ({"ats": "successfactors", "base": "http://127.0.0.1"}, False),
                ({"ats": "successfactors"}, False),
                ({"ats": "taleo", "host": "cinfin.taleo.net", "section": "ex"}, True),
                ({"ats": "taleo", "host": "epco.taleo.net", "section": "ent_trans"}, True),
                ({"ats": "taleo", "host": "evil.example.com", "section": "ex"}, False),
                ({"ats": "taleo", "host": "cinfin.taleo.net", "section": "../x"}, False),
                ({"ats": "taleo", "host": "cinfin.taleo.net:8080", "section": "ex"}, False),
                ({"ats": "taleo", "host": "cinfin.taleo.net"}, False)]:
    got, why = netsafe.clean_config(cfg)
    check(f"clean_config {cfg} -> {'ok' if ok else 'refused'}", (got is not None) == ok)
check("every request goes through netsafe", "netsafe.urlopen" in open(os.path.join(HERE, "..", "ats_sap_taleo.py"), encoding="utf8").read()
      and "urllib.request.urlopen" not in open(os.path.join(HERE, "..", "ats_sap_taleo.py"), encoding="utf8").read())
check("default name from the site address", company_add.default_name({"ats": "successfactors", "base": "https://jobs.bostonscientific.com"}, None, "") == "Bostonscientific"
      and company_add.default_name({"ats": "successfactors", "base": "https://jobs.example.com"}, "Example Corp", "") == "Example Corp")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
