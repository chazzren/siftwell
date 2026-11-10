#!/usr/bin/env python3
"""Server for Siftwell: serves the report, runs refreshes on demand, stores marks and settings.
Listens on the home network; every request needs the access key (cookie set by visiting /?k=KEY once),
except requests from this computer itself.   Usage: python server.py [port] (normally started by "Start Siftwell")"""
import base64, datetime as dt, hmac, json, os, re, secrets, subprocess, sys, threading
import osdeps
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip

import paths
HERE, DATA = paths.APP, paths.DATA
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
SECRETS = paths.SECRETS
LOG = os.path.join(DATA, "update.log")
os.makedirs(DATA, exist_ok=True)
TOKEN_FILE = paths.ACCESS_KEY
if not os.path.exists(TOKEN_FILE):
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, secrets.token_urlsafe(18).encode()); os.close(fd)
TOKEN = open(TOKEN_FILE).read().strip()

sys.path.insert(0, HERE)
import people
people.ensure_migrated()
import catalog, joblock, backup
try:
    _CATALOG_MIGRATED = catalog.migrate()  # one-time: build DATA/catalog.db from the old file-based data (here, in the server process)
except Exception as e:
    _CATALOG_MIGRATED = False
    print(f"catalog migration failed: {type(e).__name__}: {e}", flush=True)
if not _CATALOG_MIGRATED:
    catalog.retire_old_files()  # files the catalog replaced move to DATA/_archive/retired-<date>/ (not on the start that migrated)
_pstate = {}
jobs_file_lock = threading.Lock()

def ps(pid=None):
    """Background-job state for one person (resume reading, tailoring, questions)."""
    pid = pid or people.current()
    return _pstate.setdefault(pid, {"resume": {"running": False, "error": None, "finished": None}, "tailor": {}, "questions": {}})

def spawn(fn, *args):
    """Run fn in a background thread as the current person."""
    pid = people.current()
    def run():
        people.set_current(pid)
        fn(*args)
    threading.Thread(target=run, daemon=True).start()

def _claude_ready():
    import claude_cli
    return bool(claude_cli.claude_ready())

# POST routes that need Claude. Without it they answer 409 with a friendly "needs_claude" error instead of starting
# something that would fail; the pages show the same prompt in place of the control.
NEEDS_CLAUDE = {
    "/api/rate": "Rating jobs", "/api/rerate": "Re-rating", "/api/tailor": "Tailoring a resume",
    "/api/tailor/resume": "The Astra review", "/api/tailor/continue": "Tailoring a resume", "/api/questions": "Asking tailoring questions",
    "/api/target/suggest": "Suggesting targets", "/api/resume": "Reading a resume with Claude",
}

_NO_CLAUDE_NOTE = {"logged": False}
def note_no_claude():
    """One log line per stretch without Claude (not one per skipped automatic run)."""
    if not _NO_CLAUDE_NOTE["logged"]:
        _NO_CLAUDE_NOTE["logged"] = True
        print("Claude isn't connected: automatic Match ratings are skipped until it is (Settings, Get started).", flush=True)

def empty_board(pid):
    """A board with no jobs yet, so a new profile can upload a resume right away."""
    import report
    st = people.settings(pid)
    report.build({"generated": dt.datetime.now().isoformat(timespec="minutes"), "salary_floor": st["salary_floor"],
                  "ai_status": "no_profile", "pivot_status": "", "pivot_name": "AI pivot", "pivot_enabled": bool(st["pivot_ai"]),
                  "claude_ready": _claude_ready(),
                  "seniority": {"mine": st["seniority_mine"], "band": st["seniority_band"]}, "ai_scored": 0,
                  "person": {"id": pid, "name": people.name(pid)}, "people": people.load_index(),
                  "current": {"base": st.get("current_base"), "label": st.get("current_label") or ""},
                  "profile": None, "companies": [], "jobs": []}, people.pdir("report.html", pid=pid))

def _people_list():
    """The household for /api/people: id, name, and whether the person has an approved resume profile yet."""
    return [dict(p, profile=os.path.exists(people.pdir("profile.json", pid=p["id"]))) for p in people.load_index()]


_BOARD_COUNTS = {}   # pid -> (mtime, size, counts): jobs.json is big, so it is read again only when it changes

def board_counts(pid):
    """For My profile's status strip: jobs on this person's board and how many Claude has rated."""
    fp = people.pdir("jobs.json", pid=pid)
    try:
        st = os.stat(fp)
    except OSError:
        return {"jobs": 0, "rated": 0, "generated": None, "counted": True}
    hit = _BOARD_COUNTS.get(pid)
    if hit and hit[:2] == (st.st_mtime_ns, st.st_size):
        return hit[2]
    d = read_json(fp, {}) or {}
    js = d.get("jobs") or []
    out = {"jobs": len(js), "rated": sum(1 for j in js if j.get("ai_fit") is not None), "generated": d.get("generated"),
           "counted": "rate_batch" in d}
    _BOARD_COUNTS[pid] = (st.st_mtime_ns, st.st_size, out)
    return out

def refresh_stale_boards():
    """After an app update, re-render each board from its saved jobs.json when report.html is older than report.py
    (same output as a rebuild; no fetching, no scoring)."""
    import report
    code = os.path.getmtime(os.path.join(HERE, "report.py"))
    for pid in people.ids():
        try:
            people.set_current(pid)
            jp, rp = people.pdir("jobs.json", pid=pid), people.pdir("report.html", pid=pid)
            if os.path.exists(rp) and os.path.getmtime(rp) >= code:
                continue
            with joblock.hold("re-render"), jobs_file_lock:
                if os.path.exists(jp):
                    report.build(json.load(open(jp)), rp)
                else:
                    empty_board(pid)
            print(f"board re-rendered for {pid} (app updated)", flush=True)
        except Exception as e:
            print(f"couldn't re-render {pid}'s board: {e}", flush=True)

def _board_has_counts(pid):
    """False for a board written before the Re-rate panel (jobs.json has no "rate_batch": the panel can't count its jobs).
    write_person puts rate_batch before the long "jobs" list, so only the start of the file is read. True when unsure."""
    try:
        with open(people.pdir("jobs.json", pid=pid), "r", encoding="utf-8") as f:
            head = f.read(4_000_000)
    except OSError:
        return True  # no board at all: nothing to count
    i = head.find('"jobs":')
    return i < 0 or '"rate_batch"' in head[:i]

def recount_old_boards():
    """Once per server start: rebuild (no fetching, no Claude) any board that predates the Re-rate panel's counts, so its
    jobs carry the rating freshness the panel needs. Until then the panel shows "Counting…"."""
    old = [p for p in people.ids() if not _board_has_counts(p)]
    if old:
        print("recounting boards from an older version:", ", ".join(old), flush=True)
        request_recompute(old)

# ---- rebuilding boards from the catalog (seconds; no fetching, no Claude)
_RECOMPUTE = {"running": False, "pending": set(), "all": False, "fails": 0, "quiet": False}
RECOMPUTE_RETRIES = 3

def _busy():
    import catalog_api
    return state["running"] or any(v.get("running") for v in RERATE.values()) or catalog_api.find_live()

def request_recompute(pids=None, auto_rate=True):
    """Rebuild these people's boards (everyone if None) in the background. While an update or re-rate is running,
    the request waits and runs as soon as it finishes (flush_recompute). auto_rate=False: the rebuild that serves this
    request doesn't start the automatic quick check of new jobs (used after a restore: no Claude use by itself)."""
    with lock:
        if not auto_rate:
            _RECOMPUTE["quiet"] = True
        if pids is None:
            _RECOMPUTE["all"] = True
        else:
            _RECOMPUTE["pending"].update(p for p in pids if p)
    flush_recompute()

def flush_recompute():
    with lock:
        if _RECOMPUTE["running"] or _busy() or not (_RECOMPUTE["all"] or _RECOMPUTE["pending"]):
            return
        _RECOMPUTE["running"] = True
    threading.Thread(target=_recompute_loop, daemon=True).start()

def _recompute_loop():
    """Runs queued rebuilds one at a time. A request is only dropped once its rebuild succeeded; a failed one is
    queued again (people named on a RECOMPUTE_FAILED line, else the whole request), up to RECOMPUTE_RETRIES times."""
    import time
    try:
        while True:
            with lock:
                if _busy() or not (_RECOMPUTE["all"] or _RECOMPUTE["pending"]):
                    return
                was_all = _RECOMPUTE["all"]
                pids = [] if was_all else sorted(_RECOMPUTE["pending"])
                quiet = _RECOMPUTE["quiet"]
                _RECOMPUTE["all"] = False
                _RECOMPUTE["pending"].clear()
                _RECOMPUTE["quiet"] = False
            failed, why = None, ""
            try:
                with joblock.hold("recompute") as token, jobs_file_lock:
                    r = subprocess.run([sys.executable, os.path.join(HERE, "jobfinder.py"), "--recompute", *pids], cwd=HERE,
                                       capture_output=True, text=True, timeout=900, env=joblock.child_env(token))
                for m in ([] if quiet else re.finditer(r"^NEW_UNRATED (\{.*\})$", r.stdout or "", re.M)):  # new listings Claude hasn't rated
                    try:
                        nu = json.loads(m.group(1)); note_new_unrated(nu["pid"], nu["ids"], bool(nu.get("first")))
                    except Exception as e:
                        print("couldn't queue the quick check of new jobs:", e, flush=True)
                if r.returncode:
                    m = re.search(r"^RECOMPUTE_FAILED (\S+)", r.stdout or "", re.M)
                    failed = m.group(1).split(",") if m else None
                    why = ((r.stdout or "")[-400:] + " " + (r.stderr or "")[-1500:]).strip()
                    if not failed:
                        failed = "all" if was_all else pids
            except Exception as e:
                failed, why = ("all" if was_all else pids), f"{type(e).__name__}: {e}"
            with lock:
                if not failed:
                    _RECOMPUTE["fails"] = 0
                    continue
                _RECOMPUTE["fails"] += 1
                n = _RECOMPUTE["fails"]
                if n <= RECOMPUTE_RETRIES:
                    if failed == "all":
                        _RECOMPUTE["all"] = True
                    else:
                        _RECOMPUTE["pending"].update(failed)
                    _RECOMPUTE["quiet"] = _RECOMPUTE["quiet"] or quiet
                else:
                    _RECOMPUTE["fails"] = 0
            print(f"board rebuild failed ({'will retry' if n <= RECOMPUTE_RETRIES else 'giving up after retries'}):", why, flush=True)
            if n <= RECOMPUTE_RETRIES:
                time.sleep(min(60, 5 * n))
    except Exception as e:
        print(f"board rebuild failed: {type(e).__name__}: {e}", flush=True)
    finally:
        with lock:
            _RECOMPUTE["running"] = False
        flush_recompute()  # a request that arrived while this loop was finishing up

# ---- Claude Code sign-in from the board (works from any device).
# `claude auth login` prints a sign-in link, then waits for the code that the sign-in page shows.
# The board shows the link, the person signs in wherever they are, and pastes the code back here.
LOGIN = {"proc": None, "out": "", "lock": threading.Lock()}

def claude_login(action, code=""):
    import claude_cli, time
    with LOGIN["lock"]:
        p = LOGIN["proc"]
        if action == "status":
            s = claude_cli.state()
            return 200, {"logged_in": s == "ready", "installed": s != "not_installed", "ready": s == "ready"}
        if action == "cancel":
            if p and p.poll() is None:
                p.kill()
            LOGIN["proc"] = None
            return 200, {"ok": True}
        if action == "start":
            exe = claude_cli.path()
            if not exe:
                return 400, {"error": "Claude Code isn't installed on the computer running the board."}
            if p and p.poll() is None:
                p.kill()
            flags = subprocess.CREATE_NO_WINDOW if osdeps.WINDOWS else 0
            p = subprocess.Popen([*osdeps.cmd(exe), "auth", "login", "--claudeai"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, creationflags=flags)
            LOGIN["proc"], LOGIN["out"] = p, ""
            def read(proc=p):
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        break
                    if LOGIN["proc"] is proc:
                        LOGIN["out"] += ch.decode("utf-8", "replace")
            threading.Thread(target=read, daemon=True).start()
            for _ in range(60):
                m = re.search(r"https://\S+/oauth/authorize\?\S+", LOGIN["out"])
                if m:
                    return 200, {"url": m.group(0)}
                if p.poll() is not None:
                    break
                time.sleep(0.25)
            return 502, {"error": "Claude Code didn't give a sign-in link. " + LOGIN["out"].strip()[-200:]}
        if action == "code":
            code = code.strip()
            if not code:
                return 400, {"error": "Paste the code from the sign-in page."}
            if not p or p.poll() is not None:
                return 409, {"error": "That sign-in expired. Start again.", "expired": True}
            before = len(LOGIN["out"])
            try:
                p.stdin.write((code + "\n").encode())
                p.stdin.flush()
            except OSError:
                return 409, {"error": "That sign-in expired. Start again.", "expired": True}
            for _ in range(120):
                if p.poll() is not None:
                    break
                time.sleep(0.25)
            said = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", LOGIN["out"][before:]).strip()
            claude_cli.invalidate()
            if claude_cli.claude_ready(fresh=True):
                if p.poll() is None:
                    p.kill()
                LOGIN["proc"] = None
                request_recompute()  # rebuilds re-check a kept "signed out" status, so the banner clears
                return 200, {"ok": True}
            if p.poll() is not None:
                LOGIN["proc"] = None
                return 400, {"error": "Sign-in didn't go through. " + (said[-200:] or "Start again and use the newest code."), "expired": True}
            return 400, {"error": "Claude Code didn't accept that code. " + (said[-200:] or "Check it and try again.")}
    return 400, {"error": "unknown action"}

def find_job(job_id):
    data = read_json(people.pdir("jobs.json"), {"jobs": []})
    job = next((j for j in data["jobs"] if j["id"] == job_id), None)
    if not job:
        raise ValueError("That job is no longer in the list. Click Update jobs and try again.")
    desc = catalog.description(job_id) or job.get("snippet", "")
    return job, desc

def bg_questions(key, job_id):
    import interview
    ps()["questions"][key] = {"running": True, "error": None}
    try:
        if job_id:
            job, desc = find_job(job_id)
            rec = interview.generate_and_cache(key, job, desc)
        else:
            rec = interview.generate_and_cache(key)
        ps()["questions"][key] = {"running": False, "error": None, **rec}
    except Exception as e:
        ps()["questions"][key] = {"running": False, "error": str(e)[:400]}


def bg_highlights(pid):
    import highlights, claude_cli
    people.set_current(pid)
    try:
        highlights.refresh(pid, use_claude=claude_cli.claude_ready())
    except Exception as e:
        print("highlights refresh failed:", e, flush=True)
    request_recompute([pid])

def apply_rescore(job_id, desc):
    """Re-score one job with Claude and write the new numbers into jobs.json and the page (skipped mid-update)."""
    import ai_score, jobfinder, report
    if state["running"]:
        return
    with joblock.hold("rate", timeout=600), jobs_file_lock:
        if state["running"]:
            return
        path = people.pdir("jobs.json")
        payload = read_json(path, None)
        if not payload:
            return
        job = next((j for j in payload["jobs"] if j["id"] == job_id), None)
        if not job:
            return
        if not ai_score.rescore_one(job, desc, jobfinder.CFG["ai"]):
            return
        jobfinder.combine(job)
        payload["jobs"].sort(key=lambda j: -j["score"])
        paths.dump_json_atomic(path, payload, indent=1)
        report.build(payload, people.pdir("report.html"))

def bg_rate(ids, mode):
    """Have Claude rate chosen jobs now (the per-card and 'rate these' buttons), then rebuild this person's board."""
    import ai_score, pivot, jobfinder, report
    st = ps()
    st["rate"] = {"running": True, "error": None, "n": len(ids)}
    try:
        if state["running"]:
            raise ValueError("An update is running. Try again when it finishes.")
        try:
            held = joblock.hold("rate", timeout=1200)  # waits for a board rebuild or re-rate to finish
            held.__enter__()
        except joblock.Busy as e:
            raise ValueError(f"Another job ({e}) is still running. Try again when it finishes.")
        try:
            with jobs_file_lock:
                _rate_now(ids, mode)
        finally:
            held.__exit__(None, None, None)
        st["rate"] = {"running": False, "error": None, "done": True}
    except Exception as e:
        st["rate"] = {"running": False, "error": str(e)[:300]}

def _rate_now(ids, mode):
    import ai_score, pivot, jobfinder, report
    if state["running"]:
        raise ValueError("An update is running. Try again when it finishes.")
    pc, prof, _ = jobfinder.person_cfg(people.current())
    if not prof:
        raise ValueError("Approve a resume profile first.")
    path = people.pdir("jobs.json")
    payload = read_json(path, None)
    want = set(ids)
    sel = [j for j in payload["jobs"] if j["id"] in want]
    descs = catalog.descriptions(want)
    for j in sel:
        j["desc"] = descs.get(j["id"]) or j.get("snippet", "")
    if mode == "pivot":
        status = pivot.score_jobs([j for j in sel if "ai" in j.get("tracks", [])], {**pc["pivot"], "max_new_per_run": len(sel), "refresh_stale": True}, log=lambda m: None)
    else:
        status = ai_score.score_jobs(sel, {**pc["ai"], "max_new_per_run": len(sel), "refresh_stale": True}, log=lambda m: None)
        for j in sel:
            jobfinder.combine(j)
            if "ai" in j.get("tracks", []):
                pivot.combine(j)
    for j in sel:
        j.pop("desc", None)
    if status not in ("ok", ""):
        raise ValueError({"cli_logged_out": "Claude Code is signed out on the Mac.", "partial": "Some ratings failed; try again."}.get(status, status))
    payload["jobs"].sort(key=lambda j: -j["score"])
    payload["ai_scored"] = sum(1 for j in payload["jobs"] if j.get("ai_fit") is not None)
    paths.dump_json_atomic(path, payload, indent=1)
    report.build(payload, people.pdir("report.html"))

def bg_interpret():
    import target
    pid = people.current()
    st = people.settings()
    ps()["target"] = {"running": True, "error": None}
    import claude_cli
    if people.target_on(st) and not claude_cli.claude_ready():
        ps()["target"] = {"running": False, "error": None, "needs_claude": True}  # stays as typed until Claude is connected
        request_recompute([pid])
        return
    try:
        derived = target.interpret(st["target_text"], st["target_scope"]) if people.target_on(st) else \
            {"target_name": "", "target_any_title": False, "target_keywords": [], "target_summary": ""}
        people.save_settings(derived)
        ps()["target"] = {"running": False, "error": None, **derived}
    except Exception as e:
        ps()["target"] = {"running": False, "error": str(e)[:300]}
    finally:
        request_recompute([pid])  # the board's Target filter depends on what was just worked out (or cleared)

def bg_suggest():
    import target
    ps()["suggest"] = {"running": True, "error": None}
    try:
        ps()["suggest"] = {"running": False, "error": None, "options": target.suggest()}
    except Exception as e:
        ps()["suggest"] = {"running": False, "error": str(e)[:300]}

def bg_resume(kind, payload):
    import resume
    st = ps()["resume"]
    st.update(running=True, error=None, finished=None, stage="get", started=dt.datetime.now().isoformat(timespec="seconds"))
    try:
        path = resume.fetch_google_doc(payload) if kind == "gdoc" else resume.save_upload(*payload)
        resume.ingest(path, progress=lambda s: st.update(stage=s))
    except Exception as e:
        st["error"] = str(e)[:400]
    st.update(running=False, stage="", finished=dt.datetime.now().isoformat(timespec="seconds"))

def review_loop(s, job, desc):
    """Astra grades; below the threshold, either pause for the candidate's answers or have Claude rework. Keeps the best version."""
    import copy, interview, resume, review, tailor
    pr = people.prefs()
    st = ps()["tailor"][s]
    path = os.path.join(people.pdir("tailored"), s + ".json")
    t = json.load(open(path))
    rv = t.setdefault("review", {"rounds": [], "asked": [], "threshold": pr["review.threshold"]})
    rv["threshold"] = pr["review.threshold"]
    ok, why = review.codex_ready()
    if not ok:
        rv["status"] = "error"; rv["error"] = why; tailor.save_tailored(s, t); return
    facts = (resume.load_active() or {}).get("_resume_text", "") + "\n\nCONFIRMED ANSWERS\n" + interview.facts_text()
    target = {"1": 1, "2": 2}.get(pr["resume.length"])
    best = max(rv["rounds"], key=lambda r: r["score"], default=None)
    best_t = copy.deepcopy(t) if best and best["score"] == rv["rounds"][-1]["score"] else None
    while True:
        rnd = len(rv["rounds"]) + 1
        st.update(step="grade", round=rnd)
        pdf = tailor.make_pdf(s)
        try:
            g = review.grade(t, pdf, desc, facts, target)
        except Exception as e:
            rv["status"] = "error"; rv["error"] = str(e)[:300]; tailor.save_tailored(s, t); return
        g.update(round=rnd, at=dt.datetime.now().isoformat(timespec="minutes"))
        rv["rounds"].append(g)
        if best is None or g["score"] > best["score"]:
            best, best_t = g, copy.deepcopy(t)
        reworks = rnd - 1
        if g["score"] >= rv["threshold"] or reworks >= pr["review.max_rounds"]:
            rv["status"] = "passed" if g["score"] >= rv["threshold"] else "below"
            break
        asked = {a.lower() for a in rv.get("asked", [])}
        new_q = [q for q in g.get("fact_requests", []) if q["requirement"].lower() not in asked]
        if new_q:
            new_q = interview.dedupe(new_q)  # drop anything an earlier answer already covers (any job, any round)
        if pr["review.ask_facts"] and new_q:
            rv["status"] = "needs_answers"; rv["pending"] = new_q
            tailor.save_tailored(s, t)
            return
        st.update(step="rework", round=rnd)
        new_t = tailor.revise(job, desc, t, g)
        new_t["review"] = rv
        t = new_t
        tailor.save_tailored(s, t)
    if best_t is not None and best is not rv["rounds"][-1]:
        kept = copy.deepcopy(best_t); kept["review"] = rv; rv["kept_round"] = best["round"]; t = kept
    rv["final"] = best["score"]
    rv.pop("pending", None)
    tailor.save_tailored(s, t)
    tailor.make_pdf(s)

def bg_continue(job_id, answers):
    """Candidate answered Astra's fact questions: save them, rework with the last grade, keep reviewing."""
    import interview, tailor
    s = tailor.slug(job_id)
    ps()["tailor"][s] = {"running": True, "error": None, "step": "rework"}
    try:
        job, desc = find_job(job_id)
        path = os.path.join(people.pdir("tailored"), s + ".json")
        t = json.load(open(path)); rv = t["review"]
        pending = rv.pop("pending", [])
        rv["asked"] = sorted(set(rv.get("asked", [])) | {q["requirement"] for q in pending})
        if answers:
            interview.add_answers(answers, f"Astra review: {job['title']} @ {job['company']}")
        rv["status"] = "reworking"
        new_t = tailor.revise(job, desc, t, rv["rounds"][-1]); new_t["review"] = rv
        tailor.save_tailored(s, new_t)
        review_loop(s, job, desc)
        ps()["tailor"][s] = {"running": False, "error": None, "slug": s}
    except Exception as e:
        ps()["tailor"][s] = {"running": False, "error": str(e)[:400], "slug": s}

def bg_resume_review(job_id):
    """Pick an interrupted review back up (e.g. after a server restart)."""
    import tailor
    s = tailor.slug(job_id)
    ps()["tailor"][s] = {"running": True, "error": None, "step": "grade"}
    try:
        job, desc = find_job(job_id)
        review_loop(s, job, desc)
        ps()["tailor"][s] = {"running": False, "error": None, "slug": s}
    except Exception as e:
        ps()["tailor"][s] = {"running": False, "error": str(e)[:400], "slug": s}

def bg_tailor(job_id, rescore=False):
    import tailor
    s = tailor.slug(job_id)
    ps()["tailor"][s] = {"running": True, "error": None, "step": "rescore" if rescore else "tailor"}
    try:
        job, desc = find_job(job_id)
        if rescore:
            try:
                apply_rescore(job_id, desc)
            except Exception as e:
                print("rescore failed:", e, flush=True)
            ps()["tailor"][s]["step"] = "tailor"
        ps()["tailor"][s]["step"] = "tailor"
        tailor.tailor(job, desc)
        ps()["tailor"][s]["step"] = "pdf"
        try:
            tailor.make_pdf(s)
        except Exception as e:
            print("pdf build failed:", e, flush=True)
        if people.prefs()["review.enabled"]:
            review_loop(s, job, desc)
        ps()["tailor"][s] = {"running": False, "error": None, "slug": s}
    except Exception as e:
        ps()["tailor"][s] = {"running": False, "error": str(e)[:400], "slug": s}

state = {"running": False, "started": None, "finished": None, "exit": None, "phase": "", "done": 0, "total": 0, "lines": []}
lock = threading.Lock()

def read_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default

def write_private(path, obj):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)

# ---- "Keep my current ratings": ratings made by older versions are marked as current (no Claude calls)
ACCEPT = {}   # pid -> {running, result, error}
def run_accept(pid):
    import ai_score, pivot
    res, err = None, None
    try:
        with joblock.hold("accept-ratings", timeout=600), jobs_file_lock:
            people.set_current(pid)
            res = {"board": ai_score.accept_current(pid), "target": None}
            try:
                if people.target_on(people.settings_strict(missing_ok=True)):
                    res["target"] = pivot.accept_current(pid)
            except paths.CacheUnreadable as e:
                err = f"Board ratings done; Target ratings skipped ({str(e)[:100]})"
        request_recompute([pid])
    except Exception as e:
        res, err = None, f"{type(e).__name__}: {str(e)[:200]}"
    with lock:
        ACCEPT[pid] = {"running": False, "result": res, "error": err}

# ---- re-rating with the latest info: its own action, separate from fetching job listings.
# One rating job per person at a time; Runs pressed meanwhile wait in that person's queue. Options (opts) come from the
# board's Re-rate panel: {tiers, only_needed, sonnet_pct, opus_top, target}, or {ids} for the automatic quick check of
# new jobs; None is the classic re-rate (the nightly one). Stop: the server creates DATA/rerate-<pid>.stop, which the
# rating subprocess checks before each batch (batches already sent finish and are saved).
RERATE = {}   # pid -> {running, label, tier, done, total, queue: [opts], stopping, lines, error, finished, started}

def _stop_file(pid):
    return os.path.join(DATA, f"rerate-{pid}.stop")

def rate_label(o):
    if not o:
        return "Full re-rate"
    if o.get("ids") is not None:
        n = len(o["ids"])
        if o.get("first"):  # a new person's first board: every passing unrated job counts as new (the Haiku cap still applies)
            return f"First quick check of {n} job{'s' if n != 1 else ''}"
        return f"Quick check of {n} new job{'s' if n != 1 else ''}"
    t = o.get("tiers") or []
    if len(t) == 3:
        return "Full re-rate"
    name = {"haiku": "Quick check · Haiku", "sonnet": f"Careful look · Sonnet top {o.get('sonnet_pct')}%",
            "opus": f"Best judgment · Opus top {o.get('opus_top')}"}[t[0]]
    return name + ("" if o.get("only_needed", True) else " (fresh look at all)")

def _rate_cmd(pid, n, o):
    cmd = [sys.executable, os.path.join(HERE, "jobfinder.py"), "--rerate", pid, "--n", str(n)]
    if o and o.get("ids") is not None:
        f = os.path.join(DATA, f"rerate-{pid}-ids.json")
        with open(f, "w") as fh:
            json.dump(sorted(o["ids"]), fh)
        cmd += ["--ids-file", f]
    elif o:
        cmd += ["--tiers", ",".join(o["tiers"]), "--sonnet-pct", str(o["sonnet_pct"]), "--opus-top", str(o["opus_top"])]
        cmd += ([] if o.get("only_needed", True) else ["--force"]) + ([] if o.get("target", True) else ["--no-target"])
    return cmd

def _rate_state(o, queue=None):
    return {"running": True, "label": rate_label(o), "auto": bool(o and o.get("ids") is not None), "tier": "", "done": 0, "total": 0, "queue": queue or [],
            "stopping": False, "lines": [], "error": None, "finished": None, "started": dt.datetime.now().isoformat(timespec="seconds")}

def _actlog(action, pid=None, detail=""):
    import actionlog
    actionlog.log(action, pid, None, detail)

def _run_one(pid, n, o):
    """One rating subprocess under the job lock; returns its exit code (None if it never ran)."""
    r = RERATE[pid]
    def waiting(kind):
        with lock:
            r["lines"] = (r["lines"] + [f"Waiting for the running {kind} to finish..."])[-8:]
    rc = None
    try:
        with joblock.hold("rerate", on_wait=waiting) as token:
            if os.path.exists(_stop_file(pid)):
                return None  # stopped while waiting for its turn
            p = subprocess.Popen(_rate_cmd(pid, n, o), cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 bufsize=1, env={**joblock.child_env(token), "SIFTWELL_STOP_FILE": _stop_file(pid)})
            with open(os.path.join(DATA, f"rerate-{pid}.log"), "w") as log:  # full output incl. per-tier TIMING lines
                for line in p.stdout:
                    log.write(line); log.flush()
                    line = line.rstrip()
                    m = re.match(r"PROGRESS ai (\d+)/(\d+)(?: (\w+))?", line)  # the Target ratings run alongside; the bar follows the main funnel
                    with lock:
                        if m:
                            r["done"], r["total"], r["tier"] = int(m.group(1)), int(m.group(2)), m.group(3) or r["tier"]
                        elif line and not line.startswith("PROGRESS"):
                            r["lines"] = (r["lines"] + [line])[-8:]
                p.wait()
            rc = p.returncode
    except Exception as e:
        with lock:
            r["lines"] = (r["lines"] + [f"Re-rating couldn't start: {type(e).__name__}: {e}"])[-8:]
    return rc

def _rating_worker(pid, n, o):
    """Runs this person's rating jobs one after another until their queue is empty."""
    try:
        if os.path.exists(_stop_file(pid)):
            os.remove(_stop_file(pid))
        while True:
            rc = _run_one(pid, n, o)
            stopped = os.path.exists(_stop_file(pid))
            if stopped:
                os.remove(_stop_file(pid))
            with lock:
                r = RERATE[pid]
                r["error"] = None if rc == 0 or stopped else (r["lines"][-1] if r["lines"] else "failed")
                r["stopped"] = stopped
                _actlog("re-rate stopped" if stopped else ("re-rate finished" if rc == 0 else "re-rate failed"), pid, r.get("label", ""))
                if r["queue"]:  # Runs pressed after a Stop still run
                    o = r["queue"].pop(0)
                    RERATE[pid] = _rate_state(o, r["queue"])
                    continue
                r.update(running=False, stopping=False, finished=dt.datetime.now().isoformat(timespec="seconds"))
                return
    except Exception as e:
        with lock:
            RERATE.setdefault(pid, {}).update(running=False, error=f"{type(e).__name__}: {e}"[:200],
                                              finished=dt.datetime.now().isoformat(timespec="seconds"))
    finally:
        flush_recompute()

def start_rating(pid, o, n=None):
    """Start a rating job for this person, or queue it behind the one running. Returns "started" or "queued"
    ("skipped" when Claude isn't connected: nothing to rate with)."""
    import claude_cli
    if not claude_cli.claude_ready():
        note_no_claude()
        return "skipped"
    _NO_CLAUDE_NOTE["logged"] = False
    n = n or int(people.prefs(pid).get("claude.per_update") or 300)
    with lock:
        r = RERATE.get(pid)
        if r and r.get("running"):
            q = r.setdefault("queue", [])
            if o and o.get("ids") is not None:  # merge with a quick check of new jobs that hasn't started yet
                for x in q:
                    if x and x.get("ids") is not None:
                        x["ids"] |= set(o["ids"]); x["first"] = bool(x.get("first") or o.get("first")); return "queued"
            if o in q:  # the same run is already waiting: don't do it twice
                return "queued"
            q.append(o)
            return "queued"
        RERATE[pid] = _rate_state(o)
    threading.Thread(target=_rating_worker, args=(pid, n, o), daemon=True).start()
    return "started"

def run_rerate(pid, n, opts=None):
    """The classic re-rate (nightly): queued like any other run."""
    start_rating(pid, opts, n)

def stop_rating(pid):
    with lock:
        r = RERATE.get(pid)
        if not (r and r.get("running")):
            return False
        r["queue"], r["stopping"] = [], True
        r["lines"] = (r["lines"] + ["Stopping: batches already sent will finish and be kept..."])[-8:]
    open(_stop_file(pid), "w").close()
    return True

def rating_status(pid):
    with lock:
        r = dict(RERATE.get(pid) or {"running": False})
    r["queue"] = [rate_label(x) for x in r.get("queue") or []]
    return r

# Automatic quick check: when a board rebuild lets new listings onto someone's board that Claude hasn't rated, a Haiku
# check of just those runs once the rebuilds have been quiet for AUTO_QUIET seconds (several saves in a row -> one run).
_AUTO = {}   # pid -> {"ids": set, "due": time}
AUTO_QUIET = 20

def note_new_unrated(pid, ids, first=False):
    import time
    with lock:
        a = _AUTO.setdefault(pid, {"ids": set(), "due": 0, "first": False})
        a["ids"].update(ids)
        a["first"] = a["first"] or first
        a["due"] = time.time() + AUTO_QUIET
        if _AUTO.get("_loop"):
            return
        _AUTO["_loop"] = True
    threading.Thread(target=_auto_loop, daemon=True).start()

def _auto_loop():
    import time
    while True:
        time.sleep(2)
        with lock:
            quiet = not (_RECOMPUTE["running"] or _RECOMPUTE["all"] or _RECOMPUTE["pending"])
            ready = [p for p, a in _AUTO.items() if p != "_loop" and quiet and a["due"] <= time.time()]
            todo = {p: _AUTO.pop(p) for p in ready}
            if not [p for p in _AUTO if p != "_loop"] and not todo:
                _AUTO.pop("_loop", None)
                return
        for p, a in todo.items():
            try:
                if people.exists(p) and people.prefs(p).get("claude.auto_rate", True):
                    start_rating(p, {"ids": set(a["ids"]), "first": a["first"]})
            except Exception as e:
                print("automatic quick check failed for", p, e, flush=True)

# ---- automatic job-listing update (setting and OS job: autoupdate.py; mode "closed" is run by siftwell_update.py)
import autoupdate
SCHEDULE_FILE = autoupdate.FILE
def schedule():
    return autoupdate.schedule()
def next_run():
    return autoupdate.next_time()  # when the next automatic update is due, whichever way it runs (None when off)
def claim_update():
    """Mark an update as running unless one (or a re-rate) already is. True when the caller may start it."""
    with lock:
        if state["running"] or any(v.get("running") for v in RERATE.values()):
            return False
        state["running"] = True
        return True
def run_scheduled_update():
    """The automatic update's work (after claim_update() said yes): fetch, then re-rate anyone whose info changed."""
    state["trigger"] = "scheduled"
    run_update()
    # separate step, after the listings are in: re-rate anyone whose info changed (cheap when nothing did)
    if state.get("exit") in (0, 3):
        for pid in people.ids():
            try:
                if people.prefs(pid).get("claude.auto_rerate", True):
                    run_rerate(pid, int(people.prefs(pid).get("claude.per_update") or 300))
            except Exception as e:
                print("nightly re-rate failed for", pid, e, flush=True)
def scheduler():
    import time
    while True:
        t = autoupdate.scheduler_next()  # None unless the mode is "while Siftwell is running" (the OS job does "closed")
        if not t:
            time.sleep(300 if autoupdate.get()["mode"] == "off" else 60); continue
        while dt.datetime.now() < t:
            time.sleep(min(300, max(1, (t - dt.datetime.now()).total_seconds())))
            if autoupdate.scheduler_next() != t:  # schedule changed
                break
        else:
            if claim_update():
                run_scheduled_update()
            time.sleep(90)

def run_update(only=None, defer_running=False):
    """defer_running: the caller didn't mark the update as running; it counts as running only once it holds the job
    lock (Catalog's Fetch now / Add, so a fetch queued behind Find employers doesn't block Remove or Import)."""
    cmd = [sys.executable, os.path.join(HERE, "jobfinder.py")] + (["--only", only] if only else [])
    osdeps.keep_awake(True)
    fresh = dict(started=dt.datetime.now().isoformat(timespec="seconds"), finished=None, exit=None, phase="fetch", done=0, total=0, lines=[])
    with lock:
        if defer_running:
            state["lines"] = []
        else:
            state.update(running=True, **fresh)
    def waiting(kind):
        with lock:
            state["lines"] = (state["lines"] + [f"Waiting for the running {kind} to finish..."])[-12:]
    rc = None
    try:
        with joblock.hold("fetch", on_wait=waiting) as token:
            if defer_running:
                with lock:
                    state.update(running=True, **{**fresh, "started": dt.datetime.now().isoformat(timespec="seconds"),
                                                  "lines": state["lines"]})
            with open(LOG, "w") as log:
                p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     env=joblock.child_env(token))
                for line in p.stdout:
                    log.write(line); log.flush()
                    line = line.rstrip()
                    m = re.match(r"PROGRESS (\w+) (\d+)/(\d+)", line)
                    with lock:
                        if m:
                            state.update(phase=m.group(1), done=int(m.group(2)), total=int(m.group(3)))
                        elif line:
                            state["lines"] = (state["lines"] + [line])[-12:]
                p.wait()
            rc = p.returncode
    except Exception as e:
        with lock:
            state["lines"] = (state["lines"] + [f"The update couldn't start: {type(e).__name__}: {e}"])[-12:]
    finally:
        with lock:
            state.update(running=False, exit=rc if rc is not None else -1, finished=dt.datetime.now().isoformat(timespec="seconds"))
        _actlog("update finished" if rc in (0, 3) else "update stopped", None, f"exit {rc}")
        osdeps.keep_awake(False)
        flush_recompute()

_GZ_TYPES = ("text/", "json", "javascript", "xml", "svg")
_GZ_CACHE = {}  # key (path, mtime, size) -> gzipped bytes; only the big board pages use it
_GZ_LOCK = threading.Lock()

def gzip_cached(key, raw):
    """gzip level 6, memoised by key (a new mtime/size replaces the old entry for that path, so memory stays bounded)."""
    with _GZ_LOCK:
        z = _GZ_CACHE.get(key)
    if z is None:
        z = gzip.compress(raw() if callable(raw) else raw, 6)
        with _GZ_LOCK:
            for k in [k for k in _GZ_CACHE if k[0] == key[0]]:
                del _GZ_CACHE[k]
            _GZ_CACHE[key] = z
    return z


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _host_ok(self):
        """Allowed if the request comes from this Mac via a loopback name, or carries the access key cookie."""
        host = (self.headers.get("Host") or "").lower()
        if self.client_address[0] in ("127.0.0.1", "::1") and host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return True
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return "jb_key" in c and hmac.compare_digest(c["jb_key"].value, TOKEN)

    def _act(self, action, pid=None, detail=""):
        """One line in DATA/actions.log for a user-triggered action (never pass secrets in detail)."""
        import actionlog
        actionlog.log(action, pid, self, detail)

    def _person(self):
        """Profile chosen with the jb_person cookie (falls back to the first profile)."""
        c = SimpleCookie(self.headers.get("Cookie") or "")
        pid = c["jb_person"].value if "jb_person" in c else None
        if not pid or not people.exists(pid):
            pid = people.first()
        people.set_current(pid)
        return pid

    def _person_cookie(self, pid):
        return f"jb_person={pid}; Max-Age=31536000; Path=/; SameSite=Strict"

    def _login(self):
        """/?k=KEY sets the cookie and redirects to the board."""
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        k = dict(p.split("=", 1) for p in q.split("&") if "=" in p).get("k", "")
        if k and hmac.compare_digest(k, TOKEN):
            self.send_response(303)
            self.send_header("Set-Cookie", f"jb_key={TOKEN}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/")
            self.end_headers()
            return True
        return False

    def _send(self, code, body, ctype="application/json", cache="no-store", gz_key=None):
        """gz_key: (path, mtime, size) to memoise the gzipped body (for big files that rarely change)."""
        compressible = any(t in ctype for t in _GZ_TYPES)
        gz_ok = compressible and "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        if callable(body):  # lazy body (big file): on a gzip cache hit it is never read from disk
            compress = gz_ok and bool(gz_key)
            b = gzip_cached(gz_key, body) if compress else body()
        else:
            b = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
            compress = gz_ok and len(b) > 1024 and code not in (204, 304)
            if compress:
                b = gzip_cached(gz_key, b) if gz_key else gzip.compress(b, 6)
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype or "javascript" in ctype else ""))
        self.send_header("Cache-Control", cache)
        if compressible:
            self.send_header("Vary", "Accept-Encoding")
        if compress:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        if self.command != "HEAD" and code not in (204, 304):
            self.wfile.write(b)

    def _send_cookie(self, obj, pid):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", self._person_cookie(pid))
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/ping":  # launchers use this to find a running Siftwell; no key, no side effects
            import getting_started
            return self._send(200, getting_started.ping())
        if self._login():
            return
        if not self._host_ok():
            return self._send(403, "<p style='font:16px system-ui;padding:24px'>Open Siftwell with your access link (it ends in ?k=…).</p>", "text/html")
        path = self.path.split("?")[0]
        if path.startswith("/api/backup/") and backup.handle_get(self, path):
            return
        pid = self._person()
        import getting_started
        if path in getting_started.GET_PATHS and getting_started.handle_get(self, path, pid, self.path.partition("?")[2]):
            return
        if pid is None:  # fresh install: nothing exists until the first person is added
            if path in ("/", "/index.html", "/setup", "/settings", "/profile"):
                import welcome_page
                return self._send(200, welcome_page.render_welcome_html(), "text/html")
            if path == "/api/people":
                return self._send(200, {"people": [], "current": None, "settings": dict(people.DEFAULT_SETTINGS), "prefs": people.prefs()})
            if path != "/api/status":
                return self._send(409, {"error": "Add a person first."})
        if path == "/setup":
            import setup_page
            return self._send(200, setup_page.render_setup_html(), "text/html")
        if path == "/settings":
            import settings_page
            return self._send(200, settings_page.render_settings_html(pid), "text/html")
        if path == "/profile":
            import profile_page
            return self._send(200, profile_page.render_profile_html(pid), "text/html")
        if path == "/catalog" or path.startswith("/api/catalog/"):
            import catalog_api
            return catalog_api.handle_get(self, path, pid)
        if path == "/api/highlights":
            import highlights
            out = highlights.payload(pid)
            out["rescoring"] = _RECOMPUTE["running"]
            return self._send(200, out)
        if path == "/api/profile/board":
            return self._send(200, board_counts(pid))
        if path == "/api/setup":
            import setup_flow
            return self._send(200, setup_flow.get_state(pid, ps()["resume"]))
        if path in ("/", "/index.html"):
            import setup_flow
            if setup_flow.needs_setup(pid):
                self.send_response(303); self.send_header("Location", "/setup"); self.end_headers(); return
            rp = people.pdir("report.html")
            if not os.path.exists(rp) and people.load_index() and catalog.stats()["open"]:
                empty_board(pid)
            if not os.path.exists(rp):
                return self._send(200, "<p>No data yet. Starting first refresh…</p><script>fetch('/api/update',{method:'POST',headers:{'X-Jobboard':'1'}}).then(()=>setTimeout(()=>location.reload(),5000))</script>", "text/html")
            st_ = os.stat(rp)
            return self._send(200, lambda: open(rp, "rb").read(), "text/html", gz_key=(rp, st_.st_mtime_ns, st_.st_size))
        if path == "/api/status":
            with lock:
                s = dict(state)
            nr = next_run()
            s["next_run"] = nr.isoformat(timespec="minutes") if nr else None
            s["schedule"] = schedule()
            s["recomputing"] = _RECOMPUTE["running"]
            s["job"] = joblock.info()  # whoever holds the job lock, even a job this server didn't start
            return self._send(200, s)
        if path == "/api/schedule":
            return self._send(200, autoupdate.status())
        if path == "/api/rerate":
            return self._send(200, rating_status(pid))
        if path == "/api/ratings/accept":
            with lock:
                r = dict(ACCEPT.get(pid) or {"running": False, "result": None, "error": None})
            return self._send(200, r)
        if path == "/api/desc":
            from urllib.parse import parse_qs
            jid = (parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").get("id") or [""])[0]
            return self._send(200, {"desc": catalog.description(jid)})
        if path == "/api/marks":
            return self._send(200, read_json(people.pdir("marks.json"), {}))
        if path == "/api/profile":
            import resume
            def clean(p):
                return {k: v for k, v in p.items() if k != "_resume_text"} if p else None
            return self._send(200, {"active": clean(resume.load_active()), "draft": clean(resume.load_draft()),
                                    "ingest": ps()["resume"]})
        m = re.fullmatch(r"/api/tailor/([a-z0-9-]+)", path)
        if m:
            s_ = m.group(1)
            st = ps()["tailor"].get(s_)
            tp = os.path.join(people.pdir("tailored"), s_ + ".json")
            if not st and os.path.exists(tp):
                st = {"running": False, "error": None, "slug": s_}
            if st and not st.get("running") and os.path.exists(tp):
                rv = (read_json(tp, {}) or {}).get("review") or {}
                st = {**st, "review_status": rv.get("status"), "pending": rv.get("pending") or [],
                      "score": (rv.get("rounds") or [{}])[-1].get("score"), "threshold": rv.get("threshold")}
            return self._send(200, st or {"running": False, "error": None, "missing": True})
        if path == "/api/tailored":
            import glob
            out = []
            for f in glob.glob(os.path.join(people.pdir("tailored"), "*.json")):
                t = read_json(f, None)
                if not t:
                    continue
                rv = t.get("review") or {}
                slug0 = os.path.basename(f)[:-5]
                live = ps()["tailor"].get(slug0, {}).get("running")
                status = "running" if live else ("interrupted" if rv.get("status") in ("reworking",) or (rv.get("rounds") and not rv.get("status")) else rv.get("status"))
                rv = {**rv, "status": status}
                out.append({"slug": os.path.basename(f)[:-5], "job": t.get("job") or {}, "created": t.get("created"),
                            "headline": t.get("headline", ""), "gaps": len(t.get("gaps") or []),
                            "review": {"status": rv.get("status"), "final": rv.get("final") or (rv.get("rounds") or [{}])[-1].get("score"),
                                       "rounds": len(rv.get("rounds") or []), "threshold": rv.get("threshold"), "pending": len(rv.get("pending") or [])}})
            out.sort(key=lambda x: x.get("created") or "", reverse=True)
            return self._send(200, {"items": out})
        m = re.fullmatch(r"/tailored/([a-z0-9-]+)\.pdf", path)
        if m:
            import tailor
            if not os.path.exists(os.path.join(people.pdir("tailored"), m.group(1) + ".json")):
                return self._send(404, "Not found", "text/plain")
            try:
                pdf = tailor.make_pdf(m.group(1))
            except Exception as e:
                return self._send(500, f"<p style='font:16px system-ui;padding:24px'>{e}</p>", "text/html")
            b = open(pdf, "rb").read()
            fn = tailor.pdf_filename(m.group(1))
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{fn}"')
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        m = re.fullmatch(r"/tailored/([a-z0-9-]+)(\.docx)?", path)
        if m:
            import tailor
            base = os.path.join(people.pdir("tailored"), m.group(1))
            if not os.path.exists(base + ".json"):
                return self._send(404, "Not found", "text/plain")
            if m.group(2):
                b = open(base + ".docx", "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Disposition", 'attachment; filename="tailored-resume.docx"')
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                return self.wfile.write(b)
            return self._send(200, tailor.render_html(m.group(1)), "text/html")
        m = re.fullmatch(r"/api/questions/([a-z0-9-]+)", path)
        if m:
            import interview
            k = m.group(1)
            st = ps()["questions"].get(k)
            if not st:
                rec = interview.fresh_questions(k)
                st = {"running": False, "error": None, **rec} if rec else {"running": False, "error": None, "missing": True}
            return self._send(200, st)
        if path == "/api/rate":
            return self._send(200, ps().get("rate") or {"running": False})
        if path == "/api/target/suggest":
            return self._send(200, ps().get("suggest") or {"running": False, "missing": True})
        if path == "/api/people":
            return self._send(200, {"people": _people_list(), "current": pid, "settings": people.settings(), "prefs": people.prefs(),
                                    "target_job": ps().get("target") or {"running": False}})
        if path == "/api/companies/mine":
            import company_add
            cos = catalog.companies(include_paused=False)
            counts = {k: sum(1 for c in cos if k in (c.get("sets") or ["tech"])) for k in people.COMPANY_SETS}
            return self._send(200, {"sets": [{"id": k, "label": v, "count": counts[k]} for k, v in people.COMPANY_SETS.items()],
                                    "watching": sorted(people.settings().get("company_sets") or ["tech"]), "own": company_add.own()})
        if path == "/api/facts":
            import interview
            return self._send(200, {"facts": interview.load_facts()})
        if path == "/api/settings":
            return self._send(200, {"has_key": bool(read_json(SECRETS, {}).get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"))})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # Same-origin only: correct Host, custom header (forces CORS preflight from other sites), matching Origin.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host") or ""
        if not self._host_ok() or self.headers.get("X-Jobboard") != "1" or (origin and origin != f"http://{host}"):
            return self._send(403, {"error": "forbidden"})
        if self.path.split("?")[0] == "/api/catalog/import/preview":  # raw .siftwell file as the body (can be large)
            import catalog_api
            pid = self._person()
            if pid is None:
                return self._send(409, {"error": "Add a person first."})
            return catalog_api.handle_import_upload(self, pid)
        if self.path.split("?")[0] == "/api/backup/upload":  # raw zip body, streamed to disk (backups can be far bigger than the JSON limit)
            return backup.handle_upload(self)
        n = int(self.headers.get("Content-Length") or 0)
        if n > 25 * 1024 * 1024:
            return self._send(413, {"error": "file too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})
        path = self.path.split("?")[0]
        pid = self._person()
        import getting_started
        if getting_started.handle_post(self, path, body):
            return
        if path.startswith("/api/backup/") and backup.handle_post(self, path, body):
            return
        if path == "/api/claude/login":  # before the no-profile check: sign-in is part of first-time setup
            return self._send(*claude_login(str(body.get("action") or ""), str(body.get("code") or "")))
        if pid is None and path != "/api/people/add":
            return self._send(409, {"error": "Add a person first."})
        if path in NEEDS_CLAUDE:
            import claude_cli
            if not claude_cli.claude_ready():
                return self._send(409, {"error": f"{NEEDS_CLAUDE[path]} needs Claude. {claude_cli.NOT_READY_MSG}", "needs_claude": True})
        if path == "/api/profile/manual":  # "Fill in my profile myself": the form's fields become the approved profile
            import resume
            try:
                prof = resume.save_manual(body.get("profile") or {})
            except ValueError as e:
                return self._send(400, {"error": str(e)[:300]})
            self._act("profile filled in by hand", pid)
            threading.Thread(target=bg_highlights, args=(pid,), daemon=True).start()  # also rebuilds the board
            return self._send(200, {"ok": True, "hash": prof.get("_hash")})
        if path == "/api/resume/prefill":  # fill the form from a .docx / .txt by plain text extraction (no AI)
            import resume
            try:
                if body.get("text"):
                    fields = resume.prefill_from_text(str(body["text"])[:200000])
                elif body.get("data_b64") and body.get("filename"):
                    try:
                        raw = base64.b64decode(body["data_b64"])
                    except Exception:
                        return self._send(400, {"error": "bad file data"})
                    fields = resume.prefill_from_file(str(body["filename"]), raw)
                else:
                    return self._send(400, {"error": "Send a .docx or .txt file, or paste the resume text."})
            except ValueError as e:
                return self._send(400, {"error": str(e)[:300]})
            except Exception as e:
                return self._send(400, {"error": f"Couldn't read that file ({type(e).__name__}). Fill in the form by hand."})
            return self._send(200, {"ok": True, "fields": fields})
        if path.startswith("/api/catalog/"):
            import catalog_api
            return catalog_api.handle_post(self, path, body, pid)
        if path == "/api/person":
            new = str(body.get("id", ""))
            if not people.exists(new):
                return self._send(404, {"error": "no such profile"})
            return self._send_cookie({"ok": True}, new)
        if path == "/api/people/add":
            try:
                new = people.add(body.get("name"))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            self._act("profile added", new)
            people.save_settings({}, pid=new)
            empty_board(new)
            import setup_flow
            setup_flow.start(new)
            return self._send_cookie({"ok": True, "id": new}, new)
        if path == "/api/highlights":
            import highlights
            if body.get("edits"):
                try:
                    highlights.apply_corrections(pid, body["edits"])
                except (ValueError, TypeError) as e:
                    return self._send(400, {"error": str(e)[:300]})
            if body.get("confirm"):
                highlights.confirm(pid)
            request_recompute([pid])
            out = highlights.payload(pid); out["rescoring"] = True
            return self._send(200, out)
        if path == "/api/highlights/refresh":
            threading.Thread(target=bg_highlights, args=(pid,), daemon=True).start()
            return self._send(202, {"ok": True})
        if path == "/api/setup/step":
            import setup_flow
            try:
                return self._send(200, {"ok": True, "state": setup_flow.save_step(pid, str(body.get("step", "")), body.get("data") or {})})
            except ValueError as e:
                return self._send(400, {"error": str(e), "field": getattr(e, "field", None)})
        if path == "/api/setup/finish":
            import setup_flow
            try:
                out = setup_flow.finish(pid)
            except ValueError as e:
                return self._send(400, {"error": str(e), "field": getattr(e, "field", None)})
            request_recompute([pid])  # the board fills from the catalog right away; the update below adds fresh listings
            if out["kick"]["interpret_target"]:
                ps()["target"] = {"running": True, "error": None}; spawn(bg_interpret)
            if out["kick"]["update"]:
                with lock:
                    busy = state["running"]
                    if not busy:
                        state["running"] = True
                if not busy:
                    threading.Thread(target=run_update, daemon=True).start()
            return self._send(200, out)
        if path == "/api/rate":
            ids = [str(x) for x in (body.get("ids") or [])][:60]
            if not ids:
                return self._send(400, {"error": "no jobs given"})
            if (ps().get("rate") or {}).get("running"):
                return self._send(409, {"error": "Already rating jobs."})
            ps()["rate"] = {"running": True, "error": None, "n": len(ids)}
            spawn(bg_rate, ids, "pivot" if body.get("mode") == "pivot" else "current")
            return self._send(202, {"ok": True})
        if path == "/api/companies/add":
            import company_add
            try:
                res = company_add.add(str(body.get("url", "")), str(body.get("name", ""))[:60], "all" if body.get("scope") == "all" else "me")
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            with lock:
                busy = state["running"]
                if not busy:
                    state["running"] = True
            self._act("company added", pid, res.get("name"))
            if not busy:
                threading.Thread(target=run_update, args=(res["name"],), daemon=True).start()
            return self._send(200, {"ok": True, **res, "fetching": not busy})
        if path == "/api/prefs":
            self._act("settings saved", pid, "reset to defaults" if body.get("reset") else "preferences")
            if body.get("reset"):
                return self._send(200, {"ok": True, "prefs": people.save_prefs({k: d for k, (d, _) in people.PREF_SCHEMA.items()})})
            return self._send(200, {"ok": True, "prefs": people.save_prefs(body.get("prefs") or {})})
        if path == "/api/person/settings":
            self._act("settings saved", pid, "profile")
            st = body.get("settings") or {}
            clean = {}
            try:
                if "salary_floor" in st: clean["salary_floor"] = max(30000, min(1_000_000, int(st["salary_floor"])))
                if "current_base" in st: clean["current_base"] = int(st["current_base"]) if st["current_base"] not in (None, "") else None
                if "seniority_mine" in st:
                    m = max(2, min(7, int(st["seniority_mine"])))
                    clean["seniority_mine"], clean["seniority_band"] = m, [max(2, m - 1), min(7, m + 1)]
            except (TypeError, ValueError):
                return self._send(400, {"error": "Numbers only for pay and level."})
            for k in ("current_label", "goals", "target_text", "prep_text"):
                if k in st: clean[k] = str(st[k])[:2000]
            if "target_scope" in st: clean["target_scope"] = "ai" if st["target_scope"] == "ai" else "all"
            if "home_zip" in st:
                hz = str(st["home_zip"] or "").strip()[:60]
                if hz:
                    import geo
                    try:
                        found = geo.geocode_home(hz)
                    except ValueError:
                        found = None
                    if not found:
                        return self._send(400, {"error": f"Couldn't find \"{hz}\". Use a 5-digit ZIP or City, ST."})
                clean["home_zip"] = hz
            if "radius_miles" in st:
                try: clean["radius_miles"] = max(5, min(150, int(st["radius_miles"])))
                except (TypeError, ValueError): return self._send(400, {"error": "Radius must be a number of miles."})
            if "remote_us" in st: clean["remote_us"] = bool(st["remote_us"])
            if "workplaces" in st:
                wp = [w for w in ("onsite", "hybrid", "remote") if w in (st["workplaces"] or [])]
                if not wp:
                    return self._send(400, {"error": "Pick at least one way of working."})
                clean["workplaces"] = wp
            if "travel_max" in st:
                if st["travel_max"] not in ("none", "light", "moderate", "any"):
                    return self._send(400, {"error": "Pick how much travel is OK."})
                clean["travel_max"] = st["travel_max"]
            if "company_sets" in st and isinstance(st["company_sets"], list):
                clean["company_sets"] = [x for x in st["company_sets"] if x in people.COMPANY_SETS] or ["tech"]
            if body.get("name"): people.rename(pid, str(body["name"]))
            before = people.settings()
            saved = people.save_settings(clean)
            changed = (before.get("target_text"), before.get("target_scope")) != (saved.get("target_text"), saved.get("target_scope"))
            if changed:
                ps()["target"] = {"running": True, "error": None}
                spawn(bg_interpret)
            request_recompute([pid])  # filters changed: re-run them over the whole catalog
            return self._send(200, {"ok": True, "settings": saved, "interpreting": changed})
        if path == "/api/target/suggest":
            if not (ps().get("suggest") or {}).get("running"):
                ps()["suggest"] = {"running": True, "error": None}
                spawn(bg_suggest)
            return self._send(202, {"ok": True})
        if path == "/api/rerate":  # body {} = classic re-rate; Re-rate panel: {tiers, only_needed, sonnet_pct, opus_top, target}
            o = None
            if body.get("tiers"):
                tiers = [t for t in ("haiku", "sonnet", "opus") if t in (body.get("tiers") or [])]
                try:
                    pct, top = int(body.get("sonnet_pct")), int(body.get("opus_top"))
                except (TypeError, ValueError):
                    return self._send(400, {"error": "Enter whole numbers for the Sonnet % and the Opus count."})
                if not tiers or not 1 <= pct <= 100 or not 1 <= top <= 2000:
                    return self._send(400, {"error": "Sonnet looks at 1 to 100% of your jobs; Opus at 1 to 2,000 jobs."})
                o = {"tiers": tiers, "only_needed": body.get("only_needed", True) is not False, "sonnet_pct": pct,
                     "opus_top": top, "target": body.get("target", True) is not False}
            with lock:
                if state["running"]:
                    return self._send(409, {"error": "Job listings are updating right now. Re-rate when that finishes."})
            how = start_rating(pid, o)
            self._act("re-rate " + how, pid, rate_label(o))
            return self._send(202, {"ok": True, how: True, "label": rate_label(o)})
        if path == "/api/rerate/stop":
            return self._send(200, {"ok": True}) if stop_rating(pid) else self._send(409, {"error": "Nothing is being rated."})
        if path == "/api/ratings/accept":
            with lock:
                if (ACCEPT.get(pid) or {}).get("running"):
                    return self._send(409, {"error": "Already working on it."})
                ACCEPT[pid] = {"running": True, "result": None, "error": None}
            self._act("keep my current ratings", pid)
            threading.Thread(target=run_accept, args=(pid,), daemon=True).start()
            return self._send(202, {"ok": True})
        if path == "/api/schedule":
            try:
                st = autoupdate.apply(body)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": f"Couldn't save: {type(e).__name__}"})
            return self._send(200, dict(st, ok=True, schedule=schedule()))
        if path == "/api/update/scheduled":  # what siftwell_update.py (the OS job) calls when this server is already running
            if not claim_update():
                return self._send(409, {"error": "busy"})
            self._act("scheduled update started", pid, "asked by the automatic update job")
            threading.Thread(target=run_scheduled_update, daemon=True).start()
            return self._send(202, {"ok": True})
        if path == "/api/update":
            with lock:
                if any(v.get("running") for v in RERATE.values()):
                    return self._send(409, {"error": "Re-rating is running. Update when it finishes."})
                if state["running"]:
                    return self._send(409, {"error": "already running"})
                state["running"] = True
            self._act("update started", pid, "one company" if body.get("only") else "all")
            threading.Thread(target=run_update, args=(body.get("only"),), daemon=True).start()
            return self._send(202, {"ok": True})
        if path == "/api/search":
            import claude_cli, nlsearch
            q = str(body.get("q") or "").strip()[:300]
            if not q:
                return self._send(400, {"error": "Type what you're looking for."})
            jobs = read_json(people.pdir("jobs.json"), {"jobs": []}).get("jobs") or []
            if not claude_cli.claude_ready():
                return self._send(200, nlsearch.keyword_search(q, jobs, catalog.descriptions(j["id"] for j in jobs)))
            try:
                crit = nlsearch.interpret(q, {j["company"] for j in jobs if j.get("company")},
                                          {j["sector"] for j in jobs if j.get("sector")})
            except claude_cli.CLIAuthError:
                return self._send(503, {"error": "Claude Code is signed out.", "signin": True})
            except Exception as e:
                return self._send(502, {"error": f"Claude couldn't read that search ({str(e)[:120]})."})
            ranked = nlsearch.rank(jobs, catalog.descriptions(j["id"] for j in jobs), crit)
            return self._send(200, {"q": q, "criteria": crit, "ids": [i for i, _ in ranked], "scores": [s for _, s in ranked]})
        if path == "/api/people/rename":
            who, nm = str(body.get("id", "")), str(body.get("name", "")).strip()
            if not people.exists(who):
                return self._send(404, {"error": "No such profile."})
            if not nm:
                return self._send(400, {"error": "Type a name first."})
            self._act("profile renamed", who)
            people.rename(who, nm)
            return self._send(200, {"ok": True, "people": _people_list(), "current": pid})
        if path == "/api/people/remove":
            gone = str(body.get("id", ""))
            if not people.exists(gone):
                return self._send(404, {"error": "No such profile."})
            if len(people.ids()) <= 1:
                return self._send(400, {"error": "This is the only profile, so it can't be removed."})
            with lock:
                busy = state["running"] or (RERATE.get(gone) or {}).get("running")
            if busy:
                return self._send(409, {"error": "An update is running. Try again when it finishes."})
            self._act("profile removed", gone)
            people.remove(gone)
            _pstate.pop(gone, None)
            nxt = pid if pid != gone else people.first()
            return self._send_cookie({"ok": True, "current": nxt}, nxt)
        if path == "/api/marks":
            marks = read_json(people.pdir("marks.json"), {})
            jid, st = str(body.get("id", "")), body.get("status", "")
            if not jid:
                return self._send(400, {"error": "id required"})
            if st in ("saved", "applied", "hidden"):
                marks[jid] = st
            else:
                marks.pop(jid, None)
            json.dump(marks, open(people.pdir("marks.json"), "w"))
            return self._send(200, {"ok": True})
        if path == "/api/resume":
            if ps()["resume"]["running"]:
                return self._send(409, {"error": "Already reading a resume."})
            if body.get("gdoc_url"):
                args = ("gdoc", body["gdoc_url"])
            elif body.get("data_b64") and body.get("filename"):
                try:
                    raw = base64.b64decode(body["data_b64"])
                except Exception:
                    return self._send(400, {"error": "bad file data"})
                args = ("file", (body["filename"], raw))
            else:
                return self._send(400, {"error": "Send a file or a Google Docs link."})
            ps()["resume"].update(running=True, error=None)
            spawn(bg_resume, *args)
            return self._send(202, {"ok": True})
        if path == "/api/profile/approve":
            import resume
            try:
                prof = resume.approve(body.get("edits") or {})
            except Exception as e:
                return self._send(400, {"error": str(e)[:300]})
            threading.Thread(target=bg_highlights, args=(pid,), daemon=True).start()
            if body.get("rescore"):
                with lock:
                    busy = state["running"]
                    if not busy:
                        state["running"] = True
                if not busy:
                    threading.Thread(target=run_update, daemon=True).start()
            return self._send(200, {"ok": True, "hash": prof.get("_hash")})
        if path == "/api/profile/edit":  # changes to the approved profile (About you, job titles); the board re-checks itself
            import resume
            try:
                prof = resume.edit_active(body.get("edits") or {})
            except ValueError as e:
                return self._send(400, {"error": str(e)[:300]})
            self._act("settings saved", pid, "profile details")
            request_recompute([pid])
            return self._send(200, {"ok": True, "profile": {k: v for k, v in prof.items() if k != "_resume_text"}})
        if path == "/api/profile/discard":
            import resume
            resume.discard_draft()
            return self._send(200, {"ok": True})
        if path == "/api/tailor":
            import tailor
            jid = str(body.get("id", ""))
            s_ = tailor.slug(jid)
            if ps()["tailor"].get(s_, {}).get("running"):
                return self._send(202, {"slug": s_})
            ps()["tailor"][s_] = {"running": True, "error": None}
            spawn(bg_tailor, jid, bool(body.get("rescore")))
            return self._send(202, {"slug": s_})
        if path == "/api/tailored/delete":
            slug_ = str(body.get("slug", ""))
            if not re.fullmatch(r"[a-z0-9-]{1,80}", slug_):
                return self._send(400, {"error": "bad id"})
            if ps()["tailor"].get(slug_, {}).get("running"):
                return self._send(409, {"error": "That resume is still being worked on. Try again when it finishes."})
            base = os.path.join(people.pdir("tailored"), slug_)
            removed = 0
            for ext in (".json", ".docx", ".pdf", ".pdf.key", ".pdf.part"):
                if os.path.exists(base + ext):
                    os.remove(base + ext); removed += 1
            ps()["tailor"].pop(slug_, None)
            return self._send(200, {"ok": True, "removed": removed})
        if path == "/api/tailor/resume":
            import tailor
            jid = str(body.get("id", ""))
            s_ = tailor.slug(jid)
            if ps()["tailor"].get(s_, {}).get("running"):
                return self._send(409, {"error": "Already working on this resume."})
            ps()["tailor"][s_] = {"running": True, "error": None, "step": "grade"}
            spawn(bg_resume_review, jid)
            return self._send(202, {"slug": s_})
        if path == "/api/tailor/continue":
            import tailor
            jid = str(body.get("id", ""))
            s_ = tailor.slug(jid)
            if ps()["tailor"].get(s_, {}).get("running"):
                return self._send(409, {"error": "Already working on this resume."})
            ps()["tailor"][s_] = {"running": True, "error": None, "step": "rework"}
            spawn(bg_continue, jid, body.get("answers") or [])
            return self._send(202, {"slug": s_})
        if path == "/api/questions":
            import tailor
            jid = str(body.get("id", ""))
            k = tailor.slug(jid) if jid else "general"
            if not ps()["questions"].get(k, {}).get("running"):
                ps()["questions"][k] = {"running": True, "error": None}
                spawn(bg_questions, k, jid or None)
            return self._send(202, {"key": k})
        if path == "/api/answers":
            import interview
            answers = body.get("answers") or []
            if not isinstance(answers, list):
                return self._send(400, {"error": "answers must be a list"})
            n = interview.add_answers(answers, str(body.get("context", ""))[:120] or "General interview")
            return self._send(200, {"added": n, "facts": interview.load_facts()})
        if path == "/api/facts/polish":
            import interview
            interview.edit_polished(str(body.get("id", "")), str(body.get("polished", "")))
            return self._send(200, {"facts": interview.load_facts()})
        if path == "/api/facts/delete":
            import interview
            interview.delete_fact(str(body.get("id", "")))
            return self._send(200, {"facts": interview.load_facts()})
        if path == "/api/settings":
            key = (body.get("anthropic_api_key") or "").strip()
            self._act("settings saved", pid, "API key " + ("saved" if key else "removed" if body.get("clear") else "unchanged"))
            sec = read_json(SECRETS, {})
            if key:
                sec["anthropic_api_key"] = key
            elif body.get("clear"):
                sec.pop("anthropic_api_key", None)
            write_private(SECRETS, sec)
            return self._send(200, {"has_key": bool(sec.get("anthropic_api_key"))})
        self._send(404, {"error": "not found"})

def busy_reason():
    """What a restart would kill right now ('' when idle); used by the Get started page's Restart button."""
    with lock:
        if state["running"]:
            return "An update is running"
        if any(r.get("running") for r in RERATE.values()):
            return "A re-rate is running"
    if _RECOMPUTE["running"]:
        return "Boards are being rebuilt"
    import catalog_api
    if catalog_api.find_live():
        return "Find employers near me is running"
    try:
        import joblock
        h = joblock.info()
        if h and h["alive"]:
            return f"A background job is running ({h['kind']})"
    except Exception:
        pass
    for p in list(_pstate.values()):
        if any(t.get("running") for t in list(p["tailor"].values())) or p["resume"].get("running") or any(q.get("running") for q in list(p["questions"].values())):
            return "A resume is being tailored or read"
    return ""

import catalog_api
catalog_api.configure(sys.modules[__name__])
def after_restore():
    """Backup & move just swapped DATA's contents: re-read the access key and the people index, drop in-memory
    per-profile state, and rebuild every board from the restored catalog (restart-free)."""
    global TOKEN
    if os.path.exists(TOKEN_FILE):
        TOKEN = open(TOKEN_FILE).read().strip() or TOKEN
    else:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd, TOKEN.encode()); os.close(fd)
    import getting_started
    getting_started.configure(PORT, TOKEN, busy_reason)
    _pstate.clear()
    people.set_current(people.first())
    with lock:  # quick checks queued before the restore were for the replaced data
        for k in [k for k in _AUTO if k != "_loop"]:
            _AUTO.pop(k, None)
    request_recompute(auto_rate=False)  # ratings come back with the backup; a restore never starts Claude by itself

if __name__ == "__main__":
    osdeps.ensure_utf8()

    class Server(ThreadingHTTPServer):
        # On Windows, SO_REUSEADDR lets a second program bind a port that's already taken, silently.
        # Claim it exclusively there so a clash fails loudly instead of another app answering.
        allow_reuse_address = not osdeps.WINDOWS
        def server_bind(self):
            if osdeps.WINDOWS:
                import socket
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    try:
        import getting_started
        BIND = getting_started.bind_host()  # 127.0.0.1 unless phone access is on (DATA/network.json)
        srv = Server((BIND, PORT), H)
        getting_started.configure(PORT, TOKEN, busy_reason)
        backup.configure(jobs_file_lock, busy_reason, after_restore)
        getting_started.note_started()
    except OSError:
        print(f"Port {PORT} is already in use by another program. Stop it, or run on another port: "
              f"python server.py <port>", flush=True)
        sys.exit(1)
    print(f"Siftwell on http://127.0.0.1:{PORT}" + (f"  (other devices: http://<this computer's IP>:{PORT}/?k=<key in {TOKEN_FILE}>)" if BIND == "0.0.0.0" else "  (this computer only)"), flush=True)
    autoupdate.ensure_initialized()  # first start: write down on/off for good (existing households stay on, new installs off)
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=refresh_stale_boards, daemon=True).start()
    threading.Thread(target=recount_old_boards, daemon=True).start()
    # start-at-sign-in entry still pointing at an old app folder or runtime? rewrite it (see getting_started.heal_startup)
    threading.Thread(target=getting_started.heal_entries, kwargs={"log": lambda m: print(m, flush=True)}, daemon=True).start()
    try:   # tray icon while Siftwell runs without its window (helper process; see tray.py)
        import tray
        tray.start_helper(PORT)
    except Exception as e:
        print(f"tray helper not started: {e}", flush=True)
    if _CATALOG_MIGRATED:
        request_recompute()  # first start on the catalog: rebuild every board from it
    srv.serve_forever()
