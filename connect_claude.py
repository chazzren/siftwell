"""The "Connect Claude" card: installs Claude Code and signs in to Claude without leaving the page it sits on.

Used by first-time setup (setup_page.py), so a new person never has to find Settings, then Get started, to connect
Claude. It talks to the same routes as the Get started checklist (getting_started.py):
  POST /api/claude/login {action: "check"}        fresh state: ready / signed_out / not_installed (+ install progress)
  POST /api/getting-started/install                 run the Claude Code installer (answers {already: true} if found)
  GET  /api/getting-started/install                 installer progress
  POST /api/claude/login {action: start|code|cancel} `claude auth login`: sign-in link, then the pasted code

The host page must define .btn / .btn.primary styles and the usual colour tokens (--surface, --line, --accent, ...).
Mount with ConnectClaude.mount(element, {onReady}); onReady runs once Claude is installed and signed in.
The sign-in page opens in the person's normal browser: pywebview.api.open_external in the desktop window (where a
new-window link may open nothing), window.open elsewhere. The link is also shown to copy, in case neither works."""

CSS = """
.cc{border:1.5px solid var(--line);border-radius:var(--r,12px);background:var(--surface);padding:18px;margin-top:8px}
.cc-head{display:flex;gap:12px;align-items:flex-start}
.cc-ico{flex:0 0 auto;width:40px;height:40px;border-radius:10px;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent)}
.cc h2{margin:0;font-size:18px;line-height:1.3}
.cc-head p{margin:4px 0 0;color:var(--muted);font-size:14.5px}
.cc-body{margin-top:14px;display:flex;flex-direction:column;gap:12px}
.cc-step{display:grid;grid-template-columns:28px minmax(0,1fr);gap:4px 12px;align-items:start}
.cc-num{width:26px;height:26px;border-radius:50%;border:2px solid var(--line);display:grid;place-items:center;font-size:13px;font-weight:700;color:var(--muted)}
.cc-step.done .cc-num{background:var(--good);border-color:var(--good);color:var(--surface)}
.cc-step.off{opacity:.55}
.cc-step b{display:block;font-size:15.5px}
.cc-step small{display:block;color:var(--muted);font-size:14px;margin-top:2px}
.cc-act{grid-column:2;display:flex;flex-direction:column;gap:10px;align-items:flex-start;margin-top:6px;min-width:0}
.cc-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;width:100%}
.cc-row input{flex:1 1 200px;min-width:0;height:var(--h,48px);border:1.5px solid var(--line);border-radius:var(--r,12px);padding:0 12px;background:var(--bg);color:var(--ink);font:inherit}
.cc-row input:focus{outline:none;border-color:var(--accent)}
.cc-link{width:100%;font:12.5px var(--mono,monospace);word-break:break-all;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;user-select:all;-webkit-user-select:all}
.cc-log{width:100%;margin:0;max-height:140px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:12px/1.4 var(--mono,monospace);white-space:pre-wrap;word-break:break-word}
.cc-msg{font-size:14px;color:var(--muted)}
.cc-msg.err{color:var(--bad)}
.cc-msg.ok{color:var(--good);font-weight:600}
.cc-ok{display:flex;gap:10px;align-items:center;color:var(--good);font-weight:600}
.cc-ok i{width:26px;height:26px;border-radius:50%;background:var(--good);color:var(--surface);display:grid;place-items:center;font-style:normal;font-size:14px}
.cc-foot{margin-top:12px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:13.5px;color:var(--muted)}
.cc-foot button{border:0;background:transparent;color:var(--accent);font:inherit;font-weight:600;cursor:pointer;padding:6px 8px;border-radius:8px}
.cc-foot button:hover{background:var(--accent-soft)}
.cc .btn.sm{height:40px;padding:0 16px;font-size:15px}
.cc-spin{display:inline-block;width:14px;height:14px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;animation:ccspin .8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes ccspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion: reduce){.cc-spin{animation:none}}
@media (max-width:480px){.cc{padding:14px}.cc-step{grid-template-columns:26px minmax(0,1fr);gap:4px 10px}.cc-act .btn{white-space:normal;height:auto;min-height:44px;padding:8px 14px}}
"""

JS = r"""
window.ConnectClaude = (function(){
  const HD = {"Content-Type": "application/json", "X-Jobboard": "1"};
  const e_ = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const ICON = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>';
  let root = null, opts = {}, st = null, ui = {}, polling = false, lastCheck = 0, readyFired = false;

  const login = body => fetch("/api/claude/login", {method: "POST", headers: HD, credentials: "same-origin", body: JSON.stringify(body)})
    .then(r => r.json().catch(() => ({})).then(d => ({ok: r.ok, d})));
  const live = () => root && root.isConnected;

  function openExternal(u){
    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) { window.pywebview.api.open_external(u); return; }
    } catch(e) {}
    window.open(u, "_blank", "noopener");
  }

  function stepHtml(n, cls, title, sub, act){
    return `<div class="cc-step ${cls}"><span class="cc-num" aria-hidden="true">${cls === "done" ? "✓" : n}</span>
      <div><b>${title}</b>${sub ? `<small>${sub}</small>` : ""}</div>${act ? `<div class="cc-act">${act}</div>` : ""}</div>`;
  }
  const msg = (t, cls) => t ? `<span class="cc-msg ${cls || ""}" role="status">${e_(t)}</span>` : "";

  function installAct(){
    const i = (st && st.install) || {};
    if (i.running) return `<span class="cc-msg"><span class="cc-spin" aria-hidden="true"></span>Installing… ${i.elapsed || 0}s. This usually takes a minute or two.</span>` +
      ((i.lines || []).length ? `<pre class="cc-log">${e_(i.lines.join("\n"))}</pre>` : "");
    let a = `<button class="btn primary sm" type="button" data-cc="install" ${ui.installing ? "disabled" : ""}>${i.exit != null ? "Try again" : "Install Claude Code"}</button>`;
    if (i.exit != null && !i.running) a += msg(i.exit === 0 && i.found === false ? "The installer finished but Claude Code still isn’t found. Try again, or press Check again." :
      "The installer stopped with an error (code " + i.exit + "). Check your internet connection and try again.", "err") +
      ((i.lines || []).length ? `<pre class="cc-log">${e_(i.lines.join("\n"))}</pre>` : "");
    return a + msg(ui.installMsg, ui.installMsgCls);
  }

  function signinAct(){
    if (ui.url) return `<div class="cc-row"><button class="btn primary sm" type="button" data-cc="open">Open the Claude sign-in page</button></div>
      <span class="cc-msg">Sign in with your Claude account in your web browser. If nothing opens, copy this link into your browser:</span>
      <div class="cc-link">${e_(ui.url)}</div>
      <span class="cc-msg">Then copy the code the sign-in page shows and paste it here:</span>
      <div class="cc-row"><input type="text" id="ccCode" placeholder="Paste the code" aria-label="Sign-in code" autocomplete="off" autocapitalize="off" spellcheck="false" value="${e_(ui.code || "")}">
        <button class="btn primary sm" type="button" data-cc="code" ${ui.busy ? "disabled" : ""}>${ui.busy ? "Checking…" : "Finish sign-in"}</button>
        <button class="btn sm" type="button" data-cc="cancel">Cancel</button></div>` + msg(ui.loginMsg, "err");
    return `<button class="btn primary sm" type="button" data-cc="start" ${ui.busy ? "disabled" : ""}>${ui.busy ? "Starting…" : "Sign in to Claude"}</button>` + msg(ui.loginMsg, "err");
  }

  function draw(){
    if (!live()) return;
    const c = $c("ccCode"); if (c) ui.code = c.value;  // keep a half-typed code across redraws
    let body;
    if (!st) body = `<span class="cc-msg"><span class="cc-spin" aria-hidden="true"></span>Checking whether Claude Code is on this computer…</span>`;
    else if (st.ready) body = `<div class="cc-ok"><i aria-hidden="true">✓</i><span>Claude is connected.</span></div>`;
    else if (st.state === "signed_out") body = stepHtml(1, "", "Sign in to Claude",
      "Claude Code is on this computer. Sign in once with your Claude account and you’re done.", signinAct());
    else body = stepHtml(1, "", "Install Claude Code", "Free, from Anthropic. It installs on this computer in a minute or two.", installAct()) +
      stepHtml(2, "off", "Sign in to Claude", "Next, sign in with your Claude account.", "");
    root.querySelector(".cc-body").innerHTML = body;
    const f = root.querySelector(".cc-foot");
    f.hidden = !!(st && st.ready);
    f.innerHTML = `<span>Did it in a terminal, or something looks wrong?</span><button type="button" data-cc="check" ${ui.checking ? "disabled" : ""}>${ui.checking ? "Checking…" : "Check again"}</button>`;
  }
  const $c = id => root && root.querySelector("#" + id);

  async function check(auto){
    if (!live()) return;
    if (auto && (polling || ui.busy || Date.now() - lastCheck < 3000)) return;
    lastCheck = Date.now();
    ui.checking = true; if (!auto) draw();
    let r;
    try { r = await login({action: "check"}); } catch(e) { r = null; }
    ui.checking = false;
    if (!live()) return;
    if (!r || !r.ok) { if (!auto) { ui.installMsg = "Couldn’t reach Siftwell. Is it still running?"; ui.installMsgCls = "err"; draw(); } return; }
    const was = st && st.state;
    if (auto && ui.url && !r.d.ready) return;  // mid sign-in: don't disturb the code box
    st = r.d;
    if (st.state !== "not_installed") { ui.installMsg = ""; }
    if (was === "signed_out" && st.state !== "signed_out") { ui.url = null; ui.loginMsg = ""; }
    draw();
    if (st.install && st.install.running) pollInstall();
    if (st.ready) fireReady();
  }

  function fireReady(){
    if (readyFired) return; readyFired = true;
    const cb = opts.onReady;
    setTimeout(() => { if (cb) cb(); }, 700);
  }

  function pollInstall(){
    if (polling) return; polling = true;
    const tick = () => fetch("/api/getting-started/install", {credentials: "same-origin"}).then(r => r.json()).then(d => {
      if (!live()) { polling = false; return; }
      st = Object.assign({}, st, {install: d});
      if (d.running) { draw(); setTimeout(tick, 1200); return; }
      polling = false; ui.installing = false;
      check(false);
    }).catch(() => { polling = false; ui.installing = false; draw(); });
    tick();
  }

  function onClick(ev){
    const b = ev.target.closest("[data-cc]"); if (!b || !root.contains(b)) return;
    ev.preventDefault();
    const act = b.dataset.cc;
    if (act === "check") check(false);
    if (act === "install") {
      ui.installing = true; ui.installMsg = ""; draw();
      fetch("/api/getting-started/install", {method: "POST", headers: HD, credentials: "same-origin", body: "{}"})
        .then(r => r.json().catch(() => ({})).then(d => ({ok: r.ok, d})))
        .then(({ok, d}) => {
          if (!ok) throw new Error(d.error || "Couldn’t start the installer.");
          if (d.already) { ui.installing = false; ui.installMsg = "Claude Code is already installed on this computer."; ui.installMsgCls = "ok"; return check(false); }
          st = Object.assign({}, st, {install: {running: true, lines: [], exit: null, elapsed: 0}}); draw(); pollInstall();
        })
        .catch(err => { ui.installing = false; ui.installMsg = err instanceof TypeError ? "Couldn’t reach Siftwell. Is it still running?" : err.message; ui.installMsgCls = "err"; draw(); });
    }
    if (act === "start") {
      ui.busy = true; ui.loginMsg = ""; draw();
      login({action: "start"}).then(({ok, d}) => {
        if (!ok) throw new Error(d.error || "Couldn’t start sign-in.");
        ui.url = d.url; ui.code = "";
        openExternal(d.url);
      }).catch(err => { ui.loginMsg = err.message; })
        .finally(() => { ui.busy = false; draw(); const c = $c("ccCode"); if (c) c.focus({preventScroll: true}); });
    }
    if (act === "open" && ui.url) openExternal(ui.url);
    if (act === "code") finish();
    if (act === "cancel") { login({action: "cancel"}); ui.url = null; ui.loginMsg = ""; ui.code = ""; draw(); }
  }

  function finish(){
    const c = $c("ccCode"), code = c ? c.value.trim() : "";
    if (!code) { ui.loginMsg = "Paste the code from the sign-in page first."; draw(); return; }
    ui.code = code; ui.busy = true; ui.loginMsg = ""; draw();
    login({action: "code", code}).then(({ok, d}) => {
      if (!ok) throw Object.assign(new Error(d.error || "Sign-in didn’t go through."), {expired: !!d.expired});
      ui.url = null; ui.code = ""; ui.busy = false;
      return check(false);
    }).catch(err => { ui.busy = false; ui.loginMsg = err.message + (err.expired ? " Press Sign in to Claude to start again." : ""); if (err.expired) ui.url = null; draw(); });
  }

  function onKey(ev){
    if (ev.target && ev.target.id === "ccCode" && ev.key === "Enter") { ev.preventDefault(); ev.stopPropagation(); finish(); }
  }

  // Someone may install or sign in from a terminal, then come back to this window: look again when it regains focus.
  const back = () => { if (live() && !document.hidden && !(st && st.ready)) check(true); };
  window.addEventListener("focus", back);
  document.addEventListener("visibilitychange", back);

  function mount(el, o){
    if (root && root !== el) { root.removeEventListener("click", onClick); root.removeEventListener("keydown", onKey); }
    root = el; opts = o || {}; st = null; ui = {}; readyFired = false; lastCheck = 0;
    root.innerHTML = `<section class="cc" aria-labelledby="ccTitle">
      <div class="cc-head"><span class="cc-ico">${ICON}</span><div><h2 id="ccTitle">Connect Claude</h2>
        <p>Claude Code is a free app from Anthropic. It lets Siftwell use your Claude account to read your resume, rate how well each job fits you, and tailor your resume. Installing it is free; using it needs a paid Claude plan (such as Pro or Max). Siftwell works without it, too.</p></div></div>
      <div class="cc-body" aria-live="polite"></div>
      <div class="cc-foot"></div></section>`;
    root.addEventListener("click", onClick);
    root.addEventListener("keydown", onKey);
    draw();
    check(false);
  }
  return {mount, check: () => check(false)};
})();
"""
