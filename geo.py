#!/usr/bin/env python3
"""Offline US geocoding for job-location strings: real distance instead of a hard-coded place list.

Data (data/geo/, ~4 MB, built once by data/agent_work/geo/build_gazetteer.py from public-domain Census files:
https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_{place,cousubs,zcta,counties}_national.zip,
2010 Gaz_places/Gaz_cousubs (CDP populations), popest sub-est2023.csv; plus USPS postal city names from GeoNames
https://download.geonames.org/export/zip/US.zip, CC BY 4.0 - keep the attribution in places.tsv):
  places.tsv   name, state, lat, lon, population, kind (p=place/CDP, c=active county subdivision / New England town,
               z=postal city name only, e.g. "Hanover, MD")
  zcta.tsv     ZIP (ZCTA) internal points + postal city label
  states.tsv   state centroids
  counties.tsv county name (without "County"), state, internal point, land area (sq mi): Census Gazetteer 2024
               counties (public domain). "Franklin County, OH" resolves to the county (kind "county", radius = the
               county's rough radius), never to a same-named town.
  aliases.json hand-curated aliases (Fort Meade, NYC...), metro phrases (Bay Area, Twin Cities...),
               foreign markers

API
  geocode_home("10001") / geocode_home("Austin, TX") -> (lat, lon, label)
  locate("US-TX-Austin") -> (lat, lon, confidence) | None
  locate_all(s) -> [Hit(lat, lon, conf, kind, label, radius_mi)]   kind: zip|place|alias|metro|county|state
  within(["McLean, VA", "Remote"], home, 35) -> (bool, nearest_miles|None, [matched strings])
  miles(lat1, lon1, lat2, lon2)
"""
import functools, json, math, os, re, threading, unicodedata
from collections import namedtuple

import paths
GEO = paths.asset("geo")
Hit = namedtuple("Hit", "lat lon conf kind label radius")   # radius only for metro hits

STATES = {"AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
          "CT": "connecticut", "DE": "delaware", "DC": "district of columbia", "FL": "florida", "GA": "georgia", "HI": "hawaii",
          "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
          "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
          "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey",
          "NM": "new mexico", "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
          "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina", "SD": "south dakota",
          "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
          "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming", "PR": "puerto rico"}
STATE_WORDS = {v: k for k, v in STATES.items()}
STATE_WORDS.update({"calif": "CA", "mass": "MA", "penn": "PA", "wash": "WA", "virgina": "VA", "dist of columbia": "DC"})
# two-letter codes that are also common English words: only trusted when written in capitals or as a whole segment
WEAK_CODES = {"IN", "OR", "ME", "OH", "HI", "OK", "DE", "AL", "LA", "ID", "MA", "PA", "CO", "GA", "MO", "NE", "SD", "MS", "MT", "WA"}
COUNTRY = {"us", "usa", "u s", "u s a", "united states", "united states of america", "america", "amer", "americas", "north america"}
STOP = set("""remote virtual home office hq headquarters corporate corp campus center centre main field site hybrid flexible anywhere
nationwide multiple various all any location locations cities zone metro area region greater north south east west central
northern southern eastern western midwest union national federal government customer client work from at the of and or in on
telework teleworker onsite travel required only job requisitions friendly based unavailable external internal outpatient hospital
university college school medical plaza tower building floor suite ste dr rd ave blvd pkwy way lane court inc llc distributed
global worldwide offsite cust office space commerce industry mission bell new city county state usa us amer opportunity
contingent pending tbd to be determined other various multiple open hub cloud lower middle upper capital republic liberty""".split())
# never a place name, even next to a state
HARD_STOP = set("remote virtual home office hq headquarters corporate corp campus hybrid field site flexible anywhere all any "
                "nationwide multiple various unavailable undisclosed telework teleworker onsite offsite distributed".split())
# a name followed by one of these is an institution, not a place ("Howard University", "Liberty Mutual")
INSTITUTION = set("university college hospital mutual insurance bank health school medical clinic institute".split())
FOREIGN_CODES = re.compile(r"(?<![A-Za-z])(BC|ON|QC|AB|NS|NB|MB|SK|NL|PE|PEI|NT|YT|GB|GBR|CAN|CRI|POL|MEX|BRA|DEU|FRA|ESP|AUS|JPN)(?![A-Za-z])")

# ------------------------------------------------------------------ "is this place outside the US?"
# Used by the fetch pipeline (jobfinder.is_foreign) and the directory builder. Whole words only, and a label that ends in
# a US state or "United States" is never foreign: "Dublin, OH", "Paris, TX", "Indianapolis, Indiana", "New Mexico".
# Two-letter state codes that are also country codes ("Hyderabad, TG, IN", "Toronto, ON, CA") are trusted only when the
# place before them is a known town in that state ("Brazil, IN", "London, KY", "Berlin, MD").
_CODE_CLASH = {"IN", "CA", "AL", "AR", "AZ", "CO", "DE", "GA", "ID", "IL", "KY", "LA", "MA", "MD", "ME", "MN", "MO", "MS",
               "MT", "NC", "NE", "PA", "SC", "SD", "TN", "VA"}
_US_TAIL = re.compile(r"(?:^|[\s,;(\-/|])(?:u\s?s\s?a?|united states(?: of america)?)\s*\)?\s*$")
_US_HEAD = re.compile(r"^\s*(?:us|usa|united states(?: of america)?)\s*[-/,:]")
_SEG = re.compile(r"\s*[,;/|()]\s*|\s+-\s+")
_FOREIGN_EXTRA = ("vancouver", "emea", "apac", "europe", "latam", "korea", "taiwan", "united kingdom", "uk",
                  "latin america", "south america", "asia pacific")

@functools.lru_cache(maxsize=1)
def _foreign_rx():
    try:
        words = json.load(open(os.path.join(GEO, "aliases.json"))).get("foreign", [])
    except Exception:
        words = []
    words = sorted({_key(x) for x in list(words) + list(_FOREIGN_EXTRA)} - {""}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(x) for x in words) + r")(?![a-z0-9])")

def _known_in_state(place, st):
    try:
        return any(r[0] == st for r in _load()["names"].get(_key(place), []))
    except Exception:
        return False

def _us_tail(label):
    """True when the label ends in a US state, a US ZIP or "United States" (or starts with "US-")."""
    raw = re.sub(r"[\s.]*$", "", norm(label, keep_case=True))
    raw = re.sub(r"\s*\(?\b\d{5}(?:-\d{4})?\)?$", "", raw).strip(" ,;-")
    low = raw.lower().replace(".", "")
    if _US_TAIL.search(low) or _US_HEAD.match(low):
        return True
    segs = [s for s in _SEG.split(raw) if s and s.strip()]
    if not segs:
        return False
    last = segs[-1].strip()
    words = _key(last).split()
    for n in range(min(4, len(words)), 0, -1):          # "Indianapolis, Indiana", "Santa Fe New Mexico"
        name = " ".join(words[-n:])
        if name in STATE_WORDS and name != "georgia":
            return True
        if name == "georgia":                           # the US state, unless it's Tbilisi
            return "tbilisi" not in low
    code = last.split()[-1] if last.split() else ""
    if len(code) == 2 and code.upper() in STATES and (code.isupper() or len(segs) > 1):
        code = code.upper()
        if code not in _CODE_CLASH:
            return True
        place = segs[-2] if len(segs) > 1 else " ".join(last.split()[:-1])
        return _known_in_state(place, code)
    return False

def looks_foreign(label):
    """Does this location label name a place outside the US? ("Dublin, Ireland" yes, "Dublin, OH" no, "Remote" no)"""
    if not label or not str(label).strip():
        return False
    label = str(label)
    flat = re.sub(r"\bnew (?:mexico|jersey|england)\b", " ", _key(label))
    hit = bool(_foreign_rx().search(flat))
    if not hit:
        hit = any(FOREIGN_CODES.fullmatch(s.strip()) for s in _SEG.split(label) if s and s.strip())
    return hit and not _us_tail(label)

def norm(s, keep_case=False):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\b[dD]\.\s?[cC]\.?(?![A-Za-z])", "DC", s)
    s = re.sub(r"(?i)\bdistrict of columbia\b", "DC", s)
    s = re.sub(r"(?i)\bu\.s\.a\b\.?|\bu\.s\.(?=\W|$)", "USA", s)
    s = re.sub(r"(?i)\bst\.?\s+(?=[a-z])", "saint ", s)
    s = re.sub(r"(?i)\bste\.\s+(?=[a-z])", "sainte ", s)
    s = re.sub(r"(?i)\bft\.?\s+(?=[a-z])", "fort ", s)
    s = re.sub(r"(?i)\bmt\.?\s+(?=[a-z])", "mount ", s)
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    return s if keep_case else s.lower()

def _key(s):
    """Normalized lookup key for a single name."""
    s = norm(s).replace(".", " ").replace("-", " ")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())

# ------------------------------------------------------------------ data
_D = {}
_LOCK = threading.Lock()

def _load():
    if _D:
        return _D
    with _LOCK:
        if not _D:
            _D.update(_read())
    return _D

def _read():
    names = {}                     # key -> [(state, lat, lon, pop, kind)]
    with open(os.path.join(GEO, "places.tsv")) as f:
        for line in f:
            if line.startswith("#"):
                continue
            n, st, la, lo, p, k = line.rstrip("\n").split("\t")
            names.setdefault(_key(n), []).append((st, float(la), float(lo), int(p), k))
    zips = {}
    with open(os.path.join(GEO, "zcta.tsv")) as f:
        for line in f:
            if not line.startswith("#"):
                z, la, lo, city = (line.rstrip("\n").split("\t") + [""])[:4]; zips[z] = (float(la), float(lo), city)
    cent = {}
    with open(os.path.join(GEO, "states.tsv")) as f:
        for line in f:
            if not line.startswith("#"):
                st, la, lo, a = line.split("\t"); cent[st] = (float(la), float(lo))
    al = json.load(open(os.path.join(GEO, "aliases.json")))
    aliases = {_key(k): (v[0], v[1], v[2]) for k, v in al["places"].items()}
    for k, (st, la, lo) in aliases.items():           # aliases outrank same-named gazetteer places
        names.setdefault(k, []).insert(0, (st, la, lo, 10 ** 8, "a"))
    metros = []
    for m in al["metros"]:
        for ph in m["phrases"]:
            metros.append((_key(ph), m["label"], m["center"][0], m["center"][1], m["radius_mi"]))
    metros.sort(key=lambda x: -len(x[0]))
    metro_rx = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(m[0]) for m in metros) + r")(?![a-z0-9])")
    foreign = sorted({_key(x) for x in al["foreign"]}, key=len, reverse=True)
    foreign_rx = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(x) for x in foreign) + r")(?![a-z0-9])")
    maxn = max(len(k.split()) for k in list(names) + list(STATE_WORDS))
    counties = {}                  # key -> [(state, lat, lon, radius_mi)]
    try:
        with open(os.path.join(GEO, "counties.tsv"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) >= 5:
                    counties.setdefault(_key(p[0]), []).append((p[1], float(p[2]), float(p[3]), math.sqrt(float(p[4]) / math.pi)))
    except OSError:
        pass
    return dict(names=names, zips=zips, cent=cent, metros={m[0]: m[1:] for m in metros}, metro_rx=metro_rx,
                foreign_rx=foreign_rx, maxn=min(maxn, 6), counties=counties)

def miles(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(a)))

# ------------------------------------------------------------------ parsing
PART_SPLIT = re.compile(r"\s*(?:;|\||/|\s&\s|\s+and\s+|\s+or\s+|\n)\s*")
SEG_SPLIT = re.compile(r"\s*(?:,|\(|\)|\[|\]|~|:|•|\s[-–—]\s|\s[-–—]|[-–—]\s|\.(?=[a-z])|_)\s*", re.I)

NOVA_RX = re.compile(r"(?<![A-Za-z])(NoVA|NOVA|NoVa)(?![A-Za-z])")

def _segments(part):
    """Split one location (case kept) into segments -> [(raw_words, weak)]. Street numbers end a segment; a segment
    that starts with a number (an address or a Workday site code) is 'weak': its names only count next to a state."""
    out = []
    # a hyphen touching a number separates codes: "LOC-10001-Arlington Office", "US-MD-COLUMBIA-720"
    parts = re.split("(" + SEG_SPLIT.pattern + ")", part)
    pieces = []
    for j in range(0, len(parts), 2):
        comma = j > 0 and "," in parts[j - 1]
        for k, p in enumerate(re.split(r"(?<=\d)-|-(?=\d)", parts[j] or "")):
            pieces.append((p, comma and k == 0))
    for seg_raw, comma in pieces:
        raw = re.sub(r"[^A-Za-z0-9 ]+", " ", seg_raw.replace("-", " ").replace(".", " ")).split()
        weak = bool(raw) and raw[0].isdigit()
        while raw and raw[0].isdigit():
            raw = raw[1:]
        cut = next((i for i, w in enumerate(raw) if any(ch.isdigit() for ch in w)), len(raw))
        raw = raw[:cut]
        # "507 RESTON VA" (site code + city + state) is kept; "7700 Wisconsin Ave" (a street) is not
        if weak and not any(len(w) == 2 and w.isupper() and w in STATES for w in raw):
            continue
        if raw:
            out.append((raw, weak, comma))
    return out

COUNTY_RX = re.compile(r"((?:[A-Za-z'\u2019.\-]+\s+){0,2}[A-Za-z'\u2019.\-]+)\s+(County|Parish|Borough|Census Area)(?![A-Za-z])", re.I)
_STATE_WORDS_LONGEST = sorted(STATE_WORDS, key=len, reverse=True)

def _state_in(text):
    """The first US state named in a piece of text: a capitalised code ("OH") or a full name ("Ohio")."""
    best = None
    for m in re.finditer(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", text):
        if m.group(1) in STATES:
            best = (m.start(), m.group(1)); break
    low = " " + _key(text) + " "
    for w in _STATE_WORDS_LONGEST:
        i = low.find(" " + w + " ")
        if i >= 0 and (best is None or i < best[0]):
            best = (i, STATE_WORDS[w]); break
    return best[1] if best else None

def _county_hits(part, d):
    """"Franklin County, OH" -> ([Hit(county)], the text without the county name). A county name with a state is looked
    up in counties.tsv; without a state only when no other state has a county of that name."""
    cty = d.get("counties")
    if not cty or not re.search(r"(?i)(county|parish|borough|census area)", part):
        return [], part
    hits, out, last, cut = [], [], 0, False
    for m in COUNTY_RX.finditer(part):
        words = m.group(1).split()
        st = _state_in(part[m.end():]) or _state_in(part[:m.start()])
        for k in range(len(words), 0, -1):
            cands = cty.get(_key(" ".join(words[-k:])))
            if not cands:
                continue
            # a county name is never read as a town of that name; an ambiguous one ("Franklin County" alone) names nothing
            pick = [c for c in cands if c[0] == st] if st else (cands if len(cands) == 1 else [])
            if pick:
                c = pick[0]
                nm = " ".join(w.capitalize() if (w.islower() or (w.isupper() and len(w) > 3)) else w for w in words[-k:])
                hits.append(Hit(c[1], c[2], 0.75, "county", f"{nm} {m.group(2).title()}, {c[0]}", c[3]))
            start = m.start(1) + (len(m.group(1)) - len(" ".join(words[-k:])))
            out.append(part[last:start]); last = m.end(); cut = True
            break
    out.append(part[last:])
    return hits, " ".join(out) if cut else part

def _parse_part(part, d):
    """Resolve one location (no ';' or '/' inside). Returns list of Hits."""
    hits, part = _county_hits(part, d)
    n = norm(part)
    flat = _key(part)
    foreign = bool(d["foreign_rx"].search(re.sub(r"new mexico|new jersey|new england|new south", "", flat))
                   or FOREIGN_CODES.search(part))
    # ZIP codes: "(75109)", "Arlington, VA 22201", or a bare ZIP
    for m in re.finditer(r"(?:\(|\b[a-z]{2}\s+|^)(\d{5})(?:-\d{4})?(?:\)|\s*$|\s*,)", n):
        z = d["zips"].get(m.group(1))
        if z:
            hits.append(Hit(z[0], z[1], 0.95, "zip", m.group(1), 0))
    # metro phrases ("NoVA" only in its usual capitalization: "Nova Lima" is in Brazil)
    phrases = [] if foreign else [m.group(1) for m in d["metro_rx"].finditer(flat)]
    if not foreign and NOVA_RX.search(part):
        phrases.append("northern virginia")
    for ph in phrases:
        label, la, lo, r = d["metros"][ph]
        hits.append(Hit(la, lo, 0.8, "metro", label, r))
    # tokens: greedy longest match of known names inside each segment
    toks = []
    for raw, weak, comma in _segments(norm(part, keep_case=True)):
        words = [w.lower() for w in raw]
        i = 0
        while i < len(words):
            found = None
            for k in range(min(d["maxn"], len(words) - i), 0, -1):
                ph = " ".join(words[i:i + k])
                cands = d["names"].get(ph)
                st, code = STATE_WORDS.get(ph), False
                if k == 1 and len(ph) == 2 and ph.upper() in STATES:
                    c2 = ph.upper()
                    st = c2 if (raw[i].isupper() or len(words) == 1 or c2 not in WEAK_CODES) else None
                    code = bool(st)
                if ph in COUNTRY:
                    found = (k, None, None, False); break
                if cands and (k > 1 or len(ph) >= 3 or cands[0][4] == "a") and ph not in HARD_STOP:
                    found = (k, cands, st, code); break
                if st:
                    found = (k, None, st, code); break
            if not found:
                i += 1; continue
            k, cands, st, code = found
            if cands or st:
                nxt = words[i + k] if i + k < len(words) else ""
                toks.append({"i": len(toks), "phrase": " ".join(words[i:i + k]), "cands": cands or [], "state": st,
                             "code": code, "weak": weak or nxt in INSTITUTION or (k == 1 and ph in STOP),
                             "comma": comma and i == 0})
            i += k
    states = [t for t in toks if t["state"]]
    used_as_state, paired = set(), set()
    for t in toks:
        if not t["cands"]:
            continue
        best = None
        for s in states:
            if s is t:
                continue
            # a state name used as a city ("Washington, DC", "New York, NY", "Indiana, PA") must be followed by
            # its state; otherwise "Maryland, New York" would become the town of Maryland, NY
            if t["state"] and not (s["state"] in ("DC", t["state"]) or (s["code"] and s["i"] == t["i"] + 1)):
                continue
            c = [c for c in t["cands"] if c[0] == s["state"]]
            if c:
                dist = (abs(s["i"] - t["i"]), 0 if s["i"] > t["i"] else 1)
                if best is None or dist < best[0]:
                    best = (dist, s, c[0])
        if best:
            _, s, c = best
            used_as_state.add(id(s)); paired.add(id(t))
            hits.append(Hit(c[1], c[2], 0.95, "alias" if c[4] == "a" else "place", _label(t["phrase"], c[0]), 0))
    have_pair = bool(paired) or any(h.kind in ("zip", "metro") for h in hits)
    # "SF, NY, Chicago": a bare NY next to other city names is New York City
    if len(toks) > 1:
        for s in states:
            if s["state"] == "NY" and s["code"] and id(s) not in used_as_state and \
                    any(t["cands"] and id(t) not in paired and t is not s for t in toks):
                hits.append(Hit(40.7128, -74.0060, 0.8, "place", "New York, NY", 0)); used_as_state.add(id(s)); have_pair = True
    # "Northridge, California": a state right after the name that matched no city rules out a namesake elsewhere
    def blocked(t, st):
        return any(s["i"] == t["i"] + 1 and s["comma"] and s["state"] != st and id(s) not in used_as_state
                   and id(s) not in paired for s in states)
    quadrant = bool(re.search(r"(?<![A-Za-z])(NW|NE|SE|SW|N\.W\.|S\.E\.)(?![A-Za-z])", part))
    tried = False
    # unpaired city names: aliases, or one clearly dominant US place of that name
    for t in toks:
        if id(t) in paired or id(t) in used_as_state or not t["cands"]:
            continue
        if t["phrase"] == "new york" and not [s for s in states if s is not t]:
            hits.append(Hit(40.7128, -74.0060, 0.8, "place", "New York, NY", 0)); have_pair = True; continue
        if t["phrase"] == "washington" and quadrant:
            hits.append(Hit(38.9042, -77.0165, 0.8, "place", "Washington, DC", 0)); continue
        if t["state"]:
            continue                       # "Washington", "Virginia" alone = a state
        c = sorted(t["cands"], key=lambda x: -x[3])
        top, second = c[0], (c[1][3] if len(c) > 1 else 0)
        if top[4] == "a":
            if not blocked(t, top[0]):
                hits.append(Hit(top[1], top[2], 0.85, "alias", _label(t["phrase"], top[0]), 0))
            continue
        if foreign or t["weak"] or blocked(t, None):
            continue
        # first unpaired name: a unique place (>=2k people) or one 2x bigger than any namesake (>=20k); later names
        # in the same location ("Houston (McKinney)", "Bend - York") or next to a matched city only if a big city
        floor = 300000 if (have_pair or tried) else (20000 if len(c) > 1 else 2000)
        tried = True
        if top[3] >= floor and top[3] >= 2 * second:
            hits.append(Hit(top[1], top[2], 0.7 if top[3] >= 250000 else 0.6, "place", _label(t["phrase"], top[0]), 0))
    # a lone state: DC is a city; anything else is just a state centroid (never 'within')
    if not any(h.kind in ("zip", "place", "alias", "metro", "county") for h in hits) and not foreign:
        for s in states:
            if id(s) in used_as_state:
                continue
            if s["state"] == "DC":
                hits.append(Hit(38.9042, -77.0165, 0.9, "place", "Washington, DC", 0))
            else:
                la, lo = d["cent"].get(s["state"], (None, None))
                if la is not None:
                    hits.append(Hit(la, lo, 0.3, "state", STATES[s["state"]].title(), 0))
    return hits

def _label(phrase, st):
    p = re.sub(r"\s+dc$", "", phrase) if st == "DC" else phrase
    return f"{p.upper() if len(p) <= 3 else p.title()}, {st}"

@functools.lru_cache(maxsize=65536)
def _locate_all(s):
    d = _load()
    hits, seen = [], set()
    for part in PART_SPLIT.split(s or ""):
        if part.strip():
            for h in _parse_part(part, d):
                k = (round(h.lat, 3), round(h.lon, 3), h.kind)
                if k not in seen:
                    seen.add(k); hits.append(h)
    return tuple(hits)

def locate_all(s):
    """All places named in a location string, as Hit tuples (kind: zip|place|alias|metro|county|state)."""
    return list(_locate_all(s or ""))

def locate(s):
    """Best single point for a location string -> (lat, lon, confidence) or None. State-only strings get conf 0.3."""
    hs = _locate_all(s or "")
    if not hs:
        return None
    h = max(hs, key=lambda h: h.conf)
    return (h.lat, h.lon, h.conf)

@functools.lru_cache(maxsize=256)
def geocode_home(q):
    """ZIP ('10001') or place ('Austin, TX') -> (lat, lon, label). Raises ValueError if unknown."""
    d = _load()
    q = str(q).strip()
    m = re.fullmatch(r"(\d{5})(?:-\d{4})?", q)
    if m:
        if m.group(1) not in d["zips"]:
            raise ValueError(f"unknown ZIP {q}")
        la, lo, city = d["zips"][m.group(1)]
        return (la, lo, f"{m.group(1)} ({city})" if city else m.group(1))
    hs = [h for h in _locate_all(q) if h.kind in ("zip", "place", "alias", "metro", "county")]
    if not hs:
        raise ValueError(f"can't geocode home {q!r}")
    h = max(hs, key=lambda h: h.conf)
    return (h.lat, h.lon, h.label)

def area_phrase(st):
    """Words for a person's search area, for Claude prompts: 'within 35 miles of Columbus, OH, or remote'.
    Built from their home ZIP/place, radius and remote setting; 'their area' when no home is set."""
    place = ""
    z = str((st or {}).get("home_zip") or "").strip()
    if z:
        try:
            lbl = geocode_home(z)[2]
            m = re.fullmatch(r"\d{5}(?:-\d{4})? \((.+)\)", lbl)
            place = m.group(1) if m else lbl
        except ValueError:
            place = ""
    if place:
        miles_ = int((st or {}).get("radius_miles") or 35)
        area = f"within {miles_} miles of {place}"
    else:
        area = "their area"
    remote = bool((st or {}).get("remote_us", True)) and "remote" in ((st or {}).get("workplaces") or ["remote"])
    return area + (", or remote" if remote and place else " or remote" if remote else ", no remote" if place else " only")

def _home(home):
    if isinstance(home, (tuple, list)) and len(home) >= 2 and isinstance(home[0], (int, float)):
        return home[0], home[1]
    la, lo, _ = geocode_home(str(home))
    return la, lo

def within(job_locations, home, radius_miles):
    """Is any job location within radius of home?  -> (bool, nearest_miles or None, [matched location strings]).
    home: (lat, lon[, label]) or a ZIP / 'City, ST'. Metro phrases ("Bay Area", "Greater Boston") match when
    home is inside the metro or its center is within the radius; their distance is to the metro center.
    State-only and remote strings never match (remote handling stays in classify())."""
    hla, hlo = _home(home)
    if isinstance(job_locations, str):
        job_locations = [job_locations]
    nearest, matched = None, []
    for loc in job_locations or []:
        hit = False
        for h in _locate_all(loc or ""):
            if h.kind == "state":
                continue
            dist = miles(hla, hlo, h.lat, h.lon)
            nearest = dist if nearest is None else min(nearest, dist)
            if dist <= radius_miles or (h.kind in ("metro", "county") and dist <= h.radius):
                hit = True
        if hit:
            matched.append(loc)
    return (bool(matched), None if nearest is None else round(nearest, 1), matched)

if __name__ == "__main__":
    import sys
    for a in sys.argv[1:] or ["10001", "US-TX-Austin", "Rockville Maryland United States", "Washington DC Metro Area",
                              "Tysons Corner, Virginia; Virtual, New Jersey", "Remote - US", "MD-BETHESDA ROW"]:
        print(repr(a), "->", locate_all(a))
