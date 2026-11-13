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
  /* type and radius scale: every size on these pages is one of these */
  --fs-xs:11px; --fs-sm:12.5px; --fs-md:14px; --fs-lg:16px; --fs-xl:20px; --fs-2xl:28px;
  --r:8px; --r-lg:12px; --r-pill:999px;
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
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:var(--fs-md);line-height:1.45;margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.wrap{max-width:1180px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 24px;padding-bottom:14px;border-bottom:1px solid var(--line)}
h1{font-size:var(--fs-xl);font-weight:700;margin:0;letter-spacing:-.01em;text-wrap:balance}
.sub{color:var(--muted);font-size:var(--fs-sm);margin-top:2px}
.stats{display:flex;gap:20px;flex-wrap:wrap}
.stat b{display:block;font-family:var(--mono);font-size:var(--fs-xl);font-weight:500;font-variant-numeric:tabular-nums}
.stat span{font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
nav.tabs{display:flex;gap:4px;margin:14px 0 0}
nav.tabs a{padding:7px 12px;border-radius:var(--r);color:var(--muted);text-decoration:none;font-weight:600}
nav.tabs a[aria-current="page"]{background:var(--accent-soft);color:var(--accent)}
.filters{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line)}
.filters input[type=search]{flex:1 1 220px;min-width:0}
input,select,button{font:inherit;color:var(--ink)}
input[type=search],select{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:6px 9px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:var(--r);overflow:hidden;background:var(--surface)}
.seg button{border:0;background:transparent;padding:6px 10px;cursor:pointer;color:var(--muted)}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--surface)}
label.chk{display:inline-flex;gap:6px;align-items:center;color:var(--muted);font-size:var(--fs-sm)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.count{color:var(--muted);font-size:var(--fs-sm);margin:10px 0}
ol.jobs{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.job{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;display:grid;grid-template-columns:58px minmax(0,1fr) 230px;gap:4px 16px;align-items:start}
.job.hidden-by-user{opacity:.45}
.scores{grid-row:span 2;display:flex;flex-direction:column;gap:6px}
.score.match{background:var(--bg);color:var(--ink);border:1px solid var(--line)}
.score.match.hi{background:var(--good-soft);color:var(--good);border-color:transparent}
.score.match.mid{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.score.match.lo{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.nocl{color:var(--muted);font-size:var(--fs-sm)}.nocl a,.acts .nocl a{color:var(--accent);font-weight:600;border:0!important;background:none!important;padding:0!important;min-height:0!important;display:inline!important}
.rsc .m.na{color:var(--muted);font-weight:400}
.rrno{font-size:var(--fs-md)}.rrno p{margin:0 0 8px}
.score{font-family:var(--mono);font-size:var(--fs-xl);font-weight:500;text-align:center;border-radius:var(--r);padding:6px 0;background:var(--accent-soft);color:var(--accent);font-variant-numeric:tabular-nums;cursor:help}
.score small{display:block;font-size:var(--fs-xs);letter-spacing:.05em;color:var(--muted)}
.title{font-weight:600;font-size:var(--fs-lg);color:var(--ink);text-decoration:none}
.title:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:var(--fs-sm);display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:2px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.chip{font-size:var(--fs-xs);padding:2px 7px;border-radius:var(--r-pill);background:var(--bg);border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.chip.remote{background:var(--good-soft);color:var(--good);border-color:transparent}
.chip.hybrid{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.chip.onsite{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.chip.poly{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.trv-heavy{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.trv-moderate,.chip.trv-some{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.chip.new{background:var(--new-soft);color:var(--new);border-color:transparent;font-weight:600}
.pay{grid-row:span 2;font-size:var(--fs-sm);color:var(--muted)}
.pay .amt{font-family:var(--mono);font-size:var(--fs-md);color:var(--ink);font-variant-numeric:tabular-nums}
.bar{position:relative;height:8px;background:var(--bar);border-radius:var(--r);margin:6px 0 3px}
.bar i{position:absolute;top:0;bottom:0;background:var(--bar-fill);border-radius:var(--r)}
.bar .mk{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink)}
.bar .mk.cur{background:var(--muted)}
.bar .mid{position:absolute;top:1px;width:6px;height:6px;margin-left:-3px;border-radius:50%;background:var(--bg);border:1.5px solid var(--ink)}
.bar.wide i{background:repeating-linear-gradient(135deg,var(--bar-fill) 0 4px,transparent 4px 7px)}
.pay .note{color:var(--warn)}
.axis{display:flex;justify-content:space-between;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted)}
.acts{display:flex;gap:6px;margin-top:8px}
.acts button{border:1px solid var(--line);background:var(--surface);border-radius:var(--r);padding:3px 8px;font-size:var(--fs-sm);cursor:pointer;color:var(--muted)}
.acts button[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.more2{grid-column:2 / 3;display:flex;flex-direction:column;gap:4px;min-width:0}
details.snip{font-size:var(--fs-sm);color:var(--muted)}
.coname{color:var(--ink);font-weight:600}
.meta .gd{font-weight:600;color:var(--ink)}
.meta .gd.hi{color:var(--good)}
.meta .gd.lo{color:var(--warn)}
details.copanel{font-size:var(--fs-sm);color:var(--muted)}
details.copanel summary{cursor:pointer;width:max-content}
details.copanel[open]{background:var(--bg);border:1px solid var(--line);border-radius:var(--r);padding:8px 10px}
details.copanel p{margin:6px 0;color:var(--ink);max-width:70ch}
details.copanel dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:3px 12px;margin:6px 0}
details.copanel dt{color:var(--muted)}
details.copanel dd{margin:0;color:var(--ink);min-width:0;overflow-wrap:anywhere}
details.copanel a{color:var(--accent)}
.asof{color:var(--muted);font-size:var(--fs-xs)}
.colinks{display:flex;gap:14px;flex-wrap:wrap;margin-top:4px}
details.snip summary{cursor:pointer;width:max-content}
details.snip p{margin:6px 0 0;max-width:70ch;white-space:pre-line}
.more{display:block;margin:14px auto;padding:8px 16px;border:1px solid var(--line);background:var(--surface);border-radius:var(--r);cursor:pointer}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);margin-top:14px}
table{border-collapse:collapse;width:100%;font-size:var(--fs-sm)}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
td.n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums}
td.err{color:var(--bad);white-space:normal;min-width:200px}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:var(--surface);border-radius:var(--r);padding:7px 12px;cursor:pointer;font-weight:600;color:var(--ink)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.btn:disabled{opacity:.6;cursor:default}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;margin-top:12px;display:flex;flex-direction:column;gap:8px}
.panel .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.panel input[type=password]{flex:1 1 260px;min-width:0;background:var(--bg);border:1px solid var(--line);border-radius:var(--r);padding:7px 9px}
.panel small,.panel .note{color:var(--muted);font-size:var(--fs-sm)}
.prog{height:6px;background:var(--bar);border-radius:var(--r);overflow:hidden}
.prog i{display:block;height:100%;background:var(--bar-fill);width:0;transition:width .4s}
.loglines{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);white-space:pre-wrap;max-height:9em;overflow:auto}
.why{font-size:var(--fs-sm);color:var(--ink);margin-top:6px;max-width:75ch}
.why b{font-weight:600;color:var(--accent)}
.banner{background:var(--warn-soft);color:var(--warn);border-radius:var(--r);padding:8px 12px;font-size:var(--fs-sm);margin-top:12px}
.clsteps{margin:8px 0 2px 20px;padding:0;color:var(--ink)}
.clsteps li{margin:6px 0}
.clrow{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:4px}
.clrow input{flex:1 1 220px;min-width:0;height:var(--h);border:1px solid var(--line);border-radius:var(--r);padding:0 10px;background:var(--surface);color:var(--ink);font:inherit}
.clmsg{display:block;margin-top:4px;color:var(--bad)}
.clok{color:var(--good)}
.drop{border:1.5px dashed var(--line);border-radius:var(--r);padding:16px;text-align:center;color:var(--muted);cursor:pointer}
.drop.over{border-color:var(--accent);background:var(--accent-soft);color:var(--accent)}
.panel textarea{width:100%;min-height:5.5em;background:var(--bg);border:1px solid var(--line);border-radius:var(--r);padding:7px 9px;font:inherit;resize:vertical}
.panel .help{font-size:var(--fs-sm);color:var(--muted);margin:0 0 4px}
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
.pv .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;min-width:0}
.pv h3{margin:0 0 4px;font-size:var(--fs-md)}
.pv .help{font-size:var(--fs-sm);color:var(--muted);margin:0 0 8px}
.pvcounts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.pvcounts button{text-align:left;border:1px solid var(--line);background:var(--bg);border-radius:var(--r);padding:8px 10px;cursor:pointer;color:var(--ink)}
.pvcounts b{display:block;font-family:var(--mono);font-size:var(--fs-xl);font-variant-numeric:tabular-nums}
.pvcounts span{font-size:var(--fs-sm);color:var(--muted)}
.gaprow{display:grid;grid-template-columns:minmax(0,11rem) minmax(0,1fr) 2.5rem;gap:8px;align-items:center;font-size:var(--fs-sm);padding:3px 0;border:0;background:none;width:100%;text-align:left;cursor:pointer;color:var(--ink)}
.gaprow[aria-pressed="true"]{font-weight:700}
.gaprow i{display:block;height:8px;border-radius:var(--r);background:var(--bar-fill)}
.gaprow em{font-style:normal;font-family:var(--mono);color:var(--muted);text-align:right}
.tl{font-size:var(--fs-sm);color:var(--muted);margin-top:3px;max-width:75ch}
.legend{color:var(--muted);font-size:var(--fs-sm);max-width:75ch;margin:14px 0 0}
dialog.sheet{border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);color:var(--ink);padding:0;width:min(640px,calc(100vw - 24px));max-height:calc(100dvh - 24px)}
dialog.sheet::backdrop{background:rgba(0,0,0,.45)}
.sheet form{display:flex;flex-direction:column;max-height:calc(100dvh - 26px)}
.sheet .qhead{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line)}
.sheet .qbody{overflow:auto;padding:4px 14px 12px;display:flex;flex-direction:column}
.sheet .qfoot{display:flex;gap:8px;flex-wrap:wrap;padding:10px 14px;border-top:1px solid var(--line)}
.q{display:flex;flex-direction:column;gap:6px;padding:12px 0;border-bottom:1px solid var(--line)}
.q:last-child{border-bottom:0}
.q .qreq{font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:.06em;color:var(--accent);font-weight:600}
.q .qtext{font-weight:600;font-size:var(--fs-md)}
.q .qwhy{font-size:var(--fs-sm);color:var(--muted)}
.q textarea{width:100%;min-height:4.2em;background:var(--bg);border:1px solid var(--line);border-radius:var(--r);padding:7px 9px;font:inherit;color:var(--ink);resize:vertical}
.ans{display:flex;gap:6px}
.ans button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:var(--r-pill);padding:4px 12px;font-size:var(--fs-sm);cursor:pointer}
.ans button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.qwait{padding:24px 0;color:var(--muted)}
.psgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:8px 12px;margin:8px 0}
.psgrid label{display:flex;flex-direction:column;gap:3px;font-size:var(--fs-sm);color:var(--muted)}
.psgrid label.chk{flex-direction:row;align-items:center}
.psgrid input[type=text],.psgrid input[type=number],.psgrid select,.psgrid textarea,#newPersonName{background:var(--bg);border:1px solid var(--line);border-radius:var(--r);padding:7px 9px;font:inherit;color:var(--ink);min-width:0}
#newPersonName{flex:1 1 200px}
.countrow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.factlist{display:flex;flex-direction:column;gap:6px;font-size:var(--fs-sm)}
.fact{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:start;padding:6px 0;border-top:1px solid var(--line)}
.linkbtn{border:0;background:none;color:var(--accent);font:inherit;font-size:var(--fs-sm);cursor:pointer;padding:0 2px}
.fact .pol{color:var(--ink);font-size:var(--fs-sm);margin-top:2px;padding-left:8px;border-left:2px solid var(--accent-soft)}
.fact .fl{color:var(--muted);font-size:var(--fs-sm)}
.fact button{border:1px solid var(--line);background:var(--surface);color:var(--muted);border-radius:var(--r);padding:2px 8px;font-size:var(--fs-sm);cursor:pointer}
@media (max-width:760px){
  .job{grid-template-columns:52px minmax(0,1fr)}
  .scores{grid-row:auto}
  .pay{grid-column:1 / -1;grid-row:auto}
  .more2{grid-column:1 / -1}
}

/* ---- v2: one control system. Every control is --h tall, --r rounded; spacing on a 4/8/12/16 scale. */
:root{--h:36px;--h-sm:28px}
header.top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 16px;padding-bottom:12px;border-bottom:0}
.brand{min-width:0}
h1{font-size:var(--fs-xl)}
.sub{font-size:var(--fs-sm)}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn,input[type=search],select,.seg,#personSel{height:var(--h);border-radius:var(--r);font-size:var(--fs-md)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:0 14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-weight:600;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--muted)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.btn.ghost{background:transparent;border-color:transparent;color:var(--accent)}
.btn.ghost:hover{background:var(--accent-soft)}
.btn.sm{height:var(--h-sm);padding:0 10px;font-size:var(--fs-sm)}
input[type=search],select,#personSel{background:var(--surface);border:1px solid var(--line);padding:0 10px;color:var(--ink)}
select{padding-right:28px}
#personSel{font-weight:600;max-width:12rem}
.seg{display:inline-flex;align-items:stretch;padding:2px;gap:2px;border:1px solid var(--line);background:var(--surface)}
.seg button{border:0;border-radius:var(--r);padding:0 10px;background:transparent;color:var(--muted);font-weight:500}
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
.nlbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;padding:7px 10px;border-radius:var(--r);background:var(--accent-soft);color:var(--ink);font-size:var(--fs-sm)}
.nlbar b{color:var(--accent);font-weight:600}
.nlbar .nlterms{color:var(--muted);font-size:var(--fs-sm);flex-basis:100%}
.nlbar.err{background:var(--bad-soft);color:var(--bad)}
.nlbar .spin{width:12px;height:12px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:nlspin .8s linear infinite}
@keyframes nlspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.nlbar .spin{animation:none}}
.badge{display:inline-grid;place-items:center;min-width:18px;height:18px;padding:0 5px;border-radius:var(--r-pill);background:var(--accent);color:var(--surface);font-size:var(--fs-xs);font-weight:700}
.fpanel{margin-top:10px;padding:12px;border:1px solid var(--line);border-radius:var(--r);background:var(--surface);display:flex;flex-direction:column;gap:12px}
.btn.icon{width:var(--h);padding:0}
.field input[type=number]{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;width:100%}
.fgroup{font-size:var(--fs-sm);font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink);border-top:1px solid var(--line);padding-top:10px}
.fgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,200px),1fr));gap:12px}
.fgroup.first{border-top:0;padding-top:0}
.fhint{margin:-6px 0 0;font-size:var(--fs-sm);color:var(--muted)}
.fhint:empty{display:none}
.fhint.err{color:var(--bad)}
.field input[type=text]{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 10px;font:inherit;width:100%;min-width:0}
.filters:has(.fpanel:not([hidden])){position:static}
.field{display:flex;flex-direction:column;gap:4px;min-width:0}
.field select{width:100%}
.flabel{font-size:var(--fs-xs);font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.checks{display:flex;flex-wrap:wrap;gap:4px 12px;min-height:var(--h);align-items:center}
.fchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.fchips:empty{display:none}
.fchip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 6px 0 10px;border-radius:var(--r-pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:var(--fs-sm);cursor:pointer}
.fchip span{color:var(--muted);font-size:var(--fs-lg);line-height:1}
.fchip:hover{border-color:var(--muted)}
.countrow{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin:8px 0}
.count{margin:0}
.pvbar{display:flex;flex-direction:column;gap:8px;margin-top:10px}
.pvbar .pvcounts{display:flex;flex-wrap:wrap;gap:6px}
.pvbar .pvcounts button{height:var(--h-sm);display:inline-flex;align-items:center;gap:6px;padding:0 12px;border-radius:var(--r-pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:var(--fs-sm);cursor:pointer;text-align:left}
.pvbar .pvcounts button b{font-family:var(--mono);font-size:var(--fs-sm);display:inline}
.pvbar .pvcounts button[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.pvgaps summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:var(--fs-sm);width:max-content}
.pvgaps[open]{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:10px 12px}
.panel{border-radius:var(--r);gap:10px}
.panel h2.sec{font-size:var(--fs-sm);font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:6px 0 0}
.acts{flex-wrap:wrap}
.acts a{display:inline-flex;align-items:center;height:var(--h-sm);padding:0 8px;border:1px solid var(--line);border-radius:var(--r);background:var(--surface);color:var(--muted);font-size:var(--fs-sm);text-decoration:none;white-space:nowrap}
.acts button.danger{margin-left:auto;color:var(--bad);border-color:var(--bad);background:var(--bad-soft)}
.acts button.danger[data-armed="1"]{background:var(--bad-soft);border-color:var(--bad)}
.acts a.pri,.acts button.pri{background:var(--accent);border-color:var(--accent);color:var(--surface);font-weight:600}
.tl2{font-size:var(--fs-sm);color:var(--muted);margin-top:4px;max-width:75ch}
.job.tlcard{grid-template-columns:58px minmax(0,1fr)}
.tlwork{display:inline-flex;align-items:center;gap:6px;font-weight:600;color:var(--accent)}
.tlwork .spin{width:11px;height:11px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:nlspin .8s linear infinite}
.tlfail{color:var(--bad);font-size:var(--fs-sm);margin-top:4px;max-width:75ch;overflow-wrap:anywhere}
.tlwarn{font-size:var(--fs-sm);margin-top:6px;max-width:75ch;overflow-wrap:anywhere;border-left:3px solid var(--warn);padding:2px 0 2px 10px}
.tlwarn ul{margin:3px 0 0;padding-left:16px}.tlwarn li{margin:1px 0}.tlwarn span{color:var(--muted)}
.tlcard.working .scores,.tlcard.failed .scores{display:grid;place-items:center}
.tlcard .tlicon{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent);font-weight:700}
.tlcard.failed .tlicon{background:var(--bad-soft);color:var(--bad)}
@media (prefers-reduced-motion:reduce){.tlwork .spin{animation:none}}
.acts button{height:var(--h-sm);border-radius:var(--r);white-space:nowrap}
@media (max-width:640px){
  .wrap{padding-block:12px 40px}
  header.top{gap:8px}
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
.fresh{color:var(--muted);font-size:var(--fs-sm)}
.avatarBtn{display:inline-flex;align-items:center;gap:8px;height:var(--h);border:1px solid var(--line);background:var(--surface);border-radius:var(--r-pill);padding:0 12px 0 4px;font-weight:600;cursor:pointer;color:var(--ink)}
.avatarBtn .av{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent);font-size:var(--fs-sm)}
.menuWrap{position:relative}
.iconBtn{position:relative;width:var(--h);height:var(--h);display:inline-grid;place-items:center;border:1px solid var(--line);background:var(--surface);border-radius:50%;color:var(--ink);cursor:pointer;padding:0}
.iconBtn:hover{background:var(--bg)}
.iconBtn[aria-expanded="true"],.iconBtn[aria-current="page"]{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
a.iconBtn{text-decoration:none}
.iconBtn:disabled{opacity:.55;cursor:default}
.iconBtn svg{width:18px;height:18px}
.iconBtn.busy svg{animation:nlspin 1.4s linear infinite}
@media (prefers-reduced-motion:reduce){.iconBtn.busy svg{animation:none}}
.rrbadge{position:absolute;top:-4px;right:-6px;min-width:18px;height:18px;padding:0 5px;border-radius:var(--r-pill);background:var(--accent);color:var(--surface);font-size:var(--fs-xs);font-weight:700;display:grid;place-items:center}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.amenu{position:absolute;right:0;top:calc(var(--h) + 6px);width:270px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:0 10px 30px rgba(0,0,0,.18);padding:6px;z-index:40}
.amenu .who{padding:8px 10px;color:var(--muted);font-size:var(--fs-sm)}
.amenu button{display:flex;width:100%;align-items:center;justify-content:space-between;gap:10px;border:0;background:none;padding:9px 10px;border-radius:var(--r);text-align:left;cursor:pointer;color:var(--ink);font-size:var(--fs-md);height:auto;font-weight:500}
.amenu button:hover{background:var(--bg)}
.amenu button[aria-current="true"]{font-weight:700}
.amenu button[aria-current="true"]::after{content:"✓";color:var(--accent)}
.amenu small{color:var(--muted);font-weight:400}
/* Rate jobs panel: a popover under the Rate jobs button that opened it; a bottom sheet on phones */
.rrpop{position:fixed;z-index:45;width:min(440px,calc(100vw - 16px));max-height:calc(100vh - 80px);overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:0 10px 30px rgba(0,0,0,.18);padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.rrpop .rrhead{display:flex;justify-content:space-between;align-items:center;gap:8px}
.rrpop .rrhead strong{font-size:var(--fs-lg)}
.rrrow{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;border-top:1px solid var(--line);padding-top:10px}
.rrrow.rec{border:1px solid var(--accent);background:var(--accent-soft);border-radius:var(--r);padding:10px}
.rrtxt{display:flex;flex-direction:column;gap:4px;min-width:0;font-size:var(--fs-sm)}
.rrtxt small,.rrfoot small{color:var(--muted);font-size:var(--fs-sm)}
.rrtag{display:inline-block;margin-left:6px;font-size:var(--fs-xs);font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.04em}
.rrtxt input[type=number]{width:72px;height:var(--h-sm);border:1px solid var(--line);border-radius:var(--r);background:var(--bg);color:var(--ink);padding:0 6px;font:inherit}
.rrtxt input[type=number][aria-invalid="true"]{border-color:var(--bad)}
.rrhint{color:var(--warn)!important}
.rrfoot{display:flex;flex-direction:column;gap:4px;border-top:1px solid var(--line);padding-top:10px}
.rrmsg{color:var(--accent)!important;font-weight:600}
.rrmsg.bad{color:var(--bad)!important}
@media (max-width:640px){.rrpop{left:0!important;right:0!important;top:auto!important;bottom:0;width:auto;max-height:85vh;border-radius:var(--r-lg) var(--r-lg) 0 0;padding-bottom:max(14px,env(safe-area-inset-bottom,0px))}}
.banner.gsbn{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:var(--accent-soft);color:var(--ink)}
.banner.gsbn span{flex:1 1 220px}
.updbn .updnotes{flex:1 1 100%;white-space:pre-wrap;word-break:break-word;max-height:260px;overflow:auto;margin:4px 0 0;padding:8px 10px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);font-size:var(--fs-sm);line-height:1.45}
.updbn .updsteps,.updbn .updmsg{flex:1 1 100%;font-size:var(--fs-sm)}
.updbn .updsteps ol{margin:4px 0 0 18px;padding:0}
.updbn .updmsg:empty{display:none}
nav.tabs a .n{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin-left:4px;font-weight:500}
.quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.qc{height:30px;border:1px solid var(--line);background:var(--surface);border-radius:var(--r-pill);padding:0 12px;font-size:var(--fs-sm);color:var(--muted);cursor:pointer;white-space:nowrap}
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
.rco{color:var(--muted);font-size:var(--fs-sm);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rmeta{grid-column:1/-1;display:flex;gap:6px 10px;flex-wrap:wrap;align-items:center;font-size:var(--fs-sm);color:var(--muted);margin-top:3px}
.rmeta .amt{font-family:var(--mono);color:var(--ink);font-size:var(--fs-sm)}
.rsc{grid-row:1/3;grid-column:2;display:flex;gap:4px}
.rsc div{text-align:center;min-width:40px}
.rsc b{display:block;font:500 var(--fs-lg)/1.15 var(--mono)}
.rsc b.m{color:var(--muted);font-size:var(--fs-lg)}
.rsc b.m.hi{color:var(--good)}
.rsc b.rv{color:var(--muted);font-size:var(--fs-lg)}
.rsc b.rv.hi{color:var(--ink)}
.rsc small{font-size:var(--fs-xs);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.vpill{font-size:var(--fs-xs);font-weight:600;padding:1px 8px;border-radius:var(--r-pill);white-space:nowrap;background:var(--bg);color:var(--muted)}
.vpill.v-apply_now,.vpill.v-after_prep{background:var(--good-soft);color:var(--good)}
.vpill.v-tailor{background:var(--accent-soft);color:var(--accent)}
.vpill.v-stretch,.vpill.v-long_shot{background:var(--warn-soft);color:var(--warn)}
.vpill.v-skip{background:var(--bad-soft);color:var(--bad)}
.ndot{width:7px;height:7px;border-radius:50%;background:var(--new);display:inline-block;margin-right:6px;vertical-align:1px}
.racts{position:absolute;right:10px;bottom:8px;display:none;gap:4px}
.jrow:hover .racts{display:flex}
.racts button{width:30px;height:26px;border:1px solid var(--line);background:var(--surface);border-radius:var(--r);cursor:pointer;color:var(--muted);font-size:var(--fs-sm);padding:0}
.racts button[aria-pressed="true"]{color:var(--accent);border-color:var(--accent)}
.detail{position:sticky;top:calc(env(safe-area-inset-top,0px) + var(--fbar,0px) + 12px);max-height:calc(100dvh - env(safe-area-inset-top,0px) - var(--fbar,0px) - 24px);overflow-y:auto;overscroll-behavior:contain;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);min-width:0}
.dpane{padding:20px 22px 28px;display:flex;flex-direction:column;gap:18px}
.dback{display:none;align-self:flex-start;border:0;background:none;color:var(--accent);font-weight:600;padding:0;cursor:pointer;font-size:var(--fs-lg)}
.dtitle{font-size:var(--fs-xl);font-weight:700;line-height:1.2;margin:0;text-wrap:balance}
.dco{display:flex;flex-wrap:wrap;gap:4px 10px;color:var(--muted);font-size:var(--fs-md);margin-top:6px;align-items:center}
.dco .coname{color:var(--ink)}
.dacts{display:flex;gap:8px;flex-wrap:wrap}
.dacts .btn[aria-pressed="true"]{border-color:var(--accent);color:var(--accent)}
.dsec{border-top:1px solid var(--line);padding-top:14px}
.dsec>h3{margin:0 0 10px;font-size:var(--fs-xs);letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:700}
.dscores{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.dsc{display:flex;gap:12px;align-items:center}
.ring{--p:0;width:54px;height:54px;border-radius:50%;flex:none;display:grid;place-items:center;background:conic-gradient(var(--accent) calc(var(--p)*1%),var(--bar) 0)}
.ring b{width:42px;height:42px;border-radius:50%;background:var(--surface);display:grid;place-items:center;font:500 var(--fs-lg) var(--mono)}
.dsc p{margin:0;font-size:var(--fs-sm);color:var(--muted)}
.dsc strong{display:block;color:var(--ink);font-size:var(--fs-md)}
.dread p{margin:0 0 10px;max-width:70ch}
.dread .lab{display:block;font-weight:600;color:var(--ink);margin-bottom:1px}
.dsec .pay{grid-row:auto;font-size:var(--fs-sm)}
.dsec details.copanel summary{display:none}
.dsec details.copanel{background:none;border:0;padding:0}
.dsec .snipp{white-space:pre-line;color:var(--muted);font-size:var(--fs-md);max-width:75ch;margin:0}
.dempty{padding:48px 24px;text-align:center;color:var(--muted)}
.dempty b{display:block;color:var(--ink);font-size:var(--fs-lg);margin-bottom:4px}
/* Empty Jobs tab: Start your job search / running / nothing passed your filters (first_search.py via /api/search) */
.startcard{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:var(--r);padding:18px 20px;margin:12px 0;display:flex;flex-direction:column;gap:10px}
.startcard h2{margin:0;font-size:var(--fs-xl);letter-spacing:-.01em;color:var(--ink)}
.startcard p{margin:0;color:var(--muted);max-width:70ch;font-size:var(--fs-md)}
.startcard .sacts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.startcard .sacts .btn{text-decoration:none}
.startcard ul{margin:0;padding-left:18px;color:var(--muted);font-size:var(--fs-md);display:flex;flex-direction:column;gap:4px}
.startcard .chk{font-size:var(--fs-md);color:var(--ink)}
.startcard .smsg{font-size:var(--fs-sm);color:var(--bad)}
.startcard .smsg:empty{display:none}
.startcard .dmsg{color:var(--ink)}
.startcard ul .linkbtn{font-size:inherit;padding:0;text-align:left}
.startcard .linkbtn{font-size:inherit}
.dchoose{display:inline-flex;flex-wrap:wrap;gap:6px 10px;align-items:center;max-width:100%}
.dchoose select{max-width:100%;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:var(--r);padding:5px 8px;font:inherit;font-size:var(--fs-sm)}
.dchoose .dest{font-size:var(--fs-sm);color:var(--muted)}
.field #coFind{margin-bottom:4px}
#view-jobs.nojobs #list .dempty,#view-jobs.nojobs .countrow,#view-jobs.nojobs .split .detail{display:none}
.reqbox{display:flex;flex-direction:column;gap:8px}
.reqbox .chip{white-space:normal}
.chip.req-unmet{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.chip.req-flag{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.reqwhy{font-size:var(--fs-sm);color:var(--muted);max-width:75ch}
.rmeta .rq{color:var(--warn);font-weight:600}
.rmeta .old,.dco .old{color:var(--muted);border:1px dashed var(--line);border-radius:var(--r-pill);padding:0 7px;font-size:var(--fs-xs)}
.tierdot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-left:3px;vertical-align:1px;background:var(--muted)}
.tierdot.t-haiku{background:transparent;border:1px solid var(--muted)}
.tiertag{font-size:var(--fs-xs);color:var(--muted)}
.ratefresh{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:var(--fs-sm);color:var(--muted)}
.rmeta .rq.un{color:var(--bad)}
.hlcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:10px}
.hlcard{border:1px solid var(--line);border-radius:var(--r);padding:10px 12px;background:var(--bg);min-width:0}
.hlcard .k{font-size:var(--fs-xs);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700;display:flex;justify-content:space-between;gap:6px}
.hlcard .k em{font-style:normal;color:var(--accent);text-transform:none;letter-spacing:0;font-weight:600}
.hlcard .v{margin-top:4px;font-size:var(--fs-md)}
.hlcard .v div+div{margin-top:3px}
.hlbanner{background:var(--accent-soft);color:var(--ink);border-radius:var(--r);padding:10px 12px;font-size:var(--fs-sm);display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between}
.hledit{display:flex;flex-direction:column;gap:8px}
.hlrow{display:grid;grid-template-columns:130px minmax(0,1fr) minmax(0,1fr) auto;gap:6px;align-items:center}
.hlrow.lic{grid-template-columns:minmax(0,1fr) 130px auto}
.hledit input,.hledit select{height:var(--h);border-radius:var(--r);border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 8px;font:inherit;min-width:0}
@media (max-width:640px){.hlrow,.hlrow.lic{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
details.howto{margin-top:16px;color:var(--muted);font-size:var(--fs-sm)}
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
/* ---- v4: one header for every page (text navigation, Find new jobs, the person menu; a bottom tab bar on phones),
   one dialog, one danger style, one way to show a score, and touch-sized controls on touch screens. */
header.top{flex-wrap:wrap;align-items:center;gap:10px 12px}
header.top .tools{display:contents}
header.top .brandline{order:1;flex:1 1 auto;min-width:0;flex-wrap:nowrap}
header.top .brandline h1{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:0 1 auto}
header.top .brandline .fresh{flex:0 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.countrow{justify-content:flex-start;gap:8px 14px}
.mainnav{order:2;display:flex;gap:2px;align-items:center}
.mainnav a{position:relative;display:inline-flex;align-items:center;height:var(--h);padding:0 10px;border-radius:var(--r);color:var(--muted);font-weight:600;text-decoration:none;white-space:nowrap}
.mainnav a:hover{color:var(--ink);background:var(--surface)}
.mainnav a[aria-current="page"]{color:var(--accent);background:var(--accent-soft)}
.mainnav .rrbadge{position:static;margin-left:6px}
header.top #rerateBtn{order:3}
header.top .findBtn{order:4}
header.top .menuWrap{order:5}
.findBtn svg{width:16px;height:16px;flex:none}
.findBtn.busy svg{animation:nlspin 1.4s linear infinite}
.findBtn:disabled{opacity:.75}
@media (prefers-reduced-motion:reduce){.findBtn.busy svg{animation:none}}
.amenu .amsep{height:1px;background:var(--line);margin:6px 4px}
.amenu a{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 10px;border-radius:var(--r);color:var(--ink);text-decoration:none;font-size:var(--fs-md);font-weight:500}
.amenu a:hover{background:var(--bg)}
.amenu #themeBtn small,.moresheet small{color:var(--muted);font-weight:400}
.tabbar,.moresheet{display:none}
nav.tabs .tabext{margin-left:auto;color:var(--accent);font-weight:600}
@media (max-width:899px){
  .mainnav{order:10;flex:1 1 100%;overflow-x:auto;scrollbar-width:none;margin:-4px 0 0 -10px}
  .mainnav::-webkit-scrollbar{display:none}
}
@media (max-width:720px){
  header.top{gap:8px;padding-bottom:8px}
  .mainnav,header.top #rerateBtn{display:none}
  #avName{display:none}
  .avatarBtn{padding:0 4px}
  .tabbar{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:25;background:var(--surface);border-top:1px solid var(--line);padding:0 env(safe-area-inset-right,0px) env(safe-area-inset-bottom,0px) env(safe-area-inset-left,0px)}
  .tabbar a,.tabbar button{flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;height:56px;border:0;background:none;padding:0;color:var(--muted);font:inherit;font-size:var(--fs-xs);font-weight:600;text-decoration:none;cursor:pointer}
  .tabbar svg{width:22px;height:22px}
  .tabbar [aria-current="page"],.tabbar [aria-expanded="true"]{color:var(--accent)}
  body{padding-bottom:calc(56px + env(safe-area-inset-bottom,0px))}
  .moresheet:not([hidden]){display:flex;flex-direction:column;gap:2px;position:fixed;left:0;right:0;bottom:calc(56px + env(safe-area-inset-bottom,0px));z-index:26;background:var(--surface);border:1px solid var(--line);border-bottom:0;border-radius:var(--r-lg) var(--r-lg) 0 0;box-shadow:0 -8px 24px rgba(0,0,0,.16);padding:8px}
  .moresheet a,.moresheet button{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:44px;width:100%;padding:0 12px;border:0;background:none;border-radius:var(--r);color:var(--ink);font:inherit;font-size:var(--fs-md);font-weight:500;text-decoration:none;text-align:left;cursor:pointer}
  .moresheet [aria-current="page"]{color:var(--accent);font-weight:700}
  nav.tabs{display:none}
}
@media (max-width:480px){.fl-new{display:none}header.top .findBtn{padding:0 12px}}
/* the app's own dialog (appConfirm) and the destructive / strong button styles every page uses */
dialog.appdlg{border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);color:var(--ink);padding:20px;width:min(440px,calc(100vw - 32px))}
dialog.appdlg::backdrop{background:rgba(0,0,0,.45)}
.btn.danger{background:var(--bad-soft);border-color:var(--bad);color:var(--bad)}
.btn.danger:hover{border-color:var(--bad)}
.btn.strong{border-color:var(--accent);color:var(--accent)}
.btn.quiet{background:transparent;border-color:transparent;color:var(--muted);font-weight:500}
.btn.quiet:hover{background:var(--bg);border-color:var(--line);color:var(--ink)}
.btn.quiet[aria-pressed="true"]{color:var(--accent);background:var(--accent-soft);border-color:transparent}
.acts a.danger,.acts button.danger{color:var(--bad)}
/* notices: one at a time; the rest behind "N more notices" (stackBanners) */
.banner.stk{display:none}
.bnmore{margin-top:6px;font-size:var(--fs-sm)}
.bnmore .linkbtn{font-size:var(--fs-sm);font-weight:600}
/* Filters: the saved search is its own tinted card; "Narrow the list" is the plain part below it */
.mscard{background:var(--accent-soft);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:var(--r);padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.mshead{display:flex;gap:8px 12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.mshead h3{margin:0;font-size:var(--fs-md);font-weight:700;color:var(--ink)}
.mssub{margin:2px 0 0;color:var(--muted);font-size:var(--fs-sm)}
.mssum{margin:0;font-weight:600;color:var(--ink);overflow-wrap:anywhere}
.msedit summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:var(--fs-sm);width:max-content}
.msedit[open] .msgrid{margin-top:10px}
.mscard .field input,.mscard .field select{background:var(--surface)}
.mscard .fhint{margin:0}
.fgsub{text-transform:none;letter-spacing:0;font-weight:500;color:var(--muted)}
/* the count line: "186 jobs · 5 hidden" with the reasons behind it, and Rate jobs */
.count .hidn{display:inline-block;vertical-align:top}
.count .hidn summary{cursor:pointer;color:var(--accent);font-weight:600;list-style:none;display:inline-flex;align-items:center;gap:4px}
.count .hidn summary::-webkit-details-marker{display:none}
.count .hidn summary::after{content:"▾";font-size:var(--fs-xs)}
.count .hidn[open] summary::after{content:"▴"}
.count .hidn ul{margin:6px 0 2px;padding:8px 12px;list-style:none;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);display:flex;flex-direction:column;gap:4px;color:var(--ink);max-width:min(560px,calc(100vw - 32px))}
.count .hidn li{display:flex;gap:8px;align-items:baseline;justify-content:space-between;flex-wrap:wrap}
.countrow .note{font-size:var(--fs-sm)}
#rateMore .n{font-family:var(--mono);font-weight:500;color:var(--accent)}
/* scores: the same number-over-label treatment in the list, the details pane and the Resumes tab */
.rsc.big{gap:14px}
.rsc.big div{min-width:56px}
.rsc.big b{font-size:var(--fs-xl)}
.dscores{display:flex;flex-direction:column;gap:10px}
.dsc{display:grid;grid-template-columns:64px minmax(0,1fr);gap:12px;align-items:start}
.dsc .sv{text-align:center}
.dsc .sv b{display:block;font:500 var(--fs-xl)/1.1 var(--mono);color:var(--ink)}
.dsc .sv b.m.hi{color:var(--good)}
.dsc .sv b.na{color:var(--muted)}
.dsc .sv small{font-size:var(--fs-xs);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.dsc details.subw summary{cursor:pointer;color:var(--accent);font-weight:600;width:max-content}
.dsc details.subw div{margin-top:4px;color:var(--ink)}
.job.tlcard .scores.rsc{grid-row:1 / span 2;grid-column:1;flex-direction:column;gap:8px}
/* details pane actions: one primary, View posting as the strong second, Save / Applied / Not for me lighter */
.dacts{align-items:center}
.dmarks{display:flex;gap:4px;flex-wrap:wrap;margin-top:-8px}
.nocl.once{display:block;margin-top:6px}
.rrmain{display:flex;flex-direction:column;gap:8px;align-items:flex-start}
.rrmain .rrsum{margin:0;font-size:var(--fs-md)}
.rrmain small{color:var(--muted);font-size:var(--fs-sm)}
.rrmore summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:var(--fs-sm);width:max-content}
.rrmore[open]{display:flex;flex-direction:column;gap:10px}
.rrlim{color:var(--muted);font-size:var(--fs-sm)}
#view-jobs.nojobs .filters,#view-jobs.nojobs .howto,#view-jobs.nojobs .pvbar{display:none}
@media (max-width:640px){
  .frow{flex-wrap:nowrap}
  .frow input[type=search]{flex:1 1 auto}
  .frow select{flex:0 1 auto;max-width:38%;min-width:0;text-overflow:ellipsis}
  #filtersBtn .fbl{display:none}
  #filtersBtn{flex:none;padding:0 10px}
  .quick,.fchips{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;margin-left:-16px;margin-right:-16px;padding:0 16px}
  .quick::-webkit-scrollbar,.fchips::-webkit-scrollbar{display:none}
  .qc,.fchip{flex:none}
  .countrow{flex-wrap:nowrap;align-items:flex-start}
  .countrow #rateMore{flex:none}
}
#filtersBtn svg{width:16px;height:16px}
/* touch screens: controls at least 32px tall, action buttons 36px */
@media (pointer:coarse){
  :root{--h-sm:32px}
  .qc,.fchip{height:32px}
  .acts a,.acts button,.dacts .btn,.dmarks .btn{min-height:36px;height:auto}
  .count .linkbtn,.bnmore .linkbtn,.hidn summary{min-height:32px;display:inline-flex;align-items:center}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
"""

# ---- shared by every page -------------------------------------------------------------------------------------------
# DOWN_SCRIPT: the "Siftwell isn't running" notice for pages other than the board (Settings, Employers, setup): the
# page asks the server now and then; three misses in a row and it says so, in the same words as the board.
DOWN_SCRIPT = """<script>(function(){
  var fails = 0, bar = null;
  function show(){
    if (bar) return;
    bar = document.createElement("div"); bar.id = "srvDown"; bar.setAttribute("role", "alert");
    bar.style.cssText = "position:sticky;top:0;z-index:60;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;padding:10px 16px;background:var(--warn-soft,#fff4d6);color:var(--text,#1b1b1b);border-bottom:1px solid var(--line,#d9d9d9);font-size:14px;line-height:1.4";
    bar.innerHTML = "<span><b>Siftwell isn\\u2019t running.</b> This page can\\u2019t reach it, so nothing here is being updated and the buttons won\\u2019t work. Open Siftwell again, then reload this page.</span>";
    var b = document.createElement("button"); b.className = "btn sm"; b.type = "button"; b.textContent = "Reload";
    b.addEventListener("click", function(){ location.reload(); }); bar.appendChild(b);
    document.body.insertBefore(bar, document.body.firstChild);
  }
  function hide(){ if (bar) { bar.remove(); bar = null; } }
  function tick(){
    fetch("/api/people", {cache: "no-store"}).then(function(){ fails = 0; hide(); }, function(){ if (++fails >= 3) show(); })
      .then(function(){ setTimeout(tick, fails ? 5000 : 20000); });
  }
  if (location.protocol.indexOf("http") === 0) setTimeout(tick, 15000);
})();</script>
"""
# CONFIRM_JS / CONFIRM_SCRIPT: the ONE confirmation pattern. window.appConfirm({title, text, ok, danger}) -> Promise<bool>
# asks a yes/no question in the app's own dialog, never the browser's confirm box. text may hold paragraphs split by
# "\n\n"; ok is the confirm button's words ("Remove them"); danger: true draws it as a destructive action (.btn.danger)
# and puts the focus on Cancel. The older call appConfirm("Title\n\nText", "OK words") still works. Every page with the
# shared header (TOOLS) has it; a page without the header includes CONFIRM_SCRIPT.
CONFIRM_JS = r"""window.appConfirm = function(o, okLabel){
  if (!o || typeof o !== "object") { var parts = String(o == null ? "" : o).split("\n\n"); o = {title: parts[0], text: parts.slice(1).join("\n\n"), ok: okLabel}; }
  return new Promise(function(resolve){
    var d = document.createElement("dialog"); d.className = "appdlg"; d.setAttribute("aria-labelledby", "appDlgT");
    d.style.cssText = "border:1px solid var(--line,#d9d9d9);border-radius:12px;padding:20px;background:var(--surface,#fff);color:var(--ink,#1b1b1b);width:min(440px,calc(100vw - 32px))";
    var h = document.createElement("h2"); h.id = "appDlgT"; h.style.cssText = "margin:0 0 8px;font-size:16px;font-weight:700"; h.textContent = o.title || "Are you sure?"; d.appendChild(h);
    String(o.text || "").split("\n\n").filter(Boolean).forEach(function(t){ var p = document.createElement("p"); p.style.cssText = "margin:0 0 8px;color:var(--muted,#555)"; p.textContent = t; d.appendChild(p); });
    var row = document.createElement("div"); row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:16px";
    var no = document.createElement("button"); no.type = "button"; no.className = "btn"; no.textContent = o.cancel || "Cancel";
    var yes = document.createElement("button"); yes.type = "button"; yes.className = "btn " + (o.danger ? "danger" : "primary"); yes.textContent = o.ok || "OK";
    row.appendChild(no); row.appendChild(yes); d.appendChild(row); document.body.appendChild(d);
    var back = document.activeElement;
    var done = function(v){ try { d.close(); } catch(e) {} d.remove(); try { if (back && back.focus) back.focus(); } catch(e) {} resolve(v); };
    no.addEventListener("click", function(){ done(false); }); yes.addEventListener("click", function(){ done(true); });
    d.addEventListener("cancel", function(e){ e.preventDefault(); done(false); });
    d.addEventListener("click", function(e){ if (e.target === d) { var r = d.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) done(false); } });
    if (!d.showModal) { d.remove(); resolve(false); return; }
    d.showModal(); (o.danger ? no : yes).focus();
  });
};
"""
CONFIRM_SCRIPT = "<script>" + CONFIRM_JS + "</script>\n"

THEME_JS = r"""// ---- theme (person menu, and More on phones): Match device -> Light -> Dark; saves display.theme and applies it at once.
// Needs $, H, PREFS, applyTheme(). Settings, Display has the same choice.
function themeMode(){ const t = PREFS["display.theme"]; return t === "light" || t === "dark" ? t : "system"; }
function themeSync(){
  const m = themeMode(), name = {system: "Match device", light: "Light", dark: "Dark"}, nxt = {system: "light", light: "dark", dark: "system"}[m];
  document.querySelectorAll("[data-theme-lbl]").forEach(e => { e.textContent = name[m]; });
  const b = $("themeBtn"); if (!b) return;
  b.dataset.mode = m;
  b.title = "Theme: " + name[m] + ". Click for " + name[nxt]; b.setAttribute("aria-label", b.title);
}
$("themeBtn").addEventListener("click", () => {
  const nxt = {system: "light", light: "dark", dark: "system"}[themeMode()];
  PREFS["display.theme"] = nxt; applyTheme(); if (typeof fillPrefs === "function") fillPrefs();
  fetch("/api/prefs", {method: "POST", headers: H, body: JSON.stringify({prefs: {"display.theme": nxt}})}).then(r => r.json())
    .then(d => { if (d.prefs) { PREFS = d.prefs; applyTheme(); if (typeof fillPrefs === "function") fillPrefs(); } }).catch(() => {});
});
"""

_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
_SPARK = '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'
_FIND = '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>'

# HEADER_JS: what the shared header does by itself on every page: the current page in the navigation, the phone tab bar
# and its More sheet. (Each page still wires Find new jobs, Rate jobs and the person menu's profiles itself.) The board
# tells it whether this profile has a Target tab: window.siftTarget(name or "").
HEADER_JS = r"""(function(){
  var $ = function(id){ return document.getElementById(id); }, P = location.pathname;
  var page = /^\/catalog/.test(P) ? "catalog" : /^\/profile/.test(P) ? "profile" : /^\/settings/.test(P) ? "settings" : "jobs";
  var nav = $({jobs: "homeBtn", catalog: "catalogBtn", profile: "resumeBtn", settings: "prefsBtn"}[page]);
  if (nav) nav.setAttribute("aria-current", "page");
  var more = $("moreSheet"), moreBtn = $("tbMore");
  function tab(){
    var h = location.hash, cur = page === "catalog" ? "employers" : page !== "jobs" ? "more"
      : h === "#saved" ? "saved" : h === "#tailored" ? "resumes" : h === "#applied" || h === "#pivot" ? "more" : "jobs";
    document.querySelectorAll("#tabbar [data-tb]").forEach(function(a){ if (a.dataset.tb === cur) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    document.querySelectorAll("#moreSheet [data-mv]").forEach(function(a){ var on = (page === a.dataset.mv) || (page === "jobs" && h === "#" + a.dataset.mv); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  }
  function target(name){
    var a = $("mvTarget"); if (!a) return;
    a.hidden = !name; if (name) a.querySelector("span").textContent = name;
  }
  window.siftTarget = function(name){ try { localStorage.setItem("jb.target", JSON.stringify(name || "")); } catch(e) {} target(name); };
  try { target(JSON.parse(localStorage.getItem("jb.target") || '""')); } catch(e) {}
  function close(){ if (!more || more.hidden) return; more.hidden = true; moreBtn.setAttribute("aria-expanded", "false"); }
  if (moreBtn) moreBtn.addEventListener("click", function(e){
    e.stopPropagation();
    var open = more.hidden; more.hidden = !open; moreBtn.setAttribute("aria-expanded", String(open));
    if (open) { var f = more.querySelector("a:not([hidden]),button"); if (f) f.focus(); }
  });
  if (more) more.addEventListener("click", function(e){
    if (e.target.closest("#mvTheme")) { var t = $("themeBtn"); if (t) t.click(); return; }
    if (e.target.closest("a")) close();
  });
  document.addEventListener("click", function(e){ if (more && !more.hidden && !e.target.closest("#moreSheet,#tbMore,#themeBtn")) close(); });
  document.addEventListener("keydown", function(e){ if (e.key === "Escape" && more && !more.hidden) { close(); moreBtn.focus(); } });
  window.addEventListener("hashchange", function(){ close(); tab(); });
  tab();
})();
"""

# The shared header: text navigation (Jobs · Employers · Profile · Settings), Rate jobs, Find new jobs and the person menu
# (profiles, My profile, Settings, theme); below 900px a compact bar, and at 720px and less a bottom tab bar (Jobs ·
# Saved · Resumes · Employers · More). Used by the board, Settings, Employers and My profile; the ids (homeBtn,
# catalogBtn, resumeBtn, prefsBtn, updateBtn, rerateBtn, themeBtn, avatarBtn, amenu, amPeople, gsBadge) are what
# those pages' scripts use. It carries its own script (the dialog and the navigation state).
TOOLS = """    <nav class="mainnav" aria-label="Siftwell">
      <a id="homeBtn" href="/#jobs">Jobs</a><a id="catalogBtn" href="/catalog" title="Every employer Siftwell checks, and ways to add more">Employers</a><a id="resumeBtn" href="/profile" title="Your resume, what you look for, your search and target">Profile</a><a id="prefsBtn" href="/settings" title="Setup checklist, resume PDFs, Claude usage, display">Settings<span class="rrbadge" id="gsBadge" hidden></span></a>
    </nav>
    <button class="iconBtn" type="button" id="rerateBtn" title="Rate jobs: choose how Claude rates your jobs (no new listings)" aria-label="Rate jobs">""" + _IC + _SPARK + """</svg><span class="rrbadge" id="rrBadge" hidden></span><span class="vh" id="rrSmall">Claude only, no new listings</span></button>
    <button class="btn primary findBtn" type="button" id="updateBtn" title="Find new jobs: check your employers for new openings">""" + _IC + _FIND + """</svg><span class="flbl" aria-hidden="true">Find<span class="fl-new"> new</span> jobs</span><span class="vh">Find new jobs: </span><span class="vh" id="updSmall">check your employers for new openings</span></button>
    <div class="menuWrap">
      <button class="avatarBtn" id="avatarBtn" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="Profiles and settings"><span class="av" id="avInit">·</span><span id="avName">Profile</span></button>
      <div class="amenu" id="amenu" role="menu" hidden>
        <div id="amPeople"></div>
        <div class="amsep" role="separator"></div>
        <a role="menuitem" href="/profile">My profile</a>
        <a role="menuitem" href="/settings">Settings</a>
        <button role="menuitem" type="button" id="themeBtn">Theme <small data-theme-lbl>Match device</small></button>
      </div>
    </div>
    <nav class="tabbar" id="tabbar" aria-label="Siftwell">
      <a href="/#jobs" data-tb="jobs">""" + _IC + """<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg><span>Jobs</span></a>
      <a href="/#saved" data-tb="saved">""" + _IC + """<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/></svg><span>Saved</span></a>
      <a href="/#tailored" data-tb="resumes">""" + _IC + """<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></svg><span>Resumes</span></a>
      <a href="/catalog" data-tb="employers">""" + _IC + """<path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-4h6v4M9 10h.01M15 10h.01M9 14h.01M15 14h.01"/></svg><span>Employers</span></a>
      <button type="button" id="tbMore" data-tb="more" aria-haspopup="menu" aria-expanded="false" aria-controls="moreSheet">""" + _IC + """<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg><span>More</span></button>
    </nav>
    <div class="moresheet" id="moreSheet" role="menu" aria-label="More" hidden>
      <a role="menuitem" href="/profile" data-mv="profile">My profile</a>
      <a role="menuitem" href="/settings" data-mv="settings">Settings</a>
      <a role="menuitem" href="/#applied" data-mv="applied">Applied</a>
      <a role="menuitem" href="/#pivot" data-mv="pivot" id="mvTarget" hidden><span>Target</span></a>
      <button role="menuitem" type="button" id="mvTheme">Theme <small data-theme-lbl>Match device</small></button>
    </div>
    <script>""" + CONFIRM_JS + HEADER_JS + """</script>
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
<div class="banner gsbn" id="chkBanner" role="status" aria-live="polite" hidden></div>
<div class="banner gsbn" id="dirBanner" role="status" aria-live="polite" hidden></div>
<div class="banner gsbn" id="ttlBanner" hidden></div>
<div class="bnmore" id="bnMore" hidden><button type="button" class="linkbtn" id="bnMoreBtn" aria-expanded="false"></button></div>
<div class="panel" id="progress" hidden>
  <div class="row"><strong id="progTitle">Updating…</strong><span class="note" id="progNote"></span><button class="btn sm" type="button" id="progStop" hidden title="Stop rating: batches already sent finish and their ratings are kept. Queued runs are cancelled.">Stop</button><button class="btn sm" type="button" id="updStop" hidden title="Stop finding new jobs now. Everything found so far is kept and your board is rebuilt with it; the employers not reached are checked next time.">Stop</button><button class="btn sm primary" type="button" id="progReload" hidden>Show new ratings</button></div>
  <div class="prog"><i id="progBar"></i></div>
  <div class="note" id="progQueue" hidden></div>
  <div class="loglines" id="progLog"></div>
</div>
<div class="rrpop" id="rrPanel" role="dialog" aria-labelledby="rrTitle" hidden>
  <div class="rrhead"><strong id="rrTitle">Rate jobs</strong><button class="btn ghost sm" type="button" id="rrClose">Close</button></div>
  <div class="rrno" id="rrNo" hidden><p><b>Rating jobs needs Claude.</b> Claude reads each posting against your resume to give the Match rating. Without it, Siftwell still finds, filters and ranks jobs by how relevant they are and by Appeal.</p><a class="btn primary sm" href="/settings#get-started">Settings, then Get started</a></div>
  <div class="rrmain">
    <p class="rrsum" id="rrSum"></p>
    <button class="btn primary" type="button" data-rr="full" id="rrGo">Rate the jobs that need it</button>
    <small id="rrEstFull"></small>
    <label class="chk rrTgt"><input type="checkbox" id="rrTgt" checked><span>Also rate for my <span class="rrTgtName">Target</span> tab <small>(extra Claude requests: up to <span class="rrTgtN"></span> more jobs)</small></span></label>
  </div>
  <details class="rrmore" id="rrMore"><summary>More options</summary>
  <div class="rrrow">
    <div class="rrtxt"><b>Quick check only</b>
      <small id="rrHAll"></small>
      <label class="chk"><input type="checkbox" id="rrHNeed" checked><span>Only jobs that need it (<span id="rrHN">0</span>)</span></label></div>
    <button class="btn sm" type="button" data-rr="haiku">Run</button>
  </div>
  <div class="rrrow">
    <div class="rrtxt"><b>Careful look only</b>
      <span>Top <input type="number" id="rrPct" min="1" max="100" step="1" aria-label="Percent of rated jobs for a careful look"> % of rated jobs <span class="note" id="rrSN"></span></span>
      <label class="chk"><input type="checkbox" id="rrSNeed" checked><span>Only ones that need it (<span id="rrSNn">0</span>)</span></label>
      <small class="rrhint" hidden>Run the quick check first for better picks.</small></div>
    <button class="btn sm" type="button" data-rr="sonnet">Run</button>
  </div>
  <div class="rrrow">
    <div class="rrtxt"><b>Best judgment only</b>
      <span>Top <input type="number" id="rrTop" min="1" max="2000" step="1" aria-label="Number of top rated jobs for best judgment"> rated jobs <span class="note" id="rrON"></span></span>
      <label class="chk"><input type="checkbox" id="rrONeed" checked><span>Only ones that need it (<span id="rrONn">0</span>)</span></label>
      <small class="rrhint" hidden>Run the quick check first for better picks.</small></div>
    <button class="btn sm" type="button" data-rr="opus">Run</button>
  </div>
  <div class="rrfoot">
    <small id="rrEst"></small>
    <small>"Top" follows your Best bets order among jobs that already have a rating. The numbers here apply to this run only; your defaults stay in Settings.</small>
  </div>
  </details>
  <small id="rrLim" class="rrlim"></small>
  <small class="rrmsg" id="rrMsg" role="status"></small>
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

<nav class="tabs" aria-label="Your jobs"><a href="#jobs" id="tab-jobs">Jobs</a><a href="#saved" id="tab-saved">Saved</a><a href="#applied" id="tab-applied">Applied</a><a href="#tailored" id="tab-tailored">Resumes</a><a href="#pivot" id="tab-pivot" hidden>Target</a><a class="tabext" id="tab-employers" href="/catalog?mine=1#companies">Your employers →</a></nav>

<section id="view-jobs">
  <div class="startcard" id="startCard" role="region" aria-labelledby="scTitle" aria-live="polite" hidden></div>
  <div class="filters">
    <div class="frow">
      <input type="search" id="q" enterkeyhint="search" placeholder="Describe a job, industry, company or role, then press Enter" aria-label="Describe what you're looking for">
      <select id="sort" aria-label="Sort">
        <option value="rel" id="sortRel" hidden>Closest to my search</option><option value="score" id="sortScore">Best bets (Appeal and Match together)</option><option value="relevant" id="sortRelevant">Most relevant to my work</option><option value="appeal">Most appealing (pay, place, level)</option><option value="odds" id="sortOdds">Best Match (Claude’s rating)</option><option value="odds_later" id="sortLater">Best Match with my resume as it is</option><option value="pay">Highest pay</option><option value="gd">Best employee reviews</option><option value="new">Newest</option>
      </select>
      <button class="btn" type="button" id="filtersBtn" aria-expanded="false" aria-controls="fPanel" aria-label="Filters"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 5h18M6 12h12M10 19h4"/></svg><span class="fbl">Filters</span><span class="badge" id="fCount" hidden></span></button>
    </div>
    <div class="nlbar" id="nlBar" role="status" aria-live="polite" hidden></div>
    <div class="quick" id="quick"></div>
    <div class="fpanel" id="fPanel" hidden>
      <section class="mscard" id="msWrap" aria-labelledby="msTitle" hidden>
        <div class="mshead"><div><h3 id="msTitle">Your search</h3><p class="mssub">Saved to your profile · changes what reaches your board</p></div><a class="btn sm" id="msEditLink" href="/profile#search">Edit search settings</a></div>
        <p class="mssum" id="msSum"></p>
        <details class="msedit" id="msEdit"><summary>Edit here</summary>
        <div class="fgrid msgrid" id="msGrid">
        <label class="field"><span class="flabel">Home ZIP or City, ST</span><input type="text" id="msZip" data-ms="home_zip" placeholder="ZIP code or City, ST" autocomplete="postal-code"></label>
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
        <label class="field"><span class="flabel">Lowest base ($)</span><input type="number" inputmode="numeric" step="5000" min="0" id="msFloor" data-ms="salary_floor" placeholder="No floor"></label>
        <label class="field wide"><span class="flabel">Your level</span><select id="msLevel" data-ms="seniority_mine">
          <option value="">Any level</option><option value="1">Entry level</option><option value="2">Mid-level</option><option value="3">Senior</option><option value="4">Lead / Manager</option><option value="5">Principal / Sr. Manager</option><option value="6">Director</option><option value="7">VP / Executive</option></select></label>
        </div>
        </details>
        <p class="fhint" id="msState" role="status" aria-live="polite"></p>
      </section>
      <div class="fgroup first">Narrow the list <span class="fgsub">· only this view, nothing is saved</span></div>
      <div class="fgrid fview">
        <label class="field"><span class="flabel">Fit</span><select id="lbl"></select></label>
        <label class="field"><span class="flabel">Company</span><input type="search" id="coFind" placeholder="Type to find a company" aria-label="Type to find a company in the list below" autocomplete="off" hidden><select id="co"><option value="all">All companies</option></select></label>
        <label class="field"><span class="flabel">Show</span><select id="st">
          <option value="active">Not hidden</option><option value="hidden">Hidden (Not for me)</option><option value="all">Everything</option></select></label>
        <label class="field" id="clrField" hidden><span class="flabel">Security clearance</span><select id="clr">
          <option value="all" selected>Any clearance</option><option value="none">No clearance mentioned</option>
          <option value="nopoly">No TS/SCI + poly</option><option value="secret">Secret or less</option></select></label>
        <div class="field"><span class="flabel">Only</span>
          <div class="checks"><label class="chk"><input type="checkbox" id="paidonly"> Pay listed</label>
          <label class="chk"><input type="checkbox" id="nowide"> No wide pay bands</label>
          <label class="chk"><input type="checkbox" id="newonly"> New</label>
          <label class="chk"><input type="checkbox" id="reqall"> Jobs I don't meet requirements for</label></div></div>
      </div>
      <div class="fgroup" id="cfGroup">Employer</div>
      <div class="fgrid" id="cfGrid">
        <label class="field"><span class="flabel">Type</span><select id="cType">
          <option value="all">Any type</option><option value="public">Publicly traded</option><option value="private">Privately owned</option>
          <option value="np">Nonprofit / public sector</option></select></label>
        <label class="field"><span class="flabel">Size</span><select id="cSize">
          <option value="all">Any size</option><option value="s">Under 200 people</option><option value="m">200 – 1,000</option>
          <option value="l">1,000 – 10,000</option><option value="xl">10,000+</option><option value="nsxl">Under 10,000</option></select></label>
        <label class="field"><span class="flabel">Value</span><select id="cVal">
          <option value="all">Any value</option><option value="v1">Under $1B</option><option value="v10">$1B – $10B</option>
          <option value="v100">$10B – $100B</option><option value="vbig">$100B+</option><option value="v10p">$10B+</option></select></label>
        <label class="field"><span class="flabel">Age</span><select id="cAge">
          <option value="all">Any age</option><option value="a5">Under 5 years old</option><option value="a15">5 – 15 years old</option>
          <option value="aold">Over 15 years old</option><option value="a15m">Under 15 years old</option></select></label>
        <label class="field"><span class="flabel">Employee reviews (Glassdoor)</span><select id="cGd">
          <option value="all">Any rating</option><option value="g40">4.0+</option><option value="g35">3.5+</option>
          <option value="g35u">3.5+ or unrated</option><option value="g40r">4.0+ with 100+ reviews</option></select></label>
        <label class="field"><span class="flabel">Layoffs</span><select id="cLay">
          <option value="all">Any</option><option value="none">None reported (18 mo)</option><option value="noknown">Hide known layoffs</option></select></label>
        <label class="field"><span class="flabel">Stock for employees</span><select id="cEq">
          <option value="all">Any</option><option value="liquid">Public stock (can be sold)</option><option value="private">Private shares / options</option></select></label>
      </div>
      <div class="row"><button class="btn ghost sm" type="button" id="fReset" title="Clears the filters above. Your saved search stays as it is.">Clear filters</button><button class="btn sm" type="button" id="fDone">Done</button></div>
    </div>
    <div class="fchips" id="fChips"></div>
  </div>
  <div class="pvbar" id="pvPanel" hidden>
    <span id="pvTitle" hidden></span>
    <div class="pvcounts" id="pvCounts"></div>
    <details class="pvgaps"><summary>What to work on</summary><p class="help" id="pvHelp"></p><div id="pvGaps"></div></details>
  </div>
  <div class="countrow"><div class="count" id="count"></div><button class="btn sm" type="button" id="rateMore" hidden aria-haspopup="dialog">Rate jobs</button><span class="note" id="rateMsg"></span></div>
  <div class="split">
    <div class="listcol"><ol class="jobs rows" id="list" role="listbox" aria-label="Jobs"></ol>
    <button class="more" id="more" hidden>Show 100 more</button></div>
    <aside class="detail" id="detail" aria-label="Job details"></aside>
  </div>
  <details class="howto"><summary>How the scores work</summary>
  <p class="legend" id="pvLegend" hidden>This tab shows jobs that fit your target, which you set on My profile, under Target. Claude rates each as a step toward it. "Now" is your shot today with an honest tailored resume. "After prep" assumes the preparation you described. Apply now = 65+ today; After prep = 65+ once prepared; Long shot = 40 to 64 even after prep. Pitch ideas only claim what's true today. Overall = 50% odds (60% now, 40% after prep) + 30% pay + 20% quality of life.</p>
  <p class="legend" id="legend2"></p>
  <p class="legend" id="legend">Verdicts come from Claude comparing each job with your resume: Strong match (strong as written), Worth tailoring (strong after honest tailoring), Stretch, Not a fit. On the pay bar, the dark tick is your <span class="floorTxt"></span> floor, the grey tick is your current base, and the ring is the midpoint. Ranges whose top is 1.6× the bottom or more are flagged as wide pay bands. Save, Applied and Not for me are kept per profile.</p>
  </details>
</section>

<section id="view-tailored" hidden>
  <div class="countrow"><div class="count" id="tlCount">Loading…</div></div>
  <ol class="jobs" id="tlList"></ol>
  <p class="legend">Every tailored resume you've made for this profile, newest first. Download PDF gives the finished resume, Download Word one you can edit; Review shows each bullet's source and the gaps Claude flagged.</p>
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
// Jobs whose titles nothing on the person's what-to-look-for list names: not on the board. They are kept apart
// (D.off_jobs; ones that are there for the Target tab stay in D.jobs, marked off_list) and offered once, in the count
// line: "N hidden because their titles aren't on your list · Show".
const OFF = D.off_jobs || []; let offShown = false;
const coOf = j => j.co || j.company;      // (two job boards of one employer show and filter as one name)
const HASREL = !!D.has_relevance;   // the profile has a what-to-look-for sheet, so every job has a Relevance
const NOMATCH_SORT = () => HASREL ? "relevant" : "appeal";   // the order when there is no Match to rank by
// Claude is optional: when it isn't connected the board says so once (banner) and shows "-" where Match would be.
let NOAI = D.claude_ready === false;
const NOAI_MSG = "Connect Claude to get Match ratings and tailoring";
const RLIM = Object.assign({haiku: 500, sonnet: 100, opus: 50, saved: 25, target: 50, quick: 200}, D.rate_limits || {});  // per-run rating limits (ai_score.RUN_LIMITS)
const NOAI_LINK = `<a href="/settings#get-started">Settings → Get started</a>`;
const hasMatch = jobs.some(j => j.ai_fit != null || j.pv_now != null);  // ratings made earlier still show and sort
const noClaude = what => `<span class="nocl">${what} needs Claude. ${NOAI_LINK}</span>`;
const nNew = jobs.filter(j => j.new).length;
const updatedAt = (() => { try { return new Date(D.generated).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}); } catch(e) { return D.generated.replace("T", " "); } })();
$("sub").textContent = "Updated " + updatedAt;
document.querySelectorAll(".floorTxt").forEach(e => e.textContent = D.salary_floor ? fmt(D.salary_floor) : "");  // (no floor set: "your floor", "salary filters")
// The Target tab is there only when this profile has a target (set on My profile, under Target), named after it.
$("tab-pivot").textContent = D.target_name || "Target";
$("tab-pivot").hidden = !D.pivot_enabled;
if (!D.pivot_enabled && location.hash === "#pivot") location.hash = "#jobs";
if (window.siftTarget && SERVED) siftTarget(D.pivot_enabled ? (D.target_name || "Target") : "");   // (the phone's More menu)
document.querySelectorAll(".rrTgtName").forEach(e => e.textContent = D.target_name || "Target");
// The board's employers live on the Employers page (open counts, last check, add / remove): one link, with how many.
$("tab-employers").textContent = `Your employers (${(D.companies || []).length.toLocaleString()}) →`;
$("stats").innerHTML = [
  [jobs.length, "matches"], [jobs.filter(j=>j.workplace==="remote").length, "remote"],
  [jobs.filter(j=>j.salary_min!=null && j.salary_min>=D.salary_floor).length, D.salary_floor ? "min ≥ " + fmt(D.salary_floor) : "pay listed"],
  [nNew, "new this run"], [D.companies.length, "companies"]
].map(([n,l]) => `<div class="stat"><b>${n.toLocaleString()}</b><span>${l}</span></div>`).join("");




const coCount = {}; jobs.forEach(j => { coCount[coOf(j)] = (coCount[coOf(j)] || 0) + 1; });
const cos = Object.keys(coCount).sort((a, b) => coCount[b] - coCount[a] || a.localeCompare(b));  // most matching jobs first
const coOpts = list => list.map(c => `<option value="${esc(c)}">${esc(c)} (${coCount[c].toLocaleString()})</option>`).join("");
$("co").insertAdjacentHTML("beforeend", coOpts(cos));
if (cos.length > 25) {   // a long list: type a few letters to shorten it
  $("coFind").hidden = false;
  $("coFind").addEventListener("input", () => {
    const t = $("coFind").value.trim().toLowerCase(), cur = $("co").value;
    const list = t ? cos.filter(c => c.toLowerCase().includes(t)) : cos;
    $("co").innerHTML = `<option value="all">${t ? `All companies (${list.length} match “${esc($("coFind").value.trim())}”)` : "All companies"}</option>` + coOpts(list);
    if (cur !== "all" && list.includes(cur)) $("co").value = cur;
    else if (cur !== "all") { $("co").value = "all"; shown = 100; render(); }
  });
}
$("clrField").hidden = !jobs.some(j => j.clearance);   // only boards with clearance jobs get the control

let shown = 100, wp = "all", mode = "current", gapSel = "";  // wp: the "Remote" quick filter ("all" or "remote")
let NL = null, NL_PREV_SORT = "score", nlSeq = 0;  // natural-language search result from /api/search
const PVL = {apply_now: "Apply now", after_prep: "After prep", after_portfolio: "After prep", long_shot: "Long shot", skip: "Skip"};
const pvLab = j => j.pv_label === "after_portfolio" ? "after_prep" : j.pv_label;
const LBL_OPTS = {
  current: [["all","Any fit"],["apply_now","Strong match"],["tailor","Worth tailoring"],["good","Strong + worth tailoring"],["stretch","Stretch"],["noskip","Hide not-a-fit"]],
  pivot: [["noskip","Hide skips"],["all","Everything"],["apply_now","Apply now"],["good","Apply now + After prep"],["after_prep","After prep"],["long_shot","Long shots"],["labs","Frontier AI labs only"]],
};
const HAS_AI_TRACK = jobs.some(j => j.ai_track);  // companies marked as AI companies exist only in catalogs from earlier versions
if (!HAS_AI_TRACK) {
  LBL_OPTS.pivot = LBL_OPTS.pivot.filter(([v]) => v !== "labs");
  document.querySelectorAll('#cType option[value="lab"], #cType option[value="ai"]').forEach(o => o.remove());
}
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
    ["all", pj.length - scored.length, "Not yet rated", "use Rate this job, or Rate jobs"]];
  $("pvCounts").innerHTML = counts.map(([v,c,l,sub]) => `<button type="button" data-lbl="${v}" title="${esc(sub)}" aria-pressed="${$("lbl").value === v}"><b>${c}</b> ${l}</button>`).join("");
  const tally = {}, label = {};
  scored.filter(j => ["apply_now","after_prep"].includes(pvLab(j))).forEach(j => (j.pv_gaps||[]).forEach(g => { const k = g.toLowerCase(); if (k.includes("ts/sci") || k.includes("scif")) return; tally[k] = (tally[k]||0) + 1; label[k] = label[k] || g; }));
  const top = Object.entries(tally).sort((a,b) => b[1]-a[1]).slice(0, 10), mx = top.length ? top[0][1] : 1;
  $("pvGaps").innerHTML = top.length ? top.map(([k,c]) => `<button type="button" class="gaprow" data-gap="${esc(k)}" aria-pressed="${gapSel===k}"><span>${esc(label[k])}</span><i style="width:${Math.max(4, c/mx*100)}%"></i><em>${c}</em></button>`).join("")
    : `<div class="note">Appears once Claude has rated some jobs as Apply now or After prep.</div>`;
}
$("pvCounts").addEventListener("click", e => { const b = e.target.closest("button[data-lbl]"); if (!b) return; $("lbl").value = b.dataset.lbl; gapSel = ""; shown = 100; drawPivotPanel(); render(); });
$("pvGaps").addEventListener("click", e => { const b = e.target.closest("button[data-gap]"); if (!b) return; gapSel = gapSel === b.dataset.gap ? "" : b.dataset.gap; if (gapSel) $("lbl").value = "noskip"; shown = 100; drawPivotPanel(); render(); });
["q","clr","co","st","sort","paidonly","newonly","reqall","lbl","nowide","cType","cSize","cVal","cAge","cGd","cLay","cEq"].forEach(id => $(id).addEventListener("input", () => { shown = 100; render(); }));
$("more").addEventListener("click", () => { shown += 100; render(); });
// "N hidden ▾" in the count line: each reason with its own Show (for this visit; nothing saved changes).
let lvlShown = false;
$("count").addEventListener("click", e => {
  const id = e.target.id;
  if (id === "reqShow") { $("reqall").checked = true; shown = 100; render(); }
  if (id === "offShow") { offShown = true; OFF.forEach(j => { j.off_list = true; jobs.push(j); }); OFF.length = 0; shown = 100; render(); }
  if (id === "lvlShow") { lvlShown = true; shown = 100; render(); }
  if (id === "hidShow") { $("st").value = "hidden"; shown = 100; render(); }
});
// ---- Your search (the card at the top of the Filters panel): this profile's saved search settings, the same ones /setup asks for.
// They decide which jobs reach the board: home ZIP / radius / ways of working / remote anywhere / pay floor are applied
// when the board is built (jobfinder.select_for_person); level and travel limit are applied here (mySearchOk).
// Each change saves through POST /api/person/settings, like My profile used to: the server re-checks this board (and
// queues the automatic quick check of new jobs), and the page reloads itself once the rebuilt board is ready.
// None of these reset Claude's ratings (the pay floor only matters to the Target tab's ratings).
let MYS = null, msBase, msTimer = null;
const msNow = () => MYS || {seniority_band: (D.seniority && D.seniority.band) || [1, 7], travel_max: D.travel_max || "any"};
function mySearchOk(j){
  const s = msNow(), SB = s.seniority_band || [1, 7], L = j.level, t = j.travel || "", tm = s.travel_max || "any";
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
    if (document.activeElement !== el) el.value = v == null || (k === "salary_floor" && !v) ? "" : String(v);  // (no floor shows as blank)
  });
  document.querySelectorAll("[data-mswp]").forEach(el => el.checked = (MYS.workplaces || []).includes(el.dataset.mswp));
}
function msSay(t, err){ $("msState").textContent = t; $("msState").classList.toggle("err", !!err); }
// The card's one-line summary: "43215 · 35 mi · on-site, hybrid · remote anywhere in the US · $60k+ · any level"
function msSummary(){
  if (!MYS) return;
  const s = MYS, wpN = {onsite: "on-site", hybrid: "hybrid", remote: "remote"}, wps = (s.workplaces || []).map(w => wpN[w] || w);
  const remoteOnly = wps.length === 1 && wps[0] === "remote", home = String(s.home_zip || "").trim();
  const trv = {none: "no travel", light: "light travel", moderate: "some travel"}[s.travel_max];
  const parts = [remoteOnly ? "" : home ? `${home} · ${s.radius_miles || 35} mi` : "No home ZIP yet", wps.join(", "),
    s.remote_us && !remoteOnly ? "remote anywhere in the US" : "", s.salary_floor ? fmt(s.salary_floor) + "+" : "any pay",
    s.seniority_mine ? LVN[s.seniority_mine] || "" : "any level", trv || ""];
  $("msSum").textContent = parts.filter(Boolean).join(" · ");
}
function msLoaded(st){
  if (!SERVED || !st) return;
  MYS = st; $("msWrap").hidden = false; msFill(); msSummary();
}
const msBoard = () => fetch("/api/profile/board" + pq()).then(r => r.json());
if (SERVED) msBoard().then(b => { if (msBase === undefined) msBase = b.board_at || null; }).catch(() => {});
function msAwaitBoard(){
  let tries = 0;
  clearTimeout(msTimer);
  const tick = () => msBoard().then(b => {
    if (b.board_at && b.board_at !== msBase && !b.rebuilding) { saveFilters(); location.reload(); return; }
    if (++tries < 90) msTimer = setTimeout(tick, 2000);
    else msSay("Saved. Your board re-checks as soon as the current Find new jobs or rating finishes.");
  }).catch(() => { msTimer = setTimeout(tick, 4000); });
  msTimer = setTimeout(tick, 1500);
}
function msSave(settings){
  msSay("Saving…");
  fetch("/api/person/settings", {method: "POST", headers: H, body: JSON.stringify({person: PID, settings})})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) { msFill(); msSay(d.error || "Couldn't save that.", true); return; }
      MYS = Object.assign({}, MYS, d.settings); msFill(); msSummary();
      if (d.area_changed) { try { sessionStorage.setItem("jb.area", "1"); } catch(e) {} if (typeof areaOffer === "function") areaOffer(); }
      D.salary_floor = MYS.salary_floor || 0;
      shown = 100; render();
      msSay("Saved. Re-checking your board…"); msAwaitBoard();
    }).catch(() => { msFill(); msSay("Couldn't reach Siftwell, so that wasn't saved.", true); });
}
$("msGrid").addEventListener("change", async e => {
  const el = e.target;
  if (el.dataset.mswp) {
    const wps = [...document.querySelectorAll("[data-mswp]")].filter(x => x.checked).map(x => x.dataset.mswp);
    if (!wps.length) { el.checked = true; msSay("Pick at least one way of working.", true); return; }
    msSave({workplaces: wps}); return;
  }
  // The older built-in area (no home ZIP yet): a ZIP changes which jobs count as near you, so say so before saving.
  if (el.dataset.ms === "home_zip" && el.value.trim() && MYS && !String(MYS.home_zip || "").trim() && !((MYS.workplaces || []).length === 1 && MYS.workplaces[0] === "remote") && jobs.length
      && !await appConfirm({title: "Set your home ZIP?", ok: "Set my home ZIP", text: "This changes which jobs count as near you. Until now Siftwell has used its built-in Washington, DC area list for this profile; with a ZIP it keeps jobs within your search radius of that place instead, so some jobs will be added to your board and some removed.\n\n(If you only want more employers near you, Settings, then Employer directory lets you pick an area for that without changing your job filter.)"})) { msFill(); el.value = ""; return; }
  if (el.dataset.ms) msSave({[el.dataset.ms]: el.type === "checkbox" ? el.checked : el.value});
});

// Pay is stored per year so every job compares on one scale (hourly pay at 2,080 hours a year); a job that states
// hourly, weekly or monthly pay is shown the way its posting states it ("$36.90/hr").
const PAYU = {hour: "/hr", day: "/day", week: "/wk", month: "/mo"};
const fmtU = v => "$" + (Math.abs(v - Math.round(v)) > 0.004 ? v.toFixed(2) : Math.round(v).toLocaleString());
function payOwn(j, sep){
  const u = PAYU[j.pay_unit];
  if (!u || j.pay_min == null) return "";
  const a = fmtU(j.pay_min), b = fmtU(j.pay_max ?? j.pay_min);
  return (a === b ? a : a + (sep || "–") + b) + u;
}
// The pay bar's scale is this board's own range of listed pay (5th to 95th percentile), widened to take in your
// floor, your current base and the job itself: a $45k or $20/hr job is drawn as sensibly as a $300k one.
let PAYQ = null;
function payScale(j){
  if (!PAYQ) {
    const q = (a, p) => a.length ? a[Math.min(a.length - 1, Math.max(0, Math.round(p * (a.length - 1))))] : null;
    const los = jobs.map(x => x.salary_min).filter(v => v != null).sort((x, y) => x - y), his = jobs.map(x => x.salary_max).filter(v => v != null).sort((x, y) => x - y);
    PAYQ = [q(los, .05) ?? 30000, q(his, .95) ?? 150000];
  }
  let lo = Math.min(PAYQ[0], j.salary_min * .9), hi = Math.max(PAYQ[1], j.salary_max * 1.1);
  for (const v of [D.salary_floor, CUR.base]) if (v) { lo = Math.min(lo, v * .9); hi = Math.max(hi, v * 1.1); }
  const step = hi - lo > 150000 ? 50000 : hi - lo > 40000 ? 10000 : 5000;
  lo = Math.max(0, Math.floor(lo / step) * step); hi = Math.ceil(hi / step) * step;
  return [lo, hi > lo ? hi : lo + step];
}
function payBar(j){
  if (j.salary_max == null) return j.lazy ? `<div class="pay"><span class="amt">Open to check</span><div>Siftwell has this job’s title and place so far. Press “Show the full posting” below and its pay is read from it.</div></div>`
    : `<div class="pay"><span class="amt">Not listed</span><div>No salary range in posting</div></div>`;
  const [lo, hi] = payScale(j), p = v => Math.max(0, Math.min(100, (v-lo)/(hi-lo)*100));
  const mid = j.salary_mid ?? Math.round((j.salary_min + j.salary_max)/2);
  const hourly = j.pay_unit === "hour" && j.pay_min != null, own = payOwn(j, " – ");
  const ax = v => hourly ? "$" + Math.round(v / 2080) + "/hr" : fmt(v);
  const midTxt = hourly ? fmtU(Math.round(mid / 2080 * 100) / 100) + "/hr" : fmt(mid);
  const one = j.salary_max === j.salary_min;
  const year = own ? ` · about ${one ? fmt(mid) : fmt(j.salary_min) + "–" + fmt(j.salary_max)} a year${hourly ? " full time" : ""}` : "";
  const note = j.wide_band
    ? `<div class="note">Wide band (top is ${(j.salary_max/j.salary_min).toFixed(1)}× bottom). Scored on midpoint ${midTxt}.</div>`
    : `<div>${one ? "" : "Midpoint " + midTxt}${mid < D.salary_floor ? (one ? "Below your floor" : " · below your floor") : ""}${one && mid >= D.salary_floor ? year.slice(3) : year}</div>`;
  return `<div class="pay"><span class="amt">${own || (one ? fmt(j.salary_min) : `${fmt(j.salary_min)} – ${fmt(j.salary_max)}`)}</span>
    <div class="bar${j.wide_band ? " wide" : ""}" title="${one ? "Pay" : "Range"} ${own || (one ? fmt(j.salary_min) : `${fmt(j.salary_min)}–${fmt(j.salary_max)}`)}${one ? "" : ", midpoint " + midTxt}">
      <i style="left:${p(j.salary_min)}%;width:${Math.max(1.5,p(j.salary_max)-p(j.salary_min))}%"></i>
      ${CUR.base ? `<span class="mk cur" style="left:${p(CUR.base)}%" title="Your current base ${fmt(CUR.base)}"></span>` : ""}
      ${D.salary_floor ? `<span class="mk" style="left:${p(D.salary_floor)}%" title="Your floor ${fmt(D.salary_floor)}"></span>` : ""}
      <span class="mid" style="left:${p(mid)}%" title="Midpoint ${midTxt}"></span>
    </div><div class="axis"><span>${ax(lo)}</span><span>${ax((lo + hi) / 2)}</span><span>${ax(hi)}</span></div>
    ${note}</div>`;
}

const LVN = {1: "Entry level", 2: "Mid-level", 3: "Senior", 4: "Lead / Manager", 5: "Principal / Sr. Manager", 6: "Director", 7: "VP / Executive"};
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
let PREFS = {"display.clearance": "all", "display.sort": "score", "display.theme": "system", "tailor.questions": "always"};
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
    if (!jobs.some(j => j.ai_fit != null) && ["score", "odds", "odds_later"].includes($("sort").value)) $("sort").value = NOMATCH_SORT();  // nothing to rank by Match yet
    if (!OPENED) SEL = null;   // (the order may just have changed: the detail pane shows the new first row)
    // Settings, Display, "Start on": Jobs, Saved, Applied, Resumes or the Target tab (an older "Companies" choice stays on Jobs:
    // employers are on the Employers page now)
    const st0 = PREFS["display.start_tab"];
    if (!location.hash && st0 && st0 !== "jobs" && st0 !== "companies" && (st0 !== "pivot" || D.pivot_enabled)) { location.hash = "#" + st0; return; }
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
  if (r.status === "not_reviewed") return r.reason === "off" ? "" : `<span class="gd">Not reviewed (${r.reason === "codex_signed_out" ? "Codex isn’t signed in" : "Codex isn’t installed"})</span>`;
  if (r.status === "error") return `<span class="gd lo">Astra review failed</span>`;
  if (r.status === "running") return `<span class="gd">Astra review in progress…</span>`;
  if (r.status === "interrupted") return `<span class="gd lo">Astra review interrupted at ${r.final ?? "?"}</span>`;
  const pass = r.status === "passed";
  return `<span class="gd ${pass ? "hi" : "lo"}">Astra ${r.final} · ${pass ? "passed" : `below ${r.threshold}`} · ${r.rounds} round${r.rounds === 1 ? "" : "s"}</span>`;
}
// Under a tailored resume's card: what Siftwell's fact check found (lines with nothing in the person's resume, profile or
// answers behind them), so they are seen before the resume is sent.
function factNotes(f){
  if (!f || !f.checked) return "";
  const w = f.warnings || [];
  if (!w.length) return f.fixed ? `<div class="tl2"><b>Fact check:</b> every line traced to your resume or answers; ${f.fixed} detail${f.fixed === 1 ? "" : "s"} set back to match your profile.</div>` : "";
  return `<div class="tlwarn" role="note"><b>Check before you send (${w.length + (f.more || 0)}):</b><ul>${w.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` +
    (f.more ? `<span>and ${f.more} more on the Review page.</span>` : "") + `</div>`;
}
// Under a tailored resume's card: why Astra didn't review it (or why its review failed), and Siftwell's own free checks.
function reviewNotes(r){
  if (!r) return "";
  const c = r.checks, bits = [];
  if (c) {
    if (c.pages) bits.push(`${c.pages} page${c.pages === 1 ? "" : "s"}`);
    if (c.keyword_coverage != null) bits.push(`covers ${c.keyword_coverage}% of the posting’s key phrases`);
    bits.push((c.issues || []).length ? c.issues.map(esc).join(" ") : "no pronoun, date-format or length problems found");
  }
  return (r.status === "error" ? `<div class="tlfail">Astra’s review didn’t finish: ${esc(r.why || "no reason given")}</div>` : "") +
    (r.status === "not_reviewed" && r.reason !== "off" && r.why ? `<div class="tl2">${esc(r.why)}</div>` : "") +
    (c ? `<div class="tl2"><b>Siftwell’s own checks:</b> ${bits.join(" · ")}</div>` : "");
}
function drawTailored(){
  const byId = Object.fromEntries(jobs.map(j => [j.id, j]));
  const nRun = TLIST.filter(x => x.state === "running").length, nReady = TLIST.filter(x => x.state !== "running" && x.state !== "failed").length;
  $("tlCount").textContent = !SERVED ? "Open the board from the server to see tailored resumes." : TLIST.length ? `${nReady} tailored resume${nReady === 1 ? "" : "s"}${nRun ? ` · ${nRun} being tailored` : ""}` : (NOAI ? "No tailored resumes yet. Tailoring a resume needs Claude: connect it under Settings, then Get started." : "No tailored resumes yet. Tap Tailor my resume on any job.");
  $("tlList").innerHTML = TLIST.map(x => {
    const j = byId[x.job.id], when = x.created ? new Date(x.created).toLocaleDateString([], {month: "short", day: "numeric", year: "numeric"}) : "";
    const m = j ? (j.ai_fit ?? j.pv_now) : null, w = x.work || {};
    const title = safeUrl(x.job.url) ? `<a class="title" href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">${esc(x.job.title || "Job")}</a>` : `<span class="title">${esc(x.job.title || "Job")}</span>`;
    const posting = safeUrl(x.job.url) ? `<a href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">View posting ↗</a>` : "";
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
      <div class="scores rsc">${j ? scoreTrio(j, false) : m != null ? `<div><b class="m ${m >= 70 ? "hi" : ""}">${m}</b><small>Match</small></div>` : ""}</div>
      <div style="min-width:0">
        ${safeUrl(x.job.url) ? `<a class="title" href="${esc(safeUrl(x.job.url))}" target="_blank" rel="noopener">${esc(x.job.title || "")}</a>` : `<span class="title">${esc(x.job.title || "")}</span>`}
        <div class="meta"><span class="coname">${esc(x.job.company || "")}</span><span>Tailored ${esc(when)}</span><span>${j ? "Still open" : "No longer on your board"}</span>${x.gaps ? `<span>${x.gaps} gap${x.gaps === 1 ? "" : "s"} flagged</span>` : ""}${w.running ? `<span class="tlwork" role="status"><span class="spin"></span>Re-tailoring: ${esc(TL_STEP[w.step] || "working…")}</span>` : reviewBadge(x.review)}</div>
        ${x.headline ? `<div class="tl2">${esc(x.headline)}</div>` : ""}
        ${w.running ? "" : factNotes(x.facts)}
        ${w.running ? "" : reviewNotes(x.review)}
        ${w.error && !w.running ? `<div class="tlfail">Re-tailoring failed: ${esc(w.error)} <button class="btn ghost sm" type="button" data-dismiss="${esc(x.slug)}">Dismiss</button></div>` : ""}
        <div class="acts">${x.review && x.review.status === "interrupted" ? `<button class="pri" data-resume="${esc(x.job.id)}" data-slug="${x.slug}">Resume review</button>` : ""}${x.review && x.review.status === "needs_answers" ? `<button class="pri" data-astra="${esc(x.job.id)}" data-slug="${x.slug}">Answer Astra's questions</button>` : ""}<a class="pri" href="/tailored/${x.slug}.pdf">Download PDF</a><a href="/tailored/${x.slug}.docx">Download Word</a><a href="/tailored/${x.slug}" target="_blank" rel="noopener">Review</a>${posting}<button class="danger" data-del="${x.slug}" data-title="${esc(x.job.title || "this job")}">Remove</button></div>
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
    row("Hiring for you", `${c.open || 0} open on your board${c.new_week && c.new_week < c.open ? `, ${c.new_week} new this week` : ""}${c.median_hr ? ` · typical pay $${c.median_hr.toFixed(2)}/hr` : c.median_mid ? ` · typical midpoint ${fmt(c.median_mid)}` : ""}`),
  ].join("");
  return `<details class="copanel" open><summary>About ${esc(j.company)}</summary>
    ${c.blurb ? `<p>${esc(c.blurb)}</p>` : ""}<dl>${facts}</dl>
    <div class="colinks">${safeUrl(c.levels_url) ? `<a href="${esc(safeUrl(c.levels_url))}" target="_blank" rel="noopener">Pay on Levels.fyi</a>` : ""}<a href="${glass}" target="_blank" rel="noopener">Reviews on Glassdoor</a></div>
    ${c.researched_at ? `<p class="asof">Facts looked up by Claude on ${esc(new Date(String(c.researched_at).slice(0, 10) + "T12:00:00").toLocaleDateString([], {month: "short", day: "numeric", year: "numeric"}))}; they can be wrong, so check the sources.</p>` : c.ownership ? "" : `<p class="asof">Company facts not researched yet.</p>`}</details>`;
}

const ago = d => { if (!d) return ""; const t = Date.parse(d); if (!t) return ""; const n = Math.round((Date.now() - t) / 864e5); return n <= 0 ? "today" : n === 1 ? "yesterday" : n < 7 ? n + "d ago" : n < 45 ? Math.round(n / 7) + "w ago" : Math.round(n / 30) + "mo ago"; };
const whereTxt = j => j.workplace === "remote" ? (j.remote_in ? `Remote (${j.remote_in})` : "Remote") : (j.where || (j.dmv_locations.length ? j.dmv_locations : j.locations)[0] || "").replace(/,?\s*(United States( of America)?|USA)$/i, "").slice(0, 40) + (j.workplace === "hybrid" ? " · Hybrid" : "");
const payTxt = j => j.salary_min == null ? (j.lazy ? "Pay: open to check" : "Pay not listed") : (payOwn(j) || (j.salary_max && j.salary_max !== j.salary_min ? `${fmt(j.salary_min)}–${fmt(j.salary_max)}` : fmt(j.salary_min)));
const TIERN = {haiku: "Quick check", sonnet: "Careful look", opus: "Best judgment"};   // the same three names everywhere (no model names)
const tierName = j => j.ai_tier ? TIERN[j.ai_tier] + (j.ai_at ? " · " + j.ai_at : "") + (j.ai_stale ? " · made with older info" : "") : "Not rated yet";
const verdict = j => mode === "pivot" ? (j.pv_label ? [pvLab(j), PVL[j.pv_label]] : null) : (j.ai_label ? [j.ai_label, LBL[j.ai_label]] : null);
let SEL = null, OPENED = false;
// The scores, one name and one order everywhere (list rows, details, Resumes, Target): Relevant · Appeal · Match. On the
// Target tab, Overall (that tab's Best bets number) stands where Appeal does.
function scoreTrio(j, pvm){
  const m = pvm ? j.pv_now : j.ai_fit;
  return (!pvm && HASREL ? `<div title="${esc(j.rel_why || "How close this job is to the work you do")}"><b class="rv${j.rel >= 70 ? " hi" : ""}">${j.rel ?? "–"}</b><small>Relevant</small></div>` : "") +
    `<div><b>${pvm ? (j.pv_score ?? j.score) : (j.appeal ?? "–")}</b><small>${pvm ? "Overall" : "Appeal"}</small></div>` +
    `<div><b class="m ${m >= 70 ? "hi" : ""}${m == null && NOAI ? " na" : ""}" title="${m == null ? (NOAI ? "Match ratings need Claude" : "Not rated yet") : pvm ? "" : tierName(j)}">${m ?? "—"}</b><small>Match${!pvm && j.ai_tier && j.ai_tier !== "opus" ? `<span class="tierdot t-${j.ai_tier}"></span>` : ""}</small></div>`;
}
function card(j){
  const s = status[j.id] || "", pvm = mode === "pivot", v = verdict(j);
  return `<li class="jrow ${s==="hidden"?"hidden-by-user":""}" role="option" tabindex="0" data-id="${esc(j.id)}" aria-selected="${SEL === j.id}">
    <div class="rtitle">${j.new ? '<span class="ndot" title="New this week"></span>' : ""}${esc(j.title)}</div>
    <div class="rsc">${scoreTrio(j, pvm)}</div>
    <div class="rco">${esc(coOf(j))} · ${esc(whereTxt(j))}</div>
    <div class="rmeta">${v ? `<span class="vpill v-${v[0]}">${v[1]}</span>` : NOAI ? "" : `<span class="vpill">Not rated yet</span>`}<span class="amt">${payTxt(j)}</span>${j.posted ? `<span>${ago(j.posted)}</span>` : ""}${(pvm ? j.pv_stale : j.ai_stale) ? '<span class="old" title="Rated before your latest info">Older info</span>' : ""}${j.req_status === "unmet" ? '<span class="rq un">Requirement not met</span>' : j.req_status === "flag" ? '<span class="rq">Check requirements</span>' : ""}${TAILORED[j.id] ? "<span>Resume ready</span>" : WORK[j.id] && WORK[j.id].state === "running" ? "<span>Tailoring…</span>" : ""}${s === "applied" ? "<span>Applied</span>" : s === "saved" ? "<span>★ Saved</span>" : ""}</div>
    <div class="racts"><button type="button" data-k="saved" aria-pressed="${s==="saved"}" title="Save" aria-label="Save">★</button><button type="button" data-k="hidden" aria-pressed="${s==="hidden"}" title="Not for me" aria-label="Not for me">✕</button></div>
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
  const wpChip = j.workplace ? `<span class="chip ${j.workplace}"${j.remote_in ? ` title="Remote for people who live in ${esc(j.remote_in)}"` : ""}>${j.workplace === "onsite" ? "On-site" : j.workplace === "remote" && j.remote_in ? `Remote (${esc(j.remote_in)})` : j.workplace[0].toUpperCase()+j.workplace.slice(1)}</span>` : `<span class="chip">Workplace not stated</span>`;
  const locs = (j.dmv_locations.length ? j.dmv_locations : j.locations).slice(0,4).map(l => `<span class="chip">${esc(l)}</span>`).join("");
  const clr = j.clearance ? `<span class="chip ${j.clearance.includes("poly")?"poly":""}">${esc(j.clearance)}</span>` : "";
  const tl = TAILORED[j.id], wk = WORK[j.id], url = safeUrl(j.url);
  // One primary action (Tailor my resume, or Download PDF once it is tailored), View posting as the strong second one,
  // and Save / Applied / Not for me as lighter actions below. Without Claude there is no Tailor button: View posting
  // is the primary action, and Claude's read says once what Claude would add.
  const noTailor = !SERVED || (NOAI && !tl && !(wk && (tlBusy(wk) || wk.state === "failed")));
  const tailorBtns = noTailor ? "" : wk && tlBusy(wk) ? `<button class="btn primary" type="button" disabled>${esc(TL_STEP[(wk.work || {}).step] || "Tailoring…")}</button><a class="btn" href="#tailored">See it in Resumes</a>`
    : wk && wk.state === "failed" ? `<button class="btn primary" type="button" data-tailor="1"${NOAI ? ' disabled title="Needs Claude"' : ""}>Tailoring failed · Try again</button>`
    : tl ? `<a class="btn primary" href="/tailored/${tl}.pdf">Download PDF</a><a class="btn" href="/tailored/${tl}.docx">Download Word</a><a class="btn" href="/tailored/${tl}" target="_blank" rel="noopener">Review</a>`
    : `<button class="btn primary" type="button" data-tailor="1">Tailor my resume</button>`;
  const viewBtn = url ? `<a class="btn ${noTailor ? "primary" : "strong"}" href="${esc(url)}" target="_blank" rel="noopener">View posting ↗</a>` : "";
  const again = tl && SERVED && !(wk && tlBusy(wk)) ? `<button class="btn quiet" type="button" data-tailor="1" data-again="1"${NOAI ? ' disabled title="Needs Claude"' : ""}>Tailor again</button>` : "";
  const sv = (val, lab, cls) => `<div class="sv"><b class="${cls || ""}">${val ?? "–"}</b><small>${lab}</small></div>`;
  const ap = j.appeal_parts;
  return `<div class="dpane" data-id="${esc(j.id)}">
    <button class="dback" type="button" id="dBack">‹ All jobs</button>
    <div><h2 class="dtitle">${esc(j.title)}</h2>
      <div class="dco"><span class="coname">${esc(coOf(j))}</span><span>${esc(whereTxt(j))}</span>${j.posted ? `<span>Posted ${ago(j.posted)}</span>` : ""}${v ? `<span class="vpill v-${v[0]}">${v[1]}</span>` : ""}${j.new ? '<span class="chip new">New</span>' : ""}</div></div>
    <div class="dacts acts">${tailorBtns}${viewBtn}</div>
    <div class="dmarks">
      <button class="btn quiet" type="button" data-k="saved" aria-pressed="${s==="saved"}">${s==="saved" ? "★ Saved" : "☆ Save"}</button>
      <button class="btn quiet" type="button" data-k="applied" aria-pressed="${s==="applied"}">${s==="applied" ? "✓ Applied" : "Mark applied"}</button>
      <button class="btn quiet" type="button" data-k="hidden" aria-pressed="${s==="hidden"}">${s==="hidden" ? "Unhide" : "Not for me"}</button>${again}</div>
    ${wk && !tlBusy(wk) && (wk.state === "failed" || (wk.work || {}).error) ? `<div class="tlfail" role="alert">Tailoring failed: ${esc((wk.work || {}).error || "Something went wrong.")}</div>` : ""}
    <section class="dsec"><h3>How you stack up</h3><div class="dscores">
      ${!pvm && HASREL ? `<div class="dsc">${sv(j.rel, "Relevant")}<p><strong>Relevant</strong>How close this job is to the work you do. ${esc(j.rel_why || "")}${j.rel_why ? "." : ""}<br><a href="/profile#search">Change what Siftwell looks for</a></p></div>` : ""}
      ${pvm ? `<div class="dsc">${sv(sc, "Overall")}<p><strong>Overall</strong>Odds, pay and quality of life combined.</p></div>`
        : `<div class="dsc">${sv(j.appeal, "Appeal")}<div><p><strong>Appeal</strong>How well this job gives you what you want: pay, place, level, company and travel.</p>${ap ? `<details class="subw"><summary>Why</summary><div>Pay ${ap.pay} · Place ${ap.place} · Level ${ap.level} · Company ${ap.company} · Travel ${ap.burden}</div></details>` : ""}</div></div>`}
      <div class="dsc">${sv(m ?? "—", "Match", "m" + (m >= 70 ? " hi" : "") + (m == null ? " na" : ""))}<p><strong>Match</strong>${m == null ? (NOAI ? "Not rated: Match ratings come from Claude (see below)." : "Not rated yet.") : pvm ? `Your shot today with an honest tailored resume (after prep: ${j.pv_later}).` : `How well your resume matches what they want${asis != null && asis !== m ? ` (${asis} as written today)` : ""}.<br><span class="tiertag t-${j.ai_tier}">${esc(tierName(j))}</span>`}</p></div>
    </div></section>
    <section class="dsec dread"><h3>Claude's read</h3>${!unrated && (pvm ? j.pv_stale : j.ai_stale) && SERVED && !NOAI ? `<div class="ratefresh"><span class="old">Rated before your latest info</span><button class="btn sm" type="button" data-rate="1">Rate this job again</button></div>` : ""}${unrated && NOAI ? `<p class="nocl once">Claude's read, the Match rating and a tailored resume need Claude. ${NOAI_LINK}</p>` : unrated ? `<p>Claude hasn't read this one yet.</p>${SERVED && D.profile ? `<button class="btn" type="button" data-rate="1">Rate this job (about 30 seconds)</button>` : ""}` : read + (NOAI && !tl ? `<p class="nocl once">A tailored resume needs Claude. ${NOAI_LINK}</p>` : "")}</section>
    ${reqSection(j)}
    <section class="dsec"><h3>Pay</h3>${payBar(j)}</section>
    <section class="dsec"><h3>Details</h3><div class="chips">${levelChip(j)}${wpChip}${locs}${clr}${j.scif ? `<span class="chip onsite">SCIF</span>` : ""}${travelChip(j)}</div></section>
    <section class="dsec"><h3>About ${esc(j.company)}</h3>${coPanel(j)}</section>
    <section class="dsec"><h3>From the posting</h3><p class="snipp" id="dDesc">${esc(j.snippet || "")}${j.snippet ? "…" : j.lazy ? "Siftwell has this job’s title and place so far. Its full text is fetched when you ask for it." : ""}</p>${SERVED ? `<button class="btn ghost sm" type="button" id="dFull" style="margin-top:6px">Show the full posting</button>` : ""}</section>
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
    const jid = SEL;
    fetch("/api/desc?id=" + encodeURIComponent(jid)).then(r => r.json()).then(d => {
      // the text was only just fetched: its pay, level and workplace are read from it and shown right away (the
      // server has stored them, so the next rebuild of the board has them too)
      const j = d.job && (jobs.find(x => x.id === jid) || OFF.find(x => x.id === jid));
      if (j) { Object.assign(j, d.job); delete j.lazy; render(); }
      if (SEL === jid && $("dDesc")) { $("dDesc").textContent = d.desc || "The full posting isn't saved; use View posting."; const b = $("dFull"); if (b) b.remove(); }
    })
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
  if (!["ArrowDown","ArrowUp","j","k"].includes(e.key) || !$("view-tailored").hidden || e.target.closest("dialog, .rrpop, .amenu, .moresheet")) return;
  const ids = window.__shownIds || []; if (!ids.length) return;
  e.preventDefault();
  let i = ids.indexOf(SEL); i = (e.key === "ArrowDown" || e.key === "j") ? Math.min(ids.length - 1, i + 1) : Math.max(0, i - 1);
  select(ids[i], OPENED);
  const el = document.querySelector(`.jrow[data-id="${CSS.escape(ids[i])}"]`); if (el) el.scrollIntoView({block: "nearest"});
});
function render(){
  const q = $("q").value.trim().toLowerCase(), clr = $("clr").value, co = $("co").value, st = $("st").value;
  window.__reqHidden = 0; window.__lvlHidden = 0; window.__offHidden = 0; let hidN = 0;
  const lvlBand = msNow().seniority_band || [1, 7];
  let r = jobs.filter(j => {
    if (wp === "remote" && j.workplace !== "remote") return false;
    const offLvl = j.level != null && (j.level < lvlBand[0] || j.level > lvlBand[1]);
    if (!(lvlShown && offLvl) && !mySearchOk(j)) { if (offLvl) window.__lvlHidden++; return false; }
    if (lvlShown && offLvl && !mySearchOk(Object.assign({}, j, {level: null}))) return false;   // (still within your travel limit)
    if (co !== "all" && coOf(j) !== co) return false;
    if (j.off_list && !offShown && mode !== "pivot") { window.__offHidden++; return false; }
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
    else if (st === "active" && s === "hidden") { hidN++; return false; }
    else if (st === "hidden" && s !== st) return false;
    if (nlOn()) { if (!NL.rank.has(j.id)) return false; }
    else if (q && !(j.title+" "+j.company+" "+j.locations.join(" ")+" "+j.sector).toLowerCase().includes(q)) return false;
    return true;
  });
  const key = $("sort").value;
  const by = {rel: j => -((nlOn() ? NL.rank.get(j.id) || 0 : 0) * 1e3 + (mode === "pivot" ? (j.pv_score ?? 0) : j.score)),
    score: j => -(mode === "pivot" ? (j.pv_score ?? 0) : j.score),
    relevant: j => -(mode === "pivot" ? (j.pv_score ?? 0) : (j.rel ?? -1) * 1e3 + (j.appeal ?? 0)), appeal: j => -((j.appeal ?? 0) * 1e3 + (j.ai_fit ?? 0)),
    gd: j => -(gdWeighted(CI[j.company] || {}) * 1e6 + (j.salary_mid || 0) / 1e3), pay: j => -(j.salary_mid ?? 0), odds: j => -(((mode === "pivot" ? j.pv_now : j.ai_fit) ?? -1) * 1e6 + ((mode === "pivot" ? j.pv_later : j.ai_asis) ?? 0) * 1e3 + (j.salary_mid || 0) / 1e3),
    odds_later: j => -(((mode === "pivot" ? j.pv_later : j.ai_asis) ?? -1) * 1e6 + ((mode === "pivot" ? j.pv_now : j.ai_fit) ?? 0) * 1e3 + (j.salary_mid || 0) / 1e3), new: j => -(Date.parse(j.first_seen + "T00:00") || 0) - (Date.parse(j.posted) || 0)/1e6};
  r.sort((a,b) => by[key](a) - by[key](b));
  const base = mode === "pivot" ? pvJobs().length : jobs.filter(j => offShown || !j.off_list).length;
  const offN = mode === "pivot" || offShown ? 0 : OFF.length + jobs.filter(j => j.off_list).length;
  // jobs Claude would rate that have no rating yet (whole board, not just this filtered list)
  const notRated = !D.profile ? 0 : mode === "pivot" ? pvJobs().filter(j => j.pv_label == null && j.req_status !== "unmet").length : jobs.filter(j => j.ai_rs && j.ai_fit == null).length;
  // ratings made with older info, for the tab being shown (the Target tab has its own ratings, so its own count)
  const staleN = mode === "pivot" ? pvJobs().filter(j => j.pv_label != null && j.pv_stale).length : (D.ratings && D.ratings.stale_all) || 0;
  // The count line: "186 jobs · 5 hidden ▾", the reasons (each with its Show) behind the disclosure; Rate jobs beside it.
  const n = x => x.toLocaleString(), hidOpen = !!document.querySelector("#count .hidn[open]");
  const why = [];
  if (window.__reqHidden) why.push([window.__reqHidden, "need something you don't meet (a degree, license or similar)", "reqShow"]);
  if (offN) why.push([offN, "have titles that aren’t on your list (My profile, What Siftwell looks for); Claude doesn’t rate them", "offShow"]);
  if (window.__lvlHidden) why.push([window.__lvlHidden, "are at a level outside the one you chose in your search", "lvlShow"]);
  if (hidN) why.push([hidN, "you marked Not for me", "hidShow"]);
  const hidT = why.reduce((a, w) => a + w[0], 0);
  const pvEmpty = mode === "pivot" && !base;
  $("count").innerHTML = (pvEmpty ? "No jobs for your target yet" : `${n(r.length)} job${r.length === 1 ? "" : "s"}`) + (r.length > shown ? ` · showing ${n(shown)}` : "") +
    (hidT ? ` · <details class="hidn"${hidOpen ? " open" : ""}><summary>${n(hidT)} hidden</summary><ul>${why.map(([c, t, id]) => `<li><span>${n(c)} ${t}</span><button type="button" class="linkbtn" id="${id}">Show</button></li>`).join("")}</ul></details>` : "");
  drawChips();
  // Rate jobs: opens the rating panel; the number is how many jobs are waiting for a rating (none rated yet, or older info)
  const moreN = mode === "pivot" ? notRated + (NOAI ? 0 : staleN) : jobs.filter(j => j.ai_rs && (j.ai_fit == null || j.ai_stale)).length;
  $("rateMore").hidden = !SERVED || !D.profile || (!moreN && !NOAI) || pvEmpty;
  $("rateMore").innerHTML = NOAI ? "Rate jobs" : `Rate jobs${moreN ? ` · <span class="n">${n(moreN)}</span> waiting` : ""}`;
  $("rateMore").title = NOAI ? "Rating jobs needs Claude" : [notRated ? `${n(notRated)} not rated yet` : "", staleN ? `${n(staleN)} rated with older info` : ""].filter(Boolean).join(", ") + ". Claude rates a limited number in one go, the ones most relevant to your work first.";
  const page = r.slice(0, shown);
  window.__shownIds = page.map(j => j.id);
  if (!page.some(j => j.id === SEL)) { SEL = !window.matchMedia("(max-width:900px)").matches && page[0] ? page[0].id : null; if (!SEL) OPENED = false; }
  $("list").innerHTML = page.length ? page.map(card).join("") : pvEmpty
    ? `<li class="dempty"><b>No jobs fit your target yet</b>This tab collects jobs that are a step toward ${esc(D.target_name || "your target")}. They show up after the next Find new jobs. To change the target, go to <a href="/profile#target">My profile, Target</a>.</li>`
    : `<li class="dempty"><b>${PIN === "saved" ? "Nothing saved yet" : PIN === "applied" ? "No applications yet" : "No jobs match"}</b>${PIN === "saved" ? "Tap Save on any job to keep it here." : PIN === "applied" ? "Mark a job as applied and it moves here, so you can keep track." : (!nlOn() && SERVED && q.split(/\s+/).length > 1 ? "Press Enter to have Claude search for that description." : "Try removing a filter.")}</li>`;
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
      box.innerHTML = `<span class="clok">Signed in to Claude.</span> <span>${inSearch ? "Running your search now." : "Ratings pick up again the next time you find new jobs (Find new jobs, at the top)."}</span>`;
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
  else if (ready && NOAI) { NOAI = false; applyNoAI(false); $("aiBanner").hidden = false; $("aiBanner").textContent = "Claude is connected. Use Find new jobs (at the top) or Rate jobs to get Match ratings."; }
  if (d.logged_in && (D.ai_status === "cli_logged_out" || D.pivot_status === "cli_logged_out")) $("aiBanner").textContent = "Claude Code is signed in. Ratings pick up again the next time you find new jobs (Find new jobs, at the top).";
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
const QUICK = [["good", "Strong & worth tailoring"], ["remote", "Remote"], ["paid", "Pay listed"], ["new", "New"]];
function quickOn(k){
  if (k === "good") return $("lbl").value === "good";
  if (k === "remote") return wp === "remote";
  if (k === "paid") return $("paidonly").checked;
  if (k === "new") return $("newonly").checked;
}
function drawQuick(){
  $("lbl").closest(".field").hidden = NOAI && !hasMatch;  // the Fit filter is about Claude's verdicts
  $("quick").innerHTML = QUICK.filter(([k]) => (k !== "good" || (mode !== "pivot" && !(NOAI && !hasMatch)))).map(([k, l]) => `<button type="button" class="qc" data-qk="${k}" aria-pressed="${!!quickOn(k)}">${l}</button>`).join("");
}
$("quick").addEventListener("click", e => {
  const b = e.target.closest("button[data-qk]"); if (!b) return;
  const k = b.dataset.qk, on = !quickOn(k);
  if (k === "good") $("lbl").value = on ? "good" : "all";
  if (k === "remote") wp = on ? "remote" : "all";
  if (k === "paid") $("paidonly").checked = on;
  if (k === "new") $("newonly").checked = on;
  shown = 100; render();
});
function drawTabCounts(){
  const n = k => Object.values(status).filter(v => v === k).length;
  $("tab-saved").innerHTML = `Saved<span class="n">${n("saved")}</span>`;
  $("tab-applied").innerHTML = `Applied<span class="n">${n("applied")}</span>`;
}

// (The board's employer table moved to the Employers page: "Your employers (n) →" in the tab row.)

// ---- The employer directory on the board: one chooser used wherever employers can be added (the Start card, after a
// change of search area, "Try the directory again"). It never adds blindly: it says how many employers, about how
// many openings and how long the first check and the daily update take, lets the person take all or the top N, and
// offers to take the batch back afterwards. pv = GET /api/directory/preview.
const nf0 = x => (x || 0).toLocaleString();
function dirDefault(pv){
  const o = pv.options || []; if (!o.length) return null;
  const all = o[o.length - 1];
  if (all.employers <= 500) return all;
  return o.filter(x => x.limit && x.limit <= 500).pop() || o[0];
}
function dirChooser(pv, pre){
  const o = pv.options || [], def = dirDefault(pv);
  if (!def) return "";
  const lab = x => x.limit ? `The ${nf0(x.employers)} with the most openings near you` : `All ${nf0(x.employers)}`;
  const sel = o.length > 1 ? `<select id="${pre}Opt" aria-label="How many employers to add">${o.map(x => `<option value="${x.limit || "all"}"${x === def ? " selected" : ""}>${lab(x)}</option>`).join("")}</select>` : "";
  return `<span class="dchoose">${sel}<span id="${pre}Est" class="dest"></span></span>`;
}
function dirChooserWire(pv, pre){
  const o = pv.options || [], est = $(pre + "Est"); if (!est) return () => null;
  const cur = () => { const s = $(pre + "Opt"); const v = s ? s.value : (o[0].limit || "all"); return o.find(x => String(x.limit || "all") === String(v)) || o[o.length - 1]; };
  const say = () => { const x = cur(), b = pv.daily_before || {};
    est.textContent = `${x.jobs ? `About ${nf0(x.jobs)} openings near you. ` : ""}First check: ${x.first_text}. Daily Find new jobs afterwards: ${x.daily_text}${b.minutes && b.text !== x.daily_text ? ` (now ${b.text})` : ""}.`; };
  if ($(pre + "Opt")) $(pre + "Opt").addEventListener("change", say);
  say();
  return () => cur().limit || null;
}
function dirAdd(limit, retry){
  return fetch("/api/directory/apply", {method: "POST", headers: H, body: JSON.stringify({fetch: true, limit, retry: !!retry})}).then(r => r.json().then(d => ({ok: r.ok, d})));
}
function dirUndo(){ return fetch("/api/directory/undo", {method: "POST", headers: H, body: "{}"}).then(r => r.json().then(d => ({ok: r.ok, d}))); }
const dirPreview = refresh => fetch("/api/directory/preview" + (refresh ? "?refresh=1" : "")).then(r => r.json());

// ---- "Build my own directory" (localdir.py), offered wherever the shared directory can't be reached, or when the
// person chose a directory built on this computer and there is none yet. bd = plan.directory.build (first_search.plan).
const buildOffer = (bd, pre) => bd && bd.offer ? `<span class="dbuild">${esc(bd.offer)} <button type="button" class="btn sm" id="${pre}Build">Build my own directory</button></span>` : "";
function buildStart(btn, msg, then){
  btn.disabled = true; if (msg) msg.textContent = " Starting…";
  fetch("/api/localdir/start", {method: "POST", headers: H, body: JSON.stringify({add: "all", metered_ok: !!btn.dataset.meteredOk})}).then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
    if (!ok && d.metered && !btn.dataset.meteredOk) { btn.disabled = false; if (msg) msg.textContent = ""; appConfirm({title: "Build anyway?", text: d.error, ok: "Build anyway"}).then(yes => { if (yes) { btn.dataset.meteredOk = "1"; buildStart(btn, msg, then); } }); return; }
    if (!ok) { btn.disabled = false; if (msg) msg.textContent = " " + (d.error || "That didn’t work."); return; }
    if (msg) msg.textContent = " Started. Employers near you are added to your list as Siftwell finds them.";
    if (then) then(d);
  }).catch(() => { btn.disabled = false; if (msg) msg.textContent = " Couldn’t reach Siftwell. Try again."; });
}

// ---- Empty Jobs tab (this board has no jobs): "Start your job search" (never searched), its progress while it runs,
// or why nothing matched, with the usual fixes. State and plan come from /api/search (first_search.py). While
// anything runs, this card is the page's ONE progress indicator (the line is first_search.progress, the same on
// every page); the header's progress box and the check banner stay hidden on an empty board.
if (SERVED && !jobs.length) (function(){
  const box = $("startCard"); let sawRun = false, lastSig = "", fails = 0, PV = null, pvFor = "", getLimit = () => null;
  const n = x => (x || 0).toLocaleString();
  const show = html => { box.innerHTML = html; box.hidden = false; $("view-jobs").classList.add("nojobs"); };
  function load(){
    fetch("/api/search").then(r => r.json()).then(s => { fails = 0; draw(s); })
      .catch(() => { if (++fails >= 3) dead(); setTimeout(load, 5000); });
  }
  function dead(){
    if (lastSig === "dead") return; lastSig = "dead";
    show(`<h2 id="scTitle">Siftwell isn’t running</h2><p>This page can’t reach Siftwell on this computer, so nothing here is being updated. Open Siftwell again, then reload this page. A job search that was running carries on where it stopped.</p><div class="sacts"><button class="btn sm" type="button" onclick="location.reload()">Reload this page</button></div>`);
  }
  const titleTip = p => p.titles === false ? `<p class="dmsg"><b>Tell Siftwell what work you do</b> to see the most relevant jobs first: add your job title on <a href="/profile#search">My profile</a>. Without one, every kind of job is kept.</p>` : "";
  // the directory's preview for this search area (asked once per area; again after "Try the directory again")
  function wantPreview(p, redraw){
    const d = p.directory || {}, key = [d.label, d.radius, d.remote_only, d.applied, p.companies].join("|");
    if (!d.possible || pvFor === key) return;
    pvFor = key; PV = null;
    dirPreview(false).then(pv => { if (pvFor === key) { PV = pv; lastSig = ""; redraw(); } }).catch(() => {});
  }
  function draw(s){
    const p = s.plan, f = p.find, job = s.mine ? s.job : {}, ck = p.check || {}, pg = s.progress || {};
    if (s.running) {
      sawRun = true;
      const line = esc(pg.line || "Getting ready…"), pct = Math.round(100 * (pg.frac == null ? .03 : pg.frac)), staged = pg.kind === "check" && pg.mine;
      const extra = job.dir_offline && job.dir_text ? `<p class="dmsg">${esc(job.dir_text)}</p>` : "";
      const sig = [line, pct, staged, !!pg.can_pause, extra].join("|");
      if (sig !== lastSig) {   // (only redraw when something changed, so the Pause button keeps its focus)
        lastSig = sig;
        show(`<h2 id="scTitle">Your job search is running</h2><p>${line}</p><div class="prog" role="progressbar" aria-label="Job search progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>${extra}<p>${staged ? "Siftwell checks the employers with the most openings near you first, and jobs that fit show up here every few minutes." : "Your jobs show up here when it’s done."} You can leave this page; the search keeps going as long as Siftwell is running${staged ? ", and if it stops you can continue where it left off" : ""}.</p>${staged && pg.can_pause ? `<div class="sacts"><button class="btn sm" type="button" id="scPause">Pause</button></div>` : ""}`);
        if ($("scPause")) $("scPause").addEventListener("click", () => { $("scPause").disabled = true; fetch("/api/search/pause", {method: "POST", headers: H, body: "{}"}).then(load).catch(() => {}); });
      }
      if (staged) fetch("/api/profile/board" + pq()).then(r => r.json()).then(b => { if (b.jobs > 0 && !b.rebuilding) { saveFilters(); location.reload(); } }).catch(() => {});
      setTimeout(load, 3000);
      return;
    }
    if (sawRun) { saveFilters(); location.reload(); return; }  // it finished: show the new board
    const err = job.error ? `<p class="smsg">${esc(job.error)}</p>` : "";
    const d = p.directory || {}, bd = d.build || {};
    wantPreview(p, () => draw(s));
    const sig = JSON.stringify([p.started_before, ck, p.companies, s.why_empty, job.error, job.note, PV, Object.assign({}, d, {build: [bd.running, bd.offer]})]);
    if (sig === lastSig) { if ($("scBuildLine")) $("scBuildLine").textContent = bd.line || ""; setTimeout(load, bd.running ? 4000 : 15000); return; }
    lastSig = sig;
    const pvOk = PV && PV.available, pvNew = pvOk ? PV.new : 0;
    const offline = PV && !PV.available && (PV.reason === "offline" || PV.reason === "error");
    // the directory built on this computer: its progress line while it runs; the offer when the shared one can't be
    // reached (or was switched off) and there is nothing built yet
    const buildLine = bd.running ? `<p class="dmsg"><b id="scBuildLine">${esc(bd.line)}</b>. Siftwell is reading employers’ public job pages on this computer (no Claude); the ones hiring near you ${p.started_before ? "are added to your list, and their jobs checked, as it finds them" : "are added to your list as it finds them"}. You can pause it in <a href="/settings#directory">Settings</a>.</p>` : "";
    const wantBuild = !bd.running && !!bd.offer && (offline || d.offline || bd.source !== "shared");
    const buildP = wantBuild ? `<p class="dmsg">${buildOffer(bd, "sc")}<span id="scBuildMsg" role="status"></span></p>` : "";
    const wireBuild = () => { if ($("scBuild")) $("scBuild").addEventListener("click", () => buildStart($("scBuild"), $("scBuildMsg"), () => { lastSig = ""; pvFor = ""; setTimeout(load, 1200); })); };
    if (!p.started_before) {
      const nothing = !p.companies && !p.catalog && !d.possible && !f.possible;
      let dirLine = "";
      if (d.possible && !PV) dirLine = `<p>Looking up employers ${d.remote_only ? "that hire remotely" : "near " + esc(d.label)} in Siftwell’s free employer directory…</p>`;
      else if (pvOk && pvNew) dirLine = `<p><b>${n(pvNew)} employers</b> ${d.remote_only ? "that hire remotely" : `with openings within ${d.radius} miles of ${esc(d.label)}`} are in ${bd.source === "local" ? "the employer directory built on this computer" : "Siftwell’s free employer directory"} (no Claude needed). Which ones should Siftwell add and check?</p><div class="sacts">${dirChooser(PV, "sc")}</div>`;
      else if (pvOk && bd.source === "local" && !bd.built) dirLine = bd.running ? "" : `<p class="dmsg"><b>Your employer directory hasn’t been built on this computer yet.</b> If you start anyway, Siftwell builds it now and begins with a starter list of large US employers that comes with the app, keeping the ones hiring near you.</p>`;
      else if (pvOk) dirLine = `<p>${bd.source === "local" ? "The employer directory built on this computer" : "Siftwell’s free employer directory"} has no new employers ${d.remote_only ? "for remote work" : "near " + esc(d.label)} right now.</p>`;
      else if (offline && bd.running) dirLine = "";
      else if (offline) dirLine = `<p class="dmsg"><b>Siftwell can’t reach its employer directory right now.</b> Check your internet connection and <button type="button" class="linkbtn" id="scRetry">try the directory again</button>. If you start anyway, Siftwell begins with a starter list of large US employers that comes with the app, and keeps the ones hiring near you.</p>`;
      dirLine += buildLine + buildP;
      const what = `check the career pages of ${p.companies ? `the ${n(p.companies)} employers you already watch${d.possible ? " and the ones it adds" : ""}` : d.possible ? "the employers it adds" : "your employers"}, the ones with the most openings near you first, and keep the jobs that fit your search${p.claude ? "; Claude then rates the best matches" : ""}`;
      show(`<h2 id="scTitle">Start your job search</h2>
        <p>Siftwell hasn’t looked for jobs for you yet. When you start, it will ${what}. Jobs start to show up within a few minutes; you can leave this page while it runs.</p>
        ${dirLine}
        ${f.possible ? `<label class="chk"><input type="checkbox" id="scFind"${f.default ? " checked" : ""}><span>Also find more ${f.remote_only ? "remote-friendly employers in your field" : "employers near " + esc(f.label)} with Claude (optional): Claude searches the web, using your Claude plan; ${esc(f.estimate)}</span></label>` : ""}
        ${f.reason === "no_place" ? `<p>Add your home ZIP (<a href="/profile#search">My profile, Job search</a>) so Siftwell can add employers near you.</p>` : ""}
        ${nothing ? `<p><b>There are no employers to check yet.</b> Add your home ZIP, or add an employer by its careers link.</p>` : ""}
        ${titleTip(p)}
        <div class="sacts"><button class="btn primary" type="button" id="scGo"${nothing ? " disabled" : ""}>Start my job search</button>${nothing ? `<a class="btn" href="/catalog#companies">Add an employer by link</a>` : ""}</div>
        <div class="smsg" id="scMsg" role="status"></div>${err}`);
      getLimit = pvOk && pvNew ? dirChooserWire(PV, "sc") : () => null;
      wireBuild();
      if ($("scRetry")) $("scRetry").addEventListener("click", () => { $("scRetry").disabled = true; dirPreview(true).then(pv => { PV = pv; lastSig = ""; draw(s); }).catch(() => { lastSig = ""; draw(s); }); });
      $("scGo").addEventListener("click", () => {
        const fb = $("scFind"); $("scGo").disabled = true; $("scMsg").textContent = "";
        fetch("/api/search/start", {method: "POST", headers: H, body: JSON.stringify({find: !!(fb && fb.checked), directory: true, limit: getLimit()})})
          .then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
            if (!ok) { $("scGo").disabled = false; $("scMsg").textContent = d.error || "The search couldn’t start."; return; }
            lastSig = ""; load();
          }).catch(() => { $("scGo").disabled = false; $("scMsg").textContent = "Couldn’t reach Siftwell. Try again."; });
      });
      setTimeout(load, bd.running ? 4000 : 15000);
      return;
    }
    const note = job.note && !bd.running ? `<p class="dmsg">${esc(job.note)}</p>` : "";
    const after = ({ok, d}) => {
      const m = $("scDirMsg"); if (!m) return;
      if (!ok) { ["scDir", "scRetry"].forEach(i => { if ($(i)) $(i).disabled = false; }); m.textContent = " " + (d.error || "That didn’t work."); return; }
      const k = (d.added || 0) + (d.linked || 0);
      m.textContent = k ? ` Added ${n(k)} to your employers${d.fetching ? "; checking their openings now" : ""}.` : " No new employers near you in the directory right now.";
      lastSig = ""; pvFor = ""; setTimeout(load, 1500);
    };
    const wireDir = () => {
      wireBuild();
      if ($("scDir")) $("scDir").addEventListener("click", () => { $("scDir").disabled = true; $("scDirMsg").textContent = " Adding…"; dirAdd(getLimit(), false).then(after).catch(() => after({ok: false, d: {error: "Couldn’t reach Siftwell. Try again."}})); });
      // Try the directory again: look first (nothing is added blindly); when it answers, the card offers its employers
      if ($("scRetry")) $("scRetry").addEventListener("click", () => {
        $("scRetry").disabled = true; if ($("scDirMsg")) $("scDirMsg").textContent = " Trying…";
        dirPreview(true).then(pv => {
          if (!pv.available) return after({ok: false, d: {error: "Still can’t reach the directory. Check your internet connection and try again."}});
          PV = pv; lastSig = ""; draw(s);
        }).catch(() => after({ok: false, d: {error: "Couldn’t reach Siftwell. Try again."}}));
      });
    };
    const offNote = pvOk && pvNew && d.offline ? `<p class="dmsg">Siftwell’s employer directory can be reached now: it has <b>${n(pvNew)} employers</b> ${d.remote_only ? "that hire remotely" : `within ${d.radius} miles of ${esc(d.label)}`}. ${dirChooser(PV, "sc")} <button type="button" class="btn sm primary" id="scDir">Add them</button><span id="scDirMsg" role="status"></span></p>`
      : (d.offline || offline) && !bd.running ? `<p class="dmsg"><b>Siftwell couldn’t reach its employer directory</b>, so ${p.companies ? "your list is the starter list of large US employers that comes with the app, not the employers near you" : "no employers near you were added"}. When you are online, <button type="button" class="linkbtn" id="scRetry">try the directory again</button>.<span id="scDirMsg" role="status"></span></p>${buildP}` : buildLine + buildP;
    if (ck.pending > 0) {   // the first check didn't get through every employer (paused, stopped or restarted)
      show(`<h2 id="scTitle">${ck.done ? "No jobs that fit yet" : "Your employers haven’t been checked yet"}</h2>
        <p>${ck.done ? `Siftwell has checked ${n(ck.done)} of your ${n(ck.total)} employers so far, and none of their openings fit your search. ` : `None of your ${n(ck.total)} employers has been checked yet. `}${ck.done ? `${n(ck.pending)} ${ck.pending === 1 ? "is" : "are"} still to check.` : ""}</p>
        ${job.dir_offline ? "" : note}${offNote}${titleTip(p)}
        <div class="sacts"><button class="btn primary" type="button" id="scCont">${ck.done ? "Continue checking" : "Check my employers"}</button></div>
        <div class="smsg" id="scMsg" role="status"></div>${err}`);
      $("scCont").addEventListener("click", () => {
        $("scCont").disabled = true; $("scMsg").textContent = "";
        fetch("/api/search/continue", {method: "POST", headers: H, body: "{}"})
          .then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
            if (!ok && !/already/i.test(d.error || "")) { $("scCont").disabled = false; $("scMsg").textContent = d.error || "That didn’t work."; return; }
            lastSig = ""; load();
          }).catch(() => { $("scCont").disabled = false; $("scMsg").textContent = "Couldn’t reach Siftwell. Try again."; });
      });
      getLimit = pvOk && pvNew && $("scEst") ? dirChooserWire(PV, "sc") : () => null;
      wireDir();
      setTimeout(load, bd.running ? 4000 : 15000);
      return;
    }
    // Everything was checked and nothing fits: say why, then what to do, the most useful fix first.
    const fixes = [];
    if (bd.running) fixes.push(`<b id="scBuildLine">${esc(bd.line)}</b>. Siftwell is reading employers’ public job pages on this computer; the ones hiring near you are added to your list, and their jobs checked, as it finds them.`);
    else if (!(pvOk && pvNew) && (d.offline || offline)) fixes.push(`<b>Siftwell couldn’t reach its employer directory</b>, so ${p.companies ? "your list is only the starter list of large US employers that comes with the app" : "no employers near you were added"}. Check your internet connection, then <button type="button" class="linkbtn" id="scRetry">try the directory again</button>.<span class="dmsg" id="scDirMsg" role="status"></span>` + (wantBuild ? `<br>${buildOffer(bd, "sc")}<span class="dmsg" id="scBuildMsg" role="status"></span>` : ""));
    else if (wantBuild && !(pvOk && pvNew)) fixes.push(`${buildOffer(bd, "sc")}<span class="dmsg" id="scBuildMsg" role="status"></span>`);
    else if (pvOk && pvNew) fixes.push(`<b>${n(pvNew)} more employers</b> ${d.remote_only ? "that hire remotely" : `within ${d.radius} miles of ${esc(d.label)}`} are in Siftwell’s free employer directory. ${dirChooser(PV, "sc")} <button type="button" class="btn sm primary" id="scDir">Add them</button><span class="dmsg" id="scDirMsg" role="status"></span>`);
    if (p.titles === false) fixes.push(`<a href="/profile#search">Tell Siftwell what work you do</a>: with your job title it can pick out the jobs that are relevant to you.`);
    else fixes.push(`<a href="/profile#search">Add more job titles</a> (My profile, then Job search): only jobs with a title like yours are kept.`);
    fixes.push(`<a href="#filters">Widen your search</a>: a bigger radius, allow remote work, or a lower pay floor (Filters, then Your search). Siftwell then offers the employers in the wider area.`);
    fixes.push(`<a href="/catalog#find">Find more employers with Claude</a>: Claude looks up employers in your area${p.claude ? "" : " (needs Claude)"}, and you add the ones Siftwell can read.`);
    fixes.push(`<a href="/catalog#companies">Add an employer by its careers link</a>.`);
    show(`<h2 id="scTitle">${p.companies ? "No jobs matched your search" : "There are no employers to check yet"}</h2>
      <p>${esc(s.why_empty || "None of your employers’ openings fit your search right now.")} Things that usually help:</p>
      ${note}<ul>${fixes.map(x => `<li>${x}</li>`).join("")}</ul>${err}`);
    getLimit = pvOk && pvNew ? dirChooserWire(PV, "sc") : () => null;
    wireDir();
    setTimeout(load, bd.running ? 4000 : 15000);
  }
  load();
})();

let PIN = "";
function route(){
  if (location.hash === "#filters") {  // links from My profile and the Start card: the Jobs tab with the Filters panel (and its Your search card) open
    history.replaceState(null, "", location.pathname + location.search + "#jobs");
    $("fPanel").hidden = false; $("filtersBtn").setAttribute("aria-expanded", "true"); syncFbar();
  }
  if (location.hash === "#companies") { location.replace("/catalog?mine=1#companies"); return; }   // (the old Companies tab: the Employers page now)
  if (location.hash === "#pivot" && !D.pivot_enabled) { history.replaceState(null, "", location.pathname + location.search + "#jobs"); }
  const v = {"#pivot": "pivot", "#tailored": "tailored", "#saved": "saved", "#applied": "applied"}[location.hash] || "jobs";
  PIN = v === "saved" || v === "applied" ? v : "";
  closeDetail(true);
  $("view-jobs").hidden = v === "tailored"; $("view-tailored").hidden = v !== "tailored";
  ["jobs","pivot","saved","applied","tailored"].forEach(t => $("tab-" + t).setAttribute("aria-current", v===t ? "page" : "false"));
  if (v === "tailored") drawTailored();
  const m = v === "pivot" ? "pivot" : "current";
  if (m !== mode || !$("lbl").options.length) { mode = m; gapSel = ""; setLabelOptions(); shown = 100; }
  $("pvPanel").hidden = mode !== "pivot";
  $("sortScore").textContent = mode === "pivot" ? "Best bets (Overall)" : "Best bets (Appeal and Match together)";
  $("sortLater").textContent = mode === "pivot" ? "Best Match after I prepare" : "Best Match with my resume as it is";
  $("sortOdds").textContent = mode === "pivot" ? "Best Match today" : "Best Match (Claude’s rating)";
  $("sortRelevant").hidden = $("sortRelevant").disabled = mode === "pivot" || !HASREL;
  if ($("sortRelevant").disabled && $("sort").value === "relevant") $("sort").value = "score";
  $("legend").hidden = mode === "pivot"; $("pvLegend").hidden = mode !== "pivot";
  $("legend2").innerHTML = mode === "pivot"
    ? "<b>Overall</b> = how worth pursuing a job is: 50% odds (60% today, 40% after prep) + 30% pay + 20% quality of life; <b>Best bets</b> on this tab orders by it. <b>Match</b> = your shot today with an honest tailored resume (Claude's 0 to 100 rating; 70+ is a genuine shot; it's a rating, not a probability). Hover it for the after-prep number."
    : (HASREL ? "<b>Relevant</b> = how close a job is to the work you do: its title against your job titles, other names for them, one step up and related roles, plus your skills found in the posting. Worked out by Siftwell itself for every job (no Claude); see and change the list under My profile, Job search. " : "") + "<b>Appeal</b> = how well a job gives you what you want, worked out from the posting and company facts: 40% pay (against your floor, or against the other jobs on your board when you have no floor), 20% workplace and distance, 15% level, 15% company (employee reviews, layoffs), 10% travel and clearance burden (the job's details show each part under Why). <b>Match</b> = how well your resume, honestly tailored, meets what they ask for (Claude's 0 to 100 rating; 70+ is a genuine shot; it's a rating, not a probability). Claude rates a limited number of jobs each run, the most relevant first: a quick check, then a careful look at the best of those, then its best judgment on the top ones; a hollow dot means a quick check, a filled dot a careful look, no dot best judgment. <b>Best bets</b> (the default order) ranks jobs high on both Appeal and Match; a job Claude hasn't rated yet is placed by its Relevance instead.";
  if (mode === "pivot") drawPivotPanel();
  render();
}
// ---- company filters (researched facts; unknown values are excluded once a filter is set, except "or unrated")
const CF_IDS = ["cType", "cSize", "cVal", "cAge", "cGd", "cLay", "cEq"];
const CF_LABEL = {cType: "", cSize: "Size: ", cVal: "Value: ", cAge: "", cGd: "Reviews ", cLay: "Layoffs: ", cEq: ""};
// A filter is offered only when the catalog has that fact for at least one employer on this board, and the whole
// Employer group goes when none is. The "AI company" choices exist only for a profile whose target is still limited
// to AI companies (an earlier version's option).
(function(){
  const cs = Object.values(CI), any = f => cs.some(f);
  const has = {cType: any(c => c.ownership), cSize: any(c => c.employees != null), cVal: any(c => c.value_usd != null), cAge: any(c => c.founded),
    cGd: any(c => c.gd_rating != null), cLay: any(c => c.layoffs), cEq: any(c => c.ownership === "public" || c.ownership === "private" || c.equity)};
  if (D.ai_scope && jobs.some(j => j.ai_track)) {
    has.cType = true;
    $("cType").insertAdjacentHTML("beforeend", (jobs.some(j => j.ai_track === "lab") ? `<option value="lab">Frontier AI lab</option>` : "") + `<option value="ai">AI company</option>`);
  }
  let n = 0;
  for (const id of CF_IDS) { $(id).closest(".field").hidden = !has[id]; n += has[id] ? 1 : 0; }
  $("cfGroup").hidden = $("cfGrid").hidden = !n;
})();
function companyOk(j){
  const c = CI[j.company] || {}, v = id => $(id).value;
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
// Clear filters: back to these. It never touches the saved search (the Your search card).
const FDEF = () => ({clr: PREFS["display.clearance"] || "all", st: "active", co: "all", lbl: mode === "pivot" ? "noskip" : "all"});
const optText = id => { const o = $(id).selectedOptions[0]; return o ? o.textContent : ""; };
function activeFilters(){
  const out = [];
  if (wp === "remote") out.push(["wp", "Remote"]);
  for (const id of ["lbl", "clr", "co"]) if ($(id).value !== "all") out.push([id, optText(id)]);
  for (const id of CF_IDS) if ($(id).value !== "all") out.push([id, CF_LABEL[id] + optText(id)]);
  if ($("st").value !== "active") out.push(["st", "Show: " + optText("st")]);
  for (const [id, t] of [["paidonly", "Pay listed"], ["nowide", "No wide pay bands"], ["newonly", "New"], ["reqall", "Including requirements I don't meet"]]) if ($(id).checked) out.push([id, t]);
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
  wp = "all"; gapSel = ""; lvlShown = false;
  shown = 100; if (mode === "pivot") drawPivotPanel(); render();
});

const FILTER_IDS = ["q","clr","co","st","sort","paidonly","newonly","reqall","nowide","cType","cSize","cVal","cAge","cGd","cLay","cEq"];
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
    if (!$("st").value) $("st").value = "active";   // (Show: Saved / Applied are the Saved and Applied tabs now)
    if (!$("clr").value) $("clr").value = "all";
    if (sv.nl && $("q").value.trim() === sv.nl.q) nlSet(sv.nl);
    if (!(NL ? ["rel"] : []).concat(["score","relevant","appeal","odds","odds_later","pay","gd","new"]).includes($("sort").value) || [...$("sort").options].some(o => o.value === $("sort").value && o.disabled)) $("sort").value = "score";
    $("lbl").value = sv.lbl; wp = sv.wp === "remote" ? "remote" : "all";  // an older "Near me" (dmv) value is ignored
    if (sv.fp) { $("fPanel").hidden = false; $("filtersBtn").setAttribute("aria-expanded", "true"); syncFbar(); }
    render(); setTimeout(() => scrollTo(0, sv.y || 0), 60);
  }
} catch(e) {}
if (!jobs.length && !D.profile) { $("aiBanner").hidden = false; $("aiBanner").innerHTML = `New profile: <a href="/profile#resume">${NOAI ? "fill in your profile" : "upload a resume"} on My profile</a>. Once it's approved, Find new jobs fills this board.`; }

function noClaudeBanner(signIn){
  if (!jobs.length && !D.profile) return;  // the "New profile" prompt is more useful until there is a profile
  const b = $("aiBanner"); b.hidden = false;
  b.innerHTML = `<span><b>${NOAI_MSG}</b> → ${NOAI_LINK}. Siftwell still finds and filters jobs and ranks them by ${HASREL ? "how relevant they are to your work, then by Appeal" : "Appeal"}.</span>` +
    (signIn && SERVED ? ` <button class="btn sm primary" type="button" data-cl="start">Sign in to Claude</button>` : "");
}
// Re-applies everything that depends on whether Claude is connected (also when the live check disagrees with the board).
function applyNoAI(signIn){
  ["odds", "odds_later"].forEach(v => { const o = $("sort").querySelector(`option[value=${v}]`); o.hidden = o.disabled = NOAI && !hasMatch; });
  if (NOAI && !hasMatch && ["score", "odds", "odds_later"].includes($("sort").value)) $("sort").value = NOMATCH_SORT();
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
else if (D.ai_status === "no_key") { $("aiBanner").hidden = false; $("aiBanner").textContent = "Claude fit scoring is off. Add an Anthropic API key in Settings, then use Find new jobs (at the top)."; }
else if (D.ai_status === "bad_key") { $("aiBanner").hidden = false; $("aiBanner").textContent = "The saved Anthropic API key was rejected. Replace it in Settings, then use Find new jobs (at the top)."; }

// ---- Notices: at most one at a time, the most useful first; the others wait behind "N more notices". (The progress
// line, #progress and #chkBanner, is never folded away.)
(function(){
  const ORDER = ["dirBanner", "aiBanner", "ttlBanner", "updBanner", "gsBanner"].map($).filter(Boolean);
  let open = false;
  const sync = () => {
    const vis = ORDER.filter(b => !b.hidden), more = vis.length - 1;
    vis.forEach((b, i) => b.classList.toggle("stk", !open && i > 0));
    ORDER.filter(b => b.hidden).forEach(b => b.classList.remove("stk"));
    $("bnMore").hidden = more < 1;
    $("bnMoreBtn").textContent = open ? "Show fewer notices" : `${more} more notice${more === 1 ? "" : "s"}`;
    $("bnMoreBtn").setAttribute("aria-expanded", String(open));
  };
  $("bnMoreBtn").addEventListener("click", () => { open = !open; sync(); });
  if (window.MutationObserver) { const mo = new MutationObserver(sync); ORDER.forEach(b => mo.observe(b, {attributes: true, attributeFilter: ["hidden"]})); }
  sync();
})();

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
  // "Rate jobs" in the count line opens the same panel as the header's Rate jobs button (rrOpen, below).

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
      if (s.error) {  // say why right here, in plain sight (the redraw below keeps it under the buttons)
        btn.textContent = "Tailoring failed · Try again"; btn.title = "";
        let n = btn.parentNode && btn.parentNode.parentNode ? btn.parentNode.parentNode.querySelector(".tlfail") : null;
        if (!n && btn.parentNode) { n = document.createElement("div"); n.className = "tlfail"; n.setAttribute("role", "alert"); btn.parentNode.insertAdjacentElement("afterend", n); }
        if (n) n.textContent = "Tailoring failed: " + s.error;
        refreshTailored(); return;
      }
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
      appConfirm({title: "Remove this tailored resume?", text: `The resume for ${del.dataset.title || "this job"} is deleted from this computer (its PDF and Word files too). This can't be undone; you can tailor a new one later.`, ok: "Remove it", danger: true}).then(yes => {
      if (!yes) return;
      del.disabled = true; del.textContent = "Removing…";
      fetch("/api/tailored/delete", {method: "POST", headers: H, body: JSON.stringify({person: PID, slug: del.dataset.del})})
        .then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
          if (!ok) { del.disabled = false; del.textContent = d.error || "Couldn't remove"; return; }
          loadTailored().then(() => { drawTailored(); render(); });
        });
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
  // ONE progress indicator. The words come from the server (first_search.progress: the same plain line on every page).
  //  - a board with no jobs: the Start card shows it (above), so nothing is drawn here;
  //  - the staged first check: the slim banner (the board stays usable and offers the new jobs instead of reloading
  //    under the reader), with Pause, and Continue checking when it stopped part-way;
  //  - Find new jobs: the progress box, with that line and a bar. The fetch's raw output is never shown here
  //    (Employers page, Runs and updates, Details).
  let chkWas = false, chkOff = false, chkSig = "", pollFails = 0, EST = null;
  function drawCheck(s){
    const c = s.check, b = $("chkBanner"), pg = s.progress || {};
    if (!c || !jobs.length) { b.hidden = true; return !!(c && c.running); }
    const n = x => (x || 0).toLocaleString();
    const fresh = c.board_at && String(c.board_at) !== String(BOARD_AT || c.board_at);
    if (BOARD_AT == null) BOARD_AT = c.board_at;
    const act = (id, label, url) => { const e = $(id); if (e) e.addEventListener("click", () => { e.disabled = true; fetch(url, {method: "POST", headers: H, body: "{}"}).then(() => { chkSig = ""; poll(); }).catch(() => { e.disabled = false; }); }); };
    let html = "";
    if (c.running) {
      chkWas = chkWas || !!c.mine;
      html = `<span>${esc(pg.line || "Checking employers…")}</span>`
           + (c.mine && fresh ? `<button class="btn sm primary" type="button" id="chkShow">Show new jobs</button>` : "")
           + (c.mine && pg.can_pause ? `<button class="btn sm ghost" type="button" id="chkPause">Pause</button>` : "");
    } else if (c.pending > 0 && !chkOff && !s.running) {
      html = `<span>${c.paused ? "Paused. " : ""}Siftwell has checked ${n(c.done)} of your ${n(c.total)} employers. ${n(c.pending)} still to check.</span>`
           + (fresh ? `<button class="btn sm" type="button" id="chkShow">Show new jobs</button>` : "")
           + `<button class="btn sm primary" type="button" id="chkCont">Continue checking</button><button class="btn sm ghost" type="button" id="chkHide">Not now</button>`;
    } else if (chkWas && fresh) {
      html = `<span>Siftwell finished checking employers.</span><button class="btn sm primary" type="button" id="chkShow">Show new jobs</button>`;
    }
    if (html !== chkSig) {
      chkSig = html; b.innerHTML = html; b.hidden = !html;
      if ($("chkShow")) $("chkShow").addEventListener("click", () => { saveFilters(); location.reload(); });
      if ($("chkHide")) $("chkHide").addEventListener("click", () => { chkOff = true; chkSig = ""; b.hidden = true; });
      act("chkPause", "", "/api/search/pause"); act("chkCont", "", "/api/search/continue");
    }
    return !!c.running;
  }
  let BOARD_AT = null;
  // What Find new jobs will check and how long it takes, from the real employer list (first_search.estimates).
  const estMine = () => !!EST && EST.profiles > 1 && EST.mine.companies < EST.all.companies;
  function estText(){
    if (!EST) return "check your employers for new openings";
    const e = estMine() ? EST.mine : EST.all;
    return `check ${estMine() ? "your" : "all"} ${e.companies.toLocaleString()} employer${e.companies === 1 ? "" : "s"} for new openings (${e.text})`;
  }
  // after Stop: the boards are rebuilt from what the fetch had finished; reload when that is done
  function stopWatch(){
    let seen = false, tries = 0, at0;
    const tick = () => fetch("/api/status" + pq()).then(r => r.json()).then(s => {
      const at = s.check && s.check.board_at;
      if (at0 === undefined) at0 = at;
      if (s.recomputing) seen = true;
      if ((seen && !s.recomputing) || (at && String(at) !== String(at0)) || ++tries > 40) { saveFilters(); return void location.reload(); }
      setTimeout(tick, 3000);
    }).catch(() => setTimeout(tick, 5000));
    setTimeout(tick, 2500);
  }
  $("updStop").addEventListener("click", () => {
    $("updStop").disabled = true;
    fetch("/api/update/stop", {method: "POST", headers: H, body: "{}"}).then(() => { $("updStop").disabled = false; poll.now && poll.now(); }).catch(() => { $("updStop").disabled = false; });
  });
  function serverDown(){
    const b = $("chkBanner"), html = `<span><b>Siftwell isn’t running.</b> This page can’t reach it, so nothing here is being updated and the buttons won’t work. Open Siftwell again, then reload this page.</span><button class="btn sm" type="button" onclick="location.reload()">Reload</button>`;
    if (!jobs.length || chkSig === html) return;
    chkSig = html; b.innerHTML = html; b.hidden = false; $("progress").hidden = true;
  }
  function poll(){
    fetch("/api/status" + pq()).then(r => r.json()).then(s => {
      pollFails = 0;
      const pg = s.progress || {active: !!s.running, line: "Finding new jobs…", frac: null};
      EST = s.estimate || EST;
      if (s.next_run) { const n = new Date(s.next_run); $("nextRun").textContent = "· finds new jobs again " + (n.toDateString() === new Date().toDateString() ? "today " : "tomorrow ") + n.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}); }
      else $("nextRun").textContent = "";
      // Claude was connected after this board was built: ask for a rebuild once, and reload when it is there, so
      // "needs Claude" doesn't stay on the buttons until the first rating run
      if (NOAI && s.claude_ready && SERVED) {
        const at = s.check && s.check.board_at;
        if (window.__clAt === undefined) { window.__clAt = at || null; fetch("/api/board/refresh", {method: "POST", headers: H, body: "{}"}).catch(() => {}); }
        else if (at && String(at) !== String(window.__clAt) && !s.recomputing) { saveFilters(); return void location.reload(); }
      }
      const staged = drawCheck(s);
      if (staged || !jobs.length) {   // the banner (or, on an empty board, the Start card) is the one indicator
        const busy = staged || (!!pg.active && pg.blocking !== false);   // (building the directory doesn't hold Find new jobs up)
        $("updateBtn").disabled = busy; $("updateBtn").classList.toggle("busy", busy);
        $("updSmall").textContent = busy ? "checking employers…" : estText(); $("updateBtn").title = busy ? (pg.line || "Checking employers…") : "Find new jobs: " + estText();
        if (!pollRerate.was) $("progress").hidden = true;
        if (staged) wasRunning = false;
        else if (wasRunning && !s.running) { wasRunning = false; if (s.exit === 0) { saveFilters(); return void location.reload(); } }
        else if (s.running) wasRunning = true;
        return void setTimeout(poll, 3000);
      }
      $("updateBtn").disabled = s.running; $("updateBtn").classList.toggle("busy", !!s.running);
      $("updSmall").textContent = s.running ? "running now…" : estText();
      $("updateBtn").title = s.running ? "Finding new jobs now…" : "Find new jobs: " + estText();
      if (s.running) {
        if (!wasRunning) scrollTo(0, 0);
        wasRunning = true; $("progress").hidden = false;
        $("progTitle").textContent = s.stopping ? "Stopping… what was found so far is kept" : (pg.line || "Finding new jobs…");
        $("progNote").textContent = "";
        $("updStop").hidden = !pg.can_stop || !!s.stopping;
        $("progBar").style.width = Math.round(100 * (pg.frac == null ? .04 : pg.frac)) + "%";
        $("progLog").textContent = "";
        setTimeout(poll, 2000);
      } else if (pg.active && pg.kind !== "idle") {  // something else holds things up (Claude finding employers, a job from before a restart)
        bgShown = true; $("progress").hidden = false;
        $("progTitle").textContent = pg.line;
        $("progNote").textContent = pg.kind === "dirbuild" ? "Siftwell is reading employers’ public job pages on this computer (no Claude). You can keep using it; pause the build in Settings, under Employer directory." : "";
        $("progBar").style.width = (pg.kind === "dirbuild" && pg.frac != null ? Math.max(1, Math.round(100 * pg.frac)) : 4) + "%"; $("progLog").textContent = "";
        setTimeout(poll, 5000);
      } else if (bgShown && !wasRunning) {
        bgShown = false; $("progress").hidden = true; setTimeout(poll, 5000);
      } else if (wasRunning) {
        $("updStop").hidden = true;
        if (s.exit === 0) location.reload();
        else if (s.stopped) { wasRunning = false; $("progTitle").textContent = "Stopped"; $("progNote").textContent = "Everything found so far is kept. Your board is being rebuilt with it; this page reloads when it is ready."; $("progBar").style.width = "100%"; stopWatch(); }
        else { $("progTitle").textContent = "Finding new jobs didn’t finish"; $("progNote").textContent = "Some employers couldn’t be checked this time. Your board shows what Siftwell has; try Find new jobs again later. (What went wrong is on the Employers page, under Finding new jobs.)"; $("progLog").textContent = ""; $("progBar").style.width = "100%"; }
      } else setTimeout(poll, 20000);   // idle: keep watching, so the page notices a check that starts later, or Siftwell closing
    }).catch(() => { if (++pollFails >= 3) serverDown(); setTimeout(poll, 5000); });
  }
  // ---- The employer directory on a board with jobs: (1) an honest notice when the first search had to use the starter
  // list because the directory couldn't be reached, with "Try the directory again"; (2) after a change of search area
  // (home, radius, ways of working), the employers the directory has for the new area, with the count, a choice and
  // the time it costs: never a blind add, and the batch can be taken back.
  const dirB = $("dirBanner");
  const dirHide = key => { dirB.hidden = true; try { sessionStorage.setItem(key, "1"); sessionStorage.removeItem("jb.area"); } catch(e) {} };
  function dirDone(d, again){
    const k = (d.added || 0) + (d.linked || 0);
    // (kept across the page's own reloads while the board fills in, so "Remove the employers this added" stays in reach)
    try { sessionStorage.removeItem("jb.area"); if (k) sessionStorage.setItem("jb.diradded", JSON.stringify({added: k, fetching: !!d.fetching})); } catch(e) {}
    const dropNote = () => { try { sessionStorage.removeItem("jb.diradded"); } catch(e) {} };
    dirB.hidden = false;
    // (again: the note is being shown anew after a reload; whether the check is still running is in the banner above it)
    dirB.innerHTML = `<span>${k ? `Added ${k.toLocaleString()} employers.${again ? " Their openings are checked right after they are added; the line above says how far that is." : d.fetching ? " Siftwell is checking their openings now; your board fills in as it goes." : " Their jobs show up after the next Find new jobs."}` : "No new employers near you in the directory right now."}</span>`
      + (k ? `<button class="btn sm ghost" type="button" id="dirUndoBtn">Remove the employers this added</button>` : "") + `<button class="btn sm ghost" type="button" id="dirClose">OK</button>`;
    $("dirClose").addEventListener("click", () => { dirB.hidden = true; dropNote(); });
    if ($("dirUndoBtn")) $("dirUndoBtn").addEventListener("click", async () => {
      if (!await appConfirm({title: `Remove the ${k.toLocaleString()} employers this added?`, text: "They leave your list (their jobs leave your board). You can add them again later.", ok: "Remove them", danger: true})) return;
      $("dirUndoBtn").disabled = true; dropNote();
      const undo = () => dirUndo().then(({ok, d}) => {
        dirB.innerHTML = `<span>${ok ? `Removed ${(d.removed || 0).toLocaleString()} employers. Your board is being re-checked.` : esc(d.error || "That didn’t work.")}</span><button class="btn sm ghost" type="button" id="dirClose">OK</button>`;
        $("dirClose").addEventListener("click", () => { dirB.hidden = true; });
        if (ok) msAwaitBoard();
      });
      // (a check that is running is paused first, so nothing is added back while the employers are taken off)
      fetch("/api/search/pause", {method: "POST", headers: H, body: "{}"}).then(() => setTimeout(undo, 2500)).catch(undo);
    });
    if (!again) { chkSig = ""; poll(); }
  }
  function dirOffer(pv, why){
    const d = dirDefault(pv); if (!pv.available || !pv.new || !d) return false;
    dirB.hidden = false;
    dirB.innerHTML = `<span><b>${pv.new.toLocaleString()} more employers</b> ${pv.remote_only ? "that hire remotely" : `within ${pv.radius} miles of ${esc(pv.label)}`} are in Siftwell’s free employer directory${why}. ${dirChooser(pv, "db")}</span>`
      + `<button class="btn sm primary" type="button" id="dirGo">Add them</button><button class="btn sm ghost" type="button" id="dirNo">Not now</button><span class="updmsg" id="dirMsg"></span>`;
    const lim = dirChooserWire(pv, "db");
    $("dirNo").addEventListener("click", () => dirHide("jb.dirno." + PID));
    $("dirGo").addEventListener("click", () => {
      $("dirGo").disabled = true; $("dirMsg").textContent = "Adding…";
      dirAdd(lim(), false).then(({ok, d}) => { if (!ok) { $("dirGo").disabled = false; $("dirMsg").textContent = d.error || "That didn’t work."; return; } dirDone(d); })
        .catch(() => { $("dirGo").disabled = false; $("dirMsg").textContent = "Couldn’t reach Siftwell. Try again."; });
    });
    return true;
  }
  window.areaOffer = function(){
    if (!jobs.length) return;     // (the Start card offers them on an empty board)
    dirPreview(false).then(pv => { if (!dirOffer(pv, " for your new search area")) { try { sessionStorage.removeItem("jb.area"); } catch(e) {} } }).catch(() => {});
  };
  function dirOfflineNotice(){
    let off = false; try { off = !!sessionStorage.getItem("jb.diroff." + PID); } catch(e) {}
    if (off || !dirB.hidden) return;
    dirB.hidden = false;
    dirB.innerHTML = `<span><b>Siftwell couldn’t reach its employer directory</b> when it set up your search, so your employers are a starter list of large US employers that comes with the app, not the employers near you.</span><button class="btn sm primary" type="button" id="dirRetry">Try the directory again</button><button class="btn sm" type="button" id="dirBuild" hidden>Build my own directory</button><button class="btn sm ghost" type="button" id="dirNo">Not now</button><span class="updmsg" id="dirMsg"></span>`;
    $("dirNo").addEventListener("click", () => dirHide("jb.diroff." + PID));
    // the other way out: build the directory on this computer (what it does and how long it takes is the button's hint
    // and is said in full before anything starts)
    fetch("/api/localdir").then(r => r.json()).then(ld => {
      const b = $("dirBuild"); if (!b || !ld.possible || ld.running || !ld.offer) return;
      b.hidden = false; b.title = ld.offer;
      b.addEventListener("click", async () => {
        if (!await appConfirm({title: "Build my own directory?", text: ld.offer, ok: "Build it"})) return;
        buildStart(b, $("dirMsg"), () => { $("dirRetry").hidden = true; chkSig = ""; poll(); });
      });
    }).catch(() => {});
    $("dirRetry").addEventListener("click", () => {
      $("dirRetry").disabled = true; $("dirMsg").textContent = "Trying…";
      dirPreview(true).then(pv => {
        if (!pv.available) { $("dirRetry").disabled = false; $("dirMsg").textContent = "Still can’t reach it. Check your internet connection and try again."; return; }
        if (!dirOffer(pv, "")) dirAdd(null, true).then(({ok, d}) => { if (ok) dirDone(d); else { $("dirRetry").disabled = false; $("dirMsg").textContent = d.error || "That didn’t work."; } });
      }).catch(() => { $("dirRetry").disabled = false; $("dirMsg").textContent = "Couldn’t reach Siftwell. Try again."; });
    });
  }
  if (jobs.length) {
    let pend = false; try { pend = !!sessionStorage.getItem("jb.area"); } catch(e) {}
    let done = null; try { done = JSON.parse(sessionStorage.getItem("jb.diradded") || "null"); } catch(e) {}
    if (done && done.added) dirDone(done, true);
    else if (pend) window.areaOffer();
    fetch("/api/directory").then(r => r.json()).then(d => { if (d.offline_start) dirOfflineNotice(); }).catch(() => {});
  }
  // ---- No job title yet: every kind of job is kept and nothing can be ranked by relevance. Say so once, plainly.
  (function(){
    const key = "jb.notitle." + PID; let off = false; try { off = !!localStorage.getItem(key); } catch(e) {}
    if (off || !jobs.length || HASREL) return;
    const b = $("ttlBanner"); b.hidden = false;
    b.innerHTML = `<span><b>Tell Siftwell what work you do to see the most relevant jobs first.</b> Without a job title it keeps every kind of job (${jobs.length.toLocaleString()} here) and can only order them by pay, place and level.</span><a class="btn sm primary" href="/profile#search">Add my job title</a><button class="btn sm ghost" type="button" id="ttlNo">Not now</button>`;
    $("ttlNo").addEventListener("click", () => { b.hidden = true; try { localStorage.setItem(key, "1"); } catch(e) {} });
  })();
  const RR = D.ratings || {};
  const need = NOAI ? 0 : (RR.stale || 0) + (RR.unrated || 0);
  $("rrSmall").textContent = NOAI ? "needs Claude" : need ? `${need} of your top ${RR.top} not rated or out of date` : "all top jobs current";
  $("rerateBtn").title = "Rate jobs: choose how Claude rates your jobs (no new listings)" + (need ? ` (${need} of your top ${RR.top} not rated or out of date)` : " (all top jobs current)");
  if (need) { $("rrBadge").hidden = false; $("rrBadge").textContent = need > 99 ? "99+" : need; }
  // ---- Rate jobs panel. One main action (rate the jobs that need it, within the per-run limits) and the single steps
  // under More options. Counts come from the board: ai_rs (per step: "-" none, "s" older info, "f" current) and ai_bb
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
  const TNAME = TIERN;
  const ratePool = jobs.filter(j => j.ai_rs);
  const byBB = ratePool.slice().sort((a, b) => (b.ai_bb || 0) - (a.ai_bb || 0) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));  // same order the server picks in
  const nf = n => n.toLocaleString();
  const reqs = (n, t) => Math.ceil(n / RB[t]);
  const plural = (n, w) => `${nf(n)} ${w}${n === 1 ? "" : "s"}`;
  const intIn = (id, lo, hi) => { const v = Number($(id).value); const ok = $(id).value.trim() !== "" && Number.isInteger(v) && v >= lo && v <= hi; $(id).setAttribute("aria-invalid", ok ? "false" : "true"); return ok ? v : null; };
  function rrCalc(){
    const pct = intIn("rrPct", 1, 100), top = intIn("rrTop", 1, 2000);
    const tgtN = Math.min(RLIM.target, +(PREFS["claude.per_update"] || RLIM.target));
    document.querySelectorAll(".rrTgtN").forEach(e => e.textContent = nf(tgtN));
    $("rrLim").textContent = `One run rates at most ${nf(RLIM.haiku)} jobs with a quick check, ${nf(RLIM.sonnet)} with a careful look and ${nf(RLIM.opus)} new ones with best judgment (plus up to ${nf(RLIM.saved)} jobs you saved). Run it again for the next batch. Uses your Claude plan.`;
    if (COUNTING) {
      ["rrHN", "rrSNn", "rrONn"].forEach(id => $(id).textContent = "Counting…");
      $("rrHAll").textContent = $("rrSum").textContent = "Counting… your board is being refreshed for this panel (a minute or so). This page reloads when it's done.";
      $("rrSN").textContent = $("rrON").textContent = "";
      $("rrEstFull").textContent = $("rrEst").textContent = "";
      document.querySelectorAll("#rrPanel [data-rr]").forEach(b => b.disabled = true);
      document.querySelectorAll(".rrhint").forEach(e => e.hidden = true);
      return {pct, top, n: {haiku: 0, sonnet: 0, opus: 0}, all: 0};
    }
    const stale = (j, i) => j.ai_rs[i] !== "f";
    const hNeed = ratePool.filter(j => stale(j, 0)).length;
    // Careful look and best judgment only pick among jobs that already have a rating (an unrated job has no Match to rank by)
    const rated = byBB.filter(j => /[sf]/.test(j.ai_rs));
    const sTop = pct ? rated.slice(0, Math.ceil(rated.length * pct / 100)) : [];
    const saved = ratePool.filter(j => status[j.id] === "saved" || status[j.id] === "applied");
    const oTop = top ? rated.slice(0, top) : [], oTopIds = new Set(oTop.map(j => j.id));
    const oSaved = top ? saved.filter(j => !oTopIds.has(j.id)) : [];
    const oPick = oTop.concat(oSaved);
    const sNeed = sTop.filter(j => stale(j, 1)).length, oNeed = oPick.filter(j => stale(j, 2)).length;
    const oRun = need => Math.min(RLIM.opus, oTop.filter(j => !need || stale(j, 2)).length) + Math.min(RLIM.saved, oSaved.filter(j => !need || stale(j, 2)).length);
    const unr = ratePool.filter(j => j.ai_fit == null).length, old = ratePool.filter(j => j.ai_fit != null && j.ai_stale).length;
    $("rrSum").textContent = !ratePool.length ? "There are no jobs on your board for Claude to rate yet." : unr || old
      ? `${[unr ? `${plural(unr, "job")} not rated yet` : "", old ? `${plural(old, "job")} rated with older info` : ""].filter(Boolean).join(", ")}.`
      : `All ${plural(ratePool.length, "job")} Claude would rate have a current rating.`;
    $("rrHAll").textContent = `${plural(ratePool.length, "job")} on your board that Claude would rate. One run checks up to ${nf(RLIM.haiku)}, the ones most relevant to your work first.`;
    $("rrHN").textContent = nf(hNeed);
    $("rrSN").textContent = pct ? `= ${plural(sTop.length, "job")}` : "(1 to 100)";
    $("rrSNn").textContent = nf(sNeed);
    $("rrON").textContent = top ? `${oSaved.length ? `+ ${nf(oSaved.length)} saved ` : ""}= ${plural(oPick.length, "job")}` : "(1 to 2,000)";
    $("rrONn").textContent = nf(oNeed);
    document.querySelectorAll(".rrhint").forEach(e => e.hidden = !(hNeed >= Math.max(10, ratePool.length * 0.2)));
    // what one run would really do: never more than the per-run limits (ai_score.RUN_LIMITS)
    const h = Math.min(RLIM.haiku, $("rrHNeed").checked ? hNeed : ratePool.length), s = Math.min(RLIM.sonnet, $("rrSNeed").checked ? sNeed : sTop.length), o = oRun($("rrONeed").checked);
    const hb = Math.min(hNeed, RLIM.haiku, +(PREFS["claude.haiku_per_night"] || RLIM.haiku));
    const full = reqs(hb, "haiku") + reqs(Math.min(sNeed, RLIM.sonnet), "sonnet") + reqs(oRun(true), "opus");
    $("rrGo").textContent = full ? `Rate the jobs that need it · about ${plural(full, "request")}` : "Everything is rated";
    $("rrEstFull").textContent = full ? `A quick check of up to ${nf(Math.min(hb, RLIM.haiku))} jobs (the most relevant first), then a careful look at your best ${pct || "?"}% of rated jobs and best judgment on your top ${top ? nf(top) : "?"}. Only missing ratings and ones made with older info are done; fewer requests if little has changed.` : "Nothing to do right now.";
    $("rrEst").textContent = `Claude requests for these: Quick check ${nf(reqs(h, "haiku"))} · Careful look ${pct ? nf(reqs(s, "sonnet")) : "?"} · Best judgment ${top ? nf(reqs(o, "opus")) : "?"} (a request rates ${RB.haiku} jobs in a quick check, ${RB.sonnet} in a careful look or best judgment). Uses your Claude plan.`;
    // without Claude nothing here can run: the buttons are off and the panel says how to connect it
    document.querySelectorAll("#rrPanel [data-rr]").forEach(b => { b.disabled = NOAI || (b.dataset.rr === "full" ? !full : b.dataset.rr !== "haiku" && !(pct && top)); b.title = NOAI ? "Needs Claude" : ""; });
    return {pct, top, n: {haiku: h, sonnet: s, opus: o}, all: ratePool.length};
  }
  let rrFrom = null;   // the button that opened the panel (the header's Rate jobs, or the one in the count line)
  function rrPlace(){
    const p = $("rrPanel"), r = (rrFrom && rrFrom.offsetParent ? rrFrom : $("rerateBtn")).getBoundingClientRect();
    p.style.top = Math.round(r.bottom + 8) + "px";
    p.style.right = Math.max(8, Math.round(innerWidth - r.right - 8)) + "px"; p.style.left = "auto";
  }
  function rrOpen(e){
    if (!$("rrPanel").hidden) return rrClose();
    rrFrom = e && e.currentTarget || $("rerateBtn");
    $("rrTitle").textContent = `Rate ${D.person && D.person.name ? D.person.name + "'s" : "your"} jobs`;
    if ($("rrPct").value === "") $("rrPct").value = PREFS["claude.sonnet_pct"] || 15;
    if ($("rrTop").value === "") $("rrTop").value = PREFS["claude.opus_top"] || 50;
    document.querySelectorAll(".rrTgt").forEach(e => e.hidden = !D.pivot_enabled);
    $("rrMsg").textContent = ""; $("rrMsg").classList.remove("bad");
    rrCalc(); rrPlace(); $("rrPanel").hidden = false; rrFrom.setAttribute("aria-expanded", "true");
    (NOAI || $("rrGo").disabled ? $("rrClose") : $("rrGo")).focus();   // (without Claude the panel explains itself: #rrNo)
  }
  function rrClose(){ $("rrPanel").hidden = true; ["rerateBtn", "rateMore"].forEach(id => $(id).setAttribute("aria-expanded", "false")); }
  ["rrPct", "rrTop", "rrHNeed", "rrSNeed", "rrONeed"].forEach(id => $(id).addEventListener("input", rrCalc));
  $("rrClose").addEventListener("click", rrClose);
  addEventListener("resize", () => { if (!$("rrPanel").hidden) rrPlace(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("rrPanel").hidden && !document.querySelector("dialog[open]")) { rrClose(); (rrFrom || $("rerateBtn")).focus(); } });
  document.addEventListener("click", e => { if (!$("rrPanel").hidden && !e.target.closest("#rrPanel,#rerateBtn,#rateMore,dialog")) rrClose(); });
  $("rrPanel").addEventListener("click", async e => {
    const b = e.target.closest("button[data-rr]"); if (!b) return;
    const kind = b.dataset.rr, c = rrCalc();
    if (kind === "haiku") { c.pct = c.pct || +(PREFS["claude.sonnet_pct"] || 15); c.top = c.top || +(PREFS["claude.opus_top"] || 50); }  // not used by the quick check
    if (!(c.pct && c.top)) { $("rrMsg").textContent = "A careful look takes 1 to 100% of your rated jobs; best judgment 1 to 2,000 jobs."; $("rrMsg").classList.add("bad"); return; }
    const only = kind === "full" ? true : $({haiku: "rrHNeed", sonnet: "rrSNeed", opus: "rrONeed"}[kind]).checked;
    const tgt = !!D.pivot_enabled && $("rrTgt").checked;   // (one Target tick for whichever run starts here)
    if (kind !== "full" && !only) {  // a forced run re-rates jobs whose ratings are current: say how many first
      const n = c.n[kind], name = {haiku: "quick check", sonnet: "careful look", opus: "best-judgment look"}[kind];
      if (!await appConfirm({title: `Give ${plural(n, "job")} a fresh ${name}?`, ok: "Rate them",
          text: `This also re-rates jobs whose ratings are current: about ${plural(reqs(n, kind), "Claude request")} on your Claude plan.` +
                (tgt ? `\n\nIt also rates up to ${plural(Math.min(RLIM.target, +(PREFS["claude.per_update"] || RLIM.target)), "job")} for your ${D.target_name || "Target"} tab.` : "")})) return;
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
        $("progTitle").textContent = (s.label || "Rating jobs") + (s.stopping ? ": stopping…" : "…");
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
          if (s.error) { $("progTitle").textContent = "Rating stopped"; $("progNote").textContent = s.error; }
          else if (pollRerate.auto && !pollRerate.mine) {  // nobody pressed Run here: don't reload under their hands, offer it
            $("progTitle").textContent = (s.label || "Rating jobs") + (s.stopped ? " stopped" : " done"); $("progNote").textContent = "";
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
  ["rerateBtn", "rateMore"].forEach(id => { $(id).setAttribute("aria-haspopup", "dialog"); $(id).setAttribute("aria-expanded", "false"); $(id).addEventListener("click", rrOpen); });
  pollRerate();
  $("updateBtn").addEventListener("click", async () => {
    const mine = estMine(), e = EST ? (mine ? EST.mine : EST.all) : null;
    const what = e ? `Siftwell checks ${mine ? "your" : "all"} ${e.companies.toLocaleString()} employer${e.companies === 1 ? "" : "s"} for new and removed openings. That takes ${e.text}.` : "Siftwell checks your employers for new and removed openings.";
    if (!await appConfirm({title: "Find new jobs now?", ok: "Find new jobs", text: what + (NOAI ? "" : " Claude then rates the new ones (this uses your Claude plan).") + (mine ? "\n\nThe other profiles’ employers are checked when they press Find new jobs, or by the automatic daily one." : "")})) return;
    fetch("/api/update", {method: "POST", headers: H, body: JSON.stringify({scope: "mine"})}).then(() => { wasRunning = true; scrollTo(0, 0); poll(); });
  });
  poll();
  // The settings page hands its Find new jobs / Rate jobs / Add a person clicks to the board (sessionStorage "jb.run").
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
    body = HEAD + BODY + data + SCRIPT + appupdate.BANNER_SCRIPT   # (appConfirm comes with the header, TOOLS)
    if not fragment:
        body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
                HEAD + "</head><body>" + BODY + data + SCRIPT + appupdate.BANNER_SCRIPT + "</body></html>")
    import paths
    paths.write_atomic(path, body)  # temp file + replace: the server never serves a half-written board
