import pytest

from bconz.pcia import (Basis, ContactRecord, ExportGateError, Provenance, SourceType,
                        assert_exportable, export_csv, resolve_jurisdiction)


def rec(source_type=SourceType.SELF_PUBLISHED_CORRESPONDENCE, basis=Basis.DPDP_3C_II,
        value="a@b.org", suppressed=False):
    return ContactRecord(
        org_display="Org", org_key="org", person_name="A Person", person_role="x",
        channel="email", value=value, suppressed=suppressed,
        provenance=Provenance(source_url="https://x", source_type=source_type,
                              lawful_basis=basis, retrieved_at="", verbatim_snippet=""),
        why_this_person="")


def test_inferred_cannot_be_laundered_with_a_claimed_basis():
    r = rec(SourceType.INFERRED, Basis.DPDP_3C_II)
    assert not r.exportable
    assert "INFERRED" in r.gate_reason


def test_suppressed_and_valueless_records_are_blocked():
    assert not rec(suppressed=True).exportable
    assert not rec(value=None).exportable


def test_export_reports_exclusions_instead_of_dropping_silently(tmp_path):
    good, bad = rec(), rec(SourceType.INFERRED)
    n, excluded = export_csv([good, bad], tmp_path / "c.csv")
    assert n == 1 and excluded == [bad]
    with pytest.raises(ExportGateError):
        export_csv([good, bad], tmp_path / "c2.csv", strict=True)
    with pytest.raises(ExportGateError):
        assert_exportable([bad])


@pytest.mark.parametrize("evidence,regime,country", [
    ((("email", "kumar.shaji@mayo.edu"),), "US", "US"),
    ((("email", "x@aiims.ac.in"),), "IN", "IN"),
    ((("email", "x@gmail.com"), ("footprint", "DE")), "EU_UK", "DE"),
    ((("phone", "+91 80 1234 5678"),), "IN", "IN"),
    ((("affiliation", "Tata Memorial Hospital, Mumbai, India"),), "IN", "IN"),
    ((("lead_country", "JP"),), "OTHER", "JP"),
    ((), "UNKNOWN", ""),
])
def test_jurisdiction(evidence, regime, country):
    got = resolve_jurisdiction(*evidence)
    assert got[:2] == (regime, country)


def test_plus_one_is_only_a_fallback():
    # +1 is North America; a footprint naming Canada must win over it.
    assert resolve_jurisdiction(("phone", "+1 416 555 0100"), ("footprint", "CA"))[1] == "CA"
    assert resolve_jurisdiction(("phone", "+1 617 555 0100"))[0] == "US"


# ------------------------------------------------ the right person for the need

from bconz import pcia  # noqa: E402


def test_corresponding_author_in_author_notes_footnote():
    """BMJ, AME and MDPI put the address in an <author-notes> footnote, not <corresp>."""
    xml = ('<front><author-notes><fn id="cor1"><label>✉</label><p>Dr Dejana Braithwaite; '
           '<email>dbraithwaite@ufl.edu</email></p></fn><fn id="fn5"><p>No competing interests. '
           'x@y.org</p></fn></author-notes></front>')
    blocks = pcia.corresp_blocks(xml)
    assert len(blocks) == 1 and "dbraithwaite" in blocks[0]
    mdpi = '<author-notes><fn id="c1-cancers-17-03406"><p>Correspondence: <email>jwu11@mdanderson.org</email></p></fn></author-notes>'
    assert pcia.corresp_blocks(mdpi)


def test_short_surname_email_is_attributed_by_initial_and_surname():
    authors = [{"firstName": "Jia", "lastName": "Wu"}, {"firstName": "Brett", "lastName": "Carter"}]
    assert pcia._author_for_email("jwu11@mdanderson.org", authors) == "Jia Wu"
    assert pcia._author_for_email("lab@mdanderson.org", authors) == ""


def test_affiliation_email_belongs_to_that_author_only():
    authors = [{"fullName": "Sheng B", "authorAffiliationDetailsList": {"authorAffiliation": [
                   {"affiliation": "Shanghai Jiao Tong University, China. Electronic address: shengbin@cs.sjtu.edu.cn."}]}},
               {"fullName": "Wong MYH", "authorAffiliationDetailsList": {"authorAffiliation": [
                   {"affiliation": "University of Cambridge, UK."}]}}]
    assert [(n, e) for n, e, _ in pcia.affiliation_emails(authors)] == [("Sheng B", "shengbin@cs.sjtu.edu.cn")]


def _fit_lead():
    return {"org_display": "Univ X", "fit": {
                "label": "Partial", "met": [{"need": "diverse_population"}, {"need": "geographic_gap"}],
                "anchor": {"url": "https://europepmc.org/article/MED/2"}},
            "signals": [
                {"source": "trials", "url": "t1", "title": "Unrelated drug trial",
                 "needs": {"geographic_gap": "no sites in India"}, "extra": {"nct": "NCT1"}},
                {"source": "publications", "url": "https://europepmc.org/article/MED/1", "title": "Other paper",
                 "needs": {}},
                {"source": "publications", "url": "https://europepmc.org/article/MED/2", "title": "The paper",
                 "needs": {"diverse_population": "…underrepresented populations"}}]}


def test_dataset_match_starts_from_the_paper_that_states_the_need():
    order = pcia.evidence_first(_fit_lead())
    assert order[0][0]["title"] == "The paper" and order[0][1] is True
    # The trial is relevant only through geography, which a paper-based fit doesn't rest on.
    assert dict((s["title"], r) for s, r in order)["Unrelated drug trial"] is False


def test_unrelated_trial_contacts_are_not_used_for_a_dataset_match(monkeypatch):
    calls = []
    monkeypatch.setattr(pcia, "contacts_from_trial", lambda *a, **k: calls.append("trial") or [])
    monkeypatch.setattr(pcia, "contacts_from_publication",
                        lambda pmid, org, why, c="", **k: calls.append(pmid) or [rec()])
    monkeypatch.setattr(pcia, "corresponding_authors_for_org", lambda *a, **k: [])
    recs = pcia.resolve({"leads": [_fit_lead()]}, log=lambda m: None)
    assert calls == ["2"]                              # only the paper stating the need
    assert recs[0].relation == "author" and recs[0].about == "The paper"


def test_plain_search_labels_colleagues_as_organisation(monkeypatch):
    lead = _fit_lead(); del lead["fit"]
    monkeypatch.setattr(pcia, "contacts_from_trial", lambda *a, **k: [rec()])
    monkeypatch.setattr(pcia, "contacts_from_publication", lambda *a, **k: [])
    recs = pcia.resolve({"leads": [lead]}, log=lambda m: None)
    assert recs and recs[0].relation == "study"        # the trial states a (geographic) need


@pytest.mark.parametrize("email,aff,org,expected", [
    ("wzhou2@emory.edu", "", "Emory University", True),
    ("jenny@gsu.edu", "", "Emory University", False),                     # co-author at Georgia State
    ("jwu11@mdanderson.org", "", "M.D. Anderson Cancer Center", True),
    ("lary.robinson@moffitt.org", "", "University of South Florida", False),
    ("someone@gmail.com", "", "Duke University", None),                    # can't tell
    ("someone@gmail.com", "Department of Radiology, Duke University, Durham NC", "Duke University", True),
    ("shengbin@cs.sjtu.edu.cn", "", "University of Cambridge", False),
])
def test_is_the_author_at_the_lead_organisation(email, aff, org, expected):
    author = {"authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": aff}]}} if aff else None
    assert pcia.at_org(email, author, org) is expected


def test_company_buyer_contacts_must_be_at_the_company(monkeypatch):
    seen = {}
    def pub(pmid, org, why, c="", require_org=False):
        seen["require_org"] = require_org
        return []
    monkeypatch.setattr(pcia, "contacts_from_publication", pub)
    monkeypatch.setattr(pcia, "corresponding_authors_for_org", lambda *a, **k: [])
    lead = {"org_display": "MIM Software Inc", "org_key": "mim software", "buyer_type": "startup",
            "buyer_intent": "Active buyer",
            "signals": [{"source": "publications", "url": "https://europepmc.org/article/MED/9", "title": "Paper",
                         "needs": {"company_rnd": "Company research"}}]}
    pcia.resolve({"leads": [lead]}, log=lambda m: None)
    assert seen["require_org"] is True


def test_510k_address_fragments_are_dropped(monkeypatch):
    class Page:
        def extract_text(self):
            return ("510(k) Summary Submitter: Viz.ai, Inc. Contact: Pooja Shah pooja.shah@viz.ai "
                    "Regulatory: poo\nja.shah@viz.ai Consultant: a@regconsult.com")
    class Reader:
        def __init__(self, *a): self.pages = [Page()]
    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", Reader)
    monkeypatch.setattr(pcia, "_get_bytes", lambda url: b"%PDF")
    recs = pcia.contacts_from_510k("K250001", "Viz.ai, Inc.", "why", "US", "Pooja Shah", "Viz device")
    assert [r.value for r in recs] == ["pooja.shah@viz.ai"]        # fragment and consultant dropped
    assert recs[0].person_name == "Pooja Shah"
