"""Claude fit scoring: rates each job against the active resume profile, caches results in DATA/ai_scores.json."""
import concurrent.futures as cf, json, os, shutil, subprocess, threading, time
import osdeps

import paths
CACHE = paths.data("ai_scores.json")
SECRETS = paths.SECRETS

SYSTEM = """You screen job postings for one specific candidate. For each posting give two fit scores from 0 to 100:

- "as_is_fit": how well the resume, as currently written, matches the posting's real requirements.
- "tailored_fit": how well it would match after honest tailoring: reordering, rewording in the posting's vocabulary, translating jargon titles to functional equivalents, and surfacing buried experience, using only the facts and reframings in the profile. Never assume anything listed under hard limits. tailored_fit is always >= as_is_fit.

Scale: 85-100 strong (meets core requirements at the posted level); 65-84 plausible (a gap they could talk around); 40-64 stretch (a key requirement missing); 0-39 poor (wrong discipline, level far off, or a credential/clearance they cannot get). Weigh real requirements, not keyword overlap. A required active TS/SCI with polygraph is a significant hurdle when the candidate only held one in the past.

"label": "apply_now" if as_is_fit >= 70; "tailor" if as_is_fit < 70 but tailored_fit >= 70; "stretch" if tailored_fit is 45-69; "skip" below 45.
"level": the candidate's standing for the posted seniority: "under" (role is junior to them), "match", or "stretch" (role is senior to them).
"reason": one plain sentence (max 25 words) to the candidate ("You ...") naming the main reason for the scores.
"tailoring": one sentence (max 25 words) naming the specific reframing that would raise the score, or "" if none is needed or none would help."""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "as_is_fit": {"type": "integer"},
                    "tailored_fit": {"type": "integer"},
                    "label": {"type": "string", "enum": ["apply_now", "tailor", "stretch", "skip"]},
                    "level": {"type": "string", "enum": ["under", "match", "stretch"]},
                    "reason": {"type": "string"},
                    "tailoring": {"type": "string"},
                },
                "required": ["id", "as_is_fit", "tailored_fit", "label", "level", "reason", "tailoring"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

def _parse(r):
    a = max(0, min(100, int(r["as_is_fit"])))
    t = max(a, min(100, int(r["tailored_fit"])))
    return {"asis": a, "fit": t, "label": r["label"], "level": r["level"], "reason": r["reason"].strip(),
            "tailor": (r.get("tailoring") or "").strip()}

def current_profile():
    """(profile_text, profile_hash) for the active resume profile, or the built-in default."""
    import resume
    prof = resume.load_active()
    goals = ""
    try:
        goals = paths.load_config().get("goals", "")
        import people
        if people.current():
            goals = people.settings().get("goals") or goals
    except Exception:
        pass
    if prof:
        return resume.profile_text(prof, goals), prof.get("_hash") or resume.profile_hash(prof)
    return "", "no_profile"  # callers check for a profile first

_lock = threading.Lock()

def api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return json.load(open(SECRETS)).get("anthropic_api_key") or None
    except Exception:
        return None

def claude_cli():
    """Path to the Claude Code CLI (signed in with the user's Claude subscription), or None."""
    return osdeps.find_exe("claude")

class CLIAuthError(Exception):
    pass

def cli_logged_in(path):
    try:
        r = subprocess.run([*osdeps.cmd(path), "auth", "status"], capture_output=True, text=True, timeout=30)
        return bool(json.loads(r.stdout).get("loggedIn"))
    except Exception:
        return False

def _score_batch_cli(path, cfg, profile, batch):
    work = paths.data("claude_work")  # empty dir so no project files/CLAUDE.md are picked up
    os.makedirs(work, exist_ok=True)
    msg = "Score these postings. Return one result per job id.\n\n" + "\n\n".join(_job_text(j) for j in batch)
    cmd = [*osdeps.cmd(path), "-p", "--model", cfg["model"], "--effort", cfg.get("effort", "low"), "--tools", "",
           "--system-prompt", SYSTEM + "\n\n" + profile, "--json-schema", json.dumps(SCHEMA),
           "--output-format", "json", "--no-session-persistence"]
    r = subprocess.run(cmd, input=msg, capture_output=True, text=True, timeout=600, cwd=work)
    try:
        out = json.loads(r.stdout)
    except Exception:
        raise RuntimeError((r.stderr or r.stdout)[:200])
    if out.get("is_error"):
        txt = str(out.get("result", ""))
        if "login" in txt.lower() or "auth" in txt.lower():
            raise CLIAuthError(txt[:200])
        raise RuntimeError(txt[:200])
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result") or "{}")
    return {x["id"]: _parse(x) for x in data.get("results", [])}

def load_all():
    """Cache: {"v": 3, "by_profile": {phash: {job_id: {"haiku": r, "sonnet": r, "opus": r}}}}.
    Each rating r carries fp (core info fingerprint), hl (highlights fingerprint) and facts (answer ids it knew)."""
    d = paths.load_json_cache(CACHE)  # missing -> None; unreadable -> CacheUnreadable (never treated as empty)
    if not isinstance(d, dict) or "by_profile" not in d:
        return {"v": 3, "by_profile": {}}
    if d.get("v") != 3:  # older single-rating format: those ratings were all made by Opus
        for ph, jobs in d["by_profile"].items():
            for jid, r in list(jobs.items()):
                if isinstance(r, dict) and "fit" in r:
                    jobs[jid] = {"opus": r}
        d["v"] = 3
    return d

def _job_text(j):
    sal = f'${j["salary_min"]:,}-${j["salary_max"]:,}' if j.get("salary_max") else "not listed"
    return (f'<job id="{j["id"]}">\nTitle: {j["title"]}\nCompany: {j["company"]} ({j.get("sector","")})\n'
            f'Location: {"; ".join(j["locations"][:4])} | Workplace: {j.get("workplace") or "unstated"} | '
            f'Clearance: {j.get("clearance") or "none mentioned"} | Salary: {sal}\n'
            f'Description:\n{(j.get("desc") or j.get("snippet") or "")[:3000]}\n</job>')

def _score_batch(client, cfg, profile, batch):
    import anthropic
    msg = "Score these postings. Return one result per job id.\n\n" + "\n\n".join(_job_text(j) for j in batch)
    resp = client.messages.create(
        model=cfg["model"],
        max_tokens=16000,
        system=SYSTEM + "\n\n" + profile,
        output_config={"effort": cfg.get("effort", "low"), "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": msg}],
    )
    if resp.stop_reason == "refusal":
        return {}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    out = {}
    for r in json.loads(text).get("results", []):
        out[r["id"]] = _parse(r)
    return out

def info_fp(profile_text):
    """Fingerprint of a block of candidate info."""
    import hashlib
    return hashlib.sha1(profile_text.encode()).hexdigest()[:12]

TIERS = ["haiku", "sonnet", "opus"]
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
TIER_RUN = {"haiku": {"batch_size": 25, "cli_concurrency": 6, "concurrency": 8},
            "sonnet": {"batch_size": 15, "cli_concurrency": 4, "concurrency": 6},
            "opus": {"batch_size": 15, "cli_concurrency": 3, "concurrency": 5}}
STOP = set("""a an and are as at be by for from has have in into is it of on or that the their this to was with will you your
experience years year skills ability knowledge working work strong including able using use etc""".split())

def info():
    """What Claude is told about the candidate, split so small changes can be handled cheaply:
    core (resume, reframings, goals) -> fp; confirmed highlights line -> hl; answers -> facts [(id, keywords)]."""
    text, phash = current_profile()
    facts, ft = [], ""
    try:
        import interview
        ft = interview.facts_text() or ""
        for f in interview.load_facts():
            words = [w for w in __import__("re").findall(r"[a-z0-9+#./-]{3,}", (f.get("requirement") or "").lower()) if w not in STOP]
            facts.append((f.get("id"), words))
    except Exception:
        pass
    lines = text.split("\n")
    hl_line = next((l for l in lines if l.startswith("Confirmed by the candidate:")), "")
    core = "\n".join(l for l in lines if l != hl_line)
    if ft:
        core = core.replace(ft, "")
    core = " ".join(core.split())  # removing the answers block leaves blank lines behind; don't let that count
    return {"text": text, "phash": phash, "fp": info_fp(core), "hl": info_fp(hl_line), "facts": facts}

def _fact_hits(words, j):
    """words are the answer's distinctive words (already filtered to ones most postings don't use)."""
    if not words:
        return False
    t = (j.get("title", "") + " " + (j.get("desc") or j.get("snippet") or "")).lower()
    return any(w in t for w in words)

def freshness(r, j, inf):
    """'fresh', 'maybe' (a small change touches this job: re-check cheaply first) or 'stale' (core info changed)."""
    if not r:
        return "missing"
    if r.get("fp") != inf["fp"]:
        return "stale"
    known = set(r.get("facts") or [])
    if r.get("hl") != inf["hl"] and (j.get("req") or {}).get("degrees") or (r.get("hl") != inf["hl"] and (j.get("req") or {}).get("licenses")):
        return "maybe"
    if any(fid not in known and _fact_hits(words, j) for fid, words in inf["facts"]):
        return "maybe"
    if r.get("dirty"):
        return "maybe"
    return "fresh"

def _restamp(r, inf):
    r["hl"] = inf["hl"]; r["facts"] = [fid for fid, _ in inf["facts"]]; r.pop("dirty", None)

def best(entry, j, inf):
    """The rating to show: the highest tier that's fresh, else the highest tier there is (marked stale)."""
    if not entry:
        return None, None, None
    for t in reversed(TIERS):
        if entry.get(t) and freshness(entry[t], j, inf) == "fresh":
            return t, entry[t], False
    for t in reversed(TIERS):
        if entry.get(t):
            return t, entry[t], True
    return None, None, None

def apply(jobs, cache, inf):
    for j in jobs:
        t, a, stale = best(cache.get(j["id"]), j, inf)
        if a:
            j["ai_fit"], j["ai_asis"], j["ai_label"] = a["fit"], a["asis"], a["label"]
            j["ai_level"], j["ai_reason"], j["ai_tailor"] = a["level"], a["reason"], a["tailor"]
            j["ai_tier"], j["ai_stale"], j["ai_at"] = t, stale, a.get("at", "")
        else:
            for k in ("ai_fit", "ai_asis", "ai_label", "ai_level", "ai_reason", "ai_tailor", "ai_tier", "ai_stale", "ai_at"):
                j.pop(k, None)

def _rate(todo, tier, inf, log):
    """Send jobs to one model; returns {id: rating} (stamped). Raises CLIAuthError on sign-in problems."""
    if not todo:
        return {}
    if not inf["text"].strip():
        raise ValueError("Upload and approve a resume first.")
    key, cli = api_key(), claude_cli()
    if not key and not (cli and cli_logged_in(cli)):
        raise CLIAuthError("Claude Code is not signed in.")
    cfg = {"model": MODELS[tier], "effort": "low", **TIER_RUN[tier]}
    bs = cfg["batch_size"]
    batches = [todo[i:i + bs] for i in range(0, len(todo), bs)]
    log(f"{tier.capitalize()} rating {len(todo)} jobs in {len(batches)} batches...")
    out, done, failed, t0 = {}, 0, 0, time.time()
    import datetime as _dt
    now = _dt.date.today().isoformat()
    client = None
    if key:
        import anthropic
        client = anthropic.Anthropic(api_key=key, max_retries=4)
    with cf.ThreadPoolExecutor(cfg["concurrency"] if key else cfg["cli_concurrency"]) as ex:
        futs = [ex.submit(_score_batch, client, cfg, inf["text"], b) if key else ex.submit(_score_batch_cli, cli, cfg, inf["text"], b) for b in batches]
        for f in cf.as_completed(futs):
            try:
                res = f.result()
            except CLIAuthError:
                for x in futs: x.cancel()
                _timing(tier, len(todo), len(batches), failed, t0, log, stopped="signed out")
                raise
            except Exception as e:
                log(f"{tier} batch failed: {type(e).__name__}: {str(e)[:150]}"); res = {}; failed += 1
            for v in res.values():
                v.update(fp=inf["fp"], hl=inf["hl"], facts=[fid for fid, _ in inf["facts"]], at=now)
            out.update(res)
            done += 1
            log(f"PROGRESS ai {done}/{len(batches)}")
    _timing(tier, len(todo), len(batches), failed, t0, log, rated=len(out))
    return out

TIMINGS = []  # per-tier timing of the current run, collected by jobfinder into the run history

def _timing(tier, jobs, batches, failed, t0, log, **extra):
    t = {"tier": tier, "jobs": jobs, "batches": batches, "failed": failed, "secs": round(time.time() - t0, 1), **extra}
    TIMINGS.append(t)
    log(f"TIMING {tier}: {jobs} jobs, {batches} batches, {failed} failed, {t['secs']}s" +
        (f", {extra['rated']} rated" if "rated" in extra else "") + (f" ({extra['stopped']})" if "stopped" in extra else ""))

def bestbets(appeal, match):
    import math
    return round(math.sqrt(max(0, appeal) * max(0, match if match is not None else 50)))

def run_funnel(jobs, budgets, refresh=False, saved=(), eligible=None, log=print):
    """Haiku on every eligible job, Sonnet on the best ~15%, Opus on the top ~300 (+ saved jobs).
    Normal runs (refresh=False) only fill missing ratings; the re-rate step (refresh=True) also redoes ratings made
    with older info: 'maybe' ones get a cheap Haiku check first and only climb to Sonnet/Opus if the score moved."""
    inf = info()
    allc = load_all()
    cache = allc["by_profile"].setdefault(inf["phash"], {})
    pool = [j for j in jobs if (eligible(j) if eligible else True)]
    # an answer only concerns jobs that mention its distinctive words ("salesforce"), not common ones ("administration")
    texts = [(j.get("title", "") + " " + (j.get("desc") or j.get("snippet") or "")).lower() for j in pool]
    def rare(words):
        out = []
        for w in words:
            df = sum(1 for t in texts if w in t) / max(1, len(texts))
            if df < 0.12:
                out.append(w)
        return out
    inf["facts"] = [(fid, rare(words)) for fid, words in inf["facts"]]
    status = "ok"
    saved = set(saved)
    def save():
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with _lock:
            paths.dump_json_atomic(CACHE, allc)
    def need(j, tier):
        r = (cache.get(j["id"]) or {}).get(tier)
        f = freshness(r, j, inf)
        return f == "missing" or (refresh and f != "fresh")
    try:
        # 1. Haiku: everyone, best Appeal first
        todo = sorted((j for j in pool if need(j, "haiku")), key=lambda j: -j.get("appeal", 0))[: budgets.get("haiku", 0)]
        old = {j["id"]: dict((cache.get(j["id"]) or {}).get("haiku") or {}) for j in todo}
        res = _rate(todo, "haiku", inf, log)
        for jid, r in res.items():
            e = cache.setdefault(jid, {})
            prev = old.get(jid) or {}
            e["haiku"] = r
            # a cheap check after a small change: if the score barely moved, the careful ratings above stay current
            if prev and prev.get("fp") == inf["fp"]:
                moved = abs(r["fit"] - prev.get("fit", r["fit"])) >= 5 or r["label"] != prev.get("label")
                for t in ("sonnet", "opus"):
                    if e.get(t) and e[t].get("fp") == inf["fp"]:
                        if moved: e[t]["dirty"] = True
                        else: _restamp(e[t], inf)
        if res: save()
        # tidy bookkeeping: ratings whose new answers don't concern them are still current
        for j in pool:
            for t, r in (cache.get(j["id"]) or {}).items():
                if r.get("fp") == inf["fp"] and not r.get("dirty") and freshness(r, j, inf) == "fresh":
                    _restamp(r, inf)
        def rank(tiers):
            # rank on the named tiers only, so a later, sharper rating doesn't reshuffle who gets picked
            def m(j):
                e = cache.get(j["id"]) or {}
                for t in tiers:
                    if e.get(t):
                        return e[t]["fit"]
                return None
            return sorted(pool, key=lambda j: -bestbets(j.get("appeal", 0), m(j)))
        # 2. Sonnet: best ~15% by Appeal x Haiku's Match
        ranked = rank(["haiku"])
        top_s = ranked[: max(0, int(len(ranked) * budgets.get("sonnet_pct", 15) / 100))]
        todo = [j for j in top_s if need(j, "sonnet")][: budgets.get("sonnet_max", 2000)]
        res = _rate(todo, "sonnet", inf, log)
        for jid, r in res.items():
            cache.setdefault(jid, {})["sonnet"] = r
        if res: save()
        # 3. Opus: top N by Appeal x Sonnet's Match (Haiku's where Sonnet hasn't looked), plus anything saved
        ranked = rank(["sonnet", "haiku"])
        top_o = ranked[: budgets.get("opus_top", 300)] + [j for j in pool if j["id"] in saved]
        seen, todo = set(), []
        for j in top_o:
            if j["id"] not in seen and need(j, "opus"):
                seen.add(j["id"]); todo.append(j)
        res = _rate(todo, "opus", inf, log)
        for jid, r in res.items():
            cache.setdefault(jid, {})["opus"] = r
        if res: save()
    except CLIAuthError:
        status = "cli_logged_out"
        log("Claude rating paused: Claude Code is not signed in.")
    save()
    apply(jobs, cache, inf)
    return status

def score_jobs(jobs, cfg, log=print):
    """Apply cached ratings; with cfg['max_new_per_run'] > 0, rate these specific jobs with Opus now
    (cfg['refresh_stale'] also redoes Opus ratings made with older info). Used by the per-job buttons."""
    inf = info()
    allc = load_all()
    cache = allc["by_profile"].setdefault(inf["phash"], {})
    status = "ok"
    n = cfg.get("max_new_per_run", 0)
    if n:
        todo = [j for j in jobs if freshness((cache.get(j["id"]) or {}).get("opus"), j, inf) == "missing"
                or (cfg.get("refresh_stale") and freshness((cache.get(j["id"]) or {}).get("opus"), j, inf) != "fresh")][:n]
        try:
            for jid, r in _rate(todo, "opus", inf, log).items():
                cache.setdefault(jid, {})["opus"] = r
            with _lock:
                paths.dump_json_atomic(CACHE, allc)
        except CLIAuthError:
            status = "cli_logged_out"
    apply(jobs, cache, inf)
    return status

def rescore_one(job, description, cfg):
    """Re-score a single job with Opus now (e.g. after the candidate answered questions about it)."""
    inf = info()
    j = dict(job, desc=description)
    try:
        res = _rate([j], "opus", inf, lambda m: None)
    except CLIAuthError:
        return None
    a = res.get(job["id"])
    if not a:
        return None
    with _lock:
        allc = load_all()
        allc["by_profile"].setdefault(inf["phash"], {}).setdefault(job["id"], {})["opus"] = a
        paths.dump_json_atomic(CACHE, allc)
    job["ai_fit"], job["ai_asis"], job["ai_label"] = a["fit"], a["asis"], a["label"]
    job["ai_level"], job["ai_reason"], job["ai_tailor"] = a["level"], a["reason"], a["tailor"]
    job["ai_tier"], job["ai_stale"], job["ai_at"] = "opus", False, a["at"]
    return a
