"""What a DIA search is looking for, and what BCONZ is offering.

A search is any combination of facets -- disease, drug, biomarker, data type,
population, company -- plus the origin of the data BCONZ would supply. Every
source builds its own query from the facets it can search, and every result
must match *all* the facets given before it counts, so widening the query
language never loosens precision.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# Data types a buyer may say they lack, as offered in the search form.
#   code -> (label, search phrases, need description, need patterns)
DATA_TYPES: dict[str, tuple[str, list[str], str, list[str]]] = {
    "genomic": ("Genomic / sequencing", ["genomic", "sequencing", "genotype", "exome", "whole-genome"],
                "genomic or sequencing data",
                [r"genom\w* data", r"sequencing data", r"genotyp\w* data", r"(whole[- ])?(genome|exome) sequenc\w*",
                 r"germline|somatic variant"]),
    "imaging": ("Imaging", ["imaging", "optical coherence tomography", "fundus", "MRI", "radiolog",
                            "x-ray", "radiograph", "computed tomography", "CT scan"],
                "imaging data",
                [r"imaging data", r"\b(oct|mri|ct|pet) (scan|image|data)s?", r"fundus (photo\w*|image\w*)",
                 r"optical coherence tomography", r"retinal image\w*", r"radiolog\w* data",
                 r"(chest )?(x-ray|radiograph)\w* (data|dataset|images)", r"(ct|mri) (dataset|cohort)s?"]),
    "reports": ("Radiology reports", ["radiology report", "radiologist report", "report generation"],
                "paired radiology reports",
                [r"radiology reports?", r"radiologist reports?", r"report generation",
                 r"paired (image|imaging)[- ](and[- ])?(text|report)s?", r"image[- ]text pairs?"]),
    "ehr": ("EHR / longitudinal clinical", ["electronic health record", "EHR", "electronic medical record"],
            "longitudinal electronic health record data",
            [r"electronic (health|medical) records?", r"\behr\b", r"\bemr\b", r"clinical records?"]),
    "claims": ("Claims / administrative", ["claims data", "administrative data", "insurance claims"],
               "claims or administrative data",
               [r"claims data", r"administrative (data|database)", r"insurance claims?", r"billing data"]),
    "biobank": ("Biobank / samples", ["biobank", "biospecimen", "tissue samples"],
                "biobank samples or biospecimens",
                [r"biobank\w*", r"biospecimen\w*", r"(tissue|blood|serum|plasma) samples?"]),
    "device": ("Device / wearable", ["wearable", "remote monitoring", "digital biomarker"],
               "wearable or remote-monitoring data",
               [r"wearable\w*", r"remote (patient )?monitoring", r"digital biomarker\w*", r"sensor data"]),
    "pro": ("Patient-reported outcomes", ["patient-reported outcome", "PROM", "quality of life"],
            "patient-reported outcome data",
            [r"patient[- ]reported outcome\w*", r"\bproms?\b", r"quality[- ]of[- ]life data"]),
}

# Where the offered data comes from. BCONZ sources directly and through partner
# networks worldwide; a search (or a dataset profile) may narrow the origins,
# e.g. ["US"] for a US real-world dataset. Origins decide the geographic signal
# ("their programme has no sites where this data comes from") and the pitch.
SUPPLY = {
    "IN": {"label": "India", "adj": "Indian", "codes": {"IN"}},
    "US": {"label": "the United States", "adj": "US", "codes": {"US"}},
    "EU": {"label": "Europe", "adj": "European",
           "codes": {"DE", "FR", "IT", "ES", "NL", "BE", "SE", "DK", "FI", "PL", "AT", "PT", "GR", "CZ",
                     "HU", "RO", "IE"}},
    "UK": {"label": "the UK", "adj": "UK", "codes": {"GB"}},
    "ASIA": {"label": "Asia", "adj": "Asian",
             "codes": {"IN", "JP", "CN", "KR", "TW", "SG", "TH", "MY", "PK", "BD", "LK", "NP", "HK", "VN",
                       "PH", "ID"}},
}
ALL_ORIGINS = list(SUPPLY)


def supply_label(origins: list[str]) -> str:
    names = [SUPPLY[o]["label"] for o in origins]
    if set(origins) >= set(ALL_ORIGINS) or not names:
        return "the regions BCONZ sources from"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def supply_pitch(origins: list[str]) -> str:
    if set(origins) >= set(ALL_ORIGINS) or not origins:
        return ("governed, research-ready clinical datasets, sourced directly and through "
                "partner networks worldwide")
    adj = [SUPPLY[o]["adj"] for o in origins]
    joined = adj[0] if len(adj) == 1 else ", ".join(adj[:-1]) + " and " + adj[-1]
    return f"governed, research-ready {joined} clinical datasets"


def core_term(term: str) -> str:
    """'Gaucher disease' -> 'gaucher'; a lower-cased phrase for containment checks."""
    t = re.sub(r"\s+(disease|syndrome|disorder)s?$", "", (term or "").strip(), flags=re.I)
    return t.lower()


@dataclass
class SearchQuery:
    disease: str = ""
    intervention: str = ""          # drug, device or procedure
    biomarker: str = ""             # gene, mutation, marker
    data_types: list[str] = field(default_factory=list)   # DATA_TYPES codes
    population: str = ""            # e.g. "South Asian", "paediatric"
    sponsor: str = ""               # company or institution
    supply: list[str] = field(default_factory=lambda: list(ALL_ORIGINS))   # SUPPLY keys

    def __post_init__(self):
        self.data_types = [d for d in dict.fromkeys(self.data_types) if d in DATA_TYPES]
        if isinstance(self.supply, str):
            self.supply = [self.supply]
        self.supply = [o for o in dict.fromkeys(self.supply or []) if o in SUPPLY] or list(ALL_ORIGINS)
        for f in ("disease", "intervention", "biomarker", "population", "sponsor"):
            setattr(self, f, (getattr(self, f) or "").strip())

    @classmethod
    def of(cls, q: "SearchQuery | str | dict | None") -> "SearchQuery":
        if isinstance(q, SearchQuery):
            return q
        if isinstance(q, str):
            return cls(disease=q)
        return cls(**{k: v for k, v in (q or {}).items() if k in cls.__dataclass_fields__})

    # ---- shape
    @property
    def empty(self) -> bool:
        """A search needs a topic or a company; data type and population only
        narrow one (every paper mentions "imaging" somewhere)."""
        return not any((self.disease, self.intervention, self.biomarker, self.sponsor))

    @property
    def worldwide(self) -> bool:
        return set(self.supply) >= set(ALL_ORIGINS)

    @property
    def supply_codes(self) -> set[str]:
        return set().union(*(SUPPLY[o]["codes"] for o in self.supply))

    @property
    def phrases(self) -> list[str]:
        """Topical phrases every result must mention (population and data type
        are handled separately: they widen, then filter)."""
        return [p for p in (self.disease, self.intervention, self.biomarker) if p]

    @property
    def data_type_phrases(self) -> list[str]:
        return [ph for d in self.data_types for ph in DATA_TYPES[d][1]]

    def label(self) -> str:
        parts = [self.disease, self.intervention, self.biomarker]
        parts += [DATA_TYPES[d][0].split(" /")[0].lower() + " data" for d in self.data_types]
        if self.population:
            parts.append(self.population)
        if self.sponsor:
            parts.append(f"at {self.sponsor}")
        return " · ".join(p for p in parts if p) or "(empty search)"

    def to_dict(self) -> dict:
        return asdict(self)

    # ---- relevance
    def matches(self, *texts: str, min_hits: int = 1) -> bool:
        """True when every topical phrase appears in the texts (at least
        `min_hits` times in total for each), and, if data types were asked
        for, at least one of their phrases does too."""
        blob = " ".join(t or "" for t in texts).lower()
        for p in self.phrases:
            if blob.count(core_term(p)) < min_hits:
                return False
        if self.data_types and not any(ph.lower() in blob for ph in self.data_type_phrases):
            return False
        if self.population and core_term(self.population) not in blob:
            return False
        return True

    def matches_title_or_body(self, title: str, body: str) -> bool:
        """Grant relevance: in the title, or recurring in the abstract."""
        return self.matches(title) or self.matches(body, min_hits=2) or self.matches(title, body, min_hits=2)

    # ---- per-source query text
    def free_text(self, quote: str = '"') -> str:
        """Space-joined quoted phrases, for sources that AND their words."""
        return " ".join(f"{quote}{p}{quote}" for p in self.phrases + ([self.population] if self.population else []))

    def epmc_clause(self) -> str:
        parts = [f'ABSTRACT:"{p}"' for p in self.phrases]
        if self.data_types:
            parts.append("(" + " OR ".join(f'ABSTRACT:"{ph}"' for ph in self.data_type_phrases) + ")")
        if self.population:
            parts.append(f'ABSTRACT:"{self.population}"')
        if self.sponsor:
            parts.append(f'AFF:"{self.sponsor}"')
        return " AND ".join(parts)


def detect_data_type_needs(sentence_low: str) -> dict[str, str]:
    """Data-type gaps stated in one (already gap-cued) sentence."""
    return {f"data_{code}": desc for code, (_, _, desc, pats) in DATA_TYPES.items()
            if any(re.search(p, sentence_low) for p in pats)}
