"""What Siftwell looks for: one sheet per profile (DATA/people/<id>/lookfor.json) and the free Relevance score.

The sheet says, in plain words, what kind of work this person does: the job titles they would hold next (their most
recent title, other names employers use for it, one step up), related roles they could move into, their main skills
and tools, and their field. Every job on the board gets a Relevance score (0-100) from it with plain code: no Claude.

Where the sheet comes from, in layers:
  1. always: plain code from the person's own data (most recent job title, job titles to search for, earlier jobs,
     skills), widened with the O*NET occupation extract in assets/onet (other names for the occupation, related
     occupations, typical tools and task words). So "RN" finds "Registered Nurse" and "Staff Nurse" with no Claude.
  2. with Claude: the resume reader's own answer (resume.build_profile returns "look_for" in the same call), or one
     small call after a hand-made profile or a changed job title (suggest). Never at upgrade, never per job.
  3. the person's own edits (added and removed chips), which always win and survive every rebuild.

Nothing here is part of a rating fingerprint or cache key (ai_score.fingerprints, pivot.cache_keys): changing the
sheet re-orders the board and changes which jobs are rated NEXT, but never makes a stored rating stale.

Learning (learn.json next to the sheet): saving or applying to a job nudges jobs with similar titles up a little,
hiding one nudges similar titles down. Bounded (see NUDGE_UP / NUDGE_DOWN), listed on the profile page, one-click reset."""
import datetime as dt, gzip, hashlib, json, math, os, re, threading

import paths, people

FILE, LEARN_FILE = "lookfor.json", "lookfor_learn.json"
ONET_FILE = os.path.join(paths.ASSETS, "onet", "onet.json.gz")
VERSION = 1

# Tier weights: how much a title match in each group counts (the most recent job counts most).
TIERS = {"same": 1.0, "occ": 0.9, "wanted": 0.85, "up": 0.85, "related": 0.6, "past": 0.5, "keyword": 0.5}
TIER_WORDS = {"same": "your job title", "occ": "another name for your job", "wanted": "a title you search for",
              "up": "one step up", "related": "a related role", "past": "a job you held before", "keyword": "a title word from your profile"}
NUDGE_UP, NUDGE_DOWN, LEARN_KEEP = 8, 10, 300
MAX_TITLES, MAX_SKILLS = 60, 40

# The 23 SOC major groups under plain names (the first two digits of an O*NET code).
FIELDS = {"11": "Management", "13": "Business and finance", "15": "Computers and math", "17": "Architecture and engineering",
          "19": "Science", "21": "Community and social services", "23": "Legal", "25": "Education", "27": "Arts, design and media",
          "29": "Healthcare", "31": "Healthcare support", "33": "Protective services", "35": "Food service",
          "37": "Cleaning and grounds", "39": "Personal care and service", "41": "Sales", "43": "Office and administrative support",
          "45": "Farming, fishing and forestry", "47": "Construction and trades", "49": "Installation, maintenance and repair",
          "51": "Production and manufacturing", "53": "Transportation and moving", "55": "Military"}

# ---------------------------------------------------------------- words
_SMALL = {"and", "of", "the", "for", "in", "at", "to", "a", "an", "or", "with", "on", "by", "per"}
# level words carry no weight: "Senior Registered Nurse II" is the same job as "Registered Nurse"
LEVEL = {"senior", "sr", "junior", "jr", "lead", "principal", "i", "ii", "iii", "iv", "v", "vi", "level", "entry", "mid",
         "experienced", "trainee", "1", "2", "3", "4", "5", "6"}
_TOK = re.compile(r"[a-z0-9]+(?:[+#]+)?")


def stem(w):
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def tokens(title):
    """Whole words of a title, lower case, plural folded, small words dropped: 'Registered Nurses (RN) - ICU' ->
    ['registered', 'nurse', 'rn', 'icu']."""
    t = (title or "").lower().replace("&", " and ").replace("'", "")
    return [stem(w) for w in _TOK.findall(t) if w not in _SMALL]


def clean_title(t):
    return " ".join(str(t or "").replace("’", "'").split())[:80]


# ---------------------------------------------------------------- the O*NET extract
_ONET, _OLOCK = {}, threading.Lock()


def onet():
    """The shipped extract (see scripts/build_onet.py), or an empty one if the file is missing: everything still works
    from the person's own titles, just without the widening."""
    if not _ONET:
        with _OLOCK:
            if not _ONET:
                try:
                    with gzip.open(ONET_FILE, "rt", encoding="utf-8") as f:
                        d = json.load(f)
                except Exception:
                    d = {"occ": {}, "df": {}, "titles": 1, "version": ""}
                d["_n"] = max(1, len(d.get("occ") or {}))
                _ONET.update(d)
    return _ONET


_WCACHE = {}


def weight(tok):
    """How much a title word counts: a word few occupations use (nurse, rn, electrician) far more than one hundreds
    use (manager, technician); level words nothing. From the extract's count of occupations per word."""
    w = _WCACHE.get(tok)
    if w is None:
        if tok in LEVEL:
            w = 0.0
        else:
            o = onet()
            idf = math.log((o["_n"] + 1) / (o["df"].get(tok, 1) + 1))
            w = idf * idf
        _WCACHE[tok] = w
    return w


def _tw(toks):
    return sum(weight(t) for t in set(toks))


def _head(seq):
    """The main word of a title: the last word before any "of"/comma tail ("Director of Nursing" -> director)."""
    return seq[-1] if seq else None


GENERIC_W = 10.0   # a one-word name lighter than this (used by 40+ occupations: "Manager", "Technician") says little by itself

_INDEX = {}


def _name_index():
    """{normalized title: [codes]} over every occupation title and other name (built once, ~0.5 s)."""
    if not _INDEX:
        idx = {}
        for code, o in onet()["occ"].items():
            for k, t in enumerate([o["t"]] + o["a"]):
                key = " ".join(sorted(set(x for x in tokens(t) if x not in LEVEL)))
                if key:
                    idx.setdefault(key, []).append((0 if k == 0 else 1 if k <= o["n"] else 2, code))
        _INDEX.update(idx)
    return _INDEX


def find_occupations(title, limit=2):
    """O*NET occupations for a typed job title, best first: [(code, how sure 0-1)]. Exact names first ("RN",
    "Staff Nurse"), then the closest names by shared words. [] when nothing is close enough."""
    toks = [t for t in tokens(title) if t not in LEVEL]
    if not toks:
        return []
    idx = _name_index()
    key = " ".join(sorted(set(toks)))
    if key in idx:
        seen, out = set(), []
        for _, code in sorted(idx[key]):
            if code not in seen:
                seen.add(code); out.append((code, 1.0))
        return out[:limit]
    mine, mw = set(toks), _tw(toks)
    if mw <= 0:
        return []
    best = {}
    for k, lst in idx.items():
        ks = set(k.split())
        shared = mine & ks
        if not shared:
            continue
        sw = _tw(shared)
        sim = sw / (0.5 * mw + 0.5 * _tw(ks))
        if sim >= 0.72:
            for rank, code in lst:
                s = sim - 0.01 * rank
                if s > best.get(code, 0):
                    best[code] = s
    if not best:
        # nothing close: the nearest name that shares the title's main word ("5th Grade Teacher" -> a teacher), if any
        head, top = toks[-1], (0.0, None)
        for k, lst in idx.items():
            ks = k.split()
            if head in ks:
                sim = _tw(mine & set(ks)) / (0.5 * mw + 0.5 * _tw(ks))
                if sim > top[0]:
                    top = (sim, min(lst)[1])
        if top[1] and top[0] >= 0.45:
            best[top[1]] = top[0]
    return sorted(((c, round(s, 2)) for c, s in best.items()), key=lambda x: (-x[1], x[0]))[:limit]


def occ_names(code, common_only=False):
    o = onet()["occ"].get(code)
    if not o:
        return []
    return [o["t"]] + (o["a"][:o["n"]] if common_only else o["a"])


def occ_title(code):
    o = onet()["occ"].get(code)
    return o["t"] if o else code


# ---------------------------------------------------------------- the sheet file
def path(pid=None):
    return people.pdir(FILE, pid=pid)


def load(pid=None):
    try:
        d = json.load(open(path(pid), encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("v") == VERSION else None
    except Exception:
        return None


def _save(sheet, pid=None):
    sheet["updated"] = dt.datetime.now().isoformat(timespec="minutes")
    paths.write_atomic(path(pid), json.dumps(sheet, indent=1, ensure_ascii=False))
    return sheet


def _profile(pid):
    try:
        return json.load(open(people.pdir("profile.json", pid=pid), encoding="utf-8"))
    except Exception:
        return None


_END = re.compile(r"(present|current|now|today)|((?:19|20)\d\d)", re.I)


def recent_title(prof):
    """The most recent job in a profile's experience: the one still running ("present"), else the latest end year,
    else the first listed (resumes list the newest first)."""
    best, best_key = "", None
    for i, e in enumerate((prof or {}).get("experience") or []):
        t = clean_title(e.get("title"))
        if not t:
            continue
        ends = _END.findall(str(e.get("dates") or ""))
        year = 9999 if any(a for a, _ in ends) else max((int(y) for _, y in ends if y), default=0)
        key = (year, -i)
        if best_key is None or key > best_key:
            best, best_key = t, key
    return best


def _auto_recent(prof):
    """The most recent job title when the person hasn't typed one: from their experience, else what Claude read off
    the resume, else the first job title they search for."""
    p = prof or {}
    lf = p.get("look_for") if isinstance(p.get("look_for"), dict) else {}
    return recent_title(p) or clean_title(lf.get("recent_title")) or clean_title(next(iter(p.get("target_roles") or []), ""))


def _basis(recent, prof):
    """What the automatic part was built from. A new basis rebuilds it (the person's own chips are kept)."""
    p = prof or {}
    lf = p.get("look_for") if isinstance(p.get("look_for"), dict) else {}
    blob = json.dumps([recent.lower(), [clean_title(e.get("title")).lower() for e in p.get("experience") or []],
                       [clean_title(x).lower() for x in p.get("target_roles") or []],
                       [clean_title(x).lower() for x in p.get("title_keywords") or []],
                       [clean_title(x).lower() for x in p.get("skills") or []], lf, onet().get("version")], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _claude_basis(recent, prof):
    """What a Claude suggestion was made for: the titles only (so adding a skill never asks again)."""
    p = prof or {}
    blob = json.dumps([recent.lower(), [clean_title(e.get("title")).lower() for e in p.get("experience") or []]])
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _dedupe(items, key=lambda x: x["t"].lower()):
    seen, out = set(), []
    for x in items:
        k = key(x)
        if k and k not in seen:
            seen.add(k); out.append(x)
    return out


def _skill_ok(s):
    s = s.strip()
    return 2 <= len(s) <= 40 and len(s.split()) <= 4 and (len(s) >= 3 or bool(re.search(r"[+#0-9]", s)))


def build(pid=None, prof=None):
    """(Re)build the automatic part of the sheet from the person's data and the O*NET extract, keep their own chips and
    removals, and save it. No Claude call: Claude's ideas arrive inside the profile ("look_for", made by the resume
    reader in its one call) or from suggest(), and are simply read here."""
    pid = pid or people.current()
    prof = prof if prof is not None else _profile(pid)
    old = load(pid) or {}
    removed = old.get("removed") or {"titles": [], "occs": [], "skills": []}
    rm_t, rm_o, rm_s = (set(removed.get(k) or []) for k in ("titles", "occs", "skills"))
    p = prof or {}
    mine_recent = clean_title(old.get("recent")) if old.get("recent_by") == "you" else ""
    lf = p.get("look_for") if isinstance(p.get("look_for"), dict) else None
    if lf and not any(lf.get(k) for k in ("same_titles", "step_up_titles", "related_roles", "key_skills")):
        lf = None
    recent = mine_recent or _auto_recent(p)
    cl = lf or old.get("claude") or {}
    titles, occs, skills = [], [], []
    add = lambda t, tier, src: titles.append({"t": clean_title(t), "tier": tier, "src": src}) if clean_title(t) else None
    if recent:
        add(recent, "same", "you" if mine_recent else "profile")
    for t in cl.get("same_titles") or []:
        add(t, "same", "claude")
    # the occupation behind the most recent title: its other names count as the same job, its neighbours as related
    found = find_occupations(recent) if recent else []
    for code, _ in found[:2]:
        occs.append({"code": code, "tier": "same", "src": "onet"})
    rel = []
    for code, _ in found[:2]:
        for r in onet()["occ"].get(code, {}).get("r", []):
            if r not in rel and r not in [c for c, _ in found[:2]]:
                rel.append(r)
    for r in rel[:8]:
        occs.append({"code": r, "tier": "related", "src": "onet"})
    for t in p.get("target_roles") or []:
        add(t, "wanted", "profile")
    for t in cl.get("step_up_titles") or []:
        add(t, "up", "claude")
    for t in cl.get("related_roles") or []:
        add(t, "related", "claude")
    for e in p.get("experience") or []:
        add(e.get("title"), "past", "profile")
    for t in p.get("title_keywords") or []:
        if len(str(t).split()) >= 2:      # whole phrases only: single words ("security") are too loose to rank by
            add(t, "keyword", "profile")
    for s in p.get("skills") or []:
        skills.append({"t": clean_title(s), "src": "profile"})
    for s in cl.get("key_skills") or []:
        skills.append({"t": clean_title(s), "src": "claude"})
    for code, _ in found[:1]:
        o = onet()["occ"].get(code, {})
        skills += [{"t": s, "src": "onet"} for s in o.get("s", [])[:8]] + [{"t": s, "src": "onet", "w": 0.5} for s in o.get("k", [])[:8]]
    # the person's own chips come first and are never dropped; removed ones stay removed
    own_t = [x for x in old.get("titles") or [] if x.get("src") == "you" and not (x.get("tier") == "same" and mine_recent and x["t"].lower() == mine_recent.lower())]
    own_s = [x for x in old.get("skills") or [] if x.get("src") == "you"]
    own_o = [x for x in old.get("occs") or [] if x.get("src") == "you"]
    titles = _dedupe(own_t + [x for x in titles if x["t"].lower() not in rm_t])[:MAX_TITLES]
    skills = _dedupe(own_s + [x for x in skills if _skill_ok(x["t"]) and x["t"].lower() not in rm_s])[:MAX_SKILLS]
    occs = _dedupe(own_o + [x for x in occs if x["code"] not in rm_o], key=lambda x: x["code"])
    field = old.get("field") if old.get("field_by") == "you" else (clean_title(cl.get("field")) or (FIELDS.get(found[0][0][:2], "") if found else ""))
    sheet = {"v": VERSION, "recent": recent, "recent_by": "you" if mine_recent else "profile", "titles": titles, "occs": occs,
             "skills": skills, "field": field or "", "field_by": old.get("field_by") or "auto", "removed": removed,
             "basis": _basis(recent, p), "claude": old.get("claude") or {},
             # a Claude suggestion is only ever asked for titles it has not seen: a sheet first built for a profile that
             # already existed (an upgrade) starts as "seen", so upgrading never spends a call
             "claude_basis": old.get("claude_basis") or _claude_basis(recent, p)}
    if lf:
        sheet["claude_basis"] = _claude_basis(recent, p)
    return _save(sheet, pid)


def ensure(pid=None, prof=None):
    """The person's sheet, built or rebuilt when their data changed since it was made. Cheap when nothing changed."""
    pid = pid or people.current()
    prof = prof if prof is not None else _profile(pid)
    sheet = load(pid)
    recent = clean_title(sheet.get("recent")) if sheet and sheet.get("recent_by") == "you" else _auto_recent(prof)
    if sheet and sheet.get("basis") == _basis(recent, prof):
        return sheet
    try:
        return build(pid, prof)
    except Exception as e:
        print(f"what-to-look-for sheet not rebuilt for {pid}: {type(e).__name__}: {e}", flush=True)
        return sheet or {"v": VERSION, "recent": "", "titles": [], "occs": [], "skills": [], "field": "", "removed": {}}


def is_empty(sheet):
    return not (sheet and (sheet.get("titles") or sheet.get("occs")))


# ---------------------------------------------------------------- edits (profile page, /setup)
def edit(pid, op):
    """One change by the person. op: {"add": "title"|"up"|"related"|"skill", "text": ...}, {"remove": "title"|"skill"|"occ",
    "text" or "code": ...}, {"recent": "..."}, {"field": "..."}, {"reset": "learning"|"sheet"}. Returns the sheet.
    Removing a title also takes it out of the profile's "job titles to search for" / title words, so it stops passing
    the title filter too (those are not part of the rating key, so no rating is touched)."""
    sheet = ensure(pid)
    rm = sheet.setdefault("removed", {})
    for k in ("titles", "occs", "skills"):
        rm.setdefault(k, [])
    if op.get("reset") == "learning":
        reset_learning(pid)
        return sheet
    if op.get("reset") == "sheet":
        try:
            os.remove(path(pid))
        except OSError:
            pass
        return build(pid)
    if "recent" in op:
        t = clean_title(op["recent"])
        sheet["recent"], sheet["recent_by"] = t, ("you" if t else "profile")
        if t and t.lower() in rm["titles"]:
            rm["titles"].remove(t.lower())
        _save(sheet, pid)
        return build(pid)
    if "field" in op:
        sheet["field"], sheet["field_by"] = clean_title(op["field"]), "you"
        return _save(sheet, pid)
    text = clean_title(op.get("text"))
    kind = op.get("add")
    if kind in ("title", "up", "related") and text:
        tier = {"title": "same", "up": "up", "related": "related"}[kind]
        if text.lower() in rm["titles"]:
            rm["titles"].remove(text.lower())
        sheet["titles"] = [x for x in sheet["titles"] if x["t"].lower() != text.lower()]
        sheet["titles"].insert(0, {"t": text, "tier": tier, "src": "you"})
        return _save(sheet, pid)
    if kind == "skill" and text:
        if text.lower() in rm["skills"]:
            rm["skills"].remove(text.lower())
        sheet["skills"] = [{"t": text, "src": "you"}] + [x for x in sheet["skills"] if x["t"].lower() != text.lower()]
        return _save(sheet, pid)
    kind = op.get("remove")
    if kind == "title" and text:
        sheet["titles"] = [x for x in sheet["titles"] if x["t"].lower() != text.lower()]
        if text.lower() not in rm["titles"]:
            rm["titles"].append(text.lower())
        if sheet.get("recent", "").lower() == text.lower():
            sheet["recent"], sheet["recent_by"] = "", "you"
        _save(sheet, pid)
        _drop_from_profile(pid, text)
        return load(pid) or sheet
    if kind == "skill" and text:
        sheet["skills"] = [x for x in sheet["skills"] if x["t"].lower() != text.lower()]
        if text.lower() not in rm["skills"]:
            rm["skills"].append(text.lower())
        return _save(sheet, pid)
    if kind == "occ" and op.get("code"):
        code = str(op["code"])
        sheet["occs"] = [x for x in sheet["occs"] if x["code"] != code]
        if code not in rm["occs"]:
            rm["occs"].append(code)
        return _save(sheet, pid)
    raise ValueError("Nothing to change.")


def _drop_from_profile(pid, text):
    """A removed title also leaves the profile's own title lists (the title filter reads those)."""
    import resume
    prev = people.current()
    try:
        people.set_current(pid)
        prof = resume.load_active()
        if not prof:
            return
        low = text.lower()
        edits = {}
        for k in ("target_roles", "title_keywords"):
            cur = prof.get(k) or []
            new = [x for x in cur if clean_title(x).lower() != low]
            if len(new) != len(cur):
                edits[k] = new
        if edits:
            resume.edit_active(edits)
            sheet = load(pid)
            if sheet:      # same data minus the removed title: no need to rebuild
                sheet["basis"] = _basis(sheet.get("recent", ""), resume.load_active())
                _save(sheet, pid)
    finally:
        people.set_current(prev)


# ---------------------------------------------------------------- Claude: one small call, only when titles changed
LOOK_PROPS = {
    "recent_title": {"type": "string"},
    "same_titles": {"type": "array", "items": {"type": "string"}},
    "step_up_titles": {"type": "array", "items": {"type": "string"}},
    "related_roles": {"type": "array", "items": {"type": "string"}},
    "key_skills": {"type": "array", "items": {"type": "string"}},
    "field": {"type": "string"},
}
LOOK_SCHEMA = {"type": "object", "properties": LOOK_PROPS, "required": list(LOOK_PROPS), "additionalProperties": False}
LOOK_RULES = """"look_for" describes what jobs to search for, for someone in ANY line of work (trades, healthcare, office, retail, teaching, driving, tech ...). Weigh the most recent job held far more than older ones.
- "recent_title": the most recent job title held, as an employer would post it (plain words, no employer name, no level number).
- "same_titles": 4 to 10 other names employers use for that same job at the same level (e.g. "Registered Nurse": "RN", "Staff Nurse").
- "step_up_titles": 3 to 6 titles one step up from it that this person could realistically be hired into next.
- "related_roles": 5 to 10 different roles they could plausibly move into with the experience they have.
- "key_skills": 10 to 20 concrete skills, tools, licenses or methods from their experience, each written the way job postings write it (1 to 3 words).
- "field": their field or industry in 1 to 4 plain words."""
LOOK_SYSTEM = "You help a job search tool decide which job postings are relevant to one person. Use only what they tell you.\n\n" + LOOK_RULES
MODEL = "claude-haiku-5-5"


def needs_suggest(pid):
    sheet, prof = load(pid), _profile(pid)
    return bool(sheet and sheet.get("recent") and sheet.get("claude_basis") != _claude_basis(sheet["recent"], prof))


def suggest(pid, force=False):
    """Ask Claude (one small, cheap call) for other names, step-ups, related roles and skills for this person's titles,
    and fold the answer into the sheet. Skipped when Claude isn't connected, when there is no title yet, and when it was
    already asked for these same titles (unless force: the person pressed the button). Returns the sheet or None."""
    import claude_cli
    sheet = ensure(pid)
    if not sheet.get("recent") or not claude_cli.claude_ready() or not (force or needs_suggest(pid)):
        return None
    prof = _profile(pid) or {}
    lines = ["Most recent job title: " + sheet["recent"]]
    older = [f'{clean_title(e.get("title"))} ({clean_title(e.get("dates"))})' for e in (prof.get("experience") or [])[:8] if clean_title(e.get("title"))]
    if older:
        lines.append("Jobs held, newest first: " + "; ".join(older))
    if prof.get("skills"):
        lines.append("Skills they list: " + "; ".join(clean_title(s) for s in prof["skills"][:30]))
    if prof.get("summary"):
        lines.append("About them: " + str(prof["summary"])[:600])
    out = claude_cli.run_json(LOOK_SYSTEM, "\n".join(lines), LOOK_SCHEMA, model=MODEL, effort="low", timeout=180,
                              feature="What to look for")
    sheet = load(pid) or sheet
    sheet["claude"] = clean_look(out)
    sheet["claude_basis"] = _claude_basis(sheet["recent"], prof)
    sheet["basis"] = ""          # (rebuild with the new ideas)
    _save(sheet, pid)
    return build(pid)


def clean_look(d):
    """Claude's answer trimmed to what the sheet stores (also applied to resume.build_profile's "look_for")."""
    d = d if isinstance(d, dict) else {}
    lst = lambda k, n: [clean_title(x) for x in (d.get(k) or []) if clean_title(x)][:n] if isinstance(d.get(k), list) else []
    return {"recent_title": clean_title(d.get("recent_title")), "same_titles": lst("same_titles", 12),
            "step_up_titles": lst("step_up_titles", 8), "related_roles": lst("related_roles", 12),
            "key_skills": lst("key_skills", 24), "field": clean_title(d.get("field"))[:60]}


# ---------------------------------------------------------------- learning from saved / applied / hidden jobs
def _learn_path(pid=None):
    return people.pdir(LEARN_FILE, pid=pid)


def learned(pid=None):
    """{job id: {"d": "up"|"down", "t": title}}. First use: seeded from the marks the person already has."""
    try:
        d = json.load(open(_learn_path(pid), encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return _seed_learning(pid)
    except Exception:
        return {}


def _seed_learning(pid=None):
    out = {}
    try:
        marks = json.load(open(people.pdir("marks.json", pid=pid)))
        titles = {j["id"]: j["title"] for j in json.load(open(people.pdir("jobs.json", pid=pid), encoding="utf-8")).get("jobs", [])}
        for jid, st in marks.items():
            if jid in titles and st in ("saved", "applied", "hidden"):
                out[jid] = {"d": "down" if st == "hidden" else "up", "t": titles[jid]}
    except Exception:
        pass
    try:
        paths.write_atomic(_learn_path(pid), json.dumps(out, ensure_ascii=False))
    except Exception:
        pass
    return out


def note_mark(pid, jid, status, title):
    """A job was saved / applied to (similar titles go up a little), hidden (down a little) or un-marked (forgotten)."""
    d = learned(pid)
    if status in ("saved", "applied", "hidden") and title:
        d.pop(jid, None)
        d[jid] = {"d": "down" if status == "hidden" else "up", "t": clean_title(title)}
        while len(d) > LEARN_KEEP:
            d.pop(next(iter(d)))
    else:
        d.pop(jid, None)
    paths.write_atomic(_learn_path(pid), json.dumps(d, ensure_ascii=False))


def reset_learning(pid=None):
    """Forget what was learned from marks (the marks themselves stay)."""
    paths.write_atomic(_learn_path(pid), "{}")


# ---------------------------------------------------------------- the Relevance score
class Scorer:
    """Relevance for one person's sheet. title_score() is cached per distinct title, so 10,000+ jobs take a second or
    two. score(job) sets job["rel"] (0-100, or None when the sheet has no titles) and job["rel_why"] (plain words)."""

    def __init__(self, sheet, learn=None):
        self.sheet = sheet or {}
        self.empty = is_empty(self.sheet)
        self.entries, self.index, self._cache = [], {}, {}
        seen = set()
        def put(title, tier, label):
            seq = [t for t in tokens(title) if t not in LEVEL]
            toks = frozenset(seq)
            w = _tw(toks)
            if not toks or w <= 0 or (toks, tier) in seen:
                return
            seen.add((toks, tier))
            i = len(self.entries)
            self.entries.append((toks, w, TIERS[tier], tier, label, _head(seq)))
            for t in toks:
                self.index.setdefault(t, []).append(i)
        for x in self.sheet.get("titles") or []:
            put(x["t"], x.get("tier") if x.get("tier") in TIERS else "related", x["t"])
        for x in self.sheet.get("occs") or []:
            tier = "occ" if x.get("tier") == "same" else "related"
            for n in occ_names(x["code"]):
                put(n, tier, n)
        self.skills = []
        for x in self.sheet.get("skills") or []:
            s = x["t"].lower()
            self.skills.append((s, re.compile(r"(?<![a-z0-9])" + re.escape(s) + r"(?:e?s)?(?![a-z0-9+#])"), float(x.get("w") or (0.8 if x.get("src") == "onet" else 1.0))))
        self.field = [t for t in tokens(self.sheet.get("field") or "") if weight(t) > 12]
        self.up, self.down = [], []
        for v in (learn or {}).values():
            toks = frozenset(t for t in tokens(v.get("t", "")) if t not in LEVEL)
            if toks and _tw(toks) > 0:
                (self.down if v.get("d") == "down" else self.up).append((toks, _tw(toks)))

    @staticmethod
    def _sim(jt, jw, toks, w, head=None):
        """How alike a job title (words jt, weight jw) and a sheet entry are, 0-1. The whole entry inside the title
        ("Registered Nurse" in "Registered Nurse - ICU") is strong; sharing only some words is weak, and nearly
        nothing unless the shared words include the entry's main word ("School Nurse" vs "School Principal")."""
        shared = jt & toks
        if not shared:
            return 0.0
        sw = sum(weight(t) for t in shared)
        ecover, jcover = sw / w, sw / jw
        if ecover >= 0.999:
            if len(toks) == 1 and jcover < 0.999:
                # a one-word name inside a longer title: "Nurse" in "Nurse Practitioner" is a fair sign, "Manager" in
                # "Product Manager" says little
                return (0.45 + 0.55 * jcover) * min(1.0, (w / GENERIC_W) ** 2)
            return 0.85 + 0.15 * jcover
        s = 0.7 * ecover ** 1.5 * (0.6 + 0.4 * jcover)
        return s if head is None or head in shared else 0.25 * s

    def title_score(self, title):
        """(0-100, tier, the sheet entry that matched) for a job title."""
        hit = self._cache.get(title)
        if hit is not None:
            return hit
        jt = frozenset(t for t in tokens(title) if t not in LEVEL)
        jw = _tw(jt)
        best = (0.0, "", "")
        if jt and jw > 0:
            cand = set()
            for t in jt:
                cand.update(self.index.get(t, ()))
            for i in cand:
                toks, w, tw_, tier, label, head = self.entries[i]
                s = tw_ * self._sim(jt, jw, toks, w, head)
                if s > best[0]:
                    best = (s, tier, label)
        nudge = 0.0
        if jt and jw > 0 and (self.up or self.down):
            u = max((self._sim(jt, jw, toks, w) for toks, w in self.up), default=0.0)
            d = max((self._sim(jt, jw, toks, w) for toks, w in self.down), default=0.0)
            nudge = NUDGE_UP * (u if u >= 0.5 else 0) - NUDGE_DOWN * (d if d >= 0.5 else 0)
        out = self._cache[title] = (round(100 * best[0]), best[1], best[2], round(nudge))
        return out

    def skill_hits(self, text):
        low = (text or "")[:8000].lower()
        return [s for s, rx, w in self.skills if s in low and rx.search(low)], sum(w for s, rx, w in self.skills if s in low and rx.search(low))

    def score(self, job):
        if self.empty:
            job["rel"], job["rel_why"] = None, ""
            return None
        T, tier, label, nudge = self.title_score(job.get("title") or "")
        hits, hw = self.skill_hits(job.get("desc") or job.get("snippet") or "") if self.skills else ([], 0.0)
        S = min(100.0, 22.0 * hw)
        # the title decides; skills found in the text close up to 30% of what's left, and by themselves reach 35
        rel = max(T + (100 - T) * 0.3 * S / 100, 0.35 * S)
        if self.field and rel > 0:
            ctx = set(tokens((job.get("dept") or "") + " " + (job.get("sector") or "")))
            if any(t in ctx for t in self.field):
                rel += 3
        rel = max(0, min(100, round(rel + nudge)))
        why = []
        if T >= 25 and label:
            why.append(f"{'Matches' if T >= 80 * TIERS.get(tier, 1) else 'Close to'} “{label}” ({TIER_WORDS.get(tier, 'on your list')})")
        if hits:
            why.append("mentions " + ", ".join(hits[:4]))
        if nudge:
            why.append("similar to jobs you " + ("saved" if nudge > 0 else "hid"))
        job["rel"], job["rel_why"] = rel, "; ".join(why) if why else "Nothing on your list matches this title"
        return rel


def scorer(pid=None, prof=None):
    pid = pid or people.current()
    return Scorer(ensure(pid, prof), learned(pid))


# ---------------------------------------------------------------- feeding the title filter and the fetch
def title_phrases(sheet, own_only=False):
    """Whole-word title phrases for the title filter (jobfinder.title_ok). own_only: just the chips the person added
    (profiles on the earlier built-in word list keep exactly the filter they had, plus what they add themselves)."""
    out = []
    for x in (sheet or {}).get("titles") or []:
        if x.get("tier") == "past" or (own_only and x.get("src") != "you"):
            continue
        out.append(x["t"])
    if not own_only:
        for x in (sheet or {}).get("occs") or []:
            for n in occ_names(x["code"], common_only=x.get("tier") != "same"):
                toks = [t for t in tokens(n) if t not in LEVEL]
                if len(toks) > 1 or _tw(toks) >= GENERIC_W:   # not the one-word catch-alls ("Manager", "Technician")
                    out.append(n)
    seen, res = set(), []
    for t in out:
        k = " ".join(t.lower().split())
        if k and k not in seen:
            seen.add(k); res.append(t.lower())
    return res


def phrase_regex(phrases):
    """One whole-word pattern for many title phrases (a trailing plural still counts), or None."""
    parts = []
    for p in sorted(set(phrases), key=len, reverse=True):
        ws = re.findall(r"[a-z0-9+#.]+", p.lower().replace("&", " "))
        if ws:
            parts.append(r"[\s/,&-]+(?:(?:and|of|the)\s+)?".join(re.escape(w) for w in ws))
    if not parts:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?:e?s)?(?![a-z0-9+#])")


# ---------------------------------------------------------------- plain-language view for the pages
SRC_WORDS = {"you": "added by you", "profile": "from your profile", "claude": "suggested by Claude", "onet": "from the occupation list"}


def view(pid=None):
    """What the profile page and /setup show."""
    pid = pid or people.current()
    sheet = ensure(pid)
    by = lambda *tiers: [{"t": x["t"], "src": x.get("src", "")} for x in sheet.get("titles") or [] if x.get("tier") in tiers]
    occs = []
    for x in sheet.get("occs") or []:
        o = onet()["occ"].get(x["code"])
        if o:
            occs.append({"code": x["code"], "t": o["t"], "tier": x.get("tier"), "names": len(o["a"]), "examples": o["a"][:6]})
    lr = learned(pid)
    ups = list(dict.fromkeys(v["t"] for v in lr.values() if v.get("d") == "up"))
    downs = list(dict.fromkeys(v["t"] for v in lr.values() if v.get("d") == "down"))
    import claude_cli
    try:
        ready = bool(claude_cli.claude_ready())
    except Exception:
        ready = False
    return {"recent": sheet.get("recent") or "", "same": by("same", "wanted"), "up": by("up"), "related": by("related", "keyword"),
            "past": by("past"), "occs_same": [o for o in occs if o["tier"] == "same"],
            "occs_related": [o for o in occs if o["tier"] != "same"],
            "skills": [{"t": x["t"], "src": x.get("src", "")} for x in sheet.get("skills") or []],
            "field": sheet.get("field") or "", "empty": is_empty(sheet),
            "learned": {"up": ups[-12:], "down": downs[-12:], "n_up": len(ups), "n_down": len(downs)},
            "claude_ready": ready, "can_suggest": ready and bool(sheet.get("recent")),
            "onet": bool(onet()["occ"]), "src_words": SRC_WORDS}
