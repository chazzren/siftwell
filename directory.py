"""The Siftwell employer directory: a free, nationwide list of employers whose jobs Siftwell can read, with where they
hire, built every week by a GitHub Actions job (scripts/build_index.py) and published on this repository's `index`
branch. No key, no account, no Claude.

The app downloads only the parts it needs: whole state files (states/OH.json.gz), so the exact home is never revealed,
plus remote.json.gz for remote-only searches, and the matching job snapshots (jobs/OH.json.gz: postings from sources
that publish postings rather than employer feeds, e.g. USAJOBS). Files are cached in DATA/directory/ (never the app
folder), checked against the manifest's SHA-256, refreshed at most once a week, and used from the cache when offline.

What it does with them:
  preview(pid)      what apply() would add right now, without adding it: how many employers, about how many jobs
                    near the person, and honest time estimates (first check, daily update) for "all" and "the top N".
  undo(pid)         takes back what the last apply() added ("Remove the employers this added").
  apply(pid)        puts EVERY employer within the person's radius (or the top remote-friendly ones for remote-only
                    searches; limit=N: only the N with the most openings nearby) on their "Near me" list (near-<pid>), plus one catalog entry per job-snapshot source with
                    postings near them ("Federal jobs (USAJOBS)" ...). An employer is offered to a person once: if they
                    take it off their list later it stays off (DATA/directory/people/<pid>.json remembers). Each
                    catalog entry also carries where the directory knows the employer hires (the "dir" key), so a
                    posting without a readable location can still count as local when everywhere the employer hires
                    is near the person (jobfinder.select_for_person). Names that are really board codes are replaced
                    by readable ones (company_add.readable_name), also on entries added earlier. Big boards the
                    builder could only sample ("maybe near": a presence in the state, places unknown) are added as
                    starters, like the shipped packs, and pruned after their first fetch when nothing is nearby.
                    The first fetch of what apply() adds is staged (first_search.py): most nearby jobs first.
  start_background  once a week: refresh the cached files and add every newly indexed nearby employer for everyone
                    who used it (they are fetched by the next update).
  FETCHERS          the "directory_jobs" reader: a snapshot source's postings from the cached files, so they go
                    through the normal catalog, per-person filters and rating funnel.

When the directory can't be reached and nothing is cached, the FIRST search (and only it: starters_ok) falls back to
the starter list of large US employers shipped in packs/; the person's record says so ("offline") and every page
tells them plainly, with "Try the directory again". Pruned or removed employers are never added again by that path.

People on the older built-in area (no home ZIP) can give the directory its own area (settings directory_zip /
directory_radius) without changing which jobs count as near them.

Two ways to get the directory ("Where my directory comes from", prefs() / source(), kept in DATA/directory/prefs.json
for the whole household): "shared" (the default: the download described above), "local" (built on this computer by
localdir.py / index_build/local.py, which writes the same per-state files under DATA/directory/local/; the app then
NEVER contacts the index branch: _get refuses) or "both" (the two merged per employer, the newer reading wins:
_merge). Everything below works on whatever _shard() returns, so nothing downstream knows the difference.

Routes (server.py): GET /api/directory, GET /api/directory/preview, POST /api/directory/apply {fetch, limit, retry},
POST /api/directory/undo, POST /api/directory/area {zip, radius}. Test hook: SIFTWELL_DIRECTORY_URL=<base>
(http://127.0.0.1:port/... or file:///...; plain urllib, because netsafe refuses local addresses);
SIFTWELL_DIRECTORY_DELAY=<s> (first background check, default 120)."""
import datetime as dt, gzip, hashlib, json, math, os, re, threading, time, urllib.parse, urllib.request

import paths

DIR = os.path.join(paths.DATA, "directory")
REFRESH_DAYS = 7
MAX_FILE = 40_000_000           # bytes per downloaded file (compressed)
MAX_JSON = 250_000_000          # bytes after unpacking
MAX_PLACES = 80                 # places kept on a catalog entry (an employer with more is never "all nearby")
MAYBE_REST_DAYS = 60            # a pruned "maybe near" employer isn't tried again for this long
REMOTE_ADD = 150                # remote-only searches: the employers with the most US-remote jobs
SOURCE_SECTOR = "Siftwell directory"
ATS = "directory_jobs"
_LOCK = threading.Lock()
_APPLY = threading.RLock()      # (re-entrant: apply() renames companies, and a rename updates these records)
STATE_CODES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
               "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR").split()
LOCAL = os.path.join(DIR, "local")     # the directory built on this computer (localdir.py)
SOURCES = ("shared", "local", "both")
_PREFS = {"sig": None, "v": None}
_CACHE = {}                             # parsed local files and merged shards, by file signature


# ---------------------------------------------------------------- where the directory comes from
def prefs():
    """{"source": "shared" | "local" | "both", "discover": bool} for this data folder (the whole household)."""
    p = os.path.join(DIR, "prefs.json")
    try:
        st = os.stat(p)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    if _PREFS["v"] is None or _PREFS["sig"] != sig:
        d = {}
        if sig is not None:
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = {}
        d = d if isinstance(d, dict) else {}
        _PREFS.update(sig=sig, v={"source": d.get("source") if d.get("source") in SOURCES else "shared",
                                  "discover": bool(d.get("discover"))})
    return dict(_PREFS["v"])


def save_prefs(**kw):
    cur = prefs()
    if kw.get("source") in SOURCES:
        cur["source"] = kw["source"]
    if "discover" in kw:
        cur["discover"] = bool(kw["discover"])
    _write(os.path.join(DIR, "prefs.json"), json.dumps(cur).encode())
    _PREFS["v"] = None
    _PREVIEW.clear()
    return cur


def source():
    return prefs()["source"]


def uses_shared():
    return source() != "local"


def uses_local():
    return source() != "shared"


def base_url():
    o = os.environ.get("SIFTWELL_DIRECTORY_URL", "").strip()
    if o:
        return o.rstrip("/")
    import appupdate
    return f"https://raw.githubusercontent.com/{appupdate.REPO}/index"


def _get(rel):
    """Bytes of one published file. The default address goes through netsafe; a test override uses plain urllib.
    Refuses when the person chose "Built on this computer": then nothing is ever asked of the index branch."""
    if not uses_shared():
        raise RuntimeError("the shared directory is switched off (Built on this computer)")
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
    """What the directory has, for the chosen source: the shared manifest (see _shared_manifest; a bare one when the
    person builds their own only) plus, under "local", the manifest of the directory built on this computer."""
    man = _shared_manifest(refresh) if uses_shared() else {"v": 1, "states": {}, "jobs": {}, "_off": True}
    if uses_local():
        man = dict(man)
        man["local"] = local_manifest()
        if not man.get("built") or man.get("_off"):
            man["built"] = man["local"].get("built")
    return man


def local_manifest():
    """The manifest of the directory built on this computer ({} when there is none)."""
    return _cached_file(os.path.join(LOCAL, "manifest.json"), gz=False) or {}


def _cached_file(path, gz=True):
    """A JSON file's content (dict), parsed again only when the file changed. None when it isn't there."""
    try:
        st = os.stat(path)
    except OSError:
        _CACHE.pop(path, None)
        return None
    sig = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE + 1)
        if gz:
            with gzip.GzipFile(fileobj=__import__("io").BytesIO(data)) as g:
                data = g.read(MAX_JSON + 1)
        d = json.loads(data.decode("utf-8"))
    except Exception:
        return None                 # (half-written: the next look reads it)
    if not isinstance(d, dict):
        return None
    _CACHE[path] = (sig, d)
    return d


def _shared_manifest(refresh=False):
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
    """One directory file as JSON (kind: 'states' or 'jobs'; name: 'OH' or 'remote') for the chosen source: the
    shared one, the one built on this computer, or the two merged per employer. None when there is none."""
    man = man or manifest()
    if uses_shared():
        shared = _shared_shard(kind, name, man)
    else:   # (built on this computer only: job snapshots downloaded earlier are still read, nothing is downloaded)
        shared = _shared_shard(kind, name, {}) if kind == "jobs" else None
    if kind != "states" or not uses_local():
        return shared
    local = _cached_file(os.path.join(LOCAL, "states", f"{name}.json.gz"))
    if local is None or shared is None:
        return shared if local is None else local
    return _merge(name, shared, local)


def _entry_key(e):
    try:
        return _key(e["c"])
    except Exception:
        return None


def _merge(name, shared, local):
    """One state's employers from the shared file and the one built here: per employer (same job board) the newer
    reading wins; a tie goes to the shared one. An employer only the shared file has stays, unless this computer has
    read its board since (index.json.gz) and no longer found it hiring in this state."""
    idx = _cached_file(os.path.join(LOCAL, "index.json.gz")) or {}
    sig = (id(shared), id(local), id(idx))
    hit = _CACHE.get(("merge", name))
    if hit and hit[0] == sig:
        return hit[2]
    mine = {}
    for e in local.get("employers") or []:
        k = _entry_key(e) if isinstance(e, dict) else None
        if k:
            mine[k] = e
    out, seen = [], set()
    for e in shared.get("employers") or []:
        k = _entry_key(e) if isinstance(e, dict) else None
        if not k or k in seen:
            continue
        seen.add(k)
        when = str(e.get("s") or "")
        le = mine.get(k)
        if le is not None:
            out.append(le if str(le.get("s") or "") > when else e)
        elif str(idx.get(_short(k)) or "") > when:
            continue
        else:
            out.append(e)
    out += [e for k, e in mine.items() if k not in seen]
    d = dict(shared, employers=out, built=max(str(shared.get("built") or ""), str(local.get("built") or "")))
    _CACHE[("merge", name)] = (sig, (shared, local, idx), d)   # (the three are kept alive, so their ids stay theirs)
    return d


def _shared_shard(kind, name, man):
    """One published file as JSON, from the cache when it matches the manifest, else downloaded and checked. None
    when it isn't published (or can't be had)."""
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
    sig = hashlib.sha256(data).hexdigest()
    hit = _CACHE.get((kind, name))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with gzip.GzipFile(fileobj=__import__("io").BytesIO(data)) as g:
            raw = g.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            return None
        d = json.loads(raw.decode("utf-8"))
        if not isinstance(d, dict):
            return None
        _CACHE[(kind, name)] = (sig, d)
        return d
    except Exception:
        return None


def refresh(force=False):
    """The weekly refresh: new manifest, then every cached file brought up to date. Returns the manifest."""
    if not uses_shared():
        return manifest()
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
    if not uses_shared():
        return False                # (nothing to refresh: the directory is built on this computer)
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
    dz = str(st.get("directory_zip") or "").strip()
    if dz and not remote_only:      # (no home ZIP: the area chosen just for the directory; the job filter is untouched)
        try:
            la, lo, label = geo.geocode_home(dz)
            return la, lo, label, int(st.get("directory_radius") or st.get("radius_miles") or 35), remote_only, remote_ok
        except Exception:
            pass
    if remote_only:
        return None, None, "anywhere in the US", 0, True, True
    return None


def _clean_entry(e):
    """A shard entry made safe (names, config, places): None when it doesn't check out. name is "" when the directory
    only has a board code for it (near_employers then describes it by place)."""
    import netsafe, company_add
    if not isinstance(e, dict) or not isinstance(e.get("c"), dict):
        return None
    cfg, why = netsafe.clean_config(e["c"])
    if cfg is None:
        return None
    url = netsafe.clean_link(e.get("u") or "") if e.get("u") else ""
    name = company_add.readable_name(netsafe.clean_text(e.get("n") or "", 60), cfg, url or "")
    places = []
    for p in e.get("p") or []:
        try:
            places.append((float(p[0]), float(p[1]), int(p[2]), str(p[3])[:80]))
        except (TypeError, ValueError, IndexError):
            continue
    return {"name": name, "cfg": cfg, "url": url, "jobs": int(e.get("j") or 0), "remote": int(e.get("r") or 0), "places": places,
            "seen": str(e.get("s") or "")[:10], "ps": [str(x)[:2] for x in (e.get("ps") or []) if isinstance(x, str)][:60],
            "cut": bool(e.get("pt")) or bool(e.get("x")), "maybe": bool(e.get("mb")), "kind": str(e.get("k") or "")[:20]}


def near_employers(pid, man=None):
    """(employers near this person, best first; info). Each employer: name, cfg, url, jobs, remote, near (postings
    within the radius), where (closest place label), places (everything loaded for it), all (True when those places
    are every place the directory knows for it). After them come the "maybe near" ones (starter=True, near 0): big
    boards the directory could only sample, present in a state near the person."""
    import geo, company_add
    a = area(pid)
    if not a:
        return [], {"reason": "no_place"}
    la, lo, label, radius, remote_only, remote_ok = a
    man = man or manifest()
    if man.get("_error") and not man.get("states") and not (man.get("local") or {}).get("states"):
        return [], {"reason": "offline", "error": man["_error"]}
    out, seen = [], set()
    if remote_only:
        d = _shard("states", "remote", man)
        if d is None:
            return [], {"states": [], "label": label, "radius": 0, "remote_only": True, "missing": ["remote"]}
        for e in d.get("employers") or []:
            c = _clean_entry(e)
            if c and c["remote"] > 0:
                k = _key(c["cfg"])
                if k not in seen:
                    seen.add(k)
                    c["name"] = c["name"] or company_add.placeholder_name(c["cfg"], "")
                    out.append(dict(c, near=c["remote"], where="Remote (US)", all=False))
        out.sort(key=lambda c: -c["near"])
        return out[:REMOTE_ADD], {"states": [], "label": label, "radius": 0, "remote_only": True}
    sts = states_near(la, lo, radius)
    missing, by_k = [], {}
    for st in sts:
        d = _shard("states", st, man)
        if d is None:
            missing.append(st)      # (not published yet, or not downloadable right now)
            continue
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
            if not n and not c["maybe"]:
                continue
            k = _key(c["cfg"])
            prev = by_k.get(k)
            if prev is not None:
                prev["near"] += n
                prev["places"] = prev["places"] + c["places"]
                prev["ps"] = sorted(set(prev["ps"]) | set(c["ps"]))
                prev["cut"] = prev["cut"] or c["cut"]
                if best and (prev["_best"] is None or best[0] < prev["_best"][0]):
                    prev["_best"] = best
                continue
            by_k[k] = dict(c, near=n, _best=best)
    loaded = set(sts) - set(missing)
    maybe = []
    for c in by_k.values():
        best = c.pop("_best")
        c["where"] = best[1] if best else ""
        c["all"] = bool(c["ps"]) and set(c["ps"]) <= loaded and not c["cut"] and 0 < len(c["places"]) <= MAX_PLACES
        c["name"] = c["name"] or company_add.placeholder_name(c["cfg"], c["where"] or label.split("(")[-1].strip(") "))
        if c["near"]:
            out.append(c)
        else:
            maybe.append(dict(c, starter=True, all=False))
    out.sort(key=lambda c: (-c["near"], c["name"].lower()))
    maybe.sort(key=lambda c: (-c["jobs"], c["name"].lower()))
    return out + maybe, {"states": sts, "label": label, "radius": radius, "remote_only": False, "missing": missing,
                         "maybe": len(maybe)}


# ---------------------------------------------------------------- offline starter: the shipped national packs
PACK_FILES = ("us-large-employers.json", "us-large-employers-AL.json")   # (not dc-area.json: it's regional)


def pack_employers():
    """Readable large US employers shipped with the app (packs/, read-only), deduplicated by board and name. They
    have no places, so apply() adds them as "starters" and prune_starters() keeps only the ones whose jobs turn out to
    be near the person (or remote, when remote work is OK) after their first fetch."""
    import netsafe
    out, keys, names = [], set(), set()
    for fn in PACK_FILES:
        try:
            with open(os.path.join(paths.PACKS, fn), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for c in d.get("companies") or []:
            if not isinstance(c, dict):
                continue
            cfg, _ = netsafe.clean_config(c)
            name = netsafe.clean_text(c.get("name") or "", 60).replace(",", "").strip()
            if not cfg or not name:
                continue
            cfg = {kk: v for kk, v in cfg.items() if not kk.startswith("verified_")}   # (stamps, not identity)
            k = _key(cfg)
            if k in keys or name.lower() in names:
                continue
            keys.add(k)
            names.add(name.lower())
            out.append({"name": name, "cfg": cfg, "url": "", "jobs": int(c.get("verified_total") or 0), "remote": 0,
                        "places": [], "near": 0, "where": "", "starter": True, "sector": c.get("sector") or ""})
    out.sort(key=lambda c: -c["jobs"])
    return out


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
def _dir_info(e):
    """What a catalog entry remembers from the directory: where the employer hires. The places themselves are kept only
    when they are the employer's whole list (then jobfinder may treat a posting with no readable place as local)."""
    if e.get("starter") and not e.get("places"):
        return None
    d = {"all": bool(e.get("all")), "st": list(e.get("ps") or [])[:60], "lab": (e.get("where") or "")[:80], "p": []}
    if d["all"]:
        d["p"] = sorted({(round(p[0], 3), round(p[1], 3)) for p in e["places"]})[:MAX_PLACES]
        d["p"] = [list(p) for p in d["p"]]
    return d


def _known_states():
    """{board key: set of states} from what is already on this computer (cached directory files, catalog entries):
    used to put the starter employers known to hire in the person's state first when the directory is unreachable."""
    out = {}
    try:
        import catalog
        for c in catalog.companies():
            st = (c.get("dir") or {}).get("st") if isinstance(c.get("dir"), dict) else None
            if st:
                out.setdefault(catalog.ats_key(c), set()).update(st)
    except Exception:
        pass
    try:
        names = [f[:-8] for f in os.listdir(_path("states")) if f.endswith(".json.gz") and len(f) == 10]
    except OSError:
        names = []
    for n in names:
        d = _shard("states", n, {"states": {}}) or {}
        for e in d.get("employers") or []:
            c = _clean_entry(e)
            if c:
                out.setdefault(_key(c["cfg"]), set()).update(set(c["ps"]) | {n})
    return out


def _order_starters(packs, la, lo):
    """Shipped starters in a sensible order: the ones known to hire in the person's state first, then the biggest.
    Sets each one's "rank" (see near_order)."""
    home = state_of(la, lo) if la is not None else None
    known = _known_states() if home else {}
    for p in packs:
        here = bool(home and home in known.get(_key(p["cfg"]), ()))
        p["rank"] = (2.0 if here else 0.0) + min(p["jobs"], 99999) / 100000.0
    packs.sort(key=lambda p: (-p["rank"], p["name"].lower()))
    return packs


def apply(pid, weekly=False, limit=None, starters_ok=False, first=False, dry=False, tag=None):
    """Add the directory's employers near this person to their Near me list (and the job-snapshot sources with
    postings near them). limit=N: only the N with the most openings nearby (None: every one). Employers offered before
    are skipped, so taking one off the list sticks; the weekly refresh therefore adds exactly the newly indexed ones
    (nothing, for someone who chose "the top N"). dry=True changes nothing and only reports. Returns
    {added: [names], linked: [names already in the catalog, now on the list], near: n, available: bool, reason,
     starters: n added to be checked and kept only if they turn out to hire nearby, renamed: n, offline: bool,
     new: [{name, near, ats, starter}] (dry runs: everything that would be added, best first)}.

    Entries already on the list get their directory facts refreshed (where the employer hires) and, when their name is
    a board code, the readable name the directory has now.

    starters_ok (the first search only): when the directory can't be had for this person's area (offline, or that
    state isn't published yet), the large national employers shipped in packs/ are added as starters, the ones known
    to hire in the person's state first; prune_starters() later drops the ones with no jobs near the person. A
    starter that was pruned is never added again this way. Without starters_ok an unreachable directory is simply
    reported (available False, reason "offline"). Directory data wins whenever it is there (same board = same employer).

    tag (localdir: "Build my own directory" adds what it finds near the person as it goes): everything added under
    one tag is ONE batch, so "Remove the employers this added" takes the whole build's additions back; the person's
    all / top N choice is left as it is."""
    import catalog, company_add
    with _APPLY:
        man = manifest()
        emps, info = near_employers(pid, man)
        if info.get("reason") == "no_place":
            return {"added": [], "linked": [], "near": 0, "available": False, "reason": "no_place", "starters": 0, "new": []}
        offline = info.get("reason") == "offline"
        rec = record(pid)
        if offline and not starters_ok:
            return {"added": [], "linked": [], "near": 0, "available": False, "reason": "offline", "starters": 0, "new": [],
                    "offline": True}
        pruned = dict(rec.get("pruned") or {})
        if starters_ok and (offline or info.get("missing")):
            have = {_key(e["cfg"]) for e in emps}
            a = area(pid)
            packs = [p for p in pack_employers() if _key(p["cfg"]) not in have and _short(_key(p["cfg"])) not in pruned]
            emps = emps + _order_starters(packs, a[0] if a else None, a[1] if a else None)
        if weekly and rec.get("top_only"):
            limit = 0                   # (they chose "the top N": the weekly check only keeps what they have up to date)
        offered = set(rec.get("offered") or [])
        pending = set(rec.get("starters_pending") or [])
        near_n = dict(rec.get("near_n") or {})
        rest = (dt.date.today() - dt.timedelta(days=MAYBE_REST_DAYS)).isoformat()
        want = f"near-{pid}"
        cos = catalog.companies()
        by_key = {catalog.ats_key(c): c for c in cos}
        by_name = {c["name"].lower(): c for c in cos}
        added, linked, starters, renames, packs_n, new, keys, skipped = [], [], 0, [], 0, [], [], 0
        items = []      # [board key, "a" (added) | "l" (already in the catalog, put on the list), name then]: what undo() goes by
        save = (lambda entry, con: None) if dry else catalog.save_company
        with catalog.db() as con:
            for e in emps:
                k = _key(e["cfg"])
                sk = "starter:" + k
                co = by_key.get(k)
                dirinfo = _dir_info(e)
                starter = bool(e.get("starter"))
                if co is not None and want in (co.get("sets") or []):
                    # already on this person's list: keep what the directory knows about it up to date
                    if dirinfo and co.get("dir") != dirinfo:
                        co["dir"] = dirinfo
                        save({kk: v for kk, v in co.items() if not kk.startswith("_")}, con)
                    if company_add.looks_like_code(co["name"]) or co["name"].startswith("Employer in "):
                        if not company_add.looks_like_code(e["name"]) and not e["name"].startswith("Employer") \
                                and e["name"].lower() not in by_name:
                            renames.append((co["name"], e["name"]))
                            by_name[e["name"].lower()] = co
                    if not starter:
                        near_n[co["name"]] = e["near"]
                        offered.add(k)
                    continue
                if k in offered or sk in offered:
                    continue
                if e.get("maybe") and pruned.get(_short(k), "") > rest:
                    continue
                if starter and not e.get("maybe") and _short(k) in pruned:
                    continue            # (a shipped starter that turned out not to hire nearby never comes back this way)
                if starter and co is None and not e.get("maybe") and e["name"].lower() in by_name:
                    continue            # (the catalog already has this employer under another board)
                if limit is not None and len(added) + len(linked) >= limit:
                    skipped += 1
                    continue            # (not offered: it can still be added later)
                offered.add(sk if starter else k)
                keys.append(sk if starter else k)
                if co is not None:
                    entry = {kk: v for kk, v in co.items() if not kk.startswith("_")}
                    entry["sets"] = sorted(set(co.get("sets") or []) | {want})
                    if dirinfo:
                        entry["dir"] = dirinfo
                    save(entry, con)
                    co.update(entry)
                    linked.append(co["name"])
                    items.append([k, "l", co["name"]])
                else:
                    name = e["name"].replace(",", "").strip()[:60]
                    if name.lower() in by_name:
                        name = f"{name[:44]} ({company_add.SYSTEM_LABEL.get(e['cfg']['ats'], e['cfg']['ats'])})"
                    if name.lower() in by_name:
                        name = f"{name[:52]} {_short(k)[:6]}"
                    sector = (e.get("sector") or "Large US employer") if starter and not e.get("maybe") else \
                        "Staffing agency" if e.get("kind") == "staffing" else SOURCE_SECTOR
                    entry = {"name": name, "tier": "dmv_office", "sector": sector, **e["cfg"], "sets": [want], "added_by": pid}
                    if dirinfo:
                        entry["dir"] = dirinfo
                    save(entry, con)
                    co = by_key[k] = by_name[name.lower()] = dict(entry)
                    added.append(name)
                    items.append([k, "a", name])
                if starter:
                    pending.add(co["name"])
                    starters += 1
                    packs_n += not e.get("maybe")
                # the order of the first check (near_order): openings nearby; starters by what is known about them
                near_n[co["name"]] = (e.get("near") or 0) if not starter else round(e.get("rank") or min(e.get("jobs") or 0, 99999) / 100000.0, 5)
                new.append({"name": co["name"], "near": e.get("near") or 0, "ats": e["cfg"].get("ats"), "starter": starter})
            # job snapshots: one catalog entry per source, shared by everyone near its postings
            jobs = {} if offline else near_jobs(pid, man)
            labels = {s: (man.get("sources") or {}).get(s, {}).get("label") for s in jobs}
            for src, n in sorted(jobs.items()):
                if not n or not re.fullmatch(r"[a-z]{2,20}", src):
                    continue
                k = "src:" + src
                if k in offered or (limit is not None and limit <= 0):
                    continue
                offered.add(k)
                keys.append(k)
                name = _source_name(src, labels.get(src))
                co = next((c for c in by_key.values() if c.get("ats") == ATS and c.get("source") == src), None)
                if co:
                    if want not in (co.get("sets") or []):
                        entry = {kk: v for kk, v in co.items() if not kk.startswith("_")}
                        entry["sets"] = sorted(set(co.get("sets") or []) | {want})
                        save(entry, con)
                    linked.append(co["name"])
                    items.append([k, "l", co["name"]])
                    near_n[co["name"]] = n
                    new.append({"name": co["name"], "near": n, "ats": ATS, "starter": False})
                else:
                    entry = {"name": name, "ats": ATS, "source": src, "tier": "national", "sector": SOURCE_SECTOR,
                             "sets": [want], "added_by": pid}
                    save(entry, con)
                    by_key[catalog.ats_key(entry)] = entry
                    added.append(name)
                    items.append([k, "a", name])
                    near_n[name] = n
                    new.append({"name": name, "near": n, "ats": ATS, "starter": False})
        out = {"added": added, "linked": linked, "near": sum(1 for e in emps if not e.get("starter")), "available": True,
               "reason": None, "jobs": jobs, "built": man.get("built"), "starters": starters, "offline": offline,
               "missing": info.get("missing") or [], "maybe": info.get("maybe", 0), "renamed": 0,
               "pack_starters": packs_n, "new": new, "skipped": skipped, "label": info.get("label") or "",
               "radius": info.get("radius") or 0, "remote_only": bool(info.get("remote_only"))}
        if dry:
            return out
        renamed = 0
        for old, new_name in renames:   # (after the transaction above: rename_company opens its own)
            try:
                if catalog.rename_company(old, new_name):
                    renamed += 1
                    _rename_in(rec, old, new_name)      # (this record is saved below, from memory)
                    near_n[new_name] = near_n.pop(old, 0)
                    if old in pending:
                        pending.discard(old); pending.add(new_name)
            except Exception:
                pass
        out["renamed"] = renamed
        batches = list(rec.get("batches") or [])
        if (added or linked) and tag and batches and batches[-1].get("tag") == tag:
            b = batches[-1]
            b.update(at=_now(), added=list(b.get("added") or []) + added, linked=list(b.get("linked") or []) + linked,
                     keys=list(b.get("keys") or []) + keys, items=list(b.get("items") or []) + items)
        elif added or linked:
            batches.append({"at": _now(), "added": added, "linked": linked, "keys": keys, "items": items, "weekly": bool(weekly),
                            "starter": bool(offline), **({"tag": tag} if tag else {})})
        rec.update(offered=sorted(offered), applied=_now(), built=man.get("built"), starters_pending=sorted(pending),
                   near_n=near_n, pruned=pruned, added=int(rec.get("added", 0)) + len(added) + len(linked),
                   batches=batches[-6:])
        if not weekly and not tag:
            rec["top_only"] = bool(limit is not None and skipped)
        if offline:
            rec["offline"] = True       # (the pages say plainly that this is the starter list, not the directory)
        else:
            rec.pop("offline", None)
        rec.pop("seen", None)
        _save_record(pid, rec)
        _PREVIEW.pop(pid, None)
        return out


# ---------------------------------------------------------------- preview and undo
_PREVIEW = {}       # pid -> (time, key, result)
TOP_CHOICES = (100, 250, 500, 1000)


def preview(pid, refresh=False):
    """What "Add employers near me" would add right now, without adding it: {available, reason, new (employers),
    jobs (their openings near the person), label, radius, remote_only, options: [{limit (None = all), employers,
    jobs, first_minutes, first_text, daily_minutes, daily_text}], daily_before: {minutes, text}, last: the last batch
    that can still be taken back}. Cached for a few minutes per search area."""
    import catalog, first_search
    st = _settings(pid)
    rec = record(pid)
    key = (str(st.get("home_zip")), str(st.get("directory_zip")), st.get("radius_miles"), st.get("directory_radius"),
           tuple(st.get("workplaces") or ()), bool(st.get("remote_us", True)), len(rec.get("offered") or []), rec.get("applied"))
    hit = _PREVIEW.get(pid)
    if hit and not refresh and hit[1] == key and time.time() - hit[0] < 300:
        return hit[2]
    if refresh:
        manifest(refresh=True)
    r = apply(pid, dry=True)
    out = {"available": r["available"], "reason": r.get("reason"), "new": 0, "jobs": 0, "options": [], "label": r.get("label", ""),
           "radius": r.get("radius", 0), "remote_only": bool(r.get("remote_only")), "last": last_batch(pid),
           "offline_start": bool(rec.get("offline")), "applied": rec.get("applied")}
    if r["available"]:
        import netsafe
        new = r["new"]
        cos = [c for c in catalog.companies(include_paused=False) if c.get("ats") in netsafe.CONFIG_RULES]
        have = {c["name"] for c in cos}
        before = first_search.fetch_minutes(cos)
        out.update(new=len(new), jobs=sum(x["near"] for x in new if not x["starter"]),
                   daily_before={"minutes": before, "text": first_search.minutes_text(before)})
        sizes = [n for n in TOP_CHOICES if n < len(new)] + [None]
        for n in sizes:
            part = new if n is None else new[:n]
            fresh = [x for x in part if x["name"] not in have]
            fm = first_search.fetch_minutes(part, first=True)
            dm = first_search.fetch_minutes(cos + fresh)
            out["options"].append({"limit": n, "employers": len(part), "jobs": sum(x["near"] for x in part if not x["starter"]),
                                   "first_minutes": fm, "first_text": first_search.minutes_text(fm),
                                   "daily_minutes": dm, "daily_text": first_search.minutes_text(dm)})
    _PREVIEW[pid] = (time.time(), key, out)
    return out


def _batch_companies(b, cos):
    """The companies a batch added, as they are in the catalog NOW: [(company, "a" | "l")]. An employer is found by its
    job board (system + config), which never changes, so one that was given a better name at its first fetch is
    still found; a batch stored before boards were recorded is found by name, then by the name its listing ids
    start with ("idp", what a renamed company keeps of its first name)."""
    import catalog
    by_key, by_name, by_idp, by_src = {}, {}, {}, {}
    for c in cos:
        by_key[catalog.ats_key(c)] = c
        by_name[c["name"]] = c
        if c.get("idp"):
            by_idp[c["idp"]] = c
        if c.get("ats") == ATS and c.get("source"):
            by_src[c["source"]] = c
    out, seen = [], set()

    def take(c, kind):
        if c is not None and c["name"] not in seen:
            seen.add(c["name"])
            out.append((c, kind))

    def by_k(k):
        k = str(k)
        if k.startswith("src:"):
            return by_src.get(k[4:])
        return by_key.get(k[8:] if k.startswith("starter:") else k)

    for it in b.get("items") or []:
        if isinstance(it, list) and len(it) >= 3:
            take(by_k(it[0]) or by_name.get(it[2]) or by_idp.get(it[2]), "l" if it[1] == "l" else "a")
    for kind, names_ in (("a", b.get("added") or []), ("l", b.get("linked") or [])):
        for nm in names_:
            take(by_name.get(nm) or by_idp.get(nm), kind)
    return out


def last_batch(pid):
    """The latest batch apply() added for this person that can be taken back: {at, employers} or None. employers is
    how many of them are on the person's list right now (what "Remove the N employers" will take off), job-listing
    sources not counted."""
    b = (record(pid).get("batches") or [])
    if not b:
        return None
    n = len(b[-1].get("added") or []) + len(b[-1].get("linked") or [])
    try:
        import catalog
        want = f"near-{pid}"
        live = [c for c, _ in _batch_companies(b[-1], catalog.companies()) if want in (c.get("sets") or [])]
        n = sum(1 for c in live if c.get("ats") != ATS) or len(live)
    except Exception:
        pass
    return {"at": b[-1].get("at"), "employers": n, "starter": bool(b[-1].get("starter"))}


def _rename_in(rec, old, new):
    """Swap a company name in one person's record (batches, starters still to be checked, the first check's order)."""
    swap = lambda xs: [new if x == old else x for x in (xs or [])]
    hit = False
    for b in rec.get("batches") or []:
        for k in ("added", "linked"):
            if old in (b.get(k) or []):
                b[k], hit = swap(b[k]), True
        for it in b.get("items") or []:
            if isinstance(it, list) and len(it) >= 3 and it[2] == old:
                it[2], hit = new, True
    if old in (rec.get("starters_pending") or []):
        rec["starters_pending"], hit = sorted(set(swap(rec["starters_pending"]))), True
    if old in (rec.get("near_n") or {}):
        rec["near_n"][new] = rec["near_n"].pop(old)
        hit = True
    return hit


def note_rename(old, new):
    """A company got a new name (catalog.rename_company): every person's record follows (batches, the order of the
    first check, starters still to be checked), so nothing here goes on pointing at a name that no longer exists."""
    with _APPLY:
        for pid in users():
            rec = record(pid)
            if rec and _rename_in(rec, old, new):
                _save_record(pid, rec)
                _PREVIEW.pop(pid, None)


def undo(pid):
    """Take back the last batch apply() added: employers only this person's Near me list had leave the catalog (their
    postings are closed, not deleted), the others just leave the list. They can be added again later. Returns
    {removed: n}."""
    import catalog
    with _APPLY:
        rec = record(pid)
        batches = list(rec.get("batches") or [])
        if not batches:
            return {"removed": 0}
        b = batches.pop()
        want = f"near-{pid}"
        pending = set(rec.get("starters_pending") or [])
        near_n = dict(rec.get("near_n") or {})
        removed = 0
        for co, kind in _batch_companies(b, catalog.companies()):
            name = co["name"]
            if want not in (co.get("sets") or []):
                continue
            sets = sorted(set(co.get("sets") or []) - {want})
            if sets or kind == "l":
                entry = {k: v for k, v in co.items() if not k.startswith("_")}
                entry["sets"] = sets
                catalog.save_company(entry)
            else:
                catalog.remove_company(name)
            pending.discard(name)
            near_n.pop(name, None)
            removed += 1
        rec.update(offered=sorted(set(rec.get("offered") or []) - set(b.get("keys") or [])), batches=batches,
                   starters_pending=sorted(pending), near_n=near_n, added=max(0, int(rec.get("added", 0)) - removed))
        if b.get("starter"):
            rec.pop("offline", None)
        _save_record(pid, rec)
        _PREVIEW.pop(pid, None)
        return {"removed": removed}


def near_order(pid):
    """{company name: postings near this person when it was added} (the order the first check goes in)."""
    return dict(record(pid).get("near_n") or {})


def _short(k):
    return hashlib.sha1(k.encode()).hexdigest()[:12]


def prune_starters(pid):
    """After a fetch: take the starters (shipped-pack employers, and the directory's "maybe near" big boards) off this
    person's Near me list when none of their open jobs is within the radius (or US-remote, when remote work is OK).
    Starters not fetched successfully yet stay pending. A pruned starter can come back later through the directory
    (with places that show it hires nearby); it isn't tried again as a "maybe" for MAYBE_REST_DAYS. Returns the names
    taken off."""
    import catalog, geo
    with _APPLY:
        rec = record(pid)
        pending = set(rec.get("starters_pending") or [])
        if not pending:
            return []
        a = area(pid)
        if not a:
            return []
        la, lo, label, radius, remote_only, remote_ok = a
        want = f"near-{pid}"
        cos = {c["name"]: c for c in catalog.companies()}
        listings = {}   # (partial rows count too: Workday stores every posting's place even without its text)
        with catalog.db() as con:
            q = f"SELECT company, data FROM listings WHERE closed_at IS NULL AND company IN ({','.join('?' * len(pending))})"
            for r in con.execute(q, sorted(pending)):
                try:
                    listings.setdefault(r["company"], []).append(json.loads(r["data"]))
                except ValueError:
                    pass
        offered = set(rec.get("offered") or [])
        pruned = dict(rec.get("pruned") or {})
        dropped = []
        for name in sorted(pending):
            co = cos.get(name)
            if co is None or want not in (co.get("sets") or []):
                pending.discard(name)          # (removed by hand, or gone)
                continue
            if (co.get("_fetch") or {}).get("status") not in ("ok", "capped"):
                continue                        # not fetched (successfully) yet: decide next time
            keep = False
            for j in listings.get(name, []):
                remote = bool(j.get("remote_strict") or j.get("remote_bare"))
                if remote and remote_ok:
                    keep = True
                elif not remote_only and la is not None and geo.within(j.get("locations") or [], (la, lo), radius)[0]:
                    keep = True
                if keep:
                    break
            pending.discard(name)
            if keep:
                continue
            entry = {k: v for k, v in co.items() if not k.startswith("_")}
            sets = sorted(set(co.get("sets") or []) - {want})
            if sets:
                entry["sets"] = sets
                catalog.save_company(entry)
            else:
                catalog.remove_company(name)    # (only this person's starter list had it)
            offered.discard("starter:" + catalog.ats_key(co))
            pruned[_short(catalog.ats_key(co))] = dt.date.today().isoformat()
            dropped.append(name)
        rec.update(starters_pending=sorted(pending), offered=sorted(offered), pruned=pruned)
        _save_record(pid, rec)
        return dropped


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
           "offline_start": bool(rec.get("offline")), "last": last_batch(pid), "top_only": bool(rec.get("top_only")),
           "starters_pending": len(rec.get("starters_pending") or []),
           "built": (man or {}).get("built"), "checked": (man or {}).get("_fetched"), "near_list": 0,
           "sources": {k: {"label": v.get("label"), "attribution": v.get("attribution")} for k, v in ((man or {}).get("sources") or {}).items()
                       if isinstance(v, dict)},
           "url_default": not os.environ.get("SIFTWELL_DIRECTORY_URL")}
    try:
        import catalog
        out["near_list"] = sum(1 for s in catalog.sets_map().values() if f"near-{pid}" in s)
    except Exception:
        pass
    st = _settings(pid)
    # no home ZIP (the older built-in area decides which jobs are near): the directory can have its own area
    out["own_area"] = not str(st.get("home_zip") or "").strip() and (st.get("workplaces") or []) != ["remote"]
    out["directory_zip"] = str(st.get("directory_zip") or "")
    out["directory_radius"] = int(st.get("directory_radius") or st.get("radius_miles") or 35)
    return out


# ---------------------------------------------------------------- weekly refresh
def start_background(log=lambda m: print(m, flush=True)):
    def loop():
        time.sleep(float(os.environ.get("SIFTWELL_DIRECTORY_DELAY") or 120))
        while True:
            try:
                for pid in users():     # starters from the shipped packs whose first fetch has happened since
                    try:
                        prune_starters(pid)
                    except Exception:
                        pass
                if users() and _stale():
                    man = refresh(force=True)
                    if not man.get("_error"):
                        for pid in users():
                            import people
                            if people.exists(pid):
                                r = apply(pid, weekly=True)
                                if r["available"] and (r["added"] or r["linked"]):
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
OFFLINE_MSG = ("Siftwell couldn’t reach its employer directory, so nothing was added. Check your internet connection and "
               "press Try the directory again.")
NO_PLACE_MSG = "Add your home ZIP (Filters, then My search) so Siftwell knows where to look."


def handle_get(h, path, pid):
    if path == "/api/directory":
        h._send(200, status(pid))
        return True
    if path == "/api/directory/preview":
        try:
            h._send(200, preview(pid, refresh="refresh=1" in (h.path.split("?", 1) + [""])[1]))
        except Exception as e:
            print("directory preview failed:", type(e).__name__, e, flush=True)
            h._send(200, {"available": False, "reason": "error", "new": 0, "jobs": 0, "options": []})
        return True
    return False


def handle_post(h, path, body, pid, server):
    if path == "/api/directory/undo":
        import first_search
        if first_search.JOB["running"]:
            h._send(409, {"error": "Siftwell is checking employers right now. Pause that first, then remove them."})
            return True
        try:
            r = undo(pid)
        except Exception as e:
            print("directory undo failed:", type(e).__name__, e, flush=True)
            h._send(500, {"error": "That didn’t work. Nothing was removed."})
            return True
        if r["removed"]:
            server._actlog("companies removed", pid, f"{r['removed']} employers the directory had added (taken back)")
            server.request_recompute([pid])
            first_search._CACHE.pop(pid, None); first_search._EST.clear()
        h._send(200, r)
        return True
    if path == "/api/directory/area":
        # an area just for the directory, for people without a home ZIP (their job filter stays as it is)
        import geo, people
        z = str(body.get("zip") or "").strip()[:60]
        if z:
            try:
                ok = geo.geocode_home(z)
            except ValueError:
                ok = None
            if not ok:
                h._send(400, {"error": f"Couldn’t find “{z}”. Use a 5-digit ZIP or City, ST."})
                return True
        try:
            rad = max(5, min(150, int(body.get("radius") or 35)))
        except (TypeError, ValueError):
            rad = 35
        people.save_settings({"directory_zip": z, "directory_radius": rad}, pid)
        _PREVIEW.pop(pid, None)
        h._send(200, {"ok": True, **status(pid)})
        return True
    if path != "/api/directory/apply":
        return False
    limit = body.get("limit")
    try:
        limit = None if limit in (None, "", "all") else max(1, min(100000, int(limit)))
    except (TypeError, ValueError):
        limit = None
    try:
        if body.get("retry") or record(pid).get("offline"):
            manifest(refresh=True)       # "Try the directory again"
        r = apply(pid, limit=limit)
    except Exception as e:
        print("directory apply failed:", type(e).__name__, e, flush=True)
        h._send(500, {"error": "Siftwell couldn’t read its employer directory. Nothing was added."})
        return True
    if not r["available"]:
        msg = {"no_place": NO_PLACE_MSG, "offline": OFFLINE_MSG}.get(r["reason"], "The directory isn’t available right now.")
        r.pop("new", None)
        h._send(409, {"error": msg, **r})
        return True
    names = r["added"] + r["linked"]
    r["fetching"] = False
    import first_search
    first_search._CACHE.pop(pid, None); first_search._EST.clear()
    first_search.note_added(pid)
    r["pending"] = len(first_search.pending(pid))
    if body.get("fetch") and r["pending"]:
        # the staged first check (most jobs nearby first; the board fills in as it goes; survives a restart)
        ok, err = first_search.start_checking(pid)
        r["fetching"] = ok or "already" in (err or "")
    if names:
        server._actlog("companies added", pid, f"{len(names)} from the Siftwell directory")
    # (job-listing sources such as USAJOBS ride along with the employers: "the top 250" is 250 employers, and says so)
    r["sources"] = sum(1 for x in (r.get("new") or []) if x.get("ats") == ATS)
    for k in ("jobs", "new"):
        r.pop(k, None)
    r["added"], r["linked"] = len(r["added"]), len(r["linked"])
    r["employers"] = max(0, r["added"] + r["linked"] - r["sources"])
    r["last"] = last_batch(pid)
    h._send(200, r)
    return True


# ---------------------------------------------------------------- Settings -> Employer directory
CAT = ("directory", "Employer directory", '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/><path d="M9 10h.01"/><path d="M15 10h.01"/>')

PANE_HTML = """<section class="sgsec"><h3 class="sgtitle">Employers near you</h3><div class="sgroup">
<div class="srow stack"><div class="slab"><span>Siftwell employer directory</span><small id="dirState" role="status" aria-live="polite">Checking…</small></div>
<div id="dirArea" hidden><div class="bk-btnrow" style="align-items:flex-end">
<label class="note" style="display:flex;flex-direction:column;gap:3px">Look for employers near<input type="text" id="dirZip" placeholder="ZIP code or City, ST" autocomplete="postal-code" style="min-width:0;width:13em;max-width:100%"></label>
<label class="note" style="display:flex;flex-direction:column;gap:3px">Within<select id="dirRadius"><option value="10">10 miles</option><option value="25">25 miles</option><option value="35">35 miles</option><option value="50">50 miles</option><option value="75">75 miles</option></select></label>
<button class="btn" type="button" id="dirAreaSave">Use this area</button></div>
<small class="note" style="display:block;margin-top:6px">This only chooses which employers are added. Which jobs count as near you stays exactly as it is; to change that, set your home ZIP on the board (Filters, then My search).</small></div>
<div id="dirPlan" class="note" style="display:none"></div>
<div class="bk-btnrow"><button class="btn primary" type="button" id="dirApply" style="white-space:normal;max-width:100%;height:auto;text-align:left" disabled>Add employers near me</button>
<button class="btn" type="button" id="dirRetry" hidden>Try the directory again</button>
<button class="btn" type="button" id="dirUndo" hidden>Remove the employers this added</button></div>
<span class="note" id="dirMsg" role="status" aria-live="polite"></span></div>
<div class="srow stack"><div class="slab"><label for="ldSource">Where my directory comes from</label><small id="ldOrigin" role="status" aria-live="polite">Checking…</small></div>
<div class="bk-btnrow"><select id="ldSource" style="max-width:100%">
<option value="shared">Siftwell’s shared directory (recommended)</option>
<option value="local">Built on this computer</option>
<option value="both">Both</option></select></div>
<small class="note" id="ldSourceNote" style="display:block;margin-top:4px"></small></div>
<div class="srow stack" id="ldRow"><div class="slab"><span>Build my own directory</span><small id="ldWhat">Siftwell can read employers’ public job pages itself, on this computer, instead of downloading the shared directory. It uses no Claude.</small></div>
<div id="ldProg" hidden><div id="ldLine" role="status" aria-live="polite" style="font-weight:500"></div>
<div role="progressbar" aria-label="Directory build progress" aria-valuemin="0" aria-valuemax="100" id="ldBarBox" style="height:6px;background:var(--bar);border-radius:3px;overflow:hidden;margin:6px 0"><i id="ldBar" style="display:block;height:100%;background:var(--bar-fill);width:0;transition:width .4s"></i></div>
<small class="note" id="ldEta" style="display:block"></small></div>
<label class="note" id="ldAddLab" style="display:flex;gap:8px;align-items:flex-start;margin:6px 0"><input type="checkbox" id="ldAdd" checked style="width:auto;height:auto;flex:none;margin-top:3px"><span>Add the employers it finds near me to my list as it goes, and check their openings (you can take them all back afterwards)</span></label>
<div class="bk-btnrow"><button class="btn" type="button" id="ldStart" style="white-space:normal;max-width:100%;height:auto;min-height:var(--h);text-align:left" disabled>Build my own directory</button>
<button class="btn" type="button" id="ldPause" hidden>Pause</button></div>
<label class="note" style="display:flex;gap:8px;align-items:flex-start;margin-top:8px"><input type="checkbox" id="ldDiscover" style="width:auto;height:auto;flex:none;margin-top:3px"><span><b style="font-weight:500">Also look for job sites that aren’t on the list yet</b> (optional). Siftwell then searches public web records (the Common Crawl index) from this computer during a build, slowly and at most once every 30 days, because many copies of Siftwell asking those free services at once would be unfair to them.</span></label>
<small class="note" id="ldData" style="display:block;margin-top:8px"></small>
<span class="note" id="ldMsg" role="status" aria-live="polite"></span></div>
<div class="srow"><div class="slab"><span>Find more with Claude</span><small>Claude can also search the web for employers the directory doesn't have. It uses your Claude plan, and only runs when you start it.</small></div>
<div class="sctl"><a class="btn sm" href="/catalog#find">Find employers</a></div></div></div>
<p class="sfoot">The directory is a free list of employers whose job pages Siftwell can read, with the places they hire, rebuilt every week
from public sources (web crawl indexes, certificate logs and public employer lists). It needs no key, no account and no Claude.
Siftwell downloads only whole-state files for the states around your home (and a remote-jobs file if you only want remote work), so
your exact location never leaves this computer. Once a week it checks for newly listed employers near you and adds them (not if you chose
to add only the ones with the most openings); employers you stop watching stay off. <span id="dirSources"></span></p>
<p class="sfoot">There are two ways to get the directory, and neither uses Claude. <b>Shared</b>: Siftwell downloads one file per state from the
Siftwell project. <b>Built on this computer</b>: Siftwell starts from the list of job sites that comes with the app and visits employers’
public job pages itself, politely (it follows each site’s robots.txt and waits between requests), the ones last seen hiring near you
first; with this choice alone it never contacts the shared directory. It keeps working even if the Siftwell project goes away, but takes
hours instead of seconds, and afterwards about 40 minutes a week in the background to stay up to date.</p></section>"""

PANE_JS = r"""(function(){
const $ = id => document.getElementById(id);
if (!$("dirApply")) return;
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const day = s => { try { return new Date(s).toLocaleDateString(); } catch(e) { return s; } };
const n = x => Number(x || 0).toLocaleString();
const post = (url, body) => fetch(url, {method: "POST", headers: H, body: JSON.stringify(body || {})}).then(r => r.json().then(d => ({ok: r.ok, d})));
let PV = null;
function limit(){ const s = $("dirOpt"); return s && s.value !== "all" ? Number(s.value) : null; }
function plan(){
  // Before anything is added: how many employers, about how many openings, and what it costs in time.
  const box = $("dirPlan"), pv = PV;
  if (!pv || !pv.available) {
    box.style.display = pv && (pv.reason === "offline" || pv.reason === "error") ? "block" : "none";
    box.innerHTML = "<b>Siftwell can’t reach its employer directory right now.</b> Check your internet connection, then press Try the directory again. Or build the directory on this computer instead (Build my own directory, below).";
    $("dirApply").disabled = true; $("dirRetry").hidden = !(pv && (pv.reason === "offline" || pv.reason === "error"));
    return;
  }
  $("dirRetry").hidden = !pv.offline_start;
  if (!pv.new) { box.style.display = "block"; box.textContent = "There are no new employers to add right now. Employers you took off your list stay off."; $("dirApply").disabled = true; $("dirApply").textContent = "Add employers near me"; return; }
  const o = pv.options, all = o[o.length - 1];
  const def = all.employers <= 500 ? all : (o.filter(x => x.limit && x.limit <= 500).pop() || o[0]);
  const keep = $("dirOpt") ? $("dirOpt").value : String(def.limit || "all");
  box.style.display = "block";
  box.innerHTML = `<b>${n(pv.new)} employers</b> ${pv.remote_only ? "that hire remotely" : `with openings within ${pv.radius} miles of ${esc(pv.label)}`} can be added.` +
    (o.length > 1 ? ` <label>Add <select id="dirOpt">${o.map(x => `<option value="${x.limit || "all"}">${x.limit ? `the ${n(x.employers)} with the most openings near you` : `all ${n(x.employers)}`}</option>`).join("")}</select></label>` : "") +
    `<div id="dirEst" style="margin-top:4px"></div>`;
  const say = () => {
    const v = $("dirOpt") ? $("dirOpt").value : "all", x = o.find(y => String(y.limit || "all") === v) || all, b = pv.daily_before || {};
    $("dirEst").textContent = `${x.jobs ? `About ${n(x.jobs)} openings near you. ` : ""}First check: ${x.first_text} (your board fills in as it goes). Daily Find new jobs afterwards: ${x.daily_text}` + (b.minutes && b.text !== x.daily_text ? `, up from ${b.text}` : "") + ". In a household, the daily check covers everyone’s employers once.";
    $("dirApply").textContent = `Add ${n(x.employers)} employer${x.employers === 1 ? "" : "s"}`;
  };
  if ($("dirOpt")) { $("dirOpt").value = [...$("dirOpt").options].some(z => z.value === keep) ? keep : String(def.limit || "all"); $("dirOpt").addEventListener("change", say); }
  say(); $("dirApply").disabled = false;
}
function preview(refresh){
  return fetch("/api/directory/preview" + (refresh ? "?refresh=1" : "")).then(r => r.json()).then(pv => { PV = pv; plan(); return pv; }).catch(() => { PV = null; plan(); });
}
function load(){
  return fetch("/api/directory").then(r => r.json()).then(d => {
    let t = d.possible ? (d.remote_only ? "Remote-friendly employers anywhere in the US." : `Employers with openings within ${d.radius} miles of ${esc(d.label)}.`)
                       : "Siftwell needs to know where to look.";
    if (d.offline_start) t = `<b>Siftwell couldn’t reach its employer directory when it set up your search</b>, so it started with a starter list of large US employers that comes with the app${d.starters_pending ? ` (${n(d.starters_pending)} still to be checked; the ones with no jobs near you are taken off)` : ""}. Press Try the directory again to get the employers near you, or build the directory on this computer (Build my own directory, below).`;
    else if (d.applied) t += ` ${n(d.near_list)} employers on your list were found this way` + (d.last && d.last.employers && d.last.employers < d.near_list ? ` (${n(d.last.employers)} of them in the last addition, ${day(d.last.at)}).` : `; last added ${day(d.applied)}.`);
    if (d.built && !d.offline_start) t += ` Directory updated ${day(d.built)}.`;
    $("dirState").innerHTML = t;
    $("dirArea").hidden = !d.own_area;
    if (d.own_area) { if (document.activeElement !== $("dirZip")) $("dirZip").value = d.directory_zip || ""; $("dirRadius").value = String(d.directory_radius || 35); }
    $("dirUndo").hidden = !(d.last && d.last.employers);
    if (d.last) $("dirUndo").textContent = `Remove the ${n(d.last.employers)} employers added ${day(d.last.at)}`;
    const src = Object.values(d.sources || {}).map(s => s.attribution && s.attribution.link ? `<a href="${esc(s.attribution.link)}" target="_blank" rel="noopener">${esc(s.attribution.name)}</a>` : "").filter(Boolean);
    $("dirSources").innerHTML = src.length ? `It also brings job postings from ${src.join(", ")}, each linked to the original posting.` : "";
    if (!d.possible) { $("dirApply").disabled = true; $("dirPlan").style.display = "none"; return; }
    return preview(false);
  }).catch(() => { $("dirState").textContent = "Couldn’t reach Siftwell."; });
}
function added(d){
  const k = d.employers != null ? d.employers + (d.sources || 0) : (d.added || 0) + (d.linked || 0), p = d.pending || 0, e = d.employers != null ? d.employers : k;
  $("dirMsg").textContent = k ? `Added ${n(e)} employer${e === 1 ? "" : "s"}${d.sources ? ` and ${n(d.sources)} job listing source${d.sources === 1 ? "" : "s"}` : ""} to your list.` + (d.fetching ? " Siftwell is checking their openings now, the ones with the most jobs near you first; your board fills in as it goes." : " Their jobs show up after the next Find new jobs.")
                              : p && d.fetching ? `No new employers to add, but ${n(p)} on your list haven’t been checked yet. Siftwell is checking them now; your board fills in as it goes.`
                              : "No new employers near you in the directory right now. Employers you took off your list stay off.";
  load();
}
$("dirApply").addEventListener("click", () => {
  $("dirApply").disabled = true; $("dirMsg").textContent = "Adding…";
  post("/api/directory/apply", {fetch: true, limit: limit()}).then(({ok, d}) => {
    if (!ok) { $("dirMsg").textContent = d.error || "That didn’t work."; load(); return; }
    added(d);
  }).catch(() => { $("dirApply").disabled = false; $("dirMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
});
$("dirRetry").addEventListener("click", () => {
  $("dirRetry").disabled = true; $("dirMsg").textContent = "Trying the directory…";
  preview(true).then(pv => {
    $("dirRetry").disabled = false;
    $("dirMsg").textContent = pv && pv.available ? (pv.new ? "The directory is back. Choose how many employers to add." : "The directory is back.") : "Still can’t reach it. Check your internet connection and try again.";
  });
});
$("dirUndo").addEventListener("click", async () => {
  const ask = window.appConfirm || (m => Promise.resolve(confirm(m)));
  if (!await ask($("dirUndo").textContent + "?\n\nThey leave your list (their jobs leave your board). You can add them again later.", "Remove them")) return;
  $("dirUndo").disabled = true; $("dirMsg").textContent = "Removing…";
  post("/api/directory/undo").then(({ok, d}) => {
    $("dirUndo").disabled = false;
    $("dirMsg").textContent = ok ? `Removed ${n(d.removed)} employers. Your board is being re-checked.` : (d.error || "That didn’t work.");
    load();
  }).catch(() => { $("dirUndo").disabled = false; $("dirMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
});
$("dirAreaSave").addEventListener("click", () => {
  $("dirAreaSave").disabled = true; $("dirMsg").textContent = "Saving…";
  post("/api/directory/area", {zip: $("dirZip").value, radius: $("dirRadius").value}).then(({ok, d}) => {
    $("dirAreaSave").disabled = false;
    $("dirMsg").textContent = ok ? "" : (d.error || "That didn’t work.");
    if (ok) load();
  }).catch(() => { $("dirAreaSave").disabled = false; $("dirMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
});
// ---- Where my directory comes from + Build my own directory (localdir.py). One status call drives both rows.
let LD = null, ldTimer = null;
const SRC_NOTE = {
  shared: "Siftwell downloads one file per state from the Siftwell project. Fast; needs the project to stay online.",
  local: "Siftwell never contacts the shared directory. It uses only what it has read itself on this computer.",
  both: "Siftwell uses the shared directory and what it has read itself; for each employer the newer reading counts."};
function ldOrigin(d){
  const parts = [];
  if (d.shared_built && d.source !== "local") parts.push(`Siftwell’s shared directory, updated ${day(d.shared_built)}`);
  if (d.local_built && d.source !== "shared") parts.push(`${parts.length ? "b" : "B"}uilt on this computer, ${day(d.local_built)}${d.local_complete ? "" : " (not finished yet)"}`);
  if (!parts.length) return "Starter list only" + (d.source === "local" ? ": your own directory hasn’t been built yet." : d.source === "both" ? ": the shared directory couldn’t be reached, and your own hasn’t been built yet." : ": the shared directory hasn’t been reached yet.");
  return parts.join(" and ") + ".";
}
function ldDraw(d){
  LD = d;
  if (document.activeElement !== $("ldSource")) $("ldSource").value = d.source;
  $("ldOrigin").textContent = ldOrigin(d);
  $("ldSourceNote").textContent = SRC_NOTE[d.source] || "";
  $("ldDiscover").checked = !!d.discover;
  const e = d.estimate || {}, pass = d.running && d.mode === "pass";
  $("ldProg").hidden = !pass;
  $("ldPause").hidden = !pass;
  $("ldAddLab").style.display = pass || !d.possible ? "none" : "flex";
  if (pass) {
    const pct = d.total ? Math.round(100 * d.done / d.total) : 1;
    $("ldLine").textContent = d.line;
    $("ldBar").style.width = pct + "%"; $("ldBarBox").setAttribute("aria-valuenow", pct);
    $("ldEta").textContent = !d.total ? "" : (d.near_eta_text ? `Employers near you: ${n(d.near_done)} of ${n(d.near_total)} job sites done, ${d.near_eta_text} to go. ` : `The job sites last seen hiring near you are done. `) + `Everything: ${d.eta_text || "a while"} to go.` + ((d.resting || []).length ? ` A job system asked Siftwell to slow down, so it is leaving it alone for a few minutes (${esc(d.resting.join(", "))}).` : "") + (d.adding ? ` Employers found near you are being added to your list (${n(d.added)} so far).` : " Nothing is added to your list by itself; use Add employers near me above.");
    $("ldWhat").textContent = "Siftwell is reading employers’ public job pages on this computer. You can keep using Siftwell, close this page, or pause; it carries on where it stopped. It uses no Claude.";
  } else if (d.running) {
    $("ldWhat").textContent = "Siftwell is doing its weekly check of your directory in the background (about 40 minutes at most). It uses no Claude.";
  } else if (d.unfinished) {
    $("ldWhat").textContent = `${d.paused ? "Paused. " : ""}Siftwell has checked ${n(e.sites - e.left)} of ${n(e.sites)} job sites so far${e.left ? `; ${e.all_text} to go` : ""}. Nothing it read is lost.`;
  } else if (d.local_complete) {
    $("ldWhat").textContent = `Your own directory is built (${n(d.local_employers)} employers with openings, across the US${d.pass_minutes ? `; it took ${n(Math.round(d.pass_minutes))} minutes` : ""}). Siftwell keeps it up to date once a week in the background${d.weekly_at ? `; last checked ${day(d.weekly_at)}` : ""}.`;
  } else {
    $("ldWhat").textContent = d.possible ? (d.offer || "") : "Siftwell needs to know where to look first: add your home ZIP on the board (Filters, then My search).";
  }
  const du = d.data || {};
  $("ldData").textContent = (du.first_mb ? `Internet data: a first build uses about ${n(du.first_mb)} MB (${du.measured ? "measured on this computer" : "measured when this version was made"}: about ${du.mb_per_1000} MB for every 1,000 job sites; Siftwell reads only the lists of openings, compressed), the weekly check a small part of that. ` : "")
    + (d.metered ? "Windows says this connection is metered: Siftwell won’t continue a build or run the weekly check by itself on it, and asks before starting one." : "");
  const b = $("ldStart");
  b.hidden = !!d.running; b.disabled = !d.possible;
  b.textContent = d.unfinished ? "Continue building" : d.local_complete ? "Build it again from the start" : "Build my own directory";
  clearTimeout(ldTimer);
  ldTimer = setTimeout(ldLoad, d.running ? 3000 : 30000);
}
function ldLoad(){ return fetch("/api/localdir").then(r => r.json()).then(ldDraw).catch(() => { clearTimeout(ldTimer); ldTimer = setTimeout(ldLoad, 10000); }); }
$("ldSource").addEventListener("change", () => {
  const v = $("ldSource").value;
  if (v === "local" && LD && !LD.local_built && !LD.running && !confirm("Use only a directory built on this computer?\n\nSiftwell will stop downloading the shared directory. Until your own is built (press Build my own directory), new employers near you can’t be added.")) { $("ldSource").value = LD.source; return; }
  $("ldMsg").textContent = "Saving…";
  post("/api/localdir/prefs", {source: v}).then(({ok, d}) => { $("ldMsg").textContent = ok ? "Saved." : (d.error || "That didn’t work."); if (ok) { ldDraw(d); load(); } })
    .catch(() => { $("ldMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
});
$("ldDiscover").addEventListener("change", () => {
  post("/api/localdir/prefs", {discover: $("ldDiscover").checked}).then(({ok, d}) => { $("ldMsg").textContent = ok ? ($("ldDiscover").checked ? "Saved. It runs with the next build." : "Saved.") : (d.error || "That didn’t work."); })
    .catch(() => { $("ldMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
});
$("ldStart").addEventListener("click", () => {
  const again = LD && LD.local_complete && !LD.unfinished;
  if (again && !confirm("Build your directory again from the start?\n\nSiftwell reads every job site again (" + ((LD.estimate || {}).all_text || "a few hours") + "). The weekly check already keeps it up to date.")) return;
  const go = meteredOk => {
    $("ldStart").disabled = true; $("ldMsg").textContent = "Starting…";
    post("/api/localdir/start", {add: $("ldAdd").checked ? "all" : "none", fresh: !!again, metered_ok: !!meteredOk}).then(({ok, d}) => {
      if (!ok && d.metered && !meteredOk) { $("ldStart").disabled = false; $("ldMsg").textContent = ""; if (confirm(d.error + "\n\nBuild anyway?")) go(true); return; }
      $("ldMsg").textContent = ok ? "" : (d.error || "That didn’t work.");
      if (ok) ldDraw(d); else $("ldStart").disabled = false;
    }).catch(() => { $("ldStart").disabled = false; $("ldMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
  };
  go(false);
});
$("ldPause").addEventListener("click", () => {
  $("ldPause").disabled = true; $("ldMsg").textContent = "Pausing…";
  post("/api/localdir/pause").then(() => { setTimeout(() => { $("ldPause").disabled = false; $("ldMsg").textContent = "Paused. Nothing it read is lost."; ldLoad(); load(); }, 2500); })
    .catch(() => { $("ldPause").disabled = false; $("ldMsg").textContent = "Couldn’t reach Siftwell. Is it still running?"; });
});
load(); ldLoad();
})();"""
PANE_SCRIPT = "<script>" + PANE_JS + "</script>"
