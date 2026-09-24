"""Organisation identity: affiliation parsing, canonical keys, country.

Getting identity right is what makes signal convergence work. If
"Dana-Farber Cancer Inst" and "Dana-Farber Cancer Institute" become two
organisations, the one lead seen in all three registries turns into two leads
seen in one each, and the strongest signal the system has disappears.
"""
from __future__ import annotations

import re

# Segments that name a sub-unit, never the organisation itself.
SUBUNIT = re.compile(
    r"^(the\s+)?(department|dept|division|div|section|unit|laboratory|lab|"
    r"program(me)?|service|group|faculty|chair|core|office|branch|"
    r"graduate school|institute of \w+ sciences?)\b", re.I)

# Words that mark a segment as an institution.
INSTITUTION = re.compile(
    r"\b(universit\w*|univ|institut\w*|inst|hospital\w*|hosp|cent(er|re)|ctr|"
    r"college|clinic\w*|foundation|school of medicine|medical school|"
    r"health\s*(system|care|services)?|academy|council|"
    r"inc|ltd|llc|gmbh|plc|s\.?a\.?|ag|corp\w*|pharma\w*|therapeutics|"
    r"biosciences?|biotech\w*|oncology|laboratories|research)\b", re.I)

# Company names whose segments carry no institution keyword.
KNOWN_INDUSTRY = re.compile(
    r"\b(janssen|sanofi|novartis|roche|genentech|pfizer|amgen|abbvie|"
    r"bristol[- ]myers|merck|astrazeneca|gsk|glaxosmithkline|takeda|bayer|"
    r"lilly|gilead|regeneron|csl behring|celgene|karyopharm|biogen|moderna|"
    r"boehringer|daiichi|astellas|eisai|otsuka|servier|ipsen|beigene|"
    r"johnson ?& ?johnson|hoffmann-la roche|celgene|incyte|seagen|jazz)\b", re.I)

ABBREV = [
    (r"\buniv\b\.?", "university"), (r"\binst\b\.?", "institute"),
    (r"\bctr\b\.?", "center"), (r"\bcentre\b", "center"),
    (r"\bhosp\b\.?", "hospital"), (r"\bmed\b\.?", "medical"),
    (r"\bnatl\b\.?", "national"), (r"\bsch\b\.?", "school"),
    (r"&", " and "), (r"\bst\b\.?", "saint"),
    (r"\bcoll\b\.?", "college"), (r"\btx\b", "texas"), (r"\bcan\b(?= (center|ctr))", "cancer"),
    (r"\bres\b\.?", "research"), (r"\bhlth\b", "health"), (r"\bchildrens\b", "children s"),
    (r"\bmem\b\.?", "memorial"),
]
LEGAL = re.compile(r"\b(inc|ltd|llc|plc|gmbh|corp|corporation|co|ag|s\.?a|"
                   r"limited|pvt|private|l\.?p)\b\.?", re.I)

COUNTRIES = {
    "india": "IN", "united states": "US", "usa": "US", "u.s.a": "US",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "ireland": "IE", "germany": "DE", "france": "FR",
    "italy": "IT", "spain": "ES", "netherlands": "NL", "the netherlands": "NL",
    "belgium": "BE", "sweden": "SE", "denmark": "DK", "norway": "NO",
    "finland": "FI", "poland": "PL", "austria": "AT", "portugal": "PT",
    "greece": "GR", "czech republic": "CZ", "czechia": "CZ", "hungary": "HU",
    "romania": "RO", "switzerland": "CH", "canada": "CA", "australia": "AU",
    "new zealand": "NZ", "japan": "JP", "china": "CN", "korea": "KR",
    "republic of korea": "KR", "south korea": "KR", "taiwan": "TW",
    "singapore": "SG", "israel": "IL", "brazil": "BR", "mexico": "MX",
    "turkey": "TR", "türkiye": "TR", "russia": "RU", "russian federation": "RU",
    "saudi arabia": "SA", "egypt": "EG", "south africa": "ZA", "thailand": "TH",
    "malaysia": "MY", "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK",
    "nepal": "NP", "iran": "IR", "argentina": "AR", "chile": "CL",
    "hong kong": "HK", "vietnam": "VN", "philippines": "PH", "indonesia": "ID",
}
US_STATES = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|"
    r"MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|"
    r"WV|WI|WY|DC)\s+\d{5}\b")
EU_EEA_UK = {"GB", "IE", "DE", "FR", "IT", "ES", "NL", "BE", "SE", "DK", "NO",
             "FI", "PL", "AT", "PT", "GR", "CZ", "HU", "RO", "CH"}
ASIA = {"IN", "JP", "CN", "KR", "TW", "SG", "TH", "MY", "PK", "BD", "LK", "NP",
        "HK", "VN", "PH", "ID"}


# Head nouns of an institution name, strongest first. The first segment
# holding a tier-1 noun wins over any tier-2 segment anywhere.
TIER1 = re.compile(r"^(universit\w*|univ|hospital\w*|hosp|institut\w*|istituto|inst|"
                   r"clinic|klinik\w*|klinikum|policlinico|inc|ltd|llc|gmbh|plc|corp\w*|"
                   r"pharmaceuticals?|therapeutics|biosciences?|biotech\w*|"
                   r"laboratories)$", re.I)
TIER2 = re.compile(r"^(cent(er|re)|ctr|centro|foundation|fondazione|college|academy|"
                   r"council|charit[eé]|onlus|school)$", re.I)
SUBUNIT_WORD = re.compile(r"^(department|dept|division|div|section|unit|laboratory|lab|"
                          r"program(me)?|service|group|faculty|school|chair|core|"
                          r"office|branch|and|&)$", re.I)
FIELD_WORD = re.compile(r"^(medicine|hematology|haematology|oncology|sciences?|biology|"
                        r"surgery|pathology|pharmacology|epidemiology|genetics|genomics|"
                        r"immunology|radiology|biostatistics|statistics|nursing|"
                        r"pharmacy|biotechnology|translational|precision|clinical|"
                        r"internal|molecular|nuclear|experimental)$", re.I)
ORDINAL = re.compile(r"^([IVX]{1,4}\.?|\d+(st|nd|rd|th)?\.?|first|second|third|fourth|"
                     r"fifth)\s", re.I)
HEAD_ADJ = re.compile(r"^(medical|universitario|universitaria|universitaire|"
                      r"university|general|clinical|teaching|national)$", re.I)
CONNECT = {"of", "at", "for", "de", "di", "del", "der", "des", "du", "la", "le", "da"}
GENERIC = re.compile(r"^((school|college|faculty) of [\w ]+|[\w ]+ (division|department|"
                     r"program|unit)|medical school|graduate school)$", re.I)


def _phrase_around(words: list[str], i: int) -> str:
    """Grow an institution name outward from its head noun at words[i]."""
    lo = i
    while lo > 0 and i - lo < 5:
        w = words[lo - 1]
        if (SUBUNIT_WORD.match(w) or FIELD_WORD.match(w) or not w[:1].isupper()
                and w.lower() not in ("the",)):
            break
        lo -= 1
    hi = i
    # Forward: "University of Washington", "Instituto Nacional de Cancerología",
    # "Anderson Cancer Center". A connector must be followed by a capitalised
    # word, and only one place word is taken after it (no "… Cleveland Ohio USA").
    while hi + 1 < len(words) and hi - i < 5:
        w = words[hi + 1]
        if w.lower() in CONNECT and hi + 2 < len(words) and words[hi + 2][:1].isupper() \
                and not SUBUNIT_WORD.match(words[hi + 2]):
            hi += 2
        elif re.match(r"^(Cancer|Medical|Research|Nacional|National|General|Memorial|"
                      r"Comprehensive|Children'?s)$", w) or TIER1.match(w) or TIER2.match(w):
            hi += 1
        else:
            break
    # "University Hospital" alone names nothing: take the proper noun that
    # follows ("University Hospital Heidelberg", "Hospital Universitario 12 de Octubre").
    generic_only = all(TIER1.match(w) or TIER2.match(w) or HEAD_ADJ.match(w)
                       for w in words[lo:hi + 1])
    taken = 0
    while generic_only and hi + 1 < len(words) and taken < 4:
        w = words[hi + 1]
        if SUBUNIT_WORD.match(w) or not (w[:1].isupper() or w[:1].isdigit()
                                         or w[:1] in "\"'“" or w.lower() in CONNECT):
            break
        hi += 1
        taken += 1
    if words[hi].lower() in CONNECT:
        hi -= 1
    return re.sub(r"[\"“”]", "", " ".join(words[lo:hi + 1])).strip(" .-'")


def institution_from_affiliation(affil: str) -> str:
    """Pick the institution out of a free-text affiliation string.

    "Department of Hematology, Mayo Clinic, Rochester, MN, USA" -> "Mayo Clinic".
    Handles comma-less strings ("... Cleveland Clinic Lerner College of Medicine
    Case Western Reserve University Cleveland Ohio USA") by growing a name out
    from its head noun. Only the first of several ';'-joined affiliations is read.
    """
    if not affil:
        return ""
    first = re.split(r";|\s\|\s", affil)[0]
    first = re.sub(r"\S+@\S+", "", first)
    segs = [s.strip(" .") for s in re.split(r",|\s-\s", first) if s.strip(" .")]

    best: tuple[int, str] | None = None
    for s in segs:
        # "II. Medical Clinic", "3rd Department of Medicine": numbered sub-units.
        if ORDINAL.match(s):
            continue
        if KNOWN_INDUSTRY.search(s) and len(s) < 80:
            cand = (1, s)
        else:
            words = s.replace("(", " ").replace(")", " ").split()
            cand = None
            for tier, rx in ((1, TIER1), (2, TIER2)):
                for i, w in enumerate(words):
                    if rx.match(w.strip(".,")):
                        ph = _phrase_around(words, i)
                        if len(ph.split()) >= 2 and not GENERIC.match(ph):
                            cand = (tier, ph)
                            break
                if cand:
                    break
        if cand and (best is None or cand[0] < best[0]):
            best = cand
            if cand[0] == 1:
                break
    if best:
        return best[1]
    # No head noun anywhere. Guessing from the remaining segments turned cities
    # ("New Haven") and fields of study into organisations, so report nothing:
    # a missed lead costs less than an invented one.
    return ""


def looks_like_person(name: str) -> bool:
    """ClinicalTrials.gov lets an investigator be the sponsor ("Paul Szabolcs")."""
    n = re.sub(r",?\s+(MD|M\.D\.|PhD|Ph\.D\.|DO|MBBS|MPH|FRCP\w*)\.?$", "", (name or "").strip())
    words = n.split()
    if not 2 <= len(words) <= 4 or re.search(r"\d", n):
        return False
    if INSTITUTION.search(n) or KNOWN_INDUSTRY.search(n) or re.search(
            r"\b(group|network|consortium|society|association|alliance|trust|agency|"
            r"organi[sz]ation|cooperative|registry|program|initiative|study)\b", n, re.I):
        return False
    return all(re.fullmatch(r"[A-Z][a-zA-Z'\-]+|[A-Z]\.?", w) for w in words)


NIH_INTRAMURAL = {"NCI": "National Cancer Institute", "NHLBI": "National Heart, Lung, and "
                  "Blood Institute", "NIDDK": "National Institute of Diabetes and Digestive "
                  "and Kidney Diseases", "NIAID": "National Institute of Allergy and "
                  "Infectious Diseases", "NEI": "National Eye Institute",
                  "NHGRI": "National Human Genome Research Institute"}


def registry_org_name(name: str) -> str:
    """Registry org names that are really sub-units of a parent.

    RePORTER lists NIH intramural work as "Division of Basic Sciences - NCI".
    """
    m = re.match(r"^(.*?)\s+-\s+([A-Z]{2,6})$", (name or "").strip(), re.I)
    if m and SUBUNIT.match(m.group(1)):
        return NIH_INTRAMURAL.get(m.group(2).upper(), m.group(2).upper())
    return name


def org_key(name: str) -> str:
    """Canonical identity so spelling variants of one organisation merge."""
    k = (name or "").lower()
    k = re.sub(r"\(.*?\)", " ", k)
    for pat, rep in ABBREV:
        k = re.sub(pat, rep, k)
    k = LEGAL.sub(" ", k)
    k = re.sub(r"^the\s+", "", k)
    k = re.sub(r"\b([a-z])\.\s*(?=[a-z]\b)", r"\1", k)     # "m.d. anderson" -> "md anderson"
    k = re.sub(r"[^a-z0-9]+", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    # Registry-specific tails that name the same organisation.
    k = re.sub(r"\s+(research and development|r and d|r d|research development)$", "", k)
    k = re.sub(r"\s+the$", "", k)
    # A university's medical school is the university for outreach purposes
    # ("Stanford University School of Medicine"). Only fold when the parent is
    # explicit or known: Baylor College of Medicine is not Baylor University.
    m = re.match(r"^(.*?)\s+(school of medicine|medical school|college of medicine|"
                 r"faculty of medicine|school of public health|medical center)$", k)
    if m and ("university" in m.group(1) or m.group(1) in UNIVERSITY_SCHOOLS):
        k = UNIVERSITY_SCHOOLS.get(m.group(1), m.group(1))
    return ALIASES.get(k, k)


UNIVERSITY_SCHOOLS = {"yale": "yale university", "harvard": "harvard university",
                      "stanford": "stanford university", "duke": "duke university",
                      "emory": "emory university", "vanderbilt": "vanderbilt university",
                      "johns hopkins": "johns hopkins university",
                      "northwestern": "northwestern university"}


# Same organisation, different registry conventions.
ALIASES = {
    "university of texas md anderson cancer center": "md anderson cancer center",
    "ut md anderson cancer center": "md anderson cancer center",
    "university of texas m d anderson cancer center": "md anderson cancer center",
    "sloan kettering institute for cancer research": "memorial sloan kettering cancer center",
    "memorial sloan kettering": "memorial sloan kettering cancer center",
    "mayo clinic rochester": "mayo clinic",
    "mayo clinic arizona": "mayo clinic",
    "mayo clinic jacksonville": "mayo clinic",
    "general hospital corporation": "massachusetts general hospital",
    "janssen": "janssen research and development",
    "hoffmann la roche": "roche",
}


# NIH RePORTER's house abbreviations ("UNIV OF TX MD ANDERSON CAN CTR").
NIH_ABBREV = {"UNIV": "University", "CTR": "Center", "CNTR": "Center", "HOSP": "Hospital",
              "MED": "Medical", "COLL": "College", "INST": "Institute", "TX": "Texas",
              "CAN": "Cancer", "RES": "Research", "HLTH": "Health", "SCI": "Science",
              "SCIS": "Sciences", "CHILDRENS": "Children's", "NATL": "National",
              "FDN": "Foundation", "BIOMED": "Biomedical", "CLIN": "Clinical",
              "SCH": "School", "ST": "State", "CO": "Company", "CORP": "Corporation",
              "ASSOC": "Association", "DEPT": "Department", "MEM": "Memorial"}
KEEP_UPPER = {"MD", "NY", "UCLA", "UCSF", "MIT", "NIH", "NCI", "USA", "LLC", "II", "III"}


def display_name(name: str) -> str:
    """Registries shout (NIH: 'MASSACHUSETTS GENERAL HOSPITAL'). Tidy the case
    and expand NIH's abbreviations so the name reads as the organisation."""
    n = (name or "").strip()
    n = re.sub(r",\s*(the|THE)$", "", n)                 # "SCRIPPS RESEARCH INSTITUTE, THE"
    if n.isupper() and len(n) > 4:
        small = {"of", "and", "the", "for", "at", "in", "de", "la"}
        out = []
        for w in n.split():
            core = w.strip(",.")
            if core in NIH_ABBREV:
                out.append(w.replace(core, NIH_ABBREV[core]))
            elif core in KEEP_UPPER:
                out.append(w)
            elif w.lower() in small:
                out.append(w.lower())
            else:
                out.append("-".join(p.capitalize() for p in w.split("-")).replace("/", "/"))
        if out:
            out[0] = out[0][:1].upper() + out[0][1:]
        n = " ".join(out)
    return n


def country_code(text: str) -> str:
    """ISO-ish country from free text, or "" when nothing says."""
    t = (text or "").lower()
    # Longest names first so "south korea" wins over "korea".
    for name in sorted(COUNTRIES, key=len, reverse=True):
        if re.search(rf"(^|[^a-z]){re.escape(name)}([^a-z]|$)", t):
            return COUNTRIES[name]
    if US_STATES.search(text or ""):
        return "US"
    return ""


def org_type(name: str, sponsor_class: str = "") -> str:
    sc = (sponsor_class or "").upper()
    if sc == "INDUSTRY" or KNOWN_INDUSTRY.search(name or "") or re.search(
            r"\b(inc|ltd|llc|gmbh|plc|pharma\w*|therapeutics|biotech\w*|"
            r"biosciences?)\b", name or "", re.I):
        return "industry"
    if sc in ("NIH", "FED", "OTHER_GOV") or re.search(
            r"\b(national institute|ministry|council|government)\b", name or "", re.I):
        return "government"
    if re.search(r"\b(hospital|clinic|health system|medical center)\b", name or "", re.I):
        return "hospital"
    return "academic"
