#!/usr/bin/env python3
"""
DIA — Demand Intelligence Agent.

  python -m atlas.dia --disease "multiple myeloma" --out ./out_mm

WHAT THIS IS
    Finds organisations that have publicly stated they need data in a disease,
    and ranks them. Supply-side intent is invisible (no hospital announces its
    data is available); demand-side intent is loud, dated, attributable and
    free. DIA mines it.

THE SIGNAL NOBODY MINES
    A paper's limitations section is a researcher stating in writing what data
    they lack: "limited by a single-centre retrospective cohort; external
    validation in a more diverse population is needed". DIA searches for stated
    gaps, not topics, and every lead carries the verbatim sentence behind it.

SOURCES (all free, no keys)
    Europe PMC           stated data limitation   verbatim gap, affiliation, date
    NIH RePORTER         funded programme         award, named PI, end date
    ClinicalTrials.gov   active development       sponsor, phase, country footprint

HONESTY RULES
    * Every dimension is checked for whether it actually discriminates across
      this run. One that does not is shown as a badge, not a number, and is
      left out of the score. No constant reported to two decimal places.
    * Scores are absolute, never rescaled to make the top lead read 100.
    * Names are recorded only as published, with the URL. No contact details
      are inferred here; that is PCIA's job, under its lawful-basis gate.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from . import orgs
from .http import get

VERSION = "1.0.0"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
REPORTER = "https://api.reporter.nih.gov/v2/projects/search"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"

Progress = Callable[[str], None]


# ---------------------------------------------------------- need taxonomy
# code -> (human description, weight toward stated_need_fit, patterns)
NEEDS: dict[str, tuple[str, float, list[str]]] = {
    "diverse_population": (
        "data from an under-represented or non-Western population", 0.60,
        [r"under-?represent\w*", r"\bdiverse (population|cohort|patient)",
         r"(ethnic|racial) (divers|minorit|dispar)\w*", r"non-?(white|western|european|caucasian)",
         r"\b(asian|south asian|indian|african|hispanic|latin\w*) (population|patient|cohort)s?",
         r"lack of divers\w*"]),
    "external_validation": (
        "an independent cohort for external validation", 0.50,
        [r"external(ly)? validat\w*", r"independent (cohort|validation|dataset)",
         r"validat\w* in (an?|other|larger|independent|prospective)"]),
    "single_centre": (
        "data beyond a single centre", 0.45,
        [r"single[- ](cent(er|re)|institution|site|hospital)", r"one (cent(er|re)|institution)",
         r"multi-?cent(er|re) (studies|study|data|validation) (are|is) (needed|required|warranted)"]),
    "generalisability": (
        "evidence that generalises beyond their current population", 0.40,
        [r"generali[sz]ab\w*", r"may not (be )?generali[sz]e", r"limited applicab\w*"]),
    "small_sample": (
        "a larger cohort than they have", 0.35,
        [r"small (sample|cohort|number)", r"limited (sample|number of patients|cohort)",
         r"larger (cohort|sample|studies|population)s? (are|is) (needed|required|warranted)"]),
    "real_world_data": (
        "real-world clinical data", 0.50,
        [r"real[- ]world (data|evidence|setting|population|cohort)", r"routine clinical practice"]),
    "longitudinal_gap": (
        "longer longitudinal follow-up", 0.35,
        [r"(short|limited) follow-?up", r"longer follow-?up(?! (duration|time|period))",
         r"long-?term (follow-?up|outcome|data)s?", r"longitudinal (data|studies)"]),
    "retrospective_only": (
        "prospective or richer data than a retrospective review", 0.25,
        [r"retrospective (nature|design|study|analysis)"]),
    # Derived from trials, not text.
    "geographic_gap": ("sites or evidence in India, where they have none", 0.25, []),
    "asia_absent": ("any Asian representation in their programme", 0.20, []),
    "funded_programme": ("active funded work in this disease", 0.15, []),
}
LIMITATION_QUERY = (
    '("single center" OR "single centre" OR "single-center" OR "single-centre" OR '
    '"external validation" OR "externally validated" OR "generalizability" OR '
    '"generalisability" OR "underrepresented" OR "under-represented" OR '
    '"diverse population" OR "small sample" OR "real-world data" OR '
    '"limited follow-up" OR "longer follow-up" OR "independent cohort")')

SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

# These phrases also appear in methods and results ("using real-world data from
# the registry", "correlated with longer follow-up duration"), where they mean
# the authors HAVE the data. Count them only in a sentence that frames a gap.
NEEDS_CUE = {"real_world_data", "longitudinal_gap", "generalisability", "external_validation"}
GAP_CUE = re.compile(
    r"\b(limit\w*|lack\w*|scarce|scarcity|insufficient|paucity|few|only|small|restricted|"
    r"needed|need|required|warrant\w*|should be|future|further|remain\w*|unknown|unclear|"
    r"underexplored|under-explored|not (been |yet )?(well )?(studied|established|known|"
    r"validated)|however|although|constrain\w*|caution|compromis\w*|hinder\w*|gap)\b", re.I)


def detect_needs(text: str) -> dict[str, str]:
    """Return {need_code: verbatim sentence} for every stated gap in text."""
    out: dict[str, str] = {}
    for sent in SENT.split(text or ""):
        low = sent.lower()
        cued = bool(GAP_CUE.search(low))
        for code, (_, _, pats) in NEEDS.items():
            if code in out or not pats:
                continue
            if code in NEEDS_CUE and not cued:
                continue
            if any(re.search(p, low) for p in pats):
                out[code] = sent.strip()[:400]
    return out


# ----------------------------------------------------------------- signals

@dataclass
class Signal:
    source: str                 # publications | grants | trials
    org_raw: str
    date: str                   # ISO date, may be ""
    title: str
    url: str
    snippet: str
    person: str = ""
    person_role: str = ""
    country: str = ""
    sponsor_class: str = ""
    needs: dict[str, str] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def harvest_publications(disease: str, years: int, limit: int, log: Progress) -> list[Signal]:
    since = date.today().year - years
    q = (f'ABSTRACT:"{disease}" AND ABSTRACT:{LIMITATION_QUERY} '
         f'AND PUB_YEAR:[{since} TO {date.today().year}] AND SRC:MED')
    out: list[Signal] = []
    cursor = "*"
    while len(out) < limit:
        d = get(EPMC + "?" + urllib.parse.urlencode({
            "query": q, "format": "json", "resultType": "core",
            "pageSize": min(100, limit), "cursorMark": cursor,
            "sort": "P_PDATE_D desc"}))
        time.sleep(0.35)
        if not d:
            break
        res = (d.get("resultList") or {}).get("result", [])
        for r in res:
            abstract = re.sub(r"<[^>]+>", " ", r.get("abstractText", "") or "")
            needs = detect_needs(abstract)
            if not needs:
                continue            # topical but no stated gap: not a lead
            authors = ((r.get("authorList") or {}).get("author") or [])
            affil = ""
            for a in authors:
                lst = ((a.get("authorAffiliationDetailsList") or {})
                       .get("authorAffiliation") or [])
                if lst:
                    affil = lst[0].get("affiliation", "")
                    break
            affil = affil or r.get("affiliation", "") or ""
            inst = orgs.institution_from_affiliation(affil)
            if not inst:
                continue
            pmid = r.get("pmid") or ""
            first = authors[0].get("fullName", "") if authors else ""
            snippet = " … ".join(dict.fromkeys(needs.values()))[:500]
            out.append(Signal(
                source="publications", org_raw=inst,
                date=r.get("firstPublicationDate", "") or "",
                title=(r.get("title") or "").strip().rstrip("."),
                url=f"https://europepmc.org/article/MED/{pmid}" if pmid else
                    f"https://europepmc.org/article/{r.get('source','')}/{r.get('id','')}",
                snippet=snippet, person=first, person_role="first author",
                country=orgs.country_code(affil), needs=needs,
                extra={"pmid": pmid, "pmcid": r.get("pmcid", ""),
                       "journal": (r.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                       "affiliation": affil[:300]}))
        nxt = d.get("nextCursorMark")
        if not res or not nxt or nxt == cursor:
            break
        cursor = nxt
    log(f"publications: {len(out)} papers with a stated data gap")
    return out[:limit]


def disease_core(disease: str) -> str:
    """'Gaucher disease' -> 'gaucher'; 'multiple myeloma' stays whole."""
    core = re.sub(r"\s+(disease|syndrome|disorder)s?$", "", disease.strip(), flags=re.I)
    return core.lower()


def grant_is_about(disease: str, title: str, abstract: str) -> bool:
    """RePORTER's text search also matches a project's keyword terms, which
    pulls in work that merely cites the disease (a kidney-disease grant that
    mentions Gaucher lipids). Keep a grant only if the disease is in its
    title or recurs in its abstract."""
    core = disease_core(disease)
    return core in (title or "").lower() or (abstract or "").lower().count(core) >= 2


def harvest_grants(disease: str, limit: int, log: Progress) -> list[Signal]:
    out: list[Signal] = []
    offset = 0
    dropped = 0
    for _page in range(6):
        if len(out) >= limit:
            break
        d = get(REPORTER, data={
            "criteria": {
                "advanced_text_search": {"operator": "and",
                                         "search_field": "projecttitle,terms,abstracttext",
                                         "search_text": disease},
                "include_active_projects": True,
                "exclude_subprojects": False,
            },
            "include_fields": ["ApplId", "ProjectNum", "ProjectTitle", "AwardAmount",
                               "ProjectStartDate", "ProjectEndDate", "ContactPiName",
                               "Organization", "AgencyIcAdmin", "FiscalYear",
                               "AbstractText"],
            "offset": offset, "limit": min(100, limit),
            "sort_field": "award_amount", "sort_order": "desc"})
        time.sleep(0.5)
        res = (d or {}).get("results") or []
        if not res:
            break
        for r in res:
            org = (r.get("organization") or {})
            name = orgs.registry_org_name(org.get("org_name") or "")
            if not name:
                continue
            if not grant_is_about(disease, r.get("project_title", ""), r.get("abstract_text", "")):
                dropped += 1
                continue
            pi = r.get("contact_pi_name") or ""
            if "," in pi:                              # "OTT, CHRISTOPHER J"
                last, _, rest = pi.partition(",")
                pi = f"{rest.strip().title()} {last.strip().title()}"
            amt = r.get("award_amount") or 0
            end = (r.get("project_end_date") or "")[:10]
            ic = (r.get("agency_ic_admin") or {}).get("name", "NIH")
            out.append(Signal(
                source="grants", org_raw=name,
                date=(r.get("project_start_date") or "")[:10],
                title=(r.get("project_title") or "").strip(),
                url=f"https://reporter.nih.gov/project-details/{r.get('appl_id')}",
                snippet=f"{r.get('project_num','')} — {ic}, award ${amt:,.0f}"
                        + (f", runs to {end}" if end else ""),
                person=pi, person_role="principal investigator",
                country=orgs.country_code(org.get("org_country", "")) or "US",
                needs={"funded_programme": f"Funded project: {r.get('project_title','')}"},
                extra={"award": amt, "end": end, "project_num": r.get("project_num", ""),
                       "ic": ic}))
        offset += len(res)
        if offset >= ((d or {}).get("meta") or {}).get("total", 0):
            break
    log(f"grants: {len(out)} active NIH projects ({dropped} dropped as only "
        f"incidentally mentioning {disease})")
    return out[:limit]


PHASE_WEIGHT = {"PHASE4": 0.6, "PHASE3": 1.0, "PHASE2": 0.7, "PHASE1": 0.45,
                "EARLY_PHASE1": 0.35}


def harvest_trials(disease: str, limit: int, log: Progress) -> list[Signal]:
    out: list[Signal] = []
    token = None
    while len(out) < limit:
        params = {
            "query.cond": disease,
            "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING",
            "pageSize": min(100, limit), "sort": "LastUpdatePostDate:desc",
            "fields": "NCTId,BriefTitle,LeadSponsorName,LeadSponsorClass,Phase,"
                      "OverallStatus,EnrollmentCount,StartDate,LocationCountry,"
                      "OverallOfficialName,OverallOfficialAffiliation,"
                      "CentralContactName"}
        if token:
            params["pageToken"] = token
        d = get(CTGOV + "?" + urllib.parse.urlencode(params))
        time.sleep(0.3)
        if not d:
            break
        for s in d.get("studies", []):
            ps = s.get("protocolSection", {})
            ident = ps.get("identificationModule", {})
            spons = (ps.get("sponsorCollaboratorsModule", {}) or {}).get("leadSponsor", {})
            design = ps.get("designModule", {}) or {}
            status = ps.get("statusModule", {}) or {}
            cl = ps.get("contactsLocationsModule", {}) or {}
            nct = ident.get("nctId", "")
            countries = sorted({(l.get("country") or "") for l in cl.get("locations", [])
                                if l.get("country")})
            codes = {orgs.country_code(c) for c in countries} - {""}
            phases = design.get("phases") or []
            enrol = (design.get("enrollmentInfo") or {}).get("count")
            officials = cl.get("overallOfficials") or []
            person = officials[0].get("name", "") if officials else ""
            sponsor = spons.get("name", "")
            if orgs.looks_like_person(sponsor):
                # Investigator-sponsored: the organisation is where they work.
                aff = officials[0].get("affiliation", "") if officials else ""
                sponsor = orgs.institution_from_affiliation(aff) or (
                    aff if aff and not orgs.looks_like_person(aff) else "")
                person = person or spons.get("name", "")
                if not sponsor:
                    continue
            needs = {}
            if codes and "IN" not in codes:
                needs["geographic_gap"] = f"{nct} has no sites in India"
            if codes and not (codes & orgs.ASIA):
                needs["asia_absent"] = f"{nct} has no sites in Asia"
            # Sponsor country is not published; a single-country footprint is
            # the best public evidence of home jurisdiction.
            home = next(iter(codes)) if len(codes) == 1 else ""
            out.append(Signal(
                source="trials", org_raw=sponsor,
                date=(status.get("startDateStruct") or {}).get("date", ""),
                title=ident.get("briefTitle", ""),
                url=f"https://clinicaltrials.gov/study/{nct}",
                snippet=f"Sponsor of {nct}, {'/'.join(phases) or 'NA'}, status "
                        f"{status.get('overallStatus','')}"
                        + (f", target enrolment {enrol}" if enrol else "")
                        + (f", sites in {', '.join(countries[:6])}"
                           + (" …" if len(countries) > 6 else "") if countries else ""),
                person=person, person_role="principal investigator" if person else "",
                country=home, sponsor_class=spons.get("class", ""), needs=needs,
                extra={"nct": nct, "phases": phases, "enrolment": enrol,
                       "countries": countries,
                       "official_affiliation": officials[0].get("affiliation", "")
                       if officials else ""}))
        token = d.get("nextPageToken")
        if not token:
            break
    log(f"trials: {len(out)} active studies")
    return out[:limit]


# ----------------------------------------------------------------- scoring

@dataclass
class Lead:
    org_key: str
    org_display: str
    org_type: str = "academic"
    country: str = ""
    signals: list[Signal] = field(default_factory=list)
    needs: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)   # need -> verbatim
    dimensions: dict[str, dict] = field(default_factory=dict)
    score: float = 0.0
    tier: str = "C"
    rationale: list[str] = field(default_factory=list)
    named_people: list[dict] = field(default_factory=list)
    opening_angle: str = ""

    @property
    def sources(self) -> list[str]:
        return sorted({s.source for s in self.signals})


def _years_ago(iso: str) -> float | None:
    try:
        d = datetime.fromisoformat((iso or "")[:10] + ("-01" if len(iso) == 7 else ""))
    except ValueError:
        return None
    return max(0.0, (datetime.now() - d).days / 365.25)


DIM_WEIGHTS = {"signal_convergence": 0.25, "stated_need_fit": 0.30,
               "budget_signal": 0.20, "recency": 0.15,
               "geographic_opening": 0.05, "reachability": 0.05}


def score_dimensions(lead: Lead) -> dict[str, float]:
    sig = lead.signals
    n_src = len(lead.sources)
    convergence = min(1.0, (n_src - 1) / 2 * 0.7
                      + 0.3 * min(1.0, math.log1p(len(sig)) / math.log1p(12)))

    # Saturating sum, so four stated gaps outrank one (max() did not).
    miss = 1.0
    for code in lead.needs:
        miss *= 1 - NEEDS[code][1]
    need_fit = 1 - miss

    grants = [s.extra.get("award", 0) or 0 for s in sig if s.source == "grants"]
    budget = min(1.0, math.log10(1 + sum(grants)) / math.log10(1 + 5_000_000)) if grants else 0.0
    for s in sig:
        if s.source == "trials":
            ph = max((PHASE_WEIGHT.get(p, 0.3) for p in s.extra.get("phases") or []),
                     default=0.3)
            if lead.org_type == "industry":
                ph = min(1.0, ph + 0.2)
            budget = max(budget, ph)

    # Recency from the newest evidence: a grant started years ago but still
    # running is current, so use its end date when it lies in the future.
    ages = []
    for s in sig:
        a = _years_ago(s.date)
        if s.source == "grants" and s.extra.get("end", "") >= date.today().isoformat():
            a = 0.0 if a is None else min(a, 0.5)
        if a is not None:
            ages.append(a)
    recency = math.exp(-min(ages) / 2.5) if ages else 0.0

    geo = 1.0 if "geographic_gap" in lead.needs else 0.0
    named = sum(1 for s in sig if s.person)
    reach = min(1.0, 0.5 * (named > 0) + 0.5 * min(1.0, named / 3)) if sig else 0.0
    return {"signal_convergence": convergence, "stated_need_fit": need_fit,
            "budget_signal": budget, "recency": recency,
            "geographic_opening": geo, "reachability": reach}


def diagnose(leads: list[Lead]) -> dict[str, dict]:
    """Does each dimension actually separate leads in THIS run?"""
    diag = {}
    for dim in DIM_WEIGHTS:
        vals = sorted(round(l.dimensions[dim]["score"], 3) for l in leads)
        if not vals:
            diag[dim] = {"distinct": 0, "iqr": 0.0, "informative": False}
            continue
        q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]
        distinct = len(set(vals))
        iqr = q(0.75) - q(0.25)
        # Binary dimensions carry information as a flag, never as a measurement.
        informative = distinct >= 4 and (iqr >= 0.05 or distinct >= 8)
        diag[dim] = {"distinct": distinct, "iqr": round(iqr, 3),
                     "min": vals[0], "p50": q(0.5), "max": vals[-1],
                     "informative": informative}
    return diag


def opening_angle(lead: Lead) -> str:
    pub = next((s for s in lead.signals if s.source == "publications"), None)
    if pub:
        code = next((c for c in NEEDS if c in pub.needs), None)
        if code:
            return (f"Reference their paper \"{pub.title[:80]}\" and the limitation they "
                    f"state — they need {NEEDS[code][0]}.")
    trial = next((s for s in lead.signals if s.source == "trials"
                  and "geographic_gap" in s.needs), None)
    if trial:
        return (f"Their trial {trial.extra.get('nct')} has no Indian sites — offer "
                f"feasibility and real-world evidence from Indian hospital networks.")
    grant = next((s for s in lead.signals if s.source == "grants"), None)
    if grant:
        return (f"Reference the funded project \"{grant.title[:80]}\" and offer a cohort "
                f"that extends it beyond its current data source.")
    return "Introduce governed, research-ready clinical datasets from Indian hospital networks."


def build_leads(signals: list[Signal]) -> list[Lead]:
    by_key: dict[str, Lead] = {}
    names: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in signals:
        k = orgs.org_key(s.org_raw)
        if len(k) < 3:
            continue
        lead = by_key.setdefault(k, Lead(org_key=k, org_display=""))
        lead.signals.append(s)
        names[k][orgs.display_name(s.org_raw)] += 1
        for code, text in s.needs.items():
            lead.needs.setdefault(code, NEEDS[code][0])
            lead.evidence.setdefault(code, text)

    for k, lead in by_key.items():
        # Unabbreviated spelling first ("Institute" over NIH's "Inst"), then the
        # most frequent, then the longest.
        abbrev = re.compile(r"\b(inst|univ|ctr|hosp|med|natl|sch)\b\.?", re.I)
        lead.org_display = max(names[k].items(), key=lambda kv: (
            not abbrev.search(kv[0]), kv[1], len(kv[0])))[0]
        sc = next((s.sponsor_class for s in lead.signals if s.sponsor_class), "")
        lead.org_type = orgs.org_type(lead.org_display, sc)
        # A company's trial footprint says nothing about where it is based, so
        # trial-derived countries count only for non-industry sponsors.
        countries = [s.country for s in lead.signals if s.country and not (
            s.source == "trials" and lead.org_type == "industry")]
        lead.country = max(set(countries), key=countries.count) if countries else ""
        # Stated gaps first (they carry the opening line), newest first within.
        lead.signals.sort(key=lambda s: s.date, reverse=True)
        lead.signals.sort(key=lambda s: s.source != "publications")
        seen = set()
        for s in lead.signals:
            if s.person and s.person.lower() not in seen:
                seen.add(s.person.lower())
                lead.named_people.append({"name": s.person, "role": s.person_role,
                                          "source_url": s.url})
        lead.dimensions = {d: {"score": v} for d, v in score_dimensions(lead).items()}
    return list(by_key.values())


def finalise(leads: list[Lead]) -> dict[str, dict]:
    diag = diagnose(leads)
    live = {d: w for d, w in DIM_WEIGHTS.items() if diag[d]["informative"]}
    total_w = sum(live.values()) or 1.0
    for lead in leads:
        for d in lead.dimensions:
            lead.dimensions[d]["informative"] = diag[d]["informative"]
            lead.dimensions[d]["weight"] = round(live.get(d, 0) / total_w, 3)
        lead.score = round(100 * sum(lead.dimensions[d]["score"] * w
                                     for d, w in live.items()) / total_w, 1)
        need_n = len([c for c in lead.needs if NEEDS[c][2]])   # text-stated gaps
        lead.tier = ("A" if lead.score >= 60 or (lead.score >= 50 and need_n >= 2)
                     else "B" if lead.score >= 42 else "C")
        lead.rationale = []
        if len(lead.sources) >= 2:
            lead.rationale.append(f"seen in {len(lead.sources)} registries "
                                  f"({', '.join(lead.sources)})")
        for code in lead.needs:
            if NEEDS[code][2]:
                lead.rationale.append(f"stated need: {NEEDS[code][0]}")
        if "geographic_gap" in lead.needs:
            lead.rationale.append("active programme with no Indian sites")
        lead.opening_angle = opening_angle(lead)
    leads.sort(key=lambda l: l.score, reverse=True)
    return diag


# --------------------------------------------------------------------- run

def run(disease: str, years: int = 3, max_pubs: int = 200, max_grants: int = 100,
        max_trials: int = 100, log: Progress | None = None) -> dict:
    """Harvest, merge, score. Returns the leads.json document."""
    log = log or (lambda m: print(f"  {m}", file=sys.stderr))
    signals = (harvest_publications(disease, years, max_pubs, log)
               + harvest_grants(disease, max_grants, log)
               + harvest_trials(disease, max_trials, log))
    leads = build_leads(signals)
    diag = finalise(leads)
    for dim, d in diag.items():
        if not d["informative"]:
            log(f"diagnostic: {dim} distinct={d['distinct']} — not discriminating, "
                f"shown as a badge and excluded from the score")
    by_src = defaultdict(int)
    for s in signals:
        by_src[s.source] += 1
    return {
        "disease": disease, "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"signals": len(signals), "organisations": len(leads),
                    "by_source": dict(by_src),
                    "tiers": {t: sum(1 for l in leads if l.tier == t) for t in "ABC"}},
        "diagnostics": diag,
        "leads": [{**{k: v for k, v in asdict(l).items() if k != "signals"},
                   "sources": l.sources,
                   "signals": [asdict(s) for s in l.signals]} for l in leads],
    }


# ------------------------------------------------------------------ report

CSS = """
:root{--bg:#fff;--fg:#16181d;--mut:#5c6370;--line:#e3e6ea;--card:#f7f8fa;--a:#1b5e20;
--b:#8a5a00;--c:#5c6370;--acc:#1f4e79}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171b;--fg:#e8eaed;
--mut:#9aa0a6;--line:#2c3036;--card:#1d2025;--a:#81c995;--b:#fdd663;--c:#9aa0a6;--acc:#8ab4f8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:32px 16px 80px}h1{font-size:25px;margin:0 0 4px}
.sub{color:var(--mut);margin:0 0 16px}.grid{display:grid;grid-template-columns:
repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:16px 0}.tile{background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:12px}.tile .n{font-size:23px;
font-weight:600}.tile .l{color:var(--mut);font-size:12px;text-transform:uppercase}
.c{border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;background:var(--card)}
.c h3{margin:0;font-size:17px}.meta{color:var(--mut);font-size:13px}.t{font-weight:600}
.tA{color:var(--a)}.tB{color:var(--b)}.tC{color:var(--c)}.badge{display:inline-block;
font-size:11px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);margin:2px}
.ev{border-left:3px solid var(--acc);padding:6px 11px;margin:8px 0;background:var(--bg);
border-radius:0 6px 6px 0;font-size:13px}.angle{border:1px dashed var(--line);border-radius:8px;
padding:9px 12px;margin-top:9px;font-size:14px}a{color:var(--acc)}
"""


def render(doc: dict, top: int = 60) -> str:
    e = html.escape
    s = doc["summary"]
    p = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' "
         f"content='width=device-width,initial-scale=1'><title>Demand leads — "
         f"{e(doc['disease'])}</title><style>{CSS}</style></head><body><div class='wrap'>"
         f"<h1>Who needs {e(doc['disease'])} data</h1><p class='sub'>Organisations that "
         f"have publicly stated a data gap, funded work, or an active programme · "
         f"DIA v{doc['version']}</p><div class='grid'>"]
    for lbl, v in [("Signals", s["signals"]), ("Organisations", s["organisations"]),
                   ("Tier A", s["tiers"]["A"]), ("Tier B", s["tiers"]["B"])] + \
                  [(k.title(), v) for k, v in s["by_source"].items()]:
        p.append(f"<div class='tile'><div class='n'>{v}</div><div class='l'>{e(lbl)}</div></div>")
    p.append("</div>")
    for l in doc["leads"][:top]:
        dims = []
        for d, v in l["dimensions"].items():
            nm = d.replace("_", " ")
            if v["informative"]:
                dims.append(f"{nm} {v['score']:.2f}")
            elif v["score"] > 0:
                dims.append(f"<span class='badge'>{nm}</span>")
        p.append(f"<div class='c'><h3>{e(l['org_display'])}</h3><div class='meta'>"
                 f"<span class='t t{l['tier']}'>Tier {l['tier']}</span> · score "
                 f"{l['score']:.1f} · {e(l['org_type'])}"
                 f"{' · ' + e(l['country']) if l['country'] else ''} · seen in "
                 f"{e(', '.join(l['sources']))}</div><div class='meta'>{' · '.join(dims)}</div>")
        for code, text in l["evidence"].items():
            if NEEDS[code][2]:
                p.append(f"<div class='ev'><strong>{e(NEEDS[code][0])}</strong><br>"
                         f"<q>{e(text[:300])}</q></div>")
        for sg in l["signals"][:4]:
            p.append(f"<div class='meta'>{e(sg['source'])} · {e(sg['date'])} · "
                     f"<a href='{e(sg['url'])}' target='_blank' rel='noopener'>"
                     f"{e(sg['title'][:110])}</a> — {e(sg['snippet'][:160])}</div>")
        p.append(f"<div class='angle'><strong>Opening angle.</strong> "
                 f"{e(l['opening_angle'])}</div></div>")
    p.append("</div></body></html>")
    return "".join(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DIA — who publicly needs data in a disease.")
    ap.add_argument("--disease", required=True)
    ap.add_argument("--out", type=Path, default=Path("./dia_out"))
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--max-pubs", type=int, default=200)
    ap.add_argument("--max-grants", type=int, default=100)
    ap.add_argument("--max-trials", type=int, default=100)
    a = ap.parse_args(argv)
    print(f"DIA v{VERSION} — {a.disease}", file=sys.stderr)
    doc = run(a.disease, a.years, a.max_pubs, a.max_grants, a.max_trials)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "leads.json").write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    (a.out / "leads.html").write_text(render(doc), encoding="utf-8")
    s = doc["summary"]
    print(f"\n  {s['signals']} signals · {s['organisations']} organisations · "
          f"tiers {s['tiers']}", file=sys.stderr)
    for dim, d in doc["diagnostics"].items():
        print(f"    {dim:<20} distinct={d['distinct']:<4} informative={d['informative']}",
              file=sys.stderr)
    for l in doc["leads"][:8]:
        print(f"    {l['score']:>5.1f} {l['tier']}  {l['org_display'][:50]}  "
              f"[{', '.join(l['sources'])}]", file=sys.stderr)
    print(f"\n  {a.out/'leads.json'}\n  {a.out/'leads.html'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
