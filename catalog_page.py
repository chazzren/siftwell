"""The Employers page (GET /catalog; called "Employers" everywhere people see it): the household's shared catalog of
companies and listings.

Same two-pane layout as /settings (settings_page.CSS): a list of sections on the left, the selected one on the
right, chosen by the URL hash (/catalog#listings); at phone width a drill-down with a "‹ Catalog" back control.
Sections: Companies (add by careers link, pause, remove, fetch now), Listings (server-side pages), Runs & updates
(history, the automatic-update control (autoupdate.py), Fetch everything now), Rating (per person; opens the board's Re-rate
panel), Find employers near me (employer_finder.py) and Share (catalog_share.py). Data comes from /api/catalog/*
(catalog_api.py); each section loads when first shown."""
import html
import json

import autoupdate
import getting_started
import people
import report
import settings_page

_SVG = settings_page._SVG
PANES = [
    ("companies", "Employers", '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 9h1M14 9h1M9 13h1M14 13h1M9 17h1M14 17h1"/>'),
    ("listings", "Job listings", '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>'),
    ("runs", "Finding new jobs", '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/><path d="M12 7v5l3 2"/>'),
    ("rating", "Ratings", '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'),
    ("find", "Find employers near me", '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/><path d="M11 8v6M8 11h6"/>'),
    ("share", "Share", '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/>'),
]
e = html.escape


def _head(cid, name):
    return (f'<div class="sphead"><a class="sback" href="/catalog" data-back>‹ Employers</a>'
            f'<div class="sprow"><h2 id="h-{cid}">{e(name)}</h2><span class="ssave" role="status" aria-live="polite"></span></div></div>')


BODIES = {
    "companies": """
<section class="sgsec"><h3 class="sgtitle">Add an employer</h3><div class="sgroup">
  <form class="srow stack" id="addForm">
    <input type="text" inputmode="url" autocapitalize="off" autocomplete="off" spellcheck="false" id="addUrl" placeholder="Paste the employer’s careers page link, e.g. careers.example.com" aria-label="Careers page link" required>
    <div class="cline"><input type="text" id="addName" placeholder="Name (optional)" aria-label="Company name (optional)" maxlength="60">
    <select id="addList" aria-label="Who it is for"></select><button class="btn primary" type="submit" id="addBtn">Add</button></div>
  </form></div>
  <p class="sfoot" id="addMsg" role="status" aria-live="polite">Siftwell works out how the employer lists its jobs, checks it can read them, adds it, then gets its jobs.</p></section>
<div class="livebar" id="fetchBar" role="status" aria-live="polite" hidden><div class="lbtop"><b id="fetchTitle">Working…</b></div><div class="pbar"><i id="fetchFill"></i></div></div>
<div class="ctools">
  <input type="search" id="coQ" placeholder="Search companies" aria-label="Search companies">
  <select id="coStatus" aria-label="Status"><option value="">Any status</option><option value="ok">OK</option><option value="suspect">Looks incomplete</option><option value="capped">Too many to read all</option><option value="error">Couldn’t be read</option><option value="paused">Paused</option><option value="new">Not checked yet</option></select>
  <select id="coListF" aria-label="Whose employers"><option value="">Every employer</option><option value="mine">Your employers</option><option value="other">Not yours</option></select>
  <select id="coAts" aria-label="Careers site type"><option value="">Any careers site type</option></select>
</div>
<p class="count" id="coCount">Loading…</p>
<p class="notice" id="factsNote" hidden></p>
<div class="clist" id="coRows"></div>
<div class="cmore"><button class="btn sm" type="button" id="coMore" hidden>Show more</button></div>""",
    "listings": """
<div class="ctools">
  <input type="search" id="lsQ" placeholder="Search title, company or location" aria-label="Search listings">
  <select id="lsState" aria-label="Open or closed"><option value="open">Open</option><option value="closed">Closed</option><option value="all">Open and closed</option></select>
  <select id="lsCo" aria-label="Company"><option value="">All companies</option></select>
  <select id="lsWho" aria-label="On whose board"><option value="">All listings</option><option value="any">On someone's board</option></select>
  <select id="lsSort" aria-label="Sort"><option value="last_seen">Last seen</option><option value="first_seen">Newest first</option><option value="company">Company</option><option value="title">Title</option></select>
</div>
<p class="count" id="lsCount">Loading…</p>
<div class="clist" id="lsRows"></div>
<div class="pager"><button class="btn sm" type="button" id="lsPrev">‹ Previous</button><span class="note" id="lsPage"></span><button class="btn sm" type="button" id="lsNext">Next ›</button></div>
<p class="sfoot">Under each listing: who it currently passes the filters for, and Claude's rating for them.</p>""",
    "runs": """
__AUTOUPDATE__
<section class="sgsec"><h3 class="sgtitle">Find new jobs now</h3><div class="sgroup">
  <div class="srow"><div class="slab"><span>Check every employer for new and removed jobs</span><small id="allEst">For everyone in the household. Claude then rates the new listings for each person (uses your Claude plan).</small></div><div class="sctl"><button class="btn primary sm" type="button" id="fetchAll">Find new jobs now</button></div></div>
  <div class="srow stack" id="allBar" role="status" aria-live="polite" hidden><div class="lbtop"><b id="allTitle"></b></div><div class="pbar"><i id="allFill"></i></div>
    <details class="rundet" id="allDet"><summary>Details</summary><div class="note mono" id="allLine"></div></details></div>
</div></section>
<section class="sgsec"><h3 class="sgtitle">History</h3><div class="clist" id="runRows"><p class="note">Loading…</p></div></section>""",
    "rating": """
<p class="note">For each person: how many catalog listings pass their filters, and how many Claude has rated. Rating happens on the board's Re-rate panel.</p>
<div id="rateCards"><p class="note">Loading…</p></div>""",
    "find": """
<div class="notice" id="fdClaude" hidden></div>
<form id="fdForm" class="sgsec">
  <h3 class="sgtitle">Where and what</h3>
  <div class="sgroup">
    <div class="srow"><div class="slab"><label for="fdLoc">Location</label><small>ZIP code or City, ST</small></div><div class="sctl cline"><input type="text" id="fdLoc" class="tin" maxlength="80" placeholder="ZIP code or City, ST"><input type="number" id="fdRad" class="tin num" min="5" max="150" aria-label="Radius in miles"><span class="note">mi</span></div></div>
    <div class="srow stack"><label for="fdFocus">Focus (optional)</label><input type="text" id="fdFocus" maxlength="300" placeholder="e.g. program management, healthcare, AI"></div>
  </div>
  <h3 class="sgtitle" style="margin-top:18px">Kinds of employers</h3>
  <div class="sgroup"><div class="srow stack"><div class="cats" id="fdCats"></div></div></div>
  <h3 class="sgtitle" style="margin-top:18px">Search size</h3>
  <div class="sgroup"><div class="srow stack">
    <div class="seg" id="fdSize" role="group" aria-label="Search size"><button type="button" data-v="small" aria-pressed="false">Small<span class="segn"> · ~30</span></button><button type="button" data-v="medium" aria-pressed="true">Medium<span class="segn"> · ~80</span></button><button type="button" data-v="large" aria-pressed="false">Large<span class="segn"> · ~150</span></button><button type="button" data-v="exhaustive" aria-pressed="false">Exhaustive</button></div>
    <p class="note" id="fdEst"></p>
    <div id="fdExh" hidden>
      <div class="cline"><label for="fdBudget">Budget</label><input type="number" id="fdBudget" class="tin num" min="5" max="200" step="1"><span class="note">Claude passes at most (5 to 200)</span></div>
      <p class="notice" id="fdExhEst" role="status" aria-live="polite"></p>
    </div>
    <div class="sbtns"><button class="btn primary" type="submit" id="fdStart">Start search</button></div>
    <p class="note" id="fdMsg" role="status" aria-live="polite"></p>
  </div></div>
</form>
<section class="sgsec" id="fdRun" hidden>
  <h3 class="sgtitle">Search</h3>
  <div class="sgroup"><div class="srow stack">
    <div class="lbtop"><b id="fdTitle"></b><span class="sbtns"><span class="cline" id="fdBudgetRow" hidden><label for="fdBudget2" class="note">Budget</label><input type="number" id="fdBudget2" class="tin num" min="5" max="200" step="1"><span class="note">passes</span></span><button class="btn sm" type="button" id="fdStop" hidden>Stop</button><button class="btn sm primary" type="button" id="fdResume" hidden>Resume</button></span></div>
    <div class="pbar" id="fdPassBar" hidden><i id="fdPassFill"></i></div>
    <div class="note" id="fdSub"></div>
    <div id="fdCatRows" class="fcats"></div>
    <div class="note mono" id="fdLines"></div>
  </div></div>
</section>
<section class="sgsec" id="fdReview" hidden>
  <h3 class="sgtitle">Employers Siftwell can read</h3>
  <div class="sgroup">
    <div class="srow stack"><div class="cline"><label for="fdList" class="note">Add for</label><select id="fdList"></select>
      <button class="btn primary sm" type="button" id="fdAdd">Add ticked</button><button class="btn sm" type="button" id="fdAddAll">Add all readable</button></div>
      <p class="note" id="fdAddMsg" role="status" aria-live="polite"></p></div>
    <div id="fdOk"></div>
  </div>
  <details class="fdet" id="fdBadWrap"><summary id="fdBadSum"></summary><p class="note" id="fdSysNote"></p><div id="fdBad"></div></details>
  <details class="fdet" id="fdKnownWrap"><summary id="fdKnownSum"></summary><div class="sgroup" id="fdKnown"></div></details>
</section>""",
    "share": """
<section class="sgsec"><h3 class="sgtitle">Export</h3><div class="sgroup">
  <div class="srow stack"><span>Which employers</span><div class="cats" id="exLists"></div></div>
  <div class="srow stack"><span>Or pick companies</span><input type="search" id="exQ" placeholder="Filter companies" aria-label="Filter companies"><div class="pick" id="exCos"></div></div>
  <div class="srow"><div class="slab"><label for="exListings">Include current listings</label><small>The open job posts and their text, so the other household sees them before their first update.</small></div><div class="sctl"><input type="checkbox" role="switch" class="sw" id="exListings" checked></div></div>
  <div class="srow stack"><div class="sbtns"><button class="btn primary" type="button" id="exBtn">Download .siftwell file</button></div><p class="note" id="exMsg" role="status" aria-live="polite"></p></div>
</div><p class="sfoot">Only public information goes in the file: company names, their job systems and (if ticked) their open listings. Never profiles, resumes, saved or applied marks, tailored resumes, settings, your access key, Claude's ratings or company research.</p></section>
<section class="sgsec"><h3 class="sgtitle">Import</h3><div class="sgroup">
  <div class="srow stack"><input type="file" id="imFile" accept=".siftwell" aria-label="Choose a .siftwell file"><p class="note" id="imMsg" role="status" aria-live="polite">Choose a .siftwell file someone shared with you.</p></div>
  <div class="srow stack" id="imGo" hidden><div class="cline"><label for="imList" class="note">Add them for</label><select id="imList"></select><button class="btn primary sm" type="button" id="imBtn">Add</button></div></div>
</div><p class="sfoot">Companies already in your catalog are matched by their job board and listings by their id. Nothing you have is removed or closed; dates keep the earliest first seen and latest last seen.</p></section>""",
}


def render(pid=None) -> str:
    name = e(people.name(pid))
    p = people.prefs(pid)
    nav, panes = [], []
    for cid, label, icon in PANES:
        nav.append(f'<a class="scat" href="#{cid}" data-cat="{cid}"><span class="sico">{_SVG.format(icon)}</span>'
                   f'<span class="sname">{e(label)}</span><span class="schev" aria-hidden="true">›</span></a>')
        panes.append(f'<section class="spane" data-cat="{cid}" aria-labelledby="h-{cid}" hidden>{_head(cid, label)}{BODIES[cid].replace('__AUTOUPDATE__', autoupdate.PANE_HTML)}</section>')
    tools = report.TOOLS.replace('id="catalogBtn" href="/catalog"', 'id="catalogBtn" href="/catalog" aria-current="page"')
    head = report.HEAD.replace("<title>Siftwell</title>", "<title>Employers · Siftwell</title>")
    body = (settings_page.BODY.replace("<h1>Settings · __NAME__</h1>", "<h1>Employers</h1>").replace("__TOOLS__", tools)
            .replace(settings_page.SUBTITLE, "Every employer and job listing Siftwell checks, for everyone in this household")
            .replace('aria-label="Settings categories"', 'aria-label="Employers page sections"').replace("__NAV__", "".join(nav))
            .replace("__PANES__", "".join(panes)).replace("__VERSION__", e(getting_started.VERSION)))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            "<script>(function(){var t=" + json.dumps(p.get("display.theme")) +
            ';if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;})();</script>' +
            head + settings_page.CSS + CSS + "</head><body>" + body +
            "<script>window.__PREFS__=" + json.dumps(p).replace("</", "<\\/") + ";window.__ME__=" + json.dumps({"id": pid, "name": people.name(pid)}).replace("</", "<\\/") +
            ";</script>\n" + SCRIPT.replace("/*__THEME__*/", report.THEME_JS) + autoupdate.SCRIPT + "</body></html>")


CSS = """<style>
.spanes{max-width:900px}
.rundet{margin-top:6px}.rundet summary{cursor:pointer;color:var(--muted);font-size:12.5px}
.rundet .mono{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11.5px;max-height:12em;overflow:auto;margin-top:4px}
.cline{display:flex;gap:8px;flex-wrap:wrap;align-items:center;min-width:0}
.cline input[type=text]{flex:1 1 160px}
.srow.stack input[type=url],.srow.stack input[type=text],.srow.stack input[type=search],.cline input,.cline select,.ctools input,.ctools select,.tin{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;min-width:0}
.tin.num{width:84px;text-align:right}
.ctools{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
.ctools input[type=search]{flex:1 1 220px}
.ctools select{max-width:100%}
.clist{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.clist:empty{display:none}
.crow{display:grid;grid-template-columns:minmax(0,2.2fr) minmax(0,1.3fr) minmax(0,1fr) auto;gap:6px 14px;align-items:center;padding:10px 14px}
.crow+.crow{border-top:1px solid var(--line)}
.crow small,.crow .sm{display:block;color:var(--muted);font-size:12.5px;overflow-wrap:anywhere}
.crow b{font-weight:600;overflow-wrap:anywhere}
.crow a{color:var(--accent);text-decoration:none}
.cact{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.cact .btn[data-armed="1"]{color:var(--bad);border-color:var(--bad)}
.pill{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--bg);color:var(--muted);border:1px solid var(--line);white-space:nowrap}
.pill.ok{background:var(--good-soft);color:var(--good);border-color:transparent}
.pill.suspect,.pill.capped,.pill.stopped,.pill.partial,.pill.running{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.pill.error{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.cmore,.pager{display:flex;justify-content:center;align-items:center;gap:12px;margin-top:10px}
.lrow{grid-template-columns:minmax(0,1fr) auto}
.whochips{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.whochips .chip{white-space:normal}
.livebar{margin-top:14px;padding:10px 14px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.lbtop{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.pbar{height:6px;border-radius:3px;background:var(--bar);margin:8px 0 6px;overflow:hidden}
.pbar i{display:block;height:100%;width:0;background:var(--bar-fill);transition:width .3s}
.rrow{grid-template-columns:minmax(0,1.6fr) minmax(0,1fr) minmax(0,1.6fr)}
.rrow details summary{cursor:pointer;color:var(--muted);font-size:12.5px}
.rrow details div{font-size:12.5px;color:var(--muted);overflow-wrap:anywhere}
.rcard{margin-top:16px}
.rgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:1px;background:var(--line)}
.rgrid div{background:var(--surface);padding:10px 14px}
.rgrid b{display:block;font-family:var(--mono);font-size:18px;font-weight:500;font-variant-numeric:tabular-nums}
.rgrid span{font-size:12px;color:var(--muted)}
.cats{display:flex;flex-wrap:wrap;gap:6px 16px}
.cats label{display:inline-flex;gap:6px;align-items:center}
.notice{margin-top:12px;padding:12px 14px;border-radius:12px;background:var(--warn-soft);color:var(--ink);border:1px solid var(--line)}
.notice a{color:var(--accent);font-weight:600}
.fcats{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.fcat{display:flex;justify-content:space-between;gap:4px 10px;font-size:13px;flex-wrap:wrap;padding:4px 0}
.fcat+.fcat{border-top:1px solid var(--line)}
.fcat .fcl{display:flex;flex-direction:column;min-width:0;flex:1 1 220px}
.fcat .fcl .note{overflow-wrap:anywhere}
.fcn{display:flex;gap:4px 10px;flex-wrap:wrap;align-items:flex-start;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.fcn b{color:var(--ink);font-weight:600}
.pill.budget{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.fsys{margin:0 0 8px}
.fsys summary{cursor:pointer;padding:4px 0;font-size:13.5px}
.fsys summary b{font-variant-numeric:tabular-nums}
#fdExh .cline{margin-top:10px}
.mono{font-family:var(--mono);font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:7.5em;overflow:hidden}
.frow{grid-template-columns:auto minmax(0,2fr) minmax(0,1.2fr) auto}
.frow input[type=checkbox]{width:18px;height:18px}
.fdet{margin-top:12px}
.fdet summary{cursor:pointer;font-weight:600;padding:6px 0}
.fdet .crow{grid-template-columns:minmax(0,1fr) minmax(0,1.4fr)}
.pick{max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:var(--r);padding:4px 8px}
.pick label{display:flex;gap:8px;align-items:center;padding:3px 0;overflow-wrap:anywhere}
.seg button{min-height:var(--h-sm)}
.srow.stack input[type=checkbox],.cats input[type=checkbox],.pick input[type=checkbox]{width:18px;height:18px;min-width:18px;flex:none;padding:0;margin:0}
.srow.stack input[type=file]{height:auto;padding:6px 0;border:0;background:none}
.pick label .note{margin-left:auto;padding-left:8px;white-space:nowrap}
@media (max-width:720px){
  .crow,.lrow,.rrow,.frow{grid-template-columns:minmax(0,1fr)}
  .frow{grid-template-columns:auto minmax(0,1fr)}
  .frow > :nth-child(n+3){grid-column:2}
  .cact{justify-content:flex-start}
  .ctools select{flex:1 1 140px}
  .sctl.cline{max-width:62%}
  .seg{display:flex}.seg button{flex:1;padding:6px 4px;font-size:12.5px;white-space:nowrap}
  #fdSize .segn{display:none}
}
</style>
"""

SCRIPT = r"""<script>
(function(){
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const safeUrl = u => { const s = String(u ?? "").trim(); return /^https?:\/\/[^\s\/?#]/i.test(s) && !/[\s\x00-\x1f]/.test(s) ? s : ""; };  // http(s) links only
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const phone = () => matchMedia("(max-width:720px)").matches;
const n = x => (x || 0).toLocaleString();
const pl = (k, one, many) => `${n(k)} ${k === 1 ? one : many}`;
const ME = window.__ME__ || {};
let PREFS = window.__PREFS__ || {};
function applyTheme(){
  const t = PREFS["display.theme"];
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("jb.theme", t); } catch(e) {}
  themeSync();
}
const get = url => fetch(url).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.error || "Something went wrong."); return d; }));
const post = (url, body) => fetch(url, {method: "POST", headers: H, body: JSON.stringify(body || {})})
  .then(r => r.json().then(d => { if (!r.ok) { const er = new Error(d.error || "Something went wrong."); er.data = d; throw er; } return d; }));
const errText = err => err instanceof TypeError ? "Couldn't reach Siftwell. Check the connection." : err.message;
const ATS = {greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", workday: "Workday", smartrecruiters: "SmartRecruiters", icims: "iCIMS",
  ukg: "UKG", oracle: "Oracle", paylocity: "Paylocity", adp: "ADP", rippling: "Rippling", workable: "Workable", bamboohr: "BambooHR",
  jazzhr: "JazzHR", breezy: "Breezy", recruitee: "Recruitee", paycom: "Paycom", saashr: "SaaSHR", dayforce: "Dayforce", jsonld: "Standard job data",
  radancy: "Radancy", eightfold: "Eightfold", avature: "Avature", applitrack: "AppliTrack", schoolspring: "SchoolSpring", jobvite: "Jobvite",
  amazon: "Amazon", jibe: "Jibe", phenom: "Phenom", clearcompany: "ClearCompany",
  successfactors: "SAP SuccessFactors", taleo: "Taleo"};
const atsName = a => ATS[a] || a || "";
const STATUS = {ok: "OK", suspect: "Looks incomplete", capped: "Too many to read all", error: "Couldn’t be read", paused: "Paused", new: "Not checked yet"};
function when(iso){
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso); if (isNaN(d)) return iso;
  const days = Math.round((Date.now() - d) / 864e5);
  const date = d.toLocaleDateString(undefined, {month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric"});
  return iso.length > 10 && days < 1 ? date + " " + d.toLocaleTimeString(undefined, {hour: "numeric", minute: "2-digit"}) : date;
}
function dur(a, b){
  if (!a || !b) return "";
  const s = Math.max(0, (new Date(b) - new Date(a)) / 1000);
  return s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h";
}
let LISTS = [], listLabel = id => (LISTS.find(l => l.id === id) || {}).label || id;
function fillListSelect(sel, def){
  sel.innerHTML = LISTS.map(l => `<option value="${esc(l.id)}">${esc(l.label)}</option>`).join("");
  if (def && LISTS.some(l => l.id === def)) sel.value = def;
}

// ---- sections: the URL hash picks one (/catalog#listings); at phone width no hash means "show the list"
const CATS = [...document.querySelectorAll(".spane")].map(p => p.dataset.cat);
const loaded = {};
function route(){
  const h = location.hash.slice(1), sel = CATS.includes(h) ? h : "", shown = sel || "companies";
  $("slayout").classList.toggle("atList", !sel);
  document.querySelectorAll(".scat").forEach(a => a.setAttribute("aria-current", a.dataset.cat === shown ? "page" : "false"));
  document.querySelectorAll(".spane").forEach(p => p.hidden = p.dataset.cat !== shown);
  if (!phone() || sel) show(shown);
}
function show(cat){
  const f = {companies: loadCompanies, listings: loadListings, runs: loadRuns, rating: loadRating, find: loadFind, share: loadShare}[cat];
  if (f && (!loaded[cat] || cat === "rating" || cat === "runs" || cat === "find")) { loaded[cat] = true; f(); }
}
window.addEventListener("hashchange", route);
document.querySelector(".snav").addEventListener("click", ev => {
  const a = ev.target.closest(".scat"); if (!a) return;
  ev.preventDefault();
  if (location.hash === "#" + a.dataset.cat) return;
  history.pushState({fromList: phone() && !CATS.includes(location.hash.slice(1))}, "", "#" + a.dataset.cat);
  route(); if (phone()) scrollTo(0, 0);
});
document.querySelector(".spanes").addEventListener("click", ev => {
  if (!ev.target.closest("[data-back]")) return;
  ev.preventDefault();
  if (history.state && history.state.fromList) history.back();
  else { history.pushState(null, "", location.pathname); route(); }
  scrollTo(0, 0);
});

// ---- live status: the ONE plain progress line every page shows (first_search.progress, via /api/status). The
// fetch's own output is only behind Details on the Finding new jobs section, and only while it runs.
let statusTimer = null, wasRunning = false;
function pollStatus(){
  clearTimeout(statusTimer);
  return get("/api/status").then(s => {
    const pg = s.progress || {active: !!s.running, line: "Finding new jobs…", frac: null};
    const run = !!pg.active && pg.blocking !== false, pct = Math.round(100 * (pg.frac == null ? .04 : pg.frac));   // (a directory build doesn't hold Find new jobs up; its line is on the board and in Settings)
    [["fetch", $("fetchBar")], ["all", $("allBar")]].forEach(([k, bar]) => {
      if (!bar) return;
      bar.hidden = !run;
      $(k + "Title").textContent = pg.line || "Working…";
      $(k + "Fill").style.width = pct + "%";
    });
    $("allDet").hidden = !s.running; if (!run) $("allDet").open = false;
    $("allLine").textContent = s.running ? (s.lines || []).filter(Boolean).slice(-8).join("\n") : "";
    const e = s.estimate && s.estimate.all;
    if (e) $("allEst").textContent = `${n(e.companies)} employer${e.companies === 1 ? "" : "s"}, for everyone in the household: ${e.text}. Claude then rates the new listings for each person (uses your Claude plan).`;
    window.__EST = e || window.__EST;
    $("fetchAll").disabled = run; $("fetchAll").textContent = run ? "Running…" : "Find new jobs now";
    $("updateBtn").disabled = run; $("updateBtn").classList.toggle("busy", run);
    if (run) { wasRunning = true; statusTimer = setTimeout(pollStatus, 2500); }
    else { if (wasRunning) { wasRunning = false; if (loaded.companies) loadCompanies(); if (loaded.runs) loadRuns(); } statusTimer = setTimeout(pollStatus, 20000); }
    return s;
  }).catch(() => { statusTimer = setTimeout(pollStatus, 8000); });
}

// ---- Companies
let COS = [], coShown = 100;
function loadCompanies(){
  return get("/api/catalog/companies").then(d => {
    COS = d.companies; LISTS = d.lists; FJ = d.facts_job || FJ;
    factsNote(); if (FJ.running) pollFacts();
    if (!$("addList").options.length) fillListSelect($("addList"), "own-" + ME.id);
    const lf = $("coListF"), cur = lf.value;
    lf.value = cur;
    const af = $("coAts"), ca = af.value, atsList = [...new Set(COS.map(c => c.ats))].sort((a, b) => atsName(a).localeCompare(atsName(b)));
    af.innerHTML = `<option value="">Any job system</option>` + atsList.map(a => `<option value="${esc(a)}">${esc(atsName(a))}</option>`).join("");
    af.value = ca;
    const lc = $("lsCo"); if (lc.options.length <= 1) lc.innerHTML = `<option value="">All companies</option>` + COS.map(c => `<option>${esc(c.name)}</option>`).join("");
    renderCompanies();
  }).catch(err => { $("coCount").textContent = errText(err); });
}
function coFiltered(){
  const q = $("coQ").value.trim().toLowerCase(), st = $("coStatus").value, li = $("coListF").value, at = $("coAts").value;
  return COS.filter(c => (!q || c.name.toLowerCase().includes(q) || atsName(c.ats).toLowerCase().includes(q)) && (!st || c.status === st)
    && (!li || (li === "mine") === !!c.mine) && (!at || c.ats === at));
}
// ---- company facts (looked up by Claude; the button looks one company up now)
let FJ = {running: null, last: null, claude: true}, factsTimer = null;
const day = s => { const d = new Date(String(s).slice(0, 10) + "T12:00:00"); return isNaN(d) ? String(s) : d.toLocaleDateString([], {month: "short", day: "numeric", year: "numeric"}); };
function factsText(c){
  const f = c.facts;
  if (FJ.running === c.name) return "Facts: Claude is looking them up…";
  if (!f) return "No company facts yet";
  if (f.at === "hand") return "Facts researched by hand";
  if (f.failed) return `Facts: none found ${day(f.failed)}` + (f.at ? ` (last found ${day(f.at)})` : "");
  return `Facts looked up ${day(f.at)}`;
}
function factsBtn(c){
  const f = c.facts || {};
  if (!FJ.claude || f.at === "hand") return "";
  return `<button class="btn sm" type="button" data-act="facts"${FJ.running ? " disabled" : ""}>${f.at ? "Refresh facts" : "Look up facts"}</button>`;
}
function factsNote(){
  const el = $("factsNote"), L = FJ.last;
  if (!FJ.claude) { el.hidden = false; el.innerHTML = 'Connect Claude to get company facts: <a href="/settings#get-started">Settings, then Get started</a>.'; return; }
  if (FJ.running) { el.hidden = false; el.textContent = `Claude is looking up facts for ${FJ.running} (usually a minute or two)…`; return; }
  if (L && !L.ok && L.message) { el.hidden = false; el.textContent = `Couldn't get facts for ${L.name}: ${L.message}`; return; }
  el.hidden = true; el.textContent = "";
}
function pollFacts(){
  clearTimeout(factsTimer);
  get("/api/catalog/facts").then(s => {
    const was = FJ.running; FJ = s;
    if (s.running) { factsNote(); renderCompanies(); factsTimer = setTimeout(pollFacts, 3000); }
    else if (was) loadCompanies();
    else factsNote();
  }).catch(() => { factsTimer = setTimeout(pollFacts, 8000); });
}
function coRow(c){
  const lists = c.mine ? "one of your employers" : (c.watchers || []).length ? "watched by " + c.watchers.join(", ") : "watched by nobody";
  const reason = c.reason ? `<small>${esc(c.reason)}</small>` : "";
  return `<div class="crow" data-name="${esc(c.name)}"><div><b>${esc(c.name)}</b><small>${esc(atsName(c.ats))}${lists ? " · " + esc(lists) : ""}</small><small>${esc(factsText(c))}</small></div>
  <div><span class="pill ${esc(c.status)}">${esc(STATUS[c.status] || c.status)}</span>${c.paused && c.fetch_status && c.fetch_status !== "ok" ? ` <span class="pill ${esc(c.fetch_status)}">${esc(STATUS[c.fetch_status] || c.fetch_status)}</span>` : ""}${reason}</div>
  <div><span>${n(c.open)} open</span><small>${c.last ? "Checked " + esc(when(c.last)) : "Not checked yet"}</small></div>
  <div class="cact"><button class="btn sm" type="button" data-act="fetch"${c.paused ? " disabled" : ""}>Check now</button>${factsBtn(c)}<button class="btn sm" type="button" data-act="watch" title="${c.mine ? "Take it off your employers (it stays on this page for the rest of the household)" : "Add it to your employers, so its jobs can reach your board"}">${c.mine ? "Stop watching" : "Watch"}</button><button class="btn sm" type="button" data-act="pause">${c.paused ? "Resume" : "Pause"}</button><button class="btn sm" type="button" data-act="remove">Remove</button></div></div>`;
}
function renderCompanies(){
  const list = coFiltered();
  $("coCount").textContent = `${n(list.length)} of ${n(COS.length)} employers · ${n(list.reduce((a, c) => a + (c.paused ? 0 : c.open), 0))} open job listings` + (list.length < COS.length ? " in this list" : "");
  $("coRows").innerHTML = list.slice(0, coShown).map(coRow).join("");
  $("coMore").hidden = list.length <= coShown;
  $("coMore").textContent = `Show more (${n(list.length - coShown)} left)`;
}
["coQ", "coStatus", "coListF", "coAts"].forEach(id => $(id).addEventListener(id === "coQ" ? "input" : "change", () => { coShown = 100; renderCompanies(); }));
$("coMore").addEventListener("click", () => { coShown += 200; renderCompanies(); });
let rmTimer = null;
$("coRows").addEventListener("click", ev => {
  const b = ev.target.closest("button[data-act]"); if (!b) return;
  const row = b.closest(".crow"), name = row.dataset.name, c = COS.find(x => x.name === name) || {}, act = b.dataset.act;
  const say = (t, bad) => { let m = row.querySelector(".rowmsg"); if (!m) { m = document.createElement("small"); m.className = "rowmsg"; row.firstElementChild.appendChild(m); } m.textContent = t; m.style.color = bad ? "var(--bad)" : ""; };
  if (act === "remove" && b.dataset.armed !== "1") {
    b.dataset.armed = "1"; b.textContent = "Tap again to remove";
    say("Removes it from everyone's boards. Its listings are kept as closed, so adding it back later keeps their history.");
    clearTimeout(rmTimer); rmTimer = setTimeout(() => { b.dataset.armed = ""; b.textContent = "Remove"; say(""); }, 6000); return;
  }
  b.disabled = true;
  if (act === "facts") {
    post("/api/catalog/facts", {name}).then(() => { FJ.running = name; FJ.last = null; factsNote(); renderCompanies(); pollFacts(); })
      .catch(err => { b.disabled = false; say(errText(err), true); if (err.data && err.data.needs_claude) { FJ.claude = false; factsNote(); renderCompanies(); } });
    return;
  }
  const url = act === "fetch" ? "/api/catalog/fetch" : act === "pause" ? "/api/catalog/pause" : act === "watch" ? "/api/catalog/watch" : "/api/catalog/remove";
  post(url, {name, paused: !c.paused, on: !c.mine}).then(d => {
    if (act === "watch") { c.mine = !!d.mine; c.watchers = d.watchers || []; renderCompanies(); return; }   // (the list and its count follow the filter)
    if (act === "fetch") { say("Checking it now. Its new jobs reach the boards when it finishes."); wasRunning = true; pollStatus(); b.disabled = false; return; }
    if (act === "remove") { COS = COS.filter(x => x.name !== name); renderCompanies(); return; }
    c.paused = !c.paused; c.status = c.paused ? "paused" : (c.fetch_status || "new"); row.outerHTML = coRow(c);
  }).catch(err => { b.disabled = false; say(errText(err), true); });
});
$("addForm").addEventListener("submit", ev => {
  ev.preventDefault();
  const b = $("addBtn"), m = $("addMsg");
  b.disabled = true; m.style.color = ""; m.textContent = "Checking that link… (this can take up to a minute)";
  let link = $("addUrl").value.trim();
  if (link && !/^[a-z][a-z0-9+.-]*:\/\//i.test(link)) link = "https://" + link.replace(/^\/+/, "");   // a bare "careers.example.com" is fine
  post("/api/catalog/add", {url: link, name: $("addName").value.trim(), list: $("addList").value}).then(d => {
    b.disabled = false; $("addUrl").value = ""; $("addName").value = "";
    m.textContent = `${d.existing ? "Siftwell already had it: now one of your employers" : "Added"} ${d.name} (${n(d.open_jobs)} open jobs). ` +
      (d.fetching ? "Getting its jobs now." : "Its jobs come with the next Find new jobs.");
    loadCompanies(); if (d.fetching) { wasRunning = true; pollStatus(); }
  }).catch(err => { b.disabled = false; m.style.color = "var(--bad)"; m.textContent = errText(err); });
});

// ---- Listings (pages come from the server)
let lsPage = 1, lsTotal = 0, lsTimer = null;
const TIER = {haiku: "Quick check", sonnet: "Careful look", opus: "Best judgment"};
function whoChip(p){
  let t;
  if (p.fit == null) t = p.unmet ? "requirements not met" : "not rated yet";
  else t = `${TIER[p.tier] || "rated"} ${p.fit}` + (p.stale ? " (needs a fresh rating)" : "");
  return `<span class="chip">${esc(p.name)}: ${esc(t)}</span>`;
}
function loadListings(){
  const qs = new URLSearchParams({q: $("lsQ").value.trim(), state: $("lsState").value, company: $("lsCo").value, who: $("lsWho").value, sort: $("lsSort").value, page: lsPage, per: 50});
  $("lsCount").textContent = "Loading…";
  if ($("lsCo").options.length <= 1 && !COS.length) loadCompanies();
  return get("/api/catalog/listings?" + qs).then(d => {
    lsTotal = d.total;
    const pages = Math.max(1, Math.ceil(d.total / d.per));
    const a = d.total ? (d.page - 1) * d.per + 1 : 0, b = Math.min(d.total, d.page * d.per);
    $("lsCount").textContent = d.total ? `Showing ${n(a)}–${n(b)} of ${n(d.total)} listings` : "No listings match.";
    $("lsRows").innerHTML = d.rows.map(r => {
      const locs = (r.locations || []).slice(0, 3).join("; ") + ((r.locations || []).length > 3 ? ` +${r.locations.length - 3}` : "");
      const seen = `First seen ${when(r.first_seen)} · last seen ${when(r.last_seen)}` + (r.closed_at ? ` · closed ${when(r.closed_at)}` : "") + (r.partial ? " · details come with the next update" : "");
      const who = r.people.length ? r.people.map(whoChip).join("") : `<span class="chip">Passes nobody's filters</span>`;
      const title = safeUrl(r.url) ? `<a href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title);
      return `<div class="crow lrow"><div><b>${title}</b><small>${esc(r.company)}${locs ? " · " + esc(locs) : ""}${r.workplace ? " · " + esc(r.workplace) : ""}</small><small>${esc(seen)}</small><div class="whochips">${who}</div></div>
        <div>${r.closed_at ? '<span class="pill">Closed</span>' : '<span class="pill ok">Open</span>'}</div></div>`;
    }).join("");
    $("lsPage").textContent = `Page ${n(d.page)} of ${n(pages)}`;
    $("lsPrev").disabled = d.page <= 1; $("lsNext").disabled = d.page >= pages;
  }).catch(err => { $("lsCount").textContent = errText(err); });
}
$("lsQ").addEventListener("input", () => { clearTimeout(lsTimer); lsTimer = setTimeout(() => { lsPage = 1; loadListings(); }, 300); });
["lsState", "lsCo", "lsWho", "lsSort"].forEach(id => $(id).addEventListener("change", () => { lsPage = 1; loadListings(); }));
$("lsPrev").addEventListener("click", () => { lsPage--; loadListings().then(() => $("lsCount").scrollIntoView({block: "nearest"})); });
$("lsNext").addEventListener("click", () => { lsPage++; loadListings().then(() => $("lsCount").scrollIntoView({block: "nearest"})); });

// ---- Runs & updates
const KIND = {fetch: "Find new jobs", recompute: "Board rebuild", rerate: "Re-rate", rescore: "Re-read listings", migrate: "Catalog set up", find: "Find employers near me"};
function runRow(r){
  const d = r.details || {};
  let what = KIND[r.kind] || r.kind;
  if (r.kind === "fetch" && d.only) what = "Checked: " + d.only;
  if (r.kind === "rerate" && d.person) what += " · " + d.person + (d.tiers ? " (" + d.tiers.join(", ") + ")" : "");
  if (r.kind === "find") what += " · " + [d.label || d.location, d.size === "exhaustive" ? `exhaustive (${n(d.passes)} of up to ${n(d.budget)} passes)` : d.size].filter(Boolean).join(", ");
  const c = [];
  if (r.kind === "find") { if (r.companies != null) c.push(`${pl(r.companies, "employer", "employers")} found`); if (r.fetched != null) c.push(`${n(r.fetched)} readable`); }
  else {
    if (r.companies != null) c.push(pl(r.companies, "company", "companies"));
    if (r.fetched != null) c.push(`${n(r.fetched)} ${r.kind === "migrate" ? "listings" : "fetched"}`);
    if (r.new) c.push(`${n(r.new)} new`); if (r.closed) c.push(`${n(r.closed)} closed`); if (r.changed) c.push(`${n(r.changed)} changed`); if (r.reopened) c.push(`${n(r.reopened)} back`);
  }
  const boards = d.boards || {};
  const bl = Object.entries(boards).map(([p, v]) => v && v.error ? `${p}: failed` : v ? `${p}: ${n(v.jobs)} jobs` : "").filter(Boolean);
  if (bl.length) c.push(bl.join(", "));
  const tim = Object.entries(boards).flatMap(([p, v]) => (v && v.timings || []).map(t => `${p} · ${t.tier}: ${n(t.jobs)} jobs in ${t.secs}s` + (t.failed ? `, ${t.failed} batches failed` : "") + (t.stopped ? ` (${t.stopped})` : "")));
  const errs = (r.errors || []).map(x => `${x.company || x.person || x.category || ""}: ${x.error || x.status || ""}`);
  const more = (errs.length ? `<details><summary>${n(errs.length)} problem${errs.length === 1 ? "" : "s"}</summary><div>${errs.map(esc).join("<br>")}</div></details>` : "") +
    (tim.length ? `<details><summary>Timing by model</summary><div>${tim.map(esc).join("<br>")}</div></details>` : "");
  const st = r.status === "running" && r.finished ? "stopped" : r.status;
  return `<div class="crow rrow"><div><b>${esc(what)}</b><small>${esc(when(r.started))}${r.finished ? " · " + esc(dur(r.started, r.finished)) : ""}</small></div>
    <div><span class="pill ${esc(st)}">${esc(st)}</span></div><div><small>${esc(c.join(" · ")) || "&nbsp;"}</small>${more}</div></div>`;
}
function loadRuns(){
  return get("/api/catalog/runs").then(d => {
    $("runRows").innerHTML = d.runs.length ? d.runs.map(runRow).join("") : `<p class="note" style="padding:10px 14px">Nothing has run yet.</p>`;
    if (d.status.running) { wasRunning = true; pollStatus(); }
  }).catch(err => { $("runRows").innerHTML = `<p class="note" style="padding:10px 14px">${esc(errText(err))}</p>`; });
}
$("fetchAll").addEventListener("click", () => {
  const e = window.__EST;
  if (!confirm("Find new jobs now?\n\n" + (e ? `Checks all ${n(e.companies)} employers for new and removed jobs, for everyone in the household. That takes ${e.text}.` : "Checks every employer for new and removed jobs, for everyone in the household.") + " Claude then rates the new listings for each person, which uses your Claude plan.")) return;
  fetch("/api/update", {method: "POST", headers: H, body: "{}"}).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.error === "already running" ? "Siftwell is already finding new jobs." : d.error); }))
    .then(() => { wasRunning = true; pollStatus(); }).catch(err => { $("allBar").hidden = false; $("allTitle").textContent = errText(err); });
});

// ---- Rating
function loadRating(){
  return get("/api/catalog/rating").then(d => {
    $("rateCards").innerHTML = d.people.map(p => {
      const s = p.summary, r = p.rerate || {};
      const stats = s ? [["Pass their filters", s.passing], ["Rated by Claude", s.rated], ["Got a careful look or best judgment", s.deep], ["Waiting for a rating", s.unrated], ["Need a fresh rating", s.stale]]
        .map(([l, v]) => `<div><b>${n(v)}</b><span>${esc(l)}</span></div>`).join("") : "";
      const tiers = s ? `Quick ${n(s.haiku)} · careful ${n(s.sonnet)} · best ${n(s.opus)}` + (s.unmet ? ` · ${n(s.unmet)} skipped (requirements not met)` : "") : "";
      const live = r.running ? `<div class="srow"><span class="note">${esc(r.label || "Re-rating")}${r.total ? ` · ${n(r.done)} of ${n(r.total)}${r.tier ? " (" + esc(r.tier) + ")" : ""}` : ""}…</span></div>` : "";
      return `<section class="sgsec rcard"><h3 class="sgtitle">${esc(p.name)}${p.id === d.current ? " (viewing now)" : ""}</h3><div class="sgroup">
        ${s ? `<div class="rgrid">${stats}</div>` : `<div class="srow"><span class="note">${p.profile ? "No board yet." : "No resume yet, so Claude can't rate jobs for " + esc(p.name) + "."}</span></div>`}
        ${s ? `<div class="srow"><small class="note">${esc(tiers)}${s.generated ? " · board built " + esc(when(s.generated)) : ""}</small></div>` : ""}${live}
        <div class="srow"><span class="note">The Re-rate panel lets you choose how carefully Claude rates.</span><button class="btn sm" type="button" data-rr="${esc(p.id)}"${p.profile ? "" : " disabled"}>Open Re-rate for ${esc(p.name)}</button></div>
      </div></section>`;
    }).join("");
  }).catch(err => { $("rateCards").innerHTML = `<p class="note">${esc(errText(err))}</p>`; });
}
$("rateCards").addEventListener("click", ev => {
  const b = ev.target.closest("[data-rr]"); if (!b) return;
  b.disabled = true;
  const go = () => { try { sessionStorage.setItem("jb.run", "rerate"); } catch(e) {} location.href = "/#jobs"; };
  if (b.dataset.rr === ME.id) return go();
  fetch("/api/person", {method: "POST", headers: H, body: JSON.stringify({id: b.dataset.rr})}).then(go).catch(() => { b.disabled = false; });
});

// ---- Find employers near me
let FD = null, fdTimer = null, fdSize = "medium";
const CSTATE = {pending: "Waiting", researching: "Claude is researching…", checking: "Checking careers pages…", done: "Done", error: "Problem"};
let fdEstTimer = null, fdEstSeq = 0;
function fdEstimate(){
  if (!FD) return;
  const exh = fdSize === "exhaustive";
  $("fdExh").hidden = !exh;
  $("fdStart").textContent = exh ? `Start exhaustive search (up to ${n(fdBudget())} passes)` : "Start search";
  if (!exh) {
    $("fdEst").textContent = `About ${FD.sizes[fdSize]} employers. This can take ${FD.estimate[fdSize]} and uses your Claude plan (Claude searches the web for each kind of employer). Siftwell then checks each careers page itself. You can leave this page; the search keeps going.`;
    return;
  }
  $("fdEst").textContent = "As many employers as Claude can find in the area: it keeps searching, one kind of employer, sub-type and city at a time, telling Claude which employers it already knows and asking for more. Siftwell checks each careers page itself. You can leave this page; Stop and Resume pick up where it left off.";
  clearTimeout(fdEstTimer);
  fdEstTimer = setTimeout(() => {
    const cats = [...$("fdCats").querySelectorAll("input:checked")].map(x => x.value), seq = ++fdEstSeq;
    const qs = new URLSearchParams({location: $("fdLoc").value.trim(), radius: $("fdRad").value, cats: cats.join(","), budget: fdBudget()});
    get("/api/catalog/find/estimate?" + qs).then(e => { if (seq === fdEstSeq) $("fdExhEst").textContent = e.text; })
      .catch(err => { if (seq === fdEstSeq) $("fdExhEst").textContent = errText(err); });
  }, 350);
}
function fdBudget(){
  const x = FD ? FD.exhaustive : {budget: 40, min: 5, max: 200}, v = parseInt($("fdBudget").value, 10);
  return isNaN(v) ? x.budget : Math.max(x.min, Math.min(x.max, v));
}
["fdLoc", "fdRad", "fdBudget"].forEach(id => $(id).addEventListener("input", () => { if (fdSize === "exhaustive") fdEstimate(); }));
$("fdCats").addEventListener("change", () => { if (fdSize === "exhaustive") fdEstimate(); });
$("fdSize").addEventListener("click", ev => {
  const b = ev.target.closest("button"); if (!b) return;
  fdSize = b.dataset.v; $("fdSize").querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); fdEstimate();
});
function fdClaudeNotice(c){
  const el = $("fdClaude");
  if (c.installed && c.signed_in) { el.hidden = true; return true; }
  el.hidden = false;
  el.innerHTML = (c.installed ? "Claude Code is installed but signed out." : "Claude Code isn't installed on this computer.") +
    " Find employers near me uses Claude Code (your Claude plan) to search the web. <a href=\"/settings#get-started\">Open Settings → Get started</a> to set it up, then come back.";
  return false;
}
let FDC = {key: "", list: []};   // the candidate list the page has (the server leaves it out of a poll when unchanged)
function loadFind(){
  clearTimeout(fdTimer);
  return get("/api/catalog/find" + (FDC.key ? "?have=" + encodeURIComponent(FDC.key) : "")).then(d => {
    const first = !FD; FD = d; LISTS = d.lists;
    if (d.run) {
      if (d.run.candidates) FDC = {key: d.run.id + ":" + d.run.sig, list: d.run.candidates};
      else if (FDC.key.split(":")[0] === String(d.run.id)) d.run.candidates = FDC.list;
      else d.run.candidates = [];
    }
    if (first) {
      $("fdCats").innerHTML = d.categories.map(c => `<label><input type="checkbox" value="${esc(c.id)}" checked> ${esc(c.label)}</label>`).join("");
      $("fdLoc").value = d.defaults.location; $("fdRad").value = d.defaults.radius;
      $("fdBudget").value = d.exhaustive.budget; $("fdBudget").min = $("fdBudget2").min = d.exhaustive.min; $("fdBudget").max = $("fdBudget2").max = d.exhaustive.max;
      fillListSelect($("fdList"), "own-" + ME.id);
      fdEstimate();
    }
    fdClaudeNotice(d.claude);
    renderFind();
    if (d.live) fdTimer = setTimeout(loadFind, d.run && d.run.details && d.run.details.size === "exhaustive" ? 4000 : 3000);
  }).catch(err => { $("fdMsg").textContent = errText(err); if (FD && FD.live) fdTimer = setTimeout(loadFind, 6000); });
}
function renderFind(){
  const d = FD, run = d.run;
  $("fdStart").disabled = d.live;
  $("fdRun").hidden = !run;
  if (!run) { $("fdReview").hidden = true; return; }
  const dt = run.details || {}, counts = run.counts || {};
  const tot = s => Object.values(counts).reduce((a, c) => a + (c[s] || 0), 0);
  const exh = dt.size === "exhaustive", passes = `pass ${n(dt.passes)} of up to ${n(dt.budget)}`;
  const label = d.live ? (d.waiting ? `Waiting for the running ${d.waiting} to finish…` : exh ? `Searching… ${passes}` : "Searching…") :
    {ok: "Search finished", partial: "Search finished (some kinds had a problem)", stopped: "Search stopped", error: "Search stopped by a problem", running: "Searching…",
     budget: `Stopped at the budget: ${n(dt.passes)} of ${n(dt.budget)} passes used`}[run.status] || run.status;
  $("fdTitle").textContent = label + (exh && !d.live && run.status !== "budget" ? ` (${n(dt.passes)} of up to ${n(dt.budget)} passes used)` : "");
  $("fdSub").textContent = `${dt.label || dt.location}, ${dt.radius} mi · ${exh ? `exhaustive search, budget ${n(dt.budget)} passes` : dt.size + " search"}${dt.focus ? " · focus: " + dt.focus : ""} · started ${when(run.started)}` +
    (dt.error === "signin" ? " · Claude Code is signed out: sign in on Settings → Get started, then Resume." : dt.error ? " · " + dt.error : "") +
    (run.status === "budget" && !d.live ? " · Raise the budget and Resume to keep going." : "");
  $("fdStop").hidden = !d.live; $("fdResume").hidden = d.live || run.status === "ok";
  const canBudget = exh && !d.live && run.status !== "ok";
  if (canBudget && $("fdBudgetRow").hidden) $("fdBudget2").value = run.status === "budget" ? Math.min(FD.exhaustive.max, (dt.passes || 0) + 20) : dt.budget;
  $("fdBudgetRow").hidden = !canBudget;
  $("fdPassBar").hidden = !exh; if (exh) $("fdPassFill").style.width = Math.min(100, 100 * (dt.passes || 0) / (dt.budget || 1)) + "%";
  $("fdCatRows").innerHTML = (dt.categories || []).map(cid => {
    const st = (dt.cats || {})[cid] || {}, c = counts[cid] || {}, lab = (d.categories.find(x => x.id === cid) || {}).label || cid;
    const checked = (c.readable || 0) + (c.unreadable || 0) + (c.known || 0) + (c.duplicate || 0) + (c.added || 0), all = checked + (c.pending || 0);
    let s = CSTATE[st.state] || st.state;
    if (exh && st.state === "researching") s = d.live ? `Claude is researching (its pass ${n(st.passes)}): ${st.doing || ""}` : `Stopped in the middle of its pass ${n(st.passes)} (${st.doing || ""}); Resume does that pass again`;
    else if (!d.live && (st.state === "researching" || st.state === "checking")) s = "Stopped part way; Resume picks up here";
    if (exh && st.state === "pending" && st.passes) s = `${n(st.passes)} pass${st.passes === 1 ? "" : "es"} so far · waiting for its next pass` + (st.error ? ` (last pass had a problem: ${st.error})` : "");
    if (st.state === "checking" && all) s = `Checking careers pages: ${checked} of ${all}`;
    if (st.state === "done") s = exh ? `Done after ${n(st.passes)} pass${st.passes === 1 ? "" : "es"}: ${st.stop || ""}` : `${n((c.readable || 0) + (c.added || 0))} readable of ${n(all)} found`;
    if (st.state === "error") s = "Problem: " + (st.error || "") + " (Resume tries again)";
    const cnt = all ? `<div class="fcn"><span><b>${n(all)}</b> found</span><span><b>${n((c.readable || 0) + (c.added || 0))}</b> readable</span><span><b>${n(c.unreadable)}</b> can't read</span><span><b>${n((c.known || 0) + (c.duplicate || 0))}</b> already in catalog</span>${c.pending ? `<span><b>${n(c.pending)}</b> to check</span>` : ""}</div>` : "";
    return `<div class="fcat"><div class="fcl"><span>${esc(lab)}</span><span class="note">${esc(s)}</span></div>${cnt}</div>`;
  }).join("");
  $("fdLines").textContent = d.live ? (d.lines || []).join("\n") : "";
  const cands = run.candidates || [];
  const ok = cands.filter(c => c.status === "readable" || c.status === "added"), bad = cands.filter(c => c.status === "unreadable"), known = cands.filter(c => c.status === "known" || c.status === "duplicate");
  $("fdReview").hidden = !cands.length || !(ok.length || bad.length || known.length);
  const catLab = id => (d.categories.find(x => x.id === id) || {}).label || id;
  const prevTicked = new Set([...document.querySelectorAll("#fdOk input:checked")].map(x => x.value));
  $("fdOk").innerHTML = ok.length ? ok.map(c => `<div class="crow frow">${c.status === "added" ? `<span class="pill ok">Added</span>` : `<input type="checkbox" value="${c.id}" aria-label="Add ${esc(c.name)}"${prevTicked.has(String(c.id)) ? " checked" : ""}>`}
      <div><b>${esc(c.name)}</b><small>${esc(catLab(c.category))}${c.location_note ? " · " + esc(c.location_note) : ""}</small>${c.why ? `<small>${esc(c.why)}</small>` : ""}</div>
      <div><span>${esc(atsName(c.ats))}</span><small>${n(c.open_jobs)} open job${c.open_jobs === 1 ? "" : "s"}${c.added_as && c.added_as !== c.name ? " · added as " + esc(c.added_as) : ""}</small></div>
      <div>${safeUrl(c.url) ? `<a href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener" class="note">Careers page</a>` : ""}</div></div>`).join("")
    : `<div class="srow"><span class="note">${d.live ? "Readable employers show up here as they're checked." : !bad.length && known.length ? "Every employer found is already in your catalog." : "None of the new employers found could be read by Siftwell."}</span></div>`;
  $("fdAdd").disabled = $("fdAddAll").disabled = !ok.some(c => c.status === "readable");
  $("fdBadWrap").hidden = !bad.length; $("fdBadSum").textContent = `${n(bad.length)} employer${bad.length === 1 ? "" : "s"} Siftwell can't read`;
  const groups = {}; bad.forEach(c => (groups[c.system || "Not identified"] = groups[c.system || "Not identified"] || []).push(c));
  const order = Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length || a.localeCompare(b));
  const openSys = new Set([...document.querySelectorAll("#fdBad details[open]")].map(x => x.dataset.sys));
  const SYSW = {"Custom careers site": "use their own custom careers site", "Page couldn't be opened": "couldn't be opened",
    "A job board, not the employer's own page": "were job-board pages, not the employer's own", "Not identified": "use a job system Siftwell didn't recognise"};
  const sysWords = k => SYSW[k] || "use " + k;
  $("fdSysNote").textContent = order.length ? "Grouped by the job system each careers page uses, biggest group first: " + order.slice(0, 4).map(k => `${n(groups[k].length)} ${sysWords(k)}`).join(", ") +
    (order.length > 4 ? `, and ${n(order.length - 4)} more group${order.length - 4 === 1 ? "" : "s"}` : "") + ". Support for the biggest job system would unlock the most employers." : "";
  $("fdBad").innerHTML = order.map(k => `<details class="fsys" data-sys="${esc(k)}"${openSys.has(k) ? " open" : ""}><summary><b>${n(groups[k].length)}</b> · ${esc(k)}</summary><div class="sgroup">` +
    groups[k].map(c => `<div class="crow"><div><b>${esc(c.name)}</b><small>${esc(catLab(c.category))}${c.location_note ? " · " + esc(c.location_note) : ""}</small></div><div><small>${esc(c.reason || "")}</small>${safeUrl(c.url) ? `<a href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener" class="sm">${esc(c.url)}</a>` : `<span class="sm">${esc(c.url)}</span>`}</div></div>`).join("") + `</div></details>`).join("");
  $("fdKnownWrap").hidden = !known.length; $("fdKnownSum").textContent = `${n(known.length)} already in your catalog`;
  $("fdKnown").innerHTML = known.map(c => `<div class="crow"><div><b>${esc(c.name)}</b><small>${esc(catLab(c.category))}</small></div><div><small>${esc(c.reason || "")}</small></div></div>`).join("");
}
$("fdForm").addEventListener("submit", ev => {
  ev.preventDefault();
  if (!FD || !fdClaudeNotice(FD.claude)) return;
  const cats = [...$("fdCats").querySelectorAll("input:checked")].map(x => x.value);
  const m = $("fdMsg"); m.style.color = ""; m.textContent = "Starting…"; $("fdStart").disabled = true;
  post("/api/catalog/find/start", {location: $("fdLoc").value.trim(), radius: +$("fdRad").value, focus: $("fdFocus").value.trim(), categories: cats, size: fdSize, budget: fdBudget()})
    .then(() => { m.textContent = ""; loadFind(); })
    .catch(err => { $("fdStart").disabled = false; m.style.color = "var(--bad)"; m.textContent = errText(err); if (err.data && err.data.claude) fdClaudeNotice(err.data.claude); });
});
$("fdStop").addEventListener("click", () => { $("fdStop").disabled = true; post("/api/catalog/find/stop").catch(() => {}).then(() => { $("fdStop").disabled = false; $("fdTitle").textContent = "Stopping (finishing the pages being checked)…"; }); });
$("fdResume").addEventListener("click", () => {
  $("fdResume").disabled = true;
  post("/api/catalog/find/resume", $("fdBudgetRow").hidden ? {} : {budget: +$("fdBudget2").value}).then(() => { $("fdResume").disabled = false; loadFind(); })
    .catch(err => { $("fdResume").disabled = false; $("fdSub").textContent = errText(err); if (err.data && err.data.claude) fdClaudeNotice(err.data.claude); });
});
function fdAdd(body){
  const m = $("fdAddMsg"); m.style.color = ""; m.textContent = "Adding…";
  post("/api/catalog/find/add", {...body, list: $("fdList").value}).then(d => {
    m.textContent = `Added ${n(d.added.length)} employer${d.added.length === 1 ? "" : "s"}${$("fdList").value === "all" ? " for everyone" : " to your employers"}. ` + (d.fetching ? "Fetching their jobs now." : "Their jobs come with the next update.");
    loaded.companies = false; loadFind();
  }).catch(err => { m.style.color = "var(--bad)"; m.textContent = errText(err); });
}
$("fdAdd").addEventListener("click", () => fdAdd({ids: [...document.querySelectorAll("#fdOk input:checked")].map(x => +x.value)}));
$("fdAddAll").addEventListener("click", () => fdAdd({all: true}));

// ---- Share
function loadShare(){
  const draw = () => {
    const mineN = COS.filter(c => c.mine).length;
    $("exLists").innerHTML = mineN ? `<label><input type="checkbox" value="mine"> All of your employers <span class="note">(${n(mineN)})</span></label>` : "";
    drawPick();
    fillListSelect($("imList"), "own-" + ME.id);
  };
  return COS.length ? Promise.resolve(draw()) : loadCompanies().then(draw);
}
const picked = new Set();
function drawPick(){
  const q = $("exQ").value.trim().toLowerCase();
  const list = COS.filter(c => !q || c.name.toLowerCase().includes(q)).slice(0, 300);
  $("exCos").innerHTML = list.map(c => `<label><input type="checkbox" value="${esc(c.name)}"${picked.has(c.name) ? " checked" : ""}> ${esc(c.name)} <span class="note">${esc(atsName(c.ats))}</span></label>`).join("") || `<span class="note">No companies match.</span>`;
}
$("exQ").addEventListener("input", drawPick);
$("exCos").addEventListener("change", ev => { const x = ev.target; if (x.checked) picked.add(x.value); else picked.delete(x.value); });
$("exBtn").addEventListener("click", () => {
  const lists = [...$("exLists").querySelectorAll("input:checked")].map(x => x.value), m = $("exMsg");
  if (!lists.length && !picked.size) { m.textContent = "Tick your employers, or at least one company."; return; }
  m.textContent = "Preparing the file…"; $("exBtn").disabled = true;
  fetch("/api/catalog/export", {method: "POST", headers: H, body: JSON.stringify({lists, names: [...picked], listings: $("exListings").checked})}).then(r => {
    if (!r.ok) return r.json().then(d => { throw new Error(d.error || "Couldn't export."); });
    const cn = (r.headers.get("X-Siftwell-Counts") || "").split(","), fn = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || "siftwell-companies.siftwell";
    return r.blob().then(b => {
      const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = fn; document.body.appendChild(a); a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
      m.textContent = `Saved ${fn}: ${pl(+cn[0], "company", "companies")}, ${pl(+cn[1], "listing", "listings")}.`;
    });
  }).catch(err => { m.textContent = errText(err); }).then(() => { $("exBtn").disabled = false; });
});
let imToken = "";
$("imFile").addEventListener("change", () => {
  const f = $("imFile").files[0], m = $("imMsg"); $("imGo").hidden = true; imToken = "";
  if (!f) return;
  m.style.color = ""; m.textContent = "Reading the file…";
  fetch("/api/catalog/import/preview", {method: "POST", headers: {"X-Jobboard": "1", "Content-Type": "application/octet-stream"}, body: f})
    .then(r => r.json().then(d => { if (!r.ok) throw new Error(d.error || "Couldn't read that file."); return d; })).then(d => {
      imToken = d.token;
      m.textContent = `${n(d.new_companies)} new compan${d.new_companies === 1 ? "y" : "ies"}, ${n(d.new_listings)} new listing${d.new_listings === 1 ? "" : "s"}, ${n(d.known_companies)} already in your catalog` +
        (d.known_listings ? ` (${n(d.known_listings)} listings you already have get their dates merged)` : "") + ".";
      $("imGo").hidden = false;
    }).catch(err => { m.style.color = "var(--bad)"; m.textContent = errText(err); });
});
$("imBtn").addEventListener("click", () => {
  const m = $("imMsg"); $("imBtn").disabled = true; m.style.color = ""; m.textContent = "Adding…";
  post("/api/catalog/import", {token: imToken, list: $("imList").value}).then(d => {
    m.textContent = `Added ${pl(d.new_companies, "company", "companies")} and ${pl(d.new_listings, "listing", "listings")}` + (d.known_companies ? `; ${pl(d.known_companies, "company", "companies")} you already had ${d.known_companies === 1 ? "is" : "are"} now among ${$("imList").value === "all" ? "everyone’s" : "yours"} too` : "") + ". Everyone's boards are being rebuilt.";
    $("imGo").hidden = true; $("imFile").value = ""; imToken = ""; loaded.companies = false; COS = [];
  }).catch(err => { m.style.color = "var(--bad)"; m.textContent = errText(err); }).then(() => { $("imBtn").disabled = false; });
});

/*__THEME__*/
applyTheme();
// ---- header: Find new jobs / Re-rate run on the board, which has the confirm and progress panel
const toBoard = run => { try { if (run) sessionStorage.setItem(run[0], run[1]); } catch(e) {} location.href = "/#jobs"; };
$("updateBtn").addEventListener("click", () => toBoard(["jb.run", "update"]));
$("rerateBtn").addEventListener("click", () => toBoard(["jb.run", "rerate"]));
$("updateBtn").title = "Find new jobs (opens the board): check your employers for new openings";
$("rerateBtn").title = "Re-rate (opens the board's Re-rate panel): choose how Claude re-rates your jobs, no new listings";
if ($("resumeBtn") && $("resumeBtn").tagName === "BUTTON") $("resumeBtn").addEventListener("click", () => toBoard(["jb.openResume", "1"]));
fetch("/api/rerate").then(r => r.json()).then(s => { if (s.running) { $("rerateBtn").classList.add("busy"); $("rerateBtn").title = "Re-rating your best jobs now…"; } }).catch(() => {});
fetch("/api/setup-status").then(r => r.json()).then(s => {
  const k = s && !s.complete && s.missing ? s.missing.length : 0, b = $("gsBadge");
  if (b) { b.hidden = !k; b.textContent = k || ""; }
}).catch(() => {});
// ---- profile menu
fetch("/api/people").then(r => r.json()).then(d => {
  const me = d.people.find(p => p.id === d.current) || {};
  $("avName").textContent = me.name || "Profile"; $("avInit").textContent = (me.name || "?").trim()[0].toUpperCase();
  $("lsWho").insertAdjacentHTML("beforeend", d.people.map(p => `<option value="${esc(p.id)}">On ${esc(p.name)}'s board</option>`).join(""));
  $("amPeople").innerHTML = `<div class="who">Profiles</div>` + d.people.map(p => `<button role="menuitem" data-person="${esc(p.id)}" aria-current="${p.id === d.current}">${esc(p.name)}</button>`).join("") + `<button role="menuitem" data-person="__add">Add a person</button><button role="menuitem" data-person="__manage">Manage profiles</button>`;
}).catch(() => {});
$("avatarBtn").addEventListener("click", ev => { ev.stopPropagation(); const h = $("amenu").hidden; $("amenu").hidden = !h; $("avatarBtn").setAttribute("aria-expanded", h); });
document.addEventListener("click", ev => { if (!ev.target.closest(".menuWrap")) { $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false"); } });
$("amenu").addEventListener("click", ev => {
  const b = ev.target.closest("button"); if (!b) return;
  $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false");
  const v = b.dataset.person; if (!v) return;
  if (v === "__add") return toBoard(["jb.run", "addPerson"]);
  if (v === "__manage") { location.href = "/settings#profiles"; return; }
  if (v === ME.id) return;
  fetch("/api/person", {method: "POST", headers: H, body: JSON.stringify({id: v})}).then(() => location.reload());
});
route();
pollStatus();
})();
</script>
"""
