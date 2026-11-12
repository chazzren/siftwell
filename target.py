"""Per-profile career targets.

A target is the person's own words ("office manager at a school or hospital", "a move from retail into human resources").
Claude turns it into a title filter and a tab name (interpret), or, for someone who isn't sure, proposes
targets from their resume and what the local market actually pays for (suggest)."""
import collections, json, os, re, statistics

import claude_cli, people, resume

import paths
MARKET = paths.data("market.json")

LEVEL_WORDS = r"\b(senior|sr|staff|principal|lead|junior|associate|director|head of|vp|vice president|chief|manager|i{1,3}|iv|v|[1-6])\b"

# ------------------------------------------------------------------ market snapshot
def write_market(jobs):
    """Compact snapshot of the shared job pool (title, company, pay, workplace) for target suggestions."""
    rows = [{"t": j["title"], "c": j["company"], "a": j.get("ai_track", ""), "m": j.get("salary_mid"),
             "w": j.get("workplace", ""), "l": j.get("level")} for j in jobs]
    json.dump(rows, open(MARKET, "w"))

def _family(title):
    t = re.sub(r"\(.*?\)|,.*$| - .*$|–.*$", "", title.lower())
    t = re.sub(LEVEL_WORDS, " ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z/&+ ]", " ", t)).strip()

def market_summary(limit=160):
    try:
        rows = json.load(open(MARKET))
    except Exception:
        rows = []
    fam = collections.defaultdict(list)
    for r in rows:
        f = _family(r["t"])
        if f:
            fam[f].append(r)
    out = []
    marked = any(r.get("a") for r in rows)  # only a catalog from an earlier version has companies marked as AI companies
    for f, rs in sorted(fam.items(), key=lambda kv: -len(kv[1]))[:limit]:
        mids = [r["m"] for r in rs if r.get("m")]
        out.append(f"{f} | {len(rs)} openings | median midpoint {'$%dk' % (statistics.median(mids) / 1000) if mids else 'n/a'}"
                   f" | {round(100 * sum(r['w'] == 'remote' for r in rs) / len(rs))}% remote"
                   + (f" | {sum(1 for r in rs if r['a'])} at AI companies" if marked else ""))
    return "\n".join(out)

def _ai_marked():
    try:
        return any(r.get("a") for r in json.load(open(MARKET)))
    except Exception:
        return False

# ------------------------------------------------------------------ interpret a target
ISCHEMA = {
    "type": "object",
    "properties": {
        "tab_name": {"type": "string"},
        "any_title": {"type": "boolean"},
        "title_keywords": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["tab_name", "any_title", "title_keywords", "summary"],
    "additionalProperties": False,
}

ISYSTEM = """You configure a job search tool from a person's career target, written in their own words.
Return:
- tab_name: 1 to 3 words naming the target, for a tab label (e.g. "School office", "Project management", "Health care").
- any_title: true when the target is open to any kind of role (e.g. "any job at a hospital", "whatever pays most"); then the title filter is skipped.
- title_keywords: 15 to 40 lowercase words or short phrases that appear in job titles fitting the target (used as a substring filter on titles, so prefer stems like "office manag", "coordinat", "technician"). Include adjacent titles this person could realistically aim for given their background. Empty list if any_title is true.
- summary: one sentence restating the target as the tool will use it."""

def interpret(target_text, scope):
    prof = resume.load_active()
    background = resume.profile_text(prof)[:6000] if prof else "(no resume yet)"
    out = claude_cli.run_json(ISYSTEM, f"TARGET (their words): {target_text}\nCompanies in scope: "
                              f"{'AI companies only' if scope == 'ai' else 'all companies the tool tracks'}\n\nBACKGROUND\n{background}",
                              ISCHEMA, effort="low", timeout=300)
    kws = sorted({k.lower().strip() for k in out.get("title_keywords", []) if 2 <= len(k.strip()) <= 40})
    return {"target_name": (out.get("tab_name") or "Target")[:24], "target_any_title": bool(out.get("any_title")),
            "target_keywords": kws, "target_summary": out.get("summary", "")[:300]}

# ------------------------------------------------------------------ suggest targets
SSCHEMA = {
    "type": "object",
    "properties": {"options": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "target_text": {"type": "string"},
        "scope": {"type": "string", "enum": ["ai", "all"]},
        "why": {"type": "string"},
        "pay": {"type": "string"},
        "odds_now": {"type": "string", "enum": ["strong", "possible", "needs prep"]},
        "prep": {"type": "string"}},
        "required": ["name", "target_text", "scope", "why", "pay", "odds_now", "prep"], "additionalProperties": False}}},
    "required": ["options"],
    "additionalProperties": False,
}

SSYSTEM = """You are a candid career strategist. The person isn't sure what to aim for. Using their resume profile, the answers they've given, their goals and constraints, and a snapshot of what the job market near them ({area}) actually has open and pays, propose 4 to 6 distinct career targets worth pursuing.

Mix: at least one they're strong for today, at least one higher-ceiling direction that needs some preparation, and anything unusual their background makes easier than it looks. Ground pay and demand in the market snapshot; don't invent numbers. Respect their constraints (pay floor, location, things they want to avoid).
For each: name (2 to 5 words); target_text (one or two sentences in the first person, ready to paste as their target); scope ("ai" only if the target is specifically about AI companies, else "all"); why (one or two sentences, specific to them); pay (typical range from the snapshot); odds_now; prep (what it would take, briefly; "none" if ready)."""

def suggest_system(st):
    return SSYSTEM.replace("{area}", __import__("geo").area_phrase(st))

def suggest():
    prof = resume.load_active()
    if not prof:
        raise ValueError("Upload and approve a resume first, so suggestions can be based on it.")
    st = people.settings()
    floor = f"${st['salary_floor']:,} base" if st.get("salary_floor") else "none given"
    marked = _ai_marked()
    msg = (f"PROFILE\n{resume.profile_text(prof, st.get('goals', ''))[:9000]}\n\nPay floor: {floor}\n\n"
           f"MARKET SNAPSHOT (title family | openings | median pay midpoint | % remote{' | how many at AI companies' if marked else ''})\n{market_summary()}")
    opts = claude_cli.run_json(suggest_system(st), msg, SSCHEMA, effort="medium", timeout=600).get("options", [])
    if not marked:  # no employer here is marked as an AI company, so a target can't be limited to them
        for o in opts:
            if isinstance(o, dict):
                o["scope"] = "all"
    return opts
