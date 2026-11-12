"""How well does the free Relevance score (lookfor.py) agree with Claude's Match ratings and the person's own marks?

    python -X utf8 scripts/eval_relevance.py <data folder COPY> [--lookfor <folder holding another lookfor.py>] [--show N]

Reads a COPY of a data folder (never point it at a live one: it writes lookfor.json into each profile). For every
profile it builds the what-to-look-for sheet without Claude, scores every job on the stored board (jobs.json) and
prints, with the stored Match ratings (ai_fit) as labels:
  rho      Spearman rank correlation of Relevance with Match over the rated jobs
  p@500    of the 500 rated jobs with the highest Relevance, the share with Match >= 70 (base = share among all rated)
  recall   of the jobs with Match >= 70, the share inside the top 20% by Relevance
  low/hi   jobs with Match >= 70 and Relevance < 20; jobs with Relevance >= 80 and Match < 40
  marks    where saved / applied jobs rank by Relevance (rank / jobs, percentile)
  spread   share of all jobs at 80+, 60+, 40+, 20+
Prints numbers only (titles only with --show, for a developer looking at their own scratch copy)."""
import json, os, sys

args = sys.argv[1:]
if not args:
    sys.exit(__doc__)
DATA = os.path.abspath(args[0])
os.environ["JOBBOARD_DATA"] = DATA
os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
os.environ["SIFTWELL_PRETEND_NO_CLAUDE"] = "1"
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
if "--lookfor" in args:
    sys.path.insert(0, os.path.abspath(args[args.index("--lookfor") + 1]))
SHOW = int(args[args.index("--show") + 1]) if "--show" in args else 0
import people, lookfor


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r, i = [0.0] * len(xs), 0
    while i < len(order):
        k = i
        while k + 1 < len(order) and xs[order[k + 1]] == xs[order[i]]:
            k += 1
        for m in range(i, k + 1):
            r[order[m]] = (i + k) / 2 + 1
        i = k + 1
    return r


def spearman(a, b):
    if len(a) < 3:
        return float("nan")
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else float("nan")


def evaluate(pid, show=0):
    people.set_current(pid)
    try:
        os.remove(people.pdir(lookfor.FILE, pid=pid))
    except OSError:
        pass
    jobs = json.load(open(people.pdir("jobs.json", pid=pid), encoding="utf-8"))["jobs"]
    try:
        marks = json.load(open(people.pdir("marks.json", pid=pid)))
    except Exception:
        marks = {}
    if os.path.exists(os.path.join(DATA, "catalog.db")):  # the full posting text, as a real board build has it
        try:
            import catalog
            descs = catalog.descriptions(j["id"] for j in jobs)
            for j in jobs:
                j["desc"] = descs.get(j["id"]) or j.get("snippet", "")
        except Exception as e:
            print("  (no posting text from the catalog:", e, ")")
    sc = lookfor.Scorer(lookfor.build(pid), {})          # no learning: the marks are the labels here
    if hasattr(sc, "fit"):
        sc.fit(jobs)
    for j in jobs:
        sc.score(j)
    rated = [j for j in jobs if j.get("ai_fit") is not None and j.get("rel") is not None]
    out = {"jobs": len(jobs), "rated": len(rated)}
    out["rho"] = round(spearman([j["rel"] for j in rated], [j["ai_fit"] for j in rated]), 3)
    top = sorted(rated, key=lambda j: (-j["rel"], j["id"]))
    good = [j for j in rated if j["ai_fit"] >= 70]
    out["base"] = round(len(good) / max(1, len(rated)), 3)
    out["p@500"] = round(sum(1 for j in top[:500] if j["ai_fit"] >= 70) / max(1, min(500, len(top))), 3)
    out["p@100"] = round(sum(1 for j in top[:100] if j["ai_fit"] >= 70) / max(1, min(100, len(top))), 3)
    k = max(1, len(rated) // 5)
    out["recall@20%"] = round(sum(1 for j in top[:k] if j["ai_fit"] >= 70) / max(1, len(good)), 3)
    out["match70_rel<20"] = f"{sum(1 for j in good if j['rel'] < 20)}/{len(good)}"
    hi = [j for j in rated if j["rel"] >= 80]
    out["rel80_match<40"] = f"{sum(1 for j in hi if j['ai_fit'] < 40)}/{len(hi)}"
    order = {j["id"]: i + 1 for i, j in enumerate(sorted(jobs, key=lambda j: (-(j.get("rel") or 0), j["id"])))}
    byid = {j["id"]: j for j in jobs}
    out["marks"] = [f"{st}: rel {byid[i]['rel']}, rank {order[i]}/{len(jobs)} (top {100 * order[i] / len(jobs):.1f}%)"
                    for i, st in marks.items() if i in byid and st in ("saved", "applied")]
    n = max(1, len(jobs))
    out["spread"] = {f"{t}+": f"{100 * sum(1 for j in jobs if (j.get('rel') or 0) >= t) / n:.1f}%" for t in (80, 60, 40, 20)}
    if show:
        print("  sheet:", json.dumps({k: v for k, v in lookfor.load(pid).items() if k in ("recent", "titles", "occs", "skills", "field")}, ensure_ascii=False)[:3000])
        for j in sorted(jobs, key=lambda j: (-(j.get("rel") or 0), j["id"]))[:show]:
            print(f"  {j['rel']:3} m={j.get('ai_fit')}  {j['title'][:70]}  | {j.get('rel_why', '')[:90]}")
        print("  -- Match>=70 with the lowest Relevance")
        for j in sorted(good, key=lambda j: j["rel"])[:show]:
            print(f"  {j['rel']:3} m={j.get('ai_fit')}  {j['title'][:70]}  | {j.get('rel_why', '')[:90]}")
        print("  -- Relevance>=60 with the lowest Match")
        for j in sorted((j for j in rated if j["rel"] >= 60), key=lambda j: j["ai_fit"])[:show]:
            print(f"  {j['rel']:3} m={j.get('ai_fit')}  {j['title'][:70]}  | {j.get('rel_why', '')[:90]}")
    return out


if __name__ == "__main__":
    for n, p in enumerate(people.load_index()):
        print(f"profile {n + 1}:")
        for k, v in evaluate(p["id"], SHOW).items():
            print(f"  {k}: {v}")
