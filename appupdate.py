"""Siftwell's own update check: looks on GitHub Releases for a newer version and, for the installed program, installs it.

  * Checks https://api.github.com/repos/<REPO>/releases/latest, at most once a day (at start-up and then daily) and from the
    "Check for updates" button in Settings -> About & updates. Switch it off with "Check for updates automatically".
    Everything that goes wrong (the repository is private so GitHub answers 404/403, rate limits, no internet, a timeout)
    is silent for the automatic check: nothing is shown. The button says "Couldn't check right now".
    GitHub's /releases/latest skips pre-releases and every 0.x release is published as a pre-release, so a 404 there is
    followed by one look at the releases list (newest non-draft release wins).
  * The request goes through netsafe (public internet addresses on port 443 only). Tests aim it at a local fake release
    server with SIFTWELL_UPDATE_API=<base url> (then plain urllib is used, because netsafe refuses local addresses).
  * A newer version shows a dismissible banner on the board and in Settings: "Siftwell 0.3.0 is available. What's new ·
    Update". Release notes are shown as plain text (set with textContent in the page).
  * Installed copy (Siftwell.exe, frozen.FROZEN): Update downloads Siftwell-Setup-<version>.exe from the release assets
    into DATA/_updates/, checks its size and, when GitHub reports one, its SHA256, then runs it silently
    (/VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /NORESTART /RELAUNCH; /RELAUNCH makes the installer start Siftwell again when
    it is done) and exits so the installer can replace the files. If anything fails the error is shown and the current
    version keeps running.
  * Portable copy (Siftwell-Portable-x.y.z.zip, paths.PORTABLE): never replaces itself; the banner says "Download the new
    portable version" and links to the release's Siftwell-Portable-<version>.zip, with the steps (close Siftwell, unzip over
    the old folder or copy your data folder into the new one).
  * ZIP / source copy: never replaces itself; the banner links to the release page ("Download the new version").

Test hooks (never set by the app itself): SIFTWELL_UPDATE_API (API base URL), SIFTWELL_UPDATE_DELAY (seconds before the
first automatic check, default 15), SIFTWELL_UPDATE_RUNNER (a command, forward slashes in paths, that is run with the downloaded file and the
installer flags in place of running the file itself; this also makes a source copy behave like an installed one).
State lives in DATA/app_update.json; nothing is written into the app folder."""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import frozen
import paths

REPO = "chazzren/siftwell"                      # GitHub owner/name; the one place the repository is named
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
API_BASE = "https://api.github.com"
INSTALLER_NAME = "Siftwell-Setup-{version}.exe"
PORTABLE_NAME = "Siftwell-Portable-{version}.zip"
INSTALLER_FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/NORESTART", "/RELAUNCH"]
CHECK_EVERY = 24 * 3600
RETRY_OFFLINE = 3600                            # no internet: try again sooner than a day
MAX_DOWNLOAD = 500 * 1024 * 1024
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FILE = os.path.join(paths.DATA, "app_update.json")
UPDATES_DIR = os.path.join(paths.DATA, "_updates")


def current_version():
    import getting_started
    return getting_started.VERSION


def api_base():
    return (os.environ.get("SIFTWELL_UPDATE_API") or API_BASE).rstrip("/")


def _testing():
    return bool(os.environ.get("SIFTWELL_UPDATE_API"))


def installed_copy():
    """True when Siftwell can replace itself: the installed program (or a test with SIFTWELL_UPDATE_RUNNER set). A portable
    copy never does (it is replaced by unzipping the new portable version)."""
    if paths.PORTABLE:
        return False
    return bool(frozen.FROZEN or os.environ.get("SIFTWELL_UPDATE_RUNNER"))


# ---------------------------------------------------------------- versions
_V = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(v):
    m = _V.match(str(v or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)), (m.group(4) or "")


def version_key(v):
    """Sort key: numbers first; a pre-release (0.3.0-rc1) sorts just before its release (0.3.0)."""
    p = parse_version(v)
    if not p:
        return None
    nums, pre = p
    return nums, 0 if pre else 1, pre


def is_newer(latest, current):
    """Is `latest` a higher version than `current`? A copy with no real version ("dev") is never told to update."""
    a, b = version_key(latest), version_key(current)
    return bool(a and b and a > b)


# ---------------------------------------------------------------- state file
_lock = threading.Lock()


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    try:
        paths.write_atomic(FILE, json.dumps(d, indent=1))
    except OSError:
        pass


def auto_enabled():
    return _load().get("auto", True) is not False


def set_auto(on):
    with _lock:
        d = _load()
        d["auto"] = bool(on)
        _save(d)


def dismiss(version):
    with _lock:
        d = _load()
        d["dismissed"] = str(version)[:40]
        _save(d)


# ---------------------------------------------------------------- the GitHub request
def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Siftwell/" + str(current_version()),
                                               "X-GitHub-Api-Version": "2022-11-28"})
    if _testing():
        r = urllib.request.urlopen(req, timeout=timeout)
    else:
        import netsafe
        r = netsafe.urlopen(req, timeout=timeout)
    with r:
        return json.loads(r.read(3_000_000).decode("utf-8", "replace"))


def _summary(rel):
    """The few fields we keep from a release, or None if it isn't usable."""
    if not isinstance(rel, dict) or rel.get("draft"):
        return None
    tag = str(rel.get("tag_name") or "")
    version = tag[1:] if tag[:1] in "vV" else tag
    if not parse_version(version):
        return None
    out = {"version": version, "tag": tag[:60], "notes": str(rel.get("body") or "")[:20000],
           "url": str(rel.get("html_url") or "")[:300], "prerelease": bool(rel.get("prerelease")), "installer": None,
           "portable": None}
    want = INSTALLER_NAME.format(version=version)
    for a in rel.get("assets") or []:
        if isinstance(a, dict) and a.get("name") == PORTABLE_NAME.format(version=version) and a.get("browser_download_url"):
            out["portable"] = {"name": a["name"], "url": str(a["browser_download_url"])[:400], "size": int(a.get("size") or 0)}
        if isinstance(a, dict) and a.get("name") == want and a.get("browser_download_url"):
            dg = str(a.get("digest") or "").lower()
            out["installer"] = {"name": want, "url": str(a["browser_download_url"]), "size": int(a.get("size") or 0),
                                "sha256": dg[7:] if re.fullmatch(r"sha256:[0-9a-f]{64}", dg) else ""}
    return out


def fetch_latest():
    """-> (summary or None, outcome): "ok" (a release), "none" (no release published), "unavailable" (404/403/429, the
    repository is private or rate limited) or "offline" (no connection, timeout, unreadable answer). Never raises."""
    base = f"{api_base()}/repos/{REPO}/releases"
    try:
        try:
            s = _summary(_get_json(base + "/latest"))
            return (s, "ok") if s else (None, "none")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return None, "unavailable"
        # /latest skips pre-releases (every 0.x release is one): look at the list once
        lst = _get_json(base + "?per_page=10")
        best = None
        for rel in lst if isinstance(lst, list) else []:
            s = _summary(rel)
            if s and (best is None or version_key(s["version"]) > version_key(best["version"])):
                best = s
        return (best, "ok") if best else (None, "none")
    except urllib.error.HTTPError:
        return None, "unavailable"
    except Exception:       # URLError, timeout, ValueError (bad JSON, netsafe.UnsafeURL), OSError ...
        return None, "offline"


_check_lock = threading.Lock()


def check(force=False):
    """Ask GitHub (when due, or always with force) and remember the answer. Returns the outcome string, or "skipped".
    Safe to call from any thread; one check at a time."""
    d = _load()
    if not force and (d.get("auto", True) is False or time.time() < float(d.get("next_check") or 0)):
        return "skipped"
    if not _check_lock.acquire(blocking=False):
        return "skipped"
    try:
        s, outcome = fetch_latest()
        with _lock:
            d = _load()
            now = time.time()
            d["checked"] = now
            d["next_check"] = now + (RETRY_OFFLINE if outcome == "offline" else CHECK_EVERY)
            d["last_outcome"] = outcome
            if outcome == "ok":
                d["latest"] = s
            elif outcome == "none":
                d.pop("latest", None)
            _save(d)
        return outcome
    finally:
        _check_lock.release()


def start_background():
    """Called once by the server: the first automatic check a little after start-up, then re-evaluated every hour (a
    check only really happens when the last one is more than a day old)."""
    def loop():
        try:
            time.sleep(float(os.environ.get("SIFTWELL_UPDATE_DELAY") or 15))
        except ValueError:
            time.sleep(15)
        while True:
            try:
                check()
            except Exception:
                pass
            time.sleep(3600)
    threading.Thread(target=loop, daemon=True, name="app-update-check").start()


# ---------------------------------------------------------------- status for the pages
INSTALL = {"phase": "idle", "pct": 0, "error": None, "version": None}   # idle / downloading / verifying / launching / failed
_ilock = threading.Lock()
_hooks = {"busy": lambda: None, "exit": None}


def configure(busy_reason=None, exit_fn=None):
    """busy_reason() -> text while an update/re-rate is running (the installer would stop it); exit_fn() ends this
    process shortly (the installer is already running)."""
    if busy_reason:
        _hooks["busy"] = busy_reason
    if exit_fn:
        _hooks["exit"] = exit_fn


def _port():
    try:
        import getting_started
        return getting_started.CTX["port"]
    except Exception:
        return None


def status():
    d = _load()
    cur = current_version()
    lat = d.get("latest") if isinstance(d.get("latest"), dict) else None
    newer = bool(lat and is_newer(lat.get("version"), cur))
    with _ilock:
        inst = dict(INSTALL)
    return {
        "current": cur, "auto": d.get("auto", True) is not False, "checked": d.get("checked"), "outcome": d.get("last_outcome"),
        "newer": newer, "dismissed": bool(newer and d.get("dismissed") == lat.get("version")),
        "latest": ({"version": lat["version"], "notes": lat.get("notes", ""), "url": lat.get("url") or RELEASES_PAGE,
                    "size": (lat.get("installer") or {}).get("size", 0),
                    "portable_url": (lat.get("portable") or {}).get("url", "")} if newer else None),
        "can_install": bool(newer and installed_copy() and lat.get("installer")),
        "installed_copy": installed_copy(), "portable": paths.PORTABLE, "release_page": RELEASES_PAGE, "install": inst,
        "data_dir": paths.DATA, "port": _port(),
    }


# ---------------------------------------------------------------- installing (installed copy only)
def _set(**kw):
    with _ilock:
        INSTALL.update(kw)


def installer_command(path):
    """argv for the silent install. SIFTWELL_UPDATE_RUNNER (tests only) replaces "run the file itself"."""
    runner = os.environ.get("SIFTWELL_UPDATE_RUNNER")
    return (shlex.split(runner) if runner else []) + [path] + INSTALLER_FLAGS


def _download(inst, dest):
    """Stream the installer to dest (a .part file); returns the SHA256 hex. Raises on any problem."""
    req = urllib.request.Request(inst["url"], headers={"User-Agent": "Siftwell/" + str(current_version()), "Accept": "application/octet-stream"})
    if _testing():
        r = urllib.request.urlopen(req, timeout=30)
    else:
        import netsafe
        r = netsafe.urlopen(req, timeout=30)
    h, got = hashlib.sha256(), 0
    with r, open(dest, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            got += len(chunk)
            if got > MAX_DOWNLOAD or (inst["size"] and got > inst["size"]):
                raise RuntimeError("The download is larger than expected, so it was stopped.")
            h.update(chunk)
            f.write(chunk)
            if inst["size"]:
                _set(pct=min(99, int(got * 100 / inst["size"])))
    return h.hexdigest(), got


def _install_worker(lat):
    inst = lat["installer"]
    version = lat["version"]
    final = os.path.join(UPDATES_DIR, inst["name"])
    part = final + ".part"
    try:
        os.makedirs(UPDATES_DIR, exist_ok=True)
        for n in os.listdir(UPDATES_DIR):          # leftovers of earlier downloads
            if n != inst["name"]:
                try:
                    os.remove(os.path.join(UPDATES_DIR, n))
                except OSError:
                    pass
        _set(phase="downloading", pct=0, error=None, version=version)
        digest, got = _download(inst, part)
        _set(phase="verifying", pct=100)
        if inst["size"] and got != inst["size"]:
            raise RuntimeError(f"The download is incomplete ({got} of {inst['size']} bytes).")
        if not inst["size"] and not inst["sha256"]:
            raise RuntimeError("The release doesn't say how big the installer should be, so it can't be checked. Download it from the release page instead.")
        if inst["sha256"] and digest != inst["sha256"]:
            raise RuntimeError("The download doesn't match the checksum GitHub lists for it, so it was not used.")
        os.replace(part, final)
        _set(phase="launching")
        cmd = installer_command(final)
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=UPDATES_DIR, close_fds=True)
        if os.name == "nt":
            kw.update(creationflags=NOWIN | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            kw.update(start_new_session=True)
        p = subprocess.Popen(cmd, **kw)
        try:
            code = p.wait(timeout=2)       # a real installer keeps running; one that dies at once didn't start
            if code != 0:
                raise RuntimeError(f"The installer stopped right away (exit code {code}).")
        except subprocess.TimeoutExpired:
            pass
        try:
            import actionlog
            actionlog.log("app update: installer started", None, None, f"version {version}")
        except Exception:
            pass
        ex = _hooks["exit"]
        if ex:
            ex()                            # the installer replaces our files; it also relaunches Siftwell when it is done
    except Exception as e:
        try:
            os.remove(part)
        except OSError:
            pass
        _set(phase="failed", error=(str(e) or type(e).__name__)[:300])


def start_install():
    """-> (ok, message). Starts the download-verify-launch-exit sequence in a background thread."""
    if not installed_copy():
        return False, "This copy of Siftwell isn't installed with the installer, so it can't update itself. Use the download link."
    st = status()
    if not st["newer"]:
        return False, "Siftwell is already up to date."
    if not st["can_install"]:
        return False, "This release has no installer for Windows. Use the download link."
    why = _hooks["busy"]()
    if why:
        return False, f"Siftwell is busy: {why}. Installing now would stop it. Try again when it finishes."
    with _ilock:
        if INSTALL["phase"] in ("downloading", "verifying", "launching"):
            return False, "The update is already being installed."
        INSTALL.update(phase="downloading", pct=0, error=None, version=st["latest"]["version"])
    lat = _load()["latest"]
    threading.Thread(target=_install_worker, args=(lat,), daemon=True, name="app-update-install").start()
    return True, "Downloading the update."


# ---------------------------------------------------------------- routes (wired in server.py)
def handle_get(h, path):
    if path == "/api/app-update":
        h._send(200, status())
        return True
    return False


def handle_post(h, path, body):
    if not path.startswith("/api/app-update/"):
        return False
    act = path.rsplit("/", 1)[1]
    if act == "check":
        outcome = check(force=True)
        return h._send(200, dict(status(), result=outcome)) or True
    if act == "auto":
        if not isinstance(body.get("on"), bool):
            return h._send(400, {"error": "Say whether to turn it on or off."}) or True
        set_auto(body["on"])
        return h._send(200, status()) or True
    if act == "dismiss":
        v = str(body.get("version") or "")
        if parse_version(v):
            dismiss(v)
        return h._send(200, status()) or True
    if act == "install":
        h._act("app update: install requested")
        ok, msg = start_install()
        return h._send(202 if ok else 409, dict(status(), ok=ok, message=msg)) or True
    return False


# ---------------------------------------------------------------- pages: banner (board + Settings) and the Settings group
BANNER_JS = r"""(function(){
if (!/^https?:$/.test(location.protocol)) return;
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const mk = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
const okUrl = u => /^https:\/\/[^\s]+$/.test(u || "");
const PHASE = {downloading: "Downloading the update…", verifying: "Checking the download…", launching: "Installing. Siftwell closes and opens again by itself in a moment."};
function steps(s){
  const o = mk("div", "updsteps");
  o.append(mk("strong", null, "To update:"));
  const ol = mk("ol");
  (s.portable ? ["Click \"Download the new portable version\" and save the ZIP.",
       "Close Siftwell (close its window; if it keeps running for your phone, use Stop Siftwell from the tray icon).",
       "Unzip the new ZIP over your old Siftwell folder and say yes to replace files. Or unzip it somewhere new and copy your old data folder into the new Siftwell folder.",
       "Open Siftwell.exe again. Your profiles, ratings and settings are in the data folder, so they carry over."]
    : s.installed_copy ? ["Click Update. Siftwell downloads the new installer, installs it and opens again."]
    : ["Click \"Download the new version\" and download the ZIP (or the Windows installer) from the page that opens.",
       "Unzip it, then double-click Start Siftwell in the new folder (use Stop Siftwell in the old one first).",
       "Everything carries over: your profiles, ratings and settings are kept outside the Siftwell folder."]).forEach(t => ol.append(mk("li", null, t)));
  o.append(ol);
  return o;
}
function render(box, s, st){
  box.textContent = "";
  if (!s || !s.newer || !s.latest || (s.dismissed && !st.keep)) { box.hidden = true; return; }
  const v = s.latest.version, inst = s.install || {};
  const busy = ["downloading", "verifying", "launching"].includes(inst.phase);
  box.hidden = false;
  box.append(mk("span", null, "Siftwell " + v + " is available."));
  const notes = mk("pre", "updnotes", s.latest.notes || "No release notes were published."); notes.hidden = true;
  const more = mk("button", "btn sm ghost", "What's new"); more.type = "button";
  more.addEventListener("click", () => { notes.hidden = !notes.hidden; extra.hidden = notes.hidden; });
  box.append(more);
  const msg = mk("span", "updmsg", busy ? (PHASE[inst.phase] + (inst.phase === "downloading" ? " " + (inst.pct || 0) + "%" : "")) : (inst.phase === "failed" ? "Couldn't update: " + inst.error + " Siftwell " + s.current + " is still running." : ""));
  if (s.can_install) {
    const b = mk("button", "btn sm primary", "Update"); b.type = "button"; b.disabled = busy;
    b.addEventListener("click", () => { b.disabled = true; fetch("/api/app-update/install", {method: "POST", headers: H, body: "{}"}).then(r => r.json()).then(d => { if (!d.ok) { msg.textContent = d.message || "Couldn't start the update."; b.disabled = false; } else watch(box, st); }).catch(() => { msg.textContent = "Couldn't reach Siftwell."; b.disabled = false; }); });
    box.append(b);
  } else {
    const a = mk("a", "btn sm primary", s.portable ? "Download the new portable version" : "Download the new version");
    a.href = s.portable && okUrl(s.latest.portable_url) ? s.latest.portable_url : okUrl(s.latest.url) ? s.latest.url : s.release_page; a.target = "_blank"; a.rel = "noopener";
    box.append(a);
  }
  if (!st.keep) {
    const x = mk("button", "btn sm ghost", "Dismiss"); x.type = "button"; x.disabled = busy;
    x.addEventListener("click", () => { box.hidden = true; fetch("/api/app-update/dismiss", {method: "POST", headers: H, body: JSON.stringify({version: v})}).catch(() => {}); });
    box.append(x);
  }
  box.append(msg);
  const extra = steps(s); extra.hidden = true; box.append(extra); box.append(notes);
  if (busy) watch(box, st);
}
let timer = null;
function watch(box, st){
  clearTimeout(timer);
  timer = setTimeout(() => load(box, st), 1000);
}
function load(box, st){
  return fetch("/api/app-update").then(r => r.json()).then(s => { render(box, s, st); return s; }).catch(() => {
    // the server went away while installing: that is the expected end of an update
    const m = box.querySelector(".updmsg"); if (m && /Installing|Downloading|Checking/.test(m.textContent)) m.textContent = "Installing. Siftwell closes and opens again by itself in a moment.";
  });
}
window.siftUpdateBanner = (box, opts) => load(box, opts || {});
const box = document.getElementById("updBanner");
if (box && !box.dataset.manual) window.siftUpdateBanner(box, {});
})();"""
BANNER_SCRIPT = "<script>" + BANNER_JS + "</script>"

CSS = """<style>
.updbn .updnotes{flex:1 1 100%;white-space:pre-wrap;word-break:break-word;max-height:260px;overflow:auto;margin:4px 0 0;padding:8px 10px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);font-size:12.5px;line-height:1.45}
.updbn .updsteps{flex:1 1 100%;font-size:13px}
.updbn .updsteps ol{margin:4px 0 0 18px;padding:0}
.updbn .updmsg{flex:1 1 100%;font-size:13px}
.updbn .updmsg:empty,.updbn[hidden]{display:none}
</style>"""

PANE_HTML = """<section class="sgsec"><h3 class="sgtitle">Siftwell</h3><div class="sgroup">
<div class="srow"><div class="slab"><span>Version</span><small id="apVerNote"></small></div><div class="sctl"><span id="apVer" class="note"></span></div></div>
<div class="srow"><div class="slab"><span>Data folder</span><small id="apDataNote"></small></div><div class="sctl"><span id="apData" class="note" style="word-break:break-all;text-align:right"></span></div></div>
<div class="srow"><div class="slab"><label for="apCheck">Check for updates</label><small id="apCheckMsg" role="status" aria-live="polite"></small></div><div class="sctl"><button class="btn sm" type="button" id="apCheck">Check for updates</button></div></div>
<div class="srow"><div class="slab"><label for="apAuto">Check for updates automatically</label><small>Once a day, Siftwell asks GitHub whether a newer version exists. Nothing is installed without your click.</small></div><div class="sctl"><input type="checkbox" role="switch" class="sw" id="apAuto"></div></div>
</div></section>
<div class="banner gsbn updbn" id="apBanner" data-manual="1" hidden></div>"""

PANE_JS = r"""(function(){
const $ = id => document.getElementById(id); if (!$("apCheck")) return;
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const box = $("apBanner");
function when(ts){ if (!ts) return "never"; const d = new Date(ts * 1000); return d.toLocaleDateString([], {month: "short", day: "numeric"}) + " " + d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}); }
function show(s){
  $("apVer").textContent = "Siftwell " + s.current;
  $("apVerNote").textContent = s.portable ? "Portable copy: your data is kept in the data folder next to Siftwell.exe." : s.installed_copy ? "Installed with the Windows installer." : "Running from a downloaded folder (ZIP).";
  $("apData").textContent = s.data_dir || "";
  $("apDataNote").textContent = "Where this copy keeps your profiles and settings." + (s.port && s.port !== 8766 ? " This copy runs on port " + s.port + " (test copy)." : "");
  $("apAuto").checked = !!s.auto;
  $("apCheckMsg").textContent = s.newer ? "Siftwell " + s.latest.version + " is available." : (s.checked ? "Last checked " + when(s.checked) + (s.outcome === "ok" || s.outcome === "none" ? ". You're up to date." : ".") : "Not checked yet.");
}
function load(){ return fetch("/api/app-update").then(r => r.json()).then(s => { show(s); return window.siftUpdateBanner(box, {keep: true}); }).catch(() => {}); }
$("apCheck").addEventListener("click", () => {
  const b = $("apCheck"); b.disabled = true; $("apCheckMsg").textContent = "Checking…";
  fetch("/api/app-update/check", {method: "POST", headers: H, body: "{}"}).then(r => r.json()).then(s => {
    show(s);
    if (s.result === "unavailable" || s.result === "offline") $("apCheckMsg").textContent = "Couldn't check right now. Try again later.";
    else if (!s.newer) $("apCheckMsg").textContent = "You're up to date (Siftwell " + s.current + ").";
    return window.siftUpdateBanner(box, {keep: true});
  }).catch(() => { $("apCheckMsg").textContent = "Couldn't check right now."; }).finally(() => { b.disabled = false; });
});
$("apAuto").addEventListener("change", () => fetch("/api/app-update/auto", {method: "POST", headers: H, body: JSON.stringify({on: $("apAuto").checked})}).then(r => r.json()).then(show).catch(() => {}));
const top = $("updBanner"), sync = () => { if (top) top.style.display = location.hash === "#about" ? "none" : ""; };
window.addEventListener("hashchange", sync); sync();
load();
})();"""
PANE_SCRIPT = "<script>" + PANE_JS + "</script>"
