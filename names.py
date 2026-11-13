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
    display(name, cfg, taken)       the name a NEW company gets (no postings read yet), unique in a plain way
    unique_name(name, cfg, taken)   "Accenture (Avanade)", "Schneider (2)": never "(taleo)" or a hash
    group_name(name), group_map(companies)   the one name two boards of an employer are shown and grouped under
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
        if lab:     # ("careersapply-pennentertainment.icims.com": the job-site word is not part of the employer's address)
            out.append(" ".join(t for t in lab.split() if not _GENERIC_LEAD.match(t)) or lab)
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
    if len(low) >= 7 and any(low.endswith(w) and 1 <= len(low) - len(w) <= 2 for w in BUSINESS_WORDS + _JOB_TAIL):
        return True     # (a letter or two run into a business word: "Lbrands", "Lmhealth")
    if len(low) >= 8 and any(low.endswith(w) and len(low) - len(w) >= 3 for w in _JOB_TAIL):
        return True     # ("Bjakcareer", "Acmejobs")
    if len(low) >= 6 and re.search(r"(?:ww|hh|jj|kk|qq|vv|xx)$", low):
        return True     # (an abbreviation run into the name: "Craneww" is Crane Worldwide)
    return False


_JOB_TAIL = ("career", "careers", "jobs", "hiring", "hcm")


# ---------------------------------------------------------------- "(...)" after a name
# A second board of one employer is told apart by a plain place or brand in brackets ("McKesson (Canada)", "Abbott
# (Nutrition)", at worst "Schneider (2)"), never by a job system, a site code or a hash ("(taleo)", "(AccentureCareers)",
# "(1 BBW PROF)", "(ADP 6dd43f)", "(board 2)").
SYSTEMS = {"taleo", "workday", "myworkdayjobs", "adp", "adpworkforcenow", "workforcenow", "icims", "ukg", "ukgpro", "ukgready",
           "ultipro", "greenhouse", "lever", "ashby", "bamboohr", "paylocity", "dayforce", "paycom", "paycor", "saashr", "oracle",
           "careerssite", "careersite", "radancy", "eightfold", "avature", "recruitee", "breezy", "breezyhr", "jobvite",
           "smartrecruiters", "workable", "jazzhr", "successfactors", "phenom", "jsonld", "brassring", "kenexa", "jibe",
           "teamtailor", "pinpoint", "rippling", "gusto", "bullhorn", "personio", "applicantpro", "applitrack", "neogov",
           "governmentjobs", "cornerstone", "csod", "silkroad", "linkedin", "indeed", "careerbuilder", "equest", "glassdoor",
           "ziprecruiter", "monster", "handshake", "tmp", "symphonytalent"}
_JOB_WORDS = {"career", "careers", "careersite", "job", "jobs", "external", "internal", "site", "sites", "board", "boards", "portal",
              "page", "hotjob", "hotjobs", "search", "apply", "opportunities", "recruiting", "recruitment", "llc", "inc", "corp",
              "employer", "payroll"}
_JOB_ENDS = r"(?:careers?|careersite|jobs?|external|internal|hotjobs?)"
_COUNTRY = re.compile(r"(?i)^(?:u\.?s\.?(?:a\.?)?|united states(?: of america)?)$")
_CFG_CODES = ("site", "section", "token", "tenant", "slug", "sub", "ns", "board", "id", "cid", "key", "search")
_SHORT_PLAIN = {"US", "UK", "USA"}


def split_suffix(name):
    """("Accenture", "AccentureCareers") for "Accenture (AccentureCareers)"; (name, "") when it ends in no brackets."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    m = re.match(r"^(.*?[^\s(])\s*\(([^()]*)\)$", n)
    return (m.group(1).strip(" ,-"), m.group(2).strip()) if m and m.group(1).strip(" ,-") else (n, "")


def _code_words(code):
    """The words in a site code: "Main_Event_Careers" -> Main Event Careers, "AvanadeCareers" -> Avanade Careers,
    "salescareers" -> sales."""
    s = re.sub(r"[_\-./]+", " ", str(code or ""))
    s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    out = []
    for w in s.split():
        prev = None
        while prev != w and (w.islower() or w.istitle()):       # run-together: job words come off its ends
            prev = w
            w = re.sub(r"(?i)^" + _JOB_ENDS + r"(?=[a-z]{3})|(?<=[a-z]{2})" + _JOB_ENDS + r"$", "", w)
        out.append(w)
    return out


def plain_suffix(code, base="", acronyms=False):
    """The plain words in a site code / search phrase that tell a board apart from the employer's other one:
    "AvanadeCareers" -> "Avanade", "Main_Event_Careers" -> "Main Event", "lisle" -> "Lisle", "salescareers" -> "Sales",
    "Accenture Federal Services" (for Accenture) -> "Federal Services". "" when the code says nothing in plain words
    ("AccentureCareers" for Accenture, "1_BBW_PROF", "abbottcareers2", "7", "taleo", a GUID). acronyms: let a short
    all-capitals word through ("CSI")."""
    code = str(code or "").strip()
    if not code or len(code) > 60 or _norm(code) in SYSTEMS or _UUID.search(code) or re.search(r"\d", code):
        return ""
    nb = _norm(base)
    ini = "".join(w[0] for w in re.split(r"[\s\-]+", str(base or "")) if w and w[0].isalpha()).lower()
    out = []
    for w in _code_words(code):
        lw = w.lower()
        if lw in _JOB_WORDS or len(w) < 2 or (len(lw) >= 2 and lw in nb) or (len(lw) >= 3 and lw == ini):
            continue
        if w in _SHORT_PLAIN:
            out.append(w)
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z'&]*", w) or len(w) < 3 or not re.search(r"[aeiouy]", lw):
            return ""
        if w.isupper() and len(w) <= 4:
            if not acronyms:
                return ""
            out.append(w)
            continue
        if is_slug(w.capitalize()):
            sp = split_business(lw)
            if not sp:
                return ""
            out.append(sp)
            continue
        if _unsayable(lw):
            return ""
        out.append(w.capitalize() if (w.islower() or w.isupper()) else w)
    s = " ".join(out)
    return s if out and len(s) <= 24 and len(out) <= 3 and not _COUNTRY.match(s) else ""


def _bad_suffix(suf, base="", cfg=None, strict=False):
    """Is the "(...)" after a name a job system, a site code or a hash, rather than a plain place or brand?
    strict: only what Siftwell or the directory wrote there itself (the system, "board 2", this board's own codes)."""
    cfg = cfg or {}
    ns = _norm(suf)
    if not ns:
        return True
    if re.fullmatch(r"\d{1,3}", suf.strip()):
        return False                                # "(2)": Siftwell's own last resort
    if re.fullmatch(r"[\d\- ]{4,}", suf.strip()):
        return True                                 # "Wawa Inc. (210515330)": a ledger number
    if re.fullmatch(r"(?i)board \d+", suf.strip()) or ns in SYSTEMS or ns == _norm(cfg.get("ats")):
        return True
    toks = suf.split()
    if len(toks) >= 2 and re.fullmatch(r"[0-9a-f]{4,8}", toks[-1].lower()) and (re.search(r"\d", toks[-1]) or _norm(" ".join(toks[:-1])) in SYSTEMS):
        return True                                 # "ADP 6dd43f", "UKG Ready 0a1b2c"
    for k in _CFG_CODES:
        v = str(cfg.get(k) or "")
        if v and _norm(v) == ns:
            return suf != plain_suffix(v, base)
    if strict:
        return False
    if _COUNTRY.match(suf.strip()):
        return True                                 # "HD Supply Management LLC (USA)"
    if re.search(r"\d", suf) and re.search(r"[A-Za-z]", suf) and " " not in suf.strip():
        return True                                 # "abbottcareers2"
    if any(w.lower() in _JOB_WORDS - {"llc", "inc", "corp", "board", "boards"} for w in _code_words(suf)):
        return True                                 # "BJsCareers", "External Career ASE", "bpcareers"
    if " " not in suf.strip() and (suf.islower() or (len(suf) >= 12 and re.search(r"[a-z][A-Z]", suf))):
        return True                                 # "maymonthomes", "BeltoneIndependentlyOwned"
    return False


# ---------------------------------------------------------------- slogans and unreadable abbreviations
_SLOGAN = re.compile(r"(?i)(?<![\w&])(?:you|you['’]ll|you['’]re|you['’]ve|your|yours|we['’]re|we['’]ll|let['’]s)(?!\w)")
_SLOGAN2 = re.compile(r"(?i)^(?:join|work|grow|build|start|find|discover|explore|make|love|come|search|view|apply|welcome|be)\b.*"
                      r"\b(?:us|team|careers?|future|here|today|now|difference|family|jobs?|journey|story)$")
_OK_VOWELLESS = {"mfg", "bldg", "mgmt", "intl", "natl", "assn", "dept", "svc", "ctr", "grp", "hwy", "blvd", "ltd", "pty", "plc", "llc",
                 "llp", "pllc", "dds", "phd", "mrs", "pvt", "dba", "std", "hts", "sts", "spc", "nw", "sw"}
_ENTITY_ABBR = {"appl", "emp", "svcs", "hldgs", "hldg", "opco", "holdco"}
_OK_CODA = {"sch", "tch", "ght", "xth", "fth", "gth", "dth", "pth", "cht", "hth", "chs", "phs", "ths", "ckl", "ghs"}


def _slogan(n):
    """A page's tag line used as a name: "You'll Love It Here", "Join Our Team", "Find Your Future"."""
    words = n.split()
    if len(words) < 3:
        return False                                # ("Your Pie" is a restaurant)
    return bool(_SLOGAN.search(n) or _SLOGAN2.match(n))


def _unsayable(w, coda=True):
    """A short word nobody can say: no vowel ("wvnh", "ghc"), or (coda) an ending no English word has ("copcp")."""
    w = str(w or "").lower()
    if not re.fullmatch(r"[a-z]{3,6}", w):
        return False
    if not re.search(r"[aeiouy]", w):
        return w not in _OK_VOWELLESS
    if not coda:
        return False
    w = w[:-1] if w.endswith("s") and not w.endswith("ss") else w
    m = re.search(r"[^aeiouy]{3,}$", w)
    if not m:
        return False
    end = m.group(0)[-3:]
    return end[0] not in "rlnmsw" and end not in _OK_CODA and end[1] != end[2]


def _abbrev(n):
    """A name made of initials written like words ("Copcp", "Hntb", "Wve Wvnh Emp") or of a ledger's abbreviations
    ("BOK USA Bio-Med Appl of Oklahoma")."""
    toks = [t.strip(".,") for t in n.split()]
    if any(t.lower() in _ENTITY_ABBR for t in toks):
        return True
    return any(re.fullmatch(r"[A-Z][a-z]{2,5}", t) and _unsayable(t, coda=len(toks) == 1) for t in toks)


def _upper_abbrev(n, cfg=None):
    """Initials written as initials: "Hntb" -> "HNTB", "Copcp" -> "COPCP", "Cvs Health" -> "CVS Health", and the
    board's own short address ("Hpe" at hpe.wd5 -> "HPE")."""
    toks = n.split()
    if len(toks) == 1 and _short_code(n, cfg):
        return n.upper()
    return " ".join(t.upper() if re.fullmatch(r"[A-Z][a-z]{2,4}", t) and _unsayable(t, coda=len(toks) == 1) else t for t in toks)


def poor(name, cfg=None):
    """Why this is not a name people can read ("" when it is fine): empty, placeholder, code, board-n, suffix,
    generic, slogan, code-prefix, inverted, slug, abbrev. A plain "(place or brand)" after a name is fine; the name
    in front of it is judged."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n:
        return "empty"
    if re.match(r"Employer(?: in\b| \(|$)", n):
        return "placeholder"
    base, suf = split_suffix(n)
    if suf:
        if re.fullmatch(r"board \d+", suf, re.I):
            return "code" if looks_like_code(base) else "board-n"
        if _bad_suffix(suf, base, cfg):
            return "suffix"
        if re.search(r"\(" + re.escape(suf) + r"\)$", base):
            return "suffix"                         # "Comfort Systems USA (Ohio) (Ohio)"
        n = base
    if looks_like_code(n):
        return "code"
    toks = n.split()
    if n.lower().strip(" .") in GENERIC or _generic_lead(toks):
        return "generic"
    if strip_country(n) != n:
        return "country"
    if strip_job_tail(n) != n:
        return "generic"
    if complete_truncated(n) != n:
        return "truncated"
    if _short_code(n, cfg):
        return "abbrev"
    if _slogan(n):
        return "slogan"
    if _lead_code(toks) and not _code_is_name(toks, cfg):
        return "code-prefix"
    if re.search(r"\b(?:of|for|of the)$", n, re.I):
        return "inverted"
    if is_slug(n, cfg):
        return "slug"
    if _abbrev(n):
        return "abbrev"
    return ""


# ---------------------------------------------------------------- cleaning without guessing
def _in_texts(phrase, texts):
    p = re.sub(r"\s+", " ", phrase).strip().lower()
    return bool(p) and any(p in t for t in texts)


def _code_is_name(toks, cfg):
    """The board's own address starts with the "code": it is the name ("C5MI Insight" at c5mi.wd1..., "A10 Networks").
    Not when the next word starts with the same letters: "MCK McKesson" at mckesson.wd3 is a ledger code in front."""
    head = _norm(toks[0]) if toks else ""
    if len(toks) > 1 and _norm(toks[1]).startswith(head) and _norm(toks[1]) != head:
        return False
    return len(head) >= 3 and any(x.startswith(head) for x in slugs(cfg))


_CTRY_TAIL = re.compile(r"(?i)[,\s]+(?:united states(?: of america)?|u\.s\.a\.?|u\.s\.?|usa|us)$")


def strip_country(n):
    """"ICR United States USA" -> "ICR", "Acme Corp, United States" -> "Acme Corp": a country tacked on behind the name
    (a ledger's way of naming the US entity). One plain "USA" stays ("Comfort Systems USA", "T-Mobile USA")."""
    n = str(n or "").strip()
    if not (re.search(r"(?i)\bunited states\b", n) or re.search(r"(?i)\b(?:usa|us|u\.s\.a?\.?)[,\s]+(?:usa|us|u\.s\.a?\.?)$", n)):
        return n
    prev = None
    while prev != n:
        prev = n
        m = _CTRY_TAIL.search(n)
        if m and len(re.sub(r"[^A-Za-z]", "", n[:m.start()])) >= 2:
            n = n[:m.start()].strip(" ,-")
    return n


_JOB_TAIL_RX = re.compile(r"(?i)[\s,\-|:]+(?:careers?(?: (?:site|page|portal|center))?|jobs|job openings|job board|human resources|hr|"
                          r"talent acquisition|recruiting|recruitment|hiring|now hiring|employment(?: opportunities)?|opportunities)$")


def strip_job_tail(n):
    """"Clearsulting Careers" -> "Clearsulting", "Anomatic Human Resources" -> "Anomatic": the job board's own words behind
    the employer's name. Kept when they are the whole name or part of it ("Jobs for the Future", "Human Resources
    Department of X" do not end that way; "Career Education Corp" neither)."""
    n = str(n or "").strip()
    m = _JOB_TAIL_RX.search(n)
    if not m:
        return n
    head = n[:m.start()].strip(" ,-|:")
    if len(re.sub(r"[^A-Za-z]", "", head)) < 2 or head.lower() in GENERIC or re.search(r"(?i)\b(?:of|for|and|&)$", head):
        return n
    return head


_TRUNC_WORDS = sorted(set(BUSINESS_WORDS) | {"services", "service", "advisory", "association", "administration", "department",
                                             "corporation", "incorporated", "laboratories", "pharmaceuticals", "communications",
                                             "certified", "operations", "operating", "partnership", "behavioral", "physicians"}
                      - {"careers", "jobs", "inc", "llc", "corp", "usa"}, key=len)
# real words a name can end in that start like a business word ("Primary Care", "Senior Life")
_WHOLE_WORDS = {"care", "home", "life", "land", "park", "bank", "art", "law", "lab", "med", "pro", "tech", "trans", "sun", "con",
                "com", "net", "new", "first", "fed", "con", "eco", "bio", "ins", "inter", "auto", "air", "all", "one", "west",
                "east", "north", "south", "fin", "cap", "res", "pharm", "health", "hosp", "food", "stores", "mart", "con"}


def complete_truncated(n):
    """A legal-entity name a ledger cut off in the middle of its last word ("PricewaterhouseCoopers Advisory Ser",
    "CenterWell Certified Healt"): the last word finished when only business words start that way ("Services",
    "Health"). Only for long names (cut-off fields are long; "Acme Home" is left alone)."""
    orig = n
    n = re.sub(r"\s+", " ", str(n or "")).strip(" ,.")
    m = re.match(r"^(.+\S)\s+([A-Za-z]{3,})$", n)
    if not m or len(n) < 24 or len(m.group(1).split()) < 2:
        return orig
    w = m.group(2).lower()
    if w in ("inc", "corp", "ltd", "llc", "llp", "pllc", "plc", "co", "lp"):
        return orig
    if w in _TRUNC_WORDS or w in _WHOLE_WORDS or w + "s" in _TRUNC_WORDS or w + "es" in _TRUNC_WORDS:   # ("Health System")
        return orig
    comp = [x for x in _TRUNC_WORDS if x.startswith(w) and len(x) > len(w)]
    if not comp:
        return orig
    c = comp[0] + "s" if comp[0] + "s" in comp else comp[0]     # ("Ser" -> "Services": a ledger's entity names are plural)
    return f"{m.group(1)} {c.upper() if m.group(2).isupper() else c.capitalize()}"


def _short_code(n, cfg):
    """A name that is the board's own two-to-four-letter address written like a word: "Rbc", "Hpe", "Vsp" (rbc.wd3 ...),
    which people write as initials. Not a word-like one ("Gap", "Box", "Nike")."""
    if not re.fullmatch(r"[A-Z][a-z]{1,3}", n or ""):
        return False
    low = n.lower()
    raw = {str((cfg or {}).get(k) or "").lower() for k in ("token", "tenant", "slug", "sub", "ns")}
    try:
        import company_add
        raw.add(_norm(company_add.host_label(cfg or {}, "")))
    except Exception:
        pass
    if low not in raw:
        return False
    if len(low) == 4:
        return _unsayable(low)
    # (three letters: initials unless a word-like one: "Gap", "Box"; "Aon" with two vowels)
    return len(low) == 2 or not (re.fullmatch(r"[bcdfghjklmnpqrstvwxz][aeiou][bcdfghjklmnpqrstvwxz]", low) or len(re.findall(r"[aeiou]", low)) >= 2)


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


def clean_display(name, texts=None, cfg=None):
    """A display name with the parts that are not the name removed: a leading entity code ("0101 The Huntington
    National Bank", "(5100) Genzyme", "AB3 Nationwide Life"), a job-site word in front ("Jobs Selectmedicalcorp"),
    everything before "d/b/a", a comma-inverted agency name ("Juvenile Justice, Department of" -> "Department of
    Juvenile Justice"), "(board 2)" and any other job-system / site-code in brackets at the end ("(taleo)",
    "(AccentureCareers)"; cfg: the board's config, so its own codes are recognised). Real names keep their numbers
    ("7-Eleven", "3M", "1-800-Flowers", "84 Lumber") and a plain place or brand in brackets ("(Canada)").
    texts: lower-cased posting texts, when there are any, to settle unclear codes."""
    n = re.sub(r"\s+", " ", _html.unescape(str(name or ""))).strip(" ,;")
    if not n:
        return ""
    n = re.sub(r"\s*\((?:board \d+)\)$", "", n, flags=re.I)
    for _ in range(3):
        base, suf = split_suffix(n)
        if not suf or not (_bad_suffix(suf, base, cfg) or re.search(r"\(" + re.escape(suf) + r"\)$", base)):
            break
        n = LEGAL.sub("", base).strip(" ,.") if _COUNTRY.match(suf) and LEGAL.search(base) else base
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
    n = complete_truncated(strip_job_tail(strip_country(n)))
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


def prefix_name(prefix, texts, need=0.1, tail=None):
    """UKG addresses a board by a code that starts with the first three letters of the employer's name ("ALL1029AECR"
    is ALL Crane Rental, "ACE1005APMI" Ace Parking, "UNI1101UDFI" United Dairy Farmers). The capitalised phrase
    starting with those letters that most postings share is the name; None when there is no such phrase. tail: the
    letters at the end of the code ("CRWL"), which follow the name's initials (Crane WorldWide Logistics): a phrase
    whose initials don't ("Crane SOPs") is not the name."""
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
    tl = re.sub(r"[^a-z]", "", str(tail or "").lower())
    if len(tl) >= 2:
        def fits(ph):
            return all(w[0] in tl for w in ph.split()[1:] if w not in ("of", "and", "&", "the"))
        docs = collections.Counter({k: v for k, v in docs.items() if fits(k)})
    if not docs:
        return None
    two = {k: v for k, v in docs.items() if len([w for w in k.split() if w not in ("of", "and", "&")]) == 2}   # ("Volunteers of America")
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


def ukg_tail(cfg):
    m = re.match(r"[A-Za-z]{3}\d{3,}([A-Za-z]{2,})$", str((cfg or {}).get("tenant") or "")) if (cfg or {}).get("ats") == "ukg" else None
    return m.group(1) if m else None


def ukg_prefix(cfg):
    m = re.match(r"([A-Za-z]{3})\d{3,}", str((cfg or {}).get("tenant") or "")) if (cfg or {}).get("ats") == "ukg" else None
    return m.group(1) if m else None


_SPLIT_MORE = ("entertainment", "care")     # (split off an address like BUSINESS_WORDS, but no sign of a run-together name)


def split_business(slug):
    """Last resort for a run-together address nobody spells out: split a common business word off its end
    ("brightviewhealth" -> "Brightview Health", "cardinalgroup" -> "Cardinal Group"). None when none fits."""
    s = re.sub(r"[^a-z]", "", str(slug or "").lower())
    for _ in range(1):
        for w in sorted(BUSINESS_WORDS + _SPLIT_MORE, key=len, reverse=True):
            if s.endswith(w) and len(s) - len(w) >= 3:
                head = s[:-len(w)]
                inner = split_business(head) if len(head) >= 9 else None
                if w == "care" and not inner:
                    continue                        # ("communicare" is one word; "freseniusmedical" + "care" is two)
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
    base, suf = split_suffix(cur)
    if suf and why in ("suffix", "board-n", "code") and why != "placeholder":
        # the brackets are a job system / site code, not part of the name: the name without them, made better if it can be
        b = clean_display(cur, [t.lower() for t in texts], cfg)
        if b and b != cur:
            return derive(b, cfg, texts, board_title, employer) or b
    elif suf and why != "placeholder":
        d = derive(base, cfg, texts, board_title, employer)     # a plain "(place)" stays on the better name
        return f"{d[:44]} ({suf})" if d else None
    if not why:
        # a one-word name the postings write as two ("Microcenter" -> "Micro Center") or with other capitals
        if cur and " " not in cur and len(texts) >= 3:
            sp = split_slug(_norm(cur), texts, min_share=0.3)
            # (not for a curly apostrophe instead of a straight one: "Lowe's" stays as it is)
            if sp and sp.replace("’", "'") != cur.replace("’", "'") and _norm(sp) == _norm(cur) and not poor(sp, cfg):
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
    if why in ("abbrev", "slogan"):
        # "Wve Wvnh Emp" (a ledger entity at communicarehealth), "You'll Love It Here" (a page's tag line), "Copcp":
        # what the postings and the board's own address say, else the initials written as initials
        if strong or spelled or title:
            return (strong or spelled or title)[:60]
        pn = prefix_name(ukg_prefix(cfg), texts, tail=ukg_tail(cfg)) if ukg_prefix(cfg) else None
        if ok(pn):
            return pn[:60]
        mined, share = mine_name(texts)
        mined = _tidy(mined) if mined else mined
        if ok(mined) and (share >= 0.5 or any(_norm(mined).startswith(x[:4]) or _initialism(x, mined) for x in sl)):
            return mined[:60]
        words = [_norm(t) for t in cur.split() if len(_norm(t)) >= 3]
        for x in sl:
            if x.isalpha() and not any(w in x for w in words):
                b = split_business(x)
                if ok(b):
                    return b[:60]
                if why == "slogan" and ok(x.capitalize()):
                    return x.capitalize()[:60]
        up = _upper_abbrev(cur, cfg)
        return up[:60] if ok(up) else None
    if why != "slug" and cleaned:
        return cleaned[0][:60]
    if spelled:
        return spelled[:60]
    if title:
        return title[:60]
    pn = prefix_name(ukg_prefix(cfg), texts, tail=ukg_tail(cfg)) if ukg_prefix(cfg) else None
    if ok(pn):
        return pn[:60]
    mined, share = mine_name(texts)
    mined = _tidy(mined) if mined else mined
    if ok(mined) and (why != "slug" or share >= 0.5 or any(_norm(mined).startswith(x[:4]) or _initialism(x, mined) for x in sl)):
        return mined[:60]
    for x in sorted(sl, key=lambda x: x != _norm(cur)):     # (the name's own run-together form before the board's address)
        b = split_business(x)
        if ok(b):
            return b[:60]
    for x in sl:        # a job-site word run into the address: "bjakcareer" -> "Bjak"
        m = re.fullmatch(r"([a-z]{3,})(?:careers?|jobs|hiring)", x)
        if m and ok(m.group(1).capitalize()):
            return m.group(1).capitalize()[:60]
    return None


# ---------------------------------------------------------------- one employer, two boards
_ENTITY_WORDS = {"laboratories", "labs", "inc", "incorporated", "corp", "corporation", "company", "co", "companies", "group", "holdings",
                 "usa", "us", "america", "americas", "international", "global", "worldwide", "enterprises", "industries", "llc", "lp",
                 "ltd", "limited", "stores", "brands", "the"}


def group_name(name):
    """The name a board is shown and grouped under on the job board: its catalog name without the "(...)" that tells
    two boards of one employer apart. "McKesson (Canada)" and "McKesson" -> "McKesson"."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    for _ in range(3):
        base, suf = split_suffix(n)
        if not suf:
            break
        n = base
    return n or str(name or "").strip()


def _owner(c):
    """Whose job system account a board is on (two boards on one account belong together when their names agree)."""
    if not isinstance(c, dict):
        return None
    for k in ("tenant", "host", "base", "token", "slug", "sub", "ns"):
        v = str(c.get(k) or "").lower()
        if v and not any(v == s or v.endswith("." + s) for s in ("recruiting.ultipro.com", "recruiting2.ultipro.com")):
            v = re.sub(r"^https?://(?:www\.)?(?:careers?|jobs?)[\-.]", "", v)
            return (c.get("ats"), re.sub(r"\d+$", "", v) if k == "token" else v)
    return None


_SHARED_SUFFIXES = ("icims.com", "taleo.net", "ultipro.com", "ukg.net", "saashr.com", "oraclecloud.com", "myworkdayjobs.com",
                    "paylocity.com", "adp.com", "dayforcehcm.com", "paycomonline.net", "greenhouse.io", "lever.co", "ashbyhq.com",
                    "workable.com", "bamboohr.com", "applytojob.com", "breezy.hr", "recruitee.com", "rippling.com",
                    "smartrecruiters.com", "applitrack.com", "schoolspring.com", "jobvite.com", "successfactors.com",
                    "avature.net", "eightfold.ai", "phenompeople.com", "clearcompany.com", "brassring.com", "jibeapply.com")


def employer_domain(c):
    """The employer's own web domain a board lives on ("careers.mckesson.com" -> "mckesson.com"), or "" for a board on
    a job system's shared host (most of them: those are told apart by name)."""
    if not isinstance(c, dict):
        return ""
    import urllib.parse
    for k in ("domain", "host", "base", "list_url", "sitemap"):
        v = str(c.get(k) or "")
        if not v:
            continue
        h = urllib.parse.urlsplit(v if "//" in v else "https://" + v).netloc.lower().split(":")[0].strip(".")
        if not h or "." not in h or any(h == s or h.endswith("." + s) for s in _SHARED_SUFFIXES):
            continue
        labs = h.split(".")
        if len(labs) >= 3 and labs[-2] in ("co", "com", "org", "net", "gov", "edu", "k12", "ac"):
            return ".".join(labs[-3:])
        return ".".join(labs[-2:])
    return ""


def groups(companies):
    """{catalog name: (group key, the one name its jobs are shown and grouped under)}. companies: catalog.companies()
    (or plain names). Boards of one employer share a group: the same name once job-system brackets, "(2)" and legal
    words are set aside ("McKesson" + "McKesson (2)", "TransPerfect" + "Transperfect (Workday)", "Odwlogistics" +
    "ODW Logistics (2)"); the same employer domain ("careers.acme.com" and "jobs.acme.com"); and, on one job-system
    account, a name that only adds words like Laboratories / Inc / Group / USA ("Abbott" + "Abbott Laboratories", never
    "Accenture" + "Accenture Federal Services"). The key ("g:mckesson") depends only on the names and boards, so it is
    the same on every page and after every rebuild while they stay the same."""
    items = [(c["name"], c) if isinstance(c, dict) else (str(c), None) for c in companies or [] if c]
    key = lambda g: _norm(re.sub(r"(?i)^the\s+", "", LEGAL.sub("", g)))
    buckets = {}
    for name, c in items:
        g = group_name(name)
        buckets.setdefault(key(g) or g.lower(), []).append((name, g, c))
    # one employer domain = one employer (a union of the buckets that share it)
    parent = {k: k for k in buckets}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    by_dom = {}
    for k, v in buckets.items():
        for _, _, c in v:
            d = employer_domain(c)
            if d:
                if d in by_dom and find(by_dom[d]) != find(k):
                    a, b = sorted((find(by_dom[d]), find(k)))
                    parent[b] = a
                by_dom.setdefault(d, k)
    merged = {}
    for k in buckets:
        merged.setdefault(find(k), []).extend(buckets[k])
    buckets = merged
    bare = lambda g: re.sub(r"(?i)^the\s+", "", g)
    best = lambda forms: max(forms, key=lambda g: (not poor(g), " " in bare(g), any(ch.isupper() for ch in bare(g)[1:]) and not g.isupper(), -len(g), g))
    shown = {k: best([g for _, g, _ in v]) for k, v in buckets.items()}
    owners = {k: {o for o in (_owner(c) for _, _, c in v) if o} for k, v in buckets.items()}
    target = {k: k for k in buckets}
    for k in sorted(buckets, key=len, reverse=True):
        words = [w for w in re.split(r"[^a-z0-9]+", re.sub(r"['’.]", "", shown[k].lower())) if w]
        for cut in range(1, len(words)):
            short = "".join(words[:cut])
            if short in buckets and short != k and all(w in _ENTITY_WORDS for w in words[cut:]) and owners[k] & owners[short]:
                shown[k], target[k] = shown[short], target[short]
                break
    out = {}
    for k, v in buckets.items():
        t = target[k]
        while target[t] != t:
            t = target[t]
        gk = "g:" + (key(shown[t]) or shown[t].lower())
        for name, _, _ in v:
            out[name] = (gk, shown[k])
    return out


def group_map(companies):
    """{catalog name: the one name its jobs are shown and grouped under} (see groups)."""
    return {n: g[1] for n, g in groups(companies).items()}


def group_keys(companies):
    """{catalog name: its group key} (see groups): boards with the same key are one employer."""
    return {n: g[0] for n, g in groups(companies).items()}


def _main_place(locs):
    """The one town most of a board's postings are in ("" when they are spread out): a plain way to tell it apart."""
    import json
    seen, n = collections.Counter(), 0
    for raw in locs or []:
        try:
            v = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("[") else raw
        except ValueError:
            v = raw
        first = (v[0] if isinstance(v, (list, tuple)) and v else v if isinstance(v, str) else "") or ""
        city = str(first).split(",")[0].strip()
        n += 1
        if re.fullmatch(r"[A-Z][A-Za-z .'\-]{2,23}", city) and city.lower() not in ("remote", "united states", "multiple locations", "various"):
            seen[city] += 1
    if not seen:
        return ""
    city, k = seen.most_common(1)[0]
    return city if k * 2 >= n else ""


def suffix_options(cfg, base, place=""):
    """Plain ways to tell this board from the employer's other one, best first: a brand or section word from its own
    address ("Avanade", "Main Event", "Lisle"), the town most of its jobs are in."""
    cfg = cfg or {}
    out = [plain_suffix(cfg.get(k), base) for k in ("search", "site", "section", "token", "slug", "sub", "ns")]
    try:
        import company_add
        out.append(plain_suffix(company_add.host_label(cfg, ""), base))
    except Exception:
        pass
    if place and _norm(place) not in _norm(base):
        out.append(re.sub(r"[(),]", "", place).strip()[:24])
    return [s for s in dict.fromkeys(out) if s]


def unique_name(name, cfg=None, taken=(), place=""):
    """`name` when no other company has it (taken: the names in use, any case), else the name with a plain "(...)":
    a brand, section or place, at worst "(2)". Never a job system or a hash."""
    name = re.sub(r"\s+", " ", str(name or "").replace(",", "").replace("::", " ")).strip()[:60]
    low = {str(t).lower() for t in taken}
    if name.lower() not in low:
        return name
    base = group_name(name)
    for s in suffix_options(cfg, base, place):
        c = f"{base[:44]} ({s})"
        if c.lower() not in low:
            return c
    for i in range(2, 1000):
        c = f"{base[:52]} ({i})"
        if c.lower() not in low:
            return c
    return name


def plain_placeholder(name, place=""):
    """"Employer in Columbus OH (ADP 6dd43f)" -> "Employer in Columbus OH": the last resort, without the job system and
    the hash. place: used when the placeholder names none ("Employer (Paylocity 6997ff)" -> "Employer in Dublin")."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    m = re.match(r"^(Employer(?: in [^()]+?)?)\s*(?:\(.*\))?$", n)
    if not m:
        return n
    n = m.group(1).replace(",", "").strip()
    return f"Employer in {place}" if n == "Employer" and place else n


def display(name, cfg=None, taken=(), where=""):
    """The name a NEW company gets before any of its postings were read (the directory's name for it, a careers
    link's): codes and job-system brackets off, a run-together address split, a placeholder without its hash, and
    unique among `taken` in a plain way. "Accenture (AccentureCareers)" -> "Accenture"."""
    n = re.sub(r"\s+", " ", str(name or "").replace(",", "")).strip()
    d = derive(n, cfg)
    if d and (not poor(d, cfg) or poor(n, cfg) in ("suffix", "board-n")):
        n = d
    if poor(n, cfg) == "placeholder":
        n = plain_placeholder(n, re.sub(r"[(),]", "", where or "").strip())
    return unique_name(n, cfg, taken)


# ---------------------------------------------------------------- the app: learn a name after the first fetch
SAMPLE = 60     # postings read for a name


def learn(company, board_title=None, log=lambda m: print(m, flush=True)):
    """After a fetch: give `company` a real name when the one it has is a code, a placeholder, a run-together address,
    a slogan, initials or a legal entity behind a code, using what its postings say; and take a job-system / site-code
    "(...)" off it. When the better name is taken by the employer's other board, it gets a plain "(brand / place)",
    at worst "(2)". The company keeps its listing ids (so ratings, saved jobs and first-seen dates stay); a name the
    person typed is never changed. Running it again changes nothing. Returns the name it has now."""
    import json
    import catalog
    with catalog.db() as con:
        row = con.execute("SELECT cfg FROM companies WHERE name=?", (company,)).fetchone()
        if not row:
            return company
        cfg = json.loads(row["cfg"])
        base, suf = split_suffix(company)
        placeholder = poor(company, cfg) == "placeholder"
        badsuf = bool(suf) and (_bad_suffix(suf, base, cfg) or bool(re.search(r"\(" + re.escape(suf) + r"\)$", base)))
        machine = bool(suf) and _bad_suffix(suf, base, cfg, strict=True)    # (Siftwell or the directory wrote it, not a person)
        # settled by Siftwell, not typed by a person (nm 2; before, nm 1 on a company the directory added): looked at
        # again when today's rules find the name poor ("Craneww" was taken for a name by an older version)
        by_us = cfg.get("nm") == 2 or (cfg.get("nm") == 1 and ("dir" in cfg or cfg.get("sector") in ("Siftwell directory", "Staffing agency")))
        if by_us and poor(company, cfg):
            cfg.pop("nm", None)
        if cfg.get("nm") and not machine:
            return company          # typed by the person, or already settled
        rows = con.execute("SELECT title, desc FROM listings WHERE company=? AND closed_at IS NULL AND desc IS NOT NULL AND desc<>'' "
                           "ORDER BY last_seen DESC LIMIT ?", (company, SAMPLE)).fetchall()
        n_all = con.execute("SELECT COUNT(*) FROM listings WHERE company=?", (company,)).fetchone()[0]
        locs = [r[0] for r in con.execute("SELECT locations FROM listings WHERE company=? AND closed_at IS NULL LIMIT 400", (company,))]
        taken = {r[0].lower() for r in con.execute("SELECT name FROM companies WHERE name<>?", (company,))}
    if not n_all and not badsuf and not (placeholder and suf):
        return company              # nothing fetched yet: decide after a fetch that returned postings
    texts = [(r["title"] or "") + "\n" + (r["desc"] or "") for r in rows]
    cur = base if suf else company  # (the name is judged without its brackets; whether it needs any is decided below)
    new = None if cfg.get("nm") else derive(cur, cfg, texts, board_title=board_title)
    new = (new or "").replace(",", "").strip()[:60]
    if new and poor(new, cfg):
        new = ""
    place = _main_place(locs)
    want = new or cur
    if poor(want, cfg) == "placeholder":
        want = plain_placeholder(want, place)
    if suf and not badsuf and want == cur:
        final = company             # its plain "(place)" stays
    else:
        final = unique_name(want, cfg, taken, place)
    settled = bool(texts) or not poor(company, cfg)
    if final and final != company and (new or badsuf or placeholder) and catalog.rename_company(company, final):
        log(f"  {company} is now called {final}")
        _follow_rename(company, final)
        company = final
    if settled:
        with catalog.db() as con:
            row = con.execute("SELECT cfg FROM companies WHERE name=?", (company,)).fetchone()
            if row:
                cfg = json.loads(row["cfg"])
                if not poor(company, cfg) and not cfg.get("nm"):    # (a name that is still a code is tried again after the next fetch)
                    cfg["nm"] = 2       # (2: settled by Siftwell; 1: typed by the person, company_add)
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
