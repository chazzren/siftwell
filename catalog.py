"""The shared household job catalog: every company the household tracks and every listing fetched from them.

DATA/catalog.db (SQLite, WAL so the server can read while an update writes):
  companies  one row per employer: its job-board config, lists (sets), paused flag, last fetch result
  listings   one row per posting ever seen: parsed fields (JSON in `data`), full text in `desc`,
             first_seen / last_seen / closed_at. Closed listings stay so a reappearing posting keeps its history.
  seen       first-seen date for every posting id (also for ones that were never stored)
  runs       history of fetches, recomputes and re-rates (counts, errors, per-tier timing)
  meta       key/value bookkeeping (migration, date of the last full fetch)

Boards are not stored here: jobfinder.recompute() runs each person's filters over the open listings and writes
their jobs.json / report.html. Claude ratings stay in DATA/ai_scores.json and DATA/pivot_scores.json (keyed by
listing id), so a listing that leaves a board and comes back keeps its ratings."""
import contextlib
import datetime as dt
import hashlib
import json
import os
import sqlite3

import paths

DB = os.path.join(paths.DATA, "catalog.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS companies(
  name TEXT PRIMARY KEY, ats TEXT NOT NULL, cfg TEXT NOT NULL, sets TEXT NOT NULL DEFAULT '["tech"]',
  tier TEXT DEFAULT '', sector TEXT DEFAULT '', ai_track TEXT DEFAULT '', paused INTEGER NOT NULL DEFAULT 0,
  added_by TEXT, added_at TEXT, last_fetch_at TEXT, last_status TEXT, last_error TEXT,
  raw_count INTEGER, open_count INTEGER, fetch_secs REAL);
CREATE TABLE IF NOT EXISTS listings(
  id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, url TEXT, locations TEXT, workplace TEXT,
  salary_min INTEGER, salary_max INTEGER, salary_mid INTEGER, dept TEXT, posted TEXT,
  first_seen TEXT, last_seen TEXT, closed_at TEXT, partial INTEGER NOT NULL DEFAULT 0,
  data TEXT NOT NULL, desc TEXT, desc_hash TEXT);
CREATE INDEX IF NOT EXISTS listings_open ON listings(closed_at);
CREATE INDEX IF NOT EXISTS listings_company ON listings(company);
CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, started TEXT NOT NULL, finished TEXT, status TEXT,
  companies INTEGER, fetched INTEGER, new INTEGER, closed INTEGER, changed INTEGER, reopened INTEGER,
  errors TEXT, details TEXT);
"""

# Board fields that depend on the person looking (never stored on a listing).
PERSON_KEYS = {"score", "appeal", "appeal_parts", "fit_score", "comp_score", "qol_score", "req_status", "req_chips",
               "req_soft", "req_reasons", "dmv_locations", "tracks", "new", "desc"}
COLUMNS = ("company", "title", "url", "workplace", "salary_min", "salary_max", "salary_mid", "dept", "posted")


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def today():
    return dt.date.today().isoformat()


@contextlib.contextmanager
def db():
    os.makedirs(paths.DATA, exist_ok=True)
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def listing_hash(title, text):
    """Changes when a posting's title or text changes (then it is parsed again)."""
    return hashlib.sha1(((title or "") + "\n" + (text or "")).encode("utf-8", "replace")).hexdigest()[:16]


def get_meta(k, default=None):
    with db() as con:
        r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def set_meta(k, v, con=None):
    if con is None:
        with db() as c:
            return set_meta(k, v, c)
    con.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


# ---------------------------------------------------------------- companies
def _company_row(r):
    c = json.loads(r["cfg"])
    c.update(name=r["name"], ats=r["ats"], sets=json.loads(r["sets"]), tier=r["tier"] or c.get("tier", ""),
             sector=r["sector"] or c.get("sector", ""))
    if r["ai_track"]:
        c["ai_track"] = r["ai_track"]
    if r["added_by"]:
        c["added_by"] = r["added_by"]
    c["_paused"] = bool(r["paused"])
    c["_fetch"] = {"at": r["last_fetch_at"], "status": r["last_status"], "error": r["last_error"],
                   "raw": r["raw_count"], "open": r["open_count"], "secs": r["fetch_secs"]}
    return c


def companies(include_paused=True):
    """Company entries (same shape as the old companies.json entries, plus _paused and _fetch)."""
    with db() as con:
        rows = con.execute("SELECT * FROM companies ORDER BY name COLLATE NOCASE").fetchall()
    out = [_company_row(r) for r in rows]
    return out if include_paused else [c for c in out if not c["_paused"]]


def save_company(entry, con=None):
    """Insert or replace one company (entry shaped like a companies.json item)."""
    if con is None:
        with db() as c:
            return save_company(entry, c)
    cfg = {k: v for k, v in entry.items() if not k.startswith("_")}
    con.execute("""INSERT INTO companies(name, ats, cfg, sets, tier, sector, ai_track, added_by, added_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET ats=excluded.ats, cfg=excluded.cfg, sets=excluded.sets, tier=excluded.tier,
                     sector=excluded.sector, ai_track=excluded.ai_track, added_by=COALESCE(excluded.added_by, companies.added_by)""",
                (cfg["name"], cfg["ats"], json.dumps(cfg), json.dumps(cfg.get("sets") or ["tech"]), cfg.get("tier", ""),
                 cfg.get("sector", ""), cfg.get("ai_track", ""), cfg.get("added_by"), now()))


def set_paused(name, paused):
    with db() as con:
        con.execute("UPDATE companies SET paused=? WHERE name=?", (1 if paused else 0, name))


def remove_company(name):
    """Take a company off the catalog. Its listings are closed (kept, so ratings and history survive a re-add)."""
    with db() as con:
        con.execute("UPDATE listings SET closed_at=? WHERE company=? AND closed_at IS NULL", (today(), name))
        con.execute("DELETE FROM companies WHERE name=?", (name,))


def sets_map():
    """{company name: set of list ids} for every company in the catalog."""
    with db() as con:
        return {r["name"]: set(json.loads(r["sets"])) for r in con.execute("SELECT name, sets FROM companies")}


# ---------------------------------------------------------------- listings
def known_hashes(company):
    """{listing id: desc_hash} for one company, so a fetch only re-parses postings whose text changed."""
    with db() as con:
        return {r["id"]: r["desc_hash"] for r in con.execute("SELECT id, desc_hash FROM listings WHERE company=? AND partial=0", (company,))}


def record_fetch(company, summary, listings, con):
    """Store one company's fetch. listings: parsed dicts (jobfinder.prepare_listing) or {"id":..., "_unchanged": True}
    for postings whose text didn't change. On success, postings not returned this time are closed.
    Returns counts {new, changed, reopened, closed, unchanged}."""
    t = today()
    counts = {"new": 0, "changed": 0, "reopened": 0, "closed": 0, "unchanged": 0}
    ok = summary.get("status") == "ok"
    for j in listings:
        jid = j["id"]
        prev = con.execute("SELECT closed_at, partial FROM listings WHERE id=?", (jid,)).fetchone()
        if j.get("_unchanged") and prev and not prev["partial"]:
            con.execute("UPDATE listings SET last_seen=?, closed_at=NULL WHERE id=?", (t, jid))
            counts["reopened" if prev["closed_at"] else "unchanged"] += 1
            continue
        fs = con.execute("SELECT first_seen FROM seen WHERE id=?", (jid,)).fetchone()
        first = fs["first_seen"] if fs else t
        if not fs:
            con.execute("INSERT INTO seen(id, first_seen) VALUES(?, ?)", (jid, first))
        put_listing(con, j, first_seen=first, last_seen=t)
        if not prev:
            counts["new"] += 1
        elif prev["closed_at"]:
            counts["reopened"] += 1
        else:
            counts["changed"] += 1
    if ok:
        cur = con.execute("UPDATE listings SET closed_at=? WHERE company=? AND closed_at IS NULL AND (last_seen IS NULL OR last_seen<?)",
                          (t, company, t))
        counts["closed"] = cur.rowcount
    open_n = con.execute("SELECT COUNT(*) FROM listings WHERE company=? AND closed_at IS NULL", (company,)).fetchone()[0]
    con.execute("""UPDATE companies SET last_fetch_at=?, last_status=?, last_error=?, raw_count=?, open_count=?, fetch_secs=?
                   WHERE name=?""", (now(), "ok" if ok else "error", None if ok else summary.get("status"),
                                     summary.get("raw_jobs"), open_n, summary.get("secs"), company))
    return counts


def put_listing(con, j, first_seen, last_seen, partial=False, closed_at=None):
    desc = j.get("desc") or ""
    data = {k: v for k, v in j.items() if k not in PERSON_KEYS and not k.startswith("_")
            and not (k.startswith(("ai_", "pv_")) and k != "ai_track")}
    data["first_seen"] = first_seen
    con.execute("""INSERT INTO listings(id, company, title, url, locations, workplace, salary_min, salary_max, salary_mid, dept, posted,
                     first_seen, last_seen, closed_at, partial, data, desc, desc_hash)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET company=excluded.company, title=excluded.title, url=excluded.url,
                     locations=excluded.locations, workplace=excluded.workplace, salary_min=excluded.salary_min,
                     salary_max=excluded.salary_max, salary_mid=excluded.salary_mid, dept=excluded.dept, posted=excluded.posted,
                     last_seen=excluded.last_seen, closed_at=excluded.closed_at, partial=excluded.partial, data=excluded.data,
                     desc=excluded.desc, desc_hash=excluded.desc_hash""",
                (j["id"], j["company"], j.get("title", ""), j.get("url"), json.dumps(j.get("locations") or []), j.get("workplace", ""),
                 j.get("salary_min"), j.get("salary_max"), j.get("salary_mid"), j.get("dept", ""), j.get("posted", ""),
                 first_seen, last_seen, closed_at, 1 if partial else 0, json.dumps(data), desc[:12000], listing_hash(j.get("title"), desc)))


def open_listings():
    """Every open, complete listing as a dict (parsed fields + first_seen), with the company's current tier/sector."""
    with db() as con:
        cos = {r["name"]: r for r in con.execute("SELECT name, tier, sector, ai_track, paused FROM companies")}
        out = []
        for r in con.execute("SELECT data, first_seen, last_seen FROM listings WHERE closed_at IS NULL AND partial=0"):
            j = json.loads(r["data"])
            c = cos.get(j["company"])
            if c is None or c["paused"]:
                continue
            j["first_seen"], j["last_seen"] = r["first_seen"], r["last_seen"]
            j["tier"], j["sector"] = c["tier"] or j.get("tier", ""), c["sector"] or j.get("sector", "")
            j["ai_track"] = c["ai_track"] or ""
            out.append(j)
    return out


def descriptions(ids):
    """{id: full posting text} for the given listing ids."""
    ids, out = list(ids), {}
    with db() as con:
        for i in range(0, len(ids), 800):
            chunk = ids[i:i + 800]
            q = "SELECT id, desc FROM listings WHERE id IN (%s)" % ",".join("?" * len(chunk))
            out.update({r["id"]: r["desc"] or "" for r in con.execute(q, chunk)})
    return out


def description(jid):
    return descriptions([jid]).get(jid, "")


def stats():
    with db() as con:
        one = lambda q, *a: con.execute(q, a).fetchone()[0]
        return {"companies": one("SELECT COUNT(*) FROM companies"), "paused": one("SELECT COUNT(*) FROM companies WHERE paused=1"),
                "open": one("SELECT COUNT(*) FROM listings WHERE closed_at IS NULL AND partial=0"),
                "partial": one("SELECT COUNT(*) FROM listings WHERE partial=1"),
                "closed": one("SELECT COUNT(*) FROM listings WHERE closed_at IS NOT NULL"),
                "last_full_fetch": get_meta("last_full_fetch")}


# ---------------------------------------------------------------- runs
def start_run(kind, **fields):
    with db() as con:
        cur = con.execute("INSERT INTO runs(kind, started, status, details) VALUES(?,?,?,?)",
                          (kind, now(), "running", json.dumps(fields.get("details") or {})))
        return cur.lastrowid


def finish_run(run_id, status="ok", **fields):
    cols = {k: (json.dumps(v) if k in ("errors", "details") else v) for k, v in fields.items()
            if k in ("companies", "fetched", "new", "closed", "changed", "reopened", "errors", "details")}
    sets = ", ".join(f"{k}=?" for k in cols)
    with db() as con:
        con.execute(f"UPDATE runs SET finished=?, status=?{', ' + sets if sets else ''} WHERE id=?",
                    (now(), status, *cols.values(), run_id))


def runs(limit=50):
    with db() as con:
        rows = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r, errors=json.loads(r["errors"] or "null"), details=json.loads(r["details"] or "null")) for r in rows]


# ---------------------------------------------------------------- one-time migration from the file-based layout
def migrate(log=print):
    """Build the catalog from DATA/companies.json, people/*/jobs.json, descriptions.json, seen.json and market.json.
    Idempotent: runs only while meta 'migrated_at' is unset. Old files are left in place (no longer read)."""
    if get_meta("migrated_at"):
        return False
    D = paths.DATA
    def load(name, default):
        try:
            return json.load(open(os.path.join(D, name), encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return default
    cos = load("companies.json", [])
    descs = load("descriptions.json", {})
    seen = load("seen.json", {})
    market = load("market.json", [])
    boards = []
    for pid in os.listdir(os.path.join(D, "people")) if os.path.isdir(os.path.join(D, "people")) else []:
        p = os.path.join(D, "people", pid, "jobs.json")
        if os.path.exists(p):
            try:
                boards.append(json.load(open(p, encoding="utf-8")))
            except ValueError:
                pass
    if not (cos or descs or boards):
        with db() as con:
            set_meta("migrated_at", now(), con)
        return False
    # the last full fetch wrote descriptions.json; its date marks which listings were "new this run"
    fetched = dt.date.fromtimestamp(os.path.getmtime(os.path.join(D, "descriptions.json"))).isoformat() \
        if os.path.exists(os.path.join(D, "descriptions.json")) else today()
    boards.sort(key=lambda b: b.get("generated") or "")  # newest last, so its copy of a listing wins
    stats = {}
    for b in boards:
        for s in b.get("companies") or []:
            stats[s["company"]] = s
    rid = start_run("migrate")
    n_list = n_partial = 0
    with db() as con:
        for c in cos:
            save_company(c, con)
            s = stats.get(c["name"])
            if s:
                con.execute("UPDATE companies SET last_fetch_at=?, last_status=?, last_error=?, raw_count=?, fetch_secs=? WHERE name=?",
                            (fetched, "ok" if s.get("status") == "ok" else "error", None if s.get("status") == "ok" else s.get("status"),
                             s.get("raw_jobs"), s.get("secs"), c["name"]))
        con.executemany("INSERT OR IGNORE INTO seen(id, first_seen) VALUES(?, ?)", list(seen.items()))
        merged = {}
        for b in boards:
            for j in b.get("jobs") or []:
                merged[j["id"]] = j
        for jid, j in merged.items():
            j = dict(j)
            wp = j.get("workplace") or ""
            dl = j.get("dmv_locations") or []
            j.setdefault("base_wp", wp)
            j["remote_strict"] = wp == "remote"
            j["remote_bare"] = False
            j["local_unnamed"] = bool(dl) and all(str(l).endswith("(DC area)") for l in dl)
            j["desc"] = descs.get(jid) or ""
            first = j.get("first_seen") or seen.get(jid) or fetched
            con.execute("INSERT OR IGNORE INTO seen(id, first_seen) VALUES(?, ?)", (jid, first))
            put_listing(con, j, first_seen=first, last_seen=fetched)
            n_list += 1
        # postings from the last fetch that no board kept: only title/company/pay/workplace survive (market.json),
        # so they're stored as partial and filled in by the next fetch
        if len(market) == len(descs):
            for jid, row in zip(descs, market):
                if jid in merged or jid.split("::", 1)[0] != row.get("c"):
                    continue
                j = {"id": jid, "company": row["c"], "title": row.get("t") or "", "salary_mid": row.get("m"),
                     "workplace": row.get("w") or "", "level": row.get("l"), "ai_track": row.get("a") or "",
                     "url": jid.split("::", 1)[1] if jid.split("::", 1)[1].startswith("http") else "", "locations": [],
                     "desc": descs[jid]}
                put_listing(con, j, first_seen=seen.get(jid) or fetched, last_seen=fetched, partial=True)
                n_partial += 1
        for c in cos:
            con.execute("UPDATE companies SET open_count=(SELECT COUNT(*) FROM listings WHERE company=? AND closed_at IS NULL AND partial=0) WHERE name=?",
                        (c["name"], c["name"]))
        set_meta("last_full_fetch", fetched, con)
        set_meta("migrated_at", now(), con)
    finish_run(rid, companies=len(cos), fetched=n_list, new=0, closed=0, changed=0,
               details={"listings": n_list, "partial": n_partial, "boards": len(boards), "seen": len(seen), "last_full_fetch": fetched})
    log(f"catalog: migrated {len(cos)} companies, {n_list} listings (+{n_partial} partial), {len(seen)} first-seen dates")
    return True
