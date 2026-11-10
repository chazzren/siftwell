"""Render data/jobs.json into a self-contained HTML report."""
import json

CURRENT = {}  # current pay comes from each profile's settings (payload["current"])

MARK = '<svg class="mk" viewBox="16 12 80 92" aria-hidden="true"><g fill="currentColor"><circle cx="38" cy="20" r="4"/><circle cx="56" cy="20" r="4"/><circle cx="74" cy="20" r="4"/></g><polygon points="22,32 90,32 64,62 64,78 48,78 48,62" fill="none" stroke="currentColor" stroke-width="7" stroke-linejoin="round"/><circle cx="56" cy="94" r="6" fill="#FAC775"/></svg>'  # = assets/brand/siftwell-mark-mono.svg

HEAD = """<title>Siftwell</title>
<link rel="icon" type="image/svg+xml" href="/assets/brand/siftwell-mark.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/assets/brand/favicon-16.png">
<link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png">
<script>try{var t=localStorage.getItem("jb.theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}</script>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a sticky filter rail over a dense ranked list; companies live on a second tab. */
:root{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#152033; --muted:#5b6678; --line:#dde1e8;
  --accent:#23468f; --accent-soft:#e6ecf8; --new:#a35a00; --new-soft:#fbefdc;
  --good:#1d7a4f; --good-soft:#e2f3ea; --warn:#9a5b00; --warn-soft:#fbf0dc; --bad:#a63232; --bad-soft:#f8e4e4;
  --bar:#cfd6e2; --bar-fill:#23468f;
  --sans:"Public Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
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
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.45;margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.wrap{max-width:1180px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 24px;padding-bottom:14px;border-bottom:1px solid var(--line)}
h1{font-size:22px;font-weight:700;margin:0;letter-spacing:-.01em;text-wrap:balance}
.sub{color:var(--muted);font-size:13px;margin-top:2px}
.stats{display:flex;gap:20px;flex-wrap:wrap}
.stat b{display:block;font-family:var(--mono);font-size:18px;font-weight:500;font-variant-numeric:tabular-nums}
.stat span{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
nav.tabs{display:flex;gap:4px;margin:14px 0 0}
nav.tabs a{padding:7px 12px;border-radius:6px;color:var(--muted);text-decoration:none;font-weight:600}
nav.tabs a[aria-current="page"]{background:var(--accent-soft);color:var(--accent)}
.filters{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line)}
.filters input[type=search]{flex:1 1 220px;min-width:0}
input,select,button{font:inherit;color:var(--ink)}
input[type=search],select{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:6px 9px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:transparent;padding:6px 10px;cursor:pointer;color:var(--muted)}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--surface)}
label.chk{display:inline-flex;gap:6px;align-items:center;color:var(--muted);font-size:13px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.count{color:var(--muted);font-size:13px;margin:10px 0}
ol.jobs{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.job{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;display:grid;grid-template-columns:58px minmax(0,1fr) 230px;gap:4px 16px;align-items:start}
.job.hidden-by-user{opacity:.45}
.scores{grid-row:span 2;display:flex;flex-direction:column;gap:6px}
.score.match{background:var(--bg);color:var(--ink);border:1px solid var(--line)}
.score.match.hi{background:var(--good-soft);color:var(--good);border-color:transparent}
.score.match.mid{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.score.match.lo{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.nocl{color:var(--muted);font-size:12.5px}.nocl a,.acts .nocl a{color:var(--accent);font-weight:600;border:0!important;background:none!important;padding:0!important;min-height:0!important;display:inline!important}
.rsc .m.na{color:var(--muted);font-weight:400}
.rrno{font-size:13.5px}.rrno p{margin:0 0 8px}
.score{font-family:var(--mono);font-size:20px;font-weight:500;text-align:center;border-radius:6px;padding:6px 0;background:var(--accent-soft);color:var(--accent);font-variant-numeric:tabular-nums;cursor:help}
.score small{display:block;font-size:10px;letter-spacing:.05em;color:var(--muted)}
.title{font-weight:600;font-size:15px;color:var(--ink);text-decoration:none}
.title:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:2px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.chip{font-size:11.5px;padding:2px 7px;border-radius:999px;background:var(--bg);border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.chip.remote{background:var(--good-soft);color:var(--good);border-color:transparent}
.chip.hybrid{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.chip.onsite{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.chip.poly{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.trv-heavy{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.trv-moderate,.chip.trv-some{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.chip.new{background:var(--new-soft);color:var(--new);border-color:transparent;font-weight:600}
.pay{grid-row:span 2;font-size:12px;color:var(--muted)}
.pay .amt{font-family:var(--mono);font-size:14px;color:var(--ink);font-variant-numeric:tabular-nums}
.bar{position:relative;height:8px;background:var(--bar);border-radius:4px;margin:6px 0 3px}
.bar i{position:absolute;top:0;bottom:0;background:var(--bar-fill);border-radius:4px}
.bar .mk{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink)}
.bar .mk.cur{background:var(--muted)}
.bar .mid{position:absolute;top:1px;width:6px;height:6px;margin-left:-3px;border-radius:50%;background:var(--bg);border:1.5px solid var(--ink)}
.bar.wide i{background:repeating-linear-gradient(135deg,var(--bar-fill) 0 4px,transparent 4px 7px)}
.pay .note{color:var(--warn)}
.axis{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;color:var(--muted)}
.acts{display:flex;gap:6px;margin-top:8px}
.acts button{border:1px solid var(--line);background:var(--surface);border-radius:5px;padding:3px 8px;font-size:12px;cursor:pointer;color:var(--muted)}
.acts button[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.more2{grid-column:2 / 3;display:flex;flex-direction:column;gap:4px;min-width:0}
details.snip{font-size:12.5px;color:var(--muted)}
.coname{color:var(--ink);font-weight:600}
.meta .gd{font-weight:600;color:var(--ink)}
.meta .gd.hi{color:var(--good)}
.meta .gd.lo{color:var(--warn)}
details.copanel{font-size:12.5px;color:var(--muted)}
details.copanel summary{cursor:pointer;width:max-content}
details.copanel[open]{background:var(--bg);border:1px solid var(--line);border-radius:var(--r,8px);padding:8px 10px}
details.copanel p{margin:6px 0;color:var(--ink);max-width:70ch}
details.copanel dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:3px 12px;margin:6px 0}
details.copanel dt{color:var(--muted)}
details.copanel dd{margin:0;color:var(--ink);min-width:0;overflow-wrap:anywhere}
details.copanel a{color:var(--accent)}
.asof{color:var(--muted);font-size:11.5px}
.colinks{display:flex;gap:14px;flex-wrap:wrap;margin-top:4px}
details.snip summary{cursor:pointer;width:max-content}
details.snip p{margin:6px 0 0;max-width:70ch;white-space:pre-line}
.more{display:block;margin:14px auto;padding:8px 16px;border:1px solid var(--line);background:var(--surface);border-radius:6px;cursor:pointer}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:8px;margin-top:14px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
td.n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums}
td.err{color:var(--bad);white-space:normal;min-width:200px}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:var(--surface);border-radius:6px;padding:7px 12px;cursor:pointer;font-weight:600;color:var(--ink)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.btn:disabled{opacity:.6;cursor:default}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-top:12px;display:flex;flex-direction:column;gap:8px}
.panel .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.panel input[type=password]{flex:1 1 260px;min-width:0;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 9px}
.panel small,.panel .note{color:var(--muted);font-size:12.5px}
.prog{height:6px;background:var(--bar);border-radius:3px;overflow:hidden}
.prog i{display:block;height:100%;background:var(--bar-fill);width:0;transition:width .4s}
.loglines{font-family:var(--mono);font-size:11.5px;color:var(--muted);white-space:pre-wrap;max-height:9em;overflow:auto}
.why{font-size:13px;color:var(--ink);margin-top:6px;max-width:75ch}
.why b{font-weight:600;color:var(--accent)}
.banner{background:var(--warn-soft);color:var(--warn);border-radius:6px;padding:8px 12px;font-size:13px;margin-top:12px}
.clsteps{margin:8px 0 2px 20px;padding:0;color:var(--ink)}
.clsteps li{margin:6px 0}
.clrow{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:4px}
.clrow input{flex:1 1 220px;min-width:0;height:var(--h);border:1px solid var(--line);border-radius:var(--r);padding:0 10px;background:var(--surface);color:var(--ink);font:inherit}
.clmsg{display:block;margin-top:4px;color:var(--bad)}
.clok{color:var(--good)}
.drop{border:1.5px dashed var(--line);border-radius:8px;padding:16px;text-align:center;color:var(--muted);cursor:pointer}
.drop.over{border-color:var(--accent);background:var(--accent-soft);color:var(--accent)}
.panel textarea{width:100%;min-height:5.5em;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit;resize:vertical}
.panel .help{font-size:12.5px;color:var(--muted);margin:0 0 4px}
.chip.lbl-apply_now{background:var(--good-soft);color:var(--good);border-color:transparent;font-weight:600}
.chip.lbl-tailor{background:var(--accent-soft);color:var(--accent);border-color:transparent;font-weight:600}
.chip.lbl-stretch{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.chip.lbl-skip{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.lab{background:var(--ink);color:var(--surface);border-color:transparent;font-weight:600}
.chip.bridge{background:var(--good-soft);color:var(--good);border-color:transparent}
.chip.lbl-after_prep{background:var(--accent-soft);color:var(--accent);border-color:transparent;font-weight:600}
.chip.lbl-long_shot{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.chip.gap{border-style:dashed}
.pv{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px;margin-top:12px}
.pv .card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;min-width:0}
.pv h3{margin:0 0 4px;font-size:14px}
.pv .help{font-size:12.5px;color:var(--muted);margin:0 0 8px}
.pvcounts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.pvcounts button{text-align:left;border:1px solid var(--line);background:var(--bg);border-radius:6px;padding:8px 10px;cursor:pointer;color:var(--ink)}
.pvcounts b{display:block;font-family:var(--mono);font-size:20px;font-variant-numeric:tabular-nums}
.pvcounts span{font-size:12px;color:var(--muted)}
.gaprow{display:grid;grid-template-columns:minmax(0,11rem) minmax(0,1fr) 2.5rem;gap:8px;align-items:center;font-size:12.5px;padding:3px 0;border:0;background:none;width:100%;text-align:left;cursor:pointer;color:var(--ink)}
.gaprow[aria-pressed="true"]{font-weight:700}
.gaprow i{display:block;height:8px;border-radius:4px;background:var(--bar-fill)}
.gaprow em{font-style:normal;font-family:var(--mono);color:var(--muted);text-align:right}
.tl{font-size:12.5px;color:var(--muted);margin-top:3px;max-width:75ch}
.legend{color:var(--muted);font-size:12.5px;max-width:75ch;margin:14px 0 0}
dialog.sheet{border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink);padding:0;width:min(640px,calc(100vw - 24px));max-height:calc(100dvh - 24px)}
dialog.sheet::backdrop{background:rgba(0,0,0,.45)}
.sheet form{display:flex;flex-direction:column;max-height:calc(100dvh - 26px)}
.sheet .qhead{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line)}
.sheet .qbody{overflow:auto;padding:4px 14px 12px;display:flex;flex-direction:column}
.sheet .qfoot{display:flex;gap:8px;flex-wrap:wrap;padding:10px 14px;border-top:1px solid var(--line)}
.q{display:flex;flex-direction:column;gap:6px;padding:12px 0;border-bottom:1px solid var(--line)}
.q:last-child{border-bottom:0}
.q .qreq{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);font-weight:600}
.q .qtext{font-weight:600;font-size:14px}
.q .qwhy{font-size:12.5px;color:var(--muted)}
.q textarea{width:100%;min-height:4.2em;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit;color:var(--ink);resize:vertical}
.ans{display:flex;gap:6px}
.ans button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:4px 12px;font-size:13px;cursor:pointer}
.ans button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.qwait{padding:24px 0;color:var(--muted)}
.psgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:8px 12px;margin:8px 0}
.psgrid label{display:flex;flex-direction:column;gap:3px;font-size:12.5px;color:var(--muted)}
.psgrid label.chk{flex-direction:row;align-items:center}
.psgrid input[type=text],.psgrid input[type=number],.psgrid select,.psgrid textarea,#newPersonName{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit;color:var(--ink);min-width:0}
#newPersonName{flex:1 1 200px}
.countrow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.factlist{display:flex;flex-direction:column;gap:6px;font-size:13px}
.fact{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:start;padding:6px 0;border-top:1px solid var(--line)}
.linkbtn{border:0;background:none;color:var(--accent);font:inherit;font-size:12px;cursor:pointer;padding:0 2px}
.fact .pol{color:var(--ink);font-size:12.5px;margin-top:2px;padding-left:8px;border-left:2px solid var(--accent-soft)}
.fact .fl{color:var(--muted);font-size:12px}
.fact button{border:1px solid var(--line);background:var(--surface);color:var(--muted);border-radius:5px;padding:2px 8px;font-size:12px;cursor:pointer}
@media (max-width:760px){
  .job{grid-template-columns:52px minmax(0,1fr)}
  .scores{grid-row:auto}
  .pay{grid-column:1 / -1;grid-row:auto}
  .more2{grid-column:1 / -1}
}

/* ---- v2: one control system. Every control is --h tall, --r rounded; spacing on a 4/8/12/16 scale. */
:root{--h:36px;--h-sm:28px;--r:8px}
header.top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 16px;padding-bottom:12px;border-bottom:0}
.brand{min-width:0}
h1{font-size:20px}
.sub{font-size:12.5px}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn,input[type=search],select,.seg,#personSel{height:var(--h);border-radius:var(--r);font-size:14px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:0 14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-weight:600;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--muted)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.btn.ghost{background:transparent;border-color:transparent;color:var(--accent)}
.btn.ghost:hover{background:var(--accent-soft)}
.btn.sm{height:var(--h-sm);padding:0 10px;font-size:13px}
input[type=search],select,#personSel{background:var(--surface);border:1px solid var(--line);padding:0 10px;color:var(--ink)}
select{padding-right:28px}
#personSel{font-weight:600;max-width:12rem}
.seg{display:inline-flex;align-items:stretch;padding:2px;gap:2px;border:1px solid var(--line);background:var(--surface)}
.seg button{border:0;border-radius:6px;padding:0 10px;background:transparent;color:var(--muted);font-weight:500}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--surface)}
nav.tabs{gap:20px;margin:4px 0 0;border-bottom:1px solid var(--line)}
nav.tabs a{padding:10px 0;border-radius:0;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;flex:0 0 auto}
nav.tabs a[aria-current="page"]{background:none;color:var(--ink);border-bottom-color:var(--accent)}
.filters{display:block;padding:10px 0 8px;border-bottom:1px solid var(--line)}
.frow{display:flex;gap:8px;align-items:center}
.frow input[type=search]{flex:1 1 auto;min-width:0}
.frow select{flex:0 0 auto}
.rmbtn{color:var(--bad);background:transparent;border:1px solid var(--line)}
.rmbtn[data-armed="1"]{background:var(--bad-soft);border-color:var(--bad)}
.nlbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;padding:7px 10px;border-radius:var(--r);background:var(--accent-soft);color:var(--ink);font-size:13px}
.nlbar b{color:var(--accent);font-weight:600}
.nlbar .nlterms{color:var(--muted);font-size:12px;flex-basis:100%}
.nlbar.err{background:var(--bad-soft);color:var(--bad)}
.nlbar .spin{width:12px;height:12px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:nlspin .8s linear infinite}
@keyframes nlspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.nlbar .spin{animation:none}}
.badge{display:inline-grid;place-items:center;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:var(--accent);color:var(--surface);font-size:11px;font-weight:700}
.fpanel{margin-top:10px;padding:12px;border:1px solid var(--line);border-radius:var(--r);background:var(--surface);display:flex;flex-direction:column;gap:12px}
.btn.icon{width:var(--h);padding:0}
.field input[type=number]{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;width:100%}
.fgroup{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink);border-top:1px solid var(--line);padding-top:10px}
.fgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,200px),1fr));gap:12px}
.fgroup.first{border-top:0;padding-top:0}
.fhint{margin:-6px 0 0;font-size:13px;color:var(--muted)}
.fhint:empty{display:none}
.fhint.err{color:var(--bad)}
.field input[type=text]{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;width:100%;min-width:0}
.filters:has(.fpanel:not([hidden])){position:static}
.field{display:flex;flex-direction:column;gap:4px;min-width:0}
.field select{width:100%}
.flabel{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.checks{display:flex;flex-wrap:wrap;gap:4px 12px;min-height:var(--h);align-items:center}
.fchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.fchips:empty{display:none}
.fchip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 6px 0 10px;border-radius:13px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:12.5px;cursor:pointer}
.fchip span{color:var(--muted);font-size:15px;line-height:1}
.fchip:hover{border-color:var(--muted)}
.countrow{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin:8px 0}
.count{margin:0}
.pvbar{display:flex;flex-direction:column;gap:8px;margin-top:10px}
.pvbar .pvcounts{display:flex;flex-wrap:wrap;gap:6px}
.pvbar .pvcounts button{height:var(--h-sm);display:inline-flex;align-items:center;gap:6px;padding:0 12px;border-radius:14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:13px;cursor:pointer;text-align:left}
.pvbar .pvcounts button b{font-family:var(--mono);font-size:13px;display:inline}
.pvbar .pvcounts button[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.pvgaps summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:13px;width:max-content}
.pvgaps[open]{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:10px 12px}
.panel{border-radius:var(--r);gap:10px}
.panel h2.sec{font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:6px 0 0}
.acts{flex-wrap:wrap}
.acts a{display:inline-flex;align-items:center;height:var(--h-sm);padding:0 8px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--muted);font-size:12px;text-decoration:none;white-space:nowrap}
.acts button.danger{margin-left:auto;color:var(--bad);border-color:transparent;background:transparent}
.acts button.danger[data-armed="1"]{background:var(--bad-soft);border-color:var(--bad)}
.acts a.pri,.acts button.pri{background:var(--accent);border-color:var(--accent);color:var(--surface);font-weight:600}
.tl2{font-size:12.5px;color:var(--muted);margin-top:4px;max-width:75ch}
.job.tlcard{grid-template-columns:58px minmax(0,1fr)}
.tlwork{display:inline-flex;align-items:center;gap:6px;font-weight:600;color:var(--accent)}
.tlwork .spin{width:11px;height:11px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:nlspin .8s linear infinite}
.tlfail{color:var(--bad);font-size:12.5px;margin-top:4px;max-width:75ch;overflow-wrap:anywhere}
.tlcard.working .scores,.tlcard.failed .scores{display:grid;place-items:center}
.tlcard .tlicon{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent);font-weight:700}
.tlcard.failed .tlicon{background:var(--bad-soft);color:var(--bad)}
@media (prefers-reduced-motion:reduce){.tlwork .spin{animation:none}}
.acts button{height:var(--h-sm);border-radius:6px;white-space:nowrap}
@media (max-width:640px){
  .wrap{padding-block:12px 40px}
  header.top{gap:8px}
  .tools{width:100%}
  #personSel{flex:1 1 auto;max-width:none}
  .frow{flex-wrap:wrap}
  .frow input[type=search]{flex:1 1 100%}
  .frow select{flex:1 1 auto}
  .fgrid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .fgrid .field:first-child,.fgrid .field:last-child{grid-column:1/-1}
  .msgrid .field:first-child,.fview .field:first-child{grid-column:auto}
  .msgrid .field.wide{grid-column:1/-1}
  nav.tabs{gap:16px;overflow-x:auto;scrollbar-width:none}
  nav.tabs::-webkit-scrollbar{display:none}
}
/* ---- v3: list + detail. Slim two-line rows on the left; everything about the selected job on the right
   (a full-screen sheet on phones). One avatar menu replaces the profile picker, Profile, gear and Update buttons. */
.wrap{max-width:1360px}
header.top{align-items:center}
.brandline{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.brandline .mk{width:24px;height:24px;flex:none;align-self:center;color:var(--ink);margin-right:-4px}
.fresh{color:var(--muted);font-size:12.5px}
.avatarBtn{display:inline-flex;align-items:center;gap:8px;height:var(--h);border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:0 12px 0 4px;font-weight:600;cursor:pointer;color:var(--ink)}
.avatarBtn .av{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent);font-size:13px}
.menuWrap{position:relative}
.iconBtn{position:relative;width:var(--h);height:var(--h);display:inline-grid;place-items:center;border:1px solid var(--line);background:var(--surface);border-radius:50%;color:var(--ink);cursor:pointer;padding:0}
.iconBtn:hover{background:var(--bg)}
.iconBtn[aria-expanded="true"],.iconBtn[aria-current="page"]{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
a.iconBtn{text-decoration:none}
.iconBtn:disabled{opacity:.55;cursor:default}
.iconBtn svg{width:18px;height:18px}
#themeBtn .ti{display:none}
#themeBtn:not([data-mode]) .ti-system,#themeBtn[data-mode="system"] .ti-system,#themeBtn[data-mode="light"] .ti-light,#themeBtn[data-mode="dark"] .ti-dark{display:block}
.iconBtn.busy svg{animation:nlspin 1.4s linear infinite}
@media (prefers-reduced-motion:reduce){.iconBtn.busy svg{animation:none}}
.rrbadge{position:absolute;top:-4px;right:-6px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:var(--accent);color:var(--surface);font-size:10.5px;font-weight:700;display:grid;place-items:center}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:640px){.tools .menuWrap{margin-left:auto}}
.amenu{position:absolute;right:0;top:calc(var(--h) + 6px);width:270px;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.18);padding:6px;z-index:40}
.amenu .who{padding:8px 10px;color:var(--muted);font-size:12px}
.amenu button{display:flex;width:100%;align-items:center;justify-content:space-between;gap:10px;border:0;background:none;padding:9px 10px;border-radius:8px;text-align:left;cursor:pointer;color:var(--ink);font-size:14px;height:auto;font-weight:500}
.amenu button:hover{background:var(--bg)}
.amenu button[aria-current="true"]{font-weight:700}
.amenu button[aria-current="true"]::after{content:"✓";color:var(--accent)}
.amenu small{color:var(--muted);font-weight:400}
/* Re-rate panel: a popover under the ✨ icon; a bottom sheet on phones */
.rrpop{position:fixed;z-index:45;width:min(440px,calc(100vw - 16px));max-height:calc(100vh - 80px);overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.18);padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.rrpop .rrhead{display:flex;justify-content:space-between;align-items:center;gap:8px}
.rrpop .rrhead strong{font-size:15px}
.rrrow{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;border-top:1px solid var(--line);padding-top:10px}
.rrrow.rec{border:1px solid var(--accent);background:var(--accent-soft);border-radius:var(--r);padding:10px}
.rrtxt{display:flex;flex-direction:column;gap:4px;min-width:0;font-size:13px}
.rrtxt small,.rrfoot small{color:var(--muted);font-size:12.5px}
.rrtag{display:inline-block;margin-left:6px;font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.04em}
.rrtxt input[type=number]{width:72px;height:var(--h-sm);border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);padding:0 6px;font:inherit}
.rrtxt input[type=number][aria-invalid="true"]{border-color:var(--bad)}
.rrhint{color:var(--warn)!important}
.rrfoot{display:flex;flex-direction:column;gap:4px;border-top:1px solid var(--line);padding-top:10px}
.rrmsg{color:var(--accent)!important;font-weight:600}
.rrmsg.bad{color:var(--bad)!important}
@media (max-width:640px){.rrpop{left:0!important;right:0!important;top:auto!important;bottom:0;width:auto;max-height:85vh;border-radius:16px 16px 0 0;padding-bottom:max(14px,env(safe-area-inset-bottom,0px))}}
.banner.gsbn{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:var(--accent-soft);color:var(--ink)}
.banner.gsbn span{flex:1 1 220px}
.updbn .updnotes{flex:1 1 100%;white-space:pre-wrap;word-break:break-word;max-height:260px;overflow:auto;margin:4px 0 0;padding:8px 10px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);font-size:12.5px;line-height:1.45}
.updbn .updsteps,.updbn .updmsg{flex:1 1 100%;font-size:13px}
.updbn .updsteps ol{margin:4px 0 0 18px;padding:0}
.updbn .updmsg:empty{display:none}
nav.tabs a .n{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:4px;font-weight:500}
.quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.qc{height:30px;border:1px solid var(--line);background:var(--surface);border-radius:15px;padding:0 12px;font-size:13px;color:var(--muted);cursor:pointer;white-space:nowrap}
.qc[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.split{display:grid;grid-template-columns:minmax(0,440px) minmax(0,1fr);gap:16px;align-items:start}
.listcol{min-width:0}
ol.rows{gap:0;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.jrow{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:11px 14px;border-bottom:1px solid var(--line);cursor:pointer;position:relative}
.jrow:last-child{border-bottom:0}
.jrow:hover{background:var(--bg)}
.jrow[aria-selected="true"]{background:var(--accent-soft)}
.jrow[aria-selected="true"]::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)}
.jrow.hidden-by-user{opacity:.5}
.rtitle{font-weight:600;line-height:1.3;min-width:0}
.rco{color:var(--muted);font-size:13px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rmeta{grid-column:1/-1;display:flex;gap:6px 10px;flex-wrap:wrap;align-items:center;font-size:12.5px;color:var(--muted);margin-top:3px}
.rmeta .amt{font-family:var(--mono);color:var(--ink);font-size:12.5px}
.rsc{grid-row:1/3;grid-column:2;display:flex;gap:4px}
.rsc div{text-align:center;min-width:40px}
.rsc b{display:block;font:500 17px/1.15 var(--mono)}
.rsc b.m{color:var(--muted);font-size:15px}
.rsc b.m.hi{color:var(--good)}
.rsc small{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.vpill{font-size:11.5px;font-weight:600;padding:1px 8px;border-radius:999px;white-space:nowrap;background:var(--bg);color:var(--muted)}
.vpill.v-apply_now,.vpill.v-after_prep{background:var(--good-soft);color:var(--good)}
.vpill.v-tailor{background:var(--accent-soft);color:var(--accent)}
.vpill.v-stretch,.vpill.v-long_shot{background:var(--warn-soft);color:var(--warn)}
.vpill.v-skip{background:var(--bad-soft);color:var(--bad)}
.ndot{width:7px;height:7px;border-radius:50%;background:var(--new);display:inline-block;margin-right:6px;vertical-align:1px}
.racts{position:absolute;right:10px;bottom:8px;display:none;gap:4px}
.jrow:hover .racts{display:flex}
.racts button{width:30px;height:26px;border:1px solid var(--line);background:var(--surface);border-radius:6px;cursor:pointer;color:var(--muted);font-size:13px;padding:0}
.racts button[aria-pressed="true"]{color:var(--accent);border-color:var(--accent)}
.detail{position:sticky;top:calc(env(safe-area-inset-top,0px) + var(--fbar,0px) + 12px);max-height:calc(100dvh - env(safe-area-inset-top,0px) - var(--fbar,0px) - 24px);overflow-y:auto;overscroll-behavior:contain;background:var(--surface);border:1px solid var(--line);border-radius:12px;min-width:0}
.dpane{padding:20px 22px 28px;display:flex;flex-direction:column;gap:18px}
.dback{display:none;align-self:flex-start;border:0;background:none;color:var(--accent);font-weight:600;padding:0;cursor:pointer;font-size:15px}
.dtitle{font-size:22px;font-weight:700;line-height:1.2;margin:0;text-wrap:balance}
.dco{display:flex;flex-wrap:wrap;gap:4px 10px;color:var(--muted);font-size:13.5px;margin-top:6px;align-items:center}
.dco .coname{color:var(--ink)}
.dacts{display:flex;gap:8px;flex-wrap:wrap}
.dacts .btn[aria-pressed="true"]{border-color:var(--accent);color:var(--accent)}
.dsec{border-top:1px solid var(--line);padding-top:14px}
.dsec>h3{margin:0 0 10px;font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:700}
.dscores{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.dsc{display:flex;gap:12px;align-items:center}
.ring{--p:0;width:54px;height:54px;border-radius:50%;flex:none;display:grid;place-items:center;background:conic-gradient(var(--accent) calc(var(--p)*1%),var(--bar) 0)}
.ring b{width:42px;height:42px;border-radius:50%;background:var(--surface);display:grid;place-items:center;font:500 16px var(--mono)}
.dsc p{margin:0;font-size:12.5px;color:var(--muted)}
.dsc strong{display:block;color:var(--ink);font-size:14px}
.dread p{margin:0 0 10px;max-width:70ch}
.dread .lab{display:block;font-weight:600;color:var(--ink);margin-bottom:1px}
.dsec .pay{grid-row:auto;font-size:13px}
.dsec details.copanel summary{display:none}
.dsec details.copanel{background:none;border:0;padding:0}
.dsec .snipp{white-space:pre-line;color:var(--muted);font-size:13.5px;max-width:75ch;margin:0}
.dempty{padding:48px 24px;text-align:center;color:var(--muted)}
.dempty b{display:block;color:var(--ink);font-size:17px;margin-bottom:4px}
.reqbox{display:flex;flex-direction:column;gap:8px}
.reqbox .chip{white-space:normal}
.chip.req-unmet{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.req-flag{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.reqwhy{font-size:12.5px;color:var(--muted);max-width:75ch}
.rmeta .rq{color:var(--warn);font-weight:600}
.rmeta .old,.dco .old{color:var(--muted);border:1px dashed var(--line);border-radius:999px;padding:0 7px;font-size:11.5px}
.tierdot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-left:3px;vertical-align:1px;background:var(--muted)}
.tierdot.t-haiku{background:transparent;border:1px solid var(--muted)}
.tiertag{font-size:11.5px;color:var(--muted)}
.ratefresh{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--muted)}
.rmeta .rq.un{color:var(--bad)}
.hlcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:10px}
.hlcard{border:1px solid var(--line);border-radius:var(--r);padding:10px 12px;background:var(--bg);min-width:0}
.hlcard .k{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700;display:flex;justify-content:space-between;gap:6px}
.hlcard .k em{font-style:normal;color:var(--accent);text-transform:none;letter-spacing:0;font-weight:600}
.hlcard .v{margin-top:4px;font-size:13.5px}
.hlcard .v div+div{margin-top:3px}
.hlbanner{background:var(--accent-soft);color:var(--ink);border-radius:var(--r);padding:10px 12px;font-size:13px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between}
.hledit{display:flex;flex-direction:column;gap:8px}
.hlrow{display:grid;grid-template-columns:130px minmax(0,1fr) minmax(0,1fr) auto;gap:6px;align-items:center}
.hlrow.lic{grid-template-columns:minmax(0,1fr) 130px auto}
.hledit input,.hledit select{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 8px;font:inherit;min-width:0}
@media (max-width:640px){.hlrow,.hlrow.lic{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
details.howto{margin-top:16px;color:var(--muted);font-size:12.5px}
details.howto summary{cursor:pointer;color:var(--accent);font-weight:600;width:max-content}
details.howto .legend{margin-top:8px}
@media (max-width:900px){
  .split{grid-template-columns:minmax(0,1fr)}
  .detail{position:fixed;inset:0;top:0;max-height:none;border:0;border-radius:0;z-index:30;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
  .detail:not(.open){display:none}
  .dback{display:inline-flex}
  .racts{display:none!important}
  .dscores{grid-template-columns:minmax(0,1fr)}
  .fresh{display:none}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
"""

THEME_JS = r"""// ---- theme button: Auto -> Light -> Dark -> Auto; saves display.theme and applies it at once. Needs $, H, PREFS, applyTheme().
function themeMode(){ const t = PREFS["display.theme"]; return t === "light" || t === "dark" ? t : "system"; }
function themeSync(){
  const b = $("themeBtn"); if (!b) return;
  const m = themeMode(), name = {system: "Auto (follows your device)", light: "Light", dark: "Dark"}, nxt = {system: "light", light: "dark", dark: "system"}[m];
  b.dataset.mode = m;
  b.title = "Theme: " + name[m] + ". Click for " + name[nxt].split(" ")[0]; b.setAttribute("aria-label", b.title);
}
$("themeBtn").addEventListener("click", () => {
  const nxt = {system: "light", light: "dark", dark: "system"}[themeMode()];
  PREFS["display.theme"] = nxt; applyTheme(); if (typeof fillPrefs === "function") fillPrefs();
  fetch("/api/prefs", {method: "POST", headers: H, body: JSON.stringify({prefs: {"display.theme": nxt}})}).then(r => r.json())
    .then(d => { if (d.prefs) { PREFS = d.prefs; applyTheme(); if (typeof fillPrefs === "function") fillPrefs(); } }).catch(() => {});
});
"""

# Header icon row (Home, Update, Re-rate, Catalog, My profile, Theme, Settings, profile menu): shared by the board and settings_page.py.
TOOLS = """    <a class="iconBtn" id="homeBtn" href="/#jobs" title="Home" aria-label="Home"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/></svg></a>
    <button class="iconBtn" type="button" id="updateBtn" title="Update job listings now: checks every employer for new jobs (about 40 min)" aria-label="Update job listings now"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg><span class="vh" id="updSmall">every employer, ~40 min</span></button>
    <button class="iconBtn" type="button" id="rerateBtn" title="Re-rate: choose how Claude re-rates your jobs, no new listings" aria-label="Re-rate jobs"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg><span class="rrbadge" id="rrBadge" hidden></span><span class="vh" id="rrSmall">Claude only, no new listings</span></button>
    <a class="iconBtn" id="catalogBtn" href="/catalog" title="Catalog: every company and listing, run history, Find employers near me, sharing" aria-label="Catalog"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3"/></svg></a>
    <a class="iconBtn" id="resumeBtn" href="/profile" title="My profile: resume, about you, job search, target, companies" aria-label="My profile"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="11" r="2.2"/><path d="M5.5 17c.6-1.9 2-3 3.5-3s2.9 1.1 3.5 3"/><path d="M15 9.5h3.5M15 13h3.5"/></svg></a>
    <button class="iconBtn" type="button" id="themeBtn" title="Theme: Auto (follows your device). Click for Light" aria-label="Theme: Auto (follows your device). Click for Light"><svg class="ti ti-system" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/></svg><svg class="ti ti-light" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><svg class="ti ti-dark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>
    <a class="iconBtn" id="prefsBtn" href="/settings" title="Settings: setup checklist, resume PDFs, review, Claude usage, display" aria-label="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span class="rrbadge" id="gsBadge" hidden></span></a>
    <div class="menuWrap">
      <button class="avatarBtn" id="avatarBtn" aria-haspopup="menu" aria-expanded="false"><span class="av" id="avInit">·</span><span id="avName">Profile</span></button>
      <div class="amenu" id="amenu" role="menu" hidden>
        <div id="amPeople"></div>
      </div>
    </div>
"""

BODY = """<div class="wrap">
<header class="top">
  <div class="brandline">
    """ + MARK + """<h1>Siftwell</h1>
    <span class="fresh" id="sub"></span><span class="fresh" id="nextRun"></span>
  </div>
  <div class="tools" id="tools" hidden>
""" + TOOLS + """  </div>
  <div id="stats" hidden></div>
</header>
<div class="banner" id="aiBanner" hidden></div>
<div class="banner gsbn" id="gsBanner" hidden></div>
<div class="banner gsbn updbn" id="updBanner" hidden></div>
<div class="panel" id="progress" hidden>
  <div class="row"><strong id="progTitle">Updating…</strong><span class="note" id="progNote"></span><button class="btn sm" type="button" id="progStop" hidden title="Stop rating: batches already sent finish and their ratings are kept. Queued runs are cancelled.">Stop</button><button class="btn sm primary" type="button" id="progReload" hidden>Show new ratings</button></div>
  <div class="prog"><i id="progBar"></i></div>
  <div class="note" id="progQueue" hidden></div>
  <div class="loglines" id="progLog"></div>
</div>
<div class="rrpop" id="rrPanel" role="dialog" aria-labelledby="rrTitle" hidden>
  <div class="rrhead"><strong id="rrTitle">Re-rate jobs</strong><button class="btn ghost sm" type="button" id="rrClose">Close</button></div>
  <div class="rrno" id="rrNo" hidden><p><b>Re-rating needs Claude.</b> Claude reads each posting against your resume to give the Match rating. Without it, Siftwell still finds, filters and ranks jobs by Appeal.</p><a class="btn primary sm" href="/settings#get-started">Settings, then Get started</a></div>
  <div class="rrrow rec">
    <div class="rrtxt"><span><b>Full re-rate</b><span class="rrtag">recommended</span></span>
      <small>Quick check of jobs that need it, then Sonnet on your best <span class="rrPctTxt"></span>%, then Opus on your top <span class="rrTopTxt"></span>. Only ratings made with older info are redone.</small>
      <small id="rrEstFull"></small>
      <label class="chk rrTgt"><input type="checkbox" id="rrTgtFull" checked><span>Also rate for my Target tab <small>(extra Claude requests: up to <span class="rrTgtN"></span> more jobs)</small></span></label></div>
    <button class="btn primary sm" type="button" data-rr="full">Run</button>
  </div>
  <div class="rrrow">
    <div class="rrtxt"><b>Quick check · Haiku</b>
      <small id="rrHAll"></small>
      <label class="chk"><input type="checkbox" id="rrHNeed" checked><span>Only jobs that need it (<span id="rrHN">0</span>)</span></label>
      <label class="chk rrTgt"><input type="checkbox" id="rrTgtHaiku"><span>Also rate for my Target tab <small>(extra Claude requests: up to <span class="rrTgtN"></span> more jobs; off unless you tick it)</small></span></label></div>
    <button class="btn sm" type="button" data-rr="haiku">Run</button>
  </div>
  <div class="rrrow">
    <div class="rrtxt"><b>Careful look · Sonnet</b>
      <span>Top <input type="number" id="rrPct" min="1" max="100" step="1" aria-label="Percent of board jobs for Sonnet"> % of board jobs <span class="note" id="rrSN"></span></span>
      <label class="chk"><input type="checkbox" id="rrSNeed" checked><span>Only ones that need it (<span id="rrSNn">0</span>)</span></label>
      <label class="chk rrTgt"><input type="checkbox" id="rrTgtSonnet"><span>Also rate for my Target tab <small>(extra Claude requests: up to <span class="rrTgtN"></span> more jobs; off unless you tick it)</small></span></label>
      <small class="rrhint" hidden>Run the quick check first for better picks.</small></div>
    <button class="btn sm" type="button" data-rr="sonnet">Run</button>
  </div>
  <div class="rrrow">
    <div class="rrtxt"><b>Best judgment · Opus</b>
      <span>Top <input type="number" id="rrTop" min="1" max="2000" step="1" aria-label="Number of top jobs for Opus"> jobs <span class="note" id="rrON"></span></span>
      <label class="chk"><input type="checkbox" id="rrONeed" checked><span>Only ones that need it (<span id="rrONn">0</span>)</span></label>
      <label class="chk rrTgt"><input type="checkbox" id="rrTgtOpus"><span>Also rate for my Target tab <small>(extra Claude requests: up to <span class="rrTgtN"></span> more jobs; off unless you tick it)</small></span></label>
      <small class="rrhint" hidden>Run the quick check first for better picks.</small></div>
    <button class="btn sm" type="button" data-rr="opus">Run</button>
  </div>
  <div class="rrfoot">
    <small id="rrEst"></small>
    <small>"Top" follows your Best bets order. These numbers apply to this run only; your defaults stay in Settings. Target-tab ratings are a separate cost: the Full re-rate includes them, single-model runs only if you tick the box.</small>
    <small class="rrmsg" id="rrMsg" role="status"></small>
  </div>
</div>
<dialog class="sheet" id="qSheet" aria-labelledby="qTitle">
  <form method="dialog" id="qForm">
    <div class="qhead"><strong id="qTitle">A few questions first</strong><button class="btn" value="cancel" type="submit" id="qClose">Close</button></div>
    <div class="qbody">
      <p class="help" id="qIntro" style="margin-top:10px">Your resume doesn't show these. Answer what's true and skip the rest. Answers are saved and reused for other jobs, and nothing is claimed more strongly than you put it.</p>
      <div id="qList"></div>
    </div>
    <div class="qfoot" id="qFoot"><button class="btn primary" type="button" id="qGo">Save answers and tailor</button><button class="btn" type="button" id="qSkip">Skip, tailor now</button></div>
  </form>
</dialog>
<div class="panel" id="addPersonPanel" hidden>
  <strong>Add a person</strong>
  <p class="help">Each person gets their own resume, answers, saved jobs, tailored resumes and settings. Next comes a short setup: resume, where, pay, level and what you're aiming for.</p>
  <form class="row" id="addPersonForm"><input type="text" id="newPersonName" placeholder="Name" aria-label="Name" autocomplete="off"><button class="btn primary" type="submit">Continue to setup</button><button class="btn" type="button" id="addPersonCancel">Cancel</button></form>
  <div class="note" id="addPersonMsg"></div>
</div>

<nav class="tabs"><a href="#jobs" id="tab-jobs">Jobs</a><a href="#pivot" id="tab-pivot">Target</a><a href="#saved" id="tab-saved">Saved</a><a href="#applied" id="tab-applied">Applied</a><a href="#tailored" id="tab-tailored">Resumes</a><a href="#companies" id="tab-companies">Companies</a></nav>

<section id="view-jobs">
  <div class="filters">
    <div class="frow">
      <input type="search" id="q" enterkeyhint="search" placeholder="Describe a job, industry, company or role, then press Enter" aria-label="Describe what you're looking for">
      <select id="sort" aria-label="Sort">
        <option value="rel" id="sortRel" hidden>Best match to search</option><option value="score">Best bets (Appeal × Match)</option><option value="appeal">Highest Appeal</option><option value="odds">Highest Match</option><option value="odds_later" id="sortLater">Match as written</option><option value="pay">Highest pay</option><option value="gd">Best Glassdoor (review-weighted)</option><option value="new">Newest</option>
      </select>
      <button class="btn" type="button" id="filtersBtn" aria-expanded="false" aria-controls="fPanel">Filters<span class="badge" id="fCount" hidden></span></button>
    </div>
    <div class="nlbar" id="nlBar" role="status" aria-live="polite" hidden></div>
    <div class="quick" id="quick"></div>
    <div class="fpanel" id="fPanel" hidden>
      <div id="msWrap" hidden>
      <div class="fgroup first">My search</div>
      <p class="fhint">These decide which jobs reach your board. They are saved with your profile.</p>
      <div class="fgrid msgrid" id="msGrid">
        <label class="field"><span class="flabel">Home ZIP or City, ST</span><input type="text" id="msZip" data-ms="home_zip" placeholder="e.g. 20170" autocomplete="postal-code"></label>
        <label class="field"><span class="flabel">Search radius</span><select id="msRadius" data-ms="radius_miles">
          <option value="10">10 miles</option><option value="25">25 miles</option><option value="35">35 miles</option><option value="50">50 miles</option><option value="75">75 miles</option></select></label>
        <div class="field wide"><span class="flabel" id="msWpLbl">Ways of working</span>
          <div class="checks" role="group" aria-labelledby="msWpLbl"><label class="chk"><input type="checkbox" data-mswp="onsite"> On-site</label>
          <label class="chk"><input type="checkbox" data-mswp="hybrid"> Hybrid</label>
          <label class="chk"><input type="checkbox" data-mswp="remote"> Remote</label></div></div>
        <div class="field wide"><span class="flabel">Nationwide</span>
          <div class="checks"><label class="chk"><input type="checkbox" id="msRemoteUs" data-ms="remote_us"> Remote jobs anywhere in the US</label></div></div>
        <label class="field"><span class="flabel">Travel limit</span><select id="msTravel" data-ms="travel_max">
          <option value="none">None</option><option value="light">Light (under 10%)</option><option value="moderate">Some (up to 25%)</option><option value="any">Any</option></select></label>
        <label class="field"><span class="flabel">Lowest base ($)</span><input type="number" inputmode="numeric" step="5000" min="30000" id="msFloor" data-ms="salary_floor"></label>
        <label class="field wide"><span class="flabel">Your level</span><select id="msLevel" data-ms="seniority_mine">
          <option value="2">Mid-level</option><option value="3">Senior</option><option value="4">Lead / Manager</option><option value="5">Principal / Sr. Manager</option><option value="6">Director</option><option value="7">VP / Executive</option></select></label>
      </div>
      <p class="fhint" id="msState" role="status" aria-live="polite"></p>
      <div class="fgroup">Narrow the list</div>
      </div>
      <div class="fgrid fview">
        <label class="field"><span class="flabel">Fit</span><select id="lbl"></select></label>
        <label class="field"><span class="flabel">Clearance</span><select id="clr">
          <option value="all">Any clearance</option><option value="none">No clearance mentioned</option>
          <option value="nopoly">No TS/SCI + poly</option><option value="secret" selected>Secret or less</option></select></label>
        <label class="field"><span class="flabel">Company</span><select id="co"><option value="all">All companies</option></select></label>
        <label class="field"><span class="flabel">Show</span><select id="st">
          <option value="active">Not hidden</option><option value="saved">Saved</option><option value="applied">Applied</option><option value="hidden">Hidden</option><option value="all">Everything</option></select></label>
        <div class="field"><span class="flabel">Only</span>
          <div class="checks"><label class="chk"><input type="checkbox" id="paidonly"> Salary listed</label>
          <label class="chk"><input type="checkbox" id="nowide"> No wide bands</label>
          <label class="chk"><input type="checkbox" id="newonly"> New</label>
          <label class="chk"><input type="checkbox" id="reqall"> Jobs I don't meet requirements for</label></div></div>
      </div>
      <div class="fgroup">Company</div>
      <div class="fgrid">
        <label class="field" id="cListField"><span class="flabel">List</span><select id="cList">
          <option value="all">All my lists</option></select></label>
        <label class="field"><span class="flabel">Type</span><select id="cType">
          <option value="all">Any type</option><option value="public">Public</option><option value="private">Private</option>
          <option value="lab">Frontier AI lab</option><option value="ai">AI company</option><option value="np">Nonprofit / gov-sponsored</option></select></label>
        <label class="field"><span class="flabel">Size</span><select id="cSize">
          <option value="all">Any size</option><option value="s">Under 200 people</option><option value="m">200 – 1,000</option>
          <option value="l">1,000 – 10,000</option><option value="xl">10,000+</option><option value="nsxl">Under 10,000</option></select></label>
        <label class="field"><span class="flabel">Value</span><select id="cVal">
          <option value="all">Any value</option><option value="v1">Under $1B</option><option value="v10">$1B – $10B</option>
          <option value="v100">$10B – $100B</option><option value="vbig">$100B+</option><option value="v10p">$10B+</option></select></label>
        <label class="field"><span class="flabel">Age</span><select id="cAge">
          <option value="all">Any age</option><option value="a5">Startup (under 5 yrs)</option><option value="a15">Growth (5 – 15 yrs)</option>
          <option value="aold">Established (15+ yrs)</option><option value="a15m">Under 15 yrs</option></select></label>
        <label class="field"><span class="flabel">Glassdoor</span><select id="cGd">
          <option value="all">Any rating</option><option value="g40">4.0+</option><option value="g35">3.5+</option>
          <option value="g35u">3.5+ or unrated</option><option value="g40r">4.0+ with 100+ reviews</option></select></label>
        <label class="field"><span class="flabel">Layoffs</span><select id="cLay">
          <option value="all">Any</option><option value="none">None reported (18 mo)</option><option value="noknown">Hide known layoffs</option></select></label>
        <label class="field"><span class="flabel">Equity</span><select id="cEq">
          <option value="all">Any equity</option><option value="liquid">Public stock (sellable RSUs)</option><option value="private">Private shares / options</option></select></label>
      </div>
      <div class="row"><button class="btn ghost sm" type="button" id="fReset">Reset to defaults</button><button class="btn sm" type="button" id="fDone">Done</button></div>
    </div>
    <div class="fchips" id="fChips"></div>
  </div>
  <div class="pvbar" id="pvPanel" hidden>
    <span id="pvTitle" hidden></span>
    <div class="pvcounts" id="pvCounts"></div>
    <details class="pvgaps"><summary>What to work on</summary><p class="help" id="pvHelp"></p><div id="pvGaps"></div></details>
  </div>
  <div class="countrow"><div class="count" id="count"></div><button class="btn ghost sm" type="button" id="rateMore" hidden></button><span class="note" id="rateMsg"></span></div>
  <div class="split">
    <div class="listcol"><ol class="jobs rows" id="list" role="listbox" aria-label="Jobs"></ol>
    <button class="more" id="more" hidden>Show 100 more</button></div>
    <aside class="detail" id="detail" aria-label="Job details"></aside>
  </div>
  <details class="howto"><summary>How the scores work</summary>
  <p class="legend" id="pvLegend" hidden>This tab shows jobs that fit your target, which you set under Resume, then Search settings. Claude rates each as a step toward it. "Now" is your shot today with an honest tailored resume. "After prep" assumes the preparation you described. Apply now = 65+ today; After prep = 65+ once prepared; Long shot = 40 to 64 even after prep. Pitch ideas only claim what's true today. Score = 50% odds (60% now, 40% after prep) + 30% pay + 20% quality of life.</p>
  <p class="legend" id="legend2"><b>Overall</b> = how worth pursuing a job is: 50% match + 30% pay + 20% quality of life. <b>Match</b> = how well your resume, honestly tailored, meets the job's requirements (Claude's 0 to 100 rating; 70+ is a genuine shot; it's a rating, not a probability).</p>
  <p class="legend" id="legend">Verdicts come from Claude comparing each job with your resume: Strong match (strong as written), Worth tailoring (strong after honest tailoring), Stretch, Not a fit. On the pay bar, the dark tick is your <span class="floorTxt"></span> floor, the grey tick is your current base, and the ring is the midpoint. Ranges whose top is 1.6× the bottom or more are flagged as wide bands. Save, Applied and Hide are kept per profile.</p>
  </details>
</section>

<section id="view-tailored" hidden>
  <div class="countrow"><div class="count" id="tlCount">Loading…</div></div>
  <ol class="jobs" id="tlList"></ol>
  <p class="legend">Every tailored resume you've made for this profile, newest first. Download PDF gives the finished resume; Review shows each bullet's source and the gaps Claude flagged.</p>
</section>
<section id="view-companies" hidden>
  <div class="tablewrap"><table>
    <thead><tr><th>Company</th><th>Sector</th><th>Presence</th><th>Source</th><th>Postings</th><th>Matches</th><th>Status</th></tr></thead>
    <tbody id="cos"></tbody>
  </table></div>
  <p class="legend">Postings = every job on the company's board. Matches = jobs left after the location (near you, or US remote), title, and <span class="floorTxt"></span> salary filters.</p>
</section>
</div>
"""

SCRIPT = r"""<script>
(function(){
const D = window.__DATA__, CUR = window.__CURRENT__;
const $ = id => document.getElementById(id);
const fmt = n => n == null ? "" : "$" + Math.round(n/1000) + "k";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const safeUrl = u => { const s = String(u ?? "").trim(); return /^https?:\/\/[^\s\/?#]/i.test(s) && !/[\s\x00-\x1f]/.test(s) ? s : ""; };  // links from postings: http(s) only
const SERVED = location.protocol.startsWith("http");
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
// Save / Applied / Hide belong to one profile. The server keeps them (DATA/people/<id>/marks.json); the browser copy is
// per profile too and only used when the board is opened as a file. Boards up to v0.3.1 kept one browser copy shared by
// every profile ("dmvjobs.status"), which is why saves showed up in every profile; it is handed over once (importLegacyMarks).
const PID = (D.person && D.person.id) || "";
const MKEY = "jb.marks." + (PID || "local"), LEGACY_MKEY = "dmvjobs.status";
let status = {};
try { status = JSON.parse(localStorage.getItem(MKEY) || (SERVED ? "{}" : localStorage.getItem(LEGACY_MKEY) || "{}")) || {}; } catch(e) {}
const cacheMarks = () => { try { localStorage.setItem(MKEY, JSON.stringify(status)); } catch(e) {} };
const saveStatus = (id) => {
  cacheMarks();
  if (SERVED && id) fetch("/api/marks", {method: "POST", headers: H, body: JSON.stringify({person: PID, id, status: status[id] || ""})}).catch(() => {});
};
const pq = () => PID ? "?person=" + encodeURIComponent(PID) : "";
const LBL = {apply_now: "Strong match", tailor: "Worth tailoring", stretch: "Stretch", skip: "Not a fit"};
const LBL_HELP = {apply_now: "Apply with your resume as it is.", tailor: "A good fit once your resume speaks to this role.", stretch: "Reachable, but there's a real gap.", skip: "Claude doesn't think this one is worth your time."};
const TIER = {dmv_hq:"HQ near you", dmv_office:"Office near you", remote_first:"Remote-first", remote_friendly:"Remote-friendly"};

const jobs = D.jobs;
// Claude is optional: when it isn't connected the board says so once (banner) and shows "-" where Match would be.
let NOAI = D.claude_ready === false;
const NOAI_MSG = "Connect Claude to get Match ratings and tailoring";
const NOAI_LINK = `<a href="/settings#get-started">Settings → Get started</a>`;
const hasMatch = jobs.some(j => j.ai_fit != null || j.pv_now != null);  // ratings made earlier still show and sort
const noClaude = what => `<span class="nocl">${what} needs Claude. ${NOAI_LINK}</span>`;
const nNew = jobs.filter(j => j.new).length;
const updatedAt = (() => { try { return new Date(D.generated).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}); } catch(e) { return D.generated.replace("T", " "); } })();
$("sub").textContent = "Updated " + updatedAt;
document.querySelectorAll(".floorTxt").forEach(e => e.textContent = fmt(D.salary_floor));
$("tab-pivot").textContent = D.target_name || "Target";
if (!D.pivot_enabled) { $("tab-pivot").hidden = true; if (location.hash === "#pivot") location.hash = "#jobs"; }
$("stats").innerHTML = [
  [jobs.length, "matches"], [jobs.filter(j=>j.workplace==="remote").length, "remote"],
  [jobs.filter(j=>j.salary_min!=null && j.salary_min>=D.salary_floor).length, "min ≥ " + fmt(D.salary_floor)],
  [nNew, "new this run"], [D.companies.length, "companies"]
].map(([n,l]) => `<div class="stat"><b>${n.toLocaleString()}</b><span>${l}</span></div>`).join("");

const LISTS = D.lists || {options: [], by_company: {}};
$("cList").insertAdjacentHTML("beforeend", LISTS.options.map(o => `<option value="${esc(o.id)}">${esc(o.label)}</option>`).join(""));
$("cListField").hidden = LISTS.options.length < 2;
const cos = [...new Set(jobs.map(j=>j.company))].sort();
$("co").insertAdjacentHTML("beforeend", cos.map(c => `<option>${esc(c)}</option>`).join(""));

let shown = 100, wp = "all", mode = "current", gapSel = "";  // wp: the "Remote" quick filter ("all" or "remote")
let NL = null, NL_PREV_SORT = "score", nlSeq = 0;  // natural-language search result from /api/search
const PVL = {apply_now: "Apply now", after_prep: "After prep", after_portfolio: "After prep", long_shot: "Long shot", skip: "Skip"};
const pvLab = j => j.pv_label === "after_portfolio" ? "after_prep" : j.pv_label;
const LBL_OPTS = {
  current: [["all","Any fit"],["apply_now","Strong match"],["tailor","Worth tailoring"],["good","Strong + worth tailoring"],["stretch","Stretch"],["noskip","Hide not-a-fit"]],
  pivot: [["noskip","Hide skips"],["all","Everything"],["apply_now","Apply now"],["good","Apply now + After prep"],["after_prep","After prep"],["long_shot","Long shots"],["labs","Frontier AI labs only"]],
};
function setLabelOptions(){ $("lbl").innerHTML = LBL_OPTS[mode].map(([v,l]) => `<option value="${v}">${l}</option>`).join(""); }
const pvJobs = () => jobs.filter(j => (j.tracks || []).includes("ai"));
function drawPivotPanel(){
  const pj = pvJobs(), scored = pj.filter(j => j.pv_label);
  const n = f => scored.filter(f).length;
  $("pvTitle").textContent = D.target_name || "Target";
  $("pvHelp").innerHTML = esc((D.target_summary ? D.target_summary + " " : "") + "Tap a number to filter.") + (NOAI ? ` ${noClaude("Rating jobs for your target")}` : "");
  const counts = [["apply_now", n(j => pvLab(j)==="apply_now"), "Apply now", "a genuine shot today"],
    ["after_prep", n(j => pvLab(j)==="after_prep"), "After prep", "once you've done the prep"],
    ["long_shot", n(j => pvLab(j)==="long_shot"), "Long shots", "possible, but a reach"],
    ["all", pj.length - scored.length, "Not yet rated", "use Get Claude's take"]];
  $("pvCounts").innerHTML = counts.map(([v,c,l,sub]) => `<button type="button" data-lbl="${v}" title="${esc(sub)}" aria-pressed="${$("lbl").value === v}"><b>${c}</b> ${l}</button>`).join("");
  const tally = {}, label = {};
  scored.filter(j => ["apply_now","after_prep"].includes(pvLab(j))).forEach(j => (j.pv_gaps||[]).forEach(g => { const k = g.toLowerCase(); if (k.includes("ts/sci") || k.includes("scif")) return; tally[k] = (tally[k]||0) + 1; label[k] = label[k] || g; }));
  const top = Object.entries(tally).sort((a,b) => b[1]-a[1]).slice(0, 10), mx = top.length ? top[0][1] : 1;
  $("pvGaps").innerHTML = top.length ? top.map(([k,c]) => `<button type="button" class="gaprow" data-gap="${esc(k)}" aria-pressed="${gapSel===k}"><span>${esc(label[k])}</span><i style="width:${Math.max(4, c/mx*100)}%"></i><em>${c}</em></button>`).join("")
    : `<div class="note">Appears once Claude has rated some jobs as Apply now or After prep.</div>`;
}
$("pvCounts").addEventListener("click", e => { const b = e.target.closest("button[data-lbl]"); if (!b) return; $("lbl").value = b.dataset.lbl; gapSel = ""; shown = 100; drawPivotPanel(); render(); });
$("pvGaps").addEventListener("click", e => { const b = e.target.closest("button[data-gap]"); if (!b) return; gapSel = gapSel === b.dataset.gap ? "" : b.dataset.gap; if (gapSel) $("lbl").value = "noskip"; shown = 100; drawPivotPanel(); render(); });
["q","clr","co","st","sort","paidonly","newonly","reqall","lbl","nowide","cList","cType","cSize","cVal","cAge","cGd","cLay","cEq"].forEach(id => $(id).addEventListener("input", () => { shown = 100; render(); }));
$("more").addEventListener("click", () => { shown += 100; render(); });
$("count").addEventListener("click", e => { if (e.target.id === "reqShow") { $("reqall").checked = true; shown = 100; render(); } });
// ---- My search (top of the Filters panel): this profile's saved search settings, the same ones /setup asks for.
// They decide which jobs reach the board: home ZIP / radius / ways of working / remote anywhere / pay floor are applied
// when the board is built (jobfinder.select_for_person); level and travel limit are applied here (mySearchOk).
// Each change saves through POST /api/person/settings, like My profile used to: the server re-checks this board (and
// queues the automatic quick check of new jobs), and the page reloads itself once the rebuilt board is ready.
// None of these reset Claude's ratings (the pay floor only matters to the Target tab's ratings).
let MYS = null, msBase, msTimer = null;
const msNow = () => MYS || {seniority_band: (D.seniority && D.seniority.band) || [3, 5], travel_max: D.travel_max || "any"};
function mySearchOk(j){
  const s = msNow(), SB = s.seniority_band || [3, 5], L = j.level, t = j.travel || "", tm = s.travel_max || "any";
  if (L != null && (L < SB[0] || L > SB[1])) return false;
  if (tm === "moderate" && t === "heavy") return false;
  if (tm === "light" && !["", "none", "light"].includes(t)) return false;
  if (tm === "none" && !["", "none"].includes(t)) return false;
  return true;
}
function msFill(){
  if (!MYS) return;
  document.querySelectorAll("[data-ms]").forEach(el => {
    const k = el.dataset.ms, v = MYS[k];
    if (el.type === "checkbox") { el.checked = !!v; return; }
    if (el.tagName === "SELECT" && v != null && ![...el.options].some(o => o.value === String(v))) el.add(new Option(k === "radius_miles" ? `${v} miles` : String(v), String(v)));
    if (document.activeElement !== el) el.value = v == null ? "" : String(v);
  });
  document.querySelectorAll("[data-mswp]").forEach(el => el.checked = (MYS.workplaces || []).includes(el.dataset.mswp));
}
function msSay(t, err){ $("msState").textContent = t; $("msState").classList.toggle("err", !!err); }
function msLoaded(st){
  if (!SERVED || !st) return;
  MYS = st; $("msWrap").hidden = false; msFill();
}
const msBoard = () => fetch("/api/profile/board" + pq()).then(r => r.json());
if (SERVED) msBoard().then(b => { if (msBase === undefined) msBase = b.board_at || null; }).catch(() => {});
function msAwaitBoard(){
  let tries = 0;
  clearTimeout(msTimer);
  const tick = () => msBoard().then(b => {
    if (b.board_at && b.board_at !== msBase && !b.rebuilding) { saveFilters(); location.reload(); return; }
    if (++tries < 90) msTimer = setTimeout(tick, 2000);
    else msSay("Saved. Your board re-checks as soon as the current update or re-rate finishes.");
  }).catch(() => { msTimer = setTimeout(tick, 4000); });
  msTimer = setTimeout(tick, 1500);
}
function msSave(settings){
  msSay("Saving…");
  fetch("/api/person/settings", {method: "POST", headers: H, body: JSON.stringify({person: PID, settings})})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) { msFill(); msSay(d.error || "Couldn't save that.", true); return; }
      MYS = Object.assign({}, MYS, d.settings); msFill();
      if (MYS.salary_floor) D.salary_floor = MYS.salary_floor;
      shown = 100; render();
      msSay("Saved. Re-checking your board…"); msAwaitBoard();
    }).catch(() => { msFill(); msSay("Couldn't reach Siftwell, so that wasn't saved.", true); });
}
$("msGrid").addEventListener("change", e => {
  const el = e.target;
  if (el.dataset.mswp) {
    const wps = [...document.querySelectorAll("[data-mswp]")].filter(x => x.checked).map(x => x.dataset.mswp);
    if (!wps.length) { el.checked = true; msSay("Pick at least one way of working.", true); return; }
    msSave({workplaces: wps}); return;
  }
  if (el.dataset.ms) msSave({[el.dataset.ms]: el.type === "checkbox" ? el.checked : el.value});
});

function payBar(j){
  if (j.salary_max == null) return `<div class="pay"><span class="amt">Not listed</span><div>No salary range in posting</div></div>`;
  const lo = 100000, hi = 400000, p = v => Math.max(0, Math.min(100, (v-lo)/(hi-lo)*100));
  const mid = j.salary_mid ?? Math.round((j.salary_min + j.salary_max)/2);
  const note = j.wide_band
    ? `<div class="note">Wide band (top is ${(j.salary_max/j.salary_min).toFixed(1)}× bottom). Scored on midpoint ${fmt(mid)}.</div>`
    : `<div>Midpoint ${fmt(mid)}${mid < D.salary_floor ? " · below your floor" : ""}</div>`;
  return `<div class="pay"><span class="amt">${fmt(j.salary_min)} – ${fmt(j.salary_max)}</span>
    <div class="bar${j.wide_band ? " wide" : ""}" title="Range ${fmt(j.salary_min)}–${fmt(j.salary_max)}, midpoint ${fmt(mid)}">
      <i style="left:${p(j.salary_min)}%;width:${Math.max(1.5,p(j.salary_max)-p(j.salary_min))}%"></i>
      ${CUR.base ? `<span class="mk cur" style="left:${p(CUR.base)}%" title="Your current base ${fmt(CUR.base)}"></span>` : ""}
      <span class="mk" style="left:${p(D.salary_floor)}%" title="Your floor ${fmt(D.salary_floor)}"></span>
      <span class="mid" style="left:${p(mid)}%" title="Midpoint ${fmt(mid)}"></span>
    </div><div class="axis"><span>$100k</span><span>$250k</span><span>$400k</span></div>
    ${note}</div>`;
}

const LVN = {2: "Mid-level", 3: "Senior", 4: "Lead / Manager", 5: "Principal / Sr. Manager", 6: "Director", 7: "VP / Executive"};
function levelChip(j){
  if (j.level == null) return "";
  return `<span class="chip" title="${j.level_src === "years" ? "Level estimated from years of experience required" : "Level from job title"}">${LVN[j.level]}${j.level_src === "years" ? " (by years)" : ""}</span>`;
}
const TRV = {heavy: "Travel", moderate: "Travel", light: "Travel", some: "Travel required (amount not stated)", none: "No travel"};
function travelChip(j){
  if (!j.travel) return "";
  const label = j.travel_pct ? `Travel up to ${j.travel_pct}%` : TRV[j.travel];
  return `<span class="chip trv-${j.travel}" title="${esc(j.travel_text || "")}">${label}</span>`;
}

// ---- preferences (from the server; defaults until loaded)
let PREFS = {"display.clearance": "secret", "display.sort": "score", "display.theme": "system", "tailor.questions": "always"};
let RESTORED = false;  // true when filters came back from a page refresh, so defaults don't override them
function applyTheme(){
  const t = PREFS["display.theme"];
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("jb.theme", t); } catch(e) {}
  themeSync();
}
try { const t = localStorage.getItem("jb.theme"); if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; } catch(e) {}
function applyDisplayDefaults(){
  applyTheme();
  if (!RESTORED) {
    $("clr").value = PREFS["display.clearance"]; $("sort").value = PREFS["display.sort"];
    if (!jobs.some(j => j.ai_fit != null) && ["score", "odds", "odds_later"].includes($("sort").value)) $("sort").value = "appeal";  // nothing to rank by Match yet
    if (!location.hash && PREFS["display.start_tab"] && PREFS["display.start_tab"] !== "jobs") { location.hash = "#" + PREFS["display.start_tab"]; return; }
  }
  render();
}

// ---- tailored resumes (per profile): registry for cards + the Tailored tab
// TLIST items: state "ready" (a finished resume), "running" (Tailor my resume was pressed; still working) or "failed".
// "work" says whether a Re-tailor is running or failed on a finished one. While anything runs, the list is re-read every
// few seconds, so the cards and the Resumes tab follow along (also after a reload: the server keeps this per profile).
let TAILORED = {}, TLIST = [], WORK = {}, tlTimer = null, tlRunning = "";
const tlBusy = x => x.state === "running" || (x.work && x.work.running);
function loadTailored(){
  if (!SERVED) return Promise.resolve();
  return fetch("/api/tailored" + pq()).then(r => r.json()).then(d => {
    TLIST = d.items || [];
    TAILORED = Object.fromEntries(TLIST.filter(x => x.state !== "running" && x.state !== "failed").map(x => [x.job.id, x.slug]));
    WORK = Object.fromEntries(TLIST.filter(x => tlBusy(x) || x.state === "failed" || (x.work && x.work.error)).map(x => [x.job.id, x]));
    $("tab-tailored").innerHTML = `Resumes${TLIST.length ? `<span class="n">${TLIST.length}</span>` : ""}`;
    const running = TLIST.filter(tlBusy).map(x => x.slug).sort().join(" ");
    const changed = running !== tlRunning; tlRunning = running;
    clearTimeout(tlTimer);
    if (running) tlTimer = setTimeout(() => loadTailored().then(c => { if (c) { render(); if (location.hash === "#tailored") drawTailored(); } else if (location.hash === "#tailored") drawTailored(); }), 4000);
    return changed;
  }).catch(() => {});
}
const TL_STEP = {start: "Starting…", rescore: "Re-scoring with your answers…", tailor: "Tailoring… (about a minute)", pdf: "Building the PDF…", grade: "Astra is grading…", rework: "Claude is reworking…"};
function reviewBadge(r){
  if (!r || !r.status) return "";
  if (r.status === "needs_answers") return `<span class="gd lo">Astra ${r.final ?? "?"} · ${r.pending} question${r.pending === 1 ? "" : "s"} waiting</span>`;
  if (r.status === "error") return `<span class="gd lo">Astra review failed</span>`;
  if (r.status === "running") return `<span class="gd">Astra review in progress…</span>`;
  if (r.status === "interrupted") return `<span class="gd lo">Astra review interrupted at ${r.final ?? "?"}</span>`;
  const pass = r.status === "passed";
  return `<span class="gd ${pass ? "hi" : "lo"}">Astra ${r.final} · ${pass ? "passed" : `below ${r.threshold}`} · ${r.rounds} round${r.rounds === 1 ? "" : "s"}</span>`;
}
function drawTailored(){
  const byId = Object.fromEntries(jobs.map(j => [j.id, j]));
  const nRun = TLIST.filter(x => x.state === "running").length, nReady = TLIST.filter(x => x.state !== "running" && x.state !== "failed").length;
  $("tlCount").textContent = !SERVED ? "Open the board from the server to see tailored resumes." : TLIST.length ? `${nReady} tailored resume${nReady === 1 ? "" : "s"}${nRun ? ` · ${nRun} being tailored` : ""}` : "No tailored resumes yet. Tap Tailor my resume on any job.";
  $("tlList").innerHTML = TLIST.map(x => {
    const j = byId[x.job.id], when = x.created ? new Date(x.created).toLocaleDateString([], {month: "short", day: "numeric", year: "numeric"}) : "";
    const m = j ? (j.ai_fit ?? j.pv_now) : null, w = x.work || {};
    const title = safeUrl(x.job.url) ? `<a class="title" href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">${esc(x.job.title || "Job")}</a>` : `<span class="title">${esc(x.job.title || "Job")}</span>`;
    const posting = safeUrl(x.job.url) ? `<a href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">Posting</a>` : "";
    if (x.state === "running" || x.state === "failed") {  // not a finished resume yet
      const run = x.state === "running";
      return `<li class="job tlcard ${run ? "working" : "failed"}" data-slug="${esc(x.slug)}">
      <div class="scores"><div class="tlicon" aria-hidden="true">${run ? "…" : "!"}</div></div>
      <div style="min-width:0">${title}
        <div class="meta"><span class="coname">${esc(x.job.company || "")}</span>${run ? `<span class="tlwork" role="status"><span class="spin"></span>${esc(TL_STEP[w.step] || "Tailoring…")}</span>` : `<span class="gd lo">Tailoring failed</span>`}</div>
        ${run ? `<div class="tl2">Claude is writing this resume. It takes a minute or two; you can keep browsing, and it stays here if you reload.</div>` : `<div class="tlfail">${esc(w.error || "Something went wrong.")}</div>`}
        <div class="acts">${run ? "" : `<button class="pri" data-retry="${esc(x.job.id)}"${NOAI ? ' disabled title="Needs Claude"' : ""}>Try again</button>`}${posting}${run ? "" : `<button class="danger" data-dismiss="${esc(x.slug)}">Remove</button>`}</div>
      </div></li>`;
    }
    return `<li class="job tlcard">
      <div class="scores">${j ? `<div class="score" title="Overall">${j.score}<small>OVERALL</small></div>` : ""}${m != null ? `<div class="score match ${m >= 70 ? "hi" : m >= 45 ? "mid" : "lo"}">${m}<small>MATCH</small></div>` : ""}</div>
      <div style="min-width:0">
        ${safeUrl(x.job.url) ? `<a class="title" href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">${esc(x.job.title || "")}</a>` : `<span class="title">${esc(x.job.title || "")}</span>`}
        <div class="meta"><span class="coname">${esc(x.job.company || "")}</span><span>Tailored ${esc(when)}</span><span>${j ? "Still open" : "No longer on your board"}</span>${x.gaps ? `<span>${x.gaps} gaps flagged</span>` : ""}${w.running ? `<span class="tlwork" role="status"><span class="spin"></span>Re-tailoring: ${esc(TL_STEP[w.step] || "working…")}</span>` : reviewBadge(x.review)}</div>
        ${x.headline ? `<div class="tl2">${esc(x.headline)}</div>` : ""}
        ${w.error && !w.running ? `<div class="tlfail">Re-tailoring failed: ${esc(w.error)} <button class="btn ghost sm" type="button" data-dismiss="${esc(x.slug)}">Dismiss</button></div>` : ""}
        <div class="acts">${x.review && x.review.status === "interrupted" ? `<button class="pri" data-resume="${esc(x.job.id)}" data-slug="${x.slug}">Resume review</button>` : ""}${x.review && x.review.status === "needs_answers" ? `<button class="pri" data-astra="${esc(x.job.id)}" data-slug="${x.slug}">Answer Astra's questions</button>` : ""}<a class="pri" href="/tailored/${x.slug}.pdf">Download PDF</a><a href="/tailored/${x.slug}" target="_blank" rel="noopener">Review</a><a href="/tailored/${x.slug}.docx">Word</a>${safeUrl(x.job.url) ? `<a href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">Posting</a>` : ""}<button class="danger" data-del="${x.slug}">Remove</button></div>
      </div></li>`;
  }).join("");
}

// ---- company info: researched facts (dated, sourced) + live hiring stats from this board
const CI = D.company_info || {};
const big = v => v == null ? "" : v >= 1e12 ? "$" + (v/1e12).toFixed(v >= 1e13 ? 0 : 1) + "T" : v >= 1e9 ? "$" + (v/1e9).toFixed(v >= 1e11 ? 0 : 1).replace(/\.0$/, "") + "B" : v >= 1e6 ? "$" + Math.round(v/1e6) + "M" : "$" + v;
const mon = s => { if (!s) return ""; const [y, m] = s.split("-"); return new Date(+y, (+m || 1) - 1, 1).toLocaleString([], {month: "short", year: "numeric"}); };
const OWN = {public: "Public", private: "Private", subsidiary: "Part of", nonprofit: "Nonprofit", "government-sponsored": "Gov-sponsored", cooperative: "Credit union / co-op"};
// Review-weighted rating for sorting: pulls small samples toward a typical 3.7 (as if 50 average reviews were added).
function gdWeighted(c){
  if (c.gd_rating == null) return 0;
  const n = c.gd_reviews ?? 100;
  return (c.gd_rating * n + 3.7 * 50) / (n + 50);
}
function gdChip(c){
  if (c.gd_rating == null) return "";
  const r = c.gd_rating, few = c.gd_reviews != null && c.gd_reviews < 100;
  const cls = few ? "" : r >= 4 ? "hi" : r >= 3.5 ? "" : "lo";
  return `<span class="gd ${cls}" title="Glassdoor rating${c.gd_reviews ? `, ${c.gd_reviews.toLocaleString()} reviews` : ""}${c.gd_as_of ? `, as of ${mon(c.gd_as_of)}` : ""}${few ? " (few reviews, read with care)" : ""}">★ ${r.toFixed(1)}${few ? "*" : ""}</span>`;
}
function coLine(j){
  const c = CI[j.company]; if (!c) return `<span>${esc(j.sector || "")}</span>`;
  const parts = [];
  if (c.ownership === "subsidiary" && c.parent) parts.push(`Part of ${esc(c.parent)}`);
  else if (c.ownership) parts.push(esc(OWN[c.ownership] || c.ownership) + (c.ownership === "private" && c.stage && c.stage.length <= 14 ? ` · ${esc(c.stage)}` : ""));
  if (c.value_usd) parts.push(`${big(c.value_usd)} ${c.value_kind === "market cap" ? "mkt cap" : "valuation"}`);
  if (c.employees) parts.push(`~${c.employees >= 10000 ? Math.round(c.employees/1000) + "k" : c.employees.toLocaleString()} people`);
  return parts.map(p => `<span>${p}</span>`).join("") + gdChip(c);
}
function coPanel(j){
  const c = CI[j.company] || {};
  const src = (u, t) => safeUrl(u) ? ` <a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${t || "source"}</a>` : ` <span class="asof">(unverified)</span>`;
  const row = (k, v) => v ? `<dt>${k}</dt><dd>${v}</dd>` : "";
  const glass = "https://www.glassdoor.com/Search/results.htm?keyword=" + encodeURIComponent(j.company.replace(/\s*\(.*\)|\s*\/.*$/g, ""));
  const facts = [
    row("Ownership", c.ownership ? esc(c.ownership === "subsidiary" && c.parent ? "Subsidiary of " + c.parent : (OWN[c.ownership] || c.ownership)) + (c.ticker ? ` (${esc(c.ticker)})` : "") + (c.stage ? ` · ${esc(c.stage)}` : "") : ""),
    row(c.value_kind === "market cap" ? "Market cap" : "Valuation", c.value_usd ? `${big(c.value_usd)}${c.value_as_of ? ` <span class="asof">as of ${mon(c.value_as_of)}</span>` : ""}${src(c.value_source)}` : ""),
    row("Raised", c.total_raised_usd ? big(c.total_raised_usd) : ""),
    row("Employees", c.employees ? `~${c.employees.toLocaleString()}${c.employees_as_of ? ` <span class="asof">as of ${mon(c.employees_as_of)}</span>` : ""}${src(c.employees_source)}` : ""),
    row("Founded", c.founded ? `${c.founded} <span class="asof">(${new Date().getFullYear() - c.founded} yrs)</span>` : ""),
    row("HQ", c.hq ? esc(c.hq) + (c.dmv_presence ? ` · ${esc(c.dmv_presence)}` : "") : ""),
    row("Equity", c.equity ? esc(c.equity) : ""),
    row("Tender offers", c.tender_offers ? esc(c.tender_offers) : ""),
    row("Layoffs (18 mo)", c.layoffs ? esc(c.layoffs) + (c.layoffs === "none reported" && !c.layoffs_source ? "" : src(c.layoffs_source)) : ""),
    row("Glassdoor", c.gd_rating != null ? `★ ${c.gd_rating.toFixed(1)}${c.gd_reviews ? ` · ${c.gd_reviews.toLocaleString()} reviews` : ""}${c.gd_recommend_pct != null ? ` · ${c.gd_recommend_pct}% would recommend` : ""}${c.gd_as_of ? ` <span class="asof">as of ${mon(c.gd_as_of)}</span>` : ""}${src(c.gd_source)}${c.gd_reviews != null && c.gd_reviews < 100 ? ` <span class="asof">(few reviews)</span>` : ""}${c.gd_note ? ` <span class="asof">${esc(c.gd_note)}</span>` : ""}` : ""),
    row("Hiring for you", `${c.open || 0} open on your board${c.new_week && c.new_week < c.open ? `, ${c.new_week} new this week` : ""}${c.median_mid ? ` · typical midpoint ${fmt(c.median_mid)}` : ""}`),
  ].join("");
  return `<details class="copanel" open><summary>About ${esc(j.company)}</summary>
    ${c.blurb ? `<p>${esc(c.blurb)}</p>` : ""}<dl>${facts}</dl>
    <div class="colinks">${safeUrl(c.levels_url) ? `<a href="${esc(safeUrl(c.levels_url))}" target="_blank" rel="noopener">Pay on Levels.fyi</a>` : ""}<a href="${glass}" target="_blank" rel="noopener">Reviews on Glassdoor</a></div>
    ${c.researched_at ? `<p class="asof">Facts looked up by Claude on ${esc(new Date(String(c.researched_at).slice(0, 10) + "T12:00:00").toLocaleDateString([], {month: "short", day: "numeric", year: "numeric"}))}; they can be wrong, so check the sources.</p>` : c.ownership ? "" : `<p class="asof">Company facts not researched yet.</p>`}</details>`;
}

const ago = d => { if (!d) return ""; const t = Date.parse(d); if (!t) return ""; const n = Math.round((Date.now() - t) / 864e5); return n <= 0 ? "today" : n === 1 ? "yesterday" : n < 7 ? n + "d ago" : n < 45 ? Math.round(n / 7) + "w ago" : Math.round(n / 30) + "mo ago"; };
const whereTxt = j => j.workplace === "remote" ? "Remote" : ((j.dmv_locations.length ? j.dmv_locations : j.locations)[0] || "").replace(/,?\s*(United States( of America)?|USA)$/i, "").slice(0, 40) + (j.workplace === "hybrid" ? " · Hybrid" : "");
const payTxt = j => j.salary_min == null ? "Pay not listed" : (j.salary_max && j.salary_max !== j.salary_min ? `${fmt(j.salary_min)}–${fmt(j.salary_max)}` : fmt(j.salary_min));
const TIERN = {haiku: "Quick rating (Haiku)", sonnet: "Sonnet rating", opus: "Careful rating (Opus)"};
const tierName = j => j.ai_tier ? TIERN[j.ai_tier] + (j.ai_at ? " · " + j.ai_at : "") + (j.ai_stale ? " · made with older info" : "") : "Not rated yet";
const verdict = j => mode === "pivot" ? (j.pv_label ? [pvLab(j), PVL[j.pv_label]] : null) : (j.ai_label ? [j.ai_label, LBL[j.ai_label]] : null);
let SEL = null, OPENED = false;
function card(j){
  const s = status[j.id] || "", pvm = mode === "pivot";
  const sc = pvm ? (j.pv_score ?? j.score) : j.score, m = pvm ? j.pv_now : j.ai_fit, v = verdict(j);
  return `<li class="jrow ${s==="hidden"?"hidden-by-user":""}" role="option" tabindex="0" data-id="${esc(j.id)}" aria-selected="${SEL === j.id}">
    <div class="rtitle">${j.new ? '<span class="ndot" title="New this week"></span>' : ""}${esc(j.title)}</div>
    <div class="rsc"><div><b>${pvm ? sc : (j.appeal ?? "–")}</b><small>${pvm ? "Overall" : "Appeal"}</small></div><div><b class="m ${m >= 70 ? "hi" : ""}${m == null && NOAI ? " na" : ""}" title="${m == null && NOAI ? "Match ratings need Claude" : pvm ? "" : tierName(j)}">${m ?? (NOAI ? "—" : "–")}</b><small>Match${!pvm && j.ai_tier && j.ai_tier !== "opus" ? `<span class="tierdot t-${j.ai_tier}"></span>` : ""}</small></div></div>
    <div class="rco">${esc(j.company)} · ${esc(whereTxt(j))}</div>
    <div class="rmeta">${v ? `<span class="vpill v-${v[0]}">${v[1]}</span>` : NOAI ? "" : `<span class="vpill">Not rated yet</span>`}<span class="amt">${payTxt(j)}</span>${j.posted ? `<span>${ago(j.posted)}</span>` : ""}${(pvm ? j.pv_stale : j.ai_stale) ? '<span class="old" title="Rated before your latest info">Older info</span>' : ""}${j.req_status === "unmet" ? '<span class="rq un">Requirement not met</span>' : j.req_status === "flag" ? '<span class="rq">Check requirements</span>' : ""}${TAILORED[j.id] ? "<span>Resume ready</span>" : WORK[j.id] && WORK[j.id].state === "running" ? "<span>Tailoring…</span>" : ""}${s === "applied" ? "<span>Applied</span>" : s === "saved" ? "<span>★ Saved</span>" : ""}</div>
    <div class="racts"><button type="button" data-k="saved" aria-pressed="${s==="saved"}" title="Save" aria-label="Save">★</button><button type="button" data-k="hidden" aria-pressed="${s==="hidden"}" title="Not for me" aria-label="Hide">✕</button></div>
  </li>`;
}
function detail(j){
  if (!j) return `<div class="dempty"><b>Pick a job</b>Select a job to see why it fits, what's missing, and what to do next.</div>`;
  const s = status[j.id] || "", pvm = mode === "pivot";
  const sc = pvm ? (j.pv_score ?? j.score) : j.score, m = pvm ? j.pv_now : j.ai_fit, v = verdict(j);
  const asis = pvm ? j.pv_later : j.ai_asis;
  const read = pvm
    ? (j.pv_reason ? `<p><span class="lab">${v ? v[1] : ""}${j.pv_now != null ? ` · now ${j.pv_now}, after prep ${j.pv_later}` : ""}</span>${esc(j.pv_reason)}</p>` : "") + (j.pv_angle ? `<p><span class="lab">How to pitch yourself</span>${esc(j.pv_angle)}</p>` : "") + ((j.pv_gaps || []).length ? `<div class="chips">${j.pv_gaps.map(g => `<span class="chip gap">${esc(g)}</span>`).join("")}</div>` : "")
    : (j.ai_reason ? `<p><span class="lab">${v ? v[1] : ""}</span>${esc(LBL_HELP[j.ai_label] || "")}</p><p><span class="lab">Why it fits, and the gap${j.ai_level && j.ai_level !== "match" ? (j.ai_level === "stretch" ? " · a step above you" : " · below your level") : ""}</span>${esc(j.ai_reason)}</p>` : "") + (j.ai_tailor ? `<p><span class="lab">How to pitch yourself</span>${esc(j.ai_tailor)}</p>` : "");
  const unrated = pvm ? j.pv_label == null : j.ai_fit == null;
  const wpChip = j.workplace ? `<span class="chip ${j.workplace}">${j.workplace === "onsite" ? "On-site" : j.workplace[0].toUpperCase()+j.workplace.slice(1)}</span>` : `<span class="chip">Workplace not stated</span>`;
  const locs = (j.dmv_locations.length ? j.dmv_locations : j.locations).slice(0,4).map(l => `<span class="chip">${esc(l)}</span>`).join("");
  const clr = j.clearance ? `<span class="chip ${j.clearance.includes("poly")?"poly":""}">${esc(j.clearance)}</span>` : "";
  const tl = TAILORED[j.id], wk = WORK[j.id];
  const tailorBtns = !SERVED ? "" : wk && tlBusy(wk) ? `<button class="btn primary" type="button" disabled>${esc(TL_STEP[(wk.work || {}).step] || "Tailoring…")}</button><a class="btn" href="#tailored">See it in Resumes</a>`
    : wk && wk.state === "failed" ? `<button class="btn primary" type="button" data-tailor="1"${NOAI ? ' disabled title="Needs Claude"' : ""}>Tailoring failed · Try again</button>`
    : tl ? `<a class="btn primary" href="/tailored/${tl}.pdf">Download resume PDF</a><a class="btn" href="/tailored/${tl}" target="_blank" rel="noopener">Review resume</a><button class="btn" type="button" data-tailor="1" data-again="1"${NOAI ? ' disabled title="Needs Claude"' : ""}>Re-tailor</button>`
    : NOAI ? `<button class="btn primary" type="button" disabled title="Needs Claude">Tailor my resume</button>${noClaude("Tailoring")}` : `<button class="btn primary" type="button" data-tailor="1">Tailor my resume</button>`;
  return `<div class="dpane" data-id="${esc(j.id)}">
    <button class="dback" type="button" id="dBack">‹ All jobs</button>
    <div><h2 class="dtitle">${esc(j.title)}</h2>
      <div class="dco"><span class="coname">${esc(j.company)}</span><span>${esc(whereTxt(j))}</span>${j.posted ? `<span>Posted ${ago(j.posted)}</span>` : ""}${v ? `<span class="vpill v-${v[0]}">${v[1]}</span>` : ""}${j.new ? '<span class="chip new">New</span>' : ""}</div></div>
    <div class="dacts acts">${tailorBtns}
      <button class="btn" type="button" data-k="saved" aria-pressed="${s==="saved"}">${s==="saved" ? "★ Saved" : "☆ Save"}</button>
      <button class="btn" type="button" data-k="applied" aria-pressed="${s==="applied"}">${s==="applied" ? "✓ Applied" : "Mark applied"}</button>
      ${safeUrl(j.url) ? `<a class="btn" href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener">View posting ↗</a>` : ""}
      <button class="btn ghost" type="button" data-k="hidden" aria-pressed="${s==="hidden"}">${s==="hidden" ? "Unhide" : "Not for me"}</button></div>
    <section class="dsec"><h3>How you stack up</h3><div class="dscores">
      ${pvm ? `<div class="dsc"><div class="ring" style="--p:${sc}"><b>${sc}</b></div><p><strong>Overall</strong>Odds, pay and quality of life combined.</p></div>`
        : `<div class="dsc"><div class="ring" style="--p:${j.appeal ?? 0}"><b>${j.appeal ?? "–"}</b></div><p><strong>Appeal</strong>How well this job gives you what you want.${j.appeal_parts ? `<br>Pay ${j.appeal_parts.pay} · Place ${j.appeal_parts.place} · Level ${j.appeal_parts.level} · Company ${j.appeal_parts.company} · Travel ${j.appeal_parts.burden}` : ""}</p></div>`}
      <div class="dsc"><div class="ring" style="--p:${m ?? 0}"><b>${m ?? "–"}</b></div><p><strong>Match</strong>${m == null ? (NOAI ? "Needs Claude." : "Not rated yet.") : pvm ? `Your shot today with an honest tailored resume (after prep: ${j.pv_later}).` : `How well your resume matches what they want${asis != null && asis !== m ? ` (${asis} as written today)` : ""}.<br><span class="tiertag t-${j.ai_tier}">${esc(tierName(j))}</span>`}</p></div>
    </div></section>
    <section class="dsec dread"><h3>Claude's read</h3>${!unrated && (pvm ? j.pv_stale : j.ai_stale) && SERVED ? `<div class="ratefresh"><span class="old">Rated before your latest info</span><button class="btn sm" type="button" data-rate="1">Re-rate this job</button></div>` : ""}${unrated && NOAI ? `<p>${noClaude("Claude's read")}</p>` : unrated ? `<p>Claude hasn't read this one yet.</p>${SERVED && D.profile ? `<button class="btn" type="button" data-rate="1">Get Claude's take (about 30 seconds)</button>` : ""}` : read}</section>
    ${reqSection(j)}
    <section class="dsec"><h3>Pay</h3>${payBar(j)}</section>
    <section class="dsec"><h3>Details</h3><div class="chips">${levelChip(j)}${wpChip}${locs}${clr}${j.scif ? `<span class="chip onsite">SCIF</span>` : ""}${travelChip(j)}</div></section>
    <section class="dsec"><h3>About ${esc(j.company)}</h3>${coPanel(j)}</section>
    <section class="dsec"><h3>From the posting</h3><p class="snipp" id="dDesc">${esc(j.snippet || "")}${j.snippet ? "…" : ""}</p>${SERVED ? `<button class="btn ghost sm" type="button" id="dFull" style="margin-top:6px">Show the full posting</button>` : ""}</section>
  </div>`;
}
function reqSection(j){
  const st = j.req_status, chips = j.req_chips || [], soft = j.req_soft || [];
  if (!st || (st === "ok" && !soft.length)) return "";
  const head = st === "unmet" ? "You may not meet a hard requirement" : st === "flag" ? "Check these requirements" : "Nice to have";
  return `<section class="dsec reqbox"><h3>Requirements</h3><div><b>${head}</b></div>
    <div class="chips">${chips.map(c => `<span class="chip req-${st}">${esc(c)}</span>`).join("")}${soft.map(c => `<span class="chip">${esc(c)}</span>`).join("")}</div>
    ${(j.req_reasons || []).length ? `<div class="reqwhy">${(j.req_reasons || []).map(esc).join("<br>")}</div>` : ""}
    ${st !== "ok" ? `<div class="reqwhy">Wrong? Fix your degrees or licenses under <a href="/profile#highlights">My profile</a> and the board re-checks.</div>` : ""}</section>`;
}
let DREAD = null;
function drawDetail(){
  const j = jobs.find(x => x.id === SEL), el = $("detail"), same = j && DREAD === j.id, top = el.scrollTop;
  syncFbar();
  el.innerHTML = detail(j);
  el.classList.toggle("open", OPENED && !!j);
  el.scrollTop = same ? top : 0;
  DREAD = j ? j.id : null;
}
// The details panel sits below the sticky search/filter bar on wide screens: keep --fbar equal to the bar's height
// (the bar grows with search notes, quick filters and filter chips, so it is measured again whenever it changes).
// While the Filters panel is open the bar scrolls away with the page (position:static), so nothing sits above the details then.
function syncFbar(){ const b = document.querySelector("#view-jobs .filters"); if (b && b.offsetHeight) document.documentElement.style.setProperty("--fbar", (getComputedStyle(b).position === "sticky" ? b.offsetHeight : 0) + "px"); }
if (window.ResizeObserver && document.querySelector("#view-jobs .filters")) new ResizeObserver(syncFbar).observe(document.querySelector("#view-jobs .filters"));
window.addEventListener("resize", syncFbar);
syncFbar();
function select(id, open){
  SEL = id; OPENED = !!open;
  document.querySelectorAll(".jrow").forEach(r => r.setAttribute("aria-selected", r.dataset.id === id));
  drawDetail();
  if (OPENED && window.matchMedia("(max-width:900px)").matches) {
    document.body.style.overflow = "hidden";
    if (!(history.state && history.state.sheet)) history.pushState({sheet: 1}, "");  // phone back gesture closes the sheet
  }
}
function closeDetail(fromPop){
  const wasOpen = OPENED && $("detail").classList.contains("open");
  OPENED = false; $("detail").classList.remove("open"); document.body.style.overflow = "";
  if (wasOpen && !fromPop && history.state && history.state.sheet) history.back();
}
window.addEventListener("popstate", () => { if ($("detail").classList.contains("open")) closeDetail(true); });
function act(e){
  const host = e.target.closest("[data-id]"); if (!host) return false;
  const id = host.dataset.id;
  const rb = e.target.closest("button[data-rate]");
  if (rb) { rateJobs([id], rb); return true; }
  const tb = e.target.closest("button[data-tailor]");
  if (tb) { tailorJob(id, tb); return true; }
  const b = e.target.closest("button[data-k]"); if (!b) return false;
  const k = b.dataset.k;
  status[id] = status[id] === k ? "" : k; if (!status[id]) delete status[id];
  saveStatus(id); render(); return true;
}
$("detail").addEventListener("click", e => {
  if (e.target.closest("#dBack")) { closeDetail(); return; }
  const full = e.target.closest("#dFull");
  if (full) {
    full.disabled = true; full.textContent = "Loading…";
    fetch("/api/desc?id=" + encodeURIComponent(SEL)).then(r => r.json()).then(d => { $("dDesc").textContent = d.desc || "The full posting isn't saved; use View posting."; full.remove(); })
      .catch(() => { full.textContent = "Couldn't load it"; });
    return;
  }
  act(e);
});
$("list").addEventListener("click", e => {
  if (e.target.closest(".racts")) { act(e); return; }
  const r = e.target.closest(".jrow"); if (r) select(r.dataset.id, true);
});
$("list").addEventListener("keydown", e => { const r = e.target.closest(".jrow"); if (r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(r.dataset.id, true); } });
document.addEventListener("keydown", e => {
  if (e.target.matches("input, select, textarea") || $("qSheet").open) return;
  if (e.key === "Escape") { closeDetail(); $("amenu").hidden = true; return; }
  if (!["ArrowDown","ArrowUp","j","k"].includes(e.key) || !$("view-companies").hidden || !$("view-tailored").hidden) return;
  const ids = window.__shownIds || []; if (!ids.length) return;
  e.preventDefault();
  let i = ids.indexOf(SEL); i = (e.key === "ArrowDown" || e.key === "j") ? Math.min(ids.length - 1, i + 1) : Math.max(0, i - 1);
  select(ids[i], OPENED);
  const el = document.querySelector(`.jrow[data-id="${CSS.escape(ids[i])}"]`); if (el) el.scrollIntoView({block: "nearest"});
});
function render(){
  const q = $("q").value.trim().toLowerCase(), clr = $("clr").value, co = $("co").value, st = $("st").value;
  window.__reqHidden = 0;
  let r = jobs.filter(j => {
    if (wp === "remote" && j.workplace !== "remote") return false;
    if (!mySearchOk(j)) return false;
    if (co !== "all" && j.company !== co) return false;
    const lb = $("lbl").value;
    if (mode === "pivot") {
      if (!(j.tracks || []).includes("ai")) return false;
      if (lb === "noskip" && j.pv_label === "skip") return false;
      if (["apply_now","after_prep","long_shot"].includes(lb) && pvLab(j) !== lb) return false;
      if (lb === "good" && !["apply_now","after_prep"].includes(pvLab(j))) return false;
      if (lb === "labs" && j.ai_track !== "lab") return false;
      if (gapSel && !(j.pv_gaps || []).some(g => g.toLowerCase() === gapSel)) return false;
    } else {
      if (lb === "good" && !["apply_now","tailor"].includes(j.ai_label)) return false;
      if (lb === "noskip" && j.ai_label === "skip") return false;
      if (["apply_now","tailor","stretch"].includes(lb) && j.ai_label !== lb) return false;
    }
    if ($("paidonly").checked && j.salary_max == null) return false;
    if ($("nowide").checked && j.wide_band) return false;
    if (!companyOk(j)) return false;
    if ($("newonly").checked && !j.new) return false;
    if (j.req_status === "unmet" && !$("reqall").checked) { window.__reqHidden++; return false; }
    if (clr === "none" && j.clearance) return false;
    if (clr === "nopoly" && j.clearance === "TS/SCI + poly") return false;
    if (clr === "secret" && ["TS/SCI + poly","TS/SCI","Top Secret"].includes(j.clearance)) return false;
    const s = status[j.id] || "";
    if (PIN) { if (s !== PIN) return false; }
    else if (st === "active" && s === "hidden") return false;
    else if (["saved","applied","hidden"].includes(st) && s !== st) return false;
    if (nlOn()) { if (!NL.rank.has(j.id)) return false; }
    else if (q && !(j.title+" "+j.company+" "+j.locations.join(" ")+" "+j.sector).toLowerCase().includes(q)) return false;
    return true;
  });
  const key = $("sort").value;
  const by = {rel: j => -((nlOn() ? NL.rank.get(j.id) || 0 : 0) * 1e3 + (mode === "pivot" ? (j.pv_score ?? 0) : j.score)),
    score: j => -(mode === "pivot" ? (j.pv_score ?? 0) : j.score), appeal: j => -((j.appeal ?? 0) * 1e3 + (j.ai_fit ?? 0)),
    gd: j => -(gdWeighted(CI[j.company] || {}) * 1e6 + (j.salary_mid || 0) / 1e3), pay: j => -(j.salary_mid ?? 0), odds: j => -(((mode === "pivot" ? j.pv_now : j.ai_fit) ?? -1) * 1e6 + ((mode === "pivot" ? j.pv_later : j.ai_asis) ?? 0) * 1e3 + (j.salary_mid || 0) / 1e3),
    odds_later: j => -(((mode === "pivot" ? j.pv_later : j.ai_asis) ?? -1) * 1e6 + ((mode === "pivot" ? j.pv_now : j.ai_fit) ?? 0) * 1e3 + (j.salary_mid || 0) / 1e3), new: j => -(Date.parse(j.first_seen + "T00:00") || 0) - (Date.parse(j.posted) || 0)/1e6};
  r.sort((a,b) => by[key](a) - by[key](b));
  const base = mode === "pivot" ? pvJobs().length : jobs.length;
  $("count").innerHTML = `${r.length.toLocaleString()} of ${base.toLocaleString()} jobs` + (r.length > shown ? ` · showing ${shown}` : "") +
    (!NOAI && D.ratings && (D.ratings.stale + D.ratings.unrated) ? ` · <span title="Rated with older info or not rated yet. Use the Re-rate (sparkle) icon at the top.">${D.ratings.stale + D.ratings.unrated} of your top ${D.ratings.top} need a fresh rating</span>` : "") +
    (window.__reqHidden ? ` · <button type="button" class="linkbtn" id="reqShow">${window.__reqHidden.toLocaleString()} hidden: requirements you don't meet</button>` : "");
  drawChips();
  const unrated = r.filter(j => mode === "pivot" ? j.pv_label == null : j.ai_fit == null);
  window.__unrated = unrated.slice(0, 45).map(j => j.id);
  $("rateMore").hidden = !SERVED || !D.profile || !unrated.length;
  $("rateMore").textContent = `Get Claude's take on the next ${Math.min(45, unrated.length)} unrated here` + (NOAI ? " (needs Claude)" : "");
  const page = r.slice(0, shown);
  window.__shownIds = page.map(j => j.id);
  if (!page.some(j => j.id === SEL)) { SEL = !window.matchMedia("(max-width:900px)").matches && page[0] ? page[0].id : null; if (!SEL) OPENED = false; }
  $("list").innerHTML = page.length ? page.map(card).join("") : `<li class="dempty"><b>${PIN === "saved" ? "Nothing saved yet" : PIN === "applied" ? "No applications yet" : "No jobs match"}</b>${PIN === "saved" ? "Tap Save on any job to keep it here." : PIN === "applied" ? "Mark a job as applied and it moves here, so you can keep track." : (!nlOn() && SERVED && q.split(/\s+/).length > 1 ? "Press Enter to have Claude search for that description." : "Try removing a filter.")}</li>`;
  $("more").hidden = r.length <= shown;
  drawDetail(); drawQuick(); drawTabCounts(); nlDraw(r.length);
}
// ---- natural-language search: Enter sends the description to Claude, which picks role / topic / company terms
function nlOn(){ return !!NL && $("q").value.trim() === NL.q; }
function nlSet(d){
  NL = {q: d.q, crit: d.criteria, ids: d.ids, raw: d, rank: new Map(d.ids.map((id, i) => [id, d.scores[i]]))};
  if ($("sort").value !== "rel") NL_PREV_SORT = $("sort").value;
  $("sortRel").hidden = false; $("sort").value = "rel";
}
function nlClear(){
  NL = null; $("sortRel").hidden = true;
  if ($("sort").value === "rel") $("sort").value = NL_PREV_SORT || "score";
  $("nlBar").hidden = true; $("nlBar").className = "nlbar";
}
function nlDraw(total){
  if (!nlOn()) return;
  const c = NL.crit, n = NL.ids.length, hid = n - total;
  const parts = [...c.role_terms.slice(0, 4), ...c.companies.slice(0, 4), ...c.sectors.slice(0, 3), ...c.topic_terms.slice(0, 5)];
  if (c.workplace === "remote") parts.push("remote"); if (c.workplace === "dmv") parts.push("Near me");
  if (c.min_salary) parts.push("$" + Math.round(c.min_salary / 1000) + "k+");
  const fb = !!(NL.raw && NL.raw.fallback);  // no Claude: a plain keyword search
  $("nlBar").className = "nlbar"; $("nlBar").hidden = false;
  $("nlBar").innerHTML = `<span>${fb ? "Keyword search for" : "Claude searched for"} <b>${esc(c.summary)}</b>: ${n.toLocaleString()} match${n === 1 ? "" : "es"}${hid > 0 ? `, ${hid.toLocaleString()} hidden by your filters` : ""}.</span>` +
    (hid > 0 ? `<button type="button" class="linkbtn" data-nl="all">Show all matches</button>` : "") +
    `<button type="button" class="linkbtn" data-nl="clear">Clear search</button>` +
    (fb ? `<span class="nlterms">${esc(NL.raw.note || "")} ${NOAI_LINK}</span>` : parts.length ? `<span class="nlterms">Matching on: ${esc(parts.join(", "))}</span>` : "");
}
function runNL(){
  const q = $("q").value.trim();
  if (!q || !SERVED || nlOn()) return;
  const seq = ++nlSeq;
  $("nlBar").className = "nlbar"; $("nlBar").hidden = false;
  $("nlBar").innerHTML = `<span class="spin" aria-hidden="true"></span><span>${NOAI ? "Searching" : "Claude is reading"} “${esc(q)}”…</span>`;
  fetch("/api/search", {method: "POST", headers: H, body: JSON.stringify({q})})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (seq !== nlSeq || $("q").value.trim() !== q) return;
      if (!ok) { if (d.signin || /signed out/i.test(d.error || "")) { $("nlBar").className = "nlbar err"; signInOffer($("nlBar"), "Claude Code is signed out, so searches can't be read yet. Showing plain keyword matches for now."); return; } throw new Error(d.error || "Search failed."); }
      nlSet(d); shown = 100; render();
    })
    .catch(e => {
      if (seq !== nlSeq) return;
      $("nlBar").className = "nlbar err";
      $("nlBar").innerHTML = `<span>${esc(e.message || "Search failed.")} Showing plain keyword matches for now.</span>`;
    });
}
$("q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); runNL(); } });
$("q").addEventListener("input", () => {
  if (NL && $("q").value.trim() !== NL.q) { nlClear(); render(); }
  if (!NL) { nlSeq++; $("nlBar").hidden = true; }
});
$("nlBar").addEventListener("click", e => {
  const b = e.target.closest("button[data-nl]"); if (!b) return;
  if (b.dataset.nl === "clear") { $("q").value = ""; nlClear(); }
  else {
    ["clr", "co", "lbl"].forEach(id => $(id).value = "all");
    ["paidonly", "nowide", "newonly"].forEach(id => $(id).checked = false); $("reqall").checked = true;
    CF_IDS.forEach(id => $(id).value = "all"); gapSel = "";
    wp = "all";
  }
  shown = 100; render();
});
if (!SERVED) $("q").placeholder = "Search title, company, location…";
else if (window.matchMedia("(max-width:640px)").matches) $("q").placeholder = "Describe the job you want…";

// ---- Claude sign-in from the board: the server starts "claude auth login", we show its link, the person
// signs in on whatever device they're using and pastes back the code the sign-in page shows.
function signInOffer(el, lead){
  el.hidden = false;
  el.innerHTML = `<span>${esc(lead)}</span> <button class="btn sm primary" type="button" data-cl="start">Sign in to Claude</button>`;
}
const clPost = body => fetch("/api/claude/login", {method: "POST", headers: H, body: JSON.stringify(body)}).then(r => r.json().then(d => ({ok: r.ok, d})));
document.addEventListener("click", e => {
  const b = e.target.closest("button[data-cl]"); if (!b) return;
  const box = b.closest(".banner, .nlbar"), act = b.dataset.cl, msg = t => { const m = box.querySelector(".clmsg"); if (m) m.textContent = t; };
  if (act === "start") {
    b.disabled = true; b.textContent = "Starting…";
    clPost({action: "start"}).then(({ok, d}) => {
      if (!ok) throw new Error(d.error || "Couldn't start sign-in.");
      box.innerHTML = `<b>Sign in to Claude</b><ol class="clsteps">
        <li><a class="btn sm primary" href="${esc(d.url)}" target="_blank" rel="noopener">Open the Claude sign-in page</a> and sign in with your Claude account.</li>
        <li>Copy the code the page shows, paste it here, and finish.<div class="clrow"><input type="text" class="clcode" placeholder="Paste the code" aria-label="Sign-in code" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="btn sm primary" type="button" data-cl="code">Finish sign-in</button><button class="btn sm" type="button" data-cl="cancel">Cancel</button></div></li>
      </ol><span class="clmsg" role="status"></span>`;
    }).catch(err => { b.disabled = false; b.textContent = "Sign in to Claude"; box.insertAdjacentHTML("beforeend", `<span class="clmsg">${esc(err.message)}</span>`); });
  }
  if (act === "code") {
    const code = box.querySelector(".clcode").value.trim();
    if (!code) { msg("Paste the code from the sign-in page first."); return; }
    b.disabled = true; b.textContent = "Checking…"; msg("");
    clPost({action: "code", code}).then(({ok, d}) => {
      if (!ok) throw Object.assign(new Error(d.error || "Sign-in didn't go through."), {expired: !!d.expired});
      const inSearch = box.id === "nlBar";
      box.className = box.className.replace(" err", "");
      box.innerHTML = `<span class="clok">Signed in to Claude.</span> <span>${inSearch ? "Running your search now." : "Ratings pick up again with the next update, or use Update now in the profile menu."}</span>`;
      if (inSearch) { nlSeq++; runNL(); }
      else document.querySelectorAll(".nlbar.err").forEach(x => x.hidden = true);
    }).catch(err => {
      b.disabled = false; msg(err.message);
      if (err.expired) { b.dataset.cl = "start"; b.textContent = "Start over"; box.querySelector(".clcode").value = ""; }  // the CLI ended; a new link is needed
      else b.textContent = "Finish sign-in";
    });
  }
  if (act === "cancel") { clPost({action: "cancel"}); box.hidden = true; }
});
if (SERVED) clPost({action: "status"}).then(({d}) => {
  const ready = !!d.logged_in && d.installed !== false;
  if (!ready && !NOAI) { NOAI = true; applyNoAI(!!d.installed); }  // Claude went away since this board was built
  else if (!ready && d.installed && NOAI) noClaudeBanner(true);  // installed but signed out: offer the sign-in button
  else if (ready && NOAI) { NOAI = false; applyNoAI(false); $("aiBanner").hidden = false; $("aiBanner").textContent = "Claude is connected. Use Update now in the profile menu (or the Re-rate sparkle icon) to get Match ratings."; }
  if (d.logged_in && (D.ai_status === "cli_logged_out" || D.pivot_status === "cli_logged_out")) $("aiBanner").textContent = "Claude Code is signed in. Ratings pick up again with the next update, or use Update now in the profile menu.";
}).catch(() => {});
// Settings gear badge: number of missing required Get started items (hidden when none); settings_page.py has the same logic.
function setGsBadge(s){
  const n = s && !s.complete && s.missing ? s.missing.length : 0, b = $("gsBadge");
  if (!b) return;
  b.hidden = !n; b.textContent = n || "";
  $("prefsBtn").setAttribute("aria-label", n ? `Settings, ${n} required setup step${n > 1 ? "s" : ""} left` : "Settings");
}
// ---- "Finish setting up" banner: links to /settings#get-started while required checklist items are missing; Dismiss is remembered in this browser
if (SERVED) {
  let gsOff = ""; try { gsOff = localStorage.getItem("jb.gsOff") || ""; } catch(e) {}
  fetch("/api/setup-status").then(r => r.json()).then(s => {
    setGsBadge(s);
    if (!s || s.complete || !s.total) return;
    const miss = (s.missing || []).slice().sort().join(","), seen = gsOff.split(",");
    if (gsOff && (s.missing || []).every(m => seen.includes(m))) return;  // dismissed; shows again if something new is missing
    const b = $("gsBanner");
    b.innerHTML = `<span>Finish setting up Siftwell (${s.done} of ${s.total} done)</span><a class="btn sm primary" href="/settings#get-started">Open the checklist</a><button class="btn sm ghost" type="button" id="gsOff">Dismiss</button>`;
    b.hidden = false;
    $("gsOff").addEventListener("click", () => { b.hidden = true; try { localStorage.setItem("jb.gsOff", miss); } catch(e) {} });
  }).catch(() => {});
}
const QUICK = [["good", "Strong & worth tailoring"], ["remote", "Remote"], ["nonprofit", "Nonprofit"], ["paid", "Pay listed"], ["new", "New"]];
function quickOn(k){
  if (k === "good") return $("lbl").value === "good";
  if (k === "remote") return wp === "remote";
  if (k === "nonprofit") return $("cList").value === "nonprofit";
  if (k === "paid") return $("paidonly").checked;
  if (k === "new") return $("newonly").checked;
}
function drawQuick(){
  const hasNP = LISTS.options.some(o => o.id === "nonprofit");
  $("lbl").closest(".field").hidden = NOAI && !hasMatch;  // the Fit filter is about Claude's verdicts
  $("quick").innerHTML = QUICK.filter(([k]) => (k !== "nonprofit" || hasNP) && (k !== "good" || (mode !== "pivot" && !(NOAI && !hasMatch)))).map(([k, l]) => `<button type="button" class="qc" data-qk="${k}" aria-pressed="${!!quickOn(k)}">${l}</button>`).join("");
}
$("quick").addEventListener("click", e => {
  const b = e.target.closest("button[data-qk]"); if (!b) return;
  const k = b.dataset.qk, on = !quickOn(k);
  if (k === "good") $("lbl").value = on ? "good" : "all";
  if (k === "remote") wp = on ? "remote" : "all";
  if (k === "nonprofit") $("cList").value = on ? "nonprofit" : "all";
  if (k === "paid") $("paidonly").checked = on;
  if (k === "new") $("newonly").checked = on;
  shown = 100; render();
});
function drawTabCounts(){
  const n = k => Object.values(status).filter(v => v === k).length;
  $("tab-saved").innerHTML = `Saved<span class="n">${n("saved")}</span>`;
  $("tab-applied").innerHTML = `Applied<span class="n">${n("applied")}</span>`;
}

$("cos").innerHTML = D.companies.slice().sort((a,b)=>b.matched-a.matched || a.company.localeCompare(b.company)).map(c => `<tr>
  <td>${esc(c.company)}</td><td>${esc(c.sector)}</td><td>${TIER[c.tier]||esc(c.tier)}</td><td>${esc(c.ats)}</td>
  <td class="n">${c.raw_jobs.toLocaleString()}</td><td class="n">${c.matched}</td>
  <td class="${c.status==="ok"?"":"err"}">${c.status==="ok"?"OK":esc(c.status)}</td></tr>`).join("");

let PIN = "";
function route(){
  if (location.hash === "#filters") {  // My profile links here: the Jobs tab with the Filters panel (and its My search group) open
    history.replaceState(null, "", location.pathname + location.search + "#jobs");
    $("fPanel").hidden = false; $("filtersBtn").setAttribute("aria-expanded", "true"); syncFbar();
  }
  const v = {"#companies": "companies", "#pivot": "pivot", "#tailored": "tailored", "#saved": "saved", "#applied": "applied"}[location.hash] || "jobs";
  PIN = v === "saved" || v === "applied" ? v : "";
  closeDetail(true);
  $("view-jobs").hidden = v === "companies" || v === "tailored"; $("view-companies").hidden = v !== "companies"; $("view-tailored").hidden = v !== "tailored";
  ["jobs","pivot","saved","applied","tailored","companies"].forEach(t => $("tab-" + t).setAttribute("aria-current", v===t ? "page" : "false"));
  if (v === "tailored") drawTailored();
  const m = v === "pivot" ? "pivot" : "current";
  if (m !== mode || !$("lbl").options.length) { mode = m; gapSel = ""; setLabelOptions(); shown = 100; }
  $("pvPanel").hidden = mode !== "pivot";
  $("sortLater").textContent = mode === "pivot" ? "Best match after prep" : "Best match as written";
  $("legend").hidden = mode === "pivot"; $("pvLegend").hidden = mode !== "pivot";
  $("legend2").innerHTML = mode === "pivot"
    ? "<b>Overall</b> = how worth pursuing a job is: 50% odds (60% today, 40% after prep) + 30% pay + 20% quality of life. <b>Match</b> = your shot today with an honest tailored resume (Claude's 0 to 100 rating; 70+ is a genuine shot; it's a rating, not a probability). Hover it for the after-prep number."
    : "<b>Appeal</b> = how well a job gives you what you want, worked out from the posting and company facts: 40% pay against your floor, 20% workplace and distance, 15% level, 15% company (Glassdoor, layoffs), 10% travel and clearance burden. <b>Match</b> = how well your resume, honestly tailored, meets what they ask for (Claude's 0 to 100 rating; 70+ is a genuine shot; it's a rating, not a probability). Every job gets a quick Haiku rating, the best ~15% a Sonnet rating, and your top 300 a careful Opus rating; a hollow dot means quick, a filled dot Sonnet, no dot Opus. <b>Best bets</b> (the default order) ranks jobs high on both.";
  if (mode === "pivot") drawPivotPanel();
  render();
}
// ---- company filters (researched facts; unknown values are excluded once a filter is set, except "or unrated")
const CF_IDS = ["cList", "cType", "cSize", "cVal", "cAge", "cGd", "cLay", "cEq"];
const CF_LABEL = {cList: "", cType: "", cSize: "Size: ", cVal: "Value: ", cAge: "", cGd: "Glassdoor ", cLay: "Layoffs: ", cEq: ""};
function companyOk(j){
  const c = CI[j.company] || {}, v = id => $(id).value;
  const li = v("cList");
  if (li !== "all" && !((LISTS.by_company || {})[j.company] || []).includes(li)) return false;
  const t = v("cType");
  if (t === "public" && c.ownership !== "public") return false;
  if (t === "private" && c.ownership !== "private") return false;
  if (t === "lab" && j.ai_track !== "lab") return false;
  if (t === "ai" && !j.ai_track) return false;
  if (t === "np" && !["nonprofit", "government-sponsored", "cooperative"].includes(c.ownership)) return false;
  const e = c.employees, sz = v("cSize");
  if (sz !== "all") {
    if (e == null) return false;
    if (sz === "s" && !(e < 200)) return false;
    if (sz === "m" && !(e >= 200 && e < 1000)) return false;
    if (sz === "l" && !(e >= 1000 && e < 10000)) return false;
    if (sz === "xl" && !(e >= 10000)) return false;
    if (sz === "nsxl" && !(e < 10000)) return false;
  }
  const val = c.value_usd, vv = v("cVal");
  if (vv !== "all") {
    if (val == null) return false;
    if (vv === "v1" && !(val < 1e9)) return false;
    if (vv === "v10" && !(val >= 1e9 && val < 1e10)) return false;
    if (vv === "v100" && !(val >= 1e10 && val < 1e11)) return false;
    if (vv === "vbig" && !(val >= 1e11)) return false;
    if (vv === "v10p" && !(val >= 1e10)) return false;
  }
  const age = c.founded ? new Date().getFullYear() - c.founded : null, a = v("cAge");
  if (a !== "all") {
    if (age == null) return false;
    if (a === "a5" && !(age < 5)) return false;
    if (a === "a15" && !(age >= 5 && age < 15)) return false;
    if (a === "aold" && !(age >= 15)) return false;
    if (a === "a15m" && !(age < 15)) return false;
  }
  const g = c.gd_rating, gv = v("cGd");
  if (gv === "g40" && !(g >= 4)) return false;
  if (gv === "g35" && !(g >= 3.5)) return false;
  if (gv === "g35u" && g != null && g < 3.5) return false;
  if (gv === "g40r" && !(g >= 4 && (c.gd_reviews || 0) >= 100)) return false;
  const lay = (c.layoffs || "").toLowerCase(), none = /^(none|no )/.test(lay), l = v("cLay");
  if (l === "none" && !none) return false;
  if (l === "noknown" && lay && !none) return false;
  const eq = v("cEq"), liquid = c.ownership === "public" || /\(public\)/i.test(c.equity || "");
  if (eq === "liquid" && !liquid) return false;
  if (eq === "private" && (liquid || c.ownership !== "private")) return false;
  return true;
}

// ---- filters panel and active-filter chips
const FDEF = () => ({clr: PREFS["display.clearance"] || "secret", st: "active", co: "all", lbl: mode === "pivot" ? "noskip" : "all"});
const optText = id => { const o = $(id).selectedOptions[0]; return o ? o.textContent : ""; };
function activeFilters(){
  const out = [];
  if (wp === "remote") out.push(["wp", "Remote"]);
  for (const id of ["lbl", "clr", "co"]) if ($(id).value !== "all") out.push([id, optText(id)]);
  for (const id of CF_IDS) if ($(id).value !== "all") out.push([id, CF_LABEL[id] + optText(id)]);
  if ($("st").value !== "active") out.push(["st", "Show: " + optText("st")]);
  for (const [id, t] of [["paidonly", "Salary listed"], ["nowide", "No wide bands"], ["newonly", "New"], ["reqall", "Including requirements I don't meet"]]) if ($(id).checked) out.push([id, t]);
  if (gapSel) out.push(["gap", "Gap: " + gapSel]);
  return out;
}
function drawChips(){
  const a = activeFilters();
  $("fChips").innerHTML = a.map(([id, t]) => `<button type="button" class="fchip" data-f="${id}" aria-label="Remove filter ${esc(t)}">${esc(t)}<span aria-hidden="true">×</span></button>`).join("");
  $("fCount").hidden = !a.length; $("fCount").textContent = a.length;
}
$("fChips").addEventListener("click", e => {
  const b = e.target.closest("button[data-f]"); if (!b) return;
  const id = b.dataset.f;
  if (id === "wp") wp = "all";
  else if (id === "gap") { gapSel = ""; if (mode === "pivot") drawPivotPanel(); }
  else if ($(id).type === "checkbox") $(id).checked = false;
  else $(id).value = id === "st" ? "active" : "all";
  shown = 100; render();
});
$("filtersBtn").addEventListener("click", () => { const open = $("fPanel").hidden; $("fPanel").hidden = !open; $("filtersBtn").setAttribute("aria-expanded", open); syncFbar(); });
$("fDone").addEventListener("click", () => { $("fPanel").hidden = true; $("filtersBtn").setAttribute("aria-expanded", "false"); syncFbar(); });
$("fReset").addEventListener("click", () => {
  const d = FDEF(); Object.entries(d).forEach(([k, v]) => $(k).value = v);
  ["paidonly", "nowide", "newonly", "reqall"].forEach(id => $(id).checked = false);
  CF_IDS.forEach(id => $(id).value = "all");
  wp = "all"; gapSel = "";
  shown = 100; if (mode === "pivot") drawPivotPanel(); render();
});

const FILTER_IDS = ["q","clr","co","st","sort","paidonly","newonly","reqall","nowide","cList","cType","cSize","cVal","cAge","cGd","cLay","cEq"];
function saveFilters(){
  try { sessionStorage.setItem("jb.filters", JSON.stringify({f: Object.fromEntries(FILTER_IDS.map(id => [id, $(id).type === "checkbox" ? $(id).checked : $(id).value])), lbl: $("lbl").value, wp, y: scrollY, nl: nlOn() ? NL.raw : null, fp: !$("fPanel").hidden})); } catch(e) {}
}
setLabelOptions();
window.addEventListener("hashchange", route); route();
""" + THEME_JS + r"""
// Home: back to the Jobs tab with the detail sheet and side panels closed, keeping search and filters.
$("homeBtn").addEventListener("click", e => {
  e.preventDefault();
  $("addPersonPanel").hidden = true;
  const onJobs = !location.hash || location.hash === "#jobs";
  if (history.state && history.state.sheet) history.replaceState(null, "", onJobs ? location.pathname + location.hash : "#jobs");  // drop the phone sheet's history entry
  else if (!onJobs) history.pushState(null, "", "#jobs");
  route(); scrollTo(0, 0);
});
try {
  const sv = JSON.parse(sessionStorage.getItem("jb.filters") || "null");
  if (sv) {
    sessionStorage.removeItem("jb.filters"); RESTORED = true;
    FILTER_IDS.forEach(id => { if (id in sv.f) { if ($(id).type === "checkbox") $(id).checked = sv.f[id]; else $(id).value = sv.f[id]; } });
    if (sv.nl && $("q").value.trim() === sv.nl.q) nlSet(sv.nl);
    if (!(NL ? ["rel"] : []).concat(["score","appeal","odds","odds_later","pay","gd","new"]).includes($("sort").value)) $("sort").value = "score";
    $("lbl").value = sv.lbl; wp = sv.wp === "remote" ? "remote" : "all";  // an older "Near me" (dmv) value is ignored
    if (sv.fp) { $("fPanel").hidden = false; $("filtersBtn").setAttribute("aria-expanded", "true"); syncFbar(); }
    render(); setTimeout(() => scrollTo(0, sv.y || 0), 60);
  }
} catch(e) {}
if (!jobs.length && !D.profile) { $("aiBanner").hidden = false; $("aiBanner").innerHTML = `New profile: <a href="/profile#resume">${NOAI ? "fill in your profile" : "upload a resume"} on My profile</a>. Once it's approved, an update fills this board (about 15 minutes).`; }

function noClaudeBanner(signIn){
  if (!jobs.length && !D.profile) return;  // the "New profile" prompt is more useful until there is a profile
  const b = $("aiBanner"); b.hidden = false;
  b.innerHTML = `<span><b>${NOAI_MSG}</b> → ${NOAI_LINK}. Siftwell still finds and filters jobs and ranks them by Appeal.</span>` +
    (signIn && SERVED ? ` <button class="btn sm primary" type="button" data-cl="start">Sign in to Claude</button>` : "");
}
// Re-applies everything that depends on whether Claude is connected (also when the live check disagrees with the board).
function applyNoAI(signIn){
  ["odds", "odds_later"].forEach(v => { const o = $("sort").querySelector(`option[value=${v}]`); o.hidden = o.disabled = NOAI && !hasMatch; });
  if (NOAI && !hasMatch && ["odds", "odds_later"].includes($("sort").value)) $("sort").value = "appeal";
  if (NOAI) noClaudeBanner(signIn);
  const panel = $("rrPanel");
  [...panel.children].forEach(c => {
    if (c.classList.contains("rrhead")) return;
    if (c.id === "rrNo") { c.hidden = !NOAI; return; }
    if (NOAI) { if (c.dataset.nh === undefined) c.dataset.nh = c.hidden ? "1" : "0"; c.hidden = true; }
    else if (c.dataset.nh !== undefined) { c.hidden = c.dataset.nh === "1"; delete c.dataset.nh; }
  });
  render();
}
if (NOAI) applyNoAI(false);
else if (D.ai_status === "cli_logged_out" || D.pivot_status === "cli_logged_out") { $("aiBanner").hidden = false; if (SERVED) signInOffer($("aiBanner"), "Claude fit scoring is paused because Claude Code is signed out."); else $("aiBanner").textContent = "Claude fit scoring is paused because Claude Code is signed out. Open the board from the server to sign in."; }
else if (D.ai_status === "no_claude") { NOAI = true; applyNoAI(false); }
else if (D.ai_status === "no_key") { $("aiBanner").hidden = false; $("aiBanner").textContent = "Claude fit scoring is off. Add an Anthropic API key in Settings, then use Update now in the profile menu."; }
else if (D.ai_status === "bad_key") { $("aiBanner").hidden = false; $("aiBanner").textContent = "The saved Anthropic API key was rejected. Replace it in Settings, then use Update now in the profile menu."; }

if (SERVED) {
  $("tools").hidden = false;
  loadTailored().then(() => { render(); if (location.hash === "#tailored") drawTailored(); });
  // The server's marks for THIS profile replace whatever the browser had (never merged with another profile's).
  fetch("/api/marks" + pq()).then(r => r.json()).then(m => { status = (m && typeof m === "object") ? m : {}; cacheMarks(); render(); importLegacyMarks(); }).catch(() => {});
  function importLegacyMarks(){
    let legacy = null, done = "jb.marksImported." + PID;
    try { if (!PID || localStorage.getItem(done)) return; legacy = JSON.parse(localStorage.getItem(LEGACY_MKEY) || "null"); } catch(e) { return; }
    const finish = () => { try { localStorage.setItem(done, "1"); } catch(e) {} };
    if (!legacy || typeof legacy !== "object" || !Object.keys(legacy).length) { finish(); return; }
    fetch("/api/marks/import", {method: "POST", headers: H, body: JSON.stringify({person: PID, marks: legacy})}).then(r => r.ok ? r.json() : null).then(d => {
      if (!d) return;
      finish();
      if (d.added) { status = d.marks || status; cacheMarks(); render(); }
    }).catch(() => {});
  }
  // Settings (/settings, settings_page.py) and My profile (/profile, profile_page.py) are their own pages; their icons in TOOLS are plain links.

  // ---- tailoring
  // ---- on-demand Claude ratings
  function rateJobs(ids, btn){
    if (!ids.length) return;
    btn.disabled = true;
    btn.textContent = ids.length > 1 ? `Claude is rating ${ids.length} jobs… (about ${Math.max(1, Math.round(ids.length / 15))} min)` : "Claude is reading it… (about 30 seconds)";
    fetch("/api/rate", {method: "POST", headers: H, body: JSON.stringify({ids, mode})}).then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
      if (!ok) { btn.disabled = false; btn.textContent = d.error || "Couldn't start"; return; }
      const check = () => fetch("/api/rate").then(r => r.json()).then(s => {
        if (s.running) return setTimeout(check, 3000);
        if (s.error) { btn.disabled = false; btn.textContent = "Failed: " + s.error; return; }
        saveFilters(); location.reload();
      });
      check();
    });
  }
  $("rateMore").addEventListener("click", () => {
    if (NOAI) { $("rateMsg").innerHTML = `Match ratings need Claude. ${NOAI_LINK}`; return; }
    rateJobs(window.__unrated || [], $("rateMore"));
  });

  // ---- profiles
  let curPerson = D.person ? D.person.id : "";
  fetch("/api/people" + pq()).then(r => r.json()).then(d => {
    curPerson = d.current;
    PREFS = d.prefs || PREFS; msLoaded(d.settings); applyDisplayDefaults();
    const me = d.people.find(p => p.id === d.current) || {};
    $("avName").textContent = me.name || "Profile"; $("avInit").textContent = (me.name || "?").trim()[0].toUpperCase();
    $("amPeople").innerHTML = `<div class="who">Profiles</div>` + d.people.map(p => `<button role="menuitem" data-person="${esc(p.id)}" aria-current="${p.id === d.current}">${esc(p.name)}</button>`).join("") + `<button role="menuitem" data-person="__add">Add a person</button><button role="menuitem" data-person="__manage">Manage profiles</button>`;
  }).catch(() => {});
  $("avatarBtn").addEventListener("click", e => { e.stopPropagation(); const h = $("amenu").hidden; $("amenu").hidden = !h; $("avatarBtn").setAttribute("aria-expanded", h); });
  document.addEventListener("click", e => { if (!e.target.closest(".menuWrap")) { $("amenu").hidden = true; $("avatarBtn").setAttribute("aria-expanded", "false"); } });
  $("amenu").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $("amenu").hidden = true;
    const v = b.dataset.person; if (!v) return;
    if (v === "__manage") { location.href = "/settings#profiles"; return; }
    if (v === "__add") { $("addPersonPanel").hidden = false; $("newPersonName").focus(); scrollTo(0, 0); return; }
    if (v === curPerson) return;
    fetch("/api/person", {method: "POST", headers: H, body: JSON.stringify({id: v})}).then(() => { location.hash = ""; location.reload(); });
  });
  $("addPersonCancel").addEventListener("click", () => { $("addPersonPanel").hidden = true; });
  $("addPersonForm").addEventListener("submit", e => {
    e.preventDefault();
    fetch("/api/people/add", {method: "POST", headers: H, body: JSON.stringify({name: $("newPersonName").value})}).then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
      if (!ok) { $("addPersonMsg").textContent = d.error || "Couldn't create it."; return; }
      location.href = "/setup";
    });
  });
  // ---- questions before tailoring, and the answer bank
  const slugify = id => id.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  const LV = {yes: "Yes", some: "Some", no: "No"};
  let facts = [], hasProfile = !!D.profile, hasDraft = false;
  // A new resume that has been read but not approved is checked and approved on My profile.
  fetch("/api/profile").then(r => r.json()).then(p => {
    hasProfile = !!p.active; hasDraft = !!p.draft;
    if (hasDraft && $("aiBanner").hidden) { $("aiBanner").hidden = false; $("aiBanner").innerHTML = `Your new resume has been read. <a href="/profile#about">Review and approve your profile</a> to use it.`; }
  }).catch(() => {});
  const loadFacts = () => fetch("/api/facts").then(r => r.json()).then(d => { facts = d.facts || []; return facts; });
  let qCtx = null;  // {id, btn, context, questions}
  function qWait(msg){ $("qList").innerHTML = `<div class="qwait">${esc(msg)}</div>`; $("qGo").disabled = true; }
  function drawQuestions(qs){
    const prev = Object.fromEntries(facts.map(f => [f.requirement.toLowerCase(), f]));
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
  function fetchQuestions(id){
    const key = id ? slugify(id) : "general";
    const poll = () => fetch("/api/questions/" + key).then(r => r.json()).then(s => s.running ? new Promise(r => setTimeout(r, 2500)).then(poll) : s);
    return fetch("/api/questions/" + key).then(r => r.json()).then(s => {
      if (!s.missing && !s.running && !s.error) return s;
      if (s.running) return poll();
      return fetch("/api/questions", {method: "POST", headers: H, body: JSON.stringify(id ? {id} : {})}).then(poll);
    });
  }
  function openQuestions(id, btn){
    const general = !id;
    qCtx = {id, btn, questions: [], context: ""};
    $("qTitle").textContent = general ? "Questions about your experience" : "A few questions first";
    $("qGo").textContent = general ? "Save answers" : "Save answers and tailor";
    $("qSkip").hidden = general; $("qSkip").textContent = "Skip, tailor now";
    qWait(general ? "Claude is working out what your target roles usually ask for that your resume doesn't show… (about a minute)"
                  : "Claude is comparing the posting with your resume… (about 30 seconds)");
    if (!$("qSheet").open) $("qSheet").showModal();
    Promise.all([loadFacts(), fetchQuestions(id)]).then(([, s]) => {
      if (qCtx.id !== id || !$("qSheet").open) return;
      if (s.error) { qWait("Couldn't get questions: " + s.error); $("qGo").disabled = general; if (!general) $("qGo").textContent = "Tailor anyway"; qCtx.questions = []; return; }
      qCtx.questions = s.questions || []; qCtx.context = s.context || "";
      if (!qCtx.questions.length) {
        if (general) { qWait("Nothing important seems to be missing for your target roles."); return; }
        $("qSheet").close(); startTailor(id, btn, false); return;
      }
      drawQuestions(qCtx.questions);
    }).catch(() => qWait("Lost contact with Siftwell. Check the connection and try again."));
  }
  $("qGo").addEventListener("click", () => {
    if (qCtx.astra) { continueTailor(collectAnswers()); return; }
    const {id, btn, context} = qCtx, answers = collectAnswers();
    $("qGo").disabled = true;
    const save = answers.length ? fetch("/api/answers", {method: "POST", headers: H, body: JSON.stringify({answers, context})}).then(r => r.json()) : Promise.resolve({added: 0});
    save.then(d => {
      if (d.facts) facts = d.facts;
      $("qSheet").close();
      if (id) startTailor(id, btn, (d.added || 0) > 0);
    });
  });
  $("qSkip").addEventListener("click", () => { if (qCtx.astra) { continueTailor([]); return; } $("qSheet").close(); startTailor(qCtx.id, qCtx.btn, false); });

  function tailorJob(id, btn){
    if (btn.dataset.slug) { window.open("/tailored/" + btn.dataset.slug, "_blank"); return; }
    if (!hasProfile) { location.href = hasDraft ? "/profile#about" : "/profile#resume"; return; }  // approve (or upload) the resume first
    const q = PREFS["tailor.questions"], j = jobs.find(x => x.id === id) || {}, m = mode === "pivot" ? j.pv_now : j.ai_fit;
    if (q === "never" || (q === "gaps" && m != null && m >= 70)) { startTailor(id, btn, false); return; }
    openQuestions(id, btn);
  }
  const STEP = s => s.step === "pdf" ? "Building PDF…" : s.step === "tailor" ? "Tailoring… (about a minute)"
    : s.step === "grade" ? `Astra is grading (round ${s.round || 1})…` : s.step === "rework" ? `Claude is reworking${s.round ? ` (after round ${s.round})` : ""}…` : null;
  const refreshTailored = () => loadTailored().then(() => { render(); if (location.hash === "#tailored") drawTailored(); });
  function pollTailor(id, slug, btn){
    const check = () => fetch("/api/tailor/" + slug + pq()).then(r => r.json()).then(s => {
      if (s.running) { btn.textContent = STEP(s) || btn.textContent; return setTimeout(check, 3000); }
      btn.disabled = false;
      if (s.error) { btn.textContent = "Tailoring failed"; btn.title = s.error; refreshTailored(); return; }
      if (s.review_status === "needs_answers" && (s.pending || []).length) { refreshTailored(); openAstraQuestions(id, slug, btn, s); return; }
      refreshTailored();
    }).catch(() => setTimeout(check, 5000));
    check();
  }
  // The job goes into the Resumes tab as "Tailoring…" right away (the server keeps that state per profile, so a reload
  // shows it too), then turns into the finished resume, or into "Tailoring failed" with Try again and Remove.
  function startTailor(id, btn, rescore){
    btn.disabled = true; btn.textContent = rescore ? "Re-scoring with your answers…" : "Tailoring… (about a minute)";
    fetch("/api/tailor", {method: "POST", headers: H, body: JSON.stringify({person: PID, id, rescore})}).then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
      if (!ok || !d.slug) { btn.disabled = false; btn.textContent = d.error || "Couldn't start tailoring"; return; }
      refreshTailored();
      pollTailor(id, d.slug, btn);
    }).catch(() => { btn.disabled = false; btn.textContent = "Lost contact with Siftwell. Try again."; });
  }
  // Astra asked for facts the resume lacks: ask the candidate, then rework
  function openAstraQuestions(id, slug, btn, s){
    qCtx = {id, btn, slug, astra: true, context: "Astra review", questions: s.pending};
    $("qTitle").textContent = `Astra scored this ${s.score}/100 (target ${s.threshold}). A few questions`;
    $("qGo").textContent = "Save answers and rework"; $("qSkip").hidden = false; $("qSkip").textContent = "Skip, rework without them";
    loadFacts().then(() => { drawQuestions(s.pending); if (!$("qSheet").open) $("qSheet").showModal(); });
  }
  $("tlList").addEventListener("click", e => {
    const retry = e.target.closest("button[data-retry]");
    if (retry) { tailorJob(retry.dataset.retry, retry); return; }
    const dis = e.target.closest("button[data-dismiss]");
    if (dis) {
      dis.disabled = true;
      fetch("/api/tailor/dismiss", {method: "POST", headers: H, body: JSON.stringify({person: PID, slug: dis.dataset.dismiss})}).then(refreshTailored);
      return;
    }
    const del = e.target.closest("button[data-del]");
    if (del) {
      if (del.dataset.armed !== "1") {  // two taps: the first arms the button for a few seconds
        del.dataset.armed = "1"; del.textContent = "Tap again to remove";
        setTimeout(() => { if (del.isConnected) { del.dataset.armed = ""; del.textContent = "Remove"; } }, 4000);
        return;
      }
      del.disabled = true; del.textContent = "Removing…";
      fetch("/api/tailored/delete", {method: "POST", headers: H, body: JSON.stringify({person: PID, slug: del.dataset.del})})
        .then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
          if (!ok) { del.disabled = false; del.textContent = d.error || "Couldn't remove"; return; }
          loadTailored().then(() => { drawTailored(); render(); });
        });
      return;
    }
    const rs = e.target.closest("button[data-resume]");
    if (rs) {
      rs.disabled = true; rs.textContent = "Astra is grading…";
      fetch("/api/tailor/resume", {method: "POST", headers: H, body: JSON.stringify({id: rs.dataset.resume})}).then(() => pollTailor(rs.dataset.resume, rs.dataset.slug, rs));
      return;
    }
    const b = e.target.closest("button[data-astra]"); if (!b) return;
    fetch("/api/tailor/" + b.dataset.slug).then(r => r.json()).then(st => openAstraQuestions(b.dataset.astra, b.dataset.slug, b, st));
  });
  function continueTailor(answers){
    const {id, btn, slug} = qCtx;
    $("qSheet").close(); btn.disabled = true; btn.textContent = "Claude is reworking…";
    fetch("/api/tailor/continue", {method: "POST", headers: H, body: JSON.stringify({id, answers})}).then(() => pollTailor(id, slug, btn));
  }

  let wasRunning = false, bgShown = false;
  const PH = {fetch: "Checking company job boards", ai: "Claude is scoring new jobs", pivot: "Claude is rating AI-pivot jobs", facts: "Claude is looking up company facts"};
  function poll(){
    fetch("/api/status").then(r => r.json()).then(s => {
      $("updateBtn").disabled = s.running; $("updateBtn").classList.toggle("busy", !!s.running);
      $("updSmall").textContent = s.running ? "running now…" : "every employer, ~40 min";
      $("updateBtn").title = s.running ? "Updating job listings now…" : "Update job listings now: checks every employer for new jobs (about 40 min)";
      if (s.next_run) { const n = new Date(s.next_run); $("nextRun").textContent = "· next update " + (n.toDateString() === new Date().toDateString() ? "today " : "tomorrow ") + n.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}); }
      else $("nextRun").textContent = "· automatic updates off";
      if (s.running) {
        wasRunning = true; $("progress").hidden = false; scrollTo(0, 0);
        $("progTitle").textContent = (PH[s.phase] || "Working") + "…";
        $("progNote").textContent = s.total ? `${s.done} of ${s.total}` : "";
        $("progBar").style.width = s.total ? (100 * s.done / s.total) + "%" : "4%";
        $("progLog").textContent = s.lines.slice(-6).join("\n");
        setTimeout(poll, 2000);
      } else if (s.job && s.job.alive && !s.job.mine) {  // the job lock is held by another process (e.g. a fetch started before a restart)
        bgShown = true; $("progress").hidden = false;
        const t = s.job.at ? new Date(s.job.at * 1000).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : "";
        $("progTitle").textContent = `A background job is running (${s.job.kind})` + (t ? ` since ${t}` : "");
        $("progNote").textContent = "It will finish on its own; Update and Re-rate wait for it.";
        $("progBar").style.width = "4%"; $("progLog").textContent = "";
        setTimeout(poll, 5000);
      } else if (bgShown && !wasRunning) {
        bgShown = false; $("progress").hidden = true; setTimeout(poll, 5000);
      } else if (wasRunning) {
        if (s.exit === 0) location.reload();
        else { $("progTitle").textContent = "Update failed"; $("progNote").textContent = "Last output:"; $("progLog").textContent = s.lines.join("\n"); }
      }
    }).catch(() => setTimeout(poll, 5000));
  }
  const RR = D.ratings || {};
  const need = NOAI ? 0 : (RR.stale || 0) + (RR.unrated || 0);
  $("rrSmall").textContent = NOAI ? "needs Claude" : need ? `${need} of your top ${RR.top} need a fresh rating` : "all top jobs current";
  $("rerateBtn").title = "Re-rate: choose how Claude re-rates your jobs, no new listings" + (need ? ` (${need} of your top ${RR.top} need a fresh rating)` : " (all top jobs current)");
  if (need) { $("rrBadge").hidden = false; $("rrBadge").textContent = need > 99 ? "99+" : need; }
  // ---- Re-rate panel. Counts come from the board: ai_rs (per tier: "-" none, "s" older info, "f" current) and ai_bb
  // (Best bets with the best available Match) on every job Claude would rate. The server picks again when it runs.
  const RB = D.rate_batch || {haiku: 25, sonnet: 15, opus: 15};
  // A board rendered from an older jobs.json has no per-job rating freshness (ai_rs) or batch sizes (rate_batch): the server
  // rebuilds it once, and until then the panel can't count (it would say "All 0 jobs").
  const COUNTING = !D.rate_batch && !!D.profile;
  if (COUNTING) {
    let tries = 0;
    (function wait(){
      fetch("/api/profile/board").then(r => r.json()).then(b => {
        if (b.counted) { saveFilters(); location.reload(); return; }
        if (++tries < 60) setTimeout(wait, 5000);
      }).catch(() => { if (++tries < 60) setTimeout(wait, 5000); });
    })();
  }
  const TNAME = {haiku: "Quick check (Haiku)", sonnet: "Careful look (Sonnet)", opus: "Best judgment (Opus)"};
  const ratePool = jobs.filter(j => j.ai_rs);
  const byBB = ratePool.slice().sort((a, b) => (b.ai_bb || 0) - (a.ai_bb || 0) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));  // same order the server picks in
  const nf = n => n.toLocaleString();
  const reqs = (n, t) => Math.ceil(n / RB[t]);
  const plural = (n, w) => `${nf(n)} ${w}${n === 1 ? "" : "s"}`;
  const intIn = (id, lo, hi) => { const v = Number($(id).value); const ok = $(id).value.trim() !== "" && Number.isInteger(v) && v >= lo && v <= hi; $(id).setAttribute("aria-invalid", ok ? "false" : "true"); return ok ? v : null; };
  function rrCalc(){
    const pct = intIn("rrPct", 1, 100), top = intIn("rrTop", 1, 2000);
    document.querySelectorAll(".rrTgtN").forEach(e => e.textContent = nf(+(PREFS["claude.per_update"] ?? 300)));
    if (COUNTING) {
      ["rrHN", "rrSNn", "rrONn"].forEach(id => $(id).textContent = "Counting…");
      $("rrHAll").textContent = "Counting… your board is being refreshed for this panel (a minute or so). This page reloads when it's done.";
      $("rrSN").textContent = $("rrON").textContent = "";
      $("rrEstFull").textContent = $("rrEst").textContent = "Counting…";
      document.querySelectorAll("#rrPanel [data-rr]").forEach(b => b.disabled = true);
      document.querySelectorAll(".rrhint").forEach(e => e.hidden = true);
      return {pct, top, n: {haiku: 0, sonnet: 0, opus: 0}, all: 0};
    }
    const stale = (j, i) => j.ai_rs[i] !== "f";
    const hNeed = ratePool.filter(j => stale(j, 0)).length;
    const sTop = pct ? byBB.slice(0, Math.floor(ratePool.length * pct / 100)) : [];
    const saved = ratePool.filter(j => status[j.id] === "saved" || status[j.id] === "applied");
    const oPick = top ? [...new Map(byBB.slice(0, top).concat(saved).map(j => [j.id, j])).values()] : [];
    const sNeed = sTop.filter(j => stale(j, 1)).length, oNeed = oPick.filter(j => stale(j, 2)).length;
    $("rrHAll").textContent = `All ${plural(ratePool.length, "job")} on your board that Claude would rate.`;
    $("rrHN").textContent = nf(hNeed);
    $("rrSN").textContent = pct ? `= ${plural(sTop.length, "job")}` : "(1 to 100)";
    $("rrSNn").textContent = nf(sNeed);
    const savedIn = oPick.length - Math.min(top || 0, byBB.length);
    $("rrON").textContent = top ? `${savedIn > 0 ? `+ ${nf(savedIn)} saved ` : ""}= ${plural(oPick.length, "job")}` : "(1 to 2,000)";
    $("rrONn").textContent = nf(oNeed);
    document.querySelectorAll(".rrPctTxt").forEach(e => e.textContent = pct || "?");
    document.querySelectorAll(".rrTopTxt").forEach(e => e.textContent = top ? nf(top) : "?");
    document.querySelectorAll(".rrhint").forEach(e => e.hidden = !(hNeed >= Math.max(10, ratePool.length * 0.2)));
    const h = $("rrHNeed").checked ? hNeed : ratePool.length, s = $("rrSNeed").checked ? sNeed : sTop.length, o = $("rrONeed").checked ? oNeed : oPick.length;
    const hb = Math.min(hNeed, +(PREFS["claude.haiku_per_night"] ?? 4000));
    const full = reqs(hb, "haiku") + reqs(sNeed, "sonnet") + reqs(oNeed, "opus");
    $("rrEstFull").textContent = full ? `About ${plural(full, "Claude request")} (fewer if the quick check finds little has changed).` : "Everything is current: nothing to do.";
    $("rrEst").textContent = `Claude requests: Quick check ${nf(reqs(h, "haiku"))} · Careful look ${pct ? nf(reqs(s, "sonnet")) : "?"} · Best judgment ${top ? nf(reqs(o, "opus")) : "?"} (${RB.haiku} Haiku or ${RB.sonnet} Sonnet/Opus jobs per request). Uses your Claude plan.`;
    document.querySelectorAll("#rrPanel [data-rr]").forEach(b => b.disabled = (b.dataset.rr !== "haiku" && !(pct && top)));
    return {pct, top, n: {haiku: h, sonnet: s, opus: o}, all: ratePool.length};
  }
  function rrPlace(){
    const p = $("rrPanel"), r = $("rerateBtn").getBoundingClientRect();
    p.style.top = Math.round(r.bottom + 8) + "px";
    p.style.right = Math.max(8, Math.round(innerWidth - r.right - 8)) + "px"; p.style.left = "auto";
  }
  function rrOpen(){
    if (!$("rrPanel").hidden) return rrClose();
    $("rrTitle").textContent = `Re-rate ${D.person && D.person.name ? D.person.name + "'s" : "your"} jobs`;
    if ($("rrPct").value === "") $("rrPct").value = PREFS["claude.sonnet_pct"] || 15;
    if ($("rrTop").value === "") $("rrTop").value = PREFS["claude.opus_top"] || 300;
    document.querySelectorAll(".rrTgt").forEach(e => e.hidden = !D.pivot_enabled);
    $("rrMsg").textContent = ""; $("rrMsg").classList.remove("bad");
    rrCalc(); rrPlace(); $("rrPanel").hidden = false; $("rerateBtn").setAttribute("aria-expanded", "true");
    $("rrPanel").querySelector("[data-rr=full]").focus();
  }
  function rrClose(){ $("rrPanel").hidden = true; $("rerateBtn").setAttribute("aria-expanded", "false"); }
  ["rrPct", "rrTop", "rrHNeed", "rrSNeed", "rrONeed"].forEach(id => $(id).addEventListener("input", rrCalc));
  $("rrClose").addEventListener("click", rrClose);
  addEventListener("resize", () => { if (!$("rrPanel").hidden) rrPlace(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("rrPanel").hidden) { rrClose(); $("rerateBtn").focus(); } });
  document.addEventListener("click", e => { if (!$("rrPanel").hidden && !e.target.closest("#rrPanel,#rerateBtn")) rrClose(); });
  $("rrPanel").addEventListener("click", e => {
    const b = e.target.closest("button[data-rr]"); if (!b) return;
    const kind = b.dataset.rr, c = rrCalc();
    if (kind === "haiku") { c.pct = c.pct || +(PREFS["claude.sonnet_pct"] || 15); c.top = c.top || +(PREFS["claude.opus_top"] || 300); }  // not used by the quick check
    if (!(c.pct && c.top)) { $("rrMsg").textContent = "Sonnet looks at 1 to 100% of your jobs; Opus at 1 to 2,000 jobs."; $("rrMsg").classList.add("bad"); return; }
    const only = kind === "full" ? true : $({haiku: "rrHNeed", sonnet: "rrSNeed", opus: "rrONeed"}[kind]).checked;
    const tgt = !!D.pivot_enabled && $({full: "rrTgtFull", haiku: "rrTgtHaiku", sonnet: "rrTgtSonnet", opus: "rrTgtOpus"}[kind]).checked;
    if (kind !== "full" && !only) {  // a forced run re-rates jobs whose ratings are current: say how many first
      const n = c.n[kind], name = {haiku: "quick check", sonnet: "careful look", opus: "best-judgment look"}[kind];
      if (!confirm(`Give ${plural(n, "job")} a fresh ${name}?\n\nThis also re-rates jobs whose ratings are current: about ${plural(reqs(n, kind), "Claude request")} on your Claude plan.` +
                   (tgt ? `\n\nIt also rates up to ${plural(+(PREFS["claude.per_update"] ?? 300), "job")} for your Target tab.` : ""))) return;
    }
    const body = {tiers: kind === "full" ? ["haiku", "sonnet", "opus"] : [kind], only_needed: only, sonnet_pct: c.pct, opus_top: c.top, target: tgt};
    b.disabled = true;
    fetch("/api/rerate", {method: "POST", headers: H, body: JSON.stringify(body)}).then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
      b.disabled = false;
      $("rrMsg").classList.toggle("bad", !ok);
      if (!ok) { $("rrMsg").textContent = d.error || "Couldn't start"; return; }
      if (d.queued) { $("rrMsg").textContent = "Queued: " + d.label; pollRerate(); return; }
      rrClose(); pollRerate.mine = true; scrollTo(0, 0); pollRerate();
    }).catch(() => { b.disabled = false; $("rrMsg").textContent = "Couldn't reach Siftwell."; $("rrMsg").classList.add("bad"); });
  });
  function pollRerate(){
    clearTimeout(pollRerate.t);
    fetch("/api/rerate").then(r => r.json()).then(s => {
      $("rerateBtn").classList.toggle("busy", !!s.running);
      if (s.running) {
        pollRerate.auto = !!s.auto && !(s.queue || []).length;  // the automatic quick check of new jobs
        $("progress").hidden = false; $("progReload").hidden = true;
        $("progTitle").textContent = (s.label || "Re-rating") + (s.stopping ? ": stopping…" : "…");
        $("progNote").textContent = s.total ? `${TNAME[s.tier] || "Claude"} · batch ${s.done} of ${s.total}` : "starting";
        $("progBar").style.width = s.total ? (100 * s.done / s.total) + "%" : "4%";
        $("progStop").hidden = false; $("progStop").disabled = !!s.stopping;
        $("progQueue").hidden = !(s.queue || []).length;
        $("progQueue").textContent = (s.queue || []).map(q => "Queued: " + q).join(" · ");
        $("progLog").textContent = (s.lines || []).slice(-4).join("\n");
        pollRerate.was = true; pollRerate.t = setTimeout(pollRerate, 3000);
      } else {
        if (pollRerate.was) {
          pollRerate.was = false; $("progStop").hidden = true; $("progQueue").hidden = true;
          if (s.error) { $("progTitle").textContent = "Re-rating stopped"; $("progNote").textContent = s.error; }
          else if (pollRerate.auto && !pollRerate.mine) {  // nobody pressed Run here: don't reload under their hands, offer it
            $("progTitle").textContent = (s.label || "Re-rating") + (s.stopped ? " stopped" : " done"); $("progNote").textContent = "";
            $("progBar").style.width = "100%"; $("progReload").hidden = false;
          } else { saveFilters(); location.reload(); return; }
          pollRerate.auto = pollRerate.mine = false;
        }
        pollRerate.t = setTimeout(pollRerate, 10000);  // a quick check of new jobs can start after a settings change
      }
    }).catch(() => { pollRerate.t = setTimeout(pollRerate, 5000); });
  }
  $("progStop").addEventListener("click", () => {
    $("progStop").disabled = true;
    fetch("/api/rerate/stop", {method: "POST", headers: H, body: "{}"}).then(() => pollRerate()).catch(() => { $("progStop").disabled = false; });
  });
  $("progReload").addEventListener("click", () => { saveFilters(); location.reload(); });
  $("rerateBtn").setAttribute("aria-haspopup", "dialog"); $("rerateBtn").setAttribute("aria-expanded", "false");
  $("rerateBtn").addEventListener("click", rrOpen);
  pollRerate();
  $("updateBtn").addEventListener("click", () => {
    if (!confirm("Update job listings now?\n\nChecks every employer's job board for new and removed jobs, then Claude rates the new ones for each profile. Takes about 40 minutes.")) return;
    fetch("/api/update", {method: "POST", headers: H, body: "{}"}).then(() => { wasRunning = true; poll(); });
  });
  poll();
  // The settings page hands its Update / Re-rate / Add a person clicks to the board (sessionStorage "jb.run").
  try {
    const r = sessionStorage.getItem("jb.run"); sessionStorage.removeItem("jb.run");
    if (r === "update" || r === "rerate") setTimeout(() => $(r + "Btn").click(), 300);
    else if (r === "addPerson") { $("addPersonPanel").hidden = false; $("newPersonName").focus(); }
  } catch(e) {}
}
})();
</script>
"""

def build(payload, path, fragment=False):
    payload.setdefault("pivot_enabled", True)
    cur = payload.get("current") or CURRENT
    data = "<script>window.__DATA__=" + json.dumps(payload, separators=(",", ":")).replace("</", "<\\/") + \
           ";window.__CURRENT__=" + json.dumps(cur) + ";</script>\n"
    import appupdate
    body = HEAD + BODY + data + SCRIPT + appupdate.BANNER_SCRIPT
    if not fragment:
        body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
                HEAD + "</head><body>" + BODY + data + SCRIPT + appupdate.BANNER_SCRIPT + "</body></html>")
    import paths
    paths.write_atomic(path, body)  # temp file + replace: the server never serves a half-written board
