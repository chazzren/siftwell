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
    (r"nursing|\bbsn\b|\bmsn\b|\bdnp\b", "nursing"),
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

# Cheap, offline fallback from the profile's free-text education/certifications (no Claude). Used when Claude
# isn't available; good enough for degree level + field.
_DEG_RX = [
    (re.compile(r"\b(ph\.?\s?d|doctor of philosophy|doctorate|ed\.?d\.?|d\.sc)\b", re.I), "doctorate"),
    (re.compile(r"\b(j\.?d\.?|juris doctor)\b", re.I), "jd"),
    (re.compile(r"\b(m\.d\.|doctor of medicine|d\.o\.)", re.I), "md"),
    (re.compile(r"\b(master|m\.?s\.?c?|m\.a\.|mba|m\.eng|mpa|mph|mfa|msn)\b", re.I), "master"),
    (re.compile(r"\b(bachelor|b\.?s\.?c?|b\.a\.|ba|bba|b\.eng|bsn)\b", re.I), "bachelor"),
    (re.compile(r"\b(associate|a\.a\.|a\.s\.)\b", re.I), "associate"),
]
def from_profile_rules(profile):
    degs = []
    for e in profile.get("education") or []:
        lv = next((l for rx, l in _DEG_RX if rx.search(e)), None)
        if not lv:
            continue
        m = re.search(r"\b(?:in|of)\s+(?:(?:science|arts)\s+in\s+)?([^,(]+)", e, re.I)
        fld = m.group(1).strip() if m else ""
        if re.match(r"(science|arts)$", fld, re.I):
            fld = ""
        yr = re.findall(r"\b(19\d\d|20\d\d)\b", e)
        degs.append({"level": lv, "field": fld, "field_group": field_group(fld), "school": "",
                     "year": int(yr[-1]) if yr else None, "completed": True})
    lic = [{"name": c, "kind": "license" if re.search(r"licen|\bRN\b|\bCPA\b|\bbar\b|\bP\.?E\.?\b", c) else "cert",
            "active": None} for c in profile.get("certifications") or []]
    return normalize({"degrees": degs, "licenses": lic, "years_experience": profile.get("years_experience"),
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

def get(pid):
    """Working highlights (extraction + user edits), or None if never extracted."""
    raw = load_raw(pid)
    if raw.get("extracted") is None and not raw.get("edits"):
        return None
    return merged(raw)

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
