"""Commercial demand: companies building products that need data.

Papers find people who *need* data; companies are the ones who *pay* for it,
and they rarely write "we lack data" anywhere. Their demand shows in what they
do: clear AI products with regulators, win small-business R&D grants, publish
product research. These sources surface that, across markets:

    FDA AI-enabled devices + 510(k)   cleared AI products. Global: the applicants
                                      include US, EU, Chinese, Korean, Japanese,
                                      Taiwanese, Israeli and Indian companies
    NIH SBIR/STTR                     US small-business R&D grants
    BIRAC                             Indian startup and SME grants (BIG, SBIRI,
                                      BIPP, PACE, IIPME, SEED, AcE, EDGE)
    Company-authored papers           Europe PMC, any country; the strongest
                                      free signal for Chinese, Korean and
                                      Japanese companies
    (Innovate UK and CORDIS company partners are read in sources_eu_uk.)

Not used, and why:
    WHO ICTRP (would cover CTRI, ChiCTR, jRCT, CRIS): robots.txt forbids
        automated access; the data is available to registered partners.
    CTRI directly: CAPTCHA.
    Health AI Register (CE-marked radiology AI): its API needs an account.
    Korea MFDS, Japan PMDA, Singapore HSA, China NMPA, CDSCO: no open
        machine-readable register (MFDS needs a free data.go.kr key).

Every signal is published by a regulator, a funder or the company itself.
"""
from __future__ import annotations

import csv
import io
import re
import time
import urllib.parse
from datetime import date, datetime

from . import orgs
from .http import get
from .query import DATA_TYPES

FDA_AI_LIST = "https://www.fda.gov/media/178541/download?attachment"
OPENFDA_510K = "https://api.fda.gov/device/510k.json"
REPORTER = "https://api.reporter.nih.gov/v2/projects/search"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BIRAC = "https://birac.nic.in/projects_supported.php"

# FDA review panels whose products are built on imaging.
IMAGING_PANELS = {"Radiology", "Ophthalmic"}
# NIH small-business activity codes: SBIR (R43/R44), STTR (R41/R42), and
# their cooperative and commercialisation variants.
SBIR_CODES = ["R41", "R42", "R43", "R44", "U43", "U44", "SB1", "U2B"]
# BIRAC schemes that fund companies' own product development.
BIRAC_SCHEMES = {5: "BIG", 2: "SBIRI", 1: "BIPP", 3: "PACE", 7: "IIPME",
                 17: "SEED Fund", 51: "AcE Fund", 49: "EDGE"}

_CACHE: dict[str, tuple[float, object]] = {}
CACHE_SECONDS = 12 * 3600


def _cached(key: str, fetch):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    val = fetch()
    if val is not None:
        _CACHE[key] = (time.time(), val)
    return val


def _us_date(s: str) -> str:
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def _focus_phrases(q) -> list[str]:
    """What a company's product or project must be about. With a data-type
    focus (an imaging archive), the data type is the product; otherwise the
    disease or drug is."""
    return [p.lower() for p in (q.data_type_phrases if q.data_types else q.phrases)]


def _mentions(text: str, phrases: list[str]) -> bool:
    low = (text or "").lower()
    return any(re.search(rf"(?<![a-z]){re.escape(p)}", low) for p in phrases)


# --------------------------------------------------------------------- FDA

def fda_ai_devices() -> list[dict]:
    """The FDA's AI-enabled device list: decision date, number, device,
    company, panel, product code."""
    def fetch():
        raw = get(FDA_AI_LIST, as_json=False)
        if not raw or "Submission Number" not in raw[:400]:
            return None
        return list(csv.DictReader(io.StringIO(raw.lstrip("﻿"))))
    return _cached("fda_ai", fetch) or []


def openfda_510k(numbers: list[str]) -> dict[str, dict]:
    """510(k) records by number: applicant, country, city, named contact.
    Batched; openFDA allows 1,000 keyless requests a day."""
    out: dict[str, dict] = {}
    todo = [n for n in dict.fromkeys(numbers) if n.startswith("K")]
    for n in todo:
        hit = _CACHE.get(f"510k:{n}")
        if hit:
            out[n] = hit[1]
    todo = [n for n in todo if n not in out]
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        d = get(f"{OPENFDA_510K}?" + urllib.parse.urlencode(
            {"search": " ".join(f"k_number:{n}" for n in batch), "limit": 100}))
        time.sleep(0.3)
        for r in (d or {}).get("results") or []:
            out[r["k_number"]] = r
            _CACHE[f"510k:{r['k_number']}"] = (time.time(), r)
    return out


def submission_url(number: str) -> str:
    base = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs"
    if number.startswith("DEN"):
        return f"{base}/cfpmn/denovo.cfm?id={number}"
    if number.startswith("P"):
        return f"{base}/cfpma/pma.cfm?id={number}"
    return f"{base}/cfpmn/pmn.cfm?ID={number}"


def harvest_fda_devices(q, limit: int, log, Signal, years: int = 3) -> list:
    """Companies with FDA-cleared AI products relevant to the search.

    A cleared product is a company that has already spent money on data, and
    will again: new indications, new sites and populations, post-market
    monitoring. With an imaging focus every imaging-panel device counts;
    otherwise the device name must mention the topic.
    """
    rows = fda_ai_devices()
    if not rows:
        log("cleared AI devices (FDA): list unavailable")
        return []
    since = date(date.today().year - years, 1, 1).isoformat()
    imaging = bool({"imaging", "reports"} & set(q.data_types))
    topic = [p.lower() for p in q.phrases]
    picked = []
    for r in rows:
        decided = _us_date(r.get("Date of Final Decision", ""))
        if not decided or decided < since:
            continue
        panel = (r.get("Panel (Lead)") or "").strip()
        device, company = (r.get("Device") or "").strip(), (r.get("Company") or "").strip()
        if q.sponsor and orgs.org_key(q.sponsor) not in orgs.org_key(company):
            continue
        if imaging:
            if panel not in IMAGING_PANELS:
                continue
        elif not (topic and _mentions(device, topic)):
            continue
        picked.append((decided, r))
    picked.sort(key=lambda x: x[0], reverse=True)
    picked = picked[:limit]
    meta = openfda_510k([r["Submission Number"] for _, r in picked])

    out = []
    for decided, r in picked:
        num = r["Submission Number"].strip()
        panel = r.get("Panel (Lead)", "").strip()
        device, company = r["Device"].strip(), r["Company"].strip()
        m = meta.get(num, {})
        kind = "De Novo" if num.startswith("DEN") else "PMA" if num.startswith("P") else "510(k)"
        code = "ai_product_imaging" if panel in IMAGING_PANELS else "ai_product"
        contact = re.sub(r"\s+", " ", m.get("contact") or "").strip()
        out.append(Signal(
            source="devices", org_raw=company, date=decided,
            title=f"{device} ({num})", url=submission_url(num),
            snippet=f"FDA {kind} {decided} — {panel} panel, product code "
                    f"{r.get('Primary Product Code', '')}"
                    + (f"; applicant in {m.get('city', '').title()}, {m.get('country_code', '')}"
                       if m.get("country_code") else ""),
            person=contact, person_role="contact named in the 510(k)" if contact else "",
            country=m.get("country_code", "") or "", sponsor_class="INDUSTRY",
            needs={code: f"Cleared AI product: {device} ({panel}, FDA {kind} {decided})"},
            extra={"registry": "FDA", "submission": num, "panel": panel,
                   "product_code": r.get("Primary Product Code", ""), "commercial": True}))
    by_country: dict[str, int] = {}
    for s in out:
        by_country[s.country or "?"] = by_country.get(s.country or "?", 0) + 1
    top = ", ".join(f"{c} {n}" for c, n in sorted(by_country.items(), key=lambda x: -x[1])[:8])
    log(f"cleared AI devices (FDA): {len(out)} since {since[:4]} ({top})")
    return out


# ------------------------------------------------------------ NIH SBIR/STTR

def harvest_sbir(q, limit: int, log, Signal) -> list:
    """US small-business R&D grants on the topic. Eligibility is restricted to
    small companies, so every recipient is a startup or SME."""
    if not q.phrases:
        return []
    text = " ".join(q.phrases + (q.data_type_phrases[:1] if q.data_types else []))
    d = get(REPORTER, data={
        "criteria": {"include_active_projects": True, "activity_codes": SBIR_CODES,
                     "advanced_text_search": {"operator": "and", "search_field": "projecttitle,terms,abstracttext",
                                              "search_text": text}},
        "include_fields": ["ApplId", "ProjectNum", "ProjectTitle", "AwardAmount", "ProjectStartDate",
                           "ProjectEndDate", "ContactPiName", "Organization", "AbstractText",
                           "ActivityCode", "AgencyIcAdmin"],
        "offset": 0, "limit": min(limit, 100), "sort_field": "project_start_date", "sort_order": "desc"})
    time.sleep(0.5)
    out = []
    for r in (d or {}).get("results") or []:
        org = (r.get("organization") or {})
        name = orgs.registry_org_name(org.get("org_name") or "")
        if not name or not q.matches_title_or_body(r.get("project_title", ""), r.get("abstract_text", "")):
            continue
        pi = r.get("contact_pi_name") or ""
        if "," in pi:
            last, _, rest = pi.partition(",")
            pi = f"{rest.strip().title()} {last.strip().title()}"
        amt = r.get("award_amount") or 0
        end = (r.get("project_end_date") or "")[:10]
        act = r.get("activity_code", "")
        title = (r.get("project_title") or "").strip()
        out.append(Signal(
            source="grants", org_raw=name, date=(r.get("project_start_date") or "")[:10],
            title=title, url=f"https://reporter.nih.gov/project-details/{r.get('appl_id')}",
            snippet=f"{r.get('project_num', '')} — NIH small-business grant ({act}), award ${amt:,.0f}"
                    + (f", runs to {end}" if end else ""),
            person=pi, person_role="principal investigator",
            country=orgs.country_code(org.get("org_country", "")) or "US", sponsor_class="INDUSTRY",
            needs={"company_grant": f"Small-business R&D grant ({act}): {title}"},
            extra={"registry": "NIH SBIR/STTR", "funder": "NIH", "award": amt, "currency": "USD",
                   "award_usd": amt, "end": end, "activity": act, "startup": True, "commercial": True}))
    log(f"US startup grants (NIH SBIR/STTR): {len(out)} active")
    return out[:limit]


# ------------------------------------------------------------------- BIRAC

_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
BENCH_IMAGING = re.compile(r"(cell|cytomet\w*|microscop\w*|fluorescen\w*|plant|flow|"
                           r"nano\w*|molecular probe|contrast agent|emulsion)", re.I)
MEDICAL_CONTEXT = re.compile(
    r"\b(ai|artificial intelligence|deep learning|machine learning|diagnos\w*|screening|detection|"
    r"radiolog\w*|scan\w*|patient\w*|clinical|point[- ]of[- ]care|cancer|tumou?r|tuberculosis|stroke|"
    r"cardi\w*|lung|breast|brain|retin\w*|ophthalm\w*|fracture|disease)\b", re.I)


def _cell(html_text: str) -> str:
    import html as _h
    t = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", " ", html_text))).strip()
    if "â€" in t:                  # UTF-8 read as cp1252 ("â€˜")
        try:
            t = t.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return t


def parse_birac(page: str) -> list[dict]:
    """BIRAC's supported-projects tables: S.No., Applicant, Title, City, State.
    The page's rows are not reliably closed, so cells are read in fives."""
    cells = [_cell(c) for c in _TD.findall(page)]
    rows = []
    for i in range(len(cells) - 4):
        if re.fullmatch(r"\d{1,5}", cells[i]) and cells[i + 1] and cells[i + 2]:
            if rows and rows[-1]["_i"] > i - 5:
                continue
            rows.append({"_i": i, "sno": cells[i], "applicant": cells[i + 1], "title": cells[i + 2],
                         "city": cells[i + 3], "state": cells[i + 4]})
    return rows


def birac_projects() -> list[dict]:
    def fetch():
        allrows = []
        for scheme, label in BIRAC_SCHEMES.items():
            url = f"{BIRAC}?scheme={scheme}&iscomplete=5"
            page = get(url, as_json=False)
            time.sleep(0.5)
            for r in parse_birac(page or ""):
                r.update(scheme=label, url=url)
                allrows.append(r)
        return allrows or None
    return _cached("birac", fetch) or []


def harvest_birac(q, limit: int, log, Signal) -> list:
    """Indian startups and SMEs funded by BIRAC for product development on the
    topic. BIRAC publishes the company, project title and city; no dates or
    amounts, so these carry no recency or budget signal."""
    phrases = _focus_phrases(q)
    if not phrases:
        return []
    out, people = [], 0
    for r in birac_projects():
        if not _mentions(r["title"], phrases):
            continue
        if q.data_types and (not MEDICAL_CONTEXT.search(r["title"]) or BENCH_IMAGING.search(r["title"])):
            continue                           # "imaging" also means cell, tissue and plant imaging
        name = r["applicant"].strip()
        if orgs.looks_like_person(name) and not orgs.is_company(name):
            people += 1                        # individual innovators: no organisation to approach
            continue
        out.append(Signal(
            source="grants", org_raw=name, date="", title=r["title"],
            url=f"{r['url']}#{r['sno']}",
            snippet=f"BIRAC {r['scheme']} — {r['city'].title()}, {r['state'].title()}",
            country="IN", sponsor_class="INDUSTRY",
            needs={"company_grant": f"BIRAC {r['scheme']} product-development grant: {r['title']}"},
            extra={"registry": "BIRAC", "funder": "BIRAC (DBT, Government of India)",
                   "scheme": r["scheme"], "startup": True, "commercial": True}))
        if len(out) >= limit:
            break
    log(f"India startup grants (BIRAC): {len(out)} projects"
        + (f" ({people} held by individual innovators left out)" if people else ""))
    return out


# ------------------------------------------------- company-authored papers

COMPANY_AFF = ('(AFF:"Inc" OR AFF:"Ltd" OR AFF:"LLC" OR AFF:"GmbH" OR AFF:"Pvt" OR AFF:"Corporation" '
               'OR AFF:"Co., Ltd" OR AFF:"B.V." OR AFF:"AG" OR AFF:"S.L." OR AFF:"SAS" OR AFF:"Pty" '
               'OR AFF:"K.K." OR AFF:"Technologies")')
LEGAL_FORM = re.compile(r"\b(inc|ltd|llc|gmbh|corp|corporation|pvt|co\.?,? ?ltd|b\.v|ag|s\.l|sas|pty|"
                        r"pte|k\.k|s\.r\.l|s\.p\.a|oy|ab|limited|private limited)(?!\w)\.?", re.I)
NOT_COMPANY = re.compile(r"\b(department|dept|division|cent(er|re)|institut\w*|laborator\w*|lab|school|"
                         r"college|universit\w*|hospital|\w*clinic\w*|klinik\w*|pharmacy|program\w*|faculty|"
                         r"medical corporation|health system|ministry|academy|society|electronic address|"
                         r"social welfare|welfare organi[sz]ation|association|foundation|county)\b", re.I)


def company_in_affiliation(line: str, gazetteer: set[str] | None = None) -> str:
    """The company named in one affiliation line, or ''.

    Requires a legal form ("Ltd", "GmbH", "Co., Ltd", "Pvt") or a name already
    known to be a company (an FDA applicant, a large company), because
    "Technologies" alone also names university departments.
    """
    for seg in re.split(r";", line or ""):
        seg = re.sub(r"\S+@\S+", "", seg)
        parts = [p.strip(" .") for p in seg.split(",") if p.strip(" .")]
        for i, p in enumerate(parts):
            # "AnchorDx Medical Co, Ltd": the legal form sits in its own part.
            if re.match(r"(?i)^(ltd|inc|llc|limited)\b", p) and i > 0:
                p = f"{parts[i - 1]}, {p.split()[0]}"
            if len(p) > 70 or NOT_COMPANY.search(p) or not re.search(r"[A-Za-z]{3}", p):
                continue
            known = gazetteer and orgs.org_key(p) in gazetteer
            if known or orgs.KNOWN_LARGE.search(p) or (LEGAL_FORM.search(p) and orgs.is_company(p)):
                return p
    return ""


def about_data(q, title: str, abstract: str) -> bool:
    """The topic in the title or recurring in the abstract, and, with a data-type
    focus, the data type in the title or at least twice in the abstract."""
    if q.phrases and not q.matches_title_or_body(title, abstract):
        return False
    if not q.data_types:
        return True
    low_t, low_a = title.lower(), abstract.lower()
    phrases = [p.lower() for p in q.data_type_phrases]
    return any(p in low_t for p in phrases) or sum(low_a.count(p) for p in phrases) >= 2


def harvest_company_papers(q, years: int, limit: int, log, Signal, gazetteer: set[str] | None = None) -> list:
    """Papers with a company author on the topic. A company publishing on this
    data is building on it: product R&D, validation, regulatory evidence."""
    if not q.phrases and not q.sponsor:
        return []
    since = date.today().year - years
    query = f'{q.epmc_clause()} AND {COMPANY_AFF} AND PUB_YEAR:[{since} TO {date.today().year}] AND SRC:MED'
    out, cursor, seen, skipped = [], "*", set(), 0
    while len(out) < limit:
        d = get(EPMC + "?" + urllib.parse.urlencode({"query": query, "format": "json", "resultType": "core",
                                                     "pageSize": 100, "cursorMark": cursor,
                                                     "sort": "P_PDATE_D desc"}))
        time.sleep(0.35)
        res = ((d or {}).get("resultList") or {}).get("result", [])
        for r in res:
            title = re.sub(r"<[^>]+>", "", r.get("title", "")).strip().rstrip(".")
            pmid = r.get("pmid") or ""
            # About the data, not merely mentioning it: a genomic test paper that
            # notes a CT scan is not imaging R&D.
            if not about_data(q, title, re.sub(r"<[^>]+>", "", r.get("abstractText", ""))):
                skipped += 1
                continue
            for a in (r.get("authorList") or {}).get("author", []):
                for af in ((a.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or []):
                    line = af.get("affiliation", "")
                    company = company_in_affiliation(line, gazetteer)
                    key = (orgs.org_key(company), pmid)
                    if not company or key in seen:
                        continue
                    seen.add(key)
                    out.append(Signal(
                        source="publications", org_raw=company, date=r.get("firstPublicationDate", "") or "",
                        title=title, url=f"https://europepmc.org/article/MED/{pmid}",
                        snippet=f"Company co-author: {a.get('fullName', '')}, {company}",
                        person=a.get("fullName", ""), person_role="company author",
                        country=orgs.country_code(line), sponsor_class="INDUSTRY",
                        needs={"company_rnd": f"Company research on this data: {title}"},
                        extra={"pmid": pmid, "pmcid": r.get("pmcid", ""), "affiliation": line[:300],
                               "company_paper": True, "commercial": True}))
        nxt = (d or {}).get("nextCursorMark")
        if not res or not nxt or nxt == cursor:
            break
        cursor = nxt
    countries: dict[str, int] = {}
    for s in out:
        countries[s.country or "?"] = countries.get(s.country or "?", 0) + 1
    top = ", ".join(f"{c} {n}" for c, n in sorted(countries.items(), key=lambda x: -x[1])[:8])
    log(f"company research (Europe PMC): {len(out)} company-authored papers ({top}); "
        f"{skipped} only mentioning the data type left out")
    return out[:limit]


def gazetteer() -> set[str]:
    """Known company identities: every FDA AI-device applicant."""
    return {orgs.org_key(r.get("Company", "")) for r in fda_ai_devices() if r.get("Company")}
