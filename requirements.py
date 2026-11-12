"""Rule-based extraction of hard requirements (degree, licenses, certifications) from job postings, and a check
against a person's confirmed resume highlights (highlights.py).

    req = parse(desc, title)              # fast (~1 ms), no network; run on every job
    res = check(req, highlights.get(pid)) # {"status": "ok"|"flag"|"unmet", "reasons": [...], "chips": [...]}

Policy (conservative): "unmet" (hide) only when a requirement is explicitly required (required wording or a
required/minimum-qualifications section), has no "or equivalent experience"-style escape, and the person clearly
lacks it. Anything ambiguous is "flag". Preferred items the person lacks add a soft chip but keep status "ok".
Certifications never hide on their own (they're usually obtainable)."""
import re

from highlights import (ENG, RELATED, COUNTS_TOWARD, GENERIC_LABEL, GROUP_LABEL, LEVEL_RANK, field_groups_in)

VERSION = 1
I = re.I

# ------------------------------------------------------------------ degree tokens
_LV = [
    ("doctorate", r"ph\.?\s?d\b\.?s?|doctor(?:ate|al degree)|doctor of philosophy|\bd\.?sc\b|\bed\.d\b|\bpsy\.?d\b|\bdnp\b|\bpharm\.?\s?d\b"),
    ("md", r"\bm\.d\.|\bmd\s*/\s*do\b|\bmd or do\b|\bmd degree|doctor of medicine|medical degree|\bd\.o\.(?=\s)"),
    ("jd", r"\bj\.d\.|\bjd\b(?!\s+edwards)|juris doctor(?:ate)?|law degree"),
    ("master", r"master'?s\b|master’s|masters\b|master of\b|master degree|\bm\.s\.|\bm\.a\.|\bmsc\b|\bmba\b|\bm\.?eng\b|\bmpa\b|"
               r"\bmpp\b|\bmph\b|\bmsw\b|\bmsn\b|\bmfa\b(?=\s+(?:in|degree))|\bms(?:ee|me|cs|ce)\b|\bms\b(?=\s*(?:/|or\b|in\b|degree|,\s*ph))|"
               r"\bma\b(?=\s*(?:/|in\b|degree))|(?<!under)graduate degree|advanced degree|post-?graduate degree"),
    ("bachelor", r"bachelor'?s?\b|bachelor’s|baccalaureate|\bb\.s\.|\bb\.a\.|\bbsc\b|\bb\.?eng\b|\bbba\b|\bbsn\b|"
                 r"\bbs(?:ee|me|ce|cs|ie)\b|\bbs\b(?=\s*(?:/|or\b|in\b|degree|,))|\bba\b(?=\s*(?:/|or\b|in\b|degree))|"
                 r"undergraduate degree|college degree|university degree|(?:4|four)[- ]year (?:college |university )?degree"),
    ("associate", r"associate'?s? degree|associate’s degree|associates degree|\ba\.a\.(?=\s)|\ba\.s\. degree|"
                  r"associate(?:'s|’s)(?=\s+(?:of|in)\s)|associates?(?=\s+(?:of|in)\s+(?:nursing|science|arts|applied))|\badn\b|\basn\b"),
]
LV_RX = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _LV), I)
# A level token only counts when it reads like a credential (not "PhD researchers", "MS Office").
CRED_AFTER = re.compile(r"^(?:'s|’s|s)?\.?\s*(?:\(\w+\)\s*)?(?:$|degree|diploma|in\b|of\b|from|required|preferred|or\b|and\b|/|,|;|:|\.|\+|"
                        r"with\b|plus\b|\(|-|–|level|program|holder|candidate|student|completed|obtained)", I)
SPECIFIC_FIELD = {"bsee": "engineering-electrical", "msee": "engineering-electrical", "bsme": "engineering-mechanical",
                  "msme": "engineering-mechanical", "bsce": "engineering-civil", "msce": "engineering-civil",
                  "bscs": "computer-science", "mscs": "computer-science", "bsie": "engineering-other",
                  "bsn": "nursing", "msn": "nursing", "dnp": "nursing", "msw": "social-sciences", "mph": "life-sciences",
                  "adn": "nursing", "asn": "nursing"}
BARE_DEGREE = re.compile(r"\b(?:a|an|relevant|related|technical|stem|engineering|science|scientific|business|accredited|formal|"
                         r"appropriate|applicable)\s+(?:\w+\s+){0,2}?degree\b(?!\s+of\b)|\bdegree\s+(?:in|from)\s", I)
NOT_DEGREE = re.compile(r"degree of|degrees? (?:celsius|fahrenheit)|360|highest degree|some degree|varying degree|certain degree|"
                        r"high degree|great degree|to a degree|large degree|lesser degree", I)

PREF = re.compile(r"prefer|desired|desirable|nice[- ]to[- ]have|\ba plus\b|is a plus|are a plus|big plus|bonus|ideal(?:ly)?\b|"
                  r"advantage|helpful|beneficial|strongly considered|is valued|\bpreference\b|optional|recommended|"
                  r"encouraged|a strong plus|would be great|desire\b|\basset\b|not essential|not required|favou?rable|not necessary", I)
REQ = re.compile(r"\brequired\b|\bmust\b|\brequires?\b|\bminimum\b|\bat least\b|\bmandatory\b|\bessential\b|\bbasic qualif|"
                 r"\bneed to have\b|\bshall\b|\bmin\.? qualif", I)
EQUIV = re.compile(
    r"equivalent (?:work |professional |practical |relevant |related |industry |military |combination|years|experience|training)|"
    r"(?<!foreign )(?<!international )equivalent(?=\s*(?:\)|$|\.|;|,))|"
    r"in lieu|substitut|commensurate (?:work )?experience|"
    r"(?:\bor|and/or)\s+(?:an?\s+)?(?:additional\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\+?\s*(?:\(\d+\)\s*)?(?:\+\s*)?(?:additional\s+)?(?:years|yrs)|"
    r"(?:\bor|and/or)\s+(?:an?\s+)?(?:(?-i:PMP|CPA|CFA|CMA|ACCA|CISSP|CIA|CISA|PE)\b|professional certification|equivalent certification|relevant certification)|"
    r";\s*or\b(?![^;]{0,120}(?:degree|bachelor|master|ph\.?d|doctor|associate|\b[bm]\.?[sa]\.?\b|mba))|"
    r"high school|\bged\b|or (?:comparable|relevant|related|equivalent|similar|professional|practical|demonstrated) (?:\w+ )?experience|"
    r"or experience\b|experience in lieu|may be considered|will be considered|or equivalent\b(?! (?:degree|field|discipline))|"
    r"or equivalent (?:field|discipline)? ?experience|years of (?:additional |relevant )?experience (?:as a substitute|instead)", I)
GLOBAL_EQUIV = re.compile(
    r"in lieu of (?:a |the )?(?:\w+ )?degree|experience (?:may|can|will) (?:be )?substitut|substitute for (?:a |the )?(?:\w+ )?degree|"
    r"equivalent (?:\w+ )?experience (?:will|may|can) be (?:considered|accepted|substituted)|degree (?:requirement )?(?:may|can) be waived|"
    r"additional (?:years of )?experience may be (?:considered|substituted)|years of experience as a substitute|"
    r"no degree required|degree not required|do not require a degree|don't require a degree|without a (?:college )?degree", I)
RELATED_RX = re.compile(r"relat|relevant|similar|equivalent field|appropriate|comparable|applicable|other (?:\w+ )?(?:field|discipline|area)|"
                        r"closely aligned|associated|allied|etc\b|such as", I)
GENERIC_RX = {
    "stem": re.compile(r"\bstem\b|science,? technology,? engineering", I),
    "quantitative": re.compile(r"quantitative|analytical (?:field|discipline)|numerate", I),
    "technical": re.compile(r"technical|scientific or engineering|technology (?:field|discipline)", I),
    "science": re.compile(r"\bsciences?\b(?! in\b)", I),
    "health": re.compile(r"health(?:care)? (?:field|discipline|profession)|clinical discipline", I),
    "any": re.compile(r"any (?:field|discipline|major|area of study)|all majors|field of study is open|regardless of (?:major|field)", I),
}
NAMED_SCIENCE = re.compile(r"(?:computer|political|data|social|information|physical|life|health|materials|earth|environmental|"
                           r"behavioral|cognitive|actuarial|nursing|exercise|natural|decision|management|animal|food|library|"
                           r"biomedical|atmospheric|marine|plant|veterinary|military|policy) sciences?|science,? technology", I)
FIELD_CUT = re.compile(r";|\.\s|\.$|\b(?:and|with|plus)\s+(?:a\s+)?(?:minimum|min\.?|at least|\d)|\+\s*\d|\bexperience\b|\byears?\b|"
                       r"\bor (?:an? )?(?:equivalent|comparable)\b|\bpreferred\b|\brequired\b|"
                       r"\bis a plus|\bfrom an? (?:accredited|recognized)", I)
# "Bachelor's degree, preferably in CS" -> the degree is required, the field only preferred
FIELD_PREF = re.compile(r"\(?,?\s*(?:preferably|ideally|preferred|with a preference for)\s+(?:in|a|an)\b[^;,)]*(?:,\s*[^;,)]*){0,4}\)?|"
                        r"\b(?:preferably|ideally)\b\s*(?:a |an |in )?(?:\w+[\s-]){0,3}(?:related )?(?:field|discipline|area)?", I)
FOREIGN = re.compile(r"\(?\bor (?:a |an |its )?(?:global|foreign|international|overseas) equivalent\)?", I)
PAREN_PREF = re.compile(r"\([^)]*(?:prefer|plus|desired)[^)]*\)", I)

# ------------------------------------------------------------------ licenses and certifications
LICENSES = [  # key, label, pattern (case-sensitive acronyms are wrapped in (?-i:...))
    ("RN", "RN license", r"registered nurse|(?-i:\bRN\b)|(?-i:\bR\.N\.)|nursing licen[sc]e"),
    ("LPN", "LPN license", r"(?-i:\bLPN\b)|licensed practical nurse"),
    ("NP", "Nurse Practitioner license", r"nurse practitioner|(?-i:\bA?PRN\b)|(?-i:\bCRNP\b)|(?-i:\bFNP\b)"),
    ("PA", "PA license", r"physician assistant|(?-i:\bPA-C\b)"),
    ("MDLIC", "medical license", r"medical licen[sc]e|licensed physician|licensed to practice medicine|board[- ]certified in|"
                                 r"board certification in|board[- ]eligible"),
    ("PHARM", "pharmacist license", r"pharmacist licen|licensed pharmacist|(?-i:\bRPh\b)"),
    ("PE", "PE license", r"professional engineer(?!ing)|(?-i:\bP\.E\.)(?![a-z])|(?-i:\bPE\b)(?=\s*(?:\)|,)?\s*(?:licen|required|preferred|registration|certif|stamp|eit\b))|"
                         r"(?-i:\bPE\b)\s+licen"),
    ("CPA", "CPA", r"(?-i:\bCPA\b)|certified public accountant"),
    ("BAR", "bar admission", r"admitted to (?:practice (?:law )?(?:in |before )?)?(?:the |a )?(?:[\w.]+\s){0,4}?bar\b|member (?:in good standing )?of (?:the |a )?(?:[\w.]+\s){0,4}?bar\b|"
                             r"bar admission|licensed to practice law|active (?:\w+ )?bar\b|bar membership|bar in good standing|"
                             r"admission to (?:the |a |practice in )?(?:[\w.]+\s){0,4}?bar\b|licensed attorney|(?:\w+ )?bar licen"),
    ("PATENT", "USPTO registration", r"registered (?:to practice )?(?:before the uspto|patent (?:attorney|agent))|uspto registration|patent bar"),
    ("SOCIAL", "clinical license (LCSW/LPC)", r"(?-i:\bL[IC]?CSW\b)|(?-i:\bLMSW\b)|(?-i:\bLPC\b)|licensed clinical social worker|"
                                              r"licensed professional counselor|licensed psychologist"),
    ("CDL", "CDL", r"(?-i:\bCDL\b)|commercial driver'?s licen"),
    ("FINRA", "FINRA license", r"(?-i:\bSeries (?:7|6|24|26|27|57|63|65|66|79|82|86|87|99)\b)|finra licen|finra registration"),
    ("TEACH", "teaching license", r"teaching (?:licen[sc]e|certificat)|teacher certification|teacher licen"),
    ("REALTY", "real estate license", r"real estate (?:salesperson |broker )?licen|licensed real estate"),
    ("INSUR", "insurance license", r"insurance (?:producer |agent )?licen|(?:life|property) (?:and|&) (?:health|casualty) licen"),
    ("ARCH", "architect license", r"licensed architect|architect(?:ural)? licen|registered architect"),
]
CERTS = [
    ("PMP", "PMP", r"(?-i:\bPMP\b)|project management professional"),
    ("CISSP", "CISSP", r"(?-i:\bCISSP\b)"),
    ("CISM", "CISM", r"(?-i:\bCISM\b)"),
    ("CISA", "CISA", r"(?-i:\bCISA\b)(?!\s*\()|certified information systems auditor"),
    ("CIA", "CIA (internal auditor)", r"certified internal auditor"),
    ("SECPLUS", "Security+", r"security\+|(?-i:\bIAT (?:level )?I{1,3}\b)|8570|8140"),
    ("CCNA", "Cisco cert", r"(?-i:\bCC[NI][AEP]\b)"),
    ("AWS", "AWS certification", r"aws certifi|aws certified|aws (?:solutions architect|developer|sysops)[- ](?:associate|professional)"),
    ("AZURE", "Azure certification", r"azure certifi|microsoft certified"),
    ("GCP", "Google Cloud certification", r"google cloud certifi|gcp certifi|professional cloud architect"),
    ("SFDC", "Salesforce certification", r"certified salesforce|salesforce certifi|salesforce (?:certified|administrator certification)|salesforce admin(?:istrator)? cert"),
    ("SCRUM", "Scrum certification", r"(?-i:\bCSM\b)|certified scrum|scrum ?master certif|(?-i:\bPSM\b)|(?-i:\bSAFe\b)|(?-i:\bCSPO\b)"),
    ("ITIL", "ITIL", r"(?-i:\bITIL\b)"),
    ("CFA", "CFA", r"(?-i:\bCFA\b)|chartered financial analyst"),
    ("CFP", "CFP", r"(?-i:\bCFP\b)|certified financial planner"),
    ("FRM", "FRM", r"(?-i:\bFRM\b)"),
    ("SHRM", "SHRM/HRCI", r"(?-i:\bSHRM-S?CP\b)|(?-i:\bS?PHR\b)"),
    ("SIXSIGMA", "Six Sigma", r"six sigma|lean six"),
    ("CMA", "CMA", r"certified management accountant"),
    ("CPHQ", "CPHQ", r"(?-i:\bCPHQ\b)"),
    ("CIPP", "CIPP", r"(?-i:\bCIPP\b)"),
    ("CFE", "CFE", r"certified fraud examiner|(?-i:\bCFE\b)"),
]
LIC_RX = [(k, lab, re.compile(p, I)) for k, lab, p in LICENSES]
CERT_RX = [(k, lab, re.compile(p, I)) for k, lab, p in CERTS]
LIC_ANY = re.compile("|".join(f"(?:{p})" for _, _, p in LICENSES), I)
CERT_ANY = re.compile("|".join(f"(?:{p})" for _, _, p in CERTS), I)
CRED_WORD = re.compile(r"licen[sc]|admitted|admission|registration|certif|\bactive\b|\bcurrent\b|\bvalid\b|good standing|"
                       r"unrestricted|unencumbered|must (?:be|hold|have|possess)|\bhold\b|eligib|required|preferred|\bplus\b|desired", I)
NEG = re.compile(r"\b(?:not|no|n't|never)\s+(?:need|needed|required|necessary|have to|be required|essential|mandatory)|"
                 r"does not need|do not need|isn't required|is not required|not a requirement", I)
LIC_WORD = re.compile(r"licen[sc]|registration|registered|designation|certif|credential|\bactive\b|\bcurrent\b|\bvalid\b|"
                      r"good standing|must (?:be|hold|have|possess)|\bhold|\bpossess|unrestricted|unencumbered|qualification", I)
LIC_ESCAPE = re.compile(r"(?-i:\bor\s+\(?[A-Z]{3,})|eligib|ability to (?:obtain|acquire|get)|able to (?:obtain|acquire)|obtain(?:ed)? (?:within|by|prior|before|in)|"
                        r"within (?:\d+|one|two|three|six|nine|twelve|eighteen) (?:days|months|years?)|in the process|pending|"
                        r"willing(?:ness)? to (?:obtain|pursue|become)|waive in|reciprocity|compact|working towards?|pursuing|"
                        r"or (?:a |an )?(?:related|equivalent|similar)|in lieu|or equivalent|or (?:other )?relevant|"
                        r"\bor\b [^.;]{0,60}(?:certif|licen|degree|experience)", I)
SKIP_CLAUSE = re.compile(r"cpa firm|transfer of value|recruiting expenses|trademark|under license|licensee|licensing agreement|licensing deals|"
                         r"equal (?:employment )?opportunit|not a licensed|is not licensed|are not licensed|reimburse|tuition|we (?:will )?(?:pay|cover|sponsor|support)|"
                         r"(?:work|working|partner|collaborate|interface|coordinate|liaise)s? (?:closely )?(?:with|alongside)|team of|supervis(?:e|es|ing)|"
                         r"lead(?:s|ing)? a team|our (?:physicians|nurses|attorneys|engineers|lawyers)|"
                         r"\bjd edwards\b|bar chart|bar raiser|raise the bar|high bar|the bar for", I)
# several licenses named as alternatives in one requirement: "RN or LPN license", "LPN/RN", "RN, LPN or NP"
LIC_ALT = re.compile(r"\bor\b|/|\beither\b|\bany of\b|\bone of\b|such as|\blike\b|e\.g\.", I)
# "... will consider other designations like LPN": the license named is an accepted alternative, not one more requirement
LIC_CONSIDER = re.compile(r"\b(?:will|may|would|can)(?: also)? (?:be )?consider|\balso consider|\bconsider(?:ed|ing)? (?:other|an?|candidates)|"
                          r"other (?:designations?|licen[sc]es?|licensures?|credentials?)|\bor (?:other|another|similar|comparable) "
                          r"(?:designation|licen[sc]|credential)|\bin lieu of\b|\balso accept|\baccept(?:ed|able)? (?:alternatives?|as well)", I)
# A higher credential satisfies a lower one: a nurse practitioner holds an RN license, and an RN does (and may do)
# everything an LPN posting asks for.
LIC_COVERS = {"NP": {"RN", "LPN"}, "RN": {"LPN"}}
LIC_FAMILY = [{"RN", "LPN", "NP"}]
# The degree a license cannot be held without (so a profile that lists the license but no degree is not flagged for
# "Associate's in Nursing"): level, field group.
LIC_IMPLIES_DEGREE = {"RN": ("associate", "nursing"), "NP": ("master", "nursing"), "PE": ("bachelor", "engineering-other"),
                      "CPA": ("bachelor", "accounting"), "BAR": ("jd", "law"), "MDLIC": ("md", "medicine")}
JURIS = re.compile(r"\b(DC|D\.C\.|District of Columbia|Maryland|Virginia|New York|California|Texas|Illinois|Massachusetts|"
                   r"Pennsylvania|New Jersey|Florida|Washington|Georgia|Colorado|[A-Z][a-z]+) (?:state )?bar\b|\bbar (?:of|in) (?:the )?(?:state of )?([A-Z][\w.]+(?: [A-Z][a-z]+)?)")

# ------------------------------------------------------------------ section headers
H_PREF = re.compile(r"prefer|other qualif|other skills|favou?rable|asset|helpful|good to know|would be nice|nice[- ]to[- ]have|bonus|desired|desirable|\bplus(?:es)?\b|ideal|stand out|extra credit|additional qualif|"
                    r"good to have|great if|even better|we'?d love", I)
H_REQ = re.compile(r"require|minimum|basic qualif|must[- ]have|what you(?:'|’)?ll (?:need|bring)|what you bring|what you need|"
                   r"qualifications|who you are|you have|you bring|you(?:'|’)?ll have|skills (?:and|&) experience|"
                   r"experience (?:and|&) skills|\beducation\b|what we(?:'|’)?re looking for|what we look for|about you|"
                   r"you should have|you will have|you possess|skills|competencies|eligibility|knowledge", I)
H_OTHER = re.compile(r"responsibilit|what you(?:'|’)?ll do|duties|about (?:us|the|our)|benefit|perks|compensation|salary|pay range|"
                     r"why join|why work|who we are|our (?:team|company|mission|culture)|the role|overview|summary|equal|eeo|"
                     r"how to apply|location|travel|physical|working conditions|what we offer|you will|day to day|impact|"
                     r"in this role|accommodation|disclaimer|privacy|life at", I)
MIDLIST = re.compile(r"[a-z0-9.)!:] - (?=[A-Z0-9])")
HEADER_HINT = re.compile(r"qualif|require|prefer|must|need|bring|have|bonus|plus|education|skills|look", I)
SENT_SPLIT = re.compile(r"(?<=[a-z0-9)][a-z0-9)][.!?])\s+(?=[A-Z•\-*])|\s+[•·●▪◦]\s+|\s{3,}")
BULLET = re.compile(r"^[\s\-–—*•·●▪◦o>]+\s*")
QUICK = re.compile(r"bachelor|master|degree|ph\.?d|doctor|\bb\.?[as]\.?\b|\bm\.?[as]\.?\b|\bmba\b|baccalaureate|\bjd\b|j\.d\.|licen|"
                   r"\bbar\b|\bRN\b|nurse|\bCPA\b|accountant|professional engineer|\bP\.?E\.?\b|certif|\bseries \d|\bCDL\b|"
                   r"cissp|\bpmp\b|security\+|8570|8140|itil|\bcsm\b|\bsafe\b|cfa|six sigma|\bphr\b|shrm|uspto|psychologist|"
                   r"social worker|lcsw|\blpc\b|\blpn\b|architect|pharmac|physician|\bbs\w{0,2}\b|\bms\w{0,2}\b|\bmp[ah]\b|\bmsw\b|\bbsn\b|\bmsn\b|"
                   r"\bdnp\b|\bmfa\b|\bmeng\b|\bbsc\b|\bmsc\b|\bbba\b", I)

def _header_state(line):
    """Return 'req' / 'pref' / 'other' if the line is a section header, else None. Also returns inline remainder."""
    s = BULLET.sub("", line).strip()
    head, rest = s, ""
    m = re.match(r"^([^:]{2,70}):\s*(.*)$", s)
    if m:
        head, rest = m.group(1), m.group(2)
    elif len(s) > 70 or s.endswith(".") or len(s.split()) > 9 or BULLET.match(line) or QUICK.search(s):
        return None, ""
    h = head.lower()
    if not m and LV_RX.search(h):
        return None, ""  # a bare "Bachelor's degree" bullet, not a header
    if H_PREF.search(h) and not re.search(r"required (?:and|&) preferred|minimum (?:and|&) preferred", h):
        return "pref", rest
    if re.search(r"required (?:and|&) preferred|minimum (?:and|&) preferred", h):
        return "mixed", rest
    if H_REQ.search(h):
        return "req", rest
    if H_OTHER.search(h):
        return "other", rest
    return (None, "") if m else ("other" if len(h.split()) <= 5 and not re.search(r"\d", h) else None, "")

def _strength(clause, section):
    if PREF.search(clause):
        # "Bachelor's required; Master's preferred" is split earlier; here a preference word wins unless the
        # clause also clearly says required for the same item (handled per segment below)
        return "preferred"
    if REQ.search(clause) or section == "req":
        return "required"
    if section == "pref":
        return "preferred"
    return "unclear"

def _clauses(text):
    """Yield (clause, section, next_clause) over the posting."""
    section = None
    lines = [l for l in re.split(r"\r?\n|<br\s*/?>", text or "")]
    # Amazon-style postings drop the "Basic/Preferred qualifications" headings and start each list mid-line
    # ("...across a team. - 5+ years ... - 2+ years of ..."): the 1st mid-line list is basic, the 2nd preferred.
    if not any(_header_state(l)[0] in ("req", "pref") for l in lines if len(l) < 90 and HEADER_HINT.search(l)):
        starts = [i for i, l in enumerate(lines) if MIDLIST.search(l) and not re.search(r"USD|annually|\$|\d,\d{3}", l)][:2]
        if starts and sum(1 for l in lines if l.lstrip().startswith("- ")) >= 2:
            marks = {}  # line index -> (header to insert before, split position or None)
            for n, i in enumerate(starts):
                if lines[i].lstrip().startswith("-"):
                    # already inside a bullet list: the mid-line list is "preferred", the block above it is "basic"
                    marks[i] = ("Preferred:", MIDLIST.search(lines[i]))
                    j = i
                    while j > 0 and lines[j - 1].strip() and lines[j - 1].lstrip().startswith("-"):
                        j -= 1
                    marks.setdefault(j, ("Requirements:", None)) if j != i else None
                else:
                    marks[i] = ("Requirements:" if not any(h == "Requirements:" for h, _ in marks.values()) else "Preferred:",
                                MIDLIST.search(lines[i]))
            new = []
            for i, l in enumerate(lines):
                if i in marks:
                    h, m = marks[i]
                    if m:
                        new += [l[:m.start() + 1], h, l[m.end() - 1:]]
                        continue
                    new.append(h)
                new.append(l)
            lines = new
    out = []
    for line in lines:
        if not line.strip():
            continue
        st, rest = _header_state(line)
        if st:
            section = st
            if not rest:
                continue
            line = rest
        for sent in SENT_SPLIT.split(line):
            sent = BULLET.sub("", sent).strip()
            if sent:
                # "X required; Y preferred" -> separate clauses
                for c in re.split(r";\s+|\s+(?=\bOR\b)", sent):
                    c = c.strip()
                    if not c:
                        continue
                    if out and re.match(r"^(?:or|OR|Or)\b", c) and out[-1][1] == section and len(out[-1][0]) < 400:
                        out[-1][0] += "; " + c  # an alternative belongs with the clause before it
                    else:
                        out.append([c, section])
    return out

# ------------------------------------------------------------------ degree parsing
def _fields(region, prefix=""):
    region = FIELD_PREF.sub(" ", FOREIGN.sub(" ", PAREN_PREF.sub(" ", region)))
    region = re.sub(r"^\W*(?:degree\s+)?of\s+(?:applied\s+)?(?:science|arts)\b(?!\s+in\b)(?:\s+degree)?", " ", region, flags=I)
    m = FIELD_CUT.search(region)
    if m:
        region = region[:m.start()]
    named_region = region
    # Only the part after "in/of/within/:" names the field; also "technical degree" / "STEM bachelor's"
    fm = re.search(r"^\W*(?:degree\s+)?of\s+(.*)$|\b(?:in|within|:)\s+(.*)$", region, I)
    field_text = (fm.group(1) or fm.group(2) or "") if fm else ""
    pre_text = (prefix[-30:] + " " + region[:fm.start()] if fm else prefix[-30:] + " " + region)
    pre_text = re.sub(r"(?i)master|bachelor|degree|science(?= in)", " ", pre_text)
    groups, generic = [], []
    for txt in (field_text, pre_text):
        if not txt.strip():
            continue
        for k, rx in GENERIC_RX.items():
            if k == "science":
                if rx.search(NAMED_SCIENCE.sub(" ", txt)) and k not in generic:
                    generic.append(k)
            elif rx.search(txt) and k not in generic:
                generic.append(k)
        t2 = GENERIC_RX["technical"].sub(" ", GENERIC_RX["quantitative"].sub(" ", txt))
        if txt is pre_text:
            # words before the token: only an obvious field adjective ("engineering degree", "business degree")
            mm = re.search(r"\b(engineering|business|accounting|finance|nursing|law|computer science|economics|"
                           r"mechanical engineering|electrical engineering|civil engineering)\s*(?:degree|$)", t2, I)
            t2 = mm.group(1) if mm else ""
        for g in field_groups_in(t2):
            if g not in groups:
                groups.append(g)
    if "engineering" in field_text.lower() and "engineering_related" not in generic and re.search(r"\bengineering\b(?!\s+(?:management|technology))", field_text, I):
        if re.search(r"(?<!mechanical )(?<!electrical )(?<!civil )(?<!software )(?<!computer )(?<!systems )(?<!aerospace )(?<!chemical )(?<!industrial )\bengineering\b", field_text, I):
            generic.append("engineering_related")
    related = bool(RELATED_RX.search(field_text))
    return groups, generic, related, field_text.strip()[:120]

def _degree_stmt(clause, section, next_clause):
    toks = []
    for m in LV_RX.finditer(clause):
        after = clause[m.end(): m.end() + 30]
        if not CRED_AFTER.match(after):
            continue
        toks.append((m.start(), m.end(), m.lastgroup, m.group(0)))
    implied = False
    if not toks:
        bm = BARE_DEGREE.search(clause)
        if not bm or NOT_DEGREE.search(clause[max(0, bm.start() - 20): bm.end() + 20]) or \
                re.search(r"(?:lieu of|substitute for|instead of|without|not require|no)\s+(?:a |the )?(?:\w+ )?$", clause[:bm.start()], I):
            return []
        toks = [(bm.start(), bm.end(), "bachelor", bm.group(0))]
        implied = True
    # One alternative per level token; tokens between explicit strength words form one statement.
    clause_has_req = bool(REQ.search(clause))
    stmts, cur = [], None
    for i, (s, e, lv, word) in enumerate(toks):
        seg_end = toks[i + 1][0] if i + 1 < len(toks) else len(clause)
        seg = clause[s:seg_end]
        st = None
        if clause_has_req:  # "Bachelor's required, Master's preferred": strength per segment
            seg_s = FIELD_PREF.sub(" ", seg)
            st = "preferred" if PREF.search(seg_s) else ("required" if REQ.search(seg_s) else None)
        groups, generic, related, ftxt = _fields(clause[e:seg_end] if not implied else clause[s:seg_end], clause[:s])
        sf = SPECIFIC_FIELD.get(re.sub(r"[^a-z]", "", word.lower()))
        if sf and sf not in groups:
            groups.append(sf)
        alt = {"level": lv, "fields": groups, "generic": generic, "related": related, "field_text": ftxt,
               "_short": len(clause[e:seg_end].strip(" ,/-")) <= 22}
        if cur and (st is None or st == cur["_st"] or cur["_st"] is None):
            cur["alts"].append(alt)
            cur["_st"] = cur["_st"] or st
        else:
            cur = {"_st": st, "alts": [alt]}
            stmts.append(cur)
    clause_st = _strength(FIELD_PREF.sub(" ", clause), section)
    out = []
    for s in stmts:
        st = s["_st"] or clause_st
        if st == "preferred" and s["_st"] is None and clause_has_req and not PREF.search(" ".join(a["field_text"] for a in s["alts"])) and len(stmts) > 1:
            st = "required"
        alts = s["alts"]
        # "Bachelor's or Master's in X": a bare alternative directly followed by "or" shares the next one's field
        for k in range(len(alts) - 2, -1, -1):
            if alts[k]["_short"] and not alts[k]["fields"] and not alts[k]["generic"]:
                for key in ("fields", "generic", "related", "field_text"):
                    alts[k][key] = alts[k + 1][key]
        for x in alts:
            x.pop("_short", None)
        lvls = [x["level"] for x in alts]
        level = min(lvls, key=lambda l: LEVEL_RANK[l])
        ctx = clause + " " + (next_clause or "")
        equiv = bool(EQUIV.search(clause) or (next_clause and re.match(r"^\s*or\b", next_clause, I) and EQUIV.search(ctx)))
        if any(l == "bachelor" for l in lvls) and re.search(r"\b(?:or|and/or)\s+(?:an?\s+)?associate", clause, I):
            level = "associate"
            alts.append({"level": "associate", "fields": [], "generic": [], "related": False, "field_text": ""})
        fields = list(dict.fromkeys(f for x in alts for f in x["fields"]))
        generic = list(dict.fromkeys(g for x in alts for g in x["generic"]))
        out.append({"level": level, "alt_levels": sorted(set(lvls), key=lambda l: LEVEL_RANK[l]), "alts": alts,
                    "fields": fields, "generic": generic, "related": any(x["related"] for x in alts),
                    "field_text": next((x["field_text"] for x in alts if x["field_text"]), ""),
                    "equiv": equiv, "strength": st, "implied": implied, "text": clause[:220]})
    return out

def _find(rx_list, clause):
    return [(k, lab, m) for k, lab, rx in rx_list for m in [rx.search(clause)] if m]

# Literal anchors (lowercase substrings, and case-sensitive ones) that must appear for a pattern to match at all.
# Checked with plain `in`, which is far cheaper than running dozens of case-insensitive regexes over every posting.
ANCHORS = {
    "RN": (["registered nurse", "nursing licen"], ["RN", "R.N."]), "LPN": (["licensed practical"], ["LPN"]),
    "NP": (["nurse practitioner"], ["PRN", "CRNP", "FNP"]), "PA": (["physician assistant"], ["PA-C"]),
    "MDLIC": (["medical licen", "licensed physician", "practice medicine", "board"], []),
    "PHARM": (["pharmacist"], ["RPh"]), "PE": (["professional engineer"], ["P.E.", "PE "]),
    "CPA": (["certified public"], ["CPA"]), "BAR": (["bar", "practice law", "licensed attorney"], []),
    "PATENT": (["uspto", "patent"], []), "SOCIAL": (["social worker", "professional counselor", "licensed psychologist"], ["CSW", "LMSW", "LPC"]),
    "CDL": (["commercial driver"], ["CDL"]), "FINRA": (["finra"], ["Series "]), "TEACH": (["teach"], []),
    "REALTY": (["real estate"], []), "INSUR": (["insurance", "casualty licen", "health licen"], []),
    "ARCH": (["architect"], []),
    "PMP": (["project management professional"], ["PMP"]), "CISSP": ([], ["CISSP"]), "CISM": ([], ["CISM"]),
    "CISA": (["information systems auditor"], ["CISA"]), "CIA": (["internal auditor"], []),
    "SECPLUS": (["security+", "8570", "8140"], ["IAT"]), "CCNA": ([], ["CCN", "CCI"]), "AWS": (["aws"], []),
    "AZURE": (["azure certifi", "microsoft certified"], []), "GCP": (["google cloud certifi", "gcp certifi", "professional cloud architect"], []),
    "SFDC": (["salesforce"], []), "SCRUM": (["scrum"], ["CSM", "PSM", "SAFe", "CSPO"]), "ITIL": ([], ["ITIL"]),
    "CFA": (["chartered financial"], ["CFA"]), "CFP": (["financial planner"], ["CFP"]), "FRM": ([], ["FRM"]),
    "SHRM": ([], ["SHRM", "PHR"]), "SIXSIGMA": (["six sigma"], []), "CMA": (["management accountant"], []),
    "CPHQ": ([], ["CPHQ"]), "CIPP": ([], ["CIPP"]), "CFE": (["fraud examiner"], ["CFE"]),
}
DEG_CI = ("associate's", "associate’s", "associate of", "associates of", "associate in", "associates in", "bachelor", "master", "degree", "ph.d", "phd", "doctor", "baccalaureate", "b.s.", "b.a.", "m.s.", "m.a.", "mba",
          "juris", "j.d.", "bsc", "msc", "m.eng", "meng", "b.eng", "bba", "bsn", "msn", "mph", "mpa", "mpp", "msw", "dnp",
          "pharm", "a.a.", "m.d.", "d.o.", "psy.d", "ed.d", "d.sc", "dsc")
DEG_CS = ("BS", "BA", "MS", "MA", "JD", "MD", "ADN", "ASN")

def _active(text, low, entries):
    out = []
    for k, lab, rx in entries:
        ci, cs = ANCHORS.get(k, ([], []))
        if any(a in low for a in ci) or any(a in text for a in cs):
            out.append((k, lab, rx, ci, cs))
    return out

def _has_deg(c, cl):
    return any(a in cl for a in DEG_CI) or any(a in c for a in DEG_CS)

def parse(desc, title=""):
    """Requirements found in a posting. Pure regex; returns a small JSON-able dict."""
    text = desc or ""
    req = {"v": VERSION, "degrees": [], "licenses": [], "certs": [], "global_equiv": False}
    low = text.lower()
    has_deg = _has_deg(text, low)
    lic, cert = _active(text, low, LIC_RX), _active(text, low, CERT_RX)
    if not (has_deg or lic or cert):
        return req
    cl = _clauses(text)
    for i, (c, section) in enumerate(cl):
        c_low = c.lower()
        if has_deg and _has_deg(c, c_low):
            nxt = cl[i + 1][0] if i + 1 < len(cl) else ""
            req["degrees"] += _degree_stmt(c, section, nxt)
        lic_c = [(k, lab, rx) for k, lab, rx, ci, cs in lic if any(a in c_low for a in ci) or any(a in c for a in cs)]
        cert_c = [(k, lab, rx) for k, lab, rx, ci, cs in cert if any(a in c_low for a in ci) or any(a in c for a in cs)]
        if not (lic_c or cert_c) or SKIP_CLAUSE.search(c):
            continue
        if lic_c:
            found = _find(lic_c, c)
            keys_here = [k for k, _, _ in found]
            consider = bool(LIC_CONSIDER.search(c))
            for k, lab, m in found:
                rest = c[:m.start()] + " " + c[m.end():]
                if not CRED_WORD.search(rest) and section not in ("req", "pref"):
                    continue
                if NEG.search(c) or (k not in ("BAR", "MDLIC") and not LIC_WORD.search(rest) and len(c) > 60):
                    continue
                if k == "BAR" and re.search(r"\bbar\b", m.group(0), I) and not re.search(r"admit|admission|member|licen|good standing|active|practice", c, I):
                    continue
                item = {"key": k, "label": lab, "strength": _strength(c, section), "escape": bool(LIC_ESCAPE.search(c)),
                        "text": c[:220]}
                others = [x for x in keys_here if x != k]
                if others and (consider or LIC_ALT.search(c)):
                    item["alts"] = others       # "RN or LPN license": holding either one meets it
                if consider:
                    item["consider"] = True     # "will consider ... like LPN": an alternative the employer accepts
                    item["escape"] = True
                if k == "BAR":
                    jm = JURIS.search(c)
                    item["jurisdiction"] = (jm.group(1) or jm.group(2) or "").strip() if jm else ""
                    if item["jurisdiction"].lower() in ("the", "a", "any", "state", "active"):
                        item["jurisdiction"] = ""
                if not any(x["key"] == k and x["strength"] == item["strength"] for x in req["licenses"]):
                    req["licenses"].append(item)
        if cert_c:
            for k, lab, m in _find(cert_c, c):
                rest = c[:m.start()] + " " + c[m.end():]
                if not CRED_WORD.search(rest + " " + m.group(0)) and section not in ("req", "pref"):
                    continue
                item = {"key": k, "label": lab, "strength": _strength(c, section), "escape": bool(LIC_ESCAPE.search(c)),
                        "text": c[:220]}
                if not any(x["key"] == k and x["strength"] == item["strength"] for x in req["certs"]):
                    req["certs"].append(item)
    if req["degrees"]:
        req["global_equiv"] = bool(GLOBAL_EQUIV.search(text))
    return req

# ------------------------------------------------------------------ check
LEVEL_SHORT = {"associate": "Associate's", "bachelor": "Bachelor's", "master": "Master's", "doctorate": "PhD",
               "jd": "JD", "md": "MD"}

def _level_ok(have, need):
    if need == "jd":
        return "yes" if have == "jd" else "no"
    if need == "md":
        return "yes" if have == "md" else "no"
    if have in ("jd", "md") and need in ("master", "doctorate"):
        return "maybe"
    return "yes" if LEVEL_RANK[have] >= LEVEL_RANK[need] else "no"

def _field_ok(group, stmt):
    fields, generic = stmt["fields"], stmt["generic"]
    if not fields and not generic:
        return "yes"  # no named field ("in a relevant field") -> only the level matters
    if "any" in generic:
        return "yes"
    if group in fields or (group in ENG and ("engineering-other" in fields or "engineering_related" in generic)):
        return "yes"
    best = "no"
    for g in generic:
        ct = COUNTS_TOWARD.get(g)
        if not ct:
            continue
        if group in ct["yes"]:
            return "yes"
        if group in ct["maybe"]:
            best = "maybe"
    if stmt["related"]:
        rel = set()
        for f in fields:
            rel |= RELATED.get(f, set())
        if "engineering_related" in generic:
            rel |= COUNTS_TOWARD["engineering_related"]["yes"]
        if group in rel:
            return "yes"
        if not fields:
            return "maybe"
        if (set(fields) - HARD_FIELDS) and not (set(generic) & HARD_GENERIC):
            return "maybe"  # soft-field postings ("business, HR or related") read "related" loosely
    if best == "no" and any(group in RELATED.get(f, set()) for f in fields):
        best = "maybe"  # a neighbouring field (CS for "Electrical Engineering", hospitality for "Business") -> flag, not hide
    if group == "other":
        best = "maybe"
    return best

HARD_FIELDS = ENG | {"computer-science", "math-stats", "physical-sciences", "life-sciences", "nursing", "medicine", "law", "accounting"}
HARD_GENERIC = {"stem", "technical", "quantitative", "science", "health"}
ORDER = {"no": 0, "maybe": 1, "yes": 2}

def _degree_match(stmt, degrees):
    best = "no"
    for alt in stmt.get("alts") or [stmt]:
        for d in degrees:
            if d.get("completed") is False:
                continue
            lv = _level_ok(d["level"], alt["level"])
            fo = _field_ok(d.get("field_group") or "other", alt)
            r = min(lv, fo, key=ORDER.get)
            if ORDER[r] > ORDER[best]:
                best = r
                if best == "yes":
                    return best
    return best

def _field_label(stmt):
    names = [GENERIC_LABEL[g] for g in stmt["generic"] if g != "any"] + [GROUP_LABEL[f] for f in stmt["fields"]]
    names = list(dict.fromkeys(names))
    if not names:
        return ""
    lab = "/".join(names[:2]) + ("…" if len(names) > 2 else "")
    return " in " + lab

def _deg_chip(stmt, escape, verb="Requires"):
    lv = "/".join(LEVEL_SHORT[l] for l in stmt.get("alt_levels", [stmt["level"]])[:2]) if verb == "Requires" else LEVEL_SHORT[stmt["level"]]
    lv = LEVEL_SHORT[stmt["level"]] + ("+" if len(stmt.get("alt_levels", [])) > 1 else "") if verb == "Requires" else lv
    s = f"{verb} {lv}{_field_label(stmt)}"
    if stmt["related"] and stmt["fields"]:
        s += " (or related)"
    if escape:
        s += " (or equivalent)"
    return s

LIC_DEGREE = {"RN": {"nursing"}, "LPN": {"nursing"}, "NP": {"nursing"}, "PE": ENG, "CPA": {"accounting", "finance", "business"},
              "PHARM": {"medicine"}, "SOCIAL": {"social-sciences"}, "ARCH": {"arts-design"}}
LIC_LEVEL = {"BAR": "jd", "PATENT": None, "MDLIC": "md", "PA": "master"}

def _canon(items, rx_list):
    keys = set()
    for x in items:
        nm = (x.get("name") if isinstance(x, dict) else str(x)) or ""
        for k, _, rx in rx_list:
            if rx.search(nm):
                keys.add(k)
        if re.search(r"\bbar\b|attorney|admitted", nm, I):
            keys.add("BAR")
    return keys

def check(req, hl):
    """Compare parsed requirements with a person's highlights. hl=None -> everything ok (nothing known)."""
    res = {"status": "ok", "reasons": [], "chips": [], "soft": []}
    if not hl or not req:
        return res
    degrees = list(hl.get("degrees") or [])
    have_lic = _canon(hl.get("licenses") or [], LIC_RX)
    for k in sorted(have_lic):     # a license implies the degree it takes to hold it
        imp = LIC_IMPLIES_DEGREE.get(k)
        if imp and not any(d.get("completed") is not False and LEVEL_RANK.get(d.get("level"), 0) >= LEVEL_RANK[imp[0]]
                           and d.get("field_group") == imp[1] for d in degrees):
            degrees.append({"level": imp[0], "field": "", "field_group": imp[1], "completed": True, "_implied": True})
    for k in list(have_lic):       # a higher license covers the lower ones (RN >= LPN)
        have_lic |= LIC_COVERS.get(k, set())
    status = "ok"
    def bump(s):
        nonlocal status
        if s == "unmet" or (s == "flag" and status == "ok"):
            status = s

    # ---- degrees: required statements are alternatives; any satisfied one clears the degree requirement
    stmts = req.get("degrees") or []
    hard = [s for s in stmts if s["strength"] == "required"] or [s for s in stmts if s["strength"] == "unclear"]
    if hard:
        matches = [(s, _degree_match(s, degrees) if degrees else "maybe") for s in hard]
        if not any(m == "yes" for _, m in matches):
            outcomes = []
            for s, m in matches:
                esc = s["equiv"] or req.get("global_equiv")
                if m == "no" and s["strength"] == "required" and not esc:
                    outcomes.append("unmet")
                else:
                    outcomes.append("flag")
            worst = "unmet" if all(o == "unmet" for o in outcomes) else "flag"
            # describe the easiest one to meet (lowest level)
            s0 = min(hard, key=lambda s: (LEVEL_RANK[s["level"]], len(s["fields"]) == 0))
            esc0 = s0["equiv"] or req.get("global_equiv")
            chip = _deg_chip(s0, esc0)
            res["chips"].append(chip)
            have = "; ".join(f'{LEVEL_SHORT[d["level"]]} {d.get("field") or ""}'.strip() for d in degrees if not d.get("_implied")) or "no degree on file"
            why = "no equivalent-experience option" if worst == "unmet" else (
                "equivalent experience accepted" if esc0 else "not clearly required" if s0["strength"] == "unclear" else "field/level unclear")
            res["reasons"].append(f'Degree: posting says "{s0["text"][:160]}" - you have {have} ({why}).')
            bump(worst)
    for s in [s for s in stmts if s["strength"] == "preferred"]:
        if degrees and _degree_match(s, degrees) != "yes":
            c = _deg_chip(s, False, verb="Prefers")
            if c not in res["soft"]:
                res["soft"].append(c)

    # ---- licenses
    lic_names = " ".join((x.get("name") or "") for x in hl.get("licenses") or [])
    groups = {d.get("field_group") for d in degrees}
    levels = {d.get("level") for d in degrees}
    # licenses the posting says it will consider instead ("will consider other designations like LPN")
    considered = {L["key"] for L in req.get("licenses") or [] if L.get("consider")} & have_lic
    for L in req.get("licenses") or []:
        k = L["key"]
        if k not in have_lic and (set(L.get("alts") or []) & have_lic
                                  or any(k in fam and considered & fam for fam in LIC_FAMILY)):
            continue    # an alternative the posting names is held: "RN or LPN", or the considered license
        if k in have_lic:
            if k == "BAR" and L.get("jurisdiction") and L["jurisdiction"].lower().replace(".", "") not in lic_names.lower().replace(".", ""):
                if L["strength"] == "required":
                    res["chips"].append(f'Requires {L["jurisdiction"]} bar (yours: other state)')
                    res["reasons"].append(f'License: "{L["text"][:160]}" - your bar admission may be in another jurisdiction.')
                    bump("flag")
            continue
        if L["strength"] == "preferred":
            res["soft"].append(f'{L["label"]} preferred')
            continue
        plausible = bool(groups & LIC_DEGREE.get(k, set())) or (LIC_LEVEL.get(k) in levels if LIC_LEVEL.get(k) else False)
        label = (f'{L["jurisdiction"]} bar admission' if k == "BAR" and L.get("jurisdiction") else L["label"])
        if L["strength"] == "required" and not L["escape"] and not plausible:
            res["chips"].append(f"Requires {label}")
            res["reasons"].append(f'License: "{L["text"][:160]}" - not in your highlights.')
            bump("unmet")
        else:
            res["chips"].append(f"Requires {label}" + (" (or eligible)" if L["escape"] else ""))
            res["reasons"].append(f'License: "{L["text"][:160]}" - not in your highlights' +
                                  (" (posting allows obtaining it)" if L["escape"] else " (add it if you hold it)") + ".")
            bump("flag")

    # ---- certifications: never hide
    have_cert = _canon(hl.get("licenses") or [], CERT_RX)
    for C in req.get("certs") or []:
        if C["key"] in have_cert:
            continue
        if C["strength"] == "required" and not C["escape"]:
            res["chips"].append(f'Requires {C["label"]}')
            res["reasons"].append(f'Certification: "{C["text"][:160]}" - not in your highlights.')
            bump("flag")
        elif C["strength"] == "preferred" and len(res["soft"]) < 6:
            res["soft"].append(f'{C["label"]} preferred')
    res["status"] = status
    res["chips"] = list(dict.fromkeys(res["chips"]))[:4]
    res["soft"] = list(dict.fromkeys(res["soft"]))[:4]
    return res

def annotate(job, text, hl):
    """Convenience for jobfinder: parse once (cached on the job by text length) and check."""
    if job.get("req", {}).get("v") != VERSION or job.get("_req_len") != len(text or ""):
        job["req"] = parse(text, job.get("title", ""))
        job["_req_len"] = len(text or "")
    r = check(job["req"], hl)
    job["req_status"], job["req_chips"], job["req_soft"], job["req_reasons"] = r["status"], r["chips"], r["soft"], r["reasons"]
    return r
