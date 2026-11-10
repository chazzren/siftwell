"""Adversarial review of a tailored resume.

Two parts:
- mechanical checks the tool runs itself (page count, bullet length, date formats, pronouns, keyword coverage);
- a grade from OpenAI's GPT-6 Astra through the Codex app, signed in with the user's ChatGPT plan. Astra sees the
  rendered PDF pages plus the text, and grades appearance, grammar, density, screening-software (ATS) fit and claims.
  It may ask for facts the resume lacks; those go to the candidate as questions, never straight into the resume."""
import json, os, re, shutil, subprocess, tempfile
import osdeps

import paths
WORK = paths.data("codex_work")  # empty working folder for Codex (read-only sandbox)
MODEL = "gpt-6-astra"
WEIGHTS = {"appearance": 20, "grammar": 20, "density": 15, "ats": 30, "claims": 15}

def codex_path():
    # The Codex desktop app on Windows keeps its CLI here, and it isn't always on the PATH Siftwell starts with.
    local = os.environ.get("LOCALAPPDATA", "")
    extra = [os.path.join(local, "Programs", "OpenAI", "Codex", "bin", "codex.exe")] if osdeps.WINDOWS and local else []
    return osdeps.find_exe("codex", extra)

def codex_ready():
    p = codex_path()
    if not p:
        return False, "Couldn't find the Codex app on this computer, so Astra couldn't review it. Install Codex and sign in with ChatGPT, or turn Astra off in Settings."
    try:
        r = osdeps.run_hidden([*osdeps.cmd(p), "login", "status"], capture_output=True, text=True, timeout=30)
        if "Logged in" in (r.stdout + r.stderr):
            return True, ""
    except Exception:
        pass
    return False, "Codex isn't signed in. Open the Codex app (or run `codex login` in a terminal) and sign in with ChatGPT."

# ------------------------------------------------------------------ mechanical checks
STOP = set("""a an and are as at be by for from has have in into is it of on or our that the their this to was we with will you your
we're who what when where which while within without able across also any can etc including such more most other per role team
work working experience years year strong ability skills preferred required plus using use""".split())

def resume_text(t):
    parts = [t.get("headline", ""), t.get("summary", "")]
    for x in t.get("experience", []):
        parts += [x.get("title", ""), x.get("functional_title", "")] + [b["text"] for b in x.get("bullets", [])]
    parts += t.get("skills", []) + t.get("education", []) + t.get("clearance", []) + t.get("additional", [])
    return "\n".join(p for p in parts if p)

def key_phrases(desc, n=30):
    """Frequent 1-3 word phrases from the posting (rough keyword list for coverage)."""
    words = re.findall(r"[a-zA-Z][a-zA-Z+/#.-]{1,}", desc.lower())
    counts = {}
    for size in (1, 2, 3):
        for i in range(len(words) - size + 1):
            g = words[i:i + size]
            if g[0] in STOP or g[-1] in STOP or any(len(w) < 3 for w in g):
                continue
            k = " ".join(g)
            counts[k] = counts.get(k, 0) + (1 if size == 1 else 2)
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    out = []
    for k, c in ranked:
        if c < 3:
            break
        if not any(k in o or o in k for o in out):
            out.append(k)
        if len(out) >= n:
            break
    return out

def mechanical(t, pdf_pages, target_pages, desc):
    issues, score = [], 100
    if target_pages and pdf_pages > target_pages:
        issues.append({"area": "density", "severity": "high", "where": "whole resume", "problem": f"{pdf_pages} pages; the setting asks for {target_pages}.", "fix": "Cut lower-value bullets."})
        score -= 15
    bullets = [b["text"] for x in t.get("experience", []) for b in x.get("bullets", [])]
    long_b = [b for b in bullets if len(b.split()) > 32]
    if long_b:
        issues.append({"area": "density", "severity": "medium", "where": long_b[0][:80], "problem": f"{len(long_b)} bullet(s) over 32 words.", "fix": "Split or tighten to one line or two."})
        score -= min(10, 3 * len(long_b))
    if any(re.search(r"\b(I|my|me|we|our)\b", b) for b in bullets):
        issues.append({"area": "grammar", "severity": "medium", "where": "bullets", "problem": "First-person pronouns in bullets.", "fix": "Start bullets with a verb; drop pronouns."})
        score -= 5
    dates = " ".join(x.get("dates", "") for x in t.get("experience", []))
    styles = {"Mon YYYY": bool(re.search(r"\b[A-Z][a-z]{2} \d{4}", dates)), "MM/YYYY": bool(re.search(r"\b\d{1,2}/\d{4}", dates)),
              "Month YYYY": bool(re.search(r"\b(January|February|March|April|June|July|August|September|October|November|December) \d{4}", dates))}
    if sum(styles.values()) > 1:
        issues.append({"area": "grammar", "severity": "low", "where": "dates", "problem": "Mixed date formats.", "fix": "Use one format, e.g. Mar 2023."})
        score -= 4
    starts = [b.split()[0].lower() for b in bullets if b.split()]
    rep = [w for w in set(starts) if starts.count(w) >= 3]
    if rep:
        issues.append({"area": "grammar", "severity": "low", "where": "bullets", "problem": f"Repeated opening verb(s): {', '.join(rep)}.", "fix": "Vary the opening verbs."})
        score -= 3
    # Lines that still echo the candidate's raw (casual) answers word for word.
    try:
        import interview
        def grams(x, n=6):
            w = re.findall(r"[a-z0-9']+", x.lower()); return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
        raw = [f["answer"] for f in interview.load_facts() if f.get("answer")]
        lines_all = [t.get("summary", "")] + bullets + (t.get("additional") or [])
        echo = [ln for ln in lines_all if any(grams(ln) & grams(a) for a in raw)]
        if echo:
            issues.append({"area": "grammar", "severity": "high", "where": echo[0][:80],
                           "problem": f"{len(echo)} line(s) reuse the candidate's casual answer wording verbatim.",
                           "fix": "Rewrite in professional resume language with the same facts."})
            score -= min(15, 5 * len(echo))
    except Exception:
        pass
    kws = key_phrases(desc)
    text = resume_text(t).lower()
    hit = [k for k in kws if k in text]
    cov = round(100 * len(hit) / len(kws)) if kws else None
    if cov is not None and cov < 50:
        score -= 8
    return {"score": max(0, score), "issues": issues, "keyword_coverage": cov, "keywords_missing": [k for k in kws if k not in hit][:15]}

# ------------------------------------------------------------------ Astra grade
SCHEMA = {
    "type": "object",
    "properties": {
        "areas": {"type": "object", "properties": {k: {"type": "integer"} for k in WEIGHTS}, "required": list(WEIGHTS), "additionalProperties": False},
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "area": {"type": "string", "enum": list(WEIGHTS)}, "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "where": {"type": "string"}, "problem": {"type": "string"}, "fix": {"type": "string"}},
            "required": ["area", "severity", "where", "problem", "fix"], "additionalProperties": False}},
        "fact_requests": {"type": "array", "items": {"type": "object", "properties": {
            "requirement": {"type": "string"}, "question": {"type": "string"}, "why": {"type": "string"}, "hint": {"type": "string"}},
            "required": ["requirement", "question", "why", "hint"], "additionalProperties": False}},
        "missing_keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["areas", "summary", "issues", "fact_requests", "missing_keywords"],
    "additionalProperties": False,
}

PROMPT = """You are a demanding reviewer grading a tailored resume for one job posting. Be strict and specific; a resume that would sail through a top recruiter's screen scores 90+.

Grade five areas from 0 to 100:
- appearance: from the attached page images. Alignment, consistent fonts and spacing, use of the page, awkward wraps, orphan lines, scannability.
- grammar: spelling, punctuation, consistent tense, parallel bullet structure, consistent dates, no pronouns.
- density: concise bullets, no filler or repetition, right amount of content for the length.
- ats: how well employer resume-screening software would parse and rank it for THIS posting. Standard headings, text order, the posting's key phrases worded as the posting words them, acronyms spelled out once, title alignment.
- claims: how the claims read. Clear rather than vague, credible rather than inflated, relevant and well ordered for this job, consistent with each other and the dates.

"issues": the most important problems (up to 12), each tied to where it occurs, with a concrete fix. Fixes must be wording, ordering, trimming or formatting changes using facts already in the resume. Never write a fix that invents a fact.
"fact_requests": facts that would materially strengthen this resume for this posting but aren't in it (e.g. a metric, team size, budget, tool, certification, outcome). Phrase each as a neutral question to the candidate. Up to 5. The candidate answers; nothing is added unless they confirm it.
Before asking, read facts.txt: its CONFIRMED ANSWERS section lists everything the candidate has already been asked and answered. Never request a fact that an answer there already covers, even under different wording, and never re-ask something they answered "No" to. If the resume fails to use a confirmed answer, report that under "issues" instead (e.g. "Uses nothing from the confirmed answer about X"). Ask only about genuinely new gaps.
"missing_keywords": important posting phrases the resume lacks.

Files in this folder: posting.txt (the job), resume.txt (the tailored resume text), facts.txt (the candidate's real background: original resume and confirmed answers), and page images attached to this message. Read the text files; grade the attached images for appearance. Do not modify any file."""

def _pdf_pages_to_png(pdf, outdir):
    """Page images for Astra (white background, as printed). Works on macOS and Windows."""
    return osdeps.pdf_to_pngs(pdf, outdir, max_pages=3, max_px=1600)

def astra(t, pdf, desc, facts_text, timeout=420):
    p = codex_path()
    os.makedirs(WORK, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as d:
        pngs, n = _pdf_pages_to_png(pdf, d)
        open(os.path.join(d, "posting.txt"), "w").write(desc[:14000])
        open(os.path.join(d, "resume.txt"), "w").write(resume_text(t))
        open(os.path.join(d, "facts.txt"), "w").write(facts_text[:30000])
        json.dump(SCHEMA, open(os.path.join(d, "schema.json"), "w"))
        out = os.path.join(d, "out.json")
        cmd = [*osdeps.cmd(p), "exec", "-m", MODEL, "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", d,
               "--output-schema", os.path.join(d, "schema.json"), "-o", out]
        for png in pngs:
            cmd += ["-i", png]
        r = osdeps.run_hidden(cmd + ["-"], input=PROMPT, capture_output=True, text=True, timeout=timeout)  # prompt via stdin (-i takes many values)
        if not os.path.exists(out):
            tail = (r.stderr or r.stdout or "")[-300:]
            if "login" in tail.lower() or "auth" in tail.lower():
                raise RuntimeError("Codex isn't signed in to ChatGPT.")
            raise RuntimeError("Astra didn't return a grade. " + tail)
        g = json.load(open(out))
    g["pages"] = n
    return g

def grade(t, pdf, desc, facts_text, target_pages):
    """Full grade: Astra's five areas (weighted) blended with the tool's own mechanical checks."""
    from pypdf import PdfReader
    pages = len(PdfReader(pdf).pages)
    mech = mechanical(t, pages, target_pages, desc)
    a = astra(t, pdf, desc, facts_text)
    areas = {k: max(0, min(100, int(a["areas"].get(k, 0)))) for k in WEIGHTS}
    astra_score = round(sum(areas[k] * w for k, w in WEIGHTS.items()) / sum(WEIGHTS.values()))
    final = round(0.85 * astra_score + 0.15 * mech["score"])
    return {"score": final, "astra": astra_score, "mechanical": mech["score"], "areas": areas, "summary": a.get("summary", ""),
            "issues": (a.get("issues") or [])[:12] + mech["issues"], "fact_requests": (a.get("fact_requests") or [])[:5],
            "missing_keywords": a.get("missing_keywords") or mech["keywords_missing"], "keyword_coverage": mech["keyword_coverage"],
            "pages": pages}
