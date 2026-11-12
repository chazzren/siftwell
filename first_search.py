"""Start my job search: the first search for a profile (the last step of /setup and the board's Start card).

What it runs, in order, in one background thread:
  1. The Siftwell employer directory (directory.py; free, no key, no Claude): every indexed employer within the person's
     radius (the top remote-friendly ones for remote-only searches) goes on their "Near me" list (near-<pid>, which
     people.company_sets() already watches), plus the job-snapshot sources with postings near them. Takes seconds.
     Skipped without a home ZIP (unless remote-only); offline it just notes that the directory couldn't be reached.
  2. Only when the person asks for it ("Find more with Claude", never by default): Claude's Find employers near the
     person's home (employer_finder, the standard Medium search; remote-only people get the "Remote-friendly employers
     in my field" kind instead). It runs through catalog_api's Find employers thread, so it uses the same job lock,
     progress and Stop as the Catalog page. Every employer Siftwell can read is then added to the Near me list too.
     Not possible when Claude isn't connected or the person has no home ZIP (and isn't remote-only).
  3. The first check of the employers, staged so the board fills in as it goes (_check): the companies this person
     watches that haven't been checked yet (on a first search also the ones not checked today) are fetched in chunks,
     the ones with the most jobs near the person first (directory.near_order). Each chunk is one ordinary update for
     those companies (server.run_update --only ...); the boards are rebuilt after the first chunk (minutes) and every
     few minutes after, and Claude rates once, with the last chunk. One progress line: "Checking employers: 184 of
     1,043". Nothing is kept in memory that matters: what is left is simply "watched companies never fetched"
     (pending), so after Pause, a crash or a restart the board offers Continue checking (start_checking), and a
     regular update in between just shortens the list.
  4. Starters (shipped packs, the directory's "maybe near" big boards) with nothing near the person are pruned.

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
PER_MINUTE = 12   # rough companies checked per minute on a first fetch (for the "about N minutes" estimate)
CHUNK_FIRST = 15  # employers in the first chunk (so jobs show up within minutes)
CHUNK = 40        # employers per chunk after that
REBUILD_SECS = 240  # boards are rebuilt after a chunk when the last rebuild is at least this old
JOB = {"running": False, "pid": None, "phase": "", "find": False, "find_run": None, "added": 0, "note": "",
       "dir": False, "dir_added": 0, "dir_near": 0, "error": None, "started": None, "finished": None,
       "check_left": 0, "check_chunk": 0, "pausing": False, "paused": False}
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
    mine = sum(1 for c in cos if set(c.get("sets") or ["tech"]) & watch)
    return mine, len(cos)


def _watched(pid):
    """This person's watched, unpaused companies Siftwell has a reader for."""
    import netsafe
    watch = people.company_sets(pid)
    return [c for c in catalog.companies(include_paused=False)
            if set(c.get("sets") or ["tech"]) & watch and c.get("ats") in netsafe.CONFIG_RULES]


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
    """{total, done, pending, running, mine, pausing} for the board's one progress line. While a check runs, done
    counts what this run has finished (plus the running chunk's progress)."""
    with _LOCK:
        job = dict(JOB)
    running = bool(job["running"] and job["phase"] == "check")
    hit = _CACHE.get(pid)
    if not hit or time.time() - hit[0] > (4 if running else 20):
        cos = _watched(pid)
        hit = _CACHE[pid] = (time.time(), len(cos), len(due(pid, cos=cos)))
    total, left = hit[1], hit[2]
    mine = job["pid"] == pid
    if running and mine:
        with S.lock:
            cur = S.state.get("done", 0) if S.state.get("running") and S.state.get("phase") == "fetch" else 0
        left = max(0, job["check_left"] - min(cur, job["check_chunk"]))
    return {"total": total, "pending": left, "done": max(0, total - left), "running": running, "mine": mine,
            "pausing": bool(running and job["pausing"]), "paused": bool(mine and job["paused"] and not job["running"])}


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
    expected = mine + (100 if dirp["default"] and not drec.get("applied") else 0)
    stats = catalog.stats()
    chk = check_status(pid)
    return {"claude": claude, "companies": mine, "catalog": total, "find": find, "directory": dirp, "check": chk,
            "checked": chk["done"], "fetch_minutes": max(2, round((total + (expected - mine)) / PER_MINUTE)),
            "started_before": bool(st.get("search_started")), "last_full_fetch": stats.get("last_full_fetch"),
            "open_listings": stats.get("open", 0)}


def status(pid):
    """Plan + what is running now (this search, a Find employers search, an update)."""
    import employer_finder as ef
    with _LOCK:
        job = dict(JOB)
    with S.lock:
        up = {k: S.state.get(k) for k in ("running", "phase", "done", "total", "exit", "finished")}
    out = {"plan": plan(pid), "job": job, "mine": job["pid"] == pid, "update": up, "find_live": _find_live(), "find": None}
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
    return out


def start(pid, find=None, directory=None):
    """Start the search for this person. find (Claude) / directory: True / False, or None for the plan's default.
    Returns (ok, error)."""
    p = plan(pid)
    want_find = p["find"]["default"] if find is None else bool(find) and p["find"]["possible"]
    want_dir = p["directory"]["default"] if directory is None else bool(directory) and p["directory"]["possible"]
    if not want_find and not want_dir and not p["companies"] and not p["catalog"]:
        return False, ("There are no companies to check yet. Add your home ZIP so Siftwell can add employers near you, "
                       "or add a company by its careers link in the Catalog.")
    with _LOCK:
        if JOB["running"]:
            return False, "A job search is already running."
        JOB.update(running=True, pid=pid, phase="directory" if want_dir else "find" if want_find else "fetch", find=want_find,
                   find_run=None, added=0, note="", dir=want_dir, dir_added=0, dir_near=0, error=None, started=_now(),
                   finished=None, check_left=0, check_chunk=0, pausing=False, paused=False)
    _PAUSE.clear()
    import setup_flow
    setup_flow._write(pid, {"search_started": _now()})
    threading.Thread(target=_work, args=(pid, want_find, p, want_dir), daemon=True, name="first-search").start()
    return True, None


def start_checking(pid, rate=True):
    """Continue checking: fetch this person's never-checked companies, staged (also what "Add employers near me" runs).
    Returns (ok, error)."""
    if not pending(pid):
        return False, "Every employer on your lists has been checked already."
    with _LOCK:
        if JOB["running"]:
            return False, "A job search is already running."
        JOB.update(running=True, pid=pid, phase="check", find=False, find_run=None, added=0, note="", dir=False, dir_added=0,
                   dir_near=0, error=None, started=_now(), finished=None, check_left=0, check_chunk=0, pausing=False,
                   paused=False)
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
    """Stop the staged check after the chunk that is running (minutes). True when there was one to pause."""
    with _LOCK:
        if not (JOB["running"] and JOB["phase"] == "check"):
            return False
        JOB["pausing"] = True
    _PAUSE.set()
    return True


def _set(**kw):
    with _LOCK:
        JOB.update(**kw)


def _check(pid, stale, rate=True):
    """The staged first check (see the module docstring). Returns the number of companies it fetched."""
    queue = due(pid, stale)
    _set(phase="check", check_left=len(queue), check_chunk=0)
    _CACHE.pop(pid, None)
    done, fails, first, last_build, tried = 0, 0, True, 0.0, set()
    while True:
        if _PAUSE.is_set():
            _set(paused=True, note="Paused. The employers checked so far are on your board; press Continue checking to do the rest.")
            break
        # what is still unchecked right now (an update that ran in between may have done some of it)
        left_now = set(due(pid, stale))
        queue = [n for n in queue if n in left_now and n not in tried]
        _set(check_left=len(queue), check_chunk=0)
        if not queue:
            break
        chunk = queue[:CHUNK_FIRST if first else CHUNK]
        while not S.claim_update():
            if _PAUSE.is_set():
                break
            time.sleep(3)
        if _PAUSE.is_set() and not S.state.get("running"):
            continue
        last = len(queue) <= len(chunk)
        build = first or last or time.time() - last_build >= REBUILD_SECS
        flags = [] if (last and rate) else ["--no-rate"] + ([] if build else ["--no-boards"])
        _set(check_chunk=len(chunk))
        if first:
            S._actlog("update started", pid, f"Checking employers: {len(queue)} to check, most jobs nearby first")
        S.run_update(",".join(chunk), flags=flags, quiet=True)
        tried.update(chunk)
        _CACHE.pop(pid, None)
        if S.state.get("exit") not in (0, 3):
            fails += 1
            if fails >= 2:
                _set(error="Checking employers stopped because two rounds in a row failed. Press Continue checking to try again.")
                break
            tried.difference_update(chunk)   # (one more try for these)
            time.sleep(5)
            continue
        fails, first = 0, False
        done += len(chunk)
        if build:
            last_build = time.time()
    S._actlog("update finished" if not _PAUSE.is_set() else "update stopped", pid, f"Checking employers: {done} checked this time")
    if done:
        _prune(pid)
        if last_build and time.time() - last_build > 5 and (S.state.get("exit") in (0, 3)):
            S.request_recompute([pid])   # (the last chunk before a pause may not have rebuilt the boards)
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
            entry["sets"] = sorted(set(co.get("sets") or ["tech"]) | {want})
            catalog.save_company(entry)
            out.append(co["name"])
    return out


def _run_directory(pid):
    """Step 1: the Siftwell directory's employers near this person onto their Near me list. Returns their names."""
    import directory
    r = directory.apply(pid)
    if not r["available"]:
        return []
    names = r["added"] + r["linked"]
    if r.get("starters") and r.get("offline"):
        _set(note="Siftwell couldn't download its employer directory this time, so it started with the large US employers it comes with; "
                  "after this first check it keeps the ones hiring near you. Nearby employers from the directory are added once it can be reached.")
    elif r.get("starters"):
        _set(note="The employer directory doesn't cover your area yet, so Siftwell also started with the large US employers it comes with; "
                  "after this first check it keeps the ones hiring near you.")
    _set(dir_added=len(names), dir_near=r["near"])
    S._actlog("companies added", pid, f"{len(names)} from the Siftwell directory"
              + (f" ({r['starters']} from the shipped large-employer list)" if r.get("starters") else ""))
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


def _work(pid, want_find, p, want_dir=False):
    try:
        added = []
        if want_dir:
            try:
                added += _run_directory(pid)
            except Exception as e:
                _set(note=f"The employer directory didn't work this time ({type(e).__name__}: {str(e)[:120]}).")
        if want_find:
            _set(phase="find")
            try:
                added += _run_find(pid, p)
            except Exception as e:
                _set(note=f"Finding employers near you didn't work this time ({type(e).__name__}: {str(e)[:120]}).")
        _set(phase="fetch")
        mine, total = watched_companies(pid)
        if not total:
            _set(error="There are no companies to check yet. Add one by its careers link in the Catalog.")
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
