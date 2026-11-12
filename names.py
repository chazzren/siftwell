"""Employer names people can read. Job systems address a board by a code or a run-together address, and the employer
field on a posting is often a legal entity with an accounting code in front, so about a quarter of the names a
directory can offer are not names: "Employer in Columbus OH (ADP 0330de)", "07e0 416d A243 7556983c79c7",
"Cameronmitchell", "10 Nationwide Children's Hospital", "(5100) Genzyme", "Jobs Selectmedicalcorp",
"Juvenile Justice Department of", "ISD ISD Renal" (DaVita).

The same derivation runs in two places: the app, after an employer's first fetch (learn(): it has every posting's
text), and the directory builder (scripts/index_build: it has one posting and the board page's title).

    poor(name, cfg)                 why a name is not a real name ("" when it is fine)
    clean_display(name, texts)      codes, generic words, "d/b/a", "X Department of" fixed; no guessing
    split_slug(slug, texts)         "cameronmitchell" + postings that say "Cameron Mitchell" -> "Cameron Mitchell"
    name_from_title(page title)     "Dewey's Pizza - Job Opportunities" -> "Dewey's Pizza"
    mine_name(texts)                the employer's name as its postings state it ("Acme Health is an equal ...")
    derive(name, cfg, texts, ...)   the best of the above, or None when nothing better is known
    learn(company)                  app: derive + catalog.rename_company (listing ids don't change, so ratings stay)
"""
import collections
import html as _html
import re

# ---------------------------------------------------------------- what is wrong with a name
GENERIC = {"agency", "homepage", "home", "careers", "career", "jobs", "job", "boards", "board", "companies", "company", "employer",
           "employers", "external", "internal", "team", "unavailable", "n/a", "na", "none", "null", "test", "default", "main",
           "corporate", "careers page", "career page", "career site", "careers site", "talent acquisition", "talent community",
           "talent", "recruiting", "recruitment", "human resources", "hr", "apply", "opportunities", "search", "welcome",
           "job opportunities", "current openings", "candidate", "candidates", "staff", "staffing", "do not use", "portal"}
_GENERIC_LEAD = re.compile(r"^(?:jobs|careers\d*|career\d+|careersapply|hotjobs|[a-z]+external|external[a-z]+|[a-z]+internal|internal[a-z]+)$", re.I)


def _generic_lead(toks):
    """A job-site word in front of the name: "Jobs Selectmedicalcorp", "Careers2 Fbms", "Externalhourly High"
    (never "Jobs for the Future", "Internal Medicine Associates")."""
    return len(toks) > 1 and bool(_GENERIC_LEAD.match(toks[0])) and toks[1].lower() not in ("for", "of", "and", "&", "in", "to", "plus")
BUSINESS_WORDS = ("healthcare", "health", "group", "partners", "financial", "finance", "insurance", "bank", "logistics",
                  "construction", "solutions", "services", "systems", "medical", "hotels", "brands", "sports", "tire", "supply",
                  "distribution", "pharmacy", "mutual", "electric", "communities", "nurseries", "roofing", "recycling", "software",
                  "pediatrics", "nursing", "treatment", "components", "holdings", "housing", "benefits", "trading", "consultants",
                  "consulting", "diagnostics", "industries", "international", "associates", "hospitals", "hospital", "university",
                  "college", "schools", "energy", "foods", "restaurants", "technologies", "technology", "pharma", "automotive",
                  "auto", "homes", "realty", "properties", "transport", "freight", "express", "labs", "network", "networks",
                  "management", "enterprises", "company", "corporation", "corp", "inc", "llc", "careers", "jobs", "usa", "law",
                  "national", "american", "community", "regional", "memorial", "federal", "county", "dental", "electrical",
                  "mechanical", "manufacturing", "engineering", "contractors", "builders", "equipment", "materials", "packaging",
                  "plastics", "steel", "motors", "markets", "stores", "retail", "wholesale", "hospitality", "hotel", "resorts",
                  "senior", "living", "homecare", "hospice", "therapy", "rehab", "dentistry", "orthopedics", "physicians",
                  "clinic", "clinics", "labs", "laboratories", "sciences", "biotech", "therapeutics", "capital", "advisors",
                  "wealth", "credit", "union", "trust", "title", "mortgage", "lending", "security", "aviation", "airlines",
                  "transportation", "trucking", "delivery", "foundation", "ministries", "church", "academy", "school", "zoo",
                  "library", "museum", "armory", "army", "physicaltherapy")
# number-led names that are real ("84 Lumber", "24 Hour Fitness", "360 Behavioral Health", "2020 Companies")
_KEEP_NUM = {"7", "24", "76", "84", "99", "360", "365", "911", "1800", "2020"}
_KEEP_MIXED = re.compile(r"^(?:\d+(?:st|nd|rd|th)|a123|3m|2u|f5|c3|g4s|k12|a1|a10|m3|8x8|h2o|e2open|b2b|p3|o2|q2|v2x|i3|3d|4front|"
                         r"1-800-\S+|\d+-eleven|7up|s&p|at&t|t-\w+|[a-z]+\d*\.(?:com|ai|io|org))$", re.I)
_UUID = re.compile(r"[0-9a-f]{8}[ _-]?[0-9a-f]{4}[ _-]?[0-9a-f]{4}[ _-]?[0-9a-f]{4}[ _-]?[0-9a-f]{12}", re.I)
_VOWELLESS = re.compile(r"[bcdfghjklmnpqrstvwxz]{5}")
LEGAL = re.compile(r"[,\s]+(Inc\.?|Incorporated|LLC|L\.L\.C\.|LLP|Corp\.?|Corporation|Co\.|Ltd\.?|Limited|N\.A\.|L\.?P\.?|P\.?C\.?|PLLC)$", re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def slugs(cfg):
    """The run-together words a board config is addressed by (token, tenant, the employer's part of a host)."""
    out = []
    for k in ("token", "tenant", "slug", "sub", "ns"):
        v = str((cfg or {}).get(k) or "")
        if v and not _UUID.search(v):
            out.append(v)
    try:
        import company_add
        lab = company_add.host_label(cfg or {}, "")
        if lab:
            out.append(lab)
    except Exception:
        pass
    return [s for s in dict.fromkeys(_norm(x) for x in out) if len(s) >= 4 and not s.isdigit()]


def looks_like_code(name):
    try:
        import company_add
        return company_add.looks_like_code(name)
    except Exception:
        return not str(name or "").strip()


def is_slug(name, cfg=None):
    """A run-together address used as a name: "Cameronmitchell", "Installedbuildingproducts", "Brightviewhealth"."""
    n = str(name or "").strip()
    if " " in n or not re.fullmatch(r"[A-Za-z][a-z]+", n):
        return False
    low = n.lower()
    if len(low) >= 13 or (_VOWELLESS.search(low) and not re.search(r"[aeiouy]", low[-3:])):
        return True     # (five consonants in a row, ending in more: "Chordsdp"; not "Nordstrom")
    if any(low.endswith(w) and 3 <= len(low) - len(w) for w in BUSINESS_WORDS) and len(low) >= 9:
        return True
    return False


def poor(name, cfg=None):
    """Why this is not a name people can read ("" when it is fine): empty, placeholder, code, board-n, generic,
    code-prefix, inverted, slug."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n:
        return "empty"
    if re.match(r"Employer(?: in\b| \()", n):
        return "placeholder"
    if looks_like_code(n):
        return "code"
    if re.search(r"\(board \d+\)$", n, re.I):
        return "board-n"
    toks = n.split()
    if n.lower().strip(" .") in GENERIC or _generic_lead(toks):
        return "generic"
    if _lead_code(toks) and not _code_is_name(toks, cfg):
        return "code-prefix"
    if re.search(r"\b(?:of|for|of the)$", n, re.I):
        return "inverted"
    if is_slug(n, cfg):
        return "slug"
    return ""


# ---------------------------------------------------------------- cleaning without guessing
def _in_texts(phrase, texts):
    p = re.sub(r"\s+", " ", phrase).strip().lower()
    return bool(p) and any(p in t for t in texts)


def _code_is_name(toks, cfg):
    """The board's own address starts with the "code": it is the name ("C5MI Insight" at c5mi.wd1..., "A10 Networks")."""
    head = _norm(toks[0]) if toks else ""
    return len(head) >= 3 and any(x.startswith(head) for x in slugs(cfg))


def _lead_code(toks, texts=None):
    """How many leading tokens of a name are an entity / requisition code (0 = none). texts (lower-cased posting
    texts) settle the unclear ones: "10 Nationwide Children's" never appears in a posting, "Nationwide Children's"
    does; "84 Lumber" does."""
    if len(toks) < 2:
        return 0
    t = toks[0]
    bare = t.strip("()[]:#-")
    rest = " ".join(toks[1:])
    if len(re.sub(r"[^A-Za-z]", "", rest)) < 3:
        return 0
    if _KEEP_MIXED.match(bare):
        return 0
    two = " ".join(toks[:2])
    if texts and _in_texts(two, texts):
        return 0                                    # the postings use the name with its number: it is the name
    seen_rest = bool(texts) and _in_texts(" ".join(toks[1:3]), texts)
    if re.fullmatch(r"\([A-Za-z0-9 .\-]{1,8}\)", t):
        return 1                                    # "(5100) Genzyme", "(USA) Ecolab"
    if re.fullmatch(r"\d{2}-\d{7}", bare):
        return 1                                    # an EIN: "82-3070213 ServiceMac"
    if re.fullmatch(r"\d+", bare):
        if bare in _KEEP_NUM and not seen_rest:
            return 0
        return 1 if (len(bare) >= 3 or bare.startswith("0") or seen_rest or len(toks) >= 3) else 0
    if re.search(r"\d", bare) and re.search(r"[A-Za-z]", bare) and len(bare) >= 3 and re.fullmatch(r"[A-Za-z0-9\-_]+", bare) \
            and (bare.upper() == bare or re.fullmatch(r"[A-Za-z]{1,3}\d{2,}\w*", bare)):
        return 1                                    # "AB3 Nationwide Life", "5H0 Hub International", "W2B Skechers", "US10791-ALACUS"
    if re.fullmatch(r"[A-Z]{2,5}(?:-[A-Z]{2,3})?", bare):
        nxt = toks[1]
        if nxt == t:
            return 2 if len(toks) > 2 and not texts else 1          # "ISD ISD Renal"
        if len(bare) >= 3 and _norm(nxt).startswith(bare.lower()) and nxt != bare:
            return 1                                # "MCK McKesson", "CAR CarMax", "RXC RxCrossroads"
        if seen_rest and not _in_texts(two, texts):
            return 1                                # "KDS Kohl's": the postings say "Kohl's", never "KDS Kohl's"
    return 0


_INVERT = re.compile(r"^(.+?),?\s+((?:The\s+)?(?:Department|Dept\.?|Office|Bureau|Division|Board|Commission|University|College|City|County|"
                     r"State|Town|Village|Township|Ministry|Institute|Society|Association|Bank|Church|Diocese|Archdiocese|"
                     r"School District|Court|Library|Museum|Friends|House|Children's Hospital|Hospital|Home|Boys & Girls Clubs?|YMCA|"
                     r"Community Foundation|Chamber of Commerce|United Way|Humane Society|Girl Scouts|Boy Scouts|Port)\s+(?:of|for)(?:\s+the)?)$", re.I)


def clean_display(name, texts=None):
    """A display name with the parts that are not the name removed: a leading entity code ("0101 The Huntington
    National Bank", "(5100) Genzyme", "AB3 Nationwide Life"), a job-site word in front ("Jobs Selectmedicalcorp"),
    everything before "d/b/a", a comma-inverted agency name ("Juvenile Justice, Department of" -> "Department of
    Juvenile Justice"), "(board 2)". Real names keep their numbers ("7-Eleven", "3M", "1-800-Flowers", "84 Lumber").
    texts: lower-cased posting texts, when there are any, to settle unclear codes."""
    n = re.sub(r"\s+", " ", _html.unescape(str(name or ""))).strip(" ,;")
    if not n:
        return ""
    n = re.sub(r"\s*\((?:board \d+)\)$", "", n, flags=re.I)
    m = re.search(r"\b(?:d/b/a|dba|d\.b\.a\.|doing business as)\s+(.{2,})$", n, re.I)
    if m:
        n = m.group(1).strip()
    for _ in range(2):
        toks = n.split()
        k = _lead_code(toks, texts)
        if not k and _generic_lead(toks):
            k = 1
        if not k:
            break
        n = " ".join(toks[k:]).strip(" -:,")
    m = _INVERT.match(n)
    if m:
        n = f"{m.group(2)} {m.group(1)}".strip()
    m = re.match(r"^(.+?),\s*The$", n)
    if m:
        n = "The " + m.group(1)
    return n[:60].strip()


# ---------------------------------------------------------------- names from the board's page and the postings
GENERIC_TITLE = re.compile(r"(?i)^(careers?( (page|site|center|portal|opportunities))?|jobs?|job (opportunities|openings|board|listings?|search)|"
                           r"current (openings|opportunities)|open (positions|roles|jobs)|recruit(ment|ing)|bamboohr|dayforce( jobs)?|home|apply|"
                           r"employment( opportunities)?|work (with|for) us|join (us|our team)|search( results| jobs)?|welcome|"
                           r"candidate (portal|experience)|external|ultipro|ukg( pro)?|paylocity|adp|workforce now|icims|taleo|"
                           r"error|page not found|not found|access denied|sign in|log ?in|untitled|loading(\.\.\.)?|unavailable|.{0,2})$")


def name_from_title(title):
    """"Woodmans Inc - Job Opportunities" -> "Woodmans Inc"; "Careers at Acme" -> "Acme"; None for generic titles."""
    t = re.sub(r"\s+", " ", _html.unescape(title or "")).strip()
    for part in re.split(r"\s+[-|–—:·]\s+|\s*\|\s*", t):
        part = part.strip(" -|:")
        part = re.sub(r"(?i)^(careers?|jobs?|job openings|job opportunities|opportunities|employment|work|current openings) (at|with|@|for)\s+", "", part)
        part = re.sub(r"(?i)\s+(careers?( (page|site|center|portal))?|jobs?|job (openings|opportunities|board)|career opportunities|employment)$", "", part).strip()
        if len(part) >= 2 and not GENERIC_TITLE.match(part) and len(part) <= 80:
            return part
    return None


_TAIL_STOP = {"is", "are", "the", "we", "our", "a", "an", "and", "in", "at", "to", "for", "has", "was", "will", "offers", "careers",
              "team", "you", "your", "this", "job", "position", "equal", "eoe", "as", "with", "of", "on", "by", "or", "if", "it"}


def split_slug(slug, texts, min_share=0.0):
    """The way an employer's postings write a run-together address: "cameronmitchell" -> "Cameron Mitchell",
    "davita" -> "DaVita", "osuphysicians" -> "OSU Physicians". texts: the postings' text, case kept. None when the
    postings never write it (min_share: in at least this share of them)."""
    s = _norm(slug)
    if len(s) < 4 or not texts:
        return None
    rx = re.compile(r"(?<![A-Za-z0-9])" + r"[ \-.,'’]{0,2}".join(re.escape(ch) for ch in s) + r"(?![A-Za-z0-9])", re.I)
    seen, docs = collections.Counter(), 0
    for t in texts:
        found = set()
        for m in rx.finditer(t):
            v = re.sub(r"\s+", " ", m.group(0)).strip(" -.,'’")
            if v.islower() or "." in v[1:-1].replace(". ", ""):
                continue                            # an address (acme.com) or a lower-case mention says nothing about the name
            found.add(v)
        if found:
            docs += 1
        seen.update(found)
    if not seen or docs < max(1, min_share * len(texts)):
        return None
    best = max(seen.items(), key=lambda kv: (kv[1], " " in kv[0], sum(ch.isupper() for ch in kv[0])))[0]
    if best.isupper() and len(best) > 6:
        spaced = [v for v in seen if not v.isupper()]
        if spaced:
            best = max(spaced, key=lambda v: seen[v])
        else:
            best = best.title()
    return best[:60]


_NAME = r"((?:The[ \t]+)?[A-Z][A-Za-z0-9&'’.\-]*(?:[ \t]+(?:(?:of|the|and|for|at|de|&)[ \t]+){0,2}[A-Z][A-Za-z0-9&'’.\-]*){0,5})"
_MINE = [(3, re.compile(_NAME + r",?(?:\s+(?:Inc|LLC|Corp|Corporation|Company|Co)\.?)?,?\s+(?:\([^)]{1,30}\)\s+)?is\s+(?:an?|the|proud to be an?)\s+"
                               r"(?:equal|eeo|affirmative|e-verify|drug[- ]free|eoe)", 0)),
         (1, re.compile(r"(?:\bAbout|\bWhy(?: [Ww]ork (?:for|at))?|\bJoin(?: the)?|\bWelcome to|\bWorking at|\bWork at|\bCareers at|\bLife at|\bAt)\s+"
                        + _NAME + r"(?=[,.:!?\n]|\s+[a-z])", 0)),
         (1, re.compile(_NAME + r"\s+(?:is|are)\s+(?:seeking|looking for|hiring|currently|now hiring|a leading|one of|committed to|dedicated to|"
                                r"growing|an?\s+[\w\-]+(?:\s+[\w\-]+){0,3}\s+(?:company|provider|leader|organization|firm|bank|manufacturer|"
                                r"distributor|retailer|hospital|health system|nonprofit|non-profit|agency|practice|contractor|builder))", 0))]
_NOT_A_NAME = {"we", "us", "our", "you", "this", "the company", "company", "the", "job", "position", "the position", "the role", "role",
               "candidates", "applicants", "employer", "it", "they", "he", "she", "who", "what", "eoe", "equal opportunity employer",
               "our team", "our company", "the team", "this position", "this role", "this job", "the job", "this opportunity", "team",
               "united states", "america", "the opportunity", "the organization", "our organization", "the employer", "client",
               "our client", "the client", "candidate", "the candidate", "applicant", "management", "summary", "overview", "location",
               "description", "job description", "position summary", "job summary", "benefits", "responsibilities", "qualifications",
               "requirements", "duties", "compensation", "pay", "schedule", "hours", "shift", "department", "full time", "part time",
               "monday", "friday", "there", "here", "what you", "why you", "if you", "must", "safety", "experience", "education"}


def mine_name(texts, need=0.3):
    """The employer's name as its postings state it: "Acme Health is an equal opportunity employer", "About Acme
    Health", "Acme Health is seeking a ...". The same name must come up in at least `need` of the postings (and in
    two of them, or twice in the only one). Returns (name, share of postings) or (None, 0)."""
    texts = [t for t in texts if t and len(t) > 40]
    if not texts:
        return None, 0
    docs, forms = collections.Counter(), {}
    for t in texts:
        got = collections.Counter()
        for w, rx in _MINE:
            for m in rx.finditer(t[:12000]):
                v = re.sub(r"\s+", " ", m.group(1)).strip(" .,-'’")
                v = re.sub(r"^(?:About|Join|At|Why|Welcome to)\s+", "", v)
                v = LEGAL.sub("", v).strip(" .,")
                words = v.split()
                while words and words[-1].lower() in _TAIL_STOP:
                    words.pop()
                v = " ".join(words)
                k = v.lower()
                if len(v) < 3 or k in _NOT_A_NAME or k in GENERIC or re.fullmatch(r"[A-Z]?[a-z]{1,2}", v) or len(words) > 6:
                    continue
                if all(x.lower() in _NOT_A_NAME or x.lower() in _TAIL_STOP for x in words):
                    continue
                got[k] += w
                forms.setdefault(k, collections.Counter())[v] += 1
        for k, w in got.items():
            docs[k] += 1 + (0.5 if w >= 3 else 0)
    if not docs:
        return None, 0
    k, score = max(docs.items(), key=lambda kv: (kv[1], len(kv[0])))
    n_docs = sum(1 for t in texts if k in t.lower())
    share = n_docs / len(texts)
    if share < need or (n_docs < 2 and not (len(texts) == 1 and sum(forms[k].values()) >= 2)):
        return None, 0
    return forms[k].most_common(1)[0][0][:60], share


_PREFIX_STOP = {"all", "the", "our", "you", "your", "this", "that", "with", "will", "must", "able", "work", "team", "for", "and", "are",
                "job", "full", "part", "pay", "per", "may", "can", "any", "new", "one", "two", "who", "why", "how", "what", "when"}


def prefix_name(prefix, texts, need=0.1):
    """UKG addresses a board by a code that starts with the first three letters of the employer's name ("ALL1029AECR"
    is ALL Crane Rental, "ACE1005APMI" Ace Parking, "UNI1101UDFI" United Dairy Farmers). The capitalised phrase
    starting with those letters that most postings share is the name; None when there is no such phrase."""
    pre = re.sub(r"[^a-z]", "", str(prefix or "").lower())[:3]
    if len(pre) < 3 or not texts:
        return None
    rx = re.compile(r"(?<![A-Za-z0-9])((?i:" + re.escape(pre) + r")[A-Za-z'’]*(?:[ \t]+(?:(?:&|of|and)[ \t]+)?[A-Z][A-Za-z0-9&'’.\-]*){1,4})")
    docs, forms = collections.Counter(), {}
    for t in texts:
        found = set()
        for m in rx.finditer(t[:12000]):
            words = m.group(1).split()
            if not words[0][0].isupper():
                continue
            for k in range(2, len(words) + 1):
                if words[k - 1].lower() in ("of", "and", "&") or words[k - 1].lower() in _TAIL_STOP:
                    continue
                ph = " ".join(words[:k]).strip(" .,-")
                found.add(ph.lower())
                forms.setdefault(ph.lower(), collections.Counter())[ph] += 1
        docs.update(found)
    if not docs:
        return None
    two = {k: v for k, v in docs.items() if len(k.split()) == 2}
    if not two:
        return None
    base, n = max(two.items(), key=lambda kv: kv[1])
    if n < max(2, need * len(texts)) or (base.split()[0] in _PREFIX_STOP and n < 0.5 * len(texts)):
        return None
    best = base
    for k, v in sorted(docs.items(), key=lambda kv: len(kv[0])):
        if k.startswith(base + " ") and v >= 0.6 * n and len(k) > len(best):
            best = k
    form = forms[best].most_common(1)[0][0]
    return _tidy(form)[:60]


def ukg_prefix(cfg):
    m = re.match(r"([A-Za-z]{3})\d{3,}", str((cfg or {}).get("tenant") or "")) if (cfg or {}).get("ats") == "ukg" else None
    return m.group(1) if m else None


def split_business(slug):
    """Last resort for a run-together address nobody spells out: split a common business word off its end
    ("brightviewhealth" -> "Brightview Health", "cardinalgroup" -> "Cardinal Group"). None when none fits."""
    s = re.sub(r"[^a-z]", "", str(slug or "").lower())
    for _ in range(1):
        for w in sorted(BUSINESS_WORDS, key=len, reverse=True):
            if s.endswith(w) and len(s) - len(w) >= 3:
                head = s[:-len(w)]
                inner = split_business(head) if len(head) >= 9 else None
                first = inner or (head.upper() if len(head) <= 3 else head.capitalize())    # "odwlogistics" -> "ODW Logistics"
                return f"{first} {w.upper() if w in ('usa', 'llc') else w.capitalize()}"
    return None


def _initialism(short, long_name):
    words = [w for w in re.split(r"[\s\-]+", long_name) if w and w.lower() not in ("of", "the", "and", "for", "&")]
    ini = "".join(w[0] for w in words).lower()
    return len(short) >= 3 and (ini == short.lower() or ini.startswith(short.lower()))


def _tidy(n):
    n = LEGAL.sub("", n or "").strip(" ,.")
    if n.isupper() and len(re.sub(r"[^A-Z]", "", n)) > 5:
        n = " ".join(w if len(w) <= 3 and not re.search(r"[AEIOU]", w) else w.capitalize() for w in n.split())
    return n


def derive(name, cfg=None, texts=None, board_title=None, employer=None):
    """The best display name for a board, or None when nothing better than `name` is known.
    name: what it is called now ("" / a code / a slug / a legal entity). cfg: its board config (for its address).
    texts: its postings' text (titles + descriptions, case kept), as many as are at hand. board_title: its page title.
    employer: the employer / company field its postings carry, when the job system has one.
    A name that is already fine is left alone. Otherwise, best first: the employer field or the current name with its
    code taken off; the board's address as the postings spell it; the board page's title; the name the postings state;
    a common business word split off the address."""
    cfg = cfg or {}
    texts = [t for t in (texts or []) if t]
    low = [t.lower() for t in texts]
    cur = re.sub(r"\s+", " ", str(name or "")).strip()
    why = poor(cur, cfg)
    if not why:
        # a one-word name the postings write as two ("Microcenter" -> "Micro Center") or with other capitals
        if cur and " " not in cur and len(texts) >= 3:
            sp = split_slug(_norm(cur), texts, min_share=0.3)
            if sp and sp != cur and _norm(sp) == _norm(cur) and not poor(sp, cfg):
                return sp[:60]
        return None
    ok = lambda n: bool(n) and not poor(n, cfg) and n != cur
    keep = lambda n: n if not _code_is_name((n or "").split(), cfg) else None
    cleaned = [c for c in (_tidy(clean_display(employer or "", low)) if keep(employer) else _tidy(employer or ""),
                           clean_display(cur, low)) if ok(c)]
    sl = list(dict.fromkeys(slugs(cfg) + ([_norm(cur)] if is_slug(cur, cfg) else [])))
    spelled, strong = None, None
    for x in sl:
        spelled = spelled or split_slug(x, texts)
        strong = strong or (split_slug(x, texts, min_share=0.3) if len(texts) >= 3 else None)
    spelled = spelled if ok(spelled) else None
    strong = strong if ok(strong) else None
    title = _tidy(clean_display(name_from_title(board_title) or "", low)) if board_title else ""
    title = title if ok(title) else None
    if why == "code-prefix" and cleaned:
        # "ISD ISD Renal" (DaVita), "9111 Cellco Partnership" (Verizon): a legal entity nobody knows gives way to the
        # name the board's address and most of its postings agree on; "0101 The Huntington National Bank" stays
        if strong and _norm(strong) not in _norm(cleaned[0]) and len(_norm(strong)) >= 4:
            return strong[:60]
        if " " not in cleaned[0] and not texts:
            # nothing left but one word ("ISD ISD Renal" -> "Renal") and no postings to check it against: the board's
            # own address is the safer name ("davita" -> "Davita")
            for x in sl:
                if x.isalpha() and not is_slug(x.capitalize(), cfg) and x not in _norm(cleaned[0]):
                    return x.capitalize()[:60]
        return cleaned[0][:60]
    if why != "slug" and cleaned:
        return cleaned[0][:60]
    if spelled:
        return spelled[:60]
    if title:
        return title[:60]
    pn = prefix_name(ukg_prefix(cfg), texts) if ukg_prefix(cfg) else None
    if ok(pn):
        return pn[:60]
    mined, share = mine_name(texts)
    mined = _tidy(mined) if mined else mined
    if ok(mined) and (why != "slug" or share >= 0.5 or any(_norm(mined).startswith(x[:4]) or _initialism(x, mined) for x in sl)):
        return mined[:60]
    for x in sl:
        b = split_business(x)
        if ok(b):
            return b[:60]
    return None


# ---------------------------------------------------------------- the app: learn a name after the first fetch
SAMPLE = 60     # postings read for a name


def learn(company, board_title=None, log=lambda m: print(m, flush=True)):
    """After a fetch: give `company` a real name when the one it has is a code, a placeholder, a run-together address
    or a legal entity behind a code, using what its postings say. The company keeps its listing ids (so ratings,
    saved jobs and first-seen dates stay); a name the person typed is never changed. Returns the name it has now."""
    import json
    import catalog
    with catalog.db() as con:
        row = con.execute("SELECT cfg FROM companies WHERE name=?", (company,)).fetchone()
        if not row:
            return company
        cfg = json.loads(row["cfg"])
        if cfg.get("nm"):
            return company          # typed by the person, or already settled
        rows = con.execute("SELECT title, desc FROM listings WHERE company=? AND closed_at IS NULL AND desc IS NOT NULL AND desc<>'' "
                           "ORDER BY last_seen DESC LIMIT ?", (company, SAMPLE)).fetchall()
        n_all = con.execute("SELECT COUNT(*) FROM listings WHERE company=?", (company,)).fetchone()[0]
    if not n_all:
        return company              # nothing fetched yet: decide after a fetch that returned postings
    texts = [(r["title"] or "") + "\n" + (r["desc"] or "") for r in rows]
    new = derive(company, cfg, texts, board_title=board_title)
    new = (new or "").replace(",", "").strip()[:60]
    settled = bool(texts) or not poor(company, cfg)
    if new and new != company and not poor(new, cfg):
        final = new
        if not catalog.rename_company(company, final):
            final = f"{new[:44]} ({cfg.get('ats', '')})" if cfg.get("ats") else ""
            if not final or not catalog.rename_company(company, final):
                final = ""
        if final:
            log(f"  {company} is now called {final}")
            _follow_rename(company, final)
            company = final
    if settled:
        with catalog.db() as con:
            row = con.execute("SELECT cfg FROM companies WHERE name=?", (company,)).fetchone()
            if row:
                cfg = json.loads(row["cfg"])
                if not poor(company, cfg):      # (a name that is still a code is tried again after the next fetch)
                    cfg["nm"] = 1
                    con.execute("UPDATE companies SET cfg=? WHERE name=?", (json.dumps(cfg), company))
    return company


def _follow_rename(old, new):
    """Things kept by company name outside the catalog follow a rename: each person's employer-directory record
    (the order of the first check, the starters still to be checked)."""
    try:
        import directory
        with directory._APPLY:
            for pid in directory.users():
                rec = directory.record(pid)
                changed = False
                nn = rec.get("near_n")
                if isinstance(nn, dict) and old in nn:
                    nn[new] = nn.pop(old)
                    changed = True
                sp = rec.get("starters_pending")
                if isinstance(sp, list) and old in sp:
                    rec["starters_pending"] = sorted({new if x == old else x for x in sp})
                    changed = True
                if changed:
                    directory._save_record(pid, rec)
    except Exception:
        pass
