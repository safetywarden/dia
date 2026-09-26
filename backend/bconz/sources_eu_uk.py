"""European and UK demand sources.

    CTIS (EU Clinical Trials Information System)   active EU development
    ISRCTN (UK primary registry)                   active UK/global development
    CORDIS (EU Horizon research funding)           funded EU programmes
    UKRI Gateway to Research                       funded UK programmes

All four are public and keyless. Every harvester returns `dia.Signal`s, so the
scorecard, identity merging and self-diagnosis treat them exactly like the US
sources. Two rules specific to these registries:

  * CTIS lists EU/EEA sites only. A CTIS trial with no Indian site is not
    evidence of a geographic gap -- the registry could not show one -- so CTIS
    signals never assert `geographic_gap` or `asia_absent`.
  * The same trial is often registered in ClinicalTrials.gov, CTIS and ISRCTN.
    Cross-registry IDs are used to count it once.

CTRI (India) is deliberately absent: its search requires a CAPTCHA, which this
tool will not bypass. See README for the access routes being pursued.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from . import orgs
from .http import get

CTIS = "https://euclinicaltrials.eu/ctis-public-api"
ISRCTN = "https://www.isrctn.com/api"
CORDIS = "https://cordis.europa.eu/search"
GTR = "https://gtr.ukri.org/gtr/api"
GTR_ACCEPT = "application/vnd.rcuk.gtr.json-v7"

# Approximate, used only for the log-scaled budget signal. Awards are always
# displayed in their original currency.
TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}

PHASE_CODE = {"I": "PHASE1", "II": "PHASE2", "III": "PHASE3", "IV": "PHASE4"}


def _phases(text: str) -> list[str]:
    """'Therapeutic confirmatory (Phase III)', 'Phase II/III' -> ['PHASE2','PHASE3']."""
    found = re.findall(r"\b(IV|III|II|I)\b", (text or "").replace("Phase", " "))
    return sorted({PHASE_CODE[f] for f in found if f in PHASE_CODE})


def _is_about(disease_core: str, *texts: str) -> bool:
    return any(disease_core in (t or "").lower() for t in texts)


def _eu_date(s: str) -> str:
    """CTIS dates are dd/mm/yyyy."""
    try:
        return datetime.strptime((s or "")[:10], "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


# --------------------------------------------------------------------- CTIS

def harvest_ctis(disease: str, limit: int, log, Signal, core: str, years: int = 5) -> list:
    out = []
    since = date(date.today().year - years, 1, 1).isoformat()
    page = 1
    while len(out) < limit and page <= 8:
        d = get(f"{CTIS}/search", data={
            "pagination": {"page": page, "size": 50},
            "sort": {"property": "decisionDate", "direction": "DESC"},
            "searchCriteria": {"containAll": disease}})
        time.sleep(0.4)
        rows = (d or {}).get("data") or []
        if not rows:
            break
        for t in rows:
            decided = _eu_date(t.get("decisionDateOverall", ""))
            if decided and decided < since:
                continue
            if not _is_about(core, t.get("conditions", ""), t.get("ctTitle", "")):
                continue
            sponsor = (t.get("sponsor") or "").strip()
            if not sponsor:
                continue
            countries = sorted({c.split(":")[0] for c in t.get("trialCountries") or []})
            ct = t.get("ctNumber", "")
            industry = "pharmaceutical" in (t.get("sponsorType") or "").lower()
            out.append(Signal(
                source="trials", org_raw=sponsor, date=decided,
                title=(t.get("ctTitle") or "").strip()[:300],
                url=f"https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT={ct}",
                snippet=f"Sponsor of EU trial {ct}, {t.get('trialPhase', '').strip() or 'phase n/a'}"
                        + (f", EU sites in {', '.join(countries[:6])}" if countries else ""),
                country="", sponsor_class="INDUSTRY" if industry else "",
                needs={},                       # EU-only registry: no geographic claims
                extra={"registry": "CTIS", "ct_number": ct, "phases": _phases(t.get("trialPhase", "")),
                       "countries": countries, "eu_only_registry": True}))
        if not (d.get("pagination") or {}).get("nextPage"):
            break
        page += 1
    out = out[:limit]
    log(f"EU trials (CTIS): {len(out)} decided since {since[:4]}")
    return out


# ------------------------------------------------------------------- ISRCTN

def _strip(root):
    for e in root.iter():
        e.tag = e.tag.split("}")[-1]
    return root


def harvest_isrctn(disease: str, limit: int, log, Signal, core: str) -> list:
    raw = get(f"{ISRCTN}/query/format/default?" + urllib.parse.urlencode(
        {"q": disease, "limit": min(limit * 2, 200)}), as_json=False)
    time.sleep(0.4)
    if not raw:
        log("UK trials (ISRCTN): unavailable")
        return []
    try:
        root = _strip(ET.fromstring(raw))
    except ET.ParseError:
        log("UK trials (ISRCTN): unreadable response")
        return []
    today = date.today().isoformat()
    out = []
    for ft in root.iter("fullTrial"):
        t = ft.find("trial")
        if t is None:
            continue
        title = t.findtext(".//title") or ""
        cond = " ".join(c.text or "" for c in t.iter("description"))
        if not _is_about(core, title, cond):
            continue
        end = (t.findtext(".//overallEndDate") or t.findtext(".//recruitmentEnd") or "")[:10]
        if end and end < today:
            continue                                      # finished: not live demand
        sp = ft.find("sponsor")
        sponsor = (sp.findtext("organisation") if sp is not None else "") or ""
        if not sponsor.strip():
            continue
        commercial = (sp.findtext("commercialStatus") or "").lower() == "commercial"
        countries = sorted({c.text for c in t.iter("country") if c.text}
                           | {c.findtext("country") for c in t.iter("trialCentre") if c.findtext("country")})
        codes = {orgs.country_code(c) for c in countries} - {""}
        isrctn = t.findtext("isrctn") or ""
        needs = {}
        if codes and "IN" not in codes:
            needs["geographic_gap"] = f"ISRCTN{isrctn} has no sites in India"
        if codes and not (codes & orgs.ASIA):
            needs["asia_absent"] = f"ISRCTN{isrctn} has no sites in Asia"
        enrol = t.findtext(".//targetEnrolment")
        start = (t.findtext(".//recruitmentStart") or t.findtext(".//overallStartDate") or "")[:10]
        phase = t.findtext(".//phase") or ""
        out.append(Signal(
            source="trials", org_raw=sponsor.strip(), date=start,
            title=title.strip()[:300], url=f"https://www.isrctn.com/ISRCTN{isrctn}",
            snippet=f"Sponsor of ISRCTN{isrctn}, {phase or 'phase n/a'}"
                    + (f", target enrolment {enrol}" if enrol else "")
                    + (f", sites in {', '.join(countries[:6])}" if countries else ""),
            country="GB" if codes == {"GB"} else "",
            sponsor_class="INDUSTRY" if commercial else "", needs=needs,
            extra={"registry": "ISRCTN", "isrctn": isrctn, "phases": _phases(phase),
                   "countries": countries, "enrolment": enrol,
                   "nct": t.findtext(".//clinicalTrialsGovNumber") or "",
                   "eudract": t.findtext(".//eudraCTNumber") or ""}))
        if len(out) >= limit:
            break
    log(f"UK trials (ISRCTN): {len(out)} active")
    return out


# ------------------------------------------------------------------- CORDIS

def _as_list(x):
    return x if isinstance(x, list) else [x] if x else []


def harvest_cordis(disease: str, limit: int, log, Signal, core: str) -> list:
    q = f"contenttype='project' AND '{disease}' AND status='SIGNED'"
    d = get(f"{CORDIS}?" + urllib.parse.urlencode({"q": q, "format": "json", "p": 1,
                                                    "num": min(limit, 100)}))
    time.sleep(0.4)
    res = (d or {}).get("hits") or ((d or {}).get("result") or {}).get("hits") or {}
    out = []
    for h in _as_list(res.get("hit")):
        p = h.get("project") or {}
        title, objective = p.get("title", ""), p.get("objective", "")
        if not _is_about(core, title, p.get("keywords", "")) and objective.lower().count(core) < 2:
            continue
        coord = next((o for o in _as_list((p.get("relations", {}).get("associations") or {})
                                          .get("organization"))
                      if (o.get("@attributes") or {}).get("type") == "coordinator"), None)
        if not coord:
            continue
        name = coord.get("legalName") or coord.get("shortName") or ""
        country = ((coord.get("address") or {}).get("country") or "").upper()[:2]
        eur = float(p.get("ecMaxContribution") or 0)
        end = (p.get("endDate") or "")[:10]
        out.append(Signal(
            source="grants", org_raw=orgs.display_name(name), date=(p.get("startDate") or "")[:10],
            title=title.strip(), url=f"https://cordis.europa.eu/project/id/{p.get('id')}",
            snippet=f"Horizon project {p.get('acronym') or p.get('id')} — EU contribution "
                    f"€{eur:,.0f}" + (f", runs to {end}" if end else ""),
            country=country if country != "UK" else "GB",
            needs={"funded_programme": f"Funded project: {title}"},
            extra={"registry": "CORDIS", "funder": "European Commission", "award": eur,
                   "currency": "EUR", "award_usd": eur * TO_USD["EUR"], "end": end}))
    log(f"EU funding (CORDIS): {len(out)} signed projects")
    return out[:limit]


# --------------------------------------------------------------------- UKRI

def _ms_date(ms) -> str:
    """GtR timestamps are epoch milliseconds."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _gtr(url: str):
    raw = get(url.replace("http://", "https://"), as_json=False, accept=GTR_ACCEPT)
    time.sleep(0.25)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def harvest_ukri(disease: str, limit: int, log, Signal, core: str) -> list:
    d = _gtr(f"{GTR}/projects?" + urllib.parse.urlencode(
        {"q": f'"{disease}"', "f": "pro.a", "s": 100, "p": 1}))
    out = []
    for p in (d or {}).get("project") or []:
        if p.get("status") != "Active":
            continue
        if not _is_about(core, p.get("title", "")) and (p.get("abstractText") or "").lower().count(core) < 2:
            continue
        links = (p.get("links") or {}).get("link") or []
        lead = next((l for l in links if l.get("rel") == "LEAD_ORG"), None)
        fund = next((l for l in links if l.get("rel") == "FUND"), None)
        org = _gtr(lead["href"]) if lead else None
        if not org or not org.get("name"):
            continue
        f = _gtr(fund["href"]) if fund else None
        gbp = float(((f or {}).get("valuePounds") or {}).get("amount", 0) or 0)
        end, start = _ms_date((f or {}).get("end")), _ms_date((f or {}).get("start"))
        funder = (((f or {}).get("funder") or {}).get("name")) or "UKRI"
        out.append(Signal(
            source="grants", org_raw=orgs.display_name(org["name"]), date=start,
            title=(p.get("title") or "").strip(),
            url=f"https://gtr.ukri.org/projects?ref={p.get('grantReference', '')}",
            snippet=f"{p.get('grantReference', '')} — {funder}, award £{gbp:,.0f}"
                    + (f", runs to {end}" if end else ""),
            country="GB", needs={"funded_programme": f"Funded project: {p.get('title', '')}"},
            extra={"registry": "UKRI", "funder": funder, "award": gbp, "currency": "GBP",
                   "award_usd": gbp * TO_USD["GBP"], "end": end}))
        if len(out) >= limit:
            break
    log(f"UK funding (UKRI): {len(out)} active projects")
    return out


# ---------------------------------------------------------------- dedupe

# Registry identifiers only. ClinicalTrials.gov "secondary IDs" also hold NIH
# grant numbers and sponsor protocol codes that many unrelated trials share;
# matching on those merged different trials together.
REGISTRY_ID = re.compile(r"^(NCT\d{8}|ISRCTN\d{8}|\d{4}-\d{6}-\d{2}(-\d{2})?)$")


def _trial_ids(s) -> set[str]:
    """Registry identifiers a trial signal carries, including the EU CT/EudraCT
    base number without its "-01" suffix so the two EU formats meet."""
    e = s.extra
    ids = {(e.get(k) or "").upper().strip() for k in ("nct", "ct_number", "eudract")}
    if e.get("isrctn"):
        ids.add("ISRCTN" + e["isrctn"].upper().removeprefix("ISRCTN"))
    ids |= {i.upper().strip() for i in e.get("secondary_ids") or []}
    ids = {i for i in ids if REGISTRY_ID.match(i)}
    ids |= {i[:14] for i in ids if re.match(r"^\d{4}-\d{6}-\d{2}-\d{2}$", i)}
    return ids


def dedupe_trials(signals: list) -> tuple[list, int]:
    """Count a trial registered in several registries once.

    The first registration seen is canonical, and ClinicalTrials.gov is
    harvested first, so its global site list wins. Duplicates lend the
    canonical record their registry IDs so PCIA can still read, say, the
    ISRCTN public contacts for that trial.
    """
    owner: dict[str, object] = {}
    out, dropped = [], 0
    for s in signals:
        if s.source != "trials":
            out.append(s)
            continue
        ids = _trial_ids(s)
        # Two records from the same registry are two trials, whatever they share.
        canon = next((owner[i] for i in ids if i in owner
                      and owner[i].extra.get("registry") != s.extra.get("registry")), None)
        if canon is not None:
            for k in ("isrctn", "ct_number"):
                if s.extra.get(k):
                    canon.extra.setdefault(k, s.extra[k])
            dropped += 1
            continue
        for i in ids:
            owner[i] = s
        out.append(s)
    return out, dropped
