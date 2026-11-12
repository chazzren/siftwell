"""Fetchers for job systems common at small and mid-size employers.

Each reader takes a companies.json entry `c` and yields jobfinder.J(...) dicts. Config fields per "ats":

  workable   token  - account slug from apply.workable.com/{token}/ (or {token}.workable.com)
                      feed: GET https://apply.workable.com/api/v1/widget/accounts/{token}?details=true
                      (one request; descriptions included)
  bamboohr   token  - subdomain from https://{token}.bamboohr.com/careers
                      feed: GET https://{token}.bamboohr.com/careers/list ; detail: /careers/{id}/detail
  jazzhr     token  - subdomain from https://{token}.applytojob.com/apply
                      feed: HTML list at /apply (two page templates handled); detail page has JobPosting ld+json
  breezy     token  - subdomain from https://{token}.breezy.hr/
                      feed: GET https://{token}.breezy.hr/json ; detail page has JobPosting ld+json
  recruitee  token  - subdomain from https://{token}.recruitee.com/
                      feed: GET https://{token}.recruitee.com/api/offers/ (descriptions included)
  paycom     key    - 32-hex client key from paycomonline.net/v4/ats/web.php/jobs?clientkey={key}
                      or .../web.php/portal/{key}/career-page
                      feed: the career page embeds an anonymous session JWT ("sessionJWT") and the API host
                      ("atsPortalMantleServiceUrl"); POST {api}/api/ats/job-posting-previews/search with that JWT,
                      detail GET {api}/api/ats/job-postings/{jobId}
  saashr     host, cid - UKG Ready / Kronos Workforce Ready, from https://{host}/ta/{cid}.careers?CareersSearch
                      (host like secure6.saashr.com); feed: GET https://{host}/ta/rest/ui/recruitment/companies/%7C{cid}/job-requisitions
  dayforce   ns, board - from https://jobs.dayforcehcm.com/en-US/{ns}/{board} (board is usually CANDIDATEPORTAL)
                      feed: GET /api/auth/csrf (sets cookies) then POST /api/geo/{ns}/jobposting/search with
                      X-CSRF-TOKEN; descriptions included

Full descriptions are fetched per job only when extra_fetchers.wanted(c, title) is true.
"""
import json, re, time, threading, html as _html, http.cookiejar, urllib.request, urllib.error, concurrent.futures as cf
import netsafe
from jobfinder import http_json, strip_html, J
from extra_fetchers import http_text, wanted

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
POOL = 6


def _wp(*vals):
    """Workplace from a board's label, a location or a title: negation first ("Not Remote" is on-site), whole words."""
    import jobtext
    got = [jobtext.workplace_label(v) for v in vals if v]
    if any(g == "onsite" and "remote" in str(v).lower() for g, v in zip(got, [v for v in vals if v])):
        return "onsite"     # a label that says "not remote" outranks a title that mentions remote
    return "remote" if "remote" in got else "hybrid" if "hybrid" in got else "onsite" if "onsite" in got else ""


def _ldjob(h):
    """The JobPosting object from a page's ld+json blocks, or {}."""
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', h, re.S):
        try:
            d = json.loads(m.group(1).strip())
        except Exception:
            continue
        for x in d if isinstance(d, list) else [d]:
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return {}


def _ld_locs(d):
    out = []
    jl = d.get("jobLocation") or []
    for l in jl if isinstance(jl, list) else [jl]:
        a = (l or {}).get("address") or {}
        if isinstance(a, dict):
            out.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion")) if x))
    return [x for x in out if x]


def _pool(fn, items):
    with cf.ThreadPoolExecutor(POOL) as ex:
        yield from ex.map(fn, items)


# ---------------------------------------------------------------- Workable
_WK_LOCK = threading.Lock()
_WK_LAST = [0.0]

def _workable_json(url):
    """Workable rate-limits per IP (HTTP 429, Retry-After: 0), so requests are serialized, spaced, and retried slowly."""
    for i in range(6):
        with _WK_LOCK:
            wait = _WK_LAST[0] + 1.5 - time.time()
            if wait > 0:
                time.sleep(wait)
            _WK_LAST[0] = time.time()
            try:
                return _req(url)
            except urllib.error.HTTPError as e:
                if e.code != 429 or i == 5:
                    raise
        time.sleep(10 * (i + 1))

def f_workable(c):
    d = _workable_json(f'https://apply.workable.com/api/v1/widget/accounts/{c["token"]}?details=true')
    for j in d.get("jobs") or []:
        locs = [", ".join(x for x in (l.get("city"), l.get("region")) if x) or l.get("country", "")
                for l in j.get("locations") or [] if not l.get("hidden")]
        if not locs:
            locs = [", ".join(x for x in (j.get("city"), j.get("state")) if x) or j.get("country", "")]
        wp = "remote" if j.get("telecommuting") else _wp(j.get("title"))
        yield J(c, j.get("title"), j.get("url") or j.get("shortlink"), locs, wp, None, strip_html(j.get("description") or ""),
                (j.get("published_on") or j.get("created_at") or "")[:10], j.get("department") or "", j.get("shortcode"))


# ---------------------------------------------------------------- BambooHR
BAMBOO_WP = {"0": "onsite", "1": "remote", "2": "hybrid"}

def f_bamboohr(c):
    base = f'https://{c["token"]}.bamboohr.com/careers'
    d = http_json(f"{base}/list")

    def detail(j):
        title = j.get("jobOpeningName") or ""
        l = j.get("location") or {}
        al = j.get("atsLocation") or {}
        loc = ", ".join(x for x in (l.get("city") or al.get("city"), l.get("state") or al.get("state") or al.get("province")) if x)
        wp = "remote" if j.get("isRemote") else BAMBOO_WP.get(str(j.get("locationType") or ""), "")
        desc, posted = "", ""
        if wanted(c, title):
            try:
                o = http_json(f'{base}/{j["id"]}/detail')["result"]["jobOpening"]
                desc, posted = strip_html(o.get("description") or ""), o.get("datePosted") or ""
                if o.get("compensation"):
                    desc = f'Compensation: {o["compensation"]}\n{desc}'
            except Exception:
                pass
        return J(c, title, f'{base}/{j["id"]}', [loc or ("Remote" if wp == "remote" else "")], wp, None, desc, posted,
                 j.get("departmentLabel") or "", j["id"])
    yield from _pool(detail, d.get("result") or [])


# ---------------------------------------------------------------- JazzHR
def f_jazzhr(c):
    root = f'https://{c["token"]}.applytojob.com'
    h = http_text(f"{root}/apply")
    rows = []
    # template A (table): <div id="row_job_YYYYMMDD..." class="jobs_row"> <a class="job_title_link" href="/apply/jobs/details/CODE?&">Title</a>
    for m in re.finditer(r'id="row_job_(\d{8})\d*_[^"]*"\s+class="jobs_row">(.*?)</div>\s*(?=<div id="row_job_|</div>)', h, re.S):
        blk = m.group(2)
        a = re.search(r'href="(?:https?://[^/"]+)?/apply/jobs/details/([A-Za-z0-9]+)[^"]*"[^>]*>(.*?)</a>', blk, re.S)
        if not a:
            continue
        loc = re.search(r"<strong>Location:</strong>\s*([^<]+)", blk)
        dept = re.search(r"<strong>Department:</strong>\s*([^<]+)", blk)
        d = m.group(1)
        rows.append((a.group(1), f"{root}/apply/jobs/details/{a.group(1)}", strip_html(a.group(2)),
                     [_html.unescape(loc.group(1).strip())] if loc else [], _html.unescape(dept.group(1).strip()) if dept else "",
                     f"{d[:4]}-{d[4:6]}-{d[6:8]}"))
    # template B (list-group): <h3 class='list-group-item-heading'><a href=".../apply/CODE/Slug">Title</a></h3><ul>...<li><i class='fa fa-map-marker'></i>Loc</li>
    if not rows:
        for m in re.finditer(r'<li class="list-group-item">(.*?)</li>\s*(?=<li class="list-group-item">|</ul>|$)', h, re.S):
            blk = m.group(1)
            a = re.search(r'href="((?:https?://[^/"]+)?/apply/([A-Za-z0-9]{6,})/[^"]*)"[^>]*>(.*?)</a>', blk, re.S)
            if not a:
                continue
            url = a.group(1) if a.group(1).startswith("http") else root + a.group(1)
            loc = re.search(r"fa-map-marker['\"]></i>\s*([^<]+)", blk)
            dept = re.search(r"fa-(?:sitemap|building|briefcase)['\"]></i>\s*([^<]+)", blk)
            rows.append((a.group(2), url, strip_html(a.group(3)), [_html.unescape(loc.group(1).strip())] if loc else [],
                         _html.unescape(dept.group(1).strip()) if dept else "", ""))
    seen = set()
    rows = [r for r in rows if not (r[0] in seen or seen.add(r[0]))]

    def detail(r):
        code, url, title, locs, dept, posted = r
        desc, wp = "", _wp(*locs, title)
        if wanted(c, title):
            try:
                d = _ldjob(http_text(url))
                desc = strip_html(d.get("description") or "")
                posted = (d.get("datePosted") or posted or "")[:10]
                locs = locs or _ld_locs(d)
                if __import__("jobtext").telecommute(d):
                    wp = "remote"
            except Exception:
                pass
        return J(c, title, url, locs, wp, None, desc, posted, dept, code)
    yield from _pool(detail, rows)


# ---------------------------------------------------------------- Breezy HR
def f_breezy(c):
    root = f'https://{c["token"]}.breezy.hr'
    jobs = http_json(f"{root}/json")

    def detail(j):
        title = j.get("name") or ""
        ls = j.get("locations") or [j.get("location") or {}]
        locs, remote = [], False
        for l in ls:
            l = l or {}
            st = (l.get("state") or {}).get("id") if isinstance(l.get("state"), dict) else l.get("state")
            locs.append(", ".join(x for x in (l.get("city"), st) if x) or l.get("name") or "")
            remote = remote or bool(l.get("is_remote"))
        wp = "remote" if remote else _wp(*locs, title)
        desc = ""
        if wanted(c, title):
            try:
                d = _ldjob(http_text(j["url"]))
                desc = strip_html(d.get("description") or "")
                if __import__("jobtext").telecommute(d):
                    wp = "remote"
            except Exception:
                pass
        sal = j.get("salary") or ""
        if sal and desc:
            desc = f"Salary: {sal}\n{desc}"
        return J(c, title, j.get("url"), locs, wp, None, desc, (j.get("published_date") or "")[:10],
                 j.get("department") or "", j.get("id"))
    yield from _pool(detail, jobs if isinstance(jobs, list) else [])


# ---------------------------------------------------------------- Recruitee
def f_recruitee(c):
    d = http_json(f'https://{c["token"]}.recruitee.com/api/offers/')
    for o in d.get("offers") or []:
        locs = [", ".join(x for x in (l.get("city"), l.get("state_code") or l.get("state")) if x) or l.get("name", "")
                for l in o.get("locations") or []] or [o.get("location") or ""]
        wp = "remote" if o.get("remote") else "hybrid" if o.get("hybrid") else "onsite" if o.get("on_site") else ""
        desc = strip_html((o.get("description") or "") + "\n" + (o.get("requirements") or ""))
        s = o.get("salary") or {}
        if s.get("min") or s.get("max"):
            desc = f'Salary: {s.get("min") or ""}-{s.get("max") or ""} {s.get("currency") or ""}/{s.get("period") or ""}\n{desc}'
        yield J(c, o.get("title"), o.get("careers_url"), locs, wp, None, desc, (o.get("published_at") or o.get("created_at") or "")[:10],
                o.get("department") or "", o.get("id"))


# ---------------------------------------------------------------- Paycom
PAYCOM_FILTERS = {"distanceFrom": 0, "workEnvironments": [], "positionTypes": [], "educationLevels": [], "categories": [],
                  "travelTypes": [], "shiftTypes": [], "otherFilters": [], "keywordSearchText": "", "location": "", "sortOption": ""}

def _req(url, body=None, headers=None, opener=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", **(headers or {})}
    if data is not None:
        hdr["Content-Type"] = "application/json"
    last = None
    for _ in range(3):
        try:
            with (opener or netsafe.build_opener()).open(urllib.request.Request(url, data=data, headers=hdr), timeout=timeout) as r:
                return json.loads(r.read())
        except netsafe.UnsafeURL:
            raise
        except Exception as e:
            last = e
            if getattr(e, "code", 0) in (400, 401, 403, 404, 429):
                break
    raise last

def f_paycom(c):
    page = f'https://www.paycomonline.net/v4/ats/web.php/portal/{c["key"]}/career-page'
    h = http_text(page)
    tok = re.search(r'"sessionJWT"\s*:\s*"([^"]+)"', h)
    api = re.search(r'atsPortalMantleServiceUrl[\\":\s]+(https:[^"]*?)\\*"', h)
    if not tok:
        raise ValueError("paycom: no session token on career page")
    api = (api.group(1).replace("\\", "") if api else "https://portal-applicant-tracking.us-cent.paycomonline.net/").rstrip("/")
    hdr = {"Authorization": tok.group(1), "Portal-Host-Referrer": page, "Locale": "en-US"}
    rows, skip = [], 0
    while skip < 2000:
        d = _req(f"{api}/api/ats/job-posting-previews/search", {"skip": skip, "take": 100, "filtersForQuery": PAYCOM_FILTERS}, hdr)
        got = d.get("jobPostingPreviews") or []
        rows += got
        skip += 100
        if not got or skip >= (d.get("jobPostingPreviewsCount") or 0):
            break

    def detail(j):
        title = j.get("jobTitle") or ""
        locs = [x.strip() for x in re.split(r"\s*;\s*|\s*\|\s*", j.get("locations") or "") if x.strip()]
        locs = [re.sub(r"\s+\d{5}(?:-\d{4})?$", "", l) for l in locs]
        wp = _wp(j.get("remoteType"))
        desc, posted, dept = strip_html(j.get("description") or ""), (j.get("postedOn") or "")[:10], ""
        if wanted(c, title):
            try:
                o = _req(f'{api}/api/ats/job-postings/{j["jobId"]}', headers=hdr)["jobPosting"]
                desc = strip_html((o.get("description") or "") + "\n" + (o.get("qualifications") or ""))
                if o.get("salaryRange"):
                    desc = f'Salary: {o["salaryRange"]}\n{desc}'
                dept = o.get("jobCategory") or ""
                try:
                    posted = (json.loads(o.get("googleJobJson") or "{}").get("datePosted") or posted)[:10]
                except Exception:
                    pass
                locs += [re.sub(r"\s+\d{5}(?:-\d{4})?$", "", x if isinstance(x, str) else (x or {}).get("location", "")) for x in o.get("secondaryLocations") or []]
            except Exception:
                pass
        url = f'https://www.paycomonline.net/v4/ats/web.php/portal/{c["key"]}/jobs/{j["jobId"]}'
        return J(c, title, url, locs, wp, None, desc, posted, dept, j["jobId"])
    yield from _pool(detail, rows)


# ---------------------------------------------------------------- Dayforce
def f_dayforce(c):
    ns, board = c["ns"], c.get("board") or "CANDIDATEPORTAL"
    jar = http.cookiejar.CookieJar()
    op = netsafe.build_opener(urllib.request.HTTPCookieProcessor(jar))
    host = "https://jobs.dayforcehcm.com"
    csrf = _req(f"{host}/api/auth/csrf", opener=op)["csrfToken"]
    start = 0
    while start < 3000:
        body = {"clientNamespace": ns, "jobBoardCode": board, "cultureCode": "en-US", "distanceUnit": 0, "paginationStart": start}
        d = _req(f"{host}/api/geo/{ns}/jobposting/search", body, {"X-CSRF-TOKEN": csrf}, op)
        got = d.get("jobPostings") or []
        for j in got:
            locs = []
            for l in j.get("postingLocations") or []:
                locs.append(", ".join(x for x in (l.get("cityName"), l.get("stateCode")) if x) or l.get("formattedAddress") or "")
            wp = "remote" if j.get("hasVirtualLocation") else _wp(j.get("jobTitle"))
            if wp == "remote" and not locs:
                locs = ["Remote"]
            yield J(c, j.get("jobTitle"), f'{host}/en-US/{ns}/{board}/jobs/{j["jobPostingId"]}', locs, wp, None,
                    strip_html(j.get("jobDescription") or ""), (j.get("postingStartTimestampUTC") or "")[:10], "", j["jobPostingId"])
        start += len(got)
        if not got or start >= (d.get("maxCount") or 0):
            break


# ---------------------------------------------------------------- UKG Ready (saashr)
def f_saashr(c):
    host, cid = c["host"], c["cid"]
    base = f"https://{host}/ta/rest/ui/recruitment/companies/%7C{cid}/job-requisitions"
    rows, off = [], 0
    while off < 2000:
        d = _req(f"{base}?offset={off}&size=50&sort=desc&ein_id=&lang=en-US")
        got = d.get("job_requisitions") or []
        rows += got
        off += 50
        if not got or off >= ((d.get("_paging") or {}).get("total") or 0):
            break

    def detail(j):
        title = j.get("job_title") or ""
        l = j.get("location") or {}
        loc = ", ".join(x for x in (l.get("city"), l.get("state")) if x)
        wp = "remote" if j.get("is_remote_job") else ""
        desc = strip_html(j.get("job_description") or "")
        if wanted(c, title):
            try:
                o = _req(f'{base}/{j["id"]}?lang=en-US')
                desc = strip_html((o.get("job_description") or "") + "\n" + (o.get("job_requirement") or "")) or desc
            except Exception:
                pass
        if j.get("base_pay_from"):
            desc = f'Pay: {j["base_pay_from"]:,.0f}-{(j.get("base_pay_to") or 0):,.0f} per {(j.get("base_pay_frequency") or "").lower()}\n{desc}'
        url = f"https://{host}/ta/{cid}.careers?ShowJob={j['id']}"
        return J(c, title, url, [loc or ("Remote" if wp else "")], wp, None, desc, "", "", j["id"])
    yield from _pool(detail, rows)


FETCHERS = {"saashr": f_saashr, "workable": f_workable, "bamboohr": f_bamboohr, "jazzhr": f_jazzhr, "breezy": f_breezy,
            "recruitee": f_recruitee, "paycom": f_paycom, "dayforce": f_dayforce}
