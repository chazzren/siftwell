"""The shared household job catalog: every company the household tracks and every listing fetched from them.

DATA/catalog.db (SQLite, WAL so the server can read while an update writes):
  companies  one row per employer: its job-board config, lists (sets), paused flag, last fetch result
  listings   one row per posting ever seen: parsed fields (JSON in `data`), full text in `desc`,
             first_seen / last_seen / closed_at. Closed listings stay so a reappearing posting keeps its history.
  seen       first-seen date for every posting id (also for ones that were never stored)
  runs       history of fetches, recomputes, re-rates and employer searches (counts, errors, per-tier timing)
  candidates employers found by "Find employers near me" (employer_finder.py), with whether Siftwell can read them
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
  name TEXT PRIMARY KEY, ats TEXT NOT NULL, cfg TEXT NOT NULL, sets TEXT NOT NULL DEFAULT '[]',
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
CREATE INDEX IF NOT EXISTS listings_page ON listings(closed_at, partial, last_seen DESC);
CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, started TEXT NOT NULL, finished TEXT, status TEXT,
  companies INTEGER, fetched INTEGER, new INTEGER, closed INTEGER, changed INTEGER, reopened INTEGER,
  errors TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS candidates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, name TEXT NOT NULL, url TEXT, category TEXT,
  location_note TEXT, why TEXT, status TEXT NOT NULL DEFAULT 'pending', reason TEXT, ats TEXT, cfg TEXT,
  open_jobs INTEGER, suggested TEXT, added_as TEXT, created TEXT, checked TEXT, system TEXT, pass INTEGER);
CREATE INDEX IF NOT EXISTS candidates_run ON candidates(run_id);
"""
# Columns added after the first release: (table, column, type). db() adds any that an older catalog.db lacks.
# candidates.system: for an employer Siftwell can't read, the job system its careers page seems to use ("Taleo",
# "Custom careers site", ...), so Find employers can group them; candidates.pass: the Exhaustive-search pass that found it.
ADDED_COLUMNS = (("candidates", "system", "TEXT"), ("candidates", "pass", "INTEGER"))
_columns_ok = set()

# Board fields that depend on the person looking (never stored on a listing).
PERSON_KEYS = {"score", "appeal", "appeal_parts", "fit_score", "comp_score", "qol_score", "req_status", "req_chips",
               "req_soft", "req_reasons", "dmv_locations", "tracks", "new", "desc", "rel", "rel_why"}
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
        if DB not in _columns_ok:
            for table, col, typ in ADDED_COLUMNS:
                if col not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            _columns_ok.add(DB)
        yield con
        con.commit()
    finally:
        con.close()


DESC_MAX = 12000  # stored text is cut here, and the hash covers the same slice so a re-parse from stored text matches


def listing_hash(title, text):
    """Changes when a posting's title or text changes (then it is parsed again)."""
    return hashlib.sha1(((title or "") + "\n" + (text or "")[:DESC_MAX]).encode("utf-8", "replace")).hexdigest()[:16]


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
                (cfg["name"], cfg["ats"], json.dumps(cfg), json.dumps(cfg.get("sets") or []), cfg.get("tier", ""),
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


def known(company):
    """{listing id: (desc_hash, partial, has_text)} for one company's stored listings (open or closed)."""
    with db() as con:
        return {r["id"]: (r["desc_hash"], bool(r["partial"]), bool(r["has_text"])) for r in con.execute(
            "SELECT id, desc_hash, partial, (desc IS NOT NULL AND desc<>'') AS has_text FROM listings WHERE company=?", (company,))}


# Closing guard: a fetch that "succeeds" but returns far fewer postings than the company has open is more likely a
# broken or truncated fetch (empty page, rate limit, site change, Workday's 2000 cap) than a mass closure.
SUSPECT_MIN_PREV = 5      # the percentage rule needs at least this many open listings before the fetch
SUSPECT_RATIO = 0.5       # returning fewer than half of them is suspect
STALE_DAYS = 14           # when a fetch can't be trusted to close, still close listings unseen this long


def record_fetch(company, summary, listings, con):
    """Store one company's fetch. listings: parsed dicts (jobfinder.prepare_listing) or {"id":..., "_unchanged": True}
    for postings whose text didn't change. On a trustworthy success, open postings not returned this time are closed.
    Not trustworthy (company marked last_status "suspect", nothing closed): the fetch returned under SUSPECT_RATIO of
    the open listings, or 0 of them, when there were >= SUSPECT_MIN_PREV open before (a smaller company dropping to 0
    is a normal closure). If the fetch returned something, listings not seen for STALE_DAYS are still closed.
    Truncated fetches (summary["truncated"]: Workday's 2000 / Amazon's 3000 cap, stopped early) close nothing at all
    (last_status "capped"): postings past the cap are never returned but may be live.
    Returns counts {new, changed, reopened, closed, unchanged}."""
    t = today()
    counts = {"new": 0, "changed": 0, "reopened": 0, "closed": 0, "unchanged": 0}
    ok = summary.get("status") == "ok"
    open_before = {r[0] for r in con.execute("SELECT id FROM listings WHERE company=? AND closed_at IS NULL", (company,))}
    returned = set()
    for j in listings:
        jid = j["id"]
        returned.add(jid)
        prev = con.execute("SELECT closed_at, partial FROM listings WHERE id=?", (jid,)).fetchone()
        if j.get("_unchanged") and prev and not prev["partial"]:
            con.execute("UPDATE listings SET last_seen=?, closed_at=NULL WHERE id=?", (t, jid))
            counts["reopened" if prev["closed_at"] else "unchanged"] += 1
            continue
        if j.get("_unchanged"):
            continue  # (can't happen: unchanged is only reported for complete rows)
        fs = con.execute("SELECT first_seen FROM seen WHERE id=?", (jid,)).fetchone()
        first = fs["first_seen"] if fs else t
        if not fs:
            con.execute("INSERT INTO seen(id, first_seen) VALUES(?, ?)", (jid, first))
        put_listing(con, j, first_seen=first, last_seen=t, partial=bool(j.get("_partial")))
        if not prev:
            counts["new"] += 1
        elif prev["closed_at"]:
            counts["reopened"] += 1
        else:
            counts["changed"] += 1
    status, note = ("ok", None) if ok else ("error", summary.get("status"))
    if ok:
        n_prev, n_got = len(open_before), len(returned)
        if summary.get("truncated"):
            status, note = "capped", f"incomplete fetch ({summary['truncated']}); missing postings kept open"
        elif n_prev >= SUSPECT_MIN_PREV and not n_got:
            status, note = "suspect", f"suspect: the fetch returned no postings but {n_prev} were open; kept them open"
        elif n_prev >= SUSPECT_MIN_PREV and n_got < SUSPECT_RATIO * n_prev:
            status, note = "suspect", f"suspect: the fetch returned {n_got} postings but {n_prev} were open; kept them open"
        gone = open_before - returned
        if status == "capped":
            gone = set()  # never close on a capped fetch: what lies past the cap is never returned
        elif status == "suspect" and n_got:
            cutoff = (dt.date.today() - dt.timedelta(days=STALE_DAYS)).isoformat()
            gone = {g for g in gone if (con.execute("SELECT last_seen FROM listings WHERE id=?", (g,)).fetchone()[0] or "") < cutoff}
        elif status != "ok":
            gone = set()  # (suspect with nothing returned)
        gone = sorted(gone)
        for k in range(0, len(gone), 500):
            chunk = gone[k:k + 500]
            cur = con.execute("UPDATE listings SET closed_at=? WHERE closed_at IS NULL AND id IN (%s)" % ",".join("?" * len(chunk)),
                              (t, *chunk))
            counts["closed"] += cur.rowcount
    open_n = con.execute("SELECT COUNT(*) FROM listings WHERE company=? AND closed_at IS NULL AND partial=0", (company,)).fetchone()[0]
    con.execute("""UPDATE companies SET last_fetch_at=?, last_status=?, last_error=?, raw_count=?, open_count=?, fetch_secs=?
                   WHERE name=?""", (now(), status, note, summary.get("raw_jobs"), open_n, summary.get("secs"), company))
    counts["status"] = status
    return counts


def put_listing(con, j, first_seen, last_seen, partial=False, closed_at=None):
    import netsafe
    if j.get("url") and not netsafe.clean_link(j["url"]):
        j = dict(j, url="")  # only http(s) links are kept (no javascript:, data:, file: ...): boards render it as a link
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
                 first_seen, last_seen, closed_at, 1 if partial else 0, json.dumps(data), desc[:DESC_MAX], listing_hash(j.get("title"), desc)))


def open_listings(lazy=False):
    """Every open, complete listing as a dict (parsed fields + first_seen), with the company's current tier/sector.
    lazy=True (boards): also the rows a fetcher stored on purpose without their text ("lazy": title, place and link
    only, because nobody's titles named them; jobfinder.lazy_text fetches the text when someone wants it)."""
    with db() as con:
        cos = {r["name"]: r for r in con.execute("SELECT name, tier, sector, ai_track, paused FROM companies")}
        out = []
        q = "SELECT data, first_seen, last_seen, partial FROM listings WHERE closed_at IS NULL"
        for r in con.execute(q + ("" if lazy else " AND partial=0")):
            if r["partial"] and '"lazy"' not in r["data"]:
                continue
            j = json.loads(r["data"])
            if r["partial"] and not j.get("lazy"):
                continue
            if not r["partial"]:
                j.pop("lazy", None)
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


def runs(limit=50, kind=None):
    with db() as con:
        if kind:
            rows = con.execute("SELECT * FROM runs WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r, errors=json.loads(r["errors"] or "null"), details=json.loads(r["details"] or "null")) for r in rows]


def get_run(run_id):
    with db() as con:
        r = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(r, errors=json.loads(r["errors"] or "null"), details=json.loads(r["details"] or "null")) if r else None


def update_run(run_id, details=None, status=None, finished=False):
    """Save a running job's progress (details replaces the stored JSON); status/finished as given."""
    sets, vals = [], []
    if details is not None:
        sets.append("details=?"); vals.append(json.dumps(details))
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if finished:
        sets.append("finished=?"); vals.append(now())
    elif status == "running":
        sets.append("finished=NULL")
    if sets:
        with db() as con:
            con.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", (*vals, run_id))


# ---------------------------------------------------------------- browsing (the Catalog page)
COMPANY_META = ("name", "tier", "sector", "sets", "size", "ai_track", "added_by")  # everything else in cfg is the job-board config


def ats_key(c):
    """Identity of a company's job board: its system plus the board config (token, tenant/site, ...), not its name."""
    return c.get("ats", "") + "|" + json.dumps({k: v for k, v in c.items() if k not in COMPANY_META and k != "ats"
                                                 and not k.startswith("_")}, sort_keys=True)


def board_config(c):
    """The job-board part of a company entry (ats + its config keys)."""
    return {k: v for k, v in c.items() if k not in COMPANY_META and not k.startswith("_")}


def find_listings(q="", state="open", company="", page=1, per=50, sort="last_seen", only=None):
    """One page of catalog listings for the Catalog page: (rows, total). q matches title, company or location.
    only: a set of listing ids to keep (e.g. one person's board)."""
    where, args = [], []
    if state == "open":
        where.append("closed_at IS NULL AND partial=0")
    elif state == "closed":
        where.append("closed_at IS NOT NULL")
    if company:
        where.append("company=?"); args.append(company)
    for w in (q or "").split()[:6]:
        where.append("(title LIKE ? OR company LIKE ? OR locations LIKE ?)"); args += [f"%{w}%"] * 3
    sql = " WHERE " + " AND ".join(where) if where else ""
    order = {"first_seen": "first_seen DESC, id", "title": "title COLLATE NOCASE, id", "company": "company COLLATE NOCASE, title COLLATE NOCASE"}.get(sort, "last_seen DESC, first_seen DESC, id")
    per = max(10, min(200, int(per)))
    page = max(1, int(page))
    cols = "id, company, title, url, locations, workplace, salary_min, salary_max, first_seen, last_seen, closed_at, partial"
    with db() as con:
        if only is not None:
            ids = [r[0] for r in con.execute(f"SELECT id FROM listings{sql} ORDER BY {order}", args) if r[0] in only]
            total, ids = len(ids), ids[(page - 1) * per:page * per]
            pos = {i: n for n, i in enumerate(ids)}
            rows = sorted(con.execute(f"SELECT {cols} FROM listings WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall(),
                          key=lambda r: pos[r["id"]]) if ids else []
        else:
            total = con.execute("SELECT COUNT(*) FROM listings" + sql, args).fetchone()[0]
            rows = con.execute(f"SELECT {cols} FROM listings{sql} ORDER BY {order} LIMIT ? OFFSET ?", (*args, per, (page - 1) * per)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["locations"] = json.loads(d["locations"] or "[]")
        except ValueError:
            d["locations"] = []
        d["partial"] = bool(d["partial"])
        out.append(d)
    return out, total


# ---------------------------------------------------------------- one-time migration from the file-based layout
def move_lists(log=print):
    """One-time, in DATA only: the shared category lists of earlier versions ("tech" / "ops" / "nonprofit") go away.
    Every company a profile watched through one of them moves onto that profile's own list (own-<id>), so each
    profile keeps watching exactly the employers it watched before; companies nobody watched stay in the catalog,
    watched by nobody. The old list names are then taken off every company and the old "company_sets" setting off
    every profile. Safe to run again (it finds nothing left to move); a restored older backup is moved again because
    the marker lives in the catalog it replaces. Returns True when it moved anything."""
    if get_meta("lists_moved"):
        return False
    import people
    legacy = set(people.LEGACY_COMPANY_SETS)
    watch, raws = {}, {}
    for pid in people.ids():
        try:
            raw = people.read_saved_strict(pid)
        except Exception as e:   # never guess from a file that can't be read right now: try again at the next start
            log(f"company lists not moved yet: {pid}'s settings can't be read ({type(e).__name__})")
            return False
        raws[pid] = raw
        # a settings file from before the key existed (or no file at all) watched the first list
        had = raw.get("company_sets") if isinstance(raw, dict) and "company_sets" in raw else ["tech"]
        watch[pid] = legacy & set(had or [])
    moved = dropped = 0
    with db() as con:
        for r in con.execute("SELECT name, sets FROM companies").fetchall():
            try:
                sets = [s for s in json.loads(r["sets"]) if isinstance(s, str)]
            except ValueError:
                sets = []
            new = [s for s in sets if s not in legacy]
            for pid, w in watch.items():
                if w & set(sets) and f"own-{pid}" not in new:
                    new.append(f"own-{pid}")
                    moved += 1
            if sorted(new) != sorted(sets):
                dropped += 1
                con.execute("UPDATE companies SET sets=? WHERE name=?", (json.dumps(sorted(new)), r["name"]))
        set_meta("lists_moved", today(), con)
    for pid, raw in raws.items():
        if isinstance(raw, dict) and "company_sets" in raw:
            raw = dict(raw)
            raw.pop("company_sets")
            people._write_settings(raw, pid)
    if dropped:
        log(f"catalog: the earlier shared company lists are gone; {moved} watched employer(s) moved onto profiles' own lists")
    return bool(dropped)


def migrate(log=print):
    """Everything that brings an older data folder up to date (each step runs once): the file-based catalog into
    catalog.db, then the earlier shared company lists onto each profile's own list."""
    done = _migrate_files(log)
    try:
        move_lists(log)
    except Exception as e:
        log(f"company lists not moved yet: {type(e).__name__}: {e}")
    return done


def _migrate_files(log=print):
    """Build the catalog from DATA/companies.json, people/*/jobs.json, descriptions.json, seen.json and market.json.
    Idempotent: runs only while meta 'migrated_at' is unset. Old files are left in place here; retire_old_files() moves
    them away on a later start."""
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
    status = "error"
    try:
        with db() as con:
            # checked again inside the write transaction, so two processes starting at once can't both migrate
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM meta WHERE k='migrated_at'").fetchone():
                status = "skipped"
                return False
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
        status = "ok"
    finally:
        finish_run(rid, status, companies=len(cos), fetched=n_list, new=0, closed=0, changed=0,
                   details={"listings": n_list, "partial": n_partial, "boards": len(boards), "seen": len(seen), "last_full_fetch": fetched})
    log(f"catalog: migrated {len(cos)} companies, {n_list} listings (+{n_partial} partial), {len(seen)} first-seen dates")
    return True


# ---------------------------------------------------------------- retire the files the catalog replaced
RETIRED_FILES = ("descriptions.json", "companies.json", "seen.json")   # only migrate() reads them, before migration
RETIRED_KEEP_DAYS = 30


def retire_old_files(log=None):
    """Once the migration has succeeded (meta 'migrated_at' set and the catalog holds listings), move the files it
    replaced into DATA/_archive/retired-<date>/ (a rename, so it is atomic; logged in migration.log), and delete
    _archive/retired-* folders older than 30 days. Does nothing when there is nothing to move. Never raises.
    market.json (target.py) and company_facts*/company_research are not touched. Returns the names moved."""
    import re
    import shutil
    import time
    D = paths.DATA
    log = log or paths._log
    moved = []
    try:
        if not get_meta("migrated_at"):
            return moved
        with db() as con:
            if not con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]:
                return moved
        present = [n for n in RETIRED_FILES if os.path.isfile(os.path.join(D, n))]
        if present:
            dest = os.path.join(D, "_archive", "retired-" + today())
            os.makedirs(dest, exist_ok=True)
            for n in present:
                target = os.path.join(dest, n)
                i = 2
                while os.path.exists(target):
                    target = os.path.join(dest, f"{i}-{n}")
                    i += 1
                os.replace(os.path.join(D, n), target)
                moved.append(n)
                log(f"retired {n} -> {target} (the catalog replaced it)")
        arch = os.path.join(D, "_archive")
        if os.path.isdir(arch):
            cutoff = time.time() - RETIRED_KEEP_DAYS * 86400
            for n in os.listdir(arch):
                p = os.path.join(arch, n)
                if re.fullmatch(r"retired-[0-9]{4}-[0-9]{2}-[0-9]{2}", n) and os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
                    log(f"deleted {p} (older than {RETIRED_KEEP_DAYS} days)")
    except Exception as e:  # never stop the server over housekeeping
        try:
            log(f"retire_old_files: {type(e).__name__}: {str(e)[:150]}")
        except Exception:
            pass
    return moved
