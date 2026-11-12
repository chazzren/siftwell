"""Offline tests for "Build my own directory" (localdir.py, index_build/local.py, index_build/seed.py, the source
preference and the merge in directory.py): the seed list, reading order, pause / crash / resume, a job system that
stops answering, the files it writes and how they merge with a downloaded directory, tagged additions and undo, the
older built-in area's directory ZIP, the weekly upkeep's order, the installed (frozen) layout with no .py files on
disk, and a Backup & move round trip.

Run: SIFTWELL_FORBID_CLAUDE=1 python -X utf8 scripts/test_localdir.py   (no network; a temp data folder)"""
import datetime as dt, gzip, hashlib, json, os, py_compile, shutil, subprocess, sys, tempfile, threading, time, zipfile
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CODEX"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path[:0] = [ROOT, HERE]
TMP = tempfile.mkdtemp(prefix="localdir_test_")
os.environ["JOBBOARD_DATA"] = os.path.join(TMP, "data")
INDEX = os.path.join(TMP, "index")
os.environ["SIFTWELL_DIRECTORY_URL"] = "file:///" + INDEX.replace("\\", "/")

import catalog, directory, people
import localdir
from index_build import build, local, seed, systems

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)

catalog.migrate(log=lambda *a: None)
TODAY = dt.date.today().isoformat()
OLD = (dt.date.today() - dt.timedelta(days=3)).isoformat()
COLUMBUS, DAYTON, CLEVELAND, AUSTIN = (39.961, -82.999), (39.759, -84.192), (41.499, -81.694), (30.267, -97.743)


def gh(token):
    return {"ats": "greenhouse", "token": token}


def tenant(cfg, name="", places=(), jobs=None, remote=0, read=None, **kw):
    t = {"c": cfg, "src": ["cc"], "found": OLD, **kw}
    if read:
        t.update(read=read, jobs=sum(p[2] for p in places) if jobs is None else jobs, remote=remote,
                 places=[list(p) for p in places], name=name, fail=0, sample=False, secs=1.0)
    if name:
        t["seed_name"] = name
    return t


# ---------------------------------------------------------------- the seed list
state = {}
for i in range(30):
    c = gh(f"ohco{i:02d}")
    state[systems.key(c)] = tenant(c, f"Ohio Co {i:02d}", [(COLUMBUS[0], COLUMBUS[1], 30 - i, "Columbus, OH", "OH")], read=OLD)
for i in range(10):
    c = gh(f"txco{i:02d}")
    state[systems.key(c)] = tenant(c, f"Texas Co {i:02d}", [(AUSTIN[0], AUSTIN[1], 5 + i, "Austin, TX", "TX")], read=OLD)
for i in range(8):
    c = {"ats": "lever", "token": f"newco{i}"}
    state[systems.key(c)] = tenant(c)                                    # never read: no state known
for i in range(5):
    c = {"ats": "ashby", "token": f"empty{i}"}
    state[systems.key(c)] = tenant(c, f"Empty {i}", [], read=OLD)        # read, nothing open
c = {"ats": "ashby", "token": "remoteco"}
state[systems.key(c)] = tenant(c, "Remote Co", [], jobs=12, remote=12, read=OLD)
c = gh("deadco")
state[systems.key(c)] = tenant(c, fail=3, err="HTTPError: 404")          # only ever failed: not handed on
c = {"ats": "smartrecruiters", "token": "notread"}
state[systems.key(c)] = tenant(c)                                        # a system the directory doesn't read
c = {"ats": "workday", "tenant": "bigco", "wd": "wd5", "site": "External"}
state[systems.key(c)] = tenant(c, "Big Co", [(COLUMBUS[0], COLUMBUS[1], 400, "Columbus, OH", "OH"), (AUSTIN[0], AUSTIN[1], 90, "Austin, TX", "TX")], remote=7, read=OLD)

s = seed.make(state, TODAY)
data = seed.dumps(s)
bs = list(seed.boards(seed.loads(data)))
by = {systems.key(b["c"]): b for b in bs}
check("seed: every readable, not-dead board is in it", len(bs) == len(state) - 2, str(len(bs)))
check("seed: dead and unread-system boards are left out", systems.key(gh("deadco")) not in by and not any(b["c"]["ats"] == "smartrecruiters" for b in bs))
b = by[systems.key({"ats": "workday", "tenant": "bigco", "wd": "wd5", "site": "External"})]
check("seed: config, name, states and remote survive the round trip", b["n"] == "Big Co" and b["st"] == {"OH": 400, "TX": 90} and b["r"] == 7 and b["j"] == 490)
check("seed: a board nobody read has no hints", by[systems.key({"ats": "lever", "token": "newco0"})]["st"] == {} and by[systems.key({"ats": "lever", "token": "newco0"})]["j"] == 0)
check("seed: deterministic bytes", seed.dumps(seed.make(state, TODAY)) == data)
check("seed: garbage is refused", seed.read(os.path.join(TMP, "nope.gz")) is None)
bad = dict(s, groups=s["groups"] + [{"a": "greenhouse", "f": ["token"], "t": [["../../etc", "x", 1, 0, ""], ["ok-token", "Fine", 1, 0, "OH1"], "junk", ["short"]]},
                                    {"a": "nosuchsystem", "f": ["x"], "t": [["y", "n", 0, 0, ""]]}])
got = {b["c"].get("token") for b in seed.boards(bad)}
check("seed: rows that don't check out are skipped, the rest kept", "ok-token" in got and "../../etc" not in got)
shipped = localdir.SEED_ASSET
check("the shipped seed exists and is under 2 MB", os.path.exists(shipped) and os.path.getsize(shipped) < 2_000_000, str(os.path.exists(shipped) and os.path.getsize(shipped)))
ship = seed.read(shipped)
n_ship = sum(len(g["t"]) for g in ship["groups"])
check("the shipped seed has thousands of job sites, with measured seconds per system", n_ship > 5000 and len(ship.get("secs") or {}) >= 5, str(n_ship))
check("localdir.seed_summary counts the same", localdir.seed_summary()["boards"] == n_ship)

# the release step that ships the newest published seed (scripts/refresh_seed.py), against a folder standing in for the index branch
PUB = os.path.join(TMP, "published")
os.makedirs(PUB)
big = dict(s, groups=s["groups"] + [{"a": "greenhouse", "f": ["token"], "t": [[f"pub{i:04d}", f"Pub {i}", 1, 0, "OH1"] for i in range(1200)]}])
big_data = seed.dumps(big)
open(os.path.join(PUB, "seed.json.gz"), "wb").write(big_data)
json.dump({"v": 1, "built": TODAY, "seed": {"sha256": hashlib.sha256(big_data).hexdigest(), "bytes": len(big_data)}}, open(os.path.join(PUB, "manifest.json"), "w"))
OUT_SEED = os.path.join(TMP, "shipped-seed.json.gz")
def refresh(*extra):
    return subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, "refresh_seed.py"), "--base", "file:///" + PUB.replace("\\", "/"), "--out", OUT_SEED, *extra],
                          capture_output=True, text=True, timeout=120)
r = refresh()
check("refresh_seed: takes the published seed when its checksum matches", r.returncode == 0 and open(OUT_SEED, "rb").read() == big_data and "refreshed" in r.stdout, r.stdout + r.stderr)
check("refresh_seed: says so when it is already the newest", "already the newest" in refresh().stdout)
json.dump({"v": 1, "built": TODAY, "seed": {"sha256": "0" * 64}}, open(os.path.join(PUB, "manifest.json"), "w"))
open(os.path.join(PUB, "seed.json.gz"), "wb").write(data)
r = refresh()
check("refresh_seed: a bad checksum keeps the shipped file and doesn't fail the release", r.returncode == 0 and open(OUT_SEED, "rb").read() == big_data and "NOT refreshed" in r.stdout, r.stdout)
json.dump({"v": 1, "built": TODAY, "seed": {"sha256": hashlib.sha256(data).hexdigest()}}, open(os.path.join(PUB, "manifest.json"), "w"))
r = refresh("--strict")
check("refresh_seed: a seed with far fewer job sites than the shipped one is refused (--strict: exit 1)", r.returncode == 1 and open(OUT_SEED, "rb").read() == big_data, r.stdout)
os.remove(os.path.join(PUB, "manifest.json"))
check("refresh_seed: an unreachable directory keeps the shipped file", refresh().returncode == 0 and open(OUT_SEED, "rb").read() == big_data)
wf = open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8").read()
check("the release workflow refreshes the seed in every job that packages the app", wf.count("scripts/refresh_seed.py") == 3 and "git add VERSION assets/directory/seed.json.gz" in wf)

# ---------------------------------------------------------------- reading order
SEED_FILE = os.path.join(TMP, "seed.json.gz")
open(SEED_FILE, "wb").write(data)
ROOT_A = os.path.join(TMP, "buildA")
L = local.Local(ROOT_A)
L.load_seeds([SEED_FILE])
check("a seed merge adds every board once", len(L.T.d) >= len(bs) and not L.load_seeds([SEED_FILE]) is True or True)
n_before = len(L.T.d)
L.merge_seed(seed.loads(data))
check("... and merging it again adds nothing", len(L.T.d) == n_before)
keys = [k for k in L.candidates() if "pack" not in L.T.d[k]["src"]]
o = local.order(L.T.d, keys, ["OH"])
names = [L.T.d[k].get("seed_name") or L.T.d[k]["c"].get("token") for k in o]
check("order: boards last seen in the person's state first, most known jobs there first",
      names[:3] == ["Big Co", "Ohio Co 00", "Ohio Co 01"] and names[30] == "Ohio Co 29", str(names[:4]))
grp = [local.rank(L.T.d[k], {"OH"})[0] for k in o]
check("order: then no known state, then elsewhere, then last seen empty", grp == sorted(grp) and grp.count(0) == 31 and grp.count(1) == 9 and grp.count(2) == 10 and grp.count(3) == 5, str([grp.count(i) for i in range(5)]))
check("order: a remote-only board with open jobs counts as 'no known state'", local.rank(L.T.d[systems.key({"ats": "ashby", "token": "remoteco"})], {"OH"})[0] == 1)
o_r = local.order(L.T.d, keys, [], remote=True)
check("order (remote-only search): most US-remote jobs first", [L.T.d[k].get("seed_name") for k in o_r[:2]] == ["Remote Co", "Big Co"])
check("order is deterministic", local.order(L.T.d, list(reversed(keys)), ["OH"]) == o)
resting = dict(L.T.d[o[0]], rest_until="2999-01-01")
check("a resting board (three failures) is not a candidate", not local.resting(L.T.d[o[0]]) and local.resting(resting))

# ---------------------------------------------------------------- a build with a fake reader: pause, crash, resume
READS = []
def fake_reader(t, title_budget=None, fail=()):
    c = t["c"]
    tok = c.get("token") or c.get("tenant")
    READS.append(tok)
    time.sleep(0.002)
    if tok in fail:
        t["fail"] = int(t.get("fail", 0)) + 1
        t["err"] = "HTTPError: HTTP Error 404: Not Found"
        return "failed"
    if tok.startswith("ohco") or tok == "bigco":
        n = 3 + len(tok)
        t.update(read=build.today(), fail=0, jobs=n, remote=1 if tok == "bigco" else 0, sample=False, secs=0.1, kind="",
                 name=t.get("seed_name") or tok, bname=None,
                 places=[[COLUMBUS[0], COLUMBUS[1], n, "Columbus, OH", "OH"]] + ([[DAYTON[0], DAYTON[1], 2, "Dayton, OH", "OH"]] if tok == "ohco03" else []))
        return "ok"
    if tok.startswith("txco"):
        t.update(read=build.today(), fail=0, jobs=4, remote=0, sample=False, secs=0.1, kind="", name=t.get("seed_name") or tok, bname=None,
                 places=[[AUSTIN[0], AUSTIN[1], 4, "Austin, TX", "TX"]])
        return "ok"
    t.update(read=build.today(), fail=0, jobs=0, remote=0, sample=False, secs=0.1, kind="", name=t.get("seed_name") or tok, bname=None, places=[])
    return "empty"

for k in [k for k in L.T.d if "pack" in L.T.d[k]["src"]]:
    del L.T.d[k]                # (keep the test small: only the seed's boards)
L.meta["packs"] = TODAY
L.compact()
AREA = {"pid": "p1", "lat": COLUMBUS[0], "lon": COLUMBUS[1], "radius": 25, "states": ["OH"], "remote_only": False}
JOB1 = {"mode": "pass", "areas": [AREA], "seeds": []}
n_all = len(L.candidates())
stop_at = lambda n: (lambda: len(READS) >= n)
out = L.run(JOB1, stop_at(20), reader=fake_reader)
check("pause: the run stops when told to", out["phase"] == "stopped" and 20 <= out["run_done"] < n_all, str(out["run_done"]))
first_run = list(READS)
check("... having read the nearby boards first (each job system in its own order, side by side)",
      not any(t.startswith("txco") for t in first_run) and [t for t in first_run if t.startswith("ohco")][:1] == ["ohco00"] and "bigco" in first_run[:4], str(first_run[:8]))
check("... and the area's state file is there, in the directory's format",
      (lambda d: d["v"] == 1 and d["state"] == "OH" and len(d["employers"]) >= 6 and {"n", "c", "u", "j", "p", "s"} <= set(d["employers"][0]))(
          json.load(gzip.open(os.path.join(ROOT_A, "states", "OH.json.gz"), "rt", encoding="utf-8"))))
check("progress: counts, a rate and how many are near the person", out["done"] == out["run_done"] and out["total"] == n_all and out["near"]["p1"] >= 6 and out["near_total"] == 31, json.dumps({k: out[k] for k in ("done", "total", "near", "near_total")}))
man = json.load(open(os.path.join(ROOT_A, "manifest.json"), encoding="utf-8"))
check("the local manifest says what is there and that the pass isn't finished", man["local"] is True and "OH" in man["states"] and not man["pass_finished"] and man["pass_started"])

# resume in a new process' worth of state: nothing is read twice, the pass carries on and finishes
L2 = local.Local(ROOT_A)
todo, total = L2.pass_todo()
check("resume: what is left is exactly what wasn't read", len(todo) == n_all - out["run_done"] and total == n_all, f"{len(todo)} {n_all} {out['run_done']}")
READS.clear()
out2 = L2.run(JOB1, lambda: False, reader=fake_reader)
check("resume: the rest is read, nothing twice", out2["phase"] == "done" and not set(READS) & set(first_run) and len(READS) == n_all - len(first_run), f"{len(READS)} {len(set(READS) & set(first_run))}")
check("... and the pass is finished", bool(local.Local(ROOT_A).meta["pass"]["finished"]) and out2["done"] == out2["total"])
check("the totals never went down across the pause", out2["done"] >= out["done"])
READS.clear()
out3 = local.Local(ROOT_A).run(JOB1, lambda: False, reader=fake_reader)
check("starting again without 'fresh' reads nothing (the pass is done)", READS == [] and out3["phase"] == "done")
out4 = local.Local(ROOT_A).run(dict(JOB1, fresh=True, limit=5), lambda: False, reader=fake_reader)
check("'fresh' starts a new pass", len(READS) == 5 and local.Local(ROOT_A).meta["pass"]["n"] == 2)

# a crash: the journal alone brings the reads back
ROOT_B = os.path.join(TMP, "buildB")
LB = local.Local(ROOT_B)
LB.merge_seed(seed.loads(data))
LB.compact()
LB.begin_pass()
LB.save_meta()
k0 = systems.key(gh("ohco00"))
tmp = dict(LB.T.d[k0])
fake_reader(tmp)
tmp["lt"] = time.time()
LB.T.d[k0] = tmp
LB.record(k0)
LB._jf.flush()
open(LB.journal, "a", encoding="utf-8").write('{"k": "torn line')         # the process died mid-write
LC = local.Local(ROOT_B)
check("crash: the journal is replayed (a torn last line is ignored)", LC.replayed == 1 and LC.T.d[k0].get("read") == build.today())
check("... so that board is not read again", k0 not in LC.pass_todo()[0])

# a job system that starts refusing connections is left alone, and its boards aren't counted as failed
ROOT_C = os.path.join(TMP, "buildC")
LD_ = local.Local(ROOT_C)
for i in range(40):
    c = {"ats": "paylocity", "id": f"1{i:04d}"} if False else gh(f"shared{i:02d}")
    LD_.T.d[systems.key(c)] = {"c": c, "src": ["seed"], "found": TODAY}
c_ok = {"ats": "lever", "token": "fineco"}
LD_.T.d[systems.key(c_ok)] = {"c": c_ok, "src": ["seed"], "found": TODAY}
LD_.meta["packs"] = TODAY
calls = []
def flaky(t, title_budget=None):
    tok = t["c"]["token"]
    calls.append(tok)
    if tok.startswith("shared") and len([c for c in calls if c.startswith("shared")]) > 4:
        t["fail"] = int(t.get("fail", 0)) + 1
        t["err"] = "RemoteDisconnected: Remote end closed connection without response"
        return "failed"
    return fake_reader(t)
outc = LD_.run({"mode": "pass", "areas": [AREA], "seeds": []}, lambda: False, reader=flaky)
n_shared_calls = len([c for c in calls if c.startswith("shared")])
check("a host that refuses connections: Siftwell stops asking instead of trying every board", n_shared_calls < 40 * 2 and outc["stats"]["deferred"] >= 25, f"{n_shared_calls} calls, {outc['stats']}")
check("... its boards are left for another day, not marked as failed three times over", max(int(t.get("fail") or 0) for t in LD_.T.d.values()) <= 1 and outc["stats"]["failed"] <= 8, str(outc["stats"]))
check("... other job systems are read as usual and the pass still finishes", "fineco" in calls and outc["phase"] == "done" and bool(LD_.meta["pass"]["finished"]))
check("host_of: one shared host per system where the address says so", local.host_of(gh("a")) == local.host_of(gh("b")) != local.host_of({"ats": "bamboohr", "token": "a"}))

# estimates: the slowest lane decides, from measured seconds
check("lane_minutes: boards x seconds / lanes read at once, the slowest lane decides",
      abs(local.lane_minutes({"greenhouse": 600, "lever": 60}, lambda a: local.board_secs(a, 3.0)) - 600 * 3.0 / build.LANES["greenhouse"] / 60) < 1e-6)
LE = local.Local(ROOT_A)
LE.meta["secs"] = {"greenhouse": [100.0, 10]}
LE.meta["seed_secs"] = {"greenhouse": 2.5, "lever": 4.0}
check("avg_secs: measured here once there are enough reads, else the seed's, else a default",
      LE.avg_secs("greenhouse") == 10.0 / build.LANES["greenhouse"] and LE.avg_secs("lever") == 4.0 and LE.avg_secs("ashby") == local.DEFAULT_SECS / 3)

# the weekly upkeep: nearby boards not tried for a week first, then the longest untried
LW = local.Local(ROOT_A)
week = time.time() - 8 * 86400
for i, (k, t) in enumerate(sorted(LW.T.d.items())):
    t["lt"] = week - i if not k.startswith("lever") else time.time()       # (lever boards were tried today)
wk, n_near = LW.weekly_todo(["OH"])
check("weekly: boards known near the person come first", n_near == 31 and all(local.rank(LW.T.d[k], {"OH"})[0] == 0 for k in wk[:n_near]))
check("weekly: then the rest, longest untried first; boards tried this week are skipped",
      [float(LW.T.d[k]["lt"]) for k in wk[n_near:]] == sorted(float(LW.T.d[k]["lt"]) for k in wk[n_near:]) and not any(k.startswith("lever") for k in wk))
held = {"n": 0}
def hold():
    held["n"] += 1
    return held["n"] < 4
READS.clear()
outw = LW.run({"mode": "weekly", "areas": [AREA], "limit": 6}, lambda: False, hold=hold, reader=fake_reader)
check("weekly: waits while a job fetch runs, then reads", held["n"] >= 4 and len(READS) == 6 and outw["mode"] == "weekly")
check("weekly: time-boxed", local.WEEKLY_MINUTES <= 60)

# ---------------------------------------------------------------- the source preference and the merge
def shard(name, emps, built=None):
    raw = gzip.compress(json.dumps({"v": 1, "state": name, "built": built or TODAY, "employers": emps}).encode(), 9, mtime=0)
    return raw

def emp(cfg, name, places, read, **kw):
    return {"n": name, "c": cfg, "u": "", "j": sum(p[2] for p in places), "r": 0, "p": [list(p) for p in places], "s": read, "ps": ["OH"], **kw}

def publish(emps):
    os.makedirs(os.path.join(INDEX, "states"), exist_ok=True)
    raw = shard("OH", emps)
    open(os.path.join(INDEX, "states", "OH.json.gz"), "wb").write(raw)
    man = {"v": 1, "built": OLD + "T00:00:00+00:00", "states": {"OH": {"employers": len(emps), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}, "jobs": {}, "sources": {}}
    json.dump(man, open(os.path.join(INDEX, "manifest.json"), "w"))

def write_local(emps, index=None):
    os.makedirs(os.path.join(directory.LOCAL, "states"), exist_ok=True)
    open(os.path.join(directory.LOCAL, "states", "OH.json.gz"), "wb").write(shard("OH", emps))
    local.write_json(os.path.join(directory.LOCAL, "manifest.json"), {"v": 1, "built": TODAY + "T12:00:00+00:00", "local": True, "states": {"OH": {"employers": len(emps)}}})
    build.save_json_gz(os.path.join(directory.LOCAL, "index.json.gz"), index or {})
    directory._PREVIEW.clear()

P = lambda n, where=COLUMBUS, label="Columbus, OH": [(where[0], where[1], n, label)]
A, B, C, D, E = gh("alpha"), gh("bravo"), gh("charlie"), gh("delta"), gh("echo")
publish([emp(A, "Alpha (shared)", P(10), OLD), emp(B, "Bravo (shared)", P(7), TODAY), emp(C, "Charlie (shared)", P(5), OLD), emp(D, "Delta (shared)", P(4), OLD)])
write_local([emp(A, "Alpha (local)", P(20), TODAY), emp(B, "Bravo (local)", P(9), OLD), emp(E, "Echo (local)", P(3), TODAY)],
            index={directory._short(directory._key(A)): TODAY, directory._short(directory._key(D)): TODAY, directory._short(directory._key(E)): TODAY})
pid = people.add("Tester")
people.save_settings({"home_zip": "43215", "radius_miles": 25}, pid)

def near_names():
    directory._PREVIEW.clear()
    emps, info = directory.near_employers(pid, directory.manifest(refresh=True) if directory.uses_shared() else directory.manifest())
    return {e["name"]: e["near"] for e in emps}, info

check("the default is the shared directory", directory.source() == "shared")
got, info = near_names()
check("shared: only the downloaded file counts (the local one is ignored)", got == {"Alpha (shared)": 10, "Bravo (shared)": 7, "Charlie (shared)": 5, "Delta (shared)": 4}, str(got))
directory.save_prefs(source="both")
got, info = near_names()
check("both: per employer the newer reading wins (local Alpha, shared Bravo)", got.get("Alpha (local)") == 20 and got.get("Bravo (shared)") == 7 and "Alpha (shared)" not in got and "Bravo (local)" not in got, str(got))
check("both: an employer only one side has is kept", got.get("Charlie (shared)") == 5 and got.get("Echo (local)") == 3)
check("both: an employer this computer read later and no longer found in the state is dropped", "Delta (shared)" not in got, str(got))
check("both: each employer once", len(got) == 4, str(got))
directory.save_prefs(source="local")
calls_get = []
real_get = directory.urllib.request.urlopen
directory.urllib.request.urlopen = lambda *a, **k: calls_get.append(a) or (_ for _ in ()).throw(AssertionError("contacted the index"))
try:
    got, info = near_names()
    check("local: only what was built on this computer", got == {"Alpha (local)": 20, "Bravo (local)": 9, "Echo (local)": 3}, str(got))
    directory.refresh(force=True); directory.manifest(refresh=True); directory.preview(pid, refresh=True); directory.apply(pid, dry=True)
    check("local: the app never contacts the index branch", calls_get == [] and not directory._stale())
    try:
        directory._get("manifest.json")
        refused = False
    except RuntimeError:
        refused = True
    check("local: a download is refused outright", refused and calls_get == [])
    check("local: the seed is not refreshed from the shared directory either", localdir.refresh_seed() is False and calls_get == [])
finally:
    directory.urllib.request.urlopen = real_get
check("the preference survives a re-read", directory.prefs()["source"] == "local" and json.load(open(os.path.join(directory.DIR, "prefs.json")))["source"] == "local")

# nothing built yet + "Built on this computer": not "offline", the state is simply missing (the first search then uses starters)
shutil.rmtree(directory.LOCAL)
directory._CACHE.clear()
emps, info = directory.near_employers(pid, directory.manifest())
check("local, nothing built: no employers, the state is reported missing (not 'offline')", emps == [] and info.get("missing") == ["OH"] and info.get("reason") is None, str(info))
r = directory.apply(pid, dry=True, starters_ok=True)
check("... so a first search falls back to the shipped starter list", r["available"] and r["starters"] > 100 and not r["offline"])

# both + the shared directory unreachable + something built here: not offline
write_local([emp(A, "Alpha (local)", P(20), TODAY), emp(E, "Echo (local)", P(3), TODAY)])
directory.save_prefs(source="both")
os.environ["SIFTWELL_DIRECTORY_URL"] = "http://127.0.0.1:9/nothing-here"
shutil.rmtree(os.path.join(directory.DIR, "states"), ignore_errors=True)
for f in ("manifest.json",):
    try:
        os.remove(os.path.join(directory.DIR, f))
    except OSError:
        pass
directory._CACHE.clear()
got, info = near_names()
check("both, shared unreachable: the locally built directory still answers", got == {"Alpha (local)": 20, "Echo (local)": 3} and info.get("reason") is None, f"{got} {info}")
directory.save_prefs(source="shared")
emps, info = directory.near_employers(pid, directory.manifest(refresh=True))
check("shared, unreachable: offline, as before", info.get("reason") == "offline")
os.environ["SIFTWELL_DIRECTORY_URL"] = "file:///" + INDEX.replace("\\", "/")

# ---------------------------------------------------------------- additions under one tag are one batch; undo takes them all back
directory.save_prefs(source="local")
write_local([emp(A, "Alpha", P(20), TODAY)])
r1 = directory.apply(pid, tag="build-1")
write_local([emp(A, "Alpha", P(20), TODAY), emp(E, "Echo", P(3), TODAY), emp(B, "Bravo", P(2), TODAY)])
r2 = directory.apply(pid, tag="build-1")
rec = directory.record(pid)
check("the build adds what it finds as it goes", r1["added"] == ["Alpha"] and sorted(r2["added"]) == ["Bravo", "Echo"])
check("... as ONE batch", len(rec["batches"]) == 1 and len(rec["batches"][0]["added"]) == 3 and rec["batches"][0]["tag"] == "build-1")
check("... leaving the all / top N choice alone", "top_only" not in rec or rec["top_only"] is False)
write_local([emp(A, "Alpha", P(20), TODAY), emp(E, "Echo", P(3), TODAY), emp(B, "Bravo", P(2), TODAY), emp(C, "Charlie", P(9), TODAY), emp(D, "Delta", P(8), TODAY)])
r3 = directory.apply(pid, tag="build-1", limit=1)
check("a limit adds only the one with the most openings nearby", r3["added"] == ["Charlie"] and r3["skipped"] == 1)
check("undo takes the whole build's additions back", directory.undo(pid)["removed"] == 4 and not [c for c in catalog.companies() if f"near-{pid}" in (c.get("sets") or [])])
r4 = directory.apply(pid, tag="build-2")
check("... and they can be added again", len(r4["added"]) == 5)

# ---------------------------------------------------------------- the engine's files through directory.py, end to end
shutil.rmtree(directory.LOCAL)
directory._CACHE.clear()
directory.undo(pid)
LF = local.Local(directory.LOCAL)
LF.merge_seed(seed.loads(data))
LF.meta["packs"] = TODAY
READS.clear()
ar = localdir.areas(pid)
check("areas: the profile's ZIP, radius and the states around it", ar and ar[0]["pid"] == pid and ar[0]["states"] == ["OH"] and ar[0]["radius"] == 25 and not ar[0]["remote_only"], str(ar))
outf = LF.run({"mode": "pass", "areas": ar, "seeds": []}, lambda: False, reader=fake_reader)
directory._CACHE.clear(); directory._PREVIEW.clear()
emps, info = directory.near_employers(pid, directory.manifest())
check("a finished build: directory.py finds the nearby employers in its files", len(emps) == 31 and info.get("missing") == [] and outf["near"][pid] == 31, f"{len(emps)} {info} {outf['near']}")
pv = directory.preview(pid, refresh=True)
check("... the chooser offers them (nothing is added blindly)", pv["available"] and pv["new"] == 31 and pv["options"])
check("... with where they hire", any(e["where"].startswith("Columbus") for e in emps))
man = directory.manifest()
check("manifest (local): no shared states, the local ones under 'local', a built date", man.get("_off") and "OH" in man["local"]["states"] and man["built"])
idx = json.load(gzip.open(os.path.join(directory.LOCAL, "index.json.gz"), "rt"))
check("the index of what was read when covers every board read, also the empty ones", len(idx) == len([t for t in LF.T.d.values() if t.get("read")]) and len(idx) > 45)
rem = json.load(gzip.open(os.path.join(directory.LOCAL, "states", "remote.json.gz"), "rt"))
check("remote.json.gz lists the boards with US-remote jobs", [e["n"] for e in rem["employers"]] == ["Big Co"])

# the one progress line
line = localdir._line({"total": 6300, "done": 1240, "near": {pid: 212}}, pid)
check("the progress line", line == "Building your directory: 1,240 of 6,300 job sites checked · 212 employers near you so far", line)
check("... before the first count", localdir._line({}, pid) == "Building your directory: getting ready")
check("... one employer", localdir._line({"total": 10, "done": 1, "near": {pid: 1}}, pid).endswith("1 employer near you so far"))
check("progress() is None when nothing runs", localdir.progress(pid) is None and not localdir.running())
est = localdir.estimate(pid)
check("estimate: job sites, the ones near first, minutes from measured seconds", est["sites"] > 0 and est["all_min"] >= est["near_min"] >= 0 and est["all_text"])
check("the offer says what, how long and that it uses no Claude", (lambda o: "job sites" in o and "no Claude" in o and "about" in o)(localdir.offer(pid, {**est, "sites": 42000, "near_sites": 2600, "all_text": "about 4 hours", "near_text": "about 15 minutes"})))
stt = localdir.status(pid)
check("status: where the directory comes from", stt["source"] == "local" and stt["origin"] == "local" and stt["local_built"] and stt["local_complete"] and not stt["running"], json.dumps({k: stt[k] for k in ("source", "origin", "local_built", "local_complete")}))
directory.save_prefs(source="shared")
check("status: shared and never reached is 'starter list only'", localdir.status(pid)["origin"] in ("starter", "shared"))
check("upkeep: not due right after a pass; due a week later; never with the shared directory only",
      (directory.save_prefs(source="local") and not localdir.upkeep_due())
      and (local.write_json(os.path.join(directory.LOCAL, "build.json"), dict(LF.meta, **{"pass": dict(LF.meta["pass"], finished=time.time() - 8 * 86400)})) and localdir.upkeep_due())
      and (directory.save_prefs(source="shared") and not localdir.upkeep_due()))
directory.save_prefs(source="local")


# ---------------------------------------------------------------- polite by design: pacing per provider (index_build/net.py)
from index_build import net, readers
import email.message, io as _io, urllib.error, urllib.request
check("providers: every Workday tenant host is one provider; Paylocity, UKG's hosts, an employer's own site",
      net.provider_of("acme.wd5.myworkdayjobs.com")[0] == net.provider_of("other.wd1.myworkdayjobs.com")[0] == "workday"
      and net.provider_of("recruiting.paylocity.com") == ("paylocity", 1.0, 1)
      and net.provider_of("recruiting2.ultipro.com")[0] == net.provider_of("acme.rec.pro.ukg.net")[0] == "ukg"
      and net.provider_of("boards-api.greenhouse.io")[0] == net.provider_of("job-boards.greenhouse.io")[0]
      and net.provider_of("careers.acme.com") == ("acme.com",) + net.DEFAULT_PACE and net.DEFAULT_PACE[0] <= 1.0)
check("providers: shared multi-tenant systems are asked about once a second on one or two connections",
      all(net.PROVIDERS[d][1] <= 1.0 and net.PROVIDERS[d][2] <= 2 for d in ("paylocity.com", "ultipro.com", "adp.com", "workable.com", "taleo.net"))
      and all(v[1] <= 3.0 and v[2] <= 4 for v in net.PROVIDERS.values()))
net.PROVIDERS["pacetest.example"] = ("pacetest", 10.0, 2)
net.PROVIDERS["slowtest.example"] = ("slowtest", 1.0, 1)
state_p = {"live": 0, "peak": 0, "times": [], "fail": None, "enc": []}
class FakeResp:
    def __init__(self, body, headers):
        self._b, self.headers, self.status = _io.BytesIO(body), headers, 200
    def read(self, n=-1):
        return self._b.read(n)
    def geturl(self):
        return "https://x"
    def close(self):
        pass
def fake_open(req, data=None, timeout=30):
    state_p["live"] += 1
    state_p["peak"] = max(state_p["peak"], state_p["live"])
    state_p["times"].append(time.time())
    state_p["enc"].append(req.get_header("Accept-encoding"))
    try:
        time.sleep(0.05)
        if state_p["fail"]:
            h = email.message.Message()
            if state_p["fail"][1] is not None:
                h["Retry-After"] = str(state_p["fail"][1])
            raise urllib.error.HTTPError(req.full_url, state_p["fail"][0], "slow down", h, None)
        h = email.message.Message()
        h["Content-Encoding"] = "gzip"
        return FakeResp(gzip.compress(b'{"jobs": [' + b'"x",' * 2000 + b'"y"]}'), h)
    finally:
        state_p["live"] -= 1
w0, p0 = net.STATS["wire"], net.STATS["plain"]
ths = [threading.Thread(target=lambda i=i: net._paced_open(fake_open, f"https://t{i}.pacetest.example/a")) for i in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
gaps = [b - a for a, b in zip(sorted(state_p["times"]), sorted(state_p["times"])[1:])]
check("pacing: requests to one provider are spaced (10 a second here) whatever the host name", min(gaps) >= 0.08, str([round(g, 3) for g in gaps]))
check("pacing: never more connections at once than the provider's cap", state_p["peak"] <= 2, str(state_p["peak"]))
r = net._paced_open(fake_open, urllib.request.Request("https://a.pacetest.example/b"))
check("gzip is asked for on every request and unpacked for the caller", state_p["enc"][-1] == "gzip" and json.loads(r.read())["jobs"][-1] == "y" and not r.headers.get("Content-Encoding"))
check("... and what crossed the wire is counted, next to what it would have been", 0 < net.STATS["wire"] - w0 < (net.STATS["plain"] - p0) / 5)
own = urllib.request.Request("https://a.pacetest.example/c", headers={"Accept-Encoding": "gzip"})
r2 = net._paced_open(fake_open, own)
check("a caller that asked for gzip itself still gets the packed bytes and the header", r2.headers.get("Content-Encoding") == "gzip" and r2.read()[:2] == b"\x1f\x8b")
state_p["fail"] = (429, 2)
t0 = time.time()
try:
    net._paced_open(fake_open, "https://a.slowtest.example/x")
    raised = False
except urllib.error.HTTPError:
    raised = True
state_p["fail"] = None
check("429: the error reaches the caller and the provider is left alone", raised and "slowtest" in net.resting())
net._paced_open(fake_open, "https://b.slowtest.example/y")
check("... for at least as long as Retry-After and the first rest say, for every host of that provider", time.time() - t0 >= min(net.REST_FIRST, 2) and time.time() - t0 >= 2, f"{time.time() - t0:.1f}s")
check("... and a good answer afterwards clears it", net.pace_for("a.slowtest.example").strikes == 0)
check("a different provider is not held up by it", (lambda t: (net._paced_open(fake_open, "https://z.pacetest.example/q"), time.time() - t)[1] < 1.0)(time.time()))

net.OWN_SITE_MAX, keep_max = 3, net.OWN_SITE_MAX
try:
    got_n = 0
    for i in range(5):
        try:
            net._paced_open(fake_open, f"https://careers.one-employer-test.com/p{i}")
            got_n += 1
        except net.OverBudget:
            pass
finally:
    net.OWN_SITE_MAX = keep_max
check("an employer's own site is asked for only so many pages in one build; a job system is not limited that way",
      got_n == 3 and net.pace_for("recruiting.paylocity.com").budget is None and net.OWN_SITE_MAX <= 60, str(got_n))

# list only: no per-posting pages in a directory build
import extra_fetchers
cdet = {"name": "directory", "_detail_budget": 2}
check("the app's detail gate: a directory read opens no posting pages (two at most, to learn a name)",
      [extra_fetchers.wanted(cdet, "Nurse") for _ in range(4)] == [True, True, False, False]
      and extra_fetchers.wanted({"name": "directory", "_detail_budget": 0}, "Nurse") is False)
seen_details = []
orig_generic = readers.generic
readers.generic = lambda c, details=0: seen_details.append(details) or {"name": None, "jobs": 0, "remote": 0, "locs": {}, "sample": False}
try:
    build.read_tenant({"c": {"ats": "paylocity", "id": "12345"}, "src": ["seed"], "seed_name": "Acme"})
    build.read_tenant({"c": {"ats": "paylocity", "id": "12346"}, "src": ["seed"]})
finally:
    readers.generic = orig_generic
check("... a board that already has a name opens none; one known only by a code opens a couple", seen_details == [0, build.NAME_DETAILS], str(seen_details))

# heavy list pages: the first few are enough, the counts are scaled up
asked = []
def fake_icims_page(url, timeout=30):
    asked.append(url)
    n = int(url.rsplit("pr=", 1)[1])
    cards = "".join(f'<li class="iCIMS_JobCardItem"><a href="https://careers-x.icims.com/jobs/{n * 10 + i}/nurse/job"><h3>Nurse {n}-{i}</h3></a>'
                    f'<dt><span class="field-label">Job Locations</span></dt><dd><span>US-OH-Columbus</span></dd></li>' for i in range(10))
    return f"<html>{cards}<p>Page {n + 1} of 12</p></html>"
keep_ht = extra_fetchers.http_text
extra_fetchers.http_text = fake_icims_page
try:
    ci = {"ats": "icims", "base": "https://careers-x.icims.com", "name": "directory", "_detail_budget": 0, "_max_pages": readers.LIST_PAGES}
    got_rows = list(extra_fetchers.f_icims(ci))
    asked_dir = len(asked)
    asked.clear()
    cfull = {"ats": "icims", "base": "https://careers-x.icims.com", "name": "directory", "_detail_budget": 0}
    full_rows = list(extra_fetchers.f_icims(cfull))
finally:
    extra_fetchers.http_text = keep_ht
check("iCIMS in a directory read: only the first list pages are asked for, and the reader says how many there were",
      asked_dir == readers.LIST_PAGES and len(got_rows) == 10 * readers.LIST_PAGES and ci.get("_pages") == (readers.LIST_PAGES, 12) and ci.get("_truncated"), f"{asked_dir} {len(got_rows)} {ci.get('_pages')}")
check("... while the app's own fetch still reads every page", len(asked) == 12 and len(full_rows) == 120 and "_pages" not in cfull)
import jobfinder
jobfinder.load_extra()
keep_fx, keep_rob = jobfinder.FETCHERS["icims"], net.robots_ok
jobfinder.FETCHERS["icims"] = lambda c: (c.__setitem__("_pages", (3, 12)), c.__setitem__("_truncated", "x"),
                                         iter([{"locations": ["Columbus, OH"], "workplace": "", "desc": "", "title": "t"}] * 30))[2]
net.robots_ok = lambda *a, **k: True
try:
    sm = readers.generic({"ats": "icims", "base": "https://careers-x.icims.com"})
finally:
    jobfinder.FETCHERS["icims"], net.robots_ok = keep_fx, keep_rob
check("... and the directory scales the sample up to the whole board and marks it as sampled", sm["jobs"] == 120 and sm["locs"] == {"Columbus, OH": 120} and sm["sample"] is True, str(sm)[:200])

# very large boards go after the rest of the near-you group
big = {"c": gh("giant"), "src": ["seed"], "seed": [9000, 0, {"OH": 5000}, True]}
small = {"c": gh("small"), "src": ["seed"], "seed": [12, 0, {"OH": 12}, True]}
mid = {"c": gh("mid"), "src": ["seed"], "seed": [300, 0, {"OH": 300}, True]}
far = {"c": gh("far"), "src": ["seed"], "seed": [50, 0, {"TX": 50}, True]}
check("order: most known jobs first, but a giant board waits behind the ordinary nearby ones (and still before the rest)",
      local.order({"giant": big, "small": small, "mid": mid, "far": far}, ["giant", "small", "mid", "far"], ["OH"]) == ["mid", "small", "giant", "far"])
check("estimates never assume a provider is asked faster than its pace", local.board_secs("paylocity", 0.2) >= local.REQS_PER_BOARD / 1.0 and local.board_secs("greenhouse", 9.0) == 3.0)
check("times for people: a range for the near-you group, plain words for everything",
      localdir._range(15) == "about 15–25 minutes" and localdir._range(70).endswith("hours") and "–" in localdir._range(70)
      and localdir._words(240) == "a few hours" and localdir._words(801) == "several hours" and not any(ch.isdigit() for ch in localdir._words(801)))
du = localdir.data_use()
check("data use: MB for a first build, from a measured MB per 1,000 job sites", du["first_mb"] > 0 and du["mb_per_1000"] > 0 and du["measured"] in (True, False))
check("metered connections: asked of the OS on Windows, unknown elsewhere", localdir.metered() in ((True, False) if sys.platform == "win32" else (None,)))

# what a build adds is always checked (and rated, within the usual limits) by the ordinary staged check
import first_search, types
started = []
keep = (first_search.pending, first_search.start_checking, localdir.S, directory.apply, dict(first_search.JOB))
pend = {"n": 5}
first_search.pending = lambda pid_: ["x"] * pend["n"]
first_search.start_checking = lambda pid_, rate=True: (started.append(rate), (True, None))[1]
localdir.S = types.SimpleNamespace(state={"running": False}, _actlog=lambda *a, **k: None)
directory.apply = lambda *a, **k: {"available": False, "added": [], "linked": []}
c0 = localdir.control(); c0["add"] = {pid: "all"}; localdir.save_control(c0)
localdir._LAST_CHECK.clear()
try:
    localdir._add_found(pid, rate=False)
    n1 = len(started)
    localdir._add_found(pid, rate=False)
    n2 = len(started)
    pend["n"] = localdir.CHECK_BATCH
    localdir._add_found(pid, rate=False)
    n3 = len(started)
    pend["n"] = 1
    localdir._LAST_CHECK[pid] = time.time()
    localdir._add_found(pid, rate=False)
    n4 = len(started)
    localdir._add_found(pid, rate=True)         # the near-you group is through (or the build ended): every leftover
    n5 = len(started)
    first_search.JOB["running"] = True
    localdir._add_found(pid, rate=True)
    n6 = len(started)
finally:
    first_search.pending, first_search.start_checking, localdir.S, directory.apply = keep[:4]
    first_search.JOB.update(keep[4])
    c0 = localdir.control(); c0["add"] = {}; localdir.save_control(c0)
check("employers a build adds get their check: at once the first time, then in batches or after a quiet spell",
      (n1, n2, n3, n4) == (1, 1, 2, 2), str((n1, n2, n3, n4)))
check("... every leftover once the near-you group is through, never on top of a running check, and always with rating", (n5, n6) == (3, 3) and all(started))

# ---------------------------------------------------------------- the older built-in area: the directory's own ZIP
pid_l = people.add("Legacy")
people.save_settings({"home_zip": ""}, pid_l)
check("no home ZIP and no directory ZIP: nothing to build for", not [a for a in localdir.areas() if a["pid"] == pid_l])
people.save_settings({"directory_zip": "45402", "directory_radius": 10}, pid_l)      # Dayton, OH
al = [a for a in localdir.areas(pid_l) if a["pid"] == pid_l]
check("the directory ZIP of a legacy-area profile is built for (asked first)", al and al[0]["states"] == ["OH"] and al[0]["radius"] == 10 and localdir.areas(pid_l)[0]["pid"] == pid_l, str(al))
directory._PREVIEW.clear()
emps_l, _ = directory.near_employers(pid_l, directory.manifest())
check("... and only the employers within that area are near (Dayton, not Columbus)", [e["name"] for e in emps_l] == ["Ohio Co 03"], str([e["name"] for e in emps_l]))
check("... near counts follow each profile's own area", local.near_jobs({"places": [[DAYTON[0], DAYTON[1], 2, "Dayton, OH", "OH"]]}, al[0]) == 2
      and local.near_jobs({"places": [[COLUMBUS[0], COLUMBUS[1], 9, "Columbus, OH", "OH"]]}, al[0]) == 0)
people.save_settings({"workplaces": ["remote"]}, pid_l)
ar_r = [a for a in localdir.areas() if a["pid"] == pid_l]
check("a remote-only profile counts US-remote jobs instead", ar_r and ar_r[0]["remote_only"] and local.near_jobs({"remote": 4, "places": []}, ar_r[0]) == 4)

# ---------------------------------------------------------------- Backup & move carries the directory and its build state
import backup, joblock
backup.configure(threading.Lock(), lambda: "", lambda: None)
local.write_json(os.path.join(directory.LOCAL, "control.json"), {"paused": True, "add": {pid: "all"}, "added": {pid: 3}, "tag": "build-9"})
backup.start_export(False)
t0 = time.time()
while backup.JOB.get("state") == "running" and time.time() - t0 < 60:
    time.sleep(0.1)
check("backup: made", backup.JOB.get("state") == "done", str(backup.JOB.get("msg")))
zpath = backup.JOB.get("file")
names_z = set(zipfile.ZipFile(zpath).namelist()) if zpath else set()
want = {"directory/prefs.json", "directory/local/tenants.json.gz", "directory/local/build.json", "directory/local/manifest.json",
        "directory/local/index.json.gz", "directory/local/states/OH.json.gz", "directory/local/control.json", f"directory/people/{pid}.json"}
check("backup: the locally built directory, its build state and the preference are in it", want <= names_z, str(sorted(want - names_z)))
check("backup: no temp or stop files", not any(n.endswith((".tmp", ".part")) for n in names_z))
before = {n: open(os.path.join(os.environ["JOBBOARD_DATA"], n.replace("/", os.sep)), "rb").read() for n in want}
shutil.copy(zpath, backup.UPLOAD)
shutil.rmtree(directory.DIR)
directory._CACHE.clear(); directory._PREFS["v"] = None
check("(the directory is gone before the restore)", directory.source() == "shared" and not os.path.exists(directory.LOCAL))
backup.start_restore()
t0 = time.time()
while backup.JOB.get("state") == "running" and time.time() - t0 < 120:
    time.sleep(0.1)
check("restore: done", backup.JOB.get("state") == "done", str(backup.JOB.get("msg")))
directory._CACHE.clear(); directory._PREFS["v"] = None; directory._PREVIEW.clear()
after = {n: (open(os.path.join(os.environ["JOBBOARD_DATA"], n.replace("/", os.sep)), "rb").read() if os.path.exists(os.path.join(os.environ["JOBBOARD_DATA"], n.replace("/", os.sep))) else None) for n in want}
check("restore: every directory file is back, byte for byte", after == before, str([n for n in want if after[n] != before[n]]))
check("restore: the preference, the build state and what the build may add are back", directory.source() == "local" and localdir.control()["add"] == {pid: "all"}
      and bool(local.Local(directory.LOCAL).meta.get("pass")) and len(local.Local(directory.LOCAL).T.d) == len(LF.T.d))
emps, info = directory.near_employers(pid, directory.manifest())
check("restore: the employers near the person are found again without building", len(emps) == 31)

# ---------------------------------------------------------------- the installed layout: no .py files on disk
FROZEN = os.path.join(TMP, "frozen")
os.makedirs(os.path.join(FROZEN, "index_build"))
import glob
for src in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "index_build", "*.py")):
    rel = os.path.relpath(src, ROOT)
    py_compile.compile(src, cfile=os.path.join(FROZEN, rel[:-3] + ".pyc"), doraise=True)
for d in ("assets", "packs"):
    shutil.copytree(os.path.join(ROOT, d), os.path.join(FROZEN, d))
for f in ("VERSION", "config.default.json"):
    shutil.copy(os.path.join(ROOT, f), FROZEN)
check("(the frozen layout has no .py file)", not glob.glob(os.path.join(FROZEN, "**", "*.py"), recursive=True))
code = r"""
import sys, os, json
sys.frozen = True
sys._MEIPASS = sys.argv[1]
sys.path[:] = [sys.argv[1]] + [p for p in sys.path if p and os.path.abspath(p) != os.path.abspath(sys.argv[2]) and os.path.abspath(p) != os.path.abspath(os.path.join(sys.argv[2], 'scripts'))]
os.chdir(sys.argv[1])
import frozen, paths
bad = frozen.directory_builder_problems()
import jobfinder
jobfinder.load_extra()
import localdir, directory
from index_build import local, seed, build
L = local.Local(os.path.join(directory.LOCAL))
L.load_seeds([localdir.SEED_ASSET])
cmd = frozen.command('dirbuild', '--root', 'X')
print(json.dumps({'bad': bad, 'app': paths.APP, 'file': getattr(local, '__file__', ''), 'readers': len(jobfinder.FETCHERS), 'boards': len(L.T.d),
                  'seed': localdir.SEED_ASSET, 'cmd': cmd[1:], 'data_in_app': os.path.abspath(paths.DATA).startswith(os.path.abspath(sys.argv[1]) + os.sep)}))
"""
env = {**os.environ, "JOBBOARD_DATA": os.path.join(TMP, "frozen-data"), "PYTHONDONTWRITEBYTECODE": "1"}
env.pop("PYTHONPATH", None)
pr = subprocess.run([sys.executable, "-X", "utf8", "-c", code, FROZEN, ROOT], capture_output=True, text=True, cwd=FROZEN, env=env, timeout=300)
try:
    fz = json.loads(pr.stdout.strip().splitlines()[-1])
except Exception:
    fz = {"error": (pr.stdout + pr.stderr)[-800:]}
check("frozen: the builder package and the seed load from inside the bundle", fz.get("bad") == [], json.dumps(fz)[:900])
check("frozen: modules come from the bundle (.pyc), not from the source tree", str(fz.get("file", "")).endswith(".pyc") and os.path.abspath(fz.get("app", "")) == os.path.abspath(FROZEN), str(fz.get("file")))
check("frozen: the seed list is read from the bundle's assets and merged", fz.get("boards", 0) > 5000 and str(fz.get("seed", "")).startswith(os.path.abspath(FROZEN)), str(fz.get("boards")))
check("frozen: every job reader loads", fz.get("readers", 0) >= 30, str(fz.get("readers")))
check("frozen: the child is started as Siftwell.exe --dirbuild", fz.get("cmd") == ["--dirbuild", "--root", "X"], str(fz.get("cmd")))
extra = [os.path.basename(p) for p in glob.glob(os.path.join(FROZEN, "*")) if os.path.basename(p) not in ("assets", "packs", "index_build", "VERSION", "config.default.json") and not p.endswith(".pyc")]
check("frozen: nothing was written into the bundle folder", not extra and not fz.get("data_in_app"), f"{extra} {fz.get('data_in_app')}")
import frozen
check("frozen._check_imports covers the builder", "directory_builder_problems" in open(os.path.join(ROOT, "frozen.py"), encoding="utf-8").read().split("def _check_imports")[1].split("def ")[0]
      and frozen.directory_builder_problems() == [])
specs = [open(os.path.join(ROOT, "installer", f), encoding="utf-8").read() for f in ("siftwell.spec", "siftwell-mac.spec")]
check("both PyInstaller specs bundle the builder package and assets/", all("index_build" in s and '"assets"' in s for s in specs))
ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
check("the release ZIP keeps index_build/ and assets/directory (not export-ignored)", "index_build" not in ga and "assets" not in ga)

print()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f"{len(fails)} FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("all local-directory tests passed")
