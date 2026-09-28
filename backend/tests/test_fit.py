from bconz import dia
from bconz.fit import DatasetProfile, apply_fit, from_harm, match_lead

W = {k: v[1] for k, v in dia.NEEDS.items()}


def lead(*needs, score=50.0, disease="glaucoma"):
    """One paper stating each need in its own sentence."""
    said = {n: f"The paper's sentence about {n}." for n in needs}
    return {"needs": {n: dia.NEEDS[n][0] for n in needs}, "evidence": said,
            "score": score, "_disease": disease,
            "signals": [{"source": "publications", "title": "Paper", "url": "u1", "needs": said}]}


US_EHR = DatasetProfile(name="US ophthalmology EHR", origin=["US"], diseases=["glaucoma"],
                        data_types=["ehr"], patients=42000, sites=12, followup_median_years=4.5)


def test_met_unmet_and_unknown_are_kept_apart():
    f = match_lead(lead("longitudinal_gap", "data_imaging", "diverse_population"), US_EHR, W)
    assert [r["need"] for r in f["met"]] == ["longitudinal_gap"]
    assert "4.5 years" in f["met"][0]["why"]
    assert [r["need"] for r in f["unmet"]] == ["data_imaging"]         # no imaging in profile
    assert [r["need"] for r in f["unknown"]] == ["diverse_population"]   # never assumed
    assert f["summary"] == "1 of 3 stated needs met"


def test_unknown_attributes_never_count_as_a_match():
    bare = DatasetProfile(name="x", diseases=["glaucoma"])
    f = match_lead(lead("small_sample", "single_centre", "longitudinal_gap"), bare, W)
    assert f["met"] == [] and len(f["unknown"]) == 3 and f["score"] == 0.0
    assert f["label"] == "Context only"


def test_strong_needs_a_stated_gap_not_just_geography():
    geo_only = match_lead(lead("geographic_gap", "asia_absent"), US_EHR, W)
    assert geo_only["label"] == "Geographic opening"
    strong = match_lead(lead("geographic_gap", "single_centre", "small_sample"), US_EHR, W)
    assert strong["label"] == "Strong"


def test_funded_programme_is_context_not_a_need():
    f = match_lead(lead("funded_programme", "longitudinal_gap"), US_EHR, W)
    assert f["summary"] == "1 of 1 stated needs met"


def test_disease_specific_cohort_size_is_used():
    p = DatasetProfile(name="x", diseases=["glaucoma", "asthma"], patients=50000,
                       disease_patients={"asthma": 300})
    f = match_lead(lead("small_sample", disease="asthma"), p, W)
    assert f["unmet"] and "300" in f["unmet"][0]["why"]


def test_ranking_prefers_fit_then_demand():
    doc = {"leads": [lead("data_imaging", score=90), lead("single_centre", "longitudinal_gap", score=40)],
           "summary": {}}
    apply_fit(doc, US_EHR, W)
    assert doc["leads"][0]["fit"]["label"] == "Strong"
    assert doc["summary"]["fit"] == {"Strong": 1, "Partial": 0, "Geographic opening": 0, "Context only": 1}


def test_from_harm_reads_only_aggregates():
    report = {"site_label": "Partner A", "input_fingerprint": "abc", "generated_at": "2026-09-01",
              "summary": {"patients": 18000, "domains": {"visit": 1, "condition": 1, "drug": 1}},
              "longitudinal": {"available": True, "followup_days_median": 1461},
              "cohort": {"available": True, "by_term": {"glaucoma": 2400, "asthma": 0}},
              "tables": [{"columns": [{"role": "icd"}]}]}
    p = from_harm(report, "Partner A EHR", ["US"], ["glaucoma"])
    assert p.patients == 18000 and p.data_types == ["ehr"] and p.followup_median_years == 4.0
    assert p.disease_patients == {"glaucoma": 2400} and p.coding == ["ICD"]
    assert p.sites is None and p.diverse is None          # HARM cannot establish these


def test_geography_alone_is_not_a_fit():
    f = match_lead(lead("geographic_gap"), US_EHR, W)
    assert f["met"] and f["label"] == "Geographic opening"
    assert match_lead(lead("geographic_gap", "longitudinal_gap"), US_EHR, W)["label"] == "Partial"


IMAGING = DatasetProfile(name="Imaging archive", origin=["IN"], diseases=["lung cancer"],
                         data_types=["imaging", "reports"], diverse=True, patients=100000)


def test_strong_must_rest_on_one_piece_of_work():
    """Run #30: an unrelated paper's 'diverse population' plus a trial's missing
    sites added up to Strong for work nobody at the organisation connected."""
    pooled = {"needs": {"diverse_population": "", "geographic_gap": "", "asia_absent": "",
                        "small_sample": ""},
              "score": 50.0, "_disease": "lung cancer",
              "signals": [
                  {"source": "publications", "title": "Curricula paper", "url": "p1",
                   "needs": {"diverse_population": "Underrepresented groups in radiology training."}},
                  {"source": "publications", "title": "Another paper", "url": "p2",
                   "needs": {"small_sample": "A small sample limits this study."}},
                  {"source": "trials", "title": "Drug trial", "url": "t1",
                   "needs": {"geographic_gap": "NCT1 has no sites in India", "asia_absent": "NCT1 has no sites in Asia"}}]}
    f = match_lead(pooled, IMAGING, W)
    assert f["label"] == "Partial"
    assert f["anchor"]["url"] in ("p1", "p2") and "geographic_gap" not in f["anchor"]["needs"]


def test_one_sentence_is_one_stated_need_unless_it_names_the_data():
    same = "Generalizability across diverse populations remains a challenge."
    one = {"needs": {"diverse_population": "", "generalisability": ""}, "score": 50.0, "_disease": "lung cancer",
           "signals": [{"source": "publications", "title": "Review", "url": "p1",
                        "needs": {"diverse_population": same, "generalisability": same}}]}
    assert match_lead(one, IMAGING, W)["label"] == "Partial"
    both = "Future work should incorporate multicentre imaging data to improve generalizability."
    typed = {"needs": {"data_imaging": "", "generalisability": ""}, "score": 50.0, "_disease": "lung cancer",
             "signals": [{"source": "publications", "title": "Radiomics", "url": "p1",
                          "needs": {"data_imaging": both, "generalisability": both}}]}
    assert match_lead(typed, IMAGING, W)["label"] == "Strong"


def test_search_focus_narrows_buyer_search_to_data_types():
    p = DatasetProfile(name="Imaging archive", origin=["IN"], diseases=["tuberculosis"],
                       data_types=["imaging", "reports"], search_focus=["imaging", "bogus"])
    q = p.query_for("tuberculosis")
    assert q.data_types == ["imaging"]
    assert q.matches("Deep learning on chest x-ray images for tuberculosis screening")
    assert not q.matches("Bedaquiline regimens for drug-resistant tuberculosis")


def test_reports_need_is_detected_and_met():
    assert "data_reports" in dia.detect_needs("A limitation is the lack of paired radiology reports for training.")
    p = DatasetProfile(name="x", diseases=["stroke"], data_types=["imaging", "reports"])
    f = match_lead(lead("data_reports", disease="stroke"), p, W)
    assert f["met"] and "Radiology reports" in f["met"][0]["why"]
