"""Natural-language job search.

Claude turns a plain-English description ("remote product roles at climate nonprofits") into match criteria:
role phrases for titles, topic phrases for postings, and exact company / sector names taken from this board.
The server then ranks every job on the board against those criteria, using the full posting text.

Each part the query names must match (role AND domain); within a part any phrase can match.
"""
import re, threading
import claude_cli

MODEL = "claude-haiku-5-5"   # fast; this runs while the person waits
_cache, _lock = {}, threading.Lock()

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "role_terms": {"type": "array", "items": {"type": "string"}},
        "topic_terms": {"type": "array", "items": {"type": "string"}},
        "companies": {"type": "array", "items": {"type": "string"}},
        "sectors": {"type": "array", "items": {"type": "string"}},
        "exclude_terms": {"type": "array", "items": {"type": "string"}},
        "workplace": {"type": "string", "enum": ["any", "remote", "dmv"]},
        "min_salary": {"type": "integer"},
    },
    "required": ["summary", "role_terms", "topic_terms", "companies", "sectors", "exclude_terms", "workplace", "min_salary"],
    "additionalProperties": False,
}

SYSTEM = """You turn a job seeker's plain-English search into match criteria for a job board.
Return:
- summary: a short restatement of what they want (under 12 words), e.g. "Product roles in climate tech, remote".
- role_terms: phrases that would appear in matching JOB TITLES, lowercase, with common variants and synonyms
  (e.g. "product manager", "product owner", "product lead", "pm"). Empty if they didn't describe a role or function.
- topic_terms: phrases for the industry, domain, mission or skills they described, as they'd appear in posting text,
  lowercase, with synonyms (e.g. climate -> "climate", "carbon", "renewable", "clean energy", "sustainability").
  Empty if they only described a role. Do not repeat role words here.
- companies: names copied EXACTLY from the company list that clearly fit (companies they named, or that fit a kind of
  company they named, like "AI labs" or "big banks"). Empty if they didn't name or describe companies.
- sectors: names copied EXACTLY from the sector list that fit the industry they described. Empty if none fit.
- exclude_terms: title phrases they said to avoid ("not sales" -> "sales"). Usually empty.
- workplace: "remote" if they asked for remote, "dmv" if they asked for an office in DC / Maryland / Virginia, else "any".
- min_salary: lowest annual pay they asked for in dollars (e.g. "over 200k" -> 200000), else 0.
Keep each term list under 15 short phrases. Prefer phrases specific enough not to match unrelated jobs."""


def interpret(q, companies, sectors):
    key = q.strip().lower()
    with _lock:
        if key in _cache:
            return _cache[key]
    prompt = (f"Search: {q.strip()}\n\nCompanies on this board:\n" + "; ".join(sorted(companies)) +
              "\n\nSectors on this board:\n" + "; ".join(sorted(sectors)))
    out = claude_cli.run_json(SYSTEM, prompt, SCHEMA, model=MODEL, effort="low", timeout=120)
    cs, ss = {c.lower(): c for c in companies}, {s.lower(): s for s in sectors}
    crit = {
        "summary": (out.get("summary") or q).strip()[:120],
        "role_terms": _terms(out.get("role_terms")),
        "topic_terms": _terms(out.get("topic_terms")),
        "companies": [cs[c.lower()] for c in out.get("companies") or [] if c.lower() in cs],
        "sectors": [ss[s.lower()] for s in out.get("sectors") or [] if s.lower() in ss],
        "exclude_terms": _terms(out.get("exclude_terms")),
        "workplace": out.get("workplace") if out.get("workplace") in ("remote", "dmv") else "any",
        "min_salary": max(0, int(out.get("min_salary") or 0)),
    }
    with _lock:
        _cache[key] = crit
    return crit


def _terms(xs):
    seen, out = set(), []
    for x in xs or []:
        x = re.sub(r"\s+", " ", str(x).strip().lower())[:60]
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out[:20]


def _pattern(terms):
    """One case-insensitive regex for a list of phrases, matched on word boundaries."""
    if not terms:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?![a-z0-9])", re.I)


def rank(jobs, descs, crit):
    """Ordered [(job id, relevance)] for jobs matching the criteria, best first."""
    role, topic, excl = _pattern(crit["role_terms"]), _pattern(crit["topic_terms"]), _pattern(crit["exclude_terms"])
    cos, secs = set(crit["companies"]), set(crit["sectors"])
    want_role = bool(role)
    want_domain = bool(topic or cos or secs)
    out = []
    for j in jobs:
        title = j.get("title") or ""
        if excl and excl.search(title):
            continue
        if crit["workplace"] == "remote" and j.get("workplace") != "remote":
            continue
        if crit["workplace"] == "dmv" and not j.get("dmv_locations"):
            continue
        if crit["min_salary"] and j.get("salary_max") is not None and j["salary_max"] < crit["min_salary"]:
            continue
        score = 0.0
        if want_role:
            if role.search(title):
                score += 10
            elif role.search(j.get("dept") or ""):
                score += 3
            else:
                continue
        if want_domain:
            d = 0.0
            if j.get("company") in cos:
                d += 8
            if j.get("sector") in secs:
                d += 5
            if topic:
                if topic.search(title):
                    d += 6
                text = descs.get(j["id"]) or j.get("snippet") or ""
                hits = len(topic.findall(text[:20000]))
                if hits:
                    d += min(hits, 8) * 0.75
            if d == 0:
                continue
            score += d
        if not want_role and not want_domain:
            score = 1  # only workplace / pay asked for
        if j.get("salary_max") is None and crit["min_salary"]:
            score -= 1  # pay unknown: keep, but below jobs that show it
        out.append((j["id"], round(score, 2)))
    out.sort(key=lambda x: -x[1])
    return out
