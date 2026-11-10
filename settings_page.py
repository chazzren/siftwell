"""The Settings page (GET /settings): per-profile preferences in a two-pane, iOS/macOS-Settings-style layout.

Left: a category list (one per PREF_SCHEMA prefix, plus the API key). Right: the selected category's controls in
rounded grouped sections. The selection lives in the URL hash (/settings#display). At phone width it becomes a
drill-down: the list alone, then one category with a "‹ Settings" back control.

Every control auto-saves on change through POST /api/prefs (people.save_prefs merges partial updates).
It reuses the board's styles (report.HEAD) and header icon row (report.TOOLS). Update / Re-rate / My profile /
Add a person hand off to the board: they set sessionStorage "jb.run" (or "jb.openResume") and go to /#jobs, where
report.py's script picks the request up and runs it with its usual confirm and progress UI."""
import html
import json

import people
import report

_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>'

# Controls: ("select", key, label, [(value, text), ...], help) / ("toggle", key, label, help) / ("number", key, label, help)
# min/max for numbers come from people.PREF_SCHEMA.
CATEGORIES = [
    ("resume", "Resume PDF", '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>', [
        ("Layout", "Applies to every PDF download, including resumes you've already tailored.", [
            ("select", "resume.length", "Length", [("1", "Fit to 1 page"), ("2", "Up to 2 pages"), ("any", "No limit")], ""),
            ("select", "resume.style", "Style", [("classic", "Classic (serif)"), ("modern", "Modern (sans-serif)"), ("compact", "Compact")], ""),
            ("select", "resume.density", "Spacing", [("comfortable", "Comfortable"), ("compact", "Compact")], ""),
            ("select", "resume.paper", "Paper", [("letter", "US Letter"), ("a4", "A4")], ""),
        ]),
        ("Content", "", [
            ("select", "resume.clearance", "Clearance", [("past", "Show active and past"), ("active", "Active only"), ("hide", "Hide")], ""),
            ("select", "resume.functional_titles", "Plain-English titles", [("paren", "In parentheses"), ("line", "On their own line"), ("hide", "Hide")], ""),
            ("toggle", "resume.summary", "Summary", ""),
            ("toggle", "resume.skills", "Skills", ""),
            ("toggle", "resume.additional", "Additional", ""),
            ("toggle", "resume.education_first", "Education first", "Put education above experience."),
        ]),
        ("Contact line", "", [
            ("toggle", "resume.contact_location", "Location", ""),
            ("toggle", "resume.contact_phone", "Phone", ""),
            ("toggle", "resume.contact_email", "Email", ""),
            ("toggle", "resume.contact_linkedin", "LinkedIn", ""),
        ]),
    ]),
    ("tailoring", "Tailoring", '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>', [
        ("Rewriting", "Applies to new tailorings.", [
            ("select", "tailor.style", "Rewrite style", [("light", "Light touch"), ("balanced", "Balanced"), ("strong", "Strong reframing")], ""),
            ("select", "tailor.questions", "Questions first", [("always", "Always ask"), ("gaps", "Only when Match is under 70"), ("never", "Never ask")], "Claude asks about skills your resume leaves out before tailoring."),
        ]),
        ("Bullets", "", [
            ("number", "tailor.bullets_recent", "Most recent role", "2 to 8 bullets."),
            ("number", "tailor.bullets_older", "Older roles", "1 to 6 bullets."),
        ]),
    ]),
    ("review", "Astra review", '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4 12 14.01l-3-3"/>', [
        ("Astra (ChatGPT)", "Astra grades each tailored resume and sends it back for rework until it passes.", [
            ("toggle", "review.enabled", "Grade every tailored resume", ""),
            ("toggle", "review.ask_facts", "Let Astra ask me for facts", ""),
            ("number", "review.threshold", "Pass score", "60 to 95."),
            ("number", "review.max_rounds", "Max rework rounds", "1 to 4."),
        ]),
    ]),
    ("claude", "Claude usage", '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>', [
        ("Ratings", "Applies from the next update.", [
            ("number", "claude.haiku_per_night", "Quick ratings per night", "Haiku, 0 to 20,000."),
            ("number", "claude.sonnet_pct", "Sonnet: best % of jobs", "0 to 50."),
            ("number", "claude.opus_top", "Opus: top jobs", "0 to 1,000."),
            ("number", "claude.per_update", "Jobs per re-rate", "Most jobs Claude re-rates in one Re-rate or nightly run."),
        ]),
        ("Automatic rating", "", [
            ("toggle", "claude.auto_rate", "Rate new jobs during updates", ""),
            ("toggle", "claude.auto_rerate", "Re-rate overnight when my info changes", ""),
        ]),
    ]),
    ("display", "Display", '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>', [
        ("Board", "", [
            ("select", "display.start_tab", "Start on", [("jobs", "Jobs"), ("pivot", "Target tab"), ("tailored", "Resumes"), ("companies", "Companies")], ""),
            ("select", "display.sort", "Default sort", [("score", "Best overall"), ("odds", "Best match"), ("odds_later", "Best match (alt)"), ("pay", "Highest pay"), ("gd", "Best Glassdoor"), ("new", "Newest")], ""),
            ("select", "display.level", "Default seniority", [("near", "Near my level"), ("mine", "My level"), ("above", "Above my level"), ("below", "Below my level"), ("all", "Any level")], ""),
            ("select", "display.clearance", "Default clearance", [("secret", "Secret or less"), ("nopoly", "No TS/SCI + poly"), ("none", "No clearance mentioned"), ("all", "Any clearance")], ""),
        ]),
        ("Appearance", "", [
            ("select", "display.theme", "Theme", [("system", "Match device"), ("light", "Light"), ("dark", "Dark")], ""),
        ]),
    ]),
]
KEY_CAT = ("apikey", "API key", '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/>')

e = html.escape


def _control(c):
    kind, key = c[0], c[1]
    cid = "p-" + key.replace(".", "-")
    if kind == "select":
        opts = "".join(f'<option value="{e(v)}">{e(t)}</option>' for v, t in c[3])
        return cid, c[2], c[4], f'<select id="{cid}" data-pref="{key}">{opts}</select>'
    if kind == "toggle":
        return cid, c[2], c[3], f'<input type="checkbox" role="switch" class="sw" id="{cid}" data-pref="{key}">'
    lo, hi = people.PREF_SCHEMA[key][1]
    return cid, c[2], c[3], f'<input type="number" inputmode="numeric" min="{lo}" max="{hi}" id="{cid}" data-pref="{key}">'


def _row(label_html, help_text, ctl):
    small = f"<small>{e(help_text)}</small>" if help_text else ""
    return f'<div class="srow"><div class="slab">{label_html}{small}</div><div class="sctl">{ctl}</div></div>'


def _group(title, foot, rows):
    t = f'<h3 class="sgtitle">{e(title)}</h3>' if title else ""
    f = f'<p class="sfoot">{e(foot)}</p>' if foot else ""
    return f'<section class="sgsec">{t}<div class="sgroup">{"".join(rows)}</div>{f}</section>'


def _pane_head(cid, name):
    return (f'<div class="sphead"><a class="sback" href="/settings" data-back>‹ Settings</a>'
            f'<div class="sprow"><h2 id="h-{cid}">{e(name)}</h2><span class="ssave" role="status" aria-live="polite"></span></div></div>')


def _render_parts():
    nav, panes = [], []
    for cid, name, icon, groups in CATEGORIES + [KEY_CAT + (None,)]:
        nav.append(f'<a class="scat" href="#{cid}" data-cat="{cid}"><span class="sico">{_SVG.format(icon)}</span>'
                   f'<span class="sname">{e(name)}</span><span class="schev" aria-hidden="true">›</span></a>')
        if groups is None:
            body = (_group("Status", "", [_row("<span>Anthropic API key</span>", "", '<span class="note" id="keyState">Checking…</span>')]) +
                    _group("Change key", "Scoring runs through your Claude subscription using the Claude Code app on this computer, so a key is "
                           "optional: only if you would rather bill scoring separately. A saved key stays on this computer "
                           "(secrets.json in your Job Board data folder) and is sent only to Anthropic. Ratings are cached, so later updates only rate what's new.",
                           ['<form class="srow stack" id="keyForm"><input type="password" id="keyInput" placeholder="Paste an Anthropic API key (sk-ant-…)" '
                            'autocomplete="off" aria-label="Anthropic API key"><div class="sbtns"><button class="btn primary" type="submit">Save key</button>'
                            '<button class="btn" type="button" id="keyClear">Remove key</button></div></form>']))
        else:
            body = "".join(_group(t, f, [_row(f'<label for="{c_id}">{e(lbl)}</label>', hlp, ctl) for c_id, lbl, hlp, ctl in map(_control, rows)])
                           for t, f, rows in groups)
            body += ('<div class="sreset"><button class="btn ghost sm" type="button" data-reset>Restore all defaults</button>'
                     '<span class="note" data-resetmsg></span></div>')
        panes.append(f'<section class="spane" data-cat="{cid}" aria-labelledby="h-{cid}" hidden>{_pane_head(cid, name)}{body}</section>')
    return "".join(nav), "".join(panes)


def render_settings_html(pid=None) -> str:
    name = e(people.name(pid))
    p = people.prefs(pid)
    nav, panes = _render_parts()
    tools = report.TOOLS.replace('id="prefsBtn" href="/settings"', 'id="prefsBtn" href="/settings" aria-current="page"')
    head = report.HEAD.replace("<title>Job Board</title>", "<title>Settings · " + name + "</title>")
    body = BODY.replace("__TOOLS__", tools).replace("__NAV__", nav).replace("__PANES__", panes).replace("__NAME__", name)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            # Apply the saved theme before first paint so the page doesn't flash the wrong colours.
            "<script>(function(){var t=" + json.dumps(p.get("display.theme")) +
            ';if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;})();</script>' +
            head + CSS + "</head><body>" + body + "<script>window.__PREFS__=" + json.dumps(p).replace("</", "<\\/") +
            ";</script>\n" + SCRIPT + "</body></html>")


CSS = """<style>
.slayout{display:grid;grid-template-columns:230px minmax(0,1fr);gap:28px;margin-top:8px}
.snav{position:sticky;top:calc(12px + env(safe-area-inset-top,0px));align-self:start;display:flex;flex-direction:column;gap:2px}
.scat{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:10px;color:var(--ink);text-decoration:none;font-weight:500}
.scat:hover{background:var(--surface)}
.scat[aria-current="page"]{background:var(--accent-soft);color:var(--accent);font-weight:600}
.sico{width:28px;height:28px;flex:none;border-radius:7px;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent)}
.scat[aria-current="page"] .sico{background:var(--surface)}
.sico svg{width:16px;height:16px}
.sname{flex:1;min-width:0}
.schev,.sback{display:none}
.spanes{min-width:0;max-width:760px}
.sphead{margin-bottom:6px}
.sprow{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.sprow h2{font-size:20px;font-weight:700;margin:0;letter-spacing:-.01em}
.ssave{font-size:12.5px;color:var(--good)}
.ssave.err{color:var(--bad)}
.sgsec{margin-top:18px}
.sgtitle{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px 14px}
.sgroup{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.sfoot{font-size:12.5px;color:var(--muted);margin:6px 14px 0}
.srow{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 14px;min-height:48px;margin:0}
.srow+.srow{border-top:1px solid var(--line)}
.slab{display:flex;flex-direction:column;gap:1px;min-width:0}
.slab label,.slab span{font-weight:500}
.slab small{color:var(--muted);font-size:12.5px}
.sctl{flex:none;display:flex;justify-content:flex-end;max-width:58%}
.sctl select{max-width:100%;width:240px}
.sctl input[type=number]{width:104px;height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;text-align:right}
.srow.stack{flex-direction:column;align-items:stretch}
.srow.stack input{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;width:100%;min-width:0}
.sbtns{display:flex;gap:8px;flex-wrap:wrap}
.sw{appearance:none;-webkit-appearance:none;width:44px;height:26px;border-radius:999px;background:var(--bar);position:relative;cursor:pointer;margin:0;flex:none;transition:background .15s}
.sw::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:var(--surface);box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
.sw:checked{background:var(--accent)}
.sw:checked::after{transform:translateX(18px)}
.sreset{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:18px}
.sreset .note{color:var(--muted);font-size:12.5px}
.sreset [data-reset][data-armed="1"]{color:var(--bad)}
@media (max-width:720px){
  .slayout{display:block}
  .slayout.atList .spanes,.slayout:not(.atList) .snav{display:none}
  .snav{position:static;gap:0;background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  .scat{border-radius:0;padding:10px 14px;min-height:48px}
  .scat+.scat{border-top:1px solid var(--line)}
  .scat[aria-current="page"]{background:none;color:var(--ink);font-weight:500}
  .scat[aria-current="page"] .sico{background:var(--accent-soft)}
  .schev{display:block;color:var(--muted);font-size:20px;line-height:1}
  .sback{display:inline-block;color:var(--accent);text-decoration:none;font-weight:600;padding:6px 0;margin-bottom:2px}
  .sctl{max-width:55%}
  .sctl select{width:100%}
}
</style>
"""

BODY = """<div class="wrap">
<header class="top">
  <div class="brandline">
    <h1>Settings · __NAME__</h1>
  </div>
  <div class="tools" id="tools">
__TOOLS__  </div>
</header>
<div class="slayout atList" id="slayout">
  <nav class="snav" aria-label="Settings categories">__NAV__</nav>
  <div class="spanes">__PANES__</div>
</div>
</div>
"""

SCRIPT = r"""<script>
(function(){
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const phone = () => matchMedia("(max-width:720px)").matches;
let PREFS = window.__PREFS__ || {};
function applyTheme(){
  const t = PREFS["display.theme"];
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("jb.theme", t); } catch(e) {}
}
applyTheme();

// ---- categories: the URL hash picks one (/settings#display); at phone width no hash means "show the list"
const CATS = [...document.querySelectorAll(".spane")].map(p => p.dataset.cat);
function route(){
  const h = location.hash.slice(1), sel = CATS.includes(h) ? h : "", shown = sel || CATS[0];
  $("slayout").classList.toggle("atList", !sel);
  document.querySelectorAll(".scat").forEach(a => a.setAttribute("aria-current", a.dataset.cat === shown ? "page" : "false"));
  document.querySelectorAll(".spane").forEach(p => p.hidden = p.dataset.cat !== shown);
}
window.addEventListener("hashchange", route); route();
document.querySelector(".snav").addEventListener("click", e => {
  const a = e.target.closest(".scat"); if (!a) return;
  e.preventDefault();
  if (location.hash === "#" + a.dataset.cat) return;
  history.pushState({fromList: phone() && !CATS.includes(location.hash.slice(1))}, "", "#" + a.dataset.cat);
  route(); if (phone()) scrollTo(0, 0);
});
document.querySelector(".spanes").addEventListener("click", e => {
  if (!e.target.closest("[data-back]")) return;
  e.preventDefault();
  if (history.state && history.state.fromList) history.back();  // return to the list entry we came from
  else { history.pushState(null, "", location.pathname); route(); }
  scrollTo(0, 0);
});

// ---- preferences: each control saves itself on change (the server merges partial updates)
const prefInputs = () => [...document.querySelectorAll("[data-pref]")];
function fillPrefs(){ prefInputs().forEach(el => { const v = PREFS[el.dataset.pref]; if (el.type === "checkbox") el.checked = !!v; else if (v != null) el.value = String(v); }); }
const valueOf = el => el.type === "checkbox" ? el.checked : el.type === "number" ? +el.value : el.value;
fillPrefs();
let saveTimer = null;
function saveState(el, text, bad){
  const s = (el.closest(".spane") || document).querySelector(".ssave"); if (!s) return;
  s.textContent = text; s.classList.toggle("err", !!bad);
  clearTimeout(saveTimer); if (!bad && text !== "Saving…") saveTimer = setTimeout(() => { s.textContent = ""; }, 2500);
}
function post(body, el){
  saveState(el, "Saving…");
  return fetch("/api/prefs", {method: "POST", headers: H, body: JSON.stringify(body)}).then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
    if (!ok) throw new Error(d.error || "Couldn't save.");
    PREFS = d.prefs || PREFS; fillPrefs(); applyTheme(); saveState(el, "Saved");
  }).catch(err => { fillPrefs(); saveState(el, err instanceof TypeError ? "Couldn't save. Check the connection." : err.message, true); });
}
document.querySelector(".spanes").addEventListener("change", e => {
  const el = e.target.closest("[data-pref]"); if (!el) return;
  if (el.type === "number" && (el.value === "" || !el.checkValidity())) {
    const lo = el.min, hi = el.max; fillPrefs(); saveState(el, `Use a whole number from ${lo} to ${hi}.`, true); return;
  }
  post({prefs: {[el.dataset.pref]: valueOf(el)}}, el);
});
// Restore all defaults: the first tap arms the button, a second tap within 5 s resets every setting.
document.querySelectorAll("[data-reset]").forEach(b => {
  let t = null;
  const msg = b.parentElement.querySelector("[data-resetmsg]");
  const disarm = () => { b.dataset.armed = ""; b.textContent = "Restore all defaults"; msg.textContent = ""; };
  b.addEventListener("click", () => {
    if (b.dataset.armed !== "1") {
      b.dataset.armed = "1"; b.textContent = "Tap again to restore defaults";
      msg.textContent = "Resets every setting on this page (all categories) for this profile.";
      clearTimeout(t); t = setTimeout(disarm, 5000); return;
    }
    clearTimeout(t); disarm();
    post({reset: true}, b).then(() => { if (!b.closest(".spane").querySelector(".ssave.err")) saveState(b, "Defaults restored"); });
  });
});

// ---- optional Anthropic API key
const keyState = () => fetch("/api/settings").then(r => r.json()).then(s => {
  $("keyState").textContent = s.has_key ? "Saved. Scoring is billed to this key instead of your subscription." : "None saved (not needed).";
}).catch(() => { $("keyState").textContent = "Couldn't check. Check the connection."; });
keyState();
$("keyForm").addEventListener("submit", e => {
  e.preventDefault(); const k = $("keyInput").value.trim(); if (!k) return;
  fetch("/api/settings", {method: "POST", headers: H, body: JSON.stringify({anthropic_api_key: k})}).then(() => { $("keyInput").value = ""; keyState(); });
});
$("keyClear").addEventListener("click", () => fetch("/api/settings", {method: "POST", headers: H, body: JSON.stringify({clear: true})}).then(keyState));

// ---- header: Update / Re-rate run on the board, which has the confirm and progress panel
const toBoard = run => { try { if (run) sessionStorage.setItem(run[0], run[1]); } catch(e) {} location.href = "/#jobs"; };
$("updateBtn").addEventListener("click", () => toBoard(["jb.run", "update"]));
$("rerateBtn").addEventListener("click", () => toBoard(["jb.run", "rerate"]));
$("updateBtn").title = "Update job listings now (opens the board): checks every employer for new jobs (about 40 min)";
$("rerateBtn").title = "Re-rate with my latest info (opens the board): Claude re-scores your best jobs, no new listings";
fetch("/api/status").then(r => r.json()).then(s => {
  if (!s.running) return;
  $("updateBtn").disabled = true; $("updateBtn").classList.add("busy"); $("updateBtn").title = "Updating job listings now…";
}).catch(() => {});
fetch("/api/rerate").then(r => r.json()).then(s => {
  if (!s.running) return;
  $("rerateBtn").disabled = true; $("rerateBtn").classList.add("busy"); $("rerateBtn").title = "Re-rating your best jobs now…";
}).catch(() => {});

// ---- profile menu
let curPerson = "";
fetch("/api/people").then(r => r.json()).then(d => {
  curPerson = d.current;
  const me = d.people.find(p => p.id === d.current) || {};
  $("avName").textContent = me.name || "Profile"; $("avInit").textContent = (me.name || "?").trim()[0].toUpperCase();
  $("amPeople").innerHTML = `<div class="who">Profiles</div>` + d.people.map(p => `<button role="menuitem" data-person="${esc(p.id)}" aria-current="${p.id === d.current}">${esc(p.name)}</button>`).join("") + `<button role="menuitem" data-person="__add">Add a person</button>`;
}).catch(() => {});
$("avatarBtn").addEventListener("click", e => { e.stopPropagation(); const h = $("amenu").hidden; $("amenu").hidden = !h; $("avatarBtn").setAttribute("aria-expanded", h); });
document.addEventListener("click", e => { if (!e.target.closest(".menuWrap")) { $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false"); } });
$("amenu").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false");
  if (b.id === "resumeBtn") return toBoard(["jb.openResume", "1"]);
  const v = b.dataset.person; if (!v) return;
  if (v === "__add") return toBoard(["jb.run", "addPerson"]);
  if (v === curPerson) return;
  fetch("/api/person", {method: "POST", headers: H, body: JSON.stringify({id: v})}).then(() => location.reload());
});
})();
</script>
"""
