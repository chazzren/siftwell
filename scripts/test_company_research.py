"""Offline tests for company_research (Claude is stubbed or blocked; nothing is spent).
Run: python -X utf8 scripts/test_company_research.py [scratch data dir]
Checks: cleaning Claude's answer, merge precedence (hand facts win), queue order, the 180-day refresh, failure backoff,
the per-update cap (highest over profiles), the no-Claude and blocked-Claude paths, the stub path through claude_cli."""
import datetime as dt, json, os, shutil, sys, tempfile
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ.pop("SIFTWELL_CLAUDE_STUB", None)
os.environ.pop("SIFTWELL_PRETEND_NO_CLAUDE", None)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
DATA = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="company_research_test_")
if os.path.isdir(DATA):
    shutil.rmtree(DATA)
os.makedirs(DATA)
os.environ["JOBBOARD_DATA"] = DATA
import paths, people, claude_cli, company_research as cr

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

TODAY = dt.date.today()
ago = lambda d: (TODAY - dt.timedelta(days=d)).isoformat()
FD = os.path.join(DATA, "company_facts")
os.makedirs(FD, exist_ok=True)
def wjson(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
def rjson(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
def reset_facts():
    shutil.rmtree(FD, ignore_errors=True)
    os.makedirs(FD)
    try:
        os.remove(os.path.join(DATA, "company_facts.json"))
    except OSError:
        pass

GOOD = {"ownership": "private", "parent": None, "ticker": None, "value_usd": 61000000000, "value_kind": "valuation",
        "value_as_of": "2026-05", "value_source": "https://example.com/val", "stage": "Series H", "total_raised_usd": 11400000000,
        "employees": 8620, "employees_as_of": "2026-06", "employees_source": "https://example.com/emp", "founded": 2017,
        "hq": "Costa Mesa, CA", "equity": "stock options", "tender_offers": None, "layoffs": "none reported", "layoffs_source": None,
        "levels_url": "https://www.levels.fyi/companies/x/salaries", "blurb": "Builds things.", "gd_rating": 4.04,
        "gd_reviews": 300, "gd_recommend_pct": 75, "gd_as_of": "2026-11", "gd_source": "https://www.glassdoor.com/x", "gd_note": None}

# ---------------------------------------------------------------- cleaning
r = cr.clean(GOOD)
check("clean keeps a good record", r["ownership"] == "private" and r["employees"] == 8620 and r["value_kind"] == "valuation")
check("clean rounds the rating to one decimal", r["gd_rating"] == 4.0 and isinstance(r["gd_rating"], float))
check("clean has exactly the schema fields", set(r) == set(cr.FIELDS))
bad = dict(GOOD, ownership="kinda", ticker="<script>", value_usd="61B", employees=True, founded=3000, gd_rating=6,
           value_source="javascript:alert(1)", employees_source="http://127.0.0.1/x", levels_url="ftp://x.com/a",
           blurb="x" * 1000 + "\n<b>", hq="Line\nbreak", extra="dropped", stage=12)
r = cr.clean(bad)
check("bad ownership -> null", r["ownership"] is None)
check("ticker with markup -> null", r["ticker"] is None)
check("string number -> null, and its kind/as-of/source dropped", r["value_usd"] is None and r["value_kind"] is None and r["value_as_of"] is None and r["value_source"] is None)
check("bool employees -> null (and its source)", r["employees"] is None and r["employees_source"] is None)
check("future founding year -> null", r["founded"] is None)
check("rating out of 1-5 -> null, with all gd_* fields", r["gd_rating"] is None and r["gd_reviews"] is None and r["gd_source"] is None)
check("non-http link -> null", r["levels_url"] is None)
check("blurb capped at 300, no line breaks", len(r["blurb"]) <= 300 and "\n" not in r["blurb"])
check("hq line break removed", r["hq"] == "Line break")
check("unknown keys dropped", "extra" not in r)
check("non-string stage -> null", r["stage"] is None)
check("local address link dropped", cr._url("http://localhost/a") is None and cr._url("https://10.0.0.1/a") is None)
check("http(s) public link kept", cr._url("https://www.glassdoor.com/Reviews/x.htm") == "https://www.glassdoor.com/Reviews/x.htm")
check("month formats", cr._month("2026-5") == "2026-05" and cr._month("2025") == "2025" and cr._month("2026-05-17") == "2026-05"
      and cr._month("May 2026") is None and cr._month("1850-01") is None)
check("rating 1.0 and 5.0 allowed", cr.clean(dict(GOOD, gd_rating=5))["gd_rating"] == 5.0 and cr.clean(dict(GOOD, gd_rating=1))["gd_rating"] == 1.0)
check("recommend % range", cr.clean(dict(GOOD, gd_recommend_pct=140))["gd_recommend_pct"] is None)
try:
    cr.clean({k: None for k in cr.FIELDS})
    check("all-null answer is a failure", False)
except ValueError:
    check("all-null answer is a failure", True)
try:
    cr.clean(["not", "a", "dict"])
    check("non-object answer is a failure", False)
except ValueError:
    check("non-object answer is a failure", True)

# ---------------------------------------------------------------- merge precedence
reset_facts()
wjson(os.path.join(FD, "part1.json"), {"Hand Co": {"ownership": "public", "blurb": "hand", "gd_rating": None}})
wjson(os.path.join(FD, "gd1.json"), {"Hand Co": {"gd_rating": 3.9}, "GdOnly Co": {"gd_rating": 4.4, "gd_source": "https://g.example.com/"}})
wjson(os.path.join(FD, "gdtodo1.json"), {"Todo Co": {"gd_rating": 1.0}})
auto = {"Hand Co": dict(cr.clean(GOOD), blurb="auto", researched_at=ago(1)),
        "GdOnly Co": dict(cr.clean(GOOD), gd_rating=2.0, researched_at=ago(1)),
        "Auto Co": dict(cr.clean(GOOD), researched_at=ago(1))}
wjson(os.path.join(FD, "auto.json"), auto)
m = cr.merge()
mf = rjson(os.path.join(DATA, "company_facts.json"))
check("merge writes company_facts.json", mf == m)
check("hand company keeps exactly its hand facts (+ gd)", mf["Hand Co"] == {"ownership": "public", "blurb": "hand", "gd_rating": 3.9})
check("Glassdoor-only hand entry is laid over the auto record", mf["GdOnly Co"]["gd_rating"] == 4.4 and mf["GdOnly Co"]["blurb"] == "Builds things.")
check("auto-only company comes from auto.json", mf["Auto Co"]["researched_at"] == ago(1))
check("gdtodo files are ignored", "Todo Co" not in mf)
check("hand_names = part* companies", cr.hand_names() == {"Hand Co"})
import jobfinder
jobfinder._FACTS["stale"] = {}
jobfinder.merge_company_facts()
check("jobfinder.merge_company_facts uses it and resets the Appeal cache", "stale" not in jobfinder._FACTS
      and jobfinder.company_facts().get("Hand Co", {}).get("blurb") == "hand")
# no hand files: the non-auto entries of an existing merged file are treated as hand facts (never lost)
reset_facts()
wjson(os.path.join(DATA, "company_facts.json"), {"Old Co": {"ownership": "private"}, "Was Auto": {"ownership": "public", "researched_at": ago(400)}})
wjson(os.path.join(FD, "auto.json"), {"New Co": dict(cr.clean(GOOD), researched_at=ago(0))})
m = cr.merge()
check("merged file without part files keeps its hand entries", m.get("Old Co") == {"ownership": "private"} and "New Co" in m)
check("old auto entries not in auto.json are dropped", "Was Auto" not in m)

# ---------------------------------------------------------------- queue order, refresh, backoff
reset_facts()
q = cr.queue(weights={"B": 2.0, "A": 5.0, "Z": 0}, open_counts={"A": 3, "B": 1, "C": 50, "D": 2, "E": 0}, auto={}, failed={}, hand=set())
check("only companies on someone's board, top-ranked first; a catalog company on nobody's board is never looked up", q == ["A", "B"])
auto = {"A": {"researched_at": ago(100)}, "B": {"researched_at": ago(200)}}
failed = {"C": {"at": ago(5)}, "D": {"at": ago(20)}}
q = cr.queue(weights={"A": 5, "B": 2, "C": 1, "D": 1, "H": 9}, open_counts={"C": 50, "D": 2, "H": 1, "Unseen": 400}, auto=auto, failed=failed, hand={"H"})
check("researched 100 days ago is skipped, 200 days ago is due", "A" not in q and "B" in q)
check("failed 5 days ago waits, 20 days ago is retried", "C" not in q and "D" in q)
check("hand-researched companies are never queued", "H" not in q)
check("...and neither is one with 400 open listings that is on nobody's board", "Unseen" not in q)

# board weights from everyone's boards
people.save_index([{"id": "ann", "name": "Ann"}, {"id": "bob", "name": "Bob"}])
paths.dump_json_atomic(people.pdir("jobs.json", pid="ann"), {"jobs": [
    {"company": "Alpha", "score": 90}, {"company": "Alpha", "score": 80}, {"company": "Beta", "score": 95},
    {"company": "Gamma", "score": 99, "req_status": "unmet"}]})
paths.dump_json_atomic(people.pdir("jobs.json", pid="bob"), {"jobs": [{"company": "Beta", "score": 40}, {"company": "Delta", "score": 10}]})
w = cr.board_weights()
check("weight = the best-ranked job on anyone's board (plus a little per job); unmet jobs ignored",
      "Gamma" not in w and w["Beta"] > w["Alpha"] > w["Delta"] and abs(w["Beta"] - 95.12) < 1e-9 and abs(w["Alpha"] - 90.12) < 1e-9)
check("queue from boards: the top-ranked first (Beta, Alpha, Delta)", cr.queue(open_counts={"Elsewhere": 9})[:4] == ["Beta", "Alpha", "Delta"])
check("the default is 10 companies per update", people.PREF_SCHEMA[cr.PREF][0] == 10 and cr.per_update_cap() == 10)

# ---------------------------------------------------------------- cap
people.save_prefs({cr.PREF: 5}, pid="ann")
people.save_prefs({cr.PREF: 12}, pid="bob")
check("per-update cap is the highest over profiles", cr.per_update_cap() == 12)
people.save_prefs({cr.PREF: 999}, pid="bob")
check("pref is clamped to 200", cr.per_update_cap() == 200)
people.save_prefs({cr.PREF: 0}, pid="ann"); people.save_prefs({cr.PREF: 0}, pid="bob")
check("cap 0 -> run is off, nothing looked up", cr.run(log=lambda m: None, research=lambda n: 1 / 0)["status"] == "off")
people.save_prefs({cr.PREF: 40}, pid="ann"); people.save_prefs({cr.PREF: 40}, pid="bob")

# ---------------------------------------------------------------- run(): saving, failures, cap, progress
reset_facts()
calls, prog = [], []
def fake(name):
    calls.append(name)
    if name == "Beta":
        raise ValueError("Claude couldn't find facts about this company")
    return dict(cr.clean(dict(GOOD, blurb=f"{name} blurb")), researched_at=TODAY.isoformat())
res = cr.run(limit=2, log=lambda m: None, progress=lambda d, t: prog.append((d, t)), research=fake)
check("run looks up at most the limit", sorted(calls) == ["Alpha", "Beta"] and res["saved"] == 1 and res["failed"] == 1)
check("progress goes 0..n of n", prog[0] == (0, 2) and prog[-1] == (2, 2))
check("success saved in auto.json with researched_at", rjson(os.path.join(FD, "auto.json"))["Alpha"]["researched_at"] == TODAY.isoformat())
fl = rjson(os.path.join(FD, "auto_failed.json"))
check("failure remembered with date and count", fl["Beta"]["at"] == TODAY.isoformat() and fl["Beta"]["count"] == 1)
check("merged facts written after a run", rjson(os.path.join(DATA, "company_facts.json"))["Alpha"]["blurb"] == "Alpha blurb")
calls.clear()
cr.run(limit=10, log=lambda m: None, research=fake)
check("second run skips the fresh one and the recent failure", "Alpha" not in calls and "Beta" not in calls and "Delta" in calls)
st = cr.status_for(["Alpha", "Beta", "Nope"])
check("status_for: researched date, failure date, nothing", st["Alpha"]["at"] == TODAY.isoformat() and st["Beta"]["failed"] == TODAY.isoformat() and "Nope" not in st)
cr.save("Beta", dict(cr.clean(GOOD), researched_at=TODAY.isoformat()))
check("a later success clears the failure", "Beta" not in rjson(os.path.join(FD, "auto_failed.json")))

# ---------------------------------------------------------------- no Claude / blocked Claude
reset_facts()
os.environ["SIFTWELL_PRETEND_NO_CLAUDE"] = "1"
check("ready() is False without Claude", cr.ready() is False)
calls.clear()
res = cr.run(limit=5, log=lambda m: None)
check("no Claude: run skips quietly (no_claude), no calls", res["status"] == "no_claude" and not calls)
os.environ.pop("SIFTWELL_PRETEND_NO_CLAUDE")
real_ready = claude_cli.claude_ready
claude_cli.claude_ready = lambda fresh=False: True   # pretend signed in: SIFTWELL_FORBID_CLAUDE must then block the call
log_path = os.path.join(DATA, claude_cli.FORBID_LOG)
res = cr.run(limit=3, log=lambda m: None)
claude_cli.claude_ready = real_ready
check("SIFTWELL_FORBID_CLAUDE: run stops with status forbidden", res["status"] == "forbidden" and res["saved"] == 0)
check("blocked calls are logged, not remembered as failures", os.path.exists(log_path) and not os.path.exists(os.path.join(FD, "auto_failed.json")))
def signed_out(name):
    raise claude_cli.CLIAuthError("Please run /login")
check("signed out: run stops, no failures stored", cr.run(limit=3, log=lambda m: None, research=signed_out)["status"] == "signed_out"
      and not os.path.exists(os.path.join(FD, "auto_failed.json")))

# ---------------------------------------------------------------- stub path through claude_cli.run_json
stub = os.path.join(DATA, "stub.json")
wjson(stub, {"_by_prompt": [["<employer>Alpha</employer>", dict(GOOD, blurb="from the stub", gd_rating=9)]]})
os.environ["SIFTWELL_CLAUDE_STUB"] = stub
check("ready() is True with a stub", cr.ready() is True)
rec = cr.research_one("Alpha")
check("research_one goes through claude_cli and cleans the answer", rec["blurb"] == "from the stub" and rec["gd_rating"] is None
      and rec["researched_at"] == TODAY.isoformat())
ok, msg = cr.research_and_save("Alpha")
check("research_and_save saves and merges", ok and rjson(os.path.join(DATA, "company_facts.json"))["Alpha"]["blurb"] == "from the stub")
os.environ["SIFTWELL_CLAUDE_STUB"] = ""
os.environ.pop("SIFTWELL_CLAUDE_STUB")
claude_cli.claude_ready = lambda fresh=False: True
ok, msg = cr.research_and_save("Beta")   # no stub: blocked by SIFTWELL_FORBID_CLAUDE
claude_cli.claude_ready = real_ready
check("button path when blocked: not saved, not remembered as a failure", not ok and "Beta" not in cr.load_failed())
check("prompt names the company only between markers", "<employer>" in open(cr.__file__, encoding="utf-8").read())

print(f"\n{'ALL OK' if not fails else str(len(fails)) + ' FAILED'}")
if len(sys.argv) <= 1:
    shutil.rmtree(DATA, ignore_errors=True)
sys.exit(1 if fails else 0)
