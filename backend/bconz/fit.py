"""Who needs THIS dataset? Match a dataset profile against stated demand.

DIA finds organisations that say what data they lack. This module holds each
of those statements up against a concrete dataset and answers, need by need:

    met      -- the dataset demonstrably supplies it (with the attribute that does)
    unmet    -- the dataset demonstrably does not
    unknown  -- the profile does not say; never counted as a match

Honesty rules, the same as the rest of the system:
  * A match is only claimed from an explicit profile attribute. A missing
    attribute is "unknown", not "probably fine".
  * Unmet needs are shown next to met ones, so nobody pitches a dataset for a
    need it cannot fill.
  * The fit score counts met needs only; it is never padded.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .query import ALL_ORIGINS, DATA_TYPES, SUPPLY, SearchQuery, supply_label

# Stated needs that describe context rather than a data requirement.
CONTEXT_ONLY = {"funded_programme"}


@dataclass
class DatasetProfile:
    name: str
    partner: str = ""                       # who supplies it
    origin: list[str] = field(default_factory=list)          # SUPPLY keys
    diseases: list[str] = field(default_factory=list)
    data_types: list[str] = field(default_factory=list)      # DATA_TYPES keys
    patients: int | None = None
    disease_patients: dict[str, int] = field(default_factory=dict)   # per disease, if known
    sites: int | None = None
    followup_median_years: float | None = None
    diverse: bool | None = None             # meaningfully multi-ethnic / under-represented groups
    prospective: bool | None = None
    population: str = ""                    # free-text description, shown not scored
    coding: list[str] = field(default_factory=list)          # e.g. ICD-10, RxNorm, LOINC
    years: str = ""                         # e.g. "2015–2024"
    source: str = "manual"                  # manual | harm
    notes: str = ""
    # Data types a buyer search must mention (e.g. ["imaging"] for an imaging
    # archive, so "tuberculosis" finds imaging demand, not drug trials).
    search_focus: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.origin = [o for o in dict.fromkeys(self.origin or []) if o in SUPPLY]
        self.data_types = [d for d in dict.fromkeys(self.data_types or []) if d in DATA_TYPES]
        self.diseases = [d.strip() for d in self.diseases if d and d.strip()]
        self.search_focus = [d for d in dict.fromkeys(self.search_focus or []) if d in DATA_TYPES]

    @classmethod
    def of(cls, d: dict) -> "DatasetProfile":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return asdict(self)

    def query_for(self, disease: str) -> SearchQuery:
        return SearchQuery(disease=disease, supply=self.origin or list(ALL_ORIGINS),
                           data_types=self.search_focus)

    def cohort_size(self, disease: str | None) -> int | None:
        if disease:
            for k, v in self.disease_patients.items():
                if k.lower() in disease.lower() or disease.lower() in k.lower():
                    return v
        return self.patients


# ---------------------------------------------------------------- matching

def _judge(code: str, p: DatasetProfile, disease: str | None) -> tuple[str, str]:
    """(met|unmet|unknown, reason) for one stated need against one dataset."""
    n = p.cohort_size(disease)
    realworld = bool({"ehr", "claims"} & set(p.data_types))
    if code.startswith("data_"):
        t = code[5:]
        label = DATA_TYPES[t][0]
        if t in p.data_types:
            return "met", f"dataset includes {label} data"
        if not p.data_types:
            return "unknown", "data types not specified"
        return "unmet", f"dataset has no {label} data"
    if code == "longitudinal_gap":
        f = p.followup_median_years
        if f is None:
            return "unknown", "follow-up length not specified"
        if f >= 2:
            return "met", f"median follow-up {f:g} years"
        return "unmet", f"median follow-up only {f:g} years"
    if code == "small_sample":
        if n is None:
            return "unknown", "cohort size not specified"
        if n >= 1000:
            return "met", f"{n:,} patients"
        return "unmet", f"only {n:,} patients"
    if code == "single_centre":
        if p.sites is None:
            return "unknown", "number of sites not specified"
        if p.sites >= 2:
            return "met", f"{p.sites} sites"
        return "unmet", "single site"
    if code == "external_validation":
        if n is None:
            return "unknown", "cohort size not specified"
        if n >= 200:
            return "met", f"independent cohort of {n:,} patients"
        return "unmet", f"only {n:,} patients for validation"
    if code == "real_world_data":
        if realworld:
            return "met", "real-world " + " and ".join(DATA_TYPES[t][0].split(" /")[0]
                                                       for t in p.data_types if t in ("ehr", "claims"))
        if not p.data_types:
            return "unknown", "data types not specified"
        return "unmet", "not real-world clinical data"
    if code == "diverse_population":
        if p.diverse is None:
            return "unknown", "population diversity not specified"
        return ("met", p.population or "diverse population") if p.diverse else \
               ("unmet", "population is not described as diverse")
    if code == "generalisability":
        if (p.sites or 0) >= 2 or p.diverse:
            why = [f"{p.sites} sites" if (p.sites or 0) >= 2 else "", "diverse population" if p.diverse else ""]
            return "met", " and ".join(w for w in why if w)
        if p.sites is None and p.diverse is None:
            return "unknown", "sites and diversity not specified"
        return "unmet", "single site, population not described as diverse"
    if code == "retrospective_only":
        if p.prospective:
            return "met", "prospectively collected"
        if p.prospective is None:
            return "unknown", "collection design not specified"
        return "unmet", "dataset is retrospective too"
    if code == "ai_product_imaging":
        if "imaging" in p.data_types:
            return "met", "dataset includes imaging data" + (" with paired reports" if "reports" in p.data_types else "")
        return ("unknown", "data types not specified") if not p.data_types else ("unmet", "dataset has no imaging data")
    if code in ("ai_product", "company_grant", "company_rnd"):
        # The work was found by searching for this dataset's topic and data types.
        return "met", "their product work is on this dataset's topic"
    if code == "geographic_gap":
        # The gap was computed against this dataset's origin, so it is met by construction.
        return "met", f"dataset is from {supply_label(p.origin or list(ALL_ORIGINS))}"
    if code == "asia_absent":
        if {"IN", "ASIA"} & set(p.origin):
            return "met", "dataset includes Asian patients"
        return "unmet", "dataset is not from Asia"
    return "unknown", "no rule for this need"


def match_lead(lead: dict, p: DatasetProfile, weights: dict[str, float]) -> dict:
    """Judge every stated need of one lead. Returns the lead's `fit` block."""
    disease = next((d for d in p.diseases if d.lower() in (lead.get("_disease") or "").lower()), None)
    rows = {"met": [], "unmet": [], "unknown": []}
    for code in lead.get("needs", {}):
        if code in CONTEXT_ONLY:
            continue
        verdict, why = _judge(code, p, disease or lead.get("_disease"))
        rows[verdict].append({"need": code, "text": lead["needs"][code],
                              "evidence": lead.get("evidence", {}).get(code, ""), "why": why})
    miss = 1.0
    for r in rows["met"]:
        miss *= 1 - weights.get(r["need"], 0.2)
    score = 1 - miss if rows["met"] else 0.0
    met_codes = {r["need"] for r in rows["met"]}
    # A lead without its signals (an older document) is judged as one piece of work.
    signals = lead.get("signals") or [{"source": "", "title": "", "url": "",
                                       "needs": lead.get("evidence") or lead.get("needs") or {}}]
    anchor = _anchor(signals, met_codes)
    # A programme with no sites where this data comes from is a commercial opening
    # in its own right (e.g. US evidence for an FDA filing) -- but a different kind
    # of fit from a stated data gap, so it gets its own label rather than "Partial".
    geo = "geographic_gap" in met_codes
    label = ("Strong" if anchor and anchor["strong"] else
             "Partial" if anchor else "Geographic opening" if geo else "Context only")
    out = {"score": round(score, 3), "label": label, **rows,
           "summary": f"{len(rows['met'])} of {sum(len(v) for v in rows.values())} stated needs met"}
    if anchor:
        out["anchor"] = {k: anchor[k] for k in ("source", "title", "url", "needs")}
    return out


GEO = ("geographic_gap", "asia_absent")
# On a tie, the most concrete evidence carries the fit: a cleared product, then a paper.
ANCHOR_SOURCE = {"devices": 3, "publications": 2, "grants": 1, "trials": 0}


def _anchor(signals: list[dict], met: set[str]) -> dict | None:
    """The one piece of work the fit rests on.

    Needs are pooled per organisation, so without this an unrelated paper's
    "diverse population" plus a trial's missing sites could add up to "Strong"
    for work nobody at the organisation connected. A fit is judged on the
    single paper, grant or trial that states the most needs the dataset meets.
    Geography is met by construction for any dataset from the right place, so
    it never makes a fit on its own; one sentence that trips two patterns is
    still one stated need, except when it names the data type itself.

    Strong: one piece of work states two needs the dataset meets, in two
    sentences, or names the dataset's data type among them.
    """
    best = None
    for s in signals:
        codes = [c for c in (s.get("needs") or {}) if c in met and c not in GEO]
        if not codes:
            continue
        sentences = {s["needs"][c] for c in codes}
        names_type = any(c.startswith("data_") for c in codes)
        strong = len(sentences) >= 2 or (names_type and len(codes) >= 2)
        rank = (strong, len(sentences), len(codes), ANCHOR_SOURCE.get(s.get("source", ""), 0))
        if best is None or rank > best["rank"]:
            best = {"rank": rank, "strong": strong, "source": s.get("source", ""),
                    "title": s.get("title", ""), "url": s.get("url", ""), "needs": codes}
    return best


LABEL_ORDER = {"Strong": 0, "Partial": 1, "Geographic opening": 2, "Context only": 3}


def apply_fit(doc: dict, p: DatasetProfile, weights: dict[str, float]) -> dict:
    """Add a `fit` block to every lead and re-rank by match, then demand."""
    for lead in doc["leads"]:
        lead["fit"] = match_lead(lead, p, weights)
        lead["match_score"] = round(100 * (0.6 * lead["fit"]["score"] + 0.4 * lead["score"] / 100), 1)
    doc["leads"].sort(key=lambda l: (-LABEL_ORDER[l["fit"]["label"]], l["match_score"], l["score"]),
                      reverse=True)
    doc["dataset"] = p.to_dict()
    labels = [l["fit"]["label"] for l in doc["leads"]]
    doc["summary"]["fit"] = {k: labels.count(k)
                             for k in ("Strong", "Partial", "Geographic opening", "Context only")}
    return doc


# ------------------------------------------------------------- the match

def match_dataset(p: DatasetProfile, log=None, regions=None, max_trials: int = 300) -> dict:
    """Search demand for every disease in the profile, pool it, judge fit."""
    from . import dia

    if not p.diseases:
        raise ValueError("a dataset profile needs at least one disease")
    log = log or (lambda m: None)
    regions = regions or dia.REGIONS
    signals = []
    for d in p.diseases:
        log(f"— demand for {d}")
        signals += dia.collect(p.query_for(d), log=log, regions=regions, max_trials=max_trials)
    q = SearchQuery(disease=", ".join(p.diseases), supply=p.origin or list(ALL_ORIGINS))
    doc = dia.assemble(signals, q, log, regions)
    doc["disease"] = f"Buyers for {p.name}"
    weights = {k: v[1] for k, v in dia.NEEDS.items()}
    return apply_fit(doc, p, weights)


# ------------------------------------------------------------ HARM import

def from_harm(report: dict, name: str, origin: list[str], diseases: list[str],
              partner: str = "") -> DatasetProfile:
    """Build a profile from a HARM profiler readiness_report.json.

    Only aggregate counts are read; nothing row-level is kept. Attributes the
    report cannot establish (sites, diversity, imaging) stay unknown.
    """
    s = report.get("summary") or {}
    L = report.get("longitudinal") or {}
    cohort = report.get("cohort") or {}
    domains = set((s.get("domains") or {}).keys())
    types = []
    if "visit" in domains and domains & {"condition", "drug", "measurement", "procedure", "note"}:
        types.append("ehr")
    follow = None
    if L.get("available") and L.get("followup_days_median"):
        follow = round(L["followup_days_median"] / 365.25, 1)
    by_term = cohort.get("by_term") or {} if cohort.get("available") else {}
    return DatasetProfile(
        name=name, partner=partner or report.get("site_label", ""), origin=origin,
        diseases=diseases, data_types=types, patients=s.get("patients") or None,
        disease_patients={k: v for k, v in by_term.items() if v},
        followup_median_years=follow, source="harm",
        coding=sorted({"ICD" for t in report.get("tables", [])
                       for c in t.get("columns", []) if c.get("role") == "icd"}),
        notes=f"From HARM report {report.get('input_fingerprint', '')} "
              f"({report.get('generated_at', '')}); cohort counts are a floor.")
