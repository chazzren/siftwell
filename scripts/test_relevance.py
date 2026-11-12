"""Offline checks for the what-to-look-for sheet and the free Relevance score (lookfor.py), how they are used (title
filter, rating order, Best bets for unrated jobs, the Appeal pay part, lazy Workday text) and the one-time move of the
earlier shared company lists onto each profile's own list. No network, no Claude (a stub answers the two places Claude
is asked). Uses its own scratch data folder (never a real one).

    python -X utf8 scripts/test_relevance.py <scratch dir>
"""
import json, os, shutil, sys, time

if len(sys.argv) < 2:
    sys.exit("usage: python -X utf8 scripts/test_relevance.py <scratch dir>")
SCRATCH = os.path.abspath(sys.argv[1])
DATA = os.path.join(SCRATCH, "relevance_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"       # anything that slips past the stub is blocked and counted
os.environ.pop("SIFTWELL_CLAUDE_STUB", None)
os.environ.pop("SIFTWELL_PRETEND_NO_CLAUDE", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import people, paths, catalog, jobfinder, ai_score, pivot, claude_cli, claude_usage, resume, lookfor

fails = 0


def check(label, ok, detail=""):
    global fails
    print(("ok   " if ok else "FAIL ") + label + (f"   [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


real_ready = claude_cli.claude_ready
claude_cli.claude_ready = lambda *a, **k: False     # start with no Claude at all

# ------------------------------------------------------------------ 1. the O*NET extract
o = lookfor.onet()
size = os.path.getsize(lookfor.ONET_FILE)
check(f"O*NET extract ships and is small ({size // 1024} KB, {len(o['occ'])} occupations, {o['titles']} titles)",
      len(o["occ"]) > 900 and o["titles"] > 40000 and size < 3_000_000)
check("the attribution notice ships next to it", os.path.exists(os.path.join(os.path.dirname(lookfor.ONET_FILE), "NOTICE.txt")))
occ = lambda t: [lookfor.occ_title(c) for c, _ in lookfor.find_occupations(t)]
check("'RN' finds Registered Nurses", occ("RN")[:1] == ["Registered Nurses"], str(occ("RN")))
rn = next(c for c, v in o["occ"].items() if v["t"] == "Registered Nurses")
names = {n.lower() for n in lookfor.occ_names(rn)}
check("Registered Nurses is also called Staff Nurse, RN, Charge Nurse", {"staff nurse", "rn", "charge nurse"} <= names)
check("...and has related occupations", any("Licensed Practical" in lookfor.occ_title(c) for c in o["occ"][rn]["r"]))
for typed, want in (("Journeyman Electrician", "Electricians"), ("CDL Truck Driver", "Heavy and Tractor-Trailer Truck Drivers"),
                    ("Senior Software Engineer", "Software Developers"), ("Elementary School Teacher", "Elementary School Teachers"),
                    ("Office Manager", "First-Line Supervisors of Office and Administrative Support Workers"), ("Registered Nurse", "Registered Nurses")):
    check(f"'{typed}' -> {want}", any(want in x for x in occ(typed)), str(occ(typed)))
check("a made-up title finds nothing (no guessing)", occ("Zxqv Blorptang") == [], str(occ("Zxqv Blorptang")))
check("a typed title never maps to a catch-all (Office Manager is not 'General and Operations Managers')",
      not any("General and Operations" in x or "All Other" in x for t in ("Office Manager", "Program Manager", "Operations Supervisor", "Phlebotomist") for x in occ(t)))
check("...unless the catch-all is what was typed", occ("General and Operations Managers") == ["General and Operations Managers"])
check("a plain title that many occupations list picks none (Teacher, Project Manager, Shift Supervisor, 5th Grade Teacher)",
      all(occ(t) == [] for t in ("Teacher", "Project Manager", "Shift Supervisor", "5th Grade Teacher", "Sales Associate")),
      str({t: occ(t) for t in ("Teacher", "Project Manager", "Shift Supervisor", "5th Grade Teacher", "Sales Associate")}))
check("...but the field is still known when they all agree (Teacher, 5th Grade Teacher -> Education)",
      lookfor.field_of("Teacher") == "Education" and lookfor.field_of("5th Grade Teacher") == "Education" and lookfor.field_of("Project Manager") == "")
check("one step up without Claude (occupation list, else a short ladder)",
      "Charge Nurse" in lookfor.step_up("Registered Nurse") and lookfor.step_up("Office Manager") == ["Office Director"]
      and lookfor.step_up("Front Desk Supervisor") == ["Front Desk Manager"] and lookfor.step_up("Assistant Store Manager") == ["Store Manager"],
      str([lookfor.step_up(t) for t in ("Registered Nurse", "Office Manager", "Front Desk Supervisor", "Assistant Store Manager")]))
P_ = lookfor.title_parts
check("a posted title is cut to its core (site, unit, requisition number and brackets are not the job)",
      P_("Phlebotomist- Westerville Family Physicians")[0] == [("phlebotomist",)] and P_("Staff RN – PICU")[0] == [("staff", "rn")]
      and P_("Program Manager (R5448)")[0] == [("program", "manager")] and P_("Registered Nurse (RN) - Med Surg")[0] == [("rn",)]
      and ("sale", "operation", "manager") in P_("Manager, Sales Operations")[0] and P_("Analyst/Consultant")[0] == [("analyst",), ("consultant",)],
      str([P_(t) for t in ("Phlebotomist- Westerville Family Physicians", "Staff RN – PICU", "Program Manager (R5448)", "Manager, Sales Operations")]))
check("short forms are the same title (RN = Registered Nurse, LPN, NP, CNA)", lookfor.phrase("Registered Nurse") == lookfor.phrase("RN") == ("rn",)
      and lookfor.phrase("Licensed Practical Nurse") == ("lpn",) and lookfor.phrase("Nurse Practitioner") == ("np",) and lookfor.phrase("Certified Nursing Assistant") == ("cna",))

# ------------------------------------------------------------------ 2. sheets and Relevance without Claude
JOBS = ["Registered Nurse - ICU", "RN, Emergency Department (Nights)", "Staff Nurse II", "Charge Nurse", "Nurse Practitioner",
        "Licensed Practical Nurse", "Medical Assistant", "Software Engineer", "Senior Backend Developer", "Product Manager",
        "Office Manager", "Front Office Manager", "Administrative Assistant", "Truck Driver CDL-A", "Delivery Driver",
        "Journeyman Electrician", "Electrician Apprentice", "Maintenance Technician", "Electrical Engineer",
        "Elementary Teacher", "4th Grade Teacher", "Substitute Teacher", "School Principal", "Internal Auditor",
        "Marketing Intern", "Warehouse Associate", "Diesel Mechanic", "DevOps Engineer", "Data Scientist", "Line Cook"]
# key: (typed title, skills, their own title as posted (85+), other names / close kin (40-84), obvious mismatches (25 or less))
PROFILES = {
    "nurse": ("RN", ["patient care", "IV therapy", "Epic"], ["Registered Nurse - ICU", "RN, Emergency Department (Nights)", "Staff RN – PICU", "Ambulatory RN – Cardiology Clinic", "New Grad Nurse – RN"],
              ["Staff Nurse II", "Charge Nurse"], ["Software Engineer", "Truck Driver CDL-A", "Office Manager", "Line Cook", "Internal Auditor", "Phlebotomist"]),
    "electrician": ("Electrician", ["conduit", "wiring", "NEC"], ["Journeyman Electrician", "Electrician Apprentice", "Electrician - Industrial (2nd shift)"],
                    ["Electrician Helper", "Electrician Supervisor"], ["Registered Nurse - ICU", "Product Manager", "Elementary Teacher", "Electrical Engineer"]),
    "office": ("Office Manager", ["scheduling", "QuickBooks"], ["Office Manager", "Front Office Manager", "Office Manager - Dental Practice"],
               ["Office Administrator", "Office Supervisor"], ["Product Manager", "Truck Driver CDL-A", "Data Scientist", "Charge Nurse", "Shift Supervisor", "Principal Program Manager", "Housekeeping Supervisor"]),
    "teacher": ("Elementary School Teacher", ["lesson planning", "classroom management"], ["Elementary School Teacher", "Elementary School Teacher (2026-27)"],
                ["Elementary Teacher", "Teacher - Elementary"], ["Software Engineer", "Diesel Mechanic", "Office Manager"]),
    "trucker": ("Truck Driver", ["CDL", "DOT regulations"], ["Truck Driver CDL-A", "CDL-A Truck Driver - Home Daily", "Local Truck Driver"],
                ["Delivery Driver", "CDL Driver"], ["Registered Nurse - ICU", "Software Engineer", "School Principal", "Dispatcher"]),
    "dev": ("Software Engineer", ["Python", "Kubernetes"], ["Software Engineer", "Senior Software Engineer", "Software Engineer II, Payments"],
            ["DevOps Engineer", "Software Developer"], ["Charge Nurse", "Truck Driver CDL-A", "Line Cook", "Office Manager"]),
}
pids = {}
for key, (title, skills, own, near, bad) in PROFILES.items():
    pid = pids[key] = people.add(key)
    people.set_current(pid)
    resume.save_manual({"name": key, "current_title": title, "skills": skills, "experience": []})
    sheet = lookfor.build(pid)
    sc = lookfor.Scorer(sheet, {})
    s = {t: sc.title_score(t)[0] for t in JOBS + own + near + bad}
    check(f"{key}: sheet built with no Claude (recent '{sheet['recent']}', {len(sheet['occs'])} occupations, {len(sheet['skills'])} skills)",
          sheet["recent"] == title and any(x["tier"] == "same" for x in sheet["occs"]) and sheet["field"])
    check(f"{key}: their own title as employers post it scores {min(s[t] for t in own)}+, other names for it {min(s[t] for t in near)}-{max(s[t] for t in near)}, "
          f"mismatches at most {max(s[t] for t in bad)}",
          min(s[t] for t in own) >= 85 and 40 <= min(s[t] for t in near) and max(s[t] for t in near) < min(s[t] for t in own) and max(s[t] for t in bad) <= 25,
          str({t: s[t] for t in own + near + bad}))
    check(f"{key}: only skills they typed are on the sheet (no occupation-list tools or task words)",
          {x["t"].lower() for x in sheet["skills"]} == {x.lower() for x in skills} and not any(x["src"] == "onet" for x in sheet["skills"]), str(sheet["skills"]))
    check(f"{key}: 80+ is rare (only their own title): {sum(1 for t in JOBS if s[t] >= 80)} of {len(JOBS)} sample titles",
          sum(1 for t in JOBS if s[t] >= 80) <= 3)
nurse = lookfor.Scorer(lookfor.load(pids["nurse"]), {})
T = lambda sc, t: sc.title_score(t)[0]
check("nurse: site and unit suffixes don't matter (Staff RN – PICU = Ambulatory RN – Cardiology Clinic; New Grad Nurse – RN close behind)",
      T(nurse, "Staff RN – PICU") == T(nurse, "Ambulatory RN – Cardiology Clinic") >= 90 and T(nurse, "New Grad Nurse – RN") >= 85,
      str([T(nurse, t) for t in ("Staff RN – PICU", "Ambulatory RN – Cardiology Clinic", "New Grad Nurse – RN")]))
check("nurse: a Nurse Practitioner is not an RN (related occupation, far below; 'Field Nurse Practitioner' too)",
      T(nurse, "Nurse Practitioner - ICU") <= 45 and T(nurse, "Field Nurse Practitioner") <= 45 and nurse.title_score("Nurse Practitioner")[1] == "relocc",
      str([nurse.title_score(t) for t in ("Nurse Practitioner - ICU", "Field Nurse Practitioner")]))
check("nurse: related roles sit in between (LPN)", 30 <= T(nurse, "Licensed Practical Nurse") <= 45 and T(nurse, "LPN") == T(nurse, "Licensed Practical Nurse"))
check("nurse: 'Your job title' always outranks another name for it, which outranks a related occupation",
      T(nurse, "Registered Nurse") > T(nurse, "Staff Nurse") > T(nurse, "Nurse Practitioner") > 0)
lookfor.edit(pids["nurse"], {"add": "title", "text": "ICU Nurse"})
chip = lookfor.Scorer(lookfor.load(pids["nurse"]), {})
check("an 'ICU Nurse' chip matches ICU Nurse postings, not 'Nurse Practitioner - ICU' (ordered phrases, not word sets)",
      T(chip, "ICU Nurse") == 100 and T(chip, "Nurse Practitioner - ICU") <= 45, str((T(chip, "ICU Nurse"), T(chip, "Nurse Practitioner - ICU"))))
lookfor.edit(pids["nurse"], {"remove": "title", "text": "ICU Nurse"})
phleb = people.add("phleb"); people.set_current(phleb)
resume.save_manual({"name": "phleb", "current_title": "Phlebotomist", "skills": [], "experience": []})
ph = lookfor.Scorer(lookfor.build(phleb), {})
check("'Phlebotomist- Westerville Family Physicians' scores the same as 'Phlebotomist'", T(ph, "Phlebotomist- Westerville Family Physicians") == T(ph, "Phlebotomist") == 100)
office = lookfor.Scorer(lookfor.load(pids["office"]), {})
check("office manager: the exact title is on top; Accounting Manager is only 'the same kind of work'; nothing unrelated is 'another name'",
      T(office, "Office Manager") == 100 and 25 < T(office, "Accounting Manager") <= 50 and office.title_score("Accounting Manager")[1] == "occ"
      and T(office, "Shift Supervisor") <= 25 and T(office, "Principal Program Manager") <= 25,
      str([office.title_score(t)[:3] for t in ("Accounting Manager", "Shift Supervisor", "Principal Program Manager")]))
check("office manager: related occupations are not other trades' supervisors (mechanics, housekeeping)",
      not any("Mechanics" in lookfor.occ_title(x["code"]) or "Housekeeping" in lookfor.occ_title(x["code"]) for x in lookfor.load(pids["office"])["occs"]),
      str([lookfor.occ_title(x["code"]) for x in lookfor.load(pids["office"])["occs"]]))
check("looser relatives sit in between (4th Grade Teacher for a teacher, Backend Developer for a developer)",
      10 <= T(lookfor.Scorer(lookfor.load(pids["teacher"]), {}), "4th Grade Teacher") < 60
      and 10 <= T(lookfor.Scorer(lookfor.load(pids["dev"]), {}), "Senior Backend Developer") < 60)
# legacy title words: single catch-all words are not titles; reframing titles become related roles
leg = people.add("legacy"); people.set_current(leg)
json.dump({"name": "L", "summary": "s", "location": "", "years_experience": 5, "clearances": [], "education": [], "certifications": ["Certified Scrum Master"],
           "skills": ["Low-code workflow implementation (Mendix)", "Agile/Scrum"], "languages": [],
           "experience": [{"employer": "A", "title": "Management Consultant", "dates": "2023 - Present", "highlights": []},
                          {"employer": "B", "title": "Operations Manager", "dates": "2019 - 2023", "highlights": []},
                          {"employer": "C", "title": "Front Desk Supervisor", "dates": "2017 - 2019", "highlights": []}],
           "reframings": [{"angle": "x", "target_titles": ["Solutions Consultant"], "evidence": []}], "hard_limits": [],
           "target_roles": ["Technical Program Manager", "Engineer", "Architect", "Manager", "Project"],
           "title_keywords": ["program manager", "security", "mendix", "manager"], "fit_keywords": ["case management"], "notes": ""},
          open(people.pdir("profile.json", pid=leg), "w"))
ls = lookfor.build(leg)
lt = {x["t"]: x["tier"] for x in ls["titles"]}
check("single catch-all words carried over from old title words are dropped (Engineer, Architect, Manager, Project, security)",
      not {"Engineer", "Architect", "Manager", "Project", "security", "manager"} & set(lt) and lt.get("Technical Program Manager") == "wanted" and lt.get("mendix") == "keyword", str(lt))
check("roles the resume reader's reframings open are related roles", lt.get("Solutions Consultant") == "related", str(lt))
check("skills are the person's own, written the way postings write them ('(Mendix)' -> Mendix, 'Agile/Scrum' -> Agile, Scrum, certifications)",
      {"mendix", "agile", "scrum", "certified scrum master", "case management"} <= {x["t"].lower() for x in ls["skills"]}, str([x["t"] for x in ls["skills"]]))
lsc = lookfor.Scorer(ls, {})
check("own titles in order: most recent 100, a title they search for 90, the job before 82, the one before that 66; a bare 'Architect' is nothing",
      [T(lsc, t) for t in ("Management Consultant", "Technical Program Manager", "Operations Manager", "Front Desk Supervisor")] == [100, 90, 82, 66]
      and T(lsc, "Senior Architect") <= 10 and T(lsc, "Software Engineer") <= 10,
      str([T(lsc, t) for t in ("Management Consultant", "Technical Program Manager", "Operations Manager", "Front Desk Supervisor", "Senior Architect", "Software Engineer")]))
check("a longer posted title keeps most of it; a title that only shares words gets a little, and says so",
      80 <= T(lsc, "Federal Management Consultant") < 100 and 40 <= T(lsc, "Program Manager, Field") <= 70 and 0 < T(lsc, "Events Program Planner") <= lookfor.SHARED_MAX,
      str([lsc.title_score(x) for x in ("Federal Management Consultant", "Program Manager, Field", "Events Program Planner")]))
j = {"title": "Program Coordinator", "desc": ""}
lsc.score(j)
check("...in plain words", j["rel"] <= lookfor.SHARED_MAX and ("Shares words" in j["rel_why"] or j["rel_why"].startswith("Nothing")), j["rel_why"])

sc = lookfor.scorer(pids["nurse"])
a = {"title": "Staff Nurse", "desc": "Provide patient care, IV therapy and charting in Epic."}
b = {"title": "Staff Nurse", "desc": "Join our team."}
c = {"title": "Clinical Coordinator", "desc": "Patient care and IV therapy experience needed; Epic a plus."}
d = {"title": "Forklift Operator", "desc": "Move pallets."}
e = {"title": "Registered Nurse", "desc": "Join our team."}
for j in (a, b, c, d, e):
    sc.score(j)
check("skills found in the posting add; a good skills match lifts an odd title a little; a mismatch stays low; the caps hold",
      78 >= a["rel"] > b["rel"] >= 60 and e["rel"] > a["rel"] and 10 <= c["rel"] <= lookfor.SKILL_ALONE and d["rel"] <= 5, str([x["rel"] for x in (a, b, c, d, e)]))
check("every score says why in plain words", "Staff Nurse" in a["rel_why"] and "mentions" in a["rel_why"] and d["rel_why"].startswith("Nothing"), a["rel_why"])
check("whole words only: 'RN' does not match Intern / Journeyman", sc.title_score("Marketing Intern")[0] <= 10 and sc.title_score("Journeyman Electrician")[0] <= 10)
check("level words don't matter: Senior Registered Nurse II = Registered Nurse", sc.title_score("Senior Registered Nurse II")[0] == sc.title_score("Registered Nurse")[0] >= 90)
many = [{"title": "Staff Nurse", "desc": "patient care"} for _ in range(60)] + [{"title": "Staff Nurse", "desc": "Epic"}] + [{"title": "X", "desc": ""} for _ in range(40)]
fit = lookfor.scorer(pids["nurse"]).fit(many)
w = {s_: w_ for s_, _, w_ in fit.skills}
check("a skill most postings on the board mention counts for nothing, a rare one in full", w["patient care"] == 0 and w["epic"] == 1.0, str(w))

bare = people.add("bare")
people.set_current(bare)
j = {"title": "Anything", "desc": "x"}
lookfor.scorer(bare).score(j)
check("no titles at all: Relevance is unknown (None), not zero", j["rel"] is None and lookfor.is_empty(lookfor.ensure(bare)))

# speed: 12,000 jobs
people.set_current(pids["nurse"])
import random
random.seed(7)
words = "Nurse Manager Senior Clinical Engineer Driver Associate Technician Registered Assistant Coordinator Analyst Teacher Sales Lead II ICU Remote Staff".split()
big = [{"title": " ".join(random.sample(words, random.randint(2, 4))), "desc": "patient care " * 5 + "lorem ipsum dolor " * 300} for _ in range(12000)]
sc = lookfor.scorer(pids["nurse"])
t0 = time.time()
for j in big:
    sc.score(j)
secs = time.time() - t0
check(f"12,000 jobs scored in {secs:.1f}s (plain code)", secs < 12 and all(0 <= j["rel"] <= 100 for j in big))

# ------------------------------------------------------------------ 3. the person's edits; ratings keys never move
pid = pids["nurse"]
people.set_current(pid)
fp0 = {k: v for k, v in ai_score.fingerprints().items()}
hash0 = resume.load_active()["_hash"]
keys0 = pivot.cache_keys(ai_score.fingerprints(), people.settings_strict(missing_ok=True), people.read_saved_strict())
lookfor.edit(pid, {"add": "title", "text": "School Nurse"})
lookfor.edit(pid, {"add": "related", "text": "Case Manager"})
lookfor.edit(pid, {"add": "skill", "text": "Telemetry"})
lookfor.edit(pid, {"remove": "occ", "code": lookfor.load(pid)["occs"][-1]["code"]})
sheet = lookfor.build(pid)       # a rebuild keeps the person's chips and removals
check("added chips survive a rebuild", {"school nurse", "case manager"} <= {x["t"].lower() for x in sheet["titles"]} and "telemetry" in {x["t"].lower() for x in sheet["skills"]})
gone = sheet["removed"]["occs"][0]
check("a removed occupation stays removed", gone not in {x["code"] for x in sheet["occs"]})
np_code = next(c for c, v in o["occ"].items() if v["t"] == "Nurse Practitioners")
before_np = lookfor.Scorer(lookfor.load(pid), {}).title_score("Nurse Practitioner")[0]
lookfor.edit(pid, {"remove": "occ", "code": np_code})
after_np = lookfor.Scorer(lookfor.build(pid), {}).title_score("Nurse Practitioner")
check("removing 'Nurse Practitioners' really removes it: no other occupation's names bring it back", before_np > 0 and after_np[0] == 0, str((before_np, after_np)))
lookfor.edit(pid, {"add": "related", "text": "Case Manager"})
lookfor.edit(pid, {"remove": "title", "text": "Case Manager"})
check("a removed title chip stops counting, and stays gone after a rebuild",
      lookfor.Scorer(lookfor.build(pid), {}).title_score("Case Manager")[0] == 0 and "case manager" in lookfor.load(pid)["removed"]["titles"],
      str((lookfor.Scorer(lookfor.build(pid), {}).title_score("Case Manager"), lookfor.load(pid)["removed"])))
lookfor.edit(pid, {"add": "related", "text": "Case Manager"})
lookfor.edit(pid, {"recent": "Charge Nurse"})
check("the most recent title can be changed by hand and counts most", lookfor.load(pid)["recent"] == "Charge Nurse"
      and lookfor.scorer(pid).title_score("Charge Nurse")[0] == 100)
lookfor.edit(pid, {"recent": ""})
tmp = people.add("tmp")
people.set_current(tmp)
resume.save_manual({"name": "tmp", "current_title": "RN", "skills": [], "experience": []})
lookfor.build(tmp)
lookfor.edit(tmp, {"remove": "title", "text": "RN"})
prof = resume.load_active()
check("removing a title also takes it out of the profile's title filter lists", "RN" not in prof["target_roles"] and "rn" not in prof["title_keywords"]
      and "rn" not in {x["t"].lower() for x in lookfor.load(tmp)["titles"]})
people.set_current(pid)
fp1 = ai_score.fingerprints()
keys1 = pivot.cache_keys(fp1, people.settings_strict(missing_ok=True), people.read_saved_strict())
check("sheet edits change no rating fingerprint or cache key (ai_score.fingerprints, pivot.cache_keys)",
      all(fp1[k] == fp0[k] for k in ("phash", "fp", "hl", "pfp")) and keys1[0] == keys0[0] and hash0 in [fp1["phash"], *fp1["phash_old"]],
      str((fp0["phash"], fp1["phash"])))
check("RATING_FORMAT is untouched", ai_score.RATING_FORMAT == 1 and pivot.RATING_FORMAT == 1)
lookfor.edit(pid, {"reset": "sheet"})
check("'Start this list over' rebuilds from the profile", "school nurse" not in {x["t"].lower() for x in lookfor.load(pid)["titles"]})

# ------------------------------------------------------------------ 4. learning from saved / hidden jobs
pid = pids["office"]
people.set_current(pid)
def rel_of(title):
    j = {"title": title, "desc": ""}
    lookfor.scorer(pid).score(j)
    return j
r1, r0 = rel_of("Clinic Receptionist")["rel"], rel_of("Office Manager")["rel"]
lookfor.note_mark(pid, "A::1", "saved", "Clinic Receptionist")
lookfor.note_mark(pid, "A::2", "hidden", "Payroll Clerk")
lookfor.note_mark(pid, "A::3", "hidden", "Office Manager")                      # their own title, hidden (wrong state, say)
lookfor.note_mark(pid, "A::4", "hidden", "Office Manager - Dallas TX")
j1, j2, j3, j4, j5 = (rel_of(t) for t in ("Clinic Receptionist", "Payroll Clerk", "Office Manager", "Office Manager - Dallas TX", "Front Office Manager"))
check("saving a job nudges similar titles up, hiding nudges them down, within bounds",
      r1 < j1["rel"] <= r1 + lookfor.NUDGE_UP and "saved" in j1["rel_why"] and "hid" in j2["rel_why"], str((r1, j1["rel"], j2["rel"], j2["rel_why"])))
check("hiding a posting with their own title never pushes that title down (Office Manager, Front Office Manager unchanged)",
      j3["rel"] == r0 and "hid" not in j3["rel_why"] and "hid" not in j5["rel_why"], str((r0, j3["rel"], j3["rel_why"], j5["rel_why"])))
check("...only the part that is not their title is learned (the place: 'Dallas')", r0 - lookfor.NUDGE_DOWN <= j4["rel"] < r0 and "hid" in j4["rel_why"], str((r0, j4["rel"], j4["rel_why"])))
v = lookfor.view(pid)
check("what was learned is listed for the profile page", v["learned"]["n_up"] == 1 and v["learned"]["n_down"] == 3)
lookfor.note_mark(pid, "A::1", "", "")
check("un-marking forgets it", "A::1" not in lookfor.learned(pid))
lookfor.edit(pid, {"reset": "learning"})
check("reset forgets everything learned", lookfor.learned(pid) == {} and rel_of("Office Manager - Dallas TX")["rel"] == r0)

# ------------------------------------------------------------------ 5. the title filter
def titles_pass(pid, titles):
    people.set_current(pid)
    pc, _, _ = jobfinder.person_cfg(pid)
    jobfinder.use_cfg(pc)
    return [t for t in titles if jobfinder.title_ok(t)]
T = ["Registered Nurse", "Staff Nurse", "Charge Nurse", "Licensed Practical Nurse", "Summer Intern", "Journeyman Electrician", "Software Engineer", "Line Cook"]
got = titles_pass(pids["nurse"], T)
check("own-titles profile: other names and related roles pass the filter too, as whole words", got == T[:4], str(got))
check("no titles: every title still passes", titles_pass(bare, T) == [t for t in T if "Intern" not in t], str(titles_pass(bare, T)))
old = people.add("Old Person")
json.dump({"salary_floor": 150000, "goals": "", "prefs": {}}, open(people.pdir("settings.json", pid=old), "w"))   # a pre-rule file: built-in words
people.set_current(old)
resume.save_manual({"name": "Old Person", "current_title": "Welder", "skills": ["MIG"], "experience": []})
pc_old = jobfinder.person_cfg(old)[0]
check("profile on the earlier built-in word list: the sheet adds nothing to its filter", people.settings(old)["title_rule"] == "builtin" and pc_old["title_words"] == [],
      str(pc_old["title_words"][:5]))
check("...but it still has a sheet and Relevance", lookfor.scorer(old).title_score("Welder")[0] == 100)
lookfor.edit(old, {"add": "title", "text": "Pipefitter"})
check("...and a title the person adds does reach its filter", jobfinder.person_cfg(old)[0]["title_words"] == ["pipefitter"])

# shared fetch: whose titles ask for full text
cfgs = [jobfinder.person_cfg(p)[0] for p in (pids["nurse"], bare)]
jobfinder.use_cfg(jobfinder.fetch_cfg(cfgs))
co = {"name": "Hospital"}
check("shared fetch with a no-titles profile: every title is still kept (title_ok), but full text up front only for named titles",
      jobfinder.title_ok("Forklift Operator") and jobfinder.fetch_wanted(co, "Staff Nurse") and not jobfinder.fetch_wanted(co, "Forklift Operator")
      and not jobfinder.fetch_wanted(co, "Nursing Intern"))
jobfinder.use_cfg(jobfinder.fetch_cfg([jobfinder.person_cfg(bare)[0]]))
check("nobody has titles: no posting asks for full text up front", not jobfinder.fetch_wanted(co, "Staff Nurse"))

# ------------------------------------------------------------------ 6. lazy rows: on boards, text fetched when wanted
people.set_current(pids["nurse"])
wd = {"name": "Mercy Health", "ats": "workday", "tenant": "mercy", "wd": "wd5", "site": "ext", "sets": [f"own-{bare}", f"own-{pids['nurse']}"], "tier": "", "sector": "Health"}
catalog.save_company(wd)
def wd_row(path, title, desc="", lazy=True):
    j = jobfinder.J(wd, title, "https://mercy.wd5.myworkdayjobs.com/en-US/ext" + path, ["Springfield, IL"], "", None, desc, "", "", path)
    if lazy:
        j["_partial"], j["lazy"] = True, "workday"
    return jobfinder.prepare_listing(j, wd)
with catalog.db() as con:
    catalog.record_fetch("Mercy Health", {"status": "ok", "raw_jobs": 2, "secs": 1},
                         [wd_row("/job/a", "Forklift Operator"), wd_row("/job/b", "Staff Nurse", "Patient care. $30 - $40 per hour", lazy=False)], con)
ids = lambda **k: sorted(j["title"] for j in catalog.open_listings(**k))
check("boards see lazy rows; other readers don't", ids() == ["Staff Nurse"] and ids(lazy=True) == ["Forklift Operator", "Staff Nurse"])
calls = []
def fake_http(url, body=None, tries=6):
    calls.append(url)
    return {"jobPostingInfo": {"jobDescription": "<p>Operate a forklift. Pay $20 - $24 per hour.</p>", "location": "Springfield, IL"}}
real_http, jobfinder.http_json = jobfinder.http_json, fake_http
import netsafe
real_cc, netsafe.check_config = netsafe.check_config, lambda c: None
text = jobfinder.lazy_text("Mercy Health::/job/a")
row = next(j for j in catalog.open_listings() if j["title"] == "Forklift Operator")
check("opening a lazy job fetches its text once and stores the posting complete (pay parsed, no longer lazy)",
      "forklift" in text.lower() and len(calls) == 1 and row.get("salary_min") == 41600 and not row.get("lazy") and "/job/a" in calls[0], str((calls, row.get("salary_min"))))
jobfinder.lazy_text("Mercy Health::/job/a")
check("a second open uses the stored text", len(calls) == 1)
with catalog.db() as con:   # the next fetch reports it text-less again: the stored text is kept and it stays complete
    k = catalog.known("Mercy Health")["Mercy Health::/job/a"]
check("the stored text survives the next fetch's partial row", k[2] and not k[1])
jobfinder.http_json, netsafe.check_config = real_http, real_cc

# ------------------------------------------------------------------ 7. Appeal pay part
def scored(pid, mid, spread=None):
    people.set_current(pid)
    jobfinder.use_cfg(jobfinder.person_cfg(pid)[0])
    if spread is not None:
        jobfinder.set_pay_spread([{"salary_mid": m} for m in spread])
    j = {"id": "a", "title": "X", "company": "C", "desc": "", "clearance": "", "workplace": "onsite", "salary_mid": mid, "level": None, "travel": ""}
    jobfinder.score(j)
    return j["appeal_parts"]["pay"]
check("profile with a pay floor: today's numbers ($2,000 a point above the floor)", scored(old, 170000) == 60 and scored(old, 150000) == 50 and scored(old, None) == 50)
hourly = [31200 + 2080 * i for i in range(20)]     # a board of $15-$34/hour jobs
p_lo, p_mid, p_hi = scored(pids["trucker"], hourly[1], hourly), scored(pids["trucker"], hourly[10], hourly), scored(pids["trucker"], hourly[19], hourly)
check("no floor: pay is placed within the board's own spread (hourly jobs aren't all 'poor', $100k isn't the ceiling)",
      p_lo < 15 and 45 <= p_mid <= 60 and p_hi > 90, str((p_lo, p_mid, p_hi)))
big_pay = [90000 + 5000 * i for i in range(30)]
check("...and a $100k job on a board of $90k-$235k jobs is near the bottom, not the top", scored(pids["dev"], 100000, big_pay) < 15)
check("no floor and too few listed pays: a broad US spread stands in", 40 <= scored(pids["trucker"], 62000, []) <= 60)

# ------------------------------------------------------------------ 8. Best bets and the rating order
people.set_current(pids["nurse"])
jobfinder.use_cfg(jobfinder.person_cfg(pids["nurse"])[0])
import math
j = {"appeal": 64, "ai_fit": 81, "rel": 5}
jobfinder.combine(j)
check("rated jobs: Best bets is still Appeal x Match, whatever the Relevance", j["score"] == round(math.sqrt(64 * 81)))
hi, lo, unk = {"appeal": 64, "rel": 100}, {"appeal": 64, "rel": 0}, {"appeal": 64, "rel": None}
for x in (hi, lo, unk):
    jobfinder.combine(x)
check("unrated jobs: ordered by Relevance instead of a flat Match 50 (no sheet: 50 as before)",
      hi["score"] > unk["score"] > lo["score"] and unk["score"] == round(math.sqrt(64 * 50)) and hi["score"] < round(math.sqrt(64 * 81)), str((hi["score"], unk["score"], lo["score"])))
top_unrated = {"id": "u", "appeal": 100, "rel": 100}
rated = [{"id": f"r{a}{m}", "appeal": a, "ai_fit": m, "rel": 0} for a in (80, 90, 100) for m in (70, 85, 91, 100)]
for x in [top_unrated] + rated:
    jobfinder.combine(x)
check("the rule: no unrated job, however relevant and appealing, outranks a rated job with Match 70+ and Appeal 80+",
      jobfinder.unrated_match(top_unrated) == jobfinder.UNRATED_MAX == 55 and all(x["score"] > top_unrated["score"] for x in rated),
      str((top_unrated["score"], min(x["score"] for x in rated))))
weak = {"id": "w", "appeal": 90, "ai_fit": 20, "rel": 0}
jobfinder.combine(weak)
check("...while a very relevant unrated job still sits above one Claude found a poor match", top_unrated["score"] > weak["score"])
tie = [{"id": "b", "score": 70, "ai_fit": 60, "appeal": 80}, {"id": "a", "score": 70, "ai_fit": 60, "appeal": 80}, {"id": "c", "score": 70, "appeal": 90},
       {"id": "d", "score": 70, "ai_fit": 91, "appeal": 54}, {"id": "e", "score": 70, "ai_fit": 60, "appeal": 82}, {"id": "f", "score": 71, "appeal": 1}]
import random as _r
orders = set()
for seed in range(5):
    _r.Random(seed).shuffle(tie)
    orders.add("".join(x["id"] for x in sorted(tie, key=jobfinder.board_order)))
check("Best bets ties are broken the same way every time: better Match, then better Appeal, then the id; unrated last", orders == {"fdeabc"}, str(orders))

claude_cli.claude_ready = lambda *a, **k: True
sent = []
def fake_rate(todo, tier, inf, log, on_batch=None):
    sent.append((tier, [j["id"] for j in todo]))
    res = {}
    for j in todo:
        r = {"asis": 60, "fit": 70, "label": "tailor", "level": "match", "reason": "stub", "tailor": ""}
        ai_score.stamp(r, inf); r["at"] = "2026-01-01"
        res[j["id"]] = r
    if res and on_batch:
        on_batch(res)
    return res
real_rate, ai_score._rate = ai_score._rate, fake_rate
N = 900
pool = [{"id": f"j{i:04d}", "title": "t", "company": "C", "locations": ["X"], "desc": "d", "req": None,
         "appeal": 100 - (i % 100), "rel": (i * 37) % 101} for i in range(N)]
prepared = []
ai_score.run_funnel(pool, {"haiku": 10 ** 9, "sonnet_pct": 0, "opus_top": 0}, log=lambda m: None, tiers=["haiku"],
                    prepare=lambda todo, log: prepared.append(len(todo)))
got = sent[0][1]
want = [j["id"] for j in sorted(pool, key=lambda j: (-j["rel"], -j["appeal"], j["id"]))[:ai_score.RUN_LIMITS["haiku"]]]
check(f"a run rates the {ai_score.RUN_LIMITS['haiku']} most relevant jobs (then Appeal), within the per-run limit", got == want and len(got) == 500)
check("the least relevant picked job beats every job left out", min(j["rel"] for j in pool if j["id"] in set(got)) >= max(j["rel"] for j in pool if j["id"] not in set(got)))
check("missing posting text is asked for just before rating, for the picked jobs only", prepared == [500])
sent.clear()
only = {j["id"] for j in pool if j["id"] not in set(got)}
ai_score.run_funnel(pool, {"haiku": 10 ** 9, "sonnet_pct": 0, "opus_top": 0}, log=lambda m: None, tiers=["haiku"], only_ids=only)
q = sent[0][1]
rest = sorted((j for j in pool if j["id"] in only), key=lambda j: (-j["rel"], -j["appeal"], j["id"]))
check("the automatic quick check picks by relevance too, within its own limit", q == [j["id"] for j in rest[:ai_score.RUN_LIMITS["quick"]]])
sent.clear()
flat = [{"id": f"k{i:04d}", "title": "t", "company": "C", "locations": ["X"], "desc": "d", "req": None, "appeal": i % 100, "rel": None} for i in range(600)]
ai_score.run_funnel(flat, {"haiku": 10 ** 9, "sonnet_pct": 0, "opus_top": 0}, log=lambda m: None, tiers=["haiku"])
check("no sheet (Relevance unknown): best Appeal first, as before", sent[0][1][:3] == [j["id"] for j in sorted(flat, key=lambda j: (-j["appeal"], j["id"]))[:3]])
ai_score._rate = real_rate

# ------------------------------------------------------------------ 9. with Claude (stubbed): same call / one small call
LOOK = {"recent_title": "Registered Nurse", "same_titles": ["Staff Nurse", "RN", "Bedside Nurse"], "step_up_titles": ["Charge Nurse", "Nurse Manager"],
        "related_roles": ["Clinical Educator", "Case Manager"], "key_skills": ["wound care", "BLS"], "field": "Hospital nursing"}
PROFILE = {"name": "N", "summary": "Nurse.", "location": "Springfield, IL", "years_experience": 8, "clearances": [], "education": [], "certifications": [],
           "skills": ["patient care"], "languages": [],
           "experience": [{"employer": "Old Clinic", "title": "Nursing Assistant", "dates": "2014 - 2017", "highlights": []},
                          {"employer": "Mercy", "title": "Registered Nurse", "dates": "2017 - Present", "highlights": []}],
           "reframings": [], "hard_limits": [], "target_roles": ["Registered Nurse"], "title_keywords": ["registered nurse"], "fit_keywords": [], "look_for": LOOK}
stub = os.path.join(SCRATCH, "relevance_stub.json")
json.dump({"_by_prompt": [["Resume:", PROFILE], ["Most recent job title:", dict(LOOK, same_titles=["Shift Nurse"], related_roles=["Triage Nurse"])]]}, open(stub, "w"))
os.environ["SIFTWELL_CLAUDE_STUB"] = stub
usage = lambda: [json.loads(l) for l in open(claude_usage.path(), encoding="utf-8")] if os.path.exists(claude_usage.path()) else []
n0 = len(usage())
cl = people.add("With Claude")
people.set_current(cl)
prof = resume.build_profile("Registered Nurse at Mercy, 2017 to present ...")
check("the resume reader returns the sheet in its ONE call (no second request)", len(usage()) == n0 + 1 and prof["look_for"]["same_titles"][:2] == ["Staff Nurse", "RN"])
check("the reader's schema asks for it", "look_for" in resume.PROFILE_SCHEMA["required"])
json.dump(prof, open(resume.DRAFT(), "w"))
resume.approve({})
sheet = lookfor.ensure(cl)
tiers = {x["t"]: (x["tier"], x["src"]) for x in sheet["titles"]}
check("the most recent job (still running), not the first listed, counts most", sheet["recent"] == "Registered Nurse" and tiers["Nursing Assistant"][0] == "past")
check("Claude's names, step-ups and related roles land in their tiers", tiers["Bedside Nurse"] == ("same", "claude") and tiers["Nurse Manager"][0] == "up"
      and tiers["Case Manager"][0] == "related" and sheet["field"] == "Hospital nursing" and "wound care" in {x["t"] for x in sheet["skills"]})
check("O*NET stays underneath as the base layer", any(x["src"] == "onet" for x in sheet["occs"]))
check("a resume-made sheet needs no further Claude call", not lookfor.needs_suggest(cl) and lookfor.suggest(cl) is None and len(usage()) == n0 + 1)
check("the sheet is not part of the rating key", resume.profile_hash(prof) == resume.profile_hash({k: v for k, v in prof.items() if k != "look_for"}))

# a hand-made profile: one small call when the title is new, none after, none without Claude
people.set_current(pids["trucker"])
check("upgrade / existing profile: the sheet was built with no Claude call and asks for none", not lookfor.needs_suggest(pids["trucker"]))
lookfor.edit(pids["trucker"], {"recent": "Dispatcher"})
check("a changed job title is worth one small call", lookfor.needs_suggest(pids["trucker"]))
n1 = len(usage())
out = lookfor.suggest(pids["trucker"])
rows = usage()[n1:]
check("...made with the cheap model and logged for Settings", out is not None and len(rows) == 1 and rows[0]["feature"] == "What to look for" and "haiku" in rows[0]["model"], str(rows))
check("...and folded into the sheet", "Shift Nurse" in {x["t"] for x in out["titles"]} and "Triage Nurse" in {x["t"] for x in out["titles"]})
# "Ask Claude for more ideas" on a profile that came from a resume: the answer is merged with the resume reader's, not lost
people.set_current(cl)
n2 = len(usage())
before_titles = {x["t"] for x in lookfor.load(cl)["titles"]}
out2 = lookfor.suggest(cl, force=True)
t2 = {x["t"]: (x["tier"], x["src"]) for x in out2["titles"]}
check("asking Claude for more on a resume-made profile changes the sheet (one call; new titles added, the resume reader's kept)",
      len(usage()) == n2 + 1 and "Shift Nurse" not in before_titles and t2.get("Shift Nurse") == ("same", "claude") and "Triage Nurse" in t2
      and "Bedside Nurse" in t2 and "Case Manager" in t2, str(sorted(t2)))
check("...the newer answer goes first", [x["t"] for x in out2["titles"] if x["src"] == "claude" and x["tier"] == "same"][0] == "Shift Nurse")
check("...and it survives a rebuild", "Shift Nurse" in {x["t"] for x in lookfor.build(cl)["titles"]})
lookfor.edit(cl, {"remove": "title", "text": "Shift Nurse"})
out3 = lookfor.suggest(cl, force=True)
check("a title the person removed is not brought back by asking again", "Shift Nurse" not in {x["t"] for x in out3["titles"]})
people.set_current(pids["trucker"])
n1 = len(usage()) - 1          # (the checks below count from here)
check("...then never again for the same titles", lookfor.suggest(pids["trucker"]) is None and len(usage()) == n1 + 1)
claude_cli.claude_ready = lambda *a, **k: False
lookfor.edit(pids["trucker"], {"recent": "Truck Driver"})
check("without Claude nothing is asked (and nothing breaks)", lookfor.suggest(pids["trucker"]) is None and len(usage()) == n1 + 1)
os.environ.pop("SIFTWELL_CLAUDE_STUB")
log = os.path.join(DATA, claude_cli.FORBID_LOG)
check("no real Claude call was attempted anywhere in this test", not os.path.exists(log), open(log).read() if os.path.exists(log) else "")

# ------------------------------------------------------------------ 10. the earlier shared lists move onto profiles' own lists
D2 = os.path.join(SCRATCH, "relevance_lists")
shutil.rmtree(D2, ignore_errors=True)
os.makedirs(os.path.join(D2, "people"))
import importlib
os.environ["JOBBOARD_DATA"] = D2
for m in (paths, people, catalog):
    importlib.reload(m)
json.dump([{"id": "ann", "name": "Ann"}, {"id": "bob", "name": "Bob"}, {"id": "cy", "name": "Cy"}, {"id": "dee", "name": "Dee"}], open(people.INDEX, "w"))
for p in ("ann", "bob", "cy", "dee"):
    people.pdir(pid=p)
json.dump({"salary_floor": 150000, "goals": "g"}, open(people.pdir("settings.json", pid="ann"), "w"))              # before the key existed: watched "tech"
json.dump({"salary_floor": 90000, "company_sets": ["ops", "nonprofit"]}, open(people.pdir("settings.json", pid="bob"), "w"))
json.dump({"salary_floor": 0, "company_sets": [], "title_rule": "own"}, open(people.pdir("settings.json", pid="cy"), "w"))  # a new-style profile
# dee: no settings file at all (the oldest layout): watched "tech"
COS = {"TechCo": ["tech"], "OpsCo": ["ops"], "Charity": ["nonprofit"], "Both": ["ops", "tech"], "AnnOwn": ["own-ann"], "CyNear": ["near-cy"],
       "Everyone": ["all"], "Mixed": ["nonprofit", "near-cy"], "Orphan": ["tech"]}
for name, sets in COS.items():
    catalog.save_company({"name": name, "ats": "greenhouse", "token": name.lower(), "sets": sets})
with catalog.db() as con:
    con.execute("UPDATE companies SET sets='[]' WHERE name='Orphan'")
    con.execute("INSERT INTO companies(name, ats, cfg, tier, sector) VALUES('Defaulted', 'greenhouse', '{}', '', '')") if False else None
OLD_WATCH = {"ann": {"tech"}, "bob": {"ops", "nonprofit"}, "cy": set(), "dee": {"tech"}}
def watched(old_rule):
    out = {}
    for p in ("ann", "bob", "cy", "dee"):
        w = ({f"own-{p}", f"near-{p}", "all"} | OLD_WATCH[p]) if old_rule else people.company_sets(p)
        out[p] = sorted(n for n, s in catalog.sets_map().items() if s & w)
    return out
before = watched(True)
check("(the old-style catalog is what the test thinks it is)", before["ann"] == ["AnnOwn", "Both", "Everyone", "TechCo"] and "Charity" in before["bob"] and before["cy"] == ["CyNear", "Everyone", "Mixed"], str(before))
moved = catalog.move_lists(log=lambda m: None)
after = watched(False)
check("every profile watches exactly the companies it watched before", moved and after == before, str(after))
sm = catalog.sets_map()
check("no old list name is left on any company", not any(s & {"tech", "ops", "nonprofit"} for s in sm.values()), str(sm))
check("a company nobody watched stays in the catalog, watched by nobody", sm["Orphan"] == set() and "Orphan" in {c["name"] for c in catalog.companies()})
check("the old setting is gone from the profiles; nothing else in their files changed",
      json.load(open(people.pdir("settings.json", pid="bob"))) == {"salary_floor": 90000}
      and json.load(open(people.pdir("settings.json", pid="ann"))) == {"salary_floor": 150000, "goals": "g"}
      and not os.path.exists(os.path.join(people.ROOT, "dee", "settings.json")))
check("older profiles keep their other old defaults (pay floor, built-in title words)", people.settings("dee")["salary_floor"] == 150000 and people.settings("ann")["title_rule"] == "builtin")
snap = json.dumps({k: sorted(v) for k, v in sm.items()}, sort_keys=True)
check("running it again changes nothing", catalog.move_lists(log=lambda m: None) is False and json.dumps({k: sorted(v) for k, v in catalog.sets_map().items()}, sort_keys=True) == snap)
catalog.set_meta("lists_moved", None)
check("...even with the marker gone (nothing left to move)", catalog.move_lists(log=lambda m: None) is False and watched(False) == before)
check("the lists are gone from the code people see", not hasattr(people, "COMPANY_SETS") and not hasattr(jobfinder, "LIST_SHORT") and "company_sets" not in people.DEFAULT_SETTINGS)
catalog.save_company({"name": "NewCo", "ats": "greenhouse", "token": "newco"})
check("a company saved without a list is watched by nobody (no default list)", catalog.sets_map()["NewCo"] == set())

# ------------------------------------------------------------------ 11. the board's title filter is the sheet
rn = people.add("Sheet Nurse"); people.set_current(rn)
resume.save_manual({"name": "Sheet Nurse", "current_title": "Registered Nurse", "skills": ["patient care"], "experience": []})
people.save_settings({"home_zip": "43215", "radius_miles": 35}, rn)
lookfor.build(rn)
nt = people.add("No Titles")
people.save_settings({"home_zip": "43215", "radius_miles": 35}, nt)
catalog.save_company({"name": "Sheet Hospital", "ats": "greenhouse", "token": "sheethosp", "sets": [f"own-{rn}", f"own-{nt}"], "tier": "", "sector": "Health"})
SH = [("s1", "Registered Nurse - ICU"), ("s2", "Nurse Practitioner"), ("s3", "Family Nurse Practitioner - Urgent Care"),
      ("s4", "Certified Registered Nurse Anesthetist (CRNA)"), ("s5", "Staff Nurse"), ("s6", "Nurse Recruiter")]
shc = next(c for c in catalog.companies() if c["name"] == "Sheet Hospital")
with catalog.db() as con:
    catalog.record_fetch("Sheet Hospital", {"status": "ok", "raw_jobs": len(SH), "secs": 1},
                         [jobfinder.prepare_listing(jobfinder.J(shc, t, "https://example.com/" + i, ["Columbus, OH"], "", None, "Patient care.", "", "", i), shc) for i, t in SH], con)
def board_of(pid):
    out = jobfinder.recompute([pid])
    d = json.load(open(people.pdir("jobs.json", pid=pid), encoding="utf-8"))
    pick = lambda js: {j["id"].split("::")[1]: j for j in js if j["company"] == "Sheet Hospital"}
    return pick(d["jobs"]), pick(d.get("off_jobs") or []), out[pid]
on, off, res = board_of(rn)
check("own-titles nurse: RN, Staff Nurse and (a related role) Nurse Practitioner jobs are on the board",
      {"s1", "s2", "s3", "s5"} <= set(on), str((sorted(on), sorted(off))))
check("...a CRNA (nothing on the list names it: Relevant 0) is not",
      "s4" in off and "s4" not in on, str((sorted(on), sorted(off), {k: (v["rel"], v["rel_why"]) for k, v in {**on, **off}.items()})))
check("...they are kept apart for 'N hidden because their titles aren't on your list - Show', and not counted",
      res["jobs"] == len(json.load(open(people.pdir("jobs.json", pid=rn), encoding="utf-8"))["jobs"]) and all(v.get("off_list") for v in off.values()))
jobfinder.use_cfg(jobfinder.person_cfg(rn)[0])
check("...and Claude is never asked about them", not any(jobfinder.eligible_for_claude(v) for v in off.values())
      and not set(off) & {i.split("::")[1] for i in jobfinder.new_unrated(rn, list(on.values()) + list(off.values()))[0]})
lookfor.edit(rn, {"remove": "occ", "code": np_code})
on2, off2, _ = board_of(rn)
check("removing 'Nurse Practitioners' from the list takes the NP jobs off the board", {"s2", "s3"} <= set(off2) and not {"s2", "s3"} & set(on2) and "s1" in on2,
      str((sorted(on2), sorted(off2))))
on3, off3, _ = board_of(nt)
check("an empty list: every title passes, as before", len(on3) == len(SH) and not off3, str((sorted(on3), sorted(off3))))
people.set_current(rn)
fake = [{"title": "Certified Registered Nurse Anesthetist (CRNA)", "tracks": ["current"]}]
check("a profile on the earlier built-in word list is not filtered by its sheet",
      jobfinder.mark_off_list(fake, lookfor.scorer(rn), {"title_rule": "builtin"}) == 0 and not fake[0].get("off_list")
      and jobfinder.mark_off_list(fake, lookfor.scorer(rn), {}) == 1)
fake = [{"title": "Certified Registered Nurse Anesthetist (CRNA)", "tracks": ["current", "ai"]}]
jobfinder.mark_off_list(fake, lookfor.scorer(rn), {})
check("a job that is also there for the Target tab stays, for that tab only", fake[0]["tracks"] == ["ai"] and fake[0]["off_list"])

print("\n" + ("ALL OK" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
