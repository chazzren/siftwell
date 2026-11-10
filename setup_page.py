"""The first-run setup page: one question per screen, Back/Continue, progress dots, resumable.

render_setup_html() returns a self-contained page (inline CSS/JS, same tokens and light/dark behaviour as
report.py). It talks to GET /api/setup, POST /api/setup/step, POST /api/setup/finish and the existing
/api/resume, /api/target/suggest, /api/questions, /api/answers, /api/status and /api/people routes.
Open it with ?mock=1 (or from a file:// URL) to run against an in-page fake server for previewing."""
import json

import claude_cli
import connect_claude
import manual_profile
import people
import setup_flow


def render_setup_html() -> str:
    boot = {"levels": {str(k): v for k, v in setup_flow._levels().items()},
            "sets": [{"id": k, "label": v} for k, v in people.COMPANY_SETS.items()],
            "radii": setup_flow.RADII, "industries": setup_flow.INDUSTRY_IDEAS, "steps": setup_flow.STEPS}
    boot["claude_ready"] = claude_cli.claude_ready()
    return (PAGE.replace("__BOOT__", json.dumps(boot).replace("</", "<\\/"))
            .replace("/*__MANUAL_CSS__*/", manual_profile.CSS + connect_claude.CSS)
            .replace("/*__MANUAL_JS__*/", manual_profile.JS + connect_claude.JS))


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Set up your board</title>
<link rel="icon" type="image/svg+xml" href="/assets/brand/siftwell-mark.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/assets/brand/favicon-16.png">
<link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#152033; --muted:#5b6678; --line:#dde1e8;
  --accent:#23468f; --accent-soft:#e6ecf8; --new:#a35a00; --new-soft:#fbefdc;
  --good:#1d7a4f; --good-soft:#e2f3ea; --warn:#9a5b00; --warn-soft:#fbf0dc; --bad:#a63232; --bad-soft:#f8e4e4;
  --bar:#cfd6e2; --bar-fill:#23468f;
  --sans:"Public Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --r:12px; --h:48px;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0f141c; --surface:#171e29; --ink:#e4e9f1; --muted:#97a2b4; --line:#2a3342;
  --accent:#8fb0f0; --accent-soft:#1f2c45; --new:#f0b25e; --new-soft:#3a2b14;
  --good:#6fcf9c; --good-soft:#163527; --warn:#f0b25e; --warn-soft:#3a2b14; --bad:#ef8b8b; --bad-soft:#3d1c1c;
  --bar:#2f3a4c; --bar-fill:#8fb0f0; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0f141c; --surface:#171e29; --ink:#e4e9f1; --muted:#97a2b4; --line:#2a3342;
  --accent:#8fb0f0; --accent-soft:#1f2c45; --new:#f0b25e; --new-soft:#3a2b14;
  --good:#6fcf9c; --good-soft:#163527; --warn:#f0b25e; --warn-soft:#3a2b14; --bad:#ef8b8b; --bad-soft:#3d1c1c;
  --bar:#2f3a4c; --bar-fill:#8fb0f0; color-scheme:dark}

*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button,input,textarea,select{font:inherit;color:inherit}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}

.shell{min-height:100vh;min-height:100dvh;display:grid;grid-template-rows:auto 1fr auto}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px max(16px,env(safe-area-inset-left)) 0 max(16px,env(safe-area-inset-right));padding-top:max(14px,env(safe-area-inset-top))}
.brand{font-weight:700;font-size:14px;letter-spacing:-.01em;color:var(--muted);display:flex;align-items:center;gap:8px;min-width:0}
.brand svg{flex:0 0 auto}
.later{font-size:14px;color:var(--muted);text-decoration:none;font-weight:600;padding:6px 8px;border-radius:8px;white-space:nowrap}
.later:hover{color:var(--accent);background:var(--accent-soft)}

.dots{display:flex;justify-content:center;align-items:center;gap:8px;list-style:none;margin:18px 0 0;padding:0}
.dots li{display:block}
.dot{display:block;width:8px;height:8px;border-radius:4px;background:var(--line);border:0;padding:0;transition:width .3s ease,background .3s ease}
.dot.done{background:var(--accent);opacity:.45;cursor:pointer}
.dot.done:hover{opacity:.8}
.dot.cur{width:28px;background:var(--accent)}
.stepof{text-align:center;font-size:12.5px;color:var(--muted);margin-top:8px;font-variant-numeric:tabular-nums}

main{width:100%;max-width:620px;margin:0 auto;padding:clamp(24px,6vh,64px) 16px 32px}
.stage{animation:in .35s cubic-bezier(.2,.8,.2,1) both}
.stage.back{animation-name:inback}
@keyframes in{from{opacity:0;transform:translateX(28px)}to{opacity:1;transform:none}}
@keyframes inback{from{opacity:0;transform:translateX(-28px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){.stage,.stage.back{animation:none}.dot{transition:none}}

.eyebrow{font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:0 0 10px}
h1.q{font-size:clamp(28px,6.4vw,38px);line-height:1.15;font-weight:700;letter-spacing:-.025em;margin:0 0 12px;text-wrap:balance}
h1.q:focus{outline:none}
.lede{font-size:clamp(16px,3.6vw,18px);color:var(--muted);margin:0 0 28px;max-width:34em;text-wrap:pretty}
.hero{width:64px;height:64px;border-radius:18px;background:var(--accent);color:var(--surface);display:grid;place-items:center;margin-bottom:24px;box-shadow:0 10px 30px -10px var(--accent)}

.field{display:block;margin:0 0 22px}
.flabel{display:block;font-weight:600;font-size:15px;margin-bottom:8px}
.fhelp{display:block;font-size:14px;color:var(--muted);margin:-2px 0 10px}
.opt{font-weight:500;color:var(--muted);font-size:13px;margin-left:6px}
.big{width:100%;height:56px;padding:0 16px;border:1.5px solid var(--line);border-radius:var(--r);background:var(--surface);font-size:20px;transition:border-color .15s}
.big:focus{border-color:var(--accent);outline:none;box-shadow:0 0 0 4px var(--accent-soft)}
.big[aria-invalid="true"],.affix[aria-invalid="true"],.tags[aria-invalid="true"]{border-color:var(--bad)!important}
textarea.big{height:auto;min-height:120px;padding:14px 16px;font-size:17px;line-height:1.45;resize:vertical}
.affix{display:flex;align-items:center;height:56px;border:1.5px solid var(--line);border-radius:var(--r);background:var(--surface);padding:0 14px;gap:6px;transition:border-color .15s}
.affix:focus-within{border-color:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
.affix span{color:var(--muted);font-size:18px}
.affix input{flex:1;min-width:0;border:0;background:transparent;font-size:20px;height:100%;outline:none;font-variant-numeric:tabular-nums}
.err{color:var(--bad);font-size:14px;font-weight:600;margin-top:8px;display:flex;gap:6px;align-items:flex-start}
.err:empty{display:none}

/* choice cards: native radio/checkbox, styled label */
.choices{display:grid;gap:10px}
.choices.cols3{grid-template-columns:repeat(3,minmax(0,1fr))}
.choices.cols2{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{position:relative;display:flex;gap:14px;align-items:flex-start;padding:16px;border:1.5px solid var(--line);border-radius:var(--r);background:var(--surface);cursor:pointer;transition:border-color .15s,background .15s}
.card:hover{border-color:var(--muted)}
.card input{position:absolute;opacity:0;pointer-events:none}
.card:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
.card:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:2px}
.card:has(input:disabled){opacity:.45;cursor:not-allowed}
.card .tick{flex:0 0 auto;width:22px;height:22px;border-radius:50%;border:1.5px solid var(--line);display:grid;place-items:center;margin-top:1px;background:var(--surface);transition:all .15s}
.card input[type=checkbox]~.tick{border-radius:6px}
.card:has(input:checked) .tick{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.card .tick svg{opacity:0}
.card:has(input:checked) .tick svg{opacity:1}
.card .ct{min-width:0;flex:1}
.card b{display:block;font-size:16px;font-weight:600}
.card small{display:block;color:var(--muted);font-size:14px;margin-top:2px;line-height:1.4}
.card .ico{flex:0 0 auto;width:40px;height:40px;border-radius:10px;background:var(--bg);display:grid;place-items:center;color:var(--accent)}
.card:has(input:checked) .ico{background:var(--surface)}
.card.compact{flex-direction:column;align-items:center;text-align:center;gap:8px;padding:16px 10px}
.card.compact .tick{position:absolute;top:10px;right:10px;width:18px;height:18px}
.pill{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.03em;padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent);vertical-align:2px;margin-left:6px}
.pill.good{background:var(--good-soft);color:var(--good)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
.pill.new{background:var(--new-soft);color:var(--new)}

/* segmented */
.seg{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;padding:4px;gap:4px;border:1.5px solid var(--line);border-radius:var(--r);background:var(--surface)}
.seg label{position:relative;display:grid;place-items:center;text-align:center;min-height:44px;padding:6px 8px;border-radius:8px;cursor:pointer;color:var(--muted);font-weight:600;font-size:14.5px;line-height:1.2}
.seg label small{display:block;font-weight:500;font-size:12px;opacity:.85}
.seg input{position:absolute;opacity:0;pointer-events:none}
.seg label:has(input:checked){background:var(--accent);color:var(--surface)}
.seg label:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:2px}

/* slider */
.slider{padding:6px 2px 0}
.slider .val{font-size:28px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin-bottom:6px}
.slider .val span{font-size:16px;color:var(--muted);font-weight:500;margin-left:4px}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:28px;background:transparent;margin:0}
input[type=range]::-webkit-slider-runnable-track{height:6px;border-radius:3px;background:linear-gradient(to right,var(--accent) var(--p,50%),var(--bar) var(--p,50%))}
input[type=range]::-moz-range-track{height:6px;border-radius:3px;background:var(--bar)}
input[type=range]::-moz-range-progress{height:6px;border-radius:3px;background:var(--accent)}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:26px;height:26px;border-radius:50%;background:var(--surface);border:2px solid var(--accent);margin-top:-10px;box-shadow:0 2px 6px rgba(0,0,0,.18)}
input[type=range]::-moz-range-thumb{width:22px;height:22px;border-radius:50%;background:var(--surface);border:2px solid var(--accent)}
.ticks{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-top:4px;font-variant-numeric:tabular-nums}
.ticks span{width:0;display:flex;justify-content:center;white-space:nowrap}
.slider:has(input:disabled){opacity:.45}

/* switch row */
.switchrow{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px;border:1.5px solid var(--line);border-radius:var(--r);background:var(--surface)}
.switchrow b{display:block;font-weight:600}
.switchrow small{display:block;color:var(--muted);font-size:14px}
.switch{flex:0 0 auto;width:52px;height:32px;border-radius:16px;border:0;background:var(--bar);position:relative;cursor:pointer;transition:background .2s}
.switch::after{content:"";position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.25);transition:transform .2s}
.switch[aria-checked="true"]{background:var(--accent)}
.switch[aria-checked="true"]::after{transform:translateX(20px)}
.switch:disabled{opacity:.45;cursor:not-allowed}

/* section label inside a screen */
.sect{font-size:12.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:30px 0 12px}
.sect:first-of-type{margin-top:0}

/* tags */
.tags{display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-height:56px;padding:8px 10px;border:1.5px solid var(--line);border-radius:var(--r);background:var(--surface);cursor:text}
.tags:focus-within{border-color:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
.tag{display:inline-flex;align-items:center;gap:4px;height:34px;padding:0 6px 0 12px;border-radius:999px;background:var(--accent-soft);color:var(--accent);font-weight:600;font-size:14.5px;max-width:100%}
.tag span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag button{border:0;background:transparent;color:inherit;width:24px;height:24px;border-radius:50%;cursor:pointer;display:grid;place-items:center;padding:0}
.tag button:hover{background:var(--surface)}
.tags input{flex:1 1 140px;min-width:120px;border:0;background:transparent;height:38px;font-size:16px;outline:none}
.ideas{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.idea{height:34px;padding:0 12px;border-radius:999px;border:1.5px dashed var(--line);background:transparent;color:var(--muted);font-weight:600;font-size:14px;cursor:pointer}
.idea:hover{border-color:var(--accent);color:var(--accent)}

/*__MANUAL_CSS__*/
/* resume */
.drop{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;text-align:center;padding:40px 20px;border:2px dashed var(--line);border-radius:16px;background:var(--surface);transition:border-color .15s,background .15s}
.drop.over{border-color:var(--accent);background:var(--accent-soft)}
.drop .ico{width:56px;height:56px;border-radius:16px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center}
.drop b{font-size:18px}
.drop small{color:var(--muted);font-size:14px}
.alt{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:16px}
.linkbtn{border:0;background:transparent;color:var(--accent);font-weight:600;cursor:pointer;padding:8px 10px;border-radius:8px;font-size:15px}
.linkbtn:hover{background:var(--accent-soft)}
.have{display:flex;gap:14px;align-items:center;padding:18px;border:1.5px solid var(--line);border-radius:16px;background:var(--surface)}
.have .ico{width:48px;height:48px;border-radius:12px;background:var(--good-soft);color:var(--good);display:grid;place-items:center;flex:0 0 auto}
.have b{display:block;overflow-wrap:anywhere}
.have small{color:var(--muted)}

.working{display:flex;flex-direction:column;align-items:center;text-align:center;gap:18px;padding:36px 8px}
.spinner{width:44px;height:44px;border-radius:50%;border:4px solid var(--accent-soft);border-top-color:var(--accent);animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion: reduce){.spinner{animation-duration:3s}}
.working p{margin:0;color:var(--muted);max-width:28em}

/* highlights */
.hgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.hcard{padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--surface);min-width:0;animation:pop .4s cubic-bezier(.2,.8,.2,1) both}
.hcard.wide{grid-column:1 / -1}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){.hcard{animation:none}}
.hhead{display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.hhead i{width:28px;height:28px;border-radius:8px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;font-style:normal}
.hval{font-size:26px;font-weight:700;letter-spacing:-.02em}
.hdetail{color:var(--muted);font-size:14px}
.hcard ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px;font-size:15px}
.hcard li{padding-left:14px;position:relative}
.hcard li::before{content:"";position:absolute;left:0;top:.6em;width:5px;height:5px;border-radius:50%;background:var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:13.5px;padding:4px 10px;border-radius:999px;background:var(--bg);border:1px solid var(--line)}
.fine{font-size:14px;color:var(--muted);margin-top:16px}

/* info callout */
.hint{display:flex;gap:12px;padding:14px 16px;border-radius:var(--r);background:var(--accent-soft);color:var(--ink);margin:0 0 24px;font-size:15px}
.hint svg{flex:0 0 auto;color:var(--accent);margin-top:2px}
.hint b{font-variant-numeric:tabular-nums}
.hint small{display:block;color:var(--muted);font-size:13px;margin-top:2px}
.note{font-size:14.5px;color:var(--muted);padding:14px 16px;border-radius:var(--r);border:1px dashed var(--line)}

/* level guess */
.guess{display:flex;align-items:center;gap:16px;padding:20px;border-radius:16px;background:var(--surface);border:1px solid var(--line);margin-bottom:24px}
.guess .lv{flex:0 0 auto;width:56px;height:56px;border-radius:14px;background:var(--accent);color:var(--surface);display:grid;place-items:center;font-size:24px;font-weight:700;font-family:var(--mono)}
.guess b{display:block;font-size:20px;letter-spacing:-.01em}
.guess small{color:var(--muted);font-size:14px}
details.pick{margin-bottom:8px}
details.pick summary{cursor:pointer;color:var(--accent);font-weight:600;padding:6px 0;list-style:none}
details.pick summary::-webkit-details-marker{display:none}
details.pick summary::after{content:" \25BE"}
details.pick[open] summary::after{content:" \25B4"}
.levels{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:10px 0 0}
.levels .card{padding:12px;gap:10px;align-items:center}
.levels .card b{font-size:14.5px}
.levels .card small{font-size:12.5px}

/* questions */
.qcount{font-size:13px;font-weight:700;color:var(--muted);letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}
h1.q.qtext{font-size:clamp(20px,4.6vw,24px);font-weight:600;line-height:1.3;letter-spacing:-.01em;margin:0 0 8px}
.qwhy{color:var(--muted);margin:0 0 20px}

/* board */
.checklist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.checklist li{display:flex;gap:14px;align-items:flex-start;padding:12px 0}
.checklist .st{flex:0 0 auto;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;border:2px solid var(--line);color:transparent;transition:all .2s}
.checklist li.done .st{background:var(--good);border-color:var(--good);color:var(--surface)}
.checklist li.run .st{border-color:var(--accent-soft);border-top-color:var(--accent);animation:spin 1s linear infinite}
.checklist li.wait{color:var(--muted)}
.checklist b{display:block;font-weight:600}
.checklist small{display:block;color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums}
.bar{height:8px;border-radius:4px;background:var(--bar);overflow:hidden;margin:24px 0 8px}
.bar i{display:block;height:100%;width:0;background:var(--accent);border-radius:4px;transition:width .6s ease}

/* footer */
.foot{position:sticky;bottom:0;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-top:1px solid var(--line);padding:12px max(16px,env(safe-area-inset-right)) max(12px,env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left))}
.foot .in{max-width:620px;margin:0 auto;display:flex;align-items:center;gap:8px}
.foot .sp{flex:1}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:var(--h);padding:0 22px;border-radius:var(--r);border:1.5px solid var(--line);background:var(--surface);font-weight:600;font-size:16px;cursor:pointer;white-space:nowrap;text-decoration:none;color:var(--ink)}
.btn:hover{border-color:var(--muted)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--surface);min-width:140px}
.btn.primary:hover{filter:brightness(1.08)}
.btn.ghost{background:transparent;border-color:transparent;color:var(--muted);padding:0 14px}
.btn.ghost:hover{color:var(--accent);background:var(--accent-soft)}
.btn:disabled{opacity:.5;cursor:not-allowed;filter:none}
.btn .spin{width:16px;height:16px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;animation:spin .8s linear infinite}

.mockbar{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;justify-content:center;font-size:12.5px;color:var(--warn);background:var(--warn-soft);padding:6px 12px}
.mockbar button{border:0;background:transparent;color:inherit;font-weight:700;cursor:pointer;text-decoration:underline;padding:2px 4px;font-size:12.5px}
.toast{position:fixed;left:50%;top:max(16px,env(safe-area-inset-top));transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 16px;border-radius:999px;font-size:14px;font-weight:600;z-index:20;box-shadow:0 8px 24px rgba(0,0,0,.2);animation:pop .3s both;max-width:calc(100vw - 32px)}

@media (max-width:520px){
  .choices.cols3,.choices.cols2{grid-template-columns:1fr}
  .choices.cols3 .card.compact{flex-direction:row;text-align:left;justify-content:flex-start;padding:14px 16px}
  .choices.cols3 .card.compact .tick{position:static;order:3;margin-left:auto}
  .hgrid{grid-template-columns:1fr}
  .levels{grid-template-columns:repeat(2,minmax(0,1fr))}
  .btn{padding:0 16px}
  .btn.primary{min-width:0;flex:0 1 auto}
  .foot .btn.ghost{padding:0 10px}
  .seg label{font-size:13.5px;padding:6px 4px}
}
</style>
</head>
<body>
<div id="mockbar" class="mockbar" hidden>
  <span>Preview mode: no server, nothing is saved.</span>
  <button type="button" id="mockReset">Start over</button>
  <button type="button" id="mockTheme">Theme: system</button>
</div>
<div class="shell">
  <div>
    <div class="top">
      <div class="brand"><svg width="24" height="24" viewBox="16 12 80 92" aria-hidden="true" style="color:var(--ink)"><g fill="currentColor"><circle cx="38" cy="20" r="4"/><circle cx="56" cy="20" r="4"/><circle cx="74" cy="20" r="4"/></g><polygon points="22,32 90,32 64,62 64,78 48,78 48,62" fill="none" stroke="currentColor" stroke-width="7" stroke-linejoin="round"/><circle cx="56" cy="94" r="6" fill="#FAC775"/></svg><span>Siftwell setup</span></div>
      <a class="later" id="later" href="/">Finish later</a>
    </div>
    <ol class="dots" id="dots" aria-label="Setup progress"></ol>
    <div class="stepof" id="stepof" aria-hidden="true"></div>
  </div>
  <main>
    <form id="form" novalidate autocomplete="off">
      <div id="stage" class="stage"></div>
    </form>
    <div id="live" class="sr" aria-live="polite"></div>
  </main>
  <div class="foot" id="foot">
    <div class="in">
      <button type="button" class="btn ghost" id="back">Back</button>
      <span class="sp"></span>
      <button type="button" class="btn ghost" id="skip" hidden>Skip</button>
      <button type="submit" form="form" class="btn primary" id="next">Continue</button>
    </div>
  </div>
</div>

<script>
"use strict";
const BOOT = __BOOT__;
const qs = new URLSearchParams(location.search);
const MOCK = qs.has("mock") || location.protocol === "file:";
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtK = n => n == null || n === "" ? "" : "$" + Math.round(n / 1000) + "k";
const clone = o => JSON.parse(JSON.stringify(o));

// Steps and how they map onto the ten progress dots (the highlights screen shares the resume dot).
const DOT = {welcome:0, resume:1, highlights:1, where:2, pay:3, level:4, direction:5, dealbreakers:6, companies:7, questions:8, board:9};
const DOT_NAMES = ["Welcome", "Resume", "Where", "Pay", "Level", "Direction", "Dealbreakers", "Companies", "Questions", "Your board"];
const STEPS = BOOT.steps;

const I = {
  check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  x: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>',
  wave: '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M4 12h10M4 17h13" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  doc: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 3v5h5M9 13h6M9 17h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  up: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 16V4m0 0l-4.5 4.5M12 4l4.5 4.5M5 15v3a2 2 0 002 2h10a2 2 0 002-2v-3" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 11v5M12 7.5v.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  alert: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" style="flex:0 0 auto;margin-top:2px"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 7v6M12 16.5v.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  clock: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="2"/><path d="M12 7.5V12l3 2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  cap: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2.5 9L12 4.5 21.5 9 12 13.5 2.5 9z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M6.5 11v4.5c0 1.4 2.5 3 5.5 3s5.5-1.6 5.5-3V11" stroke="currentColor" stroke-width="1.9"/></svg>',
  badge: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="9.5" r="5.5" stroke="currentColor" stroke-width="1.9"/><path d="M8.5 14l-1.5 7 5-2.5 5 2.5-1.5-7" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
  shield: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.5-4.3-1.2-7.5-4.9-7.5-9.5V6L12 3z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
  spark: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
  dot: '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="currentColor"/></svg>',
  home: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3.5 11L12 4l8.5 7M6 9.5V20h12V9.5" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
  building: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="3.5" width="14" height="17" rx="1.5" stroke="currentColor" stroke-width="1.9"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M10 20.5v-4h4v4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
  split: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3.5 11L9 6.5l5.5 4.5M5.5 9.5V18h7" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><rect x="14" y="9" width="7" height="11" rx="1" stroke="currentColor" stroke-width="1.9"/></svg>',
  laptop: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="5" width="14" height="10" rx="1.5" stroke="currentColor" stroke-width="1.9"/><path d="M2.5 19h19" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
  arrow: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 12h15m0 0l-5-5m5 5l-5 5" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  target: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.9"/><circle cx="12" cy="12" r="4.5" stroke="currentColor" stroke-width="1.9"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
  compass: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.9"/><path d="M15.5 8.5l-2 5-5 2 2-5 5-2z" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
};

// ------------------------------------------------------------------ API (real or mock)
async function api(method, path, body){
  if (MOCK) return Mock.handle(method, path, body);
  const r = await fetch(path, {method, headers: method === "POST" ? H : {}, body: method === "POST" ? JSON.stringify(body || {}) : undefined, credentials: "same-origin"});
  let d = {};
  try { d = await r.json(); } catch(e) {}
  if (!r.ok) { const e = new Error(d.error || `Something went wrong (${r.status}).`); e.field = d.field; e.status = r.status; throw e; }
  return d;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
/*__MANUAL_JS__*/
// Claude is optional: false when it isn't installed / signed in (the server says so in /api/setup and in BOOT).
const NOCL = () => !MOCK && ((S && S.claude) ? S.claude.ready === false : BOOT.claude_ready === false);
const NEED_CL = "Needs Claude. Connect it below, or later in Settings.";
// The inline Connect Claude card (connect_claude.py): installs Claude Code and signs in without leaving setup. Once
// connected, refresh the state and redraw the current step in its with-Claude form (the resume step switches to upload).
function mountConnect(el){
  ConnectClaude.mount(el, {onReady: async () => {
    BOOT.claude_ready = true;
    try { const d = await api("GET", "/api/setup"); if (d && d.values) S = d; } catch(e) {}
    S.claude = Object.assign({}, S.claude, {ready: true});
    toast("Claude is connected.");
    if (cur === "direction") V.direction = radio("dir") || V.direction;
    if (cur === "resume") local = {mode: ""};
    if (["resume", "direction", "questions"].includes(cur)) render();
  }});
}

// ------------------------------------------------------------------ state
let S = null;          // last state from the server
let V = null;          // working copy of S.values for the screen being edited
let cur = "welcome";
let dir = 1;
let local = {};        // per-screen transient UI state (suggestions, questions, upload mode)

function say(msg){ $("live").textContent = ""; setTimeout(() => { $("live").textContent = msg; }, 30); }
function toast(msg){
  const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 3200);
}

function renderDots(){
  const furthest = STEPS.indexOf(S.step);
  const curDot = DOT[cur];
  $("dots").innerHTML = DOT_NAMES.map((n, i) => {
    const reachable = i !== curDot && i <= DOT[S.step] && cur !== "board" && S.step !== "board";
    const cls = "dot" + (i === curDot ? " cur" : i < Math.max(curDot, DOT[STEPS[furthest]] || 0) ? " done" : "");
    const label = `${n}${i === curDot ? " (current step)" : i < curDot ? " (done)" : ""}`;
    return `<li>${reachable ? `<button type="button" class="${cls}" data-dot="${i}" aria-label="Go to ${esc(label)}"></button>`
                            : `<span class="${cls}" role="img" aria-label="${esc(label)}"${i === curDot ? ' aria-current="step"' : ""}></span>`}</li>`;
  }).join("");
  $("stepof").textContent = `Step ${curDot + 1} of ${DOT_NAMES.length}`;
}
$("dots").addEventListener("click", e => {
  const b = e.target.closest("[data-dot]"); if (!b) return;
  const i = +b.dataset.dot; const step = STEPS.find(s => DOT[s] === i);
  if (step) go(step === "resume" && S.resume.status !== "none" ? "highlights" : step, i < DOT[cur] ? -1 : 1);
});

function go(step, d){
  dir = d || 1; cur = step; local = {};
  V = clone(S.values);
  render();
}

function render(){
  const scr = SCREENS[cur];
  const st = $("stage");
  st.className = "stage" + (dir < 0 ? " back" : "");
  void st.offsetWidth;  // restart the slide-in animation
  st.innerHTML = scr.html();
  renderDots();
  footer(scr.foot ? scr.foot() : {});
  if (scr.mount) scr.mount();
  const f = st.querySelector("[data-autofocus]") || st.querySelector("h1.q");
  if (f) f.focus({preventScroll: true});
  window.scrollTo({top: 0});
  document.title = (scr.title || "Set up your board") + " · Siftwell";
}

function footer(o){
  $("back").hidden = o.back === false;
  $("skip").hidden = !o.skip; $("skip").textContent = o.skipLabel || "Skip";
  $("next").hidden = o.next === false;
  $("next").innerHTML = esc(o.nextLabel || "Continue");
  $("next").disabled = !!o.disabled;
  $("foot").hidden = o.hide === true;
  $("later").hidden = cur === "board";
}
function busy(on, label){
  $("next").disabled = on; $("back").disabled = on; $("skip").disabled = on;
  if (on) $("next").innerHTML = `<span class="spin" aria-hidden="true"></span>${esc(label || "Saving")}`;
}

function showErr(field, msg){
  document.querySelectorAll(".err").forEach(e => { e.textContent = ""; });
  document.querySelectorAll("[aria-invalid]").forEach(e => e.removeAttribute("aria-invalid"));
  if (!msg) return;
  const box = document.querySelector(`.err[data-for="${field}"]`) || document.querySelector(".err[data-for='_']");
  if (box) box.innerHTML = I.alert + `<span>${esc(msg)}</span>`;
  const inp = document.querySelector(`[data-field="${field}"]`);
  if (inp) {
    inp.setAttribute("aria-invalid", "true");
    const f = inp.matches("input,textarea,select") ? inp : inp.querySelector("input:not([disabled]),textarea");
    if (f) f.focus({preventScroll: true});
    (box || inp).scrollIntoView({block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
  }
  say(msg);
}
const errBox = f => `<div class="err" data-for="${f}" id="err-${f}"></div>`;

async function saveAndNext(step, data, nextStep){
  showErr();
  busy(true);
  try {
    const d = await api("POST", "/api/setup/step", {step, data});
    S = d.state || d;
    go(nextStep || STEPS[STEPS.indexOf(step) + 1]);
  } catch(e) {
    busy(false); footer(SCREENS[cur].foot ? SCREENS[cur].foot() : {});
    showErr(e.field || "_", e.message);
  }
}

$("form").addEventListener("input", e => { const f = e.target.closest("[data-field]"); if (f && f.getAttribute("aria-invalid")) showErr(); });
$("form").addEventListener("change", e => { const f = e.target.closest("[data-field]"); if (f && f.getAttribute("aria-invalid")) showErr(); });
$("form").addEventListener("submit", e => { e.preventDefault(); const s = SCREENS[cur]; if (!$("next").disabled && !$("next").hidden) s.next ? s.next() : saveAndNext(cur, s.collect ? s.collect() : {}); });
$("back").addEventListener("click", () => { const s = SCREENS[cur]; if (s.back && s.back() === false) return; const i = STEPS.indexOf(cur); let p = STEPS[i - 1]; if (p === "resume" && S.resume.status !== "none" && cur === "where") p = "highlights"; if (p) go(p, -1); });
$("skip").addEventListener("click", () => { const s = SCREENS[cur]; s.skip ? s.skip() : saveAndNext(cur, {}); });
document.addEventListener("keydown", e => {
  if (e.altKey && e.key === "ArrowLeft" && !$("back").hidden && !$("back").disabled) { e.preventDefault(); $("back").click(); }
});

// ------------------------------------------------------------------ small builders
function radioCard(name, value, checked, title, sub, opts){
  opts = opts || {};
  return `<label class="card${opts.compact ? " compact" : ""}">
    <input type="${opts.type || "radio"}" name="${name}" value="${esc(value)}"${checked ? " checked" : ""}${opts.disabled ? " disabled" : ""}${opts.field ? ` data-field="${opts.field}"` : ""}>
    ${opts.icon ? `<span class="ico">${opts.icon}</span>` : ""}
    <span class="ct"><b>${title}</b>${sub ? `<small>${sub}</small>` : ""}</span>
    <span class="tick">${I.check}</span></label>`;
}
function tagInput(id, items, placeholder, label){
  return `<div class="tags" id="${id}" data-field="${id}" role="group" aria-label="${esc(label)}">${items.map(t => tagChip(t)).join("")}
    <input type="text" aria-label="${esc(label)}: type and press Enter to add" placeholder="${esc(placeholder)}" enterkeyhint="done"></div>`;
}
const tagChip = t => `<span class="tag" data-v="${esc(t)}"><span>${esc(t)}</span><button type="button" aria-label="Remove ${esc(t)}">${I.x}</button></span>`;
function mountTags(id){
  const box = $(id), inp = box.querySelector("input");
  const add = v => { v = v.trim().replace(/\s+/g, " "); if (!v) return; if ([...box.querySelectorAll(".tag")].some(t => t.dataset.v.toLowerCase() === v.toLowerCase())) return; inp.insertAdjacentHTML("beforebegin", tagChip(v)); say(`Added ${v}`); };
  box.addEventListener("click", e => { const b = e.target.closest(".tag button"); if (b) { const t = b.parentElement; say(`Removed ${t.dataset.v}`); t.remove(); inp.focus(); return; } if (e.target === box) inp.focus(); });
  inp.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === ",") { if (inp.value.trim()) { e.preventDefault(); add(inp.value); inp.value = ""; } else if (e.key === ",") e.preventDefault(); }
    else if (e.key === "Backspace" && !inp.value) { const l = box.querySelectorAll(".tag"); if (l.length) { say(`Removed ${l[l.length - 1].dataset.v}`); l[l.length - 1].remove(); } }
  });
  inp.addEventListener("blur", () => { if (inp.value.trim()) { add(inp.value); inp.value = ""; } });
  return {add, values: () => [...box.querySelectorAll(".tag")].map(t => t.dataset.v)};
}
const checked = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(i => i.value);
const radio = name => (document.querySelector(`input[name="${name}"]:checked`) || {}).value;
const toK = v => v == null || v === "" ? "" : String(Math.round(v / 1000));

// ------------------------------------------------------------------ screens
const SCREENS = {};

SCREENS.welcome = {
  title: "Welcome",
  html: () => `
    <div class="hero">${I.wave}</div>
    <h1 class="q" tabindex="-1">Welcome. Let’s set up your job board.</h1>
    <p class="lede">A few quick questions and your board will show the jobs worth your time. It takes about five minutes, and you can stop anytime: we’ll pick up where you left off.</p>
    <label class="field"><span class="flabel">What should we call you?</span>
      <input class="big" id="name" data-field="name" data-autofocus value="${esc(V.name)}" maxlength="40" autocomplete="given-name" aria-describedby="err-name">
      ${errBox("name")}</label>`,
  foot: () => ({back: false, nextLabel: "Get started"}),
  collect: () => ({name: $("name").value}),
};

SCREENS.resume = {
  title: "Your resume",
  html: () => {
    const r = S.resume;
    if (r.status === "reading" || local.reading) return `
      <h1 class="q" tabindex="-1">Reading your resume…</h1>
      <div class="working" role="status"><div class="spinner" aria-hidden="true"></div>
        <p>Pulling out your experience, education, certifications and skills. This usually takes about a minute. You can keep this page open or come back later.</p></div>`;
    if (r.status !== "none" && !local.replace) return `
      <p class="eyebrow">Your resume</p>
      <h1 class="q" tabindex="-1">${r.manual ? "We have your profile." : "We already have your resume."}</h1>
      <p class="lede">${r.manual ? "You filled it in yourself. Use it as is, or change it." : "Use it as is, or upload a newer one."}</p>
      <div class="have"><span class="ico">${I.doc}</span><div><b>${esc((r.file || "Resume").replace(/^\d{8}-\d{6}_/, ""))}</b><small>${r.manual ? "Filled in by you" : "Read and ready"}</small></div></div>
      <div class="alt"><button type="button" class="linkbtn" id="replace">${r.manual ? "Change it" : "Upload a different resume"}</button></div>`;
    if (local.mode === "manual") return `
      <p class="eyebrow">Your profile</p>
      <h1 class="q" tabindex="-1">Tell us about your work.</h1>
      <p class="lede">${NOCL() ? "Fill in this short form instead of having Claude read a resume (a Word or text resume can fill it in for you)." : "Fill in the short form below instead of uploading a resume."} Your answers stay on this computer.</p>
      <div id="mpRoot"></div>${errBox("_")}
      <div class="alt"><button type="button" class="linkbtn" id="modeFile">${NOCL() ? "Connect Claude instead" : "Upload a resume instead"}</button></div>`;
    if (NOCL() && !local.mode) return `
      <p class="eyebrow">Your resume</p>
      <h1 class="q" tabindex="-1">Add your resume.</h1>
      <p class="lede">Claude reads your resume to build your profile, so we can match jobs to you and tailor applications later. Connect Claude here first (a couple of minutes), or skip Claude and fill in a short form.</p>
      <div id="ccRoot"></div>
      <div class="alt"><button type="button" class="linkbtn" id="modeManual">Skip Claude and fill in a short form</button></div>${errBox("_")}`;
    return `
      <p class="eyebrow">Your resume</p>
      <h1 class="q" tabindex="-1">Add your resume.</h1>
      <p class="lede">It’s how we match jobs to you, guess your level, and tailor applications later. Claude reads it to build your profile; the file is kept with your profile on this computer.</p>
      ${local.mode === "paste" ? `
        <label class="field"><span class="flabel">Paste your resume text</span>
          <textarea class="big" id="paste" data-field="paste" rows="10" data-autofocus placeholder="Paste the full text of your resume here"></textarea>${errBox("paste")}</label>
        <div class="alt"><button type="button" class="linkbtn" id="modeFile">Upload a file instead</button></div>` :
      local.mode === "gdoc" ? `
        <label class="field"><span class="flabel">Google Docs link</span>
          <span class="fhelp">Sharing must be set to “Anyone with the link can view”.</span>
          <input class="big" id="gdoc" data-field="gdoc" type="url" inputmode="url" data-autofocus placeholder="https://docs.google.com/document/d/…">${errBox("gdoc")}</label>
        <div class="alt"><button type="button" class="linkbtn" id="modeFile">Upload a file instead</button></div>` : `
        <div class="drop" id="drop">
          <span class="ico">${I.up}</span>
          <b>Drop your resume here</b>
          <small>PDF, Word (.docx) or text, up to 15 MB</small>
          <small>Your resume is saved only on this computer.</small>
          <label class="btn primary" style="margin-top:4px" for="file" id="pick" tabindex="0" role="button">Choose a file</label>
          <input type="file" id="file" class="sr" accept=".pdf,.doc,.docx,.rtf,.odt,.txt,.md,.png,.jpg,.jpeg,.heic" tabindex="-1">
        </div>
        ${errBox("file")}
        <div class="alt"><button type="button" class="linkbtn" id="modePaste">Paste text instead</button><button type="button" class="linkbtn" id="modeGdoc">Use a Google Docs link</button><button type="button" class="linkbtn" id="modeManual">Fill in my profile myself</button></div>`}
      ${errBox("_")}`;
  },
  foot: () => {
    const r = S.resume;
    if (r.status === "reading" || local.reading) return {next: false, back: false};
    if (r.status !== "none" && !local.replace) return {nextLabel: r.manual ? "Use this profile" : "Use this resume"};
    if (local.mode === "manual") return {nextLabel: "Save my profile", skip: true, skipLabel: "Skip for now"};
    if (NOCL() && !local.mode) return {next: false, skip: true, skipLabel: "Skip for now"};
    if (local.mode === "paste" || local.mode === "gdoc") return {nextLabel: "Read my resume", skip: true, skipLabel: "Skip for now"};
    return {next: false, skip: true, skipLabel: "Skip for now"};
  },
  mount(){
    const on = (id, fn) => $(id) && $(id).addEventListener("click", fn);
    on("replace", async () => {
      local.replace = true;
      if (S.resume.manual) {  // change the hand-filled profile: start from what they entered
        try { const d = await api("GET", "/api/profile"); ManualProfile.load(d.active); } catch(e) {}
        local.mode = "manual";
      }
      render();
    });
    on("modePaste", () => { local = {...local, mode: "paste"}; render(); });
    on("modeGdoc", () => { local = {...local, mode: "gdoc"}; render(); });
    on("modeFile", () => { local = {...local, mode: ""}; render(); });
    on("modeManual", () => { local = {...local, mode: "manual"}; render(); });
    if ($("mpRoot")) ManualProfile.mount($("mpRoot"), {name: S.name});
    if ($("ccRoot")) mountConnect($("ccRoot"));
    if ($("pick")) $("pick").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file").click(); } });
    if ($("file")) $("file").addEventListener("change", e => e.target.files[0] && this.sendFile(e.target.files[0]));
    const drop = $("drop");
    if (drop) {
      ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", e => e.dataTransfer.files[0] && this.sendFile(e.dataTransfer.files[0]));
    }
    if (S.resume.status === "reading" || local.reading) this.poll();
    if (S.resume.error && !local.reading) showErr("_", S.resume.error);
  },
  sendFile(f){
    if (f.size > 15 * 1024 * 1024) return showErr("file", "That file is larger than 15 MB.");
    const rd = new FileReader();
    rd.onload = () => this.send({filename: f.name, data_b64: String(rd.result).split(",")[1]});
    rd.readAsDataURL(f);
  },
  async send(body){
    try { await api("POST", "/api/resume", body); }
    catch(e) { return showErr(local.mode === "paste" ? "paste" : local.mode === "gdoc" ? "gdoc" : "file", e.message); }
    local.reading = true; S.resume = {...S.resume, status: "reading", error: null}; render();
  },
  async poll(){
    const me = ++this.pollId;
    while (cur === "resume" && this.pollId === me) {
      await sleep(MOCK ? 900 : 2500);
      if (cur !== "resume" || this.pollId !== me) return;
      try { S = await api("GET", "/api/setup"); } catch(e) { continue; }
      if (S.resume.status !== "reading") {
        if (S.resume.error) { local = {mode: local.mode}; render(); return; }
        return saveAndNext("resume", {}, "highlights");
      }
    }
  },
  pollId: 0,
  async next(){
    if (local.mode === "manual") {
      busy(true, "Saving your profile");
      try { await ManualProfile.submit(); }
      catch(e) { busy(false); footer(this.foot()); return showErr("_", e.message); }
      return saveAndNext("resume", {}, "highlights");
    }
    if (local.mode === "paste") {
      const t = $("paste").value.trim();
      if (t.length < 200) return showErr("paste", "That looks too short to be a full resume. Paste the whole thing.");
      return this.send({filename: "pasted-resume.txt", data_b64: btoa(unescape(encodeURIComponent(t)))});
    }
    if (local.mode === "gdoc") {
      const u = $("gdoc").value.trim();
      if (!/docs\.google\.com\/document\/d\//.test(u)) return showErr("gdoc", "That doesn’t look like a Google Docs link.");
      return this.send({gdoc_url: u});
    }
    saveAndNext("resume", {}, S.resume.status !== "none" ? "highlights" : "where");
  },
  skip(){ saveAndNext("resume", {skipped: true}, "where"); },
};

SCREENS.highlights = {
  title: "What we read",
  html: () => {
    const h = S.highlights || {cards: []};
    const card = (c, i) => {
      const wide = c.chips || (c.items && c.items.some(x => x.length > 48));
      let body = "";
      if (c.value) body += `<div class="hval">${esc(c.value)}</div>${c.detail ? `<div class="hdetail">${esc(c.detail)}</div>` : ""}`;
      if (c.items) body += `<ul>${c.items.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
      if (c.chips) body += `<div class="chips">${c.chips.map(x => `<span class="chip">${esc(x)}</span>`).join("")}${c.more ? `<span class="chip">+${c.more} more</span>` : ""}</div>`;
      return `<section class="hcard${wide ? " wide" : ""}" style="animation-delay:${i * 70}ms" aria-label="${esc(c.label)}">
        <div class="hhead"><i>${I[c.icon] || I.dot}</i>${esc(c.label)}</div>${body}</section>`;
    };
    return `
      <p class="eyebrow">Your resume</p>
      <h1 class="q" tabindex="-1">Here’s what we read${h.name ? `, ${esc(h.name.split(" ")[0])}` : ""}.</h1>
      <p class="lede">${h.cards.length ? "A quick look at what stood out. This is what we’ll match jobs against." : "We couldn’t pull much from that file. You can carry on and fix it later on My profile."}</p>
      <div class="hgrid">${h.cards.map(card).join("")}</div>
      <p class="fine">Something off? You can edit your profile any time on My profile (the person icon at the top of the board). ${errBox("_")}</p>`;
  },
  foot: () => ({nextLabel: "Looks right"}),
  collect: () => ({}),
  back(){ go("resume", -1); local.replace = false; return false; },
};

SCREENS.where = {
  title: "Where you’ll work",
  html: () => {
    const ri = Math.max(0, BOOT.radii.indexOf(V.radius_miles));
    const w = V.workplaces;
    return `
      <p class="eyebrow">Location</p>
      <h1 class="q" tabindex="-1">Where do you want to work?</h1>
      <p class="lede">We’ll keep on-site and hybrid jobs within your commute, and remote ones wherever you’re allowed.</p>
      <div class="choices cols3" role="group" aria-label="Ways of working" data-field="workplaces">
        ${radioCard("wp", "onsite", w.includes("onsite"), "On-site", "", {type: "checkbox", compact: true, icon: I.building})}
        ${radioCard("wp", "hybrid", w.includes("hybrid"), "Hybrid", "", {type: "checkbox", compact: true, icon: I.split})}
        ${radioCard("wp", "remote", w.includes("remote"), "Remote", "", {type: "checkbox", compact: true, icon: I.laptop})}
      </div>${errBox("workplaces")}
      <div id="commute">
        <div class="sect" style="margin-top:28px">Your commute</div>
        <label class="field"><span class="flabel">Home ZIP code</span>
          <input class="big" id="zip" data-field="home_zip" inputmode="numeric" pattern="[0-9]*" maxlength="5" autocomplete="postal-code" value="${esc(V.home_zip)}" placeholder="ZIP code" style="max-width:200px;font-family:var(--mono);letter-spacing:.06em" aria-describedby="err-home_zip">
          ${errBox("home_zip")}</label>
        <div class="field slider"><span class="flabel" id="radLbl">How far would you travel?</span>
          <div class="val" id="radVal" aria-hidden="true">${BOOT.radii[ri]}<span>miles</span></div>
          <input type="range" id="rad" min="0" max="${BOOT.radii.length - 1}" step="1" value="${ri}" aria-labelledby="radLbl" aria-valuetext="${BOOT.radii[ri]} miles">
          <div class="ticks" aria-hidden="true">${BOOT.radii.map(r => `<span>${r}</span>`).join("")}</div>
        </div>
      </div>
      <div class="switchrow" id="remoteRow" style="margin-top:8px">
        <div><b id="ruLbl">Remote jobs anywhere in the US</b><small>Include remote roles open nationwide, not just nearby.</small></div>
        <button type="button" class="switch" id="ru" role="switch" aria-checked="${V.remote_us ? "true" : "false"}" aria-labelledby="ruLbl"></button>
      </div>`;
  },
  mount(){
    const sync = () => {
      const w = checked("wp");
      const onlyRemote = w.length === 1 && w[0] === "remote";
      $("commute").style.opacity = onlyRemote ? .45 : 1;
      $("zip").disabled = onlyRemote; $("rad").disabled = onlyRemote;
      $("ru").disabled = !w.includes("remote");
      const i = +$("rad").value, r = BOOT.radii[i];
      $("radVal").innerHTML = `${r}<span>miles</span>`; $("rad").setAttribute("aria-valuetext", `${r} miles`);
      $("rad").style.setProperty("--p", (i / (BOOT.radii.length - 1) * 100) + "%");
    };
    document.querySelectorAll('input[name="wp"]').forEach(i => i.addEventListener("change", sync));
    $("rad").addEventListener("input", sync);
    $("zip").addEventListener("input", e => { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 5); });
    $("ru").addEventListener("click", e => { const b = e.currentTarget; b.setAttribute("aria-checked", b.getAttribute("aria-checked") === "true" ? "false" : "true"); });
    sync();
  },
  collect: () => ({home_zip: $("zip").value, radius_miles: BOOT.radii[+$("rad").value], workplaces: checked("wp"),
                   remote_us: $("ru").getAttribute("aria-checked") === "true"}),
};

SCREENS.pay = {
  title: "Pay",
  html: () => {
    const m = S.market;
    return `
      <p class="eyebrow">Pay</p>
      <h1 class="q" tabindex="-1">What are you looking to make?</h1>
      <p class="lede">Base salary per year, in thousands. Type 150 for $150,000.</p>
      ${m ? `<div class="hint">${I.info}<div>Similar roles list a median base of <b>${fmtK(m.median)}</b>, with most between <b>${fmtK(m.p25)}</b> and <b>${fmtK(m.p75)}</b>.<small>From ${esc(m.basis)}.</small></div></div>` : ""}
      <label class="field"><span class="flabel">Lowest base you’d accept</span>
        <span class="fhelp">Jobs that clearly pay less are hidden.</span>
        <span class="affix" data-field="salary_floor"><span>$</span><input id="floor" inputmode="numeric" value="${toK(V.salary_floor)}" placeholder="${m ? toK(m.p25) : "120"}" aria-describedby="err-salary_floor" data-autofocus><span>k</span></span>
        ${errBox("salary_floor")}</label>
      <label class="field"><span class="flabel">Target base<span class="opt">Optional</span></span>
        <span class="fhelp">What a great offer looks like.</span>
        <span class="affix" data-field="salary_target"><span>$</span><input id="target" inputmode="numeric" value="${toK(V.salary_target)}" placeholder="${m ? toK(m.p75) : "160"}" aria-describedby="err-salary_target"><span>k</span></span>
        ${errBox("salary_target")}</label>
      <label class="field"><span class="flabel">Current base<span class="opt">Optional</span></span>
        <span class="fhelp">Only used to show raises on your board. Never shared.</span>
        <span class="affix" data-field="current_base"><span>$</span><input id="curbase" inputmode="numeric" value="${toK(V.current_base)}" placeholder="—" aria-describedby="err-current_base"><span>k</span></span>
        ${errBox("current_base")}</label>
      ${errBox("_")}`;
  },
  mount(){ ["floor", "target", "curbase"].forEach(id => $(id).addEventListener("input", e => { e.target.value = e.target.value.replace(/[^\d.,]/g, ""); })); },
  collect: () => ({salary_floor: $("floor").value, salary_target: $("target").value, current_base: $("curbase").value}),
};

SCREENS.level = {
  title: "Your level",
  html: () => {
    const g = S.inferred.level, L = S.levels, m = V.seniority_mine;
    const band = V.band;
    const nm = n => L[String(n)] || "";
    return `
      <p class="eyebrow">Level</p>
      <h1 class="q" tabindex="-1">${g ? "Here’s our guess at your level." : "What level are you at?"}</h1>
      <p class="lede">We use it to skip jobs that are far too junior or too senior for you.</p>
      <div class="guess" aria-live="polite"><span class="lv" id="lvNum">${m}</span><div><b id="lvName">${esc(nm(m))}</b>
        <small>${g ? (g.level === m ? `Based on ${esc(g.why)}.` : `Your pick. Our guess was ${esc(g.name)}.`) : "Pick the level that fits you best."}</small></div></div>
      <details class="pick"${g ? "" : " open"}><summary>${g ? "Not quite? Choose your level" : "Choose your level"}</summary>
        <div class="levels" role="radiogroup" aria-label="Your level" data-field="seniority_mine">
          ${[2, 3, 4, 5, 6, 7].map(n => radioCard("lv", n, n === m, esc(nm(n)), g && g.level === n ? "Our guess" : `Level ${n}`)).join("")}
        </div>${errBox("seniority_mine")}</details>
      <div class="sect" style="margin-top:28px">Show me jobs that are</div>
      <div class="choices cols3" role="group" aria-label="Which levels to show" data-field="band" id="band">${this_band(m, band)}</div>
      ${errBox("band")}`;
  },
  mount(){
    document.querySelectorAll('input[name="lv"]').forEach(i => i.addEventListener("change", () => {
      const m = +radio("lv"), band = checked("band").map(Number);
      $("lvNum").textContent = m; $("lvName").textContent = S.levels[String(m)];
      const g = S.inferred.level;
      $("lvName").nextElementSibling.textContent = g ? (g.level === m ? `Based on ${g.why}.` : `Your pick. Our guess was ${g.name}.`) : "";
      $("band").innerHTML = this_band(m, band.length ? band : [-1, 0, 1]);
    }));
  },
  collect: () => ({seniority_mine: +radio("lv") || V.seniority_mine, band: checked("band").map(Number)}),
};
function this_band(m, band){
  const L = S.levels, nm = n => L[String(n)] || "";
  return [[-1, "A little below", m - 1], [0, "At my level", m], [1, "A little above", m + 1]].map(([o, t, n]) => {
    const ok = n >= 2 && n <= 7;
    return radioCard("band", o, ok && band.includes(o), t, ok ? esc(nm(n)) : "Not available", {type: "checkbox", compact: true, disabled: !ok});
  }).join("");
}

SCREENS.direction = {
  title: "Direction",
  html: () => {
    const d = V.direction || (V.target_text ? "specific" : "");
    return `
      <p class="eyebrow">Direction</p>
      <h1 class="q" tabindex="-1">Where do you want to go next?</h1>
      <p class="lede">Your board always shows jobs that fit you today. A direction adds a second tab for where you’d like to head.</p>
      <div class="choices" role="radiogroup" aria-label="Direction" data-field="direction">
        ${radioCard("dir", "keep", d === "keep", "Keep doing what I do", "More of the same work, ideally with better pay or conditions.", {icon: I.arrow})}
        ${radioCard("dir", "specific", d === "specific", "Aim at something specific", "A role, industry or kind of company you have in mind.", {icon: I.target})}
        ${radioCard("dir", "unsure", d === "unsure", "I’m not sure yet", NOCL() ? NEED_CL : "We’ll suggest a few directions based on your resume and what’s hiring.", {icon: I.compass, disabled: NOCL()})}
      </div>${errBox("direction")}
      ${NOCL() ? `<p class="fine">Without Claude, a direction you type is saved and starts working once you connect it.</p>
        <div class="alt" id="dirConnectRow"><button type="button" class="linkbtn" id="dirConnect">Connect Claude now</button></div><div id="ccRoot"></div>` : ""}
      <div id="dirMore" style="margin-top:20px"></div>`;
  },
  mount(){
    document.querySelectorAll('input[name="dir"]').forEach(i => i.addEventListener("change", () => this.more()));
    if ($("dirConnect")) $("dirConnect").addEventListener("click", () => { $("dirConnectRow").hidden = true; mountConnect($("ccRoot")); });
    this.more();
  },
  more(){
    const d = radio("dir"), box = $("dirMore");
    if (d === "specific") {
      box.innerHTML = `<label class="field"><span class="flabel">In your own words, what are you aiming for?</span>
        <span class="fhelp">For example: “Product management in health tech” or “Any role at an AI company that pays the most.”</span>
        <textarea class="big" id="ttext" data-field="target_text" rows="3" maxlength="2000" aria-describedby="err-target_text">${esc(V.target_text)}</textarea>${errBox("target_text")}</label>
        ${radioCard("scope", "ai", V.target_scope === "ai", "Only AI companies", "Limit this direction to AI labs and AI-first companies.", {type: "checkbox"})}`;
      $("ttext").addEventListener("input", e => { V.target_text = e.target.value; });
      box.querySelector('input[name="scope"]').addEventListener("change", e => { V.target_scope = e.target.checked ? "ai" : "all"; });
    } else if (d === "unsure") {
      this.suggest();
    } else box.innerHTML = "";
  },
  async suggest(){
    const box = $("dirMore");
    const show = () => {
      if (radio("dir") !== "unsure") return;
      const s = local.sugg;
      if (s.error) { box.innerHTML = `<div class="note">${esc(s.error)}</div>${errBox("target_text")}`; return; }
      if (s.running) { box.innerHTML = `<div class="working" role="status" style="padding:24px 8px"><div class="spinner" aria-hidden="true"></div><p>Looking at your resume and what’s hiring nearby… about a minute.</p></div>`; return; }
      const odds = {"strong": "good", "possible": "warn", "needs prep": "new"};
      box.innerHTML = `<div class="sect">Pick one to start with</div>
        <div class="choices" role="radiogroup" aria-label="Suggested directions" data-field="target_text">${(s.options || []).map((o, i) =>
          radioCard("sugg", i, V.target_text === o.target_text, `${esc(o.name)}<span class="pill ${odds[o.odds_now] || ""}">${esc(o.odds_now)}</span>`,
            `${esc(o.why)}<br><span style="font-variant-numeric:tabular-nums">${esc(o.pay)}</span>${o.prep && o.prep !== "none" ? ` · Prep: ${esc(o.prep)}` : ""}`)).join("")}</div>
        ${errBox("target_text")}
        <div class="alt" style="justify-content:flex-start"><button type="button" class="linkbtn" id="own">None of these. I’ll describe my own</button></div>`;
      box.querySelectorAll('input[name="sugg"]').forEach(inp => inp.addEventListener("change", () => { const o = s.options[+inp.value]; V.target_text = o.target_text; V.target_scope = o.scope; }));
      $("own").addEventListener("click", () => { document.querySelector('input[name="dir"][value="specific"]').checked = true; this.more(); $("ttext").focus(); });
    };
    if (local.sugg && !local.sugg.error) return show();
    local.sugg = {running: true}; show();
    try {
      let s = await api("GET", "/api/target/suggest");
      if (!s.options || !s.options.length) { await api("POST", "/api/target/suggest", {}); s = {running: true}; }
      while (s.running) { await sleep(MOCK ? 800 : 3000); s = await api("GET", "/api/target/suggest"); }
      local.sugg = s;
    } catch(e) { local.sugg = {error: e.message}; }
    if (local.sugg.error && /resume/i.test(local.sugg.error)) local.sugg.error = "Suggestions need your resume. Go back and add it, or describe your own direction.";
    if (cur === "direction") show();
  },
  collect(){
    const d = radio("dir");
    return {direction: d, target_text: d === "keep" ? "" : V.target_text, target_scope: V.target_scope};
  },
};

SCREENS.dealbreakers = {
  title: "Dealbreakers",
  html: () => {
    const emp = S.inferred.current_employer;
    const clr = [["none", "No clearance jobs", "Hide anything that asks for one."],
                 ["secret", "Up to Secret", "Hide Top Secret and above."],
                 ["nopoly", "Anything but a polygraph", "Hide TS/SCI with polygraph."],
                 ["all", "Any clearance", "Show everything."]];
    const tr = [["none", "None"], ["light", "Light", "under 10%"], ["moderate", "Some", "up to 25%"], ["any", "Any"]];
    return `
      <p class="eyebrow">Dealbreakers</p>
      <h1 class="q" tabindex="-1">Anything you’d rather not see?</h1>
      <p class="lede">We’ll keep these off your board. Change them anytime.</p>
      <div class="sect">Security clearance jobs</div>
      <div class="choices cols2" role="radiogroup" aria-label="Security clearance" data-field="clearance">${clr.map(([v, t, s]) => radioCard("clr", v, V.clearance === v, t, s)).join("")}</div>
      ${errBox("clearance")}
      <div class="sect" id="trLbl">Most travel you’d do</div>
      <div class="seg" role="radiogroup" aria-labelledby="trLbl" data-field="travel_max">${tr.map(([v, t, s]) => `<label><input type="radio" name="tr" value="${v}"${V.travel_max === v ? " checked" : ""}><span>${t}${s ? `<small>${s}</small>` : ""}</span></label>`).join("")}</div>
      ${errBox("travel_max")}
      <div class="sect">Employers to skip</div>
      ${tagInput("emps", V.skip_employers, "Add a company", "Employers to skip")}
      ${emp && V.skip_employers.includes(emp) ? `<p class="fine" style="margin-top:8px">We added ${esc(emp)}, your current employer, so your own company’s postings stay out of the way.</p>` : ""}
      ${errBox("skip_employers")}
      <div class="sect">Industries to skip</div>
      ${tagInput("inds", V.skip_industries, "Add an industry", "Industries to skip")}
      <div class="ideas" id="ideas" aria-label="Common choices">${S.industry_ideas.filter(x => !V.skip_industries.includes(x)).map(x => `<button type="button" class="idea" data-idea="${esc(x)}">+ ${esc(x)}</button>`).join("")}</div>
      ${errBox("skip_industries")}${errBox("_")}`;
  },
  mount(){
    this.e = mountTags("emps"); this.i = mountTags("inds");
    $("ideas").addEventListener("click", e => { const b = e.target.closest("[data-idea]"); if (!b) return; this.i.add(b.dataset.idea); b.remove(); });
  },
  collect(){ return {clearance: radio("clr"), travel_max: radio("tr"), skip_employers: this.e.values(), skip_industries: this.i.values()}; },
};

SCREENS.companies = {
  title: "Companies",
  html: () => {
    const sug = S.suggested_sets || [];
    return `
      <p class="eyebrow">Companies</p>
      <h1 class="q" tabindex="-1">Which companies should we watch?</h1>
      <p class="lede">We check these employers’ career pages directly, every day. ${sug.length ? "We’ve picked the lists that fit where you’re headed." : ""}</p>
      <div class="choices" role="group" aria-label="Company lists" data-field="company_sets">
        ${S.company_sets.map(c => {
          const [t, sub] = c.label.split(/ \((.*)\)$/);
          const extra = [sub ? sub.charAt(0).toUpperCase() + sub.slice(1) : "", c.count ? `${c.count} companies` : ""].filter(Boolean).join(" · ");
          return radioCard("sets", c.id, V.company_sets.includes(c.id), esc(t) + (sug.includes(c.id) ? '<span class="pill">Suggested</span>' : ""), esc(extra), {type: "checkbox"});
        }).join("")}
      </div>${errBox("company_sets")}
      <p class="fine">You can add any other company from the board later.</p>`;
  },
  collect: () => ({company_sets: checked("sets")}),
};

SCREENS.questions = {
  title: "A few questions",
  html: () => {
    const q = local.q;
    if (!q && NOCL()) return `
      <p class="eyebrow">Optional</p>
      <h1 class="q" tabindex="-1">Tailoring questions need Claude.</h1>
      <p class="lede">Siftwell can ask a few quick questions about skills and tools your resume doesn’t show, but that part needs Claude. Connect it here, or press Continue and answer them later from the board.</p>
      <div id="ccRoot"></div>`;
    if (!q) return `
      <p class="eyebrow">Optional</p>
      <h1 class="q" tabindex="-1">Got experience your resume doesn’t show?</h1>
      <p class="lede">We can ask a few quick questions about skills and tools that jobs like yours ask for. Your answers make matching and tailored resumes more accurate. Skip it if you’d rather do this later.</p>
      <div class="note">Usually 5 to 10 questions. Answer as briefly as you like. Nothing is added to your resume without your say.</div>${errBox("_")}`;
    if (q.running) return `<p class="eyebrow">Optional</p><h1 class="q" tabindex="-1">Thinking of good questions…</h1>
      <div class="working" role="status"><div class="spinner" aria-hidden="true"></div><p>Comparing your resume with what jobs like yours ask for. About a minute.</p></div>`;
    if (q.error || !(q.questions || []).length) return `<p class="eyebrow">Optional</p><h1 class="q" tabindex="-1">${q.error ? "We couldn’t come up with questions." : "Nothing to ask right now."}</h1>
      <p class="lede">${esc(q.error || "Your resume already covers what jobs like yours ask for.")} You can do this later from the board.</p>`;
    const it = q.questions[q.i], a = q.answers[q.i] || {};
    return `
      <div class="qcount">Question ${q.i + 1} of ${q.questions.length}</div>
      <h1 class="q qtext" tabindex="-1">${esc(it.question)}</h1>
      <p class="qwhy">${esc(it.why)}</p>
      <div class="seg" role="radiogroup" aria-label="Your answer" style="margin-bottom:16px">
        ${[["yes", "Yes"], ["some", "A little"], ["no", "No"]].map(([v, t]) => `<label><input type="radio" name="lvl" value="${v}"${a.level === v ? " checked" : ""}><span>${t}</span></label>`).join("")}
      </div>
      <label class="field"><span class="flabel">Details<span class="opt">Optional</span></span>
        <textarea class="big" id="ans" rows="3" placeholder="${esc(it.hint)}">${esc(a.answer || "")}</textarea></label>${errBox("_")}`;
  },
  foot(){
    const q = local.q;
    if (!q && NOCL()) return {nextLabel: "Continue"};
    if (!q) return {nextLabel: "Ask me", skip: true, skipLabel: "Skip"};
    if (q.running) return {next: false, skip: true, skipLabel: "Skip"};
    if (q.error || !(q.questions || []).length) return {nextLabel: "Continue"};
    const last = q.i === q.questions.length - 1;
    return {nextLabel: last ? "Save answers" : "Next question", skip: true, skipLabel: last ? "Skip and finish" : "Skip this one"};
  },
  mount(){ if ($("ccRoot")) mountConnect($("ccRoot")); },
  keep(){ const q = local.q; if (q && q.questions && $("ans")) q.answers[q.i] = {level: radio("lvl") || "", answer: $("ans").value.trim()}; },
  async start(){
    local.q = {running: true}; render();
    try {
      let s = await api("GET", "/api/questions/general");
      if (!s.questions) { await api("POST", "/api/questions", {}); s = {running: true}; }
      while (s.running) { await sleep(MOCK ? 800 : 3000); s = await api("GET", "/api/questions/general"); }
      local.q = s.error ? {error: s.error} : {questions: s.questions || [], i: 0, answers: []};
    } catch(e) { local.q = {error: e.message}; }
    if (local.q.error && /resume|profile/i.test(local.q.error)) local.q.error = "Questions need your resume first.";
    if (cur === "questions") render();
  },
  async next(){
    const q = local.q;
    if (!q && NOCL()) return saveAndNext("questions", {skipped: true});
    if (!q) return this.start();
    if (q.error || !(q.questions || []).length) return saveAndNext("questions", {});
    this.keep();
    if (q.i < q.questions.length - 1) { q.i++; dir = 1; return render(); }
    await this.save();
  },
  async save(){
    const q = local.q;
    const answers = q.questions.map((it, i) => ({requirement: it.requirement, question: it.question, ...(q.answers[i] || {})})).filter(a => a.level || a.answer);
    if (answers.length) {
      busy(true, "Saving answers");
      try { await api("POST", "/api/answers", {answers, context: "Setup"}); }
      catch(e) { busy(false); footer(this.foot()); return showErr("_", e.message); }
    }
    saveAndNext("questions", {answered: answers.length});
  },
  skip(){
    const q = local.q;
    if (q && q.questions && q.questions.length && !q.error) {
      q.answers[q.i] = {};
      if (q.i < q.questions.length - 1) { q.i++; dir = 1; return render(); }
      return this.save();
    }
    saveAndNext("questions", {skipped: true});
  },
  back(){
    const q = local.q;
    if (q && q.questions && q.i > 0) { this.keep(); q.i--; dir = -1; render(); return false; }
    if (q && !q.running) { local.q = null; dir = -1; render(); return false; }
  },
};

SCREENS.board = {
  title: "Setting up your board",
  html: () => `
    <p class="eyebrow">Almost there</p>
    <h1 class="q" tabindex="-1" id="bTitle">Setting up your board…</h1>
    <p class="lede" id="bLede">This takes about 15 minutes the first time. You can close this page; we’ll keep working and your board will be ready when you come back.</p>
    <div class="bar" role="progressbar" aria-label="Overall progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" id="bBar"><i></i></div>
    <ol class="checklist" id="bList" aria-live="polite"></ol>${errBox("_")}
    <p class="lede" style="margin-top:20px">While you wait: the Get started checklist (in <a href="/settings#get-started" style="color:var(--accent);font-weight:600">Settings</a>) checks Claude, PDFs, starting at login and phone access. Your board keeps getting ready if you go there.</p>`,
  foot: () => ({back: false, skip: false, nextLabel: "Go to my board"}),
  next(){ location.href = "/"; },
  async mount(){
    const items = [
      {id: "save", t: "Saving your answers"},
      {id: "target", t: "Working out which jobs fit your direction", only: () => !!(this.kick && this.kick.interpret_target)},
      {id: "fetch", t: "Gathering openings from the companies you picked"},
      {id: "score", t: "Reading the best matches against your resume", only: () => !NOCL()},
      {id: "build", t: "Building your board"},
    ];
    const st = {save: "run"}; let sub = {};
    const draw = () => {
      const shown = items.filter(i => !i.only || i.only());
      const done = shown.filter(i => st[i.id] === "done").length;
      let frac = done / shown.length;
      if (st.fetch === "run" && sub.total) frac += (sub.done / sub.total) / shown.length * .99;
      if (st.score === "run" && sub.total) frac += (sub.done / sub.total) / shown.length * .99;
      $("bBar").firstElementChild.style.width = Math.round(frac * 100) + "%"; $("bBar").setAttribute("aria-valuenow", Math.round(frac * 100));
      $("bList").innerHTML = shown.map(i => {
        const s = st[i.id] || "wait";
        const note = s === "run" && sub[i.id] ? `<small>${esc(sub[i.id])}</small>` : "";
        return `<li class="${s}"><span class="st" aria-hidden="true">${s === "done" ? I.check : ""}</span><div><b>${esc(i.t)}</b>${note}</div><span class="sr">${s === "done" ? "done" : s === "run" ? "in progress" : "waiting"}</span></li>`;
      }).join("");
    };
    draw();
    if (!this.finished) {
      try { const r = await api("POST", "/api/setup/finish", {}); this.kick = r.kick || {}; this.finished = true; }
      catch(e) { st.save = "wait"; draw(); return showErr("_", e.message); }
    }
    st.save = "done"; if (this.kick.interpret_target) st.target = "run"; draw();
    let sawRun = false;
    for (let n = 0; cur === "board"; n++) {
      await sleep(MOCK ? 700 : 3000);
      if (cur !== "board") return;
      try {
        if (st.target === "run") { const p = await api("GET", "/api/people"); if (!(p.target_job || {}).running) st.target = "done"; }
        const s = await api("GET", "/api/status");
        if (s.running && s.phase !== "facts") {  // (the facts step comes after the board is built: it keeps going in the background)
          sawRun = true;
          if (s.phase === "fetch") { st.fetch = "run"; sub = {done: s.done, total: s.total, fetch: s.total ? `${s.done} of ${s.total} companies checked` : "Starting…"}; }
          else { st.fetch = "done"; st.score = "run"; sub = {done: s.done, total: s.total, score: s.total ? `Batch ${s.done} of ${s.total}` : "Starting…"}; }
        } else if (sawRun || n > 3) {
          ["fetch", "score", "build", "target"].forEach(k => { st[k] = "done"; });
          draw();
          $("bTitle").textContent = "Your board is ready.";
          $("bLede").textContent = s.exit && s.exit !== 0 ? "Some companies couldn’t be reached this time; they’ll be tried again on the next update." : "Everything’s in place. Have a look.";
          say("Your board is ready.");
          return;
        }
      } catch(e) {}
      draw();
    }
  },
};

// ------------------------------------------------------------------ mock server (?mock=1 or file://)
const Mock = {
  key: "jb.setup.mock",
  fresh(){
    return {
      pid: "alex", name: "Alex", step: "welcome", done: false, steps: STEPS, optional: ["questions"], theme: "system",
      resume: {status: "none", error: null, file: ""},
      highlights: {name: "", summary: "", cards: []},
      inferred: {level: null, current_employer: ""},
      market: null,
      levels: BOOT.levels,
      company_sets: BOOT.sets.map((s, i) => ({...s, count: [214, 168, 131][i] || null})),
      suggested_sets: ["tech"], industry_ideas: BOOT.industries,
      values: {name: "", home_zip: "", radius_miles: 35, workplaces: ["onsite", "hybrid", "remote"], remote_us: true, current_base: null,
               salary_floor: 150000, salary_target: null, seniority_mine: 4, band: [-1, 0, 1], direction: "", target_text: "", target_scope: "all",
               clearance: "secret", travel_max: "any", skip_employers: [], skip_industries: [], company_sets: ["tech"], company_sets_saved: false},
      _t: {},
    };
  },
  load(){ try { const s = JSON.parse(sessionStorage.getItem(this.key)); if (s && s.steps) return s; } catch(e) {} return this.fresh(); },
  save(){ try { sessionStorage.setItem(this.key, JSON.stringify(this.s)); } catch(e) {} },
  readProfile(){
    const s = this.s;
    s.resume = {status: "draft", error: null, file: "20261109-101500_Alex Rivera Resume.pdf"};
    s.highlights = {name: "Alex Rivera", summary: "", cards: [
      {id: "years", label: "Experience", icon: "clock", value: "9 years", detail: "Senior Program Manager at Northwind Health"},
      {id: "education", label: "Education", icon: "cap", items: ["MBA, George Mason University", "BA in Economics, University of Maryland"]},
      {id: "certifications", label: "Certifications", icon: "badge", items: ["PMP", "Certified ScrumMaster"]},
      {id: "clearances", label: "Clearances", icon: "shield", items: ["Public Trust (current)"]},
      {id: "skills", label: "Skills", icon: "spark", chips: ["Program management", "Vendor management", "Budgeting", "Stakeholder engagement", "Process improvement", "Jira", "Smartsheet", "SQL", "Change management", "Risk management", "Agile delivery", "Data analysis", "Contract oversight", "Executive reporting"], more: 6},
    ]};
    s.inferred = {level: {level: 4, name: BOOT.levels["4"], why: "your most recent title, “Senior Program Manager” and about 9 years of experience"}, current_employer: "Northwind Health"};
    s.market = {median: 146000, p25: 128000, p75: 171000, n: 212, basis: "212 openings with pay listed, roles like yours near your level"};
    s.suggested_sets = ["ops", "nonprofit"];
    if (!s._saved_emp) s.values.skip_employers = ["Northwind Health"];
    if (!s.values.company_sets_saved) s.values.company_sets = ["ops", "nonprofit"];
  },
  err(msg, field){ const e = new Error(msg); e.field = field; throw e; },
  money(v, field, label, optional){
    if (v === "" || v == null) { if (optional) return null; this.err(`Enter ${label}.`, field); }
    let n = parseFloat(String(v).replace(/[$,k]/g, ""));
    if (isNaN(n)) this.err(`Use numbers only for ${label}.`, field);
    if (n > 0 && n < 2000) n *= 1000;
    if (n < 20000 || n > 2000000) this.err(`${label[0].toUpperCase() + label.slice(1)} should be between $20,000 and $2,000,000.`, field);
    return Math.round(n);
  },
  step(step, d){
    const s = this.s, v = s.values;
    if (step === "welcome") { const n = String(d.name || "").trim(); if (!n) this.err("Tell us what to call you.", "name"); v.name = s.name = n; }
    if (step === "where") {
      if (d.home_zip && !/^\d{5}$/.test(d.home_zip)) this.err("ZIP codes are five digits.", "home_zip");
      if (!d.workplaces.length) this.err("Pick at least one way of working.", "workplaces");
      if (!d.home_zip && !(d.workplaces.length === 1 && d.workplaces[0] === "remote")) this.err("Add your ZIP so we can measure commutes, or choose remote only.", "home_zip");
      Object.assign(v, d, {remote_us: d.remote_us && d.workplaces.includes("remote")});
    }
    if (step === "pay") {
      const c = this.money(d.current_base, "current_base", "your current base", true), f = this.money(d.salary_floor, "salary_floor", "the lowest base you’d take"), t = this.money(d.salary_target, "salary_target", "your target", true);
      if (t != null && t < f) this.err("Your target should be at or above your floor.", "salary_target");
      Object.assign(v, {current_base: c, salary_floor: f, salary_target: t});
    }
    if (step === "level") { if (!d.band.length) this.err("Pick at least one band of jobs to see.", "band"); Object.assign(v, d); }
    if (step === "direction") {
      if (!d.direction) this.err("Choose one of the options.", "direction");
      if (d.direction !== "keep" && !String(d.target_text || "").trim()) this.err(d.direction === "specific" ? "Describe what you’re aiming for." : "Pick one of the suggestions, or describe your own.", "target_text");
      Object.assign(v, d);
      if (!v.company_sets_saved) { const t = (d.target_text || "").toLowerCase(); s.suggested_sets = d.direction === "keep" ? ["ops", "nonprofit"] : /\b(ai|tech|software|data)\b/.test(t) ? ["tech"] : /nonprofit|mission|health/.test(t) ? ["nonprofit", "ops"] : ["ops"]; v.company_sets = s.suggested_sets.slice(); }
    }
    if (step === "dealbreakers") { Object.assign(v, d); s._saved_emp = true; }
    if (step === "companies") { if (!d.company_sets.length) this.err("Pick at least one list of companies.", "company_sets"); v.company_sets = d.company_sets; v.company_sets_saved = true; }
    if (step === "highlights" && s.resume.status === "draft") s.resume.status = "active";
    const i = STEPS.indexOf(step) + 1;
    if (i > STEPS.indexOf(s.step)) s.step = STEPS[i];
  },
  async handle(method, path, body){
    this.s = this.s || this.load();
    const s = this.s, t = s._t, now = Date.now();
    await sleep(method === "POST" ? 350 : 120);
    let out;
    if (path === "/api/setup") {
      if (s.resume.status === "reading" && now - t.resume > 3500) this.readProfile();
      out = clone(s);
    } else if (path === "/api/setup/step") { this.step(body.step, body.data || {}); out = {ok: true, state: clone(s)}; }
    else if (path === "/api/resume") { s.resume = {...s.resume, status: "reading", error: null}; t.resume = now; out = {ok: true}; }
    else if (path === "/api/target/suggest") {
      if (method === "POST") { t.sugg = now; out = {ok: true}; }
      else if (!t.sugg) out = {running: false, missing: true};
      else if (now - t.sugg < 2500) out = {running: true};
      else out = {running: false, options: [
        {name: "Operations leadership", target_text: "Director-level operations or program leadership at a mission-driven organization.", scope: "all", why: "Nine years running programs and vendors maps straight onto operations director roles.", pay: "$150k–$190k", odds_now: "strong", prep: "none"},
        {name: "Health tech product", target_text: "Product management at a health technology company.", scope: "all", why: "Your health-sector program work is the domain knowledge product teams hire for.", pay: "$155k–$205k", odds_now: "possible", prep: "A short product course and one shipped side project."},
        {name: "AI program management", target_text: "Technical program management at an AI company.", scope: "ai", why: "AI companies are hiring program managers who can run cross-team delivery.", pay: "$170k–$240k", odds_now: "needs prep", prep: "Get hands-on with LLM tools; 2–3 months."},
      ]};
    } else if (path === "/api/questions") { t.q = now; out = {key: "general"}; }
    else if (path === "/api/questions/general") {
      if (!t.q) out = {running: false, missing: true};
      else if (now - t.q < 2500) out = {running: true};
      else out = {running: false, questions: [
        {requirement: "Budget ownership", question: "Have you owned or managed a budget? If so, roughly how large, and what were you responsible for?", why: "Many senior program roles ask for budget accountability.", hint: "e.g. “Managed a $2M vendor budget for two years, approved spend and reported monthly.”"},
        {requirement: "Salesforce or CRM", question: "Have you used Salesforce or another CRM? Where, and what did you do with it?", why: "Operations roles often expect CRM reporting or administration.", hint: "e.g. “Built dashboards in Salesforce for a 40-person team.”"},
        {requirement: "Hiring and managing people", question: "Have you hired or directly managed people? How many, and for how long?", why: "Director-level postings usually require people management.", hint: "e.g. “Managed 4 analysts for 3 years; hired 2.”"},
      ]};
    } else if (path === "/api/answers") out = {added: (body.answers || []).length};
    else if (path === "/api/setup/finish") { s.done = true; s.step = "board"; t.fin = now; out = {ok: true, kick: {interpret_target: !!s.values.target_text, update: true}}; }
    else if (path === "/api/people") out = {target_job: {running: now - t.fin < 3000}};
    else if (path === "/api/status") {
      const e = (now - t.fin) / 1000;
      out = e < 9 ? {running: true, phase: "fetch", done: Math.round(e / 9 * 186), total: 186} : e < 15 ? {running: true, phase: "ai", done: Math.round((e - 9) / 6 * 8), total: 8} : {running: false, exit: 0};
    } else out = {};
    this.save();
    return out;
  },
};

// ------------------------------------------------------------------ boot
function applyTheme(t){ if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
async function boot(){
  if (MOCK) {
    $("mockbar").hidden = false; $("later").href = "#";
    $("mockReset").addEventListener("click", () => { try { sessionStorage.removeItem(Mock.key); } catch(e) {} Mock.s = null; SCREENS.board.finished = false; start(); });
    const order = ["system", "light", "dark"]; let ti = 0;
    $("mockTheme").addEventListener("click", () => { ti = (ti + 1) % 3; applyTheme(order[ti]); $("mockTheme").textContent = "Theme: " + order[ti]; });
  }
  start();
}
async function start(){
  try { S = await api("GET", "/api/setup"); }
  catch(e) { $("stage").innerHTML = `<h1 class="q">We couldn’t load setup.</h1><p class="lede">${esc(e.message)}</p>`; footer({back: false, next: false}); return; }
  if (!MOCK) applyTheme(S.theme);
  const resume = S.step !== "welcome" && S.step !== "board";
  go(S.done && S.step !== "board" ? "welcome" : S.step);
  if (resume) toast(`Welcome back${S.name ? ", " + S.name : ""}. Picking up where you left off.`);
}
boot();
</script>
</body>
</html>
"""
