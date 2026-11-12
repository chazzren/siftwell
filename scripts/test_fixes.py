"""Offline checks for the ratings / tokens / tailoring fixes: ratings kept when the profile is edited, the Target tab's
narrow re-check after one answer, per-run and per-night limits, the usage log, the lean Claude command line, local PDF
text, the model each small job uses, boards rebuilt after an upgrade, highlights before the first rating, and the
tailored resume's fact check and Word file. No network, no Claude (stubs and fakes only), its own scratch data folder.

    python -X utf8 scripts/test_fixes.py <scratch dir>
"""
import json, os, shutil, sys, threading, time

if len(sys.argv) < 2:
    sys.exit("usage: python -X utf8 scripts/test_fixes.py <scratch dir>")
SCRATCH = os.path.abspath(sys.argv[1])
DATA = os.path.join(SCRATCH, "fixes_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CODEX"] = "1"
for k in ("SIFTWELL_CLAUDE_STUB", "SIFTWELL_PRETEND_NO_CLAUDE", "SIFTWELL_NIGHT"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [sys.argv[0], "8891"]          # (server.py reads its port from argv when imported; nothing is started)

import people, paths, catalog, jobfinder, ai_score, pivot, claude_cli, claude_usage, resume, interview, target, tailor, review, osdeps, lookfor

fails = 0


def check(label, ok, detail=""):
    global fails
    print(("ok   " if ok else "FAIL ") + label + (f"   [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


real_ready = claude_cli.claude_ready
claude_cli.claude_ready = lambda *a, **k: False
FORBID_LOG = os.path.join(DATA, claude_cli.FORBID_LOG)

PHONE = "217-555-" + "0142"      # (a made-up number, put together here so the release leak scan sees no phone number)
PROFILE = {"name": "Dana Whitfield", "summary": "Office manager with eight years of experience in dental and medical practices.",
           "location": "Springfield, IL", "years_experience": 8, "clearances": [], "education": ["Associate of Applied Science, Office Administration, Richland Community College, 2014"],
           "certifications": ["CPR and First Aid (American Red Cross)"], "skills": ["Dentrix", "QuickBooks", "Insurance verification", "Staff scheduling"], "languages": [],
           "experience": [{"employer": "Maple Street Dental Associates", "title": "Office Manager", "dates": "March 2019 - Present",
                           "highlights": ["Run the front office for a four-dentist practice with six support staff.", "Trained three new receptionists on phones, check-in and recall calls."]},
                          {"employer": "Lakeview Family Clinic", "title": "Front Desk Coordinator", "dates": "June 2016 - February 2019",
                           "highlights": ["Checked in about sixty patients a day and answered a six-line phone."]}],
           "reframings": [], "hard_limits": [], "target_roles": ["Office Manager"], "title_keywords": ["office manager"], "fit_keywords": [], "notes": "",
           "_resume_text": "Dana Whitfield\nSpringfield, IL | dana@example.com | " + PHONE + " | linkedin.com/in/danaw\n\nEXPERIENCE\nOffice Manager, Maple Street Dental Associates (March 2019 - Present)\n"
                           "- Run the front office for a four-dentist practice with six support staff.\n- Trained three new receptionists on phones, check-in and recall calls.\n"
                           "- Send patient statements and follow up on unpaid insurance claims in Dentrix.\nFront Desk Coordinator, Lakeview Family Clinic (June 2016 - February 2019)\n"
                           "- Checked in about sixty patients a day and answered a six-line phone.\n\nEDUCATION\nAssociate of Applied Science, Office Administration, Richland Community College, 2014\n\n"
                           "SKILLS\nDentrix, QuickBooks, insurance verification, staff scheduling"}


def make_person(name, prof=PROFILE):
    pid = people.add(name)
    people.set_current(pid, process_wide=True)
    p = json.loads(json.dumps(prof))
    p["_hash"] = resume.profile_hash(p)
    p["_approved"] = "2026-01-01T10:00"
    json.dump(p, open(resume.ACTIVE(), "w"))
    return pid


def rating(inf, fit=80):
    r = {"asis": fit - 10, "fit": fit, "label": "tailor", "level": "match", "reason": "stub", "tailor": "", "at": "2026-01-02"}
    ai_score.stamp(r, inf)
    return r


# ------------------------------------------------------------------ 6. editing the profile keeps every rating (as older info)
pid = make_person("Dana")
people.save_settings({"target_text": "an office manager job at a school or hospital", "prep_text": "", "salary_floor": 0}, pid=pid)
JOBS = [{"id": f"J::{i}", "title": "Office Manager" if i % 2 else "Billing Specialist", "company": "C", "locations": ["Springfield, IL"],
         "desc": ("Salesforce administration needed. " if i == 3 else "") + "Run a busy front office.", "req": None, "appeal": 60, "tracks": ["ai"],
         "comp_score": 50, "qol_score": 50, "fit_score": 50} for i in range(40)]
inf0 = ai_score.info()
f0 = ai_score.fingerprints()
key0 = pivot.cache_keys(f0, people.settings_strict(), people.read_saved_strict())[0]
allc = ai_score.load_all()
allc["by_profile"][inf0["phash"]] = {j["id"]: {"haiku": rating(inf0, 60 + i % 30), "opus": rating(inf0, 60 + i % 30)} for i, j in enumerate(JOBS)}
paths.dump_json_atomic(ai_score.CACHE, allc)
paths.dump_json_atomic(pivot.CACHE, {pivot.FORMAT_KEY: 1, key0: {j["id"]: {"now": 60, "later": 70, "label": "after_prep", "gaps": [], "reason": "r", "angle": "a",
                                                                        "fp": f0["pfp"], "fmt": 1} for j in JOBS}})


def shown():
    """(Match ratings on the board, how many of them stale, Target ratings, stale) as a rebuild would apply them."""
    inf = ai_score.info()
    a = ai_score.load_all()
    ai_score.adopt(a["by_profile"], inf["phash"], inf["phash_old"])
    cache = a["by_profile"].get(inf["phash"]) or {}
    js = [dict(j) for j in JOBS]
    ai_score.apply(js, cache, inf)
    pv = [dict(j) for j in JOBS]
    pivot.score_jobs(pv, {"max_new_per_run": 0}, log=lambda m: None)
    return (sum(1 for j in js if j.get("ai_fit") is not None), sum(1 for j in js if j.get("ai_stale")),
            sum(1 for j in pv if j.get("pv_now") is not None), sum(1 for j in pv if j.get("pv_stale")))


check("before any edit: 40 Match and 40 Target ratings, all current", shown() == (40, 0, 40, 0), str(shown()))
for field, value in (("notes", "Also handled payroll for six months."), ("summary", "Office manager, eight years, dental and medical."),
                     ("skills", ["Dentrix", "QuickBooks", "Payroll"]), ("certifications", ["CPR and First Aid (American Red Cross)", "Notary Public"])):
    resume.edit_active({field: value})
    got = shown()
    check(f"editing {field} on My profile: no rating vanishes, all are kept and shown as 'older info'", got == (40, 40, 40, 40), str(got))
check("...the earlier rating keys are remembered on the profile, and fingerprints / cache_keys formulas are untouched",
      inf0["phash"] in resume.load_active()["_hash_aliases"] and ai_score.fingerprints()["phash"] == resume.profile_hash(resume.load_active())
      and ai_score.RATING_FORMAT == 1 and pivot.RATING_FORMAT == 1 and pivot.VERSION == "v2")
draft = dict(resume.load_active(), summary="A brand new resume.", _created="2026-02-01T09:00")
for k in ("_hash", "_hash_aliases", "_approved"):
    draft.pop(k, None)
json.dump(draft, open(resume.DRAFT(), "w"))
resume.approve({})
check("approving a new resume keeps them too (older info)", shown() == (40, 40, 40, 40), str(shown()))
resume.save_manual({"name": "Dana", "current_title": "Office Manager", "skills": ["Dentrix"], "experience": []})
check("...and so does replacing the profile with a hand-filled one", shown()[0] == 40 and shown()[2] == 40, str(shown()))
n_stored = sum(len(v) for v in ai_score.load_all()["by_profile"].values())
check("nothing was dropped from the ratings file", n_stored == 40, str(n_stored))

# ------------------------------------------------------------------ 7. one answer does not make every Target rating stale
pid2 = make_person("Tara")
people.save_settings({"target_text": "customer operations lead", "prep_text": "", "salary_floor": 0}, pid=pid2)
f1 = ai_score.fingerprints()
k1 = pivot.cache_keys(f1, people.settings_strict(), people.read_saved_strict())
old_style = {j["id"]: {"now": 60, "later": 70, "label": "after_prep", "gaps": [], "reason": "r", "angle": "a", "fp": f1["pfp"], "fmt": 1} for j in JOBS}
paths.dump_json_atomic(pivot.CACHE, {**json.load(open(pivot.CACHE)), k1[0]: old_style})


def target_state():
    pv = [dict(j) for j in JOBS]
    pivot.score_jobs(pv, {"max_new_per_run": 0}, log=lambda m: None)
    return {j["id"]: j.get("pv_stale") for j in pv if j.get("pv_now") is not None}


st0 = target_state()
check("Target ratings stored by an earlier version (fingerprint only) are current", len(st0) == 40 and not any(st0.values()))
interview.add_answers([{"requirement": "Salesforce administration", "question": "Used Salesforce?", "level": "yes", "answer": "Admin for two years at the clinic."}], "test")
f2 = ai_score.fingerprints()
st1 = target_state()
check("answering one question changes the Target fingerprint (as before)...", f2["pfp"] != f1["pfp"] and f2["tfp"] == f1["tfp"])
check("...but only the job that mentions the answer's topic becomes stale (1 of 40, not 40)",
      sum(1 for v in st1.values() if v) == 1 and st1["J::3"] is True, str(sum(1 for v in st1.values() if v)))
check("...without touching the cache key (pivot.cache_keys) or any stored fingerprint",
      pivot.cache_keys(f2, people.settings_strict(), people.read_saved_strict())[0] == k1[0]
      and all(r["fp"] == f1["pfp"] for r in json.load(open(pivot.CACHE))[k1[0]].values()))
interview.add_answers([{"requirement": "Zendesk queues", "question": "Zendesk?", "level": "some", "answer": "A little."}], "test")
st2 = target_state()
check("a second answer on a topic no posting mentions adds nothing", sum(1 for v in st2.values() if v) == 1, str(sum(1 for v in st2.values() if v)))
fid = next(f["id"] for f in interview.load_facts() if f["requirement"].startswith("Salesforce"))
interview.delete_fact(fid)
st3 = target_state()
check("deleting the Salesforce answer: that job is current again (it knew nothing of it)", st3["J::3"] is False and not any(st3.values()), str(st3["J::3"]))
people.save_settings({"goals": "I want a short commute."}, pid=pid2)
st4 = target_state()
check("a goals edit still makes every Target rating stale", all(st4.values()))
people.save_settings({"goals": ""}, pid=pid2)
# new-style ratings carry what they knew themselves
fr = pivot.Freshness(ai_score.fingerprints(), JOBS)
newr = {"now": 1, "later": 2, "fp": "someotherfp", "fmt": 1, "tfp": ai_score.fingerprints()["tfp"], "facts": sorted(fr.keys)}
check("a rating that stores its own answers is judged from them (no ledger needed)", fr.ok(newr, JOBS[3]) and fr.ok(newr, JOBS[4])
      and not fr.ok(dict(newr, tfp="x"), JOBS[4]) and not fr.ok(dict(newr, fmt=2), JOBS[4]) and not fr.ok({"now": 1, "fp": "never-seen", "fmt": 1}, JOBS[4]))

# ------------------------------------------------------------------ 9. limits
L = ai_score.RUN_LIMITS
check("per-run limits: 500 quick checks, 100 second looks, 50 careful, 25 saved, 50 Target, 200 automatic", L == {"haiku": 500, "sonnet": 100, "opus": 50, "saved": 25, "target": 50, "quick": 200}, str(L))
people.set_current(pid, process_wide=True)
claude_cli.claude_ready = lambda *a, **k: True
sent = []


def fake_rate(todo, tier, inf, log, on_batch=None):
    sent.append((tier, [j["id"] for j in todo]))
    res = {j["id"]: rating(inf, 70) for j in todo}
    if res and on_batch:
        on_batch(res)
    ai_score.TIMINGS.append({"tier": tier, "jobs": len(todo), "rated": len(res)})
    return res


real_rate, ai_score._rate = ai_score._rate, fake_rate
N = 700
big = [{"id": f"B::{i:04d}", "title": "t", "company": "C", "locations": ["X"], "desc": "d", "req": None, "appeal": 100 - (i % 100), "rel": i % 90} for i in range(N)]
marks = {f"B::{i:04d}": "saved" for i in range(600, 660)}          # 60 saved jobs, in the order they were saved
json.dump(marks, open(people.pdir("marks.json"), "w"))
order = jobfinder.saved_ids()
check("saved jobs come back the most recently saved first", order[:3] == ["B::0659", "B::0658", "B::0657"] and len(order) == 60)
HUGE = {"haiku": 10 ** 9, "sonnet_pct": 100, "sonnet_max": 10 ** 9, "opus_top": 50, "opus_max": 10 ** 9}
ai_score.run_funnel(big, HUGE, saved=order, log=lambda m: None)
by = {t: ids for t, ids in sent}
extra = [i for i in by["opus"] if i in marks]
check("one run: 500 quick checks, 100 second looks, 50 careful + at most 25 saved (75, not 150), the latest saved first",
      len(by["haiku"]) == 500 and len(by["sonnet"]) == 100 and len(by["opus"]) <= 75 and len(extra) <= 25 + 50
      and [i for i in by["opus"] if i in marks and i not in by["opus"][:50]] == [i for i in order if i not in by["opus"][:50]][:25],
      str((len(by["haiku"]), len(by["sonnet"]), len(by["opus"]), len(extra))))
# one budget for a scheduled night: the re-rate after the update only gets what the update left
os.environ["SIFTWELL_NIGHT"] = "20260101T020000"
b0, t0 = jobfinder.night_budgets(pid, {"haiku": 500, "sonnet_pct": 15, "sonnet_max": 100, "opus_top": 50, "opus_max": 50}, 50)
check("night, step 1 (the update): the full run budget", (b0["haiku"], b0["sonnet_max"], b0["opus_max"], t0) == (500, 100, 50, 50))
jobfinder.night_spent(pid, [{"tier": "haiku", "jobs": 420, "rated": 400}, {"tier": "sonnet", "rated": 60}, {"tier": "opus", "rated": 62}, {"tier": "target", "jobs": 30}])
b1, t1 = jobfinder.night_budgets(pid, {"haiku": 500, "sonnet_pct": 15, "sonnet_max": 100, "opus_top": 50, "opus_max": 50}, 50)
check("night, step 2 (the re-rate): only what is left (100 quick checks, 40 second looks, 0 careful, 13 saved, 20 Target), never 500 + 500",
      (b1["haiku"], b1["sonnet_max"], b1["opus_max"], b1["saved_max"], t1) == (100, 40, 0, 13, 20), str((b1, t1)))
os.environ["SIFTWELL_NIGHT"] = "20260102T020000"
b2, _ = jobfinder.night_budgets(pid, {"haiku": 500, "sonnet_max": 100, "opus_max": 50}, 50)
check("the next night starts fresh", b2["haiku"] == 500)
os.environ.pop("SIFTWELL_NIGHT")
b3, t3 = jobfinder.night_budgets(pid, {"haiku": 500}, 50)
check("a run a person starts is never cut by the night's tally", b3 == {"haiku": 500} and t3 == 50)
sent.clear()
os.environ["SIFTWELL_NIGHT"] = "20260103T020000"
jobfinder.use_cfg(jobfinder.person_cfg(pid)[0])
fresh_jobs = [dict(j, id=j["id"].replace("B::", "N::"), tracks=[], workplace="onsite", salary_mid=None, level=None, travel="", clearance="", title="Office Manager") for j in big]
ai_score.TIMINGS.clear()
jobfinder.score_person(fresh_jobs, resume.load_active(), new_claude=True)
first_h = sum(len(ids) for t, ids in sent if t == "haiku")
sent.clear(); ai_score.TIMINGS.clear()
jobfinder.score_person(fresh_jobs, resume.load_active(), new_claude=True, refresh=True)
second_h = sum(len(ids) for t, ids in sent if t == "haiku")
check(f"through the real rating path: update {first_h} + re-rate {second_h} quick checks in one night = at most 500", first_h == 500 and second_h == 0, str((first_h, second_h)))
os.environ.pop("SIFTWELL_NIGHT")
ai_score._rate = real_rate
claude_cli.claude_ready = lambda *a, **k: False

import server
check("the per-card rate button never takes more than a run's own limit (50, was 60)", 'RUN_LIMITS["target" if' in open(server.__file__, encoding="utf-8").read())
check("a quick check of 1,674 new jobs says what it really rates", server.rate_label({"ids": set(range(1674))}) == "Quick check of the 200 most relevant of 1,674 new jobs"
      and server.rate_label({"ids": {1, 2, 3}}) == "Quick check of 3 new jobs", server.rate_label({"ids": set(range(1674))}))

# ------------------------------------------------------------------ 4. boards from an older version are rebuilt at start
pb = people.add("Boarded")
json.dump({"generated": "x", "rate_batch": {}, "jobs": [{"id": "a"}]}, open(people.pdir("jobs.json", pid=pb), "w"))
check("a board without Relevance (written before this version) is seen as old", server._board_has_counts(pb) is False)
json.dump({"generated": "x", "rate_batch": {}, "has_relevance": True, "rel_v": lookfor.BUILD, "jobs": [{"id": "a", "rel": 5}]}, open(people.pdir("jobs.json", pid=pb), "w"))
check("a board with this version's Relevance is left alone", server._board_has_counts(pb) is True)
json.dump({"generated": "x", "rate_batch": {}, "jobs": [{"id": "a"}]}, open(people.pdir("jobs.json", pid=pb), "w"))
asked = []
real_rr, server.request_recompute = server.request_recompute, lambda pids=None, auto_rate=True: asked.append((sorted(pids), auto_rate))
server.recount_old_boards()
server.request_recompute = real_rr
check("at start it is rebuilt, with the automatic quick check off (no Claude)", asked and pb in asked[0][0] and asked[0][1] is False, str(asked))

lookfor.build(pid)
check("a board that is still empty already knows the person has a what-to-look-for sheet (so it opens on 'Most relevant', not 'Most appealing')",
      jobfinder._has_relevance(pid, []) is True and jobfinder._has_relevance(pb, []) is False and jobfinder._has_relevance(pb, [{"rel": 3}]) is True)

# ------------------------------------------------------------------ 5. highlights are read when setup approves the draft
import highlights
calls = []
real_refresh = highlights.refresh


def slow_refresh(p, profile=None, use_claude=True):
    time.sleep(0.6)
    calls.append((p, use_claude))
    return real_refresh(p, profile, use_claude=False)


highlights.refresh = slow_refresh
t0 = time.time()
threading.Thread(target=server.bg_highlights, args=(pid, False), daemon=True).start()
time.sleep(0.1)
server.wait_highlights(10)
waited = time.time() - t0
check("a rating run waits for a highlights read that is under way", waited >= 0.5 and calls == [(pid, False)] and os.path.exists(highlights.path(pid)), str((waited, calls)))
highlights.refresh = real_refresh
src = open(server.__file__, encoding="utf-8").read()
check("the setup step that approves the resume draft starts the highlights read", "had_draft and resume.load_draft() is None" in src and "wait_highlights()" in src)

# ------------------------------------------------------------------ 9/10. the usage log and the lean command line
people.set_current(pid, process_wide=True)
claude_usage.record("Match ratings", "m", {"input_tokens": 10, "output_tokens": 5}, 3)
claude_usage.record("Match ratings", "m", {}, 3, error="timed out")
claude_usage.record("Search", "m", {}, None, stub=True)
s = claude_usage.summary()
check("usage: a call with no answer is listed as failed; test answers are counted apart, not as requests",
      s["today"]["calls"] == 2 and s["today"]["failed"] == 1 and s["today"]["test"] == 1 and [f["feature"] for f in s["today"]["features"]] == ["Match ratings"], str(s["today"]))
runs = []


class FakeRun:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def fake_run(cmd, **kw):
    runs.append((cmd, kw))
    if "--help" in cmd:
        return FakeRun("  --safe-mode   x\n  --disable-slash-commands   x\n  --strict-mcp-config  x\n  --tools <tools...>\n")
    return FakeRun(MODE["out"]) if MODE["out"] != "TIMEOUT" else (_ for _ in ()).throw(__import__("subprocess").TimeoutExpired(cmd, 1))


MODE = {"out": "this is not json"}
real_run, osdeps.run_hidden = osdeps.run_hidden, fake_run
real_path, claude_cli.path = claude_cli.path, lambda: os.path.join(DATA, "fake-claude.exe")
os.environ["CLAUDECODE"] = "1"; os.environ["CLAUDE_CODE_ENTRYPOINT"] = "test"; os.environ["CLAUDE_CODE_USE_BEDROCK"] = "keepme"
os.environ.pop("SIFTWELL_FORBID_CLAUDE")          # (osdeps.run_hidden is the fake above: no process, no Claude, can be reached)
n0 = len(list(claude_usage._lines()))
errs = []
for out in ("this is not json", "TIMEOUT", json.dumps({"is_error": True, "result": "overloaded", "usage": {"input_tokens": 7}})):
    MODE["out"] = out
    try:
        claude_cli.run_json("sys", "prompt", {"type": "object"}, model=claude_cli.HAIKU, feature="Search")
        errs.append(None)
    except Exception as e:
        errs.append(type(e).__name__)
rows = list(claude_usage._lines())[n0:]
check("a timeout, an unreadable answer and an error from Claude each leave a line in the usage log",
      errs == ["CLIError"] * 3 and [r.get("error") for r in rows] == ["no readable answer", "timed out", "Claude reported an error"] and rows[2]["in"] == 7, str((errs, rows)))
MODE["out"] = json.dumps({"structured_output": {"ok": 1}, "usage": {"input_tokens": 3, "output_tokens": 1}})
runs.clear()
got = claude_cli.run_json("sys", "prompt", {"type": "object"}, model=claude_cli.HAIKU, feature="Search")
cmd, kw = runs[-1]
check("every call is lean: no tools, no skills or slash commands, no MCP, no CLAUDE.md (the flags this Claude Code knows)",
      got == {"ok": 1} and all(f in cmd for f in ("--safe-mode", "--disable-slash-commands", "--strict-mcp-config")) and "--no-chrome" not in cmd
      and cmd[cmd.index("--tools") + 1] == "" and "--no-session-persistence" in cmd and "--bare" not in cmd and "--setting-sources" not in cmd, str(cmd))
check("...and does not inherit a surrounding Claude Code session (sign-in and provider settings are kept)",
      "CLAUDECODE" not in kw["env"] and "CLAUDE_CODE_ENTRYPOINT" not in kw["env"] and kw["env"].get("CLAUDE_CODE_USE_BEDROCK") == "keepme")
rc = claude_cli.command("p", "m", "low", "s", {}, read_dir="D:/x")
check("tools only where a feature needs them (a scanned resume: Read in one folder; company facts: web search)",
      rc[rc.index("--tools") + 1] == "Read" and "--add-dir" in rc and claude_cli.command("p", "m", "low", "s", {}, tools=["WebSearch"])[-3:] == ["WebSearch", "--permission-mode", "dontAsk"])
batch = [{"id": "J::1", "title": "t", "company": "c", "locations": ["x"], "desc": "d"}]
MODE["out"] = json.dumps({"structured_output": {"results": [{"id": "J::1", "as_is_fit": 50, "tailored_fit": 60, "label": "stretch", "level": "match", "reason": "r", "tailoring": ""}]},
                          "usage": {"input_tokens": 1}})
runs.clear()
res = ai_score._score_batch_cli(claude_cli.path(), {"model": "claude-haiku-5-5", "effort": "low"}, "PROFILE", batch)
check("Match ratings use the same lean command line", res["J::1"]["fit"] == 60 and "--safe-mode" in runs[-1][0] and "CLAUDECODE" not in runs[-1][1]["env"])
MODE["out"] = "error: unknown option '--safe-mode'"
runs.clear()
try:
    claude_cli.run_json("sys", "prompt", {"type": "object"})
except Exception:
    pass
second = [c for c, _ in runs if "-p" in c]
check("a Claude Code that refuses a lean flag is asked again without it (once), not left broken", len(second) == 2 and "--safe-mode" in second[0] and "--safe-mode" not in second[1], str(len(second)))
claude_cli._LEAN.clear()
osdeps.run_hidden, claude_cli.path = real_run, real_path
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_USE_BEDROCK"):
    os.environ.pop(k, None)

# which model does the small jobs, and nothing is sent twice
asked = []
real_rj = claude_cli.run_json


def spy(system, prompt, schema, model=claude_cli.OPUS, **kw):
    asked.append({"system": system, "prompt": prompt, "model": model, **kw})
    if "items" in schema.get("properties", {}):
        return {"items": []}
    if "questions" in schema.get("properties", {}):
        return {"questions": []}
    if "tab_name" in schema.get("properties", {}):
        return {"tab_name": "Office", "any_title": False, "title_keywords": ["office manag"], "summary": "s"}
    return {}


claude_cli.run_json = spy
people.set_current(pid2, process_wide=True)
interview._save([{"id": "f1", "date": "2026-01-01", "context": "", "polished": "Administered Salesforce for two years.", "requirement": "Salesforce administration",
                  "question": "q", "level": "yes", "answer": "ya did salesforce admin 2 yrs"},
                 {"id": "f2", "date": "2026-01-01", "context": "", "polished": "", "requirement": "Zendesk", "question": "q", "level": "some", "answer": "a bit of zendesk"}])
interview.polish(interview.load_facts())
interview.generate()
target.interpret("office manager at a school", "all")
m = {("polish" if "polished" in a["system"] else "questions" if "find true experience" in a["system"] else "target"): a for a in asked}
check("answer polish and interview questions run on Sonnet, the target's name and title words on Haiku (not Opus)",
      m["polish"]["model"] == claude_cli.SONNET and m["questions"]["model"] == claude_cli.SONNET and m["target"]["model"] == claude_cli.HAIKU
      and m["target"].get("feature") == "Target setup", str({k: v["model"] for k, v in m.items()}))
qp = m["questions"]["prompt"]
check("interview questions: each answer is sent once (it used to go twice)", qp.count("Administered Salesforce for two years.") == 1 and qp.count("a bit of zendesk") == 1, str((qp.count("Administered Salesforce"), qp.count("a bit of zendesk"))))
pt_ = resume.profile_text(resume.load_active())
check("the profile text gives each answer once: the polished statement, not polished + raw note",
      pt_.count("Administered Salesforce for two years.") == 1 and "ya did salesforce" not in pt_ and "a bit of zendesk" in pt_)
check("...and the rating fingerprints still use their own frozen text (unchanged by this)", "raw note: ya did salesforce" in ai_score._fp_facts_text(interview.load_facts()))
claude_cli.run_json = real_rj

# a PDF with real text is read on this computer; only a scan goes to Claude
if tailor.CHROME and os.path.exists(tailor.CHROME):
    body = "".join(f"<p>{l}</p>" for l in PROFILE["_resume_text"].split("\n") if l.strip()) * 2
    pdf = os.path.join(DATA, "resume-text.pdf")
    tailor._chrome_pdf(f"<html><body>{body}</body></html>", pdf)
    scan = os.path.join(DATA, "resume-scan.pdf")
    tailor._chrome_pdf("<html><body><svg width='300' height='300'><rect width='300' height='300' fill='#888'/></svg></body></html>", scan)
    text = resume.extract_text(pdf)
    check("an ordinary PDF resume: its text is read locally (pypdf), no Claude call", "Maple Street Dental" in text and len(text) > 300 and not os.path.exists(FORBID_LOG))
    try:
        resume.extract_text(scan)
        went = False
    except claude_cli.ClaudeForbidden:
        went = True
    except Exception as e:
        went = "blocked" in str(e).lower()
    check("a scan with no text in it still goes to Claude (blocked here, and counted)", went and os.path.exists(FORBID_LOG))
    os.remove(FORBID_LOG)
else:
    print("skip the PDF checks (no Chrome or Edge on this computer to make a test PDF)")

# ------------------------------------------------------------------ 12/13. tailored resumes: fact check and the Word file
people.set_current(pid, process_wide=True)
json.dump(dict(PROFILE, _hash=resume.profile_hash(PROFILE), _approved="2026-03-01T10:00"), open(resume.ACTIVE(), "w"))
interview._save([{"id": "a1", "date": "2026-01-01", "context": "", "polished": "Prepared the monthly payroll for 14 staff in QuickBooks.", "requirement": "Payroll",
                  "question": "q", "level": "yes", "answer": "did payroll monthly for 14 people in quickbooks"}])
T = {"headline": "Office Manager · Dental practice operations", "headline_short": "Office Manager", "skill_groups": [], "layout": {k: "default" for k in tailor.LAYOUT_ENUMS},
     "summary": "Office manager with eight years of experience running busy practices.", "summary_sources": [],
     "experience": [{"employer": "Maple Street Dental", "location": "Springfield, IL", "title": "Office Manager", "functional_title": "Practice Administrator", "dates": "2019 - Present",
                     "bullets": [{"text": "Run the front office for a four-dentist practice with six support staff.", "source": "Run the front office for a four-dentist practice with six support staff.", "change": "kept"},
                                 {"text": "Prepared monthly payroll for 14 staff in QuickBooks.", "source": "did payroll monthly for 14 people in quickbooks", "change": "reworded"},
                                 {"text": "Trained three new receptionists on phones and check-in.", "source": "Your answer: Trained three new receptionists on phones, check-in and recall calls.", "change": "added_from_notes"},
                                 {"text": "Cut claim denials by 40% through weekly audits.", "source": "Reduced denials through audits", "change": "surfaced"}]},
                    {"employer": "Lakeview Family Clinic", "location": "", "title": "Front Desk Coordinator", "functional_title": "", "dates": "Jun 2016 - Feb 2019",
                     "bullets": [{"text": "Checked in about 60 patients a day.", "source": "Checked in about sixty patients a day and answered a six-line phone.", "change": "reworded"}]},
                    {"employer": "Sunrise Consulting Group", "location": "", "title": "Operations Lead", "functional_title": "", "dates": "2012 - 2014", "bullets": []}],
     "skills": ["Dentrix", "QuickBooks", "Staff scheduling", "Kubernetes"], "education": ["A.A.S. Office Administration, Richland Community College", "MBA, Stanford University"],
     "clearance": ["Secret (previously held)"], "additional": ["CPR and First Aid (American Red Cross)", "Volunteer coordinator"], "dropped": [], "gaps": ["Eaglesoft experience"],
     "unsupported_requests": ["Bilingual Spanish"], "job": {"id": "J::1", "title": "Office Manager", "company": "Bright Smiles", "url": "", "locations": []},
     "contact": tailor.contact_header(PROFILE["_resume_text"]), "created": "2026-03-02T10:00"}
t1 = json.loads(json.dumps(T))
ck = tailor.fact_check(t1)
W = " | ".join(w["text"] for w in ck["warnings"])
F = " | ".join(ck["fixed"])
e0, e1 = t1["experience"][0], t1["experience"][1]
check("employer, title and dates are copied from the profile, not trusted to the model (a shortened employer name is put back)",
      e0["employer"] == "Maple Street Dental Associates" and e0["dates"] == "March 2019 - Present" and e1["dates"] == "June 2016 - February 2019" and "Maple Street Dental Associates" in F, F)
check("the plain-English title and the bullets are left as written", e0["functional_title"] == "Practice Administrator" and len(e0["bullets"]) == 4)
check("a job that is not on the profile is flagged", "Sunrise Consulting Group" in W, W)
check("education comes from the profile; a degree that is nowhere is flagged", t1["education"][0] == PROFILE["education"][0] and "Stanford" in W, str(t1["education"]))
check("certifications get their own section from the profile, and are not repeated under Additional",
      t1["certifications"] == PROFILE["certifications"] and t1["additional"] == ["Volunteer coordinator"], str((t1["certifications"], t1["additional"])))
ch = [b["change"] for b in e0["bullets"]]
check("'From your answers' is put on the bullet that really comes from an answer, and taken off the one that comes from the resume",
      ch[0] == "kept" and ch[1] == "added_from_notes" and ch[2] == "surfaced" and "label corrected" in F, str(ch))
check("a bullet whose source is nowhere is flagged, and marked on the review page", e0["bullets"][3].get("unverified") and "Cut claim denials" in W and not e0["bullets"][0].get("unverified"))
check("a number in no source is flagged (40%); numbers that are in a source are not (14 staff, six -> 60 is flagged as changed)",
      "“40”" in W and "“14”" not in W, W)
check("a skill in no source is flagged (Kubernetes); real ones are not", "Kubernetes" in W and "Dentrix" not in W and "Staff scheduling" not in W, W)
json.dump(t1, open(os.path.join(people.pdir("tailored"), "x.json"), "w")) if os.makedirs(people.pdir("tailored"), exist_ok=True) is None else None
page = tailor.render_html("x")
check("the review page shows 'Check before you send' and what was corrected", "Check before you send" in page and "Corrected automatically" in page and "source not found" in page)
prompts = []
claude_cli.run_json = lambda system, prompt, schema, **kw: (prompts.append(prompt), json.loads(json.dumps({k: T[k] for k in tailor.SCHEMA["properties"]})))[1]
rev = tailor.revise(T["job"], "posting text", t1, {"score": 70, "summary": "ok", "issues": [], "missing_keywords": []})
claude_cli.run_json = real_rj
check("the rework step is told every finding as something it must fix, and its answer is checked again",
      "FACT CHECK BY THE TOOL" in prompts[0] and "Kubernetes" in prompts[0] and rev["experience"][0]["employer"] == "Maple Street Dental Associates" and rev["checks"]["warnings"])

# the Word file: same sections and settings as the PDF
import docx as _docx
import re as _re


def word_text(path):
    d = _docx.Document(path)
    return [p.text for p in d.paragraphs if p.text.strip()]


def pdf_heads(t, pr):
    return _re.findall(r"<h2>([^<]+)</h2>", tailor.render_print(t, pr))


pr_all = people.prefs()
out = os.path.join(DATA, "all.docx")
tailor.write_docx(t1, out, pr_all)
wt = word_text(out)
heads_w = [x.title() for x in wt if x.isupper() and len(x) < 40]
check("Word, default settings: the same sections in the same order as the PDF, Certifications included",
      heads_w == pdf_heads(t1, pr_all) and "Certifications" in heads_w and any("CPR and First Aid" in x for x in wt), str((heads_w, pdf_heads(t1, pr_all))))
check("...with the contact line, headline, employer (as on the profile), plain-English title and dates",
      wt[0] == "Dana Whitfield" and "dana@example.com" in wt[1] and PHONE in wt[1] and any("Maple Street Dental Associates" in x and "Springfield, IL" in x for x in wt)
      and any("Office Manager (Practice Administrator)" in x and "March 2019 - Present" in x for x in wt), str(wt[:8]))
off = {**pr_all, "resume.contact_phone": False, "resume.contact_email": False, "resume.contact_linkedin": False, "resume.summary": False,
       "resume.skills": False, "resume.additional": False, "resume.clearance": "hide", "resume.functional_titles": "hide", "resume.education_first": True, "resume.paper": "a4"}
tailor.write_docx(t1, out, off)
wo = word_text(out)
blob = "\n".join(wo)
heads_o = [x.title() for x in wo if x.isupper() and len(x) < 40]
check("Word follows every Resume setting: phone, email, LinkedIn, summary, skills, additional and clearance are gone when switched off",
      not any(x in blob for x in (PHONE, "dana@example.com", "linkedin", "eight years of experience running", "Kubernetes", "Volunteer coordinator", "Secret (previously", "Practice Administrator"))
      and "Springfield, IL" in wo[1], blob[:300])
check("...and the section order (education first), still matching the PDF exactly", heads_o == pdf_heads(t1, off) == ["Education", "Certifications", "Professional Experience"], str((heads_o, pdf_heads(t1, off))))
d = _docx.Document(out)
check("...and the paper size (A4)", abs(d.sections[0].page_width.inches - 8.27) < 0.01)
people.save_prefs({"resume.skills": True, "resume.summary": True}, pid=pid)
p1 = tailor.make_docx("x")
had_skills = "Dentrix" in "\n".join(word_text(p1))
people.save_prefs({"resume.skills": False}, pid=pid)
p2 = tailor.make_docx("x")
check("the Word download is rebuilt when a Resume setting changes (Skills on, then off)", had_skills and "Dentrix" not in "\n".join(word_text(p2)))
people.save_prefs({"resume.skills": True}, pid=pid)
old = json.loads(json.dumps(T)); old.pop("contact"); old["contact"] = T["contact"]
check("a resume tailored before this version (no Certifications, no checks) still renders, PDF and Word alike",
      "Certifications" not in pdf_heads(old, pr_all) and tailor.write_docx(old, out, pr_all) is None and "Check before you send" not in tailor.checks_html(old.get("checks")))

# keyword coverage and when to stop reworking
POST = ("About Bright Smiles\nWe are a family dental group with amazing culture and amazing benefits. Amazing culture matters.\n\n"
        "Requirements\n- Dental office management experience with Dentrix or Eaglesoft\n- Insurance verification and insurance claims follow-up\n"
        "- Staff scheduling and payroll in QuickBooks\n- Eaglesoft reporting is a plus\n- Insurance verification daily\n\nBenefits\n401k match, dental coverage, amazing culture, paid time off, 401k match.\n")
req = review.requirements_part(POST)
check("keyword coverage looks at the posting's requirements only (not the company story or benefits)",
      "Insurance verification" in req and "amazing culture" not in req and "401k" not in req, req[:120])
mech = review.mechanical(t1, 1, 2, POST)
check("...and leaves out what is already listed as a gap (Eaglesoft)", mech["keyword_coverage"] is not None
      and not any("eaglesoft" in k for k in mech["keywords_missing"]) and not any("amazing" in k or "401k" in k for k in mech["keywords_missing"]), str(mech))
iss = lambda area, problem, fix, sev="medium": {"area": area, "severity": sev, "where": "x", "problem": problem, "fix": fix}
check("an issue that needs a fact the person doesn't have can't be fixed honestly; wording and layout issues can",
      review.unfixable(iss("claims", "No metrics on claim follow-up.", "Add a number: how many claims per week."), t1)
      and review.unfixable(iss("ats", "The posting asks for Eaglesoft experience.", "Mention Eaglesoft."), t1)
      and not review.unfixable(iss("grammar", "Mixed tenses.", "Use past tense."), t1) and not review.unfixable(iss("ats", "Uses 'front desk' where the posting says 'reception'.", "Reword to reception."), t1))
check("...and a round whose remaining issues are all of that kind is the last one",
      review.only_unfixable_left({"issues": [iss("claims", "No metrics.", "Quantify: add numbers.", "high"), iss("grammar", "x", "y", "low")]}, t1)
      and not review.only_unfixable_left({"issues": [iss("grammar", "Mixed tenses.", "Fix.", "high")]}, t1))
# the loop itself, with a stand-in reviewer
scores = iter([70, 71, 90])
grades = []
real = (review.codex_path, review.codex_ready, review.grade, tailor.revise, tailor.make_pdf)
review.codex_path = lambda: "codex"
review.codex_ready = lambda: (True, "")
review.grade = lambda t, pdf, desc, facts, target: (grades.append(1), {"score": next(scores), "issues": [iss("grammar", "Mixed tenses.", "Fix.", "high")], "fact_requests": [], "missing_keywords": [], "areas": {}})[1]
tailor.revise = lambda job, desc, cur, g: json.loads(json.dumps({k: v for k, v in cur.items() if k != "review"}))
tailor.make_pdf = lambda s: os.path.join(DATA, "none.pdf")
people.save_prefs({"review.threshold": 85, "review.max_rounds": 4, "review.ask_facts": False}, pid=pid)
clean = json.loads(json.dumps(t1)); clean.pop("review", None); clean["checks"] = {"warnings": [], "fixed": []}
json.dump(clean, open(os.path.join(people.pdir("tailored"), "loop.json"), "w"))
server.ps()["tailor"]["loop"] = {"running": True}
server.review_loop("loop", T["job"], POST)
rv = json.load(open(os.path.join(people.pdir("tailored"), "loop.json")))["review"]
check("the review loop stops after a rework that moved the grade by less than 3 (70 -> 71): 2 rounds, not 5",
      len(grades) == 2 and rv["status"] == "below" and "less" not in rv.get("stopped", "less") and rv["final"] == 71, str((len(grades), rv.get("stopped"))))
review.codex_path, review.codex_ready, review.grade, tailor.revise, tailor.make_pdf = real

newp = people.add("Newcomer")
legacy = people.add("Legacy")
json.dump({"salary_floor": 0, "prefs": {"resume.length": "1"}}, open(people.pdir("settings.json", pid=legacy), "w"))
check("a new profile is asked questions before tailoring only when the posting has gaps; an existing profile keeps 'always'",
      people.prefs(newp)["tailor.questions"] == "gaps" and people.prefs(legacy)["tailor.questions"] == "always" and people.prefs(pid)["tailor.questions"] == "gaps")

check("no real Claude call was attempted anywhere in this test", not os.path.exists(FORBID_LOG), open(FORBID_LOG).read() if os.path.exists(FORBID_LOG) else "")
print("\n" + ("ALL OK" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
