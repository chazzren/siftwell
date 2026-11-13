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
Prints numbers only (titles only with --show, for a developer looking at their own scratch copy).

    --split   learning from Claude's ratings (lookfor.learn_from_ratings), measured honestly: the rated jobs are split
              in two (the earlier-rated half / five random halves), Relevance learns from one half and is measured
              on the other, before (the sheet alone) and after; the person's sheet is kept as it is (chips, removals).
    --sim     also simulate which jobs the automatic quick checks pick (RUN_LIMITS["haiku"] per run, six runs) from
              no ratings: Relevance alone, learning after each run, learning + the exploration share (pick_haiku);
              prints how many Match >= 70 jobs have been rated after each run. Slow (a few minutes per profile)."""
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


HI = 70


def _board(pid):
    """The stored board with its posting text, the person's sheet without what it learned from Claude, their marks."""
    people.set_current(pid)
    jobs = json.load(open(people.pdir("jobs.json", pid=pid), encoding="utf-8"))["jobs"]
    if os.path.exists(os.path.join(DATA, "catalog.db")):
        import catalog
        descs = catalog.descriptions(j["id"] for j in jobs)
        for j in jobs:
            j["desc"] = descs.get(j["id"]) or j.get("snippet", "")
    return jobs, dict(lookfor.ensure(pid), from_claude={}), lookfor.learned(pid)


def _score(jobs, sheet, marks, fc):
    sc = lookfor.Scorer(dict(sheet, from_claude=fc or {}), marks).fit(jobs)
    for j in jobs:
        sc.score(j)
    return {j["id"]: (j["rel"] or 0, j.get("rel_x", 0)) for j in jobs}


def _learn(rated, sheet):
    return lookfor.learn_from_ratings([(j["title"], j["ai_fit"], j.get("desc") or "") for j in rated], sheet)


def _metrics(jobs, test, rel, marked, K=250):
    good = [j for j in test if j["ai_fit"] >= HI]
    key = lambda j: (-rel[j["id"]][0], -j.get("appeal", 0), j["id"])
    top = sorted(test, key=key)
    rank = {j["id"]: i + 1 for i, j in enumerate(sorted(jobs, key=key))}
    return {"rho": spearman([rel[j["id"]][0] for j in test], [j["ai_fit"] for j in test]),
            f"p@{K}": sum(1 for j in top[:K] if j["ai_fit"] >= HI) / max(1, min(K, len(top))),
            "recall@20%": sum(1 for j in top[:max(1, len(test) // 5)] if j["ai_fit"] >= HI) / max(1, len(good)),
            "hi_rel<20": sum(1 for j in good if rel[j["id"]][0] < 20) / max(1, len(good)),
            "marked_rank_pct": sum(100 * rank[i] / len(jobs) for i in marked if i in rank) / max(1, sum(1 for i in marked if i in rank))}


def split_eval(pid):
    import random
    jobs, sheet, marks = _board(pid)
    try:
        marked = [i for i, v in json.load(open(people.pdir("marks.json", pid=pid))).items() if v in ("saved", "applied")]
    except Exception:
        marked = []
    rated = [j for j in jobs if j.get("ai_fit") is not None]
    print(f"  jobs {len(jobs)}, rated {len(rated)}, Match >= {HI}: {sum(1 for j in rated if j['ai_fit'] >= HI)}")
    if len(rated) < 50:
        return
    base = _score(jobs, sheet, marks, {})
    halves = []
    by_time = sorted(rated, key=lambda j: (j.get("ai_at") or "", j["id"]))
    halves.append(("earlier half -> later half", by_time[:len(by_time) // 2], by_time[len(by_time) // 2:]))
    for seed in range(5):
        xs = list(rated)
        random.Random(seed).shuffle(xs)
        halves.append((f"random half {seed}", xs[:len(xs) // 2], xs[len(xs) // 2:]))
    fmt = lambda d: "  ".join(f"{k} {v:.3f}" if k != "marked_rank_pct" else f"{k} {v:.1f}" for k, v in d.items())
    sums = {}
    for name, learn_on, test in halves:
        fc = _learn(learn_on, sheet)
        b, a = _metrics(jobs, test, base, marked), _metrics(jobs, test, _score(jobs, sheet, marks, fc), marked)
        print(f"  {name}: learned {len(fc['up'])} titles up, {len(fc['down'])} down, {len(fc['terms'])} words")
        print(f"    before  {fmt(b)}\n    after   {fmt(a)}")
        if name.startswith("random"):
            for k in b:
                sums.setdefault(k, [0.0, 0.0])
                sums[k][0] += b[k] / 5; sums[k][1] += a[k] / 5
    print("  mean of the random halves: " + "  ".join(f"{k} {v[0]:.3f} -> {v[1]:.3f}" for k, v in sums.items()))
    if "--sim" in args:
        import ai_score
        n = ai_score.RUN_LIMITS["haiku"]
        for label, learn_on, explore in (("Relevance alone", False, 0.0), ("learning", True, 0.0),
                                         ("learning + exploration", True, ai_score.EXPLORE_SHARE)):
            got, fc, found = set(), {}, []
            for run in range(6):
                rel = _score(rated, sheet, marks, fc)
                for j in rated:
                    j["rel"], j["rel_x"] = rel[j["id"]]
                pick = ai_score.pick_haiku([j for j in rated if j["id"] not in got], n, explore)
                got.update(j["id"] for j in pick)
                found.append(sum(1 for j in rated if j["id"] in got and j["ai_fit"] >= HI))
                if learn_on:
                    fc = _learn([j for j in rated if j["id"] in got], sheet)
            print(f"  simulated runs of {n} quick checks, {label}: Match >= {HI} rated after runs 1-6: {found}")


if __name__ == "__main__":
    for n, p in enumerate(people.load_index()):
        print(f"profile {n + 1}:")
        if "--split" in args:
            split_eval(p["id"])
            continue
        for k, v in evaluate(p["id"], SHOW).items():
            print(f"  {k}: {v}")
