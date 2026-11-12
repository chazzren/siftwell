"""Build my own directory (app side): the employer directory read on this computer, so Siftwell doesn't depend on the
shared one staying online. No Claude, no key, no account.

The reading itself is index_build/local.py (the weekly builder's own readers and file format); it runs as a child
process (`localdir.py --root ...` from source, `Siftwell.exe --dirbuild ...` installed: frozen.command) at below-normal
priority, writes only under DATA/directory/local/, and stops when this server is gone. This module starts, pauses and
watches it, and tells the pages about it:

  start(pid, add=...)   start (or carry on) a pass for everyone's areas. A person can ask for what it finds near them
                        to be added as it goes (add "all" or a number: at most that many; nothing blind: the button
                        says so, the whole build is ONE batch for "Remove the employers this added"). Choosing to
                        build switches "Where my directory comes from" from Shared to Both.
  pause()               stop now; nothing read is lost (the journal), Continue carries on where it stopped.
  progress(pid)         the build's line for first_search.progress, the ONE progress line: "Building your directory:
                        1,240 of 6,300 job sites checked · 212 employers near you so far". It never blocks Find new
                        jobs ("blocking": False).
  status(pid)           everything Settings -> Employer directory shows: where the directory comes from, how far the
                        build is, honest time estimates (seconds measured per job system: here once there are
                        enough, else the weekly builder's from the seed), the sentence that offers the build.
  start_background()    after a restart: carry on an unfinished pass that wasn't paused. Once a week after a finished
                        pass: the upkeep (boards known near the people here, then a slice of the rest, at most
                        local.WEEKLY_MINUTES; never while a job fetch or a first check runs), then the weekly rule for
                        newly found employers (directory.apply(weekly=True)).
  refresh_seed()        when the shared directory is in use and reachable: fetch a newer seed list from it
                        (DATA/directory/seed.json.gz, SHA-256 checked). Never with "Built on this computer".

While a pass runs, the monitor thread looks at the child's progress file every few seconds; each time the area's
state files were rewritten (about once a minute) it adds the newly found employers for the people who asked for that
and starts their check (first_search.start_checking; Claude rates once, after the boards near them are through).

Server-owned files in DATA/directory/local/: control.json (paused, who asked for additions), job.json (what the child
was started for), stop (ask the child to stop), build.log. Routes (server.py): GET /api/localdir,
POST /api/localdir/start {add, fresh}, POST /api/localdir/pause, POST /api/localdir/prefs {source, discover}.
Test hooks: SIFTWELL_LOCALDIR_DELAY=<s> (first background look, default 90); SIFTWELL_LOCALDIR_LIMIT=<n> (read at
most n job sites per run: scripts/test_localdir.py)."""
import datetime as dt, json, os, subprocess, sys, threading, time

import directory
import paths

ROOT = directory.LOCAL
SEED_ASSET = os.path.join(paths.ASSETS, "directory", "seed.json.gz")
SEED_DATA = os.path.join(directory.DIR, "seed.json.gz")
WEEKLY_DAYS = 7
CHECK_BATCH = 25        # employers a build has added before their check starts while the near-you group is still read
CHECK_QUIET = 600       # ... or this many seconds since the last check it started
_LAST_CHECK = {}
STOP_GRACE = 45         # seconds a paused build gets to save before it is ended
NO_PLACE = "Add your home ZIP (Filters, then My search) so Siftwell knows which employers to read first."
S = None                # the server module (configure)
_LOCK = threading.RLock()
_PROC = {"p": None, "mode": None, "starting": False, "token": None}
_SEED = {}              # path signature -> summary


def configure(server_module):
    global S
    S = server_module


def _local():
    from index_build import local
    return local


def _read(name, default=None):
    return _local().read_json(os.path.join(ROOT, name), {} if default is None else default)


def control():
    c = _read("control.json")
    c.setdefault("add", {})
    c.setdefault("added", {})
    return c


def save_control(c):
    _local().write_json(os.path.join(ROOT, "control.json"), c)


# ---------------------------------------------------------------- the seed list
def seed_path():
    """The newest seed on this computer: the one fetched from the shared directory when there is one, else the
    shipped one."""
    return SEED_DATA if os.path.exists(SEED_DATA) else SEED_ASSET


def seed_summary():
    """{boards, built, secs: {system: seconds}, rows: [(system, states text)]} of the seed (cached per file)."""
    from index_build import seed
    p = seed_path()
    try:
        st = os.stat(p)
    except OSError:
        return {"boards": 0, "built": "", "secs": {}, "rows": []}
    sig = (p, st.st_mtime_ns, st.st_size)
    if _SEED.get("sig") != sig:
        s = seed.read(p) or {}
        rows = [(g.get("a"), str(r[-1] or "")) for g in s.get("groups") or [] if isinstance(g.get("t"), list)
                for r in g["t"] if isinstance(r, list) and r]
        _SEED.clear()
        _SEED.update(sig=sig, v={"boards": len(rows), "built": str(s.get("built") or ""), "rows": rows,
                                 "lanes": s.get("lanes") if isinstance(s.get("lanes"), dict) else {},
                                 "secs": s.get("secs") if isinstance(s.get("secs"), dict) else {}})
    return _SEED["v"]


def refresh_seed():
    """A newer seed list from the shared directory, when it is in use, reachable and has one. True when fetched."""
    if not directory.uses_shared():
        return False
    try:
        import hashlib
        from index_build import seed
        ent = (directory.manifest() or {}).get("seed")
        if not isinstance(ent, dict) or not ent.get("sha256"):
            return False
        for p in (SEED_DATA, SEED_ASSET):
            try:
                with open(p, "rb") as f:
                    if hashlib.sha256(f.read()).hexdigest() == ent["sha256"]:
                        return False        # (already have it)
            except OSError:
                pass
        data = directory._get(seed.FILE)
        if hashlib.sha256(data).hexdigest() != ent["sha256"]:
            raise ValueError("checksum mismatch")
        seed.loads(data)
        directory._write(SEED_DATA, data)
        return True
    except Exception as e:
        print("seed list not refreshed:", type(e).__name__, str(e)[:100], flush=True)
        return False


# ---------------------------------------------------------------- who it builds for
def areas(first=None):
    """[{pid, lat, lon, radius, states, remote_only}] for every profile with a place (or a remote-only search), the
    asking profile first."""
    import people
    out = []
    ids = list(people.ids())
    if first in ids:
        ids.remove(first)
        ids.insert(0, first)
    for pid in ids:
        try:
            a = directory.area(pid)
        except Exception:
            a = None
        if not a:
            continue
        la, lo, label, radius, remote_only, remote_ok = a
        out.append({"pid": pid, "lat": la, "lon": lo, "radius": radius, "remote_only": bool(remote_only),
                    "states": [] if la is None else directory.states_near(la, lo, radius)})
    return out


def _area(pid):
    return next((a for a in areas(pid) if a["pid"] == pid), None)


# ---------------------------------------------------------------- the child process
def running():
    p = _PROC["p"]
    return bool(_PROC["starting"] or (p is not None and p.poll() is None))


def _progress():
    """The running child's progress ({} when none, or it hasn't written yet)."""
    pr = _read("progress.json")
    if _PROC["p"] is None or pr.get("token") != _PROC["token"]:
        return {}       # (the token, not the pid: a venv's python.exe is a launcher, so the child's pid isn't Popen's)
    return pr


def _meta():
    return _read("build.json")


def unfinished():
    p = _meta().get("pass") or {}
    return bool(p.get("started") and not p.get("finished"))


def start(pid=None, mode="pass", add=None, fresh=False):
    """Start a pass (or carry on the unfinished one), or the weekly upkeep. add: "all" or a number: add what it finds
    near `pid` as it goes (at most that many). Returns (ok, error)."""
    with _LOCK:
        if pid and add and mode == "pass":
            c = control()
            c["add"][pid] = "all" if add == "all" else max(1, int(add))
            save_control(c)
        if running():
            return (True, None) if mode == "pass" and _PROC["mode"] == "pass" else (False, "Siftwell is already working on your directory.")
        ars = areas(pid)
        if not ars:
            return False, NO_PLACE
        _PROC.update(starting=True, mode=mode)
    try:
        if mode == "pass" and directory.source() == "shared":
            directory.save_prefs(source="both")     # (they asked for their own: use it, next to the shared one)
        c = control()
        if mode == "pass":
            c["paused"] = False
            if not unfinished():
                c["tag"] = "build-" + dt.datetime.now().strftime("%Y%m%d%H%M%S")
                c["added"] = {}
            save_control(c)
        job = {"mode": mode, "areas": ars, "discover": bool(directory.prefs().get("discover")) and mode == "pass",
               "fresh": bool(fresh), "seeds": [SEED_ASSET, SEED_DATA], "token": os.urandom(6).hex()}
        lim = os.environ.get("SIFTWELL_LOCALDIR_LIMIT")
        if lim and lim.isdigit():
            job["limit"] = int(lim)
        threading.Thread(target=_launch, args=(job,), daemon=True, name="directory-build").start()
    except Exception:
        _PROC.update(starting=False)
        raise
    return True, None


def _launch(job):
    import frozen
    p = None
    try:
        if job["mode"] == "pass":
            refresh_seed()
        os.makedirs(ROOT, exist_ok=True)
        _local().write_json(os.path.join(ROOT, "job.json"), job)
        for name in ("stop", "progress.json"):
            try:
                os.remove(os.path.join(ROOT, name))
            except OSError:
                pass
        logp = os.path.join(ROOT, "build.log")
        try:
            if os.path.getsize(logp) > 2_000_000:
                os.remove(logp)
        except OSError:
            pass
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | 0x00004000    # BELOW_NORMAL_PRIORITY_CLASS: stays out of the way
        with open(logp, "ab") as out:
            p = subprocess.Popen(frozen.command("dirbuild", "--root", ROOT, "--parent", os.getpid(), utf8=True, windowed=True),
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, creationflags=flags,
                                 cwd=paths.DATA, env={**os.environ, "SIFTWELL_FORBID_CLAUDE": "1", "PYTHONUTF8": "1"})
        with _LOCK:
            _PROC.update(p=p, starting=False, token=job["token"])
    except Exception as e:
        print("directory build could not start:", type(e).__name__, e, flush=True)
        with _LOCK:
            _PROC.update(p=None, starting=False)
        return
    try:
        _monitor(p, job["mode"], job["token"])
    except Exception as e:
        print("directory build monitor failed:", type(e).__name__, e, flush=True)
    finally:
        with _LOCK:
            if _PROC["p"] is p:
                _PROC["p"] = None


def pause():
    """Stop the running build now (what it read is kept). True when there was one."""
    with _LOCK:
        p = _PROC["p"]
        c = control()
        c["paused"] = True
        save_control(c)
        if p is None or p.poll() is not None:
            return False
        try:
            open(os.path.join(ROOT, "stop"), "w").close()
        except OSError:
            pass

    def end():
        try:
            p.wait(STOP_GRACE)
        except subprocess.TimeoutExpired:
            try:
                p.terminate()       # (only the child this server started)
            except Exception:
                pass
    threading.Thread(target=end, daemon=True).start()
    return True


def stop_and_wait(timeout=60):
    """For a restore (backup.py): the build must not write while the data folder is swapped."""
    with _LOCK:
        p = _PROC["p"]
    if p is None or p.poll() is not None:
        return
    try:
        open(os.path.join(ROOT, "stop"), "w").close()
        p.wait(timeout)
    except Exception:
        try:
            p.terminate()
        except Exception:
            pass


# ---------------------------------------------------------------- adding what it finds
def _add_found(pid, rate):
    """Put the employers the build has found near this person so far on their list (when they asked for that) and
    get their openings checked. Returns how many were added."""
    import people
    c = control()
    want = c["add"].get(pid)
    if not want or not people.exists(pid):
        return 0
    limit = None
    if want != "all":
        limit = int(want) - int(c["added"].get(pid, 0))
        if limit <= 0:
            return 0
    r = directory.apply(pid, limit=limit, tag=c.get("tag") or "build")
    n = (len(r["added"]) + len(r["linked"])) if r.get("available") else 0
    import first_search
    if n:
        c = control()
        c["added"][pid] = int(c["added"].get(pid, 0)) + n
        save_control(c)
        S._actlog("companies added", pid, f"{n} found while building your directory on this computer")
        first_search._CACHE.pop(pid, None)
        first_search._EST.clear()
        first_search.note_added(pid)
    # Their openings get checked (and the best matches rated, within the usual limits) by the ordinary staged check.
    # While the near-you group is still being read it starts for a good batch or after a quiet spell, not for every
    # handful, and whatever is added while it runs joins it; once that group is through (rate=True here) every
    # leftover is checked at once. So nothing the build adds is left unchecked or unrated.
    try:
        if not first_search.JOB["running"] and not S.state.get("running"):
            left = len(first_search.pending(pid))
            if left and (rate or left >= CHECK_BATCH or time.time() - _LAST_CHECK.get(pid, 0) >= CHECK_QUIET):
                ok, _ = first_search.start_checking(pid, rate=True)
                if ok:
                    _LAST_CHECK[pid] = time.time()
    except Exception as e:
        print("directory build: check not started:", type(e).__name__, e, flush=True)
    return n


def _monitor(p, mode, token):
    import people
    last = 0
    while True:
        alive = p.poll() is None
        pr = _read("progress.json")
        rev = int(pr.get("rev") or 0) if pr.get("token") == token else 0
        if mode == "pass" and (rev != last or not alive):
            last = rev
            directory._PREVIEW.clear()
            near_done = int(pr.get("near_done") or 0) >= int(pr.get("near_total") or 0)
            for pid in list(control()["add"]):
                try:
                    _add_found(pid, rate=near_done or not alive)
                except Exception as e:
                    print("directory build: adding employers failed:", type(e).__name__, e, flush=True)
        if not alive:
            break
        time.sleep(5)
    directory._PREVIEW.clear()
    if mode == "pass" and not unfinished():
        c = control()
        c.update(add={}, paused=False)      # (from here on the weekly rule adds what is newly found)
        save_control(c)
        S._actlog("directory built", None, "The employer directory was built on this computer")
    if mode == "weekly":
        for pid in directory.users():
            try:
                if people.exists(pid):
                    r = directory.apply(pid, weekly=True)
                    if r["available"] and (r["added"] or r["linked"]):
                        print(f"directory (built here): {len(r['added']) + len(r['linked'])} newly found employers for {pid}", flush=True)
            except Exception as e:
                print("directory upkeep: adding employers failed:", type(e).__name__, e, flush=True)


# ---------------------------------------------------------------- honest estimates and the words for the pages
def _range(m):
    """A time for the near-you group as an honest range: "about 15–25 minutes", "about 1–1½ hours". The low end is
    the estimate; the high end allows for the largest employers and for job systems that ask Siftwell to slow down."""
    lo, hi = max(1.0, m), max(1.0, m) * 1.6 + 3
    if hi < 100:
        r = lambda x: max(5, 5 * round(x / 5))
        a, b = (r(lo), r(hi)) if lo >= 8 else (max(1, round(lo)), r(hi))
        return f"about {a}–{b} minutes" if a != b else f"about {a} minutes"
    h = lambda x: (lambda v: f"{int(v)}" if v == int(v) else (f"{int(v)}½" if int(v) else "½"))(max(0.5, round(x / 30) / 2))
    a, b = h(lo), h(hi)
    return f"about {a}–{b} hours" if a != b else f"about {a} hour{'' if a == '1' else 's'}"


def _words(m):
    """The whole build's time in plain words, never a falsely exact number: it depends on other people's servers."""
    if m < 45:
        return "under an hour"
    if m < 100:
        return "about an hour"
    if m < 200:
        return "a couple of hours"
    if m < 480:
        return "a few hours"
    if m < 900:
        return "several hours"
    return "most of a day"


DEFAULT_MB_PER_1000 = 55.0      # measured over a 20-minute real build and projected per job system over a whole pass
MEASURED_SITES = 10000          # this computer's own figure is used once it has read this many (the first ones are the heaviest)


def data_use():
    """{mb_per_1000, first_mb, measured}: internet data a first full build uses, from what really crossed the wire
    (index_build/net.py counts it). Before anything was measured here: the figure measured when this was built."""
    u = _meta().get("use") or {}
    sites, wire = int(u.get("sites") or 0), int(u.get("wire") or 0)
    measured = sites >= MEASURED_SITES
    per = (wire / 1e6) / (sites / 1000.0) if measured else DEFAULT_MB_PER_1000
    total = seed_summary()["boards"] or 0
    first = per * total / 1000.0
    return {"mb_per_1000": round(per, 1), "first_mb": int(round(first, -2) if first >= 150 else round(first, -1)), "measured": measured}


_METERED = {"at": 0.0, "v": None}


def metered():
    """True when the operating system says this internet connection is metered (Windows only: its own "metered
    connection" setting, asked through PowerShell, cached ten minutes). None when it can't be told (macOS, Linux)."""
    if sys.platform != "win32":
        return None
    if time.time() - _METERED["at"] < 600:
        return _METERED["v"]
    v = None
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "[void][Windows.Networking.Connectivity.NetworkInformation,Windows,ContentType=WindowsRuntime];"
                            "[Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile().GetConnectionCost().NetworkCostType"],
                           capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        out = (r.stdout or "").strip().lower()
        if out:
            v = out in ("fixed", "variable")
    except Exception:
        v = None
    _METERED.update(at=time.time(), v=v)
    return v


def estimate(pid):
    """How long a build takes for this person: {sites, near_sites, all_min, near_min, all_text (plain words: "a few
    hours"), near_text (a range: "about 15–25 minutes"), measured}.
    Before anything was read here it comes from the seed (boards per job system x the seconds the weekly builder
    measured for that system, spread over the lanes read at once); afterwards from what was measured on this computer;
    while a pass is under way, from what is still left."""
    L = _local()
    meta = _meta()
    mine = {a: v[0] / v[1] for a, v in (meta.get("secs") or {}).items() if isinstance(v, list) and len(v) == 2 and v[1] >= L.MEASURED_MIN}
    seed = seed_summary()
    secs = lambda a: (L.board_secs(a, mine[a]) if a in mine else
                      L.board_secs(a, float((seed["secs"] or {}).get(a) or L.DEFAULT_SECS), L.seed_width(a, seed.get("lanes"))))
    pr = _read("progress.json")
    if unfinished() and pr.get("total") and pr.get("mode") == "pass":
        return {"sites": int(pr["total"]), "left": max(0, int(pr["total"]) - int(pr.get("done") or 0)),
                "near_sites": int(pr.get("near_total") or 0), "all_min": float(pr.get("eta_min") or 0),
                "near_min": float(pr.get("near_eta_min") or 0), "all_text": _words(float(pr.get("eta_min") or 0)),
                "near_text": _range(float(pr.get("near_eta_min") or 0)), "measured": bool(mine)}
    a = _area(pid) if pid else None
    states = set((a or {}).get("states") or [])
    alln, near = {}, {}
    for ats, st in seed["rows"]:
        alln[ats] = alln.get(ats, 0) + 1
        if states and any(part[:2] in states for part in st.split()):
            near[ats] = near.get(ats, 0) + 1
    am, nm = L.lane_minutes(alln, secs), L.lane_minutes(near, secs)
    return {"sites": seed["boards"], "left": seed["boards"], "near_sites": sum(near.values()), "all_min": am, "near_min": nm,
            "all_text": _words(am), "near_text": _range(nm), "measured": bool(mine)}


def offer(pid, est=None):
    """The sentence that offers the build, the same on every page: what it does, how long it takes, no Claude."""
    e = est or estimate(pid)
    a = _area(pid) if pid else None
    if not e["sites"]:
        return ""
    first = ""
    if a and not a["remote_only"] and e["near_sites"]:
        first = f", the {e['near_sites']:,} last seen hiring near you first ({e['near_text']})"
    elif a and a["remote_only"]:
        first = ", the ones last seen with remote jobs first"
    return (f"Siftwell can build the directory on this computer: it reads the public job pages of {e['sites']:,} job sites "
            f"itself{first}, then the rest in the background ({e['all_text']} in all; you can pause it and keep using "
            "Siftwell meanwhile). It asks each job system slowly, about one page a second, so it is no burden on them. "
            f"The employers it finds near you are added to your list as it goes. It uses about {data_use()['first_mb']:,} MB "
            "of internet data the first time, and no Claude.")


def _line(pr, pid):
    n = lambda x: f"{int(x or 0):,}"
    if not pr.get("total"):
        return "Building your directory: getting ready"
    near = int((pr.get("near") or {}).get(str(pid)) or 0)
    a = _area(pid)
    what = "remote-friendly employers" if a and a["remote_only"] else f"employer{'' if near == 1 else 's'} near you"
    tail = f" · {n(near)} {what} so far" if a else ""
    return f"Building your directory: {n(pr.get('done'))} of {n(pr.get('total'))} job sites checked{tail}"


def progress(pid):
    """The build's entry for first_search.progress (None when no pass is running)."""
    if not running() or _PROC["mode"] != "pass":
        return None
    pr = _progress()
    tot = int(pr.get("total") or 0)
    return {"active": True, "kind": "dirbuild", "line": _line(pr, pid), "frac": (int(pr.get("done") or 0) / tot) if tot else .01,
            "mine": True, "can_pause": False, "pausing": False, "done": int(pr.get("done") or 0), "total": tot, "blocking": False}


def _iso(t):
    try:
        return dt.datetime.fromtimestamp(float(t)).isoformat(timespec="seconds") if t else None
    except (TypeError, ValueError, OSError):
        return None


def brief(pid):
    """The little the board and /setup need: is a build running, its line, and the offer."""
    run = running() and _PROC["mode"] == "pass"
    out = {"running": run, "line": _line(_progress(), pid) if run else "", "source": directory.source(),
           "unfinished": unfinished(), "paused": bool(control().get("paused")) and unfinished(),
           "built": bool((directory.local_manifest().get("states") or {})), "offer": ""}
    if not run and not out["built"] and not out["unfinished"]:
        try:
            out["offer"] = offer(pid)
        except Exception:
            out["offer"] = ""
    return out


def status(pid):
    meta, c = _meta(), control()
    run = running()
    pr = _progress() if run else {}
    lm = directory.local_manifest()
    ps = meta.get("pass") or {}
    try:
        with open(directory._path("manifest.json"), encoding="utf-8") as f:
            shared = json.load(f)
    except (OSError, ValueError):
        shared = {}
    rec = directory.record(pid) if pid else {}
    src = directory.source()
    est = estimate(pid)
    a = _area(pid) if pid else None
    has_local = bool(lm.get("states"))
    has_shared = bool(shared.get("states")) and not rec.get("offline")
    if src == "shared":
        origin = "shared" if has_shared else "starter"
    elif src == "local":
        origin = "local" if has_local else "starter"
    else:
        origin = "both" if has_shared and has_local else "shared" if has_shared else "local" if has_local else "starter"
    out = {"source": src, "discover": bool(directory.prefs().get("discover")), "possible": bool(a),
           "running": run, "mode": _PROC["mode"] if run else None, "unfinished": unfinished(),
           "paused": bool(c.get("paused")) and unfinished() and not run,
           "line": _line(pr, pid) if run and _PROC["mode"] == "pass" else "",
           "done": int(pr.get("done") or 0), "total": int(pr.get("total") or 0), "rate": float(pr.get("rate") or 0),
           "near": int((pr.get("near") or {}).get(str(pid)) or 0), "near_done": int(pr.get("near_done") or 0),
           "near_total": int(pr.get("near_total") or 0), "estimate": est, "offer": offer(pid, est),
           "origin": origin, "shared_built": shared.get("built") if has_shared else None,
           "local_built": (_iso(ps.get("finished")) or lm.get("built")) if has_local else None,
           "local_complete": bool(ps.get("finished")), "local_employers": int(lm.get("employers") or 0),
           "pass_minutes": ps.get("minutes"), "adding": c["add"].get(pid), "added": int(c["added"].get(pid, 0)),
           "weekly_at": _iso((meta.get("weekly") or {}).get("at")), "seed": {"boards": seed_summary()["boards"], "built": seed_summary()["built"]},
           "discovery": {"at": (meta.get("discovery") or {}).get("at"), "found": int((meta.get("discovery") or {}).get("found") or 0)},
           "remote_only": bool(a and a["remote_only"]), "data": data_use(), "metered": bool(metered()) if not run else False}
    if run and pr.get("total"):
        out["eta_text"] = _words(float(pr.get("eta_min") or 0))
        out["near_eta_text"] = _range(float(pr.get("near_eta_min") or 0)) if out["near_done"] < out["near_total"] else ""
        out["resting"] = [str(x) for x in (pr.get("resting") or [])][:4]
    return out


# ---------------------------------------------------------------- background: carry on, weekly upkeep
def _busy():
    """True while a job fetch, a first check or anything else holding the job lock runs."""
    try:
        import first_search, joblock
        if first_search.JOB["running"] or S.state.get("running"):
            return True
        j = joblock.info()
        return bool(j and j.get("alive"))
    except Exception:
        return True


def upkeep_due():
    if not directory.uses_local() or running() or unfinished():
        return False
    meta = _meta()
    done = (meta.get("pass") or {}).get("finished")
    if not done:
        return False
    last = max(float(done), float((meta.get("weekly") or {}).get("at") or 0))
    return time.time() - last >= WEEKLY_DAYS * 86400


def start_background(log=lambda m: print(m, flush=True)):
    def loop():
        time.sleep(float(os.environ.get("SIFTWELL_LOCALDIR_DELAY") or 90))
        first = True
        while True:
            try:
                if directory.uses_local() and not running() and not metered():
                    if first and unfinished() and not control().get("paused"):
                        ok, err = start()
                        log("directory build: carrying on where it stopped" if ok else f"directory build not continued: {err}")
                    elif upkeep_due() and not _busy():
                        ok, err = start(mode="weekly")
                        if ok:
                            log("directory (built here): weekly upkeep started")
            except Exception as e:
                log(f"directory build background failed: {type(e).__name__}: {e}")
            first = False
            time.sleep(1800)
    threading.Thread(target=loop, daemon=True, name="directory-build-bg").start()


# ---------------------------------------------------------------- routes
def handle_get(h, path, pid):
    if path != "/api/localdir":
        return False
    try:
        h._send(200, status(pid))
    except Exception as e:
        print("localdir status failed:", type(e).__name__, e, flush=True)
        h._send(200, {"source": directory.source(), "possible": False, "running": False, "error": True})
    return True


def handle_post(h, path, body, pid):
    if path == "/api/localdir/start":
        add = body.get("add")
        if add in (None, "", "none", False):
            add = None
        elif add != "all":
            try:
                add = max(1, min(100000, int(add)))
            except (TypeError, ValueError):
                add = "all"
        if metered() and not body.get("metered_ok"):
            dm = data_use()["first_mb"]
            h._send(409, {"metered": True, "error": f"Windows says this internet connection is metered (data may be limited or cost money). "
                                                    f"A first build uses about {dm:,} MB."})
            return True
        try:
            ok, err = start(pid, add=add, fresh=bool(body.get("fresh")))
        except Exception as e:
            print("localdir start failed:", type(e).__name__, e, flush=True)
            ok, err = False, "The build couldn’t start. Nothing was changed."
        if not ok:
            h._send(409, {"error": err})
            return True
        S._actlog("directory build started", pid, "Build my own directory")
        h._send(200, {"ok": True, **status(pid)})
        return True
    if path == "/api/localdir/pause":
        pause()
        h._send(200, {"ok": True, **status(pid)})
        return True
    if path == "/api/localdir/prefs":
        kw = {}
        if body.get("source") in directory.SOURCES:
            kw["source"] = body["source"]
        if "discover" in body:
            kw["discover"] = bool(body["discover"])
        before = directory.source()
        directory.save_prefs(**kw)
        if kw.get("source") == "shared" and running():
            pause()             # (they went back to the shared directory only)
        if kw.get("source") and kw["source"] != before:
            S._actlog("settings changed", pid, f"Where my directory comes from: {kw['source']}")
            try:
                import first_search
                first_search._CACHE.clear()
            except Exception:
                pass
        h._send(200, {"ok": True, **status(pid)})
        return True
    return False


def main(argv=None):
    """The child process: read job sites until done or told to stop (index_build/local.py)."""
    from index_build import local
    return local.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
