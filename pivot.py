"""Target track: Claude judges each job as a step toward the person's own career target (any target).

Two numbers per job: now_fit (a realistic shot today, with honest tailoring) and later_fit (after the
3-4 month build plan). Gap tags come from a fixed list so the board can total them into a portfolio plan.
Runs on the Claude subscription via the Claude Code CLI. Cache: DATA/pivot_scores.json keyed by profile and target:
{"_rating_format": 1, "v2:<profile key>:<target key>": {job_id: rating}}. Each rating carries fp (fingerprint of the
person's data) and fmt. Like ai_score, nothing code-side (prompt, model, schema) goes into keys or fingerprints."""
import concurrent.futures as cf, json, os, re, threading, time

import claude_cli

import paths
CACHE = paths.data("pivot_scores.json")
# Key prefix of every stored Target rating. It is a frozen part of the cache key, not a version: never change it
# (changing it would orphan every stored rating). To invalidate ratings on purpose, bump RATING_FORMAT instead.
VERSION = "v2"
# Bump (1 -> 2) ONLY to deliberately invalidate every stored Target rating. That makes every user re-rate, which costs
# them Claude tokens and plan limits, so it must be a conscious decision and announced in the release notes.
RATING_FORMAT = 1
FORMAT_KEY = "_rating_format"
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
Pay floor: ${floor:,} base. Location: {area}.
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
                              floor=int(st.get("salary_floor") or 0), prep=st.get("prep_text") or "(not specified)", area=__import__("geo").area_phrase(st))

def target_key(st):
    """Key of the person's target settings: their own words (whitespace-normalized), scope and pay floor. Pass the
    person's saved settings file (not merged with code defaults), so a changed default can't re-key anything."""
    import hashlib
    def w(v):
        return " ".join(v.split()) if isinstance(v, str) else v
    return hashlib.sha256(json.dumps([w(st.get("target_text")), w(st.get("prep_text")), st.get("target_scope"),
                                      st.get("salary_floor")]).encode()).hexdigest()[:10]

def target_key_legacy(st):
    """target_key as older versions computed it (raw text, settings merged with defaults). Frozen: only used to adopt
    ratings stored under it."""
    import hashlib
    return hashlib.sha256(json.dumps([st.get("target_text"), st.get("prep_text"), st.get("target_scope"),
                                      st.get("salary_floor")]).encode()).hexdigest()[:10]

def cache_keys(f, st, saved=None):
    """(key, older keys of the same person and target) for pivot_scores.json.
    st: the person's settings merged with defaults, from a read that succeeded (people.settings_strict), never {}.
    The key is target_key(st): for every settings file that holds the four target fields it equals the key stored
    from the raw file. saved: that raw file (or None); if a field was missing from it, the key older versions stored
    (computed from the raw file, so None for the missing field) is adopted, as are the all-None key (a failed read
    once produced it) and the all-defaults key."""
    import people
    tk = target_key(st)
    key = f"{VERSION}:{f['phash']}:{tk}"
    tks = [target_key(saved or {}), target_key({}), target_key(people.DEFAULT_SETTINGS), target_key_legacy(st)]
    old = []
    for ph in [f["phash"], *f["phash_old"]]:
        for t in tks:
            k = f"{VERSION}:{ph}:{t}"
            if k != key and k not in old:
                old.append(k)
    return key, old

def accept_current(pid):
    """"Keep my current ratings" for the Target tab: stamp this person's Target ratings that have no fingerprint
    (made by older versions) with their current one so they aren't re-rated. Ratings with a fingerprint that differs
    from today's were made from different data and are left alone. Nothing calls Claude.
    Returns {"stamped": n, "already_current": n, "left_alone": n}."""
    import ai_score, people
    people.set_current(pid)
    saved, st = people.read_saved_strict(), people.settings_strict()
    f = ai_score.fingerprints()
    key, old_keys = cache_keys(f, st, saved)
    counts = {"stamped": 0, "already_current": 0, "left_alone": 0}
    with _lock:
        allc = load_cache()
        allc.setdefault(FORMAT_KEY, 1)
        ai_score.adopt(allc, key, old_keys)
        for r in (allc.get(key) or {}).values():
            if not isinstance(r, dict):
                continue
            if fresh(r, f):
                counts["already_current"] += 1
            elif "fp" not in r:
                r["fp"], r["fmt"] = f["pfp"], RATING_FORMAT
                counts["stamped"] += 1
            else:
                counts["left_alone"] += 1
        if counts["stamped"]:
            paths.dump_json_atomic(CACHE, allc)
    return counts

def fresh(r, f):
    """Rating made from the same data under the current RATING_FORMAT (accepts the fingerprint older versions stored)."""
    return bool(r) and r.get("fmt", 1) == RATING_FORMAT and r.get("fp") in (f["pfp"], f["pfp_old"])

def _job_text(j):
    sal = f'${j["salary_min"]:,}-${j["salary_max"]:,}' if j.get("salary_max") else "not listed"
    return (f'<job id="{j["id"]}">\nTitle: {j["title"]}\nCompany: {j["company"]} ({"frontier AI lab" if j.get("ai_track") == "lab" else "AI company" if j.get("ai_track") else j.get("sector", "")})\n'
            f'Location: {"; ".join(j["locations"][:4])} | Workplace: {j.get("workplace") or "unstated"} | '
            f'Clearance: {j.get("clearance") or "none mentioned"} | Salary: {sal}\n'
            f'Description:\n{(j.get("desc") or j.get("snippet") or "")[:3500]}\n</job>')

def load_cache():
    """Missing -> {}; unreadable -> paths.CacheUnreadable (never an empty cache that would then be saved)."""
    d = paths.load_json_cache(CACHE)
    return d if isinstance(d, dict) else {}

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
    profile, _ = ai_score.current_profile()
    try:
        saved = people.read_saved_strict()
        st = people.settings_strict()
    except paths.CacheUnreadable as e:
        # Never derive a cache key from a failed or partial read: that would file (or look up) ratings under a junk key
        # and could re-rate hundreds of jobs. Nothing is rated, applied or written this time.
        log(f"Target rating skipped: the profile's settings can't be read right now ({str(e)[:120]}).")
        return "settings_unreadable"
    f = ai_score.fingerprints()
    key, old_keys = cache_keys(f, st, saved)
    system = system_for(st)
    allc = load_cache()
    allc.setdefault(FORMAT_KEY, 1)  # caches written before the stamp existed were all format 1
    ai_score.adopt(allc, key, old_keys)
    cache = allc.setdefault(key, {})
    for k in list(allc):
        if re.match(r"v1:", k):
            allc.pop(k)  # v1-era scores (an old prompt layout, long gone); v2 keys are never dropped by code
    fp = f["pfp"]
    need = (lambda j: not fresh(cache.get(j["id"]), f)) if cfg.get("refresh_stale") else (lambda j: j["id"] not in cache)
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
            def one(b):  # after Stop, batches not yet sent are skipped; ones already sent finish and are kept
                return None if claude_cli.stop_requested() else _batch(cfg, system, profile, b)
            futs = [ex.submit(one, b) for b in batches]
            for fut in cf.as_completed(futs):  # (not "f": that is the fingerprints, used below)
                try:
                    res = fut.result()
                    if res is None:
                        status, res = "partial", {}
                    for v in res.values():
                        v["fp"], v["fmt"] = fp, RATING_FORMAT
                    if res:
                        with _lock:
                            cache.update(res)
                            paths.dump_json_atomic(CACHE, allc)  # save as we go, so a stopped run keeps what it got
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
        paths.dump_json_atomic(CACHE, allc)
    for j in jobs:
        if j["id"] in cache:
            apply(j, cache[j["id"]])
            j["pv_stale"] = not fresh(cache[j["id"]], f)
        combine(j)
    return status
