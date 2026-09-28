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


def test_trials_respect_data_type_focus(monkeypatch):
    """ClinicalTrials.gov can't filter by data type; the harvester must."""
    def study(nct, title, summary=""):
        return {"protocolSection": {"identificationModule": {"nctId": nct, "briefTitle": title},
                                    "descriptionModule": {"briefSummary": summary},
                                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Acme Pharma Inc", "class": "INDUSTRY"}},
                                    "contactsLocationsModule": {"locations": [{"country": "United States"}]}}}
    page = {"studies": [study("NCT1", "Drug X versus placebo in pneumonia"),
                        study("NCT2", "Deep learning on chest X-ray for pneumonia detection"),
                        study("NCT3", "AI triage", "Uses chest radiographs to detect pneumonia")]}
    monkeypatch.setattr(dia, "get", lambda *a, **k: page)
    monkeypatch.setattr(dia.time, "sleep", lambda s: None)
    q = SearchQuery(disease="pneumonia", data_types=["imaging"])
    got = [s.extra["nct"] for s in dia.harvest_trials(q, 10, lambda m: None)]
    assert got == ["NCT2", "NCT3"]
    assert len(dia.harvest_trials(SearchQuery(disease="pneumonia"), 10, lambda m: None)) == 3


@pytest.mark.parametrize("sentence,found", [
    # Run #30 false positives: not about people, or describing data they already have.
    ("Radiology remains underrepresented in U.S. medical school clinical curricula.", False),
    ("This study aims to illuminate the contributions of underrepresented pioneers in radiology.", False),
    ("We examined outcomes in a racially diverse cohort of 4,000 older adults.", False),
    ("Synthetic data improved recall for underrepresented classes.", False),
    # Real needs.
    ("Traditional criteria may overlook high-risk individuals, particularly in underrepresented populations.", True),
    ("External validation in multicenter and ethnically diverse cohorts is required.", True),
    ("Challenges remain, including generalizability across diverse populations.", True),
    ("Patients with severe prestroke disability (PSD) remain underrepresented in thrombectomy studies.", True),
])
def test_diverse_population_is_about_people_and_a_gap(sentence, found):
    assert ("diverse_population" in dia.detect_needs(sentence)) is found


def test_data_type_cue_must_be_near_the_data_phrase():
    methods = ("This study proposes a deep learning approach to segment lung tumor regions from CT scans "
               "and classify images as cancerous or noncancerous, aiming to overcome the limitations of "
               "conventional ML models.")
    assert "data_imaging" not in dia.detect_needs(methods)
    assert "data_imaging" not in dia.detect_needs(
        "This study evaluated limited sequence wrist MRI scans in suspected scaphoid fractures.")


def test_glued_abstract_headings_split_sentences():
    t = "Concerns about generalizability remain a barrier.MethodsWe reviewed 40 CT scans."
    assert dia.sentences(t) == ["Concerns about generalizability remain a barrier.", "We reviewed 40 CT scans."]


def test_workforce_diversity_is_not_a_data_need():
    assert "diverse_population" not in dia.detect_needs(
        "Despite growing interest, the inclusion of women and underrepresented minorities in radiology "
        "residency remains limited.")
    assert "diverse_population" in dia.detect_needs(
        "Patients from underrepresented populations are often excluded from imaging datasets.")
