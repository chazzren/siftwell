"""Build the Siftwell employer directory (published on the repo's `index` branch; read by directory.py).

    python scripts/build_index.py --out <folder> [--states OH,CO,DC] [--limit N] [--minutes M] [--no-cc] [--no-ct] ...

Steps:
  1. Discover job-board tenants: the starter packs (packs/*.json), the Common Crawl URL index (cc.py) and certificate
     names (ct.py) for every system in systems.SYSTEMS, job-board links in the HN "Who is hiring" thread, and employer
     web domains from Web Data Commons (gov.wdc, a budget per run). Employer names by place from the IRS BMF (and DOL LCA
     when a file is given) are tied to tenants by slug (gov.py); a slug is only kept when the board has jobs in that
     employer's state.
  2. Read each tenant's public feed (readers.py; robots.txt, pacing, one honest User-Agent) to learn where it hires:
     locations (geocoded offline with geo.py), open jobs, US-remote jobs. Boards that fail three runs in a row rest for
     four weeks; empty boards are left out of the files.
  3. Job snapshots from sources that publish postings (postings.py: USAJOBS, CareerOneStop, HN, The Muse), bucketed by
     state.
  4. Write states/<ST>.json.gz, states/remote.json.gz, jobs/<ST>.json.gz, jobs/remote.json.gz and manifest.json
     (sizes, SHA-256, counts, sources and attribution). Builder state (what was read when) is kept in _state/ on the same
     branch, so a time-boxed run carries on where the last one stopped.

Only company names, job-system configs, careers links, places with job counts and dates are published: no people."""
import argparse, concurrent.futures as cf, datetime as dt, glob, gzip, hashlib, json, os, re, sys, threading, time

from . import net, systems, readers, cc, ct, gov, postings

LANES = {"greenhouse": 3, "lever": 1, "ashby": 3, "workday": 6, "jsonld": 4}   # boards read at once per job system
LANE_DEFAULT = 3        # every other system (each system has its own lane: its boards share hosts)
STALE_DAYS = 6          # a board read more recently than this isn't read again
KEEP_DAYS = 35          # a board unread this long (it kept failing) is left out of the files
REST_DAYS = 28          # after three failures in a row
ALL_STATES = sorted(set(__import__("directory").STATE_CODES))
README = """# Siftwell employer directory (generated)

This branch is written by the "Employer directory" GitHub Actions workflow (.github/workflows/index.yml) once a week,
as a single commit. Siftwell downloads the files here to find employers near you: whole state files only, so your exact
location is never sent anywhere. Nothing here is about people: company names, job-system settings, careers links,
places with job counts, and dates. Job snapshots link to the original postings and name their source.

Built {built}. {employers:,} employers with open jobs, {jobs:,} snapshot postings.
"""


def log(*a):
    print(*a, flush=True)


def today():
    return dt.date.today().isoformat()


def _days_since(d):
    try:
        return (dt.date.today() - dt.date.fromisoformat(d[:10])).days
    except Exception:
        return 10 ** 6


# ---------------------------------------------------------------- state
def load_json_gz(path, default):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json_gz(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    data = gzip.compress(raw, 9, mtime=0)
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return data


class Tenants:
    def __init__(self, path):
        self.path = path
        self.d = load_json_gz(path, {})
        self.lock = threading.Lock()
        self.new = {}

    def add(self, cfg, src, name=None, hint=None):
        if not cfg:
            return None
        k = systems.key(cfg)
        with self.lock:
            t = self.d.get(k)
            if t is None:
                t = self.d[k] = {"c": cfg, "src": [], "found": today()}
                self.new[src] = self.new.get(src, 0) + 1
            if src not in t["src"]:
                t["src"].append(src)
            if name and (src == "pack" or not t.get("pack_name")):
                t["pack_name" if src == "pack" else "gov_name"] = name
            if hint:
                t.setdefault("hints", [])
                if hint not in t["hints"]:
                    t["hints"].append(hint)
        return k

    def save(self):
        save_json_gz(self.path, self.d)


# ---------------------------------------------------------------- discovery
def seed_packs(T):
    import paths
    n = 0
    for f in sorted(glob.glob(os.path.join(paths.PACKS, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in d.get("companies") or []:
            import netsafe
            cfg, _ = netsafe.clean_config(c)
            if cfg:
                T.add(cfg, "pack", c.get("name"))
                n += 1
    log(f"packs: {n} seed boards")


def discover_cc(T, crawls, cap):
    for crawl in crawls:
        ix = cc.Index(crawl)
        for s in systems.SYSTEMS:
            if not s.read:
                continue
            for prefix in s.cc:
                n0 = len(T.d)
                try:
                    for u in ix.urls(prefix, cap, log):
                        T.add(systems.parse(u), "cc")
                except Exception as e:
                    log(f"  cc {crawl} {prefix}: failed ({type(e).__name__}: {str(e)[:80]})")
                log(f"  cc {crawl} {s.id}: +{len(T.d) - n0} new boards")


def discover_ct(T, probe_budget):
    wd_known = {t["c"].get("tenant", "").lower() for t in T.d.values() if t["c"].get("ats") == "workday"}
    probes = []
    for s in systems.SYSTEMS:
        if not s.read:
            continue
        for dom in s.ct:
            n0 = len(T.d)
            for h in ct.hosts(dom, log):
                c = systems.ct_host_config(s.id, h)
                if not c:
                    continue
                if s.id == "workday":
                    if c["tenant"] not in wd_known:
                        probes.append(c)
                else:
                    T.add(c, "ct")
            log(f"  ct {dom}: +{len(T.d) - n0} new boards")
    found = 0
    for c in probes[:probe_budget]:
        cc_ = readers.workday_find_site(c)
        if cc_:
            T.add(cc_, "ct")
            found += 1
    log(f"  ct workday: {len(probes)} tenants without a known site, {min(len(probes), probe_budget)} probed, {found} found")


PROBE = {   # job systems addressable by a slug alone: (system, URL that answers 200 for a real board)
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}",
    "lever": "https://api.lever.co/v0/postings/{s}?mode=json&limit=1",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{s}",
}


def discover_names(T, names, probes, budget):
    """Tie employer names (with their state) to tenants: slug matches against known tenants, then a probe budget."""
    idx = {}
    for k, t in T.d.items():
        c = t["c"]
        for v in (c.get("token"), c.get("tenant")):
            if v:
                idx.setdefault(str(v).lower(), []).append(k)
    matched, probed, hits = 0, 0, 0
    for e in names:
        sl = gov.slugs(e["name"])
        ks = [k for s in sl for k in idx.get(s, [])]
        if ks:
            for k in ks[:2]:
                t = T.d[k]
                t.setdefault("gov_name", e["name"])
                h = "state:" + e["state"]
                t.setdefault("hints", [])
                if h not in t["hints"]:
                    t["hints"].append(h)
            matched += 1
            continue
        if probed >= budget:
            continue
        for s in sl[:2]:
            for ats, url in PROBE.items():
                pk = f"{ats}:{s}"
                if pk in probes and _days_since(probes[pk][0]) < 60:
                    ok = probes[pk][1]
                else:
                    probed += 1
                    try:
                        d = net.get_json(url.format(s=s), tries=1, timeout=20)
                        ok = bool(d.get("jobs") if isinstance(d, dict) else d)
                    except Exception:
                        ok = False
                    probes[pk] = (today(), ok)
                if ok:
                    T.add({"ats": ats, "token": s}, "gov", e["name"], "need:" + e["state"])
                    hits += 1
    log(f"  names: {len(names)} employers, {matched} matched a known board, {probed} probes, {hits} probe hits")


def discover_wdc(T, st, budget):
    doms = gov.wdc(log=log)
    if not doms:
        return
    cur = int(st.get("wdc_cursor", 0)) % max(1, len(doms))
    batch = doms[cur:cur + budget]
    st["wdc_cursor"] = cur + len(batch)
    found = 0
    def one(dn):
        try:
            return gov.resolve_domain(dn[0])
        except Exception:
            return None
    with cf.ThreadPoolExecutor(6) as ex:
        for cfg in ex.map(one, batch):
            if cfg:
                T.add(cfg, "wdc")
                found += 1
    log(f"  WDC: {len(batch)} domains checked (from #{cur}), {found} readable job boards")


# ---------------------------------------------------------------- reading
_GEO = {}


def place_of(label):
    """(lat, lon, state, label) for a location label, or None (state-only, remote and foreign labels are None)."""
    if label in _GEO:
        return _GEO[label]
    import geo, directory
    r = None
    try:
        hs = [h for h in geo.locate_all(label) if h.kind != "state"]
        if hs:
            h = max(hs, key=lambda h: h.conf)
            m = re.search(r", ([A-Z]{2})$", h.label)
            stc = m.group(1) if m else directory.state_of(h.lat, h.lon)
            if stc:
                r = (round(h.lat, 3), round(h.lon, 3), stc, h.label)
    except Exception:
        r = None
    _GEO[label] = r
    return r


def pick_name(t, s):
    if t.get("pack_name"):
        return t["pack_name"]
    import company_add
    c = t["c"]
    bn = (s or {}).get("name") or ""
    slug = re.sub(r"[^a-z0-9]", "", str(c.get("token") or c.get("tenant") or "").lower())
    if bn and c["ats"] == "workday":   # (Workday gives a posting's legal entity: keep it only when it names the tenant)
        nb = re.sub(r"[^a-z0-9]", "", bn.lower())
        if not slug or not (slug[:5] in nb or nb[:5] in slug):
            bn = ""
        else:
            bn = re.sub(r"\b(Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Company|Co\.|Ltd\.?|N\.A\.|LP)$", "", bn).strip(" ,.")
    if bn:
        return bn[:60]
    if t.get("gov_name"):
        return t["gov_name"][:60]
    return company_add.default_name(c)


def lane(c):
    return c.get("ats") or "other"


def read_all(T, args, deadline, want_states):
    todo = []
    for k, t in T.d.items():
        if t.get("rest_until") and t["rest_until"] > today():
            continue
        s = systems.BY_ID.get(t["c"].get("ats"))
        if s is not None and not s.read:
            continue
        if t.get("read") and _days_since(t["read"]) < STALE_DAYS:
            continue
        todo.append(k)

    def prio(k):
        t = T.d[k]
        hinted = any(h.split(":", 1)[1] in want_states for h in t.get("hints", []))
        return (0 if "pack" in t["src"] else 1 if hinted else 2, 0 if not t.get("read") else 1,
                {"workday": 0, "icims": 1, "greenhouse": 2}.get(t["c"]["ats"], 3), t.get("read") or "")
    todo.sort(key=prio)
    if args.limit:
        todo = todo[:args.limit]
    log(f"read: {len(todo)} boards to read (of {len(T.d)} known)")
    pools = {}
    for k in todo:
        ln = lane(T.d[k]["c"])
        if ln not in pools:
            pools[ln] = cf.ThreadPoolExecutor(LANES.get(ln, LANE_DEFAULT))
    stats = {"ok": 0, "empty": 0, "failed": 0, "skipped": 0, "late": 0}
    done_n = [0]

    def one(k):
        if time.time() > deadline:
            stats["late"] += 1
            return
        t = T.d[k]
        try:
            s = readers.read(dict(t["c"]))
        except readers.Skip:
            stats["skipped"] += 1
            return
        except Exception as e:
            t["fail"] = int(t.get("fail", 0)) + 1
            t["err"] = f"{type(e).__name__}: {str(e)[:100]}"
            if t["fail"] >= 3:
                t["rest_until"] = (dt.date.today() + dt.timedelta(days=REST_DAYS)).isoformat()
            stats["failed"] += 1
            return
        places = {}
        for lab, n in s["locs"].items():
            p = place_of(lab)
            if p:
                kk = (p[0], p[1])
                cur = places.get(kk)
                places[kk] = [p[0], p[1], (cur[2] if cur else 0) + n, p[3], p[2]]
        t.update(read=today(), fail=0, jobs=s["jobs"], remote=s["remote"], places=list(places.values()),
                 sample=bool(s.get("sample")), name=pick_name(t, s), secs=s.get("secs"))
        t.pop("err", None)
        t.pop("rest_until", None)
        stats["ok" if s["jobs"] else "empty"] += 1
        done_n[0] += 1
        if done_n[0] % 200 == 0:
            log(f"  read {done_n[0]} boards ({stats})")

    futs = [pools[lane(T.d[k]["c"])].submit(one, k) for k in todo]
    for f in cf.as_completed(futs):
        try:
            f.result()
        except Exception as e:
            log(f"  reader crashed: {type(e).__name__}: {e}")
    for p in pools.values():
        p.shutdown(wait=True)
    # a board found only by a name probe counts only if it hires in that employer's state
    dropped = 0
    for k in list(T.d):
        t = T.d[k]
        need = [h.split(":", 1)[1] for h in t.get("hints", []) if h.startswith("need:")]
        if need and t.get("read") and set(t["src"]) == {"gov"} and not any(p[4] in need for p in t.get("places") or []):
            del T.d[k]
            dropped += 1
    log(f"read: {stats}; {dropped} name-probe boards dropped (no jobs in that employer's state)")
    return stats


# ---------------------------------------------------------------- output
def entry(t, state=None):
    places = [[p[0], p[1], p[2], p[3]] for p in t.get("places") or [] if state is None or p[4] == state]
    places.sort(key=lambda p: -p[2])
    e = {"n": t.get("name") or "", "c": t["c"], "u": systems.careers_url(t["c"]), "j": int(t.get("jobs") or 0),
         "r": int(t.get("remote") or 0), "p": places[:60], "s": t.get("read")}
    if t.get("sample"):
        e["x"] = 1
    return e


def bucket_jobs(items, src):
    """{state or 'remote': [job]} with each job's geocoded places."""
    out = {}
    for j in items:
        if not j.get("u") or not j.get("t"):
            continue
        pts, sts = [], set()
        for lab in j.get("l") or []:
            p = place_of(lab)
            if p:
                pts.append([p[0], p[1]])
                sts.add(p[2])
        rec = {"src": src, "t": j["t"][:200], "o": (j.get("o") or "")[:100], "u": j["u"][:1000], "l": [l[:100] for l in (j.get("l") or [])[:6]],
               "p": pts[:6], "w": j.get("w") or "", "pay": j.get("pay"), "d": j.get("d") or "", "x": (j.get("x") or "")[:400]}
        for s in sts:
            out.setdefault(s, []).append(rec)
        if j.get("w") == "remote":
            out.setdefault("remote", []).append(rec)
    return out


def write(out, T, jobs_by, want_states, stats, t0, prior_manifest):
    man = {"v": 1, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "states": {}, "jobs": {},
           "sources": {}, "stats": stats}
    live = {k: t for k, t in T.d.items() if t.get("read") and _days_since(t["read"]) <= KEEP_DAYS and int(t.get("jobs") or 0) > 0}
    by_state = {}
    for t in live.values():
        for s in {p[4] for p in t.get("places") or []}:
            by_state.setdefault(s, []).append(t)
    for st in want_states:
        emps = sorted((entry(t, st) for t in by_state.get(st, [])), key=lambda e: (-sum(p[2] for p in e["p"]), e["n"].lower()))
        data = save_json_gz(os.path.join(out, "states", f"{st}.json.gz"), {"v": 1, "state": st, "built": man["built"], "employers": emps})
        man["states"][st] = {"employers": len(emps), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    rem = sorted((entry(t) | {"p": []} for t in live.values() if int(t.get("remote") or 0) > 0), key=lambda e: -e["r"])[:5000]
    data = save_json_gz(os.path.join(out, "states", "remote.json.gz"), {"v": 1, "state": "remote", "built": man["built"], "employers": rem})
    man["states"]["remote"] = {"employers": len(rem), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    njobs = 0
    for st in list(want_states) + ["remote"]:
        items = jobs_by.get(st, [])
        if not items:
            continue
        data = save_json_gz(os.path.join(out, "jobs", f"{st}.json.gz"), {"v": 1, "state": st, "built": man["built"], "jobs": items})
        man["jobs"][st] = {"jobs": len(items), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        njobs += len(items)
    # states not built this run keep their earlier files (a --states sample run doesn't wipe the rest)
    for kind in ("states", "jobs"):
        for st, ent in ((prior_manifest or {}).get(kind) or {}).items():
            if st not in man[kind] and os.path.exists(os.path.join(out, kind, f"{st}.json.gz")) and st not in want_states:
                man[kind][st] = ent
    for sid, (label, attr) in postings.SOURCES.items():
        if any(j["src"] == sid for js in jobs_by.values() for j in js):
            man["sources"][sid] = {"label": label, "attribution": attr}
    man["stats"].update(employers=len(live), boards_known=len(T.d), run_minutes=round((time.time() - t0) / 60, 1),
                        http=dict(net.STATS))
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, sort_keys=True)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.format(built=man["built"], employers=len(live), jobs=njobs))
    return man


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Siftwell employer directory.")
    ap.add_argument("--out", required=True, help="output folder (the index branch's working tree)")
    ap.add_argument("--states", default="", help="comma-separated state codes to write (default: all)")
    ap.add_argument("--limit", type=int, default=0, help="read at most this many boards this run")
    ap.add_argument("--minutes", type=float, default=300, help="stop starting new reads after this many minutes")
    ap.add_argument("--crawls", type=int, default=2, help="newest Common Crawl crawls to look through")
    ap.add_argument("--cc-blocks", type=int, default=400, help="Common Crawl index blocks per URL prefix, at most")
    ap.add_argument("--ct-probe", type=int, default=300, help="Workday tenants from certificates to probe for a site")
    ap.add_argument("--wdc", type=int, default=400, help="Web Data Commons domains to check this run")
    ap.add_argument("--probe", type=int, default=300, help="slug probes for employer names per state")
    ap.add_argument("--lca-file", default=os.environ.get("DOL_LCA_FILE") or os.environ.get("DOL_LCA_URL") or "")
    ap.add_argument("--no-cc", action="store_true")
    ap.add_argument("--no-ct", action="store_true")
    ap.add_argument("--no-names", action="store_true", help="skip IRS BMF / DOL LCA")
    ap.add_argument("--no-wdc", action="store_true")
    ap.add_argument("--no-postings", action="store_true")
    ap.add_argument("--no-read", action="store_true", help="discover only")
    args = ap.parse_args(argv)
    t0 = time.time()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    want = [s.strip().upper() for s in args.states.split(",") if s.strip()] or ALL_STATES
    bad = [s for s in want if s not in ALL_STATES]
    if bad:
        ap.error(f"unknown state codes: {bad}")
    state_path = os.path.join(out, "_state", "builder.json.gz")
    st = load_json_gz(state_path, {})
    probes = {k: tuple(v) for k, v in load_json_gz(os.path.join(out, "_state", "probes.json.gz"), {}).items()}
    try:
        prior = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    except (OSError, ValueError):
        prior = None
    T = Tenants(os.path.join(out, "_state", "tenants.json.gz"))
    log(f"directory build: {len(T.d)} boards known from earlier runs; states {','.join(want) if len(want) < 10 else str(len(want)) + ' states'}")

    seed_packs(T)
    if not args.no_cc:
        crawls = cc.latest_crawls(args.crawls)
        log(f"Common Crawl: {crawls or 'unavailable'}")
        discover_cc(T, crawls, args.cc_blocks)
        T.save()
    if not args.no_ct:
        discover_ct(T, args.ct_probe)
        T.save()
    hn_items, hn_links = ([], []) if args.no_postings else postings.hn(log)
    for u in hn_links:
        T.add(systems.parse(u), "hn")
    if not args.no_names:
        names = []
        for s in want:
            names += gov.bmf(s, log=log)[:max(args.probe * 3, 200)]
        if args.lca_file:
            names += gov.lca(args.lca_file, set(want), log=log)[:2000]
        else:
            log("  DOL LCA: skipped (dol.gov refuses automated downloads; pass --lca-file to use a downloaded file)")
        discover_names(T, names, probes, args.probe * len(want))
        save_json_gz(os.path.join(out, "_state", "probes.json.gz"), {k: list(v) for k, v in probes.items()})
    if not args.no_wdc:
        discover_wdc(T, st, args.wdc)
    log(f"discovery: {len(T.d)} boards known; new this run by source: {T.new}")
    T.save()
    stats = {"discovered_new": T.new}
    if not args.no_read:
        deadline = t0 + args.minutes * 60
        stats["read"] = read_all(T, args, deadline, set(want))
        T.save()
    jobs_by = {}
    if not args.no_postings:
        for sid, items in (("usajobs", postings.usajobs(log)), ("careeronestop", postings.careeronestop(want, log)),
                           ("hn", hn_items), ("muse", postings.muse(log))):
            for k, v in bucket_jobs(items, sid).items():
                jobs_by.setdefault(k, []).extend(v)
    save_json_gz(state_path, st)
    man = write(out, T, jobs_by, want, stats, t0, prior)
    log(f"done in {man['stats']['run_minutes']} min: {man['stats']['employers']} employers with jobs, "
        f"{sum(v['employers'] for k, v in man['states'].items() if k != 'remote')} state entries, "
        f"{sum(v['jobs'] for v in man['jobs'].values())} snapshot postings")
    return 0
