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

# How high a job can score through each kind of entry on the sheet (0-100). The person's own titles come first: their
# most recent title (and titles they added themselves), then titles they search for, Claude's other names for that same
# job, the job they held before. Names from the occupation list (O*NET) always sit below those; related roles and loose
# title phrases below that. Older jobs fade (PAST_CAPS: the job before this one, the one before that, ...).
CAPS = {"same": 100, "wanted": 90, "same_claude": 86, "alt": 78, "up": 72, "related": 60, "keyword": 55, "occ": 50,
        "relocc": 42}
PAST_CAPS = (82, 66, 58, 52)
TIER_WORDS = {"same": "your job title", "wanted": "a title you search for", "same_claude": "another name for your job",
              "alt": "another name for your job", "up": "one step up", "related": "a related role",
              "past": "a job you held before", "keyword": "a title phrase from your profile",
              "occ": "the same kind of work", "relocc": "a related occupation"}
NUDGE_UP, NUDGE_DOWN, LEARN_KEEP = 8, 10, 300
MAX_TITLES, MAX_SKILLS = 60, 60
# Skills found in the posting text. A title match is worth its full cap only when the posting also mentions the person's
# skills: with none it gets (100 - SKILL_PART)% of it, so two postings with the same title are told apart by their
# text and the caps stay true ceilings. With no title match at all, skills alone reach at most SKILL_ALONE.
# Only the person's own skills count (see build).
SKILL_PART, SKILL_ALONE = 12, 25
# A title that is not on the sheet but shares telling words with the person's titles ("Program Manager, Field" for
# someone looking for "Technical Program Manager") gets a little credit, at most this much: far below any real match.
SHARED_MAX = 25

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
         "experienced", "trainee", "1", "2", "3", "4", "5", "6", "new", "grad", "graduate"}
# words employers add to a title that say nothing about the job
NOISE = {"remote", "hybrid", "prn", "temporary", "temp", "urgent", "hiring", "now"}
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


GENERIC_W = 10.0   # a one-word name lighter than this (used by 40+ occupations: "Manager", "Technician") says little by itself
HEAD_MIN = 40      # a word that ends this many names in the occupation list is a job word ("Manager", "Practitioner")

# Short forms that mean exactly the same job, always (the occupation list adds more, see _lex). Kept tiny on purpose.
ABBR = {"rn": "registered nurse", "lpn": "licensed practical nurse", "lvn": "licensed vocational nurse",
        "np": "nurse practitioner", "cna": "certified nursing assistant", "emt": "emergency medical technician",
        "cpa": "certified public accountant"}
_LEX = {}


def _lex():
    """Built once from the extract (~0.5 s): heads = words that end many job names (a title that goes on with one of
    them after the person's own title is a different job: "Nurse Practitioner", "Electrician Helper"); abbr = {long
    form as a word tuple: short form} for short forms that are reliable, meaning the occupation list gives the short
    form exactly one long form (RN = Registered Nurse; "RA" has seven, so it is left alone); index = {name as an
    ordered word phrase: [(0 the occupation's title / 1 a commonly reported name / 2 another name, code)]}."""
    if not _LEX:
        occs = onet()["occ"]              # (loaded before taking the lock: onet() takes it too)
        with _OLOCK:
            if not _LEX:
                heads, pairs, names = {}, {}, []
                for code, o in occs.items():
                    all_names = [o["t"]] + o["a"]
                    shorts = [a for a in all_names if re.fullmatch(r"[A-Z]{3,5}", a)]
                    for k, t in enumerate(all_names):
                        seq = [x for x in tokens(t) if x not in LEVEL]
                        if not seq:
                            continue
                        heads[seq[-1]] = heads.get(seq[-1], 0) + 1
                        names.append((seq, 0 if k == 0 else 1 if k <= o["n"] else 2, code))
                        ws = [w for w in re.findall(r"[A-Za-z]+", t) if w.lower() not in _SMALL]
                        for a in shorts:
                            if len(ws) == len(a) and "".join(w[0].upper() for w in ws) == a:
                                pairs.setdefault(a.lower(), set()).add(tuple(tokens(t)))
                abbr = {tuple(tokens(long)): short for short, long in ABBR.items()}
                for short, longs in pairs.items():
                    if len(longs) == 1 and short not in ABBR and heads.get(short, 0) < HEAD_MIN:
                        abbr.setdefault(next(iter(longs)), short)
                first = {}
                for long in abbr:
                    first.setdefault(long[0], []).append(long)
                for v in first.values():
                    v.sort(key=len, reverse=True)
                lex = {"heads": {w for w, n in heads.items() if n >= HEAD_MIN}, "head_n": heads, "abbr": abbr, "abbr_first": first}
                index = {}
                for seq, rank, code in names:
                    index.setdefault(" ".join(canon(seq, lex)), []).append((rank, code))
                lex["index"] = index
                _LEX.update(lex)
    return _LEX


def canon(seq, lex=None):
    """A word list with long forms folded to their short form: [registered, nurse, icu] -> [rn, icu]."""
    lex = lex or _lex()
    first, abbr = lex["abbr_first"], lex["abbr"]
    if not any(t in first for t in seq):
        return list(seq)
    out, i = [], 0
    while i < len(seq):
        for long in first.get(seq[i], ()):
            if tuple(seq[i:i + len(long)]) == long:
                out.append(abbr[long]); i += len(long)
                break
        else:
            out.append(seq[i]); i += 1
    return out


def phrase(title):
    """A title as the ordered words that are compared: level and filler words dropped, long forms folded."""
    return tuple(canon([t for t in tokens(title) if t not in LEVEL and t not in NOISE]))


_PAREN = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")
_CODE = re.compile(r"(?:\b(?:req(?:uisition)?|job|id|ref|jr|r)\s*[#:-]?\s*\d{3,}\b)|#\s*\d+|\b[a-z]{0,4}-?\d{4,}\b", re.I)
_SEPS = re.compile(r"\s+[-–—|:@•]+\s*|[-–—|:]+\s+|\s*[–—|•]\s*|--+")


def title_parts(title):
    """A posted title taken apart: (core phrases, side phrases). Employers add the site, unit, shift and requisition
    number after the title ("Phlebotomist- Westerville Family Physicians", "Staff RN – PICU", "Program Manager (R5448)");
    the core is what comes before that, and it is what gets compared with the sheet. "Manager, Sales Operations" is
    also read as "Sales Operations Manager"; "Analyst/Consultant" as either. The side phrases (the parts after a dash
    or in brackets: "New Grad Nurse – RN") only count when one of them IS a title on the sheet."""
    t = " ".join(str(title or "").replace("’", "'").split())
    side = []
    def paren(m):
        side.append(m.group(1) or m.group(2) or "")
        return " "
    t = _CODE.sub(" ", _PAREN.sub(paren, t))
    segs = [s.strip(" ,;/") for s in _SEPS.split(t) if s and s.strip(" ,;/")]
    if not segs:
        return [], [p for p in (phrase(s) for s in side) if p]
    main, side = segs[0], segs[1:] + side
    cores = []
    parts = [p.strip() for p in main.split(",") if p.strip()]
    if len(parts) > 1:
        left, right = parts[0], parts[1]
        lp = phrase(left)
        cores.append(left)
        if 0 < len(lp) <= 3:
            cores.append(right + " " + left)      # "Manager, Sales Operations" -> "Sales Operations Manager"
        side = [right] + parts[2:] + side
    else:
        cores.append(main)
    out = []
    for c in cores:
        if "/" in c:
            bits = [b.strip() for b in c.split("/") if b.strip()]
            if len(bits) > 1 and all(len(phrase(b)) >= 2 for b in bits):
                out += bits[:3]                    # "Project Manager / Scrum Master": two titles
                continue
            m = re.search(r"(\S+)\s*/\s*(\S+)", c)  # "Analyst/Consultant": either word
            if m:
                out += [c[:m.start()] + m.group(1) + c[m.end():], c[:m.start()] + m.group(2) + c[m.end():]]
                continue
        out.append(c)
    seen, res = set(), []
    for c in out:
        p = tuple(x for x in phrase(c) if not (len(x) >= 3 and x.isdigit()))
        if p and p not in seen:
            seen.add(p); res.append(p)
    return res, [p for p in (phrase(s) for s in side) if p]


CATCH_ALL = {"11-1021.00", "11-1011.00"}   # General and Operations Managers, Chief Executives: far too broad to widen by


def _catch_all(code):
    return code in CATCH_ALL or "All Other" in (onet()["occ"].get(code) or {}).get("t", "")


def find_occupations(title, limit=2):
    """O*NET occupations for a typed job title, best first: [(code, how sure 0-1)]. Conservative on purpose: only an
    occupation that lists the typed title as one of its names (1.0), or lists the main part of it ("Journeyman
    Electrician" has "Electrician": 0.8). Never by loosely shared words, never a catch-all ("General and Operations
    Managers", "... All Other") unless that is what was typed, and nothing at all when the name fits too many
    occupations to choose from ("Teacher" alone names 20 kinds). [] when unsure: the sheet then simply uses the
    person's own titles."""
    seq = phrase(title)
    if not seq:
        return []
    idx = _lex()["index"]
    key = " ".join(seq)
    hits, sure = idx.get(key), 1.0
    if not hits:
        subs = []
        for n in range(len(seq) - 1, 0, -1):
            for i in range(len(seq) - n, -1, -1):          # the end of the title first (its main word), then the rest
                subs.append(seq[i:i + n])
        for sub in subs:
            if len(sub) == 1 and (weight(sub[0]) < GENERIC_W or sub[0] in LEVEL):
                continue
            hits = idx.get(" ".join(sub))
            if hits:
                sure = 0.8
                break
    if not hits:
        return []
    return _choose(hits, seq, sure)[:limit]


def _choose(hits, seq, sure):
    """Which of the occupations that list a title to use. A plain title sits under many ("Project Manager", "Shift
    Supervisor", "Teacher"): then none is chosen, because any pick would be a guess."""
    occ, typed = onet()["occ"], set(seq)
    def own(code):      # how much of the typed title is in the occupation's own title
        return _tw(typed & set(phrase(occ[code]["t"])))
    rank = {}
    for r, code in hits:
        rank[code] = min(r, rank.get(code, 9))
    # 1. occupations named after the title itself ("Truck Driver": Heavy and Tractor-Trailer Truck Drivers, Light Truck Drivers)
    exact = [c for c, r in rank.items() if r == 0]
    if exact:
        return [(c, sure) for c in sorted(exact)]
    full = [c for c, r in rank.items() if r <= 1 and typed <= set(phrase(occ[c]["t"])) and not _catch_all(c)]
    if full:
        return [(c, sure) for c in sorted(full, key=lambda c: (rank[c], c))] if len(full) <= 3 else []
    # 2. otherwise only a title that one or two occupations list at all
    if len(rank) > 2:
        return []
    codes = [c for c in rank if not _catch_all(c)]
    top = max((own(c) for c in codes), default=0)
    return [(c, sure) for c in sorted(codes, key=lambda c: (rank[c], c)) if own(c) == top]


def field_of(title):
    """The field for a typed title: the major group of its occupation, or the one group every occupation that lists
    the title (or its main words) belongs to, even when there are too many to pick one ("Teacher", "4th Grade
    Teacher" -> Education). "" when they disagree."""
    found = find_occupations(title)
    if found:
        return FIELDS.get(found[0][0][:2], "")
    seq, idx = phrase(title), _lex()["index"]
    for n in range(len(seq), 0, -1):
        for i in range(len(seq) - n, -1, -1):
            hits = idx.get(" ".join(seq[i:i + n]))
            if hits:
                groups = {code[:2] for _, code in hits if not _catch_all(code)}
                return FIELDS.get(groups.pop(), "") if len(groups) == 1 else ""
    return ""


def related_occupations(code, limit=5):
    """The occupation list's neighbours of an occupation, kept only when they are plainly the same line of work: the
    same major group or a telling word in common ("Truck" drivers and "Truck" mechanics). Catch-alls are left out."""
    o = onet()["occ"].get(code) or {}
    heads = _lex()["heads"]
    mine = {t for t in phrase(o.get("t", "")) if weight(t) >= GENERIC_W and t not in heads and t not in ("first", "line")}
    fls = o.get("t", "").startswith("First-Line Supervisors")     # (their neighbours are supervisors of every other trade)
    out = []
    for r in o.get("r", []):
        ro = onet()["occ"].get(r)
        if not ro or _catch_all(r) or r == code:
            continue
        if (r[:2] == code[:2] and not fls) or mine & set(phrase(ro["t"])):
            out.append(r)
    return out[:limit]


_SUP = ("supervisor", "manager", "foreman", "charge", "head", "chief")
_LADDER = (("supervisor", "manager"), ("manager", "director"), ("director", "vice president"), ("coordinator", "manager"))
_UNDER = ("assistant", "associate", "deputy", "vice")


def step_up(title, limit=4):
    """Titles one step up from a job title, with no Claude: names in the occupation list that are the same title plus
    a supervising word ("Registered Nurse" -> "Charge Nurse", "Nurse Manager"; "Electrician" -> "Electrician
    Supervisor"), else the next rung of a short ladder ("Assistant Store Manager" -> "Store Manager"; supervisor ->
    manager -> director). Few and plain; the person can remove them."""
    seq = phrase(title)
    if not seq:
        return []
    words = clean_title(title).split()
    low = [stem(w.lower().strip(",")) for w in words]
    if len(words) > 1 and low[0] in _UNDER and low[1] not in ("president",):
        return [" ".join(words[1:])]
    mine = set(seq) | {t for t in tokens(title) if t not in LEVEL}     # (both "rn" and "registered nurse")
    if mine & set(_SUP) or any(a in mine for a, _ in _LADDER):
        for a, b in _LADDER:
            hit = [i for i, w in enumerate(low) if w == a]
            if hit:
                i = hit[-1]
                return [" ".join(words[:i] + [b.title() + ("," if words[i].endswith(",") else "")] + words[i + 1:])]
        return []
    tells = {t for t in mine if weight(t) >= GENERIC_W}
    out, seen = [], set()
    for key, lst in _lex()["index"].items():
        ks = key.split()
        if not 2 <= len(ks) <= len(seq) + 1 or not tells & set(ks):
            continue
        sup = [k for k in ks if k in _SUP]
        if len(sup) == 1 and set(ks) - set(sup) <= mine and key not in seen:
            seen.add(key)
            out.append((min(r for r, _ in lst), len(ks), key))
    shorts = set(_lex()["abbr"].values()) | {"hvac", "cdl", "it", "hr"}
    return [" ".join(w.upper() if w in shorts else w.capitalize() for w in k.split()) for _, _, k in sorted(out)][:limit]


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


def _typed_title(p):
    """The "Current job title" typed on the fill-in-myself form (a profile made without Claude). The form's save
    (resume.build_manual_profile) puts it first in the job titles to search for; when that first title is simply one
    of the roles in the work history, nothing else was typed."""
    if not p.get("_manual"):
        return ""
    t = clean_title(next(iter(p.get("target_roles") or []), ""))
    return "" if t.lower() in {clean_title(e.get("title")).lower() for e in p.get("experience") or []} else t


def _auto_recent(prof):
    """The most recent job title when the person hasn't typed one on the sheet: the "Current job title" of a profile they
    filled in themselves ("Registered Nurse", not the role line "Staff RN, Medical-Surgical" under it), else from their
    experience, else what Claude read off the resume, else the first job title they search for."""
    p = prof or {}
    lf = p.get("look_for") if isinstance(p.get("look_for"), dict) else {}
    return (_typed_title(p) or recent_title(p) or clean_title(lf.get("recent_title"))
            or clean_title(next(iter(p.get("target_roles") or []), "")))


BUILD = 2   # the way the automatic part is made. A new number rebuilds every sheet once (own chips and removals kept, no Claude).


def _facts(pid):
    try:
        d = json.load(open(people.pdir("facts.json", pid=pid), encoding="utf-8"))
        return [f for f in d if isinstance(f, dict)] if isinstance(d, list) else []
    except Exception:
        return []


def _licenses(pid):
    """License / certification names the person confirmed (highlights.json), if any."""
    try:
        import highlights
        h = highlights.get(pid) or {}
        return [clean_title(x.get("name")) for x in h.get("licenses") or [] if isinstance(x, dict) and x.get("name")]
    except Exception:
        return []


def _basis(recent, prof, pid=None):
    """What the automatic part was built from. A new basis rebuilds it (the person's own chips are kept)."""
    p = prof or {}
    lf = p.get("look_for") if isinstance(p.get("look_for"), dict) else {}
    low = lambda xs: [clean_title(x).lower() for x in xs or []]
    blob = json.dumps([BUILD, recent.lower(), low(e.get("title") for e in p.get("experience") or []), low(p.get("target_roles")),
                       low(p.get("title_keywords")), low(p.get("skills")), low(p.get("certifications")), low(p.get("fit_keywords")),
                       [low(r.get("target_titles")) for r in p.get("reframings") or [] if isinstance(r, dict)],
                       [(f.get("requirement"), f.get("level")) for f in _facts(pid)] if pid else [], lf, onet().get("version")],
                      sort_keys=True)
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


def _skill_forms(s):
    """A skill as postings write it: the whole phrase, what is in brackets and each side of a slash
    ("Low-code workflow implementation (Mendix)" -> also "Mendix"; "Agile/Scrum" -> "Agile", "Scrum")."""
    s = clean_title(s)
    out = [s]
    for m in re.findall(r"\(([^()]{2,30})\)", s):
        out.append(m.strip())
    bare = re.sub(r"\s*\([^()]*\)", "", s).strip()
    if bare and bare != s:
        out.append(bare)
    if "/" in bare and len(bare) <= 40:
        out += [b.strip() for b in bare.split("/") if b.strip()]
    return [x for x in out if x]


_NOT_SPECIALTY = re.compile(r"^(?:(?:part|full)[- ]time|per diem|prn|nights?|days?|evenings?|weekends?|remote|hybrid|"
                            r"on-?site|contract(?:or)?|temp(?:orary)?|seasonal|interim|\d.*)$", re.I)


def _title_core(t):
    """("Staff RN", "Medical-Surgical") for "Staff RN, Medical-Surgical": the job title, and the specialty or unit a
    resume writes after a comma (a skill at most, never part of the title). A title whose first part is only a rank or
    a catch-all job word keeps its comma: "Manager, Sales Operations" and "Director, Nursing" are whole titles, read as
    "Sales Operations Manager" (title_parts)."""
    t = clean_title(t)
    left, sep, right = t.partition(",")
    left, right = left.strip(), right.strip()
    if not sep or not left or not right or len(right.split()) > 4 or _generic_word(left):
        return t, ""
    try:
        import jobtext
        if (jobtext.title_level(left) or 0) >= 4:
            return t, ""
    except Exception:
        pass
    return left, ("" if _NOT_SPECIALTY.match(right) else right)


def _items(s, home=""):
    """One skill line as separate items ("RN license; BLS; ACLS" is three), without the ones that are just a place."""
    try:
        import highlights
        return highlights.split_items(s, home)
    except Exception:
        return [str(s)]


def _generic_word(t):
    """One plain word that names hundreds of different jobs ("Engineer", "Manager", "Project"): too loose to rank by."""
    p = phrase(t)
    return len(p) <= 1 and (not p or weight(p[0]) < GENERIC_W or _lex()["head_n"].get(p[0], 0) >= 100)


def _merge_look(first, second):
    """Two sets of Claude's ideas as one: every list is the union, `first` (the newer one) in front; single values
    come from `first` when it has them."""
    first, second = clean_look(first), clean_look(second)
    out = {}
    for k, v in first.items():
        if isinstance(v, list):
            seen, out[k] = set(), []
            for x in v + second[k]:
                if x.lower() not in seen:
                    seen.add(x.lower()); out[k].append(x)
        else:
            out[k] = v or second[k]
    return out


def build(pid=None, prof=None):
    """(Re)build the automatic part of the sheet from the person's data and the O*NET extract, keep their own chips and
    removals, and save it. No Claude call: Claude's ideas arrive inside the profile ("look_for", made by the resume
    reader in its one call) and from suggest() ("Ask Claude for more ideas"); both are kept and merged here, the newer
    one first.

    Titles, in the order they count (see CAPS): the most recent title; the titles the person searches for; Claude's
    other names for the same job; one step up (Claude's, else step_up()); related roles (Claude's and the ones the
    resume reader's reframings open); the jobs held before, newest first; whole title phrases from the profile. One-word
    catch-alls ("Engineer", "Manager") carried over from older title-word lists are left out. Occupations: only the
    one(s) that list the most recent title by name (find_occupations), and their plainly related neighbours.
    A title from the profile with a specialty after a comma ("Staff RN, Medical-Surgical") goes on as the title alone;
    the specialty of a job they held becomes a skill (_title_core).
    Skills: only what the person has: their profile's skills and certifications, licenses they confirmed, answers they
    gave (yes / some), Claude's reading of their resume, and the match words the resume reader noted. The occupation
    list's typical tools and task words are NOT added: they describe the occupation, not the person (they put "mentions
    python" on a thousand jobs for people who never used it, and words like "family" or "status" matched everything)."""
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
    asked = old.get("claude") if isinstance(old.get("claude"), dict) and any(old["claude"].values()) else None
    recent = mine_recent or _auto_recent(p)
    # Claude's ideas: the resume reader's (in the profile) and the answer to "Ask Claude for more ideas" (kept on the
    # sheet). Both count; whichever was made later goes first.
    asked_newer = bool(asked) and str(old.get("claude_at") or "") >= str(p.get("_created") or p.get("_approved") or "")
    cl = _merge_look(asked, lf) if asked_newer else _merge_look(lf, asked)
    titles, occs, skills, specialties = [], [], [], []
    def add(t, tier, src):
        t = clean_title(t)
        if src == "profile" and tier in ("wanted", "past", "keyword"):
            # "Staff RN, Medical-Surgical" is the title "Staff RN"; the specialty of a job held counts as a skill
            t, spec = _title_core(t)
            if spec and tier == "past":
                specialties.append(spec)
        if tier == "keyword" and phrase(t) in {phrase(x["t"]) for x in titles}:
            return                # a title already on the sheet under another spelling ("rn" for Registered Nurse)
        if t and not (tier in ("wanted", "related", "keyword", "up") and _generic_word(t)):
            titles.append({"t": t, "tier": tier, "src": src})
    if recent:
        add(recent, "same", "you" if mine_recent else "profile")
    for t in cl["same_titles"]:
        add(t, "same", "claude")
    # the occupation that lists the most recent title by name: its other names widen the search, its neighbours are related
    found = [c for c, _ in find_occupations(recent)] if recent else []
    for code in found:
        occs.append({"code": code, "tier": "same", "src": "onet"})
    for code in found[:1]:
        for r in related_occupations(code):
            if r not in found:
                occs.append({"code": r, "tier": "related", "src": "onet"})
    for t in p.get("target_roles") or []:
        add(t, "wanted", "profile")
    for t in cl["step_up_titles"]:
        add(t, "up", "claude")
    if recent and not cl["step_up_titles"]:
        for t in step_up(recent):
            add(t, "up", "onet")
    for t in cl["related_roles"]:
        add(t, "related", "claude")
    for r in p.get("reframings") or []:           # roles the resume reader said this experience opens
        for t in (r.get("target_titles") or [])[:4] if isinstance(r, dict) else []:
            add(t, "related", "profile")
    for e in p.get("experience") or []:
        add(e.get("title"), "past", "profile")
    heads = _lex()["heads"]
    for t in p.get("title_keywords") or []:
        ph = phrase(t)
        # whole phrases, or one telling word ("mendix", "salesforce"); never a loose single word ("security", "manager")
        if len(ph) >= 2 or (len(ph) == 1 and len(ph[0]) >= 3 and ph[0] not in heads and weight(ph[0]) >= 2 * GENERIC_W):
            add(t, "keyword", "profile")
    home = str(p.get("location") or "")
    def skill(s, src, w=None):
        for item in _items(s, home):      # typed with commas or semicolons: one chip each; "Ohio" alone is no skill
            for form in _skill_forms(item):
                skills.append({"t": form, "src": src, **({"w": w} if w else {})})
    for s in (p.get("skills") or []) + (p.get("certifications") or []) + _licenses(pid) + specialties:
        skill(s, "profile")
    for f in _facts(pid):
        if f.get("level") in ("yes", "some") and f.get("requirement"):
            skill(f["requirement"], "answers")
    for s in cl["key_skills"]:
        skill(s, "claude")
    for s in p.get("fit_keywords") or []:
        skill(s, "profile", 0.6)
    # the person's own chips come first and are never dropped; removed ones stay removed
    own_t = [x for x in old.get("titles") or [] if x.get("src") == "you" and not (x.get("tier") == "same" and mine_recent and x["t"].lower() == mine_recent.lower())]
    own_s = [x for x in old.get("skills") or [] if x.get("src") == "you"]
    own_o = [x for x in old.get("occs") or [] if x.get("src") == "you"]
    titles = _dedupe(own_t + [x for x in titles if x["t"].lower() not in rm_t])[:MAX_TITLES]
    skills = _dedupe(own_s + [x for x in skills if _skill_ok(x["t"]) and x["t"].lower() not in rm_s])[:MAX_SKILLS]
    occs = _dedupe(own_o + [x for x in occs if x["code"] not in rm_o], key=lambda x: x["code"])
    field = old.get("field") if old.get("field_by") == "you" else (cl["field"] or (field_of(recent) if recent else ""))
    sheet = {"v": VERSION, "recent": recent, "recent_by": "you" if mine_recent else "profile", "titles": titles, "occs": occs,
             "skills": skills, "field": field or "", "field_by": old.get("field_by") or "auto", "removed": removed,
             "basis": _basis(recent, p, pid), "claude": asked or {}, "claude_at": old.get("claude_at") or "",
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
    if sheet and sheet.get("basis") == _basis(recent, prof, pid):
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
                sheet["basis"] = _basis(sheet.get("recent", ""), resume.load_active(), pid)
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
    have = [x["t"] for x in sheet.get("titles") or [] if x.get("tier") != "past"][:40]
    if have:      # (so a second ask brings new ideas instead of the same list)
        lines.append("Already on their list (suggest titles that are NOT here): " + "; ".join(have))
    gone = (sheet.get("removed") or {}).get("titles") or []
    if gone:
        lines.append("They removed these, do not suggest them again: " + "; ".join(gone[:40]))
    out = claude_cli.run_json(LOOK_SYSTEM, "\n".join(lines), LOOK_SCHEMA, model=MODEL, effort="low", timeout=180,
                              feature="What to look for")
    sheet = load(pid) or sheet
    # kept next to the resume reader's ideas (build merges the two, the newer first); an earlier answer is kept too
    sheet["claude"] = _merge_look(out, sheet.get("claude"))
    sheet["claude_at"] = dt.datetime.now().isoformat(timespec="seconds")
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
OWN_TIERS = ("same", "wanted", "same_claude", "past", "up")


class Scorer:
    """Relevance for one person's sheet: plain code, explainable, no Claude.

    The title decides. A posted title is first cut down to its core (title_parts: the site, unit and requisition number
    after a dash, comma or bracket are not the job), then compared with every entry on the sheet as an ORDERED phrase,
    never as a bag of words ("Nurse Practitioner - ICU" is not an "ICU Nurse"):
      the same phrase                                    100% of the entry's cap (CAPS: own titles 100 ... related 42)
      the entry at the end, words before it              93%  ("Pediatric Registered Nurse", "Staff RN")
      the entry, then a specialty                        88%  ("Registered Nurse ICU")
      the entry, then another job word                   50%  ("Nurse Practitioner" for "Nurse": a different job)
      the entry's words in order with one or two between 72%  ("Business Process Improvement Manager")
      a shorter title that is the end of the entry       50-80% ("Elementary Teacher" for "Elementary School Teacher")
    A title that fits no entry but shares telling words with the person's titles gets a little (at most SHARED_MAX).
    The best entry wins (the longer one on a tie), so the reason shown is always one line. A title the person removed
    takes its own matches away with it. Skills the person really has, found in the posting text, add a little
    (SKILL_PART / SKILL_ALONE); common ones that most postings mention count less (fit()). Saved / hidden jobs nudge by
    the words of their titles that are NOT the person's own job titles, so hiding one "Registered Nurse" posting in
    the wrong state never pushes Registered Nurse jobs down.

    title_score() is cached per distinct title, so 10,000+ jobs take a second or two. score(job) sets job["rel"]
    (0-100, or None when the sheet has no titles) and job["rel_why"] (plain words)."""

    def __init__(self, sheet, learn=None):
        self.sheet = sheet or {}
        self.empty = is_empty(self.sheet)
        self.heads = _lex()["heads"]
        self.entries, self.index, self._cache = [], {}, {}
        removed = self.sheet.get("removed") or {}
        gone = {phrase(t) for t in removed.get("titles") or []}
        blocked = set(gone)              # names the occupation list may not bring back
        for code in removed.get("occs") or []:
            gone.add(phrase(occ_title(code)))
            blocked.update(phrase(n) for n in occ_names(code))
        seen = {}

        def put(title, tier, cap, loose=False):
            p = phrase(title)
            w = _tw(p)
            if not p or w <= 0:
                return
            if tier in ("alt", "occ", "relocc") and (p in blocked or any(self._inside(g, p) for g in gone)):
                return                   # the person removed this (or the title inside it): the occupation list can't bring it back
            k = seen.get(p)
            if k is not None:
                if self.entries[k][2] < cap:
                    self.entries[k] = (p, w, cap, tier, clean_title(title), loose)
                return
            seen[p] = len(self.entries)
            self.entries.append((p, w, cap, tier, clean_title(title), loose))

        recent = phrase(self.sheet.get("recent") or "")
        past_n = 0
        for x in self.sheet.get("titles") or []:
            tier = x.get("tier")
            if tier == "same":
                tier = "same" if x.get("src") != "claude" else "same_claude"
            elif tier == "past":
                p = phrase(x["t"])
                if p == recent or p in seen and self.entries[seen[p]][3] == "past":
                    continue
                put(x["t"], "past", PAST_CAPS[min(past_n, len(PAST_CAPS) - 1)])
                past_n += 1
                continue
            elif tier not in CAPS:
                tier = "related"
            put(x["t"], tier, CAPS[tier], loose=tier == "keyword")
        own = set(recent) | {t for t in tokens(self.sheet.get("recent") or "") if t not in LEVEL}
        longs = {short: long for long, short in _lex()["abbr"].items()}
        for t in recent:                 # "RN" also has the words of "Registered Nurse"
            own.update(longs.get(t, ()))
        own_w = _tw(recent)
        for x in self.sheet.get("occs") or []:
            same = x.get("tier") == "same"
            for n in occ_names(x["code"]):
                p = phrase(n)
                if same:
                    # a name that shares the telling words of the person's own title is another name for their job
                    # ("Staff Nurse" for an RN); the occupation's other names are only the same kind of work
                    # ("Accounting Manager" is in the same occupation as "Office Manager", and is not the same job)
                    close = own_w > 0 and _tw(set(p) & own) >= 0.5 * own_w
                    put(n, "alt" if close else "occ", CAPS["alt" if close else "occ"])
                else:
                    put(n, "relocc", CAPS["relocc"])
        for i, e in enumerate(self.entries):
            for t in set(e[0]):
                self.index.setdefault(t, []).append(i)
        have = {e[0] for e in self.entries if e[3] in OWN_TIERS}
        self.gone = [g for g in gone if g and g not in have]
        self.own_toks = set()
        for e in self.entries:
            if e[3] in OWN_TIERS:
                self.own_toks.update(e[0])
        self.own_toks |= own
        self.word_w = {}                 # word -> the best cap (0-1) of a title on the sheet that has it
        for e in self.entries:
            if e[3] not in ("alt", "occ", "relocc"):
                for t in e[0]:
                    self.word_w[t] = max(self.word_w.get(t, 0.0), e[2] / 100)
        self.skills = []
        for x in self.sheet.get("skills") or []:
            s = x["t"].lower()
            self.skills.append([s, re.compile(r"(?<![a-z0-9])" + re.escape(s) + r"(?:e?s)?(?![a-z0-9+#])"), float(x.get("w") or 1.0)])
        self.has_skills = bool(self.skills)
        self.field = [t for t in tokens(self.sheet.get("field") or "") if weight(t) > 12]
        self.up, self.down = [], []
        for v in (learn or {}).values():
            toks = self._other_words(v.get("t", ""))
            w = _tw(toks)
            if toks and w >= GENERIC_W:
                (self.down if v.get("d") == "down" else self.up).append((toks, w))

    def _other_words(self, title):
        """The words of a posted title that are not the person's own job titles (the unit, place, specialty ...)."""
        return frozenset(t for t in canon([t for t in tokens(title) if t not in LEVEL and t not in NOISE])
                         if t not in self.own_toks and not t.isdigit())

    def fit(self, jobs):
        """Weigh each skill by how telling it is on THIS board: one that a third of the postings mention ("team
        leadership") counts for nothing, one that few mention ("Epic", "conduit") counts in full. Optional; without it
        every skill counts the same."""
        if not self.skills or not jobs:
            return self
        texts = [(j.get("desc") or j.get("snippet") or "")[:8000].lower() for j in jobs]
        n = len(texts)
        for sk in self.skills:
            df = sum(1 for t in texts if sk[0] in t) / n
            rare = 1.0 if df <= 0.03 else 0.0 if df >= 0.35 else math.log(0.35 / df) / math.log(0.35 / 0.03)
            sk[2] = round(sk[2] * rare, 3)
        return self

    def _factor(self, C, e):
        """How well the core of a posted title (word tuple C) fits one entry: 0-1 (see the class note)."""
        E, w, _, _, _, loose = e
        n, m = len(C), len(E)
        if C == E:
            return 1.0
        if m < n:
            for i in range(n - m + 1):
                if C[i:i + m] == E:
                    if loose:
                        return 1.0
                    after = C[i + m:]
                    if any(t in self.heads for t in after):
                        f = 0.5
                    elif after:
                        f = 0.88 - 0.04 * i - 0.02 * (len(after) - 1)
                    else:
                        f = 0.93 - 0.04 * (i - 1)
                    if m == 1:          # a one-word name inside a longer title: "Manager" says little, "Phlebotomist" a lot
                        f *= min(1.0, (w / GENERIC_W) ** 2)
                    return max(0.4, f) if m > 1 else f
            if m >= 2 and not loose:
                pos, k = [], 0
                for i, t in enumerate(C):
                    if k < m and t == E[k]:
                        pos.append(i); k += 1
                if k == m and not any(t in self.heads for t in C[pos[-1] + 1:]):
                    gaps = pos[-1] - pos[0] + 1 - m
                    if 1 <= gaps <= 2:
                        return 0.72 - 0.06 * (gaps - 1)
        elif n < m and C[-1] == E[-1] and not loose:
            k = 0
            for t in E:
                if k < n and t == C[k]:
                    k += 1
            if k == n:
                f = 0.5 + 0.3 * _tw(C) / w
                return f * (min(1.0, (weight(C[0]) / GENERIC_W) ** 2) if n == 1 else 1.0)
        return 0.0

    def _shared(self, C):
        """(points, the shared words) for a core title that fits no entry: the share of its telling words that are
        words of the person's own titles."""
        den = _tw(C)
        if den <= 0:
            return 0.0, []
        got = sorted(((weight(t) * self.word_w[t], t) for t in set(C) if t in self.word_w), reverse=True)
        return SHARED_MAX * sum(x for x, _ in got) / den, [t for x, t in got if x > 0][:2]

    @staticmethod
    def _inside(E, N):
        """Is phrase E a run of words inside phrase N (or N itself)?"""
        m = len(E)
        return any(N[i:i + m] == E for i in range(len(N) - m + 1))

    def title_score(self, title):
        """(0-100, tier, the sheet entry that matched, nudge, how close 0-1, that entry's cap) for a job title."""
        hit = self._cache.get(title)
        if hit is not None:
            return hit
        cores, side = title_parts(title)
        best = (0.0, 0, "", "", 0.0, SHARED_MAX + SKILL_ALONE)          # score, entry length, tier, label, factor, cap
        for C in cores:
            cand = set()
            for t in C:
                cand.update(self.index.get(t, ()))
            gone = [g for g in self.gone if self._inside(g, C)]
            for i in cand:
                e = self.entries[i]
                if gone and any(self._inside(e[0], g) for g in gone):
                    continue             # the person removed this title: it takes its matches with it
                f = self._factor(C, e)
                if f > 0:
                    key = (e[2] * f, len(e[0]))
                    if key > best[:2]:
                        best = (key[0], key[1], e[3], e[4], f, e[2])
            if not gone:
                pts, words = self._shared(C)
                if pts > best[0]:
                    best = (pts, 0, "shared", ", ".join(words), 0.0, SHARED_MAX + SKILL_ALONE)
        for S in side:                   # "New Grad Nurse – RN", "Registered Nurse (RN)": only a whole title counts
            for i in self.index.get(S[-1], ()):
                e = self.entries[i]
                if e[0] == S and not e[5] and (e[2] * 0.92, len(S)) > best[:2]:
                    best = (e[2] * 0.92, len(S), e[3], e[4], 0.92, e[2])
        nudge = 0.0
        if self.up or self.down:
            jt = self._other_words(title)
            if jt:
                u = max((_tw(jt & toks) / w for toks, w in self.up), default=0.0)
                d = max((_tw(jt & toks) / w for toks, w in self.down), default=0.0)
                nudge = NUDGE_UP * (u if u >= 0.6 else 0) - NUDGE_DOWN * (d if d >= 0.6 else 0)
        out = self._cache[title] = (round(best[0]), best[2], best[3], round(nudge), best[4], best[5])
        return out

    def skill_hits(self, text):
        low = (text or "")[:8000].lower()
        hits = [(s, w) for s, rx, w in self.skills if s in low and rx.search(low)]
        hits.sort(key=lambda x: -x[1])
        return [s for s, w in hits if w > 0], sum(w for _, w in hits)

    def score(self, job):
        if self.empty:
            job["rel"], job["rel_why"] = None, ""
            return None
        T, tier, label, nudge, f, cap = self.title_score(job.get("title") or "")
        hits, hw = self.skill_hits(job.get("desc") or job.get("snippet") or "") if self.skills else ([], 0.0)
        S = 1 - math.exp(-hw / 1.5)
        if not self.has_skills:          # no skills on the sheet: nothing to tell postings apart by, the title counts in full
            S = 1.0 if T else 0.0
        # the title decides: its points count in full when the posting text also mentions the person's skills, a little
        # less (SKILL_PART) when it mentions none; skills with no title match reach SKILL_ALONE
        # (never above the cap of the entry that matched: skills cannot lift "another name" over the person's own title)
        rel = min(cap, T * (1 - SKILL_PART / 100 * (1 - S)) + (1 - T / 100) * SKILL_ALONE * (S if self.has_skills else 0))
        if self.field and rel > 0:
            ctx = set(tokens((job.get("dept") or "") + " " + (job.get("sector") or "")))
            if any(t in ctx for t in self.field):
                rel += 3
        rel = max(0, min(100, round(rel + nudge)))
        why = []
        if T >= 12 and tier == "shared":
            why.append(f"Shares words with titles on your list ({label})")
        elif T >= 12 and label:
            why.append(f"{'Matches' if f >= 0.85 else 'Close to'} “{label}” ({TIER_WORDS.get(tier, 'on your list')})")
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
    removed = (sheet or {}).get("removed") or {}
    gone = {phrase(t) for t in removed.get("titles") or []} | {phrase(n) for c in removed.get("occs") or [] for n in occ_names(c)}
    for x in (sheet or {}).get("titles") or []:
        if x.get("tier") == "past" or (own_only and x.get("src") != "you"):
            continue
        out.append(x["t"])
    if not own_only:
        for x in (sheet or {}).get("occs") or []:
            for n in occ_names(x["code"], common_only=x.get("tier") != "same"):
                toks = [t for t in tokens(n) if t not in LEVEL]
                # not the one-word catch-alls ("Manager", "Technician"), and nothing the person removed
                if (len(toks) > 1 or _tw(toks) >= GENERIC_W) and phrase(n) not in gone:
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
SRC_WORDS = {"you": "added by you", "profile": "from your profile", "claude": "suggested by Claude", "onet": "from the occupation list",
             "answers": "from your answers"}


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
