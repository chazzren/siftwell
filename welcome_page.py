"""First-run page (served at / while there are no profiles yet): name the first person, then go to /setup.
The same form adds every later person too (GET /people/new: Settings > Profiles and the profile menu's "Add a person"
lead there), so there is one way to add a person. Uses the board's styles (report.HEAD) and POST /api/people/add,
which creates the profile and sets the cookie; /setup follows."""
import html

import backup
import paths
import report


def render_welcome_html() -> str:
    head = report.HEAD.replace("<title>Siftwell</title>", "<title>Welcome to Siftwell</title>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
            head + CSS + backup.CSS + "</head><body>" + BODY + SCRIPT + backup.SCRIPT + "</body></html>")


def render_add_person_html() -> str:
    """Add a person to a household that already has one: the welcome page's form, without the first-run extras."""
    head = report.HEAD.replace("<title>Siftwell</title>", "<title>Add a person · Siftwell</title>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
            head + CSS + "</head><body>" + ADD_BODY + SCRIPT + report.DOWN_SCRIPT + "</body></html>")


CSS = """<style>
.welcome{max-width:520px;margin:12vh auto 0}
.welcome h1{font-size:26px;margin-bottom:8px}
.welcome p{color:var(--muted);margin:0 0 16px}
.welcome form{display:flex;gap:8px;flex-wrap:wrap}
.welcome input{flex:1 1 220px;min-width:0;height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 12px;font:inherit}
.welcome .more{font-size:13.5px;margin-top:24px}
.welcome .more a,.welcome .back{color:var(--accent);font-weight:600}
.welcome .back{display:inline-block;margin-bottom:18px;text-decoration:none}
.welcome .privacy{margin-top:20px;padding:12px 14px;border:1px solid var(--line);border-radius:var(--r);background:var(--surface);font-size:13.5px;color:var(--muted)}
.welcome .privacy b{color:var(--ink)}
.welcome .privacy small{display:block;margin-top:6px;font-size:12px;word-break:break-all}
.welcome .brandline{margin-bottom:8px}.welcome .brandline h1{margin:0}
.welcome .claude{margin-top:10px;display:flex;flex-direction:column;align-items:flex-start;gap:6px}
.welcome .claude .btn{text-decoration:none;white-space:normal;text-align:center}
.welcome .claude p{margin:0;font-size:13.5px}
.welcome .msg{color:var(--bad);font-size:13px;margin-top:10px;min-height:1em}
</style>
"""

# The form both pages share (SCRIPT below sends it).
FORM = """<form id="addForm">
    <input type="text" id="name" placeholder="__PH__" aria-label="Name" autocomplete="off" maxlength="40" required>
    <button class="btn primary" type="submit">__BTN__</button>
  </form>
  <div class="msg" id="msg" role="status"></div>"""

BODY = """<div class="wrap"><main class="welcome">
  <div class="brandline">""" + report.MARK + """<h1>Welcome to Siftwell</h1></div>
  <p>Each person in your household gets their own board, resume and settings. Start with the first person; a short setup follows (resume, where, pay, level and what you're aiming for).</p>
  """ + FORM.replace("__PH__", "First person's name").replace("__BTN__", "Add the first person") + """
  <div class="claude"><a class="btn" href="/getting-started">Connect Claude first (optional)</a>
    <p>Claude reads your resume, rates how well each job fits you, and tailors your resume. You can also connect it during setup, or skip it: Siftwell works without it.</p></div>
  <div class="privacy"><b>Your information stays on this computer.</b> Siftwell keeps your resume, profiles, saved jobs and ratings in a folder on this PC (not in the cloud). If you connect Claude, job descriptions and your resume are sent to Claude only to rate jobs and tailor resumes.<small>Data folder: <code>""" + html.escape(paths.DATA) + """</code></small></div>
  """ + backup.WELCOME_HTML + """
  <p class="more">The <a href="/getting-started">Get started checklist</a> also checks that this computer can make PDFs, start Siftwell when you sign in, and reach your phone.</p>
</main></div>
"""

ADD_BODY = """<div class="wrap"><main class="welcome">
  <a class="back" href="/settings#profiles">‹ Profiles</a>
  <div class="brandline">""" + report.MARK + """<h1>Add a person</h1></div>
  <p>Each person in your household gets their own board, resume and settings. A short setup follows (resume, where, pay, level and what they're aiming for).</p>
  """ + FORM.replace("__PH__", "Their name").replace("__BTN__", "Continue to setup") + """
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
    .catch(err => { msg.textContent = err instanceof TypeError ? "Couldn't reach Siftwell. Is it still running?" : err.message; });
});
document.getElementById("name").focus();
</script>
"""
