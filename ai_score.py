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
        return resume.profile_text(prof, goals), profile_keys(prof)[0]
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
    import claude_cli as _cc
    return _cc.path()

class CLIAuthError(Exception):
    pass

def cli_logged_in(path):
    try:
        import claude_cli as _cc
        r = osdeps.run_hidden([*osdeps.cmd(path), "auth", "status"], capture_output=True, text=True, timeout=30, env=_cc.child_env())
        return bool(json.loads(r.stdout).get("loggedIn"))
    except Exception:
        return False

def _usage(cfg, usage, batch, stub=False):
    """One line in DATA/claude_usage.jsonl for this batch (never lets a rating fail)."""
    try:
        import claude_usage
        claude_usage.record("Match ratings", cfg.get("model"), usage, len(batch), stub=stub)
    except Exception:
        pass

def _score_batch_cli(path, cfg, profile, batch):
    import claude_cli as _cc
    msg = "Score these postings. Return one result per job id.\n\n" + "\n\n".join(_job_text(j) for j in batch)
    if os.environ.get(_cc.STUB_ENV):
        # tests: a canned answer instead of Claude. {"_rate_all": {...one result without "id"...}} rates every job in
        # the batch the same way; otherwise the answer is used as is ({"results": [...]}).
        canned = _cc._stub(msg)
        if canned is not None:
            if isinstance(canned, dict) and "_rate_all" in canned:
                canned = {"results": [{**canned["_rate_all"], "id": j["id"]} for j in batch]}
            _usage(cfg, {}, batch, stub=True)
            return {x["id"]: _parse(x) for x in canned.get("results", [])}
    _cc.forbid_check(f"ai_score CLI {cfg['model']} x{len(batch)}")
    work = paths.data("claude_work")  # empty dir so no project files/CLAUDE.md are picked up
    os.makedirs(work, exist_ok=True)
    # the same lean command line as every other Siftwell call (no tools, skills, MCP or CLAUDE.md: claude_cli.command)
    cmd = _cc.command(path, cfg["model"], cfg.get("effort", "low"), SYSTEM + "\n\n" + profile, SCHEMA)
    def failed(why):     # a batch that brought nothing back is still listed in Settings
        try:
            import claude_usage
            claude_usage.record("Match ratings", cfg.get("model"), {}, len(batch), error=why)
        except Exception:
            pass
    try:
        r = osdeps.run_hidden(cmd, input=msg, capture_output=True, text=True, timeout=600, cwd=work, env=_cc.child_env(),
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        failed("timed out")
        raise
    try:
        out = json.loads(r.stdout)
        if not isinstance(out, dict):
            raise ValueError("not an object")
    except Exception:
        if _cc._lean_refused(path, r.stdout, r.stderr):
            return _score_batch_cli(path, cfg, profile, batch)
        failed("no readable answer")
        raise RuntimeError((r.stderr or r.stdout)[:200])
    if isinstance(out.get("usage"), dict):
        _usage(cfg, out["usage"], batch)   # what this batch really used, for Settings
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
    """Cache: {"v": 3, "rating_format": 1, "by_profile": {phash: {job_id: {"haiku": r, "sonnet": r, "opus": r}}}}.
    Each rating r carries fp (core info fingerprint), hl (highlights fingerprint), facts (answer ids it knew) and fmt
    (RATING_FORMAT it was made under; missing = 1). "v" is the file layout, not a reason to re-rate."""
    d = paths.load_json_cache(CACHE)  # missing -> None; unreadable -> CacheUnreadable (never treated as empty)
    if not isinstance(d, dict) or "by_profile" not in d:
        return {"v": 3, "rating_format": RATING_FORMAT, "by_profile": {}}
    d.setdefault("rating_format", 1)  # caches written before the stamp existed were all format 1
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
    import claude_cli as _cc
    _cc.forbid_check(f"ai_score API {cfg['model']} x{len(batch)}")
    import anthropic
    msg = "Score these postings. Return one result per job id.\n\n" + "\n\n".join(_job_text(j) for j in batch)
    resp = client.messages.create(
        model=cfg["model"],
        max_tokens=16000,
        system=SYSTEM + "\n\n" + profile,
        output_config={"effort": cfg.get("effort", "low"), "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": msg}],
    )
    u = getattr(resp, "usage", None)
    if u is not None:
        _usage(cfg, {k: getattr(u, k, 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens")}, batch)
    if resp.stop_reason == "refusal":
        return {}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    out = {}
    for r in json.loads(text).get("results", []):
        out[r["id"]] = _parse(r)
    return out

TIERS = ["haiku", "sonnet", "opus"]
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
TIER_RUN = {"haiku": {"batch_size": 25, "cli_concurrency": 6, "concurrency": 8},
            "sonnet": {"batch_size": 15, "cli_concurrency": 4, "concurrency": 6},
            "opus": {"batch_size": 15, "cli_concurrency": 3, "concurrency": 5}}
# The most one rating run may do, whoever asked (automatic runs, the nightly re-rate, the Re-rate panel, "Rate more").
# They are fixed numbers on purpose: what a run costs follows what a person can look at, not how many jobs their area
# has. Settings can lower them, never raise them. haiku: quick checks, most relevant first (pick_order). sonnet: second looks, only
# for jobs that already have a rating. opus: new most-careful ratings (jobs the person saved come on top, up to
# "saved", the most recently saved first). target: Target-tab ratings. quick: the automatic quick check after a
# settings change or board rebuild. A scheduled night (the update, then the re-rate after it) shares ONE such budget
# (jobfinder.night_budgets), so it never does 500 + 500 quick checks.
RUN_LIMITS = {"haiku": 500, "sonnet": 100, "opus": 50, "saved": 25, "target": 50, "quick": 200}

STOP = set("""a an and are as at be by for from has have in into is it of on or that the their this to was with will you your
experience years year skills ability knowledge working work strong including able using use etc""".split())

# ---------------------------------------------------------------- rating fingerprints
# A cached rating is shown as current when the fingerprints stored with it equal the ones computed now. They MUST only
# depend on the person's own data (resume profile, notes, answers, highlights, goals, target settings), never on code:
# no prompt or system text, model names, schemas, constants or wording of the text sent to Claude. That way installing
# a new release never makes existing ratings missing or stale, so nobody pays for the same ratings twice.
#
# RATING_FORMAT is the ONLY code-side switch. Bump it (1 -> 2) solely to deliberately invalidate every stored rating,
# e.g. when the scale itself changes meaning. Doing so makes every user re-rate their jobs, which costs them Claude
# tokens and plan limits, so it must be a conscious decision and announced in the release notes.
RATING_FORMAT = 1


def info_fp(text):
    """Fingerprint of a block of text (12 hex chars of SHA-1)."""
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def _ws(s):
    return " ".join(str(s or "").split())


def user_goals():
    """The person's own goals text: their profile's goals, else the household config's (DATA/config.json). Shipped
    defaults (config.default.json) are code, so they're left out on purpose."""
    cfg = paths.load_json_cache(paths.CONFIG)  # missing -> None; unreadable -> CacheUnreadable (after a short retry)
    goals = (cfg.get("goals") if isinstance(cfg, dict) else None) or ""
    import people
    if people.current():
        # missing file = no goals of their own; an unreadable one raises (never a silently different fingerprint)
        goals = people.settings_strict(missing_ok=True).get("goals") or goals
    return goals


# The renderers below are a FROZEN hashing format, not a prompt. They reproduce, byte for byte, the candidate text the
# app sent Claude when rating format 1 was introduced, so ratings stored before this change keep matching. Never edit
# them to follow prompt changes (edit resume.profile_text / interview.facts_text instead, which are free to change).
_LEVELS_V1 = {"yes": "Yes", "some": "Some / a little", "no": "No"}


def _fp_core_lines(prof):
    lines = [f"CANDIDATE PROFILE ({prof.get('location','')}, ~{prof.get('years_experience','?')} years experience)",
             "", "Summary: " + prof.get("summary", ""), ""]
    for label, key in (("Clearances", "clearances"), ("Education", "education"), ("Certifications", "certifications"),
                       ("Skills", "skills"), ("Languages", "languages")):
        if prof.get(key):
            lines.append(f"{label}: " + "; ".join(prof[key]))
    lines += ["", "Experience:"]
    for e in prof.get("experience", []):
        lines.append(f"- {e['title']}, {e['employer']} ({e['dates']})")
        lines += [f"    * {h}" for h in e.get("highlights", [])]
    lines += ["", "Honest reframings this candidate can use when tailoring:"]
    for r in prof.get("reframings", []):
        lines.append(f"- {r['angle']} (opens: {', '.join(r['target_titles'])}; evidence: {' / '.join(r['evidence'])})")
    lines += ["", "Hard limits (must never be claimed): " + "; ".join(prof.get("hard_limits", []))]
    if prof.get("notes"):
        lines += ["", "Additional facts confirmed by the candidate (not on the resume): " + prof["notes"]]
    return lines


def _fp_facts_text(facts):
    have = [f for f in facts if f.get("level") != "no"]
    lack = [f for f in facts if f.get("level") == "no"]
    lines = []
    if have:
        lines.append("Facts the candidate confirmed in Q&A (not on the resume). Each has a polished statement to work from and the "
                     "candidate's raw note for nuance. Treat raw notes as facts, never as copy: write resume text in professional "
                     "language. Use facts only as strongly as stated: 'Some / a little' means familiarity or limited use, never "
                     "expertise; never add numbers, dates, tools or outcomes the answer doesn't contain.")
        for f in have:
            body = f.get("polished") or f.get("answer") or "(no details given)"
            raw = f" (raw note: {f['answer']})" if f.get("polished") and f.get("answer") else ""
            lines.append(f"- {f.get('requirement')} [{_LEVELS_V1.get(f.get('level'), '')}]: {body}{raw}")
    if lack:
        lines.append("The candidate confirmed they do NOT have (never claim): " + "; ".join(f.get("requirement") or "" for f in lack))
    return "\n".join(lines)


def _fp_hl_line(h):
    if not h:
        return ""
    degs = "; ".join(f"{d.get('level','')} {('in ' + d['field']) if d.get('field') else ''}".strip() for d in h.get("degrees") or [])
    lic = "; ".join(l.get("name", "") for l in h.get("licenses") or [])
    m = h.get("management") or {}
    return ("Confirmed by the candidate: degrees: " + (degs or "none") + "; licenses/certifications: " + (lic or "none")
            + (f"; years of experience: {h['years_experience']}" if h.get("years_experience") is not None else "")
            + (f"; currently manages {m['direct_reports']} direct report(s)" if m.get("direct_reports") is not None else ""))


def _person_facts():
    """The person's confirmed answers. No file -> []. A file that exists but can't be read -> retried briefly, then
    paths.CacheUnreadable (a silently different fingerprint would re-rate everything)."""
    import interview
    d = paths.load_json_cache(interview.FACTS())
    return d if isinstance(d, list) else []


def _person_highlights():
    import highlights, people
    raw = paths.load_json_cache(highlights.path(people.current()))
    if not isinstance(raw, dict) or (raw.get("extracted") is None and not raw.get("edits")):
        return None
    return highlights.merged(raw)


def profile_keys(prof):
    """(key, older keys) for the person's rating caches. The key is the hash of the person's own profile data (job
    titles are not part of it). Older keys of the same person are adopted so no stored rating is lost: the _hash stored
    in the profile (made by an older version, so it may include job titles), and the older formulas applied to today's
    data (with job titles; before whitespace was normalized)."""
    import resume
    key = resume.profile_hash(prof)
    old = []
    for h in (prof.get("_hash"), *(prof.get("_hash_aliases") or []), resume.profile_hash_v1(prof),
              resume.profile_hash_legacy(prof)):
        if h and h != key and h not in old:
            old.append(h)
    return key, old


def adopt(by_key, key, old_keys):
    """Move ratings stored under older keys of the same profile to its current key (never across people). Only when the
    current key is missing or empty; every matching old key is merged in (the newest rating wins a conflict)."""
    if by_key.get(key):
        return False
    moved = False
    for k in old_keys:
        if k == key or k not in by_key:
            continue
        old = by_key.pop(k)
        cur = by_key.get(key)
        if not cur:
            by_key[key] = old
        elif isinstance(cur, dict) and isinstance(old, dict):
            for jid, r in old.items():
                if jid not in cur:
                    cur[jid] = r
                elif isinstance(r, dict) and isinstance(cur[jid], dict):
                    # same job rated under both: keep the newest rating (per tier for Match ratings)
                    if "at" in r or "at" in cur[jid]:
                        if str(r.get("at") or "") > str(cur[jid].get("at") or ""):
                            cur[jid] = r
                    else:
                        for tier, rr in r.items():
                            ct = cur[jid].get(tier)
                            if not ct or (isinstance(rr, dict) and isinstance(ct, dict)
                                          and str(rr.get("at") or "") > str(ct.get("at") or "")):
                                cur[jid][tier] = rr
        moved = True
    return moved


def accept_current(pid):
    """"Keep my current ratings": mark this person's ratings made by older versions of the app (no fingerprint, or made
    before highlights were fingerprinted, so no hl) as made from their current data, so they aren't re-rated. Ratings
    that carry a current-scheme fingerprint (fp and hl) that differs from today's are left alone: they were made from
    different data. Ratings marked dirty are left alone too. Only this person's cache entry is touched; nothing calls
    Claude. Returns {tier: {"stamped": n, "already_current": n, "left_alone": n, "dirty": n}}."""
    import people
    people.set_current(pid)
    inf = info()
    counts = {t: {"stamped": 0, "already_current": 0, "left_alone": 0, "dirty": 0} for t in TIERS}
    with _lock:
        allc = load_all()
        adopt(allc["by_profile"], inf["phash"], inf["phash_old"])
        entry = allc["by_profile"].get(inf["phash"]) or {}
        for e in entry.values():
            for t, r in e.items():
                c = counts.setdefault(t, {"stamped": 0, "already_current": 0, "left_alone": 0, "dirty": 0})
                if not isinstance(r, dict):
                    continue
                if r.get("dirty"):
                    c["dirty"] += 1
                elif fp_ok(r, inf) and "hl" in r:
                    c["already_current"] += 1
                elif "fp" not in r or "hl" not in r:
                    stamp(r, inf)
                    c["stamped"] += 1
                else:
                    c["left_alone"] += 1
        if any(c["stamped"] for c in counts.values()):
            paths.dump_json_atomic(CACHE, allc)
    return counts


def fingerprints(prof=None):
    """Everything that decides whether a stored rating is current. Data only (see the note above RATING_FORMAT).
      phash / phash_old  cache key (+ older keys to adopt)
      fp                 core info: resume profile, notes, goals (whitespace-normalized)
      hl / hl_old        the confirmed-highlights line (normalized / as stored by older versions)
      pfp / pfp_old      Target tab: core + answers + highlights + goals (normalized / as stored by older versions)
      facts              [(answer id, its keywords)] for the cheap 'maybe' re-check
      tfp / fact_keys    Target tab: pfp without the answers, and [(answer id:content, its keywords)] (see pivot.Freshness)"""
    import re
    if prof is None:
        import resume
        prof = resume.load_active()
    if not prof:
        e = info_fp("")
        return {"phash": "no_profile", "phash_old": [], "fp": e, "hl": e, "hl_old": e, "pfp": e, "pfp_old": e, "facts": [],
                "tfp": e, "fact_keys": []}
    goals = user_goals()
    facts = _person_facts()
    core = _fp_core_lines(prof)
    hl_line = _fp_hl_line(_person_highlights())
    full = list(core)
    ft = _fp_facts_text(facts)
    if ft:
        full += ["", ft]
    if hl_line:
        full += ["", hl_line]
    if goals:
        core += ["", goals]
        full += ["", goals]
    full_text = "\n".join(full)
    phash, old = profile_keys(prof)
    kw, fkeys = [], []
    for f in facts:
        words = [w for w in re.findall(r"[a-z0-9+#./-]{3,}", (f.get("requirement") or "").lower()) if w not in STOP]
        kw.append((f.get("id"), words))
        # one answer as the Target tab tracks it: its id plus what it says now (so an edited answer counts as changed)
        fkeys.append((f"{f.get('id')}:" + info_fp(_ws(_fp_facts_text([f])))[:8], words))
    # tfp: everything in pfp EXCEPT the answers (core + highlights + goals). With fact_keys it lets the Target tab see
    # that only an answer changed, and re-check just the jobs that mention that answer's topic (pivot.Freshness).
    # Additive: fp / hl / pfp and the cache keys above are computed exactly as before.
    rest = list(_fp_core_lines(prof)) + (["", hl_line] if hl_line else []) + (["", goals] if goals else [])
    return {"phash": phash, "phash_old": old, "fp": info_fp(_ws("\n".join(core))),
            "hl": info_fp(_ws(hl_line)), "hl_old": info_fp(hl_line),
            "pfp": info_fp(_ws(full_text)), "pfp_old": info_fp(full_text), "facts": kw,
            "tfp": info_fp(_ws("\n".join(rest))), "fact_keys": fkeys}


def info():
    """What Claude is told about the candidate (text: the prompt, free to change) plus the fingerprints of the
    person's data, split so small changes can be handled cheaply: core (resume, reframings, goals) -> fp; confirmed
    highlights line -> hl; answers -> facts [(id, keywords)]."""
    text, _ = current_profile()
    f = fingerprints()
    return {"text": text, **f}


def fmt_ok(r):
    return (r or {}).get("fmt", 1) == RATING_FORMAT


def fp_ok(r, inf):
    """Rating made from the same core info, under the current RATING_FORMAT."""
    return bool(r) and fmt_ok(r) and r.get("fp") == inf["fp"]


def hl_ok(r, inf):
    return r.get("hl") in (inf["hl"], inf.get("hl_old"))


def stamp(r, inf):
    r.update(fp=inf["fp"], hl=inf["hl"], facts=[fid for fid, _ in inf["facts"]], fmt=RATING_FORMAT)

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
    if not fp_ok(r, inf):
        return "stale"
    known = set(r.get("facts") or [])
    if not hl_ok(r, inf) and ((j.get("req") or {}).get("degrees") or (j.get("req") or {}).get("licenses")):
        return "maybe"
    if any(fid not in known and _fact_hits(words, j) for fid, words in inf["facts"]):
        return "maybe"
    if r.get("dirty"):
        return "maybe"
    return "fresh"

def _restamp(r, inf):
    stamp(r, inf); r.pop("dirty", None)

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

def _rate(todo, tier, inf, log, on_batch=None):
    """Send jobs to one model; returns {id: rating} (stamped). Raises CLIAuthError on sign-in problems.
    on_batch(res) runs (in this thread) after each finished batch, so callers can save as they go. Once the person
    presses Stop (claude_cli.stop_requested), batches not yet sent are skipped; ones already sent finish."""
    import claude_cli as _cc
    if not todo:
        return {}
    if not inf["text"].strip():
        raise ValueError("Upload and approve a resume first.")
    key, cli = api_key(), claude_cli()
    if not key and not _cc.claude_ready():
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
    def one(b):
        if _cc.stop_requested():
            return None
        return _score_batch(client, cfg, inf["text"], b) if key else _score_batch_cli(cli, cfg, inf["text"], b)
    skipped = 0
    with cf.ThreadPoolExecutor(cfg["concurrency"] if key else cfg["cli_concurrency"]) as ex:
        futs = [ex.submit(one, b) for b in batches]
        for f in cf.as_completed(futs):
            try:
                res = f.result()
            except CLIAuthError:
                for x in futs: x.cancel()
                _timing(tier, len(todo), len(batches), failed, t0, log, stopped="signed out")
                raise
            except Exception as e:
                log(f"{tier} batch failed: {type(e).__name__}: {str(e)[:150]}"); res = {}; failed += 1
            if res is None:
                skipped += 1; res = {}
                if skipped == 1:
                    log(f"Stopping: {tier.capitalize()} batches already sent will finish and be kept.")
            for v in res.values():
                stamp(v, inf); v["at"] = now
            out.update(res)
            if res and on_batch:
                on_batch(res)
            done += 1
            log(f"PROGRESS ai {done}/{len(batches)} {tier}")
    _timing(tier, len(todo), len(batches), failed, t0, log, rated=len(out), **({"stopped": "stopped by you"} if skipped else {}))
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

def pick_order(j):
    """Which unrated jobs get this run's quick checks: the most relevant to the person's own work first (the free
    Relevance score from their what-to-look-for sheet, lookfor.py), then the highest Appeal. Jobs with no Relevance
    (no sheet yet) simply go by Appeal, as before. Only the ORDER of rating depends on the sheet: fingerprints and
    cache keys don't, so changing the sheet never makes a stored rating stale."""
    rel = j.get("rel")
    return (-(rel if rel is not None else 0), -j.get("appeal", 0), j["id"])

# The exploration share of an automatic run: Relevance goes by titles, so a job whose title the person's sheet doesn't
# name is never rated first, and Claude's ratings (which Relevance learns from, lookfor.learn_from_ratings) can't show
# what the titles miss. This share of the quick checks goes to the jobs just below the cut with the strongest other
# signals (lookfor's job["rel_x"]: an employer the person saved or applied at, title words that come with high Match,
# posting text like the highly rated ones; then Appeal). Inside RUN_LIMITS: it replaces picks, never adds any.
EXPLORE_SHARE = 0.10

def explore_key(j):
    return (-((j.get("rel_x") or 0) + 0.3 * (j.get("appeal") or 0) + 0.3 * (j.get("rel") or 0)), j["id"])

def pick_haiku(cands, n, explore=0.0):
    """The n jobs a run gives quick checks: by pick_order, except a share `explore` (0-1) of them, which goes to the
    best of the rest by explore_key (only jobs with some signal: rel_x > 0). Never more than n; the same jobs as plain
    pick_order when there are n or fewer, or nothing to explore."""
    order = sorted(cands, key=pick_order)
    k = int(n * max(0.0, min(0.5, explore)))
    if k <= 0 or len(order) <= n:
        return order[:n]
    main, rest = order[:n - k], order[n - k:]
    extra = sorted((j for j in rest if (j.get("rel_x") or 0) > 0), key=explore_key)[:k]
    got = {j["id"] for j in extra}
    fill = [j for j in rest if j["id"] not in got][:k - len(extra)]
    return main + sorted(extra + fill, key=pick_order)

def _prepare(jobs, eligible):
    """Shared set-up for a rating run: info + fingerprints, this profile's cache, the eligible pool, and answers
    narrowed to their distinctive words."""
    inf = info()
    allc = load_all()
    adopt(allc["by_profile"], inf["phash"], inf["phash_old"])
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
    return inf, allc, cache, pool

def rank_match(entry, tiers):
    """Match used for ranking: the first of `tiers` this job has a rating from (None if none)."""
    entry = entry or {}
    for t in tiers:
        if entry.get(t):
            return entry[t]["fit"]
    return None

BEST_AVAILABLE = ["opus", "sonnet", "haiku"]

def mark_state(jobs, pool, cache, inf):
    """For the Re-rate panel's counts: on each job Claude would rate, ai_rs = one letter per tier (haiku, sonnet,
    opus): "-" no rating, "s" needs a fresh one (older info), "f" current; ai_bb = its Best bets score with the best
    available Match (Opus, else Sonnet, else Haiku). Jobs outside the pool get neither."""
    ids = {j["id"] for j in pool}
    code = {"missing": "-", "fresh": "f"}
    for j in jobs:
        if j["id"] not in ids:
            j.pop("ai_rs", None); j.pop("ai_bb", None)
            continue
        e = cache.get(j["id"]) or {}
        j["ai_rs"] = "".join(code.get(freshness(e.get(t), j, inf), "s") for t in TIERS)
        j["ai_bb"] = bestbets(j.get("appeal", 0), rank_match(e, BEST_AVAILABLE))

def run_funnel(jobs, budgets, refresh=False, saved=(), eligible=None, log=print, tiers=None, force=False, pick="funnel",
               only_ids=None, prepare=None, explore=0.0):
    """One rating run, within RUN_LIMITS: Haiku on up to 500 eligible jobs (most relevant first, then best Appeal:
    pick_order; prepare(jobs), if given, is called with the picked jobs first, to fetch any posting text still missing), Sonnet on up to 100
    of the best jobs that already have a rating, Opus on up to 50 of the top ones (+ up to 25 saved jobs, the most
    recently saved first: `saved` is an ordered list).
    budgets: {"haiku": n, "sonnet_pct": share of the rated jobs Sonnet may look at, "sonnet_max": n, "opus_top": how far
    down the ranking Opus may look, "opus_max": n}; anything above RUN_LIMITS is cut to it. A job nobody has rated yet
    (the board shows it with no Match) is never sent to Sonnet or Opus on a guessed score: it waits for its Haiku check.
    Normal runs (refresh=False) only fill missing ratings; the re-rate step (refresh=True) also redoes ratings made
    with older info: 'maybe' ones get a cheap Haiku check first and only climb to Sonnet/Opus if the score moved.
    Re-rate panel options: tiers (which models run), force (rate the picked jobs again even if current; only when the
    person asks), pick="best" (rank by Best bets with the best available Match instead of the funnel's per-step
    ranking), only_ids (Haiku only looks at these jobs: the automatic check of new listings).
    explore: the share of the Haiku picks that goes to exploration (pick_haiku; automatic runs pass EXPLORE_SHARE).
    Every finished batch is saved right away, so a stopped run keeps what it got."""
    import claude_cli as _cc
    import math
    tiers = list(tiers or TIERS)
    inf, allc, cache, pool = _prepare(jobs, eligible)
    status = "ok"
    saved_order = list(dict.fromkeys(saved)) if isinstance(saved, (list, tuple)) else sorted(saved)
    saved = set(saved_order)
    cap = lambda key, limit: max(0, min(RUN_LIMITS[limit], int(budgets.get(key, RUN_LIMITS[limit]) or 0)))
    n_haiku = max(0, min(RUN_LIMITS["quick" if only_ids is not None else "haiku"], int(budgets.get("haiku", 0) or 0)))
    n_sonnet = cap("sonnet_max", "sonnet") if budgets.get("sonnet_pct", 15) else 0
    n_opus = cap("opus_max", "opus") if budgets.get("opus_top", 50) else 0
    if not api_key() and not _cc.claude_ready():
        # Siftwell works without Claude: skip quietly (one line, only when a rating run was really asked for)
        if any(budgets.get(k) for k in ("haiku", "sonnet_pct", "opus_top")):
            log("Claude isn't connected, so Match ratings are skipped (Appeal, filters and search still work).")
        apply(jobs, cache, inf)
        mark_state(jobs, pool, cache, inf)
        return "no_claude"
    def save():
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with _lock:
            paths.dump_json_atomic(CACHE, allc)
    def need(j, tier):
        if force:
            return True
        r = (cache.get(j["id"]) or {}).get(tier)
        f = freshness(r, j, inf)
        return f == "missing" or (refresh and f != "fresh")
    def keep(tier):
        def put(res):
            for jid, r in res.items():
                cache.setdefault(jid, {})[tier] = r
            save()
        return put
    def rank(tiers_):
        # rank on the named tiers only, so a later, sharper rating doesn't reshuffle who gets picked
        # (ties broken by job id, the same way the Re-rate panel counts them). Only jobs that have one of those
        # ratings: an unrated job has no Match to rank by.
        rated = [j for j in pool if rank_match(cache.get(j["id"]), tiers_) is not None]
        return sorted(rated, key=lambda j: (-bestbets(j.get("appeal", 0), rank_match(cache.get(j["id"]), tiers_)), j["id"]))
    try:
        # 1. Haiku: the most relevant first, then best Appeal, up to this run's limit (the rest wait for the next run
        #    or "Rate more")
        if "haiku" in tiers:
            hpool = pool if only_ids is None else [j for j in pool if j["id"] in only_ids]
            todo = pick_haiku([j for j in hpool if need(j, "haiku")], n_haiku, explore if pick == "funnel" and not force else 0.0)
            if prepare and todo:
                try:
                    prepare(todo, log)
                except Exception as e:
                    log(f"Couldn't fetch missing posting text: {type(e).__name__}: {str(e)[:120]}")
            old = {j["id"]: dict((cache.get(j["id"]) or {}).get("haiku") or {}) for j in todo}
            was = {j["id"]: freshness((cache.get(j["id"]) or {}).get("haiku"), j, inf) for j in todo}
            def put_haiku(res):
                for jid, r in res.items():
                    e = cache.setdefault(jid, {})
                    prev = old.get(jid) or {}
                    e["haiku"] = r
                    # a cheap check after a small change: if the score barely moved, the careful ratings above stay
                    # current. (A forced second look at a current rating changes nothing above it.)
                    if prev and fp_ok(prev, inf) and was.get(jid) != "fresh":
                        moved = abs(r["fit"] - prev.get("fit", r["fit"])) >= 5 or r["label"] != prev.get("label")
                        for t in ("sonnet", "opus"):
                            if e.get(t) and fp_ok(e[t], inf):
                                if moved: e[t]["dirty"] = True
                                else: _restamp(e[t], inf)
                save()
            _rate(todo, "haiku", inf, log, on_batch=put_haiku)
        # tidy bookkeeping: ratings whose new answers don't concern them are still current
        for j in pool:
            for t, r in (cache.get(j["id"]) or {}).items():
                if fp_ok(r, inf) and not r.get("dirty") and freshness(r, j, inf) == "fresh":
                    _restamp(r, inf)
        # 2. Sonnet: the best ~15% of the Haiku-rated jobs by Appeal x Haiku's Match, up to this run's limit
        if "sonnet" in tiers and n_sonnet and not _cc.stop_requested():
            ranked = rank(["haiku"] if pick == "funnel" else BEST_AVAILABLE)
            top_s = ranked[: max(0, math.ceil(len(ranked) * max(0, min(100, budgets.get("sonnet_pct", 15))) / 100))]
            todo = [j for j in top_s if need(j, "sonnet")][:n_sonnet]
            _rate(todo, "sonnet", inf, log, on_batch=keep("sonnet"))
        # 3. Opus: the top N by Appeal x Sonnet's Match (Haiku's where Sonnet hasn't looked), up to this run's limit
        #    of new ratings, plus the jobs the person saved
        if "opus" in tiers and n_opus and not _cc.stop_requested():
            ranked = rank(["sonnet", "haiku"] if pick == "funnel" else BEST_AVAILABLE)
            todo = [j for j in ranked[: max(0, int(budgets.get("opus_top", 50)))] if need(j, "opus")][:n_opus]
            seen = {j["id"] for j in todo}
            by_id = {j["id"]: j for j in pool}
            n_saved = max(0, min(RUN_LIMITS["saved"], int(budgets.get("saved_max", RUN_LIMITS["saved"]))))
            todo += [by_id[i] for i in saved_order if i in by_id and i not in seen and need(by_id[i], "opus")][:n_saved]
            _rate(todo, "opus", inf, log, on_batch=keep("opus"))
    except CLIAuthError:
        status = "cli_logged_out"
        log("Claude rating paused: Claude Code is not signed in.")
    save()
    apply(jobs, cache, inf)
    mark_state(jobs, pool, cache, inf)
    return status

def score_jobs(jobs, cfg, log=print):
    """Apply cached ratings; with cfg['max_new_per_run'] > 0, rate these specific jobs with Opus now
    (cfg['refresh_stale'] also redoes Opus ratings made with older info). Used by the per-job buttons."""
    inf = info()
    allc = load_all()
    adopt(allc["by_profile"], inf["phash"], inf["phash_old"])
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
        adopt(allc["by_profile"], inf["phash"], inf["phash_old"])
        allc["by_profile"].setdefault(inf["phash"], {}).setdefault(job["id"], {})["opus"] = a
        paths.dump_json_atomic(CACHE, allc)
    job["ai_fit"], job["ai_asis"], job["ai_label"] = a["fit"], a["asis"], a["label"]
    job["ai_level"], job["ai_reason"], job["ai_tailor"] = a["level"], a["reason"], a["tailor"]
    job["ai_tier"], job["ai_stale"], job["ai_at"] = "opus", False, a["at"]
    return a
