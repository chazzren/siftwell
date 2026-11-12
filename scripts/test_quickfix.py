"""Offline checks for: US places kept / foreign places dropped, whole-word title excludes, the "only your own job
titles" rule, defaults for new vs. existing profiles, the per-run rating limits (with stubbed raters) and the Claude
usage log. No network, no Claude. Uses its own scratch data folder (never a real one).

    python -X utf8 scripts/test_quickfix.py <scratch dir>
"""
import json, os, shutil, sys

if len(sys.argv) < 2:
    sys.exit("usage: python -X utf8 scripts/test_quickfix.py <scratch dir>")
SCRATCH = os.path.abspath(sys.argv[1])
DATA = os.path.join(SCRATCH, "quickfix_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"       # anything that slips past the stubs is blocked and counted
os.environ.pop("SIFTWELL_CLAUDE_STUB", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import people, paths, geo, jobfinder, ai_score, pivot, claude_cli, claude_usage, resume

fails = 0


def check(label, ok, detail=""):
    global fails
    print(("ok   " if ok else "FAIL ") + label + (f"   [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


# ------------------------------------------------------------------ 2. US places are not "foreign"
US = ["Indianapolis, IN", "Indianapolis, Indiana", "Indiana", "Fort Wayne, IN, US", "Indianapolis IN 46204", "Brazil, IN",
      "Dublin, OH", "Dublin, Ohio", "Dublin, CA", "Remote (Dublin, OH)", "Dublin, OH, United States",
      "Santa Fe, New Mexico", "New Mexico", "Albuquerque, NM", "Paris, TX", "Hybrid - Paris, Texas", "London, KY",
      "Berlin, MD", "Sydney, OH", "Poland, OH", "Amsterdam, NY", "Milwaukee, WI", "Ukiah, CA", "Mexico, MO", "Peru, IL",
      "Lebanon, PA", "Athens, GA", "Rome, GA", "Atlanta, Georgia", "Naples, FL", "Cuba, MO", "Jamaica, NY", "Lima, OH",
      "Cairo, IL", "Vancouver, WA", "Melbourne, FL", "Manchester, NH", "Moscow, ID", "Geneva, IL", "Delhi, NY",
      "Remote", "Remote - United States", "US-Remote", "Remote, USA", "Main Campus", "Washington, DC", "New England"]
FOREIGN = ["Dublin, Ireland", "Bangalore, India", "London, UK", "Mexico City, Mexico", "London", "Toronto, ON",
           "Toronto, ON, CA", "Hyderabad, TG, IN", "Bengaluru, KA, IN", "Remote - UK", "Remote, Canada", "EMEA",
           "Paris, France", "Sydney, Australia", "Tokyo", "Munich, Germany", "Tbilisi, Georgia", "Remote - India",
           "Berlin", "Vancouver, BC", "Singapore", "Mexico", "India", "United Kingdom", "Warsaw, Poland",
           "Sao Paulo, Brazil", "Amsterdam, NL", "Cambridge, UK", "Pune (India) europe"]
bad = [x for x in US if jobfinder.is_foreign(x)]
check(f"{len(US)} US labels are never called foreign", not bad, ", ".join(bad))
bad = [x for x in FOREIGN if not jobfinder.is_foreign(x)]
check(f"{len(FOREIGN)} foreign labels are still caught", not bad, ", ".join(bad))
check("remote + a US town with a foreign namesake counts as remote-US", jobfinder.is_remote_us("Remote - Dublin, OH")
      and jobfinder.is_remote_us("Remote (Indianapolis, IN)") and not jobfinder.is_remote_us("Remote - Dublin, Ireland"))
check("old substring list really had the bug (the test examples are meaningful)",
      any(c in " indianapolis, in " for c in jobfinder.NON_US) and any(c in " dublin, oh " for c in jobfinder.NON_US))


def listing(loc, wp=""):
    return {"company": "X", "sector": "", "tier": "", "title": "Office Manager", "url": "u", "locations": [loc],
            "workplace": wp, "salary": None, "desc": "", "posted": "", "dept": "", "id": "X::" + loc}


kept = [l for l in ("Indianapolis, IN", "Dublin, OH", "Santa Fe, New Mexico", "Paris, TX", "London, KY")
        if jobfinder.prepare_listing(listing(l), {"name": "X"}) is not None]
check("prepare_listing keeps postings in US towns named like foreign places", len(kept) == 5, str(kept))
gone = [l for l in ("Dublin, Ireland", "Bangalore, India", "London, UK", "Mexico City, Mexico")
        if jobfinder.prepare_listing(listing(l), {"name": "X"}) is None]
check("prepare_listing still drops postings abroad", len(gone) == 4, str(gone))
from scripts.index_build import readers
check("directory builder (readers._nonus) uses the same rule",
      not readers._nonus("Indianapolis, IN") and not readers._nonus("Dublin, OH") and readers._nonus("Dublin, Ireland")
      and readers._nonus("Bangalore, India"))

# ------------------------------------------------------------------ 3. title excludes are whole words
DEF = json.load(open(paths.CONFIG_DEFAULT, encoding="utf-8"))
ex = DEF["title_exclude"]
check("shipped excludes are short and generic", set(ex) <= {"intern", "interns", "internship", "internships", "co-op"}, str(ex))
keep = ["Internal Medicine Physician", "Internal Auditor", "International Sales Manager", "Internist", "Director of Internal Communications",
        "Co-operative Bank Teller", "Internationalization Engineer"]
drop = ["Marketing Intern", "Summer Interns 2027", "Software Engineering Internship", "Internships - Finance", "Intern, Accounting",
        "INTERN - HR", "Engineering Co-op", "Co-Op Student (Fall)"]
bad = [t for t in keep if jobfinder.excluded_words(t, ex)]
check("'intern' / 'co-op' no longer drop Internal, International, Co-operative ...", not bad, str(bad))
bad = [t for t in drop if not jobfinder.excluded_words(t, ex)]
check("intern, interns, internship(s) and co-op titles are still dropped", not bad, str(bad))
check("an entry ending in * is a word beginning", jobfinder.excluded_words("Senior Recruiter", ["recruit*"]) == ["recruit*"]
      and not jobfinder.excluded_words("Senior Recruiter", ["recruit"]) and not jobfinder.excluded_words("Precruitment", ["recruit*"]))
check("'new grad' covers New Grad / New Grads / New Graduate", all(jobfinder.excluded_words(t, ["new grad"]) for t in
      ("New Grad Nurse", "New Grads 2027", "New Graduate RN")) and not jobfinder.excluded_words("Renew Gradually", ["new grad"]))
# a household config.json written before this rule: its own entries keep matching anywhere in the title
old_mode = jobfinder.OLD_EXCLUDE_MATCH
jobfinder.OLD_EXCLUDE_MATCH = True
house = ["intern", "recruit", "tax ", "hr "]
check("older household lists: their own stems still work, 'intern' is whole-word",
      jobfinder.excluded_words("Senior Recruiter", house) == ["recruit"] and jobfinder.excluded_words("Tax Manager", house) == ["tax "]
      and not jobfinder.excluded_words("Internal Auditor", house) and jobfinder.excluded_words("Audit Intern", house) == ["intern"])
jobfinder.OLD_EXCLUDE_MATCH = old_mode

# ------------------------------------------------------------------ 4. defaults: new profiles vs. profiles from before
new = people.add("New Person")
s = people.settings(new)
check("new profile: no pay floor, no level, no shared lists, own-titles rule",
      s["salary_floor"] == 0 and s["seniority_mine"] is None and s["seniority_band"] == [1, 7] and s["company_sets"] == []
      and s["title_rule"] == "own", str({k: s[k] for k in ("salary_floor", "seniority_mine", "seniority_band", "company_sets", "title_rule")}))
check("new profile watches only its own lists", people.company_sets(new) == {f"own-{new}", f"near-{new}", "all"})

# a profile as an earlier version left it: a settings file that never heard of the new keys / an old explicit file
old = "old-person"
people.save_index(people.load_index() + [{"id": old, "name": "Old Person"}])
json.dump({"home_zip": "20001", "radius_miles": 35, "salary_floor": 150000, "seniority_mine": 4, "seniority_band": [3, 5],
           "company_sets": ["tech"], "target_text": "", "prep_text": "", "target_scope": "all",
           "prefs": {"claude.per_update": 300, "claude.opus_top": 300, "claude.sonnet_pct": 15, "claude.haiku_per_night": 4000,
                     "claude.auto_rate": True}}, open(people.pdir("settings.json", pid=old), "w"))
bare = "bare-person"
people.save_index(people.load_index() + [{"id": bare, "name": "Bare Person"}])
people.pdir(pid=bare)   # no settings.json at all
for pid in (old, bare):
    s = people.settings(pid)
    check(f"{pid}: keeps the old floor, level, list and built-in title words",
          s["salary_floor"] == 150000 and s["seniority_mine"] == 4 and s["seniority_band"] == [3, 5] and s["company_sets"] == ["tech"]
          and s["title_rule"] == "builtin" and "tech" in people.company_sets(pid))
pr = people.prefs(old)
check("older saved rating numbers now mean 'as many as allowed'", pr["claude.haiku_per_night"] == 500 and pr["claude.per_update"] == 50
      and pr["claude.opus_top"] == 300 and pr["claude.sonnet_pct"] == 15, str({k: v for k, v in pr.items() if k.startswith("claude.")}))

# the Target cache key for an existing profile is what the old formula gives (frozen copy of that formula)
import hashlib
def old_target_key(st):
    w = lambda v: " ".join(v.split()) if isinstance(v, str) else v
    return hashlib.sha256(json.dumps([w(st.get("target_text")), w(st.get("prep_text")), st.get("target_scope"), st.get("salary_floor")]).encode()).hexdigest()[:10]
OLD_DEFAULTS = {"target_text": "", "prep_text": "", "target_scope": "all", "salary_floor": 150000}
fake_f = {"phash": "abc", "phash_old": []}
for pid in (old, bare):
    people.set_current(pid)
    key, olds = pivot.cache_keys(fake_f, people.settings_strict(pid, missing_ok=True), people.read_saved_strict(pid))
    check(f"{pid}: Target cache key unchanged", key == f"{pivot.VERSION}:abc:{old_target_key(OLD_DEFAULTS)}", key)
    check(f"{pid}: the all-defaults key older versions stored is still adopted",
          f"{pivot.VERSION}:abc:{old_target_key(OLD_DEFAULTS)}" in [key] + olds)

# title rule: only the person's own job titles; none given -> every title passes; old profiles keep the old vocabulary
def titles_pass(pid, titles):
    pc, _, _ = jobfinder.person_cfg(pid)
    jobfinder.use_cfg(pc)
    return [t for t in titles if jobfinder.title_ok(t)]
T = ["Registered Nurse", "Forklift Operator", "Software Engineer", "Line Cook", "Dental Hygienist", "Marketing Intern"]
check("no job titles on the profile: every title passes (except the excludes)", titles_pass(new, T) == T[:5], str(titles_pass(new, T)))
people.set_current(new)
resume.save_manual({"name": "New Person", "current_title": "Line Cook", "skills": ["grill", "prep"], "experience": []})
check("with own job titles: only those pass", titles_pass(new, T) == ["Line Cook"], str(titles_pass(new, T)))
pc_new = jobfinder.person_cfg(new)[0]
check("no built-in vocabulary for new profiles", pc_new["title_include"] == ["line cook"] and pc_new["senior_title_words"] == [], str(pc_new["title_include"]))
check("old profile keeps the old built-in words", titles_pass(old, T) == ["Registered Nurse", "Software Engineer"], str(titles_pass(old, T)))
check("old profile keeps the old seniority bonus words", jobfinder.person_cfg(old)[0]["senior_title_words"] == jobfinder.LEGACY_SENIOR_WORDS)
both = jobfinder.fetch_cfg([jobfinder.person_cfg(p)[0] for p in (new, old)])
people.set_current(bare)
check("shared fetch: one person with titles + one with the old list = union", "line cook" in both["title_include"] and "engineer" in both["title_include"])
os.remove(people.pdir("profile.json", pid=new))
both = jobfinder.fetch_cfg([jobfinder.person_cfg(p)[0] for p in (new, old)])
check("shared fetch: someone with no titles means every title is fetched", both["title_include"] == [])

# Appeal with no floor / no level and no keywords still gives sensible, different numbers
jobfinder.use_cfg(jobfinder.person_cfg(new)[0])
def scored(**kw):
    j = {"id": "a", "title": "Line Cook", "company": "C", "desc": "", "clearance": "", "workplace": "onsite", "salary_mid": None,
         "level": None, "travel": "", **kw}
    jobfinder.score(j)
    return j
a, b, c = scored(), scored(salary_mid=40000), scored(workplace="remote", travel="heavy")
check("Appeal works with no floor, level or keywords", 0 < a["appeal"] <= 100 and b["appeal"] > a["appeal"] and a["fit_score"] == 0
      and c["appeal_parts"]["place"] > a["appeal_parts"]["place"], str((a["appeal"], b["appeal"], c["appeal"])))
check("level: no level chosen treats every level alike; entry level (1) is a valid choice",
      scored(level=2)["appeal_parts"]["level"] == scored(level=6)["appeal_parts"]["level"] and jobfinder.LEVEL_NAMES[1] == "Entry level")

# ------------------------------------------------------------------ 5. per-run rating limits (stubbed raters)
people.set_current(new)
resume.save_manual({"name": "New Person", "current_title": "Line Cook", "skills": ["grill"], "experience": []})
claude_cli.claude_ready = lambda *a, **k: True
sent = []   # (tier, [ids])


def fake_rate(todo, tier, inf, log, on_batch=None):
    sent.append((tier, [j["id"] for j in todo]))
    res = {}
    for j in todo:
        r = {"asis": 60, "fit": 40 + (int(j["id"][1:]) % 50), "label": "tailor", "level": "match", "reason": "stub", "tailor": ""}
        ai_score.stamp(r, inf); r["at"] = "2026-01-01"
        res[j["id"]] = r
    if res and on_batch:
        on_batch(res)
    return res


real_rate, ai_score._rate = ai_score._rate, fake_rate
N = 1800
def pool():
    return [{"id": f"j{i:05d}", "title": "Line Cook", "company": "C", "locations": ["Springfield, IL"], "desc": f"cook {i}",
             "appeal": 100 - (i % 100), "req": None} for i in range(N)]
HUGE = {"haiku": 10 ** 9, "sonnet_pct": 100, "sonnet_max": 10 ** 9, "opus_top": 10 ** 9, "opus_max": 10 ** 9}
L = ai_score.RUN_LIMITS
check("the limits are the agreed numbers", (L["haiku"], L["sonnet"], L["opus"], L["target"], L["quick"]) == (500, 100, 50, 50, 200), str(L))

jobs = pool()
saved = {"j01700", "j01701", "j01702"}   # low Appeal, saved by the person
ai_score.run_funnel(jobs, HUGE, saved=saved, log=lambda m: None)
by = {t: ids for t, ids in sent}
check("run 1: Haiku rates at most 500, the most appealing first", len(by["haiku"]) == 500 and all(int(i[1:]) % 100 < 28 for i in by["haiku"]),
      str(len(by.get("haiku", []))))
check("run 1: Sonnet rates at most 100, only jobs Haiku has rated", len(by["sonnet"]) == 100 and set(by["sonnet"]) <= set(by["haiku"]),
      str(len(by.get("sonnet", []))))
new_opus = [i for i in by["opus"] if i not in saved]
check("run 1: Opus rates at most 50 new jobs (all already rated) plus the saved ones",
      len(new_opus) == 50 and set(new_opus) <= set(by["haiku"]) and saved <= set(by["opus"]), f"{len(new_opus)} new, {len(by['opus'])} total")
unr = [j for j in jobs if j.get("ai_fit") is None]
check("jobs over the limit stay unrated (no Match, shown as a dash)", len(unr) == N - 500 - len(saved - set(by["haiku"])), str(len(unr)))
check("an unrated job never gets a guessed Match", all("ai_fit" not in j for j in unr))

sent.clear()
jobs = pool()
ai_score.run_funnel(jobs, HUGE, saved=saved, log=lambda m: None)
by2 = {t: ids for t, ids in sent}
check("run 2 ('Rate more'): the next 500, none repeated", len(by2["haiku"]) == 500 and not set(by2["haiku"]) & set(by["haiku"]))
check("run 2: Sonnet and Opus stay within their limits", len(by2.get("sonnet", [])) <= 100 and len(by2.get("opus", [])) <= 50)

sent.clear()
jobs = pool()
ai_score.run_funnel(jobs, HUGE, log=lambda m: None, tiers=["haiku"], only_ids={j["id"] for j in jobs})
check("automatic quick check: at most 200", len(sent[0][1]) == 200, str(len(sent[0][1])))

sent.clear()
jobs = pool()
ai_score.run_funnel(jobs, HUGE, log=lambda m: None, tiers=["sonnet"], pick="best", force=True)
check("Re-rate panel, Sonnet only, 'fresh look at all': still at most 100", len(sent[0][1]) == 100, str(len(sent[0][1])))
rated_ids = {j["id"] for j in jobs if j.get("ai_fit") is not None}
check("... and none of them was unrated", set(sent[0][1]) <= rated_ids)
sent.clear()
jobs = pool()
ai_score.run_funnel(jobs, HUGE, log=lambda m: None, tiers=["opus"], pick="best", force=True)
check("Re-rate panel, Opus only, forced: at most 50", len(sent[0][1]) == 50, str(len(sent[0][1])))
sent.clear()
jobs = pool()
ai_score.run_funnel(jobs, {"haiku": 40, "sonnet_pct": 10, "sonnet_max": 100, "opus_top": 5, "opus_max": 50}, log=lambda m: None)
by3 = {t: ids for t, ids in sent}
check("a person's lower Settings numbers are honoured", len(by3["haiku"]) == 40 and len(by3.get("opus", [])) <= 5, str({k: len(v) for k, v in by3.items()}))
ai_score._rate = real_rate

# what the settings turn into for a run
lim_old, lim_new = jobfinder.rate_limits(people.prefs(old)), jobfinder.rate_limits(people.prefs(new))
check("an old profile's saved 4000 / 300 / 300 become 500 quick checks, 50 Target ratings, window 300",
      lim_old == {"haiku": 500, "sonnet_pct": 15, "sonnet_max": 100, "opus_top": 300, "opus_max": 50, "target": 50}, str(lim_old))
check("a new profile's defaults sit inside the limits",
      lim_new == {"haiku": 500, "sonnet_pct": 15, "sonnet_max": 100, "opus_top": 50, "opus_max": 50, "target": 50}, str(lim_new))
people.save_prefs({"claude.auto_rate": False}, pid=new)
check("automatic rating off: automatic runs rate nothing, a run the person asks for still does",
      not any(jobfinder.rate_limits(people.prefs(new)).values()) and jobfinder.rate_limits(people.prefs(new), auto=False)["haiku"] == 500)
people.save_prefs({"claude.auto_rate": True}, pid=new)

class A:  # the command line the server builds for "Rate more" / the Re-rate panel / the automatic quick check
    tiers, force, sonnet_pct, opus_top, no_target, ids_file = "haiku,sonnet,opus", False, 15, 2000, False, None
o = jobfinder.rate_opts(old, A)
check("Re-rate panel / Rate more run: same style of limit (no unlimited Sonnet)",
      o["budgets"] == {"haiku": 500, "sonnet_pct": 15, "sonnet_max": 100, "opus_top": 2000, "opus_max": 50} and o["pivot"]["max_new_per_run"] == 50, str(o))
A.tiers = "sonnet"
o = jobfinder.rate_opts(old, A)
check("single-model run from the panel is capped too", o["budgets"]["sonnet_max"] == 100 and o["budgets"]["haiku"] == 500 and o["pick"] == "best")
idsf = os.path.join(DATA, "ids.json")
json.dump([f"j{i:05d}" for i in range(900)], open(idsf, "w"))
A.tiers, A.ids_file = None, idsf
o = jobfinder.rate_opts(old, A)
check("automatic quick check after a settings save / rebuild: 200 at most", o["budgets"]["haiku"] == 200 and o["tiers"] == ["haiku"] and not o["target"])

# Target (pivot) ratings: at most 50 per run, whatever the caller asks for
people.set_current(old)
resume.save_manual({"name": "Old Person", "current_title": "Program Manager", "skills": ["planning"], "experience": []})
st = json.load(open(people.pdir("settings.json", pid=old)))
st.update(target_text="Move into operations leadership", target_keywords=["operations"], target_name="Ops")
json.dump(st, open(people.pdir("settings.json", pid=old), "w"))
asked = []
def fake_batch(cfg, system, profile, batch):
    asked.extend(j["id"] for j in batch)
    return {j["id"]: {"now": 60, "later": 70, "label": "after_prep", "gaps": [], "reason": "stub", "angle": ""} for j in batch}
real_batch, pivot._batch = pivot._batch, fake_batch
pj = [{"id": f"p{i:04d}", "title": "Operations Manager", "company": "C", "locations": ["X"], "desc": "d", "score": 50, "appeal": 50,
       "fit_score": 0, "comp_score": 50, "qol_score": 50, "clearance": "", "tracks": ["ai"]} for i in range(400)]
pivot.score_jobs(pj, {**jobfinder.BASE_CFG["pivot"], "max_new_per_run": 10 ** 6}, log=lambda m: None)
check("Target ratings: at most 50 per run even if asked for more", len(asked) == 50, str(len(asked)))
asked.clear()
pivot.score_jobs(pj, {**jobfinder.BASE_CFG["pivot"], "max_new_per_run": 50}, log=lambda m: None)
check("Target ratings: the next run does the next 50", len(asked) == 50 and len(set(asked)) == 50)
pivot._batch = real_batch

# ------------------------------------------------------------------ 6. the usage log
usage_file = claude_usage.path()
if os.path.exists(usage_file):
    os.remove(usage_file)
stub = os.path.join(DATA, "stub.json")
json.dump({"_by_prompt": [["Score these postings", {"_rate_all": {"as_is_fit": 61, "tailored_fit": 73, "label": "tailor", "level": "match",
                                                                    "reason": "Stub.", "tailoring": ""}}],
                          ["SECRET-PROMPT", {"ok": True}]]}, open(stub, "w"))
os.environ["SIFTWELL_CLAUDE_STUB"] = stub
out = claude_cli.run_json("system text", "SECRET-PROMPT about Jane Doe, 12 Elm St", {"type": "object"}, model="claude-haiku-5-5", feature="Search")
batch = [{"id": f"u{i}", "title": "Cook", "company": "C", "locations": ["X"], "desc": "PRIVATE-DESC"} for i in range(7)]
res = ai_score._score_batch_cli("claude", {"model": "claude-haiku-5-5"}, "PROFILE Jane Doe", batch)
check("stubbed Match batch rates every job without calling Claude", len(res) == 7 and res["u0"]["fit"] == 73)
claude_usage.record("Tailored resumes", "claude-opus-5-5", {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 50,
                                                           "cache_creation_input_tokens": 10}, None)
rows = [json.loads(l) for l in open(usage_file, encoding="utf-8")]
check("one line per call", len(rows) == 3 and out == {"ok": True}, str(len(rows)))
check("lines hold time, feature, model, tokens and jobs in the batch",
      rows[1]["feature"] == "Match ratings" and rows[1]["jobs"] == 7 and rows[1]["model"] == "claude-haiku-5-5" and rows[1].get("stub") is True
      and rows[2] == {**rows[2], "in": 1200, "out": 300, "cache_read": 50, "cache_write": 10, "jobs": None} and all(r["t"] for r in rows), str(rows))
raw = open(usage_file, encoding="utf-8").read()
check("no prompt text or personal data in the log", not any(x in raw for x in ("SECRET", "Jane", "Elm", "PRIVATE", "PROFILE", "system text")))
check("only the agreed fields are written", all(set(r) <= {"t", "feature", "model", "in", "out", "cache_read", "cache_write", "jobs", "stub"} for r in rows))
sm = claude_usage.summary()
tl = {f["feature"]: f for f in sm["today"]["features"]}
check("summary: today and last 7 days, by feature", sm["today"]["calls"] == 3 and sm["week"]["calls"] == 3 and tl["Tailored resumes"]["tokens"] == 1560
      and tl["Match ratings"]["jobs"] == 7 and tl["Search"]["calls"] == 1, str(sm["today"]))
import datetime as dt
with open(usage_file, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"t": (dt.datetime.now() - dt.timedelta(days=3)).isoformat(timespec="seconds"), "feature": "Match ratings",
                         "model": "m", "in": 100, "out": 0, "cache_read": 0, "cache_write": 0, "jobs": 25}) + "\n")
    fh.write(json.dumps({"t": (dt.datetime.now() - dt.timedelta(days=30)).isoformat(timespec="seconds"), "feature": "Match ratings",
                         "model": "m", "in": 999999, "out": 0, "cache_read": 0, "cache_write": 0, "jobs": 25}) + "\n")
    fh.write("not json\n")
sm = claude_usage.summary()
check("older lines count toward 7 days only; lines past a week and junk are ignored",
      sm["today"]["calls"] == 3 and sm["week"]["calls"] == 4 and sm["week"]["in"] == 1300, str(sm["week"]))
os.environ.pop("SIFTWELL_CLAUDE_STUB")
blocked = os.path.join(DATA, claude_cli.FORBID_LOG)
check("no real Claude call was attempted", not os.path.exists(blocked), open(blocked).read() if os.path.exists(blocked) else "")

print("\nall passed" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
