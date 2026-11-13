"""Tailor the active resume to one job: Claude rewrites within the facts, every bullet cites its source line.
Writes DATA/people/<id>/tailored/<slug>.json; the PDF and the Word file are both drawn from it and this profile's
Resume settings by the same code (resolve), so they always show the same sections. After Claude answers, plain code
checks the result against the person's own data (fact_check): employers, titles, dates and education are copied back
from the profile, every bullet's stated source is looked up, and numbers or skills found in no source are flagged."""
import datetime as dt, html, json, os, re
import frozen
import osdeps

import claude_cli, people, resume

def OUT(): return people.pdir("tailored")

LIST = {"type": "array", "items": {"type": "string"}}
BULLET = {"type": "object", "properties": {
    "text": {"type": "string"},
    "source": {"type": "string"},
    "change": {"type": "string", "enum": ["kept", "reworded", "surfaced", "added_from_notes"]}},
    "required": ["text", "source", "change"], "additionalProperties": False}
# Per-resume layout controls Claude may set during a review rework. "default" = use the profile's Settings.
LAYOUT_ENUMS = {
    "margins": ["default", "narrow", "normal", "wide"],
    "font_size": ["default", "9.5", "10", "10.5", "11"],
    "line_spacing": ["default", "tight", "normal", "airy"],
    "section_spacing": ["default", "tight", "normal", "airy"],
    "titles": ["default", "paren", "line", "hide"],
    "skills_style": ["default", "inline", "grouped"],
    "headline": ["default", "full", "short", "none"],
    "summary": ["default", "on", "off"],
    "section_order": ["default", "experience_first", "skills_before_experience", "education_first"],
}
LAYOUT = {"type": "object", "properties": {k: {"type": "string", "enum": v} for k, v in LAYOUT_ENUMS.items()},
          "required": list(LAYOUT_ENUMS), "additionalProperties": False}
SKILL_GROUP = {"type": "object", "properties": {"label": {"type": "string"}, "items": LIST},
               "required": ["label", "items"], "additionalProperties": False}

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "headline_short": {"type": "string"},
        "skill_groups": {"type": "array", "items": SKILL_GROUP},
        "layout": LAYOUT,
        "summary": {"type": "string"},
        "summary_sources": LIST,
        "experience": {"type": "array", "items": {"type": "object", "properties": {
            "employer": {"type": "string"}, "location": {"type": "string"}, "title": {"type": "string"},
            "functional_title": {"type": "string"}, "dates": {"type": "string"},
            "bullets": {"type": "array", "items": BULLET}},
            "required": ["employer", "location", "title", "functional_title", "dates", "bullets"], "additionalProperties": False}},
        "skills": LIST,
        "education": LIST,
        "clearance": LIST,
        "additional": LIST,
        "dropped": LIST,
        "gaps": LIST,
        "unsupported_requests": LIST,
    },
    "required": ["headline", "headline_short", "skill_groups", "layout", "summary", "summary_sources", "experience", "skills",
                 "education", "clearance", "additional", "dropped", "gaps", "unsupported_requests"],
    "additionalProperties": False,
}

SYSTEM = """You tailor a candidate's real resume to one job posting. You are an honest editor, not a ghostwriter.

ALLOWED:
- Reorder sections, roles' bullets and skills so the most relevant come first.
- Reword bullets using the posting's vocabulary when the meaning stays true.
- Surface experience that is in the resume but buried, or listed elsewhere (e.g. a skill line) into a relevant bullet.
- Add a "functional_title" next to the official title when it is an accurate plain-language equivalent (e.g. a military or agency title translated to its industry equivalent). Leave it empty when the official title is already clear. Never replace the official title.
- Write everything in polished, professional resume language. The candidate's answers and notes are often quick and casual: treat them as facts, never as copy. Never paste an answer's wording; rephrase it as a crisp bullet (strong verb first, correct names and capitalization, no slang, no first person, no hedging filler), keeping its exact meaning and limits.
- Use facts from "Additional facts confirmed by the candidate" and "Facts the candidate confirmed in Q&A" (mark those bullets change = "added_from_notes", with source "Your answer: <requirement>" or "Your notes"). Use them exactly as strongly as the candidate stated them: "Some / a little" supports wording like "familiar with" or "used", never "expert in" or "led"; add no numbers, dates or outcomes the answer doesn't contain. Place each fact under the employer the answer names; if it names none, put it in skills or "additional", not under a job.
- Cut or shorten material that doesn't help for this job (list what you cut in "dropped").
- Certifications and licenses get their own section, filled in by the tool from the profile: do not repeat them under "education" or "additional".

NEVER:
- Invent or inflate employers, titles, dates, degrees, certifications, clearances, tools, team sizes, metrics or outcomes.
- Claim anything in the candidate's hard limits or anything they answered "No" to.
- Imply current possession of a clearance the candidate only held in the past.

"headline_short" is a compact version of the headline (70 characters or fewer). "skill_groups" sorts the same skills into 2 to 4 labeled groups (e.g. "Platforms", "Delivery", "Security"); use only skills already in "skills". "layout": when first tailoring, set every field to "default" (the candidate's own settings apply).

Every bullet needs "source": the resume line (quote it, or the closest exact phrase) it is based on. If you cannot point to a source, do not write the bullet. "summary_sources" lists the resume lines the summary relies on.

"gaps" are the posting's important requirements that the real resume does not meet (be specific and candid). "unsupported_requests" are things the posting asks for that you deliberately did not claim. Keep the resume to what fits on one to two pages; 3 to 6 bullets per recent role, fewer for older roles. Write bullets in the candidate's voice without pronouns, starting with strong verbs."""

REVISE = """You are revising a tailored resume after an independent reviewer graded it. You control both the wording and the "layout" fields: use layout to fix the reviewer's appearance and density notes (margins, font size, line and section spacing, how plain-English titles display, grouped skills with bold labels, a shorter headline, section order). Keep it readable: never pick a smaller font and tighter spacing and narrower margins all at once unless the page limit demands it, and stay within the candidate's page limit. Leave a field at "default" when the reviewer raised nothing about it. Apply the reviewer's fixes where they are true to the candidate's facts: tighten wording, fix grammar and consistency, reorder for relevance, use the posting's phrasing for things the candidate really did, correct any wording that overstates or misattributes. Use new facts from "Facts the candidate confirmed in Q&A" where they help, exactly as strongly as stated.

Decline any fix that would require a fact the original resume or the candidate's answers don't support (for example an invented metric, an aspirational "target role" line presented as experience, or a tool they never used). List each declined fix in "unsupported_requests" with a short reason. Every bullet still needs a source, as before. Return the complete revised resume."""

def revise(job, description, current, review):
    """Rework a tailored resume using a reviewer's grade; same honesty rules and schema as tailor()."""
    prof = resume.load_active()
    rtext = prof.get("_resume_text", "")
    issues = "\n".join(f"- [{i['area']}/{i['severity']}] {i['where']}: {i['problem']} Fix: {i['fix']}" for i in review.get("issues", []))
    # what the tool's own fact check found in the current version: these must be fixed, whatever the reviewer said
    warns = [w["text"] for w in ((current.get("checks") or {}).get("warnings") or [])][:20]
    facts_block = ("\n\nFACT CHECK BY THE TOOL (each line is something in the current resume that no source supports. "
                   "Fix every one: remove it, or reword it to what the sources say. Do not defend it.)\n" + "\n".join("- " + w for w in warns)) if warns else ""
    prompt = (f"JOB POSTING\nTitle: {job['title']}\nCompany: {job['company']}\n\n{description[:12000]}\n\n"
              f"ORIGINAL RESUME (the only source of facts besides confirmed answers)\n{rtext}\n\n"
              f"CANDIDATE PROFILE\n{resume.profile_text(prof)}\n\n"
              f"CURRENT TAILORED RESUME (JSON)\n{json.dumps({k: current.get(k) for k in SCHEMA['properties']}, indent=1)[:30000]}\n\n"
              f"REVIEWER GRADE: {review.get('score')}/100. Summary: {review.get('summary', '')}\n"
              f"Missing posting keywords: {', '.join(review.get('missing_keywords', [])[:20])}\nISSUES\n{issues}{facts_block}")
    out = claude_cli.run_json(SYSTEM + "\n\n" + REVISE + "\n\n" + preference_rules(), prompt, SCHEMA, effort="medium", timeout=900)
    for k in ("job", "contact", "created"):
        out[k] = current.get(k)
    fact_check(out, prof)
    return out

def save_tailored(s, t):
    json.dump(t, open(os.path.join(OUT(), s + ".json"), "w"), indent=1)
    try:
        make_docx(s)      # (from the same sections and settings as the PDF; rebuilt again on download if settings change)
    except Exception as e:
        print("Word file not written:", e, flush=True)

# ------------------------------------------------------------------ fact check (plain code, after Claude)
def _norm(s):
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", str(s or "").lower()).split())

def _stem(w):
    for suf in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)] + ("y" if suf == "ies" else "")
    return w

def _words(s):
    return [_stem(w) for w in _norm(s).split() if len(w) >= 3 or w.isdigit() or re.search(r"[+#]", w)]

def _like(a, b):
    import difflib
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if (a in b or b in a) and min(len(a), len(b)) >= 4:      # "Acme" for "Acme Corporation"
        return 0.85
    return difflib.SequenceMatcher(None, a, b).ratio()

def _found(src, lines, need=0.7):
    """Is this quoted source really in these lines? True when one line holds most of its words (the model quotes
    loosely: a word dropped, a tense changed), or the lines together hold nearly all of them."""
    ws = set(_words(src))
    if not ws:
        return False
    allw = set()
    for ln in lines:
        lw = set(_words(ln))
        allw |= lw
        if len(ws & lw) / len(ws) >= need:
            return True
    return len(ws) >= 4 and len(ws & allw) / len(ws) >= 0.9

_NUM = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")

def _numbers(s):
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(str(s or ""))}

def fact_check(t, prof=None, facts=None):
    """Check a tailored resume against the person's own data and fix what plain code can. Changes t in place and
    stores the outcome in t["checks"] = {"fixed": [what was corrected], "warnings": [{"kind", "text"}], "at"}.

    Fixed by copying, never trusted to the model: each role's employer, title and dates (from the profile's matching
    job; a sample came back with a shortened employer name), education lines, and the Certifications section (the
    profile's own list). Each bullet's stated source is then looked up in the resume text and in the answers the person
    gave: a bullet labelled "From your answers" that is really on the resume (or the other way round) gets the right
    label, and one whose source is found nowhere is flagged. Numbers (40%, $2M, 12 people) and skills that appear in
    none of the person's sources are flagged too. Warnings are shown on the Resumes card and the review page, and are
    handed to the rework step (revise) as things that must be fixed."""
    prof = prof if prof is not None else (resume.load_active() or {})
    if facts is None:
        try:
            import interview
            facts = interview.load_facts()
        except Exception:
            facts = []
    fixed, warns = [], []
    warn = lambda kind, text: warns.append({"kind": kind, "text": text[:260]})
    short = lambda s, n=90: (str(s)[:n].rstrip() + "…") if len(str(s)) > n else str(s)
    # ---- 1. roles: employer, title, dates as on the profile
    roles = [p for p in prof.get("experience") or [] if isinstance(p, dict)]
    used = set()
    year = lambda s: set(re.findall(r"(?:19|20)\d\d", str(s or "")))
    for x in t.get("experience") or []:
        if not roles:
            break
        best, best_i = 0.0, None
        for i, p in enumerate(roles):
            emp, ttl = _like(x.get("employer"), p.get("employer")), _like(x.get("title"), p.get("title"))
            yr = 1.0 if year(x.get("dates")) & year(p.get("dates")) else 0.0
            if emp < 0.5 and not (ttl >= 0.8 and yr):
                continue
            sc = 0.55 * emp + 0.3 * ttl + 0.15 * yr - (0.05 if i in used else 0)
            if sc > best:
                best, best_i = sc, i
        if best_i is None:
            warn("role", f"“{short(x.get('title'), 60)}, {short(x.get('employer'), 60)}” is not a job on your profile. Check it before you send.")
            continue
        used.add(best_i)
        p = roles[best_i]
        for k, label in (("employer", "Employer"), ("title", "Job title"), ("dates", "Dates")):
            want = " ".join(str(p.get(k) or "").split())
            if want and x.get(k) != want:
                if _norm(x.get(k)) != _norm(want):
                    fixed.append(f"{label} “{short(x.get(k), 60)}” set back to “{short(want, 60)}”, as on your profile.")
                x[k] = want
    # ---- 2. education and certifications: the profile's own lines
    rtext = prof.get("_resume_text") or ""
    edu = [" ".join(str(e).split()) for e in prof.get("education") or [] if str(e).strip()]
    out_edu = []
    for line in t.get("education") or []:
        m = max(edu, key=lambda e: _like(line, e), default=None)
        if m and (_like(line, m) >= 0.55 or _found(line, [m], 0.6)):
            if _norm(m) != _norm(line):
                fixed.append(f"Education line “{short(line, 60)}” set back to “{short(m, 60)}”, as on your profile.")
            line = m
        elif not _found(line, rtext.splitlines(), 0.6):
            warn("education", f"Education line “{short(line)}” is not on your profile or resume.")
        if line not in out_edu:
            out_edu.append(line)
    if "education" in t:
        t["education"] = out_edu
    certs = [" ".join(str(c).split()) for c in prof.get("certifications") or [] if str(c).strip()]
    t["certifications"] = certs
    if certs:   # each credential in one place only
        dup = lambda line: any(_like(line, c) >= 0.8 or _found(c, [line], 0.9) for c in certs)
        for k in ("education", "additional"):
            if t.get(k):
                t[k] = [x for x in t[k] if not dup(x)]
    # ---- 3. every bullet's source
    res_lines = [l for l in rtext.splitlines() if l.strip()]
    for e in roles:
        res_lines += [str(h) for h in e.get("highlights") or []]
    res_lines += [str(prof.get("summary") or "")] + [str(s) for k in ("skills", "certifications", "education", "clearances", "languages") for s in prof.get(k) or []]
    have = [f for f in facts or [] if isinstance(f, dict) and f.get("level") != "no"]
    ans_lines = [str(f.get(k) or "") for f in have for k in ("requirement", "answer", "polished")] + [str(prof.get("notes") or "")]
    ans_lines = [l for l in ans_lines if l.strip()]
    for x in t.get("experience") or []:
        for b in x.get("bullets") or []:
            b.pop("unverified", None)
            src = str(b.get("source") or "")
            m = re.match(r"\s*your (answers?|notes?)\s*[:\-–]?\s*(.*)", src, re.I | re.S)
            said_answer = bool(m) or b.get("change") == "added_from_notes"
            body = m.group(2) if m and m.group(2).strip() else src
            in_ans = bool(ans_lines) and (_found(body, ans_lines) or any(_like(body, f.get("requirement")) >= 0.6 for f in have)
                                          or bool(m and re.match(r"notes?", m.group(1), re.I) and (prof.get("notes") or "").strip()))
            in_res = _found(body, res_lines)
            if said_answer:
                if in_ans:
                    b["change"] = "added_from_notes"
                elif in_res:
                    b["change"] = "surfaced"
                    fixed.append(f"A bullet labelled “From your answers” is from your resume: label corrected (“{short(b.get('text'), 70)}”).")
                else:
                    b["unverified"] = True
                    warn("source", f"No answer of yours backs this bullet: “{short(b.get('text'))}”")
            elif in_res:
                pass
            elif in_ans:
                b["change"] = "added_from_notes"
                fixed.append(f"A bullet marked as from your resume comes from your answers: label corrected (“{short(b.get('text'), 70)}”).")
            else:
                b["unverified"] = True
                warn("source", f"The source given for this bullet is not in your resume or answers: “{short(b.get('text'))}”")
    # ---- 4. numbers and skills that are in no source
    everything = res_lines + ans_lines + [str(prof.get("years_experience") or "")] + [f"{e.get('title')} {e.get('employer')} {e.get('dates')}" for e in roles]
    try:
        import highlights
        h = highlights.get(people.current()) or {}
        everything += [json.dumps(h)]
    except Exception:
        pass
    known_nums = set().union(*(_numbers(l) for l in everything)) if everything else set()
    texts = [(b.get("text") or "") for x in t.get("experience") or [] for b in x.get("bullets") or []] + [t.get("summary") or ""] + list(t.get("additional") or [])
    seen_n = set()
    for text in texts:
        for n in sorted(_numbers(text) - known_nums):
            if n not in seen_n and not (len(n) == 1 and n in "0123456789" and False):
                seen_n.add(n)
                warn("number", f"“{n}” is in none of your sources: “{short(text)}”")
    known_words = set()
    for l in everything:
        known_words.update(_words(l))
    blob = _norm(" ".join(everything))
    for sk in t.get("skills") or []:
        ws = [w for w in _words(sk) if not w.isdigit()]
        if ws and not (all(w in known_words for w in ws) or _norm(sk) in blob):
            warn("skill", f"Skill “{short(sk, 60)}” is in none of your sources (your resume, profile or answers).")
    t["checks"] = {"fixed": fixed[:30], "warnings": warns[:30], "at": dt.datetime.now().isoformat(timespec="minutes")}
    return t["checks"]

def preference_rules():
    """Extra instructions from this profile's Tailoring and Resume settings (never loosen the honesty rules above)."""
    import people
    pr = people.prefs()
    length = {"1": "The finished resume must fit on ONE page: summary of 2 sentences at most, at most {r} bullets for the most recent role and {o} for each older role, skills list of 12 items or fewer, cut anything that isn't relevant to this job.",
              "2": "Keep it to two pages at most.",
              "any": "Length is flexible; include everything relevant."}[pr["resume.length"]]
    r, o = pr["tailor.bullets_recent"], pr["tailor.bullets_older"]
    if pr["resume.length"] == "1":
        r, o = min(r, 4), min(o, 2)
    style = {"light": "Rewrite lightly: mostly reorder, trim and swap in the posting's vocabulary; keep the candidate's original wording wherever it already works.",
             "balanced": "Rewrite in a balanced way: reword bullets for this job where it helps, keep the meaning exact.",
             "strong": "Reframe strongly: lead with the angle that best fits this job, regroup and rewrite bullets around it, use reframings and answers fully. The honesty rules still apply without exception."}[pr["tailor.style"]]
    rules = ["CANDIDATE PREFERENCES", length.format(r=r, o=o), style,
             f"Use at most {r} bullets for the most recent role and at most {o} for each older role."]
    if not pr["resume.summary"]:
        rules.append("Keep the summary to one short sentence (the candidate hides it in the PDF).")
    if pr["resume.clearance"] == "active":
        rules.append("Only mention clearances the candidate currently holds.")
    return "\n".join(rules)

def slug(job_id):
    return re.sub(r"[^a-z0-9]+", "-", job_id.lower()).strip("-")[:80]

def contact_header(resume_text, prof=None):
    """Name/contact lines as written at the top of the resume (kept verbatim, never sent anywhere but Claude).
    A profile filled in by hand has no resume text: its name, location and contact fields (email, phone, LinkedIn, when
    given) are used instead, in the same shape (name, then one line), so the Resume PDF contact toggles apply to them."""
    lines = [l.strip() for l in (resume_text or "").splitlines() if l.strip()]
    head = []
    for l in lines[:6]:
        if re.fullmatch(r"[A-Z][A-Z &/]{3,}", l) or l.upper() in ("EDUCATION", "EXPERIENCE", "SUMMARY", "PROFESSIONAL EXPERIENCE"):
            break
        head.append(l)
    return head[:4] or profile_contact(prof)

def profile_contact(prof):
    """[name, "location | email | phone | linkedin"] from a profile's own fields (a hand-filled one), or []."""
    if not prof:
        return []
    c = prof.get("contact") if isinstance(prof.get("contact"), dict) else {}
    name = " ".join(str(prof.get("name") or "").split())
    bits = [" ".join(str(x or "").split()) for x in (prof.get("location"), c.get("email"), c.get("phone"), c.get("linkedin"))]
    bits = [b for b in bits if b]
    if not name and not bits:
        return []
    return [name or "Resume"] + ([" | ".join(bits)] if bits else [])

def contact_of(t):
    """The contact lines a tailored resume is drawn with: its own, or (made from a hand-filled profile before it kept
    any) the profile's."""
    if t.get("contact"):
        return t["contact"]
    try:
        return profile_contact(resume.load_active())
    except Exception:
        return []

def tailor(job, description):
    prof = resume.load_active()
    if not prof:
        raise ValueError("Upload and approve a resume first.")
    rtext = prof.get("_resume_text", "")
    prompt = (f"JOB POSTING\nTitle: {job['title']}\nCompany: {job['company']}\nLocation: {'; '.join(job.get('locations', [])[:4])}\n"
              f"Clearance noted: {job.get('clearance') or 'none'}\n\n{description[:12000]}\n\n"
              f"ORIGINAL RESUME (the only source of facts)\n{rtext}\n\n"
              f"CANDIDATE PROFILE\n{resume.profile_text(prof)}")
    out = claude_cli.run_json(SYSTEM + "\n\n" + preference_rules(), prompt, SCHEMA, effort="medium", timeout=900)
    out["job"] = {k: job.get(k) for k in ("id", "title", "company", "url", "locations")}
    out["contact"] = contact_header(rtext, prof)
    out["created"] = dt.datetime.now().isoformat(timespec="minutes")
    fact_check(out, prof)      # copy the facts back from the profile, look up every source, flag what has none
    os.makedirs(OUT(), exist_ok=True)
    s = slug(job["id"])
    save_tailored(s, out)
    return s

def write_docx(t, path, pr=None, fit=0):
    """The Word file, drawn from the same resolved sections, order, contact details and layout as the PDF (resolve),
    so every Resume setting applies to it too. Plain paragraphs and real bullets: easy to edit, fine for screening
    software, and opens in Google Docs."""
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    R = resolve(t, pr, fit)
    d = Document()
    wide, tall = (8.27, 11.69) if R["paper"] == "A4" else (8.5, 11.0)
    for s in d.sections:
        s.page_width, s.page_height = Inches(wide), Inches(tall)
        s.left_margin = s.right_margin = Inches(R["margin_h"])
        s.top_margin = s.bottom_margin = Inches(R["margin_v"])
    body_font, head_font = R["word_fonts"]
    size, gap = R["size"], R["gap"]
    accent = RGBColor.from_string(R["accent"].lstrip("#").upper())
    grey = RGBColor(0x4A, 0x52, 0x5C)
    st = d.styles["Normal"]; st.font.name = body_font; st.font.size = Pt(size)
    st.paragraph_format.line_spacing = round(R["lh"] / 1.2, 2)
    st.paragraph_format.space_after = Pt(0)
    text_w = Inches(wide - 2 * R["margin_h"])
    def run(p, text, bold=False, italic=False, pt=None, color=None, font=None):
        r = p.add_run(text); r.bold = bold; r.italic = italic
        if pt: r.font.size = Pt(pt)
        if color is not None: r.font.color.rgb = color
        if font: r.font.name = font
        return r
    def para(text="", align=None, before=0, after=0, **kw):
        p = d.add_paragraph()
        if text: run(p, text, **kw)
        if align: p.alignment = align
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(before), Pt(after)
        return p
    def heading(text):
        p = para(text.upper(), before=12 * gap, after=4 * gap, bold=True, pt=size * .84, color=accent, font=head_font)
        p.paragraph_format.keep_with_next = True
        pPr = p._p.get_or_add_pPr(); bdr = OxmlElement("w:pBdr"); b = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "2"), ("w:color", "C9CED6")):
            b.set(qn(k), v)
        bdr.append(b); pPr.append(bdr)
    def two(left, right, **kw):       # left text, right text at the right margin (employer | place, title | dates)
        p = para(before=0)
        p.paragraph_format.tab_stops.add_tab_stop(text_w, WD_TAB_ALIGNMENT.RIGHT)
        p.paragraph_format.keep_with_next = True
        return p
    if R["name"]:
        para(R["name"], align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, pt=size * 1.95, font=head_font)
    if R["contact"]:
        para("  ·  ".join(R["contact"]), align=WD_ALIGN_PARAGRAPH.CENTER, before=3 * gap, pt=size * .88, color=grey, font=head_font)
    if R["headline"]:
        para(R["headline"], align=WD_ALIGN_PARAGRAPH.CENTER, before=6 * gap, pt=size * .94, color=accent, font=head_font)
    for key, title, body in R["sections"]:
        heading(title)
        if "p" in body:
            para(body["p"])
        for label, items in body.get("groups") or []:
            p = para(); run(p, label + ": ", bold=True); run(p, " · ".join(items))
        for ln in body.get("lines") or []:
            para(ln, after=1)
        for x in body.get("roles") or []:
            p = two(None, None)
            run(p, x["employer"], bold=True)
            if x["location"]:
                run(p, "\t" + x["location"], pt=size * .88, color=grey)
            p2 = two(None, None)
            run(p2, x["title"], italic=True)
            if x["ft"] and R["ft_mode"] == "paren":
                run(p2, f" ({x['ft']})", pt=size * .9, color=grey)
            if x["dates"]:
                run(p2, "\t" + x["dates"], pt=size * .88, color=grey)
            if x["ft"] and R["ft_mode"] == "line":
                para(x["ft"], pt=size * .9, color=grey).paragraph_format.keep_with_next = True
            for i, b in enumerate(x["bullets"]):
                bp = d.add_paragraph(b, style="List Bullet")
                bp.paragraph_format.space_before = Pt(1.5 * gap)
                bp.paragraph_format.space_after = Pt(7 * gap if i == len(x["bullets"]) - 1 else 0)
    d.save(path)

def docx_path(s):
    return os.path.join(OUT(), s + ".docx")

def make_docx(s):
    """Build tailored/<slug>.docx from its JSON with this profile's Resume settings: rebuilt when the resume, the
    settings or this code changed (so a download always matches the PDF). It also takes over what the PDF had to do
    to fit the page limit (which trimming step it stopped at), when a PDF could be made."""
    import hashlib, people
    src, out = os.path.join(OUT(), s + ".json"), docx_path(s)
    pr = people.prefs()
    rprefs = {k: v for k, v in pr.items() if k.startswith("resume.")}
    trim, fit = 0, 0
    try:
        make_pdf(s)
        d = json.load(open(pdf_path(s) + ".fit"))
        trim, fit = int(d.get("trim") or 0), int(d.get("fit") or 0)
    except Exception:
        pass      # no browser to make a PDF with: the Word file is simply untrimmed
    key = hashlib.sha256(json.dumps([rprefs, os.path.getmtime(src), frozen.code_mtime(__file__), trim, fit], sort_keys=True).encode()).hexdigest()[:16]
    keyfile = out + ".key"
    if os.path.exists(out) and os.path.exists(keyfile) and open(keyfile).read() == key:
        return out
    variants = list(_trims(json.load(open(src)), pr))
    tv, pv = variants[min(trim, len(variants) - 1)]
    write_docx(tv, out, pv, fit)
    open(keyfile, "w").write(key)
    return out

AREA_NAMES = {"appearance": "Appearance", "grammar": "Grammar", "density": "Density", "ats": "Screening software", "claims": "Claims"}

def astra_html(rv):
    """Sidebar block on the review page: Astra's rounds, area scores and the latest critique."""
    if not rv or not rv.get("rounds"):
        return ""
    e = html.escape
    last = rv["rounds"][-1]
    status = {"passed": "Passed", "below": f"Below {rv.get('threshold')}", "needs_answers": "Waiting on your answers",
              "error": "Review failed", "reworking": "Reworking"}.get(rv.get("status"), "")
    rounds = " → ".join(str(r["score"]) for r in rv["rounds"])
    kept = f" Kept round {rv['kept_round']} (highest score)." if rv.get("kept_round") and rv["kept_round"] != last["round"] else ""
    kept += (" " + rv["stopped"]) if rv.get("stopped") else ""
    areas = "".join(f"<li>{AREA_NAMES.get(k, k)}: <b>{v}</b></li>" for k, v in last.get("areas", {}).items())
    issues = "".join(f"<li><b>{e(AREA_NAMES.get(i['area'], i['area']))}</b> ({e(i['severity'])}): {e(i['problem'])}<br><i>{e(i['fix'])}</i></li>"
                     for i in last.get("issues", [])[:8])
    cov = f"<p>Posting keywords covered: {last['keyword_coverage']}%</p>" if last.get("keyword_coverage") is not None else ""
    LN = {"margins": "Margins", "font_size": "Font size", "line_spacing": "Line spacing", "section_spacing": "Section spacing",
          "titles": "Plain-English titles", "skills_style": "Skills", "headline": "Headline", "summary": "Summary", "section_order": "Section order"}
    lay = [(LN.get(k, k), v.replace("_", " ")) for k, v in (rv.get("_layout") or {}).items() if v and v != "default"]
    return (f'<section><h3>Astra review: {rv.get("final") or last["score"]}/100 · {e(status)}</h3>'
            f'<p>Rounds: {e(rounds)} (pass at {rv.get("threshold")}).{e(kept)}</p><p>{e(last.get("summary", ""))}</p>'
            f'<ul>{areas}</ul>{cov}'
            + (f'<p>Layout set by Claude: {e(", ".join(f"{k} {v}" for k, v in lay))}</p>' if lay else "")
            + f'<details><summary>Latest critique</summary><ul>{issues}</ul></details></section>')

def checks_html(c):
    """Sidebar block on the review page: what Siftwell's own fact check found (and what it corrected by itself)."""
    if not isinstance(c, dict) or not (c.get("warnings") or c.get("fixed")):
        return ""
    e = html.escape
    w = "".join(f"<li>{e(x.get('text', ''))}</li>" for x in c.get("warnings") or [])
    f = "".join(f"<li>{e(x)}</li>" for x in c.get("fixed") or [])
    return (('<section class="gaps"><h3>Check before you send</h3><p>Siftwell compared this resume with your own resume, profile and '
             f'answers. These lines have nothing behind them:</p><ul>{w}</ul></section>') if w else "") + \
           (f'<section><h3>Corrected automatically</h3><ul>{f}</ul></section>' if f else "")

def render_html(s):
    t = json.load(open(os.path.join(OUT(), s + ".json")))
    e = html.escape
    tag = {"kept": "Kept", "reworded": "Reworded", "surfaced": "Surfaced", "added_from_notes": "From your answers"}
    exp = ""
    for x in t["experience"]:
        bl = "".join(f'<li><span class="txt">{e(b["text"])}</span><span class="src"><b>{tag.get(b["change"], b["change"])}</b> · from: “{e(b["source"])}”'
                     + ('<b class="unv"> · source not found: check this line</b>' if b.get("unverified") else "") + '</span></li>' for b in x["bullets"])
        ft = f' ({e(x["functional_title"])})' if x.get("functional_title") else ""
        exp += f'<div class="role"><div><b>{e(x["employer"])}</b>{"  |  " + e(x["location"]) if x.get("location") else ""}</div><div><i>{e(x["title"])}{ft}</i>  |  {e(x["dates"])}</div><ul>{bl}</ul></div>'
    lst = lambda items: "".join(f"<li>{e(i)}</li>" for i in items) or "<li>None</li>"
    contact = "".join(f'<div class="{"name" if i == 0 else "ct"}">{e(c)}</div>' for i, c in enumerate(contact_of(t)))
    j = t["job"]
    import netsafe
    link = netsafe.clean_link(j.get("url"))  # (http/https only)
    posting = f'<a href="{e(link)}" target="_blank" rel="noopener">View posting ↗</a>' if link else ""
    import report        # the app's own dialog (appConfirm), the same one every page uses
    boot = json.dumps({"person": people.current() or "", "id": j.get("id") or "", "title": j.get("title") or ""}).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tailored: {e(j['title'])}</title>
<script>try{{var t=localStorage.getItem("jb.theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<style>
:root{{--bg:#f5f6f8;--paper:#fff;--surface:#fff;--ink:#152033;--muted:#5b6678;--line:#dde1e8;--accent:#23468f;--accent-soft:#e6ecf8;--warn:#9a5b00;--warn-soft:#fbf0dc;--bad:#a63232;--bad-soft:#f8e4e4}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f141c;--paper:#171e29;--surface:#171e29;--ink:#e4e9f1;--muted:#97a2b4;--line:#2a3342;--accent:#8fb0f0;--accent-soft:#1f2c45;--warn:#f0b25e;--warn-soft:#3a2b14;--bad:#ef8b8b;--bad-soft:#3d1c1c;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#0f141c;--paper:#171e29;--surface:#171e29;--ink:#e4e9f1;--muted:#97a2b4;--line:#2a3342;--accent:#8fb0f0;--accent-soft:#1f2c45;--warn:#f0b25e;--warn-soft:#3a2b14;--bad:#ef8b8b;--bad-soft:#3d1c1c;color-scheme:dark}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Public Sans",system-ui,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:20px 16px 48px;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:20px}}
.bar{{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}}
.bar h1{{font-size:20px;margin:2px 0 0}} .bar .acts a,.bar .acts button,.btn{{font:inherit;font-weight:600;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:8px;padding:0 12px;min-height:36px;display:inline-flex;align-items:center;text-decoration:none;cursor:pointer}}
.bar .primary,.btn.primary{{background:var(--accent);border-color:var(--accent);color:var(--paper)}} .btn.danger{{background:var(--bad-soft);border-color:var(--bad);color:var(--bad)}}
.bar .acts{{display:flex;gap:8px;flex-wrap:wrap}} .bar .acts button[aria-pressed="true"]{{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}} .bar .acts button:disabled{{opacity:.6;cursor:default}}
.back{{color:var(--accent);font-weight:600;text-decoration:none}} .back:hover{{text-decoration:underline}} .tmsg{{flex-basis:100%;margin:0;color:var(--muted);font-size:13px}} .tmsg:empty{{display:none}}
.paper{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:28px 32px;min-width:0}}
.name{{font-size:22px;font-weight:700;text-align:center}} .ct{{text-align:center;color:var(--muted);font-size:12.5px}}
.headline{{text-align:center;font-weight:600;margin:6px 0 4px}}
h2{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--line);padding-bottom:3px;margin:16px 0 6px}}
.role{{margin:8px 0}} ul{{margin:4px 0 0;padding-left:18px}} li{{margin:2px 0}}
.src{{display:block;font-size:11.5px;color:var(--muted)}} .src b{{color:var(--accent);font-weight:600}} .src b.unv{{color:var(--warn)}}
body.clean .src{{display:none}}
aside{{display:flex;flex-direction:column;gap:12px}} aside section{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:12px 14px}}
aside h3{{margin:0 0 6px;font-size:13px}} aside ul{{font-size:13px}} .gaps{{background:var(--warn-soft)!important;border-color:transparent!important}} .gaps h3{{color:var(--warn)}}
@media (max-width:860px){{.wrap{{grid-template-columns:1fr}}}}
@media print{{body{{background:#fff;color:#000}} .bar,aside{{display:none}} .wrap{{display:block;padding:0}} .paper{{border:0;padding:0}} .src{{display:none}}}}
</style></head><body>
<div class="wrap">
 <div class="bar"><div><a class="back" href="/#tailored">‹ Resumes</a><h1>{e(j['title'])} · {e(j['company'])}</h1></div>
  <div class="acts">
   <a class="primary" href="/tailored/{s}.pdf">Download PDF</a>
   <a href="/tailored/{s}.docx">Download Word</a>
   {posting}
   <button id="applied" type="button" aria-pressed="false" hidden>Mark applied</button>
   <button id="again" type="button">Tailor again</button>
   <button id="toggle" type="button">Hide sources</button>
  </div><p class="tmsg" id="tmsg" role="status"></p></div>
 <div class="paper">
  {contact}
  <div class="headline">{e(t.get('headline',''))}</div>
  <h2>Summary</h2><p>{e(t['summary'])}</p>
  {'<h2>Security Clearance</h2>' + ''.join(f'<div>{e(c)}</div>' for c in t['clearance']) if t.get('clearance') else ''}
  <h2>Professional Experience</h2>{exp}
  {'<h2>Skills</h2><p>' + e(' · '.join(t['skills'])) + '</p>' if t.get('skills') else ''}
  {'<h2>Education</h2>' + ''.join(f'<div>{e(x)}</div>' for x in t['education']) if t.get('education') else ''}
  {'<h2>Certifications</h2>' + ''.join(f'<div>{e(x)}</div>' for x in t['certifications']) if t.get('certifications') else ''}
  {'<h2>Additional</h2>' + ''.join(f'<div>{e(x)}</div>' for x in t['additional']) if t.get('additional') else ''}
 </div>
 <aside>
  {astra_html({**(t.get("review") or {}), "_layout": t.get("layout")} if t.get("review") else None)}
  {checks_html(t.get("checks"))}
  <section class="gaps"><h3>Real gaps for this job</h3><ul>{lst(t['gaps'])}</ul></section>
  <section><h3>Asked for, not claimed</h3><ul>{lst(t['unsupported_requests'])}</ul></section>
  <section><h3>Cut for this version</h3><ul>{lst(t['dropped'])}</ul></section>
  <section><h3>How to use this</h3><ul><li>Every bullet shows the resume line it came from. Check each one before you send.</li><li>Download PDF gives the finished, formatted resume (sources hidden). Use Word if you want to edit it first.</li><li>For a Google Doc, upload the Word file to Google Drive and open it with Google Docs.</li></ul></section>
 </aside>
</div>
{report.CONFIRM_SCRIPT}<script>(function(){{
var B = {boot}, $ = function(i){{ return document.getElementById(i); }}, H = {{"Content-Type": "application/json", "X-Jobboard": "1"}};
$("toggle").onclick = function(){{ var c = document.body.classList.toggle("clean"); this.textContent = c ? "Show sources" : "Hide sources"; }};
var say = function(t){{ $("tmsg").textContent = t; }};
// Mark applied: the same mark as on the board (Save / Applied / Not for me are kept per profile)
var q = B.person ? "?person=" + encodeURIComponent(B.person) : "", applied = false;
function show(){{ var b = $("applied"); b.hidden = false; b.setAttribute("aria-pressed", String(applied)); b.textContent = applied ? "\u2713 Applied" : "Mark applied"; }}
if (B.id) fetch("/api/marks" + q).then(function(r){{ return r.json(); }}).then(function(m){{ applied = (m || {{}})[B.id] === "applied"; show(); }}).catch(function(){{}});
$("applied").onclick = function(){{
  var next = !applied, b = this; b.disabled = true;
  fetch("/api/marks", {{method: "POST", headers: H, body: JSON.stringify({{person: B.person, id: B.id, status: next ? "applied" : ""}})}})
    .then(function(r){{ if (!r.ok) throw 0; applied = next; show(); say(next ? "Marked as applied. It is on your Applied tab." : ""); }})
    .catch(function(){{ say("Couldn\u2019t reach Siftwell, so that wasn\u2019t saved."); }}).then(function(){{ b.disabled = false; }});
}};
// Tailor again: Claude writes a new version for this job; the Resumes tab shows it working
$("again").onclick = function(){{
  var b = this;
  appConfirm({{title: "Tailor this resume again?", ok: "Tailor again", text: "Claude writes a new version for this job (about a minute; it uses your Claude plan). It replaces this one when it is done."}}).then(function(yes){{
    if (!yes) return;
    b.disabled = true; say("Starting\u2026");
    fetch("/api/tailor", {{method: "POST", headers: H, body: JSON.stringify({{person: B.person, id: B.id}})}})
      .then(function(r){{ return r.json().then(function(d){{ return {{ok: r.ok, d: d}}; }}); }})
      .then(function(x){{ if (!x.ok) {{ b.disabled = false; say(x.d.error || "Tailoring couldn\u2019t start."); return; }} location.href = "/#tailored"; }})
      .catch(function(){{ b.disabled = false; say("Couldn\u2019t reach Siftwell. Try again."); }});
  }});
}};
}})();</script>
</body></html>"""

# ------------------------------------------------------------------ PDF (print layout rendered by headless Chrome)
CHROME = osdeps.chrome_path()  # Chrome, or Edge on Windows

def _contact_bits(contact):
    """Name + one tidy contact line from the resume's header lines (drops stray separators)."""
    if not contact:
        return "", []
    bits = []
    for line in contact[1:]:
        bits += [b.strip() for b in re.split(r"\s*[|•·]\s*", line) if b.strip()]
    bits = [re.sub(r"^https?://(www\.)?", "", b).rstrip("/") for b in bits]
    return contact[0], bits

STYLES = {
    # body font, heading font, accent
    "classic": ('Charter, "Bitstream Charter", Cambria, Georgia, serif', '"Avenir Next", Avenir, "Segoe UI", "Helvetica Neue", Arial, sans-serif', "#1f3a6e"),
    "modern": ('"Avenir Next", Avenir, "Segoe UI", "Helvetica Neue", Arial, sans-serif', '"Avenir Next", Avenir, "Segoe UI", "Helvetica Neue", Arial, sans-serif', "#1d4f91"),
    "compact": ('"Helvetica Neue", Helvetica, Calibri, Arial, sans-serif', '"Helvetica Neue", Helvetica, Calibri, Arial, sans-serif', "#222222"),
}

def _keep_contact(bit, pr):
    b = bit.lower()
    if "@" in b:
        return pr["resume.contact_email"]
    if "linkedin" in b:
        return pr["resume.contact_linkedin"]
    if re.search(r"\d{3}\D{0,2}\d{3}\D?\d{4}", b):
        return pr["resume.contact_phone"]
    return pr["resume.contact_location"]

WORD_FONTS = {"classic": ("Cambria", "Calibri"), "modern": ("Calibri", "Calibri"), "compact": ("Arial", "Arial")}

def resolve(t, pr=None, fit=0):
    """What is on this resume and how it is laid out: the one answer both the PDF (render_print) and the Word file
    (write_docx) are drawn from. It applies this profile's Resume settings (which contact details, summary, skills,
    additional, clearance, plain-English titles, section order, style, density, paper) and Claude's per-resume layout
    (t["layout"], set during a review rework). fit = tightening step (0-4) used to meet the page limit.
    Returns {"name", "contact": [...], "headline", "sections": [(key, title, body)], ...layout numbers}, where body is
    {"p": text} / {"lines": [...]} / {"groups": [(label, items)]} / {"roles": [...]}; empty sections are left out."""
    import people
    pr = pr or {k: d for k, (d, _) in people.PREF_SCHEMA.items()}
    name, bits = _contact_bits(contact_of(t))
    bits = [b for b in bits if _keep_contact(b, pr)]
    body_font, head_font, accent = STYLES.get(pr["resume.style"], STYLES["classic"])
    L = {k: v for k, v in (t.get("layout") or {}).items() if v and v != "default"}  # Claude's per-resume overrides
    dense = pr["resume.density"] == "compact" or pr["resume.style"] == "compact"
    size = (float(L["font_size"]) if "font_size" in L else (9.6 if dense else 10.2)) - 0.35 * fit
    lh = {"tight": 1.25, "normal": 1.36, "airy": 1.45}.get(L.get("line_spacing"), 1.28 if dense else 1.36) - 0.02 * fit
    gap = max(0.4, {"tight": 0.75, "normal": 1.0, "airy": 1.25}.get(L.get("section_spacing"), 0.75 if dense else 1.0) - 0.15 * fit)
    mv, mh = {"narrow": (0.45, 0.5), "normal": (0.55, 0.6), "wide": (0.7, 0.75)}.get(L.get("margins"), (0.45, 0.5) if dense else (0.55, 0.6))
    ft_mode = L.get("titles", pr["resume.functional_titles"])
    roles = [{"employer": x.get("employer") or "", "location": x.get("location") or "", "title": x.get("title") or "",
              "dates": x.get("dates") or "", "ft": (x.get("functional_title") or "") if ft_mode != "hide" else "",
              "bullets": [b["text"] for b in x.get("bullets") or []]} for x in t.get("experience") or []]
    clear = t.get("clearance") or []
    if pr["resume.clearance"] == "hide":
        clear = []
    elif pr["resume.clearance"] == "active":
        clear = [c for c in clear if not re.search(r"previously|not current|formerly|expired|inactive", c, re.I)]
    show_summary = {"on": True, "off": False}.get(L.get("summary"), pr["resume.summary"])
    groups = [(g["label"], g["items"]) for g in (t.get("skill_groups") or []) if g.get("items")]
    if not pr["resume.skills"]:
        skills = {}
    elif L.get("skills_style") == "grouped" and groups:
        skills = {"groups": groups}
    else:
        skills = {"p": " · ".join(t["skills"])} if t.get("skills") else {}
    lines = lambda items: {"lines": [i for i in items or [] if i]} if items else {}
    blocks = {
        "summary": ("Summary", {"p": t["summary"]} if t.get("summary") and show_summary else {}),
        "clearance": ("Security Clearance", lines(clear)),
        "experience": ("Professional Experience", {"roles": roles} if roles else {}),
        "skills": ("Skills", skills),
        "education": ("Education", lines(t.get("education"))),
        "certifications": ("Certifications", lines(t.get("certifications"))),     # the profile's own list (fact_check)
        "additional": ("Additional", lines(t.get("additional")) if pr["resume.additional"] else {}),
    }
    order = {"experience_first": ["summary", "experience", "skills", "clearance", "education", "certifications", "additional"],
             "skills_before_experience": ["summary", "clearance", "skills", "experience", "education", "certifications", "additional"],
             "education_first": ["summary", "education", "certifications", "clearance", "experience", "skills", "additional"]}.get(
        L.get("section_order"),
        ["summary", "education", "certifications", "clearance", "experience", "skills", "additional"] if pr["resume.education_first"]
        else ["summary", "clearance", "experience", "skills", "education", "certifications", "additional"])
    headline = {"short": t.get("headline_short") or t.get("headline"), "none": ""}.get(L.get("headline"), t.get("headline"))
    return {"name": name, "contact": bits, "headline": headline or "", "ft_mode": ft_mode,
            "sections": [(k, blocks[k][0], blocks[k][1]) for k in order if blocks[k][1]],
            "fonts": (body_font, head_font), "word_fonts": WORD_FONTS.get(pr["resume.style"], WORD_FONTS["classic"]), "accent": accent,
            "size": size, "lh": lh, "gap": gap, "margin_v": mv - 0.04 * fit, "margin_h": mh - 0.04 * fit,
            "paper": "A4" if pr["resume.paper"] == "a4" else "Letter"}

def render_print(t, pr=None, fit=0):
    """Single-column, ATS-friendly resume page: real text, standard headings. pr = preferences; fit = tightening step (0-4).
    Everything on it comes from resolve(), the same as the Word file."""
    e = html.escape
    R = resolve(t, pr, fit)
    name, bits, headline, ft_mode = R["name"], R["contact"], R["headline"], R["ft_mode"]
    (body_font, head_font), accent = R["fonts"], R["accent"]
    size, lh, gap, margin_v, margin_h, paper = R["size"], R["lh"], R["gap"], R["margin_v"], R["margin_h"], R["paper"]
    def role(x):
        ftxt = x["ft"]
        ft_inline = f' <span class="ft">({e(ftxt)})</span>' if ftxt and ft_mode == "paren" else ""
        ft_line = f'<div class="ftl">{e(ftxt)}</div>' if ftxt and ft_mode == "line" else ""
        bl = "".join(f"<li>{e(b)}</li>" for b in x["bullets"])
        return (f'<section class="role"><div class="rh"><span class="emp">{e(x["employer"])}</span>'
                f'<span class="loc">{e(x["location"])}</span></div>'
                f'<div class="rh"><span class="ttl">{e(x["title"])}{ft_inline}</span><span class="dt">{e(x["dates"])}</span></div>'
                f'{ft_line}<ul>{bl}</ul></section>')
    def body_html(body):
        if "roles" in body:
            return "".join(role(x) for x in body["roles"])
        if "groups" in body:
            return "".join(f'<div class="ln"><b>{e(label)}:</b> {e(" · ".join(items))}</div>' for label, items in body["groups"])
        if "lines" in body:
            return "".join(f'<div class="ln">{e(i)}</div>' for i in body["lines"])
        return f"<p>{e(body['p'])}</p>"
    # Each section is one block: its heading never sits alone at a page bottom, and short sections stay whole.
    parts = [f'<section class="blk{" keep" if key != "experience" else ""}"><h2>{title}</h2>{body_html(body)}</section>'
             for key, title, body in R["sections"]]
    g = lambda pt: f"{pt * gap:.1f}pt"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(name)} Resume</title>
<style>
@page {{ size: {paper}; margin: {margin_v:.2f}in {margin_h:.2f}in; }}
* {{ box-sizing: border-box; }}
html, body {{ background: #ffffff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
body {{ margin: 0; color: #1b1f24; font: {size:.2f}pt/{lh:.2f} {body_font}; }}
.name {{ font: 600 {size * 1.95:.1f}pt/1.1 {head_font}; letter-spacing: .01em; text-align: center; }}
.contact {{ text-align: center; font: {size * .88:.1f}pt/1.4 {head_font}; color: #4a525c; margin-top: {g(3)}; }}
.contact span + span::before {{ content: "·"; margin: 0 6pt; color: #9aa1aa; }}
.headline {{ text-align: center; font: 500 {size * .94:.1f}pt/1.35 {head_font}; color: {accent}; margin: {g(6)} auto 0; max-width: 6.6in; }}
h2 {{ font: 600 {size * .84:.1f}pt/1 {head_font}; letter-spacing: .12em; text-transform: uppercase; color: {accent};
      border-bottom: .75pt solid #c9ced6; padding-bottom: 3pt; margin: {g(12)} 0 {g(5)}; }}
p {{ margin: 0; }}
h2 {{ break-after: avoid; page-break-after: avoid; }}
.blk.keep {{ break-inside: avoid; page-break-inside: avoid; }}
p, li, .ln, .headline {{ text-wrap: pretty; orphans: 3; widows: 3; }}
.role .rh:first-child {{ break-after: avoid; }}
.role {{ margin: 0 0 {g(7)}; break-inside: avoid; }}
.rh {{ display: flex; justify-content: space-between; gap: 12pt; align-items: baseline; }}
.emp {{ font-weight: 700; }}
.loc, .dt {{ font-size: {size * .88:.1f}pt; color: #4a525c; white-space: nowrap; }}
.ttl {{ font-style: italic; }}
.ft, .ftl {{ font-style: normal; color: #4a525c; font-size: {size * .9:.1f}pt; }}
ul {{ margin: {g(2)} 0 0; padding-left: 13pt; }}
li {{ margin: {g(1.5)} 0; padding-left: 2pt; }}
li::marker {{ color: #8a929c; }}
.ln {{ margin: 1pt 0; }}
</style></head><body>
<div class="name">{e(name)}</div>
<div class="contact">{"".join(f"<span>{e(b)}</span>" for b in bits)}</div>
{f'<div class="headline">{e(headline)}</div>' if headline else ""}
{"".join(parts)}
</body></html>"""

def _pages(path):
    try:
        return len(re.findall(rb"/Type\s*/Page[^s]", open(path, "rb").read()))
    except Exception:
        return 0

def pdf_path(s):
    return os.path.join(OUT(), s + ".pdf")

def _chrome_pdf(page_html, out):
    """Print one HTML page to PDF with headless Chrome. Chrome sometimes writes the file and never exits, so watch the file."""
    import subprocess, tempfile, time
    tmp = out + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "resume.html")
        open(page, "w").write(page_html)
        p = osdeps.popen_hidden([CHROME, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                              "--use-mock-keychain", "--password-store=basic", f"--user-data-dir={os.path.join(d, 'profile')}",
                              "--no-pdf-header-footer", f"--print-to-pdf={tmp}", osdeps.file_url(page)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        last, stable, deadline = -1, 0, time.time() + 60
        while time.time() < deadline:
            time.sleep(0.4)
            size = os.path.getsize(tmp) if os.path.exists(tmp) else -1
            if size > 1000 and size == last:
                stable += 1
                if stable >= 2 or p.poll() is not None:
                    break
            else:
                stable = 0
            last = size
            if p.poll() is not None and size <= 0:
                break
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
    if not (os.path.exists(tmp) and os.path.getsize(tmp) > 1000):
        raise RuntimeError("PDF build failed (Chrome produced no file).")
    os.replace(tmp, out)

def make_pdf(s):
    """Build data/.../tailored/<slug>.pdf from its JSON using this profile's resume settings (cached per settings)."""
    import hashlib, people
    src = os.path.join(OUT(), s + ".json")
    out = pdf_path(s)
    pr = people.prefs()
    rprefs = {k: v for k, v in pr.items() if k.startswith("resume.")}
    key = hashlib.sha256(json.dumps([rprefs, os.path.getmtime(src), frozen.code_mtime(__file__)], sort_keys=True).encode()).hexdigest()[:16]
    keyfile = out + ".key"
    if os.path.exists(out) and os.path.exists(keyfile) and open(keyfile).read() == key:
        return out
    if not CHROME or not os.path.exists(CHROME):
        raise RuntimeError("No Chrome or Edge browser found, so a PDF can't be built (Word download still works).")
    t = json.load(open(src))
    target = {"1": 1, "2": 2}.get(pr["resume.length"])
    # Stage 1: tighten type and spacing. Stage 2 (only if still too long): trim lowest-value content in a fixed order.
    done, used = False, (0, 0)
    for n, (tv, pv) in enumerate(_trims(t, pr)):
        for fit in (range(0, 5) if n == 0 else (4,)):
            _chrome_pdf(render_print(tv, pv, fit), out)
            used = (n, fit)
            if not target or _pages(out) <= target:
                done = True
                break
        if done:
            break
    open(keyfile, "w").write(key)
    json.dump({"trim": used[0], "fit": used[1]}, open(out + ".fit", "w"))   # (the Word file follows the same steps: make_docx)
    return out

def _trims(t0, pr):
    """The versions tried, in order, to meet the page limit: as written, then without Additional, then older roles cut
    to 2 bullets, the newest to 4, skills to 10. (settings, content) pairs; the PDF and the Word file use the same one."""
    import copy
    yield t0, pr
    t1 = copy.deepcopy(t0); p1 = {**pr, "resume.additional": False}; yield t1, p1
    t2 = copy.deepcopy(t1)
    for x in t2.get("experience", [])[1:]:
        x["bullets"] = x["bullets"][:2]
    yield t2, p1
    t3 = copy.deepcopy(t2)
    if t3.get("experience"):
        t3["experience"][0]["bullets"] = t3["experience"][0]["bullets"][:4]
    yield t3, p1
    t4 = copy.deepcopy(t3); t4["skills"] = (t4.get("skills") or [])[:10]; yield t4, p1

def pdf_filename(s):
    t = json.load(open(os.path.join(OUT(), s + ".json")))
    name = (contact_of(t) or ["Resume"])[0]
    co = re.sub(r"[^\w .&-]", "", (t.get("job") or {}).get("company", "")).strip()
    return re.sub(r"\s+", " ", f"{name} - Resume - {co}".strip(" -")) + ".pdf"
