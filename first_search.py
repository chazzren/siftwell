"""Start my job search: the first search for a profile (the last step of /setup and the board's Start card).

What it runs, in order, in one background thread:
  1. Find employers near the person's home (employer_finder, the standard Medium search; remote-only people get the
     "Remote-friendly employers in my field" kind instead). It runs through catalog_api's Find employers thread, so it
     uses the same job lock, progress and Stop as the Catalog page. Every employer Siftwell can read is then added to the
     person's "Near me" list (near-<pid>, which people.company_sets() already watches). Skipped when Claude isn't
     connected, when the person has no home ZIP (and isn't remote-only), or when a search for this place already ran
     for them (they can still ask to "Look for more").
  2. The first job fetch: exactly what the board's Find new jobs (Update) button runs (server.run_update). When the
     catalog was already fully fetched today, only the newly added employers are fetched.
  3. The fetch rebuilds every board and (with Claude) rates the new jobs, as every update does.

Routes (wired in server.py): GET /api/search -> status(pid), POST /api/search/start -> start(pid, find)."""
import datetime as dt
import threading
import time

import catalog
import people

S = None          # the server module (configure)
SIZE = "medium"   # the standard Find employers size (not Exhaustive)
PER_MINUTE = 12   # rough companies checked per minute on a first fetch (for the "about N minutes" estimate)
JOB = {"running": False, "pid": None, "phase": "", "find": False, "find_run": None, "added": 0, "note": "",
       "error": None, "started": None, "finished": None}
_LOCK = threading.Lock()


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
    # A finished search for this place isn't run again by default ("Look for more" asks for it); a stopped one resumes.
    find["default"] = find["possible"] and not (prior and prior["status"] in ("ok", "partial", "budget"))
    expected = mine + (find["size"] // 2 if find["default"] else 0)
    stats = catalog.stats()
    return {"claude": claude, "companies": mine, "catalog": total, "find": find,
            "fetch_minutes": max(2, round((total + (expected - mine)) / PER_MINUTE)),
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


def start(pid, find=None):
    """Start the search for this person. find: True / False, or None for the plan's default. Returns (ok, error)."""
    p = plan(pid)
    want_find = p["find"]["default"] if find is None else bool(find) and p["find"]["possible"]
    if not want_find and not p["companies"] and not p["catalog"]:
        return False, "There are no companies to check yet. Add one by its careers link in the Catalog" + (
            "." if p["claude"] else ", or connect Claude so Siftwell can find employers near you.")
    with _LOCK:
        if JOB["running"]:
            return False, "A job search is already running."
        JOB.update(running=True, pid=pid, phase="find" if want_find else "fetch", find=want_find, find_run=None, added=0,
                   note="", error=None, started=_now(), finished=None)
    import setup_flow
    setup_flow._write(pid, {"search_started": _now()})
    threading.Thread(target=_work, args=(pid, want_find, p), daemon=True, name="first-search").start()
    return True, None


def _set(**kw):
    with _LOCK:
        JOB.update(**kw)


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


def _work(pid, want_find, p):
    try:
        added = []
        if want_find:
            try:
                added = _run_find(pid, p)
            except Exception as e:
                _set(note=f"Finding employers near you didn't work this time ({type(e).__name__}: {str(e)[:120]}).")
        _set(phase="fetch")
        mine, total = watched_companies(pid)
        if not total:
            _set(error="There are no companies to check yet. Add one by its careers link in the Catalog.")
            return
        # The first fetch: the same thing Find new jobs (Update) runs. If an update is already running and nothing was
        # added, that update does the job; otherwise wait for it and run ours.
        if not added and S.state.get("running"):
            while S.state.get("running"):
                time.sleep(3)
            return
        fresh = catalog.stats().get("last_full_fetch") == dt.date.today().isoformat()
        if fresh and not added:  # every company was checked today already: the board just needs rebuilding from the catalog
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
        while not S.claim_update():
            time.sleep(3)
        only = ",".join(added) if added and fresh else None
        S._actlog("update started", pid, "Start my job search" + (f": {len(added)} new employers" if only else ""))
        S.run_update(only)
    except Exception as e:
        _set(error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        _set(running=False, phase="done", finished=_now())
