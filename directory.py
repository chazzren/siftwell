"""The Siftwell employer directory: a free, nationwide list of employers whose jobs Siftwell can read, with where they
hire, built every week by a GitHub Actions job (scripts/build_index.py) and published on this repository's `index`
branch. No key, no account, no Claude.

The app downloads only the parts it needs: whole state files (states/OH.json.gz), so the exact home is never revealed,
plus remote.json.gz for remote-only searches, and the matching job snapshots (jobs/OH.json.gz: postings from sources
that publish postings rather than employer feeds, e.g. USAJOBS). Files are cached in DATA/directory/ (never the app
folder), checked against the manifest's SHA-256, refreshed at most once a week, and used from the cache when offline.

What it does with them:
  apply(pid)        puts EVERY employer within the person's radius (or the top remote-friendly ones for remote-only
                    searches) on their "Near me" list (near-<pid>), plus one catalog entry per job-snapshot source with
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

Routes (server.py): GET /api/directory, POST /api/directory/apply {fetch}. Test hook: SIFTWELL_DIRECTORY_URL=<base>
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
    if man.get("_error") and not man.get("states"):
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


def apply(pid, weekly=False):
    """Add EVERY directory employer near this person to their Near me list (and the job-snapshot sources with postings
    near them). Employers offered before are skipped, so taking one off the list sticks; the weekly refresh therefore
    adds exactly the newly indexed ones. Returns
    {added: [names], linked: [names already in the catalog, now on the list], near: n, available: bool, reason,
     starters: n added to be checked and kept only if they turn out to hire nearby, renamed: n}.

    Entries already on the list get their directory facts refreshed (where the employer hires) and, when their name is
    a board code, the readable name the directory has now.

    When the directory can't be had for this person's area (offline, or that state isn't published yet), the large
    national employers shipped in packs/ are added as starters; prune_starters() later drops the ones with no jobs near
    the person. Directory data wins whenever it is there (same board = same employer)."""
    import catalog, company_add
    with _APPLY:
        man = manifest()
        emps, info = near_employers(pid, man)
        if info.get("reason") == "no_place":
            return {"added": [], "linked": [], "near": 0, "available": False, "reason": "no_place", "starters": 0}
        offline = info.get("reason") == "offline"
        if offline or info.get("missing"):
            have = {_key(e["cfg"]) for e in emps}
            emps = emps + [p for p in pack_employers() if _key(p["cfg"]) not in have]
        rec = record(pid)
        offered = set(rec.get("offered") or [])
        pending = set(rec.get("starters_pending") or [])
        pruned = dict(rec.get("pruned") or {})
        near_n = dict(rec.get("near_n") or {})
        rest = (dt.date.today() - dt.timedelta(days=MAYBE_REST_DAYS)).isoformat()
        want = f"near-{pid}"
        cos = catalog.companies()
        by_key = {catalog.ats_key(c): c for c in cos}
        by_name = {c["name"].lower(): c for c in cos}
        added, linked, starters, renames = [], [], 0, []
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
                        catalog.save_company({kk: v for kk, v in co.items() if not kk.startswith("_")}, con)
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
                if starter and co is None and not e.get("maybe") and e["name"].lower() in by_name:
                    continue            # (the catalog already has this employer under another board)
                offered.add(sk if starter else k)
                if co is not None:
                    entry = {kk: v for kk, v in co.items() if not kk.startswith("_")}
                    entry["sets"] = sorted(set(co.get("sets") or ["tech"]) | {want})
                    if dirinfo:
                        entry["dir"] = dirinfo
                    catalog.save_company(entry, con)
                    co.update(entry)
                    linked.append(co["name"])
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
                    catalog.save_company(entry, con)
                    co = by_key[k] = by_name[name.lower()] = dict(entry)
                    added.append(name)
                if starter:
                    pending.add(co["name"])
                    starters += 1
                near_n[co["name"]] = e.get("near") or 0
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
                        catalog.save_company(entry, con)
                    linked.append(co["name"])
                    near_n[co["name"]] = n
                else:
                    entry = {"name": name, "ats": ATS, "source": src, "tier": "national", "sector": SOURCE_SECTOR,
                             "sets": [want], "added_by": pid}
                    catalog.save_company(entry, con)
                    by_key[catalog.ats_key(entry)] = entry
                    added.append(name)
                    near_n[name] = n
        renamed = 0
        for old, new in renames:        # (after the transaction above: rename_company opens its own)
            try:
                if catalog.rename_company(old, new):
                    renamed += 1
                    near_n[new] = near_n.pop(old, 0)
                    if old in pending:
                        pending.discard(old); pending.add(new)
            except Exception:
                pass
        rec.update(offered=sorted(offered), applied=_now(), built=man.get("built"), starters_pending=sorted(pending),
                   near_n=near_n, pruned=pruned, added=int(rec.get("added", 0)) + len(added) + len(linked))
        rec.pop("seen", None)
        _save_record(pid, rec)
        return {"added": added, "linked": linked, "near": sum(1 for e in emps if not e.get("starter")), "available": True,
                "reason": None, "jobs": jobs, "built": man.get("built"), "starters": starters, "offline": offline,
                "missing": info.get("missing") or [], "maybe": info.get("maybe", 0), "renamed": renamed}


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
    import first_search
    r["pending"] = len(first_search.pending(pid))
    if body.get("fetch") and r["pending"]:
        # the staged first check (most jobs nearby first; the board fills in as it goes; survives a restart)
        ok, err = first_search.start_checking(pid)
        r["fetching"] = ok or "already" in (err or "")
    server._actlog("companies added", pid, f"{len(names)} from the Siftwell directory")
    r.pop("jobs", None)
    r["added"], r["linked"] = len(r["added"]), len(r["linked"])
    h._send(200, r)
    return True


# ---------------------------------------------------------------- Settings -> Employer directory
CAT = ("directory", "Employer directory", '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/><path d="M9 10h.01"/><path d="M15 10h.01"/>')

PANE_HTML = """<section class="sgsec"><h3 class="sgtitle">Employers near you</h3><div class="sgroup">
<div class="srow stack"><div class="slab"><span>Siftwell employer directory</span><small id="dirState">Checking…</small></div>
<div class="bk-btnrow"><button class="btn primary" type="button" id="dirApply" style="white-space:normal;max-width:100%;height:auto;text-align:left">Add employers near me from the Siftwell directory</button></div>
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
      const k = (d.added || 0) + (d.linked || 0), p = d.pending || 0;
      $("dirMsg").textContent = k ? `Added ${k.toLocaleString()} employers to your Near me list.` + (d.fetching ? " Siftwell is checking their openings now, the ones with the most jobs near you first; your board fills in as it goes." : " Their jobs show up after the next Find new jobs.")
                                  : p && d.fetching ? `No new employers to add, but ${p.toLocaleString()} on your list haven't been checked yet. Siftwell is checking them now; your board fills in as it goes.`
                                  : "No new employers near you in the directory right now. Employers you took off your list stay off.";
      load();
    }).catch(() => { $("dirApply").disabled = false; $("dirMsg").textContent = "Couldn't reach Siftwell. Is it still running?"; });
});
load();
})();"""
PANE_SCRIPT = "<script>" + PANE_JS + "</script>"
