"""Target track: Claude judges each job as a step toward the person's own career target (any target).

Two numbers per job: now_fit (a realistic shot today, with honest tailoring) and later_fit (after the
3-4 month build plan). Gap tags come from a fixed list so the board can total them into a portfolio plan.
Runs on the Claude subscription via the Claude Code CLI. Cache: data/pivot_scores.json keyed by profile."""
import concurrent.futures as cf, json, os, re, threading, time

import claude_cli

import paths
CACHE = paths.data("pivot_scores.json")
VERSION = "v2"
_lock = threading.Lock()

SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "now_fit": {"type": "integer"},
        "later_fit": {"type": "integer"},
        "label": {"type": "string", "enum": ["apply_now", "after_prep", "long_shot", "skip"]},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "angle": {"type": "string"}},
        "required": ["id", "now_fit", "later_fit", "label", "gaps", "reason", "angle"], "additionalProperties": False}}},
    "required": ["results"],
    "additionalProperties": False,
}

SYSTEM_TMPL = """You are a blunt, well-informed career advisor. The candidate's TARGET, in their words: {target}
Their goals and constraints: {goals}
Pay floor: ${floor:,} base. Location: DMV area or remote only.
What they're willing to do to get there: {prep}

For each job, judge it as a step toward that target for THIS candidate, using only facts in their profile (resume, approved reframings, answers they gave). Weigh pay heavily if their target or goals emphasize compensation.
- now_fit 0-100: how competitive they'd be today with an honest tailored resume. 70+ means a genuine shot.
- later_fit 0-100: the same after the preparation above, done well. Must be >= now_fit. Don't inflate: preparation closes skill and evidence gaps, not years of experience, degrees or track records they lack.
- label: apply_now if now_fit >= 65; after_prep if now_fit < 65 and later_fit >= 65; long_shot if later_fit is 40-64; skip if later_fit < 40, or the job clearly conflicts with their target or constraints.
- gaps: up to 4 of the biggest requirements they don't meet, each 1 to 4 words using common generic names so they can be counted across jobs (e.g. "Python", "Quota-carrying sales", "People management", "Hands-on LLM building", "TS/SCI clearance").
- reason: one sentence on why, specific to this posting.
- angle: one sentence on how they'd pitch themselves, using only what is true TODAY. Never describe planned preparation as done; if the pitch depends on it, add "Once prepared: ..." as a separate clause."""

def system_for(st):
    return SYSTEM_TMPL.format(target=st.get("target_text") or "(none given)", goals=st.get("goals") or "(none given)",
                              floor=int(st.get("salary_floor") or 0), prep=st.get("prep_text") or "(not specified)")

def target_key(st):
    import hashlib
    h = hashlib.sha256(json.dumps([st.get("target_text"), st.get("prep_text"), st.get("target_scope"),
                                   st.get("salary_floor")]).encode()).hexdigest()[:10]
    return h

def _job_text(j):
    sal = f'${j["salary_min"]:,}-${j["salary_max"]:,}' if j.get("salary_max") else "not listed"
    return (f'<job id="{j["id"]}">\nTitle: {j["title"]}\nCompany: {j["company"]} ({"frontier AI lab" if j.get("ai_track") == "lab" else "AI company" if j.get("ai_track") else j.get("sector", "")})\n'
            f'Location: {"; ".join(j["locations"][:4])} | Workplace: {j.get("workplace") or "unstated"} | '
            f'Clearance: {j.get("clearance") or "none mentioned"} | Salary: {sal}\n'
            f'Description:\n{(j.get("desc") or j.get("snippet") or "")[:3500]}\n</job>')

def load_cache():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}

def _batch(cfg, system, profile, batch):
    msg = "Assess these postings. Return one result per job id.\n\n" + "\n\n".join(_job_text(j) for j in batch)
    out = claude_cli.run_json(system + "\n\nCANDIDATE\n" + profile, msg, SCHEMA,
                              model=cfg["model"], effort=cfg.get("effort", "low"), timeout=600)
    res = {}
    for r in out.get("results", []):
        later = max(r["later_fit"], r["now_fit"])
        res[r["id"]] = {"now": max(0, min(100, r["now_fit"])), "later": max(0, min(100, later)), "label": r["label"],
                        "gaps": [g.strip()[:40] for g in r["gaps"][:4]], "reason": r["reason"], "angle": r["angle"]}
    return res

def apply(job, a):
    job["pv_now"], job["pv_later"], job["pv_label"] = a["now"], a["later"], a["label"]
    job["pv_gaps"], job["pv_reason"], job["pv_angle"] = a["gaps"], a["reason"], a["angle"]
    job["pv_bridge"] = False

def combine(job):
    """Pivot score: realistic odds (weighted to now) + pay + quality of life, with a nudge for frontier labs."""
    if job.get("pv_now") is not None:
        fit = 0.6 * job["pv_now"] + 0.4 * job["pv_later"]
    else:
        fit = job["fit_score"] * 0.8  # keyword fallback until Claude has looked
    s = 0.5 * fit + 0.3 * job["comp_score"] + 0.2 * job["qol_score"]
    job["pv_score"] = round(min(100, s))

CODER = re.compile(r"software engineer|research|scientist|machine learning engineer|ml engineer|kernel|compiler|gpu|hardware", re.I)

def priority(j, st):
    """Which unrated jobs Claude should look at first: target-title matches, pay, level band, frontier labs (if AI-scoped)."""
    t = j["title"].lower()
    kws = st.get("target_keywords") or []
    p = min(30, 15 * sum(1 for k in kws if k in t)) if kws else 0
    if st.get("target_scope") == "ai" and j.get("ai_track") == "lab":
        p += 20
    mid, floor = j.get("salary_mid"), st.get("salary_floor") or 0
    if mid:
        p += max(-20, min(30, (mid - floor) / 5000))
    if CODER.search(t) and not any(k in t for k in kws):
        p -= 10
    p -= 15 if j.get("clearance") in ("TS/SCI + poly", "TS/SCI", "Top Secret") else 0
    band, lv = st.get("seniority_band") or [3, 5], j.get("level")
    p -= 20 if lv is not None and not (band[0] <= lv <= band[1]) else 0
    return p + 0.2 * j.get("score", 0)

def score_jobs(jobs, cfg, log=print):
    """jobs: the AI-track jobs (with desc). Scores uncached ones, applies cache to all. Returns a status string."""
    import ai_score
    import people
    profile, phash = ai_score.current_profile()
    st = people.settings()
    key = f"{VERSION}:{phash}:{target_key(st)}"
    system = system_for(st)
    allc = load_cache()
    cache = allc.setdefault(key, {})
    for k in list(allc):
        if not k.startswith(VERSION + ":"):
            allc.pop(k)  # drop scores from older prompt versions; each person's profile+target keeps its own
    fp = ai_score.info_fp(profile)
    need = (lambda j: j["id"] not in cache or cache[j["id"]].get("fp") != fp) if cfg.get("refresh_stale") else (lambda j: j["id"] not in cache)
    todo = sorted((j for j in jobs if need(j)), key=lambda j: -priority(j, st))[: max(0, cfg.get("max_new_per_run", 300))]
    status = "ok"
    if todo and not claude_cli.logged_in():
        status, todo = "cli_logged_out", []
        log("Pivot scoring skipped: Claude Code is not signed in.")
    if todo:
        bs = cfg.get("batch_size", 12)
        batches = [todo[i:i + bs] for i in range(0, len(todo), bs)]
        log(f"Pivot scoring {len(todo)} AI-company jobs in {len(batches)} batches...")
        done, failed, t0 = 0, 0, time.time()
        with cf.ThreadPoolExecutor(cfg.get("cli_concurrency", 3)) as ex:
            futs = [ex.submit(_batch, cfg, system, profile, b) for b in batches]
            for f in cf.as_completed(futs):
                try:
                    res = f.result()
                    for v in res.values():
                        v["fp"] = fp
                    with _lock:
                        cache.update(res)
                except claude_cli.CLIAuthError:
                    status = "cli_logged_out"
                    for x in futs: x.cancel()
                    break
                except Exception as e:
                    status = "partial"; failed += 1
                    log(f"Pivot batch failed: {type(e).__name__}: {str(e)[:150]}")
                done += 1
                log(f"PROGRESS pivot {done}/{len(batches)}")
        ai_score.TIMINGS.append({"tier": "target", "jobs": len(todo), "batches": len(batches), "failed": failed,
                                 "secs": round(time.time() - t0, 1), "status": status})
        log(f"TIMING target: {len(todo)} jobs, {len(batches)} batches, {failed} failed, {time.time() - t0:.1f}s ({status})")
        json.dump(allc, open(CACHE, "w"))
    for j in jobs:
        if j["id"] in cache:
            apply(j, cache[j["id"]])
            j["pv_stale"] = cache[j["id"]].get("fp") != fp
        combine(j)
    return status
