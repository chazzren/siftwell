"""Build my own directory: the employer directory, read on this computer instead of downloaded.

The weekly build on GitHub (build.py) stays the fast way to get the directory. This module does the same reading from
the person's own computer, so the app keeps working if that project ever stops: no LLM, no key, no account.

What it starts from: the seed list (seed.py: every job board the builder knew when the release was made, with
last-known names and states as hints), plus the shipped starter packs. What it does: reads each board's public feed
with the SAME code the weekly build uses (build.read_tenant -> readers.read: robots.txt, pacing, one request at a
time per host, the per-system lanes build.LANES, the per-board limits readers.CAP / GENERIC_SECS) and writes the
SAME files (build.write_states), under DATA/directory/local/:

  tenants.json.gz     every board and what was read (the builder's own state format)
  journal.jsonl       one line per board read since the state was last saved: nothing is lost on Pause, a crash or
                      a restart (it is replayed when the build opens)
  build.json          the pass under way, measured seconds per job system, what discovery did and when
  states/<ST>.json.gz, states/remote.json.gz, manifest.json, index.json.gz
                      the directory itself, in the published per-state format; directory.py merges it with the
                      downloaded one per employer (the newer reading wins; index.json.gz says when each board was
                      last read here, so an employer that stopped hiring in a state leaves it)
  progress.json       what the running build is doing (read by localdir.py for the one progress line)
  job.json, stop      written by the app: the areas to build for / "stop now"

Being a good guest: every request is paced per provider (net.install: about one request a second and one or two
connections for a shared job system; only listing pages are read, never a page per posting), so the build is slow on
purpose for each provider and fast only because many different providers are read side by side. On top, a job system that starts refusing connections (BREAK_AFTER
failures in a row on one host: some systems throttle a home connection that asks for many boards) is left alone for
COOL_SECS, then twice as long, and after COOL_MAX rests its remaining boards are left for another day. Those boards
are not counted as failed.

Order (so it is useful in minutes): boards last seen hiring in the states around the people here (most known jobs
there first; for remote-only searches: most US-remote jobs), then boards nobody has a state for, then boards last seen
elsewhere, then boards last seen with no open jobs. The area's state files are rewritten about once a minute while it
runs, so "Near me" fills in as it goes; everything else every quarter of an hour and at the end.

A pass = every board tried once. Pause / a restart carry on where the pass stopped (a board's "lt" is when it was
last tried here). After a pass, the weekly upkeep (mode "weekly") re-reads the boards known near the people here and
then the boards not tried for the longest, for at most WEEKLY_MINUTES, and waits while a job fetch holds the job lock.

Optional (off unless the person turns it on): discover() looks for boards that aren't on the list yet in the Common
Crawl URL index, a few index blocks per job system, slowly (CC_GAP seconds between requests), and not again for
DISCOVER_DAYS: many copies of Siftwell hitting a free public service should stay unnoticeable.

Run as a child process of the server (localdir.py starts `localdir.py --build`): python -m is not used, so it works
the same from source and inside an installed build."""
import argparse, collections, concurrent.futures as cf, datetime as dt, hashlib, json, os, re, sys, threading, time, types
import urllib.parse

from . import build, net, seed as seedmod, systems

WRITE_FIRST = 20        # seconds after the start that the area's state files are first rewritten
WRITE_SECS = 60         # ... and then this often, when something in them changed
ALL_WRITE_SECS = 900    # every changed state file (and the index of what was read when)
WEEKLY_MINUTES = 40     # the weekly upkeep's time box
DISCOVER_DAYS = 30      # a Common Crawl prefix is not looked through again for this long
CC_BLOCKS = 12          # index blocks per job-system prefix (the weekly build on GitHub reads up to 400)
CC_GAP = 3.0            # seconds between requests to Common Crawl
WD_SITES = 300          # Workday tenants whose robots.txt (list of career sites) is read after a discovery
TITLES = 1500           # board pages asked for the employer's name per run, at most
DEFAULT_SECS = 3.0      # one board's read when nothing has been measured for its system
MEASURED_MIN = 8        # reads of a system before its own measured average is used
HEAVY = 1500            # a board last seen with this many open jobs is read after the rest of its group
REQS_PER_BOARD = 1.5    # requests one board takes on average, for estimates before anything was measured here
BREAK_AFTER = 6         # this many connection failures in a row on one host: stop asking it for a while
COOL_SECS = 120         # ... for this long the first time, twice as long each time after
COOL_MAX = 4            # ... and after this many rests in a row its boards are left for another day
RETRIES = 3             # times one board is put back in line because its host (not the board) was failing
HOST_QUIET = "the job system stopped answering; this board is tried again another day"
TRANSPORT = re.compile(r"(RemoteDisconnected|URLError|TimeoutError|timeout|Connection\w*Error|IncompleteRead|SSL\w*Error|"
                       r"HTTPError: HTTP Error (429|502|503|504))")


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def read_json(path, default=None):
    for i in range(4):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, type(default)) or default is None else default
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            time.sleep(0.05)        # (the other process is in the middle of replacing it)
    return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    for i in range(20):             # (Windows: a reader has the file open for a moment)
        try:
            os.replace(tmp, path)
            return True
        except OSError:
            time.sleep(0.05)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def short(k):
    return hashlib.sha1(k.encode()).hexdigest()[:12]


def readable(t):
    s = systems.BY_ID.get(t["c"].get("ats"))
    return s is None or s.read


def resting(t, today=None):
    return bool(t.get("rest_until")) and t["rest_until"] > (today or build.today())


def known(t):
    """({state: open jobs}, US-remote jobs, open jobs, seen) for a board: from its own read here, else the seed's
    hint. seen False: nobody has read it yet."""
    if t.get("read"):
        st = {}
        for p in t.get("places") or []:
            st[p[4]] = st.get(p[4], 0) + int(p[2] or 0)
        return st, int(t.get("remote") or 0), int(t.get("jobs") or 0), True
    s = t.get("seed")
    if isinstance(s, list) and len(s) == 4 and isinstance(s[2], dict):
        return s[2], int(s[1] or 0), int(s[0] or 0), bool(s[3])
    return {}, 0, 0, False


def rank(t, states, remote=False):
    """Sort key: (group, -known jobs). Group 0: last seen hiring in one of `states` (remote=True: or US-remote);
    1: no state known (never read, or it hires somewhere unnamed); 2: last seen elsewhere; 3: last seen with nothing
    open; 4: resting after repeated failures."""
    st, rem, jobs, seen = known(t)
    near = sum(st.get(s, 0) for s in states) + (rem if remote else 0)
    if near > 0:
        return (0, -near)
    if resting(t):
        return (4, 0)
    if not seen:        # (never read: a public list's employer in one of these states comes right after the known ones)
        return (0, 0) if any(s in st for s in states) else (1, 0)
    if not st:
        return (1, -jobs) if (jobs > 0 or not seen) else (3, 0)
    return (2, -jobs)


def order(tenants, keys, states, remote=False):
    """keys in reading order (see rank); ties in a stable, deterministic order. Within the near-you group the very
    large boards (HEAVY known jobs or more: many list pages each) go after the others, so a handful of giants on one
    slow job system never hold back the hundreds of ordinary employers behind them."""
    states = set(states)

    def key(k):
        g, n = rank(tenants[k], states, remote)
        heavy = 1 if g == 0 and known(tenants[k])[2] >= HEAVY else 0
        return (g, heavy, n, k)
    return sorted(keys, key=key)


def near_jobs(t, a):
    """Open jobs of board t inside area a ({lat, lon, radius, remote_only}); US-remote jobs for a remote-only area."""
    if a.get("remote_only"):
        return int(t.get("remote") or 0)
    if a.get("lat") is None:
        return 0
    import geo
    n = 0
    for p in t.get("places") or []:
        if geo.miles(a["lat"], a["lon"], p[0], p[1]) <= a["radius"]:
            n += int(p[2] or 0)
    return n


def host_of(c):
    """The host a board is read from, as far as its address tells (one shared host for most job systems)."""
    try:
        h = urllib.parse.urlsplit(systems.careers_url(c)).netloc.lower()
    except Exception:
        h = ""
    return h or str(c.get("ats") or "other")


OLD_LANES = {"greenhouse": 3, "lever": 1, "ashby": 3, "workday": 6, "jsonld": 4}   # a seed without "lanes" was measured with these (else 3)


def board_secs(a, secs, width=None):
    """Seconds of its lane one board of system `a` takes: what a read took (secs) spread over the boards read at once
    when that was measured (width; default: today's lane), but never faster than the provider's own pace allows."""
    return max(secs / (width or build.LANES.get(a, build.LANE_DEFAULT)), REQS_PER_BOARD / net.system_rate(a))


def seed_width(a, lanes=None):
    return int((lanes or {}).get(a) or OLD_LANES.get(a, 3))


def lane_minutes(counts, lane_secs):
    """Minutes to read {job system: boards}: each system is its own lane, paced per provider; the slowest decides.
    lane_secs(system) = board_secs(...) for that system."""
    return max((n * lane_secs(a) for a, n in counts.items()), default=0.0) / 60.0


class Local:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.T = build.Tenants(os.path.join(root, "tenants.json.gz"))
        self.journal = os.path.join(root, "journal.jsonl")
        self.meta_path = os.path.join(root, "build.json")
        self.meta = read_json(self.meta_path, {})
        self._jl = threading.Lock()
        self._jf = None
        self.replayed = self._replay()

    # ------------------------------------------------------------ state on disk
    def _replay(self):
        n = 0
        try:
            with open(self.journal, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        k, t = d["k"], d["t"]
                    except (ValueError, KeyError, TypeError):
                        continue            # (a torn last line)
                    if t is None:
                        self.T.d.pop(k, None)
                    elif isinstance(t, dict) and isinstance(t.get("c"), dict):
                        self.T.d[k] = t
                    n += 1
        except OSError:
            pass
        return n

    def record(self, k):
        """Append board k as it is now to the journal (None when it was dropped)."""
        t = self.T.d.get(k)
        line = json.dumps({"k": k, "t": {a: b for a, b in t.items() if not a.startswith("_")} if t is not None else None},
                          separators=(",", ":"))
        with self._jl:
            if self._jf is None:
                self._jf = open(self.journal, "a", encoding="utf-8")
            self._jf.write(line + "\n")
            self._jf.flush()

    def save_meta(self):
        write_json(self.meta_path, self.meta)

    def compact(self):
        """Save the whole state and empty the journal."""
        with self._jl:
            snap = {k: {a: b for a, b in t.items() if not a.startswith("_")} for k, t in dict(self.T.d).items()}
            build.save_json_gz(self.T.path, snap)
            if self._jf is not None:
                self._jf.close()
                self._jf = None
            try:
                os.remove(self.journal)
            except OSError:
                try:
                    open(self.journal, "w").close()
                except OSError:
                    pass
        self.save_meta()

    # ------------------------------------------------------------ what it starts from
    def merge_seed(self, s, src="seed"):
        """Boards of a seed (seed.py) into the state: new ones are added, known ones get the seed's name and hints."""
        new = 0
        for b in seedmod.boards(s):
            k = systems.key(b["c"])
            t = self.T.d.get(k)
            if t is None:
                t = self.T.d[k] = {"c": b["c"], "src": [src], "found": build.today()}
                new += 1
            if b["n"]:
                t["seed_name"] = b["n"]
            t["seed"] = [b["j"], b["r"], b["st"], b["seen"]]
        if isinstance((s or {}).get("secs"), dict):
            self.meta["seed_secs"] = {str(a): float(v) for a, v in s["secs"].items() if isinstance(v, (int, float))}
            self.meta["seed_lanes"] = {str(a): int(v) for a, v in (s.get("lanes") or {}).items() if isinstance(v, int) and v > 0}
        return new

    def load_seeds(self, paths_):
        """Merge the seed files that are new or changed since the last time (the shipped one, then a newer one the
        app fetched). Also the shipped starter packs. True when anything was merged."""
        seen = self.meta.setdefault("seeds", {})
        did = False
        for p in paths_:
            try:
                st = os.stat(p)
            except OSError:
                continue
            sig = f"{st.st_size}:{int(st.st_mtime)}"
            if seen.get(p) == sig:
                continue
            s = seedmod.read(p)
            if s is None:
                continue
            n = self.merge_seed(s)
            seen[p] = sig
            did = True
            log(f"seed {p}: {n} new job sites, {len(self.T.d)} known")
        if did or not self.meta.get("packs"):
            build.seed_packs(self.T)
            self.meta["packs"] = build.today()
            did = True
        return did

    # ------------------------------------------------------------ the pass
    def candidates(self):
        today = build.today()
        return [k for k, t in self.T.d.items() if readable(t) and not resting(t, today)]

    def begin_pass(self, fresh=False):
        """The pass under way, or a new one when there is none (or fresh=True and the last one is finished)."""
        p = self.meta.get("pass")
        if not p or (fresh and p.get("finished")):
            p = self.meta["pass"] = {"n": int((p or {}).get("n", 0)) + 1, "started": time.time(), "finished": None}
        return p

    def pass_todo(self):
        p = self.meta.get("pass") or {}
        t0 = float(p.get("started") or 0)
        cand = self.candidates()
        return [k for k in cand if float(self.T.d[k].get("lt") or 0) < t0], len(cand)

    def weekly_todo(self, states, remote=False):
        """The upkeep's reading order: boards known near the people here that weren't tried for STALE_DAYS, then the
        rest, longest untried first."""
        states = set(states)
        old = time.time() - build.STALE_DAYS * 86400
        near, rest = [], []
        for k in self.candidates():
            t = self.T.d[k]
            if float(t.get("lt") or 0) >= old:
                continue
            (near if rank(t, states, remote)[0] == 0 else rest).append(k)
        near.sort(key=lambda k: (rank(self.T.d[k], states, remote), k))
        rest.sort(key=lambda k: (float(self.T.d[k].get("lt") or 0), k))
        return near + rest, len(near)

    def avg_secs(self, a, near=False):
        """Lane seconds one board of system `a` takes (board_secs): measured here (near=True: on the boards last seen
        near the people here, which are bigger and so take longer), else by the weekly build (the seed), else a default."""
        if near:
            m = (self.meta.get("secs_near") or {}).get(a)
            if m and m[1] >= MEASURED_MIN:
                return board_secs(a, m[0] / m[1])
        m = (self.meta.get("secs") or {}).get(a)
        if m and m[1] >= MEASURED_MIN:
            return board_secs(a, m[0] / m[1])
        s = (self.meta.get("seed_secs") or {}).get(a)
        return board_secs(a, float(s), seed_width(a, self.meta.get("seed_lanes"))) if s else board_secs(a, DEFAULT_SECS, 3)

    def estimate(self, keys):
        """Minutes to read these boards, from the seconds measured per job system (here, else by the weekly build)."""
        per = collections.Counter(build.lane(self.T.d[k]["c"]) for k in keys if k in self.T.d)
        return lane_minutes(per, self.avg_secs)

    # ------------------------------------------------------------ output
    def write_out(self, states=None, index=False):
        """Rewrite states/<ST>.json.gz for these states (None: every state) and remote.json.gz, and the manifest."""
        snap = types.SimpleNamespace(d=dict(self.T.d))
        live, by_state = build.live_boards(snap)
        built = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        want = sorted(states) if states is not None else sorted(set(build.ALL_STATES) | set(by_state))
        want = [s for s in want if s in build.ALL_STATES]
        ents = build.write_states(self.root, live, by_state, want, built)
        build.drop_suffixes(live)
        man = read_json(os.path.join(self.root, "manifest.json"), {})
        man.setdefault("states", {}).update(ents)
        p = self.meta.get("pass") or {}
        man.update(v=1, built=built, local=True, employers=len(live), boards_known=len(snap.d),
                   boards_read=sum(1 for t in snap.d.values() if t.get("read")),
                   pass_finished=p.get("finished"), pass_started=p.get("started"))
        write_json(os.path.join(self.root, "manifest.json"), man)
        if index:
            build.save_json_gz(os.path.join(self.root, "index.json.gz"),
                               {short(k): t["read"] for k, t in snap.d.items() if t.get("read")})
        return ents

    # ------------------------------------------------------------ discovery (optional)
    def discover(self, stop, found):
        """Boards that aren't on the list yet, from the newest Common Crawl URL index: a few index blocks per job
        system, slowly, each prefix at most once every DISCOVER_DAYS. found(keys) is called with the new ones."""
        from . import cc
        d = self.meta.setdefault("discovery", {})
        done = d.setdefault("done", {})
        fresh = lambda p: p in done and build._days_since(done[p]) < DISCOVER_DAYS
        prefixes = [p for s in systems.SYSTEMS if s.read for p in s.cc]
        if all(fresh(p) for p in prefixes):
            return 0
        net.HOST_GAP.update({"data.commoncrawl.org": CC_GAP, "index.commoncrawl.org": max(CC_GAP, 5.0)})
        crawls = cc.latest_crawls(1)
        if not crawls or stop():
            log("discovery: Common Crawl isn't answering; it is tried again with the next build")
            return 0
        seen = set(self.T.d)
        wd_extra, total = set(), [0]

        def sweep():
            new = [k for k in set(self.T.d) - seen]
            gone = [k for k in seen - set(self.T.d)]
            seen.update(new)
            seen.difference_update(gone)
            for k in new + gone:
                self.record(k)
            total[0] += len(new)
            if new:
                found(new)

        def after(prefix):
            done[prefix] = build.today()
            sweep()
            self.save_meta()
        build.discover_cc(self.T, crawls, CC_BLOCKS, wd_extra, want=lambda p: not fresh(p) and not stop(), after=after)
        if not stop():
            try:
                build.workday_sites_pass(self.T, self.meta.setdefault("wd", {}), wd_extra, WD_SITES, 0)
            except Exception as e:
                log(f"discovery: Workday sites failed ({type(e).__name__}: {str(e)[:80]})")
            sweep()
        d.update(at=build.today(), crawl=crawls[0], found=int(d.get("found", 0)) + total[0])
        self.save_meta()
        log(f"discovery: {total[0]} job sites that weren't on the list ({crawls[0]})")
        return total[0]

    # ------------------------------------------------------------ the run
    def run(self, job, stop, hold=None, reader=None):
        """Read boards for job = {mode: "pass" | "weekly", areas: [{pid, lat, lon, radius, states, remote_only}],
        discover: bool, fresh: bool (start a new pass when the last one is finished), minutes: time box}. stop():
        True = stop now; hold(): True = wait (a job fetch is running). reader: tests replace build.read_tenant.
        Returns the final progress dict."""
        reader = reader or build.read_tenant
        mode = job.get("mode") or "pass"
        areas = [a for a in job.get("areas") or [] if isinstance(a, dict)]
        states = sorted({s for a in areas for s in a.get("states") or []})
        remote = any(a.get("remote_only") for a in areas)
        t_start = time.time()
        wire0 = (int(net.STATS.get("wire", 0)), int(net.STATS.get("plain", 0)))
        minutes = float(job.get("minutes") or (WEEKLY_MINUTES if mode == "weekly" else 0))
        deadline = t_start + minutes * 60 if minutes else None
        stopped = lambda: stop() or (deadline is not None and time.time() > deadline)
        if mode == "weekly":
            keys, n_near = self.weekly_todo(states, remote)
            total = len(keys)
        else:
            self.begin_pass(fresh=bool(job.get("fresh")))
            keys, total = self.pass_todo()
            keys = order(self.T.d, keys, states, remote)
            n_near = sum(1 for k in keys if rank(self.T.d[k], set(states), remote)[0] == 0)
        base_done = total - len(keys) if mode != "weekly" else 0
        if job.get("limit"):                # (tests: read only the first few)
            keys = keys[:int(job["limit"])]
            n_near = min(n_near, len(keys))
        # the boards last seen near the people here, counted over the whole pass (a resumed run carries on counting)
        near_base = 0
        if mode != "weekly":
            ps = self.meta["pass"]
            if "near_total" not in ps:
                ps.update(near_total=n_near, near_done=0)
            near_base = int(ps.get("near_done") or 0)
        self.save_meta()
        g0 = set(keys[:n_near])
        mu = threading.Lock()
        left = collections.Counter(build.lane(self.T.d[k]["c"]) for k in keys)
        left0 = collections.Counter(build.lane(self.T.d[k]["c"]) for k in g0)
        st = {"ok": 0, "empty": 0, "failed": 0, "skipped": 0, "deferred": 0}
        done_at = collections.deque()
        near = {a.get("pid"): set() for a in areas}
        for k, t in self.T.d.items():           # what earlier runs already found near each person
            if t.get("read") and int(t.get("jobs") or 0) > 0 and build._days_since(t["read"]) <= build.KEEP_DAYS:
                for a in areas:
                    if near_jobs(t, a) > 0:
                        near[a.get("pid")].add(k)
        dirty, counts = set(), {"todo": len(keys), "done": 0, "g0": len(g0), "g0_done": 0}
        n_keys = len(keys)
        title_budget = [TITLES]
        secs, secs_near = self.meta.setdefault("secs", {}), self.meta.setdefault("secs_near", {})
        rev = [0]
        disc = {"state": "off", "found": 0}
        pools, futs = {}, []

        hosts, tries, flock = {}, {}, threading.Lock()

        def requeue(k, ln):
            with flock:
                futs.append(pools[ln].submit(one, k))

        def finish(k, t, tmp, r, took, ln, timed=True):
            """Store what a read made of board k and count it."""
            before = {p[4] for p in t.get("places") or []}
            tmp.pop("_titled", None)
            tmp["lt"] = time.time()
            if k not in self.T.d:
                return                  # (dropped meanwhile: a respelt Workday board)
            self.T.d[k] = tmp
            self.record(k)
            with mu:
                st[r] = st.get(r, 0) + 1
                counts["done"] += 1
                left[ln] -= 1
                if k in g0:
                    counts["g0_done"] += 1
                    left0[ln] -= 1
                if timed and r in ("ok", "empty"):
                    m = (secs_near if k in g0 else secs).setdefault(ln, [0.0, 0])
                    m[0] += took
                    m[1] += 1
                done_at.append(time.time())
                dirty.update(before | {p[4] for p in tmp.get("places") or []})
                if tmp.get("remote") or t.get("remote"):
                    dirty.add("remote")
                live = r == "ok"
                for a in areas:
                    s = near[a.get("pid")]
                    if live and near_jobs(tmp, a) > 0:
                        s.add(k)
                    else:
                        s.discard(k)

        def one(k):
            if stopped():
                return
            while hold is not None and hold():
                time.sleep(2)
                if stopped():
                    return
            t = self.T.d.get(k)
            if t is None:
                return
            ln, host = build.lane(t["c"]), host_of(t["c"])
            tmp = {a: b for a, b in t.items() if not a.startswith("_")}
            with mu:
                hs = hosts.setdefault(host, {"streak": 0, "cools": 0, "until": 0.0, "blocked": False})
                state = "blocked" if hs["blocked"] else "cool" if hs["until"] > time.time() else "ok"
            if state == "cool":         # its job system is being left alone for a while: back in line
                time.sleep(0.2 if reader is not build.read_tenant else 1)
                return requeue(k, ln)
            if state == "blocked":      # ... and that didn't help: another day (not a failure of this board)
                tmp["err"] = HOST_QUIET
                return finish(k, t, tmp, "deferred", 0, ln, timed=False)
            t0 = time.time()
            try:
                r = reader(tmp, title_budget)
            except Exception as e:      # (read_tenant catches a board's own errors: this is a bug in a reader)
                tmp["err"] = f"{type(e).__name__}: {str(e)[:100]}"
                r = "failed"
            took = time.time() - t0
            transport = r == "failed" and bool(TRANSPORT.match(tmp.get("err") or ""))
            with mu:
                hs["streak"] = hs["streak"] + 1 if transport else 0
                if r in ("ok", "empty"):
                    hs["cools"] = 0
                again = transport and (hs["streak"] >= 3 or hs["cools"] > 0) and tries.get(k, 0) < RETRIES
                if transport and hs["streak"] >= BREAK_AFTER:
                    hs["streak"] = 0
                    hs["cools"] += 1
                    if hs["cools"] > COOL_MAX:
                        hs["blocked"] = True
                        log(f"{host} keeps refusing connections: its remaining job sites are left for another day")
                    else:
                        wait = COOL_SECS * 2 ** (hs["cools"] - 1) * (0.01 if reader is not build.read_tenant else 1)
                        hs["until"] = time.time() + wait
                        log(f"{host} is refusing connections: leaving it alone for {wait:.0f} s")
                if again:
                    tries[k] = tries.get(k, 0) + 1
            if again:                   # the host's trouble, not this board's: nothing is recorded against it
                return requeue(k, ln)
            finish(k, t, tmp, r, took, ln)

        def submit(ks):
            for k in ks:
                t = self.T.d.get(k)
                if t is None:
                    continue
                ln = build.lane(t["c"])
                with flock:
                    if ln not in pools:
                        pools[ln] = cf.ThreadPoolExecutor(build.LANES.get(ln, build.LANE_DEFAULT), thread_name_prefix=f"dir-{ln}")
                    futs.append(pools[ln].submit(one, k))

        def progress(phase, final=False):
            now = time.time()
            with mu:
                while done_at and now - done_at[0] > 300:
                    done_at.popleft()
                span = min(300.0, max(1.0, now - t_start))
                rate = len(done_at) * 60.0 / span
                eta0 = lane_minutes({a: n for a, n in left0.items() if n > 0}, lambda a: self.avg_secs(a, near=True))
                eta = max(((left0.get(a, 0) * self.avg_secs(a, near=True) + max(0, n - left0.get(a, 0)) * self.avg_secs(a))
                           for a, n in left.items() if n > 0), default=0.0) / 60.0
                resting = sorted(set(net.resting()) | {h for h, v in hosts.items() if v["blocked"] or v["until"] > now})
                out = {"pid": os.getpid(), "token": job.get("token"), "at": round(now, 1), "mode": mode, "phase": phase, "started": round(t_start, 1),
                       "total": total + counts["todo"] - n_keys,
                       "done": base_done + counts["done"], "run_done": counts["done"], "run_todo": counts["todo"],
                       "rate": round(rate, 1), "run_rate": round(counts["done"] * 60.0 / max(1.0, now - t_start), 1),
                       "eta_min": round(eta, 1), "near_total": near_base + counts["g0"], "near_done": near_base + counts["g0_done"],
                       "near_eta_min": round(eta0, 1), "near": {str(p): len(s) for p, s in near.items()},
                       "stats": dict(st), "rev": rev[0], "discover": dict(disc), "final": final, "resting": resting[:8],
                       "http": dict(net.STATS),
                       "top": sorted(([k] + v for k, v in list(net.BY.items())), key=lambda x: -x[2])[:12]}
            write_json(os.path.join(self.root, "progress.json"), out)
            return out

        def flush(everything):
            with mu:
                d = set(dirty)
                want = d if everything else (d & (set(states) | {"remote"}))
                dirty.difference_update(want)
            if not want and not everything:
                return
            try:
                self.write_out(sorted(s for s in want if s != "remote"), index=everything)
                rev[0] += 1
            except Exception as e:
                log(f"writing the state files failed: {type(e).__name__}: {e}")
                with mu:
                    dirty.update(want)

        def discovering():
            disc["state"] = "running"

            def found(new):
                new = [k for k in new if readable(self.T.d.get(k) or {"c": {}})]
                with mu:
                    counts["todo"] += len(new)
                    for k in new:
                        left[build.lane(self.T.d[k]["c"])] += 1
                    disc["found"] += len(new)
                submit(new)
            try:
                self.discover(stopped, found)
                disc["state"] = "done"
            except Exception as e:
                disc["state"] = "failed"
                log(f"discovery failed: {type(e).__name__}: {e}")

        log(f"{mode}: {len(keys)} job sites to check ({n_near} last seen near: {','.join(states) or 'remote'}); "
            f"{total} known; about {self.estimate(keys):.0f} minutes")
        progress("starting")
        submit(keys)
        dth = None
        if job.get("discover") and mode != "weekly":
            dth = threading.Thread(target=discovering, daemon=True, name="dir-discover")
            dth.start()
        last_w, last_all, first = time.time() - WRITE_SECS + WRITE_FIRST, time.time(), True
        while True:
            time.sleep(0.5 if reader is not build.read_tenant else 2)
            with flock:
                futs[:] = [f for f in futs if not f.done()]
                busy = bool(futs) or (dth is not None and dth.is_alive())
            if stopped() or not busy:
                break
            now = time.time()
            if now - last_all >= ALL_WRITE_SECS:
                flush(True)
                last_all = last_w = time.time()
            elif now - last_w >= WRITE_SECS:
                flush(False)
                last_w = time.time()
            progress("reading")
        was_stopped = stopped()
        for p in pools.values():
            p.shutdown(wait=not was_stopped, cancel_futures=was_stopped)
        if was_stopped:
            time.sleep(0.3)             # (reads that were just finishing get to write their line)
        if mode != "weekly" and not was_stopped:
            todo, _ = self.pass_todo()
            if not todo:
                self.meta["pass"]["finished"] = time.time()
                self.meta["pass"]["minutes"] = round(float(self.meta["pass"].get("minutes") or 0) + (time.time() - t_start) / 60, 1)
        elif mode != "weekly":
            self.meta["pass"]["minutes"] = round(float(self.meta["pass"].get("minutes") or 0) + (time.time() - t_start) / 60, 1)
        use = self.meta.setdefault("use", {"sites": 0, "wire": 0, "plain": 0})
        use["sites"] = int(use.get("sites", 0)) + st["ok"] + st["empty"]
        use["wire"] = int(use.get("wire", 0)) + int(net.STATS.get("wire", 0)) - wire0[0]
        use["plain"] = int(use.get("plain", 0)) + int(net.STATS.get("plain", 0)) - wire0[1]
        if mode == "weekly":
            self.meta["weekly"] = {"at": time.time(), "checked": counts["done"]}
        else:
            self.meta["pass"]["near_done"] = near_base + counts["g0_done"]
            self.meta["pass"]["near_total"] = near_base + counts["g0"]
        progress("writing")
        with mu:
            dirty.update(states)
        flush(True)
        self.compact()
        out = progress("stopped" if was_stopped else "done", final=True)
        log(f"{mode} {'stopped' if was_stopped else 'done'}: {counts['done']} job sites checked in {(time.time() - t_start) / 60:.1f} min ({st})")
        return out


# ---------------------------------------------------------------- the child process
def _parent_alive(pid, cache=[0.0, True]):
    if not pid:
        return True
    if time.time() - cache[0] > 5:
        try:
            import joblock
            cache[1] = joblock._alive(pid)[0]
        except Exception:
            cache[1] = True
        cache[0] = time.time()
    return cache[1]


def _fetch_running():
    """True while a job fetch (Find new jobs, the staged first check) holds the job lock."""
    try:
        import joblock
        j = joblock.info()
        return bool(j and j.get("alive") and j.get("kind") in ("fetch", "job"))
    except Exception:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the employer directory on this computer (started by Siftwell).")
    ap.add_argument("--root", required=True, help="DATA/directory/local")
    ap.add_argument("--parent", type=int, default=0, help="stop when this process is gone")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"      # nothing here may ever call Claude
    job = read_json(os.path.join(root, "job.json"), {})
    stop_file = os.path.join(root, "stop")
    stop = lambda: os.path.exists(stop_file) or not _parent_alive(args.parent)
    try:
        net.install()       # every request, also the app readers', paced per provider (net.py: polite by design)
        L = Local(root)
        if L.replayed:
            log(f"carried on from the journal: {L.replayed} job sites read since the last save")
        L.load_seeds([p for p in job.get("seeds") or [] if isinstance(p, str)])
        if L.replayed:
            L.compact()
        L.run(job, stop, hold=_fetch_running if job.get("mode") == "weekly" else None)
    except Exception as e:
        import traceback
        traceback.print_exc()
        write_json(os.path.join(root, "progress.json"), {"pid": os.getpid(), "token": job.get("token"), "at": time.time(), "phase": "failed", "final": True,
                                                          "error": f"{type(e).__name__}: {str(e)[:200]}"})
        sys.stdout.flush()
        os._exit(1)
    sys.stdout.flush()
    os._exit(0)     # (reader threads still waiting on a slow board must not keep the process alive)
