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

PROFILE_HASH_KEYS = ("summary", "experience", "reframings", "hard_limits", "target_roles", "notes", "clearances",
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
    """profile_hash before whitespace was normalized; ratings stored under it are adopted by ai_score/pivot. Frozen."""
    keep = {k: prof.get(k) for k in PROFILE_HASH_KEYS}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]

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
    draft.update(clean_edits(edited))
    draft["_approved"] = dt.datetime.now().isoformat(timespec="minutes")
    draft["_hash"] = profile_hash(draft)
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
    prof.update(clean_edits(edited))
    prof["_edited"] = dt.datetime.now().isoformat(timespec="minutes")
    prof["_hash"] = profile_hash(prof)
    paths.write_atomic(ACTIVE(), json.dumps(prof, indent=1))
    return prof

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
