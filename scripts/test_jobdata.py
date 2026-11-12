"""Offline checks for the facts Siftwell reads from postings (jobtext.py, geo.py, requirements.py, names.py and how
jobfinder / catalog use them): pay (hourly, single values, false positives), levels in any field, remote vs. "not
remote", foreign remote jobs, a bare city name that exists in several states, the one-time re-parse of stored
listings, requirement alternatives, employer display names (and that a rename keeps every listing id, so ratings
stay), the per-employer fetch budget and blank-line clean-up. No network, no Claude. Its own scratch data folder.

    python -X utf8 scripts/test_jobdata.py <scratch dir>
"""
import json, os, shutil, sys, time

if len(sys.argv) < 2:
    sys.exit("usage: python -X utf8 scripts/test_jobdata.py <scratch dir>")
SCRATCH = os.path.abspath(sys.argv[1])
DATA = os.path.join(SCRATCH, "jobdata_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CODEX"] = "1"
os.environ.pop("SIFTWELL_CLAUDE_STUB", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jobtext, geo, people, paths, catalog, jobfinder, requirements, names, claude_cli

fails = 0


def check(label, ok, detail=""):
    global fails
    print(("ok   " if ok else "FAIL ") + label + (f"   [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


# ------------------------------------------------------------------ 3. pay
P = jobtext.parse_pay
def pay(s):
    p = P(s)
    return (p["lo"], p["hi"], p["unit"]) if p else None

CASES = [("$36.90/hr", (36.90, 36.90, "hour")), ("Pay: $18.50 - $22.75 per hour", (18.50, 22.75, "hour")),
         ("$25.00 - $38.00 an hour", (25.0, 38.0, "hour")), ("$17/hour", (17, 17, "hour")),
         ("Starting at $19.25 per hour", (19.25, 19.25, "hour")), ("Up to $41.00 Per Hour", (41.0, 41.0, "hour")),
         ("$40,000 per year", (40000, 40000, "year")), ("Salary range: $95,000 - $120,000", (95000, 120000, "year")),
         ("The base salary is from $95,000/year in our lowest region up to $135,000", (95000, 135000, "year")),
         ("$120k - $180k", (120000, 180000, "year")), ("$120 - $180k base", (120000, 180000, "year")),
         ("Min\nUSD $45,000.00/Yr.\n\nMax\nUSD $50,000.00/Yr.", (45000, 50000, "year")),
         ("Pay Range $13.50 - $15.25", (13.50, 15.25, "hour")), ("Weekly pay of $1,250 per week", (1250, 1250, "week")),
         ("$5,200 - $6,100 per month", (5200, 6100, "month")), ("between $28 and $34 per hour", (28, 34, "hour")),
         ("Hourly rate: $22.00", (22.0, 22.0, "hour")), ("Annual salary: $65,000", (65000, 65000, "year")),
         ("Compensation: $31.25/hr - $46.88/hr", (31.25, 46.88, "hour")), ("$52,000.00 - $58,500.00 annually", (52000, 58500, "year"))]
bad = [(s, pay(s)) for s, want in CASES if want is not None and pay(s) != want]
check(f"{len(CASES)} ways of writing pay are read (cents, single values, hour / week / month / year)", not bad, str(bad))
NOT_PAY = ["$5,000 sign-on bonus", "Up to $5,000 sign-on bonus for experienced nurses", "401k with company match up to $4,000",
           "We are a $2 billion company", "revenue of $40,000,000 last year", "manages a budget of $250,000 per year",
           "$10M ARR and growing", "tuition reimbursement up to $5,250 per year", "$2.00 per hour shift differential",
           "an additional $3.00 per hour for night shift", "Referral bonus: $1,500", "$500 retention bonus", "401k",
           "$20 gift card", "over $300,000 in sales per year", "a $50 monthly phone stipend", "Costs $15 per month",
           "sign-on bonus of $10,000 - $15,000"]
bad = [(s, pay(s)) for s in NOT_PAY if pay(s) is not None]
check(f"{len(NOT_PAY)} dollar amounts that are not base pay are left alone (bonus, 401k, revenue, differential)", not bad, str(bad))
check("the real pay wins over a bonus in the same posting",
      pay("Benefits: 401k match. $7,500 sign-on bonus!\nPay: $34.10 - $51.15 per hour based on experience.") == (34.10, 51.15, "hour"))
p = P("$36.90/hr")
check("hourly pay is annualised at 2,080 hours for comparisons", p["annual_lo"] == round(36.90 * 2080) and p["annual_hi"] == round(36.90 * 2080))
check("hourly pay reads as hourly, yearly in thousands",
      jobtext.pay_label(36.9, 36.9, "hour") == "$36.90/hr" and jobtext.pay_label(18.5, 22.75, "hour") == "$18.50–$22.75/hr"
      and jobtext.pay_label(17, 17, "hour") == "$17/hr" and jobtext.pay_label(45000, 52000, "year") == "$45k–$52k",
      jobtext.pay_label(18.5, 22.75, "hour"))
s = jobfinder.parse_salary("$18.50 - $22.75 per hour")
check("jobfinder.parse_salary keeps its (low, high, text) shape, annualised", s[:2] == (18.50 * 2080, 22.75 * 2080) and "18.50" in s[2] and s[3] == "hour")
check("old behaviour kept: no pay -> None", jobfinder.parse_salary("Great benefits and a fun team") is None)


def listing(title="Registered Nurse", loc="Columbus, OH", wp="", desc="", co="X", jid=None):
    return jobfinder.J({"name": co}, title, "https://example.com/j/" + (jid or title), [loc] if isinstance(loc, str) else loc, wp, None, desc, "", "", jid or title)


j = jobfinder.prepare_listing(listing(desc="Join us. Pay: $36.90/hr. Full time."), {"name": "X"})
check("a stored listing carries the unit, the hourly figures and an annualised range",
      j["pay_unit"] == "hour" and j["pay_min"] == 36.9 and j["pay_max"] == 36.9 and j["salary_min"] == j["salary_max"] == round(36.9 * 2080)
      and j["salary_mid"] == round(36.9 * 2080), str({k: j.get(k) for k in ("pay_unit", "pay_min", "salary_min", "salary_mid")}))
j = jobfinder.prepare_listing(listing(title="Line Cook - $17/hour", desc="Busy kitchen."), {"name": "X"})
check("pay in the title is read when the text has none", j["pay_unit"] == "hour" and j["pay_min"] == 17)
j = jobfinder.prepare_listing(listing(desc="Salary $45,000 - $52,000 per year"), {"name": "X"})
check("yearly pay: unit year, salary fields as before", j["pay_unit"] == "year" and (j["salary_min"], j["salary_max"]) == (45000, 52000))

# ------------------------------------------------------------------ 4. levels
TL = jobtext.title_level
UNKNOWN = ["Staff RN", "Staff Nurse", "IV Therapy Nurse", "Staff Accountant", "Research Fellow", "Registered Nurse", "Electrician",
           "Office Manager", "Staff Pharmacist", "Postdoctoral Fellow", "Support Staff", "Cashier - Store 616", "RN - 4 West",
           "Machine Operator 2nd Shift", "Head Start Teacher", "Lead Generation Specialist", "Case Manager", "Title I Teacher",
           "4th Grade Teacher", "Staff Attorney", "Member of Technical Staff", "Funeral Director"]
bad = [(t, TL(t)) for t in UNKNOWN if TL(t) is not None]
check(f"{len(UNKNOWN)} titles that state no level stay unknown (Staff RN, IV Therapy Nurse, Research Fellow...)", not bad, str(bad))
LEVELS = {"Electrician 1": 1, "Accountant I": 1, "Apprentice Electrician": 1, "Electrician Apprentice": 1, "Management Trainee": 1,
          "Junior Accountant": 1, "Jr. Developer": 1, "Entry-Level Office Assistant": 1, "Electrician Helper": 1,
          "New Grad RN": 1, "Graduate Nurse": 1, "Marketing Intern": 1, "Nurse II - Night Shift": 2, "Electrician 2": 2,
          "Journeyman Electrician": 2, "Mid-Level Engineer": 2, "Senior Accountant": 3, "Sr. Electrician": 3, "Accountant III": 3,
          "Maintenance Technician Level 3": 3, "Staff Engineer": 4, "Staff Software Engineer": 4, "Lead Electrician": 4,
          "Nurse Manager": 4, "Charge Nurse": 4, "Electrical Foreman": 4, "Software Engineer IV": 4, "Head Cashier": 4,
          "Engineering Manager": 4, "Shift Supervisor": 4, "Senior Staff Engineer": 5, "Principal Engineer": 5, "Senior Manager": 5,
          "Assistant Director of Nursing": 5, "Director of Nursing": 6, "Head of Operations": 6, "Vice President, Sales": 7,
          "Chief Nursing Officer": 7, "Technical Fellow, Engineering": 7}
bad = [(t, TL(t), w) for t, w in LEVELS.items() if TL(t) != w]
check(f"{len(LEVELS)} titles get a sane level in any field (entry level exists; 'staff' is senior only for engineers)", not bad, str(bad))
YL = jobtext.years_level
check("years: 0-1 entry, 2-4 mid, 5+ senior, never a manager from years alone",
      [YL(0), YL(1), YL(2), YL(4), YL(5), YL(9), YL(15), YL(None)] == [1, 1, 2, 2, 3, 3, 3, None])
check("'0-1 years of experience' and 'no experience required' are entry level",
      jobtext.seniority("Dietary Aide", "Requires 0-1 years of experience in food service.") == (1, "years")
      and jobtext.seniority("Warehouse Associate", "No experience required. We will train you.") == (1, "years")
      and jobtext.seniority("Registered Nurse", "Minimum 2 years of experience in acute care.") == (2, "years")
      and jobtext.seniority("Registered Nurse", "Caring team.") == (None, ""))
check("jobfinder still offers title_level / years_level / LEVEL_NAMES (setup uses them)",
      jobfinder.title_level("Staff RN") is None and jobfinder.years_level(8) == 3 and jobfinder.LEVEL_NAMES[1] == "Entry level")
import setup_flow
g = setup_flow.infer_level({"experience": [{"title": "Staff RN"}], "years_experience": 8})
check("the setup hint never tells a staff RN 'Lead / Manager'", not g or g["level"] <= 3, str(g))
g = setup_flow.infer_level({"experience": [{"title": "Nurse Manager"}], "years_experience": 12})
check("...but a nurse manager still gets it", bool(g) and g["level"] == 4, str(g))

# ------------------------------------------------------------------ 2. remote / not remote
W = lambda v: jobtext.workplace_label(v, typed=True)
WP = {"Office Worker (NOT Remote)": "onsite", "Remote work is not available": "onsite", "Remote work is an option": "hybrid",
      "Remote work only": "remote", "Remote": "remote", "Fully Remote": "remote", "Hybrid": "hybrid", "On-Site": "onsite",
      "Onsite": "onsite", "Non-Remote": "onsite", "No Remote": "onsite", "Not Remote": "onsite", "In Person": "onsite",
      "In office": "onsite", "Remote: No": "onsite", "Hybrid (not fully remote)": "hybrid", "Work from home": "remote",
      "Telecommute": "remote", "Remote - US": "remote", "": "", "Flexible": ""}
bad = [(k, W(k), v) for k, v in WP.items() if W(k) != v]
check(f"{len(WP)} workplace values are read with negation first", not bad, str(bad))
check("location labels: 'Not Remote', 'Remote: No', 'Virtual Care Center' are not remote; 'Remote', 'US - Remote' are",
      jobfinder.is_remote_us("Remote") and jobfinder.is_remote_us("US - Remote") and jobfinder.is_remote_us("Work from home")
      and not jobfinder.is_remote_us("Not Remote") and not jobfinder.is_remote_us("Non-Remote - Dallas, TX")
      and not jobfinder.is_remote_us("Remote: No") and not jobfinder.is_remote_us("Virtual Care Center, Columbus, OH")
      and not jobfinder.is_remote_us("Little Rock"))
check("foreign remote labels are not US-remote",
      not any(jobfinder.is_remote_us(x) for x in ("Remote, Poland", "Remote - Belfast, UK", "Remote (Denmark)", "Remote, PL", "UK - Remote", "Remote, GB")))
check("'Remote, GA' / 'Remote - IN' (US states) stay US-remote", jobfinder.is_remote_us("Remote, GA") and jobfinder.is_remote_us("Remote, PA"))
icims = {"jobLocationType": "TELECOMMUTE", "jobLocation": [{"address": {"streetAddress": "1125 Fulton Street", "addressLocality": "Brooklyn", "addressRegion": "NY"}}]}
check("iCIMS: TELECOMMUTE on a posting with a street address is not remote", not jobtext.telecommute(icims))
check("...a real remote posting (no street, or applicant location rules) is",
      jobtext.telecommute({"jobLocationType": "TELECOMMUTE"}) and jobtext.telecommute(dict(icims, applicantLocationRequirements={"name": "USA"}))
      and jobtext.telecommute({"jobLocationType": "TELECOMMUTE", "jobLocation": {"address": {"streetAddress": "UNAVAILABLE", "addressRegion": "OH"}}}))
C = {"name": "X"}
j = jobfinder.prepare_listing(listing("Retail Sales Consultant", "Columbus, OH", jobtext.workplace_label("Office Worker (NOT Remote)")), C)
check("AT&T-style 'Office Worker (NOT Remote)' is stored on-site, not remote", j["workplace"] == "onsite" and not j["remote_strict"])
j = jobfinder.prepare_listing(listing("Customer Success Manager – Belfast, UK", "Remote", "remote"), C)
check("a remote posting whose title names a foreign place is not US-remote", j is None or not j["remote_strict"], str(j and j["remote_strict"]))
j = jobfinder.prepare_listing(listing("Support Engineer", "Aarhus, Denmark", "remote"), C)
check("remote + a foreign location: dropped", j is None)
j = jobfinder.prepare_listing(listing("Support Engineer (Remote)", "Remote, Poland", "remote"), C)
check("'Remote, Poland': dropped", j is None)
j = jobfinder.prepare_listing(listing("Support Engineer - Remote", "Remote", "remote"), C)
check("a plain US remote posting is still remote", j is not None and j["remote_strict"] and j["workplace"] == "remote")
j = jobfinder.prepare_listing(listing("Account Manager - Dublin, OH", "Remote", "remote"), C)
check("a US town in the title doesn't stop a remote job", j is not None and j["remote_strict"])

# ------------------------------------------------------------------ 8. blank lines; titles
t = "Line one\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\nLine two\n \n\t\n\nLine three\nLine four"
check("16 newlines in a row collapse to one blank line", jobtext.clean_text(t) == "Line one\n\nLine two\n\nLine three\nLine four")
check("strip_html does it at ingest", "\n\n\n" not in jobfinder.strip_html("<p>A</p><p></p><p> </p><br><br><br><br><div>B</div>"))
T = {"006356-Maintenance Electrician 1": "Maintenance Electrician 1", "R0088425 - Registered Dietitian": "Registered Dietitian",
     "(12345) Office Clerk": "Office Clerk", "JR-10234: Data Analyst": "Data Analyst", "911 Dispatcher": "911 Dispatcher",
     "3rd Shift Welder": "3rd Shift Welder", "401k Specialist": "401k Specialist", "Electrician 1": "Electrician 1",
     "Nurse II - Night Shift": "Nurse II - Night Shift", "Staff Nurse - R0012345": "Staff Nurse", "Welder (Req #204418)": "Welder",
     "2026-19146 Generalist": "Generalist", "1st Grade Teacher": "1st Grade Teacher", "24/7 Support Agent": "24/7 Support Agent"}
bad = [(k, jobtext.clean_title(k)) for k, v in T.items() if jobtext.clean_title(k) != v]
check("requisition codes are stripped from titles; real numbers stay", not bad, str(bad))
j = listing("006356-Maintenance Electrician 1", jid="e1")
check("J() stores the clean title; the id doesn't depend on it", j["title"] == "Maintenance Electrician 1" and j["id"] == "X::e1")
check("...and the level is read from it", jobtext.title_level(j["title"]) == 1)

# ==== part 2 ====

# ------------------------------------------------------------------ 1. a bare city name needs support
home = geo.geocode_home("43215")
kinds = lambda s: [(h.kind, h.label) for h in geo.locate_all(s)]
check("'Columbus' alone is a guess (kind 'bare'), with or without other words around it",
      kinds("Columbus") == [("bare", "Columbus, OH")] and ("bare", "Columbus, OH") in kinds("01054 - Piedmont Columbus Midtown Acute")
      and kinds("Columbus Healthcare Center") == [("bare", "Columbus, OH")])
check("labelled places are as sure as before", kinds("Dublin, OH") == [("place", "Dublin, OH")] and kinds("Columbus, GA") == [("place", "Columbus, GA")]
      and kinds("US-OH-Columbus") == [("place", "Columbus, OH")] and kinds("Columbus OH") == [("place", "Columbus, OH")])
check("a city with no namesake of any size stays a plain place", kinds("Chicago") == [("place", "Chicago, IL")] and kinds("Westerville") == [("place", "Westerville, OH")])
check("within(): strict callers place a bare name only in a backed state",
      not geo.within(["Columbus"], home, 35, states=set())[0] and not geo.within(["Columbus"], home, 35, states={"GA"})[0]
      and geo.within(["Columbus"], home, 35, states={"OH"})[0] and geo.within(["Springfield"], home, 60, states={"OH"})[0])
check("within() without context reads it as it always did", geo.within(["Columbus"], home, 35)[0] and not geo.within(["Springfield"], home, 60)[0])
check("typing 'Columbus' as a home still means the big one", geo.geocode_home("Columbus")[2] == "Columbus, OH")
check("a bare name nobody could place names no place", jobfinder.vague_location("Columbus") and not jobfinder.vague_location("Columbus, OH"))

catalog.migrate(log=lambda *a: None)
people.add("Nora")
PID = people.ids()[-1]
people.save_settings({"home_zip": "43215", "radius_miles": 35}, PID)


def company(name, **kw):
    e = {"name": name, "ats": "greenhouse", "token": name.lower().replace(" ", ""), "tier": "dmv_office", "sector": "x", "sets": [f"own-{PID}"]}
    e.update(kw)
    catalog.save_company(e)
    return e


def store(co, jobs):
    c = next(x for x in catalog.companies() if x["name"] == co)
    with catalog.db() as con:
        out = [jobfinder.prepare_listing(jobfinder.J(c, t, "https://example.com/" + jid, locs, wp, None, desc, "", "", jid), c)
               for jid, t, locs, wp, desc in jobs]
        catalog.record_fetch(co, {"status": "ok", "raw_jobs": len(out), "secs": 1}, [o for o in out if o], con)


company("Team Georgia")          # the state agency: only Georgia postings
company("Kidney Care National")  # hires in both Columbus, OH and Columbus, GA
company("Buckeye Clinics")       # only Ohio
company("Nowhere Named")         # nothing to go on
company("Georgia-Pacific")       # the name must not count as a state
company("The Ohio State University")   # a state in the name must not hide the Ohio its postings name
company("Local Health", dir={"all": True, "p": [[39.96, -83.0], [40.1, -83.1]], "st": ["OH"], "lab": "Columbus, OH"})
GA_TEXT = "Join Team Georgia! Applicants must hold a current Georgia license as a Registered Nurse. State of Georgia benefits."
store("Team Georgia", [("g1", "Registered Nurse", ["Columbus"], "", GA_TEXT), ("g2", "Nurse Manager", ["Atlanta, GA"], "", GA_TEXT)])
store("Kidney Care National", [("k1", "Staff RN", ["01054 - Piedmont Columbus Midtown Acute"], "", "Dialysis RN. Current Georgia license required."),
                               ("k2", "Staff RN", ["Columbus Healthcare Center"], "", "Dialysis RN for our Ohio clinic. Ohio RN license."),
                               ("k3", "Staff RN", ["Columbus"], "", "Dialysis RN. Great team."),
                               ("k4", "PCT", ["Columbus, OH"], "", "x"), ("k5", "PCT", ["Columbus, GA"], "", "x")])
store("Buckeye Clinics", [("b1", "RN", ["Columbus"], "", "Great team."), ("b2", "RN", ["Dayton, OH"], "", "x"), ("b3", "RN", ["Dublin, OH"], "", "x")])
store("Nowhere Named", [("n1", "RN", ["Columbus"], "", "Great team.")])
store("Georgia-Pacific", [("p1", "Electrician", ["Columbus"], "", "Georgia-Pacific is hiring. Georgia-Pacific makes paper."), ("p2", "Electrician", ["Columbus, OH"], "", "x")])
store("The Ohio State University", [("u1", "Outpatient RN", ["Columbus Campus"], "", "The Ohio State University Wexner Medical Center. Requires a current Ohio RN license. Columbus, OH 43210.")])
store("Local Health", [("l1", "RN", ["Columbus"], "", "Great team."), ("l2", "RN", ["Main Campus"], "", "x")])
pc, prof, st = jobfinder.person_cfg(PID)
jobfinder.use_cfg(pc)
people.set_current(PID, process_wide=True)
pool = catalog.open_listings(lazy=True)
got = {j["id"].split("::")[1]: j for j in jobfinder.select_for_person(pool)}
check("Georgia postings at a bare 'Columbus' are not on an Ohio board (the posting names Georgia)", "g1" not in got and "k1" not in got, str(sorted(got)))
check("'Columbus Healthcare Center' + a posting that says Ohio: near", "k2" in got)
check("an employer in both Columbus, OH and Columbus, GA with nothing in the text: unplaced, so not shown", "k3" not in got)
check("labelled places are untouched: 'Columbus, OH' in, 'Columbus, GA' out", "k4" in got and "k5" not in got)
check("an employer that only hires in Ohio: its bare 'Columbus' is Columbus, OH", "b1" in got and "b3" in got)
check("no support at all: unplaced", "n1" not in got)
check("a state in the company's name is not support ('Georgia-Pacific'): its other postings decide", "p1" in got)
check("'Columbus Campus' at The Ohio State University, whose posting names Ohio: near", "u1" in got)
check("an all-nearby employer still shows a posting that names no place", "l2" in got and "l1" in got)
check("the stored listing remembers the states its text names", next(j for j in pool if j["id"].endswith("::g1"))["loc_st"] == ["GA"])

# ------------------------------------------------------------------ 6. requirements: higher covers lower, alternatives
RN = {"degrees": [{"level": "bachelor", "field": "Nursing", "field_group": "nursing", "completed": True}],
      "licenses": [{"name": "Registered Nurse (RN), Ohio", "kind": "license"}]}
RN_NODEG = {"degrees": [], "licenses": [{"name": "RN - Ohio", "kind": "license"}]}
LPN = {"degrees": [{"level": "associate", "field": "Practical Nursing", "field_group": "nursing", "completed": True}],
       "licenses": [{"name": "LPN - Ohio", "kind": "license"}]}
rq = lambda text, hl: requirements.check(requirements.parse(text, "Registered Nurse"), hl)
check("an RN meets 'Current Ohio LPN License' (RN >= LPN)", rq("Requirements:\nCurrent Ohio LPN License\nBLS certification", RN)["status"] == "ok")
r = rq("Qualifications:\n- Current Ohio RN license required. We will consider other designations like LPN.", RN)
check("'will consider other designations like LPN' doesn't ask an RN for an LPN license", r["status"] == "ok" and not r["chips"], str(r))
r = rq("Qualifications:\n- Current Ohio RN license required. We will consider other designations like LPN.", LPN)
check("...and an LPN is not hidden from that job", r["status"] == "ok", str(r))
r = rq("Must have a current RN or LPN license in the State of Ohio.", LPN)
check("'RN or LPN license': either one meets it", r["status"] == "ok" and not r["chips"], str(r))
check("an LPN is still asked for an RN license when only RN is named", rq("Requirements:\nCurrent Ohio RN license required.", LPN)["status"] in ("flag", "unmet"))
r = rq("Requirements:\n- Associate's in Nursing required\n- Current Ohio RN license", RN)
check("a BSN meets \"Associate's in Nursing\" (BSN >= ADN)", r["status"] == "ok" and not r["chips"], str(r))
check("'ADN or BSN' is met by an associate degree", rq("Required: ADN or BSN from an accredited school of nursing.", LPN)["status"] == "ok")
r = rq("Minimum Qualifications: Associate's in Nursing.", RN_NODEG)
check("an RN license with no degree on file is not flagged for a nursing associate degree", r["status"] == "ok", str(r))
check("a master's requirement is still not met by a bachelor's", rq("Requirements: Master's degree in Nursing required.", RN)["status"] == "unmet")
check("'Sales Associate in our store' is not an associate degree", not requirements.parse("You will work as a Sales Associate in our store. Associates in the warehouse help.", "Sales Associate")["degrees"])
ACC = {"degrees": [{"level": "master", "field": "Accounting", "field_group": "accounting", "completed": True}], "licenses": []}
check("Master's >= Bachelor's", rq("Requirements: Bachelor's degree in Accounting required.", ACC)["status"] == "ok")

# ------------------------------------------------------------------ 5. employer names
N = names
POOR = ["", "Employer in Columbus OH (ADP 0330de)", "07e0 416d A243 7556983c79c7", "Cameronmitchell", "Acecashexpress", "Osuphysicians",
        "10 Nationwide Children's Hospital", "AB3 Nationwide Life Insurance", "(5100) Genzyme", "(USA) Ecolab", "5H0 Hub International",
        "82-3070213 ServiceMac", "W2B Skechers USA Retail", "Agency", "Homepage", "Jobs Selectmedicalcorp", "Juvenile Justice Department of",
        "Hondros (board 2)", "ISD ISD Renal", "Installedbuildingproducts", "Brightviewhealth", "0101 The Huntington National Bank"]
bad = [n for n in POOR if not N.poor(n)]
check(f"{len(POOR)} code-like / placeholder names are recognised", not bad, str(bad))
GOOD = ["7-Eleven", "3M", "1-800-Flowers", "84 Lumber", "24 Hour Fitness", "OhioHealth", "Nationwide Children's Hospital", "AT&T", "CVS Health",
        "Accenture", "Department of Juvenile Justice", "Internal Medicine Associates", "Jobs for the Future", "PNC Financial Services",
        "A123 Systems", "Bath & Body Works", "U.S. Bank", "Target", "Walmart", "L.L.Bean", "T-Mobile", "2020 Companies", "Five Below",
        "City of Columbus", "The Ohio State University", "Cardinal Health", "DaVita", "360 Behavioral Health", "K12 Inc"]
bad = [(n, N.poor(n)) for n in GOOD if N.poor(n)]
check(f"{len(GOOD)} real names are left alone (7-Eleven, 3M, 1-800-Flowers, 84 Lumber...)", not bad, str(bad))
CLEAN = {"10 Nationwide Children's Hospital": "Nationwide Children's Hospital", "AB3 Nationwide Life Insurance": "Nationwide Life Insurance",
         "(5100) Genzyme": "Genzyme", "(USA) Ecolab": "Ecolab", "5H0 Hub International": "Hub International",
         "82-3070213 ServiceMac": "ServiceMac", "W2B Skechers USA Retail": "Skechers USA Retail",
         "Juvenile Justice Department of": "Department of Juvenile Justice", "Juvenile Justice, Department of": "Department of Juvenile Justice",
         "Hondros (board 2)": "Hondros", "0101 The Huntington National Bank": "The Huntington National Bank",
         "Acme Holdings LLC d/b/a Sunny Day Care": "Sunny Day Care", "MCK McKesson Corporation": "McKesson Corporation",
         "7-Eleven": "7-Eleven", "3M": "3M", "1-800-Flowers": "1-800-Flowers", "84 Lumber": "84 Lumber", "Ohio, State of": "State of Ohio"}
bad = [(k, N.clean_display(k)) for k, v in CLEAN.items() if N.clean_display(k) != v]
check("codes, 'd/b/a' and comma-inverted names are cleaned safely", not bad, str(bad))
CM = ["Server\nCameron Mitchell Restaurants is hiring servers. At Cameron Mitchell, great people deliver genuine hospitality.",
      "Line Cook\nJoin Cameron Mitchell Restaurants! Cameron Mitchell Restaurants is an equal opportunity employer.",
      "Host\nCameron Mitchell Restaurants (CMR) is growing."]
check("a run-together address is split the way the postings write it", N.split_slug("cameronmitchell", CM) == "Cameron Mitchell", str(N.split_slug("cameronmitchell", CM)))
check("...and gets their capitals", N.split_slug("davita", ["DaVita is hiring. Join DaVita today", "At DaVita we care"]) == "DaVita")
check("derive: a slug name becomes the spelled-out one", N.derive("Cameronmitchell", {"ats": "ukg", "tenant": "CAM1000", "board": "b"}, CM) == "Cameron Mitchell")
DV = ["Patient Care Technician\nDaVita is seeking a PCT. DaVita is an equal opportunity employer.", "RN\nJoin DaVita. Renal care.", "Biomed\nDaVita teammates."]
check("derive: a Workday subsidiary code gives way to the tenant the postings name ('ISD ISD Renal' = DaVita)",
      N.derive("ISD ISD Renal", {"ats": "workday", "tenant": "davita", "wd": "wd1", "site": "DKC_External"}, DV) == "DaVita",
      str(N.derive("ISD ISD Renal", {"ats": "workday", "tenant": "davita", "wd": "wd1", "site": "DKC_External"}, DV)))
check("derive: a code prefix is dropped but the real legal name stays",
      N.derive("0101 The Huntington National Bank", {"ats": "workday", "tenant": "huntington", "wd": "wd12", "site": "HNBcareers"},
               ["Teller\nHuntington is hiring. The Huntington National Bank is an Equal Opportunity Employer."] * 3) == "The Huntington National Bank")
UDF = ["Food Lead\nUnited Dairy Farmers is an equal opportunity employer. About United Dairy Farmers: ice cream since 1940.",
       "Cashier\nUnited Dairy Farmers is seeking friendly cashiers.", "Manager\nJoin United Dairy Farmers today, we are hiring."]
check("derive: a placeholder gets the name its postings state", N.derive("Employer in Columbus OH (UKG uni110)", {"ats": "ukg", "tenant": "UNI1101UDFI", "board": "x"}, UDF) == "United Dairy Farmers",
      str(N.derive("Employer in Columbus OH (UKG uni110)", {"ats": "ukg", "tenant": "UNI1101UDFI", "board": "x"}, UDF)))
check("derive: the board page's title names a code-only board", N.derive("Employer (Paylocity 6997ff)", {"ats": "paylocity", "id": "6997ffbe-94a8-44cb-8ba7-1de69dc5abf6"}, [], board_title="Dewey&#39;s Pizza - Job Opportunities") == "Dewey's Pizza")
check("derive: no text at all: a business word is split off the address", N.derive("Brightviewhealth", {"ats": "icims", "base": "https://careers-brightviewhealth.icims.com"}, []) == "Brightview Health")
ACE = ["Valet\nACE Parking is an Affirmative Action employer. Park cars downtown.", "Cashier\nJoin Ace Parking as a cashier in our garage.",
       "Site Manager\nThis position supervises staff. Ace Parking Management offers benefits.", "Attendant\nWe are hiring. All Applicants Welcome here."]
check("derive: a UKG code starts with the employer's first letters ('ACE1005APMI' = Ace Parking)",
      N.derive("Employer in Columbus OH (UKG ace100)", {"ats": "ukg", "tenant": "ACE1005APMI", "board": "b"}, ACE) in ("Ace Parking", "ACE Parking"),
      str(N.derive("Employer in Columbus OH (UKG ace100)", {"ats": "ukg", "tenant": "ACE1005APMI", "board": "b"}, ACE)))
MC = ["Tech\nJoining Micro Center means more. At Micro Center, we care.", "Sales\nMICRO CENTER is the nation's leading retailer. Life at Micro Center is great.",
      "Cashier\nMicro Center is hiring cashiers now."]
check("derive: a one-word name the postings write as two is spelled their way ('Microcenter' -> 'Micro Center')",
      N.derive("Microcenter", {"ats": "ukg", "tenant": "MIC1003MEI", "board": "b"}, MC) == "Micro Center")
check("derive: a page title in capitals with LLC is tidied", N.derive("Employer (Paylocity 33704a)", {"ats": "paylocity", "id": "33704aa8-8475-45e8-b8a8-55e4d6765e36"}, [], board_title="NEMEAN SOLUTIONS LLC - Job Opportunities") == "Nemean Solutions")
check("derive: a good name is never touched", N.derive("OhioHealth", {"ats": "workday", "tenant": "ohiohealth", "wd": "wd5", "site": "x"}, DV) is None
      and N.derive("7-Eleven", {}, CM) is None and N.derive("3M", {}, []) is None)
check("derive: nothing known -> None (the placeholder stays)", N.derive("Employer in Columbus OH (ADP 0330de)", {"ats": "adp", "cid": "0330dee1-d933-49d0-9a55-3d0d5b7b0b3f"}, []) is None)
import company_add
check("space-separated GUID pieces are a code", company_add.looks_like_code("07e0 416d A243 7556983c79c7") and not company_add.looks_like_code("Dead Beef Cafe")
      and not company_add.looks_like_code("84 Lumber") and not company_add.looks_like_code("Ace Hardware"))

# a rename keeps every listing id (so ratings, marks and first-seen dates stay with their jobs)
company("Cameronmitchell", ats="ukg", host="recruiting.ultipro.com", tenant="CAM1000CMR", board="b1")
store("Cameronmitchell", [("c1", "Server", ["Columbus, OH"], "", CM[0].split("\n", 1)[1] * 3), ("c2", "Line Cook", ["Dublin, OH"], "", CM[1].split("\n", 1)[1] * 3),
                          ("c3", "Host", ["Columbus, OH"], "", CM[2].split("\n", 1)[1] * 4)])
ids_before = sorted(j["id"] for j in catalog.open_listings() if j["company"] == "Cameronmitchell")
import ai_score
paths.dump_json_atomic(ai_score.CACHE, {"v": 3, "rating_format": ai_score.RATING_FORMAT, "by_profile": {"ph": {ids_before[0]: {"haiku": {"fit": 77}}}}})
new_name = jobfinder.learn_company_name("Cameronmitchell")
after = [j for j in catalog.open_listings() if j["company"] == new_name]
check("after a fetch a slug name is learned from the postings", new_name == "Cameron Mitchell", new_name)
check("...its listings follow and keep their ids", sorted(j["id"] for j in after) == ids_before and len(after) == 3, str([j["id"] for j in after]))
check("...so a stored rating still belongs to its job", ids_before[0] in ai_score.load_all()["by_profile"]["ph"] and any(j["id"] == ids_before[0] for j in after))
c2 = next(x for x in catalog.companies() if x["name"] == "Cameron Mitchell")
j2 = jobfinder.J(c2, "Server", "https://example.com/c1", ["Columbus, OH"], "", None, "x", "", "", "c1")
check("...and the next fetch produces the same ids under the new name", j2["id"] == ids_before[0] and j2["company"] == "Cameron Mitchell" and c2.get("idp") == "Cameronmitchell")
check("the board's identity is unchanged by a rename", catalog.ats_key(c2) == catalog.ats_key({k: v for k, v in c2.items() if k not in ("idp", "nm")}))
check("a learned name is settled: not looked at again", c2.get("nm") == 1 and jobfinder.learn_company_name("Cameron Mitchell") == "Cameron Mitchell")
company("Zed Typed", nm=1, ats="ukg", host="recruiting.ultipro.com", tenant="ZED1", board="b")
store("Zed Typed", [("z1", "Server", ["Columbus, OH"], "", CM[0] * 3)])
check("a name the person typed is never renamed", jobfinder.learn_company_name("Zed Typed") == "Zed Typed")
company("Cameronmitchell")
c3 = next(x for x in catalog.companies() if x["name"] == "Cameronmitchell")
check("a new company that takes the old name can't collide with the renamed one's ids", jobfinder.J(c3, "x", "u", [], "", None, "", "", "", "c1")["id"] != ids_before[0])

# ------------------------------------------------------------------ 2b. stored listings are read again once (no ratings lost)
company("Old Workday", ats="workday", tenant="oldco", wd="wd1", site="Ext")
OLD = [("o1", "Retail Sales Consultant", ["Dallas, TX"], "remote", "Sell phones in our store.\n\n\n\n\n\n\n\nPay: $18.50 - $22.75 per hour"),
       ("o2", "Support Engineer", ["Remote"], "remote", "This role is remote. $95,000 - $120,000"),
       ("o3", "Staff RN", ["Columbus, OH"], "", "Hospital nursing. 2 years of experience required."),
       ("o4", "Support Engineer", ["Remote, Poland"], "remote", "Remote in Poland.")]
with catalog.db() as con:
    for jid, t, locs, wp, desc in OLD:   # rows as an earlier version stored them: old flags, old level, no pay, no "pv"
        d = {"id": f"Old Workday::{jid}", "company": "Old Workday", "title": t, "url": "https://example.com/" + jid, "locations": locs,
             "workplace": wp, "base_wp": wp, "remote_strict": wp == "remote", "remote_bare": False, "local_unnamed": False,
             "salary_min": None, "salary_max": None, "salary_text": "", "level": 4 if "Staff" in t else None, "level_src": "title",
             "sector": "", "tier": "", "dept": "", "posted": "", "desc": desc, "snippet": desc[:600]}
        catalog.put_listing(con, d, first_seen="2026-01-05", last_seen="2026-11-01")
catalog.set_meta("parse_version", 1)
n = jobfinder.reparse_stored(log=lambda m: None)
rows = {}
with catalog.db() as con:
    for r in con.execute("SELECT id, data, desc, first_seen, closed_at, desc_hash FROM listings WHERE company='Old Workday'"):
        rows[r["id"].split("::")[1]] = (json.loads(r["data"]), r["desc"], r["first_seen"], r["closed_at"], r["desc_hash"])
check("the one-time re-read ran over every open listing", n >= 4 and catalog.get_meta("parse_version") == jobtext.PARSE_VERSION)
check("a Workday 'remote' that nothing in the posting backs is no longer remote, and is asked for again at the next fetch",
      rows["o1"][0]["remote_strict"] is False and rows["o1"][0]["base_wp"] == "" and rows["o1"][4] == "")
check("a real remote posting stays remote", rows["o2"][0]["remote_strict"] is True and rows["o2"][0]["workplace"] == "remote" and rows["o2"][4] != "")
check("hourly pay is found in the stored text", rows["o1"][0]["pay_unit"] == "hour" and rows["o1"][0]["pay_min"] == 18.5 and rows["o1"][0]["salary_max"] == round(22.75 * 2080))
check("blank lines in the stored text are collapsed", "\n\n\n" not in rows["o1"][1])
check("'Staff RN' is no longer Lead / Manager: level from its 2 years", rows["o3"][0]["level"] == 2 and rows["o3"][0]["level_src"] == "years")
check("a foreign remote posting is closed", rows["o4"][3] is not None)
check("ids and first-seen dates are untouched", set(rows) == {"o1", "o2", "o3", "o4"} and all(v[2] == "2026-01-05" for v in rows.values()))
check("it runs once", jobfinder.reparse_stored(log=lambda m: None) == 0)

# ------------------------------------------------------------------ 7. per-employer fetch budget
def slow_reader(c):
    for i in range(1000):
        if jobfinder.over_budget(c):
            jobfinder.budget_stop(c, f"listing postings ({i} of 1000)")
            return
        time.sleep(0.02)
        yield jobfinder.J(c, f"Clerk {i}", f"https://example.com/s{i}", ["Columbus, OH"], "", None, "Desk work.", "", "", f"s{i}")

def deaf_reader(c):     # never asks over_budget(): the fetch layer cuts it off after the grace time
    for i in range(1000):
        time.sleep(0.02)
        yield jobfinder.J(c, f"Clerk {i}", f"https://example.com/d{i}", ["Columbus, OH"], "", None, "Desk work.", "", "", f"d{i}")

jobfinder.FETCHERS["slowtest"], jobfinder.FETCHERS["deaftest"] = slow_reader, deaf_reader
import netsafe
_cc, netsafe.check_config = netsafe.check_config, lambda c: None
company("Slow Co", ats="slowtest")
company("Deaf Co", ats="deaftest")
t0 = time.time()
s, js = jobfinder.process(next(x for x in catalog.companies() if x["name"] == "Slow Co"), budget=1)
took = time.time() - t0
check("a slow employer stops at its time budget and keeps what it read", s["status"] == "ok" and 0 < s["raw_jobs"] < 200 and took < 5 and s["budget_hit"] and "budget" in (s["truncated"] or ""), str(s))
with catalog.db() as con:
    counts = catalog.record_fetch("Slow Co", s, js, con)
check("...it is marked capped, so nothing is closed for what wasn't read", counts["status"] == "capped")
_g, jobfinder.FETCH_BUDGET_GRACE = jobfinder.FETCH_BUDGET_GRACE, 1
t0 = time.time()
s, js = jobfinder.process(next(x for x in catalog.companies() if x["name"] == "Deaf Co"), budget=1)
check("a reader that never checks is cut off by the fetch layer", s["budget_hit"] and time.time() - t0 < 8 and 0 < s["raw_jobs"] < 400, str(s))
jobfinder.FETCH_BUDGET_GRACE = _g
s, js = jobfinder.process(next(x for x in catalog.companies() if x["name"] == "Slow Co"), budget=0)
check("budget 0 = no limit", s["raw_jobs"] == 1000 and not s["budget_hit"])
netsafe.check_config = _cc
os.environ["SIFTWELL_FETCH_BUDGET"] = "77"
check("the budget comes from --budget, else the environment, else the default", jobfinder.fetch_budget() == 77)
os.environ.pop("SIFTWELL_FETCH_BUDGET")
import extra_fetchers
jobfinder.CFG["homes"] = [(home, 35.0)]
big = extra_fetchers.oracle_searches({"ats": "oracle"}, 91405)
check("a huge Oracle board is searched by place (each home + remote), a small one read whole",
      len(big) == 2 and "latitude=39.9" in big[0][0] and "radius=45" in big[0][0] and "ORA_REMOTE" in big[1][0]
      and extra_fetchers.oracle_searches({"ats": "oracle"}, 300) == [("", "")], str(big))
js_ = extra_fetchers.jibe_searches({"ats": "jibe"}, 18956)
check("a huge Jibe board (Costco) is searched around each home too", js_ == [{"location": "Columbus, OH", "stretch": 45, "stretchUnit": "MILES"}]
      and extra_fetchers.jibe_searches({"ats": "jibe"}, 400) == [{}], str(js_))
card = '<span class="sr-only field-label">Work Location</span> <span > In Person</span> <span class="sr-only field-label">ID</span> <span > 2026-19146</span>'
check("iCIMS: the card's own 'Work Location: In Person' is read", extra_fetchers._icims_workplace(card) == "onsite"
      and extra_fetchers._icims_workplace(card.replace("In Person", "Remote")) == "remote"
      and extra_fetchers._icims_workplace('<span class="field-label">Remote</span> <span>No</span>') == "onsite"
      and extra_fetchers._icims_workplace('<span class="field-label">ID</span> <span>7</span>') == "")
facets = [{"facetParameter": "remoteType", "values": [{"id": "r1", "descriptor": "Remote work is not available", "count": 316},
                                                      {"id": "r2", "descriptor": "Remote work is an option", "count": 18},
                                                      {"id": "r3", "descriptor": "Remote work only", "count": 1}]}]
check("Workday's remote facet: only the value that means remote is fetched as remote", jobfinder._wd_location_facets(facets) == {"remoteType": ["r3"]})

blocked = os.path.join(DATA, claude_cli.FORBID_LOG)
check("no Claude call was attempted", not os.path.exists(blocked))

print("\nall passed" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
