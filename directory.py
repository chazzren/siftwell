"""The Siftwell employer directory: a free, nationwide list of employers whose jobs Siftwell can read, with where they
hire, built every week by a GitHub Actions job (scripts/build_index.py) and published on this repository's `index`
branch. No key, no account, no Claude.

The app downloads only the parts it needs: whole state files (states/OH.json.gz), so the exact home is never revealed,
plus remote.json.gz for remote-only searches, and the matching job snapshots (jobs/OH.json.gz: postings from sources
that publish postings rather than employer feeds, e.g. USAJOBS). Files are cached in DATA/directory/ (never the app
folder), checked against the manifest's SHA-256, refreshed at most once a week, and used from the cache when offline.

What it does with them:
  apply(pid)        puts the employers within the person's radius (or the top remote-friendly ones for remote-only
                    searches) on their "Near me" list (near-<pid>), plus one catalog entry per job-snapshot source with
                    postings near them ("Federal jobs (USAJOBS)" ...). An employer is offered to a person once: if they
                    take it off their list later it stays off (DATA/directory/people/<pid>.json remembers).
  start_background  once a week: refresh the cached files and add newly indexed employers for everyone who used it.
  FETCHERS          the "directory_jobs" reader: a snapshot source's postings from the cached files, so they go
                    through the normal catalog, per-person filters and rating funnel.

Routes (server.py): GET /api/directory, POST /api/directory/apply {fetch}. Test hook: SIFTWELL_DIRECTORY_URL=<base>
(http://127.0.0.1:port/... or file:///...; plain urllib, because netsafe refuses local addresses);
SIFTWELL_DIRECTORY_DELAY=<s> (first background check, default 120)."""
import datetime as dt, gzip, hashlib, json, math, os, re, threading, time, urllib.parse, urllib.request

import paths

DIR = os.path.join(paths.DATA, "directory")
REFRESH_DAYS = 7
MAX_FILE = 40_000_000           # bytes per downloaded file (compressed)
MAX_JSON = 250_000_000          # bytes after unpacking
MAX_ADD = 400                   # employers added per apply (the ones with the most jobs nearby first)
REMOTE_ADD = 150                # remote-only searches: the employers with the most US-remote jobs
SOURCE_SECTOR = "Siftwell directory"
ATS = "directory_jobs"
_LOCK = threading.Lock()
_APPLY = threading.Lock()
STATE_CODES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
               "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR").split()


def base_url():
    o = os.environ.get("SIFTWELL_DIRECTORY_URL", "").strip()
    if o:
        return o.rstrip("/")
    import appupdate
    return f"https://raw.githubusercontent.com/{appupdate.REPO}/index"


def _get(rel):
    """Bytes of one published file. The default address goes through netsafe; a test override uses plain urllib."""
    url = base_url() + "/" + rel
    req = urllib.request.Request(url, headers={"User-Agent": "Siftwell (employer directory)"})
    if os.environ.get("SIFTWELL_DIRECTORY_URL"):
        opener = urllib.request.urlopen
    else:
        import netsafe
        opener = netsafe.urlopen
    with opener(req, timeout=60) as r:
        data = r.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError(f"{rel} is too large")
    return data


def _path(*parts):
    return os.path.join(DIR, *parts)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- manifest + shards
def manifest(refresh=False):
    """The cached manifest, fetched again when it's a week old (or refresh=True). None when there is none at all."""
    p = _path("manifest.json")
    cur = None
    try:
        with open(p, encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        pass
    age = None
    if cur and cur.get("_fetched"):
        try:
            age = (dt.datetime.now() - dt.datetime.fromisoformat(cur["_fetched"])).total_seconds()
        except ValueError:
            age = None
    if cur and not refresh and age is not None and age < REFRESH_DAYS * 86400:
        return cur
    with _LOCK:
        try:
            new = json.loads(_get("manifest.json").decode("utf-8"))
            if not isinstance(new, dict) or new.get("v") != 1:
                raise ValueError("unknown directory format")
            new["_fetched"] = _now()
            _write(p, json.dumps(new).encode())
            return new
        except Exception as e:
            if cur:
                cur["_error"] = f"{type(e).__name__}"
                return cur          # offline or the server is down: keep using what we have
            return {"v": 1, "_error": f"{type(e).__name__}: {str(e)[:120]}", "states": {}, "jobs": {}}


def _shard(kind, name, man=None):
    """One published file as JSON (kind: 'states' or 'jobs'; name: 'OH' or 'remote'), from the cache when it matches
    the manifest, else downloaded and checked. None when it isn't published (or can't be had)."""
    man = man or manifest()
    ent = (man.get(kind) or {}).get(name)
    rel = f"{kind}/{name}.json.gz"
    p = _path(kind, f"{name}.json.gz")
    data = None
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError:
        pass
    if ent and (data is None or hashlib.sha256(data).hexdigest() != ent.get("sha256")):
        try:
            new = _get(rel)
            if hashlib.sha256(new).hexdigest() != ent.get("sha256"):
                raise ValueError("checksum mismatch")
            _write(p, new)
            data = new
        except Exception:
            pass                    # (keep any older copy)
    if data is None:
        return None
    try:
        with gzip.GzipFile(fileobj=__import__("io").BytesIO(data)) as g:
            raw = g.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            return None
        d = json.loads(raw.decode("utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def refresh(force=False):
    """The weekly refresh: new manifest, then every cached file brought up to date. Returns the manifest."""
    man = manifest(refresh=force or _stale())
    for kind in ("states", "jobs"):
        try:
            names = [f[:-8] for f in os.listdir(_path(kind)) if f.endswith(".json.gz")]
        except OSError:
            names = []
        for n in names:
            _shard(kind, n, man)
    return man


def _stale():
    try:
        with open(_path("manifest.json"), encoding="utf-8") as f:
            t = json.load(f).get("_fetched")
        return (dt.datetime.now() - dt.datetime.fromisoformat(t)).days >= REFRESH_DAYS
    except Exception:
        return True


# ---------------------------------------------------------------- geography (offline, from assets/geo/places.tsv)
_GRID = {}


def _grid():
    if _GRID:
        return _GRID
    import geo
    g = {}
    with open(os.path.join(geo.GEO, "places.tsv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6 or parts[5] not in ("p", "c"):
                continue
            la, lo = float(parts[2]), float(parts[3])
            g.setdefault((math.floor(la), math.floor(lo)), []).append((la, lo, parts[1]))
    _GRID.update(g)
    return _GRID


def _cells(lat, lon, radius):
    dla = radius / 69.0 + 0.01
    dlo = radius / max(10.0, 69.0 * math.cos(math.radians(lat))) + 0.01
    for a in range(math.floor(lat - dla), math.floor(lat + dla) + 1):
        for b in range(math.floor(lon - dlo), math.floor(lon + dlo) + 1):
            yield (a, b)


def states_near(lat, lon, radius):
    """Every state with a town within radius miles of the point (always including the point's own state)."""
    import geo
    g = _grid()
    out = set()
    for cell in _cells(lat, lon, radius + 5):
        for la, lo, st in g.get(cell, ()):
            if st not in out and geo.miles(lat, lon, la, lo) <= radius + 5:
                out.add(st)
    own = state_of(lat, lon)
    if own:
        out.add(own)
    return sorted(out)


def state_of(lat, lon):
    """The state of the nearest town (None far from any)."""
    import geo
    g = _grid()
    best = None
    for r in (15, 60):
        for cell in _cells(lat, lon, r):
            for la, lo, st in g.get(cell, ()):
                d = geo.miles(lat, lon, la, lo)
                if best is None or d < best[0]:
                    best = (d, st)
        if best:
            return best[1]
    return None


# ---------------------------------------------------------------- who is near a person
def _settings(pid):
    import people
    return people.settings(pid)


def area(pid):
    """(lat, lon, label, radius, remote_only, remote_ok) for a person, or None when they have no home and aren't
    remote-only."""
    import geo
    st = _settings(pid)
    wps = st.get("workplaces") or ["onsite", "hybrid", "remote"]
    remote_only = wps == ["remote"]
    remote_ok = "remote" in wps and bool(st.get("remote_us", True))
    z = str(st.get("home_zip") or "").strip()
    if z:
        try:
            la, lo, label = geo.geocode_home(z)
            return la, lo, label, int(st.get("radius_miles") or 35), remote_only, remote_ok
        except Exception:
            pass
    if remote_only:
        return None, None, "anywhere in the US", 0, True, True
    return None


def _clean_entry(e):
    """A shard entry made safe (names, config, places): None when it doesn't check out."""
    import netsafe
    if not isinstance(e, dict) or not isinstance(e.get("c"), dict):
        return None
    cfg, why = netsafe.clean_config(e["c"])
    if cfg is None:
        return None
    name = netsafe.clean_text(e.get("n") or "", 60).replace(",", "").strip()
    if not name:
        return None
    places = []
    for p in e.get("p") or []:
        try:
            places.append((float(p[0]), float(p[1]), int(p[2]), str(p[3])[:80]))
        except (TypeError, ValueError, IndexError):
            continue
    return {"name": name, "cfg": cfg, "url": netsafe.clean_link(e.get("u") or "") if e.get("u") else "",
            "jobs": int(e.get("j") or 0), "remote": int(e.get("r") or 0), "places": places, "seen": str(e.get("s") or "")[:10]}


def near_employers(pid, man=None):
    """(employers near this person, best first; info). Each employer: name, cfg, url, jobs, remote, near (postings
    within the radius), where (closest place label)."""
    import geo
    a = area(pid)
    if not a:
        return [], {"reason": "no_place"}
    la, lo, label, radius, remote_only, remote_ok = a
    man = man or manifest()
    if man.get("_error") and not man.get("states"):
        return [], {"reason": "offline", "error": man["_error"]}
    out, seen = [], set()
    if remote_only:
        d = _shard("states", "remote", man) or {}
        for e in d.get("employers") or []:
            c = _clean_entry(e)
            if c and c["remote"] > 0:
                k = _key(c["cfg"])
                if k not in seen:
                    seen.add(k)
                    out.append(dict(c, near=c["remote"], where="Remote (US)"))
        out.sort(key=lambda c: -c["near"])
        return out[:REMOTE_ADD], {"states": [], "label": label, "radius": 0, "remote_only": True}
    sts = states_near(la, lo, radius)
    for st in sts:
        d = _shard("states", st, man) or {}
        for e in d.get("employers") or []:
            c = _clean_entry(e)
            if not c:
                continue
            n, best = 0, None
            for pla, plo, cnt, lab in c["places"]:
                m = geo.miles(la, lo, pla, plo)
                if m <= radius:
                    n += cnt
                    if best is None or m < best[0]:
                        best = (m, lab)
            if not n:
                continue
            k = _key(c["cfg"])
            if k in seen:
                prev = next(x for x in out if _key(x["cfg"]) == k)
                prev["near"] += n
                continue
            seen.add(k)
            out.append(dict(c, near=n, where=best[1]))
    out.sort(key=lambda c: (-c["near"], c["name"].lower()))
    return out, {"states": sts, "label": label, "radius": radius, "remote_only": False}


def near_jobs(pid, man=None):
    """{source id: postings near this person} from the job snapshots (remote ones count when remote work is OK)."""
    import geo
    a = area(pid)
    if not a:
        return {}
    la, lo, label, radius, remote_only, remote_ok = a
    man = man or manifest()
    out = {}
    names = ([] if remote_only else states_near(la, lo, radius)) + (["remote"] if remote_ok else [])
    for st in names:
        d = _shard("jobs", st, man) or {}
        for j in d.get("jobs") or []:
            if not isinstance(j, dict):
                continue
            src = str(j.get("src") or "")
            if st == "remote":
                ok = True
            else:
                ok = any(isinstance(p, list) and len(p) >= 2 and geo.miles(la, lo, float(p[0]), float(p[1])) <= radius for p in j.get("p") or [])
            if ok:
                out[src] = out.get(src, 0) + 1
    return out


def _key(cfg):
    import catalog
    return catalog.ats_key(cfg)


# ---------------------------------------------------------------- per-person record
def _rec_path(pid):
    return _path("people", f"{re.sub(r'[^A-Za-z0-9_-]', '_', pid)}.json")


def record(pid):
    try:
        with open(_rec_path(pid), encoding="utf-8") as f:
            r = json.load(f)
            if isinstance(r, dict):
                return r
    except (OSError, ValueError):
        pass
    return {}


def _save_record(pid, r):
    _write(_rec_path(pid), json.dumps(r, indent=1).encode())


def users():
    try:
        return [f[:-5] for f in os.listdir(_path("people")) if f.endswith(".json")]
    except OSError:
        return []


# ---------------------------------------------------------------- add to the catalog
def apply(pid, limit=MAX_ADD):
    """Add the directory's employers near this person to their Near me list (and the job-snapshot sources with postings
    near them). Employers offered before are skipped, so taking one off the list sticks. Returns
    {added: [names], linked: [names already in the catalog, now on the list], near: n, available: bool, reason}."""
    import catalog, company_add
    with _APPLY:
        man = manifest()
        emps, info = near_employers(pid, man)
        if info.get("reason"):
            return {"added": [], "linked": [], "near": 0, "available": False, "reason": info["reason"], "error": info.get("error")}
        rec = record(pid)
        offered = set(rec.get("offered") or [])
        want = f"near-{pid}"
        by_key = {catalog.ats_key(c): c for c in catalog.companies()}
        added, linked = [], []
        for e in emps:
            k = _key(e["cfg"])
            if k in offered:
                continue
            if len(added) + len(linked) >= limit:
                break
            offered.add(k)
            co = by_key.get(k)
            if co:
                if want not in (co.get("sets") or []):
                    entry = {kk: v for kk, v in co.items() if not kk.startswith("_")}
                    entry["sets"] = sorted(set(co.get("sets") or ["tech"]) | {want})
                    catalog.save_company(entry)
                    linked.append(co["name"])
                continue
            entry, existing = company_add.save_found(e["cfg"], e["name"], want, pid, sector=SOURCE_SECTOR)
            by_key[k] = entry
            (linked if existing else added).append(entry["name"])
        # job snapshots: one catalog entry per source, shared by everyone near its postings
        jobs = near_jobs(pid, man)
        labels = {s: (man.get("sources") or {}).get(s, {}).get("label") for s in jobs}
        for src, n in sorted(jobs.items()):
            if not n or not re.fullmatch(r"[a-z]{2,20}", src):
                continue
            k = "src:" + src
            if k in offered:
                continue
            offered.add(k)
            name = _source_name(src, labels.get(src))
            co = next((c for c in by_key.values() if c.get("ats") == ATS and c.get("source") == src), None)
            if co:
                if want not in (co.get("sets") or []):
                    entry = {kk: v for kk, v in co.items() if not kk.startswith("_")}
                    entry["sets"] = sorted(set(co.get("sets") or []) | {want})
                    catalog.save_company(entry)
                linked.append(co["name"])
            else:
                entry = {"name": name, "ats": ATS, "source": src, "tier": "national", "sector": SOURCE_SECTOR,
                         "sets": [want], "added_by": pid}
                catalog.save_company(entry)
                added.append(name)
        rec.update(offered=sorted(offered), applied=_now(), built=man.get("built"),
                   added=int(rec.get("added", 0)) + len(added) + len(linked))
        _save_record(pid, rec)
        return {"added": added, "linked": linked, "near": len(emps), "available": True, "reason": None,
                "jobs": jobs, "built": man.get("built")}


def _source_name(src, label=None):
    import netsafe
    try:
        _register()
    except Exception:
        pass
    default = {"usajobs": "Federal jobs (USAJOBS)", "careeronestop": "Jobs from CareerOneStop", "hn": "Hacker News: Who is hiring",
               "muse": "Jobs from The Muse"}.get(src, src.title() + " jobs")
    return (netsafe.clean_text(label or default, 60) or default).replace(",", "")


# ---------------------------------------------------------------- status for the pages
def status(pid):
    a = area(pid)
    rec = record(pid)
    try:
        with open(_path("manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        man = None
    out = {"possible": bool(a), "reason": None if a else "no_place", "label": a[2] if a else "", "radius": a[3] if a else 0,
           "remote_only": bool(a and a[4]), "applied": rec.get("applied"), "added": rec.get("added", 0),
           "built": (man or {}).get("built"), "checked": (man or {}).get("_fetched"), "near_list": 0,
           "sources": {k: {"label": v.get("label"), "attribution": v.get("attribution")} for k, v in ((man or {}).get("sources") or {}).items()
                       if isinstance(v, dict)},
           "url_default": not os.environ.get("SIFTWELL_DIRECTORY_URL")}
    try:
        import catalog
        out["near_list"] = sum(1 for s in catalog.sets_map().values() if f"near-{pid}" in s)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- weekly refresh
def start_background(log=lambda m: print(m, flush=True)):
    def loop():
        time.sleep(float(os.environ.get("SIFTWELL_DIRECTORY_DELAY") or 120))
        while True:
            try:
                if users() and _stale():
                    man = refresh(force=True)
                    if not man.get("_error"):
                        for pid in users():
                            import people
                            if people.exists(pid):
                                r = apply(pid)
                                if r["added"] or r["linked"]:
                                    log(f"directory: {len(r['added']) + len(r['linked'])} newly indexed employers for {pid}")
            except Exception as e:
                log(f"directory refresh failed: {type(e).__name__}: {e}")
            time.sleep(6 * 3600)
    threading.Thread(target=loop, daemon=True, name="directory").start()


# ---------------------------------------------------------------- the job-snapshot reader
def f_directory_jobs(c):
    """A snapshot source's postings from every cached job file (the states people here search in, plus remote)."""
    from jobfinder import J
    src = c.get("source")
    seen = set()
    try:
        names = sorted(f[:-8] for f in os.listdir(_path("jobs")) if f.endswith(".json.gz"))
    except OSError:
        names = []
    man = manifest()
    attrib = ((man.get("sources") or {}).get(src) or {}).get("attribution") or {}
    note = str(attrib.get("note") or "")[:300]
    import netsafe
    for n in names:
        d = _shard("jobs", n, man) or {}
        for j in d.get("jobs") or []:
            if not isinstance(j, dict) or j.get("src") != src:
                continue
            url = netsafe.clean_link(str(j.get("u") or ""))
            if not url or url in seen:
                continue
            seen.add(url)
            pay = j.get("pay")
            sal = None
            if isinstance(pay, list) and len(pay) == 2 and all(isinstance(x, (int, float)) for x in pay) and pay[1]:
                sal = (pay[0] or pay[1], pay[1], "listed range")
            desc = netsafe.clean_text(str(j.get("x") or ""), 2000)
            org = netsafe.clean_text(str(j.get("o") or ""), 100)
            desc = " ".join(x for x in (f"Employer: {org}." if org else "", desc, note) if x)
            locs = [netsafe.clean_text(str(l), 100) for l in (j.get("l") or [])[:6]]
            yield J(c, netsafe.clean_text(str(j.get("t") or ""), 200), url, locs or (["Remote (US)"] if j.get("w") == "remote" else []),
                    "remote" if j.get("w") == "remote" else "", sal, desc, str(j.get("d") or "")[:10], org, url)


FETCHERS = {ATS: f_directory_jobs}


def _register():
    """Let netsafe accept the directory_jobs config (one field: the source id)."""
    import netsafe
    netsafe.CONFIG_RULES.setdefault(ATS, {"source": (netsafe._rx(r"[a-z]{2,20}"), True)})


_register()


# ---------------------------------------------------------------- routes
def handle_get(h, path, pid):
    if path == "/api/directory":
        h._send(200, status(pid))
        return True
    return False


def handle_post(h, path, body, pid, server):
    if path != "/api/directory/apply":
        return False
    try:
        r = apply(pid)
    except Exception as e:
        h._send(500, {"error": f"The directory couldn't be read ({type(e).__name__})."})
        return True
    if not r["available"]:
        msg = {"no_place": "Add your home ZIP (Filters, then My search) so Siftwell knows where to look.",
               "offline": "Siftwell couldn't download the employer directory. Check your internet connection and try again."}.get(r["reason"], "The directory isn't available right now.")
        h._send(409, {"error": msg, **r})
        return True
    names = r["added"] + r["linked"]
    r["fetching"] = False
    if names and body.get("fetch") and server.claim_update():
        r["fetching"] = True
        server._actlog("update started", pid, f"Siftwell directory: {len(names)} employers")
        threading.Thread(target=server.run_update, args=(",".join(names),), daemon=True).start()
    server._actlog("companies added", pid, f"{len(names)} from the Siftwell directory")
    h._send(200, r)
    return True


# ---------------------------------------------------------------- Settings -> Employer directory
CAT = ("directory", "Employer directory", '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/><path d="M9 10h.01"/><path d="M15 10h.01"/>')

PANE_HTML = """<section class="sgsec"><h3 class="sgtitle">Employers near you</h3><div class="sgroup">
<div class="srow stack"><div class="slab"><span>Siftwell employer directory</span><small id="dirState">Checking…</small></div>
<div class="bk-btnrow"><button class="btn primary" type="button" id="dirApply">Add employers near me from the Siftwell directory</button></div>
<span class="note" id="dirMsg" role="status" aria-live="polite"></span></div>
<div class="srow"><div class="slab"><span>Find more with Claude</span><small>Claude can also search the web for employers the directory doesn't have. It uses your Claude plan, and only runs when you start it.</small></div>
<div class="sctl"><a class="btn sm" href="/catalog#find">Find employers</a></div></div></div>
<p class="sfoot">The directory is a free list of employers whose job pages Siftwell can read, with the places they hire, rebuilt every week
from public sources (web crawl indexes, certificate logs and public employer lists). It needs no key, no account and no Claude.
Siftwell downloads only whole-state files for the states around your home (and a remote-jobs file if you only want remote work), so
your exact location never leaves this computer. Once a week it checks for newly listed employers near you and adds them; employers
you take off your Near me list stay off. <span id="dirSources"></span></p></section>"""

PANE_JS = r"""(function(){
const $ = id => document.getElementById(id);
if (!$("dirApply")) return;
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const day = s => { try { return new Date(s).toLocaleDateString(); } catch(e) { return s; } };
function load(){
  fetch("/api/directory").then(r => r.json()).then(d => {
    let t = d.possible ? (d.remote_only ? "Remote-friendly employers anywhere in the US." : `Employers with openings within ${d.radius} miles of ${esc(d.label)}.`)
                       : "Add your home ZIP (Filters, then My search on the board) so Siftwell knows where to look.";
    if (d.applied) t += ` Last added ${day(d.applied)}; ${Number(d.near_list || 0).toLocaleString()} employers are on your Near me list.`;
    if (d.built) t += ` Directory updated ${day(d.built)}.`;
    $("dirState").innerHTML = t;
    $("dirApply").disabled = !d.possible;
    const src = Object.values(d.sources || {}).map(s => s.attribution && s.attribution.link ? `<a href="${esc(s.attribution.link)}" target="_blank" rel="noopener">${esc(s.attribution.name)}</a>` : "").filter(Boolean);
    $("dirSources").innerHTML = src.length ? `It also brings job postings from ${src.join(", ")}, each linked to the original posting.` : "";
  }).catch(() => { $("dirState").textContent = "Couldn't reach Siftwell."; });
}
$("dirApply").addEventListener("click", () => {
  $("dirApply").disabled = true; $("dirMsg").textContent = "Adding…";
  fetch("/api/directory/apply", {method: "POST", headers: H, body: JSON.stringify({fetch: true})})
    .then(r => r.json().then(d => ({ok: r.ok, d}))).then(({ok, d}) => {
      $("dirApply").disabled = false;
      if (!ok) { $("dirMsg").textContent = d.error || "That didn't work."; return; }
      const k = (d.added || []).length + (d.linked || []).length;
      $("dirMsg").textContent = k ? `Added ${k.toLocaleString()} employers to your Near me list.` + (d.fetching ? " Siftwell is checking their openings now; your board fills in when it's done." : " Their jobs show up after the next Find new jobs.")
                                  : "No new employers near you in the directory right now. Employers you took off your list stay off.";
      load();
    }).catch(() => { $("dirApply").disabled = false; $("dirMsg").textContent = "Couldn't reach Siftwell. Is it still running?"; });
});
load();
})();"""
PANE_SCRIPT = "<script>" + PANE_JS + "</script>"
