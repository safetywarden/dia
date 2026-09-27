import pytest

from bconz import dia
from bconz.query import ALL_ORIGINS, SearchQuery, supply_label, supply_pitch


def test_every_facet_must_match():
    q = SearchQuery(disease="glaucoma", intervention="latanoprost")
    assert q.matches("Latanoprost versus timolol in open-angle glaucoma")
    assert not q.matches("Open-angle glaucoma progression")          # drug missing
    q2 = SearchQuery(disease="diabetic retinopathy", data_types=["imaging"])
    assert q2.matches("Fundus imaging for diabetic retinopathy screening")
    assert not q2.matches("Diabetic retinopathy and HbA1c")          # no imaging term


def test_empty_needs_a_topic_or_company():
    assert SearchQuery(data_types=["imaging"]).empty
    assert SearchQuery(population="South Asian").empty
    assert not SearchQuery(sponsor="Novartis").empty
    assert not SearchQuery(intervention="semaglutide").empty


def test_supply_defaults_to_worldwide_and_validates():
    assert SearchQuery(disease="asthma").worldwide
    assert SearchQuery(disease="asthma", supply=["US", "XX"]).supply == ["US"]
    assert SearchQuery(disease="asthma", supply="US").supply == ["US"]


def test_pitch_names_the_origin():
    assert "US" in supply_pitch(["US"]) and "Indian" not in supply_pitch(["US"])
    assert "partner networks worldwide" in supply_pitch(ALL_ORIGINS)
    assert supply_label(["US", "UK"]) == "the United States or the UK"


def test_old_disease_string_still_works():
    assert SearchQuery.of("Gaucher disease").disease == "Gaucher disease"
    assert dia.grant_is_about("Gaucher disease", "Gene therapy for Gaucher disease", "")


def _trial(countries, **extra):
    return dia.Signal(source="trials", org_raw="X", date="", title="", url="u", snippet="",
                      extra={"countries": countries, "nct": "NCT1", **extra})


def test_geography_for_us_data():
    q = SearchQuery(disease="asthma", supply=["US"])
    eu_only, has_us = _trial(["Germany", "France"]), _trial(["United States", "Germany"])
    dia.apply_geography([eu_only, has_us], q)
    assert "no sites in the United States" in eu_only.needs["geographic_gap"]
    assert "geographic_gap" not in has_us.needs
    assert "asia_absent" not in eu_only.needs                 # not relevant to US supply


def test_geography_worldwide_flags_single_region_programmes():
    q = SearchQuery(disease="asthma")
    one, many = _trial(["United States"]), _trial(["United States", "Germany", "Japan"])
    dia.apply_geography([one, many], q)
    assert "only in the United States" in one.needs["geographic_gap"]
    assert "geographic_gap" not in many.needs


def test_eu_only_registry_never_asserts_geography():
    s = _trial(["Germany"], eu_only_registry=True)
    dia.apply_geography([s], SearchQuery(disease="asthma", supply=["US"]))
    assert s.needs == {}


@pytest.mark.parametrize("sentence,code", [
    ("Imaging data were not available for most patients, a key limitation.", "data_imaging"),
    ("Future studies with longitudinal electronic health records are needed.", "data_ehr"),
    ("A limitation is the lack of genomic data in this cohort.", "data_genomic"),
])
def test_data_type_needs(sentence, code):
    assert code in dia.detect_needs(sentence)


def test_passing_mention_is_not_a_paper_about_the_disease():
    q = SearchQuery(disease="chronic kidney disease")
    assert not q.matches_title_or_body(
        "Outcomes of staged versus primary major amputation",
        "Patients with diabetes, chronic kidney disease and heart failure were included.")
    assert q.matches_title_or_body("Progression of chronic kidney disease in adults", "")
    assert q.matches_title_or_body("Kidney outcomes", "In chronic kidney disease … chronic kidney disease")


def test_titles_lose_markup():
    assert dia.clean_text("Diagnostic [&lt;sup&gt;68&lt;/sup&gt;Ga]Ga-FAPI PET") == "Diagnostic [68Ga]Ga-FAPI PET"


def test_academic_name_beats_a_wrong_industry_class():
    from bconz.orgs import org_type
    assert org_type("Stanford University", "INDUSTRY") == "academic"
    assert org_type("Novartis Pharmaceuticals", "INDUSTRY") == "industry"
    assert org_type("Janssen Research & Development", "INDUSTRY") == "industry"


def test_data_type_need_requires_a_gap():
    assert "data_imaging" not in dia.detect_needs("We analysed OCT imaging data from 400 eyes.")
