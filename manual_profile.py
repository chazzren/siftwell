"""The "Fill in my profile myself" form: how a profile is made without Claude. Shared by /profile (Resume) and /setup.

CSS and JS are plain strings the two pages embed. The JS defines window.ManualProfile:
  mount(root, {claude, onSaved, button})  draws the form into root (values are kept between redraws)
  submit()                                POST /api/profile/manual; resolves with the reply, rejects with a friendly Error
  load(profile)                           fill the form from an existing profile object (e.g. a hand-filled one)
A .docx / .txt resume (or pasted text) pre-fills the form through POST /api/resume/prefill (local text reading, no AI).
The server side lives in resume.py (build_manual_profile, save_manual, prefill_from_text)."""

CSS = """
.mp{display:flex;flex-direction:column;gap:14px;text-align:left}
.mp label.f{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:600;min-width:0}
.mp label.f small{font-weight:400;color:var(--muted)}
.mp input[type=text],.mp input[type=number],.mp textarea,.mp select{width:100%;min-width:0;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font:inherit;font-weight:400}
.mp textarea{min-height:5em;resize:vertical}
.mp input[type=file]{max-width:100%;min-width:0;font:inherit;font-size:13px}
.mp .mp-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.mp .mp-pre{border:1px dashed var(--line);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px;background:var(--surface)}
.mp .mp-pre p,.mp .mp-note{margin:0;font-size:13px;color:var(--muted)}
.mp .mp-pre details summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:13px}
.mp .mp-role{border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--surface);display:flex;flex-direction:column;gap:8px}
.mp .mp-row3,.mp .mp-ct{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,2fr) minmax(0,1.3fr);gap:8px}
.mp h3{margin:2px 0 0;font-size:14px}
.mp .mp-btns{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.mp .mp-msg{font-size:13px;color:var(--muted)}.mp .mp-msg.err{color:var(--bad)}.mp .mp-msg.ok{color:var(--good)}
.mp button.mp-b{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.mp button.mp-b.primary{background:var(--accent);border-color:var(--accent);color:var(--surface);font-weight:600}
.mp button.mp-b.link{border:0;background:none;color:var(--accent);padding:0;font-weight:600}
.mp .mp-clr{display:flex;flex-direction:column;gap:6px;min-width:0}
.mp .mp-q{font-size:13px;font-weight:600}
.mp .mp-yn{display:flex;gap:16px}
.mp .mp-yn label{display:inline-flex;align-items:center;gap:6px;font-size:14px;min-height:32px;cursor:pointer}
.mp .mp-yn input{width:18px;height:18px;margin:0}
@media (max-width:560px){.mp .mp-grid,.mp .mp-row3,.mp .mp-ct{grid-template-columns:minmax(0,1fr)}}
"""

JS = r"""
window.ManualProfile = (function(){
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  // Clearance levels, asked only after "Do you hold a security clearance?" is answered Yes (most people never need it).
  const CLR = [["Public Trust", "Public Trust"], ["Secret", "Secret"], ["Top Secret", "Top Secret"], ["TS/SCI", "TS/SCI"], ["TS/SCI + poly", "TS/SCI + polygraph"]];
  const blankRole = () => ({title: "", employer: "", dates: "", highlights: ""});
  const blank = () => ({name: "", location: "", current_title: "", years_experience: "", summary: "", experience: [blankRole()],
                        skills: "", education: "", certifications: "", clearance: "", email: "", phone: "", linkedin: ""});
  const lines = v => Array.isArray(v) ? v.join("\n") : (v || "");
  let D = blank(), root = null, opts = {}, msg = {t: "", cls: ""}, hasClr = null;   // hasClr: null until answered

  function fill(src, only){
    if (!src) return;
    const t = (k, v) => { if (v != null && String(v).trim() !== "" && !(only && D[k] && String(D[k]).trim())) D[k] = v; };
    ["name", "location", "current_title", "summary", "clearance"].forEach(k => t(k, src[k]));
    if (src.years_experience != null) t("years_experience", src.years_experience);
    ["skills", "education", "certifications"].forEach(k => t(k, lines(src[k])));
    const ct = src.contact && typeof src.contact === "object" ? src.contact : {};
    ["email", "phone", "linkedin"].forEach(k => t(k, ct[k]));
    if ((src.clearances || []).length && !D.clearance) D.clearance = src.clearances[0];
    if ((src.experience || []).length) D.experience = src.experience.map(e => ({title: e.title || "", employer: e.employer || "", dates: e.dates || "", highlights: lines(e.highlights)}));
    if (!D.experience.length) D.experience = [blankRole()];
  }
  function load(p){ D = blank(); hasClr = null; fill(p && Object.assign({}, p, {current_title: ((p.target_roles || [])[0]) || ""}), false); if (root) draw(); }

  const f = (k, label, ctl, help) => `<label class="f">${esc(label)}${help ? `<small>${esc(help)}</small>` : ""}${ctl}</label>`;
  const inp = (k, ph, type) => `<input type="${type || "text"}" data-mp="${k}" value="${esc(D[k])}"${ph ? ` placeholder="${esc(ph)}"` : ""}${type === "number" ? ' min="0" max="70"' : ""} autocomplete="off">`;
  const ta = (k, rows, ph) => `<textarea data-mp="${k}" rows="${rows}"${ph ? ` placeholder="${esc(ph)}"` : ""}>${esc(D[k])}</textarea>`;
  const role = (r, i) => `<div class="mp-role" data-role="${i}">
    <div class="mp-row3"><label class="f">Job title<input type="text" data-r="title" value="${esc(r.title)}" autocomplete="off"></label>
      <label class="f">Employer<input type="text" data-r="employer" value="${esc(r.employer)}" autocomplete="off"></label>
      <label class="f">Dates<input type="text" data-r="dates" value="${esc(r.dates)}" placeholder="Jan 2020 - Present" autocomplete="off"></label></div>
    <label class="f">What you did <small>One accomplishment per line.</small><textarea data-r="highlights" rows="4">${esc(r.highlights)}</textarea></label>
    ${D.experience.length > 1 ? `<div><button type="button" class="mp-b link" data-act="rmrole" data-i="${i}">Remove this role</button></div>` : ""}</div>`;

  const clrOn = () => hasClr !== null ? hasClr : (D.clearance ? true : null);
  function draw(){
    root.innerHTML = `<div class="mp">
      <div class="mp-pre"><b>Start from a resume file <span class="mp-note">(optional)</span></b>
        <p>A Word (.docx) or text (.txt) resume fills in the form for you to check. It is read on this computer; nothing is sent anywhere.</p>
        <input type="file" data-act="file" accept=".docx,.txt,.md,.text" aria-label="Choose a .docx or .txt resume">
        <details><summary>Or paste your resume text</summary><textarea data-act="paste" rows="5" aria-label="Resume text"></textarea>
          <div class="mp-btns" style="margin-top:6px"><button type="button" class="mp-b" data-act="usepaste">Fill the form from this text</button></div></details>
        <span class="mp-msg" data-pre role="status"></span></div>
      <div class="mp-grid">${f("name", "Full name", inp("name"), "As it should appear on your resume.")}${f("location", "Location", inp("location", "City, ST"))}
        ${f("current_title", "Current job title", inp("current_title", "Your job title"), "This is what Siftwell searches for first.")}
        ${f("years_experience", "Years of experience", inp("years_experience", "", "number"), "Optional. Worked out from your roles if blank.")}</div>
      <div class="mp-ct">${f("email", "Email", inp("email"))}${f("phone", "Phone", inp("phone"))}${f("linkedin", "LinkedIn", inp("linkedin", "linkedin.com/in/…"))}</div>
      <p class="mp-note" style="margin-top:-6px">Optional. Printed at the top of the resumes Siftwell tailors for you (Settings → Resume PDF chooses which); not sent to Claude.</p>
      ${f("summary", "Summary", ta("summary", 4, "Two or three sentences about what you do best."))}
      <h3>Experience</h3><div id="mpRoles">${D.experience.map(role).join("")}</div>
      <div><button type="button" class="mp-b" data-act="addrole">+ Add a role</button></div>
      <div class="mp-grid">${f("skills", "Skills", ta("skills", 4), "One per line, or separated by commas.")}
        ${f("education", "Education", ta("education", 4, "e.g. a diploma, degree or training program, and where"), "One per line.")}</div>
      <div class="mp-grid">${f("certifications", "Certifications and licenses", ta("certifications", 3, "e.g. a license; a certificate"), "One per line, or separated by semicolons.")}
        <div class="f mp-clr" role="group" aria-labelledby="mpClrQ"><span class="mp-q" id="mpClrQ">Do you hold a security clearance?</span>
          <span class="mp-yn"><label><input type="radio" name="mpclr" value="no"${clrOn() === false ? " checked" : ""}> No</label><label><input type="radio" name="mpclr" value="yes"${clrOn() ? " checked" : ""}> Yes</label></span>
          ${clrOn() ? f("clearance", "Which one?", `<select data-mp="clearance">${(!D.clearance || CLR.some(c => c[0] === D.clearance) ? CLR : [[D.clearance, D.clearance]].concat(CLR)).map(([v, t]) => `<option value="${esc(v)}"${D.clearance === v ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>`, "Only what you hold today.") : ""}</div></div>
      ${opts.button ? `<div class="mp-btns"><button type="button" class="mp-b primary" data-act="save">Save my profile</button></div>` : ""}
      <div class="mp-msg ${msg.cls}" data-msg role="status">${esc(msg.t)}</div></div>`;
  }
  function say(t, cls){ msg = {t: t || "", cls: cls || ""}; const m = root && root.querySelector("[data-msg]"); if (m) { m.textContent = msg.t; m.className = "mp-msg " + msg.cls; } }
  function pre(t, cls){ const m = root && root.querySelector("[data-pre]"); if (m) { m.textContent = t || ""; m.className = "mp-msg " + (cls || ""); } }

  function prefill(body){
    pre("Reading it…");
    return fetch("/api/resume/prefill", {method: "POST", headers: {"Content-Type": "application/json", "X-Jobboard": "1"}, body: JSON.stringify(body)})
      .then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
        if (!ok) { pre(d.error || "Couldn't read that.", "err"); return; }
        fill(d.fields, false); draw(); pre("Filled in what could be read. Check every field and fix anything that's wrong.", "ok");
      }).catch(() => pre("Couldn't reach Siftwell.", "err"));
  }
  function onInput(e){
    const el = e.target, k = el.dataset.mp, r = el.dataset.r;
    if (k) D[k] = el.value;
    else if (r) D.experience[+el.closest("[data-role]").dataset.role][r] = el.value;
  }
  function onClick(e){
    const b = e.target.closest("[data-act]"); if (!b) return;
    const a = b.dataset.act;
    if (a === "addrole") { D.experience.push(blankRole()); draw(); }
    else if (a === "rmrole") { D.experience.splice(+b.dataset.i, 1); if (!D.experience.length) D.experience = [blankRole()]; draw(); }
    else if (a === "usepaste") { const t = root.querySelector('[data-act="paste"]').value.trim(); if (t.length < 40) { pre("Paste the resume text first.", "err"); return; } prefill({text: t}); }
    else if (a === "save") { submit().then(d => { say("Saved. Your profile is ready.", "ok"); if (opts.onSaved) opts.onSaved(d); }).catch(err => say(err.message, "err")); }
  }
  function onChange(e){
    const el = e.target;
    if (el.name === "mpclr") { hasClr = el.value === "yes"; D.clearance = hasClr ? (D.clearance || CLR[0][0]) : ""; draw(); const r = root.querySelector('input[name="mpclr"]:checked'); if (r) r.focus(); return; }
    if (el.dataset.act === "file" && el.files[0]) {
      const file = el.files[0];
      if (file.size > 15 * 1024 * 1024) { pre("That file is over 15 MB.", "err"); return; }
      const fr = new FileReader();
      fr.onload = () => prefill({filename: file.name, data_b64: String(fr.result).split(",")[1] || ""});
      fr.readAsDataURL(file);
    }
  }
  const split = s => String(s || "").split(/\n+/).map(x => x.trim()).filter(Boolean);
  const splitList = s => String(s || "").split(/[\n,;]+/).map(x => x.trim()).filter(Boolean);
  // credentials: one per line or per semicolon ("RN license; BLS; ACLS" is three); a comma stays ("RN license, Ohio")
  const splitCreds = s => String(s || "").split(/[\n;]+/).map(x => x.trim()).filter(Boolean);
  function payload(){
    return {name: D.name, location: D.location, current_title: D.current_title, summary: D.summary,
      years_experience: D.years_experience === "" ? null : D.years_experience,
      experience: D.experience.map(r => ({title: r.title, employer: r.employer, dates: r.dates, highlights: split(r.highlights)})),
      skills: splitList(D.skills), education: split(D.education), certifications: splitCreds(D.certifications), clearance: D.clearance,
      contact: {email: D.email, phone: D.phone, linkedin: D.linkedin}};
  }
  function submit(){
    return fetch("/api/profile/manual", {method: "POST", headers: {"Content-Type": "application/json", "X-Jobboard": "1"}, body: JSON.stringify({profile: payload()})})
      .then(r => r.json().then(d => { if (!r.ok) throw new Error(d.error || "Couldn't save that."); return d; }));
  }
  function mount(el, o){
    root = el; opts = o || {};
    if (!D.name && opts.name) D.name = opts.name;
    if (!root.dataset.mpWired) {
      root.dataset.mpWired = "1";
      root.addEventListener("input", onInput); root.addEventListener("click", onClick); root.addEventListener("change", onChange);
    }
    draw();
  }
  return {mount, submit, load, say};
})();
"""
