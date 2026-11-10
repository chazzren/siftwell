"""Share companies and job listings between Siftwell households: a .siftwell file is a zip of versioned JSON.

Only public data goes in: each company's name, job system and board config (plus its size/sector labels), and,
if asked, its current (open) listings with their posting text and first/last seen dates. Never: profiles, resumes,
marks, tailored resumes, settings, the access key, Claude ratings, company research or Glassdoor facts, or which
person added a company or which lists it is in.

Import merge rules: companies match by job-system key (catalog.ats_key), listings by id. Earliest first_seen and
latest last_seen win; nothing is removed or closed. New companies go into the list the importer picks (companies
already in the catalog get that list added). The server rebuilds everyone's boards afterwards."""
import datetime as dt
import io
import json
import zipfile

import catalog

FORMAT = "siftwell-catalog"
VERSION = 1
MAX_FILE = 400 * 1024 * 1024        # biggest .siftwell file accepted
MAX_UNZIPPED = 1500 * 1024 * 1024   # guard against zip bombs
COMPANY_KEEP_META = ("tier", "sector", "size", "ai_track")  # public labels kept with a shared company
LISTING_COLS = ("id", "company", "title", "url", "workplace", "salary_min", "salary_max", "salary_mid", "dept", "posted",
                "first_seen", "last_seen")


def _public_company(c):
    out = {"name": c["name"], **catalog.board_config(c)}
    for k in COMPANY_KEEP_META:
        if c.get(k):
            out[k] = c[k]
    return out


def _public_data(d):
    """A listing's parsed fields without anything person-specific or from Claude (ai_track is a company label)."""
    return {k: v for k, v in d.items() if not k.startswith("_") and k not in catalog.PERSON_KEYS
            and not (k.startswith(("ai_", "pv_", "gd_", "glassdoor")) and k != "ai_track")}


def export(names, with_listings=True, app_version=""):
    """Bytes of a .siftwell file for these company names."""
    want = set(names)
    cos = [c for c in catalog.companies() if c["name"] in want]
    listings = []
    if with_listings and cos:
        names_l = [c["name"] for c in cos]
        with catalog.db() as con:
            for i in range(0, len(names_l), 400):
                chunk = names_l[i:i + 400]
                q = (f"SELECT {', '.join(LISTING_COLS)}, locations, data, desc FROM listings WHERE closed_at IS NULL AND partial=0 "
                     f"AND company IN ({','.join('?' * len(chunk))})")
                for r in con.execute(q, chunk):
                    row = {k: r[k] for k in LISTING_COLS}
                    row["locations"] = json.loads(r["locations"] or "[]")
                    row["data"] = _public_data(json.loads(r["data"] or "{}"))
                    row["desc"] = r["desc"] or ""
                    listings.append(row)
    manifest = {"format": FORMAT, "version": VERSION, "exported": dt.date.today().isoformat(), "app_version": app_version,
                "companies": len(cos), "listings": len(listings)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        z.writestr("companies.json", json.dumps([_public_company(c) for c in cos], indent=1))
        z.writestr("listings.json", json.dumps(listings))
    return buf.getvalue(), manifest


def read(raw):
    """Parse a .siftwell file -> (manifest, companies, listings). Raises ValueError with a plain message."""
    if len(raw) > MAX_FILE:
        raise ValueError("That file is too big.")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
            raise ValueError("That file is too big once unpacked.")
        manifest = json.loads(z.read("manifest.json"))
        companies = json.loads(z.read("companies.json"))
        listings = json.loads(z.read("listings.json")) if "listings.json" in z.namelist() else []
    except ValueError:
        raise
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        raise ValueError("That isn't a Siftwell share file (.siftwell).")
    if manifest.get("format") != FORMAT:
        raise ValueError("That isn't a Siftwell share file (.siftwell).")
    if int(manifest.get("version") or 0) > VERSION:
        raise ValueError("That file was made by a newer Siftwell. Update Siftwell, then import it.")
    if not isinstance(companies, list) or not isinstance(listings, list):
        raise ValueError("That share file is damaged.")
    clean = []
    for c in companies:
        if isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("ats"), str) and c["name"].strip():
            clean.append({k: v for k, v in c.items() if k not in ("sets", "added_by") and not k.startswith("_")})
    return manifest, clean, [j for j in listings if isinstance(j, dict) and j.get("id") and j.get("company")]


def _plan(companies, listings):
    """Match the file against the catalog: {src name: (local name, is_new)} plus listing ids already present."""
    local = catalog.companies()
    by_key = {catalog.ats_key(c): c["name"] for c in local}
    taken = {c["name"].lower() for c in local}
    names = {}
    for c in companies:
        k = catalog.ats_key(c)
        if k in by_key:
            names[c["name"]] = (by_key[k], False)
            continue
        nm = c["name"].replace(",", "").strip()[:60]
        if nm.lower() in taken:
            nm = f"{nm} ({c['ats']})"
            i = 2
            while nm.lower() in taken:
                nm, i = f"{c['name'][:50]} ({c['ats']} {i})", i + 1
        taken.add(nm.lower())
        by_key[k] = nm
        names[c["name"]] = (nm, True)
    ids = [_local_id(j, names) for j in listings if j["company"] in names]
    present = set()
    with catalog.db() as con:
        for i in range(0, len(ids), 800):
            chunk = ids[i:i + 800]
            present.update(r[0] for r in con.execute(f"SELECT id FROM listings WHERE id IN ({','.join('?' * len(chunk))})", chunk))
    return names, present


def _local_id(j, names):
    """Listing ids start with the company name; a company that has another name here gets its listings renamed too."""
    src = j["company"]
    dst = names[src][0]
    jid = str(j["id"])
    return dst + jid[len(src):] if dst != src and jid.startswith(src + "::") else jid


def preview(raw):
    manifest, companies, listings = read(raw)
    names, present = _plan(companies, listings)
    new_cos = sum(1 for v in names.values() if v[1])
    ids = [_local_id(j, names) for j in listings if j["company"] in names]
    return {"manifest": manifest, "companies": len(companies), "new_companies": new_cos, "known_companies": len(companies) - new_cos,
            "listings": len(ids), "new_listings": sum(1 for i in ids if i not in present), "known_listings": sum(1 for i in ids if i in present)}


def apply(raw, set_id, pid):
    """Merge a .siftwell file into the catalog. Returns counts."""
    manifest, companies, listings = read(raw)
    names, _ = _plan(companies, listings)
    out = {"new_companies": 0, "known_companies": 0, "new_listings": 0, "updated_listings": 0}
    today = catalog.today()
    cur = {c["name"]: c for c in catalog.companies()}
    with catalog.db() as con:
        con.execute("BEGIN IMMEDIATE")
        for c in companies:
            local, is_new = names[c["name"]]
            if is_new:
                entry = {**c, "name": local, "sets": [set_id], "added_by": pid}
                entry.setdefault("tier", "dmv_office")
                entry.setdefault("sector", "Shared with you")
                catalog.save_company(entry, con)
                out["new_companies"] += 1
            else:
                e = cur.get(local)
                if e is not None and set_id not in (e.get("sets") or []):
                    e["sets"] = sorted(set(e.get("sets") or ["tech"]) | {set_id})
                    con.execute("UPDATE companies SET sets=? WHERE name=?", (json.dumps(e["sets"]), local))
                out["known_companies"] += 1
        touched = set()
        for j in listings:
            if j["company"] not in names:
                continue
            local = names[j["company"]][0]
            jid = _local_id(j, names)
            fs, ls = j.get("first_seen") or today, j.get("last_seen") or j.get("first_seen") or today
            prev = con.execute("SELECT first_seen, last_seen, partial FROM listings WHERE id=?", (jid,)).fetchone()
            seen = con.execute("SELECT first_seen FROM seen WHERE id=?", (jid,)).fetchone()
            if seen is None:
                con.execute("INSERT INTO seen(id, first_seen) VALUES(?, ?)", (jid, fs))
            elif fs < seen["first_seen"]:
                con.execute("UPDATE seen SET first_seen=? WHERE id=?", (fs, jid))
            if prev is None or prev["partial"]:
                d = dict(j.get("data") or {})
                d.update({k: j.get(k) for k in LISTING_COLS if k not in ("first_seen", "last_seen")})
                d["id"], d["company"], d["locations"], d["desc"] = jid, local, j.get("locations") or [], j.get("desc") or ""
                if prev is not None:
                    fs, ls = min(fs, prev["first_seen"] or fs), max(ls, prev["last_seen"] or ls)
                closed = None if prev is None else con.execute("SELECT closed_at FROM listings WHERE id=?", (jid,)).fetchone()[0]
                catalog.put_listing(con, d, first_seen=fs, last_seen=ls, closed_at=closed)
                con.execute("UPDATE listings SET first_seen=? WHERE id=?", (fs, jid))  # (an update keeps the old first_seen)
                out["new_listings" if prev is None else "updated_listings"] += 1
            else:
                nf, nl = min(fs, prev["first_seen"] or fs), max(ls, prev["last_seen"] or ls)
                if (nf, nl) != (prev["first_seen"], prev["last_seen"]):
                    con.execute("UPDATE listings SET first_seen=?, last_seen=? WHERE id=?", (nf, nl, jid))
                    data = con.execute("SELECT data FROM listings WHERE id=?", (jid,)).fetchone()[0]
                    try:
                        dd = json.loads(data)
                        dd["first_seen"] = nf
                        con.execute("UPDATE listings SET data=? WHERE id=?", (json.dumps(dd), jid))
                    except ValueError:
                        pass
                    out["updated_listings"] += 1
            touched.add(local)
        for nm in touched:
            con.execute("UPDATE companies SET open_count=(SELECT COUNT(*) FROM listings WHERE company=? AND closed_at IS NULL AND partial=0) WHERE name=?",
                        (nm, nm))
    return out
