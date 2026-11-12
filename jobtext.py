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

PARSE_VERSION = 4   # bump when stored listings must be parsed again from their saved text (jobfinder.reparse_stored)

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
_UNIT_AFTER = re.compile(r"^\s*(?:usd|us dollars?)?\s*(?:\.00)?\s*(?:/\s*per|/|per|an?|each|every)\s*(?:" + _UNIT_WORDS + r")\b\.?|"
                         r"^\s*(?:usd)?\s*(?:" + r"(?P<hour2>hourly)|(?P<year2>annually|annual|yearly|per annum)|(?P<week2>weekly)|(?P<month2>monthly)" + r")\b", re.I)
_UNIT_BEFORE = re.compile(r"(?:(?P<hour>hourly|per hour|an hour|/\s?h(?:ou)?r)|(?P<year>annual(?:ly|ized)?|yearly|per year|salary|salaried|/\s?y(?:ea)?r)"
                          r"|(?P<week>weekly|per week)|(?P<month>monthly|per month))", re.I)
_SEP = re.compile(r"^\s*(?:usd|us dollars?)?\s*(?:(?:/|per|an?)\s*(?:" + _UNIT_WORDS + r")\b\.?\s*)?(?:-|–|—|to|through|and|up to)\s*(?:usd\s*)?$", re.I)
# what stands between a minimum and its maximum: "Min: $70,123 Max: $121,931", "Minimum Rate $85,000 Annually Maximum Rate
# $165,000", "Pay Band Min USD $87,320.00/Yr. Pay Band Max USD $135,160.00/Yr.", "Salary minimum: $115,000; Salary maximum: $150,000"
_MINMAX = re.compile(r"^\W*(?:usd)?\s*(?:/|per)?\s*(?:" + _UNIT_WORDS + r")?\W*(?:[A-Za-z]+\s+){0,2}max(?:imum)?\b(?:\s+[A-Za-z]+){0,2}\W*(?:usd\s*)?$", re.I)
# words that say a dollar amount is NOT base pay
_NOT_PAY_BEFORE = re.compile(r"additional|extra\b|increase|\+\s*$|plus\s*$|bonus|sign[- ]?on|signing|referral|retention|tuition|reimburs|stipend|allowance|relocation|401|match|"
                             r"revenue|sales of|budget|portfolio|assets|funding|grant|quota|savings?|discount|gift|deductible|coverage|"
                             r"insurance|loan|award|scholarship|differential|incentive|commission|fee\b|cost|worth|valued at|"
                             r"invest|raised|raise of|fund\b|purchase|over \$?$|more than \$?$|in sales|book of business|premium|"
                             r"contribution|hsa\b|fsa\b|credit|prize|donat|per diem of|company of|business of|deals?\b|"
                             r"contracts? (?:worth|valued|values?|of|totall?ing)|fundrais|\braising\b|\bgoals?\b|pipeline", re.I)
# on-target / total earnings: pay, but not base pay. Shown when the posting gives nothing else; a base figure wins.
_OTE = re.compile(r"on[- ]target|\bote\b|total (?:target |estimated |annual )?(?:compensation|cash|rewards|earnings)|"
                  r"target (?:total )?(?:compensation|earnings)", re.I)
_NOT_PAY_AFTER = re.compile(r"^\s*(?:\+|plus)?\s*(?:usd\s*)?(?:million|billion|mm\b|bn\b|[mb]\b|sign[- ]?on|signing|bonus|referral|retention|"
                            r"stipend|allowance|differential|incentive|in (?:sales|revenue|assets|funding|tuition|benefits|bonus)|"
                            r"(?:shift|night|weekend) diff|tuition|reimburs|match|off\b|discount|gift|deductible|credit|"
                            r"(?:annual |yearly )?(?:revenue|budget|portfolio))", re.I)
# words that say base pay after all, when they come after a not-pay word in the same clause: "Additional US Location(s)
# Base Pay Range: $111,000 - $197,300", "Shift Differential Eligible: Yes Pay Range: $37.00 - $55.00"
_PAY_PHRASE = re.compile(r"(?:pay|salary|wage|compensation|hiring|hourly)\s+(?:range|rate|band|scale)|base\s+(?:pay|salary|compensation)|"
                         r"(?:pay|salary|salaries|wages?)\s*(?:is|are|:)", re.I)
# the second amount of a range written without its dollar sign: "$85,000 - 140,000", "$87K-115K", "$18-22/hr"
_BARE_HI = re.compile(r"^\s*(?:usd\s*)?(?:-|–|—|to)\s*(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?([kK](?![A-Za-z]))?(?![\d,]*\d|\s*%)")
_MIN_BEFORE = re.compile(r"\bmin(?:imum)?\b(?:\s+[A-Za-z]+){0,2}\W*(?:usd\s*)?$", re.I)
# pay per something that is not time ("$60-$200 per visit", "Pay Range Per Project $50 - $150"), or in another currency:
# nothing a year's pay can be worked out from
_PER_OTHER_AFTER = re.compile(r"^\s*(?:usd\s*)?(?:(?:/|per|an?|each)[\s-]*(?:visit|article|project|session|class|piece|unit|word|mile|shift|"
                              r"student|lesson|game|event|trip|load|call|case|patient|item|page|post|story)\b|(?:cad|eur|gbp|aud|mxn|inr)\b)", re.I)
_PER_OTHER_BEFORE = re.compile(r"per[\s-]*(?:visit|article|project|session|class|piece|unit|word|mile|student|lesson|game|event|trip|load|call|"
                               r"case|patient|item|page|post|story)\b[^$\n]{0,30}$", re.I)
_PAY_WORD = re.compile(r"pay\b|pays\b|paid\b|salary|wage|rate\b|compensation|range|starting|starts|base\b|earn|hourly|"
                       r"per hour|annual|\bmin\b|minimum|\bmax\b|up to|from\b", re.I)


def _num(s, k):
    v = float(s.replace(",", ""))
    return v * 1000 if k and v < 10000 else v      # ("$172,900K" is a slip for $172,900)


def _unit_of(m):
    return next((k.rstrip("2") for k, v in m.groupdict().items() if v), None) if m else None


def _guess_unit(lo, hi, cents, ctx_before):
    """The unit of a pay figure that names none: by the words before it, else by its size."""
    b = None
    seg = ctx_before[-60:]
    k = seg.rfind("$")
    if k >= 0:      # "$6,250 per month ($75,000 annualized)": "per month" belongs to the amount before it
        seg = re.sub(r"^\$\s?[\d,.]*\d\s?[kK]?", "", seg[k:])
        um = _UNIT_AFTER.match(seg)
        seg = seg[um.end():] if um else seg
    for m in _UNIT_BEFORE.finditer(seg):
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
            joined = sep or (len(gap) <= 40 and _MINMAX.match(gap) and _MIN_BEFORE.search(before)) \
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
        if not is_range:
            # "$85,000 - 140,000", "$87K-115K": the second amount has no dollar sign. It must look like money (thousands
            # written out, a k, cents like the first, or a unit right after it) and be no more than 10x the first.
            bm = _BARE_HI.match(text[m.end(): m.end() + 30])
            if bm:
                hi2, lo2 = _num(bm.group(1), bm.group(2)), lo
                if bm.group(2) and not m.group(2) and lo2 < 1000:
                    lo2 *= 1000
                moneyish = "," in bm.group(1) or bool(bm.group(2)) or ("." in bm.group(1) and cents) \
                    or bool(_UNIT_AFTER.match(text[m.end() + bm.end(): m.end() + bm.end() + 20]))
                if moneyish and lo2 <= hi2 <= 10 * lo2:
                    lo, hi = lo2, hi2
                    cents = cents or "." in bm.group(1)
                    end, is_range, k_one = m.end() + bm.end(), True, k_one or bool(bm.group(2))
        e0 = end - 1 if text[end - 1: end].isspace() else end      # (the amount's own match takes one blank after it)
        after = text[e0: e0 + 60]
        clause = re.split(r"[.;!?]\s|\n|•|\|", before)[-1]
        # A new line after the amount starts something else ("Base Salary: $143,000 - $185,000" / "Bonus program and
        # equity", "... $238,830" / "Monthly cell phone stipend"); a unit on the next line counts only when it is alone there.
        line = after.split("\n", 1)[0]
        um = _UNIT_AFTER.match(after)
        if um and "\n" in after[:um.end()] and after[um.end():].split("\n", 1)[0].strip(" .:;,)*"):
            um = None
        nb = None
        for nb in _NOT_PAY_BEFORE.finditer(clause[-45:]):
            pass
        # "$95,000 - $120,000 + bonus", "$120,000 annually plus commission": the amount is the base, the rest comes on
        # top ("$5,000+ sign-on bonus", with the plus right on the number, is still a bonus)
        tail = after[um.end():].split("\n", 1)[0] if um else line
        on_top = tail.lstrip().lower().startswith(("+", "plus ")) and (is_range or bool(um) or after[:1].isspace())
        unit = _unit_of(um)
        # A not-pay word before the amount doesn't count when words that say base pay follow it, or when the figure is a
        # range with its unit in a line that says pay ("Pay range: Global Relocation Program Manager: $110,000.00 -
        # $145,000.00/per year", "The hourly salary range for this contract position is $60 to $85/hr").
        if nb and (_PAY_PHRASE.search(clause[-45:][nb.end():]) or (is_range and unit and _PAY_PHRASE.search(before))):
            nb = None
        if (not on_top and (_NOT_PAY_AFTER.match(line) or _NOT_PAY_AFTER.match(tail))) or nb:
            continue
        if _PER_OTHER_AFTER.match(tail) or _PER_OTHER_BEFORE.search(clause):
            continue
        if not unit and is_range:               # "$18.50/hr - $22.75": the unit sits between the two amounts
            unit = _unit_of(re.search(r"(?:/|per|an?)\s*(?:" + _UNIT_WORDS + r")\b", text[m.end(): end], re.I))
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
        phrase = re.sub(r"\s+", " ", text[m.start(): e0 + (um.end() if um else 0)]).strip()[:80]
        score = 2 * explicit + 2 * pay_word + is_range
        out.append((score, hi * per, {"lo": lo, "hi": hi, "unit": unit, "annual_lo": round(lo * per), "annual_hi": round(hi * per),
                                      "text": phrase, "range": is_range, "ote": bool(_OTE.search(clause[-70:]))}))
    return out


def parse_pay(text):
    """The posting's base pay, or None. Among several figures:
    - a range beats a lone value ("base salary $120,000 to $130,000 ... total compensation up to $260,000", "raise
      $1,500,000 a year"): a lone figure is the pay only when the posting gives no described range;
    - among ranges the highest wins, as it always did ("Level I: ... Level II: ...", "McLean: ... Richmond: ...", "New
      York City Metro Area: ..."): the pay floor hides a job for good, so it must go by the most the posting offers.
      Ranges the posting describes as pay (a unit or pay wording) are trusted; a bare range counts next to them only
      when it is of the same size (half their lowest to twice their highest), so a revenue figure can't win;
    - with no described figure at all, a range beats a lone value, then the highest;
    - on-target or total earnings are shown only when the posting gives no other figure."""
    c = pay_candidates(text)
    c = [x for x in c if not x[2]["ote"]] or c
    if not c:
        return None
    good = [x for x in c if x[0] >= 2]
    if not good:
        return max(c, key=lambda x: (x[2]["range"], x[1], x[0]))[2]
    ranges = [x for x in good if x[2]["range"]] or good       # (only lone described values: they set the size)
    top, bottom = max(x[1] for x in ranges), min(x[2]["annual_lo"] for x in ranges)
    pool = [x for x in ranges if x[2]["range"]] + [x for x in c if x[0] < 2 and x[2]["range"] and bottom / 2 <= x[2]["annual_lo"] and x[1] <= 2 * top]
    return max(pool or good, key=lambda x: (x[1], x[0]))[2]


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


_REMOTE_LOC = re.compile(r"\bremote\b|\banywhere\b|\bvirtual\b|\btelework\w*|\btelecommut\w*|\bwork[- ](?:from|at)[- ]home\b|\bwfh\b|"
                         r"\bhome[- ]based\b", re.I)
def remote_label(loc):
    """Does a location label say the job is remote? "Remote", "US - Remote", "Virtual", "Work from home", "IL Home Based": yes.
    "Not Remote", "Non-Remote", "Remote: No", "Virtual Care Center": no."""
    s = str(loc or "").replace("_", " ")      # "Remote_United States"
    if not _REMOTE_LOC.search(s):
        return False
    if _NOT_REMOTE.search(s) or _REMOTE_LOC_NOT.search(s):
        return False
    return not facility_label(s)


# A site code in front of a facility's name: "09536 - Mainplace Nocturnal-CA Remote" is a dialysis clinic (its name
# ends in "Remote"), "01088 - Columbus Victorian Village Selec" a store. "1234 - Remote" and "0001 - Remote - OH" are
# still remote: nothing but the code, remote words and a state.
_SITE_CODE = re.compile(r"^\s*#?\d{3,}\s*[-–—:]\s*(?=\S)")
_PLACE_FILL = re.compile(r"\b(?:remote|virtual|anywhere|telework\w*|telecommut\w*|work|from|at|home|based|wfh|us|usa|united states|only|in|"
                         r"position|office)\b", re.I)


def facility_label(loc):
    """Is this label a numbered site with a name of its own ("09536 - Mainplace Nocturnal-CA Remote")?"""
    s = str(loc or "")
    m = _SITE_CODE.match(s)
    if not m:
        return False
    rest = _STATE_NAME_RX.sub(" ", _PLACE_FILL.sub(" ", s[m.end():]))
    rest = re.sub(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])", " ", rest)
    return bool(re.search(r"[A-Za-z]{3,}", rest))


def remote_state(loc):
    """The one US state a remote label is tied to: "OH - Work from home" -> "OH", "Remote - Texas" -> "TX", "Remote,
    Minnesota, USA" -> "MN", "US-VA-REMOTE" -> "VA", "Home, TX" -> "TX". None for "Remote", "Remote - US", a label
    that names a town ("Remote - Houston, TX": remote, and near Houston) or more than one state."""
    s = str(loc or "").replace("_", " ")
    if not remote_label(s) and not re.fullmatch(r"\s*(?:home|home office)\s*,\s*[A-Za-z]{2}\s*", s, re.I):
        return None
    found = {_STATE_NAMES[m.group(1).lower()] for m in _STATE_NAME_RX.finditer(s)}
    rest = _STATE_NAME_RX.sub(" ", s)
    for m in re.finditer(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", rest):
        if m.group(1) in _CODES:
            found.add(m.group(1))
    if len(found) != 1:
        return None
    rest = re.sub(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])", " ", _PLACE_FILL.sub(" ", rest))
    if re.search(r"[A-Za-z]{3,}", rest):        # something else is named: a town, a site
        return None
    return next(iter(found))


# Work that is done in person whatever the label says: visiting people at home, a clinic, the field.
_VETO_TITLE = re.compile(r"\bin[- ]home\b|\bhome[- ]health\b|\bhome[- ]visit\w*|\bhouse[- ]calls?\b|\bhome[- ]care\b|\bhome[- ]infusion\b|"
                         r"\bhome (?:hemo)?dialysis\b|\bhome therap\w+|\bfield (?:nurse|rn|service|technician|tech|engineer|sales|rep\w*|based|clinical|"
                         r"case manager|care)\b|\bfield[- ]based\b|\bmobile (?:nurse|rn|phlebotom\w+|examiner|clinician)\b|\btravel(?:ing)? "
                         r"(?:nurse|rn|cna|lpn|technician|tech|therapist)\b|\bon[- ]?site\b|\bin[- ]person\b|\bin[- ]cent(?:er|re)\b", re.I)
_VETO_TEXT = re.compile(r"\bin[- ]home (?:visits?|assessments?|health (?:evaluations?|assessments?|risk)|evaluations?|care (?:visits?|to)|"
                        r"patient|nursing|exams?|appointments?)|\bhome visits?\b|"
                        r"\bvisit(?:s|ing)? (?:patients?|members?|clients?)(?: and families)? in (?:their|the|his or her) (?:own )?homes?\b|"
                        r"\b(?:in|at) (?:the )?(?:patients?|members?|clients?)['’]?s?['’]? (?:own )?homes?\b|"
                        r"\btravel(?:s|ing)? to (?:patients?|members?|clients?|participants?)['’]?s?['’]? ?(?:homes?|residences?|bedsides?)\b|"
                        r"\btravel(?:s|ing)? to (?:patients|members|participants)\b|"
                        r"\bpatient care in an? (?:outpatient|clinic|clinical|in-?cent(?:er|re)|inpatient|hospital|dialysis)\b[^.\n]{0,20}setting|"
                        r"\b(?:outpatient|in-?cent(?:er|re)) (?:dialysis )?(?:clinic|facility|setting)\b[^.\n]{0,60}\bpatient care\b|"
                        r"\bthis (?:is an?|position is|role is|job is)(?: a| an)? (?:100% |fully |full[- ]time )?(?:on[- ]?site|in[- ]person|field[- ]based)\b|"
                        r"\b(?:100%|fully) (?:on[- ]?site|in[- ]person)\b|\bmust (?:work|be) on[- ]?site\b|\bnot (?:a )?remote (?:position|role|job)\b", re.I)


def remote_veto(title, text):
    """The words that say a job is done in person although its label says remote or work from home ("In-Home Health
    Evaluation Nurse Practitioner" at "OH - Work from home", "provides patient care in an outpatient setting"), or ""."""
    m = _VETO_TITLE.search(title or "")
    if m and not re.search(r"\b(?:or|and|/)\s*remote\b|\bremote\s*(?:or|and|/)", title or "", re.I):
        return m.group(0)
    m = _VETO_TEXT.search((text or "")[:6000])
    return m.group(0) if m else ""


# ---------------------------------------------------------------- language and country evidence in a posting's words
_LANG = {
    "fr": set("le la les des et pour vous nous dans avec une est sur au aux du votre notre nos vos ou qui que en de un être sont".split()),
    "es": set("el los las para con una por del que en y su sus nuestro nuestra como más es un de la se al tu".split()),
    "de": set("der die das und mit für wir sie ein eine zu von im den dem des ist sind auf bei als oder ihre unser".split()),
    "nl": set("de het een en van voor met je wij zijn bij op te dat die als ook naar jij jouw onze ons aan".split()),
    "pt": set("o os as para com uma em do da que e você não de um na no dos das por se ao nossa nosso".split()),
    "it": set("il lo gli le per con una che di e in del della dei un è sono nel alla al come più".split()),
}
_ENGLISH = set("the and of to in for with you our is a are as on be will or this that we your an at by from have".split())
_TITLE_FOREIGN = re.compile(r"\b(?:pharmacien(?:ne)?s?|technicien(?:ne)?s?|commis|g[ée]rant(?:e)?|conseill(?:er|[èe]re)s?|infirmi(?:er|[èe]re)s?|"
                            r"vendeu(?:r|se)s?|responsable|gestionnaire|directeur|directrice|adjoint(?:e)?|pr[ée]pos[ée](?:e)?s?|caissi(?:er|[èe]re)s?|"
                            r"stagiaire|ing[ée]nieur(?:e)?|d[ée]veloppeu(?:r|se)|assistant(?:e)? technique|chef d['’ ]?[ée]quipe|livreur|cuisini(?:er|[èe]re)|"
                            r"verpleegkundige|medewerker|verzorgende|begeleider|wijkverpleegkundige|helpende|huishoudelijke|"
                            r"mitarbeiter(?:in)?|sachbearbeiter(?:in)?|kaufmann|kauffrau|pflegefachkraft|werkstudent(?:in)?|leiter(?:in)?|"
                            r"gerente|ingenier[oa]|analista|vendedor(?:a)?|enfermer[oa]|coordinador(?:a)?|asistente|ejecutiv[oa]|auxiliar|"
                            r"desarrollador(?:a)?|contador(?:a)?|jefe de|practicante|becari[oa]|estagi[áa]ri[oa]|engenheir[oa]|vendedor)\b|"
                            r"\((?:m/w/d|w/m/d|m/f/d|f/m/d|h/f|f/h|m/v|m/v/x|m/f/x)\)|\bh/f\b", re.I)


def non_english(title, text=""):
    """Is this posting written in another language (French, Spanish, German, Dutch, Portuguese, Italian)? Judged by
    its text when there is some (everyday words of that language far outnumber English ones), else by its title."""
    words = re.findall(r"[a-zà-ÿ]+", (text or "")[:1500].lower())
    if len(words) >= 40:
        en = sum(1 for w in words if w in _ENGLISH)
        best = max(sum(1 for w in words if w in s and w not in _ENGLISH) for s in _LANG.values())
        return best >= 8 and best > 2 * en
    return bool(_TITLE_FOREIGN.search(title or ""))


_TEXT_US = re.compile(r"\bUnited States\b|\bU\.S\.A?\b\.?|\bUSA\b|\bUS[- ](?:based|only|citizens?|residents?|work authorization|time zones?)\b|"
                      r"\b(?:authorized|eligible|eligibility|authorization) to work in the U|\bwithin the US\b|\banywhere in the US\b|"
                      r"\b(?:EST|CST|MST|PST|EDT|CDT|PDT|Eastern Time|Central Time|Pacific Time|Mountain Time)\b|\b401\s?\(?k\)?", re.I)
_TEXT_ABROAD = re.compile(r"(?:\bbased in|\blocated in|\bresid(?:e|es|ing|ent) (?:in|of)|\blive in|\bliving in|\bremote(?:ly)? (?:in|from|within|across)|"
                          r"\bright to work in|\beligible to work in|\bauthori[sz]ed to work in|\bwork permit for|"
                          r"\blocation\s*:|\bwork location\s*:|\bcountry\s*:)\s*(?:the |our )?([A-Z][^.\n;:(]{1,60})")
_TEXT_MONEY = re.compile(r"[€£₹]\s?\d|\b\d[\d,.]*\s?(?:EUR|GBP|CAD|AUD|INR|MXN|PLN|CHF|SEK|ZAR)\b|\b(?:EUR|GBP|CAD|AUD|INR|MXN|PLN|CHF|ZAR)\s?\$?\d|\bCA\$\s?\d|\bC\$\s?\d")


def text_us(text):
    """Does the posting's text say the job is in the US ("United States", "authorized to work in the U.S.", a US
    time zone, a 401(k))?"""
    return bool(_TEXT_US.search((text or "")[:8000]))


def text_abroad(text, is_foreign):
    """Does the posting's text place the job in another country: "based in Toronto", "remote within Canada", "right to
    work in the UK", "Location: Athens, Greece", pay in euros or pounds? is_foreign(place words) decides what is
    abroad (geo). Offices merely mentioned ("we have teams in London and Austin") don't count."""
    t = (text or "")[:8000]
    if _TEXT_MONEY.search(t):
        return True
    for m in _TEXT_ABROAD.finditer(t):
        if is_foreign(m.group(1)[:60]):
            return True
    return False


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
