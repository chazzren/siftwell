"""Start my job search: the first search for a profile (the last step of /setup and the board's Start card).

What it runs, in order, in one background thread:
  1. The Siftwell employer directory (directory.py; free, no key, no Claude): every indexed employer within the person's
     radius (the top remote-friendly ones for remote-only searches) goes on their "Near me" list (near-<pid>, which
     people.company_sets() already watches), plus the job-snapshot sources with postings near them. Takes seconds.
     Skipped without a home ZIP (unless remote-only); offline it just notes that the directory couldn't be reached.
  2. Only when the person asks for it ("Find more with Claude", never by default): Claude's Find employers near the
     person's home (employer_finder, the standard Medium search; remote-only people get the "Remote-friendly employers
     in my field" kind instead). It runs through catalog_api's Find employers thread, so it uses the same job lock,
     progress and Stop as the Catalog page. Every employer Siftwell can read is then added to their employers too.
     Not possible when Claude isn't connected or the person has no home ZIP (and isn't remote-only).
  3. The first check of the employers, staged so the board fills in as it goes (_check): the companies this person
     watches that haven't been checked yet (on a first search also the ones not checked today) are fetched in chunks,
     the ones with the most jobs near the person first (directory.near_order). Each chunk is one ordinary update for
     those companies (server.run_update --only ...); the boards are rebuilt about a minute in (while the first chunk's
     slow boards are still being read: jobfinder --boards-every), then every few minutes, and Claude rates once, with
     the last chunk. A chunk never waits long for its last few slow employers: when only a few are left and nothing
     has finished for STALL_SECS, the chunk is ended, the next one starts, and the slow ones are checked together at
     the very end (given SLOW_STALL_SECS without any progress before they are left to the next regular update).
     Nothing is kept in memory that matters: what is left is simply "watched companies never fetched" (pending), so
     after Pause, a crash or a restart the board offers Continue checking (start_checking), and a regular update in
     between just shortens the list.
  4. Starters (shipped packs, the directory's "maybe near" big boards) with nothing near the person are pruned.

ONE progress line for every page (progress(pid), sent as "progress" by /api/status and /api/search): "Checking
employers: 184 of 1,043 · your board fills in as we go", "Finding new jobs: 12 of 40 employers"... The pages show that
line and nothing else; the fetch's raw output stays behind Details on the Employers page's Runs tab. The numbers of a
staged check belong to the run (_RUN): the total is fixed when it starts (it only grows when employers are added
meanwhile) and the done count never goes down, whatever is pruned or added while it runs.

Time estimates (fetch_minutes, estimates) are worked out from the real companies and how long each one took last
time, never a fixed number.

Routes (wired in server.py): GET /api/search -> status(pid), POST /api/search/start -> start(pid, find, directory),
POST /api/search/continue -> start_checking(pid), POST /api/search/pause -> pause(pid). /api/status carries
check_status(pid) as "check" for the board's progress line."""
import datetime as dt
import threading
import time

import catalog
import people

S = None          # the server module (configure)
SIZE = "medium"   # the standard Find employers size (not Exhaustive)
CHUNK_FIRST = 15  # employers in the first chunk (so jobs show up within minutes)
CHUNK = 40        # employers per chunk after that
REBUILD_SECS = 240  # boards are rebuilt after a chunk when the last rebuild is at least this old
STALL_LEFT = 3    # a chunk with at most this many employers still running ...
STALL_SECS = 75   # ... and nothing finished for this long is ended; those employers are checked at the very end
SLOW_STALL_SECS = 900   # the last pass over the slow employers: this long without any progress and they are left for the next update
# The most time one employer may take in a chunk (jobfinder --budget): it then stops by itself, keeps what it read and
# counts as checked, well inside STALL_SECS, instead of being cut off with nothing. The slow pass at the end gives
# whoever was still cut a longer budget; anything left after that is finished by the next regular update.
CHUNK_BUDGET = 55
BUILD_WAIT = 150        # a first search with "Built on this computer" waits this long for the build's first results
SLOW_BUDGET = 600
FAST_LANES, WD_LANES = 12, 4          # jobfinder.fetch reads this many employers at once (Workday has its own lane)
DEFAULT_SECS = {"fast": 25.0, "workday": 90.0}   # one employer's check when nothing has been measured yet
JOB = {"running": False, "pid": None, "phase": "", "find": False, "find_run": None, "added": 0, "note": "",
       "dir": False, "dir_added": 0, "dir_near": 0, "error": None, "started": None, "finished": None,
       "check_left": 0, "check_chunk": 0, "pausing": False, "paused": False, "dir_offline": False, "dir_text": "",
       "slow": 0, "slow_pass": False}
# The running staged check's own counters (see the module docstring): base = watched employers that needed no check
# when it started, queued = every employer it was asked to check, finished = the ones it is done with, shown = the
# highest done count any page was told (so the number never goes back).
_RUN = {"base": 0, "queued": set(), "finished": set(), "shown": 0}
_LOCK = threading.Lock()
_PAUSE = threading.Event()
_CACHE = {}       # pid -> (time, check numbers): the board asks every couple of seconds


def configure(server_module):
    global S
    S = server_module


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _settings(pid):
    import setup_flow
    return setup_flow._settings(pid)


def find_categories(st):
    """The kinds of employers to look for: every local kind, plus remote-friendly ones when remote work is OK;
    remote-only people get just the remote-friendly kind."""
    import employer_finder as ef
    wps = st.get("workplaces") or ["onsite", "hybrid", "remote"]
    if wps == ["remote"]:
        return ["remote"]
    return [c for c in ef.CAT_IDS if c != "remote"] + (["remote"] if "remote" in wps else [])


def _place(st):
    """(location to search, label to show) from the person's home ZIP; ("", "") when none is set or it's unknown."""
    z = str(st.get("home_zip") or "").strip()
    if not z:
        return "", ""
    try:
        import geo
        return z, geo.geocode_home(z)[2]
    except Exception:
        return "", ""


def _same_place(d, pid, location):
    return d.get("pid") == pid and str(d.get("location") or "").strip().lower() == location.strip().lower()


def prior_find(pid, location):
    """The latest Find employers search this person ran for this place (or None)."""
    for r in catalog.runs(200, kind="find"):
        if _same_place(r.get("details") or {}, pid, location):
            return r
    return None


def near_count(pid):
    """Companies on this person's Near me list."""
    want = f"near-{pid}"
    try:
        return sum(1 for s in catalog.sets_map().values() if want in s)
    except Exception:
        return 0


def watched_companies(pid):
    """(companies this person watches, every company that gets checked): paused companies aren't checked."""
    watch = people.company_sets(pid)
    cos = catalog.companies(include_paused=False)
    mine = sum(1 for c in cos if set(c.get("sets") or []) & watch)
    return mine, len(cos)


def _watched(pid):
    """This person's watched, unpaused companies Siftwell has a reader for."""
    import netsafe
    watch = people.company_sets(pid)
    return [c for c in catalog.companies(include_paused=False)
            if set(c.get("sets") or []) & watch and c.get("ats") in netsafe.CONFIG_RULES]


def due(pid, stale=False, cos=None):
    """Names of this person's companies that still need their first check (stale=True: also the ones not checked
    today), the ones with the most jobs near the person first; companies the directory didn't count sit after the
    biggest ones."""
    import directory
    order = directory.near_order(pid)
    today = dt.date.today().isoformat()
    out = []
    for c in (cos if cos is not None else _watched(pid)):
        at = (c.get("_fetch") or {}).get("at")
        if not at or (stale and at[:10] < today):
            out.append(c["name"])
    out.sort(key=lambda n: (-order.get(n, 3), n.lower()))
    return out


def pending(pid):
    """Watched companies never checked yet."""
    return due(pid)


def check_status(pid):
    """{total, done, pending, running, mine, pausing, paused, dir_offline} for the pages. While this person's check
    runs, the numbers are the run's own (_RUN): they only go up."""
    with _LOCK:
        job = dict(JOB)
        run = {"base": _RUN["base"], "queued": len(_RUN["queued"]), "finished": len(_RUN["finished"])}
    running = bool(job["running"] and job["phase"] == "check")
    hit = _CACHE.get(pid)
    if not hit or time.time() - hit[0] > (6 if running else 20):
        cos = _watched(pid)
        off = False
        try:
            import directory
            off = bool(directory.record(pid).get("offline"))
        except Exception:
            pass
        hit = _CACHE[pid] = (time.time(), len(cos), len(due(pid, cos=cos)), off)
    total, left = hit[1], hit[2]
    mine = job["pid"] == pid
    if running and mine and run["queued"]:      # (not yet, in the first moment of a run: the numbers above still hold)
        with S.lock:
            cur = S.state.get("done", 0) if S.state.get("running") and S.state.get("phase") == "fetch" else 0
        total = run["base"] + run["queued"]
        done = run["base"] + run["finished"] + min(cur, job["check_chunk"])
        with _LOCK:
            done = _RUN["shown"] = max(_RUN["shown"], min(done, total))
        left = total - done
    return {"total": total, "pending": left, "done": max(0, total - left), "running": running, "mine": mine,
            "pausing": bool(running and job["pausing"]), "paused": bool(mine and job["paused"] and not job["running"]),
            "dir_offline": bool(hit[3]), "slow_pass": bool(running and mine and job["slow_pass"])}


# ---------------------------------------------------------------- honest time estimates
_AVG = {"at": 0.0, "v": None}


def _avg_secs():
    """{"fast": s, "workday": s}: what one employer's check took on average, measured from the catalog (the default
    until at least ten have been measured)."""
    if _AVG["v"] is not None and time.time() - _AVG["at"] < 120:
        return _AVG["v"]
    xs = {"fast": [], "workday": []}
    try:
        for c in catalog.companies(include_paused=False):
            sec = (c.get("_fetch") or {}).get("secs")
            if sec:
                xs["workday" if c.get("ats") == "workday" else "fast"].append(float(sec))
    except Exception:
        pass
    v = {k: (sum(x) / len(x) if len(x) >= 10 else DEFAULT_SECS[k]) for k, x in xs.items()}
    _AVG.update(at=time.time(), v=v)
    return v


def fetch_minutes(cos, first=False):
    """About how many minutes one check of these companies takes: what each took last time (the measured average for
    the ones never checked), spread over the lanes the fetch runs at once. first=True: none of them has been read
    before (every posting's text is new), so their own earlier times don't apply."""
    if not cos:
        return 0
    avg = _avg_secs()
    tot, longest = {"fast": 0.0, "workday": 0.0}, 0.0
    for c in cos:
        lane = "workday" if c.get("ats") == "workday" else "fast"
        sec = None if first else (c.get("_fetch") or {}).get("secs")
        sec = float(sec) if sec else avg[lane]
        tot[lane] += sec
        longest = max(longest, sec)
    secs = max(tot["fast"] / FAST_LANES, tot["workday"] / WD_LANES, longest) + 45 + 0.04 * len(cos)   # (+ building the boards)
    return max(1, round(secs / 60))


def minutes_text(m):
    """"about 25 minutes", "about 1 hour", "about 2½ hours" (rounded the way a person would say it)."""
    m = int(m or 0)
    if m < 1:
        return "under a minute"
    if m < 50:
        m = m if m < 10 else 5 * round(m / 5)
        return f"about {m} minute{'' if m == 1 else 's'}"
    h = round(m / 30) / 2
    if h == 1:
        return "about 1 hour"
    return f"about {int(h) if h == int(h) else str(int(h)) + '½'} hours"


_EST = {}


def estimates(pid):
    """{"all": {companies, minutes, text}, "mine": {...}, "profiles": n}: what Find new jobs costs for the whole
    household and for this profile's own employers, from the real company list (cached a minute)."""
    hit = _EST.get(pid)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    import netsafe
    watch = people.company_sets(pid)
    cos = [c for c in catalog.companies(include_paused=False) if c.get("ats") in netsafe.CONFIG_RULES]
    mine = [c for c in cos if set(c.get("sets") or []) & watch]

    def one(xs):
        m = fetch_minutes(xs)
        return {"companies": len(xs), "minutes": m, "text": minutes_text(m)}
    out = {"all": one(cos), "mine": one(mine), "profiles": len(people.ids())}
    _EST[pid] = (time.time(), out)
    return out


def mine_names(pid):
    """Names of this profile's own employers (what a profile's Find new jobs checks in a household of several)."""
    return [c["name"] for c in _watched(pid)]


# ---------------------------------------------------------------- the one progress line
def progress(pid):
    """What is running now, in one plain line, for every page: {active, kind, line, frac, mine, can_pause, pausing,
    done, total}. kind: directory / find / check / update / rate / build / other / idle."""
    with _LOCK:
        job = dict(JOB)
    with S.lock:
        up = {k: S.state.get(k) for k in ("running", "phase", "done", "total")}
        rerate = any(v.get("running") for v in S.RERATE.values())
    n = lambda x: f"{int(x or 0):,}"
    out = {"active": True, "kind": "other", "line": "", "frac": None, "mine": True, "can_pause": False, "pausing": False,
           "done": 0, "total": 0}
    mine = job["pid"] == pid
    if job["running"] and not mine:
        who = people.name(job["pid"]) if job["pid"] and people.exists(job["pid"]) else "another profile"
        return dict(out, kind="check", mine=False, line=f"Siftwell is checking employers for {who}. Find new jobs waits until that is done.")
    if job["running"]:
        ph = job["phase"]
        if ph == "directory":
            b = _build_line(pid)
            return dict(out, kind="directory", frac=.03, line=b["line"] if b else "Adding employers to check…")
        if ph == "find":
            return dict(out, kind="find", frac=.06, line="Claude is searching the web for employers. Their jobs are checked when it’s done.")
        if ph == "build":
            return dict(out, kind="build", frac=.9, line="Building your board from the jobs Siftwell already has…")
        if ph == "check":
            ck = check_status(pid)
            frac = .08 + (.87 * ck["done"] / ck["total"] if ck["total"] else 0)
            if up["running"] and up["phase"] in ("ai", "pivot"):
                return dict(out, kind="rate", frac=.96, done=ck["done"], total=ck["total"],
                            line="Almost done: Claude is reading the best matches against your resume.")
            if up["running"] and up["phase"] not in ("fetch", None):
                return dict(out, kind="build", frac=.97, done=ck["done"], total=ck["total"], line="Almost done: building your board.")
            line = f"Checking employers: {n(ck['done'])} of {n(ck['total'])} · your board fills in as we go"
            if ck["slow_pass"]:
                k = max(1, ck["total"] - ck["done"])
                line = (f"Checking employers: {n(ck['done'])} of {n(ck['total'])} · finishing the last {n(k)}, "
                        f"which {'has' if k == 1 else 'have'} a lot of openings")
            if ck["pausing"]:
                line = f"Pausing… {n(ck['done'])} of {n(ck['total'])} employers checked so far"
            return dict(out, kind="check", frac=frac, done=ck["done"], total=ck["total"], line=line,
                        can_pause=not ck["pausing"], pausing=ck["pausing"])
        return dict(out, kind="other", frac=.05, line="Getting ready…")
    if up["running"]:
        ph, d, t = up["phase"], up["done"] or 0, up["total"] or 0
        if ph == "fetch":
            return dict(out, kind="update", done=d, total=t, frac=.02 + (.8 * d / t if t else 0),
                        line=f"Finding new jobs: {n(d)} of {n(t)} employers" if t else "Finding new jobs: getting ready…")
        if ph in ("ai", "pivot"):
            return dict(out, kind="rate", frac=.88, line="Finding new jobs: Claude is rating the new ones…")
        if ph == "facts":
            return dict(out, kind="rate", frac=.97, line="Finding new jobs: looking up a few company facts…")
        return dict(out, kind="build", frac=.95, line="Finding new jobs: building your board…")
    try:
        if _find_live():
            return dict(out, kind="find", line="Claude is searching the web for employers…")
    except Exception:
        pass
    b = _build_line(pid)
    if b:
        return dict(out, **b)    # ("blocking": False: Find new jobs stays available while the directory is built)
    if rerate:
        return dict(out, active=False, kind="idle")      # (re-rating has its own panel on the board)
    try:
        import joblock
        j = joblock.info() or {}
        if j.get("alive") and not j.get("mine") and j.get("kind") not in ("recompute", "re-render"):
            return dict(out, kind="other", line="Siftwell is finishing a job that was started earlier. Find new jobs waits until that is done.")
    except Exception:
        pass
    return dict(out, active=False, kind="idle")


def _build_line(pid):
    """"Build my own directory" while it runs (localdir.progress), or None."""
    try:
        import localdir
        return localdir.progress(pid)
    except Exception:
        return None


def _claude_ok():
    import employer_finder as ef
    cs = ef.claude_status()
    return bool(cs.get("installed") and cs.get("signed_in"))


def _find_live():
    import catalog_api
    return catalog_api.find_live()


def plan(pid):
    """What Start my job search would do for this person, for the page to explain before they click."""
    import employer_finder as ef
    st = _settings(pid)
    location, label = _place(st)
    cats = find_categories(st)
    remote_only = cats == ["remote"]
    claude = _claude_ok()
    mine, total = watched_companies(pid)
    prior = prior_find(pid, location) if (location or remote_only) else None
    reason = None
    if not claude:
        reason = "no_claude"
    elif not location and not remote_only:
        reason = "no_place"
    find = {"possible": reason is None, "reason": reason, "remote_only": remote_only, "categories": cats,
            "label": label or ("anywhere in the US" if remote_only else ""), "location": location,
            "radius": int(st.get("radius_miles") or 35), "size": ef.SIZES[SIZE], "estimate": ef.ESTIMATE[SIZE],
            "near": near_count(pid), "prior": None}
    if prior:
        find["prior"] = {"status": prior["status"], "found": prior.get("companies"), "readable": prior.get("fetched"),
                         "finished": prior.get("finished")}
    # Claude's search runs only when the person ticks "Find more with Claude" (it uses their Claude plan).
    find["default"] = False
    import directory
    drec = directory.record(pid)
    dirp = {"possible": bool(location or remote_only), "label": find["label"], "radius": find["radius"],
            "remote_only": remote_only, "applied": drec.get("applied"), "default": bool(location or remote_only)}
    dirp["offline"] = bool(drec.get("offline"))
    try:
        import localdir
        dirp["build"] = localdir.brief(pid)     # "Build my own directory": running? its line; else the offer
    except Exception:
        dirp["build"] = {"running": False, "offer": ""}
    stats = catalog.stats()
    chk = check_status(pid)
    est = estimates(pid)
    return {"claude": claude, "companies": mine, "catalog": total, "find": find, "directory": dirp, "check": chk,
            "checked": chk["done"], "fetch_minutes": est["mine"]["minutes"], "estimate": est,
            "started_before": bool(st.get("search_started")), "last_full_fetch": stats.get("last_full_fetch"),
            "open_listings": stats.get("open", 0), "titles": has_titles(pid), "remote_only": remote_only,
            "legacy_area": not location and not remote_only}


def has_titles(pid):
    """True when the person has told Siftwell what work they do (job titles on their what-to-look-for sheet, or the
    older built-in title rule): without any, every title passes and the board can't put the relevant jobs first."""
    try:
        if people.settings(pid).get("title_rule") == "builtin":
            return True
        import lookfor
        return not lookfor.is_empty(lookfor.load(pid))
    except Exception:
        return True


def why_empty(pid):
    """After a search that left the board empty: one plain sentence saying why, from what Siftwell knows."""
    st = _settings(pid)
    cos = _watched(pid)
    if not cos:
        return "Siftwell isn’t watching any employers for you yet, so there was nothing to check."
    names = [c["name"] for c in cos]
    open_n = 0
    try:
        with catalog.db() as con:
            for i in range(0, len(names), 500):
                part = names[i:i + 500]
                q = f"SELECT COUNT(*) FROM listings WHERE closed_at IS NULL AND company IN ({','.join('?' * len(part))})"
                open_n += con.execute(q, part).fetchone()[0]
    except Exception:
        open_n = None
    some = f"{len(cos):,} employer{'' if len(cos) == 1 else 's'}"
    if open_n == 0:
        return (f"Siftwell checked your {some} and found no open jobs it could read. "
                "That usually means there are too few employers on your list.")
    limits = []
    wps = st.get("workplaces") or ["onsite", "hybrid", "remote"]
    location, label = _place(st)
    if wps == ["remote"]:
        limits.append("remote jobs only")
    elif location:
        limits.append(f"within {int(st.get('radius_miles') or 35)} miles of {label or location}" + (" or remote" if "remote" in wps else ", not remote"))
    if st.get("salary_floor"):
        limits.append(f"paying at least ${int(st['salary_floor']):,}")
    if st.get("seniority_mine"):
        limits.append("around your level")
    if has_titles(pid):
        limits.append("with a job title like yours")
    found = f"Your {some} have {open_n:,} open jobs" if open_n else f"Siftwell checked your {some}"
    return f"{found}, but none matched your search" + (f" ({'; '.join(limits)})" if limits else "") + "."


def status(pid):
    """Plan + what is running now (this search, a Find employers search, an update)."""
    import employer_finder as ef
    with _LOCK:
        job = dict(JOB)
    with S.lock:
        up = {k: S.state.get(k) for k in ("running", "phase", "done", "total", "exit", "finished")}
    out = {"plan": plan(pid), "job": job, "mine": job["pid"] == pid, "update": up, "find_live": _find_live(), "find": None,
           "progress": progress(pid)}
    rid = job.get("find_run")
    if rid:
        try:
            r = catalog.get_run(rid)
            n = ef.counts(rid)
            d = r.get("details") or {}
            states = [(d.get("cats") or {}).get(c, {}).get("state") for c in d.get("categories") or []]
            out["find"] = {"status": r["status"], "found": sum(sum(v.values()) for v in n.values()),
                           "readable": sum(v.get("readable", 0) + v.get("added", 0) for v in n.values()),
                           "kinds": len(states), "kinds_done": sum(1 for s in states if s in ("done", "error")),
                           "label": d.get("label") or d.get("location")}
        except Exception:
            pass
    out["running"] = bool(job["running"] or up["running"] or out["find_live"])
    if not out["running"] and out["plan"]["started_before"]:
        try:
            if not S.board_counts(pid).get("jobs"):
                out["why_empty"] = why_empty(pid)
        except Exception:
            pass
    return out


def _fresh_job(pid, phase, **kw):
    """(caller holds _LOCK) Reset JOB for a new run."""
    JOB.update(running=True, pid=pid, phase=phase, find=False, find_run=None, added=0, note="", dir=False, dir_added=0,
               dir_near=0, error=None, started=_now(), finished=None, check_left=0, check_chunk=0, pausing=False,
               paused=False, dir_offline=False, dir_text="", slow=0, slow_pass=False)
    JOB.update(kw)
    _RUN.update(base=0, queued=set(), finished=set(), shown=0)


def start(pid, find=None, directory=None, limit=None):
    """Start the search for this person. find (Claude) / directory: True / False, or None for the plan's default.
    limit: add only the N directory employers with the most openings nearby (None: all). Returns (ok, error)."""
    p = plan(pid)
    want_find = p["find"]["default"] if find is None else bool(find) and p["find"]["possible"]
    want_dir = p["directory"]["default"] if directory is None else bool(directory) and p["directory"]["possible"]
    if not want_find and not want_dir and not p["companies"] and not p["catalog"]:
        return False, ("There are no employers to check yet. Add your home ZIP so Siftwell can add employers near you, "
                       "or add an employer by its careers link on the Employers page.")
    with _LOCK:
        if JOB["running"]:
            return False, "A job search is already running."
        _fresh_job(pid, "directory" if want_dir else "find" if want_find else "fetch", find=want_find, dir=want_dir)
    _PAUSE.clear()
    import setup_flow
    setup_flow._write(pid, {"search_started": _now()})
    threading.Thread(target=_work, args=(pid, want_find, p, want_dir, limit), daemon=True, name="first-search").start()
    return True, None


def start_checking(pid, rate=True):
    """Continue checking: fetch this person's never-checked companies, staged (also what "Add employers near me" runs).
    Returns (ok, error)."""
    if not pending(pid):
        return False, "Every one of your employers has been checked already."
    with _LOCK:
        if JOB["running"]:
            return False, "A job search is already running."
        _fresh_job(pid, "check")
    _PAUSE.clear()

    def work():
        try:
            _check(pid, False, rate)
        except Exception as e:
            _set(error=f"{type(e).__name__}: {str(e)[:200]}")
        finally:
            _set(running=False, phase="done", finished=_now())
            _CACHE.pop(pid, None)
    threading.Thread(target=work, daemon=True, name="check-employers").start()
    return True, None


def pause(pid):
    """Pause the staged check now: the fetch that is running is ended (what it finished is kept; the employers it was
    in the middle of are checked again on Continue). True when there was one to pause."""
    with _LOCK:
        if not (JOB["running"] and JOB["phase"] == "check"):
            return False
        JOB["pausing"] = True
    _PAUSE.set()
    S.stop_update()
    return True


def _set(**kw):
    with _LOCK:
        JOB.update(**kw)


def note_added(pid):
    """Employers were just added for this person: when their check is running, count them in its total right away (the
    check itself picks them up after the chunk it is on), so every page shows the same, larger total at once."""
    with _LOCK:
        if not (JOB["running"] and JOB["pid"] == pid and JOB["phase"] == "check" and _RUN["queued"]):
            return
    names = due(pid)
    with _LOCK:
        _RUN["queued"].update(names)
    _CACHE.pop(pid, None)


def _fetched_since(names, t0):
    """The names among these whose check finished (well or not) at or after t0 (an ISO time)."""
    want = set(names)
    return {c["name"] for c in catalog.companies() if c["name"] in want and ((c.get("_fetch") or {}).get("at") or "") >= t0}


def _run_chunk(chunk, flags, stall):
    """One fetch of these employers (server.run_update), watched: when at most STALL_LEFT of them are still running
    (any number, for the long `stall` of a last chunk) and nothing has finished for `stall` seconds, the fetch is
    ended so the next chunk can start. Returns (cut, names not finished)."""
    t0 = catalog.now()
    th = threading.Thread(target=S.run_update, args=(",".join(chunk),), kwargs={"flags": flags, "quiet": True}, daemon=True)
    th.start()
    cut, last, last_at = False, -1, time.time()
    while th.is_alive():
        th.join(2)
        if _PAUSE.is_set() or cut:
            continue
        with S.lock:
            ph, d, t = S.state.get("phase"), S.state.get("done", 0), S.state.get("total", 0)
        if ph != "fetch" or not t or d >= t:
            last_at = time.time()       # (waiting for the job lock, or already building boards / rating)
            continue
        if d != last:
            last, last_at = d, time.time()
        elif time.time() - last_at >= stall and (t - d <= STALL_LEFT or stall >= SLOW_STALL_SECS):
            cut = S.stop_update()
    if not cut and not _PAUSE.is_set():
        return False, []
    time.sleep(1.5)                      # (the ended fetch's last writes)
    got = _fetched_since(chunk, t0)
    return cut, [n for n in chunk if n not in got]


def _check(pid, stale, rate=True):
    """The staged first check (see the module docstring). Returns the number of companies it fetched."""
    queue = due(pid, stale)
    t_start = catalog.now()
    with _LOCK:
        _RUN.update(base=max(0, len(_watched(pid)) - len(queue)), queued=set(queue), finished=set(), shown=0)
    _set(phase="check", check_left=len(queue), check_chunk=0, slow=0, slow_pass=False)
    _CACHE.pop(pid, None)
    fails, first, last_build, tried, slow, need_build, seen = 0, True, 0.0, set(), [], False, set(queue)
    while True:
        if _PAUSE.is_set():
            _set(paused=True, note="Paused. The employers checked so far are on your board; press Continue checking to do the rest.")
            break
        # what is still unchecked right now: an update that ran in between may have done some of it, and employers
        # added meanwhile (Add employers near me) join the end of the queue
        now_due = due(pid, stale)
        left_now = set(now_due)
        new = [n for n in now_due if n not in seen]
        seen.update(new)
        with _LOCK:
            _RUN["queued"].update(new)
            _RUN["finished"].update(n for n in _RUN["queued"] if n not in left_now)
        queue = [n for n in queue if n in left_now and n not in tried] + new
        slow = [n for n in slow if n in left_now]
        _set(check_left=len(queue) + len(slow), check_chunk=0, slow=len(slow))
        if not queue and not slow:
            break
        slow_pass = not queue
        chunk = slow if slow_pass else queue[:CHUNK_FIRST if first else CHUNK]
        claimed = False
        while not _PAUSE.is_set() and not claimed:
            claimed = S.claim_update()
            if not claimed:
                time.sleep(3)
        if not claimed:
            continue
        if _PAUSE.is_set():
            with S.lock:
                S.state["running"] = False
            continue
        last = slow_pass or (len(queue) <= len(chunk) and not slow)
        build = first or last or need_build or time.time() - last_build >= REBUILD_SECS
        flags = ["--boards-every", str(REBUILD_SECS)] + ([] if (last and rate) else ["--no-rate"] + ([] if build else ["--no-boards"]))
        flags += ["--budget", str(SLOW_BUDGET if slow_pass else CHUNK_BUDGET)]
        _set(check_chunk=len(chunk), slow_pass=slow_pass)
        if first:
            S._actlog("update started", pid, f"Checking employers: {len(queue)} to check, most jobs nearby first")
        # the last chunk has nothing waiting behind it, so it is only ended after a long silence
        cut, unfinished = _run_chunk(chunk, flags, SLOW_STALL_SECS if last else STALL_SECS)
        _CACHE.pop(pid, None)
        _AVG["v"] = None
        _EST.clear()
        if _PAUSE.is_set():
            need_build = True            # (the fetch was ended: the boards are rebuilt below)
            with _LOCK:
                _RUN["finished"].update(n for n in chunk if n not in unfinished)
            continue
        if cut:
            need_build, first, fails = True, False, 0
            tried.update(chunk)
            with _LOCK:
                _RUN["finished"].update(n for n in chunk if n not in unfinished)
            if last:
                # even with nothing else waiting they took too long: the next regular update (no time limit) checks them
                if unfinished:
                    _set(note=(f"{len(unfinished)} large employer{'' if len(unfinished) == 1 else 's'} took too long to read this time; "
                               "Siftwell tries again with the next Find new jobs."))
                slow = []
                break
            slow += [n for n in unfinished if n not in slow]
            continue
        if S.state.get("exit") not in (0, 3):
            fails += 1
            if fails >= 2:
                _set(error="Checking employers stopped because two rounds in a row failed. Press Continue checking to try again.")
                break
            time.sleep(5)                # (one more try for these)
            continue
        fails, first = 0, False
        tried.update(chunk)
        with _LOCK:
            _RUN["finished"].update(chunk)
        if build:
            last_build, need_build = time.time(), False
        if slow_pass:
            slow = []
    with _LOCK:
        asked = set(_RUN["queued"])
    done = len(_fetched_since(asked, t_start))     # (what was really checked, whatever was added or removed meanwhile)
    _set(slow_pass=False)
    S._actlog("update finished" if not _PAUSE.is_set() else "update stopped", pid, f"Checking employers: {done} checked this time")
    if done:
        _prune(pid)
    if need_build:
        S.request_recompute([pid])       # (a fetch that was ended didn't get to rebuild the boards)
    return done


def _run_find(pid, p):
    """Step 1. Returns the names of the employers added to the person's Near me list."""
    import catalog_api, employer_finder as ef
    f = p["find"]
    prior = prior_find(pid, f["location"])
    if prior and prior["status"] in ("stopped", "running", "error") and ef.latest() and ef.latest()["id"] == prior["id"]:
        rid = prior["id"]                  # an interrupted search for this place: carry on where it stopped
        catalog.update_run(rid, status="running")
    else:
        rid = ef.start(pid, f["location"], f["radius"], "", f["categories"], SIZE)
    _set(find_run=rid)
    if not catalog_api._start_find_thread(rid):
        _set(note="Another Find employers search was already running, so this one was skipped.")
        catalog.update_run(rid, status="stopped", finished=True)
        return []
    t = catalog_api.FIND["thread"]
    if t:
        t.join()
    r = catalog.get_run(rid)
    if (r.get("details") or {}).get("error") == "signin":
        _set(note="Claude Code is signed out, so the search for nearby employers stopped.")
    cands = ef.candidates(rid)
    ids = [c["id"] for c in cands if c["status"] == "readable"]
    added = ef.add(ids, f"near-{pid}", pid) if ids else []
    added += _link_known(pid, cands)
    S._actlog("companies added", pid, f"{len(added)} from Start my job search")
    _set(added=len(added))
    return added


KNOWN_PREFIX = "Already in your catalog as "

def _link_known(pid, cands):
    """Employers the search found that the catalog already has (e.g. another person's Near me list): put them on this
    person's Near me list too, so they watch them. Returns their names."""
    names = {c["reason"][len(KNOWN_PREFIX):] for c in cands
             if c["status"] == "known" and str(c.get("reason") or "").startswith(KNOWN_PREFIX)}
    want, out = f"near-{pid}", []
    for co in catalog.companies():
        if co["name"] in names and want not in (co.get("sets") or []):
            entry = {k: v for k, v in co.items() if not k.startswith("_")}
            entry["sets"] = sorted(set(co.get("sets") or []) | {want})
            catalog.save_company(entry)
            out.append(co["name"])
    return out


def _run_directory(pid, limit=None):
    """Step 1: the Siftwell directory's employers near this person onto their Near me list. Returns their names.
    When the directory can't be reached, the starter list of large employers the app comes with is used instead, and
    the pages say so plainly (JOB dir_offline / dir_text; directory.record(pid)["offline"])."""
    import directory, localdir
    building = False
    if directory.uses_local():
        # "Built on this computer" (or Both): make sure the build is running and that what it finds near this person
        # keeps being added (the limit they chose is the most it adds), and give it a moment to find the first ones.
        b = localdir.brief(pid)
        if b["running"] or not b["built"] or (b["unfinished"] and not b["paused"]):   # (a build they paused stays paused)
            try:
                ok, _ = localdir.start(pid, add=limit or "all")
                building = ok or localdir.running()
            except Exception as e:
                print("directory build not started:", type(e).__name__, e, flush=True)
            t0 = time.time()
            while building and not b["built"] and time.time() - t0 < BUILD_WAIT and not _PAUSE.is_set():
                time.sleep(3)
                b = localdir.brief(pid)
                if not b["running"]:
                    break
    # (while the build is filling the list in, the shipped starter list isn't needed: its employers are read anyway)
    r = directory.apply(pid, limit=limit, starters_ok=not building, first=True, tag=localdir.control().get("tag") if building else None)
    if not r["available"]:
        if building:
            _set(dir_text="Siftwell is building your directory on this computer; employers near you are added as it finds them.")
        return []
    names = r["added"] + r["linked"]
    n = len(names)
    if building:
        _set(dir_text=(f"{n:,} employer{'' if n == 1 else 's'} added so far. " if n else "") +
             "Siftwell is building your directory on this computer; employers near you are added as it finds them.")
        _set(note=JOB["dir_text"])
    elif r.get("offline"):
        text = (f"Siftwell couldn’t reach its employer directory, so it is starting with a starter list of {n:,} large US employers "
                "that comes with the app. After this first check it keeps the ones hiring near you.") if n else \
               "Siftwell couldn’t reach its employer directory, so no employers near you were added this time."
        _set(dir_offline=True, dir_text=text, note=text + " Use “Try the directory again” on your board or in Settings when you are back online.")
    elif r.get("pack_starters"):
        text = (f"{n:,} employers added. The directory doesn’t cover all of your area yet, so {r['pack_starters']:,} of them are large US "
                "employers from the starter list that comes with the app; after this first check Siftwell keeps the ones hiring near you.")
        _set(dir_text=text, note=text)
    else:
        _set(dir_text=f"{n:,} employer{'' if n == 1 else 's'} added" if n else "No new employers to add")
    _set(dir_added=n, dir_near=r["near"])
    S._actlog("companies added", pid, (f"{n} found so far by the directory build on this computer" if building else
                                      f"{n} from the starter list of large employers (the directory couldn't be reached)" if r.get("offline")
                                      else f"{n} from the Siftwell directory" + (f" ({r['starters']} to try out)" if r.get("starters") else "")))
    return names


def _prune(pid):
    """After the first fetch: shipped-pack starters (offline fallback) with no jobs near the person leave Near me."""
    import directory
    try:
        dropped = directory.prune_starters(pid)
    except Exception as e:
        print("prune_starters failed:", type(e).__name__, e, flush=True)
        return
    if dropped:
        S._actlog("companies removed", pid, f"{len(dropped)} large employers with no jobs near you (Near me)")
        S.request_recompute([pid])


def _work(pid, want_find, p, want_dir=False, limit=None):
    try:
        added = []
        if want_dir:
            try:
                added += _run_directory(pid, limit)
            except Exception as e:
                print("directory apply failed:", type(e).__name__, e, flush=True)
                _set(dir_offline=True, dir_text="Siftwell couldn’t read its employer directory this time.",
                     note="Siftwell couldn’t read its employer directory this time. Use “Try the directory again” on your board or in Settings.")
        if want_find:
            _set(phase="find")
            try:
                added += _run_find(pid, p)
            except Exception as e:
                print("find employers failed:", type(e).__name__, e, flush=True)
                _set(note="Claude’s search for employers didn’t work this time. You can run it again from the Employers page.")
        _set(phase="fetch")
        _EST.clear(); _CACHE.pop(pid, None)     # (the employer list just changed)
        mine, total = watched_companies(pid)
        if not total and _build_line(pid):
            _set(note="Siftwell is building your directory on this computer. Employers near you are added, and their jobs checked, as it finds them.")
            return
        if not total:
            _set(error=("Siftwell couldn’t reach its employer directory, so there are no employers to check yet. Check your internet "
                        "connection, then press Try the directory again." if JOB.get("dir_offline")
                        else "There are no employers to check yet. Add one by its careers link on the Employers page."))
            return
        # The first check, staged. Nothing due (every company was checked today): the board just needs rebuilding.
        fresh = catalog.stats().get("last_full_fetch") == dt.date.today().isoformat()
        if not due(pid, stale=not fresh):
            if S.state.get("running"):
                while S.state.get("running"):
                    time.sleep(3)
                return
            _set(phase="build")
            S.request_recompute([pid])
            t0 = time.time()
            while time.time() - t0 < 900:
                time.sleep(1)
                with S.lock:
                    rc = S._RECOMPUTE
                    if not (rc["running"] or rc["all"] or pid in rc["pending"]):
                        break
            return
        _check(pid, stale=not fresh)
    except Exception as e:
        _set(error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        _set(running=False, phase="done", finished=_now())
        _CACHE.pop(pid, None)
