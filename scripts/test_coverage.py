"""Offline tests for the "every publicly readable job near you" work: county labels (geo), postings without a readable
place (employer places from the directory), dead boards ageing out (catalog.record_fetch), readable company names,
every nearby directory employer + the staged first check's queue (directory.apply, first_search.due), Workday's unnamed
location facets, and the directory builder (career-site recovery and dedupe, weak place labels, names from board pages,
the USAJOBS / SchoolSpring pulls).

Run: SIFTWELL_FORBID_CLAUDE=1 python -X utf8 scripts/test_coverage.py   (no network; a temp data folder)"""
import datetime as dt, gzip, hashlib, json, os, sys, tempfile
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
TMP = tempfile.mkdtemp(prefix="coverage_test_")
os.environ["JOBBOARD_DATA"] = os.path.join(TMP, "data")
INDEX = os.path.join(TMP, "index")
os.environ["SIFTWELL_DIRECTORY_URL"] = "file:///" + INDEX.replace("\\", "/")

import catalog, company_add, directory, geo, jobfinder, people

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

# ---------------------------------------------------------------- geo: counties
def kinds(s):
    return [(h.kind, h.label) for h in geo.locate_all(s)]

check("Franklin County, OH is the county", kinds("Franklin County, OH") == [("county", "Franklin County, OH")])
check("a county is never a same-named town", not any(k == "place" for k, _ in kinds("Franklin County, OH")))
check("county without a state, ambiguous: nothing", kinds("Franklin County") == [])
check("county name in upper case", kinds("FRANKLIN COUNTY, OH") == [("county", "Franklin County, OH")])
check("state spelled out", kinds("Work in Delaware County, Ohio") == [("county", "Delaware County, OH")])
check("parish", kinds("Jefferson Parish, LA") == [("county", "Jefferson Parish, LA")])
check("St. county", kinds("St. Louis County, MO") == [("county", "St. Louis County, MO")])
check("apostrophe county", kinds("Prince George's County, MD")[0][0] == "county")
check("county + city keeps the city", ("place", "Columbus, OH") in kinds("Columbus, Franklin County, OH"))
check("plain town still a town", kinds("Delaware, OH") == [("place", "Delaware, OH")])
home = geo.geocode_home("43215")
check("Franklin County OH is within 35 mi of Columbus", geo.within(["Franklin County, OH"], home, 35)[0])
check("Franklin County KY is not", not geo.within(["Franklin County, KY"], home, 35)[0])
check("neighbouring county outside a 10 mi radius", not geo.within(["Delaware County, OH"], home, 10)[0])
check("counties file is small", os.path.getsize(os.path.join(geo.GEO, "counties.tsv")) < 150_000)

# ---------------------------------------------------------------- postings without a readable place
V = jobfinder.vague_location
check("empty is vague", V(""))
check("Main Office / Headquarters / Building 5 are vague", all(V(x) for x in ("Main Office", "Headquarters", "Building 5", "Main Campus", "Statewide")))
check("a state the employer hires in is vague", V("Multiple Locations - OH", ("OH",)) and V("Ohio", ("OH",)))
check("another state is not", not V("Texas", ("OH",)) and not V("Multiple Locations - TX", ("OH",)))
check("a real town is not vague", not V("Dublin, OH") and not V("Austin, TX"))
check("remote and foreign labels are not vague", not V("Remote") and not V("Toronto, Canada") and not V("London, United Kingdom"))
homes = [(home, 35.0)]
near_info = {"places": [[39.96, -83.0], [40.1, -83.1]], "all": True}
check("employer all near", jobfinder.employer_all_near(near_info, homes))
check("one far place: not all near", not jobfinder.employer_all_near({"places": [[39.96, -83.0], [41.5, -81.7]], "all": True}, homes))
check("incomplete place list: never all near", not jobfinder.employer_all_near({"places": [[39.96, -83.0]], "all": False}, homes))
check("no homes: never", not jobfinder.employer_all_near(near_info, []))

catalog.migrate(log=lambda *a: None)
def company(name, **kw):
    e = {"name": name, "ats": "greenhouse", "token": name.lower().replace(" ", ""), "tier": "dmv_office", "sector": "x", "sets": ["tech"]}
    e.update(kw)
    catalog.save_company(e)
    return e
company("Local Clinic", dir={"all": True, "p": [[39.96, -83.0], [40.1, -83.1]], "st": ["OH"], "lab": "Columbus, OH"})
company("Two State Co", dir={"all": True, "p": [[39.96, -83.0], [41.5, -81.7]], "st": ["OH"], "lab": "Columbus, OH"})
company("Unknown Co")
check("dir is not part of the board's identity", catalog.ats_key(catalog.companies()[0]) == catalog.ats_key({k: v for k, v in catalog.companies()[0].items() if k != "dir"}))
check("places_map carries the directory places", set(catalog.places_map()) == {"Local Clinic", "Two State Co"})
def listing(co, title, locs):
    return {"id": f"{co}::{title}", "company": co, "title": title, "locations": locs, "salary_max": None, "workplace": "",
            "remote_strict": False, "remote_bare": False, "local_unnamed": False}
pool = [listing("Local Clinic", "Nurse", ["Main Office"]), listing("Local Clinic", "Clerk", []), listing("Local Clinic", "Aide", ["Ohio"]),
        listing("Local Clinic", "Far", ["Austin, TX"]), listing("Local Clinic", "Town", ["Dublin, OH"]),
        listing("Two State Co", "Nurse", ["Main Office"]), listing("Unknown Co", "Nurse", ["Headquarters"])]
jobfinder.CFG.update(homes=homes, legacy_area=False, remote_ok=True, workplaces=["onsite", "hybrid", "remote"], targets=[],
                     salary_floor=0, keep_below_floor=True, keep_unlisted_salary=True)
jobfinder.title_ok = lambda t: True
_real_sets, people.company_sets = people.company_sets, lambda pid=None: {"tech"}
got = {j["id"].split("::")[1] + "@" + j["company"]: j for j in jobfinder.select_for_person(pool, catalog.sets_map())}
people.company_sets = _real_sets
check("unnamed place at an all-nearby employer is local", "Nurse@Local Clinic" in got and "Clerk@Local Clinic" in got and "Aide@Local Clinic" in got)
check("... and says where it probably is", got.get("Nurse@Local Clinic", {}).get("dmv_locations") == ["Main Office (near Columbus, OH)"]
      and got.get("Clerk@Local Clinic", {}).get("dmv_locations") == ["Near Columbus, OH"])
check("a named far place stays out", "Far@Local Clinic" not in got)
check("a named near place still works the usual way", got.get("Town@Local Clinic", {}).get("dmv_locations") == ["Dublin, OH"])
check("employer with a far place: unnamed stays out", "Nurse@Two State Co" not in got)
check("employer the directory doesn't know: unnamed stays out", "Nurse@Unknown Co" not in got)

# ---------------------------------------------------------------- Workday: unnamed location facets
facets = [{"facetParameter": "locations", "values": [
    {"id": "a", "descriptor": "Columbus, OH", "count": 40}, {"id": "b", "descriptor": "Main Campus", "count": 30},
    {"id": "c", "descriptor": "Building 5", "count": 5}, {"id": "d", "descriptor": "Austin, TX", "count": 50},
    {"id": "e", "descriptor": "Warehouse", "count": 590}, {"id": "f", "descriptor": "Toronto, Canada", "count": 9}]}]
check("named facets only by default", jobfinder._wd_location_facets(facets) == {"locations": ["a"]})
check("a local employer's unnamed facets are queried too, within the cap",
      jobfinder._wd_location_facets(facets, unnamed=True) == {"locations": ["a", "e"]})
facets[0]["values"][4]["count"] = 100
check("... biggest first, others while they fit", jobfinder._wd_location_facets(facets, unnamed=True) == {"locations": ["a", "e", "b", "c"]})

# ---------------------------------------------------------------- record_fetch: dead boards age out
def fetch(co, ids, status="ok"):
    with catalog.db() as con:
        return catalog.record_fetch(co, {"status": status, "raw_jobs": len(ids), "secs": 1},
                                    [dict(listing(co, i, ["Columbus, OH"]), desc="text " + i) for i in ids], con)
def open_n(co):
    with catalog.db() as con:
        return con.execute("SELECT COUNT(*) FROM listings WHERE company=? AND closed_at IS NULL", (co,)).fetchone()[0]
def age(co, days, fail_days=None):
    d = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with catalog.db() as con:
        con.execute("UPDATE listings SET last_seen=? WHERE company=?", (d, co))
        if fail_days is not None:
            con.execute("UPDATE companies SET fail_since=? WHERE name=?", ((dt.date.today() - dt.timedelta(days=fail_days)).isoformat(), co))
# Workday: a posting whose text is stored isn't requested again every day (one day in WD_RECHECK_DAYS)
wd_calls = []
def fake_wd(url, body=None, tries=6):
    wd_calls.append(url)
    if url.endswith("/jobs"):
        return {"total": 3, "facets": [], "jobPostings": [{"title": f"Analyst {i}", "externalPath": f"/job/Columbus/A_{i}", "locationsText": "Columbus, OH"} for i in range(3)]}
    return {"jobPostingInfo": {"location": "Columbus, OH", "jobDescription": "<p>Analyse things.</p>", "startDate": "2026-11-01"}}
real_http, jobfinder.http_json = jobfinder.http_json, fake_wd
jobfinder.fetch_wanted = lambda c, t: True
wdc = company("Wd Co", ats="workday", tenant="wdco", wd="wd1", site="Careers", tier="dmv_hq")
def wd_fetch():
    wd_calls.clear()
    s, js = jobfinder.process(dict(wdc))
    with catalog.db() as con:
        catalog.record_fetch("Wd Co", s, js, con)
    return sum("/job/" in u for u in wd_calls), s, js
n1, s1, _ = wd_fetch()
check("Workday first fetch reads every posting's text", n1 == 3 and s1["status"] == "ok" and open_n("Wd Co") == 3)
jobfinder.WD_RECHECK_DAYS = 10 ** 9      # (no posting's weekly day is today)
n2, s2, js2 = wd_fetch()
check("Workday later fetch doesn't ask for stored text again", n2 == 0 and all(j.get("_unchanged") for j in js2) and open_n("Wd Co") == 3)
jobfinder.WD_RECHECK_DAYS = 1            # (every posting's day is today)
check("... except on the posting's weekly day", wd_fetch()[0] == 3)
jobfinder.WD_RECHECK_DAYS = 7
jobfinder.http_json = real_http

company("Dead Board")
ids = [f"j{i}" for i in range(8)]
fetch("Dead Board", ids)
check("8 open after a good fetch", open_n("Dead Board") == 8)
c = fetch("Dead Board", [], "error: HTTPError 500")
check("an errored fetch closes nothing", open_n("Dead Board") == 8 and c["status"] == "error")
age("Dead Board", 30)
fetch("Dead Board", [], "error: HTTPError 500")
check("first failure after a long break closes nothing (the app just wasn't run)", open_n("Dead Board") == 8)
age("Dead Board", 30, fail_days=catalog.STALE_DAYS + 1)
c = fetch("Dead Board", [], "error: HTTPError 500")
check("failing for STALE_DAYS and unseen for STALE_DAYS: aged out", open_n("Dead Board") == 0 and c["closed"] == 8)
company("Empty Board")
fetch("Empty Board", ids)
c = fetch("Empty Board", [])
check("suspiciously empty fetch: kept open", open_n("Empty Board") == 8 and c["status"] == "suspect")
age("Empty Board", 30, fail_days=catalog.STALE_DAYS + 1)
fetch("Empty Board", [])
check("... and aged out once it has been empty for STALE_DAYS", open_n("Empty Board") == 0)
company("Back Again")
fetch("Back Again", ids)
fetch("Back Again", [], "error: timeout")
fetch("Back Again", ids)
with catalog.db() as con:
    fs = con.execute("SELECT fail_since FROM companies WHERE name='Back Again'").fetchone()[0]
check("a good fetch clears fail_since", fs is None and open_n("Back Again") == 8)
age("Back Again", 30)
fetch("Back Again", ids[:5])
check("a trustworthy fetch still closes what is gone", open_n("Back Again") == 5)

# ---------------------------------------------------------------- names
L = company_add.looks_like_code
check("UUID names are codes", L("0330Dee1 D933 49D0 8F0A 0A1B2C3D4E5F") and L("38ce6eaf-8096-42ab-95a9-aaf31d00ac23"))
check("UKG tenant codes are codes", L("Lic1000Lmhs") and L("Car1038") and L("12345"))
check("real names are not", not any(L(x) for x in ("3M", "84 Lumber", "Stripe", "OhioHealth", "Decade", "A123 Systems", "7 Eleven")))
check("leading code is dropped", company_add.readable_name("US10791-ALACUS Air Liquide USA", {}) == "Air Liquide USA")
check("code name falls back to the careers host", company_add.readable_name("Lic1000Lmhs", {"ats": "icims", "base": "https://careers-lickingmemorial.icims.com"}) == "Lickingmemorial")
check("shared hosts give no name", company_add.readable_name("Lic1000Lmhs", {"ats": "ukg", "host": "recruiting.ultipro.com", "tenant": "LIC1000LMHS", "board": "b"}) == "")
check("placeholder says where and which system", company_add.placeholder_name({"ats": "paylocity", "id": "38ce6eaf-8096-42ab-95a9-aaf31d00ac23"}, "Columbus, OH") == "Employer in Columbus OH (Paylocity 38ce6e)")
check("default_name never returns a code", not L(company_add.default_name({"ats": "paylocity", "id": "38ce6eaf-8096-42ab-95a9-aaf31d00ac23"}))
      and not L(company_add.default_name({"ats": "ukg", "host": "recruiting.ultipro.com", "tenant": "LIC1000LMHS", "board": "x"})))
check("default_name keeps readable ones", company_add.default_name({"ats": "greenhouse", "token": "stripe"}) == "Stripe")
check("Workday link without a career site is not a board", company_add._match("https://acme.wd1.myworkdayjobs.com/robots.txt") is None
      and company_add._match("https://acme.wd5.myworkdayjobs.com/en-US") is None and company_add._match("https://acme.wd5.myworkdayjobs.com/es") is None)
check("Workday link with a site still is", company_add._match("https://acme.wd1.myworkdayjobs.com/en-US/External_Careers/job/x") ==
      {"ats": "workday", "tenant": "acme", "wd": "wd1", "site": "External_Careers"})
company("Car1038", ats="ukg", host="recruiting.ultipro.com", tenant="CAR1038", board="b1")
fetch("Car1038", ["a", "b"])
check("rename moves the listings", catalog.rename_company("Car1038", "Cardinal Example") and open_n("Cardinal Example") == 2 and open_n("Car1038") == 0)
with catalog.db() as con:
    rid = [r[0] for r in con.execute("SELECT id FROM listings WHERE company='Cardinal Example' ORDER BY id")]
check("... and keeps their ids (ratings and marks are keyed by them)", rid == ["Car1038::a", "Car1038::b"])
check("rename refuses a taken name", not catalog.rename_company("Cardinal Example", "Local Clinic"))

# ---------------------------------------------------------------- directory.apply: every nearby employer
def put(rel, obj):
    p = os.path.join(INDEX, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = gzip.compress(json.dumps(obj).encode(), mtime=0)
    open(p, "wb").write(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
def emp(i, lat=39.96, lon=-83.0, n=None, **kw):
    e = {"n": f"Employer {i:04d}", "c": {"ats": "greenhouse", "token": f"emp{i:04d}"}, "u": f"https://job-boards.greenhouse.io/emp{i:04d}",
         "j": 10, "r": 0, "p": [[lat, lon, n if n is not None else 1 + i % 50, "Columbus, OH"]], "s": "2026-11-10", "ps": ["OH"]}
    e.update(kw)
    return e
def publish(emps):
    man = {"v": 1, "built": dt.datetime.now().isoformat(), "states": {}, "jobs": {}, "sources": {}}
    man["states"]["OH"] = put("states/OH.json.gz", {"v": 1, "state": "OH", "employers": emps})
    os.makedirs(INDEX, exist_ok=True)
    json.dump(man, open(os.path.join(INDEX, "manifest.json"), "w"))
    directory.manifest(refresh=True)
emps = [emp(i) for i in range(650)]
emps += [emp(900, 41.5, -81.7, 99)]                                                         # Cleveland: not near
emps += [emp(901, n=7, c={"ats": "paylocity", "id": "38ce6eaf-8096-42ab-95a9-aaf31d00ac23"},
             u="https://recruiting.paylocity.com/recruiting/jobs/All/38ce6eaf-8096-42ab-95a9-aaf31d00ac23")]
emps[-1]["n"] = "38Ce6Eaf 8096 42Ab 95A9 Aaf31D00Ac23"
emps += [emp(902, 41.5, -81.7, 500, mb=1, x=1)]                                             # big sampled board, seen elsewhere in OH
emps += [emp(903, n=3, k="staffing")]
emps += [emp(904, n=4, ps=["OH", "TX"])]
publish(emps)
pid = people.add("Tester")
people.save_settings({"home_zip": "43215", "radius_miles": 35}, pid=pid)
r = directory.apply(pid)
near = catalog.sets_map()
mine = {n for n, s in near.items() if f"near-{pid}" in s}
check("every nearby employer is added, not 400", len(r["added"]) == 654 and len(mine) == 654)
check("an employer elsewhere in the state is not", "Employer 0900" not in mine)
check("a code name never reaches the catalog, and a placeholder carries no job system or code", "Employer in Columbus OH" in mine
      and not any(company_add.looks_like_code(n) for n in mine) and not any("Paylocity" in n or "38ce6e" in n.lower() for n in mine))
check("a big sampled board is added as a starter (maybe near)", "Employer 0902" in mine and r["starters"] == 1
      and "Employer 0902" in directory.record(pid)["starters_pending"])
cos = {c["name"]: c for c in catalog.companies()}
check("the directory's places are stored when they are the whole list", cos["Employer 0005"]["dir"]["all"] is True and cos["Employer 0005"]["dir"]["p"] == [[39.96, -83.0]])
check("... and not when the employer also hires in a state that wasn't loaded", cos["Employer 0904"]["dir"]["all"] is False and cos["Employer 0904"]["dir"]["p"] == [])
check("staffing agencies are marked", cos["Employer 0903"]["sector"] == "Staffing agency")
check("apply() again adds nothing", directory.apply(pid)["added"] == [])
import first_search
order = first_search.due(pid)
check("the first check goes by nearby job count", order[0] == "Employer 0049" and order.index("Employer 0049") < order.index("Employer 0001"))
check("pending = watched and never fetched", len(first_search.pending(pid)) >= 654)
fetch("Employer 0049", ["a"])
check("a fetched company leaves the queue", "Employer 0049" not in first_search.pending(pid))
catalog.remove_company("Employer 0010")
emps.append(emp(700, n=60))
emps[651]["n"] = "Woodmans Inc"                                                             # the directory learned the real name
publish(emps)
r = directory.apply(pid, weekly=True)
check("the weekly refresh adds exactly the newly indexed employer", r["added"] == ["Employer 0700"])
check("a removed employer stays removed", "Employer 0010" not in {c["name"] for c in catalog.companies()})
check("a placeholder name is replaced when the directory learns the real one", r["renamed"] == 1 and "Woodmans Inc" in {c["name"] for c in catalog.companies()})
# the sampled board's first fetch found nothing nearby: pruned, and not offered again right away
fetch("Employer 0902", ["x1"])
with catalog.db() as con:
    con.execute("UPDATE listings SET data=json_set(data, '$.locations', json_array('Cleveland, OH')) WHERE company='Employer 0902'")
check("a starter with nothing nearby is pruned", directory.prune_starters(pid) == ["Employer 0902"])
check("... and not added again next time", "Employer 0902" not in directory.apply(pid)["added"])

# ---------------------------------------------------------------- the builder
from index_build import build, systems, readers, postings
check("systems.parse rejects Workday non-sites", systems.parse("https://acme.wd1.myworkdayjobs.com/robots.txt") is None
      and systems.parse("https://acme.wd1.myworkdayjobs.com/fr-CA") is None)
check("... but still knows the tenant", systems.workday_host("https://acme.wd1.myworkdayjobs.com/robots.txt") == ("acme", "wd1"))
ROBOTS = """Sitemap: https://osu.wd1.myworkdayjobs.com/OSUCareers/siteMap.xml
Sitemap: https://osu.wd1.myworkdayjobs.com/OSUEventJobs/siteMap.xml
Sitemap: https://other.wd1.myworkdayjobs.com/Nope/siteMap.xml

User-agent: *
Allow: /OSUCareers/
Disallow: /refreshFacet/
"""
check("career sites from robots.txt", readers.parse_workday_robots(ROBOTS, "osu.wd1.myworkdayjobs.com") == ["OSUCareers", "OSUEventJobs"])
T = build.Tenants(os.path.join(TMP, "tenants.json.gz"))
T.d[systems.key({"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "robots"})] = {"c": {"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "robots"}, "src": ["cc"]}
T.d[systems.key({"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "osucareers"})] = {"c": {"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "osucareers"}, "src": ["cc"]}
T.d[systems.key({"ats": "workday", "tenant": "fine", "wd": "wd5", "site": "External"})] = {"c": {"ats": "workday", "tenant": "fine", "wd": "wd5", "site": "External"}, "src": ["cc"]}
asked = []
def fake_sites(t, w):
    asked.append(f"{t}.{w}")
    return {"osu.wd1": ["OSUCareers", "OSUEventJobs"], "new.wd3": ["Careers"], "fine.wd5": []}[f"{t}.{w}"]
readers.workday_sites = fake_sites
build.log = lambda *a: None
st = {}
build.workday_sites_pass(T, st, {("new", "wd3")}, 100)
sites = sorted((t["c"]["tenant"], t["c"]["site"]) for t in T.d.values())
check("robots/lang sites are replaced by the tenant's real sites, respellings dropped, new tenants added",
      sites == [("fine", "External"), ("new", "Careers"), ("osu", "OSUCareers"), ("osu", "OSUEventJobs")])
asked.clear()
build.workday_sites_pass(T, st, set(), 100)
check("a tenant's robots.txt is read once", asked == [])

def ten(c, jobs, places, **kw):
    return dict({"c": c, "src": ["cc"], "read": build.today(), "jobs": jobs, "places": places}, **kw)
P1, P2 = [39.96, -83.0, 30, "Columbus, OH", "OH"], [41.5, -81.7, 12, "Cleveland, OH", "OH"]
live = {
    "a": ten({"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "OSUCareers"}, 900, [P1, P2], bname="The Ohio State University"),
    "b": ten({"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "OSUEventJobs"}, 40, [P1], bname="The Ohio State University"),
    "c": ten({"ats": "workday", "tenant": "osu", "wd": "wd1", "site": "Mirror"}, 900, [P1, P2], bname="The Ohio State University"),
    "d": ten({"ats": "greenhouse", "token": "acme"}, 5, [P1]),
    "e": ten({"ats": "ukg", "host": "recruiting.ultipro.com", "tenant": "ABC1000", "board": "11111111-1111-1111-1111-111111111111"}, 20, [P1]),
    "f": ten({"ats": "ukg", "host": "recruiting.ultipro.com", "tenant": "ABC1000", "board": "22222222-2222-2222-2222-222222222222"}, 8, [P2]),
    "g": ten({"ats": "taleo", "host": "uh.taleo.net", "section": "2"}, 50, [P2]),
    "h": ten({"ats": "taleo", "host": "uh.taleo.net", "section": "nursing"}, 30, [P2]),
}
sfx = build.distinct_boards(live)
check("every distinct career site is kept (Workday site, UKG board, Taleo section)", set(sfx) == {"a", "b", "d", "e", "f", "g", "h"})
check("an exact mirror is merged", "c" not in sfx)
check("extra sites carry the site's name", sfx["a"] == "" and sfx["b"] == "OSUEventJobs" and sfx["f"] == "board 2" and sfx["h"] == "nursing")
e = build.entry(live["b"], "OH", sfx["b"])
check("entry: name with the site, states list", e["n"] == "The Ohio State University (OSUEventJobs)" and e["ps"] == ["OH"] and "mb" not in e)
big = ten({"ats": "icims", "base": "https://careers-big.icims.com"}, 5000, [[39.9 + i / 1000, -83.0, 1, f"Place {i}, OH", "OH"] for i in range(200)], sample=True)
e = build.entry(big, "OH")
check("entry: 150 places a state, cut flag, sampled boards are maybe-near", len(e["p"]) == 150 and e["pt"] == 1 and e["mb"] == 1 and e["x"] == 1)
check("entry: a UKG code gets no name (the app describes it)", build.entry(live["e"], "OH")["n"] == "")
check("entry: a board-page title is used", build.entry(dict(live["e"], tname="Woodmans Inc"), "OH")["n"] == "Woodmans")
check("staffing agencies are marked", build.entry(ten({"ats": "greenhouse", "token": "x"}, 5, [P1], pack_name="Acme Staffing Group"), "OH").get("k") == "staffing")
N = readers.name_from_title
check("names from page titles", N("Woodmans Inc - Job Opportunities") == "Woodmans Inc" and N("Careers at University of Doha") == "University of Doha"
      and N("15 Lightyears Inc.") == "15 Lightyears Inc." and N("Acme Careers | Jobs") == "Acme")
check("generic titles give nothing", N("Recruitment") is None and N("Job Board | Dayforce Jobs") is None and N("BambooHR") is None and N("") is None)
check("wants a board title only for code-like addresses", build.wants_board_title(live["e"], None) and not build.wants_board_title(live["d"], None)
      and not build.wants_board_title(live["a"], "The Ohio State University")
      and build.wants_board_title({"c": {"ats": "dayforce", "ns": "chordsdp", "board": "X"}}, None))
pl = build.board_places({"Green": 4, "Columbus": 3, "Akron, OH": 2})
check("a bare small-town word counts when the board names that state elsewhere", {p[3] for p in pl} >= {"Green, OH", "Akron, OH"})
pl = build.board_places({"Green": 4, "Austin, TX": 2})
check("... and is dropped otherwise", "Green, OH" not in {p[3] for p in pl} and "Austin, TX" in {p[3] for p in pl})
check("... and always for a staffing board", "Green, OH" not in {p[3] for p in build.board_places({"Green": 4, "Akron, OH": 2}, staffing=True)})
check("a bare big city still counts", "Chicago, IL" in {p[3] for p in build.board_places({"Chicago": 4})})

# USAJOBS: every state, every page, both ends of a list longer than one search pages through
os.environ["USAJOBS_API_KEY"], os.environ["USAJOBS_EMAIL"] = "test-key", "tester (no address)"
calls = []
def item(i, loc="Columbus, Ohio"):
    return {"MatchedObjectDescriptor": {"PositionTitle": f"Job {i}", "OrganizationName": "Agency", "PositionURI": f"https://www.usajobs.gov/job/{i}",
            "PositionLocation": [{"LocationName": loc}], "PositionRemuneration": [{"MinimumRange": "50000", "MaximumRange": "70000", "RateIntervalCode": "PA"}],
            "PublicationStartDate": "2026-11-01T00:00:00", "UserArea": {"Details": {"JobSummary": "Summary"}}}}
def fake_get(url):
    calls.append(url)
    page = int(url.split("&Page=")[1].split("&")[0])
    if "LocationName=Ohio" in url:
        return {"SearchResult": {"SearchResultCountAll": 1200, "SearchResultItems": [item(i) for i in range((page - 1) * 500, min(1200, page * 500))]}}
    if "LocationName=Texas" in url:      # 25,000 postings: more than one search pages through
        base = 100000 if "SortDirection=asc" in url else 200000 if "SortDirection=desc" in url else 300000
        return {"SearchResult": {"SearchResultCountAll": 25000, "SearchResultItems": [item(base + (page - 1) * 500 + k, "Austin, Texas") for k in range(500)]}}
    if "RemoteIndicator=True" in url:
        return {"SearchResult": {"SearchResultCountAll": 2, "SearchResultItems": [item(3), item(999001, "Anywhere in the U.S. (remote job)")]}}
    return {"SearchResult": {"SearchResultCountAll": 0, "SearchResultItems": []}}
logs = []
js = postings.usajobs(logs.append, get=fake_get)
by = {j["u"]: j for j in js}
check("USAJOBS: one search per state plus remote", sum("LocationName=" in u and "Page=1&" in u and "Sort" not in u for u in calls) == len(postings.US_STATES)
      and any("RemoteIndicator=True" in u for u in calls))
check("USAJOBS: every page of a state", sum(1 for j in js if "Columbus" in " ".join(j["l"])) == 1200)
check("USAJOBS: a list past the paging limit is read from both ends", sum(1 for j in js if "Austin" in " ".join(j["l"])) == 30000 and "Texas" in logs[-1])
check("USAJOBS: remote flag merged onto a posting already seen", by["https://www.usajobs.gov/job/3"]["w"] == "remote" and by["https://www.usajobs.gov/job/999001"]["w"] == "remote")
check("USAJOBS: pay and summary kept, key never in the output", by["https://www.usajobs.gov/job/3"]["pay"] == [50000, 70000] and "test-key" not in json.dumps(js))
del os.environ["USAJOBS_API_KEY"]
check("USAJOBS: skipped cleanly without the secrets", postings.usajobs(lambda m: None, get=fake_get) == [])
os.environ["CAREERONESTOP_TOKEN"], os.environ["CAREERONESTOP_USERID"] = "t", "u"
check("CareerOneStop stays off by default even with keys", postings.careeronestop(["OH"], lambda m: None) == [])
def ss_get(url):
    page = int(url.split("page=")[1].split("&")[0])
    rows = [{"jobId": 1000 + (page - 1) * 100 + k, "employer": "Westerville City Schools", "title": "Teacher", "location": "Westerville, Ohio",
             "displayDate": "2026-11-12T08:00:00"} for k in range(100 if page < 3 else 20)]
    return {"value": {"jobsList": rows}}
ss = postings.schoolspring(lambda m: None, get=ss_get)
check("SchoolSpring: every page, link to the posting", len(ss) == 220 and ss[0]["u"] == "https://www.schoolspring.com/jobs?jobid=1000" and ss[0]["l"] == ["Westerville, Ohio"])
bj = build.bucket_jobs(ss, "schoolspring")
check("SchoolSpring postings land in their state", len(bj.get("OH", [])) == 220)
check("sources carry attribution", all(postings.SOURCES[s][1].get("link") for s in ("usajobs", "schoolspring")))
for sysid, url, want in (("applitrack", "https://www.applitrack.com/dcps/onlineapp/default.aspx", {"ats": "applitrack", "slug": "dcps"}),
                         ("schoolspring", "https://westerville.schoolspring.com/", {"ats": "schoolspring", "sub": "westerville"}),
                         ("jobvite", "https://jobs.jobvite.com/acme-co/jobs", {"ats": "jobvite", "slug": "acme-co"})):
    c = systems.parse(url)
    check(f"{sysid}: a crawled link becomes a board the app can read",
          c is not None and all(c.get(k) == v for k, v in want.items()) and sysid in __import__("ats_public").FETCHERS and systems.BY_ID[sysid].cc)

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
