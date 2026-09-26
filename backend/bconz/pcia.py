#!/usr/bin/env python3
"""
PCIA — Provenance-first Contact Intelligence Agent.

  python3 pcia.py --leads ./out_mm/leads.json --out ./contacts --top 25

WHAT THIS IS
    Resolves the right human to approach for each organisation DIA or PIA
    surfaced, and records WHERE the contact detail was published and WHY that
    makes it lawful to use. Every record carries a source URL and the verbatim
    text it came from.

THE DESIGN DECISION THAT MATTERS
    Most "contact enrichment" works by inference: take a name and a company
    domain, generate firstname.lastname@domain, verify with an SMTP probe, sell
    the result. That is not public data — it is a guess about a person, and it
    has no lawful basis under India's DPDP Act, where Section 7's legitimate
    uses are a closed list that excludes commercial profiling and marketing.

    This tool does the opposite. It only collects contact details that the
    person or their institution PUBLISHED FOR THE PURPOSE OF BEING CONTACTED:

      * Corresponding-author emails in open-access papers. The author put that
        address in the article, under a heading that says "Corresponding
        Author", specifically so readers can write to them about the work.
      * ClinicalTrials.gov central contacts. The sponsor publishes a name,
        role, email and phone so people can enquire about the study.
      * NIH RePORTER principal investigators. Published under public-funding
        transparency obligations.

    This is narrower than a bought list. It is also better, because the person
    it finds is the author of the exact sentence in which they said they lacked
    data — so the approach writes itself and lands with someone who cares.

WHAT IS DELIBERATELY NOT IMPLEMENTED
    * Email pattern guessing or permutation of any kind
    * Scraping LinkedIn or any social platform (contrary to their terms, and a
      profile shared with a platform's network is not published at large)
    * Purchased or leaked contact databases with unknown provenance
    * Personal, as opposed to professional, contact details

    A record without a verifiable source URL and a lawful basis is stored as
    NOT EXPORTABLE and the export function refuses to emit it. That gate is
    structural, not a convention someone has to remember.

SOURCES: Europe PMC, ClinicalTrials.gov API v2, NIH RePORTER. No API keys.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import orgs
from .http import get as _get

VERSION = "1.0.0"
Progress = Callable[[str], None]


# ------------------------------------------------------- lawful basis model

class SourceType:
    """How the contact detail entered the public domain. This, not whether the
    value is findable, is what the DPDP Section 3(c)(ii) test turns on."""

    SELF_PUBLISHED_CORRESPONDENCE = "SELF_PUBLISHED_CORRESPONDENCE"
    REGISTRY_PUBLISHED_CONTACT = "REGISTRY_PUBLISHED_CONTACT"
    STATUTORY_REGISTER = "STATUTORY_REGISTER"
    INSTITUTIONAL_PAGE = "INSTITUTIONAL_PAGE"
    INFERRED = "INFERRED"                 # never lawful here — gate blocks it


class Basis:
    DPDP_3C_II = "DPDP_3C_II_PUBLIC"      # made public by the data principal
    STATUTORY = "STATUTORY_PUBLICATION"    # published under legal obligation
    LEGITIMATE_INTEREST = "GDPR_LEGITIMATE_INTEREST"
    CONSENT = "CONSENT"
    NONE = "NONE"


# Only these combinations may ever leave the system.
EXPORTABLE = {
    (SourceType.SELF_PUBLISHED_CORRESPONDENCE, Basis.DPDP_3C_II),
    (SourceType.SELF_PUBLISHED_CORRESPONDENCE, Basis.LEGITIMATE_INTEREST),
    (SourceType.REGISTRY_PUBLISHED_CONTACT, Basis.DPDP_3C_II),
    (SourceType.REGISTRY_PUBLISHED_CONTACT, Basis.LEGITIMATE_INTEREST),
    (SourceType.STATUTORY_REGISTER, Basis.STATUTORY),
    (SourceType.INSTITUTIONAL_PAGE, Basis.LEGITIMATE_INTEREST),
}


class ExportGateError(RuntimeError):
    pass


@dataclass
class Provenance:
    source_url: str
    source_type: str
    lawful_basis: str
    retrieved_at: str
    verbatim_snippet: str                 # the published text carrying the value
    jurisdiction: str = "UNKNOWN"         # regime: IN | EU_UK | US | OTHER | UNKNOWN
    publisher: str = ""                   # who published it, if not the person
    country: str = ""                     # ISO code the jurisdiction was read from
    jurisdiction_source: str = ""         # what evidence decided it


@dataclass
class ContactRecord:
    org_display: str
    org_key: str
    person_name: str
    person_role: str
    channel: str                          # email | phone | none
    value: str | None
    provenance: Provenance
    why_this_person: str                  # links back to the demand signal
    confidence: float = 1.0
    suppressed: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def exportable(self) -> bool:
        if self.suppressed or not self.value:
            return False
        return (self.provenance.source_type, self.provenance.lawful_basis) in EXPORTABLE

    @property
    def gate_reason(self) -> str:
        if self.suppressed:
            return "suppressed by do-not-contact list"
        if not self.value:
            return "no published contact value — approach via the institution"
        if not self.exportable:
            return (f"blocked: {self.provenance.source_type} / "
                    f"{self.provenance.lawful_basis} is not an exportable basis")
        return "ok"


def assert_exportable(recs: list[ContactRecord]) -> None:
    """Structural gate. Any export path must call this first."""
    bad = [r for r in recs if not r.exportable]
    if bad:
        raise ExportGateError(
            f"{len(bad)} record(s) lack an exportable lawful basis and cannot be "
            f"emitted. First: {bad[0].person_name} — {bad[0].gate_reason}")


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
CORRESP_RE = re.compile(r"<corresp\b.*?</corresp>", re.S | re.I)
EMAIL_TAG = re.compile(r"<email[^>]*>([^<]+)</email>", re.I)
AFF_RE = re.compile(r"<aff\b.*?</aff>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")

# Country-code TLDs that settle jurisdiction on their own. Generic TLDs
# (.com, .org, .edu is US-only in practice) are handled separately.
CCTLD = {"in": "IN", "uk": "GB", "de": "DE", "fr": "FR", "it": "IT", "es": "ES",
         "nl": "NL", "be": "BE", "se": "SE", "dk": "DK", "no": "NO", "fi": "FI",
         "pl": "PL", "at": "AT", "pt": "PT", "gr": "GR", "cz": "CZ", "hu": "HU",
         "ro": "RO", "ch": "CH", "ie": "IE", "jp": "JP", "cn": "CN", "kr": "KR",
         "au": "AU", "ca": "CA", "sg": "SG", "tw": "TW", "br": "BR", "il": "IL",
         "edu": "US", "gov": "US"}
# International dialling prefixes. "+1" is shared with Canada, so it proves
# North America rather than the US; it is only used when nothing better exists.
PHONE_CC = [("+91", "IN"), ("+44", "GB"), ("+49", "DE"), ("+33", "FR"), ("+39", "IT"),
            ("+34", "ES"), ("+31", "NL"), ("+32", "BE"), ("+46", "SE"), ("+45", "DK"),
            ("+47", "NO"), ("+358", "FI"), ("+48", "PL"), ("+43", "AT"), ("+351", "PT"),
            ("+30", "GR"), ("+420", "CZ"), ("+36", "HU"), ("+40", "RO"), ("+41", "CH"),
            ("+353", "IE"), ("+81", "JP"), ("+86", "CN"), ("+82", "KR"), ("+61", "AU"),
            ("+65", "SG"), ("+972", "IL"), ("+55", "BR"), ("+1", "US")]


def _regime(country: str) -> str:
    if not country:
        return "UNKNOWN"
    if country == "IN":
        return "IN"
    if country in orgs.EU_EEA_UK:
        return "EU_UK"
    if country == "US":
        return "US"
    return "OTHER"


def resolve_jurisdiction(*evidence: tuple[str, str]) -> tuple[str, str, str]:
    """First piece of evidence that names a country wins.

    `evidence` is (label, text) pairs in priority order: the published text
    nearest the contact first, the organisation's home country last. Returns
    (regime, country, which evidence decided). The contact's own location is
    what counts, so an email's ccTLD outranks the lead's home country.
    """
    weak: tuple[str, str, str] | None = None
    for label, text in evidence:
        if not text:
            continue
        if label == "phone" and re.sub(r"[^\d+]", "", text).startswith("+1"):
            weak = weak or ("US", "US", "phone (+1, North America)")
            continue
        if label == "email":
            tld = text.rsplit(".", 1)[-1].lower()
            c = CCTLD.get(tld, "")
        elif label == "phone":
            digits = re.sub(r"[^\d+]", "", text)
            c = next((cc for pre, cc in PHONE_CC if digits.startswith(pre)), "")
        elif label in ("lead_country", "footprint"):
            c = text if len(text) == 2 else ""
        else:
            c = orgs.country_code(text)
        if c:
            return _regime(c), c, label
    return weak or ("UNKNOWN", "", "")


def _jurisdiction(text: str) -> str:
    return resolve_jurisdiction(("text", text))[0]


def _basis_for(jur: str, source_type: str) -> str:
    if source_type == SourceType.STATUTORY_REGISTER:
        return Basis.STATUTORY
    if jur == "IN":
        return Basis.DPDP_3C_II
    if jur == "EU_UK":
        return Basis.LEGITIMATE_INTEREST
    # Elsewhere the self-publication argument still holds and is the narrower,
    # safer of the two. Prefer it.
    return Basis.DPDP_3C_II


def _prov(source_url: str, source_type: str, snippet: str, publisher: str,
          *evidence: tuple[str, str]) -> Provenance:
    jur, country, how = resolve_jurisdiction(*evidence)
    return Provenance(
        source_url=source_url, source_type=source_type,
        lawful_basis=_basis_for(jur, source_type),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        verbatim_snippet=snippet, jurisdiction=jur, publisher=publisher,
        country=country, jurisdiction_source=how)


# ------------------------------------------------- source: published papers

def contacts_from_publication(pmid: str, lead_org: str, why: str,
                              lead_country: str = "") -> list[ContactRecord]:
    """Corresponding-author email from the open-access full text.

    The strongest basis available: the author placed the address in the paper
    under a 'Corresponding Author' heading, for the express purpose of being
    written to about that work.
    """
    out: list[ContactRecord] = []
    meta = _get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
                + urllib.parse.urlencode({"query": f"EXT_ID:{pmid}", "format": "json",
                                          "resultType": "core", "pageSize": 1}))
    time.sleep(0.35)
    if not meta:
        return out
    res = (meta.get("resultList", {}) or {}).get("result", [])
    if not res:
        return out
    rec = res[0]
    pmcid = rec.get("pmcid")
    open_access = rec.get("isOpenAccess") == "Y" and rec.get("inEPMC") == "Y"
    title = rec.get("title", "")[:150]
    affil = rec.get("affiliation", "") or ""
    authors = ((rec.get("authorList") or {}).get("author") or [])
    article_url = f"https://europepmc.org/article/MED/{pmid}"

    if not (pmcid and open_access):
        # Not open access: the name is public, the email is not published here.
        author = (rec.get("authorString", "") or "").split(",")[0].strip()
        if author:
            out.append(ContactRecord(
                org_display=lead_org, org_key="", person_name=author,
                person_role="first author",
                channel="none", value=None,
                provenance=_prov(article_url, SourceType.SELF_PUBLISHED_CORRESPONDENCE,
                                 f"Author of: {title}", "Europe PMC",
                                 ("affiliation", affil), ("lead_country", lead_country)),
                why_this_person=why,
                notes=["article is not open access — no published email; "
                       "approach via the institution's published research office"]))
        return out

    xml = _get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
               as_json=False)
    time.sleep(0.35)
    if not xml:
        return out

    aff_text = " ".join(re.sub(r"\s+", " ", TAGS.sub(" ", a))
                        for a in AFF_RE.findall(xml)[:3])
    seen: set[str] = set()
    for block in CORRESP_RE.findall(xml)[:6]:
        emails = EMAIL_TAG.findall(block) or EMAIL_RE.findall(TAGS.sub(" ", block))
        plain = re.sub(r"\s+", " ", TAGS.sub(" ", block)).strip()
        # The name sits between the label and the email in the corresp block.
        name_m = re.search(
            r"(?:Corresponding Authors?|Correspondence(?: to)?)\s*[:\-]?\s*"
            r"([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){0,3})", plain)
        label_name = name_m.group(1).strip() if name_m else ""
        for em in emails:
            em = em.strip().rstrip(".,;")
            if not EMAIL_RE.fullmatch(em) or em.lower() in seen:
                continue
            seen.add(em.lower())
            name = label_name or _author_for_email(em, authors) or "Corresponding author"
            out.append(ContactRecord(
                org_display=lead_org, org_key="", person_name=name,
                person_role="corresponding author", channel="email", value=em,
                provenance=_prov(f"https://europepmc.org/article/PMC/{pmcid}",
                                 SourceType.SELF_PUBLISHED_CORRESPONDENCE, plain[:300],
                                 "Europe PMC open-access full text",
                                 ("corresp", plain), ("email", em), ("affiliation", affil),
                                 ("aff_xml", aff_text), ("lead_country", lead_country)),
                why_this_person=why,
                notes=[f"published in: {title}"]))
    return out


def _author_for_email(email: str, authors: list[dict]) -> str:
    """Which listed author does a published corresponding email belong to?

    Attribution only: both the address and the author list are published in
    the same article. The surname must appear in the address's local part,
    and exactly one author may match — an ambiguous match names nobody.
    """
    local = re.sub(r"[^a-z]", "", email.split("@")[0].lower())
    hits = []
    for a in authors:
        last = re.sub(r"[^a-z]", "", (a.get("lastName") or "").lower())
        if len(last) >= 3 and last in local:
            hits.append(f"{a.get('firstName', '')} {a.get('lastName', '')}".strip())
    return hits[0] if len(hits) == 1 else ""


def corresponding_authors_for_org(org: str, disease: str, why: str,
                                  max_papers: int = 3,
                                  lead_country: str = "") -> list[ContactRecord]:
    """Find recent open-access papers from an organisation and take the
    corresponding author.

    Needed because most leads surface through a trial or a grant, neither of
    which publishes an email for a researcher. A corresponding author at the
    same institution, working on the same disease, is both the better contact
    and the one with the cleanest lawful basis — so it is worth the extra call
    rather than falling back on guessing an address.
    """
    out: list[ContactRecord] = []
    # Strip legal suffixes that break affiliation matching.
    clean = re.sub(r"\b(inc|ltd|llc|plc|gmbh|corp|co)\b\.?", "", org, flags=re.I)
    clean = re.sub(r"[^\w\s]", " ", clean).strip()
    if len(clean) < 5:
        return out
    q = (f'(AFF:"{clean}" AND ABSTRACT:"{disease}") '
         f'AND OPEN_ACCESS:y AND IN_EPMC:y AND SRC:MED')
    d = _get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
             + urllib.parse.urlencode({"query": q, "format": "json",
                                       "pageSize": max_papers,
                                       "resultType": "core",
                                       "sort": "P_PDATE_D desc"}))
    time.sleep(0.35)
    if not d:
        return out
    for r in (d.get("resultList", {}) or {}).get("result", [])[:max_papers]:
        pmid = r.get("pmid")
        if not pmid:
            continue
        got = contacts_from_publication(str(pmid), org, why, lead_country)
        out += [g for g in got if g.channel == "email"]
        if out:
            break          # one good corresponding author per org is enough
    return out


# --------------------------------------------------- source: trial registry

def contacts_from_trial(nct: str, lead_org: str, why: str,
                        lead_country: str = "") -> list[ContactRecord]:
    """Central contact published by the sponsor so people can enquire.

    Registry contacts carry no address, so jurisdiction is read from what is
    published alongside them: the email's country domain, the phone's country
    code, the official's affiliation, then a single-country site footprint.
    """
    out: list[ContactRecord] = []
    url = (f"https://clinicaltrials.gov/api/v2/studies/{nct}?"
           + urllib.parse.urlencode({
               "fields": "NCTId,BriefTitle,LeadSponsorName,CentralContactName,"
                         "CentralContactEMail,CentralContactPhone,CentralContactRole,"
                         "OverallOfficialName,OverallOfficialAffiliation,"
                         "LocationFacility,LocationCountry"}))
    d = _get(url)
    time.sleep(0.3)
    if not d:
        return out
    ps = d.get("protocolSection", {}) or {}
    cl = ps.get("contactsLocationsModule", {}) or {}
    title = (ps.get("identificationModule", {}) or {}).get("briefTitle", "")[:150]
    study_url = f"https://clinicaltrials.gov/study/{nct}"
    codes = {orgs.country_code(l.get("country", "")) for l in cl.get("locations") or []} - {""}
    footprint = next(iter(codes)) if len(codes) == 1 else ""
    officials = cl.get("overallOfficials") or []
    official_aff = officials[0].get("affiliation", "") if officials else ""

    for c in (cl.get("centralContacts") or [])[:3]:
        name = c.get("name") or "Study contact"
        snippet = (f"Central contact listed on {nct}: {name}"
                   + (f", {c.get('role')}" if c.get("role") else "")
                   + ". Published by the sponsor for study enquiries.")
        for channel, val in (("email", c.get("email")), ("phone", c.get("phone"))):
            if not val:
                continue
            out.append(ContactRecord(
                org_display=lead_org, org_key="", person_name=name,
                person_role=(c.get("role") or "study contact").title(),
                channel=channel, value=val.strip(),
                provenance=_prov(study_url, SourceType.REGISTRY_PUBLISHED_CONTACT,
                                 snippet, "ClinicalTrials.gov",
                                 ("email", c.get("email") or ""),
                                 ("phone", c.get("phone") or ""),
                                 ("official_affiliation", official_aff),
                                 ("footprint", footprint),
                                 ("lead_country", lead_country)),
                why_this_person=why, notes=[f"study: {title}"]))

    for o in officials[:2]:
        if not o.get("name"):
            continue
        out.append(ContactRecord(
            org_display=lead_org, org_key="", person_name=o["name"],
            person_role="Principal investigator", channel="none", value=None,
            provenance=_prov(study_url, SourceType.REGISTRY_PUBLISHED_CONTACT,
                             f"Overall official for {nct}: {o['name']}"
                             + (f", {o.get('affiliation','')}" if o.get("affiliation") else ""),
                             "ClinicalTrials.gov",
                             ("official_affiliation", o.get("affiliation", "")),
                             ("footprint", footprint), ("lead_country", lead_country)),
            why_this_person=why,
            notes=["name published; no direct email published — route via the "
                   "study's central contact"]))
    return out


# ------------------------------------------------------ source: ISRCTN (UK)

def contacts_from_isrctn(isrctn: str, lead_org: str, why: str,
                         lead_country: str = "") -> list[ContactRecord]:
    """Contacts the registrant marked **Public** on ISRCTN.

    ISRCTN asks the registrant, per contact, whether it may be shown publicly;
    "Protected" contacts are withheld by ISRCTN and never reach this tool.
    That explicit choice is recorded in the snippet as the provenance.
    """
    import xml.etree.ElementTree as ET

    out: list[ContactRecord] = []
    num = isrctn.upper().removeprefix("ISRCTN")
    raw = _get(f"https://www.isrctn.com/api/trial/ISRCTN{num}/format/default", as_json=False)
    time.sleep(0.3)
    if not raw:
        return out
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for e in root.iter():
        e.tag = e.tag.split("}")[-1]
    url = f"https://www.isrctn.com/ISRCTN{num}"
    for c in root.iter("contact"):
        if (c.findtext("privacy") or "").strip().lower() != "public":
            continue
        email = (c.findtext(".//email") or "").strip()
        if not email or not EMAIL_RE.fullmatch(email):
            continue
        name = " ".join(x for x in (c.findtext("forename"), c.findtext("surname"))
                        if x and x.strip() not in ("-", "None")).strip() or "Study contact"
        roles = [t.text for t in c.iter("contactType") if t.text]
        country = c.findtext(".//country") or ""
        out.append(ContactRecord(
            org_display=lead_org, org_key="", person_name=name,
            person_role=", ".join(roles) or "Study contact", channel="email", value=email,
            provenance=_prov(url, SourceType.REGISTRY_PUBLISHED_CONTACT,
                             f"Contact on ISRCTN{num} ({', '.join(roles) or 'contact'}), "
                             f"privacy set to Public by the registrant.", "ISRCTN",
                             ("affiliation", country), ("email", email),
                             ("lead_country", lead_country)),
            why_this_person=why, notes=[f"ISRCTN{num}"]))
    return out


# ------------------------------------------------------- source: NIH grants

def contact_from_grant(person: str, org: str, url: str, why: str,
                       org_country: str = "US") -> ContactRecord:
    """PI named under public-funding transparency. Name only; no email."""
    return ContactRecord(
        org_display=org, org_key="", person_name=person,
        person_role="Principal investigator", channel="none", value=None,
        provenance=_prov(url or "https://reporter.nih.gov/", SourceType.STATUTORY_REGISTER,
                         f"Principal investigator of record: {person}, {org}",
                         "NIH RePORTER", ("lead_country", org_country or "US")),
        why_this_person=why,
        notes=["RePORTER publishes the name, not an email address; reach via the "
               "institution's published research-office address"])


# --------------------------------------------------------------- suppression

def load_suppression(path: Path | None) -> set[str]:
    """Do-not-contact list. Honoured everywhere, including cached records."""
    if not path or not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip().lower()
        if s and not s.startswith("#"):
            out.add(s)
    return out


# --------------------------------------------------------------- the outreach

def draft_opening(rec: ContactRecord, lead: dict) -> str:
    """One sentence, built from what THEY published, not a template.

    The whole point of sourcing contacts this way is that the person found is
    the author of the statement that qualified them as a lead. Say so.
    """
    needs = lead.get("needs", {}) or {}
    need_text = next(iter(needs.values()), None)
    pub = next((s for s in lead.get("signals", [])
                if s.get("source") == "publications"), None)
    if pub and need_text:
        return (f"You noted in \"{pub.get('title','')[:70]}\" that the work needs "
                f"{need_text}. We assemble governed, research-ready clinical "
                f"datasets from Indian hospital networks and may be able to help.")
    trial = next((s for s in lead.get("signals", [])
                  if s.get("source") == "trials"), None)
    if trial:
        return (f"Your programme {trial.get('extra', {}).get('nct', '')} currently has "
                f"no Indian sites. We work with Indian hospital networks on governed "
                f"real-world data and feasibility.")
    grant = next((s for s in lead.get("signals", [])
                  if s.get("source") == "grants"), None)
    if grant:
        return (f"Regarding your funded project \"{grant.get('title','')[:70]}\" — we "
                f"assemble governed clinical datasets from Indian hospital networks "
                f"that could extend its data base.")
    return ("We assemble governed, research-ready clinical datasets from Indian "
            "hospital networks.")


# -------------------------------------------------------------------- report

CSS = """
:root{--bg:#fff;--fg:#16181d;--mut:#5c6370;--line:#e3e6ea;--card:#f7f8fa;
--ok:#1b5e20;--no:#b3261e;--acc:#1f4e79}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171b;--fg:#e8eaed;
--mut:#9aa0a6;--line:#2c3036;--card:#1d2025;--ok:#81c995;--no:#f2b8b5;--acc:#8ab4f8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:25px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 10px;
padding-bottom:6px;border-bottom:1px solid var(--line)}
.sub{color:var(--mut);margin:0 0 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.tile .n{font-size:23px;font-weight:600}.tile .l{color:var(--mut);font-size:12px;
text-transform:uppercase;letter-spacing:.04em}
.c{border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0;background:var(--card)}
.c h3{margin:0 0 2px;font-size:16px}
.meta{color:var(--mut);font-size:13px}
.badge{display:inline-block;font-size:10px;padding:2px 8px;border-radius:99px;
border:1px solid;text-transform:uppercase;letter-spacing:.04em;margin-left:6px}
.bok{color:var(--ok);border-color:var(--ok)}.bno{color:var(--no);border-color:var(--no)}
.val{font-family:ui-monospace,monospace;font-size:14px;margin:6px 0}
.prov{border-left:3px solid var(--acc);padding:6px 11px;margin:8px 0;background:var(--bg);
border-radius:0 6px 6px 0;font-size:12.5px;color:var(--mut)}
.angle{background:var(--bg);border:1px dashed var(--line);border-radius:8px;
padding:9px 12px;margin-top:9px;font-size:14px}
a{color:var(--acc)}footer{margin-top:44px;padding-top:14px;border-top:1px solid var(--line);
color:var(--mut);font-size:12px}
"""


def render(recs: list[ContactRecord], leads_by_key: dict, disease: str) -> str:
    e = html.escape
    ok = [r for r in recs if r.exportable]
    blocked = [r for r in recs if not r.exportable]
    p = [f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Contacts — {e(disease)}</title><style>{CSS}</style></head><body>"
         f"<div class='wrap'><h1>Outreach contacts</h1>"
         f"<p class='sub'>{e(disease)} · every record carries the URL it was "
         f"published at and the basis for using it · PCIA v{VERSION}</p>"]

    by_basis: dict[str, int] = defaultdict(int)
    for r in ok:
        by_basis[r.provenance.source_type] += 1
    p.append("<div class='grid'>")
    for lbl, v in [("Contactable", len(ok)), ("Name only", len(blocked)),
                   ("Corresponding authors",
                    by_basis.get(SourceType.SELF_PUBLISHED_CORRESPONDENCE, 0)),
                   ("Registry contacts",
                    by_basis.get(SourceType.REGISTRY_PUBLISHED_CONTACT, 0)),
                   ("Organisations", len({r.org_display for r in recs}))]:
        p.append(f"<div class='tile'><div class='n'>{v}</div><div class='l'>{lbl}</div></div>")
    p.append("</div>")

    p.append("<h2>Contactable now</h2>")
    for r in ok:
        lead = leads_by_key.get(r.org_key, {})
        p.append(f"<div class='c'><h3>{e(r.person_name)}"
                 f"<span class='badge bok'>{e(r.channel)}</span></h3>"
                 f"<div class='meta'>{e(r.person_role)} · {e(r.org_display)} · "
                 f"{e(r.provenance.jurisdiction)}</div>"
                 f"<div class='val'>{e(r.value or '')}</div>"
                 f"<div class='prov'><strong>Published at</strong> "
                 f"<a href='{e(r.provenance.source_url)}' target='_blank' rel='noopener'>"
                 f"{e(r.provenance.source_url)}</a><br>"
                 f"<strong>Type</strong> {e(r.provenance.source_type)} · "
                 f"<strong>Basis</strong> {e(r.provenance.lawful_basis)}<br>"
                 f"<q>{e(r.provenance.verbatim_snippet[:240])}</q></div>"
                 f"<div class='angle'><strong>Opening.</strong> "
                 f"{e(draft_opening(r, lead))}</div></div>")

    if blocked:
        p.append("<h2>Named, but no published contact</h2>"
                 "<p class='sub'>These people are publicly identified but did not "
                 "publish a contact address. Reach them through their institution's "
                 "own published research-office channel. Do not guess an address.</p>")
        for r in blocked[:60]:
            p.append(f"<div class='c'><h3>{e(r.person_name)}"
                     f"<span class='badge bno'>no published contact</span></h3>"
                     f"<div class='meta'>{e(r.person_role)} · {e(r.org_display)}</div>"
                     f"<div class='prov'><a href='{e(r.provenance.source_url)}' "
                     f"target='_blank' rel='noopener'>{e(r.provenance.source_url)}</a><br>"
                     f"{e(r.gate_reason)}</div></div>")

    p.append("<footer>Sources: Europe PMC open-access full text, ClinicalTrials.gov, "
             "NIH RePORTER. No email addresses were guessed, no social platforms "
             "scraped, no third-party contact lists used. Records without an "
             "exportable lawful basis are shown here for review but cannot be "
             "exported by this tool.</footer></div></body></html>")
    return "".join(p)


def export_csv(recs: list[ContactRecord], path: Path,
               strict: bool = False) -> tuple[int, list[ContactRecord]]:
    """Write only exportable records.

    Silently dropping the rest would be its own failure: the operator would
    believe they had exported everything. So the excluded records are returned
    and reported, and `strict=True` refuses the whole export instead.
    """
    ok = [r for r in recs if r.exportable]
    excluded = [r for r in recs if not r.exportable]
    if strict and excluded:
        assert_exportable(recs)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["organisation", "person", "role", "channel", "value",
                    "source_url", "source_type", "lawful_basis", "jurisdiction",
                    "retrieved_at", "why_this_person"])
        for r in ok:
            w.writerow([r.org_display, r.person_name, r.person_role, r.channel,
                        r.value, r.provenance.source_url, r.provenance.source_type,
                        r.provenance.lawful_basis, r.provenance.jurisdiction,
                        r.provenance.retrieved_at, r.why_this_person])
    return len(ok), excluded


# ------------------------------------------------------------------ resolve

def suppressed(r: ContactRecord, suppression: set[str]) -> bool:
    ident = (r.value or "").lower()
    return bool(suppression) and (ident in suppression
                                  or r.person_name.lower() in suppression)


def resolve(doc: dict, top: int = 20, suppression: set[str] | None = None,
            log: Progress | None = None) -> list[ContactRecord]:
    """Resolve lawful contacts for the top N leads of a DIA leads document."""
    log = log or (lambda m: print(f"  {m}", file=sys.stderr))
    suppression = suppression or set()
    leads = doc.get("leads", [])[:top]
    disease = doc.get("disease", "")
    recs: list[ContactRecord] = []

    for i, lead in enumerate(leads, 1):
        org = lead.get("org_display", "")
        key = lead.get("org_key", "")
        country = lead.get("country", "")
        why = "; ".join(lead.get("rationale", [])[:2]) or "surfaced by DIA"
        log(f"[{i}/{len(leads)}] {org[:52]}")

        found: list[ContactRecord] = []
        for s in lead.get("signals", [])[:6]:
            src = s.get("source")
            if src == "publications":
                m = re.search(r"/MED/(\d+)", s.get("url", ""))
                if m:
                    found += contacts_from_publication(m.group(1), org, why, country)
            elif src == "trials":
                extra = s.get("extra", {}) or {}
                if extra.get("nct"):
                    found += contacts_from_trial(extra["nct"], org, why, country)
                if extra.get("isrctn"):
                    found += contacts_from_isrctn(extra["isrctn"], org, why, country)
                # CTIS publishes investigator and CRO emails under EU trial
                # transparency law, not for contact. Deliberately not used.
            elif src == "grants" and s.get("person"):
                found.append(contact_from_grant(s["person"], org, s.get("url", ""), why,
                                                s.get("country") or "US"))

        # No published email from the lead's own signals: look for a
        # corresponding author at the same organisation on the same disease.
        if not any(f.channel == "email" for f in found) and disease:
            found += corresponding_authors_for_org(org, disease, why, lead_country=country)

        for r in found:
            r.org_key = key
            if suppressed(r, suppression):
                r.suppressed = True
                r.notes.append("on the do-not-contact list")
        recs += found

    # Dedupe. A published value identifies the record on its own, so registry
    # typos of one person's name ("Cliford"/"Clifford") collapse; name-only
    # records dedupe on the name.
    seen: set[tuple] = set()
    uniq: list[ContactRecord] = []
    for r in recs:
        k = ((r.org_key, r.channel, r.value.lower()) if r.value
             else (r.org_key, r.person_name.lower(), r.channel))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def to_json(recs: list[ContactRecord], disease: str) -> dict:
    return {"disease": disease, "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "contacts": [{**asdict(r), "exportable": r.exportable,
                          "gate_reason": r.gate_reason} for r in recs]}


# ---------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PCIA — provenance-first contact resolution.")
    ap.add_argument("--leads", type=Path, required=True, help="DIA leads.json")
    ap.add_argument("--out", type=Path, default=Path("./pcia_out"))
    ap.add_argument("--top", type=int, default=20, help="resolve the top N leads")
    ap.add_argument("--suppress", type=Path, default=None,
                    help="do-not-contact list, one email or name per line")
    a = ap.parse_args(argv)

    data = json.loads(a.leads.read_text(encoding="utf-8"))
    disease = data.get("disease", "")
    suppression = load_suppression(a.suppress)
    print(f"PCIA v{VERSION} — resolving contacts for top {a.top} leads "
          f"({len(suppression)} suppressed)\n", file=sys.stderr)
    uniq = resolve(data, a.top, suppression)
    leads_by_key = {l.get("org_key", ""): l for l in data.get("leads", [])}

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "contacts.html").write_text(
        render(uniq, leads_by_key, disease), encoding="utf-8")
    (a.out / "contacts.json").write_text(
        json.dumps(to_json(uniq, disease), indent=2, default=str), encoding="utf-8")
    n, excluded = export_csv(uniq, a.out / "contactable.csv")

    ok = [r for r in uniq if r.exportable]
    print(f"\n{'='*66}", file=sys.stderr)
    print(f"  {len(uniq)} records · {len(ok)} contactable · "
          f"{len(uniq) - len(ok)} name-only", file=sys.stderr)
    by = defaultdict(int)
    for r in ok:
        by[r.provenance.source_type] += 1
    for k, v in by.items():
        print(f"    {v:>3}  {k}", file=sys.stderr)
    jur = defaultdict(int)
    for r in ok:
        jur[r.provenance.jurisdiction] += 1
    print(f"  jurisdiction: {dict(jur)}", file=sys.stderr)
    if excluded:
        print(f"  {len(excluded)} record(s) excluded from the CSV by the lawful-basis "
              f"gate — see contacts.html for each reason", file=sys.stderr)
    print(f"\n  csv (gated): {a.out/'contactable.csv'} — {n} rows", file=sys.stderr)
    print(f"  report:      {a.out/'contacts.html'}", file=sys.stderr)
    for r in ok[:6]:
        print(f"    {r.person_name[:26]:<28}{(r.value or '')[:34]:<36}"
              f"{r.provenance.jurisdiction:<8}{r.provenance.source_type[:28]}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
