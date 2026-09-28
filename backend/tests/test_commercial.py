from bconz import dia, orgs
from bconz import sources_commercial as sc
from bconz.fit import DatasetProfile, match_lead
from bconz.query import SearchQuery

W = {k: v[1] for k, v in dia.NEEDS.items()}
IMAGING_Q = SearchQuery(disease="lung cancer", data_types=["imaging"], supply=["IN"])


def test_buyer_types_across_markets():
    cases = {"Qure.Ai Technologies": "startup", "Lunit Inc.": "startup", "Adas3D Medical S.L.": "startup",
             "Shanghai United Imaging Intelligence Co., Ltd.": "medtech", "Siemens Healthineers AG": "medtech",
             "IQVIA": "cro", "Google LLC": "bigtech", "Novartis Pharmaceuticals": "pharma",
             "Deeptek Medical Imaging Pvt Ltd": "startup", "Stanford University": "academic",
             "Abbott Northwestern Hospital": "hospital"}
    for name, want in cases.items():
        assert orgs.buyer_type(name, orgs.org_type(name)) == want, name


def test_fda_devices_keep_imaging_panels_and_read_country(monkeypatch):
    rows = [{"Date of Final Decision": "06/29/2026", "Submission Number": "K260001", "Device": "qXR-Detect",
             "Company": "Qure.Ai Technologies", "Panel (Lead)": "Radiology", "Primary Product Code": "QIH"},
            {"Date of Final Decision": "05/01/2026", "Submission Number": "K260002", "Device": "ECG AI",
             "Company": "Heart Co Inc", "Panel (Lead)": "Cardiovascular", "Primary Product Code": "DQK"},
            {"Date of Final Decision": "01/01/2019", "Submission Number": "K190003", "Device": "Old CT AI",
             "Company": "Old Co Inc", "Panel (Lead)": "Radiology", "Primary Product Code": "QIH"}]
    monkeypatch.setattr(sc, "fda_ai_devices", lambda: rows)
    monkeypatch.setattr(sc, "openfda_510k", lambda nums: {"K260001": {
        "country_code": "IN", "city": "MUMBAI", "contact": "Sri Anusha  Matta"}})
    out = sc.harvest_fda_devices(IMAGING_Q, 50, lambda m: None, dia.Signal)
    assert [s.extra["submission"] for s in out] == ["K260001"]         # imaging panel, recent
    s = out[0]
    assert s.country == "IN" and s.person == "Sri Anusha Matta" and "ai_product_imaging" in s.needs


def test_birac_rows_are_read_in_fives_and_filtered():
    page = ("<table><tr><td>S.No.</td><td>Applicant Name</td><td>Proposal Title</td><td>City</td><td>State</td></tr>"
            "<tr><td>1</td><td>Predible Health</td><td>EGFR mutation prediction using non-invasive imaging in lung cancer</td>"
            "<td>Trivandrum</td><td>KERALA</td><td>2</td><td>Shanmukha Innovations Pvt Ltd</td>"
            "<td>Hand-held imaging flow cytometer for malaria</td><td>Bangalore</td><td>KARNATAKA</td>"
            "<td>3</td><td>Vikas Mehra</td><td>AI imaging for stroke</td><td>Pune</td><td>MAHARASHTRA</td></table>")
    rows = sc.parse_birac(page)
    assert [r["applicant"] for r in rows] == ["Predible Health", "Shanmukha Innovations Pvt Ltd", "Vikas Mehra"]


def test_birac_keeps_clinical_imaging_companies_only(monkeypatch):
    rows = [{"sno": "1", "applicant": "Predible Health", "title": "EGFR prediction using non-invasive imaging in lung cancer",
             "city": "Trivandrum", "state": "KERALA", "scheme": "BIG", "url": "u"},
            {"sno": "2", "applicant": "Shanmukha Innovations Pvt Ltd", "title": "Hand-held imaging flow cytometer for malaria",
             "city": "Bangalore", "state": "KARNATAKA", "scheme": "BIG", "url": "u"},
            {"sno": "3", "applicant": "Vikas Mehra", "title": "AI imaging for stroke",
             "city": "Pune", "state": "MAHARASHTRA", "scheme": "BIG", "url": "u"}]
    monkeypatch.setattr(sc, "birac_projects", lambda: rows)
    out = sc.harvest_birac(IMAGING_Q, 50, lambda m: None, dia.Signal)
    assert [s.org_raw for s in out] == ["Predible Health"]   # bench imaging and individuals left out
    assert out[0].country == "IN" and out[0].extra["startup"]


def test_company_found_in_affiliation_lines():
    g = {orgs.org_key("Qure.Ai Technologies")}
    assert sc.company_in_affiliation("Qure.ai, Mumbai, India", g) == "Qure.ai"
    assert sc.company_in_affiliation("AnchorDx Medical Co, Ltd, Guangzhou, China") == "AnchorDx Medical Co, Ltd"
    assert sc.company_in_affiliation("Vuno Inc, Seoul, Republic of Korea") == "Vuno Inc"
    assert sc.company_in_affiliation("Center for Diagnostics and Therapeutics, Georgia State University") == ""
    assert sc.company_in_affiliation("Hamad Medical Corporation, Doha, Qatar") == ""
    assert sc.company_in_affiliation("Department of Engineering and Digital Technologies, University of X") == ""


def _lead(signals):
    leads = dia.build_leads(signals, IMAGING_Q)
    assert len(leads) == 1
    return leads[0]


def test_buyer_intent_needs_two_commercial_signals():
    dev = dia.Signal(source="devices", org_raw="Qure.Ai Technologies", date="2026-06-01", title="qXR (K1)",
                     url="u1", snippet="", sponsor_class="INDUSTRY",
                     needs={"ai_product_imaging": "Cleared AI product"}, extra={"submission": "K1"})
    paper = dia.Signal(source="publications", org_raw="Qure.ai", date="2025-01-01", title="Chest X-ray AI in India",
                       url="u2", snippet="", sponsor_class="INDUSTRY",
                       needs={"company_rnd": "Company research"}, extra={})
    one = _lead([dev])
    assert one.buyer_type == "startup" and one.buyer_intent == "Likely buyer"
    both = _lead([dev, paper])                                   # "Qure.ai" and "Qure.Ai Technologies" merge
    assert both.buyer_intent == "Active buyer" and len(both.commercial_evidence) == 2


def test_drug_trial_alone_is_not_a_commercial_buyer():
    trial = dia.Signal(source="trials", org_raw="Novartis Pharmaceuticals", date="2026-01-01", title="Drug X",
                       url="t", snippet="", sponsor_class="INDUSTRY", needs={}, extra={"nct": "NCT1"})
    l = _lead([trial])
    assert l.buyer_type == "pharma" and l.buyer_intent == ""


def test_cleared_imaging_product_is_met_by_an_imaging_dataset():
    p = DatasetProfile(name="x", origin=["IN"], diseases=["lung cancer"], data_types=["imaging", "reports"])
    lead = {"needs": {"ai_product_imaging": ""}, "score": 50, "_disease": "lung cancer",
            "signals": [{"source": "devices", "title": "qXR", "url": "u",
                         "needs": {"ai_product_imaging": "Cleared AI product: qXR"}}]}
    f = match_lead(lead, p, W)
    assert f["met"][0]["need"] == "ai_product_imaging" and "paired reports" in f["met"][0]["why"]
    assert f["label"] == "Partial" and f["anchor"]["source"] == "devices"


def test_large_company_subsidiaries_are_one_buyer():
    keys = {orgs.org_key(n) for n in ["Siemens Healthcare GmbH", "Siemens Medical Solutions USA, Inc.",
                                      "Siemens Healthineers AG"]}
    assert keys == {"siemens healthineers"}
    assert orgs.org_key("GE Medical Systems, LLC") == orgs.org_key("GE Healthcare") == "ge healthcare"
    assert orgs.buyer_type("GE Medical Systems, LLC", "industry") == "medtech"
