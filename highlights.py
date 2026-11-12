"""Structured resume "highlights": degrees, licenses/certs, clearance, years, management, languages, industries,
top skills. Extracted once from the active profile (and its resume text) by Claude, confirmed and edited by the
user, and used by requirements.check() to hide jobs whose hard requirements the person clearly doesn't meet.

Storage: data/people/<pid>/highlights.json
    {"extracted": {...}, "edits": {...}, "confirmed": "2026-11-09T10:00" | null,
     "extracted_at": "...", "source_hash": "..."}
The working view (get(pid)) is `extracted` with each edited top-level field replaced by the user's version, so a
re-extraction never overwrites what the user corrected."""
import datetime as dt, hashlib, json, os, re

import people

LEVELS = ["associate", "bachelor", "master", "doctorate", "jd", "md"]
# Numeric rank for "a higher degree satisfies a lower one". JD/MD are professional doctorates: they satisfy
# bachelor's and "advanced degree" requirements; against a Master's/PhD requirement they only earn a flag.
LEVEL_RANK = {"associate": 1, "bachelor": 2, "master": 3, "jd": 3.5, "md": 3.5, "doctorate": 4}
LEVEL_LABEL = {"associate": "Associate's", "bachelor": "Bachelor's", "master": "Master's", "doctorate": "PhD",
               "jd": "JD", "md": "MD"}

# ------------------------------------------------------------------ field taxonomy
FIELD_GROUPS = ["engineering-mechanical", "engineering-electrical", "engineering-civil", "engineering-other",
                "computer-science", "math-stats", "physical-sciences", "life-sciences", "nursing", "medicine", "law",
                "accounting", "finance", "economics", "business", "social-sciences", "communications-english",
                "education", "arts-design", "hospitality", "other"]
GROUP_LABEL = {"engineering-mechanical": "Mechanical/Aerospace Eng.", "engineering-electrical": "Electrical/Computer Eng.",
               "engineering-civil": "Civil Eng.", "engineering-other": "Engineering", "computer-science": "Computer Science",
               "math-stats": "Math/Statistics", "physical-sciences": "Physical Sciences", "life-sciences": "Life Sciences",
               "nursing": "Nursing", "medicine": "Medicine", "law": "Law", "accounting": "Accounting", "finance": "Finance",
               "economics": "Economics", "business": "Business", "social-sciences": "Social Sciences",
               "communications-english": "Communications/English", "education": "Education", "arts-design": "Arts/Design",
               "hospitality": "Hospitality", "other": "Other"}
ENG = {"engineering-mechanical", "engineering-electrical", "engineering-civil", "engineering-other"}

# Ordered: first match wins, so specific phrases come before generic words.
FIELD_PATTERNS = [
    (r"mechanical|aerospace|aeronautic|astronautic|mechatronic", "engineering-mechanical"),
    (r"electrical|electronics?\b|computer engineering|electrical and computer|\bece\b|\beecs\b", "engineering-electrical"),
    (r"civil|structural engineering|environmental engineering|construction engineering|geotechnical|transportation engineering", "engineering-civil"),
    (r"computer science|software engineering|\bcs\b|(?-i:\bIT\b)|computing|informatics|information (?:systems|technology|science)|\bmis\b|"
     r"cyber ?security|computer information|data science|machine learning|artificial intelligence|bioinformatics|"
     r"human[- ]computer interaction|\bhci\b", "computer-science"),
    (r"(?:systems|industrial|chemical|biomedical|materials|nuclear|optical|petroleum|manufacturing|ocean|marine|"
     r"agricultural|naval|general) engineering|engineering|naval architecture", "engineering-other"),
    (r"statistic|mathemat|\bmath\b|operations research|actuar|analytics|quantitative|biostatistic|econometric", "math-stats"),
    (r"physics|chemistry|geolog|earth science|astronom|materials science|atmospheric|meteorolog|oceanograph|physical science", "physical-sciences"),
    (r"nursing|\bb\.?s\.?n\b|\bm\.?s\.?n\b|\bd\.?n\.?p\b|\ba\.?[ds]\.?n\b", "nursing"),
    (r"medicine|medical degree|\bm\.?d\.?\b|pharmac|osteopath|clinical", "medicine"),
    (r"biolog|biochem|life science|neuroscience|genetic|microbio|molecular|ecology|environmental science|public health|"
     r"epidemiolog|kinesiolog|nutrition|health science|biotech", "life-sciences"),
    (r"\blaw\b|legal|juris|paralegal", "law"),
    (r"accounting|accountancy", "accounting"),
    (r"finance|financial", "finance"),
    (r"economics|economic\b", "economics"),
    (r"hospitality|hotel|tourism|culinary|event management|restaurant", "hospitality"),
    (r"business|management|administration|\bmba\b|marketing|commerce|supply chain|logistics|human resources|"
     r"entrepreneur|organizational leadership|project management|procurement|real estate", "business"),
    (r"journalism|communication|english|writing|literature|linguistic|rhetoric|public relations|media studies", "communications-english"),
    (r"education|teaching|pedagog|curriculum", "education"),
    (r"design|fine arts?\b|\bart\b|arts\b|music|film|architecture|photograph|theat", "arts-design"),
    (r"politic|government|international (?:relations|affairs|studies)|public (?:policy|administration|affairs)|"
     r"sociolog|psycholog|anthropolog|social work|social science|history|geograph|urban planning|criminal justice|"
     r"security studies|development studies|philosoph|humanities|liberal arts|policy", "social-sciences"),
]
_FIELD_RES = [(re.compile(p, re.I), g) for p, g in FIELD_PATTERNS]

def field_group(text):
    """Best field group for a degree field ('Hospitality Management' -> hospitality). '' text -> 'other'."""
    t = text or ""
    for rx, g in _FIELD_RES:
        if rx.search(t):
            return g
    return "other"

def field_groups_in(text):
    """Every field group named in a phrase (for postings that list several fields)."""
    out, t = [], text or ""
    for rx, g in _FIELD_RES:
        if rx.search(t) and g not in out:
            out.append(g)
    return out

# Groups that count as "related" when a posting says "<fields> or a related field".
RELATED = {
    "engineering-mechanical": ENG | {"physical-sciences"},
    "engineering-electrical": ENG | {"computer-science", "physical-sciences"},
    "engineering-civil": ENG,
    "engineering-other": ENG | {"physical-sciences", "computer-science"},
    "computer-science": {"engineering-electrical", "engineering-other", "math-stats"},
    "math-stats": {"computer-science", "physical-sciences", "economics", "finance"} | ENG,
    "physical-sciences": ENG | {"math-stats", "life-sciences"},
    "life-sciences": {"physical-sciences", "nursing", "medicine"},
    "nursing": {"medicine", "life-sciences"},
    "medicine": {"nursing", "life-sciences"},
    "law": {"social-sciences"},
    "accounting": {"finance", "business", "economics"},
    "finance": {"accounting", "economics", "business", "math-stats"},
    "economics": {"finance", "math-stats", "business", "social-sciences", "accounting"},
    "business": {"finance", "accounting", "economics", "hospitality"},
    "social-sciences": {"economics", "communications-english", "law", "education"},
    "communications-english": {"social-sciences", "arts-design", "education"},
    "education": {"social-sciences", "communications-english"},
    "arts-design": {"communications-english"},
    "hospitality": {"business"},
    "other": set(),
}

# Generic posting phrases -> groups that clearly count ("yes") and groups that might ("maybe" -> flag, never hide).
STEM_CORE = ENG | {"computer-science", "math-stats", "physical-sciences", "life-sciences"}
ALL = set(FIELD_GROUPS)
COUNTS_TOWARD = {
    "stem": {"yes": STEM_CORE, "maybe": {"economics", "nursing", "medicine"}},
    "quantitative": {"yes": ENG | {"computer-science", "math-stats", "physical-sciences", "economics", "finance"},
                     "maybe": {"accounting", "life-sciences", "business"}},
    "technical": {"yes": ENG | {"computer-science", "math-stats", "physical-sciences"},
                  "maybe": {"life-sciences", "economics", "finance"}},
    "engineering_related": {"yes": ENG | {"computer-science", "physical-sciences"}, "maybe": {"math-stats"}},
    "science": {"yes": {"computer-science", "math-stats", "physical-sciences", "life-sciences", "nursing", "medicine"} | ENG,
                "maybe": {"social-sciences", "economics"}},
    "business_related": {"yes": {"business", "finance", "accounting", "economics", "hospitality"},
                         "maybe": {"communications-english", "social-sciences", "math-stats", "law"}},
    "health": {"yes": {"nursing", "medicine", "life-sciences"}, "maybe": {"business", "social-sciences"}},
    "any": {"yes": ALL, "maybe": set()},
}
GENERIC_LABEL = {"stem": "STEM", "quantitative": "quantitative field", "technical": "technical field",
                 "engineering_related": "Engineering", "science": "Science", "business_related": "Business",
                 "health": "health field", "any": "any field"}

# ------------------------------------------------------------------ schema + extraction
STR = {"type": "string"}
LIST = {"type": "array", "items": STR}
SCHEMA = {
    "type": "object",
    "properties": {
        "degrees": {"type": "array", "items": {"type": "object", "properties": {
            "level": {"type": "string", "enum": LEVELS},
            "field": STR,
            "field_group": {"type": "string", "enum": FIELD_GROUPS},
            "school": STR,
            "year": {"type": ["integer", "null"]},
            "completed": {"type": "boolean"}},
            "required": ["level", "field", "field_group", "school", "year", "completed"], "additionalProperties": False}},
        "licenses": {"type": "array", "items": {"type": "object", "properties": {
            "name": STR, "kind": {"type": "string", "enum": ["license", "cert"]},
            "active": {"type": ["boolean", "null"]}},
            "required": ["name", "kind", "active"], "additionalProperties": False}},
        "clearance": {"type": "object", "properties": {
            "level": {"type": "string", "enum": ["none", "public trust", "secret", "top secret", "ts/sci", "ts/sci + poly"]},
            "active": {"type": ["boolean", "null"]}, "note": STR},
            "required": ["level", "active", "note"], "additionalProperties": False},
        "years_experience": {"type": ["integer", "null"]},
        "management": {"type": "object", "properties": {
            "manages_people": {"type": "boolean"}, "direct_reports": {"type": ["integer", "null"]}, "note": STR},
            "required": ["manages_people", "direct_reports", "note"], "additionalProperties": False},
        "languages": {"type": "array", "items": {"type": "object", "properties": {
            "language": STR, "level": {"type": "string", "enum": ["native", "fluent", "professional", "conversational", "basic", ""]}},
            "required": ["language", "level"], "additionalProperties": False}},
        "industries": LIST,
        "top_skills": LIST,
    },
    "required": ["degrees", "licenses", "clearance", "years_experience", "management", "languages", "industries", "top_skills"],
    "additionalProperties": False,
}

SYSTEM = """You extract verifiable facts from a resume into structured "highlights" for a job-matching tool.
These facts decide which jobs are hidden from the candidate, so accuracy matters more than completeness.

Rules:
- Use only what the resume states. Never infer, upgrade or guess a credential. A course, bootcamp or "coursework in X" is not a degree. A degree in progress has completed=false.
- degrees: one entry per degree. level is one of associate, bachelor, master, doctorate (PhD/EdD/DSc etc.), jd, md (MD/DO). MBA, MS, MA, MPA, MPH, MEng are master. field is the major as written (e.g. "Computer Science"); field_group is the closest bucket; use "other" if none fits. year is the graduation year or null.
- licenses: professional licenses (RN, PE, CPA, bar admission with jurisdiction e.g. "Admitted to the Maryland bar", medical license, CDL, FINRA Series 7, teaching license) have kind "license"; certifications (PMP, CISSP, Security+, AWS, Salesforce, Scrum Master, SHRM, etc.) have kind "cert". active is true if stated current, false if stated expired/lapsed, else null.
- clearance: the highest clearance the resume says is currently held (active=true); if only past clearances are listed, give the highest past one with active=false. "none" if none is mentioned. note: short verbatim-ish detail.
- years_experience: total years of professional experience (count military service), or null if unclear.
- management: manages_people true only if the resume says they supervised/managed/led people (direct reports, a team they managed, a division they commanded). direct_reports: the number if stated (largest), else null. note: the supporting phrase.
- languages: spoken languages with level as stated (English included only if listed).
- industries: 2-6 short industry labels from their employers (e.g. "defense", "hospitality", "SaaS").
- top_skills: 8-15 concrete skills or tools the resume demonstrates, most prominent first.
Never include phone numbers, email addresses or street addresses."""

def _profile_prompt(prof):
    lines = []
    for k in ("education", "certifications", "clearances", "languages", "skills"):
        if prof.get(k):
            lines.append(f"{k}: " + "; ".join(prof[k]))
    if prof.get("years_experience") is not None:
        lines.append(f"years_experience (from profile): {prof['years_experience']}")
    for e in prof.get("experience", [])[:12]:
        lines.append(f"- {e.get('title')}, {e.get('employer')} ({e.get('dates')})")
    body = "Structured profile already extracted from this resume:\n" + "\n".join(lines)
    if prof.get("_resume_text"):
        body += "\n\nFull resume text (the source of truth):\n\n" + prof["_resume_text"][:40000]
    return body

def normalize(h):
    """Fill defaults and fix field_group/level against the local taxonomy (also used on user edits)."""
    h = dict(h or {})
    degs = []
    for d in h.get("degrees") or []:
        d = dict(d)
        d["level"] = d.get("level") if d.get("level") in LEVELS else "bachelor"
        d["field"] = (d.get("field") or "").strip()
        if d.get("field_group") not in FIELD_GROUPS or (d.get("field_group") == "other" and d["field"]):
            d["field_group"] = field_group(d["field"])
        d.setdefault("school", ""); d.setdefault("year", None); d.setdefault("completed", True)
        degs.append(d)
    h["degrees"] = degs
    lic = []
    for x in h.get("licenses") or []:
        x = dict(x)
        if not (x.get("name") or "").strip():
            continue
        x["kind"] = x.get("kind") if x.get("kind") in ("license", "cert") else "cert"
        x.setdefault("active", None)
        lic.append(x)
    h["licenses"] = lic
    h.setdefault("clearance", {"level": "none", "active": None, "note": ""})
    h.setdefault("years_experience", None)
    h.setdefault("management", {"manages_people": False, "direct_reports": None, "note": ""})
    h.setdefault("languages", []); h.setdefault("industries", []); h.setdefault("top_skills", [])
    return h

def extract(profile, model="claude-opus-5-5"):
    """Structured highlights from a profile dict (uses its _resume_text when present). One Claude call."""
    import claude_cli
    out = claude_cli.run_json(SYSTEM, _profile_prompt(profile), SCHEMA, model=model, effort="medium", timeout=600)
    return normalize(out)

# Cheap, offline reading of the profile's free-text education / certifications (no Claude). Used for a profile the
# person filled in themselves and whenever Claude isn't available; good for degree level + field.
#
# Degree short forms, without dots, lower case -> (level, the field the short form itself names or "").
DEGREE_ABBR = {
    "phd": ("doctorate", ""), "dphil": ("doctorate", ""), "dsc": ("doctorate", ""), "edd": ("doctorate", "Education"),
    "dnp": ("doctorate", "Nursing"), "psyd": ("doctorate", "Psychology"), "pharmd": ("doctorate", "Pharmacy"),
    "dpt": ("doctorate", "Physical Therapy"), "dba": ("doctorate", "Business Administration"),
    "jd": ("jd", "Law"), "md": ("md", "Medicine"), "do": ("md", "Medicine"),
    "ma": ("master", ""), "ms": ("master", ""), "msc": ("master", ""), "mba": ("master", "Business Administration"),
    "msn": ("master", "Nursing"), "msw": ("master", "Social Work"), "med": ("master", "Education"),
    "mph": ("master", "Public Health"), "mpa": ("master", "Public Administration"), "mpp": ("master", "Public Policy"),
    "mfa": ("master", "Fine Arts"), "meng": ("master", "Engineering"), "macc": ("master", "Accounting"),
    "llm": ("master", "Law"),
    "ba": ("bachelor", ""), "bs": ("bachelor", ""), "bsc": ("bachelor", ""), "bba": ("bachelor", "Business Administration"),
    "bsn": ("bachelor", "Nursing"), "bsw": ("bachelor", "Social Work"), "bfa": ("bachelor", "Fine Arts"),
    "beng": ("bachelor", "Engineering"), "bed": ("bachelor", "Education"),
    "aa": ("associate", ""), "as": ("associate", ""), "aas": ("associate", ""), "adn": ("associate", "Nursing"),
    "asn": ("associate", "Nursing"),
}
# Short forms that are no English word and no state code: read in any case ("bsn"). Every other one must be written in
# capitals ("BA", "MS"), and "MEd" / "BEd" exactly so ("Med-Surg" is not a Master of Education).
_ABBR_ANYCASE = {"phd", "dphil", "edd", "dnp", "psyd", "pharmd", "mba", "msn", "msw", "mph", "mpa", "mfa", "meng", "macc",
                 "llm", "msc", "bsc", "bba", "bsn", "bsw", "bfa", "beng", "aas", "adn", "asn"}
_ABBR_CASED = {"med": ("MEd",), "bed": ("BEd",)}
# Also state codes or plain words ("Boston, MA", "Oxford, MS"): a degree only at the start of the line or with a field.
_ABBR_WEAK = {"ma", "ms", "md", "as", "do"}
_ABBR_TOKEN = re.compile(r"(?<![A-Za-z0-9.])(?:(?:[A-Za-z]{1,5}\.){1,4}[A-Za-z]{0,3}|[A-Za-z]{2,7})(?![A-Za-z0-9])")
_DEG_WORDS = [
    ("doctorate", re.compile(r"\bdoctor(?:ate|al)\b|\bdoctor(?=\s+of\s+(?!medicine|osteopath|jurisprudence|law\b))", re.I)),
    ("jd", re.compile(r"\bjuris doctor(?:ate)?\b|\bdoctor of (?:jurisprudence|law)\b", re.I)),
    ("md", re.compile(r"\bdoctor of (?:medicine|osteopath\w*(?: medicine)?)\b|\bmedical degree\b", re.I)),
    ("master", re.compile(r"\bmaster(?:'s|s)?(?![A-Za-z])", re.I)),
    ("bachelor", re.compile(r"\bbachelor(?:'s|s)?(?![A-Za-z])|\bbaccalaureate\b", re.I)),
    ("associate", re.compile(r"\bassociate(?:'s|s)?(?![A-Za-z])", re.I)),
]
_DEG_ORDER = ["doctorate", "jd", "md", "master", "bachelor", "associate"]   # a line names one degree: the highest
_SCHOOLISH = re.compile(r"universit|college|\bschool\b|institute|academy|polytechnic|\bcampus\b|seminary|conservatory", re.I)
_DEG_LEAD = re.compile(r"^\.?\s*(?:\(\s*[A-Za-z.]{2,8}\s*\)\s*)?(?:degree\b\s*)?"
                       r"(?:of\s+(?:applied\s+)?(?:science|arts|philosophy)s?\b\s*)?(?:degree\b\s*)?", re.I)
_FIELD_END = re.compile(r"\s*(?:,|;|\(|\)|\||\s[-\u2013\u2014]\s|\bfrom\b|\bat\b|\b(?:19|20)\d\d\b|\bgraduat|\bgpa\b|\bminor\b|"
                        r"\bcum laude\b|\bwith honou?rs\b)", re.I)
_DASHES = " ,:-\u2013\u2014/"


def _field_cut(s):
    s = _FIELD_END.split(s or "", maxsplit=1)[0]
    s = re.sub(r"\s+degree$", "", s.strip(" ." + _DASHES), flags=re.I)
    return " ".join(s.split())[:80]


def _named_field(s):
    """`s` when it reads as a field of study we know and not as a school ("Computer Science", not "Ohio State")."""
    s = _field_cut(s)
    return s if s and len(s.split()) <= 6 and not _SCHOOLISH.search(s) and field_group(s) != "other" else ""


def parse_degree(text):
    """One education line as the person typed it -> {"level", "field", "field_group"}, or None when it names no degree.
    "BSN", "B.S.N." and "Bachelor of Science in Nursing" are all a Bachelor's in Nursing; "ADN" / "A.D.N." an
    Associate's in Nursing; "BS Computer Science", "B.A., English", "MS in Accounting", "MBA", "MEd", "JD", "PhD" too."""
    t = " ".join(str(text or "").replace("\u2019", "'").split())
    t = re.sub(r"^[\s\-\u2013\u2014*\u2022\u00b7]+", "", t)
    if not t:
        return None
    found = []      # (order, start, end, level, the field the short form names)
    for lv, rx in _DEG_WORDS:
        for m in rx.finditer(t):
            found.append((_DEG_ORDER.index(lv), m.start(), m.end(), lv, ""))
    for m in _ABBR_TOKEN.finditer(t):
        tok = m.group(0)
        low = tok.replace(".", "").lower()
        if low not in DEGREE_ABBR:
            continue
        if "." in tok:
            if len([x for x in tok.split(".") if x]) < 2:
                continue                      # "do." at the end of a sentence
        else:
            if low in _ABBR_CASED:
                if tok not in _ABBR_CASED[low]:
                    continue
            elif low not in _ABBR_ANYCASE and not tok.isupper():
                continue
            if low in _ABBR_WEAK and m.start() > 0:
                after = t[m.end():]
                if not (re.match(r"\s*,?\s*(?:in|of|degree)\b", after, re.I) or (re.match(r"\s+[A-Za-z]", after) and _named_field(after))):
                    continue
            if low == "ms" and re.match(r"\s+(?:office|word|excel|access|windows|project|teams|sql|dynamics|outlook|365)\b", t[m.end():], re.I):
                continue                      # Microsoft, not a Master's
        lv, fld = DEGREE_ABBR[low]
        found.append((_DEG_ORDER.index(lv), m.start(), m.end(), lv, fld))
    if not found:
        return None
    _, start, end, level, implied = min(found)
    rest = _DEG_LEAD.sub("", t[end:], count=1)
    field = ""
    m = re.match(r"\s*[,:\-\u2013\u2014]?\s*(?:in|of|with a (?:major|concentration) in|major(?:ing)? in)\s+(.+)", rest, re.I)
    if m:                                     # "... in Nursing", "Master of Business Administration"
        field = _field_cut(m.group(1))
        if _SCHOOLISH.search(field):
            field = ""
    if not field and not implied:             # "BS Computer Science", "B.A., English"
        field = _named_field(rest.lstrip(_DASHES))
    if not field and not implied:             # "Bachelor's degree, Ohio University, in Accounting"
        field = next((f for f in (_named_field(x.group(1)) for x in re.finditer(r"\b(?:in|major:?)\s+([^,(;]+)", rest, re.I)) if f), "")
    if not field and not implied:             # "Accounting, B.S."
        before = [x for x in re.split(r"[,;(|]", t[:start]) if x.strip(_DASHES)]
        field = _named_field(before[-1]) if before else ""
    field = field or implied or {"jd": "Law", "md": "Medicine"}.get(level, "")
    return {"level": level, "field": field, "field_group": field_group(field)}


# A status, a year or a place after a credential says something about it and is no credential of its own.
_QUALIFIER = re.compile(r"^(?:active|current|inactive|expired|lapsed|pending|in progress|multi-?state|compact|unencumbered|"
                        r"unrestricted|state of .+|(?:exp(?:ires|ired|iration)?\.?|since|issued|renewed|valid (?:through|until))\b.*|"
                        r"(?:\d{1,2}/)?(?:19|20)\d\d(?:\s*[-\u2013]\s*(?:(?:19|20)\d\d|present))?|#?\s*[A-Z]{0,3}\d{4,})$", re.I)
# City names that are also things people list as skills (software, methods): never dropped as "just a place".
_PLACE_OR_SKILL = {"phoenix", "mobile", "aurora", "mesa", "orange", "enterprise", "paradise", "independence", "providence",
                   "surprise", "corona", "temple", "vista", "tyler", "meridian", "concord", "reading", "oracle", "jupiter",
                   "commerce", "industry", "snowflake", "sterling", "hope", "liberty", "normal", "mission", "summit", "victoria",
                   "beaumont", "gary", "troy", "union", "spring", "sandy", "mercury", "eureka", "apex", "jira", "java", "excel"}


def just_place(s, home=""):
    """True when the text is only a place: a US state ("Ohio"), "City, ST" / "City, State", or one city name that is the
    person's own town (`home`, their profile's location) or a large city. A skill that merely contains a place word
    ("Ohio RN license", "Phoenix framework") is not one, and neither is a short code ("OR", "PA", "CT": those are skills)."""
    try:
        import geo
        raw = " ".join(str(s or "").split()).strip(" .")
        k = geo._key(raw)
        if not k or re.search(r"\d", k):
            return False
        if k in set(geo.STATES.values()) or k in ("district of columbia", "washington dc"):
            return True
        m = re.fullmatch(r"(.+?)\s*,?\s+([A-Z]{2})\.?", raw)
        if m and m.group(2) in geo.STATES and geo._known_in_state(m.group(1), m.group(2)):
            return True
        for code, name in geo.STATES.items():
            if k.endswith(" " + name) and geo._known_in_state(k[:-len(name) - 1], code):
                return True                   # "Columbus Ohio"
        if k in _PLACE_OR_SKILL:
            return False
        hits = [h for h in geo._load()["names"].get(k, []) if h[4] != "a"]
        if not hits:
            return False
        return k == geo._key(str(home or "").split(",")[0]) or max(h[3] for h in hits) >= 100000
    except Exception:
        return False


def split_items(text, home="", keep_places=False):
    """Skills or credentials as typed, one per item: split at new lines and semicolons, and at commas outside brackets
    ("RN license; BLS; ACLS", "BLS, ACLS, PALS").
    keep_places=False (skills): items that are just a place, a year or a status are dropped ("RN license, Ohio" ->
    "RN license"). keep_places=True (license names): a comma followed by such a detail stays with its credential
    ("RN license, Ohio" is one item)."""
    out = []
    for chunk in re.split(r"[;\n\r]+", str(text or "")):
        chunk = " ".join(chunk.split()).strip(" ,")
        if not chunk:
            continue
        if just_place(chunk, home):           # "Columbus, OH"
            out += [chunk] if keep_places else []
            continue
        parts =[x.strip() for x in re.split(r",(?![^()]*\))", chunk) if x.strip()]
        detail = [bool(_QUALIFIER.match(x)) or just_place(x, home) for x in parts]
        if keep_places:
            out += [chunk] if len(parts) > 1 and (any(detail) or any(len(x.split()) > 5 for x in parts)) else parts
        else:
            out += [x for x, d in zip(parts, detail) if not d]
    seen, res = set(), []
    for x in out:
        if x.lower() not in seen:
            seen.add(x.lower()); res.append(x)
    return res


def from_profile_rules(profile):
    degs = []
    for e in profile.get("education") or []:
        for line in re.split(r"[;\n\r]+", str(e)):
            d = parse_degree(line)
            if not d:
                continue
            yr = re.findall(r"\b(19\d\d|20\d\d)\b", line)
            degs.append({**d, "school": "", "year": int(yr[-1]) if yr else None, "completed": True})
    home = profile.get("location") or ""
    lic = [{"name": c, "kind": "license" if re.search(r"licen|\bRN\b|\bCPA\b|\bbar\b|\bP\.?E\.?\b", c) else "cert",
            "active": None} for raw in profile.get("certifications") or [] for c in split_items(raw, home, keep_places=True)]
    clr = "none"
    for c in profile.get("clearances") or []:
        cl = str(c).lower()
        lv = ("ts/sci + poly" if "poly" in cl else "ts/sci" if ("sci" in cl) else "top secret" if ("top secret" in cl or cl.strip() == "ts")
              else "secret" if "secret" in cl else "public trust" if "public trust" in cl else None)
        if lv and ["none", "public trust", "secret", "top secret", "ts/sci", "ts/sci + poly"].index(lv) > \
                ["none", "public trust", "secret", "top secret", "ts/sci", "ts/sci + poly"].index(clr):
            clr = lv
    return normalize({"degrees": degs, "licenses": lic, "years_experience": profile.get("years_experience"),
                      "clearance": {"level": clr, "active": None, "note": ""},
                      "top_skills": [str(s) for s in (profile.get("skills") or [])[:12]],
                      "languages": [{"language": l.split("(")[0].strip(), "level": ""} for l in profile.get("languages") or []]})

# ------------------------------------------------------------------ storage
EDITABLE = list(SCHEMA["properties"])

def path(pid):
    return people.pdir("highlights.json", pid=pid)

def load_raw(pid):
    try:
        return json.load(open(path(pid)))
    except Exception:
        return {"extracted": None, "edits": {}, "confirmed": None}

def save_raw(pid, raw):
    tmp = path(pid) + ".tmp"
    json.dump(raw, open(tmp, "w"), indent=1)
    os.replace(tmp, path(pid))

def merged(raw):
    base = normalize(raw.get("extracted") or {})
    for k, v in (raw.get("edits") or {}).items():
        if k in EDITABLE:
            base[k] = v
    return normalize(base)

def _fill_field_groups(h, pid):
    """A degree stored with no field ("BSN, Ohio State" as an earlier version read it: Bachelor's, field unknown) gets
    its field GROUP from the profile's own education lines, read again with parse_degree. Only the group, and only in
    this working view: the stored level and field text stay as they are, so nothing a rating was made from changes
    (ai_score reads merged(), and the Claude prompt prints level and field, never the group)."""
    todo = [d for d in h.get("degrees") or [] if not d.get("field") and d.get("field_group") in (None, "", "other")]
    if not todo:
        return h
    try:
        prof = json.load(open(people.pdir("profile.json", pid=pid), encoding="utf-8"))
        read = [x for x in (parse_degree(l) for e in prof.get("education") or [] for l in re.split(r"[;\n\r]+", str(e))) if x]
    except Exception:
        return h
    for d in todo:
        g = [x["field_group"] for x in read if x["level"] == d.get("level") and x["field_group"] != "other"]
        if g:
            d["field_group"] = g[0]
    return h

def get(pid):
    """Working highlights (extraction + user edits), or None if never extracted."""
    raw = load_raw(pid)
    if raw.get("extracted") is None and not raw.get("edits"):
        return None
    return _fill_field_groups(merged(raw), pid)

def source_hash(profile):
    keep = {k: profile.get(k) for k in ("education", "certifications", "clearances", "_resume_text")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]

def save(pid, extracted, profile=None):
    """Store a fresh extraction; the user's edits are kept and still win. Re-confirmation is requested."""
    raw = load_raw(pid)
    raw["extracted"] = normalize(extracted)
    raw["extracted_at"] = dt.datetime.now().isoformat(timespec="minutes")
    if profile is not None:
        raw["source_hash"] = source_hash(profile)
    raw["confirmed"] = None
    save_raw(pid, raw)
    return merged(raw)

def refresh(pid, profile=None, use_claude=True):
    """Extract from the person's active profile and save (call after a new resume is approved)."""
    if profile is None:
        profile = json.load(open(people.pdir("profile.json", pid=pid)))
    try:
        h = extract(profile) if use_claude else from_profile_rules(profile)
    except Exception as e:
        print("highlights: Claude extraction failed, using rules:", e, flush=True)
        h = from_profile_rules(profile)
    return save(pid, h, profile)

def stale(pid, profile):
    return load_raw(pid).get("source_hash") != source_hash(profile)

def apply_corrections(pid, edits, confirm=True):
    """edits: {field: new value} for any of EDITABLE (whole-field replacement, e.g. the full degrees list).
    Passing None for a field drops the edit (reverts to the extracted value). Returns the working view."""
    raw = load_raw(pid)
    cur = dict(raw.get("edits") or {})
    for k, v in (edits or {}).items():
        if k not in EDITABLE:
            continue
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = normalize({k: v})[k] if k in ("degrees", "licenses") else v
    raw["edits"] = cur
    if confirm:
        raw["confirmed"] = dt.datetime.now().isoformat(timespec="minutes")
    save_raw(pid, raw)
    return merged(raw)

def confirm(pid):
    raw = load_raw(pid)
    raw["confirmed"] = dt.datetime.now().isoformat(timespec="minutes")
    save_raw(pid, raw)
    return raw["confirmed"]

def payload(pid):
    """What the highlights screen needs (GET /api/highlights)."""
    raw = load_raw(pid)
    return {"highlights": get(pid), "extracted": raw.get("extracted"), "edited_fields": sorted((raw.get("edits") or {}).keys()),
            "confirmed": raw.get("confirmed"), "extracted_at": raw.get("extracted_at"),
            "options": {"levels": [{"id": l, "label": LEVEL_LABEL[l]} for l in LEVELS],
                        "field_groups": [{"id": g, "label": GROUP_LABEL[g]} for g in FIELD_GROUPS],
                        "license_kinds": ["license", "cert"],
                        "clearance_levels": SCHEMA["properties"]["clearance"]["properties"]["level"]["enum"]}}
