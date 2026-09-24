import pytest

from atlas.orgs import country_code, institution_from_affiliation as inst, org_key


@pytest.mark.parametrize("affil,expected", [
    ("Department of Hematology, Mayo Clinic, Rochester, MN, USA", "Mayo Clinic"),
    ("Department of Medical Oncology, Dana-Farber Cancer Institute, Boston, MA",
     "Dana-Farber Cancer Institute"),
    ("Department of Internal Medicine, College of Medicine, Korea University, Seoul, Korea",
     "Korea University"),
    ("Clinical Research Division, Fred Hutchinson Cancer Center, Seattle, WA",
     "Fred Hutchinson Cancer Center"),
    ("Cleveland Clinic Lerner College of Medicine Case Western Reserve University "
     "Cleveland Ohio USA", "Cleveland Clinic"),
    ("Department of Hematology Instituto Nacional de Cancerología Mexico City Mexico",
     "Instituto Nacional de Cancerología"),
    ("Division of Hematology, University of Washington, Seattle", "University of Washington"),
    ("Janssen Research & Development, LLC, Spring House, PA, USA",
     "Janssen Research & Development"),
    ("Memorial Sloan Kettering Cancer Center, New York, NY 10065",
     "Memorial Sloan Kettering Cancer Center"),
    ("University of Alabama at Birmingham, Birmingham, AL", "University of Alabama at Birmingham"),
    ("Department of Hematology, University Hospital Heidelberg, Heidelberg, Germany",
     "University Hospital Heidelberg"),
    ('Servicio de Hematología, Hospital Universitario "12 de Octubre", Madrid',
     "Hospital Universitario 12 de Octubre"),
    ("Hemostaseology and Medical Oncology, Innsbruck, Austria", ""),
    ("II. Medical Clinic, University Medical Center Hamburg-Eppendorf, Hamburg",
     "University Medical Center Hamburg-Eppendorf"),
])
def test_institution(affil, expected):
    assert inst(affil) == expected


def test_nih_intramural_maps_to_parent():
    from atlas.orgs import registry_org_name
    assert registry_org_name("Division of Basic Sciences - NCI") == "National Cancer Institute"
    assert registry_org_name("Mayo Clinic Rochester") == "Mayo Clinic Rochester"


def test_never_returns_a_department():
    got = inst("Department of Nuclear Medicine and, Division of Cancer Epidemiology")
    assert not got.lower().startswith(("department", "division"))


@pytest.mark.parametrize("a,b", [
    ("Dana-Farber Cancer Inst", "Dana-Farber Cancer Institute"),
    ("M.D. Anderson Cancer Center", "MD Anderson Cancer Center"),
    ("Sanofi R&D", "Sanofi"),
    ("Janssen Research & Development, LLC", "Janssen Research and Development"),
    ("The University of Chicago", "University of Chicago"),
])
def test_variants_merge(a, b):
    assert org_key(a) == org_key(b)


def test_country():
    assert country_code("AIIMS, New Delhi, India") == "IN"
    assert country_code("Seoul, Republic of Korea") == "KR"
    assert country_code("Rochester, MN 55905") == "US"
    assert country_code("somewhere") == ""
