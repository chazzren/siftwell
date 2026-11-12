"""Plain-code readers for the facts in a job posting: its pay, level and workplace, plus the clean-up of its text and
title. No network, no Claude, nothing about who is looking: jobfinder.prepare_listing() stores what these return.

    clean_text(s)            3+ newlines -> one blank line (Workday postings carry runs of 16)
    clean_title(t)           "006356-Maintenance Electrician 1" -> "Maintenance Electrician 1"
    parse_pay(text)          {"lo", "hi", "unit", "annual_lo", "annual_hi", "text"} or None
    pay_label(lo, hi, unit)  "$36.90/hr", "$18.50-$22.75/hr", "$45k-$52k"
    title_level(title)       1-7 or None (unknown stays unknown)
    years_required(text), years_level(years), seniority(title, text)
    workplace_label(s)       "remote" / "hybrid" / "onsite" / "" for a board's own workplace or location label
    remote_label(loc)        does this location label say the job is remote? ("Not Remote" doesn't)
    telecommute(d)           a schema.org JobPosting that is really remote (iCIMS marks in-person jobs TELECOMMUTE)
    text_states(text)        US states a posting names ("current Georgia license", "Columbus, GA 31901")
"""
import re

PARSE_VERSION = 2   # bump when stored listings must be parsed again from their saved text (jobfinder.reparse_stored)

# ---------------------------------------------------------------- text and titles
_BLANKS = re.compile(r"\n(?:[ \t\xa0​]*\n){2,}")


def clean_text(s):
    """Posting text with runs of blank lines collapsed to one (the page shows it with its line breaks)."""
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t\xa0​]+\n", "\n", s)
    return _BLANKS.sub("\n\n", s).strip()


# a requisition code in front of the title: "006356-Maintenance Electrician 1", "R0088425 - Nurse", "(12345) Clerk",
# "JR-10234: Analyst", "2026-19146 Generalist". Never a number that belongs to the title ("911 Dispatcher", "3rd Shift
# Welder", "401k Specialist", "1st Grade Teacher").
_REQ_HEAD = re.compile(r"^\s*(?:\(\s*[A-Z]{0,5}[-_ ]?\d{3,}[A-Z0-9]*\s*\)\s*[-–—:|]?\s*"
                       r"|#?[A-Z]{0,5}[-_]?\d{3,}(?:-\d+)*[A-Z0-9]*\s*[-–—:|]\s*"
                       r"|(?:19|20)\d{2}-\d{3,}\s+"
                       r"|(?:req(?:uisition)?|job|posting)\s*(?:id|#|no\.?|number)?\s*[:#]?\s*[A-Z]{0,4}-?\d{3,}\s*[-–—:|]\s*)(?=[A-Za-z(])", re.I)
_REQ_TAIL = re.compile(r"\s*(?:[-–—|]\s*|\(\s*)(?:(?:req(?:uisition)?|job|posting)\s*(?:id|#|no\.?|number)?\s*[:#]?\s*)?#?[A-Z]{0,4}[-_]?\d{5,}(?:[-_]\d+)?\s*\)?\s*$", re.I)


def clean_title(t):
    """A job title without the requisition code some boards put in front of (or after) it."""
    t = re.sub(r"\s+", " ", t or "").strip()
    for _ in range(2):
        m = _REQ_HEAD.match(t)
        if not m or len(re.sub(r"[^A-Za-z]", "", t[m.end():])) < 3:
            break
        t = t[m.end():].strip()
    m = _REQ_TAIL.search(t)
    if m and len(re.sub(r"[^A-Za-z]", "", t[:m.start()])) >= 3:
        t = t[:m.start()].strip()
    return t


# ---------------------------------------------------------------- pay
HOURS_PER_YEAR = 2080
PER_YEAR = {"hour": HOURS_PER_YEAR, "day": 260, "week": 52, "month": 12, "year": 1}
UNIT_SHORT = {"hour": "/hr", "day": "/day", "week": "/wk", "month": "/mo", "year": ""}
# what one unit of pay may plausibly be, in dollars (anything else is not base pay: a bonus, a typo, a revenue figure)
UNIT_RANGE = {"hour": (7.25, 500), "day": (60, 4000), "week": (300, 20000), "month": (1200, 80000), "year": (15000, 2_000_000)}

_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?([kK](?![A-Za-z]))?"
_UNIT_WORDS = (r"(?P<hour>h(?:ou)?rs?|hourly|hr\.)|(?P<day>day|daily|diem)|(?P<week>w(?:ee)?k|weekly)|(?P<month>mo(?:nth)?|monthly)"
               r"|(?P<year>y(?:ea)?r|annum|annually|annual|yearly)")
_UNIT_AFTER = re.compile(r"^\s*(?:usd|us dollars?)?\s*(?:\.00)?\s*(?:/|per|an?|each|every)\s*(?:" + _UNIT_WORDS + r")\b\.?|"
                         r"^\s*(?:usd)?\s*(?:" + r"(?P<hour2>hourly)|(?P<year2>annually|annual|yearly|per annum)|(?P<week2>weekly)|(?P<month2>monthly)" + r")\b", re.I)
_UNIT_BEFORE = re.compile(r"(?:(?P<hour>hourly|per hour|an hour|/\s?h(?:ou)?r)|(?P<year>annual(?:ly|ized)?|yearly|per year|salary|salaried|/\s?y(?:ea)?r)"
                          r"|(?P<week>weekly|per week)|(?P<month>monthly|per month))", re.I)
_SEP = re.compile(r"^\s*(?:usd|us dollars?)?\s*(?:(?:/|per|an?)\s*(?:" + _UNIT_WORDS + r")\b\.?\s*)?(?:-|–|—|to|through|and|up to)\s*(?:usd\s*)?$", re.I)
_MINMAX = re.compile(r"^\W*(?:usd)?\s*(?:/|per)?\s*(?:" + _UNIT_WORDS + r")?\W*\s*max(?:imum)?\W*\s*(?:usd\s*)?$", re.I)
# words that say a dollar amount is NOT base pay
_NOT_PAY_BEFORE = re.compile(r"additional|extra\b|increase|\+\s*$|plus\s*$|bonus|sign[- ]?on|signing|referral|retention|tuition|reimburs|stipend|allowance|relocation|401|match|"
                             r"revenue|sales of|budget|portfolio|assets|funding|grant|quota|savings?|discount|gift|deductible|coverage|"
                             r"insurance|loan|award|scholarship|differential|incentive|commission|fee\b|cost|worth|valued at|"
                             r"invest|raised|raise of|fund\b|purchase|over \$?$|more than \$?$|in sales|book of business|premium|"
                             r"contribution|hsa\b|fsa\b|credit|prize|donat|per diem of|company of|business of|deals?\b|contracts?\b", re.I)
_NOT_PAY_AFTER = re.compile(r"^\s*(?:\+|plus)?\s*(?:usd\s*)?(?:million|billion|mm\b|bn\b|[mb]\b|sign[- ]?on|signing|bonus|referral|retention|"
                            r"stipend|allowance|differential|incentive|in (?:sales|revenue|assets|funding|tuition|benefits|bonus)|"
                            r"(?:shift|night|weekend) diff|tuition|reimburs|match|off\b|discount|gift|deductible|credit|"
                            r"(?:annual |yearly )?(?:revenue|budget|portfolio))", re.I)
_PAY_WORD = re.compile(r"pay\b|pays\b|paid\b|salary|wage|rate\b|compensation|range|starting|starts|base\b|earn|hourly|"
                       r"per hour|annual|\bmin\b|minimum|\bmax\b|up to|from\b", re.I)


def _num(s, k):
    v = float(s.replace(",", ""))
    return v * 1000 if k else v


def _unit_of(m):
    return next((k.rstrip("2") for k, v in m.groupdict().items() if v), None) if m else None


def _guess_unit(lo, hi, cents, ctx_before):
    """The unit of a pay figure that names none: by the words before it, else by its size."""
    b = None
    for m in _UNIT_BEFORE.finditer(ctx_before[-60:]):
        b = _unit_of(m)
    if b and UNIT_RANGE[b][0] <= lo <= hi <= UNIT_RANGE[b][1]:
        return b, True
    if hi >= 15000:
        return "year", False
    if hi <= 150 and (cents or hi <= 100):
        return "hour", False
    return None, False


def pay_candidates(text):
    """Every pay figure in the text as (score, annual_hi, dict). A figure is a range ("$18.50 - $22.75 per hour",
    "from $95,000 to $120,000") or one value with a unit or pay wording ("$36.90/hr", "Starting at $19.25 per hour",
    "Salary: $40,000 per year"). Bonuses, 401k, tuition and revenue figures are left out."""
    text = text or ""
    ms = list(re.finditer(_AMT, text))
    out, used = [], set()
    for i, m in enumerate(ms):
        if i in used:
            continue
        before = text[max(0, m.start() - 70): m.start()]
        if re.search(r"\d[,.]?$", text[max(0, m.start() - 1): m.start()]):
            continue
        lo = hi = _num(m.group(1), m.group(2))
        cents = "." in m.group(1)
        end, is_range, k_one = m.end(), False, bool(m.group(2))
        if i + 1 < len(ms):
            n = ms[i + 1]
            gap = text[m.end(): n.start()]
            sep = len(gap) <= 40 and _SEP.match(gap)
            if sep and re.search(r"\band\s*(?:usd\s*)?$", gap, re.I) and not re.search(r"between\s*(?:usd\s*)?$", before, re.I):
                sep = None                          # "$20 and $25" is a range only after "between"
            joined = sep or (len(gap) <= 40 and _MINMAX.match(gap) and re.search(r"min(?:imum)?\W*(?:usd\s*)?$", before, re.I)) \
                or (len(gap) <= 90 and "$" not in gap and re.search(r"from\s*(?:usd\s*)?$", before, re.I)
                    and re.search(r"\bto\s*(?:usd\s*)?$", gap, re.I))
            if joined:
                hi2, lo2 = _num(n.group(1), n.group(2)), lo
                if n.group(2) and not m.group(2) and lo2 < 1000:
                    lo2 *= 1000                     # "$120 - $180k"
                if hi2 >= lo2:
                    lo, hi = lo2, hi2
                    cents = cents or "." in n.group(1)
                    end, is_range, k_one = n.end(), True, k_one or bool(n.group(2))
                    used.add(i + 1)
        after = text[end: end + 60]
        clause = re.split(r"[.;!?]\s|\n|•|\|", before)[-1]
        um = _UNIT_AFTER.match(after)
        if _NOT_PAY_AFTER.match(after) or (um and _NOT_PAY_AFTER.match(after[um.end():])) or _NOT_PAY_BEFORE.search(clause[-45:]):
            continue
        unit = _unit_of(um)
        if not unit and is_range:               # "$18.50/hr - $22.75": the unit sits between the two amounts
            unit = _unit_of(re.search(r"(?:/|per|an?)\s*(?:" + _UNIT_WORDS + r")\b", text[m.end(): ms[i + 1].start()], re.I))
        explicit, worded = bool(unit), False
        if not unit:
            if is_range and not k_one and 100 < hi < 1000 and lo >= 30 and not cents and not re.search(r"hour|/\s?hr", before[-40:], re.I):
                lo, hi = lo * 1000, hi * 1000       # "$120 - $180" in a salary line means thousands
            unit, worded = _guess_unit(lo, hi, cents, before)
        if not unit:
            continue
        pay_word = bool(_PAY_WORD.search(before[-60:]))
        if not is_range and not explicit and not (pay_word and (unit == "year" or worded)):
            continue                                # a lone "$65,000" or "$22" with nothing saying it is pay
        a, b = UNIT_RANGE[unit]
        if not (a <= lo <= hi <= b):
            continue
        per = PER_YEAR[unit]
        phrase = re.sub(r"\s+", " ", text[m.start(): end + (um.end() if um else 0)]).strip()[:80]
        score = 2 * explicit + 2 * pay_word + is_range
        out.append((score, hi * per, {"lo": lo, "hi": hi, "unit": unit, "annual_lo": round(lo * per), "annual_hi": round(hi * per),
                                      "text": phrase}))
    return out


def parse_pay(text):
    """The posting's base pay, or None. Among several figures the best-described wins (a unit and pay wording beat a
    bare range), then the highest."""
    c = pay_candidates(text)
    return max(c, key=lambda x: (x[0] >= 2, x[1], x[0]))[2] if c else None


def _money(v, unit):
    if unit == "year":
        return "$" + (f"{v / 1000:.0f}k" if v >= 10000 else f"{v:,.0f}")
    return "$" + (f"{v:,.2f}" if abs(v - round(v)) > 0.004 else f"{v:,.0f}")


def pay_label(lo, hi, unit):
    """How pay reads on a card: hourly pay stays hourly ("$36.90/hr"), yearly pay is in thousands ("$45k-$52k")."""
    if lo is None:
        return ""
    unit = unit if unit in UNIT_SHORT else "year"
    a, b = _money(lo, unit), _money(hi if hi is not None else lo, unit)
    return (a if a == b else f"{a}–{b}") + UNIT_SHORT[unit]


# ---------------------------------------------------------------- level
LEVEL_NAMES = {1: "Entry level", 2: "Mid-level", 3: "Senior", 4: "Lead / Manager", 5: "Principal / Sr. Manager", 6: "Director", 7: "VP / Executive"}
IC_MANAGER = (r"(?:product|program|project|account|success|partner|partnership|relationship|case|community|portfolio|delivery|release|"
              r"marketing|channel|alliance|territory|solutions?|implementation|deployment|engagement|technical program|"
              r"technical account|technical product|risk|compliance|vendor|contract|grants?|data|knowledge|content|campaign|"
              r"brand|events?|office|facility|property|operations program|care|social media|category|construction|estimating)")
# titles where "staff", "fellow" and "distinguished" are ladder rungs (engineering and research ladders)
_ENG = r"(?:engineer|engineering|developer|scientist|architect|designer|researcher|programmer|sre|devops|software|firmware|hardware|technologist)"
_NUM_NOT_GRADE = (r"shift|store|unit|grade|room|floor|bldg|building|line|station|zone|district|region|area|site|plant|location|route|"
                  r"team|crew|ward|pod|lab|campus|phase|week|day|no|number|ste|suite|hall|wing|bay|dock|gate|terminal|cell|group|dept|"
                  r"department|class|section|post|squad|engine|ladder|truck|bus|car|machine|press|mill|door|lot")
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}


def _grade_suffix(title):
    """The grade at the end of a title (or of its first part): "Electrician 1", "Nurse II - Night Shift",
    "Accountant III", "Technician Level 2". None when the number means something else ("Store 616", "3rd Shift",
    "IV Therapy Nurse", "RN - 4 West")."""
    segs = [s.strip() for s in re.split(r"\s+[-–—|]\s+|[,(/]", title) if s.strip()]
    for seg in ([segs[0]] if segs else []) + ([segs[-1]] if len(segs) > 1 else []):
        m = re.search(r"([A-Za-z][A-Za-z.&']*)\s+(?:(?:level|lvl|tier|grade|step)\s+)?(i{1,3}|iv|v|[1-5])$", seg, re.I)
        if not m:
            continue
        word, g = m.group(1).lower().strip("."), m.group(2).lower()
        if re.fullmatch(_NUM_NOT_GRADE, word) or word in ("part", "type", "pre", "k", "title", "schedule", "category"):
            continue
        if re.search(r"\bgrade\s+\S+$", seg, re.I) and re.search(r"teach|school|element|math|reading|class", title, re.I):
            continue            # "4th Grade Teacher", "Teacher Grade 5"
        if g in _ROMAN and g == "i" and m.group(2) != "I":
            continue            # a lower-case "i" is not a grade
        return _ROMAN.get(g) or int(g)
    return None


def title_level(title):
    """The level a job title states, 1-7 (LEVEL_NAMES), or None when it states none. Works for any field: "Staff RN",
    "Staff Accountant" and "IV Therapy Nurse" say nothing about level; "Staff Engineer" does; "Electrician 1",
    "Apprentice", "Junior" and "Trainee" are entry level; a grade only counts at the end of the title."""
    raw = title or ""
    t = " " + re.sub(r"[^a-z0-9/&+ ]", " ", raw.lower()) + " "
    t = re.sub(r"\s+", " ", t)
    eng = bool(re.search(_ENG, t))
    if re.search(r" (vp|svp|evp|avp|vice president|cto|ciso|cio|coo|ceo|cfo|cno|cmo|president|managing director|executive director) ", t) \
            or re.search(r" (senior|sr) director ", t):
        return 7
    if re.search(r" chief ", t) and not re.search(r" (crew|shift|line|party|section|station|battalion) chief | chief (resident|clerk|engineer) ", t):
        return 7
    if eng and re.search(r" (distinguished|fellow) ", t):
        return 7
    if re.search(r" (assistant|associate|asst|assoc|deputy) director ", t):
        return 5
    if re.search(r" (director|head of) ", t) and not re.search(r" funeral director ", t) or re.search(r" (senior|sr) principal ", t):
        return 6
    if re.search(r" (apprentice(?:ship)?|trainee|in training|intern|internship|new grad(?:uate)?s?|graduate nurse|entry level) ", t):
        return 1
    if re.search(r" (principal|group manager|group product manager|senior manager|sr manager|senior engineering manager) ", t) \
            or (eng and re.search(r" (senior|sr) staff ", t)) or re.search(r" level 5 ", t):
        return 5
    if eng and re.search(r" staff ", t) and not re.search(r" (support|technical|of|and|&) staff | staff (assistant|nurse|rn|accountant|attorney|support) ", t):
        return 4
    if re.search(r" (tech lead|team lead|team leader|supervisor|foreman|foreperson|superintendent|charge nurse|crew chief|shift chief|"
                 r"chief engineer|level 4) ", t):
        return 4
    if re.search(r" (lead|leader) ", t) and not re.search(r" lead (generation|gen|abatement|paint|development|qualification|intake|acid) ", t):
        return 4
    if re.search(r" head (?!start )[a-z]", t):
        return 4            # Head Nurse, Head Cashier, Head Cook, Head Coach
    m = re.search(r" (\w+ )?(\w+ )?manager ", t)
    if m and not re.search(IC_MANAGER + r" manager ", t):
        return 4  # people manager (engineering manager, nurse manager, manager of X, ...)
    if re.search(r" (senior|sr|snr|level 3) ", t):
        return 3
    if re.search(r" (junior|jr|helper|entry|learner|cadet|level 1) ", t):
        return 1
    if re.search(r" (mid|mid level|intermediate|journeyman|journeyperson|level 2) ", t):
        return 2
    g = _grade_suffix(re.sub(r"\s+", " ", raw).strip())
    return g if g else None


YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years|yrs|year)", re.I)
NO_EXPERIENCE = re.compile(r"no (?:prior |previous )?(?:work )?experience (?:is )?(?:required|necessary|needed)|"
                           r"entry[- ]level (?:position|role|job|opportunity)|experience (?:is )?not (?:required|necessary)|"
                           r"will(?:ing to)? train|we (?:will )?train|paid training|no experience\b", re.I)


def years_required(text):
    """The years of experience the posting asks for (its largest required minimum), 0 for "0-1 years" or "no
    experience required", None when it doesn't say."""
    text = text or ""
    best = None
    for m in YEARS.finditer(text):
        ctx = text[m.end(): m.end() + 60].lower()
        pre = text[max(0, m.start() - 40): m.start()].lower()
        if "experience" not in ctx and "experience" not in pre:
            continue
        y = int(m.group(1))
        if re.search(r"prefer|nice to have|bonus|plus\b|desired|ideal", text[max(0, m.start() - 200): m.start()].lower()):
            continue  # preferred qualifications overstate the bar
        if y == 0 and not m.group(2):
            continue
        if 0 <= y <= 20 and (best is None or y > best):  # the main (largest) required minimum
            best = y
    if best is None and NO_EXPERIENCE.search(text):
        best = 0
    return best


def years_level(y):
    """Level from years of experience alone: entry (0-1), mid (2-4), senior (5+). Years never make a job a lead or a
    manager: only its title does."""
    if y is None:
        return None
    return 1 if y <= 1 else 2 if y <= 4 else 3


def seniority(title, text):
    lv = title_level(title)
    if lv is not None:
        return lv, "title"
    y = years_required(text)
    return years_level(y), ("years" if y is not None else "")


# ---------------------------------------------------------------- workplace
_NOT_REMOTE = re.compile(r"\b(?:not|non|no)\b[\s\-_/:]*(?:a |eligible for |available for )?remote\b|"
                         r"\bremote\b[^.;,\n]{0,25}?\b(?:not|n't|no|unavailable|ineligible)\b|\bremote\s*[:=\-]\s*(?:no|false|n|none)\b", re.I)
_REMOTE_PARTLY = re.compile(r"\bhybrid\b|\bpartial(?:ly)?\b|\bflex(?:ible)?\b|\b(?:an )?option(?:al)?\b|\bpossible\b|"
                            r"\bsome\b|\boccasional(?:ly)?\b|\bdays?\b|\bmix\b|\bcombination\b", re.I)
_REMOTE_WORD = re.compile(r"\bremote(?:ly)?\b|\btelecommut\w*|\btelework\w*|\bwork[- ]from[- ]home\b|\bwfh\b|\bvirtual\b|\bhome[- ]based\b", re.I)
_ONSITE_WORD = re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\bin[- ]person\b|\boffice worker\b|\bon[- ]?premises?\b|\bon location\b|"
                          r"\bin the office\b|\boffice[- ]based\b", re.I)


# "Virtual Care Center", "Remote Monitoring Unit", "Anywhere Real Estate" are places or names, not remote work
_REMOTE_LOC_NOT = re.compile(r"\b(?:virtual|remote|anywhere)\s+(?:care|health|visit|nursing|urgent|monitoring|patient|sitter|sitting|"
                             r"icu|hospital|learning|academy|school|reality|real estate|sensing|pharmacy|clinic|deposit|site|sites|"
                             r"area|areas|location area|village|community|communities|access|control|pilot|pilots|start|starter|"
                             r"support|assistant|desktop|infrastructure|events?|production|machines?|servers?)\b", re.I)


def workplace_label(s, typed=False):
    """What a workplace value says: Workday's remoteType ("Remote", "Hybrid", "On-Site", "Office Worker (NOT
    Remote)", "Remote work is not available", "Remote work is an option"), a "Work Location" field, a location label
    or a title ("Accountant (Remote)"). Negation is read first, so "not remote" is on-site; "Remote Sensing Analyst"
    and "Virtual Care Nurse" are not remote work. typed: the value comes from a field that only holds a workplace
    type, so "Office", "Site" and "Field" mean on-site too."""
    s = " ".join(str(s or "").split())
    if not s:
        return ""
    if _NOT_REMOTE.search(s):
        return "hybrid" if re.search(r"\bhybrid\b", s, re.I) else "onsite"
    if re.search(r"\bhybrid\b", s, re.I):
        return "hybrid"
    r = _REMOTE_LOC_NOT.sub(" ", s)
    if _REMOTE_WORD.search(r):
        if _ONSITE_WORD.search(r) or (typed and _REMOTE_PARTLY.search(_REMOTE_WORD.sub(" ", r))):
            return "hybrid"
        return "remote"
    if _ONSITE_WORD.search(s) or (typed and re.search(r"\boffice\b|\bsite\b|\bfield\b", s, re.I)):
        return "onsite"
    return ""


_REMOTE_LOC = re.compile(r"\bremote\b|\banywhere\b|\bvirtual\b|\btelework\w*|\btelecommut\w*|\bwork[- ]from[- ]home\b|\bwfh\b", re.I)
def remote_label(loc):
    """Does a location label say the job is remote? "Remote", "US - Remote", "Virtual", "Work from home": yes.
    "Not Remote", "Non-Remote", "Remote: No", "Virtual Care Center": no."""
    s = str(loc or "")
    if not _REMOTE_LOC.search(s):
        return False
    return not _NOT_REMOTE.search(s) and not _REMOTE_LOC_NOT.search(s)


def telecommute(d):
    """Is a schema.org JobPosting really remote? jobLocationType TELECOMMUTE counts when the posting gives no street
    address, or says where remote applicants may live (applicantLocationRequirements). iCIMS marks every job
    TELECOMMUTE, in-person hospital jobs with a street address included."""
    if not isinstance(d, dict) or "TELECOMMUTE" not in str(d.get("jobLocationType") or "").upper():
        return False
    if d.get("applicantLocationRequirements"):
        return True
    locs = d.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    for jl in locs:
        a = (jl.get("address") if isinstance(jl, dict) else None) or {}
        if isinstance(a, dict):
            street = str(a.get("streetAddress") or "").strip()
            if street and street.upper() not in ("UNAVAILABLE", "N/A", "NA", "REMOTE", "VIRTUAL"):
                return False
    return True


# two-letter country codes after "Remote" that are no US state ("Remote, PL", "Remote - GB")
_REMOTE_CC = re.compile(r"\b(?i:remote|virtual|home)\b\W{1,4}(?:in\s+)?(UK|GB|PL|DK|IE|FR|ES|NL|SE|NO|FI|PT|IT|CH|AT|BE|CZ|RO|BG|HU|GR|TR|JP|CN|SG|"
                        r"AU|NZ|BR|MX|ZA|PH|MY|KR|TW|HK|EU|LT|LV|EE|HR|RS|UA|SK|SI|CY|LU|IS|EG|NG|KE|CL|PE|UY|CR)\b|"
                        r"\b(UK|GB|PL|DK|IE|FR|ES|NL|SE|NO|FI|PT|IT|CH|AT|BE|CZ|RO|BG|HU|GR|TR|JP|CN|SG|AU|NZ|BR|MX|ZA|PH|MY|KR|TW|HK|EU)\b"
                        r"\W{1,4}(?i:remote|virtual)\b")


def foreign_remote(label):
    """A remote label that names another country by its two-letter code ("Remote, PL", "UK - Remote")."""
    return bool(_REMOTE_CC.search(str(label or "")))


def title_place(title):
    """The place a title ends with, if any: "Customer Success Manager – Belfast, UK" -> "Belfast, UK",
    "Support Engineer (Aarhus, Denmark)" -> "Aarhus, Denmark". "" when the title names none."""
    t = (title or "").strip()
    m = re.search(r"\(([^()]{3,60})\)\s*$", t) or re.search(r"\s[-–—|@]\s*([^-–—|@]{3,60})$", t)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- states a posting names
_STATE_NAMES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
                "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
                "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
                "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
                "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
                "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
                "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
                "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
                "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC"}
_STATE_NAME_RX = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(_STATE_NAMES, key=len, reverse=True)) + r")(?![A-Za-z])", re.I)
_STATE_CODE_RX = re.compile(r",\s*([A-Z]{2})(?=\s+\d{5}\b|\s*[,.;)\n]|\s*$)|\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
_CODES = set(_STATE_NAMES.values())


def text_states(text, limit=6):
    """US states a posting's text names, most-mentioned first: full names ("a current Georgia license", "State of
    Ohio") and codes written as part of an address ("Columbus, GA 31901", "Dublin, OH"). At most `limit`: a posting
    that lists every state says nothing about where the job is."""
    text = text or ""
    n = {}
    for m in _STATE_NAME_RX.finditer(text):
        w = m.group(1)
        if not w[0].isupper():
            continue
        st = _STATE_NAMES[w.lower()]
        if st == "WA" and re.match(r"\s*,?\s*(?:d\.?c\.?|university|state university|post|street|st\b|ave|blvd|county)", text[m.end(): m.end() + 22], re.I):
            continue            # Washington, DC / Washington University / Washington Street
        if st == "VA" and re.search(r"west\s*$", text[max(0, m.start() - 6): m.start()], re.I):
            continue
        if st == "NY" and re.match(r"\s+(?:times|life|stock|yankees|mets|presbyterian)", text[m.end(): m.end() + 16], re.I):
            continue
        n[st] = n.get(st, 0) + 1
    for m in _STATE_CODE_RX.finditer(text):
        st = m.group(1) or m.group(2)
        if st in _CODES:
            n[st] = n.get(st, 0) + 1
    if len(n) > limit:
        return []
    return [k for k, _ in sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))]
