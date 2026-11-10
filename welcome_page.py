"""First-run page (served at / while there are no profiles yet): name the first person, then go to /setup.
Uses the board's styles (report.HEAD) and POST /api/people/add, which creates the profile and sets the cookie."""
import report


def render_welcome_html() -> str:
    head = report.HEAD.replace("<title>Job Board</title>", "<title>Welcome to Job Board</title>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
            head + CSS + "</head><body>" + BODY + SCRIPT + "</body></html>")


CSS = """<style>
.welcome{max-width:520px;margin:12vh auto 0}
.welcome h1{font-size:26px;margin-bottom:8px}
.welcome p{color:var(--muted);margin:0 0 16px}
.welcome form{display:flex;gap:8px;flex-wrap:wrap}
.welcome input{flex:1 1 220px;min-width:0;height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 12px;font:inherit}
.welcome .msg{color:var(--bad);font-size:13px;margin-top:10px;min-height:1em}
</style>
"""

BODY = """<div class="wrap"><main class="welcome">
  <h1>Welcome to Job Board</h1>
  <p>Each person in your household gets their own board, resume and settings. Start with the first person; a short setup follows (resume, where, pay, level and what you're aiming for).</p>
  <form id="addForm">
    <input type="text" id="name" placeholder="First person's name" aria-label="Name" autocomplete="off" maxlength="40" required>
    <button class="btn primary" type="submit">Add the first person</button>
  </form>
  <div class="msg" id="msg" role="status"></div>
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
