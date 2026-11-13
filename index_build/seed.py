"""The seed list: every job board the directory builder knows, small enough to ship with the app.

"Build my own directory" (local.py) starts from it instead of discovering job boards from scratch: for each board the
job system and its settings (what a reader needs), the name the shared directory last published for it, and where it
was last seen hiring (state -> open jobs; US-remote jobs; for a board found through a public list of employers and not
read yet, that employer's state with 0 jobs). Those last two are HINTS ONLY: they decide the order the
app reads boards in (the ones last seen near the person first) and give a board a readable name before its own read
has one. Nothing from the seed is shown as a fact about an employer; the app's own read replaces it.

Where it comes from: the weekly build writes seed.json.gz next to manifest.json on the `index` branch (build.write);
a release ships the newest one as assets/directory/seed.json.gz (scripts/refresh_seed.py, or scripts/make_seed.py
from a builder state on disk); and when the shared directory can be reached the app fetches a newer one into
DATA/directory/seed.json.gz (localdir.refresh_seed). Never a person, only boards.

Format (gzip, JSON, deterministic):
  {"v": 1, "built": "YYYY-MM-DD", "secs": {system: average seconds one read took},
   "groups": [{"a": system, "f": [config fields], "t": [[config values ..., name, jobs, remote, "OH12 PA3"], ...]}]}
Boards are grouped by system and config fields, so the field names are written once. jobs is -1 for a board the
builder never managed to read (nothing is known about it), 0 for one read and found with nothing open."""
import gzip, json

FILE = "seed.json.gz"
MAX_BYTES = 6_000_000           # a seed file larger than this (compressed) is refused
MAX_JSON = 80_000_000
STATES_MAX = 60


def _keep(t):
    """Boards worth handing on: a system the directory reads, and not a board that has only ever failed."""
    from . import systems
    s = systems.BY_ID.get(t["c"].get("ats"))
    if s is not None and not s.read:
        return False
    if not t.get("read") and int(t.get("fail") or 0) >= 3:
        return False
    return True


def make(tenants, built=""):
    """The seed for a builder state ({key: tenant}, see build.Tenants)."""
    from . import build
    groups, secs = {}, {}
    for k in sorted(tenants):
        t = tenants[k]
        if not _keep(t):
            continue
        c = {f: v for f, v in t["c"].items() if not f.startswith("verified_")}
        ats = c.get("ats")
        if not ats or any(not isinstance(v, (str, int, float, bool)) for v in c.values()):
            continue
        fields = tuple(sorted(f for f in c if f != "ats"))
        st = {}
        for p in t.get("places") or []:
            try:
                st[p[4]] = st.get(p[4], 0) + int(p[2])
            except (IndexError, TypeError, ValueError):
                continue
        if not st:      # (a board not read yet: the state a public list's employer is in, as a hint with no jobs)
            for h in t.get("hints") or []:
                if h.startswith("state:") and len(h) == 8:
                    st.setdefault(h[6:], 0)
        top = sorted(st.items(), key=lambda x: (-x[1], x[0]))[:STATES_MAX]
        name = build.best_name(t) if (t.get("read") or t.get("pack_name") or t.get("lnames")) else ""
        row = [c[f] for f in fields] + [name, int(t.get("jobs") or 0) if t.get("read") else -1, int(t.get("remote") or 0),
                                         " ".join(f"{s}{n}" for s, n in top)]
        groups.setdefault((ats, fields), []).append(row)
        if t.get("secs") is not None and t.get("read"):
            a = secs.setdefault(ats, [0.0, 0])
            a[0] += float(t["secs"])
            a[1] += 1
    return {"v": 1, "built": built,
            "secs": {a: round(v[0] / v[1], 2) for a, v in sorted(secs.items()) if v[1] >= 5},
            # (how many boards of a system were read at once when those seconds were measured: a read's seconds
            # include waiting for its turn, so an estimate divides by this, not by today's lane width)
            "lanes": {a: build.LANES.get(a, build.LANE_DEFAULT) for a, v in sorted(secs.items()) if v[1] >= 5},
            "groups": [{"a": a, "f": list(f), "t": rows} for (a, f), rows in sorted(groups.items())]}


def dumps(seed):
    return gzip.compress(json.dumps(seed, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), 9, mtime=0)


def loads(data):
    """The seed dict from the file's bytes; raises ValueError when it isn't one."""
    if len(data) > MAX_BYTES:
        raise ValueError("seed file too large")
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
        raw = g.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise ValueError("seed file too large")
    d = json.loads(raw.decode("utf-8"))
    if not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("groups"), list):
        raise ValueError("not a seed file")
    return d


def count(data):
    return sum(len(g.get("t") or []) for g in loads(data)["groups"])


def read(path):
    """The seed at path as a dict, or None when there is none (or it can't be read)."""
    try:
        with open(path, "rb") as f:
            return loads(f.read(MAX_BYTES + 1))
    except (OSError, ValueError, EOFError):
        return None


def boards(seed):
    """Every board of a seed: {"c": config (checked: netsafe.clean_config), "n": name, "j": jobs, "r": remote jobs,
    "st": {state: jobs}, "seen": False when the builder never read it}. Rows that don't check out are skipped."""
    import netsafe
    for g in (seed or {}).get("groups") or []:
        ats, fields, rows = g.get("a"), g.get("f"), g.get("t")
        if not isinstance(ats, str) or not isinstance(fields, list) or not isinstance(rows, list):
            continue
        nf = len(fields)
        for row in rows:
            if not isinstance(row, list) or len(row) != nf + 4:
                continue
            cfg, _ = netsafe.clean_config({"ats": ats, **dict(zip(fields, row[:nf]))})
            if not cfg:
                continue
            st = {}
            for part in str(row[nf + 3] or "").split():
                if len(part) > 2 and part[:2].isalpha() and part[2:].isdigit():
                    st[part[:2].upper()] = int(part[2:])
            try:
                j = int(row[nf + 1] or 0)
                yield {"c": cfg, "n": netsafe.clean_text(str(row[nf] or ""), 60), "j": max(0, j),
                       "r": int(row[nf + 2] or 0), "st": st, "seen": j >= 0}
            except (TypeError, ValueError):
                continue
