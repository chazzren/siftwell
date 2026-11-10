"""Resume ingest -> text -> structured profile (draft for review) -> active profile used by scoring/tailoring."""
import datetime as dt, hashlib, json, os, re, shutil, subprocess, tempfile, urllib.request
import osdeps

import claude_cli, people

import paths
DATA = paths.DATA
def RESUMES(): return people.pdir("resumes")
def DRAFT(): return people.pdir("profile_draft.json")
def ACTIVE(): return people.pdir("profile.json")

TEXTUTIL_EXT = {".doc", ".docx", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive", ".wordml"}
CLAUDE_READ_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT_EXT = {".txt", ".md", ".markdown", ".text"}
ALLOWED = TEXTUTIL_EXT | CLAUDE_READ_EXT | TEXT_EXT | {".heic"}

# ------------------------------------------------------------------ ingest
def safe_name(name):
    base = os.path.basename(name or "resume")
    return re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:120] or "resume"

def save_upload(filename, data: bytes):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED:
        raise ValueError(f"Unsupported file type {ext or '(none)'}. Use PDF, Word, RTF, text, or an image.")
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("File is larger than 15 MB.")
    os.makedirs(RESUMES(), exist_ok=True)
    path = os.path.join(RESUMES(), dt.datetime.now().strftime("%Y%m%d-%H%M%S_") + safe_name(filename))
    with open(path, "wb") as f:
        f.write(data)
    return path

def fetch_google_doc(url):
    m = re.search(r"docs\.google\.com/document/d/([A-Za-z0-9_-]{20,})", url or "")
    if not m:
        raise ValueError("That doesn't look like a Google Docs link (docs.google.com/document/d/...).")
    export = f"https://docs.google.com/document/d/{m.group(1)}/export?format=docx"
    req = urllib.request.Request(export, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data, ctype = r.read(), r.headers.get("Content-Type", "")
    except Exception as e:
        raise ValueError(f"Couldn't download the Google Doc ({e}).")
    if "html" in ctype or not data.startswith(b"PK"):
        raise ValueError("Google wouldn't share that doc without a sign-in. In Google Docs, either set sharing to "
                         "'Anyone with the link can view', or use File > Download > Microsoft Word and upload that file.")
    return save_upload("google-doc.docx", data)

# ------------------------------------------------------------------ extraction
def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        return open(path, encoding="utf-8", errors="replace").read()
    if ext in TEXTUTIL_EXT:
        if osdeps.MAC:
            r = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", path], capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or not r.stdout.strip():
                raise ValueError("Couldn't read that document. Try saving it as PDF or .docx.")
            return r.stdout
        if ext == ".docx":
            import docx
            d = docx.Document(path)
            text = "\n".join(p.text for p in d.paragraphs)
            for tb in d.tables:
                for row in tb.rows:
                    text += "\n" + " | ".join(c.text for c in row.cells)
            if not text.strip():
                raise ValueError("That Word file looks empty. Try saving it as PDF.")
            return text
        if ext in (".html", ".htm"):
            return re.sub(r"<[^>]+>", " ", open(path, encoding="utf-8", errors="replace").read())
        raise ValueError("On this computer, use a PDF or .docx resume (open it in Word and Save As .docx).")
    if ext == ".heic":
        tmp = path + ".jpg"
        if osdeps.MAC:
            subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", path, "--out", tmp], capture_output=True, timeout=60)
        else:
            try:
                import pillow_heif
                from PIL import Image
                pillow_heif.register_heif_opener()
                Image.open(path).convert("RGB").save(tmp, "JPEG")
            except Exception:
                raise ValueError("Couldn't open that iPhone photo. Send it as a JPEG or PDF instead.")
        path, ext = tmp, ".jpg"
    # PDF or image: let Claude read the file directly (handles scans and odd layouts).
    with tempfile.TemporaryDirectory(dir=DATA) as d:
        local = os.path.join(d, "resume" + ext)
        shutil.copy(path, local)
        out = claude_cli.run_json(
            "You transcribe resumes. Return the full text of the resume file exactly as written, preserving section "
            "order, headings, dates and bullet text. Do not summarize, correct or add anything.",
            f"Read the file {local} and return its complete text.",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
            read_dir=d, effort="low")
    text = (out.get("text") or "").strip()
    if len(text) < 200:
        raise ValueError("Couldn't find resume text in that file.")
    return text

# ------------------------------------------------------------------ profile
LIST = {"type": "array", "items": {"type": "string"}}
PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "summary": {"type": "string"},
        "location": {"type": "string"},
        "years_experience": {"type": "integer"},
        "clearances": LIST, "education": LIST, "certifications": LIST, "skills": LIST, "languages": LIST,
        "experience": {"type": "array", "items": {"type": "object", "properties": {
            "employer": {"type": "string"}, "title": {"type": "string"}, "dates": {"type": "string"},
            "highlights": LIST}, "required": ["employer", "title", "dates", "highlights"], "additionalProperties": False}},
        "reframings": {"type": "array", "items": {"type": "object", "properties": {
            "angle": {"type": "string"}, "target_titles": LIST, "evidence": LIST},
            "required": ["angle", "target_titles", "evidence"], "additionalProperties": False}},
        "hard_limits": LIST,
        "target_roles": LIST,
        "title_keywords": LIST,
        "fit_keywords": LIST,
    },
    "required": ["name", "summary", "location", "years_experience", "clearances", "education", "certifications",
                 "skills", "languages", "experience", "reframings", "hard_limits", "target_roles", "title_keywords",
                 "fit_keywords"],
    "additionalProperties": False,
}

PROFILE_SYSTEM = """You turn a resume into a structured candidate profile for a job search tool.

Facts (clearances, education, certifications, skills, languages, experience) must come only from the resume. Copy them; do not upgrade or infer credentials.

"reframings" are honest ways to present the candidate's real experience for other kinds of roles: 4 to 8 of them. Each has an "angle" (how to frame it, one sentence), "target_titles" (job titles that framing opens up), and "evidence" (short quotes or close paraphrases of resume lines that support it). A reframing may translate jargon (military, agency or company-specific titles) into industry terms, group experience under a functional label, or emphasize a buried skill. It must never imply an employer, title, credential, clearance, tool or number the resume doesn't support.

"hard_limits" are things a tailored resume must never claim for this candidate: credentials they lack, technologies or domains with no evidence, levels well above their experience, clearances they don't currently hold. 4 to 10 items, each specific.

"target_roles" are 8 to 15 job titles worth searching for, mixing roles they fit as written and roles reachable through the reframings.

"title_keywords" are 15 to 30 lowercase words or short phrases that appear in titles of suitable jobs (used as a title filter, e.g. "solutions architect", "program manager"). "fit_keywords" are 15 to 30 lowercase terms that signal a good match inside a job description.

Never include phone numbers, email addresses or street addresses anywhere."""

def build_profile(text):
    prof = claude_cli.run_json(PROFILE_SYSTEM, "Resume:\n\n" + text[:40000], PROFILE_SCHEMA, effort="medium", timeout=900)
    prof["notes"] = ""
    return prof

# What the person's rating key is made from: resume content, reframings, notes. NOT the job titles to search for
# (target_roles): those are a board filter, so editing them must not reset ratings.
PROFILE_HASH_KEYS = ("summary", "experience", "reframings", "hard_limits", "notes", "clearances",
                     "certifications", "skills")
# The same list as older versions hashed it (it included target_roles). Frozen: only used to adopt old ratings.
PROFILE_HASH_KEYS_V1 = ("summary", "experience", "reframings", "hard_limits", "target_roles", "notes", "clearances",
                        "certifications", "skills")

def _norm_ws(v):
    """Same content -> same value: collapse runs of whitespace and trim, recursively (key order is handled by sort_keys)."""
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, list):
        return [_norm_ws(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm_ws(x) for k, x in v.items()}
    return v

def profile_hash(prof):
    """Key of this person's cached Claude ratings (saved as _hash when the profile is approved). Only the person's own
    profile data goes in, never code or prompt text, so an app update can't change it."""
    keep = {k: _norm_ws(prof.get(k)) for k in PROFILE_HASH_KEYS}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]

def profile_hash_legacy(prof):
    """profile_hash before whitespace was normalized and before job titles left it; ratings stored under it are adopted
    by ai_score/pivot. Frozen."""
    keep = {k: prof.get(k) for k in PROFILE_HASH_KEYS_V1}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]

def profile_hash_v1(prof):
    """profile_hash as it was when job titles were part of it (whitespace-normalized). Frozen: adoption only."""
    keep = {k: _norm_ws(prof.get(k)) for k in PROFILE_HASH_KEYS_V1}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]

def hash_aliases(before, after):
    """Older rating keys of this same person to remember when a profile is saved. If only things that are not part of the
    rating key changed (job titles), the keys the profile had before (its stored _hash, and the older formulas applied to
    the old data) still point at this person's ratings, so they are kept as _hash_aliases and adopted by
    ai_score.profile_keys. If the resume content changed, the ratings were made from different data: no aliases."""
    if not before or profile_hash(before) != profile_hash(after):
        return []
    new = profile_hash(after)
    out = []
    for h in [*(before.get("_hash_aliases") or []), before.get("_hash"), profile_hash_v1(before), profile_hash_legacy(before)]:
        if h and h != new and h not in out:
            out.append(h)
    return out

def ingest(path, progress=None):
    """Full pipeline for one uploaded file; writes the draft profile for review. progress(stage) is called as it goes."""
    note = progress or (lambda s: None)
    note("read")
    text = extract_text(path)
    note("build")
    prof = build_profile(text)
    prof["_source_file"] = os.path.basename(path)
    prof["_resume_text"] = text
    prof["_created"] = dt.datetime.now().isoformat(timespec="minutes")
    json.dump(prof, open(DRAFT(), "w"), indent=1)
    return prof

EDIT_TEXT = {"summary": 4000, "location": 120, "notes": 4000}
EDIT_LISTS = ("clearances", "education", "certifications", "skills", "languages", "target_roles", "hard_limits", "title_keywords")

def _strs(v, field):
    if isinstance(v, str):
        v = v.split("\n")
    if not isinstance(v, list):
        raise ValueError(f"{field} should be a list.")
    return [" ".join(str(x).split())[:2000] for x in v if str(x).strip()][:200]

def clean_edits(edited):
    """The fields of a profile a person may change, checked and trimmed. Anything else is ignored."""
    out = {}
    for k, n in EDIT_TEXT.items():
        if k in edited:
            out[k] = str(edited[k] or "").strip()[:n]
    for k in EDIT_LISTS:
        if k in edited:
            out[k] = _strs(edited[k], k)
    if "years_experience" in edited and edited["years_experience"] not in (None, ""):
        try:
            out["years_experience"] = max(0, min(70, int(edited["years_experience"])))
        except (TypeError, ValueError):
            raise ValueError("Years of experience should be a whole number.")
    if "experience" in edited:
        if not isinstance(edited["experience"], list):
            raise ValueError("experience should be a list.")
        out["experience"] = [{"title": " ".join(str(e.get("title", "")).split())[:200], "employer": " ".join(str(e.get("employer", "")).split())[:200],
                              "dates": " ".join(str(e.get("dates", "")).split())[:80], "highlights": _strs(e.get("highlights", []), "highlights")}
                             for e in edited["experience"] if isinstance(e, dict) and (str(e.get("title", "")).strip() or str(e.get("employer", "")).strip())][:40]
    if "reframings" in edited:
        if not isinstance(edited["reframings"], list):
            raise ValueError("reframings should be a list.")
        out["reframings"] = [{"angle": str(r.get("angle", "")).strip()[:2000], "target_titles": _strs(r.get("target_titles", []), "target_titles"),
                              "evidence": _strs(r.get("evidence", []), "evidence")}
                             for r in edited["reframings"] if isinstance(r, dict) and str(r.get("angle", "")).strip()][:20]
    return out

def approve(edited):
    """Merge the user's edits into the draft and make it the active profile."""
    draft = json.load(open(DRAFT())) if os.path.exists(DRAFT()) else (load_active() or {})
    before = load_active()
    draft.update(clean_edits(edited))
    draft["_approved"] = dt.datetime.now().isoformat(timespec="minutes")
    draft["_hash"] = profile_hash(draft)
    draft.pop("_hash_aliases", None)
    if hash_aliases(before, draft):
        draft["_hash_aliases"] = hash_aliases(before, draft)
    json.dump(draft, open(ACTIVE(), "w"), indent=1)
    if os.path.exists(DRAFT()):
        os.remove(DRAFT())
    return draft

def edit_active(edited):
    """Change fields of the approved profile in place (no new draft). Returns the profile; raises ValueError for bad input
    or when there is no approved profile yet."""
    prof = load_active()
    if not prof:
        raise ValueError("There's no approved profile to edit yet. Upload a resume first.")
    before = dict(prof)
    prof.update(clean_edits(edited))
    prof["_edited"] = dt.datetime.now().isoformat(timespec="minutes")
    prof["_hash"] = profile_hash(prof)
    prof.pop("_hash_aliases", None)
    if hash_aliases(before, prof):
        prof["_hash_aliases"] = hash_aliases(before, prof)
    paths.write_atomic(ACTIVE(), json.dumps(prof, indent=1))
    return prof

# ------------------------------------------------------------------ no Claude: fill in the profile by hand
CLEARANCE_LEVELS = ["Public Trust", "Secret", "Top Secret", "TS/SCI", "TS/SCI + poly"]
_LEVEL_WORDS = re.compile(r"^(senior|sr\.?|junior|jr\.?|lead|principal|staff|chief|head of|associate|assistant|vice president of|vp of|director of|manager of)\s+", re.I)

def _title_keywords(titles):
    out = []
    for t in titles:
        t = " ".join(str(t).lower().split())
        for v in (t, _LEVEL_WORDS.sub("", t).strip()):
            if len(v) >= 3 and v not in out:
                out.append(v)
    return out[:30]

def _years_from(experience):
    ys = [int(y) for e in experience for y in re.findall(r"\b(?:19|20)\d\d\b", e.get("dates", ""))]
    return max(0, min(70, dt.date.today().year - min(ys))) if ys else None

def build_manual_profile(f):
    """The same profile.json structure the resume reader produces, from the "Fill in my profile myself" form.
    f: name, location, current_title, years_experience, summary, experience [{title, employer, dates, highlights}],
    skills, education, certifications, clearance (one of CLEARANCE_LEVELS or ""). Raises ValueError on an empty form."""
    f = f or {}
    clr = str(f.get("clearance") or "").strip()
    p = clean_edits({k: f[k] for k in ("summary", "location", "skills", "education", "certifications", "experience", "years_experience")
                     if k in f})
    title = " ".join(str(f.get("current_title") or "").split())[:200]
    exp = p.get("experience") or []
    if not (title or p.get("summary") or exp or p.get("skills")):
        raise ValueError("Add at least your current job title, a few skills, or one role, so Siftwell knows what to look for.")
    roles = []
    for t in [title] + [e["title"] for e in exp]:
        if t and t.lower() not in [r.lower() for r in roles]:
            roles.append(t)
    years = p.get("years_experience")
    if years is None:
        years = _years_from(exp)
    skills = p.get("skills") or []
    prof = {"name": " ".join(str(f.get("name") or "").split())[:80], "summary": p.get("summary", ""), "location": p.get("location", ""),
            "years_experience": years if years is not None else 0,
            "clearances": [clr] if clr and clr.lower() != "none" else [], "education": p.get("education", []),
            "certifications": p.get("certifications", []), "skills": skills, "languages": [], "experience": exp,
            "reframings": [], "hard_limits": [], "target_roles": roles[:15], "title_keywords": _title_keywords(roles),
            "fit_keywords": [s.lower() for s in skills][:30], "notes": ""}
    return prof

def save_manual(f):
    """Make the hand-filled profile the approved, active one (replacing any draft). Returns the profile."""
    prof = build_manual_profile(f)
    prof["_source_file"] = "Filled in by hand"
    prof["_manual"] = True
    now = dt.datetime.now().isoformat(timespec="minutes")
    prof["_created"] = prof["_approved"] = now
    prof["_hash"] = profile_hash(prof)
    paths.write_atomic(ACTIVE(), json.dumps(prof, indent=1))
    if os.path.exists(DRAFT()):
        os.remove(DRAFT())
    return prof

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin|github)\.com\S*", re.I)
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_RANGE = re.compile(rf"((?:{_MON}\s+)?(?:19|20)\d\d)\s*(?:-|\u2013|\u2014|to)\s*((?:{_MON}\s+)?(?:19|20)\d\d|present|current|now)", re.I)
_HEADS = {
    "summary": r"(professional |career )?(summary|profile|objective)|about( me)?|summary of qualifications",
    "experience": r"(professional |work |relevant |employment )?(experience|history)|employment|work history|career history",
    "skills": r"((technical|core|key) )?(skills|competencies|technologies|expertise)(?: (?:and|&) .*)?",
    "education": r"education(?: (?:and|&) .*)?|academic background",
    "certifications": r"(?:certifications?|licenses?|licensure|certificates?)(?: (?:and|&) .*)?|licenses? (?:and|&) certifications?",
    "clearance": r"(security )?clearances?",
    "other": r"projects|awards|publications|references|volunteer.*|interests|languages|training|activities|honors.*|affiliations",
}
_BULLET = re.compile(r"^\s*(?:[\u2022\u25cf\u25aa\u25e6\u00b7*\u2013\u2014-]|o(?=\s))\s+(.*\S)")
_ORG = re.compile(r"\b(inc|llc|ltd|corp|corporation|company|co\.|university|college|agency|department|dept|group|bank|systems|technologies|"
                  r"solutions|labs?|associates|partners|consulting|services|foundation|institute|hospital|school|army|navy|command)\b", re.I)

def _scrub(s):
    return " ".join(_URL.sub(" ", _PHONE.sub(" ", _EMAIL.sub(" ", s))).split())

def _heading(line):
    s = line.strip().rstrip(":").strip()
    if not s or len(s) > 42 or s.endswith("."):
        return None
    for k, rx in _HEADS.items():
        if re.fullmatch(rx, s.lower()):
            return k
    return None

def _split_head(text):
    """(title, employer) from one line such as "Senior Engineer, Acme Corp" or "Acme Corp | Senior Engineer"."""
    parts = [p.strip() for p in re.split(r"\s+[|\u2013\u2014-]\s+|\s+at\s+|\s*\|\s*|,\s+", text) if p.strip()]
    if len(parts) >= 2:
        a, b = parts[0], parts[1]
        return (b, a) if _ORG.search(a) and not _ORG.search(b) else (a, b)
    return (parts[0] if parts else "", "")

def prefill_from_text(text):
    """Best-effort fields for the "Fill in my profile myself" form from the plain text of a resume (no AI): headings,
    date ranges and bullets. Phone numbers, emails and links are dropped. The person checks everything."""
    lines = [l.rstrip() for l in (text or "").replace("\r", "\n").split("\n")]
    head, sec, cur = [], {k: [] for k in _HEADS}, "head"
    for l in lines:
        if not l.strip():
            continue
        h = _heading(l)
        if h:
            cur = h
            continue
        (head if cur == "head" else sec[cur]).append(l.strip())
    out = {"name": "", "location": "", "current_title": "", "summary": "", "experience": [], "skills": [], "education": [],
           "certifications": [], "clearance": "", "years_experience": None}
    for l in head[:6]:
        c = _scrub(l)
        if c and len(c.split()) <= 5 and not re.search(r"\d|resume|curriculum", c, re.I):
            out["name"] = c.title() if c.isupper() else c
            break
    for l in head[:8]:
        m = re.search(r"([A-Z][A-Za-z.' -]+,\s*[A-Z]{2})\b", _scrub(l))
        if m:
            out["location"] = m.group(1).strip()
            break
    out["summary"] = " ".join(_scrub(l) for l in sec["summary"])[:2000]
    # experience: a line holding a date range starts a role; the one or two short lines above it are its title / employer
    entries, pending = [], []
    for l in sec["experience"]:
        b = _BULLET.match(l)
        m = _RANGE.search(l)
        if b:
            if entries:
                entries[-1]["highlights"].append(_scrub(b.group(1)))
            pending = []
        elif m and len(l) < 200:
            rest = _scrub((l[:m.start()] + " " + l[m.end():]).strip(" |,-\u2013\u2014()\t"))
            heads = pending[-2:] + ([rest] if rest else [])
            if entries and pending:  # those header lines were taken as the last role's text: give them back
                for _ in pending[-2:]:
                    if entries[-1]["highlights"]:
                        entries[-1]["highlights"].pop()
            if len(heads) >= 2:
                a, b2 = heads[0], heads[1]
                title, emp = (b2, a) if _ORG.search(a) and not _ORG.search(b2) else (a, b2)
            else:
                title, emp = _split_head(heads[0]) if heads else ("", "")
            entries.append({"title": title[:200], "employer": emp[:200], "dates": m.group(0), "highlights": []})
            pending = []
        else:
            c = _scrub(l)
            if entries:
                entries[-1]["highlights"].append(c)
            if len(c) <= 90 and not c.endswith("."):
                pending.append(c)
            else:
                pending = []
    if not entries and sec["experience"]:
        entries = [{"title": "", "employer": "", "dates": "", "highlights": [_scrub(l) for l in sec["experience"]][:20]}]
    out["experience"] = entries[:15]
    if entries and entries[0]["title"]:
        out["current_title"] = entries[0]["title"]
    out["years_experience"] = _years_from(entries)
    sk = []
    for l in sec["skills"]:
        b = _BULLET.match(l)
        l = (b.group(1) if b else l)
        if ":" in l:
            l = l.split(":", 1)[1]
        for p in re.split(r"[,;|\u2022\u00b7]", l):
            p = _scrub(p).strip(" .")
            if p and len(p) <= 40 and p.lower() not in [x.lower() for x in sk]:
                sk.append(p)
    out["skills"] = sk[:60]
    def plain(ls):
        return [_scrub(_BULLET.match(l).group(1) if _BULLET.match(l) else l) for l in ls if _scrub(l)][:15]
    out["education"], out["certifications"] = plain(sec["education"]), plain(sec["certifications"])
    blob = " ".join(lines)
    if re.search(r"ts\s*/\s*sci.{0,40}poly|poly.{0,40}ts\s*/\s*sci|full[- ]scope", blob, re.I):
        out["clearance"] = "TS/SCI + poly"
    elif re.search(r"ts\s*/\s*sci|top secret\s*/\s*sci", blob, re.I):
        out["clearance"] = "TS/SCI"
    elif re.search(r"top secret|\bTS\b(?=.{0,30}clearance)|clearance.{0,25}\bTS\b", blob, re.I):
        out["clearance"] = "Top Secret"
    elif re.search(r"secret(?=.{0,25}clearance)|clearance.{0,25}secret|\bsecret clearance", blob, re.I):
        out["clearance"] = "Secret"
    elif re.search(r"public trust", blob, re.I):
        out["clearance"] = "Public Trust"
    return out

def prefill_from_file(filename, data: bytes):
    """Fields from an uploaded .docx / .txt resume by plain text extraction. Raises ValueError (friendly) for other types."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in TEXT_EXT | TEXTUTIL_EXT:
        raise ValueError("Without Claude, Siftwell can read Word (.docx) and text (.txt) resumes. For a PDF or photo, "
                         "copy its text into a .txt file, or fill in the form by hand.")
    path = save_upload(filename, data)
    return prefill_from_text(extract_text(path))

def load_active():
    try:
        return json.load(open(ACTIVE()))
    except Exception:
        return None

def load_draft():
    try:
        return json.load(open(DRAFT()))
    except Exception:
        return None

def discard_draft():
    if os.path.exists(DRAFT()):
        os.remove(DRAFT())

def profile_text(prof, goals=""):
    """Plain-text profile handed to Claude for scoring and tailoring."""
    if not prof:
        return ""
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
    try:
        import interview
        ft = interview.facts_text()
        if ft:
            lines += ["", ft]
    except Exception:
        pass
    try:
        import highlights, people
        h = highlights.get(people.current())
        if h:
            degs = "; ".join(f"{d.get('level','')} {('in ' + d['field']) if d.get('field') else ''}".strip() for d in h.get("degrees") or [])
            lic = "; ".join(l.get("name", "") for l in h.get("licenses") or [])
            m = h.get("management") or {}
            lines += ["", "Confirmed by the candidate: degrees: " + (degs or "none") + "; licenses/certifications: " + (lic or "none")
                      + (f"; years of experience: {h['years_experience']}" if h.get("years_experience") is not None else "")
                      + (f"; currently manages {m['direct_reports']} direct report(s)" if m.get("direct_reports") is not None else "")]
    except Exception:
        pass
    if goals:
        lines += ["", goals]
    return "\n".join(lines)
