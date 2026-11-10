"""First-run page (served at / while there are no profiles yet): name the first person, then go to /setup.
Uses the board's styles (report.HEAD) and POST /api/people/add, which creates the profile and sets the cookie."""
import html

import backup
import paths
import report


def render_welcome_html() -> str:
    head = report.HEAD.replace("<title>Siftwell</title>", "<title>Welcome to Siftwell</title>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
            head + CSS + backup.CSS + "</head><body>" + BODY + SCRIPT + backup.SCRIPT + "</body></html>")


CSS = """<style>
.welcome{max-width:520px;margin:12vh auto 0}
.welcome h1{font-size:26px;margin-bottom:8px}
.welcome p{color:var(--muted);margin:0 0 16px}
.welcome form{display:flex;gap:8px;flex-wrap:wrap}
.welcome input{flex:1 1 220px;min-width:0;height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 12px;font:inherit}
.welcome .more{font-size:13.5px;margin-top:24px}
.welcome .more a{color:var(--accent);font-weight:600}
.welcome .privacy{margin-top:20px;padding:12px 14px;border:1px solid var(--line);border-radius:var(--r);background:var(--surface);font-size:13.5px;color:var(--muted)}
.welcome .privacy b{color:var(--ink)}
.welcome .privacy small{display:block;margin-top:6px;font-size:12px;word-break:break-all}
.welcome .brandline{margin-bottom:8px}.welcome .brandline h1{margin:0}
.welcome .msg{color:var(--bad);font-size:13px;margin-top:10px;min-height:1em}
</style>
"""

BODY = """<div class="wrap"><main class="welcome">
  <div class="brandline">""" + report.MARK + """<h1>Welcome to Siftwell</h1></div>
  <p>Each person in your household gets their own board, resume and settings. Start with the first person; a short setup follows (resume, where, pay, level and what you're aiming for).</p>
  <form id="addForm">
    <input type="text" id="name" placeholder="First person's name" aria-label="Name" autocomplete="off" maxlength="40" required>
    <button class="btn primary" type="submit">Add the first person</button>
  </form>
  <div class="msg" id="msg" role="status"></div>
  <div class="privacy"><b>Your information stays on this computer.</b> Siftwell keeps your resume, profiles, saved jobs and ratings in a folder on this PC (not in the cloud). If you connect Claude, job descriptions and your resume are sent to Claude only to rate jobs and tailor resumes.<small>Data folder: <code>""" + html.escape(paths.DATA) + """</code></small></div>
  """ + backup.WELCOME_HTML + """
  <p class="more">New here? The <a href="/getting-started">Get started checklist</a> checks this computer and sets up Claude, PDFs and phone access with buttons.</p>
</main></div>
"""

SCRIPT = r"""<script>
document.getElementById("addForm").addEventListener("submit", e => {
  e.preventDefault();
  const msg = document.getElementById("msg"), name = document.getElementById("name").value.trim();
  if (!name) return;
  msg.textContent = "";
  fetch("/api/people/add", {method: "POST", headers: {"Content-Type": "application/json", "X-Jobboard": "1"}, body: JSON.stringify({name})})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => { if (!ok) throw new Error(d.error || "Couldn't create it."); location.href = "/setup"; })
    .catch(err => { msg.textContent = err instanceof TypeError ? "Couldn't reach the board. Is it still running?" : err.message; });
});
</script>
"""
