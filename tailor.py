"""Tailor the active resume to one job: Claude rewrites within the facts, every bullet cites its source line.
Writes DATA/people/<id>/tailored/<slug>.json and .docx; server renders an HTML view (printable to PDF)."""
import datetime as dt, html, json, os, re
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
    prompt = (f"JOB POSTING\nTitle: {job['title']}\nCompany: {job['company']}\n\n{description[:12000]}\n\n"
              f"ORIGINAL RESUME (the only source of facts besides confirmed answers)\n{rtext}\n\n"
              f"CANDIDATE PROFILE\n{resume.profile_text(prof)}\n\n"
              f"CURRENT TAILORED RESUME (JSON)\n{json.dumps({k: current.get(k) for k in SCHEMA['properties']}, indent=1)[:30000]}\n\n"
              f"REVIEWER GRADE: {review.get('score')}/100. Summary: {review.get('summary', '')}\n"
              f"Missing posting keywords: {', '.join(review.get('missing_keywords', [])[:20])}\nISSUES\n{issues}")
    out = claude_cli.run_json(SYSTEM + "\n\n" + REVISE + "\n\n" + preference_rules(), prompt, SCHEMA, effort="medium", timeout=900)
    for k in ("job", "contact", "created"):
        out[k] = current.get(k)
    return out

def save_tailored(s, t):
    json.dump(t, open(os.path.join(OUT(), s + ".json"), "w"), indent=1)
    write_docx(t, os.path.join(OUT(), s + ".docx"))

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

def contact_header(resume_text):
    """Name/contact lines as written at the top of the resume (kept verbatim, never sent anywhere but Claude)."""
    lines = [l.strip() for l in resume_text.splitlines() if l.strip()]
    head = []
    for l in lines[:6]:
        if re.fullmatch(r"[A-Z][A-Z &/]{3,}", l) or l.upper() in ("EDUCATION", "EXPERIENCE", "SUMMARY", "PROFESSIONAL EXPERIENCE"):
            break
        head.append(l)
    return head[:4]

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
    out["contact"] = contact_header(rtext)
    out["created"] = dt.datetime.now().isoformat(timespec="minutes")
    os.makedirs(OUT(), exist_ok=True)
    s = slug(job["id"])
    json.dump(out, open(os.path.join(OUT(), s + ".json"), "w"), indent=1)
    write_docx(out, os.path.join(OUT(), s + ".docx"))
    return s

def write_docx(t, path):
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    d = Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Inches(0.7)
        s.top_margin = s.bottom_margin = Inches(0.6)
    st = d.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
    def para(text, bold=False, size=None, align=None, space_after=2):
        p = d.add_paragraph(); r = p.add_run(text); r.bold = bold
        if size: r.font.size = Pt(size)
        if align: p.alignment = align
        p.paragraph_format.space_after = Pt(space_after)
        return p
    def heading(text):
        p = para(text.upper(), bold=True, size=11, space_after=1)
        p.paragraph_format.space_before = Pt(8)
    contact = t.get("contact") or []
    if contact:
        para(contact[0], bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
        for c in contact[1:]:
            para(c, size=9.5, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
    if t.get("headline"):
        para(t["headline"], bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    heading("Summary"); para(t["summary"])
    if t.get("clearance"):
        heading("Security Clearance")
        for c in t["clearance"]: para(c, space_after=0)
    heading("Professional Experience")
    for e in t["experience"]:
        p = d.add_paragraph(); p.paragraph_format.space_before = Pt(5); p.paragraph_format.space_after = Pt(0)
        p.add_run(e["employer"]).bold = True
        if e.get("location"): p.add_run(f"  |  {e['location']}")
        p2 = d.add_paragraph(); p2.paragraph_format.space_after = Pt(1)
        r = p2.add_run(e["title"]); r.italic = True
        if e.get("functional_title"): p2.add_run(f" ({e['functional_title']})").italic = True
        p2.add_run(f"  |  {e['dates']}")
        for b in e["bullets"]:
            bp = d.add_paragraph(b["text"], style="List Bullet"); bp.paragraph_format.space_after = Pt(0)
    if t.get("skills"):
        heading("Skills"); para(" · ".join(t["skills"]))
    if t.get("education"):
        heading("Education")
        for x in t["education"]: para(x, space_after=0)
    if t.get("additional"):
        heading("Additional")
        for x in t["additional"]: para(x, space_after=0)
    d.save(path)

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

def render_html(s):
    t = json.load(open(os.path.join(OUT(), s + ".json")))
    e = html.escape
    tag = {"kept": "Kept", "reworded": "Reworded", "surfaced": "Surfaced", "added_from_notes": "From your answers"}
    exp = ""
    for x in t["experience"]:
        bl = "".join(f'<li><span class="txt">{e(b["text"])}</span><span class="src"><b>{tag.get(b["change"], b["change"])}</b> · from: “{e(b["source"])}”</span></li>' for b in x["bullets"])
        ft = f' ({e(x["functional_title"])})' if x.get("functional_title") else ""
        exp += f'<div class="role"><div><b>{e(x["employer"])}</b>{"  |  " + e(x["location"]) if x.get("location") else ""}</div><div><i>{e(x["title"])}{ft}</i>  |  {e(x["dates"])}</div><ul>{bl}</ul></div>'
    lst = lambda items: "".join(f"<li>{e(i)}</li>" for i in items) or "<li>None</li>"
    contact = "".join(f'<div class="{"name" if i == 0 else "ct"}">{e(c)}</div>' for i, c in enumerate(t.get("contact", [])))
    j = t["job"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tailored: {e(j['title'])}</title>
<style>
:root{{--bg:#f5f6f8;--paper:#fff;--ink:#152033;--muted:#5b6678;--line:#dde1e8;--accent:#23468f;--warn:#9a5b00;--warn-soft:#fbf0dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f141c;--paper:#171e29;--ink:#e4e9f1;--muted:#97a2b4;--line:#2a3342;--accent:#8fb0f0;--warn:#f0b25e;--warn-soft:#3a2b14;color-scheme:dark}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Public Sans",system-ui,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:20px 16px 48px;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:20px}}
.bar{{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}}
.bar h1{{font-size:18px;margin:0}} .bar a,.bar button{{font:inherit;font-weight:600;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:6px;padding:7px 12px;text-decoration:none;cursor:pointer}}
.bar .primary{{background:var(--accent);border-color:var(--accent);color:var(--paper)}}
.paper{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:28px 32px;min-width:0}}
.name{{font-size:22px;font-weight:700;text-align:center}} .ct{{text-align:center;color:var(--muted);font-size:12.5px}}
.headline{{text-align:center;font-weight:600;margin:6px 0 4px}}
h2{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--line);padding-bottom:3px;margin:16px 0 6px}}
.role{{margin:8px 0}} ul{{margin:4px 0 0;padding-left:18px}} li{{margin:2px 0}}
.src{{display:block;font-size:11.5px;color:var(--muted)}} .src b{{color:var(--accent);font-weight:600}}
body.clean .src{{display:none}}
aside{{display:flex;flex-direction:column;gap:12px}} aside section{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:12px 14px}}
aside h3{{margin:0 0 6px;font-size:13px}} aside ul{{font-size:13px}} .gaps{{background:var(--warn-soft)!important;border-color:transparent!important}} .gaps h3{{color:var(--warn)}}
@media (max-width:860px){{.wrap{{grid-template-columns:1fr}}}}
@media print{{body{{background:#fff;color:#000}} .bar,aside{{display:none}} .wrap{{display:block;padding:0}} .paper{{border:0;padding:0}} .src{{display:none}}}}
</style></head><body>
<div class="wrap">
 <div class="bar"><h1>{e(j['title'])} · {e(j['company'])}</h1>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
   <button id="toggle" type="button">Hide sources</button>
   <a class="primary" href="/tailored/{s}.pdf">Download PDF</a>
   <a href="/tailored/{s}.docx">Download Word</a>
   <a href="{e(j.get('url') or '#')}" target="_blank" rel="noopener">Open posting</a>
  </div></div>
 <div class="paper">
  {contact}
  <div class="headline">{e(t.get('headline',''))}</div>
  <h2>Summary</h2><p>{e(t['summary'])}</p>
  {'<h2>Security Clearance</h2>' + ''.join(f'<div>{e(c)}</div>' for c in t['clearance']) if t.get('clearance') else ''}
  <h2>Professional Experience</h2>{exp}
  {'<h2>Skills</h2><p>' + e(' · '.join(t['skills'])) + '</p>' if t.get('skills') else ''}
  {'<h2>Education</h2>' + ''.join(f'<div>{e(x)}</div>' for x in t['education']) if t.get('education') else ''}
  {'<h2>Additional</h2>' + ''.join(f'<div>{e(x)}</div>' for x in t['additional']) if t.get('additional') else ''}
 </div>
 <aside>
  {astra_html({**(t.get("review") or {}), "_layout": t.get("layout")} if t.get("review") else None)}
  <section class="gaps"><h3>Real gaps for this job</h3><ul>{lst(t['gaps'])}</ul></section>
  <section><h3>Asked for, not claimed</h3><ul>{lst(t['unsupported_requests'])}</ul></section>
  <section><h3>Cut for this version</h3><ul>{lst(t['dropped'])}</ul></section>
  <section><h3>How to use this</h3><ul><li>Every bullet shows the resume line it came from. Check each one before you send.</li><li>Download PDF gives the finished, formatted resume (sources hidden). Use Word if you want to edit it first.</li><li>For a Google Doc, upload the Word file to Google Drive and open it with Google Docs.</li></ul></section>
 </aside>
</div>
<script>document.getElementById("toggle").onclick=function(){{var c=document.body.classList.toggle("clean");this.textContent=c?"Show sources":"Hide sources";}};</script>
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

def render_print(t, pr=None, fit=0):
    """Single-column, ATS-friendly resume page: real text, standard headings. pr = preferences; fit = tightening step (0-4)."""
    import people
    pr = pr or {k: d for k, (d, _) in people.PREF_SCHEMA.items()}
    e = html.escape
    name, bits = _contact_bits(t.get("contact") or [])
    bits = [b for b in bits if _keep_contact(b, pr)]
    body_font, head_font, accent = STYLES.get(pr["resume.style"], STYLES["classic"])
    L = {k: v for k, v in (t.get("layout") or {}).items() if v and v != "default"}  # Claude's per-resume overrides
    dense = pr["resume.density"] == "compact" or pr["resume.style"] == "compact"
    size = (float(L["font_size"]) if "font_size" in L else (9.6 if dense else 10.2)) - 0.35 * fit
    lh = {"tight": 1.25, "normal": 1.36, "airy": 1.45}.get(L.get("line_spacing"), 1.28 if dense else 1.36) - 0.02 * fit
    gap = max(0.4, {"tight": 0.75, "normal": 1.0, "airy": 1.25}.get(L.get("section_spacing"), 0.75 if dense else 1.0) - 0.15 * fit)
    mv, mh = {"narrow": (0.45, 0.5), "normal": (0.55, 0.6), "wide": (0.7, 0.75)}.get(L.get("margins"), (0.45, 0.5) if dense else (0.55, 0.6))
    margin_v, margin_h = mv - 0.04 * fit, mh - 0.04 * fit
    paper = "A4" if pr["resume.paper"] == "a4" else "Letter"
    ft_mode = L.get("titles", pr["resume.functional_titles"])
    def role(x):
        ftxt = x.get("functional_title") if ft_mode != "hide" else ""
        ft_inline = f' <span class="ft">({e(ftxt)})</span>' if ftxt and ft_mode == "paren" else ""
        ft_line = f'<div class="ftl">{e(ftxt)}</div>' if ftxt and ft_mode == "line" else ""
        bl = "".join(f"<li>{e(b['text'])}</li>" for b in x["bullets"])
        return (f'<section class="role"><div class="rh"><span class="emp">{e(x["employer"])}</span>'
                f'<span class="loc">{e(x.get("location") or "")}</span></div>'
                f'<div class="rh"><span class="ttl">{e(x["title"])}{ft_inline}</span><span class="dt">{e(x["dates"])}</span></div>'
                f'{ft_line}<ul>{bl}</ul></section>')
    # Each section is one block: its heading never sits alone at a page bottom, and short sections stay whole.
    sec = lambda title, body: f'<section class="blk{" keep" if title != "Professional Experience" else ""}"><h2>{title}</h2>{body}</section>' if body else ""
    lines = lambda items: "".join(f'<div class="ln">{e(i)}</div>' for i in items or [])
    clear = t.get("clearance") or []
    if pr["resume.clearance"] == "hide":
        clear = []
    elif pr["resume.clearance"] == "active":
        clear = [c for c in clear if not re.search(r"previously|not current|formerly|expired|inactive", c, re.I)]
    show_summary = {"on": True, "off": False}.get(L.get("summary"), pr["resume.summary"])
    groups = [g for g in (t.get("skill_groups") or []) if g.get("items")]
    if L.get("skills_style") == "grouped" and groups:
        skills_html = "".join(f'<div class="ln"><b>{e(g["label"])}:</b> {e(" · ".join(g["items"]))}</div>' for g in groups)
    else:
        skills_html = f'<p>{e(" · ".join(t["skills"]))}</p>' if t.get("skills") else ""
    blocks = {
        "summary": sec("Summary", f"<p>{e(t['summary'])}</p>" if t.get("summary") and show_summary else ""),
        "clearance": sec("Security Clearance", lines(clear)),
        "experience": sec("Professional Experience", "".join(role(x) for x in t.get("experience", []))),
        "skills": sec("Skills", skills_html if pr["resume.skills"] else ""),
        "education": sec("Education", lines(t.get("education"))),
        "additional": sec("Additional", lines(t.get("additional")) if pr["resume.additional"] else ""),
    }
    order = {"experience_first": ["summary", "experience", "skills", "clearance", "education", "additional"],
             "skills_before_experience": ["summary", "clearance", "skills", "experience", "education", "additional"],
             "education_first": ["summary", "education", "clearance", "experience", "skills", "additional"]}.get(
        L.get("section_order"),
        ["summary", "education", "clearance", "experience", "skills", "additional"] if pr["resume.education_first"]
        else ["summary", "clearance", "experience", "skills", "education", "additional"])
    parts = [blocks[k] for k in order]
    headline = {"short": t.get("headline_short") or t.get("headline"), "none": ""}.get(L.get("headline"), t.get("headline"))
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
        p = subprocess.Popen([CHROME, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
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
    key = hashlib.sha256(json.dumps([rprefs, os.path.getmtime(src), os.path.getmtime(__file__)], sort_keys=True).encode()).hexdigest()[:16]
    keyfile = out + ".key"
    if os.path.exists(out) and os.path.exists(keyfile) and open(keyfile).read() == key:
        return out
    if not CHROME or not os.path.exists(CHROME):
        raise RuntimeError("No Chrome or Edge browser found, so a PDF can't be built (Word download still works).")
    import copy
    t = json.load(open(src))
    target = {"1": 1, "2": 2}.get(pr["resume.length"])
    # Stage 1: tighten type and spacing. Stage 2 (only if still too long): trim lowest-value content in a fixed order.
    def trims(t0):
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
    done = False
    for tv, pv in trims(t):
        for fit in (range(0, 5) if tv is t else (4,)):
            _chrome_pdf(render_print(tv, pv, fit), out)
            if not target or _pages(out) <= target:
                done = True
                break
        if done:
            break
    open(keyfile, "w").write(key)
    return out

def pdf_filename(s):
    t = json.load(open(os.path.join(OUT(), s + ".json")))
    name = (t.get("contact") or ["Resume"])[0]
    co = re.sub(r"[^\w .&-]", "", (t.get("job") or {}).get("company", "")).strip()
    return re.sub(r"\s+", " ", f"{name} - Resume - {co}".strip(" -")) + ".pdf"
