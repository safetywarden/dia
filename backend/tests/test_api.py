import importlib
import os

import pytest
from fastapi.testclient import TestClient

from bconz.pcia import Basis, ContactRecord, Provenance, SourceType


def _contact(value, st=SourceType.SELF_PUBLISHED_CORRESPONDENCE, basis=Basis.DPDP_3C_II):
    return ContactRecord(
        org_display="Mayo Clinic", org_key="mayo clinic", person_name=f"P {value}",
        person_role="corresponding author", channel="email" if value else "none",
        value=value, provenance=Provenance("https://europepmc.org/x", st, basis, "t", "snip",
                                           jurisdiction="US"),
        why_this_person="stated need")


FAKE_DOC = {
    "disease": "multiple myeloma", "version": "t",
    "summary": {"signals": 2, "organisations": 1, "by_source": {}, "tiers": {"A": 1}},
    "diagnostics": {},
    "leads": [{"org_key": "mayo clinic", "org_display": "Mayo Clinic", "org_type": "hospital",
               "country": "US", "score": 70.0, "tier": "A", "needs": {}, "evidence": {},
               "dimensions": {}, "rationale": [], "named_people": [], "opening_angle": "",
               "sources": ["publications"],
               "signals": [{"source": "publications", "url": "https://europepmc.org/1"}]}],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("DIA_API_TOKEN", "secret")
    monkeypatch.setenv("DIA_RUN_WORKER", "0")
    from app import db, worker, main
    importlib.reload(db); importlib.reload(worker); importlib.reload(main)
    monkeypatch.setattr(worker.dia, "run", lambda *a, **k: FAKE_DOC)
    monkeypatch.setattr(worker.pcia, "resolve", lambda *a, **k: [
        _contact("ok@mayo.edu"), _contact("guess@mayo.edu", SourceType.INFERRED), _contact(None)])
    with TestClient(main.app) as c:
        c.headers["Authorization"] = "Bearer secret"
        c.worker = worker
        yield c


def _run(client):
    rid = client.post("/runs", json={"disease": "multiple myeloma"}).json()["id"]
    client.worker.execute(client.worker._claim())
    return rid


def test_markets_are_recorded_and_required(client):
    r = client.post("/runs", json={"disease": "Gaucher disease", "regions": ["uk", "eu", "uk"]}).json()
    assert r["params"]["regions"] == ["eu", "uk"]
    assert client.post("/runs", json={"disease": "Gaucher disease", "regions": []}).status_code == 422
    assert client.post("/runs", json={"disease": "Gaucher disease", "regions": ["xx"]}).status_code == 422


def test_faceted_search_is_stored_and_labelled(client):
    r = client.post("/runs", json={"disease": "glaucoma", "data_types": ["imaging", "bogus"],
                                   "supply": ["US"]}).json()
    assert r["disease"] == "glaucoma · imaging data"
    assert r["params"]["query"]["data_types"] == ["imaging"]
    assert r["params"]["query"]["supply"] == ["US"]
    # Data type alone is not a search.
    assert client.post("/runs", json={"data_types": ["imaging"]}).status_code == 422
    opts = client.get("/options").json()
    assert "imaging" in opts["data_types"] and "US" in opts["supply"]


def test_new_column_added_to_existing_database(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)   # a watches table from before `query` existed
    con.execute("CREATE TABLE watches (id INTEGER PRIMARY KEY, disease VARCHAR(200) UNIQUE, "
                "interval_days INTEGER, active BOOLEAN, seen_signals JSON, "
                "last_run_at DATETIME, created_by VARCHAR(200), created_at DATETIME)")
    con.commit(); con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    from app import db
    importlib.reload(db)
    db.init()
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(watches)")]
    assert "query" in cols
    db.init()                                   # second start: no error, no duplicate


def test_dataset_profile_and_buyer_match(client, monkeypatch):
    body = {"name": "US ophthalmology EHR", "partner": "Partner A", "origin": ["US"],
            "diseases": ["glaucoma", "diabetic retinopathy"], "data_types": ["ehr", "imaging"],
            "patients": 42000, "sites": 12, "followup_median_years": 4.5}
    d = client.post("/datasets", json=body).json()
    assert d["profile"]["origin"] == ["US"] and d["profile"]["sites"] == 12
    assert client.post("/datasets", json={**body, "diseases": []}).status_code == 422

    harm = client.post("/datasets/from-harm", json={
        "name": "Partner B", "origin": ["US"], "diseases": ["asthma"],
        "report": {"summary": {"patients": 900, "domains": {"visit": 1, "condition": 1}}}}).json()
    assert harm["patients"] == 900 and harm["data_types"] == ["ehr"] and harm["source"] == "harm"
    assert len(client.get("/datasets").json()) == 1          # derived profile is not auto-saved

    seen = {}
    def fake_match(profile, log=None, regions=None):
        seen["profile"] = profile
        doc = {**FAKE_DOC, "disease": f"Buyers for {profile.name}",
               "summary": {**FAKE_DOC["summary"], "fit": {"Strong": 1}}}
        doc["leads"] = [{**FAKE_DOC["leads"][0], "fit": {"label": "Strong", "score": 0.7}}]
        return doc
    monkeypatch.setattr(client.worker.fit, "match_dataset", fake_match)
    run = client.post(f"/datasets/{d['id']}/match", json={"regions": ["us"]}).json()
    assert run["disease"] == "Buyers for US ophthalmology EHR"
    client.worker.execute(client.worker._claim())
    assert seen["profile"].diseases == ["glaucoma", "diabetic retinopathy"]
    leads = client.get(f"/runs/{run['id']}/leads").json()
    assert leads[0]["fit"]["label"] == "Strong"


def test_auth_required(client):
    assert client.get("/runs", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_run_and_gated_export(client):
    rid = _run(client)
    run = client.get(f"/runs/{rid}").json()
    assert run["status"] == "done" and run["summary"]["contactable"] == 1
    assert client.get(f"/runs/{rid}/leads").json()[0]["org_display"] == "Mayo Clinic"

    r = client.get(f"/runs/{rid}/contacts.csv")
    assert r.headers["X-Exported-Rows"] == "1" and r.headers["X-Excluded-Rows"] == "2"
    assert "ok@mayo.edu" in r.text and "guess@mayo.edu" not in r.text
    assert client.get(f"/runs/{rid}/contacts.csv?strict=true").status_code == 409
    assert len(client.get(f"/runs/{rid}/exports").json()) == 1      # refused one not logged


def test_legacy_migration_copies_once_and_keeps_ids(client, tmp_path, monkeypatch):
    rid = _run(client)
    client.post("/suppression", json={"value": "x@y.org"})
    from app import db
    old_url = db.URL

    # Point the app at a fresh database, with the old one as legacy.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'new.db'}")
    monkeypatch.setenv("LEGACY_DATABASE_URL", old_url)
    importlib.reload(db)
    db.Base.metadata.create_all(db.engine)
    counts = db.migrate_from_legacy()
    assert counts["runs"] == 1 and counts["leads"] == 1 and counts["contacts"] == 3
    assert counts["suppression"] == 1
    with db.Session() as s:
        assert s.get(db.Run, rid).disease == "multiple myeloma"
    assert db.migrate_from_legacy() is None          # second boot: no duplicates


def test_suppression_reaches_stored_records(client):
    rid = _run(client)
    client.post("/suppression", json={"value": "OK@mayo.edu", "reason": "asked to stop"})
    r = client.get(f"/runs/{rid}/contacts.csv")
    assert "ok@mayo.edu" not in r.text and r.headers["X-Exported-Rows"] == "0"
    shown = {c["value"]: c for c in client.get(f"/runs/{rid}/contacts").json()}
    assert shown["ok@mayo.edu"]["exportable"] is False


def test_outreach_draft_queue_and_outbox(client):
    rid = _run(client)
    bad = client.post(f"/runs/{rid}/outreach", json={"org_key": "mayo clinic", "email": "x@mayo.edu"})
    assert bad.status_code == 422                                  # must say where it was found
    d = client.post(f"/runs/{rid}/outreach", json={"org_key": "mayo clinic", "person_name": "Ann Lee",
                                                    "email": "ann.lee@mayo.edu",
                                                    "found_at": "mayo.edu research contacts page"}).json()
    assert d["status"] == "draft" and d["body"].startswith("Dear Ann Lee,")
    assert "I found your address on mayo.edu research contacts page." in d["body"]
    assert "reply \"no\"" in d["body"] and "Bangalore" in d["body"] and len(d["linkedin"]) <= 300
    assert client.get("/outreach/outbox.json").json() == []        # drafts are not sent
    q = client.put(f"/outreach/{d['id']}", json={"status": "queued", "subject": "Edited"}).json()
    box = client.get("/outreach/outbox.json").json()
    assert q["status"] == "queued" and box[0]["to"] == "ann.lee@mayo.edu" and box[0]["subject"] == "Edited"
    client.post("/suppression", json={"value": "ann.lee@mayo.edu"})
    assert client.get("/outreach/outbox.json").json() == []        # a later "no" still wins
    assert client.post(f"/runs/{rid}/outreach", json={
        "org_key": "mayo clinic", "email": "ann.lee@mayo.edu", "found_at": "x"}).status_code == 409


def test_outreach_without_email_is_a_draft_for_linkedin(client):
    rid = _run(client)
    d = client.post(f"/runs/{rid}/outreach", json={"org_key": "mayo clinic"}).json()
    assert d["body"].startswith("Dear Mayo Clinic team,") and "forward" in d["body"]
    assert client.put(f"/outreach/{d['id']}", json={"status": "queued"}).status_code == 422
