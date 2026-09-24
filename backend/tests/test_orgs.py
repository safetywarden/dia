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


def test_no_fallback_to_cities_or_fields():
    assert inst("Department of Internal Medicine, Yale School of Medicine, New Haven, CT") \
        == "Yale School of Medicine"
    assert inst("Section of Hematology, New Haven, CT, USA") == ""


@pytest.mark.parametrize("name,expected", [
    ("Paul Szabolcs", True), ("Jane Q. Smith, MD", True), ("Sanofi", False),
    ("Mayo Clinic", False), ("European Myeloma Network", False), ("Azafaros B.V.", False),
])
def test_looks_like_person(name, expected):
    from atlas.orgs import looks_like_person
    assert looks_like_person(name) is expected


@pytest.mark.parametrize("raw,shown", [
    ("UNIV OF TX MD ANDERSON CAN CTR", "University of Texas MD Anderson Cancer Center"),
    ("CINCINNATI CHILDRENS HOSP MED CTR", "Cincinnati Children's Hospital Medical Center"),
    ("SCRIPPS RESEARCH INSTITUTE, THE", "Scripps Research Institute"),
])
def test_nih_display(raw, shown):
    from atlas.orgs import display_name
    assert display_name(raw) == shown


def test_md_anderson_merges_across_registries():
    assert org_key("UNIV OF TX MD ANDERSON CAN CTR") == org_key("M.D. Anderson Cancer Center")


def test_grant_relevance():
    from atlas.dia import grant_is_about
    assert grant_is_about("Gaucher disease", "Gene therapy for Gaucher disease type 1", "")
    assert not grant_is_about("Gaucher disease", "Lipids in diabetic kidney disease",
                              "... as seen in Gaucher ... lipid storage ...")


def test_need_detection_requires_a_gap_for_method_phrases():
    from atlas.dia import detect_needs
    assert "real_world_data" not in detect_needs(
        "We evaluated lyso-Gb1 using real-world data from the Gaucher Outcome Survey.")
    assert "real_world_data" in detect_needs(
        "There is limited long-term real-world data on taliglucerase alfa.")
    assert "longitudinal_gap" not in detect_needs(
        "This correlated with longer follow-up duration (p = 0.001).")


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
