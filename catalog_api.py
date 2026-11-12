"""Routes for the Catalog page (/catalog and /api/catalog/*), kept out of server.py.

The server calls handle_get / handle_post with its request handler; `S` is the server module (set by configure), used
for the shared update state, the board-rebuild queue, the schedule and the rating jobs.
Every change to the catalog here queues a board rebuild for everyone (S.request_recompute())."""
import datetime as dt
import json
import os
import re
import secrets
import threading
from urllib.parse import parse_qs

import catalog
import people

S = None
FIND = {"thread": None, "stop": None, "run_id": None, "lines": [], "waiting": None}
_FLOCK = threading.Lock()
_BOARDS = {}   # pid -> {"mtime", "jobs": {id: (tier, fit, stale, unmet)}, "summary": {...}}
_BLOCK = threading.Lock()
IMPORT_DIR = "imports"   # in DATA: uploaded .siftwell files waiting for the Add click (deleted after, or after a day)


def configure(server_module):
    global S
    S = server_module


def find_live():
    t = FIND["thread"]
    return bool(t and t.is_alive())


# ---------------------------------------------------------------- lists and boards
def lists(pid=None):
    """Who a newly added employer is for: this person ("Your employers") or everyone in the household. There are no
    other lists: the shared category lists of earlier versions are gone (catalog.move_lists)."""
    pid = pid or people.current()
    return [{"id": f"own-{pid}", "label": "Your employers"}, {"id": "all", "label": "Everyone in the household"}]


def _list_id(body, pid, default):
    """The catalog list id for an add: "all" when the page asked for everyone, else this person's own list (default:
    own-<id>, or near-<id> for employers found near them, which the weekly directory check may prune)."""
    return "all" if str(body.get("list") or "") == "all" else f"{default}-{pid}"


def _watchers(sets, names):
    """Plain words for who watches a company: profile names, or "everyone"."""
    if "all" in sets:
        return ["everyone"]
    out = []
    for s in sets:
        p = s.split("-", 1)[1] if s.startswith(("own-", "near-")) else None
        if p in names and names[p] not in out:
            out.append(names[p])
    return out


def _board(pid):
    """This person's current board, indexed by listing id (cached until jobs.json changes)."""
    p = people.pdir("jobs.json", pid=pid)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    with _BLOCK:
        hit = _BOARDS.get(pid)
        if hit and hit["mtime"] == mt:
            return hit
        try:
            with open(p, encoding="utf-8") as f:
                b = json.load(f)
        except (OSError, ValueError):
            return hit
        jobs = {}
        s = {"passing": 0, "rated": 0, "deep": 0, "opus": 0, "sonnet": 0, "haiku": 0, "stale": 0, "unrated": 0, "unmet": 0}
        for j in b.get("jobs") or []:
            tier, fit, stale, unmet = j.get("ai_tier"), j.get("ai_fit"), bool(j.get("ai_stale")), j.get("req_status") == "unmet"
            jobs[j["id"]] = (tier if fit is not None else None, fit, stale, unmet)
            s["passing"] += 1
            if unmet:
                s["unmet"] += 1
            if fit is not None:
                s["rated"] += 1
                if tier in ("haiku", "sonnet", "opus"):
                    s[tier] += 1
                if tier in ("sonnet", "opus"):
                    s["deep"] += 1
                if stale:
                    s["stale"] += 1
            elif not unmet:
                s["unrated"] += 1
        s["backlog"] = s["unrated"] + s["stale"]
        s["generated"] = b.get("generated")
        hit = {"mtime": mt, "jobs": jobs, "summary": s}
        _BOARDS[pid] = hit
        return hit


# ---------------------------------------------------------------- GET
def plain_reason(status, error):
    """What went wrong with an employer's last check, in plain words for the Employers page. The stored note is a
    log line ("incomplete fetch (capped at 300 of 500 job pages; 79 of 300 job pages failed to load); missing postings
    kept open"); the page says what it means for the person."""
    e = str(error or "")
    if not e:
        return ""
    if status == "capped":
        m = re.search(r"(\d[\d,]*) of (\d[\d,]*)", e)
        if "time budget" in e or "ran out" in e:
            return "This employer has more openings than Siftwell could read in one go. It kept what it read and reads the rest next time; nothing was closed."
        return ("Siftwell read " + (f"{m.group(1)} of this employer’s {m.group(2)} job pages" if m else "only part of this employer’s job pages")
                + " this time (the site limits how many can be read at once). The jobs it couldn’t read stay open on your board.")
    if status == "suspect":
        m = re.search(r"returned (\d+|no) postings but (\d+) were open", e)
        return (f"The last check came back with {'no' if m and m.group(1) == 'no' else (m.group(1) if m else 'far fewer')} jobs where there were {m.group(2) if m else 'more'} before. "
                "That usually means the site had a hiccup, so Siftwell kept the earlier jobs open and will check again.") if m else \
            "The last check came back with far fewer jobs than before, so Siftwell kept the earlier jobs open and will check again."
    if status == "error":
        low = e.lower()
        if "404" in low or "not found" in low:
            return "The employer’s job page wasn’t found (it may have moved). Its jobs stay as they were; try Check now, or add the employer again from its careers link."
        if "403" in low or "401" in low or "forbidden" in low:
            return "The employer’s job site refused the request this time. Its jobs stay as they were; Siftwell tries again at the next check."
        if "timed out" in low or "timeout" in low or "urlopen" in low or "connection" in low:
            return "The employer’s job site didn’t answer in time. Its jobs stay as they were; Siftwell tries again at the next check."
        return "The employer’s job site couldn’t be read this time. Its jobs stay as they were; Siftwell tries again at the next check."
    return e


def handle_get(h, path, pid):
    q = {k: v[0] for k, v in parse_qs(h.path.partition("?")[2]).items()}
    if path == "/catalog":
        import catalog_page
        return h._send(200, catalog_page.render(pid), "text/html")
    if path == "/api/catalog/companies":
        import company_research
        try:
            facts = company_research.status_for()
        except Exception:
            facts = {}
        cos = []
        watch, names = people.company_sets(pid), {p["id"]: p["name"] for p in people.load_index()}
        for c in catalog.companies():
            f = c["_fetch"]
            status = "paused" if c["_paused"] else (f["status"] or "new")
            cos.append({"name": c["name"], "ats": c["ats"], "mine": bool(set(c.get("sets") or []) & watch), "watchers": _watchers(c.get("sets") or [], names), "paused": c["_paused"],
                        "status": status, "fetch_status": f["status"], "reason": plain_reason(f["status"], f["error"]), "last": f["at"], "open": f["open"] or 0,
                        "abroad": bool(f.get("abroad")), "foreign": f.get("foreign") or 0,
                        "raw": f["raw"], "secs": f["secs"], "sector": c.get("sector") or "", "added_by": c.get("added_by"),
                        "facts": facts.get(c["name"])})
        return h._send(200, {"companies": cos, "lists": lists(pid), "current": pid, "stats": catalog.stats(),
                             "facts_job": facts_status()})
    if path == "/api/catalog/facts":
        return h._send(200, facts_status())
    if path == "/api/catalog/listings":
        ppl = people.load_index()
        boards = {p["id"]: _board(p["id"]) for p in ppl}
        who, only = q.get("who", ""), None
        if who == "any":
            only = set().union(*[set(b["jobs"]) for b in boards.values() if b]) if any(boards.values()) else set()
        elif who in boards:
            only = set(boards[who]["jobs"]) if boards[who] else set()
        try:
            page, per = int(q.get("page") or 1), int(q.get("per") or 50)
            if not (1 <= page <= 10**6):
                raise ValueError
            rows, total = catalog.find_listings(q.get("q", "")[:200], q.get("state", "open"), q.get("company", "")[:80],
                                                page, per, q.get("sort", "last_seen"), only)
        except (ValueError, OverflowError):
            return h._send(400, {"error": "bad page"})
        for r in rows:
            r["people"] = []
            for p in ppl:
                b = boards.get(p["id"])
                hit = b and b["jobs"].get(r["id"])
                if hit:
                    tier, fit, stale, unmet = hit
                    r["people"].append({"id": p["id"], "name": p["name"], "tier": tier, "fit": fit, "stale": stale, "unmet": unmet})
        return h._send(200, {"rows": rows, "total": total, "page": page, "per": max(10, min(200, per))})
    if path == "/api/catalog/runs":
        runs = catalog.runs(80)
        job = __import__("joblock").info()
        for r in runs:
            d = r.get("details") or {}
            if r["status"] == "running" and not (job and job["alive"]) and not (r["kind"] == "find" and find_live()):
                r["status"] = "interrupted"  # its process is gone (e.g. Siftwell was closed mid-run)
            if r["kind"] == "find":
                r["details"] = {k: d.get(k) for k in ("location", "label", "radius", "size", "categories", "person", "error", "passes", "budget")}
        with S.lock:
            st = dict(S.state)
        nr = S.next_run()
        return h._send(200, {"runs": runs, "schedule": S.schedule(), "next_run": nr.isoformat(timespec="minutes") if nr else None,
                             "status": st, "job": __import__("joblock").info(), "stats": catalog.stats()})
    if path == "/api/catalog/rating":
        out = []
        for p in people.load_index():
            b = _board(p["id"])
            out.append({"id": p["id"], "name": p["name"], "summary": b["summary"] if b else None,
                        "profile": os.path.exists(people.pdir("profile.json", pid=p["id"])), "rerate": S.rating_status(p["id"])})
        return h._send(200, {"people": out, "current": pid})
    if path == "/api/catalog/find":
        import employer_finder as ef
        run = ef.latest()
        live = find_live() and FIND["run_id"] == (run or {}).get("id")
        if run and run["status"] == "running" and not live:
            catalog.update_run(run["id"], status="stopped", finished=True)  # the server restarted mid-search: resumable
            run["status"] = "stopped"
        out = {"categories": [{"id": c[0], "label": c[1]} for c in ef.CATEGORIES], "sizes": ef.SIZES, "estimate": ef.ESTIMATE,
               "exhaustive": {"budget": ef.BUDGET_DEFAULT, "min": ef.BUDGET_MIN, "max": ef.BUDGET_MAX, "min_new": ef.MIN_NEW},
               "defaults": ef.defaults(pid), "claude": ef.claude_status(), "live": live, "lines": FIND["lines"][-6:],
               "waiting": FIND["waiting"] if live else None, "lists": lists(pid), "current": pid, "run": None}
        if run:
            d = dict(run.get("details") or {})
            d.pop("pid", None)
            sig = ef.signature(run["id"])
            out["run"] = {"id": run["id"], "status": run["status"], "started": run["started"], "finished": run["finished"],
                          "details": d, "counts": ef.counts(run["id"]), "systems": ef.systems(run["id"]), "sig": sig}
            if q.get("have") != f"{run['id']}:{sig}":  # (the page already has this list: skip it)
                out["run"]["candidates"] = ef.candidates(run["id"])
        return h._send(200, out)
    if path == "/api/catalog/find/estimate":
        import employer_finder as ef
        try:
            est = ef.estimate(q.get("location", ""), q.get("radius", ""), q.get("cats", "").split(","), q.get("budget"))
        except ValueError as e:
            return h._send(400, {"error": str(e)})
        return h._send(200, est)
    return h._send(404, {"error": "not found"})


# ---------------------------------------------------------------- POST
def _start_fetch(only=None):
    """Start an update (all companies, or a comma-separated list) unless one is running or waiting. Returns
    (started, error). The update counts as running only once it holds the job lock (run_update(defer_running=True)):
    while it waits (e.g. for Find employers), Remove and Import still work."""
    with S.lock:
        if any(v.get("running") for v in S.RERATE.values()):
            return False, "Re-rating is running. Fetch when it finishes."
        if S.state["running"]:
            return False, "An update is already running. Try again when it finishes."
        if S.state.get("queued"):
            return False, "An update is already waiting to start. Try again when it finishes."
        S.state["queued"] = True

    def go():
        try:
            S.run_update(only, defer_running=True)
        finally:
            with S.lock:
                S.state["queued"] = False
    threading.Thread(target=go, daemon=True).start()
    return True, None


FACTS = {"running": None, "last": None}   # the Catalog's "Look up facts" button: company being looked up, last result


def facts_status():
    import company_research
    with _FLOCK:
        out = {"running": FACTS["running"], "last": FACTS["last"]}
    try:
        out["claude"] = bool(company_research.ready())
    except Exception:
        out["claude"] = False
    return out


def _facts_thread(name, pid):
    import company_research, joblock
    ok, msg = False, ""
    try:
        with joblock.hold("company facts", timeout=30):
            ok, msg = company_research.research_and_save(name)
    except joblock.Busy as e:
        msg = f"Waiting too long for the running {e} to finish. Try again later."
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:200]}"
    with _FLOCK:
        FACTS["running"] = None
        FACTS["last"] = {"name": name, "ok": ok, "message": "" if ok else msg, "at": dt.datetime.now().isoformat(timespec="seconds")}
    S._actlog("company facts looked up" if ok else "company facts failed", pid, name)
    if ok:
        S.request_recompute()  # Appeal and the Companies view pick up the new facts


def _start_find_thread(run_id):
    import employer_finder as ef
    stop = threading.Event()

    def log(m):
        if not m.startswith("Waiting for"):
            FIND["waiting"] = None  # (the search has the job lock now)
        with _FLOCK:
            FIND["lines"] = (FIND["lines"] + [m])[-30:]

    def waiting(kind):
        FIND["waiting"] = kind
        log(f"Waiting for the running {kind} to finish...")

    def work():
        try:
            ef.run(run_id, stop, on_wait=waiting, log=log)
        finally:
            FIND["waiting"] = None
            S.flush_recompute()
    with _FLOCK:
        if find_live():
            return False
        FIND.update(stop=stop, run_id=run_id, lines=[], waiting=None)
        FIND["thread"] = threading.Thread(target=work, daemon=True, name="find-employers")
        FIND["thread"].start()
    return True


def _clean_imports():
    d = os.path.join(S.DATA, IMPORT_DIR)
    if not os.path.isdir(d):
        return
    import time
    for n in os.listdir(d):
        p = os.path.join(d, n)
        try:
            if time.time() - os.path.getmtime(p) > 86400:
                os.remove(p)
        except OSError:
            pass


def _remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def handle_import_upload(h, pid):
    """POST /api/catalog/import/preview with the raw .siftwell file as the body. The upload is streamed to
    DATA/imports/<token>.siftwell in chunks (never held in memory whole) and deleted again if it can't be read."""
    import catalog_share
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        n = -1
    if n <= 0:
        return h._send(400, {"error": "Choose a .siftwell file first."})
    if n > catalog_share.MAX_FILE:
        return h._send(413, {"error": "That file is too big."})
    _clean_imports()
    os.makedirs(os.path.join(S.DATA, IMPORT_DIR), exist_ok=True)
    token = secrets.token_hex(8)
    p = os.path.join(S.DATA, IMPORT_DIR, token + ".siftwell")
    try:
        left = n
        with open(p, "wb") as f:
            while left > 0:
                chunk = h.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            raise ValueError("The upload was cut off. Choose the file again.")
        pv = catalog_share.preview(p)
    except ValueError as e:
        _remove(p)
        return h._send(400, {"error": str(e)})
    except Exception as e:
        _remove(p)
        print("catalog import preview failed:", type(e).__name__, str(e)[:200], flush=True)
        return h._send(400, {"error": "That share file couldn't be read."})
    return h._send(200, {"ok": True, "token": token, **pv})


def handle_post(h, path, body, pid):
    import company_add
    if path == "/api/catalog/add":
        url = str(body.get("url") or "").strip()
        if not url:
            return h._send(400, {"error": "Paste a careers page link first."})
        set_id = _list_id(body, pid, "own")
        try:
            res = company_add.add(url, str(body.get("name") or "")[:60], target_set=set_id)
        except ValueError as e:
            return h._send(400, {"error": str(e)})
        h._act("company added", pid, res.get("name"))
        started, _ = _start_fetch(res["name"])
        if not started:
            S.request_recompute()
        return h._send(200, {"ok": True, **res, "fetching": started})
    if path == "/api/catalog/watch":   # put a company on this person's employers, or take it off (it stays in the catalog)
        name = str(body.get("name") or "")
        co = next((c for c in catalog.companies() if c["name"] == name), None)
        if co is None:
            return h._send(404, {"error": "That company isn't in the catalog."})
        sets = set(co.get("sets") or [])
        if body.get("on"):
            sets.add(f"own-{pid}")
        else:
            if "all" in sets and not sets & {f"own-{pid}", f"near-{pid}"}:
                return h._send(409, {"error": "This one was added for everyone in the household. Use Remove to take it away for everyone."})
            sets -= {f"own-{pid}", f"near-{pid}"}
        with catalog.db() as con:
            con.execute("UPDATE companies SET sets=? WHERE name=?", (json.dumps(sorted(sets)), name))
        h._act("employer watched" if body.get("on") else "employer no longer watched", pid, name)
        S.request_recompute([pid])
        names = {p["id"]: p["name"] for p in people.load_index()}
        return h._send(200, {"ok": True, "mine": bool(sets & people.company_sets(pid)), "watchers": _watchers(sorted(sets), names)})
    if path in ("/api/catalog/pause", "/api/catalog/remove", "/api/catalog/fetch"):
        name = str(body.get("name") or "")
        if name not in {c["name"] for c in catalog.companies()}:
            return h._send(404, {"error": "That company isn't in the catalog."})
        if path == "/api/catalog/fetch":
            started, err = _start_fetch(name)
            if not started:
                return h._send(409, {"error": err})
            h._act("update started", pid, "one company")
            return h._send(202, {"ok": True})
        if path == "/api/catalog/pause":
            paused = bool(body.get("paused"))
            catalog.set_paused(name, paused)
            h._act("company paused" if paused else "company resumed", pid, name)
        else:
            with S.lock:
                if S.state["running"]:
                    return h._send(409, {"error": "An update is running. Remove it when that finishes."})
            catalog.remove_company(name)
            h._act("company removed", pid, name)
        S.request_recompute()
        return h._send(200, {"ok": True})
    if path == "/api/catalog/facts":
        import company_research, joblock
        name = str(body.get("name") or "")
        if name not in {c["name"] for c in catalog.companies()}:
            return h._send(404, {"error": "That company isn't in the catalog."})
        if not company_research.ready():
            return h._send(409, {"error": "Connect Claude to get company facts: Settings, then Get started.", "needs_claude": True})
        if name in company_research.hand_names():
            return h._send(400, {"error": "This company's facts were researched by hand and are kept as they are."})
        if S._busy():
            return h._send(409, {"error": "An update, re-rate or employer search is running. Try again when it finishes."})
        job = joblock.info()
        if job and job.get("alive"):
            return h._send(409, {"error": f"A background job is running ({job.get('kind') or 'another job'}). Try again when it finishes."})
        with _FLOCK:
            if FACTS["running"]:
                return h._send(409, {"error": f"Claude is already looking up {FACTS['running']}. Try again when it finishes."})
            FACTS["running"] = name
        h._act("company facts started", pid, name)
        threading.Thread(target=_facts_thread, args=(name, pid), daemon=True, name="company-facts").start()
        return h._send(202, {"ok": True})
    if path == "/api/catalog/find/start":
        import employer_finder as ef
        if find_live():
            return h._send(409, {"error": "A search is already running."})
        cs = ef.claude_status()
        if not cs["installed"] or not cs["signed_in"]:
            return h._send(409, {"error": "Claude Code isn't installed." if not cs["installed"] else "Claude Code is signed out.", "claude": cs})
        try:
            rid = ef.start(pid, body.get("location"), body.get("radius"), body.get("focus"), body.get("categories") or [], body.get("size"),
                           budget=body.get("budget"))
        except ValueError as e:
            return h._send(400, {"error": str(e)})
        h._act("find employers started", pid, f"{body.get('size')} search" + (f", budget {body.get('budget')} passes" if body.get("size") == ef.EXHAUSTIVE else ""))
        _start_find_thread(rid)
        return h._send(202, {"ok": True, "run_id": rid})
    if path == "/api/catalog/find/stop":
        if not find_live():
            return h._send(409, {"error": "No search is running."})
        FIND["stop"].set()
        return h._send(200, {"ok": True})
    if path == "/api/catalog/find/resume":
        import employer_finder as ef
        run = ef.latest()
        if not run or run["status"] in ("ok",):
            return h._send(409, {"error": "There's no stopped search to resume."})
        if find_live():
            return h._send(409, {"error": "A search is already running."})
        cs = ef.claude_status()
        if not cs["installed"] or not cs["signed_in"]:
            return h._send(409, {"error": "Claude Code isn't installed." if not cs["installed"] else "Claude Code is signed out.", "claude": cs})
        if body.get("budget") is not None:
            try:
                ef.set_budget(run["id"], body.get("budget"))
            except ValueError as e:
                return h._send(400, {"error": str(e)})
        elif run["status"] == "budget":
            return h._send(400, {"error": "This search used its whole budget. Raise the budget to keep going."})
        catalog.update_run(run["id"], status="running")
        h._act("find employers resumed", pid)
        _start_find_thread(run["id"])
        return h._send(202, {"ok": True})
    if path == "/api/catalog/find/add":
        import employer_finder as ef
        set_id = _list_id(body, pid, "near")
        ids = [int(x) for x in (body.get("ids") or []) if str(x).isdigit()]
        if body.get("all"):
            run = ef.latest()
            ids = [c["id"] for c in ef.candidates(run["id"]) if c["status"] == "readable"] if run else []
        if not ids:
            return h._send(400, {"error": "Tick at least one employer."})
        added = ef.add(ids, set_id, pid)
        h._act("companies added", pid, f"{len(added)} from Find employers")
        started = False
        if added:
            started, _ = _start_fetch(",".join(added))
            if not started:
                S.request_recompute()
        return h._send(200, {"ok": True, "added": added, "fetching": started})
    if path == "/api/catalog/export":
        import catalog_share, getting_started
        names = {str(x) for x in (body.get("names") or [])}
        want = set(body.get("lists") or [])
        if want:
            # "mine": every employer this person watches (the only list there is)
            names |= {c["name"] for c in catalog.companies() if people.company_sets(pid) & set(c.get("sets") or [])}
        if not names:
            return h._send(400, {"error": "Tick your employers, or at least one company."})
        data, man = catalog_share.export(sorted(names), bool(body.get("listings", True)), getting_started.VERSION)
        h._act("catalog exported", pid, f"{man['companies']} companies, {man['listings']} listings")
        fn = f"siftwell-companies-{dt.date.today().isoformat()}.siftwell"
        h.send_response(200)
        h.send_header("Content-Type", "application/zip")
        h.send_header("Content-Disposition", f'attachment; filename="{fn}"')
        h.send_header("X-Siftwell-Counts", f"{man['companies']},{man['listings']}")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        return h.wfile.write(data)
    if path == "/api/catalog/import":
        import catalog_share
        token = str(body.get("token") or "")
        set_id = _list_id(body, pid, "own")
        if not re.fullmatch(r"[0-9a-f]{16}", token):
            return h._send(400, {"error": "Choose the file again."})
        p = os.path.join(S.DATA, IMPORT_DIR, token + ".siftwell")
        if not os.path.isfile(p):
            return h._send(400, {"error": "Choose the file again."})
        with S.lock:
            if S.state["running"]:
                return h._send(409, {"error": "An update is running. Add these when it finishes."})
        try:
            out = catalog_share.apply(p, set_id, pid)
        except ValueError as e:
            _remove(p)
            return h._send(400, {"error": str(e)})
        except Exception as e:
            _remove(p)
            print("catalog import failed:", type(e).__name__, str(e)[:200], flush=True)
            return h._send(400, {"error": "That share file couldn't be imported. Nothing was changed."})
        _remove(p)
        h._act("catalog imported", pid, f"{out['new_companies']} new companies, {out['new_listings']} new listings")
        S.request_recompute()
        return h._send(200, {"ok": True, **out})
    return h._send(404, {"error": "not found"})
