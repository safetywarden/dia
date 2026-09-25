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
