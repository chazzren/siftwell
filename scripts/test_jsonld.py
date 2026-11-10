"""Offline tests for jsonld_fetcher parsing (JobPosting JSON-LD / microdata). Run: python -X utf8 scripts/test_jsonld.py"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import jsonld_fetcher as j

def ld(obj):
    return '<html><head><script type="application/ld+json">' + json.dumps(obj) + "</script></head><body></body></html>"

POST = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Data Analyst", "identifier": {"@type": "PropertyValue", "value": "R-77"},
        "description": "<p>Analyze &amp; report.</p><ul><li>SQL</li><li>Python</li></ul>", "datePosted": "2026-03-04T10:00:00Z",
        "employmentType": ["FULL_TIME"], "hiringOrganization": {"@type": "Organization", "name": "Acme Co"},
        "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Arlington", "addressRegion": "Virginia", "addressCountry": "US"}},
        "baseSalary": {"@type": "MonetaryAmount", "currency": "USD", "value": {"@type": "QuantitativeValue", "minValue": 90000, "maxValue": 120000, "unitText": "YEAR"}}}

def one(page, url="https://acme.example/careers/jobs/1"):
    return [n for n in (j.normalize(o, url) for o in j.postings_in(page)) if n]

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

r = one(ld(POST))
check("single posting parsed", len(r) == 1 and r[0]["title"] == "Data Analyst")
check("location City, ST", r[0]["locations"] == ["Arlington, VA"])
check("salary annual", r[0]["salary"][:2] == (90000, 120000))
check("description text", r[0]["desc"].startswith("Analyze & report.") and "SQL" in r[0]["desc"] and "<" not in r[0]["desc"])
check("id/date/org/type", (r[0]["ident"], r[0]["posted"], r[0]["org"], r[0]["employment_type"]) == ("R-77", "2026-03-04", "Acme Co", "FULL_TIME"))

lst = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
    {"@type": "ListItem", "position": 1, "item": dict(POST, title="A")}, {"@type": "ListItem", "position": 2, "item": dict(POST, title="B")}]}
check("ItemList", [x["title"] for x in one(ld(lst))] == ["A", "B"])
check("@graph", len(one(ld({"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, POST]}))) == 1)
check("array of scripts + list of postings", len(one(ld([POST, dict(POST, title="C")]))) == 2)
check("@type as list", len(one(ld(dict(POST, **{"@type": ["JobPosting", "Thing"]})))) == 1)

hourly = dict(POST, baseSalary={"currency": "USD", "value": {"minValue": 25, "maxValue": 35, "unitText": "HOUR"}})
check("hourly salary x2080", one(ld(hourly))[0]["salary"][:2] == (52000, 72800))
single = dict(POST, baseSalary={"currency": "USD", "value": {"value": 6000, "unitText": "MONTH"}})
check("single monthly value", one(ld(single))[0]["salary"][:2] == (72000, 72000))
check("string salary", one(ld(dict(POST, baseSalary={"currency": "USD", "value": "85000"})))[0]["salary"][:2] == (85000, 85000))
check("non-USD salary ignored", one(ld(dict(POST, baseSalary={"currency": "EUR", "value": {"minValue": 50000, "maxValue": 60000, "unitText": "YEAR"}})))[0]["salary"] is None)
nosal = dict(POST); nosal.pop("baseSalary")
check("no salary", one(ld(nosal))[0]["salary"] is None)

rem = dict(POST, jobLocationType="TELECOMMUTE", applicantLocationRequirements={"@type": "Country", "name": "USA"}); rem.pop("jobLocation")
rr = one(ld(rem))[0]
check("remote US", rr["workplace"] == "remote" and rr["locations"] == ["Remote, US"])
remx = dict(rem, applicantLocationRequirements={"@type": "Country", "name": "Canada"})
check("remote non-US skipped", one(ld(remx)) == [])
nonus = dict(POST, jobLocation={"@type": "Place", "address": {"addressLocality": "Toronto", "addressRegion": "ON", "addressCountry": "CA"}})
check("non-US skipped", one(ld(nonus)) == [])
multi = dict(POST, jobLocation=[nonus["jobLocation"], POST["jobLocation"]])
check("multi-location keeps if any US", len(one(ld(multi))) == 1)
check("address as string", one(ld(dict(POST, jobLocation={"address": "Reston, VA"})))[0]["locations"] == ["Reston, VA"])
check("bad JSON ignored", one('<script type="application/ld+json">{oops</script>') == [])

micro = """<div itemscope itemtype="https://schema.org/JobPosting"><h1 itemprop="title">Nurse</h1>
<meta itemprop="datePosted" content="2026-02-01"><div itemprop="description"><p>Care for <b>patients</b>.</p></div>
<span itemprop="hiringOrganization" itemscope itemtype="https://schema.org/Organization"><span itemprop="name">Mercy</span></span>
<span itemprop="jobLocation" itemscope itemtype="https://schema.org/Place"><span itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">
<span itemprop="addressLocality">Baltimore</span>, <span itemprop="addressRegion">MD</span> <meta itemprop="addressCountry" content="US"></span></span></div>"""
m = one(micro)
check("microdata", len(m) == 1 and m[0]["title"] == "Nurse" and m[0]["locations"] == ["Baltimore, MD"] and m[0]["org"] == "Mercy" and "patients" in m[0]["desc"])

links = '<a href="/careers/jobs/123-analyst">x</a><a href="/careers/jobs/124-nurse">y</a><a href="https://other.example/jobs/9">z</a><a href="/about">a</a>'
g = j.job_links(links, "https://acme.example/careers")
check("job_links same-site grouping", list(g) == ["/careers/jobs/"] and len(g["/careers/jobs/"]) == 2)
sm = '<urlset><url><loc>https://a.example/careers/x1</loc><lastmod>2026-01-01</lastmod></url><url><loc>https://a.example/blog/y</loc></url></urlset>'
import re
orig_get, orig_allowed = j.get_text, j.allowed
j.get_text, j.allowed = lambda u, h=None: sm, lambda u: True
try:
    check("sitemap parse", j.read_sitemap("https://a.example/sitemap.xml") == [("https://a.example/careers/x1", "2026-01-01"), ("https://a.example/blog/y", "")])
finally:
    j.get_text, j.allowed = orig_get, orig_allowed
print("FAILED: %s" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
