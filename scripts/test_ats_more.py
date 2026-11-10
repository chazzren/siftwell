"""Offline tests for ats_more (Radancy / Eightfold / Avature) using small saved pages in scripts/fixtures_ats_more/.
Run: SIFTWELL_FORBID_CLAUDE=1 python -X utf8 scripts/test_ats_more.py   (no network; ats_more.fetch is replaced)"""
import json, os, sys, tempfile, urllib.error
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("JOBBOARD_DATA", tempfile.mkdtemp(prefix="ats_more_test_"))
import ats_more, netsafe

FX = os.path.join(HERE, "fixtures_ats_more")
def fx(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

ats_more.GAP = 0
ats_more._wanted = lambda c, title: True
CALLS = []
ROUTES = {}   # url substring -> text (or an exception to raise)

def fake_fetch(url, headers=None, robots=True, tries=3, cap=0):
    CALLS.append(url)
    for k, v in ROUTES.items():
        if k in url:
            if isinstance(v, Exception):
                raise v
            return v, url
    raise urllib.error.HTTPError(url, 404, "not routed", {}, None)

real_robots = ats_more.robots_ok
ats_more.fetch = fake_fetch
import jsonld_fetcher   # (its sitemap reader is used for Radancy sites that forbid /search-jobs/)
jsonld_fetcher.get_text = lambda url, headers=None: next(v for k, v in ROUTES.items() if k in url)
jsonld_fetcher.allowed = lambda u: True

def reset(routes):
    CALLS.clear()
    ROUTES.clear()
    ROUTES.update(routes)
    ats_more._robots.clear()
    ats_more._ef_mode.clear()

# ------------------------------------------------------------------ robots.txt: longest match wins
r = ats_more.parse_robots(fx("ef_robots.txt"))
check("robots: Disallow / but Allow /api/pcsx -> allowed", ats_more.rules_allow(r, "/api/pcsx/search?domain=x"))
check("robots: Disallow / blocks other paths", not ats_more.rules_allow(r, "/candidate/profile"))
check("robots: Allow /$ only the root", ats_more.rules_allow(r, "/") and not ats_more.rules_allow(r, "/x"))
r = ats_more.parse_robots(fx("av_robots.txt"))
check("robots: avature portal allowed", ats_more.rules_allow(r, "/careers/SearchJobs/?jobOffset=6") and ats_more.rules_allow(r, "/en_US/careers/SearchJobs"))
check("robots: qtvc= forbidden", not ats_more.rules_allow(r, "/careers/SearchJobs?qtvc=1"))
r = ats_more.parse_robots(fx("tb_robots_closed.txt"))
check("robots: Disallow:/search-jobs/ (no space)", not ats_more.rules_allow(r, "/search-jobs/results?x=1") and ats_more.rules_allow(r, "/job/a/b/1/2"))
check("robots: empty file allows everything", ats_more.rules_allow(ats_more.parse_robots(""), "/anything"))
check("robots: own group beats *", not ats_more.rules_allow(ats_more.parse_robots("User-agent: *\nAllow: /\n\nUser-agent: siftwell\nDisallow: /\n"), "/x"))

# robots_ok itself (network replaced): 404 = no restrictions, 5xx = refuse
ats_more.fetch = lambda url, **kw: (_ for _ in ()).throw(urllib.error.HTTPError(url, 404, "", {}, None))
ats_more._robots.clear()
check("robots_ok: no robots.txt -> allowed", real_robots("https://a.example/x"))
ats_more.fetch = lambda url, **kw: (_ for _ in ()).throw(urllib.error.HTTPError(url, 503, "", {}, None))
ats_more._robots.clear()
try:
    real_robots("https://b.example/x"); blocked = False
except ats_more.Blocked:
    blocked = True
check("robots_ok: robots.txt 503 -> refuse for now", blocked)
ats_more.fetch = fake_fetch
ats_more.robots_ok = lambda url: True   # (the fetcher tests below replace fetch entirely; robots is covered above)

# ------------------------------------------------------------------ locations
L = ats_more.us_label
check("loc: City, StateName", L("Miami, Florida") == "Miami, FL")
check("loc: City, ST, US (Eightfold standardized)", L("Brookfield, WI, US") == "Brookfield, WI")
check("loc: ALL CAPS city + United States", L("TEMPERANCE,MI,United States") == "Temperance, MI")
check("loc: US-TX-Austin", L("US-TX-Austin") == "Austin, TX")
check("loc: county in the middle", L("Miami, Miami-Dade, Florida") == "Miami, FL")
check("loc: country-first 'US, CA, Santa Clara'", L("US, CA, Santa Clara") == "Santa Clara, CA")
check("eightfold std place: country code decides (IL = Israel, not Illinois)", ats_more._ef_std_label("Tel Aviv-Yafo, Tel Aviv District, IL") is None
      and ats_more._ef_std_label("Brookfield, WI, US") == "Brookfield, WI" and ats_more._ef_std_label("Taipei City,TW") is None)
check("loc: abroad with country", L("Almere Stad, Netherlands") is None and L("Bascharage, Luxembourg") is None)
check("loc: Canada province is not a US state", L("Toronto, ON") is None and L("Calgary, Alberta, Canada") is None)
check("loc: remote US kept", L("Remote - US") == "Remote - US" and L("Remote, USA") == "Remote")
check("loc: remote Canada dropped", L("Remote - Canada") is None)
check("loc: bare US place known to gazetteer", L("Atlanta") == "Atlanta")
check("loc: bare place abroad dropped", L("ChengDu") is None and L("Jerusalem") is None)
check("loc: Indiana is not India", L("Indianapolis, IN") == "Indianapolis, IN" and L("Indiana") == "Indiana")
check("loc: United States alone", L("United States") == "United States")
ls, out = ats_more.us_locations(["Berlin, Germany", "Miami, Florida", "Miami, FL"])
check("us_locations: dedupe + drop abroad", ls == ["Miami, FL"] and not out)
check("us_locations: only abroad flagged", ats_more.us_locations(["Berlin, Germany"]) == ([], True) and ats_more.us_locations([]) == ([], False))

# ------------------------------------------------------------------ config validation (netsafe.clean_config)
ok = lambda c: netsafe.clean_config(c)[0] is not None
check("config: radancy", ok({"ats": "radancy", "base": "https://jobs.carnivalcorp.com"}))
check("config: radancy rejects a path / private host / http junk",
      not ok({"ats": "radancy", "base": "https://jobs.example.com/search-jobs"}) and not ok({"ats": "radancy", "base": "http://127.0.0.1"})
      and not ok({"ats": "radancy", "base": "javascript:alert(1)"}) and not ok({"ats": "radancy"}))
check("config: eightfold", ok({"ats": "eightfold", "host": "nvidia.eightfold.ai", "domain": "nvidia.com"}))
check("config: eightfold rejects bad host/domain",
      not ok({"ats": "eightfold", "host": "evil.com/x", "domain": "a.com"}) and not ok({"ats": "eightfold", "host": "a.com", "domain": "a.com?x=1"})
      and not ok({"ats": "eightfold", "host": "a.com"}) and not ok({"ats": "eightfold", "host": "a b.com", "domain": "a.com"}))
check("config: avature", ok({"ats": "avature", "base": "https://koch.avature.net", "portal": "careers"}))
check("config: avature rejects bad portal",
      not ok({"ats": "avature", "base": "https://koch.avature.net", "portal": "../x"}) and not ok({"ats": "avature", "base": "https://koch.avature.net", "portal": "a/b"})
      and not ok({"ats": "avature", "base": "https://koch.avature.net"}))
check("config: unknown keys dropped", netsafe.clean_config({"ats": "avature", "base": "https://k.avature.net", "portal": "careers", "evil": 1})[0] == {"ats": "avature", "base": "https://k.avature.net", "portal": "careers"})

# ------------------------------------------------------------------ Radancy
CO = {"ats": "radancy", "base": "https://jobs.example.com", "name": "Example Cruises", "sector": "t", "tier": "t"}
reset({"search-jobs/results": fx("tb_results.json"), "/job/": fx("tb_job.html"), "robots.txt": fx("tb_robots_open.txt")})
cards = ats_more.tb_cards(json.loads(fx("tb_results.json"))["results"])
check("radancy: cards parsed (title, id, location, link)", len(cards) == 4 and cards[0]["id"].isdigit() and cards[0]["title"] and cards[0]["loc"] == "Miami, Florida" and cards[0]["href"].startswith("/job/"))
check("radancy: US facet found from the filters", ats_more.tb_us_facet(json.loads(fx("tb_results.json"))["filters"]) == "6252001")
ats_more.tb_can_search = lambda base: True
jobs = list(ats_more.f_radancy(dict(CO)))
check("radancy: abroad card dropped, 3 US listings", len(jobs) == 3)
j = jobs[0]
check("radancy: listing shape", j["company"] == "Example Cruises" and j["id"] == "Example Cruises::" + cards[0]["id"] and j["url"].startswith("https://jobs.example.com/job/")
      and j["locations"] == ["Miami, FL"] and j["posted"] == "2026-11-10" and j["desc"] and j["salary"] and j["salary"][:2] == (70000, 90000) and j["dept"])
check("radancy: facet was applied to the search", any("FacetFilters%5B0%5D.ID=6252001" in u for u in CALLS if "search-jobs/results" in u))
# a site that forbids /search-jobs/ -> sitemap + posting pages
ats_more.tb_can_search = lambda base: False
reset({"sitemap.xml": fx("tb_sitemap.xml"), "senior-analyst": fx("tb_job.html"), "103122106999": fx("tb_job_abroad.html")})
jobs = list(ats_more.f_radancy(dict(CO, name="check")))
check("radancy sitemap: only the US posting, no search-jobs request", len(jobs) == 1 and jobs[0]["locations"] == ["Miami, FL"] and jobs[0]["id"].endswith("::103122106352")
      and not any("search-jobs" in u for u in CALLS))
ats_more.tb_can_search = lambda base: True
# partial rows: titles nobody wants get no detail request
reset({"search-jobs/results": fx("tb_results.json"), "/job/": fx("tb_job.html")})
ats_more._wanted = lambda c, t: False
jobs = list(ats_more.f_radancy(dict(CO)))
check("radancy: unwanted titles are partial rows with a location and no detail request",
      len(jobs) == 3 and all(j.get("_partial") and j["locations"] and not j["desc"] for j in jobs) and not any("/job/" in u and "search-jobs" not in u for u in CALLS))
ats_more._wanted = lambda c, t: True
# list stops: cap flagged
reset({"search-jobs/results": fx("tb_results.json").replace('data-total-results=\\"4\\"', 'data-total-results=\\"500\\"'), "/job/": fx("tb_job.html")})
c = dict(CO)
old = ats_more.LIST_PAGES
ats_more.LIST_PAGES = 1
list(ats_more.f_radancy(c))
ats_more.LIST_PAGES = old
check("radancy: capped list is flagged for the catalog", bool(c.get("_truncated")))
# an error page is an error, not zero jobs
reset({"search-jobs/results": urllib.error.HTTPError("u", 403, "forbidden", {}, None)})
try:
    list(ats_more.f_radancy(dict(CO))); raised = False
except urllib.error.HTTPError:
    raised = True
check("radancy: 403 is raised (nothing is closed on an error)", raised)

# ------------------------------------------------------------------ Eightfold
EF = {"ats": "eightfold", "host": "x.eightfold.ai", "domain": "x.com", "name": "Ex AI", "sector": "t", "tier": "t"}
def efs(count):
    d = json.loads(fx("ef_pcsx_search.json"))
    d["data"]["count"] = count
    return json.dumps(d)
reset({"api/pcsx/search": efs(3), "api/pcsx/position_details": fx("ef_pcsx_detail.json")})
jobs = list(ats_more.f_eightfold(dict(EF)))
pos = json.loads(fx("ef_pcsx_search.json"))["data"]["positions"]
check("eightfold pcsx: one listing per position", len(jobs) == len(pos) == 3)
j = jobs[0]
check("eightfold pcsx: shape", j["id"] == f"Ex AI::{pos[0]['id']}" and j["url"] == f"https://x.eightfold.ai/careers/job/{pos[0]['id']}" and j["desc"]
      and j["posted"] and j["title"] == pos[0]["name"] and j["locations"] and all(", " in l or "Remote" in l or l == "United States" for l in j["locations"]))
check("eightfold pcsx: US filter + 10 per page requested", "location=United+States" in CALLS[0] and "start=0" in CALLS[0])
check("eightfold pcsx: stops at the reported count", len([u for u in CALLS if "api/pcsx/search" in u]) == 1)
c = dict(EF)
reset({"api/pcsx/search": efs(5000)})
old = ats_more.EF_CAP
ats_more.EF_CAP = 3
list(ats_more.f_eightfold(c))
ats_more.EF_CAP = old
check("eightfold: capped list flagged", "stops at 3" in (c.get("_truncated") or ""))
# apply/v2 fallback when pcsx is refused (403)
reset({"api/pcsx/": urllib.error.HTTPError("u", 403, "FORBIDDEN", {}, None), "api/apply/v2/jobs/": fx("ef_v2_detail.json"),
       "api/apply/v2/jobs": json.dumps(dict(json.loads(fx("ef_v2_search.json")), count=2))})
jobs = list(ats_more.f_eightfold(dict(EF)))
v2 = json.loads(fx("ef_v2_search.json"))["positions"]
check("eightfold v2 fallback: listings", len(jobs) == len(v2) == 2 and jobs[0]["locations"] and jobs[0]["desc"] and jobs[0]["url"].endswith("/careers/job/%s" % v2[0]["id"]))
check("eightfold v2 fallback: remembered (second page doesn't retry pcsx)", sum(1 for u in CALLS if "api/pcsx/" in u) == 1)
# both refused -> error
reset({"api/pcsx/": urllib.error.HTTPError("u", 403, "FORBIDDEN", {}, None), "api/apply/v2/jobs": urllib.error.HTTPError("u", 403, "FORBIDDEN", {}, None)})
try:
    list(ats_more.f_eightfold(dict(EF))); raised = False
except urllib.error.HTTPError:
    raised = True
check("eightfold: both APIs refused -> error, not an empty list", raised)
# abroad-only positions are dropped
abroad = json.loads(fx("ef_pcsx_search.json"))
abroad["data"]["positions"][0]["locations"] = ["Israel, Tel Aviv"]
abroad["data"]["positions"][0]["standardizedLocations"] = ["Tel Aviv-Yafo, Tel Aviv District, IL"]
abroad["data"]["count"] = 3
reset({"api/pcsx/search": json.dumps(abroad), "api/pcsx/position_details": fx("ef_pcsx_detail.json")})
check("eightfold: a position only abroad is dropped", len(list(ats_more.f_eightfold(dict(EF)))) == 2)
ats_more._wanted = lambda c, t: False
reset({"api/pcsx/search": efs(3)})
jobs = list(ats_more.f_eightfold(dict(EF)))
check("eightfold: unwanted titles are partial rows, no detail requests", all(j.get("_partial") for j in jobs) and not any("position_details" in u for u in CALLS))
ats_more._wanted = lambda c, t: True

# ------------------------------------------------------------------ Avature
AV = {"ats": "avature", "base": "https://koch.avature.net", "portal": "careers", "name": "Koch Co", "sector": "t", "tier": "t"}
reset({"SearchJobs": fx("av_koch_list.html"), "JobDetail": fx("av_koch_detail.html")})
cards = ats_more.av_cards(fx("av_koch_list.html"))
check("avature: Koch cards (title, id, 'Location:' field)", len(cards) == 3 and cards[0]["id"].isdigit() and cards[0]["loc"] == "Atlanta, Georgia" and cards[0]["title"])
check("avature: next page offset", ats_more.av_next(fx("av_koch_list.html")) == 6)
bcards = ats_more.av_cards(fx("av_bloomberg_list.html"))
check("avature: Bloomberg template (list-item-location span)", len(bcards) == 3 and all(x["loc"] and x["title"] for x in bcards) and ats_more.av_next(fx("av_bloomberg_list.html")) == 12)
dl, desc = ats_more.av_detail(fx("av_koch_detail.html"))
check("avature: detail location + description", dl == ["Atlanta, Georgia"] and len(desc) > 300 and "<" not in desc)
c = dict(AV)
jobs = list(ats_more.f_avature(c))
check("avature: abroad card dropped, US listings with descriptions", len(jobs) == 2 and jobs[0]["locations"] == ["Atlanta, GA"] and jobs[0]["desc"] and jobs[0]["id"] == "Koch Co::" + cards[0]["id"])
check("avature: stops when the next page adds nothing new (no endless loop)", sum(1 for u in CALLS if "SearchJobs" in u) == 2 and not c.get("_truncated"))
c = dict(AV)
old = ats_more.LIST_PAGES
ats_more.LIST_PAGES = 1
list(ats_more.f_avature(c))
ats_more.LIST_PAGES = old
check("avature: page cap flagged", "stopped after 1 list pages" in (c.get("_truncated") or ""))
check("avature: list url has no qtvc and uses the portal", all("qtvc" not in u for u in CALLS) and CALLS[0].startswith("https://koch.avature.net/careers/SearchJobs/"))

# ------------------------------------------------------------------ detection (company_add.detect path)
d = ats_more.detect("https://koch.avature.net/en_US/careers/SearchJobs", "")
check("detect: avature link with locale", d == {"ats": "avature", "base": "https://koch.avature.net", "portal": "careers"})
d = ats_more.detect("https://www.kochinc.com/career-opportunities", fx("av_corp_page.html"))
check("detect: avature portal found inside a corporate page", d == {"ats": "avature", "base": "https://koch.avature.net", "portal": "careers"})
check("detect: avature root without a portal word is not guessed", ats_more.detect("https://recruiting360.avature.net/", "") is None)
d = ats_more.detect("https://nvidia.eightfold.ai/careers", fx("ef_careers.html"))
check("detect: eightfold (domain read from the page)", d == {"ats": "eightfold", "host": "nvidia.eightfold.ai", "domain": "nvidia.com"})
d = ats_more.detect("https://careers.company.com/careers?domain=company.com&start=0", "")
check("detect: eightfold domain= in the link", d is None or d["ats"] != "eightfold" or d["domain"] == "company.com")
d = ats_more.detect("https://jobs.example.com", fx("tb_home.html"))
check("detect: radancy via talentbrew files", d == {"ats": "radancy", "base": "https://jobs.example.com"})
check("detect: plain page is none", ats_more.detect("https://example.com/careers", "<html>hello</html>") is None)
# a corporate page linking to an Eightfold career site
reset({"/careers": fx("ef_careers.html")})
d = ats_more.detect("https://www.corp.com/jobs", '<a href="https://careers.corp.com/careers?start=0&sort_by=hot">Jobs</a>')
check("detect: corporate page linking to an Eightfold site", d == {"ats": "eightfold", "host": "careers.corp.com", "domain": "nvidia.com"})
# two candidates: the one that answers wins
reset({"api/pcsx/search": urllib.error.HTTPError("u", 404, "", {}, None), "api/apply/v2/jobs": urllib.error.HTTPError("u", 404, "", {}, None),
       "search-jobs/results": fx("tb_results.json")})
ats_more.tb_can_search = lambda base: True
page = fx("tb_home.html") + '<a href="https://kdrp.eightfold.ai/careers">talent</a>' + fx("ef_careers.html")
d = ats_more.detect("https://jobs.example.com", page)
check("detect: Radancy site that also mentions a dead Eightfold hub -> Radancy", d and d["ats"] == "radancy")

# ------------------------------------------------------------------ verify
reset({"search-jobs/results": fx("tb_results.json")})
n, name = ats_more.verify({"ats": "radancy", "base": "https://jobs.carnivalcorp.com"})
check("verify radancy: total and a name", n == 4 and name == "Carnivalcorp")
reset({"api/pcsx/search": efs(1483)})
n, name = ats_more.verify({"ats": "eightfold", "host": "nvidia.eightfold.ai", "domain": "nvidia.com"})
check("verify eightfold: count from the API + name", n == 1483 and name == "Nvidia")
reset({"SearchJobs": fx("av_koch_list.html")})
n, name = ats_more.verify({"ats": "avature", "base": "https://koch.avature.net", "portal": "careers"})
check("verify avature: US jobs on the first pages", n == 2 and name == "Koch")
reset({"SearchJobs": "<html>nothing</html>"})
try:
    ats_more.verify({"ats": "avature", "base": "https://koch.avature.net", "portal": "careers"}); raised = False
except ValueError:
    raised = True
check("verify avature: an empty list is an error", raised)

# ------------------------------------------------------------------ registered where the app looks
import jobfinder
jobfinder.load_extra()
check("fetchers registered in jobfinder", all(k in jobfinder.FETCHERS for k in ("radancy", "eightfold", "avature")))

check("at most 2 workers per company", ats_more.WORKERS <= 2)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
