"""Offline checks for a profile someone filled in themselves (no Claude), as a nurse with a BSN would:
the degree she typed is read with its level and field ("BSN", "B.S.N.", "Bachelor of Science in Nursing", "ADN", "MBA",
"BS Computer Science" ...), postings' requirements are read exactly (CCNE is not a Cisco certification, PRN is not a
nurse practitioner, "A.D.N degree required" is an Associate's), the What Siftwell looks for sheet has no junk (places
as skills, "RN license; BLS; ACLS" as one chip, "rn, medical-surgical" as a related role), and the setup pages (the
typed job title, the level hint, the steps without Claude, Skip on the Where step). No network, no Claude.
Its own scratch data folder.

    python -X utf8 scripts/test_profile_fixes.py <scratch dir>
"""
import json, os, shutil, sys

if len(sys.argv) < 2:
    sys.exit("usage: python -X utf8 scripts/test_profile_fixes.py <scratch dir>")
SCRATCH = os.path.abspath(sys.argv[1])
DATA = os.path.join(SCRATCH, "profile_fixes_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CODEX"] = "1"
os.environ.pop("SIFTWELL_CLAUDE_STUB", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import people, resume, highlights, requirements, lookfor, setup_flow, setup_page, manual_profile, ai_score

fails = 0


def check(label, ok, detail=""):
    global fails
    print(("ok   " if ok else "FAIL ") + label + (f"   [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


# ------------------------------------------------------------------ A1. the degree a person typed
D = highlights.parse_degree
def deg(s):
    d = D(s)
    return (d["level"], d["field_group"]) if d else None

CASES = [
    ("BSN", ("bachelor", "nursing")), ("B.S.N.", ("bachelor", "nursing")), ("Bachelor of Science in Nursing", ("bachelor", "nursing")),
    ("BSN, Ohio State University, 2018", ("bachelor", "nursing")), ("bsn", ("bachelor", "nursing")),
    ("ADN", ("associate", "nursing")), ("ASN", ("associate", "nursing")), ("A.D.N.", ("associate", "nursing")),
    ("Associate Degree in Nursing", ("associate", "nursing")), ("MSN", ("master", "nursing")), ("DNP", ("doctorate", "nursing")),
    ("MBA", ("master", "business")), ("BBA", ("bachelor", "business")), ("BSW", ("bachelor", "social-sciences")),
    ("MSW", ("master", "social-sciences")), ("MEd", ("master", "education")), ("JD", ("jd", "law")),
    ("PhD", ("doctorate", "other")), ("BA", ("bachelor", "other")), ("BS", ("bachelor", "other")), ("B.A.", ("bachelor", "other")),
    ("B.S.", ("bachelor", "other")), ("MS", ("master", "other")), ("MA", ("master", "other")),
    ("BS Computer Science", ("bachelor", "computer-science")), ("B.A., English", ("bachelor", "communications-english")),
    ("MS in Accounting", ("master", "accounting")), ("PhD in Chemistry", ("doctorate", "physical-sciences")),
    ("Bachelor's degree, Accounting", ("bachelor", "accounting")), ("Accounting, B.S., 2011", ("bachelor", "accounting")),
    ("Associate degree in Business, Lakeside Community College", ("associate", "business")),
    ("Master of Business Administration, Xavier University", ("master", "business")),
    ("Boston College, Chestnut Hill, MA - BA History", ("bachelor", "social-sciences")),
    # not degrees
    ("University of Massachusetts, Amherst, MA", None), ("Med-Surg certificate", None), ("MS Office coursework", None),
    ("Diploma, Columbus High School", None),
]
for text, want in CASES:
    check(f"degree typed as {text!r} -> {want}", deg(text) == want, str(D(text)))
check("the school is never taken for the field", D("BSN, University of Toledo")["field"] == "Nursing" and D("BS, Ohio State University")["field"] == "",
      str((D("BSN, University of Toledo"), D("BS, Ohio State University"))))

NURSE = {"name": "Nora Test", "location": "Columbus, OH", "current_title": "Registered Nurse", "years_experience": 6,
         "summary": "Medical-surgical nurse.",
         "experience": [{"title": "Staff RN, Medical-Surgical", "employer": "Riverside Hospital", "dates": "2019 - Present",
                         "highlights": ["Cared for five to six patients a shift"]}],
         "skills": ["Patient care", "Ohio", "Epic", "IV therapy"], "education": ["BSN, Ohio State University, 2018"],
         "certifications": ["RN license; BLS; ACLS"], "clearance": ""}
pid = people.add("Nora")
people.set_current(pid)
prof = resume.save_manual(NURSE)
hl = highlights.refresh(pid, prof, use_claude=False)
check("a hand-filled 'BSN, Ohio State University, 2018' is a Bachelor's in Nursing",
      [(d["level"], d["field"], d["field_group"]) for d in hl["degrees"]] == [("bachelor", "Nursing", "nursing")], str(hl["degrees"]))
check("'RN license; BLS; ACLS' is three credentials", [x["name"] for x in hl["licenses"]] == ["RN license", "BLS", "ACLS"], str(hl["licenses"]))
check("...and a state after a comma stays with its license",
      [x["name"] for x in highlights.from_profile_rules({"certifications": ["RN license, Ohio", "BLS, ACLS, PALS"]})["licenses"]]
      == ["RN license, Ohio", "BLS", "ACLS", "PALS"])

BSN_POSTS = ["Requirements:\n- Bachelor's in Nursing required\n- Current RN license required",
             "Requirements:\n- BSN required", "Requirements:\n- B.S.N. required",
             "Requirements:\n- Bachelor of Science in Nursing (BSN) from an accredited school required"]
for d in BSN_POSTS:
    r = requirements.check(requirements.parse(d), highlights.get(pid))
    check(f"a BSN holder meets {d.splitlines()[1]!r}", r["status"] == "ok" and not r["chips"], str(r))
r = requirements.check(requirements.parse("Requirements:\n- MSN required"), highlights.get(pid))
check("...and is still told about a Master's in Nursing she lacks", r["chips"] == ["Requires Master's in Nursing"], str(r))

# a profile whose highlights an earlier version read ("Bachelor's", field unknown): the working view finds the field
# group again, and what ratings were made from (level + field text) is exactly as stored
old = people.add("Olive")
people.set_current(old)
resume.save_manual(NURSE)
STORED = {"degrees": [{"level": "bachelor", "field": "", "field_group": "other", "school": "", "year": 2018, "completed": True}],
          "licenses": [{"name": "RN license; BLS; ACLS", "kind": "license", "active": None}], "years_experience": 6}
highlights.save_raw(old, {"extracted": highlights.normalize(STORED), "edits": {}, "confirmed": None})
before = ai_score._fp_hl_line(highlights.merged(highlights.load_raw(old)))
r = requirements.check(requirements.parse(BSN_POSTS[0]), highlights.get(old))
check("highlights read by an earlier version: 'Bachelor's in Nursing' is met too (no 'field/level unclear')", r["status"] == "ok" and not r["chips"], str(r))
raw = highlights.load_raw(old)
check("...without changing what is stored, or the line ratings are fingerprinted with",
      raw["extracted"]["degrees"][0]["field"] == "" and raw["extracted"]["degrees"][0]["field_group"] == "other"
      and ai_score._fp_hl_line(highlights.merged(raw)) == before
      == "Confirmed by the candidate: degrees: bachelor; licenses/certifications: RN license; BLS; ACLS; years of experience: 6",
      before)
people.set_current(pid)

# ------------------------------------------------------------------ A2. certification names are whole and exact
def found(desc):
    r = requirements.parse(desc)
    return sorted(x["key"] for x in r["licenses"] + r["certs"])

CCNE = ("Requirements:\n- Graduate of a nursing program accredited by the Commission on Collegiate Nursing Education (CCNE) "
        "or ACEN required.\n- CCNE accreditation required")
check("'Commission on Collegiate Nursing Education' / CCNE is not a Cisco certification", found(CCNE) == [], str(found(CCNE)))
r = requirements.check(requirements.parse(CCNE), highlights.get(pid))
check("...so the nurse sees no 'Requires Cisco cert'", r["status"] == "ok" and not any("Cisco" in c for c in r["chips"] + r["soft"]), str(r))
for name in ("CCNA", "CCNP", "CCIE"):
    check(f"{name} is still a Cisco certification", found(f"Requirements:\n- {name} certification required") == ["CCNA"])
for name in ("CCNE", "CCNB", "CCIA", "ACCNA", "CCNAX"):
    check(f"{name} is not", found(f"Requirements:\n- {name} certification required") == [], str(found(f"Requirements:\n- {name} certification required")))
check("PRN (an as-needed shift) is not a nurse practitioner license",
      found("PRN position.\nRequirements:\n- PRN availability required\n- Current RN license required") == ["RN"])
check("...APRN is", found("Requirements:\n- APRN license required") == ["NP"])
check("CSM as a job (Customer Success Manager) is not a Scrum certification", found("Requirements:\n- 3+ years as a CSM required") == [])
check("...CSM next to Scrum / certification is", found("Requirements:\n- CSM or other Scrum certification required") == ["SCRUM"])
check("'Board certified in Medical-Surgical Nursing' is not a physician's license",
      found("Requirements:\n- Board certified in Medical-Surgical Nursing required") == [])
check("...'Board certified in Internal Medicine' is", found("Requirements:\n- Board certified in Internal Medicine required") == ["MDLIC"])
check("a number that only contains 8570 is not the DoD directive",
      found("Requirements:\n- Certification required. Call 555-18570 or see req 85701") == []
      and found("Requirements:\n- DoD 8570 IAT Level II certification required") == ["SECPLUS"])

# ------------------------------------------------------------------ A3. an Associate's in Nursing is not a Bachelor's
for line in ("A.D.N degree required", "A.D.N. degree required", "ADN required", "Associate Degree in Nursing required",
             "ASN required", "Must have an A.D.N degree", "A nursing degree (A.D.N) required", "A nursing degree required"):
    req = requirements.parse("Requirements:\n- " + line)
    lv = [(d["level"], d["fields"]) for d in req["degrees"]]
    check(f"{line!r} asks for an Associate's in Nursing", lv == [("associate", ["nursing"])], str(lv))
    r = requirements.check(req, highlights.get(pid))
    check("...which a BSN holder meets", r["status"] == "ok" and not r["chips"], str(r))
r = requirements.check(requirements.parse("Requirements:\n- A.D.N degree required"),
                       highlights.normalize({"degrees": [{"level": "bachelor", "field": "English", "field_group": "communications-english"}]}))
check("...and someone with no nursing degree is told 'Associate's in Nursing', not Bachelor's",
      r["chips"] and r["chips"][0].startswith("Requires Associate's in Nursing"), str(r))

# ------------------------------------------------------------------ B1. the What Siftwell looks for sheet
v = lookfor.view(pid)
skills = [x["t"] for x in v["skills"]]
titles = {k: [x["t"] for x in v[k]] for k in ("same", "up", "related", "past")}
check("'RN license; BLS; ACLS' is three skills on the sheet", all(s in skills for s in ("RN license", "BLS", "ACLS")) and not any(";" in s for s in skills), str(skills))
check("a state typed among the skills ('Ohio') is not a skill", not any(s.lower() == "ohio" for s in skills), str(skills))
check("...real skills stay", all(s in skills for s in ("Patient care", "Epic", "IV therapy")), str(skills))
check("no related role 'rn, medical-surgical'", not any("medical" in t.lower() for t in titles["related"] + titles["same"] + titles["up"]), str(titles))
check("the role line 'Staff RN, Medical-Surgical' is on the sheet as the title 'Staff RN'",
      "Staff RN" in titles["same"] + titles["past"] and not any("," in t for ts in titles.values() for t in ts), str(titles))
check("...and its specialty is a skill", "Medical-Surgical" in skills, str(skills))
S = highlights.split_items
check("split: commas, semicolons and new lines", S("BLS, ACLS; PALS\nNRP") == ["BLS", "ACLS", "PALS", "NRP"])
check("split: nothing inside brackets", S("Low-code tools (Mendix, Appian), SQL") == ["Low-code tools (Mendix, Appian)", "SQL"])
check("places are dropped: a state, City, ST, the person's own town", S("Ohio; Columbus, OH; Epic", "Columbus, OH") == ["Epic"] and S("Dayton", "Dayton, OH") == [])
check("a skill that only contains a place word stays", S("Ohio RN license; Phoenix; Oracle; Reading; New York Life underwriting")
      == ["Ohio RN license", "Phoenix", "Oracle", "Reading", "New York Life underwriting"], str(S("Ohio RN license; Phoenix; Oracle; Reading; New York Life underwriting")))
check("short codes that are also skills stay (OR, PA, CT)", S("OR, PA, CT") == ["OR", "PA", "CT"])
C = lookfor._title_core
check("title and specialty", C("Staff RN, Medical-Surgical") == ("Staff RN", "Medical-Surgical") and C("Registered Nurse, ICU") == ("Registered Nurse", "ICU"),
      str((C("Staff RN, Medical-Surgical"), C("Registered Nurse, ICU"))))
check("'Manager, Sales Operations' / 'Director, Nursing' keep their comma (the function is part of the title)",
      C("Manager, Sales Operations") == ("Manager, Sales Operations", "") and C("Director, Nursing") == ("Director, Nursing", "")
      and C("Senior Manager, Finance") == ("Senior Manager, Finance", ""))
check("a shift or schedule after the comma is not a specialty", C("Sales Associate, Part-Time") == ("Sales Associate", ""))

# ------------------------------------------------------------------ B2. the job title typed on the form comes first
check("the sheet's most recent title is the typed 'Registered Nurse', not the role line", v["recent"] == "Registered Nurse", v["recent"])
check("...and that is what setup's job title question starts with", setup_flow.recent_title(pid) == "Registered Nurse"
      and setup_flow.get_state(pid)["values"]["recent_title"] == "Registered Nurse", setup_flow.recent_title(pid))
check("no title typed: the most recent role (unchanged)", lookfor._auto_recent({"_manual": True, "target_roles": ["Staff RN"],
      "experience": [{"title": "Staff RN", "dates": "2019 - Present"}]}) == "Staff RN")
check("a resume Claude read: the most recent role (unchanged)", lookfor._auto_recent({"target_roles": ["Nurse Educator", "Staff RN"],
      "experience": [{"title": "Staff RN", "dates": "2019 - Present"}]}) == "Staff RN")

# ------------------------------------------------------------------ B7. the level hint
check("six years as a staff nurse: no level hint", setup_flow.infer_level(prof) is None and setup_flow.get_state(pid)["inferred"]["level"] is None,
      str(setup_flow.infer_level(prof)))
check("years alone never make a hint", setup_flow.infer_level({"experience": [{"title": "Accountant"}], "years_experience": 15}) is None)
g = setup_flow.infer_level({"experience": [{"title": "Senior Accountant"}], "years_experience": 2})
check("a title that states its level does", bool(g) and g["level"] == 3 and "Senior Accountant" in g["why"] and "years" not in g["why"], str(g))
g = setup_flow.infer_level({"experience": [{"title": "Nurse Manager"}], "years_experience": 12})
check("...'Nurse Manager' is Lead / Manager", bool(g) and g["level"] == 4, str(g))

# ------------------------------------------------------------------ B4 / B5 / B6 / B3. the setup steps
check("without Claude the tailoring questions are not a step", "questions" not in setup_flow.steps_for(False)
      and setup_flow.steps_for(True) == setup_flow.STEPS and len(setup_flow.steps_for(False)) == len(setup_flow.STEPS) - 1)
check("...Employers is followed by the last screen", setup_flow.next_step("companies", False) == "board" and setup_flow.next_step("companies", True) == "questions")
setup_flow._write(pid, {"setup_step": "questions", "setup_done": False})
st = setup_flow.get_state(pid)
check("...and someone who had stopped on that step carries on at the last one", st["step"] == "board" and "questions" not in st["active_steps"], st["step"])
setup_flow._write(pid, {"setup_step": "where"})
st = setup_flow.save_step(pid, "where", {"skipped": True})
check("the Where step can be skipped: nothing saved, on to Pay", st["step"] == "pay" and st["values"]["home_zip"] == "" and st["values"]["workplaces"] == setup_flow.WORKPLACES, str(st["step"]))
try:
    setup_flow.validate("where", {"workplaces": []}); ok = False
except setup_flow.SetupError:
    ok = True
check("...Continue on it still checks the answers", ok)
P = setup_page.PAGE
check("the stepper says Employers, like the page", '"Dealbreakers", "Employers", "Questions"' in P and '"Companies"' not in P)
check("the Where screen offers Skip", 'skip(){ saveAndNext("where", {skipped: true}); }' in P)
check("an error is put on the page once (its box is the alert; no copy in the live region)",
      'role="alert"' in P and "\n  say(msg);\n}" not in P.replace("\r\n", "\n"))
check("Continue / Back pass over a step that is left out", "go(nextStep || nextOf(step))" in P and "let p = prevOf(cur)" in P)
check("the form splits credentials at semicolons", "certifications: splitCreds(D.certifications)" in manual_profile.JS)

try:
    log = open(os.path.join(DATA, "forbidden_claude_calls.log")).read().strip()
except OSError:
    log = ""
check("no Claude call was attempted", not log, log[:200])

print(f"\n{fails} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
