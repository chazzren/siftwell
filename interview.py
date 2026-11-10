"""Ask the candidate about skills their resume doesn't show, and keep the answers as a reusable fact bank.

Answers live in data/facts.json and are handed to Claude (scoring and tailoring) as candidate-confirmed facts,
to be used exactly as strongly as stated. "No" answers become things never to claim."""
import datetime as dt, json, os, re, secrets, threading

import claude_cli, people, resume

def FACTS(): return people.pdir("facts.json")
def QDIR(): return people.pdir("questions")
_lock = threading.Lock()

# ------------------------------------------------------------------ fact bank
def load_facts():
    try:
        return json.load(open(FACTS()))
    except Exception:
        return []

def _save(facts):
    json.dump(facts, open(FACTS(), "w"), indent=1)

LEVELS = {"yes": "Yes", "some": "Some / a little", "no": "No"}

def add_answers(answers, context):
    """answers: [{requirement, question, level: yes|some|no, answer}]. Unanswered ones are skipped.
    A new answer to the same requirement replaces the old one."""
    added = 0
    with _lock:
        facts = load_facts()
        for a in answers:
            level = a.get("level") if a.get("level") in LEVELS else ""
            text = (a.get("answer") or "").strip()[:1500]
            req = (a.get("requirement") or "").strip()[:200]
            if not (level or text) or not req:
                continue
            prev = next((f for f in facts if a.get("fact_id") and f["id"] == a["fact_id"]), None)
            if prev:  # a follow-up to something already answered: add to that answer, don't replace it
                if text:
                    prev["answer"] = (prev.get("answer", "") + " " + text).strip()[:3000]
                if level == "yes" or (level == "some" and prev.get("level") == "no"):
                    prev["level"] = level
                prev["polished"] = ""; prev["date"] = dt.date.today().isoformat()
                added += 1
                continue
            facts = [f for f in facts if f["requirement"].lower() != req.lower()]
            facts.append({"id": secrets.token_hex(4), "date": dt.date.today().isoformat(), "context": context[:120], "polished": "",
                          "requirement": req, "question": (a.get("question") or "")[:400],
                          "level": level or "yes", "answer": text})
            added += 1
        _save(facts)
    if added:
        try:
            polish_all()  # one quick Claude call; tailoring then works from professional wording
        except Exception as e:
            print("polish failed:", e, flush=True)
    return added

POLISH_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "polished": {"type": "string"}}, "required": ["id", "polished"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}

POLISH_SYSTEM = """You turn a job seeker's quick, casual answers into polished resume-ready statements.
For each answer, write one or two concise professional sentences that state exactly what the answer says: no more, no less.
- Fix grammar, capitalization and product/agency names (e.g. "NRO" -> "National Reconnaissance Office (NRO)" on first use is fine; "opencode" -> "OpenCode").
- Drop filler, hedges and slang; no first person ("I", "my"); write as resume phrasing (start with a verb where natural).
- Keep every qualifier that limits the claim (e.g. "helped", "part of", "hasn't launched yet", "a little"). Never upgrade "helped" to "led", never add numbers, tools, outcomes or scope that aren't in the answer.
- If the answer is "no" or says they lack it, write a short neutral statement of that."""

def polish(facts_list):
    """Fill in 'polished' for answers that lack it (one Claude call for the batch). Returns how many were polished."""
    todo = [f for f in facts_list if f.get("answer") and not f.get("polished")]
    if not todo:
        return 0
    msg = "\n\n".join(f'<answer id="{f["id"]}">\nQuestion: {f.get("question","")}\nTopic: {f["requirement"]}\n'
                       f'Level: {LEVELS.get(f["level"], f["level"])}\nAnswer: {f["answer"]}\n</answer>' for f in todo)
    out = claude_cli.run_json(POLISH_SYSTEM, msg, POLISH_SCHEMA, effort="low", timeout=300)
    got = {x["id"]: x["polished"].strip() for x in out.get("items", [])}
    for f in todo:
        if got.get(f["id"]):
            f["polished"] = got[f["id"]][:600]
    return sum(1 for f in todo if f.get("polished"))

def polish_all():
    with _lock:
        facts = load_facts()
    n = polish(facts)
    if n:
        with _lock:
            cur = {f["id"]: f for f in load_facts()}
            for f in facts:
                if f.get("polished") and f["id"] in cur:
                    cur[f["id"]]["polished"] = f["polished"]
            _save(list(cur.values()))
    return n

def edit_polished(fid, text):
    with _lock:
        facts = load_facts()
        for f in facts:
            if f["id"] == fid:
                f["polished"] = (text or "").strip()[:600]
        _save(facts)

def delete_fact(fid):
    with _lock:
        _save([f for f in load_facts() if f["id"] != fid])

def facts_text(facts=None):
    """Block appended to the candidate profile for scoring and tailoring."""
    facts = load_facts() if facts is None else facts
    have = [f for f in facts if f["level"] != "no"]
    lack = [f for f in facts if f["level"] == "no"]
    lines = []
    if have:
        lines.append("Facts the candidate confirmed in Q&A (not on the resume). Each has a polished statement to work from and the "
                     "candidate's raw note for nuance. Treat raw notes as facts, never as copy: write resume text in professional "
                     "language. Use facts only as strongly as stated: 'Some / a little' means familiarity or limited use, never "
                     "expertise; never add numbers, dates, tools or outcomes the answer doesn't contain.")
        for f in have:
            body = f.get("polished") or f["answer"] or "(no details given)"
            raw = f" (raw note: {f['answer']})" if f.get("polished") and f.get("answer") else ""
            lines.append(f"- {f['requirement']} [{LEVELS[f['level']]}]: {body}{raw}")
    if lack:
        lines.append("The candidate confirmed they do NOT have (never claim): " + "; ".join(f["requirement"] for f in lack))
    return "\n".join(lines)

# ------------------------------------------------------------------ question generation
QSCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
        "requirement": {"type": "string"},
        "question": {"type": "string"},
        "why": {"type": "string"},
        "hint": {"type": "string"}},
        "required": ["requirement", "question", "why", "hint"], "additionalProperties": False}}},
    "required": ["questions"],
    "additionalProperties": False,
}

QSYSTEM = """You help a job seeker find true experience their resume leaves out, so an honest tailored resume can include it.

Compare the target (a job posting, or a set of target roles) with the candidate's resume, profile, and the answers they have already given. Find the requirements and strong preferences the resume shows no evidence for, but that this candidate could plausibly have given their actual jobs (tools commonly used in those roles, duties their titles usually involve, adjacent skills, certifications, training, side projects, volunteer or military work). Prioritize the ones that would most change their odds.

Ask up to {n} questions, one requirement each, most important first. Rules:
- Neutral and specific, never leading: ask whether and how they've done it, not to confirm it. ("Have you used Terraform or another infrastructure-as-code tool? If so, where, for how long, and for what?")
- Invite concrete details a resume line could use: where, when, how long, scale, outcome.
- Skip anything the resume already demonstrates and anything already answered.
- Skip requirements no reasonable answer could meet (a degree they clearly lack, ten more years of experience).
- Never ask about age, health, family, religion, nationality, ethnicity, salary history or other protected or sensitive matters.
"requirement" is a 2 to 6 word label for what the posting wants (e.g. "Terraform / infrastructure as code"). "why" is one short sentence on how a yes would help with this job. "hint" is a short example of a useful answer's shape, without inventing facts about this candidate.
Return an empty list if nothing important is missing."""

def _qpath(key):
    return os.path.join(QDIR(), re.sub(r"[^a-z0-9-]", "", key) + ".json")

def cached_questions(key):
    try:
        return json.load(open(_qpath(key)))
    except Exception:
        return None

def generate(job=None, description=""):
    """Questions for one job (job dict + description) or, with job=None, for the candidate's target roles overall."""
    prof = resume.load_active()
    if not prof:
        raise ValueError("Approve your resume profile first.")
    known = load_facts()
    answered = answered_block(known)
    if job:
        target = (f"JOB POSTING\nTitle: {job['title']}\nCompany: {job['company']}\n"
                  f"Clearance noted: {job.get('clearance') or 'none'}\n\n{description[:12000]}")
        n = 6
    else:
        target = ("TARGET ROLES (general interview, not one posting)\n" + "\n".join(prof.get("target_roles", [])) +
                  "\n\nAsk about the skills, tools and experiences that postings for these roles most often require "
                  "and the resume doesn't show.")
        n = 10
    prompt = (f"{target}\n\nORIGINAL RESUME\n{prof.get('_resume_text', '')[:20000]}\n\n"
              f"CANDIDATE PROFILE\n{resume.profile_text(prof)}\n\nALREADY ANSWERED\n{answered}")
    out = claude_cli.run_json(QSYSTEM.replace("{n}", str(n)), prompt, QSCHEMA, effort="medium", timeout=600)
    qs = out.get("questions", [])[:n]
    return dedupe(qs, known)

def facts_hash(facts=None):
    import hashlib
    facts = load_facts() if facts is None else facts
    return hashlib.sha1(json.dumps([(f["id"], f.get("answer"), f.get("level")) for f in facts]).encode()).hexdigest()[:12]

def answered_block(facts):
    if not facts:
        return "(none yet)"
    return "\n".join(f"- [{f['id']}] {f['requirement']}: {LEVELS.get(f['level'], f['level'])}"
                     + (f" - {f.get('polished') or f.get('answer')}" if (f.get('polished') or f.get('answer')) else "") for f in facts)

DEDUPE_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "status": {"type": "string", "enum": ["new", "covered", "followup"]},
    "fact_id": {"type": "string"}, "question": {"type": "string"}},
    "required": ["i", "status", "fact_id", "question"], "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False}

DEDUPE_SYSTEM = """You stop a job seeker from being asked the same thing twice.
You get candidate questions (numbered) and the answers the candidate already gave (with ids). For each question decide:
- "covered": an earlier answer already addresses what this question is really after, even if worded differently or under a different label (e.g. "LLM agent building" vs "Hands-on generative AI experience"; "Scrum delivery" vs "Agile tooling"). A "No" answer also covers it. Give that answer's id.
- "followup": an earlier answer is on the same topic but clearly leaves out a specific detail this question needs (e.g. they said they used Salesforce, the question needs admin vs user, or scale). Give that answer's id and rewrite the question as a short follow-up that acknowledges what they said and asks only for the missing detail.
- "new": no earlier answer is about this. fact_id "" and question "".
Be strict about "covered": when in doubt between covered and followup, choose covered unless the missing detail would really change a resume line."""

def dedupe(questions, facts=None):
    """Drop questions an earlier answer already covers; turn partial overlaps into short follow-ups (marked fact_id).
    Uses a quick Haiku call; on any failure falls back to dropping exact-label repeats."""
    facts = load_facts() if facts is None else facts
    if not questions or not facts:
        return questions
    labels = {f["requirement"].lower() for f in facts}
    try:
        qtext = "\n".join(f"{i}. [{q.get('requirement','')}] {q.get('question','')}" for i, q in enumerate(questions))
        out = claude_cli.run_json(DEDUPE_SYSTEM, f"CANDIDATE QUESTIONS\n{qtext}\n\nALREADY ANSWERED\n{answered_block(facts)}",
                                  DEDUPE_SCHEMA, model="claude-haiku-5-5", effort="low", timeout=180)
        by_i = {r["i"]: r for r in out.get("results", [])}
    except Exception as e:
        print("question de-dupe fell back to labels:", e, flush=True)
        return [q for q in questions if q.get("requirement", "").lower() not in labels]
    fid = {f["id"]: f for f in facts}
    kept = []
    for i, q in enumerate(questions):
        r = by_i.get(i) or {"status": "new"}
        if r["status"] == "covered" and r.get("fact_id") in fid:
            continue
        if r["status"] == "followup" and r.get("fact_id") in fid and r.get("question"):
            f = fid[r["fact_id"]]
            q = {**q, "question": r["question"], "fact_id": f["id"], "requirement": f["requirement"],
                 "earlier": f.get("polished") or f.get("answer") or LEVELS.get(f["level"], "")}
        elif q.get("requirement", "").lower() in labels:
            continue
        kept.append(q)
    return kept

def fresh_questions(key):
    """Cached questions, re-checked against answers given since they were made."""
    rec = cached_questions(key)
    if not rec:
        return None
    fh = facts_hash()
    if rec.get("facts_hash") != fh:
        rec["questions"] = dedupe(rec.get("questions") or [])
        rec["facts_hash"] = fh
        try:
            json.dump(rec, open(_qpath(key), "w"), indent=1)
        except Exception:
            pass
    return rec

def generate_and_cache(key, job=None, description=""):
    qs = generate(job, description)
    os.makedirs(QDIR(), exist_ok=True)
    rec = {"questions": qs, "created": dt.datetime.now().isoformat(timespec="minutes"), "facts_hash": facts_hash(),
           "context": f"{job['title']} @ {job['company']}" if job else "General interview"}
    json.dump(rec, open(_qpath(key), "w"), indent=1)
    return rec
