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
