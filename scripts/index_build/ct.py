"""Certificate Transparency (crt.sh): tenant subdomains of job systems that give each customer its own host
(acme.wd5.myworkdayjobs.com, careers-acme.icims.com, acme.bamboohr.com ...). Public, no key. crt.sh is slow and
often times out on big domains, so a failure just skips the source for this run."""
import json

from . import net


def hosts(domain, log=print):
    """Distinct certificate names under domain (wildcards stripped)."""
    url = f"https://crt.sh/?q=%25.{domain}&output=json&exclude=expired"
    try:
        raw = net.get(url, robots=False, timeout=180, tries=3)
        rows = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        log(f"  crt.sh {domain}: skipped ({type(e).__name__})")
        return []
    out = set()
    for r in rows:
        for n in str(r.get("name_value") or "").split("\n"):
            n = n.strip().lower().lstrip("*.")
            if n.endswith("." + domain) and n.count(".") >= domain.count(".") + 1:
                out.add(n)
    log(f"  crt.sh {domain}: {len(out)} names")
    return sorted(out)
