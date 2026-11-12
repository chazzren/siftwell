"""The My profile page (GET /profile): everything about the person, in the same two-pane layout as Settings.

Left: a section list (Resume, About you, Highlights & answers, Job search, Target, Companies). Right: the selected
section. The selection lives in the URL hash (/profile#search); at phone width it is a drill-down with a "‹ My profile"
back control. A status strip on top shows what is read, approved and rated, and what is missing, with links.

Layout CSS, pane helpers and the shared script pieces (router, header icons, profile menu, "Saved" text) come from
settings_page.py. Controls save themselves on change: job search, target and company settings go through
POST /api/person/settings (which re-checks the board and queues the automatic quick check), edits to the approved
profile through POST /api/profile/edit. A freshly read resume is a draft: it is checked and approved on About you
(POST /api/profile/approve)."""
import html
import json

import claude_cli
import manual_profile
import people
import report
import settings_page
from settings_page import _SVG, _group, _pane_head, _row, e

# Set to the Catalog page's path ("/catalog") when that page exists; the Companies section then links to it.
CATALOG_HREF = "/catalog"

CATEGORIES = [
    ("resume", "Resume", '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>'),
    ("about", "About you", '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
    ("highlights", "Highlights & answers", '<path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9L12 17.8 5.8 21.1 7 14.2 2 9.3l6.9-1z"/>'),
    ("search", "Job search", '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.3-4.3"/>'),
    ("target", "Target", '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
    ("companies", "Companies", '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>'),
]

FILE_TYPES = ".pdf,.doc,.docx,.rtf,.odt,.txt,.md,.html,.png,.jpg,.jpeg,.heic,.webp"


def _pad(inner):
    return f'<div class="spad">{inner}</div>'


def _select(cid, key, options):
    opts = "".join(f'<option value="{e(str(v))}">{e(t)}</option>' for v, t in options)
    return f'<select id="{cid}" data-ps="{key}">{opts}</select>'


def _row_ps(label, help_text, cid, ctl):
    return _row(f'<label for="{cid}">{e(label)}</label>', help_text, ctl)


def _textarea(cid, key, label, rows=4, placeholder=""):
    ph = f' placeholder="{e(placeholder)}"' if placeholder else ""
    return _pad(f'<textarea id="{cid}" data-ps="{key}" rows="{rows}" aria-label="{e(label)}"{ph}></textarea>')


def _pane_resume():
    return (_group("Your resume", "Claude reads it to build your profile. The file is kept with your profile on this computer.", [
        '<div class="srow stack"><div class="note" id="resumeState" role="status" aria-live="polite">Checking…</div>'
        '<div class="prog" id="resProg" hidden><i id="resBar"></i></div></div>',
        '<div class="srow stack" id="resPick"><label class="drop" id="drop" for="resumeFile">Drop a resume here or click to choose a file'
        '<br><small>PDF, Word, RTF, text, or a photo of a printed resume</small></label>'
        f'<input type="file" id="resumeFile" accept="{FILE_TYPES}" hidden></div>',
        '<form class="srow stack" id="gdocForm"><input type="url" id="gdocUrl" placeholder="Or paste a Google Docs link (docs.google.com/document/d/…)" '
        'aria-label="Google Docs link"><div class="sbtns"><button class="btn" type="submit">Use Google Doc</button></div></form>',
    ]) + '<p class="sfoot">A Google Doc link works if sharing is set to "Anyone with the link can view". Otherwise use File &gt; Download &gt; '
         'Microsoft Word in Google Docs and drop that file here. A new resume becomes a draft you check under About you before it replaces the current profile.</p>' +
            '<div class="hlbanner" id="resNoClaude" style="margin-top:18px" hidden><span><b>Claude isn\'t connected</b>, so Siftwell can\'t read a resume by itself. '
            'Fill in your profile below (a Word or text resume can fill the form in for you), or connect Claude to have it read PDFs, photos and Google Docs.</span>'
            '<span class="row"><a class="btn sm" href="/settings#get-started">Connect Claude</a></span></div>' +
            '<p class="sfoot" id="manualLink" hidden><button type="button" class="linkbtn" id="manualOpen">Fill in my profile myself instead</button></p>'
            '<div id="manualWrap" hidden style="margin-top:14px">' + _group("Fill in my profile myself", "Siftwell uses this to choose which jobs to show. You can change any of it later under About you.",
                                                                          ['<div class="spad"><div id="manualRoot"></div></div>']) + '</div>')


def _pane_about():
    return (_group("Profile name", "", [_row_ps("Name", "Shown at the top of the board and in the profile menu.", "ab-name",
                                                 '<input type="text" id="ab-name" maxlength="40" autocomplete="off">')]) +
            '<div class="hlbanner" id="abDraft" style="margin-top:18px" hidden><span>Claude read your resume and drafted this. Fix anything that is wrong, then approve: '
            'it decides which jobs you see and what tailored resumes may claim. Nothing is saved until you approve.</span>'
            '<span class="row"><button class="btn primary sm" type="button" id="rvApprove">Approve and re-score jobs</button>'
            '<button class="btn sm" type="button" id="rvDiscard">Discard draft</button></span></div>'
            '<div id="abBody"></div>'
            '<p class="note pnote" id="abNote" role="status" aria-live="polite"></p>')


def _pane_highlights():
    return (_group("What we pulled from your resume",
                   "Jobs that require a degree or license you don't have are hidden (you can still show them from Filters). "
                   "Fix anything that's wrong and the board re-checks itself.", [_pad(
                       '<div class="hlbanner" id="hlBanner" hidden><span>Please check these are right. They decide which jobs are hidden.</span>'
                       '<span class="row"><button class="btn sm" type="button" id="hlEditBtn2">Fix something</button>'
                       '<button class="btn primary sm" type="button" id="hlConfirm">Looks right</button></span></div>'
                       '<div class="hlcards" id="hlCards"><div class="note">Loading…</div></div>'
                       '<div class="row"><button class="btn sm" type="button" id="hlEditBtn">Edit</button>'
                       '<button class="btn ghost sm" type="button" id="hlRefresh">Re-read my resume</button><span class="note" id="hlMsg" role="status" aria-live="polite"></span></div>'
                       '<div class="hledit" id="hlEdit" hidden></div>')]) +
            _group("What you've told me", 'Skills and experience your resume leaves out. Scoring and tailoring use these exactly as you stated them; "No" answers are never claimed.', [_pad(
                '<div class="row" style="justify-content:space-between"><span class="note" id="factCount"></span>'
                '<button class="btn sm" type="button" id="generalQs">Answer general questions</button></div>'
                '<div class="factlist" id="factList"></div>')]))


def _pane_search():
    # Home ZIP / radius, ways of working, remote anywhere, travel limit, pay floor and level live in the board's
    # Filters panel (My search, report.py); this pane keeps only what Filters doesn't cover.
    pay = [
        _row_ps("Current base ($, optional)", "Shown on each job's pay bar.", "ps-current_base",
                '<input type="number" inputmode="numeric" step="5000" id="ps-current_base" data-ps="current_base">'),
        _row_ps("Current package, one line (optional)", "", "ps-current_label",
                '<input type="text" id="ps-current_label" data-ps="current_label" placeholder="e.g. your pay, schedule and time off">'),
    ]
    return ('<p class="sfoot pmoved" id="psMoved">Location, ways of working, travel, pay floor and level are set in the board\'s Filters. '
            '<a href="/#filters">Open Filters on the board</a></p>' +
            _group("What Siftwell looks for", "Siftwell gives every job a Relevance score from this list, with plain matching and no Claude: "
                   "a job title on the list counts most, then one step up, then related roles; your skills found in a posting add a little. "
                   "Your board shows jobs whose titles match the list (with nothing on it, every job title is shown), puts the most relevant first, "
                   "and Claude rates the most relevant ones first. Changing the list never resets ratings you already have.",
                   [_pad('<div id="lfRoot" class="lf"><p class="note">Loading…</p></div>')]) +
            '<p class="sfoot">Other names for a job, related occupations and typical skills come from the O*NET occupation list '
            '(U.S. Department of Labor), which ships with Siftwell and works offline.</p>' +
            _group("Goals for Claude to weigh", "Pay, commute, what to avoid. Claude reads this when it rates a job.",
                   [_textarea("ps-goals", "goals", "Goals for Claude to weigh", 4)]) +
            _group("Your current pay", "", pay) +
            '<p class="sfoot">Each change re-checks your board right away (no new listings).<span id="psAutoRate"> Jobs that newly appear get a quick Claude check automatically.</span></p>')


def _pane_target():
    return (_group("What you're aiming for", "In your own words. It gets its own tab where Claude rates each job as a step toward it. "
                   "Leave it blank to skip, or tap Not sure? for suggestions.",
                   [_textarea("ps-target_text", "target_text", "Target", 4, "e.g. Office manager at a school or hospital, or a move from retail into human resources")]) +
            # (shown only to a profile that already limited its target this way in an earlier version: see fillSettings)
            '<div id="tgScopeWrap" hidden>' +
            _group("Which companies", "", [_row_ps("Companies", "", "ps-target_scope",
                                                   _select("ps-target_scope", "target_scope", [("all", "Every employer I watch"), ("ai", "Only the ones marked as AI companies")]))]) +
            '</div>' +
            _group("What you'd do to get there", "Time, courses, certifications, projects.",
                   [_textarea("ps-prep_text", "prep_text", "What you'd do to get there", 3, "e.g. 5 hours a week for 3 months; one certification; no degree")]) +
            _group("Claude's reading", "", [_pad('<div class="note" id="tgState" role="status" aria-live="polite"></div>'
                                                 '<div class="row"><button class="btn" type="button" id="tgSuggest">Not sure? Suggest targets</button></div>'
                                                 '<div class="factlist" id="tgSugg"></div>')]))


def _pane_companies():
    catalog = (f'<a href="{e(CATALOG_HREF)}">Browse every company Siftwell tracks</a>' if CATALOG_HREF
               else '<span class="note" id="catalogSlot">A page for browsing every employer Siftwell checks is coming.</span>')
    return ('<p class="sfoot" style="margin-top:14px"><span id="coCount"></span>Your employers come from the Siftwell employer directory near you, '
            'the companies you add here or on the Employers page, and what Claude finds for you.</p>' +
            _group("Add a company", "", [
                '<form class="srow stack" id="coAddForm"><input type="url" id="coUrl" placeholder="Paste a company\'s careers or job-list link" aria-label="Careers page link">'
                '<input type="text" id="coName" placeholder="Name (optional)" aria-label="Company name">'
                '<select id="coScope" aria-label="Who sees it"><option value="me">Just this profile</option><option value="all">Everyone</option></select>'
                '<div class="sbtns"><button class="btn primary" type="submit">Add company</button></div></form>',
                '<div class="srow"><span class="note" id="coMsg" role="status" aria-live="polite"></span></div>']) +
            _group("Employers on my own list", "Added by you, or kept from an earlier version of Siftwell.", [_pad('<div class="factlist" id="coOwn"><div class="note">Loading…</div></div>')]) +
            # CLEAR SPOT for the Catalog link: set CATALOG_HREF above once the Catalog page exists.
            _group("Browse all companies", "", [f'<div class="srow" id="coCatalog"><div class="slab">{catalog}</div></div>']))


PANES = {"resume": _pane_resume, "about": _pane_about, "highlights": _pane_highlights, "search": _pane_search,
         "target": _pane_target, "companies": _pane_companies}


def _render_parts():
    nav, panes = [], []
    for cid, name, icon in CATEGORIES:
        nav.append(f'<a class="scat" href="#{cid}" data-cat="{cid}"><span class="sico">{_SVG.format(icon)}</span>'
                   f'<span class="sname">{e(name)}</span><span class="schev" aria-hidden="true">›</span></a>')
        panes.append(f'<section class="spane" data-cat="{cid}" aria-labelledby="h-{cid}" hidden>'
                     f'{_pane_head(cid, name, "/profile", "My profile")}{PANES[cid]()}</section>')
    return "".join(nav), "".join(panes)


def render_profile_html(pid=None) -> str:
    name = e(people.name(pid))
    p = people.prefs(pid)
    nav, panes = _render_parts()
    tools = report.TOOLS.replace('id="resumeBtn" href="/profile"', 'id="resumeBtn" href="/profile" aria-current="page"')
    head = report.HEAD.replace("<title>Siftwell</title>", f"<title>{name}'s profile</title>")
    body = (BODY.replace("__TOOLS__", tools).replace("__NAV__", nav).replace("__PANES__", panes).replace("__NAME__", name))
    data = {"name": people.name(pid), "settings": people.settings(pid)}
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            # Apply the saved theme before first paint so the page doesn't flash the wrong colours.
            "<script>(function(){var t=" + json.dumps(p.get("display.theme")) +
            ';if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;})();</script>' +
            head + settings_page.CSS + CSS + "<style>" + manual_profile.CSS + "</style></head><body>" + body +
            "<script>window.__PREFS__=" + json.dumps(p).replace("</", "<\\/") + ";window.__PS__=" + json.dumps(data).replace("</", "<\\/") +
            ";window.__CLAUDE__=" + json.dumps({"ready": claude_cli.claude_ready()}) +
            ";</script>\n" + settings_page.fill_script(SCRIPT).replace("/*__MANUAL__*/", manual_profile.JS) + "</body></html>")


CSS = """<style>
.pmoved{margin:0 14px 16px;font-size:13.5px}
.pstrip{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:10px 0 0;font-size:13px}
.pchip{display:inline-flex;gap:5px;align-items:baseline;border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:3px 11px;color:var(--muted)}
.pchip b{color:var(--ink);font-weight:600}
.pchip::before{content:"✓";color:var(--good);font-weight:700}
.pchip.warn::before{content:"!";color:var(--warn)}
.pmiss{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:baseline;flex-basis:100%;color:var(--muted)}
.pmiss a{color:var(--accent);font-weight:600}
.pmiss a+a::before{content:"·";color:var(--muted);margin-right:6px;font-weight:400}
.spad{padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.spad textarea,.spad input:not([type=checkbox]):not([type=file]),.spad select,.srow.stack select{width:100%;min-width:0;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit;color:var(--ink)}
.spad textarea{min-height:5.5em;resize:vertical}
.spad .row,.sgroup .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.spad .note,.pnote{color:var(--muted);font-size:12.5px;margin:0}
.lf{display:flex;flex-direction:column;gap:16px}
.lf h4{margin:0 0 2px;font-size:14px;font-weight:600}
.lf .lfsec{display:flex;flex-direction:column;gap:7px;min-width:0}
.lfchips{display:flex;flex-wrap:wrap;gap:6px;min-width:0}
.lfchip{display:inline-flex;align-items:center;gap:2px;max-width:100%;border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:2px 4px 2px 11px;font-size:13.5px;line-height:1.5}
.lfchip span{overflow-wrap:anywhere}
.lfchip.occ{border-style:dashed}
.lfchip small{color:var(--muted);margin-left:5px}
.lfchip button{flex:none;border:0;background:none;color:var(--muted);cursor:pointer;font:inherit;font-size:15px;line-height:1;width:24px;height:24px;border-radius:50%}
.lfchip button:hover,.lfchip button:focus-visible{background:var(--bar,var(--line));color:var(--ink)}
.lfadd{display:flex;gap:6px;min-width:0}
.lfadd input{flex:1}
.lfadd .btn{flex:none}
.pnote{margin:8px 14px 0}
.sctl input[type=text],.sctl input[type=url]{width:240px;max-width:100%;height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit}
.srow.stack input[type=text]{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;width:100%;min-width:0}
.srow .drop{width:100%}
.expcard{border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--surface);display:flex;flex-direction:column;gap:6px}
.exprow{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,2fr) minmax(0,1fr);gap:6px}
.hledit label.f{font-weight:600;font-size:13px;display:block;margin-top:4px}
#abBody .sgsec:first-child{margin-top:18px}
.sgroup>.hlbanner{border-radius:0}
@media (max-width:720px){.exprow{grid-template-columns:minmax(0,1fr)}.sctl input[type=text],.sctl input[type=url]{width:100%}}
</style>
"""

BODY = """<div class="wrap">
<header class="top">
  <div class="brandline">
    """ + report.MARK + """<h1 id="pgName">__NAME__'s profile</h1>
    <span class="fresh">About you: your resume, what you're looking for, and where you'd work</span>
  </div>
  <div class="tools" id="tools">
__TOOLS__  </div>
</header>
<div class="pstrip" id="pstrip" role="status" aria-live="polite"></div>
<div class="slayout atList" id="slayout">
  <nav class="snav" aria-label="My profile sections">__NAV__</nav>
  <div class="spanes">__PANES__</div>
</div>
</div>
<dialog class="sheet" id="qSheet" aria-labelledby="qTitle">
  <form method="dialog" id="qForm">
    <div class="qhead"><strong id="qTitle">Questions about your experience</strong><button class="btn" value="cancel" type="submit" id="qClose">Close</button></div>
    <div class="qbody">
      <p class="note" style="margin:10px 0 0">Your resume doesn't show these. Answer what's true and skip the rest. Answers are saved and reused for other jobs, and nothing is claimed more strongly than you put it.</p>
      <div id="qList"></div>
    </div>
    <div class="qfoot"><button class="btn primary" type="button" id="qGo">Save answers</button></div>
  </form>
</dialog>
"""

SCRIPT = r"""<script>
(function(){
/*__PRELUDE__*/
/*__ROUTER__*/
const PS0 = window.__PS__ || {};
let SET = PS0.settings || {};
let PROF = null, DRAFT = null, ING = {}, BOARD = null, HL = null, FACTS = [], TJ = {running: false}, AB = {reframings: []}, SUGG = [];
const lines = a => (a || []).join("\n");
const unlines = s => s.split("\n").map(x => x.trim()).filter(Boolean);
const nf = n => (n || 0).toLocaleString();
const when = s => { const d = new Date(s); return isNaN(d) ? String(s || "").replace("T", " ") : d.toLocaleString([], {dateStyle: "medium", timeStyle: "short"}); };
const go = id => { history.pushState({fromList: false}, "", "#" + id); route(); scrollTo(0, 0); };
const jpost = (url, body) => fetch(url, {method: "POST", headers: H, body: JSON.stringify(body)}).then(r => r.json().then(d => ({ok: r.ok, d})));
const netErr = err => err instanceof TypeError ? "Couldn't save. Check the connection." : err.message;
const saved = (el, p) => p.then(({ok, d}) => { if (!ok) throw new Error(d.error || "Couldn't save."); return d; });
/*__THEME__*/
/*__HEADER__*/
/*__MANUAL__*/
const CL = window.__CLAUDE__ || {ready: true};  // false: Claude isn't connected; every Claude control explains instead of failing
const NEED_CL = `Needs Claude. Connect it under Settings, then Get started.`;
if (!CL.ready && $("psAutoRate")) $("psAutoRate").hidden = true;   // (no Claude: nothing is rated automatically)

// ---- the name (page title, header, profile menu)
function showName(n){
  $("pgName").textContent = n + "'s profile"; document.title = n + "'s profile";
  if (document.activeElement !== $("ab-name")) $("ab-name").value = n;
}
function onPeople(d){ const me = d.people.find(p => p.id === d.current); if (me) showName(me.name); }
$("ab-name").addEventListener("change", e => {
  const el = e.target, n = el.value.trim();
  if (!n) { onPeople({people: PEOPLE, current: curPerson}); saveState(el, "Type a name first.", true); return; }
  saveState(el, "Saving…");
  saved(el, jpost("/api/person/settings", {name: n, settings: {}})).then(() => { saveState(el, "Saved"); loadPeople(); })
    .catch(err => { onPeople({people: PEOPLE, current: curPerson}); saveState(el, netErr(err), true); });
});

// ---- status strip: what's read, approved and rated, and what's missing
function drawStrip(){
  const chips = [], miss = [], a = PROF, d = DRAFT;
  if (ING.running) chips.push(["warn", "Resume", "being read…"]);
  else if (a && a._manual && !d) chips.push(["ok", "Profile", "filled in by you " + when(a._approved || a._created)]);
  else if (a || d) chips.push(["ok", "Resume", "read " + when((a && (a._created || a._approved)) || (d && d._created))]);
  else { chips.push(["warn", "Resume", CL.ready ? "not uploaded" : "no profile yet"]); miss.push({go: "resume", text: CL.ready ? "Upload your resume" : "Fill in your profile"}); }
  if (d && !ING.running) { chips.push(["warn", "Profile", "new draft to approve"]); miss.push({go: "about", text: "Approve your new profile"}); }
  else if (a && a._manual) {}   // (said above)
  else if (a) chips.push(["ok", "Profile", "approved"]);
  else chips.push(["warn", "Profile", "not approved"]);
  if (BOARD) {
    chips.push([BOARD.jobs ? "ok" : "warn", "Board", BOARD.jobs ? `${nf(BOARD.jobs)} jobs · ${nf(BOARD.rated)} rated by Claude` : "no jobs yet"]);
    if (!BOARD.jobs && a) miss.push({href: "/", text: "Find new jobs to fill your board"});
  }
  if (a && HL && HL.highlights && !HL.confirmed) miss.push({go: "highlights", text: a._manual ? "Check the facts in your profile" : "Check the facts we pulled from your resume"});
  const wps = SET.workplaces || ["onsite", "hybrid", "remote"];
  if (!(SET.home_zip || "").trim() && wps.some(w => w !== "remote")) miss.push({href: "/#filters", text: "Add your home ZIP in the board's Filters (without one, Siftwell uses its built-in Washington, DC area list)"});
  if (ING.error) miss.push({go: "resume", text: "Fix the resume problem"});
  $("pstrip").innerHTML = chips.map(([k, t, v]) => `<span class="pchip ${k}"><b>${t}</b> ${esc(v)}</span>`).join("") +
    `<span class="pmiss">${miss.length ? "Missing: " + miss.map(m => m.go ? `<a href="#${m.go}" data-go="${m.go}">${esc(m.text)}</a>` : `<a href="${m.href}">${esc(m.text)}</a>`).join("") : "Nothing missing."}</span>`;
}
$("pstrip").addEventListener("click", e => { const a = e.target.closest("[data-go]"); if (!a) return; e.preventDefault(); go(a.dataset.go); });
$("abBody").addEventListener("click", e => { const a = e.target.closest("[data-go]"); if (a) { e.preventDefault(); go(a.dataset.go); } });
let boardT = null;
function loadBoard(){ return fetch("/api/profile/board").then(r => r.json()).then(b => { BOARD = b; drawStrip(); }).catch(() => {}); }
const soonBoard = () => { clearTimeout(boardT); boardT = setTimeout(loadBoard, 8000); };  // a board rebuild takes a few seconds

// ---- Resume: upload / replace, last read, reading progress
let ingestSeen = false;
const STAGE = {get: ["Getting the file…", 12], read: ["Reading the text…", 35], build: ["Claude is building your profile…", 70]};
function drawResume(){
  const a = PROF, d = DRAFT, since = ING.started ? Math.max(0, Math.round((Date.now() - new Date(ING.started)) / 1000)) : 0;
  const st = STAGE[ING.stage] || ["Reading your resume…", 20];
  $("resumeState").textContent = ING.running ? `${st[0]} This takes about a minute${since > 5 ? ` (${since}s so far)` : ""}.`
    : ING.error ? "Couldn't use that resume: " + ING.error
    : d ? `New resume read: ${d._source_file || "resume"}, ${when(d._created)}. Check it under About you and approve it to use it.`
    : a && a._manual ? `Active: filled in by hand, ${when(a._approved)}.` + (CL.ready ? " Claude is connected now: upload your resume above and Claude will read it to improve this profile." : "")
    : a ? `Active: ${a._source_file || "resume"}, read ${when(a._created || a._approved)}, approved ${when(a._approved)}. Upload a new one to replace it.`
    : CL.ready ? "No resume uploaded yet. Jobs are scored against the profile set up earlier." : "No profile yet. Fill in the form below to tell Siftwell what to look for.";
  $("resProg").hidden = !ING.running; $("resBar").style.width = st[1] + "%";
  $("resPick").hidden = $("gdocForm").hidden = !!ING.running || !CL.ready;
  $("resNoClaude").hidden = CL.ready;
  drawManual();
}
function loadProfile(){
  return fetch("/api/profile").then(r => r.json()).then(p => {
    PROF = p.active; DRAFT = p.draft; ING = p.ingest || {};
    drawResume(); loadLF(); drawStrip();
    if (!$("abBody").contains(document.activeElement)) drawAbout();
    drawFacts(); $("generalQs").disabled = !PROF || !CL.ready;
    clearTimeout(loadProfile.t);
    if (ING.running) { ingestSeen = true; loadProfile.t = setTimeout(loadProfile, 2500); }
    else if (ingestSeen) { ingestSeen = false; if (DRAFT) go("about"); }
  }).catch(() => {});
}
function sendResume(body){
  $("resumeState").textContent = "Uploading…";
  jpost("/api/resume", body).then(({ok, d}) => { if (!ok) $("resumeState").textContent = d.error || "Upload failed."; else { ingestSeen = true; setTimeout(loadProfile, 600); } })
    .catch(() => { $("resumeState").textContent = "Couldn't reach Siftwell. Check the connection."; });
}
function readFile(file){
  if (!file) return;
  if (file.size > 15 * 1024 * 1024) { $("resumeState").textContent = "That file is over 15 MB."; return; }
  const fr = new FileReader();
  fr.onload = () => sendResume({filename: file.name, data_b64: String(fr.result).split(",")[1] || ""});
  fr.readAsDataURL(file);
}
$("resumeFile").addEventListener("change", e => readFile(e.target.files[0]));
["dragenter", "dragover"].forEach(ev => $("drop").addEventListener(ev, e => { e.preventDefault(); $("drop").classList.add("over"); }));
["dragleave", "drop"].forEach(ev => $("drop").addEventListener(ev, e => { e.preventDefault(); $("drop").classList.remove("over"); }));
$("drop").addEventListener("drop", e => readFile(e.dataTransfer.files[0]));
$("gdocForm").addEventListener("submit", e => { e.preventDefault(); const u = $("gdocUrl").value.trim(); if (u) sendResume({gdoc_url: u}); });

// ---- Resume without Claude: the "Fill in my profile myself" form (manual_profile.py). Shown straight away when there is no
// profile yet and Claude isn't connected; otherwise behind a link, since saving it replaces the current profile.
let manualOpen = false, manualMounted = false;
function drawManual(){
  const has = !!(PROF || DRAFT), busy = !!ING.running;
  const show = !busy && (manualOpen || (!CL.ready && !has));
  $("manualWrap").hidden = !show;
  $("manualLink").hidden = show || busy;
  $("manualOpen").textContent = !has ? "Fill in my profile myself instead" : PROF && PROF._manual ? "Edit my hand-filled profile" : "Replace my profile by filling it in myself";
  if (show && !manualMounted) {
    manualMounted = true;
    if (PROF && PROF._manual) ManualProfile.load(PROF);
    ManualProfile.mount($("manualRoot"), {button: true, name: PS0.name, onSaved: () => { manualOpen = false; loadProfile().then(() => { soonBoard(); go("about"); }); }});
  }
}
$("manualOpen").addEventListener("click", () => {
  if ((PROF || DRAFT) && !(PROF && PROF._manual) && !confirm("Saving the form replaces your current profile (the one Claude read). Continue?")) return;
  manualOpen = true; drawManual();
});

// ---- About you: the structured profile. An approved profile saves as you edit; a new draft waits for Approve.
const LISTS = [["clearances", "Clearances", "One per line, e.g. Secret (active)"], ["education", "Education", "One per line"],
               ["certifications", "Certifications and licenses", "One per line"], ["skills", "Skills", "One per line"], ["languages", "Languages", "One per line"]];
const gblock = (title, foot, inner) => `<section class="sgsec"><h3 class="sgtitle">${title}</h3><div class="sgroup spad">${inner}</div>${foot ? `<p class="sfoot">${foot}</p>` : ""}</section>`;
const expCard = e => `<div class="expcard" data-exp><div class="exprow"><input type="text" aria-label="Job title" placeholder="Title" data-f="title" value="${esc(e.title)}"><input type="text" aria-label="Employer" placeholder="Employer" data-f="employer" value="${esc(e.employer)}"><input type="text" aria-label="Dates" placeholder="Dates" data-f="dates" value="${esc(e.dates)}"></div>
  <textarea aria-label="What you did, one per line" data-f="highlights" rows="4" placeholder="What you did, one per line">${esc(lines(e.highlights))}</textarea><div class="row"><button type="button" class="btn sm" data-rmexp>Remove this role</button></div></div>`;
const refRow = (r, i) => `<div class="fact"><div><b>${esc(r.angle)}</b><div class="fl">Opens: ${esc((r.target_titles || []).join(", "))}<br>Based on: ${esc((r.evidence || []).join(" / "))}</div></div><button type="button" data-rmref="${i}">Remove</button></div>`;
function drawAbout(){
  const p = DRAFT || PROF, box = $("abBody");
  $("abDraft").hidden = !DRAFT || !!ING.running;
  if (!p) { box.innerHTML = CL.ready ? `<p class="note pnote">No profile yet. <a href="#resume" data-go="resume">Upload your resume</a> and Claude drafts one here for you to check.</p>` : `<p class="note pnote">No profile yet. <a href="#resume" data-go="resume">Fill in your profile</a> and it shows up here to fine-tune.</p>`; return; }
  AB = {reframings: (p.reframings || []).slice()};
  const ta = (k, label, rows, v) => `<textarea data-ab="${k}" rows="${rows}" aria-label="${label}">${esc(v)}</textarea>`;
  box.innerHTML =
    gblock("Summary", "Claude reads this when it rates a job and when it tailors a resume.", ta("summary", "Summary", 5, p.summary)) +
    gblock("Basics", "", `<div class="psgrid"><label>Location<input type="text" data-ab="location" value="${esc(p.location)}"></label><label>Years of experience<input type="number" min="0" max="70" data-ab="years_experience" value="${p.years_experience ?? ""}"></label></div>`) +
    LISTS.map(([k, t, ph]) => gblock(t, "", `<textarea data-ab="${k}" rows="${k === "skills" ? 6 : 3}" aria-label="${t}" placeholder="${ph}">${esc(lines(p[k]))}</textarea>`)).join("") +
    gblock("Experience", "", `<div id="abExp">${(p.experience || []).map(expCard).join("")}</div><div class="row"><button type="button" class="btn sm" id="abAddExp">+ Add a role</button></div>`) +
    gblock("Allowed reframings", "Honest ways to present your experience for other roles. Remove any you're not comfortable claiming.", `<div class="factlist" id="abRefr">${AB.reframings.map(refRow).join("") || `<div class="note">None.</div>`}</div>`) +
    gblock("Never claim", "Tailored resumes will never say these.", ta("hard_limits", "Never claim, one per line", 4, lines(p.hard_limits))) +
    gblock("True things your resume leaves out", "For example a certification in progress, a tool you use daily, or a project you led. Tailoring may use these.", ta("notes", "True things your resume leaves out", 3, p.notes || ""));
}
function collectAbout(){
  const q = k => $("abBody").querySelector(`[data-ab="${k}"]`);
  const out = {summary: q("summary").value, location: q("location").value, notes: q("notes").value, hard_limits: unlines(q("hard_limits").value)};
  LISTS.forEach(([k]) => out[k] = unlines(q(k).value));
  const y = q("years_experience").value; if (y !== "") out.years_experience = +y;
  out.experience = [...$("abBody").querySelectorAll("[data-exp]")].map(c => { const g = f => c.querySelector(`[data-f="${f}"]`).value; return {title: g("title"), employer: g("employer"), dates: g("dates"), highlights: unlines(g("highlights"))}; });
  out.reframings = AB.reframings;
  return out;
}
function saveAbout(){
  const el = $("abBody"); saveState(el, "Saving…");
  saved(el, jpost("/api/profile/edit", {edits: collectAbout()})).then(d => { PROF = d.profile; saveState(el, "Saved"); drawStrip(); soonBoard(); })
    .catch(err => saveState(el, netErr(err), true));
}
$("abBody").addEventListener("change", () => { if (!DRAFT) saveAbout(); });
$("abBody").addEventListener("click", e => {
  if (e.target.id === "abAddExp") { $("abExp").insertAdjacentHTML("beforeend", expCard({})); $("abExp").lastElementChild.querySelector("input").focus(); return; }
  if (e.target.closest("[data-rmexp]")) { e.target.closest("[data-exp]").remove(); if (!DRAFT) saveAbout(); return; }
  const rr = e.target.closest("[data-rmref]");
  if (rr) { AB.reframings.splice(+rr.dataset.rmref, 1); $("abRefr").innerHTML = AB.reframings.map(refRow).join("") || `<div class="note">None.</div>`; if (!DRAFT) saveAbout(); }
});
$("rvApprove").addEventListener("click", () => {
  const edits = collectAbout();
  $("rvApprove").disabled = true; $("abNote").textContent = "Approving…";
  jpost("/api/profile/approve", {edits, rescore: true}).then(({ok, d}) => {
    if (!ok) { $("abNote").textContent = d.error || "Couldn't approve."; return; }
    $("abNote").innerHTML = `Approved. Your board is updating with it (about 15 minutes); <a href="/">follow it on the board</a>.`;
    loadProfile(); soonBoard();
  }).catch(() => { $("abNote").textContent = "Couldn't reach Siftwell."; }).finally(() => { $("rvApprove").disabled = false; });
});
$("rvDiscard").addEventListener("click", () => jpost("/api/profile/discard", {}).then(() => { $("abNote").textContent = ""; loadProfile(); }));

// ---- Job search and Target: every control saves on change
function fillOne(el){
  if (el.dataset.wp) { el.checked = (SET.workplaces || []).includes(el.dataset.wp); return; }
  const v = SET[el.dataset.ps];
  if (el.type === "checkbox") el.checked = !!v;
  else {
    if (el.tagName === "SELECT" && v != null && ![...el.options].some(o => o.value === String(v))) el.add(new Option(String(v), String(v)));
    el.value = v == null ? "" : String(v);
  }
}
const fillSettings = () => {
  document.querySelectorAll("[data-ps],[data-wp]").forEach(fillOne);
  const w = $("tgScopeWrap"); if (w && $("ps-target_scope").value === "ai") w.hidden = false;
};
function savePS(el, settings){
  saveState(el, "Saving…");
  return saved(el, jpost("/api/person/settings", {settings})).then(d => {
    SET = Object.assign({}, SET, d.settings); saveState(el, "Saved"); drawStrip(); soonBoard();
    if (d.interpreting) { TJ = {running: true}; drawTarget(); setTimeout(pollTarget, 1500); }
  }).catch(err => { (el.dataset.wp ? document.querySelectorAll("[data-wp]") : [el]).forEach(fillOne); saveState(el, netErr(err), true); });
}
document.querySelector(".spanes").addEventListener("change", e => {
  const el = e.target.closest("[data-ps],[data-wp]"); if (!el) return;
  if (el.dataset.wp) { savePS(el, {workplaces: [...document.querySelectorAll("[data-wp]")].filter(x => x.checked).map(x => x.dataset.wp)}); return; }
  savePS(el, {[el.dataset.ps]: el.type === "checkbox" ? el.checked : el.value});
});
// ---- What Siftwell looks for: the sheet behind the free Relevance score (chips; every change saves and re-checks the board)
let LF = null, lfPoll = null;
const lfChip = (kind, x, extra) => `<span class="lfchip${kind === "occ" ? " occ" : ""}" title="${esc((LF.src_words || {})[x.src] || extra || "")}"><span>${esc(x.t)}${kind === "occ" ? `<small>+ ${nf(x.names)} other names</small>` : ""}</span><button type="button" data-lfrm="${kind}" data-v="${esc(kind === "occ" ? x.code : x.t)}" aria-label="Remove ${esc(x.t)}">×</button></span>`;
const lfAdd = (kind, ph, label) => `<form class="lfadd" data-lfadd="${kind}"><input type="text" maxlength="80" placeholder="${esc(ph)}" aria-label="${esc(label)}"><button class="btn sm" type="submit">Add</button></form>`;
function drawLF(){
  const r = $("lfRoot"); if (!r || !LF) return;
  const sec = (title, help, chips, add) => `<div class="lfsec"><h4>${title}</h4><p class="note">${help}</p>${chips ? `<div class="lfchips">${chips}</div>` : ""}${add || ""}</div>`;
  const occNote = "A whole occupation from the O*NET list: every name employers use for it counts.";
  const lr = LF.learned || {up: [], down: []};
  r.innerHTML =
    `<div class="lfsec"><h4><label for="lfRecent">Your most recent job title</label></h4><p class="note">This one counts most. ${LF.recent ? "" : "<b>Add it</b> so Siftwell can tell which jobs are close to your work."}</p>
      <form class="lfadd" id="lfRecentForm"><input type="text" id="lfRecent" maxlength="80" value="${esc(LF.recent)}" placeholder="e.g. Registered Nurse, Electrician, Office Manager"><button class="btn sm" type="submit">Save</button></form></div>` +
    sec("Job titles you’re looking for", "The same job under the names employers use, and other titles you’d take.",
        LF.same.map(x => lfChip("title", x)).join("") + LF.occs_same.map(x => lfChip("occ", x, occNote)).join(""), lfAdd("title", "Add a job title", "Add a job title")) +
    sec("One step up", "Senior, lead and supervisor versions of your titles already count. Add the titles you’d move up into.",
        LF.up.map(x => lfChip("title", x)).join(""), lfAdd("up", "Add a step-up title", "Add a step-up title")) +
    sec("Related roles", "Different jobs you could plausibly move into. They count for less than your own titles.",
        LF.related.map(x => lfChip("title", x)).join("") + LF.occs_related.map(x => lfChip("occ", x, occNote)).join(""), lfAdd("related", "Add a related role", "Add a related role")) +
    sec("Skills and tools", "Found in a posting’s text, each one adds a little.", LF.skills.map(x => lfChip("skill", x)).join(""), lfAdd("skill", "Add a skill or tool", "Add a skill or tool")) +
    (LF.past.length ? sec("Jobs you held before", "From your profile. They count a little.", LF.past.map(x => lfChip("title", x)).join("")) : "") +
    `<div class="lfsec"><h4><label for="lfField">Your field</label></h4><form class="lfadd" id="lfFieldForm"><input type="text" id="lfField" maxlength="60" value="${esc(LF.field)}" placeholder="e.g. Healthcare, Construction, Education"><button class="btn sm" type="submit">Save</button></form></div>` +
    `<div class="lfsec"><h4>Learned from what you save and hide</h4><p class="note">${lr.n_up || lr.n_down
        ? `Jobs with titles like the ${nf(lr.n_up)} you saved or applied to move up a little${lr.up.length ? ` (${esc(lr.up.slice(-4).join(", "))})` : ""}; titles like the ${nf(lr.n_down)} you hid move down a little${lr.down.length ? ` (${esc(lr.down.slice(-4).join(", "))})` : ""}. Never more than a few points.`
        : "Nothing yet. Saving a job nudges similar titles up a little; hiding one nudges similar titles down. Never more than a few points."}</p>
      <div class="row">${lr.n_up || lr.n_down ? `<button class="btn ghost sm" type="button" data-lfreset="learning">Forget what was learned</button>` : ""}
      <button class="btn ghost sm" type="button" data-lfreset="sheet">Start this list over</button>
      ${LF.claude_ready ? `<button class="btn sm" type="button" id="lfSuggest"${LF.can_suggest && !(LF.job || {}).running ? "" : " disabled"}>${(LF.job || {}).running ? "Claude is thinking…" : "Ask Claude for more titles"}</button>` : ""}</div>
      <p class="note" id="lfMsg" role="status" aria-live="polite">${LF.claude_ready ? ((LF.job || {}).error ? esc(LF.job.error) : "Asking Claude is one small request.") : "Connect Claude to get more title ideas → Settings → Get started. The list works without it."}</p></div>`;
}
function loadLF(){
  return fetch("/api/lookfor").then(r => r.json()).then(d => {
    LF = d; drawLF();
    clearTimeout(lfPoll); if ((d.job || {}).running) lfPoll = setTimeout(loadLF, 2500);
  }).catch(() => { const r = $("lfRoot"); if (r && !LF) r.innerHTML = `<p class="note">Couldn't load. Check the connection.</p>`; });
}
function lfOp(op){
  const m = $("lfMsg"); if (m) m.textContent = "Saving…";
  return jpost("/api/lookfor", {op}).then(({ok, d}) => {
    if (!ok) { if ($("lfMsg")) $("lfMsg").textContent = d.error || "Couldn't save."; return; }
    LF = d.sheet; drawLF(); if ($("lfMsg")) $("lfMsg").textContent = "Saved. Your board is re-checking."; soonBoard();
    if ((LF.job || {}).running) lfPoll = setTimeout(loadLF, 2500);
  }).catch(() => { if ($("lfMsg")) $("lfMsg").textContent = "Couldn't save. Check the connection."; });
}
$("lfRoot").addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target, inp = f.querySelector("input"), v = inp.value.trim();
  if (f.id === "lfRecentForm") { lfOp({recent: v}); return; }
  if (f.id === "lfFieldForm") { lfOp({field: v}); return; }
  if (v && f.dataset.lfadd) lfOp({add: f.dataset.lfadd, text: v});
});
$("lfRoot").addEventListener("click", e => {
  const rm = e.target.closest("[data-lfrm]");
  if (rm) { lfOp(rm.dataset.lfrm === "occ" ? {remove: "occ", code: rm.dataset.v} : {remove: rm.dataset.lfrm, text: rm.dataset.v}); return; }
  const rs = e.target.closest("[data-lfreset]");
  if (rs) { if (rs.dataset.lfreset !== "sheet" || confirm("Start the list over from your profile? The titles and skills you added or removed here are forgotten.")) lfOp({reset: rs.dataset.lfreset}); return; }
  if (e.target.closest("#lfSuggest")) {
    jpost("/api/lookfor/suggest", {}).then(({ok, d}) => { if (!ok) { $("lfMsg").textContent = d.error || "Couldn't ask Claude."; return; } LF.job = {running: true}; drawLF(); lfPoll = setTimeout(loadLF, 2500); });
  }
});
function drawTarget(){
  $("tgState").textContent = TJ.running ? "Claude is working out which jobs fit this target…"
    : (TJ.needs_claude || (!CL.ready && SET.target_text && !SET.target_summary)) ? "Your target is saved. It starts working once Claude is connected (Settings, then Get started)."
    : TJ.error ? "Couldn't interpret the target: " + TJ.error
    : SET.target_text ? (SET.target_summary ? `Tab "${SET.target_name || "Target"}": ${SET.target_summary}` + (SET.target_any_title ? " (any job title)" : ` (titles like: ${(SET.target_keywords || []).slice(0, 8).join(", ")}…)`) : "")
    : "No target set.";
}
function pollTarget(){
  fetch("/api/people").then(r => r.json()).then(d => {
    SET = Object.assign({}, SET, d.settings); TJ = d.target_job || {running: false}; drawTarget();
    if (TJ.running) setTimeout(pollTarget, 3000);
  }).catch(() => {});
}
if (!CL.ready) { $("tgSuggest").disabled = true; $("tgSuggest").title = NEED_CL; $("tgSuggest").insertAdjacentHTML("afterend", ` <span class="note">${NEED_CL}</span>`); }
$("tgSuggest").addEventListener("click", () => {
  $("tgSuggest").disabled = true; $("tgSugg").innerHTML = `<div class="note">Claude is reading your resume and the job market… (about a minute)</div>`;
  const poll = () => fetch("/api/target/suggest").then(r => r.json()).then(s => {
    if (s.running) return setTimeout(poll, 3000);
    $("tgSuggest").disabled = false;
    if (s.error) { $("tgSugg").innerHTML = `<div class="note">${esc(s.error)}</div>`; return; }
    SUGG = s.options || [];
    $("tgSugg").innerHTML = SUGG.map((o, i) => `<div class="fact"><div><b>${esc(o.name)}</b> · ${esc(o.pay)} · odds now: ${esc(o.odds_now)}<div>${esc(o.why)}</div><div class="fl">Prep: ${esc(o.prep)}</div></div><button type="button" data-use="${i}">Use this</button></div>`).join("");
  });
  jpost("/api/target/suggest", {}).then(poll);
});
$("tgSugg").addEventListener("click", e => {
  const b = e.target.closest("button[data-use]"); if (!b) return;
  const o = SUGG[+b.dataset.use], s = {target_text: o.target_text, target_scope: o.scope};
  if (o.prep && o.prep.toLowerCase() !== "none" && !$("ps-prep_text").value) s.prep_text = o.prep;
  Object.entries(s).forEach(([k, v]) => $("ps-" + k).value = v);
  savePS($("ps-target_text"), s);
});

// ---- Highlights & answers: degrees, licenses and the answers you've given
let hlEditing = false;
const LVL = {associate: "Associate's", bachelor: "Bachelor's", master: "Master's", doctorate: "PhD", jd: "JD", md: "MD"};
function loadHL(){
  return fetch("/api/highlights").then(r => r.json()).then(d => { HL = d; drawHL(); drawStrip(); if (d.rescoring) setTimeout(loadHL, 5000); }).catch(() => {});
}
function drawHL(){
  if (!HL) return;
  const h = HL.highlights;
  if (!h) { $("hlCards").innerHTML = `<div class="note">Nothing pulled yet. Upload your resume, or tap "Re-read my resume".</div>`; $("hlBanner").hidden = true; return; }
  const ed = new Set(HL.edited_fields || []), mark = k => ed.has(k) ? "<em>edited</em>" : "";
  const card = (k, title, body) => `<div class="hlcard"><div class="k">${title}${mark(k)}</div><div class="v">${body}</div></div>`;
  const m = h.management || {}, c = h.clearance || {};
  $("hlCards").innerHTML = [
    card("degrees", "Education", (h.degrees || []).length ? h.degrees.map(d => `<div><b>${esc(LVL[d.level] || d.level)}</b>${d.field ? " in " + esc(d.field) : ""}${d.school ? `<br><span class="note">${esc(d.school)}${d.year ? " · " + d.year : ""}${d.completed === false ? " · in progress" : ""}</span>` : ""}</div>`).join("") : "No degree listed"),
    card("licenses", "Licenses & certifications", (h.licenses || []).length ? h.licenses.map(l => `<div>${esc(l.name)}${l.kind === "license" ? " <span class='note'>(license)</span>" : ""}</div>`).join("") : "None listed"),
    card("years_experience", "Experience", h.years_experience != null ? `${h.years_experience} years` : "Not stated"),
    card("management", "People you manage", m.manages_people ? (m.direct_reports != null ? `${m.direct_reports} direct report${m.direct_reports === 1 ? "" : "s"}` : "Yes") + (m.note ? `<br><span class="note">${esc(m.note)}</span>` : "") : "None"),
    card("clearance", "Clearance", c.level ? esc(c.level.replace(/_/g, " ").toUpperCase()) + (c.active === false ? " (inactive)" : "") : "None"),
    card("languages", "Languages", (h.languages || []).map(x => esc(x.language) + (x.level ? ` <span class="note">(${esc(x.level)})</span>` : "")).join(", ") || "Not listed"),
  ].join("");
  $("hlBanner").hidden = !!HL.confirmed;
  $("hlMsg").textContent = HL.rescoring ? "Re-checking jobs against these… (about a minute; reload after)" : HL.confirmed ? "Confirmed " + String(HL.confirmed).replace("T", " ") : "";
}
function drawHLEdit(){
  const h = (HL && HL.highlights) || {}, o = (HL && HL.options) || {};
  const lvOpts = v => (o.levels || []).map(x => `<option value="${x.id}"${x.id === v ? " selected" : ""}>${esc(x.label)}</option>`).join("");
  const degRow = d => `<div class="hlrow" data-deg><select aria-label="Degree">${lvOpts(d.level || "bachelor")}</select><input aria-label="Field" placeholder="Field, e.g. Economics" value="${esc(d.field || "")}"><input aria-label="School" placeholder="School" value="${esc(d.school || "")}"><button type="button" class="btn sm" data-rm>Remove</button></div>`;
  const licRow = l => `<div class="hlrow lic" data-lic><input aria-label="Name" placeholder="e.g. PMP, CPA, RN" value="${esc(l.name || "")}"><select aria-label="Kind"><option value="cert"${l.kind !== "license" ? " selected" : ""}>Certification</option><option value="license"${l.kind === "license" ? " selected" : ""}>License</option></select><button type="button" class="btn sm" data-rm>Remove</button></div>`;
  const m = h.management || {};
  $("hlEdit").innerHTML = `<label class="f">Degrees</label><div id="hlDegs">${(h.degrees || []).map(degRow).join("")}</div><button type="button" class="btn ghost sm" id="hlAddDeg" style="align-self:flex-start">+ Add a degree</button>
    <label class="f">Licenses and certifications</label><div id="hlLics">${(h.licenses || []).map(licRow).join("")}</div><button type="button" class="btn ghost sm" id="hlAddLic" style="align-self:flex-start">+ Add one</button>
    <div class="psgrid"><label>Years of experience<input id="hlYears" type="number" min="0" max="60" value="${h.years_experience ?? ""}"></label>
    <label>Direct reports right now<input id="hlReports" type="number" min="0" max="10000" value="${m.direct_reports ?? ""}"></label></div>
    <div class="row"><button type="button" class="btn primary" id="hlSave">Save and re-check jobs</button><button type="button" class="btn" id="hlCancel">Cancel</button></div>`;
  window.__degRow = degRow; window.__licRow = licRow;
}
function openHLEdit(){ hlEditing = true; drawHLEdit(); $("hlEdit").hidden = false; $("hlEdit").scrollIntoView({block: "nearest"}); }
$("hlEditBtn").addEventListener("click", openHLEdit); $("hlEditBtn2").addEventListener("click", openHLEdit);
$("hlEdit").addEventListener("click", e => {
  if (e.target.closest("[data-rm]")) { e.target.closest(".hlrow").remove(); return; }
  if (e.target.id === "hlAddDeg") { $("hlDegs").insertAdjacentHTML("beforeend", window.__degRow({})); return; }
  if (e.target.id === "hlAddLic") { $("hlLics").insertAdjacentHTML("beforeend", window.__licRow({})); return; }
  if (e.target.id === "hlCancel") { $("hlEdit").hidden = true; return; }
  if (e.target.id === "hlSave") {
    const degrees = [...$("hlDegs").querySelectorAll("[data-deg]")].map(r => { const [lv, f, sc] = r.querySelectorAll("select,input"); return {level: lv.value, field: f.value.trim(), school: sc.value.trim(), completed: true}; }).filter(d => d.level);
    const licenses = [...$("hlLics").querySelectorAll("[data-lic]")].map(r => { const [n, k] = r.querySelectorAll("input,select"); return {name: n.value.trim(), kind: k.value, active: true}; }).filter(l => l.name);
    const h = HL.highlights || {}, m = Object.assign({}, h.management || {});
    const rep = $("hlReports").value; m.direct_reports = rep === "" ? null : +rep; m.manages_people = (m.direct_reports || 0) > 0;
    const edits = {degrees, licenses, management: m};
    if ($("hlYears").value !== "") edits.years_experience = +$("hlYears").value;
    e.target.disabled = true;
    jpost("/api/highlights", {edits}).then(({ok, d}) => {
      e.target.disabled = false;
      if (!ok) { $("hlMsg").textContent = d.error || "Couldn't save."; return; }
      HL = d; $("hlEdit").hidden = true; drawHL(); setTimeout(loadHL, 5000); soonBoard();
    }).catch(() => { e.target.disabled = false; $("hlMsg").textContent = "Couldn't reach Siftwell."; });
  }
});
$("hlConfirm").addEventListener("click", () => jpost("/api/highlights", {confirm: true}).then(({d}) => { HL = d; drawHL(); drawStrip(); }));
if (!CL.ready) { $("hlRefresh").textContent = "Re-check from my profile"; $("generalQs").title = NEED_CL; $("generalQs").insertAdjacentHTML("afterend", `<span class="note">${NEED_CL}</span>`); }
$("hlRefresh").addEventListener("click", () => { $("hlMsg").textContent = CL.ready ? "Claude is re-reading your resume… (about a minute)" : "Re-checking your profile…"; jpost("/api/highlights/refresh", {}).then(() => setTimeout(loadHL, 45000)); });

// answers you've given (also asked for when you tailor a resume)
const LV = {yes: "Yes", some: "Some", no: "No"};
const loadFacts = () => fetch("/api/facts").then(r => r.json()).then(d => { FACTS = d.facts || []; drawFacts(); return FACTS; });
function drawFacts(){
  $("factCount").textContent = FACTS.length ? `${FACTS.length} answer${FACTS.length === 1 ? "" : "s"}` : "";
  $("factList").innerHTML = FACTS.length ? FACTS.slice().reverse().map(f => `<div class="fact"><div><b>${esc(f.requirement)}</b> · ${LV[f.level] || ""}${f.answer ? ": " + esc(f.answer) : ""}
    ${f.polished ? `<div class="pol" data-pid="${esc(f.id)}">Resume wording: <span>${esc(f.polished)}</span> <button type="button" class="linkbtn" data-edit="${esc(f.id)}">Edit</button></div>` : ""}
    <div class="fl">${esc(f.context || "")} · ${esc(f.date || "")}</div></div><button type="button" data-del="${esc(f.id)}">Remove</button></div>`).join("")
    : `<div class="note">Nothing yet. Tap "Tailor my resume" on a job, or answer general questions.</div>`;
}
$("factList").addEventListener("click", e => {
  const ed = e.target.closest("button[data-edit]");
  if (ed) {
    const box = ed.closest(".pol"), cur = box.querySelector("span").textContent;
    box.innerHTML = `<textarea style="width:100%;min-height:3.5em">${esc(cur)}</textarea><button type="button" class="linkbtn" data-save="${esc(ed.dataset.edit)}">Save</button>`;
    return;
  }
  const sv = e.target.closest("button[data-save]");
  if (sv) {
    const text = sv.closest(".pol").querySelector("textarea").value;
    jpost("/api/facts/polish", {id: sv.dataset.save, polished: text}).then(({d}) => { FACTS = d.facts; drawFacts(); });
    return;
  }
  const b = e.target.closest("button[data-del]"); if (!b) return;
  jpost("/api/facts/delete", {id: b.dataset.del}).then(({d}) => { FACTS = d.facts; drawFacts(); });
});
let qCtx = null;
function qWait(msg){ $("qList").innerHTML = `<div class="qwait">${esc(msg)}</div>`; $("qGo").disabled = true; }
function drawQuestions(qs){
  const prev = Object.fromEntries(FACTS.map(f => [f.requirement.toLowerCase(), f]));
  $("qList").innerHTML = qs.map((q, i) => { const p = q.fact_id ? null : prev[q.requirement.toLowerCase()];
    return `<div class="q" data-i="${i}" data-level="${p ? p.level : ""}">
      <div class="qreq">${esc(q.requirement)}${q.fact_id ? " · follow-up" : ""}</div>${q.earlier ? `<div class="qwhy">You said before: ${esc(q.earlier)}</div>` : ""}<div class="qtext">${esc(q.question)}</div><div class="qwhy">${esc(q.why || "")}</div>
      <div class="ans" role="group" aria-label="Answer">${Object.entries(LV).map(([k, v]) => `<button type="button" data-lv="${k}" aria-pressed="${p && p.level === k}">${v}</button>`).join("")}</div>
      <textarea aria-label="Details" placeholder="${esc(q.hint)}">${p ? esc(p.answer) : ""}</textarea></div>`; }).join("");
  $("qGo").disabled = false;
}
$("qList").addEventListener("click", e => {
  const b = e.target.closest(".ans button"); if (!b) return;
  const q = b.closest(".q"), on = b.getAttribute("aria-pressed") !== "true";
  q.querySelectorAll(".ans button").forEach(x => x.setAttribute("aria-pressed", "false"));
  b.setAttribute("aria-pressed", on); q.dataset.level = on ? b.dataset.lv : "";
});
function collectAnswers(){
  return [...$("qList").querySelectorAll(".q")].map(el => { const q = qCtx.questions[+el.dataset.i];
    return {requirement: q.requirement, question: q.question, fact_id: q.fact_id || "", level: el.dataset.level || (el.querySelector("textarea").value.trim() ? "yes" : ""), answer: el.querySelector("textarea").value.trim()}; })
    .filter(a => a.level || a.answer);
}
function fetchQuestions(){
  const poll = () => fetch("/api/questions/general").then(r => r.json()).then(s => s.running ? new Promise(r => setTimeout(r, 2500)).then(poll) : s);
  return fetch("/api/questions/general").then(r => r.json()).then(s => {
    if (!s.missing && !s.running && !s.error) return s;
    if (s.running) return poll();
    return jpost("/api/questions", {}).then(poll);
  });
}
$("generalQs").addEventListener("click", () => {
  qCtx = {questions: [], context: ""};
  qWait("Claude is working out what your target roles usually ask for that your resume doesn't show… (about a minute)");
  if (!$("qSheet").open) $("qSheet").showModal();
  Promise.all([loadFacts(), fetchQuestions()]).then(([, s]) => {
    if (!$("qSheet").open) return;
    if (s.error) { qWait("Couldn't get questions: " + s.error); qCtx.questions = []; return; }
    qCtx.questions = s.questions || []; qCtx.context = s.context || "";
    if (!qCtx.questions.length) { qWait("Nothing important seems to be missing for your target roles."); return; }
    drawQuestions(qCtx.questions);
  }).catch(() => qWait("Lost contact with Siftwell. Check the connection and try again."));
});
$("qGo").addEventListener("click", () => {
  const answers = collectAnswers(); $("qGo").disabled = true;
  (answers.length ? jpost("/api/answers", {answers, context: qCtx.context}).then(({d}) => d) : Promise.resolve({}))
    .then(d => { if (d.facts) { FACTS = d.facts; drawFacts(); } $("qSheet").close(); })
    .catch(() => { $("qGo").disabled = false; });
});

// ---- Companies: lists watched, companies added, adding by link
function loadCompanies(){
  return fetch("/api/companies/mine").then(r => r.json()).then(d => {
    $("coCount").textContent = d.watched ? `Siftwell watches ${nf(d.watched)} employer${d.watched === 1 ? "" : "s"} for you. ` : "";
    $("coOwn").innerHTML = d.own.length ? d.own.slice(0, 40).map(c => `<div class="fact"><div><b>${esc(c.name)}</b><div class="fl">${esc(c.ats)}${c.everyone ? " · everyone" : " · this profile"}</div></div></div>`).join("") + (d.own.length > 40 ? `<div class="note">And ${nf(d.own.length - 40)} more. The Catalog page lists them all.</div>` : "") : `<div class="note">None yet. Paste a careers link above.</div>`;
  }).catch(() => { $("coOwn").innerHTML = `<div class="note">Couldn't load. Check the connection.</div>`; });
}
$("coAddForm").addEventListener("submit", e => {
  e.preventDefault();
  $("coMsg").textContent = "Checking that link…";
  jpost("/api/companies/add", {url: $("coUrl").value, name: $("coName").value, scope: $("coScope").value}).then(({ok, d}) => {
    if (!ok) { $("coMsg").textContent = d.error || "Couldn't add it."; return; }
    $("coMsg").textContent = `${d.existing ? "Already tracked; now on your list" : "Added"}: ${d.name} (${d.open_jobs} open jobs on its board). ` + (d.fetching ? "Fetching its jobs now; they'll appear on the board when the update bar finishes." : "An update is running; its jobs arrive with the next update.");
    $("coUrl").value = ""; $("coName").value = ""; loadCompanies(); soonBoard();
  }).catch(() => { $("coMsg").textContent = "Couldn't reach Siftwell. Check the connection."; });
});

fillSettings(); drawTarget(); drawStrip(); drawResume();
loadProfile(); loadBoard(); loadHL(); loadFacts(); loadCompanies(); pollTarget(); loadPeople();
})();
</script>
"""
