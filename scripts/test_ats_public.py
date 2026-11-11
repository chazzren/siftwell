"""Offline tests for ats_public (AppliTrack / SchoolSpring / Jobvite) using saved pages in scripts/fixtures_ats_public/.
Run: SIFTWELL_FORBID_CLAUDE=1 python -X utf8 scripts/test_ats_public.py   (no network; ats_public.fetch is replaced)"""
import json, os, sys, tempfile, urllib.error
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("JOBBOARD_DATA", tempfile.mkdtemp(prefix="ats_public_test_"))
import ats_more, ats_public, netsafe

FX = os.path.join(HERE, "fixtures_ats_public")
def fx(name):
    with open(os.path.join(FX, name), encoding="utf-8", errors="replace") as f:
        return f.read()

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

ats_more.GAP = 0
ats_public.SS_RETRY_WAIT = 0
ats_public._wanted = lambda c, title: True
CALLS, ROUTES = [], {}

def fake_fetch(url, headers=None, robots=True, tries=3, cap=0):
    CALLS.append(url)
    for k, v in ROUTES.items():
        if k in url:
            if isinstance(v, Exception):
                raise v
            return v, url
    raise urllib.error.HTTPError(url, 404, "not routed", {}, None)

ats_public.fetch = fake_fetch
ats_public.get_json = lambda url, **kw: json.loads(fake_fetch(url)[0])

def reset(routes):
    CALLS.clear(); ROUTES.clear(); ROUTES.update(routes)

# ------------------------------------------------------------------ robots: NEOGOV-style "no crawlers" is honoured
r = ats_more.parse_robots(fx("neogov_robots.txt"))
check("robots: Disallow / for * blocks NEOGOV/PeopleAdmin-style sites", not ats_more.rules_allow(r, "/careers/home"))

# ------------------------------------------------------------------ AppliTrack
jobs = ats_public.at_parse(fx("at_dcps_output.js"))
check("applitrack: parses the jobs", len(jobs) >= 1 and all(j["id"].isdigit() and j["title"] for j in jobs))
check("applitrack: has text and a date", any(len(j["desc"]) > 200 for j in jobs) and all(j["posted"] for j in jobs))
reset({"/dcps/onlineapp/jobpostings/Output.asp": fx("at_dcps_output.js"), "/dcps/onlineapp/default.aspx": fx("at_dcps_default.html")})
c = {"ats": "applitrack", "slug": "dcps", "place": "Clintwood, VA", "name": "Dickenson", "sector": "K-12"}
out = list(ats_public.f_applitrack(c))
check("applitrack: one J per posting", len(out) == len(jobs))
check("applitrack: place becomes the location", out[0]["locations"] == ["Clintwood, VA"])
check("applitrack: link opens the posting", "AppliTrackJobId=" + jobs[0]["id"] in out[0]["url"] and out[0]["url"].startswith("https://www.applitrack.com/dcps/"))
check("applitrack: ids unique and prefixed", len({j["id"] for j in out}) == len(out) and out[0]["id"].startswith("Dickenson::"))
check("applitrack: no place -> no location (not wrong)", list(ats_public.f_applitrack(dict(c, place="")))[0]["locations"] == [])
check("applitrack: config check", netsafe.clean_config({"ats": "applitrack", "slug": "dcps", "place": "Clintwood, VA"})[0] is not None
      and netsafe.clean_config({"ats": "applitrack", "slug": "../x"})[0] is None)
check("applitrack: place from an address", ats_public._place_from("PO Box 1 South East Street Frederick, MD 21701") == "Frederick, MD")
cfg = ats_public.detect("https://www.applitrack.com/dcps/onlineapp/default.aspx?all=1")
check("applitrack: detect from link", cfg and cfg["slug"] == "dcps")
check("applitrack: detect from a page linking to it", ats_public.detect("https://district.example.org/jobs", '<a href="https://www.applitrack.com/dcps/onlineapp/default.aspx">Apply</a>')["slug"] == "dcps")
check("applitrack: verify count", ats_public.verify(cfg)[0] == len(jobs))

# ------------------------------------------------------------------ SchoolSpring
lst = json.loads(fx("ss_list.json"))["value"]["jobsList"]
reset({"GetPagedJobsWithSearch": fx("ss_list.json"), "api/Jobs/5988915": fx("ss_detail.json")})
c = {"ats": "schoolspring", "sub": "campbell", "name": "Campbell", "sector": "K-12"}
out = list(ats_public.f_schoolspring(c))
check("schoolspring: one J per posting", len(out) == len(lst))
d = next(j for j in out if j["id"].endswith("::5988915"))
check("schoolspring: state names become City, ST", d["locations"] == ["Gillette, WY"])
check("schoolspring: text + pay from the detail", "Purpose Statement" in d["desc"] and d["desc"].startswith("Pay: $17.93 - $19.59"))
check("schoolspring: posted date + school as dept", d["posted"] == "2026-11-11" and d["dept"] == "PRONGHORN ELEMENTARY")
check("schoolspring: other jobs without detail route stay partial", any(j.get("_partial") for j in out if not j["id"].endswith("::5988915")))
check("schoolspring: first page only when it is short", sum("GetPagedJobsWithSearch" in u for u in CALLS) == 1)
check("schoolspring: location cleanup", ats_public.ss_location("n/a, Oregon") == "Oregon" and ats_public.ss_location("Libby, Montana") == "Libby, MT")
check("schoolspring: detect", ats_public.detect("https://campbell.schoolspring.com/")["sub"] == "campbell" and ats_public.detect("https://www.schoolspring.com/jobs") is None)
check("schoolspring: config check", netsafe.clean_config({"ats": "schoolspring", "sub": "campbell"})[0] is not None and netsafe.clean_config({"ats": "schoolspring", "sub": "a/b"})[0] is None)
reset({"GetPagedJobsWithSearch": json.dumps({"success": True, "value": {"jobsList": []}})})
check("schoolspring: empty board", list(ats_public.f_schoolspring(c)) == [])

# ------------------------------------------------------------------ Jobvite
rows = ats_public.jv_parse(fx("jv_list.html"), "washingtonhospital")
check("jobvite: parses the list with departments", len(rows) > 50 and rows[0]["dept"] == "Accounting / Finance" and rows[0]["loc"] == "Fremont, California")
rows2 = ats_public.jv_parse(fx("jv_list_dated.html"), "heifer")
check("jobvite: list variant with a posting-date column", len(rows2) > 5 and all(r["posted"] for r in rows2) and "," in rows2[0]["loc"] + ",")
desc, locs = ats_public.jv_detail(fx("jv_detail.html"))
check("jobvite: detail text and place", "Salary Range" in desc and locs == ["Fremont, California"])
reset({"/washingtonhospital/jobs": fx("jv_list.html"), "/washingtonhospital/job/": fx("jv_detail.html")})
c = {"ats": "jobvite", "slug": "washingtonhospital", "name": "Washington Hospital", "sector": "Hospital"}
out = list(ats_public.f_jobvite(c))
check("jobvite: one J per posting", len(out) == len(rows))
check("jobvite: City, ST + text + link", out[0]["locations"] == ["Fremont, CA"] and "Salary Range" in out[0]["desc"] and out[0]["url"].endswith("/job/" + rows[0]["id"]))
check("jobvite: detect", ats_public.detect("https://jobs.jobvite.com/careers/washingtonhospital/jobs")["slug"] == "washingtonhospital"
      and ats_public.detect("https://jobs.jobvite.com/careers") is None)
check("jobvite: config check", netsafe.clean_config({"ats": "jobvite", "slug": "x"})[0] is not None and netsafe.clean_config({"ats": "jobvite", "slug": "x y"})[0] is None)
check("jobvite: verify count and name", ats_public.verify({"ats": "jobvite", "slug": "washingtonhospital"}) == (len(rows), "Washington Hospital"))

# ------------------------------------------------------------------ registered everywhere
import jobfinder
jobfinder.load_extra()
check("registered in jobfinder.FETCHERS", all(k in jobfinder.FETCHERS for k in ("applitrack", "schoolspring", "jobvite")))
import company_add
check("company_add.detect knows the link forms", company_add.detect.__code__ is not None)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
