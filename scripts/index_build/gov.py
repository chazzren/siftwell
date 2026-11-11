"""Free, keyless lists of employers by place, and how they are tied to readable job boards without Claude.

  bmf(state)   IRS Exempt Organizations Business Master File (https://www.irs.gov/charities-non-profits/exempt-
               organizations-business-master-file-extract-eo-bmf): every tax-exempt organisation with its city, state and
               revenue. Kept: name, city, state, revenue (no officers, no people).
  lca(path)    DOL OFLC LCA disclosure data (employer + worksite city/state). dol.gov refuses automated downloads
               (HTTP 403 from its CDN), so this only runs on a file given with --lca-file / env DOL_LCA_FILE or a URL in
               env DOL_LCA_URL; otherwise it is skipped.
  wdc()        Web Data Commons schema.org JobPosting subset (http://webdatacommons.org/structureddata/): the list of
               web domains whose pages carry JobPosting markup, with how many postings were seen. The multi-GB data files
               aren't read; the domain list (13 MB) is enough to know where to look.

Resolution (no LLM): an employer name becomes a few slug guesses ("OhioHealth Corporation" -> ohiohealth,
ohiohealthcorporation) that are matched against tenants already discovered (Greenhouse token, Workday tenant ...) and,
within a budget per run, probed on the job systems whose feeds are addressable by slug. A guess only counts when the
board's postings are in the employer's state, so a different "Acme" elsewhere isn't taken. A WDC domain is opened at a
few careers addresses and resolved with company_add's own detection (a known job system linked from the page) or
jsonld_fetcher.detect_config (the site's own JobPosting pages). Names that resolve to nothing are dropped (see
README_INDEX in build.py: the app can only watch employers it can read)."""
import csv, io, re, zipfile
import xml.etree.ElementTree as ET

from . import net

BMF_URL = "https://www.irs.gov/pub/irs-soi/eo_{st}.csv"
WDC_STATS = "https://data.dws.informatik.uni-mannheim.de/structureddata/2024-12/quads/classspecific/JobPosting/JobPosting_domain_stats.csv"
SUFFIX = re.compile(r"\b(inc|incorporated|llc|ltd|corp|corporation|company|co|the|plc|lp|llp|pllc|pc|na|of america)\b")


def slugs(name):
    """Slug guesses for an employer name, best first."""
    n = re.sub(r"&", " and ", (name or "").lower())
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    full = re.sub(r"\s+", "", n)
    short = re.sub(r"\s+", "", SUFFIX.sub(" ", n))
    out = [short, full, re.sub(r"\s+", "-", SUFFIX.sub(" ", n).strip())]
    return [s for s in dict.fromkeys(out) if 3 <= len(s) <= 60]


def bmf(state, min_revenue=20_000_000, log=print):
    """[{name, city, state, revenue}] for exempt organisations in state with at least min_revenue a year."""
    try:
        raw = net.get(BMF_URL.format(st=state.lower()), timeout=120)
    except Exception as e:
        log(f"  IRS BMF {state}: skipped ({type(e).__name__})")
        return []
    out = []
    for r in csv.DictReader(io.StringIO(raw.decode("latin-1"))):
        try:
            rev = int(r.get("REVENUE_AMT") or 0)
        except ValueError:
            continue
        if rev >= min_revenue and r.get("STATUS", "01") == "01":
            out.append({"name": _title(r.get("NAME", "")), "city": (r.get("CITY") or "").title(), "state": state, "revenue": rev})
    out.sort(key=lambda x: -x["revenue"])
    log(f"  IRS BMF {state}: {len(out)} organisations with revenue >= ${min_revenue // 1_000_000}M")
    return out


def _title(s):
    small = {"of", "and", "the", "for", "in", "at", "on"}
    words = [w.lower() if w.lower() in small else w if (len(w) <= 4 and not re.search(r"[AEIOU]", w)) else w.capitalize()
             for w in s.split()]
    t = " ".join(words)
    return t[:1].upper() + t[1:]


def lca(source, states, log=print):
    """[{name, city, state, filings}] from a DOL LCA disclosure .xlsx (path or URL), for the given states."""
    try:
        if re.match(r"https?://", source):
            data = net.get(source, timeout=600, cap=400_000_000)
            zf = zipfile.ZipFile(io.BytesIO(data))
        else:
            zf = zipfile.ZipFile(source)
    except Exception as e:
        log(f"  DOL LCA: skipped ({type(e).__name__}: {str(e)[:80]})")
        return []
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    with zf.open("xl/sharedStrings.xml") as f:
        for _, el in ET.iterparse(f):
            if el.tag == ns + "si":
                shared.append("".join(t.text or "" for t in el.iter(ns + "t")))
                el.clear()
    sheet = next(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet"))
    cols, counts = {}, {}
    want = {"EMPLOYER_NAME", "WORKSITE_CITY", "WORKSITE_STATE"}
    with zf.open(sheet) as f:
        for _, row in ET.iterparse(f):
            if row.tag != ns + "row":
                continue
            vals = {}
            for c in row.iter(ns + "c"):
                ref = re.match(r"[A-Z]+", c.get("r", "")).group(0)
                v = c.find(ns + "v")
                if v is None:
                    is_ = c.find(ns + "is")
                    txt = "".join(t.text or "" for t in is_.iter(ns + "t")) if is_ is not None else ""
                else:
                    txt = shared[int(v.text)] if c.get("t") == "s" else (v.text or "")
                vals[ref] = txt
            row.clear()
            if not cols:
                cols = {v: k for k, v in vals.items() if v in want}
                continue
            st = vals.get(cols.get("WORKSITE_STATE", ""), "").strip().upper()
            if st not in states:
                continue
            k = (vals.get(cols.get("EMPLOYER_NAME", ""), "").strip(), vals.get(cols.get("WORKSITE_CITY", ""), "").strip().title(), st)
            if k[0]:
                counts[k] = counts.get(k, 0) + 1
    out = [{"name": n, "city": c, "state": s, "filings": v} for (n, c, s), v in counts.items()]
    out.sort(key=lambda x: -x["filings"])
    log(f"  DOL LCA: {len(out)} employer/worksite pairs in {', '.join(sorted(states))}")
    return out


def wdc(min_postings=3, max_postings=20000, log=print):
    """[(domain, postings)] from the WDC JobPosting domain list: US-looking domains (com/org/edu/gov/us/net), biggest
    first. Job boards and staffing sites are filtered out by name."""
    try:
        raw = net.get(WDC_STATS, timeout=300)
    except Exception as e:
        log(f"  WDC: skipped ({type(e).__name__})")
        return []
    out = []
    junk = re.compile(r"job|career|hiring|recruit|staff|talent|resume|indeed|monster|glassdoor|linkedin|zip|work|employ|vacanc|gig|temp", re.I)
    for line in raw.decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        dom = parts[0].strip().lower()
        try:
            n = int(parts[2])
        except ValueError:
            continue
        if not (min_postings <= n <= max_postings):
            continue
        if not re.search(r"\.(com|org|edu|gov|us|net)$", dom) or junk.search(dom.rsplit(".", 1)[0]):
            continue
        out.append((dom, n))
    out.sort(key=lambda x: -x[1])
    log(f"  WDC: {len(out)} candidate employer domains")
    return out


def resolve_domain(dom, log=print):
    """A job-board config for an employer's web domain: a known job system linked from its careers page, or its own
    JobPosting pages. None when neither is found."""
    from .systems import parse
    import jsonld_fetcher
    for url in (f"https://{dom}/careers", f"https://careers.{dom}/", f"https://jobs.{dom}/", f"https://www.{dom}/careers"):
        try:
            page = net.get_text(url, timeout=25, tries=1, cap=3_000_000)
        except Exception:
            continue
        for m in re.finditer(r"https?://[^\s\"'<>]+", page):
            c = parse(m.group(0))
            if c:
                return c
        cfg = None
        for probe in (lambda: __import__("ats_sap_taleo").detect_page(url, page),   # (the same chain company_add.detect uses)
                      lambda: __import__("ats_more").detect(url, page),
                      lambda: __import__("ats_public").detect(url, page),
                      lambda: jsonld_fetcher.detect_config(url, page)):
            try:
                cfg = probe()
            except Exception:
                cfg = None
            if cfg:
                break
        if cfg:
            import netsafe
            cfg, _ = netsafe.clean_config(cfg)
            if cfg:
                return cfg
    return None
