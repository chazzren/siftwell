#!/usr/bin/env python3
"""Build Siftwell's compact occupation extract (assets/onet/onet.json.gz) from the official O*NET database download.

    1. Download the "Text" database zip from https://www.onetcenter.org/database.html (e.g. db_31_0_text.zip) and unzip
       it somewhere OUTSIDE the repo (never commit the raw download).
    2. python scripts/build_onet.py <folder with the .txt files> [out file]

What is kept, per occupation: its title, the other job titles people use for it (O*NET "Job Titles" / "Alternate
Titles", with the commonly reported ones first), the closest related occupations, the in-demand software named for it,
and a few words that set its tasks apart from other occupations (worked out here from the task statements). Everything
else in the download (ratings, abilities, work context ...) is left out, which takes ~100 MB down to under 1 MB.

O*NET is published by the U.S. Department of Labor, Employment and Training Administration, under CC BY 4.0. The
notice shipped next to the extract (assets/onet/NOTICE.txt) and docs/GUIDE.md carry the required attribution; this
extract is a modified, trimmed version of the database.

Plain stdlib; reads both the newer file names (Job Titles.txt, Software Skills.txt) and the older ones
(Alternate Titles.txt, Technology Skills.txt)."""
import collections, csv, gzip, json, math, os, re, sys

STATES = set("al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa "
             "ri sc sd tn tx ut vt va wa wv wi wy".split())
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the their them these this those to was
with will such other others using use used uses may including include includes related various within between per about
work works working worker workers job jobs duties duty perform performs performing ensure ensures provide provides provided
providing maintain maintains maintaining prepare prepares preparing determine determines determining conduct conducts make
makes making need needs needed required require requires appropriate necessary according following specific information
activities activity operations operation procedures procedure equipment materials material services service records record
problems problem programs program methods method systems system standards requirements data new order orders based
ensure assist assists assisting develop develops developing review reviews reviewing identify plan plans planning monitor
monitors monitoring direct directs directing coordinate coordinates coordinating evaluate evaluates evaluating staff
personnel employees individuals people areas area types type parts part time order results conditions condition
changes change issues policies policy purposes regarding concerning tasks task assigned supervise supervises""".split())


def rows(folder, *names):
    for n in names:
        p = os.path.join(folder, n)
        if os.path.exists(p):
            with open(p, encoding="utf-8", newline="") as f:
                yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
            return
    raise SystemExit(f"None of {names} found in {folder}")


def clean(t):
    return " ".join((t or "").replace("’", "'").split())


def names_of(title):
    """'Emergency Room Nurse (ER Nurse)' -> ['Emergency Room Nurse', 'ER Nurse']."""
    title = clean(title)
    out = []
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", title)
    for t in ([m.group(1), m.group(2)] if m else [title]):
        t = t.strip(" ,;-")
        if len(t) >= 2 and t.lower() not in STATES:
            out.append(t)
    return out


def words(text):
    return re.findall(r"[a-z]{3,}", re.sub(r"'s|s'(?![a-z])|'", "", text.lower()).replace("-", " "))


def stem(w):
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                             "assets", "onet", "onet.json.gz")
    version = ""
    try:
        version = re.search(r"O\*NET ([\d.]+) Database", open(os.path.join(src, "Read Me.txt"), encoding="utf-8").read()).group(1)
    except Exception:
        pass
    occ = {}
    for r in rows(src, "Occupation Data.txt"):
        occ[r["O*NET-SOC Code"]] = {"t": clean(r["Title"]), "a": [], "n": 0, "r": [], "s": [], "k": [], "z": 0,
                                    "_desc": r.get("Description", "")}
    # ---- other names: commonly reported ones first, then the rest
    seen = {c: {o["t"].lower()} for c, o in occ.items()}
    def add(code, title):
        o = occ.get(code)
        if not o:
            return
        for t in names_of(title):
            if t.lower() not in seen[code]:
                seen[code].add(t.lower())
                o["a"].append(t)
    for r in rows(src, "Sample of Reported Titles.txt"):
        add(r["O*NET-SOC Code"], r["Reported Job Title"])
    for o in occ.values():
        o["n"] = len(o["a"])
    for r in rows(src, "Job Titles.txt", "Alternate Titles.txt"):
        add(r["O*NET-SOC Code"], r.get("Job Title") or r.get("Alternate Title") or "")
        st = r.get("Short Title") or ""
        if st and st != "n/a":
            add(r["O*NET-SOC Code"], st)
    # ---- related occupations (the two "primary" tiers: the ten closest)
    for r in rows(src, "Related Occupations.txt"):
        if r["Relatedness Tier"].startswith("Primary") and r["Related O*NET-SOC Code"] in occ and r["O*NET-SOC Code"] in occ:
            occ[r["O*NET-SOC Code"]]["r"].append(r["Related O*NET-SOC Code"])
    for r in rows(src, "Job Zones.txt"):
        if r["O*NET-SOC Code"] in occ:
            occ[r["O*NET-SOC Code"]]["z"] = int(r["Job Zone"])
    # ---- software: the in-demand names, minus the ones nearly every occupation lists (Microsoft Office ...)
    soft, sdf = collections.defaultdict(list), collections.Counter()
    for r in rows(src, "Software Skills.txt", "Technology Skills.txt"):
        name = clean(r.get("Workplace Example") or r.get("Example") or "")
        hot = (r.get("Hot Technology") == "Y", r.get("In Demand") == "Y")
        if name and hot[1] and r["O*NET-SOC Code"] in occ:   # "In Demand": often asked for in this occupation's postings
            soft[r["O*NET-SOC Code"]].append((not hot[0], name))
            sdf[name] += 1
    n_occ = len(occ)
    for code, lst in soft.items():
        keep = [n for _, n in sorted(lst) if sdf[n] <= 0.2 * n_occ and not n.lower().endswith(" software")]
        occ[code]["s"] = keep[:12]
    # ---- words that set an occupation's tasks apart (tf-idf over the task statements + description)
    tf = {c: collections.Counter() for c in occ}
    surface = collections.defaultdict(collections.Counter)
    def feed(code, text, weight=1):
        for w in words(text):
            if w in STOP or len(w) < 4:
                continue
            s = stem(w)
            if s in STOP:
                continue
            tf[code][s] += weight
            surface[s][w] += 1
    for r in rows(src, "Task Statements.txt"):
        if r["O*NET-SOC Code"] in occ:
            feed(r["O*NET-SOC Code"], r["Task"], 2 if r.get("Task Type") == "Core" else 1)
    for c, o in occ.items():
        feed(c, o.pop("_desc"), 2)
    df = collections.Counter()
    for c in tf:
        df.update(tf[c].keys())
    for c, cnt in tf.items():
        scored = sorted(((n * math.log(n_occ / df[s]), s) for s, n in cnt.items() if n >= 3 and df[s] <= 0.10 * n_occ), reverse=True)
        occ[c]["k"] = [surface[s].most_common(1)[0][0] for _, s in scored[:10]]
    # ---- in how many occupations each title word turns up (a word used by few occupations, like "nurse" or "rn",
    #      says far more about a job than one used by hundreds, like "manager"; lookfor.weight uses this)
    tdf = collections.Counter()
    for o in occ.values():
        seen_words = set()
        for t in [o["t"]] + o["a"]:
            seen_words.update(stem(w) for w in re.findall(r"[a-z0-9]+(?:[+#]+)?", t.lower().replace("&", " and ").replace("'", "")))
        tdf.update(seen_words)
    data = {"version": version, "titles": sum(1 + len(o["a"]) for o in occ.values()),
            "source": "O*NET %s Database, U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). "
                      "CC BY 4.0. Trimmed and modified by Siftwell." % version,
            "occ": occ, "df": {w: n for w, n in tdf.items() if n >= 2}}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    with open(out, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0, compresslevel=9) as z:   # mtime=0: the same input gives the same file
            z.write(raw)
    print(f"O*NET {version}: {len(occ)} occupations, {data['titles']} titles -> {out} "
          f"({os.path.getsize(out) / 1024:.0f} KB; {len(raw) / 1024:.0f} KB unpacked)")


if __name__ == "__main__":
    main()
