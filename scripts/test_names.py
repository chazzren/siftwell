"""Offline checks for employer display names (names.py): job-system / site-code brackets come off ("Accenture
(AccentureCareers)", "Schneider (taleo)", "Lbrands (1 BBW PROF)"), initials, ledger entities, slogans and page titles
give way to the employer's name ("Copcp", "Wve Wvnh Emp", "You'll Love It Here", "Careersapply Pennentertainment"),
placeholders lose their system and hash, two boards of one employer are told apart in plain words and share one
name on the job board (names.group_name / group_map), renames keep listing ids and never flip-flop, and good names
are left alone. No network, no Claude. Its own scratch data folder.

    python -X utf8 scripts/test_names.py <scratch dir>
"""
import json, os, shutil, sys

if len(sys.argv) < 2:
    sys.exit("usage: python -X utf8 scripts/test_names.py <scratch dir>")
SCRATCH = os.path.abspath(sys.argv[1])
DATA = os.path.join(SCRATCH, "names_test_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CODEX"] = "1"
os.environ.pop("SIFTWELL_CLAUDE_STUB", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import catalog, jobfinder, names as N, claude_cli

fails = 0


def check(label, ok, detail=""):
    global fails
    print(("ok   " if ok else "FAIL ") + label + (f"   [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


def eq(label, got, want):
    check(label, got == want, f"got {got!r}, want {want!r}")


WD = lambda tenant, site, **kw: dict({"ats": "workday", "tenant": tenant, "site": site, "wd": "wd5"}, **kw)
TALEO = lambda host, section: {"ats": "taleo", "host": host, "section": section}
ADP = {"ats": "adp", "cid": "6dd43f0a-1111-4222-8333-444455556666"}
ACC = WD("accenture", "AccentureCareers")
COPCP = {"ats": "ukg", "host": "recruiting.ultipro.com", "tenant": "CEN1032COHP", "board": "14b4a75f-f5ce-4e30-822d-7266b16aa02e"}
CHS = WD("communicarehealth", "CHSExternalCareerSite")
FME = WD("freseniusmedicalcare", "fme")
PENN = {"ats": "icims", "base": "https://careersapply-pennentertainment.icims.com"}
LOVE = {"ats": "icims", "base": "https://careers-roosters.icims.com"}

# ------------------------------------------------------------------ 1. good names are left alone
GOOD = ["Nationwide Children's Hospital", "L Brands", "JPMorgan Chase", "The Ohio State University", "AT&T", "3M", "H&R Block",
        "McKesson", "eBay", "OhioHealth", "CVS Health", "PNC Financial Services", "Bosch", "Kraft Heinz", "Ernst & Young", "Kohls",
        "Smith Mfg", "Your Pie", "We Energies", "Our Lady of Peace", "Toys R Us", "Abbott", "Express", "TransPerfect", "Schneider",
        "Accenture Federal Services", "Wright-Patt Credit Union", "Lindt", "Hirsch", "Knight Transportation", "T-Mobile", "HNTB",
        "COPCP", "DSW", "IBM", "U.S. Bank", "Five Below", "Schmidt Baking", "Welch's", "Marsh McLennan", "Lyft", "Crocs",
        "McKesson (Canada)", "Abbott (Nutrition)", "Accenture (Avanade)", "Hyatt (Lisle)", "Schneider (2)", "BD (Becton Dickinson)"]
bad = [(n, N.poor(n)) for n in GOOD if N.poor(n)]
check(f"{len(GOOD)} real names are fine, a plain '(place / brand)' included", not bad, str(bad))
bad = [(n, N.derive(n, {})) for n in GOOD if N.derive(n, {}) is not None]
check("...and nothing is derived for them", not bad, str(bad))
bad = [(n, N.clean_display(n)) for n in GOOD if N.clean_display(n) != n]
check("...and cleaning leaves them as they are", not bad, str(bad))
bad = [(n, N.display(n, {})) for n in GOOD if N.display(n, {}) != n]
check("...and a new company keeps such a name", not bad, str(bad))

# ------------------------------------------------------------------ 2. job-system / site-code brackets
POOR = {"Accenture (AccentureCareers)": ACC, "Lbrands (1 BBW PROF)": TALEO("lbrands.taleo.net", "1_BBW_PROF"),
        "Schneider (taleo)": TALEO("schneider.taleo.net", "11"), "Employer in Columbus OH (ADP 6dd43f)": ADP,
        "Copcp": COPCP, "Wve Wvnh Emp": CHS, "BOK USA Bio-Med Appl of Oklahoma": FME, "Careersapply Pennentertainment": PENN,
        "You'll Love It Here": LOVE, "McKesson (board 2)": {}, "Abbott Laboratories (abbottcareers2)": WD("abbott", "abbottcareers2"),
        "Odwlogistics (board 2)": {}, "Transperfect (Workday)": {}, "Express (iCIMS)": {}, "Boeing (INTERN)": WD("boeing", "INTERN"),
        "Gilead Sciences (gileadhotjobcareers)": {}, "BJ's Wholesale Club (BJsCareers)": {}, "HD Supply Management LLC (USA)": {},
        "Comfort Systems USA (Ohio) (Ohio)": {}, "Join Our Team": {}, "Find Your Future": {}, "Hntb": {}, "Employer (Paylocity 6997ff)": {}}
bad = [n for n, c in POOR.items() if not N.poor(n, c)]
check(f"{len(POOR)} names with a system / code in brackets, initials, slogans and placeholders are recognised", not bad, str(bad))

eq("'Accenture (AccentureCareers)' -> 'Accenture'", N.derive("Accenture (AccentureCareers)", ACC), "Accenture")
eq("...also without knowing the board (the brackets look like a site code)", N.clean_display("Accenture (AccentureCareers)"), "Accenture")
eq("'Lbrands (1 BBW PROF)' -> 'Lbrands'", N.derive("Lbrands (1 BBW PROF)", TALEO("lbrands.taleo.net", "1_BBW_PROF")), "Lbrands")
LB = ["Sales Associate\nL Brands is hiring. Join L Brands today.", "Manager\nAbout L Brands: a great place.", "Cashier\nAt L Brands we care."]
eq("...and 'L Brands' once its postings spell it", N.derive("Lbrands (1 BBW PROF)", TALEO("lbrands.taleo.net", "1_BBW_PROF"), LB), "L Brands")
eq("'Schneider (taleo)' -> 'Schneider'", N.derive("Schneider (taleo)", TALEO("schneider.taleo.net", "11")), "Schneider")
eq("'(Workday)', '(iCIMS)', '(UKG Ready)' come off", [N.clean_display(x) for x in ("Transperfect (Workday)", "Express (iCIMS)", "Acme (UKG Ready)")],
   ["Transperfect", "Express", "Acme"])
eq("'(board 2)' comes off and the run-together name is split", N.derive("Odwlogistics (board 2)", {}), "ODW Logistics")
eq("a country in brackets is not a board: 'HD Supply Management LLC (USA)'", N.clean_display("HD Supply Management LLC (USA)"), "HD Supply Management")
eq("a doubled '(Ohio) (Ohio)' is said once", N.clean_display("Comfort Systems USA (Ohio) (Ohio)"), "Comfort Systems USA (Ohio)")
eq("a plain brand in brackets stays ('Clayton Properties Group (Arbor)')", N.clean_display("Clayton Properties Group (Arbor)", None, WD("claytonhomes", "Arbor")),
   "Clayton Properties Group (Arbor)")

# ------------------------------------------------------------------ 3. initials, ledger entities, slogans, page titles
eq("'Copcp' -> 'COPCP' when nothing else is known", N.derive("Copcp", COPCP), "COPCP")
CO = ["Medical Assistant\nCentral Ohio Primary Care is hiring. Central Ohio Primary Care Physicians is an equal opportunity employer.",
      "Nurse\nAbout Central Ohio Primary Care: the largest physician-owned group. Central Ohio Primary Care is growing.",
      "Front Desk\nJoin Central Ohio Primary Care today. Central Ohio Primary Care offers benefits."]
eq("...and the name its postings share once they are read", N.derive("Copcp", COPCP, CO), "Central Ohio Primary Care")
eq("'Wve Wvnh Emp' -> the board's own address, split", N.derive("Wve Wvnh Emp", CHS), "Communicare Health")
CH = ["STNA\nCommuniCare Health Services is hiring. CommuniCare is an equal opportunity employer.", "RN\nAbout CommuniCare Health: we care.",
      "LPN\nJoin CommuniCare Health today."]
eq("...spelled the way its postings spell it", N.derive("Wve Wvnh Emp", CHS, CH), "CommuniCare Health")
eq("'BOK USA Bio-Med Appl of Oklahoma' -> 'Fresenius Medical Care'", N.derive("BOK USA Bio-Med Appl of Oklahoma", FME), "Fresenius Medical Care")
eq("'Careersapply Pennentertainment' -> 'Penn Entertainment'", N.derive("Careersapply Pennentertainment", PENN), "Penn Entertainment")
eq("'You'll Love It Here' -> the careers address when nothing else is known", N.derive("You'll Love It Here", LOVE), "Roosters")
RO = ["Barber\nRoosters Men's Grooming Center is hiring. About Roosters: classic barbershops.", "Stylist\nJoin Roosters today. Roosters is growing.",
      "Manager\nAt Roosters, we care. Roosters is an equal opportunity employer."]
eq("...and the employer its postings name", N.derive("You'll Love It Here", LOVE, RO), "Roosters")
check("a slogan is never taken from a page title", N.derive("Employer (iCIMS 12ab34)", {"ats": "icims", "base": "https://careers-x1.icims.com"}, [],
                                                         board_title="You'll Love It Here | Careers") is None)
eq("initials written like a word are written as initials", [N.derive(x, {}) for x in ("Hntb", "Ghc", "Cvs Health", "Ncr")], ["HNTB", "GHC", "CVS Health", "NCR"])
eq("a tenant that is one word stays one word ('communicare')", N.split_business("communicarehealth"), "Communicare Health")

# ------------------------------------------------------------------ 4. placeholders
eq("a placeholder loses its system and hash", N.plain_placeholder("Employer in Columbus OH (ADP 6dd43f)"), "Employer in Columbus OH")
eq("...and names the town its jobs are in when it named none", N.plain_placeholder("Employer (Paylocity 6997ff)", "Dublin"), "Employer in Dublin")
eq("a new placeholder company: plain", N.display("Employer in Columbus OH (ADP 6dd43f)", ADP), "Employer in Columbus OH")
eq("...and a second one is still told apart, without a hash", N.display("Employer in Columbus OH (ADP 0330de)", {"ats": "adp", "cid": "0330dee1-d933-49d0-805d-d480b2ad35af"},
                                                                    {"employer in columbus oh"}), "Employer in Columbus OH (2)")
check("the plain placeholder is still known to be a placeholder", N.poor("Employer in Columbus OH") == "placeholder" and N.poor("Employer in Columbus OH (2)") == "placeholder")

# ------------------------------------------------------------------ 5. two boards of one employer
eq("the second board gets a plain brand from its own address", N.unique_name("Accenture", WD("accenture", "AvanadeCareers"), {"accenture"}), "Accenture (Avanade)")
eq("...or a plain section word", N.unique_name("Hyatt", TALEO("hyatt.taleo.net", "lisle"), {"hyatt"}), "Hyatt (Lisle)")
eq("...or the town most of its jobs are in", N.unique_name("McKesson", {"ats": "radancy", "base": "https://careers.mckesson.com"}, {"mckesson"}, place="Irving"), "McKesson (Irving)")
eq("...at worst a number, never the job system or a code", N.unique_name("Schneider", TALEO("schneider.taleo.net", "11"), {"schneider"}), "Schneider (2)")
eq("...and the next one the next number", N.unique_name("Schneider", TALEO("schneider.taleo.net", "12"), {"schneider", "schneider (2)"}), "Schneider (3)")
eq("a site code that says nothing gives no suffix", [N.plain_suffix(x, "Abbott Laboratories") for x in ("abbottcareers2", "1_BBW_PROF", "7", "taleo", "AbbottCareers", "CSI")],
   ["", "", "", "", "", ""])
eq("a site code with a plain word gives it", [N.plain_suffix(x, "Dave & Buster's") for x in ("Main_Event_Careers", "salescareers", "INTERN", "Kaplan_Teach")],
   ["Main Event", "Sales", "Intern", "Kaplan Teach"])
eq("group_name: the shared name", [N.group_name(x) for x in ("McKesson (Canada)", "Abbott (Nutrition)", "Schneider (2)", "McKesson", "Comfort Systems USA (Ohio)", "3M")],
   ["McKesson", "Abbott", "Schneider", "McKesson", "Comfort Systems USA", "3M"])
CAT = [dict(WD("abbott", "abbottcareers"), name="Abbott"), dict(WD("abbott", "abbottcareers2"), name="Abbott Laboratories"),
       {"name": "McKesson", "ats": "radancy", "base": "https://careers.mckesson.com"}, {"name": "McKesson (2)", "ats": "workday", "tenant": "mckesson", "site": "x"},
       {"name": "Express", "ats": "icims", "base": "https://careers-express.icims.com"}, {"name": "Express (2)", "ats": "taleo", "host": "express.taleo.net", "section": "2"},
       {"name": "Express Wash Concepts", "ats": "workday", "tenant": "expresswashconcepts", "site": "x"},
       {"name": "Odwlogistics", "ats": "ukg", "tenant": "ODW1000ODWL", "board": "a"}, {"name": "ODW Logistics (2)", "ats": "ukg", "tenant": "ODW1000ODWL", "board": "b"},
       {"name": "TransPerfect", "ats": "recruitee", "token": "transperfect4"}, {"name": "Transperfect (2)", "ats": "workday", "tenant": "transperfect", "site": "transperfect"},
       dict(ACC, name="Accenture"), dict(ACC, name="Accenture Federal Services", search="Accenture Federal Services"),
       dict(WD("accenture", "AvanadeCareers"), name="Accenture (Avanade)"), {"name": "Schneider", **TALEO("schneider.taleo.net", "7")},
       {"name": "Schneider Downs", "ats": "greenhouse", "token": "schneiderdowns"}, {"name": "Boeing", **WD("boeing", "EXTERNAL")},
       {"name": "The Boeing", **WD("boeing", "subsidiary")}]
gm = N.group_map(CAT)
eq("group_map: Express, Abbott, McKesson, ODW and TransPerfect each show one name",
   [gm[x] for x in ("Express", "Express (2)", "Abbott", "Abbott Laboratories", "McKesson", "McKesson (2)", "Odwlogistics", "ODW Logistics (2)", "TransPerfect", "Transperfect (2)")],
   ["Express", "Express", "Abbott", "Abbott", "McKesson", "McKesson", "ODW Logistics", "ODW Logistics", "TransPerfect", "TransPerfect"])
eq("...different employers stay apart", [gm[x] for x in ("Express Wash Concepts", "Accenture Federal Services", "Accenture (Avanade)", "Schneider", "Schneider Downs", "The Boeing")],
   ["Express Wash Concepts", "Accenture Federal Services", "Accenture", "Schneider", "Schneider Downs", "Boeing"])
check("...every company has a group and plain names work too", set(gm) == {c["name"] for c in CAT} and N.group_map(["McKesson", "McKesson (Canada)"]) ==
      {"McKesson": "McKesson", "McKesson (Canada)": "McKesson"})

# ------------------------------------------------------------------ 6. the app: after a fetch (names.learn)
def company(name, **kw):
    e = {"name": name, "ats": "greenhouse", "token": name.lower().replace(" ", ""), "tier": "dmv_office", "sector": "x", "sets": ["ops"]}
    e.update(kw)
    if e["ats"] != "greenhouse":
        e.pop("token")
    catalog.save_company(e)
    return e


def store(co, jobs):
    c = next(x for x in catalog.companies() if x["name"] == co)
    with catalog.db() as con:
        out = [jobfinder.prepare_listing(jobfinder.J(c, t, "https://example.com/" + jid, locs, "", None, desc, "", "", jid), c) for jid, t, locs, desc in jobs]
        catalog.record_fetch(co, {"status": "ok", "raw_jobs": len(out), "secs": 1}, [o for o in out if o], con)


def ids(co):
    return sorted(j["id"] for j in catalog.open_listings() if j["company"] == co)


def cfg_of(co):
    return next((x for x in catalog.companies() if x["name"] == co), None)


quiet = lambda m: None
FILL = " We offer great benefits and a friendly team in a busy location. " * 3
jobs = lambda pre, town="Columbus, OH": [(pre + "1", "Driver", [town], "Drive a truck." + FILL), (pre + "2", "Clerk", [town], "File papers." + FILL),
                                         (pre + "3", "Planner", [town], "Plan loads." + FILL)]

company("Schneider", **TALEO("schneider.taleo.net", "7"))
store("Schneider", jobs("s"))
company("Schneider (taleo)", **TALEO("schneider.taleo.net", "11"))
store("Schneider (taleo)", jobs("t", "Green Bay, WI"))
before = ids("Schneider (taleo)")
got = N.learn("Schneider (taleo)", log=quiet)
eq("learn: 'Schneider (taleo)' next to 'Schneider' -> a plain place, never the system", got, "Schneider (Green Bay)")
check("...its listings keep their ids", ids(got) == before and len(before) == 3 and cfg_of(got).get("idp") == "Schneider (taleo)", str(ids(got)))
eq("...running it again changes nothing", [N.learn(got, log=quiet), N.learn(got, log=quiet), N.learn("Schneider", log=quiet)], [got, got, "Schneider"])
check("...and both are settled", cfg_of(got).get("nm") == 2 and cfg_of("Schneider").get("nm") == 2)

# a snapshot source of the directory (directory_jobs) is named by Siftwell and never renamed; nothing after a colon is a
# job board's label (pre-release 0.5.0 finding: "Hacker News: Who is hiring" became "Hacker News: Who is")
eq("nothing after a colon is cut ('Hacker News: Who is hiring')", [N.clean_display("Hacker News: Who is hiring"), N.strip_job_tail("Hacker News: Who is hiring")],
   ["Hacker News: Who is hiring", "Hacker News: Who is hiring"])
company("Hacker News: Who is", ats="directory_jobs", source="hn", tier="national")
eq("learn: a directory source an older version had cut gets its whole name back, once", [N.learn("Hacker News: Who is", log=quiet), N.learn("Hacker News: Who is hiring", log=quiet)],
   ["Hacker News: Who is hiring", "Hacker News: Who is hiring"])

company("Accenture (AccentureCareers)", **ACC)
store("Accenture (AccentureCareers)", jobs("a"))
eq("learn: 'Accenture (AccentureCareers)' -> 'Accenture' when that is free", N.learn("Accenture (AccentureCareers)", log=quiet), "Accenture")
company("Accenture (AvanadeCareers)", **WD("accenture", "AvanadeCareers"))
store("Accenture (AvanadeCareers)", jobs("v"))
eq("...and the employer's other board gets its brand", N.learn("Accenture (AvanadeCareers)", log=quiet), "Accenture (Avanade)")
eq("...no flip-flop", [N.learn("Accenture", log=quiet), N.learn("Accenture (Avanade)", log=quiet)], ["Accenture", "Accenture (Avanade)"])

company("Lbrands", **TALEO("lbrands.taleo.net", "bbw_in"))
store("Lbrands", jobs("l"))
company("Lbrands (1 BBW PROF)", **TALEO("lbrands.taleo.net", "1_BBW_PROF"))
store("Lbrands (1 BBW PROF)", jobs("m", "Reynoldsburg, OH") + [("m4", "Buyer", ["New York, NY"], "Buy things." + FILL), ("m5", "Analyst", ["Kettering, OH"], "Count." + FILL),
                                                             ("m6", "Lead", ["Dayton, OH"], "Lead." + FILL), ("m7", "Tech", ["Akron, OH"], "Fix." + FILL)])
got = N.learn("Lbrands (1 BBW PROF)", log=quiet)
eq("learn: 'Lbrands (1 BBW PROF)' with jobs all over -> a number, not the code", got, "Lbrands (2)")
eq("...stable", N.learn(got, log=quiet), got)

for i, cid in enumerate(("6dd43f0a-1111-4222-8333-444455556666", "0330dee1-d933-49d0-805d-d480b2ad35af")):
    nm = f"Employer in Columbus OH (ADP {cid[:6]})"
    company(nm, ats="adp", cid=cid)
    store(nm, jobs("p%d" % i))
a = N.learn("Employer in Columbus OH (ADP 6dd43f)", log=quiet)
b = N.learn("Employer in Columbus OH (ADP 0330de)", log=quiet)
eq("learn: placeholders nothing is known about lose their system and hash, and stay apart", [a, b], ["Employer in Columbus OH", "Employer in Columbus OH (2)"])
eq("...stable", [N.learn(a, log=quiet), N.learn(b, log=quiet)], [a, b])
check("...and not settled: a real name can still be learned later", not cfg_of(a).get("nm") and not cfg_of(b).get("nm"))
store(b, [("q1", "Server", ["Columbus, OH"], RO[0] + FILL), ("q2", "Host", ["Columbus, OH"], RO[1] + FILL), ("q3", "Cook", ["Columbus, OH"], RO[2] + FILL)])
before = ids(b)
got = N.learn(b, log=quiet)
check("...which happens once its postings name the employer, ids kept", got == "Roosters" and set(before) <= set(ids(got)), got)

company("Copcp", **COPCP)
store("Copcp", [("k1", "Medical Assistant", ["Columbus, OH"], CO[0] + FILL), ("k2", "Nurse", ["Columbus, OH"], CO[1] + FILL), ("k3", "Front Desk", ["Columbus, OH"], CO[2] + FILL)])
eq("learn: 'Copcp' -> the name its postings share", N.learn("Copcp", log=quiet), "Central Ohio Primary Care")
company("Wve Wvnh Emp", **CHS)
store("Wve Wvnh Emp", jobs("w"))
eq("learn: 'Wve Wvnh Emp' -> 'Communicare Health'", N.learn("Wve Wvnh Emp", log=quiet), "Communicare Health")
company("Careersapply Pennentertainment", **PENN)
store("Careersapply Pennentertainment", jobs("e"))
eq("learn: 'Careersapply Pennentertainment' -> 'Penn Entertainment'", N.learn("Careersapply Pennentertainment", log=quiet), "Penn Entertainment")
company("You'll Love It Here", **LOVE)
store("You'll Love It Here", [("r1", "Barber", ["Columbus, OH"], RO[0] + FILL), ("r2", "Stylist", ["Columbus, OH"], RO[1] + FILL), ("r3", "Manager", ["Columbus, OH"], RO[2] + FILL)])
got = N.learn("You'll Love It Here", log=quiet)
eq("learn: a slogan gives way to the employer; taken by its other board -> a plain suffix", N.group_name(got), "Roosters")
check("...with no system or code in it", got != "Roosters" and not N.poor(got, cfg_of(got)), got)
company("BOK USA Bio-Med Appl of Oklahoma", **FME)
store("BOK USA Bio-Med Appl of Oklahoma", jobs("f"))
eq("learn: a ledger entity -> 'Fresenius Medical Care'", N.learn("BOK USA Bio-Med Appl of Oklahoma", log=quiet), "Fresenius Medical Care")

company("Zed Typed (Ohio Team)", nm=1, ats="ukg", host="recruiting.ultipro.com", tenant="ZED1", board="b")
store("Zed Typed (Ohio Team)", jobs("z"))
company("Cvs Typed", nm=1, token="cvstyped")
store("Cvs Typed", jobs("y"))
eq("a name the person typed is never renamed", [N.learn("Zed Typed (Ohio Team)", log=quiet), N.learn("Cvs Typed", log=quiet)], ["Zed Typed (Ohio Team)", "Cvs Typed"])
company("Settled (taleo)", nm=1, **TALEO("settled.taleo.net", "3"))
store("Settled (taleo)", jobs("x"))
eq("a settled name still loses the job system an older version put in brackets", N.learn("Settled (taleo)", log=quiet), "Settled")

# ------------------------------------------------------------------ 7. names still poor after a real fetch (re-test findings)
UKGC = lambda t: {"ats": "ukg", "host": "recruiting.ultipro.com", "tenant": t, "board": "3a2849cd-0da6-4a57-813a-80b366fb0172"}
for n, c in (("Bjakcareer", {"ats": "workable", "token": "bjakcareer"}), ("Craneww", UKGC("CRA1009CRWL")), ("Lbrands", TALEO("lbrands.taleo.net", "x")),
             ("Lmhealth", UKGC("LIC1000LMHS")), ("Homepage", {"ats": "recruitee", "token": "eworgmbh"}), ("ICR United States USA", {}),
             ("MCK McKesson", WD("mckesson", "External_Careers")), ("Rbc", WD("rbc", "x")), ("Hpe", WD("hpe", "x"))):
    check(f"poor: {n!r}", bool(N.poor(n, c)), N.poor(n, c))
eq("a country tacked on comes off; one plain USA stays", [N.clean_display(x) for x in ("ICR United States USA", "Acme Corp, United States", "Comfort Systems USA", "T-Mobile USA")],
   ["ICR", "Acme Corp", "Comfort Systems USA", "T-Mobile USA"])
eq("the job board's own words behind a name come off", [N.clean_display(x) for x in ("Clearsulting Careers", "Anomatic Human Resources", "Acme - Careers",
   "Jobs for the Future", "Career Education Corp", "Human Resources")], ["Clearsulting", "Anomatic", "Acme", "Jobs for the Future", "Career Education Corp", "Human Resources"])
check("...and such names count as poor until then", N.poor("Clearsulting Careers") and N.poor("Corporatehcm") and not N.poor("Jobs for the Future"))
eq("a ledger's cut-off last word is finished; short names are left alone", [N.complete_truncated(x) for x in
   ("PricewaterhouseCoopers Advisory Ser", "CenterWell Certified Healt", "Nationwide Mutual Insurance Comp", "Acme Home", "The Ohio State University")],
   ["PricewaterhouseCoopers Advisory Services", "CenterWell Certified Health", "Nationwide Mutual Insurance Company", "Acme Home", "The Ohio State University"])
eq("a ledger code that repeats the name's start comes off ('MCK McKesson' at mckesson)", N.derive("MCK McKesson", WD("mckesson", "External_Careers")), "McKesson")
check("...a real code-led name the address starts with stays ('C5MI Insight' at c5mi)", not N.poor("C5MI Insight", WD("c5mi", "x")))
eq("the board's own short address is written as initials", [N.derive("Rbc", WD("rbc", "x")), N.derive("Hpe", WD("hpe", "x"))], ["RBC", "HPE"])
check("...never a word-like one, nor without its address", not N.poor("Gap", WD("gap", "x")) and not N.poor("Hpe") and not N.poor("Nike", WD("nike", "x")))
eq("a job-site word run into the address comes off when nothing else is known", N.derive("Bjakcareer", {"ats": "workable", "token": "bjakcareer"}), "Bjak")
CRW = ["Warehouse Associate\nCrane Worldwide Logistics is hiring. Crane Worldwide Logistics is an equal opportunity employer.",
       "Driver\nAbout Crane Worldwide Logistics: we move freight. Crane Worldwide Logistics offers benefits.", "Clerk\nJoin Crane Worldwide Logistics today."]
eq("'Craneww' -> the name its postings use (UKG's code starts with it)", N.derive("Craneww", UKGC("CRA1009CRWL"), CRW), "Crane Worldwide Logistics")
CRS = [t + "\nFollow the Crane SOPs at all times. Crane SOPs apply." for t in CRW] + ["Loader\nFollow Crane SOPs. Crane SOPs matter."]
eq("...not a phrase the code's letters rule out ('Crane SOPs' for CRA...CRWL)", N.derive("Craneww", UKGC("CRA1009CRWL"), CRS), "Crane Worldwide Logistics")
LMH = ["RN\nLicking Memorial Health Systems is an equal opportunity employer.", "LPN\nAbout Licking Memorial Health Systems: care close to home.",
       "Tech\nJoin Licking Memorial Health Systems today."]
eq("'Lmhealth' -> 'Licking Memorial Health Systems'", N.derive("Lmhealth", UKGC("LIC1000LMHS"), LMH), "Licking Memorial Health Systems")
eq("'Lbrands' -> 'L Brands' once its postings spell it", N.derive("Lbrands", TALEO("lbrands.taleo.net", "x"), LB), "L Brands")
import company_add
eq("a job-site word in front of an iCIMS address is not the employer's", [company_add.tenant_label(x) for x in
   ("careersapply-pennentertainment", "jobs-noodles", "externalhourly-highgate", "careers2-imagefirst", "storecareers-gpminvestments", "st-joseph", "fieldstone-homes")],
   ["pennentertainment", "noodles", "highgate", "imagefirst", "gpminvestments", "st-joseph", "fieldstone-homes"])
eq("...so the name made from it is the employer's", company_add.default_name({"ats": "icims", "base": "https://jobs-noodles.icims.com"}), "Noodles")
GC = [dict(WD("abbott", "abbottcareers"), name="Abbott"), dict(WD("abbott", "abbottcareers2"), name="Abbott Laboratories"),
      {"name": "MedStar Health", "ats": "jibe", "base": "https://careers.medstarhealth.org"}, {"name": "MedStar", "ats": "jsonld", "list_url": "https://jobs.medstarhealth.org/x"},
      {"name": "Express", "ats": "icims", "base": "https://careers-express.icims.com"}, {"name": "Express (2)", "ats": "taleo", "host": "express.taleo.net", "section": "2"},
      {"name": "Express Wash Concepts", "ats": "workday", "tenant": "expresswashconcepts", "site": "x"},
      {"name": "Acme Greenhouse", "ats": "greenhouse", "token": "acme"}, {"name": "Other Lever", "ats": "lever", "token": "other"}]
gk = N.group_keys(GC)
check("group key: one employer's boards share one (same name, same account, same employer domain)",
      gk["Abbott"] == gk["Abbott Laboratories"] == "g:abbott" and gk["MedStar Health"] == gk["MedStar"] and gk["Express"] == gk["Express (2)"], str(gk))
check("...others keep their own, and boards on a job system's shared host are never joined by host", gk["Express Wash Concepts"] != gk["Express"]
      and gk["Acme Greenhouse"] != gk["Other Lever"])
check("...the key is the same however the list is ordered", N.group_keys(list(reversed(GC))) == gk)
eq("...and group_map shows the one name", N.group_map(GC)["MedStar"], "MedStar Health")

allnames = [c["name"] for c in catalog.companies()]
bad = [n for n in allnames if N.poor(n, cfg_of(n)) in ("suffix", "board-n", "slogan", "generic", "code")
       or any(s in n.lower() for s in ("(taleo", "(adp", "careers)", "(workday", "(icims", "bbw prof"))]
check("no company is left with a system, a site code or a hash in its name", not bad, str(bad))
check("every catalog name is unique", len({n.lower() for n in allnames}) == len(allnames))
again = [N.learn(n, log=quiet) for n in allnames]
check("a second pass over the whole catalog renames nothing", again == allnames, str([(a, b) for a, b in zip(allnames, again) if a != b]))

blocked = os.path.join(DATA, claude_cli.FORBID_LOG)
check("no Claude call was attempted", not os.path.exists(blocked))

print("\nall passed" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
