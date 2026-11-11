"""Job systems the directory looks for: one row per system.

    System(id, cc=[SURT prefixes in the Common Crawl URL index], ct=[domains whose certificate names are tenants],
           rx=None or a regex whose named groups are the config fields, careers="https://... {field} ...")

A URL from Common Crawl, a certificate name from crt.sh, or a link found in a posting is turned into a company config
by company_add._match (the app's own detection, so the configs are exactly what the app reads) or, for a system that
module doesn't know yet, by the row's rx. A new job system is one more row; its reader is found in jobfinder.FETCHERS
(after load_extra) unless readers.py has a lighter one, so a system the app can read needs nothing else here.

read=False keeps a system's tenants out of the reading step (its feed's robots.txt forbids crawlers)."""
import re
from collections import namedtuple

System = namedtuple("System", "id cc ct rx careers read", defaults=((), (), None, "", True))

SYSTEMS = [
    System("greenhouse", ("io,greenhouse,boards)/", "io,greenhouse,job-boards)/"), (), None, "https://job-boards.greenhouse.io/{token}"),
    System("lever", ("co,lever,jobs)/",), (), None, "https://jobs.lever.co/{token}"),
    System("ashby", ("com,ashbyhq,jobs)/",), (), None, "https://jobs.ashbyhq.com/{token}"),
    System("workday", ("com,myworkdayjobs,",), ("myworkdayjobs.com",), None, "https://{tenant}.{wd}.myworkdayjobs.com/{site}"),
    # SmartRecruiters' API robots.txt allows only LinkedInBot, so the builder doesn't read it (the app still can).
    System("smartrecruiters", ("com,smartrecruiters,jobs)/", "com,smartrecruiters,careers)/"), (), None, "https://jobs.smartrecruiters.com/{token}", False),
    System("icims", ("com,icims,",), ("icims.com",), None, "{base}/jobs/search"),
    System("workable", ("com,workable,apply)/",), (), None, "https://apply.workable.com/{token}/"),
    System("bamboohr", ("com,bamboohr,",), ("bamboohr.com",), None, "https://{token}.bamboohr.com/careers"),
    System("jazzhr", ("com,applytojob,",), ("applytojob.com",), None, "https://{token}.applytojob.com/apply"),
    System("breezy", ("hr,breezy,",), ("breezy.hr",), None, "https://{token}.breezy.hr/"),
    System("recruitee", ("com,recruitee,",), ("recruitee.com",), None, "https://{token}.recruitee.com/"),
    System("rippling", ("com,rippling,ats)/",), (), None, "https://ats.rippling.com/{token}/jobs"),
    System("paylocity", ("com,paylocity,recruiting)/recruiting/jobs/",), (), None, "https://recruiting.paylocity.com/recruiting/jobs/All/{id}"),
    System("ukg", ("com,ultipro,recruiting)/", "com,ultipro,recruiting2)/", "net,ukg,pro,rec,"), (), None, "https://{host}/{tenant}/JobBoard/{board}"),
    System("dayforce", ("com,dayforcehcm,jobs)/",), (), None, "https://jobs.dayforcehcm.com/{ns}/{board}"),
    System("taleo", ("net,taleo,",), (), None, "https://{host}/careersection/{section}/jobsearch.ftl"),
    System("paycom", ("net,paycomonline,www)/v4/ats/",), (), None, "https://www.paycomonline.net/v4/ats/web.php/jobs?clientkey={key}"),
    System("saashr", ("com,saashr,",), (), None, "https://{host}/ta/{cid}.careers"),
    System("adp", ("com,adp,workforcenow)/mascsr/",), (), None, "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}"),
    # Public-employer systems (ats_public.py): school districts, hospitals, small governments.
    System("applitrack", ("com,applitrack,www)/",), (), re.compile(r"applitrack\.com/(?P<slug>[A-Za-z0-9][A-Za-z0-9_.-]{0,59})/onlineapp", re.I), "https://www.applitrack.com/{slug}/onlineapp/"),
    System("schoolspring", ("com,schoolspring,",), ("schoolspring.com",), re.compile(r"(?://|^)(?!www\.|api\.)(?P<sub>[a-z0-9][a-z0-9-]{0,60})\.schoolspring\.com", re.I), "https://{sub}.schoolspring.com/"),
    System("jobvite", ("com,jobvite,jobs)/",), (), re.compile(r"jobs\.jobvite\.com/(?P<slug>[A-Za-z0-9][A-Za-z0-9_.-]{0,59})", re.I), "https://jobs.jobvite.com/{slug}/jobs"),
    # Not read on purpose: NEOGOV / GovernmentJobs.com and PeopleAdmin forbid every crawler in robots.txt. If that
    # changes and the app gains readers, they are one row each, e.g.:
    # System("neogov", ("com,governmentjobs,www)/careers/",), (), re.compile(r"governmentjobs\.com/careers/(?P<agency>[A-Za-z0-9_-]+)"), "https://www.governmentjobs.com/careers/{agency}"),
    # System("peopleadmin", ("com,peopleadmin,",), ("peopleadmin.com",), re.compile(r"(?P<host>[a-z0-9-]+\.peopleadmin\.com)"), "https://{host}/postings/search"),
    # Systems on employers' own domains (Phenom, Oracle Recruiting Cloud on custom hosts, SuccessFactors career sites)
    # come in through the Web Data Commons route (gov.resolve_domain), which runs company_add's own detection.
]
BY_ID = {s.id: s for s in SYSTEMS}

BAD = {"www", "app", "api", "apply", "assets", "static", "cdn", "help", "support", "jobs", "careers", "widget", "embed",
       "j", "boards", "job-boards", "v1", "embed", "search", "login", "admin", "mail", "status", "blog", "docs"}


def parse(url):
    """A company config for a job-board URL, or None."""
    if not url:
        return None
    u = url if re.match(r"https?://", url) else "https://" + url
    try:
        import company_add
        c = company_add._match(u)
    except Exception:
        c = None
    if not c:
        for s in SYSTEMS:
            if s.rx is not None:
                m = s.rx.search(u)
                if m:
                    c = {"ats": s.id, **m.groupdict()}
                    break
    if not c:
        return None
    tok = str(c.get("token") or c.get("tenant") or c.get("slug") or c.get("sub") or "").lower()
    if tok in BAD or tok.startswith("embed"):
        return None
    if c.get("ats") == "greenhouse":
        c["token"] = c["token"].lower()
    if c.get("ats") == "workday" and c.get("site", "").lower() in ("wday", "cxs", "job", "details", "login"):
        return None
    try:
        import netsafe
        c, why = netsafe.clean_config(c)
    except Exception:
        return None
    return c


def key(c):
    """One key per job board, the way catalog.ats_key tells two configs apart."""
    try:
        import catalog
        return catalog.ats_key(c)
    except Exception:
        return (c.get("ats"),) + tuple(sorted((k, str(v).lower()) for k, v in c.items() if k != "ats"))


def careers_url(c):
    s = BY_ID.get(c.get("ats"))
    try:
        if s and s.careers:
            return s.careers.format(**c)
    except (KeyError, IndexError):
        pass
    return c.get("list_url") or c.get("base") or ""


def ct_host_config(system, host):
    """A config from a certificate name (a tenant subdomain), when the host alone is enough."""
    host = host.lower().lstrip("*.").strip()
    if system == "workday":
        m = re.fullmatch(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", host)
        return {"ats": "workday", "tenant": m.group(1), "wd": m.group(2)} if m else None   # (site still unknown)
    if system == "icims":
        if re.match(r"(www|cdn\d*|images|provider|login|api|sso|mail)\.", host):
            return None
        return parse(f"https://{host}/jobs") if re.fullmatch(r"[a-z0-9-]+\.icims\.com", host) else None
    return parse(f"https://{host}/")
