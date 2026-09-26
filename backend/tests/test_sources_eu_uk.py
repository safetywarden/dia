import pytest

from bconz import dia, orgs
from bconz import sources_eu_uk as eu


def sig(registry, **extra):
    return dia.Signal(source="trials", org_raw="Janssen", date="", title="t", url=f"u-{registry}",
                      snippet="", extra={"registry": registry, **extra})


def test_same_trial_in_three_registries_counts_once():
    ctgov = sig("ClinicalTrials.gov", nct="NCT07665450", secondary_ids=["2026-526654-14-01"])
    ctis = sig("CTIS", ct_number="2026-526654-14-01")
    isrctn = sig("ISRCTN", isrctn="15262649", nct="NCT07665450", eudract="2026-526654-14")
    other = sig("ISRCTN", isrctn="99999999")
    grant = dia.Signal(source="grants", org_raw="x", date="", title="", url="g", snippet="")
    out, dropped = eu.dedupe_trials([grant, ctgov, ctis, isrctn, other])
    assert dropped == 2 and out == [grant, ctgov, other]
    # The canonical record keeps the other registries' IDs for PCIA.
    assert ctgov.extra["isrctn"] == "15262649" and ctgov.extra["ct_number"] == "2026-526654-14-01"


def test_shared_grant_numbers_do_not_merge_different_trials():
    a = sig("ClinicalTrials.gov", nct="NCT00000001", secondary_ids=["P30CA006516", "NCI-2021-01"])
    b = sig("ClinicalTrials.gov", nct="NCT00000002", secondary_ids=["P30CA006516", "NCI-2021-01"])
    c = sig("ClinicalTrials.gov", nct="NCT00000003", secondary_ids=["2026-526654-14-01"])
    d = sig("ClinicalTrials.gov", nct="NCT00000004", secondary_ids=["2026-526654-14-01"])
    out, dropped = eu.dedupe_trials([a, b, c, d])
    assert dropped == 0 and len(out) == 4


def test_eu_number_meets_eudract_base():
    ctis = sig("CTIS", ct_number="2024-512345-11-00")
    isrctn = sig("ISRCTN", isrctn="1", eudract="2024-512345-11")
    out, dropped = eu.dedupe_trials([ctis, isrctn])
    assert dropped == 1 and out == [ctis]


@pytest.mark.parametrize("text,phases", [
    ("Therapeutic confirmatory  (Phase III)", ["PHASE3"]),
    ("Phase II/III", ["PHASE2", "PHASE3"]),
    ("Phase I", ["PHASE1"]),
    ("", []),
])
def test_phase_parsing(text, phases):
    assert eu._phases(text) == phases


def test_ctis_never_claims_a_geographic_gap(monkeypatch):
    """CTIS only lists EU sites, so 'no India site' there is not evidence."""
    monkeypatch.setattr(eu, "get", lambda *a, **k: {"data": [{
        "ctNumber": "2026-1", "ctTitle": "Multiple myeloma study", "conditions": "Multiple Myeloma",
        "trialCountries": ["France:2"], "decisionDateOverall": "16/09/2026",
        "sponsor": "Janssen Cilag International", "sponsorType": "Pharmaceutical company",
        "trialPhase": "Phase III"}], "pagination": {"nextPage": False}})
    monkeypatch.setattr(eu.time, "sleep", lambda s: None)
    out = eu.harvest_ctis("multiple myeloma", 10, lambda m: None, dia.Signal, "multiple myeloma")
    assert len(out) == 1 and out[0].needs == {} and out[0].sponsor_class == "INDUSTRY"
    assert out[0].extra["eu_only_registry"] is True


def test_uk_nations_are_gb():
    assert orgs.country_code("Belfast, Northern Ireland") == "GB"
    assert orgs.country_code("Dublin, Ireland") == "IE"
    assert orgs.country_code("Canterbury, England") == "GB"
