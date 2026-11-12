"""Offline tests for the first-search experience: the employer directory's preview / "top N" / undo, the honest
offline fallback (starter list only on the first search, pruned starters never re-added, sensible order), the staged
check's counters (one total, never going back, whatever is added or pruned meanwhile), its plain progress line, a
chunk that doesn't wait for a slow employer, time estimates from real numbers, and the Backup & move round trip
(directory memory + Claude usage history).

Run: SIFTWELL_FORBID_CLAUDE=1 python -X utf8 scripts/test_first_search.py   (no network; a temp data folder)"""
import datetime as dt, gzip, hashlib, json, os, shutil, sys, tempfile, threading, time
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
TMP = tempfile.mkdtemp(prefix="first_search_test_")
os.environ["JOBBOARD_DATA"] = os.path.join(TMP, "data")
INDEX = os.path.join(TMP, "index")
GOOD_URL = "file:///" + INDEX.replace("\\", "/")
os.environ["SIFTWELL_DIRECTORY_URL"] = GOOD_URL

import catalog, directory, first_search, people

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- a fake server module (no processes, no network)
class FakeServer:
    """What first_search needs from server.py. run_update "checks" each company in turn (record_fetch), slowly enough
    to watch; names in HANG never finish until stop_update() is called."""
    def __init__(self):
        self.lock = threading.RLock()
        self.state = {"running": False, "phase": "fetch", "done": 0, "total": 0, "exit": None, "lines": []}
        self.RERATE = {}
        self.HANG, self.PER, self.log, self.recomputes, self._stop = set(), 0.01, [], [], threading.Event()
        self.runs, self.on_fetch = [], None

    def claim_update(self):
        with self.lock:
            if self.state["running"]:
                return False
            self.state["running"] = True
            return True

    def stop_update(self):
        self._stop.set()
        return True

    def run_update(self, only=None, defer_running=False, flags=(), quiet=False, names=None):
        chunk = [n for n in (only or "").split(",") if n]
        self.runs.append((chunk, list(flags)))
        self._stop.clear()
        with self.lock:
            self.state.update(running=True, phase="fetch", done=0, total=len(chunk), exit=None)
        rc = 0
        todo = [n for n in chunk if n not in self.HANG] + [n for n in chunk if n in self.HANG]
        for n in todo:
            if n in self.HANG:
                self._stop.wait(30)
            if self._stop.is_set():
                rc = 1
                break
            time.sleep(self.PER)
            with catalog.db() as con:
                catalog.record_fetch(n, {"status": "ok", "raw_jobs": 1, "secs": 2},
                                     [{"id": f"{n}::a", "company": n, "title": "Nurse", "locations": ["Columbus, OH"], "salary_max": None,
                                       "workplace": "", "remote_strict": False, "remote_bare": False, "local_unnamed": False, "desc": "x"}], con)
            with self.lock:
                self.state["done"] += 1
            if self.on_fetch:
                self.on_fetch(n)
        with self.lock:
            self.state.update(running=False, exit=rc)

    def _actlog(self, action, pid=None, detail=""):
        self.log.append((action, detail))

    def request_recompute(self, pids=None, auto_rate=True):
        self.recomputes.append(pids)

    def board_counts(self, pid):
        return {"jobs": 0}


S = FakeServer()
first_search.configure(S)


# ---------------------------------------------------------------- a small published directory
def put(rel, obj):
    p = os.path.join(INDEX, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = gzip.compress(json.dumps(obj).encode(), mtime=0)
    open(p, "wb").write(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
def emp(i, lat=39.96, lon=-83.0, n=None, **kw):
    e = {"n": f"Employer {i:04d}", "c": {"ats": "greenhouse", "token": f"emp{i:04d}"}, "u": f"https://job-boards.greenhouse.io/emp{i:04d}",
         "j": 10, "r": 0, "p": [[lat, lon, n if n is not None else 1 + i, "Columbus, OH"]], "s": "2026-11-10", "ps": ["OH"]}
    e.update(kw)
    return e
def publish(emps):
    man = {"v": 1, "built": dt.datetime.now().isoformat(), "states": {}, "jobs": {}, "sources": {}}
    man["states"]["OH"] = put("states/OH.json.gz", {"v": 1, "state": "OH", "employers": emps})
    json.dump(man, open(os.path.join(INDEX, "manifest.json"), "w"))
    directory.manifest(refresh=True)
def mine(pid):
    return {n for n, s in catalog.sets_map().items() if f"near-{pid}" in s}

EMPS = [emp(i) for i in range(300)] + [emp(900, 41.5, -81.7, 99)]      # 300 near Columbus (1..300 openings), one in Cleveland
publish(EMPS)
pid = people.add("Nia")
people.save_settings({"home_zip": "43215", "radius_miles": 35}, pid=pid)

# ---------------------------------------------------------------- preview: nothing is added blindly
before = len(catalog.companies())
pv = directory.preview(pid)
check("preview counts the employers and their openings", pv["available"] and pv["new"] == 300 and pv["jobs"] == sum(range(1, 301)))
check("preview changes nothing", len(catalog.companies()) == before and not mine(pid) and not directory.record(pid))
opts = {o["limit"]: o for o in pv["options"]}
check("preview offers the top N and all", list(opts) == [100, 250, None] and opts[None]["employers"] == 300 and opts[100]["employers"] == 100)
check("the top 100 are the ones with the most openings", opts[100]["jobs"] == sum(range(201, 301)))
check("estimates grow with the choice and are worded", opts[100]["first_minutes"] <= opts[None]["first_minutes"]
      and opts[100]["daily_minutes"] <= opts[None]["daily_minutes"] and opts[None]["first_text"].startswith("about "))
check("the estimate before adding is given too", "minutes" in pv["daily_before"])

# ---------------------------------------------------------------- the top N, then the rest, then undo
r = directory.apply(pid, limit=100)
m = mine(pid)
check("limit adds exactly the top N", len(r["added"]) == 100 and len(m) == 100 and "Employer 0299" in m and "Employer 0200" in m and "Employer 0199" not in m)
check("the rest are not marked as offered", directory.preview(pid)["new"] == 200)
check("a weekly refresh adds nothing for someone who chose the top N", directory.apply(pid, weekly=True)["added"] == [] and len(mine(pid)) == 100)
catalog.remove_company("Employer 0250")                                  # taken off by hand
r2 = directory.apply(pid)
check("adding all later adds the remainder", len(r2["added"]) == 200 and len(mine(pid)) == 299)
check("an employer removed by hand stays removed", "Employer 0250" not in mine(pid))
last = directory.last_batch(pid)
check("the last batch is remembered", last and last["employers"] == 200)
u = directory.undo(pid)
check("undo removes exactly what the last add brought", u["removed"] == 200 and len(mine(pid)) == 99 and "Employer 0100" not in {c["name"] for c in catalog.companies()})
check("... and they can be added again", directory.preview(pid)["new"] == 200)
check("... but the hand-removed one still stays off", "Employer 0250" not in [x["name"] for x in directory.apply(pid, dry=True)["new"]])
u2 = directory.undo(pid)
check("undo again takes back the batch before", u2["removed"] == 99 and not mine(pid))
check("nothing left to undo", directory.undo(pid)["removed"] == 0)

# an employer two profiles share is only unlinked, never removed
pid_b = people.add("Omar")
people.save_settings({"home_zip": "43215", "radius_miles": 35}, pid=pid_b)
directory.apply(pid_b, limit=5)
directory.apply(pid, limit=5)
check("a shared employer is linked, not duplicated", mine(pid) == mine(pid_b) and len(mine(pid)) == 5)
directory.undo(pid)
check("undo for one profile leaves the other's list alone", not mine(pid) and len(mine(pid_b)) == 5)
directory.undo(pid_b)

# employers that were given a better name at their first fetch are still taken back (found by their job board)
r = directory.apply(pid, limit=20)
first20 = sorted(mine(pid))
check("20 added; the count offered for undo is 20", len(first20) == 20 and directory.last_batch(pid)["employers"] == 20)
def give_listing(name):
    c = next(x for x in catalog.companies() if x["name"] == name)
    with catalog.db() as con:
        catalog.put_listing(con, {"id": f"{name}::1", "company": name, "title": "Clerk", "url": "https://example.com/1", "locations": ["Columbus, OH"]},
                            first_seen="2026-11-01", last_seen="2026-11-01")
for i, nm in enumerate(first20[:6]):
    give_listing(nm)
    check(f"renamed like a first fetch does ({nm})", catalog.rename_company(nm, f"Better Name {i}"))
rec = directory.record(pid)
check("the batch follows the new names", {f"Better Name {i}" for i in range(6)} <= set(rec["batches"][-1]["added"] + rec["batches"][-1]["linked"]))
check("...the count offered for undo is still 20", directory.last_batch(pid)["employers"] == 20, str(directory.last_batch(pid)))
# a record written before boards were stored and before names were kept up to date: old names only
old_rec = directory.record(pid)
old_rec["batches"][-1].pop("items", None)
old_rec["batches"][-1]["added"] = [first20[i] if x == f"Better Name {i}" else x for x in old_rec["batches"][-1]["added"] for i in [next((k for k in range(6) if x == f"Better Name {k}"), 0)]]
directory._save_record(pid, old_rec)
check("...also for a batch that only knows the first names (found by what their listing ids start with)", directory.last_batch(pid)["employers"] == 20,
      str(directory.last_batch(pid)))
u = directory.undo(pid)
check("undo takes back all 20, the renamed ones included", u["removed"] == 20 and not mine(pid) and not [c for c in catalog.companies() if c["name"].startswith("Better Name")],
      str((u, len(mine(pid)))))

# ---------------------------------------------------------------- time estimates come from real numbers
cos_fast = [{"ats": "greenhouse", "_fetch": {"secs": 12}} for _ in range(120)]
check("estimate: measured seconds over the lanes", first_search.fetch_minutes(cos_fast) == round((120 * 12 / 12 + 45 + 0.04 * 120) / 60))
cos_wd = [{"ats": "workday", "_fetch": {"secs": 60}} for _ in range(40)]
check("estimate: Workday's narrow lane dominates", first_search.fetch_minutes(cos_fast + cos_wd) >= 10)
check("estimate: more employers never take less", first_search.fetch_minutes(cos_fast * 10) > first_search.fetch_minutes(cos_fast))
check("estimate: a slow employer counts for no more than the regular per-employer budget (it is cut there and finished at the end)",
      first_search.employer_secs({"ats": "workday", "_fetch": {"secs": 199}}) == first_search.REGULAR_CAP)
# the re-test's numbers: a first check of 250 employers took about 10 minutes (setup said "about 40"), 10 for a
# remote-only profile about 4.5 at most
first_search._AVG["v"] = {}
mix250 = [{"ats": "workday"}] * 70 + [{"ats": "icims"}] * 30 + [{"ats": "oracle"}] * 8 + [{"ats": "adp"}] * 60 + [{"ats": "greenhouse"}] * 40 + [{"ats": "ukg"}] * 42
m250 = first_search.fetch_minutes(mix250, first=True)
check(f"estimate before anything is measured: a first check of 250 employers is about 10 minutes ({m250}), said as a range",
      8 <= m250 <= 13 and "–" in first_search.minutes_text(m250),
      str((m250, first_search.minutes_text(m250))))
m10 = first_search.fetch_minutes([{"ats": "workday"}] * 4 + [{"ats": "greenhouse"}] * 6, first=True)
check(f"...and of 10 employers a minute or two ({m10})", 1 <= m10 <= 3, str(m10))
first_search._AVG["v"] = None
check("estimate wording is always a range", [first_search.minutes_text(x) for x in (0, 1, 4, 7, 10, 23, 44, 60, 95, 150)] ==
      ["under a minute", "about 1–2 minutes", "about 4–6 minutes", "about 7–11 minutes", "about 10–15 minutes", "about 25–35 minutes",
       "about 45 minutes to 1 hour", "about 1–1½ hours", "about 1½–2½ hours", "about 2½–4 hours"],
      str([first_search.minutes_text(x) for x in (0, 1, 4, 7, 10, 23, 44, 60, 95, 150)]))
first_search._EST.clear()
e = first_search.estimates(pid)
check("estimates: mine and all, from the real list", e["all"]["companies"] == len(catalog.companies()) and e["mine"]["companies"] == 0 and e["profiles"] == 2)

# ---------------------------------------------------------------- the staged check: counters and the one line
directory.apply(pid, limit=100)
first_search._CACHE.clear()
st0 = first_search.check_status(pid)
check("before the check: 0 of 100", (st0["done"], st0["total"], st0["pending"], st0["running"]) == (0, 100, 100, False))

seen, lines = [], []
def sample():
    while not stop_sampling.is_set():
        c = first_search.check_status(pid)
        if c["running"] and c["mine"]:
            seen.append((c["done"], c["total"]))
            lines.append(first_search.progress(pid)["line"])
        time.sleep(0.004)

added_mid = {"done": False}
def on_fetch(name):
    # mid-run: employers are added (the total may grow, done must not jump) and a starter prune runs (nothing may drop)
    if not added_mid["done"] and S.state["done"] >= 5 and len(S.runs) >= 2:
        added_mid["done"] = True
        directory.apply(pid, limit=20)
        directory.prune_starters(pid)
        catalog.remove_company("Employer 0201")          # one not yet checked disappears mid-check

S.on_fetch = on_fetch
first_search.CHUNK_FIRST, first_search.CHUNK = 10, 25
ok, err = first_search.start_checking(pid, rate=False)
check("the check starts", ok, str(err))
stop_sampling = threading.Event()
th = threading.Thread(target=sample, daemon=True); th.start()
t0 = time.time()
while first_search.JOB["running"] and time.time() - t0 < 60:
    time.sleep(0.05)
stop_sampling.set(); th.join(2)
check("the check finishes", not first_search.JOB["running"] and not first_search.JOB["error"], str(first_search.JOB.get("error")))
dones, totals = [d for d, _ in seen], [t for _, t in seen]
check("done never goes back", all(b >= a for a, b in zip(dones, dones[1:])), str(dones[:40]))
check("the total never shrinks", all(b >= a for a, b in zip(totals, totals[1:])), str(sorted(set(totals))))
check("the total grows only by the employers added meanwhile", sorted(set(totals)) == [100, 120], str(sorted(set(totals))))
check("done never exceeds the total", all(d <= t for d, t in seen))
check("done doesn't jump when employers are added", max(b - a for a, b in zip(dones, dones[1:])) <= 12, str(max(b - a for a, b in zip(dones, dones[1:]))))
lines = [l for l in lines if l]          # (a sample taken just as the run ended)
check("never 0 of 0", not any(t == 0 for _, t in seen) and not any(" of 0 " in l for l in lines))
check("one plain line, no raw output", all(l.startswith(("Checking employers: ", "Almost done", "Pausing")) for l in lines) and not any("raw=" in l or "kept=" in l for l in lines),
      str(set(l[:30] for l in lines)))
check("the line carries the same numbers", any(l == f"Checking employers: {d:,} of {t:,} · your board fills in as we go" for (d, t), l in zip(seen, lines)))
fin = [d for a, d in S.log if a == "update finished"]
checked_now = sum(1 for c in catalog.companies() if (c["_fetch"] or {}).get("at") and f"near-{pid}" in (c.get("sets") or []))
check("the log says how many were really checked", fin and fin[-1] == f"Checking employers: {checked_now} checked this time", f"{fin} vs {checked_now}")
first_search._CACHE.clear()
st1 = first_search.check_status(pid)
check("after the check everything is done and the numbers agree", st1["pending"] == 0 and st1["done"] == st1["total"] == checked_now, str(st1))
check("chunks went most openings first", S.runs[0][0][0] == "Employer 0299" and len(S.runs[0][0]) == 10)
p = first_search.progress(pid)
check("idle: no progress line", p["active"] is False and p["line"] == "")

# a regular Find new jobs: the same kind of plain line
with S.lock:
    S.state.update(running=True, phase="fetch", done=12, total=40)
check("Find new jobs line", first_search.progress(pid)["line"] == "Finding new jobs: 12 of 40 employers")
with S.lock:
    S.state.update(phase="ai")
check("rating line has no model names", "Haiku" not in first_search.progress(pid)["line"] and first_search.progress(pid)["kind"] == "rate")
with S.lock:
    S.state.update(running=False)

# ---------------------------------------------------------------- a slow employer doesn't hold a chunk up
directory.apply(pid, limit=60)          # 60 more to check
S.runs.clear(); S.on_fetch = None
S.HANG = {"Employer 0175"}              # in the first chunk; never finishes by itself
first_search.STALL_SECS, first_search.SLOW_STALL_SECS, first_search.STALL_LEFT = 0.6, 2.0, 3
first_search._CACHE.clear()
ok, err = first_search.start_checking(pid, rate=False)
t0 = time.time(); first_cut = None
while first_search.JOB["running"] and time.time() - t0 < 60:
    if first_cut is None and len(S.runs) >= 2:
        first_cut = time.time() - t0
    time.sleep(0.02)
took = time.time() - t0
check("the next chunk starts although one employer is still being read", first_cut is not None and first_cut < 9, str(first_cut))
check("the slow employer is tried again at the very end, alone", S.runs[-1][0] == ["Employer 0175"], str(S.runs[-1][0]))
check("... and is left for the next Find new jobs when it still doesn't finish", "took too long" in (first_search.JOB["note"] or "") and took < 30, first_search.JOB["note"])
first_search._CACHE.clear()
st2 = first_search.check_status(pid)
check("everything else was checked", st2["pending"] == 1, str(st2))
check("the boards are rebuilt after an ended fetch", [pid] in S.recomputes)
S.HANG = set()

# pause keeps the numbers and offers Continue
directory.apply(pid, limit=40)
S.PER = 0.05; S.runs.clear()
first_search._CACHE.clear()
first_search.start_checking(pid, rate=False)
time.sleep(0.5)
first_search.pause(pid)
t0 = time.time()
while first_search.JOB["running"] and time.time() - t0 < 30:
    time.sleep(0.05)
first_search._CACHE.clear()
st3 = first_search.check_status(pid)
check("pause stops the check and keeps what was done", st3["paused"] and 0 < st3["pending"] < 41 and st3["done"] + st3["pending"] == st3["total"], str(st3))
S.PER = 0.002
first_search.start_checking(pid, rate=False)
t0 = time.time()
while first_search.JOB["running"] and time.time() - t0 < 30:
    time.sleep(0.05)
first_search._CACHE.clear()
check("Continue checking does the rest", first_search.check_status(pid)["pending"] == 0)

# ---------------------------------------------------------------- why the board is empty, said plainly
w = first_search.why_empty(pid)
check("why_empty names the numbers and the search", "open jobs" in w and "within 35 miles of" in w and "none matched your search" in w, w)
check("no job title yet is known", first_search.has_titles(pid) is False)
pid_c = people.add("Empty")
check("why_empty: nobody to check", "isn’t watching any employers" in first_search.why_empty(pid_c))

# ---------------------------------------------------------------- the directory can't be reached
pid_o = people.add("Offline")
people.save_settings({"home_zip": "43215", "radius_miles": 35}, pid=pid_o)
shutil.rmtree(directory.DIR + "_keep", ignore_errors=True)
os.makedirs(directory.DIR + "_keep")
for n in ("manifest.json", "states", "jobs"):               # no cache at all, and nothing to download
    src = os.path.join(directory.DIR, n)
    if os.path.exists(src):
        shutil.move(src, os.path.join(directory.DIR + "_keep", n))
os.environ["SIFTWELL_DIRECTORY_URL"] = "file:///" + os.path.join(TMP, "nowhere").replace("\\", "/")
n_before = len(catalog.companies())
r = directory.apply(pid_o)
check("Add employers near me reports the failure when the directory is unreachable", r["available"] is False and r["reason"] == "offline"
      and len(catalog.companies()) == n_before and not mine(pid_o))
pvo = directory.preview(pid_o, refresh=True)
check("... and so does the preview", pvo["available"] is False and pvo["reason"] == "offline")
# one shipped employer is known (from an earlier directory entry in the catalog) to hire in Ohio
packs = directory.pack_employers()
known = packs[len(packs) // 2]
catalog.save_company({"name": known["name"], "tier": "national", "sector": "x", **known["cfg"], "sets": ["own-" + pid_b],
                      "dir": {"all": False, "st": ["OH", "TX"], "lab": "", "p": []}})
r = directory.apply(pid_o, starters_ok=True, first=True)
check("the first search falls back to the shipped starter list, and says so", r["available"] and r["offline"] and r["pack_starters"] > 100
      and directory.record(pid_o).get("offline") is True)
first_search._CACHE.clear()
check("the pages are told (dir_offline)", first_search.check_status(pid_o)["dir_offline"] is True and directory.status(pid_o)["offline_start"] is True)
order = first_search.due(pid_o)
check("starters: the one known to hire in the person's state comes first", order[0] == known["name"], order[:3])
jobs_of = {p["name"]: p["jobs"] for p in packs}
rest = [n for n in order[1:] if n in jobs_of]
check("... then the biggest employers, not the alphabet", jobs_of[rest[0]] == max(jobs_of[n] for n in rest) and jobs_of[rest[0]] > jobs_of[rest[-1]]
      and rest != sorted(rest, key=str.lower), str(rest[:4]))
# a starter that turned out not to hire nearby is pruned and never added again by this path
victim = order[1]
with catalog.db() as con:
    catalog.record_fetch(victim, {"status": "ok", "raw_jobs": 1, "secs": 1},
                         [{"id": f"{victim}::a", "company": victim, "title": "Clerk", "locations": ["Austin, TX"], "salary_max": None, "workplace": "",
                           "remote_strict": False, "remote_bare": False, "local_unnamed": False, "desc": "x"}], con)
dropped = directory.prune_starters(pid_o)
check("a starter with no jobs nearby is pruned", dropped == [victim])
r = directory.apply(pid_o, starters_ok=True, first=True)
check("a pruned starter is never re-added", victim not in r["added"] + r["linked"] and victim not in mine(pid_o))
r = directory.apply(pid_o)
check("pressing Add again while unreachable adds nothing", r["available"] is False and victim not in mine(pid_o))
# back online: "Try the directory again"
shutil.rmtree(directory.DIR + "_keep")
os.environ["SIFTWELL_DIRECTORY_URL"] = GOOD_URL
directory.manifest(refresh=True)
r = directory.apply(pid_o, limit=10)
check("Try the directory again brings the real nearby employers", r["available"] and not r["offline"] and len(r["added"]) + len(r["linked"]) == 10)
check("... and the offline note goes away", not directory.record(pid_o).get("offline") and directory.status(pid_o)["offline_start"] is False)
check("... without re-adding the pruned starter", victim not in mine(pid_o))

# ---------------------------------------------------------------- an area just for the directory (no home ZIP)
pid_l = people.add("Legacy")
check("no home ZIP: the directory has nowhere to look", directory.area(pid_l) is None and directory.status(pid_l)["own_area"] is True)
people.save_settings({"directory_zip": "43215", "directory_radius": 25}, pid=pid_l)
a = directory.area(pid_l)
check("its own area works without touching the job filter", a is not None and a[3] == 25 and people.settings(pid_l)["home_zip"] == "")
check("... and the preview uses it", directory.preview(pid_l)["available"] and directory.preview(pid_l)["radius"] == 25)

# ---------------------------------------------------------------- Backup & move keeps the directory memory and usage history
import backup, claude_usage, joblock
claude_usage.record("Match ratings", "test-model", {"input_tokens": 10, "output_tokens": 5}, 3, stub=True)
usage_file = os.path.join(os.environ["JOBBOARD_DATA"], "claude_usage.jsonl")
check("there is a usage history to keep", os.path.exists(usage_file))
backup.configure(threading.RLock(), lambda: "", lambda: None)
def snapshot():
    recs = {u: directory.record(u) for u in sorted(directory.users())}
    return {"users": sorted(directory.users()), "records": recs, "usage": open(usage_file, encoding="utf-8").read() if os.path.exists(usage_file) else None,
            "companies": sorted((c["name"], tuple(sorted(c.get("sets") or []))) for c in catalog.companies()),
            "cached": sorted(os.listdir(os.path.join(directory.DIR, "states")))}
want = snapshot()
backup.JOB.clear(); backup.JOB.update(kind="export", state="running")
backup._build_export(False)
check("export finishes", backup.JOB.get("state") == "done", str(backup.JOB.get("msg")))
import zipfile
names = set(zipfile.ZipFile(backup.JOB["file"]).namelist())
check("the backup holds the directory memory and the usage history", f"directory/people/{pid}.json" in names and "claude_usage.jsonl" in names
      and "directory/manifest.json" in names and any(n.startswith("directory/states/") for n in names))
shutil.copyfile(backup.JOB["file"], backup.UPLOAD)
# everything changes after the export ...
directory.undo(pid_o); directory.apply(pid)
os.remove(usage_file)
shutil.rmtree(os.path.join(directory.DIR, "people"))
check("(the state really changed)", snapshot() != want and directory.users() == [])
backup.JOB.clear(); backup.JOB.update(kind="restore", state="running")
backup._do_restore()
check("restore finishes", backup.JOB.get("state") == "done", str(backup.JOB.get("msg")))
got = snapshot()
check("after export and restore the state is identical", got == want,
      str({k: (got[k] == want[k]) for k in want}))
check("directory.users() is back, so weekly additions carry on", sorted(directory.users()) == want["users"] and len(want["users"]) >= 3)
check("the offered / removed memory is back: a removed employer stays off", "Employer 0250" not in [x["name"] for x in directory.apply(pid, dry=True)["new"]])

print()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f"{len(fails)} FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("all passed")
