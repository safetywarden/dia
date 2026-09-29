"""BCONZ DIA API: runs DIA -> PCIA and serves leads, contacts and gated export.

Every route except /health requires `Authorization: Bearer $DIA_API_TOKEN`.
The web app holds that token server-side and forwards the signed-in user's
identity in `X-DIA-User`, which is recorded on runs, exports and
suppressions for the audit trail.
"""
from __future__ import annotations

import csv
import hmac
import io
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from bconz import dia, outreach, pcia
from bconz.fit import DatasetProfile, from_harm
from bconz.query import DATA_TYPES, SUPPLY, SearchQuery

from . import db, worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
TOKEN = os.environ.get("DIA_API_TOKEN", "").strip()
RUN_WORKER = os.environ.get("DIA_RUN_WORKER", "1") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not TOKEN:
        logging.warning("DIA_API_TOKEN is not set — every authenticated route will refuse")
    db.init()
    stop = None
    if RUN_WORKER:
        worker.recover_stale()
        stop = worker.start()
    yield
    if stop:
        stop.set()


app = FastAPI(title="BCONZ DIA API", version=dia.VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=[o for o in os.environ.get("DIA_CORS", "").split(",") if o],
                   allow_methods=["*"], allow_headers=["*"])


def user(authorization: str = Header(default=""),
         x_dia_user: str = Header(default="")) -> str:
    supplied = authorization.removeprefix("Bearer ").strip()
    if not TOKEN or not hmac.compare_digest(supplied, TOKEN):
        raise HTTPException(401, "invalid or missing API token")
    return x_dia_user or "api"


# ------------------------------------------------------------------ schemas

class RunIn(BaseModel):
    # Any combination of facets; at least one of disease, intervention,
    # biomarker or sponsor. See bconz/query.py.
    disease: str = Field("", max_length=200)
    intervention: str = Field("", max_length=200)
    biomarker: str = Field("", max_length=200)
    data_types: list[str] = Field(default_factory=list)
    population: str = Field("", max_length=120)
    sponsor: str = Field("", max_length=200)
    # Where the offered data comes from; default worldwide.
    supply: list[str] = Field(default_factory=list)
    top_contacts: int = Field(20, ge=0, le=60)
    years: int = Field(3, ge=1, le=10)
    # Markets whose registries to search. Europe PMC and ClinicalTrials.gov are
    # global and always included.
    regions: list[Literal["us", "eu", "uk", "in"]] = Field(default_factory=lambda: ["us", "eu", "uk", "in"])


class SuppressIn(BaseModel):
    value: str = Field(min_length=3, max_length=300)
    reason: str = ""


class WatchIn(BaseModel):
    disease: str = Field(min_length=3, max_length=200)     # the search's label
    interval_days: int = Field(7, ge=1, le=90)
    query: dict | None = None                               # full query, when faceted
    regions: list[str] | None = None


def run_out(r: db.Run, full: bool = False) -> dict:
    out = {"id": r.id, "disease": r.disease, "status": r.status, "summary": r.summary,
           "created_by": r.created_by, "watch_id": r.watch_id,
           "created_at": r.created_at, "finished_at": r.finished_at, "params": r.params}
    if full:
        out |= {"diagnostics": r.diagnostics, "progress": r.progress,
                "error": r.error.splitlines()[0] if r.error else ""}
    return out


def _run(s, run_id: int) -> db.Run:
    r = s.get(db.Run, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r


# ------------------------------------------------------------------- routes

@app.get("/options")
def options(_: str = Depends(user)):
    """Vocabulary for the search form, so the web app never drifts from the engine."""
    return {"data_types": {k: v[0] for k, v in DATA_TYPES.items()},
            "supply": {k: v["label"] for k, v in SUPPLY.items()},
            "regions": list(dia.REGIONS)}


@app.get("/health")
def health():
    with db.Session() as s:
        s.execute(select(1))
    return {"ok": True, "dia": dia.VERSION, "pcia": pcia.VERSION}


@app.post("/runs", status_code=201)
def create_run(body: RunIn, who: str = Depends(user)):
    if not body.regions:
        raise HTTPException(422, "choose at least one market")
    q = SearchQuery(disease=body.disease, intervention=body.intervention,
                    biomarker=body.biomarker, data_types=body.data_types,
                    population=body.population, sponsor=body.sponsor, supply=body.supply)
    if q.empty:
        raise HTTPException(422, "give a disease, drug, biomarker or company")
    with db.Session() as s:
        r = db.Run(disease=q.label()[:200], created_by=who,
                   params={"top_contacts": body.top_contacts, "years": body.years,
                           "regions": sorted(set(body.regions)), "query": q.to_dict()})
        s.add(r)
        s.commit()
        return run_out(r, full=True)


@app.get("/runs")
def list_runs(limit: int = Query(50, le=200), _: str = Depends(user)):
    with db.Session() as s:
        rows = s.scalars(select(db.Run).order_by(db.Run.created_at.desc()).limit(limit))
        return [run_out(r) for r in rows]


@app.get("/runs/{run_id}")
def get_run(run_id: int, _: str = Depends(user)):
    with db.Session() as s:
        return run_out(_run(s, run_id), full=True)


@app.get("/runs/{run_id}/leads")
def get_leads(run_id: int, tier: str | None = None, new_only: bool = False,
              _: str = Depends(user)):
    with db.Session() as s:
        _run(s, run_id)
        q = select(db.Lead).where(db.Lead.run_id == run_id).order_by(db.Lead.rank)
        if tier:
            q = q.where(db.Lead.tier.in_(list(tier.upper())))
        if new_only:
            q = q.where(db.Lead.is_new.is_(True))
        return [{**l.data, "rank": l.rank, "is_new": l.is_new} for l in s.scalars(q)]


@app.get("/runs/{run_id}/contacts")
def get_contacts(run_id: int, _: str = Depends(user)):
    with db.Session() as s:
        _run(s, run_id)
        supp = worker.suppression_set()
        out = []
        for c in s.scalars(select(db.Contact).where(db.Contact.run_id == run_id)
                           .order_by(db.Contact.exportable.desc(), db.Contact.id)):
            d = dict(c.data)
            if _suppressed_now(c, supp):
                d |= {"exportable": False, "suppressed": True,
                      "gate_reason": "suppressed by do-not-contact list"}
            out.append(d)
        return out


def _suppressed_now(c: db.Contact, supp: set[str]) -> bool:
    return (c.value or "").lower() in supp or c.person_name.lower() in supp


@app.get("/runs/{run_id}/contacts.csv")
def export_contacts(run_id: int, strict: bool = False, who: str = Depends(user)):
    """Gated export. Only records with an exportable (source, basis) pair that
    are not on the do-not-contact list *today* leave the system. Exclusions
    are counted in the response headers and the audit log — never dropped
    silently. `strict=true` refuses the whole export if anything is excluded."""
    with db.Session() as s:
        run = _run(s, run_id)
        supp = worker.suppression_set()
        rows = list(s.scalars(select(db.Contact).where(db.Contact.run_id == run_id)))
        ok = [c for c in rows if c.exportable and not _suppressed_now(c, supp)]
        excluded = len(rows) - len(ok)
        if strict and excluded:
            raise HTTPException(409, f"{excluded} record(s) lack an exportable lawful basis "
                                     f"or are suppressed; strict export refused")
        s.add(db.Export(run_id=run_id, rows=len(ok), excluded=excluded, exported_by=who))
        s.commit()

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["organisation", "person", "role", "channel", "value", "source_url",
                    "source_type", "lawful_basis", "jurisdiction", "retrieved_at",
                    "why_this_person", "relation_to_need", "about"])
        for c in ok:
            p = c.data["provenance"]
            w.writerow([c.org_display, c.person_name, c.person_role, c.channel, c.value,
                        c.source_url, c.source_type, c.lawful_basis, c.jurisdiction,
                        p.get("retrieved_at", ""), c.data.get("why_this_person", ""),
                        c.data.get("relation", ""), c.data.get("about", "")])
        slug = "".join(ch if ch.isalnum() else "_" for ch in run.disease.lower())
        return StreamingResponse(
            iter([buf.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="contacts_{slug}_{run_id}.csv"',
                     "X-Exported-Rows": str(len(ok)), "X-Excluded-Rows": str(excluded),
                     "Access-Control-Expose-Headers": "X-Exported-Rows, X-Excluded-Rows"})


@app.get("/runs/{run_id}/exports")
def list_exports(run_id: int, _: str = Depends(user)):
    with db.Session() as s:
        return [{"rows": e.rows, "excluded": e.excluded, "by": e.exported_by,
                 "at": e.created_at}
                for e in s.scalars(select(db.Export).where(db.Export.run_id == run_id)
                                   .order_by(db.Export.created_at.desc()))]


# -------------------------------------------------------------- suppression

@app.get("/suppression")
def list_suppression(_: str = Depends(user)):
    with db.Session() as s:
        return [{"id": x.id, "value": x.value, "reason": x.reason, "by": x.created_by,
                 "at": x.created_at}
                for x in s.scalars(select(db.Suppression).order_by(db.Suppression.id.desc()))]


@app.post("/suppression", status_code=201)
def add_suppression(body: SuppressIn, who: str = Depends(user)):
    v = body.value.strip().lower()
    with db.Session() as s:
        if s.scalar(select(db.Suppression).where(db.Suppression.value == v)):
            return {"value": v, "already": True}
        s.add(db.Suppression(value=v, reason=body.reason, created_by=who))
        s.commit()
    return {"value": v}


@app.delete("/suppression/{sid}", status_code=204)
def remove_suppression(sid: int, _: str = Depends(user)):
    with db.Session() as s:
        s.execute(delete(db.Suppression).where(db.Suppression.id == sid))
        s.commit()


# ----------------------------------------------------------------- outreach

class DraftIn(BaseModel):
    org_key: str = Field(min_length=1, max_length=300)
    person_name: str = Field("", max_length=300)
    email: str = Field("", max_length=300)
    found_at: str = Field("", max_length=1000)      # where the address was published


class OutreachEdit(BaseModel):
    person_name: str | None = Field(None, max_length=300)
    email: str | None = Field(None, max_length=300)
    found_at: str | None = Field(None, max_length=1000)
    subject: str | None = Field(None, max_length=300)
    body: str | None = Field(None, max_length=20000)
    linkedin: str | None = Field(None, max_length=2000)
    status: Literal["draft", "queued", "sent", "skipped"] | None = None


def outreach_out(o: db.Outreach, warning: str = "") -> dict:
    return {"id": o.id, "run_id": o.run_id, "org_key": o.org_key, "org_display": o.org_display,
            "person_name": o.person_name, "email": o.email, "found_at": o.found_at,
            "subject": o.subject, "body": o.body, "linkedin": o.linkedin, "angle": o.angle,
            "status": o.status, "created_by": o.created_by, "created_at": o.created_at,
            "updated_at": o.updated_at, "sent_at": o.sent_at, "warning": warning}


def _check_address(s, email: str, found_at: str, person: str) -> str:
    """Refuse suppressed or malformed addresses; warn on an earlier message."""
    email = email.strip()
    if not email:
        return ""
    if not outreach.EMAIL_OK.match(email):
        raise HTTPException(422, "that doesn't look like an email address")
    if not found_at.strip():
        raise HTTPException(422, "say where you found this address (a URL or the page/paper); "
                                 "the email tells the recipient")
    supp = worker.suppression_set()
    if email.lower() in supp or (person and person.lower() in supp):
        raise HTTPException(409, f"{email} is on the do-not-contact list")
    earlier = s.scalar(select(db.Outreach).where(func.lower(db.Outreach.email) == email.lower(),
                                                 db.Outreach.status == "sent"))
    return (f"Already sent to {email} on {earlier.sent_at:%d %b %Y}: one follow-up at most."
            if earlier and earlier.sent_at else "")


@app.post("/runs/{run_id}/outreach", status_code=201)
def draft_outreach(run_id: int, body: DraftIn, who: str = Depends(user)):
    """Write a first-touch draft for one lead of a run. Nothing is sent."""
    with db.Session() as s:
        run = _run(s, run_id)
        lead = s.scalar(select(db.Lead).where(db.Lead.run_id == run_id, db.Lead.org_key == body.org_key))
        if lead is None:
            raise HTTPException(404, "lead not found in this run")
        warning = _check_address(s, body.email, body.found_at, body.person_name)
        params = run.params or {}
        supply = (params.get("query") or {}).get("supply") or None
        d = outreach.draft(lead.data, params.get("dataset"), supply, body.person_name, body.found_at)
        o = db.Outreach(run_id=run_id, org_key=lead.org_key, org_display=lead.org_display,
                        person_name=body.person_name.strip(), email=body.email.strip(),
                        found_at=body.found_at.strip(), subject=d["subject"], body=d["body"],
                        linkedin=d["linkedin"], angle=d["angle"], created_by=who)
        s.add(o)
        s.commit()
        return outreach_out(o, warning)


@app.get("/outreach")
def list_outreach(status: str | None = None, run_id: int | None = None, _: str = Depends(user)):
    with db.Session() as s:
        q = select(db.Outreach).order_by(db.Outreach.updated_at.desc())
        if status:
            q = q.where(db.Outreach.status.in_(status.split(",")))
        if run_id:
            q = q.where(db.Outreach.run_id == run_id)
        return [outreach_out(o) for o in s.scalars(q)]


@app.put("/outreach/{oid}")
def edit_outreach(oid: int, body: OutreachEdit, _: str = Depends(user)):
    with db.Session() as s:
        o = s.get(db.Outreach, oid)
        if o is None:
            raise HTTPException(404, "not found")
        changes = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else body.dict(exclude_none=True)
        new_email = changes.get("email", o.email)
        new_found = changes.get("found_at", o.found_at)
        warning = ""
        if "email" in changes or changes.get("status") in ("queued", "sent"):
            warning = _check_address(s, new_email, new_found, changes.get("person_name", o.person_name))
        if changes.get("status") in ("queued", "sent") and not new_email:
            raise HTTPException(422, "add the recipient's email first")
        for k, v in changes.items():
            setattr(o, k, v.strip() if isinstance(v, str) and k in ("email", "found_at", "person_name") else v)
        if changes.get("status") == "sent" and not o.sent_at:
            o.sent_at = db.now()
        o.updated_at = db.now()
        s.commit()
        return outreach_out(o, warning)


@app.delete("/outreach/{oid}", status_code=204)
def delete_outreach(oid: int, _: str = Depends(user)):
    with db.Session() as s:
        s.execute(delete(db.Outreach).where(db.Outreach.id == oid))
        s.commit()


@app.get("/outreach/outbox.json")
def outbox(_: str = Depends(user)):
    """Queued emails in the format send_outreach.py reads. Suppressed addresses
    are left out even if they were queued before the request to stop."""
    supp = worker.suppression_set()
    with db.Session() as s:
        rows = s.scalars(select(db.Outreach).where(db.Outreach.status == "queued", db.Outreach.email != ""))
        return [{"to": o.email, "subject": o.subject, "body": o.body.rstrip("\n") + "\n", "dia_outreach_id": o.id}
                for o in rows if o.email.lower() not in supp]


# ----------------------------------------------------------------- datasets

class DatasetIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    partner: str = Field("", max_length=200)
    origin: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    data_types: list[str] = Field(default_factory=list)
    patients: int | None = Field(None, ge=0)
    disease_patients: dict[str, int] = Field(default_factory=dict)
    sites: int | None = Field(None, ge=0)
    followup_median_years: float | None = Field(None, ge=0, le=100)
    diverse: bool | None = None
    prospective: bool | None = None
    population: str = Field("", max_length=500)
    coding: list[str] = Field(default_factory=list)
    years: str = Field("", max_length=40)
    source: str = "manual"
    notes: str = Field("", max_length=2000)
    search_focus: list[str] = Field(default_factory=list)
    outreach_blurb: str = Field("", max_length=1500)


class HarmIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    partner: str = ""
    origin: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    report: dict


class MatchIn(BaseModel):
    regions: list[Literal["us", "eu", "uk", "in"]] = Field(default_factory=lambda: ["us", "eu", "uk", "in"])
    top_contacts: int = Field(20, ge=0, le=60)


def dataset_out(d: db.Dataset) -> dict:
    return {"id": d.id, "name": d.name, "partner": d.partner, "profile": d.profile,
            "created_by": d.created_by, "created_at": d.created_at, "updated_at": d.updated_at}


def _profile(body: DatasetIn) -> DatasetProfile:
    p = DatasetProfile.of(body.dict() if hasattr(body, "dict") else body.model_dump())
    if not p.diseases:
        raise HTTPException(422, "a dataset needs at least one disease")
    return p


@app.get("/datasets")
def list_datasets(_: str = Depends(user)):
    with db.Session() as s:
        return [dataset_out(d) for d in s.scalars(select(db.Dataset).order_by(db.Dataset.updated_at.desc()))]


@app.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, who: str = Depends(user)):
    p = _profile(body)
    with db.Session() as s:
        d = db.Dataset(name=p.name, partner=p.partner, profile=p.to_dict(), created_by=who)
        s.add(d)
        s.commit()
        return dataset_out(d)


@app.put("/datasets/{did}")
def update_dataset(did: int, body: DatasetIn, _: str = Depends(user)):
    p = _profile(body)
    with db.Session() as s:
        d = s.get(db.Dataset, did)
        if d is None:
            raise HTTPException(404, "dataset not found")
        d.name, d.partner, d.profile, d.updated_at = p.name, p.partner, p.to_dict(), db.now()
        s.commit()
        return dataset_out(d)


@app.delete("/datasets/{did}", status_code=204)
def delete_dataset(did: int, _: str = Depends(user)):
    with db.Session() as s:
        s.execute(delete(db.Dataset).where(db.Dataset.id == did))
        s.commit()


@app.post("/datasets/from-harm")
def dataset_from_harm(body: HarmIn, _: str = Depends(user)):
    """Derive a profile from a HARM readiness_report.json for review. The
    report itself is not stored; only the returned aggregate profile is, and
    only if the caller then saves it."""
    return from_harm(body.report, body.name, body.origin, body.diseases, body.partner).to_dict()


@app.post("/datasets/{did}/match", status_code=201)
def match_dataset(did: int, body: MatchIn, who: str = Depends(user)):
    with db.Session() as s:
        d = s.get(db.Dataset, did)
        if d is None:
            raise HTTPException(404, "dataset not found")
        r = db.Run(disease=f"Buyers for {d.name}"[:200], created_by=who,
                   params={"dataset_id": d.id, "dataset": d.profile, "regions": sorted(set(body.regions)),
                           "top_contacts": body.top_contacts})
        s.add(r)
        s.commit()
        return run_out(r, full=True)


# ------------------------------------------------------------------ watches

@app.get("/watches")
def list_watches(_: str = Depends(user)):
    with db.Session() as s:
        out = []
        for w in s.scalars(select(db.Watch).order_by(db.Watch.created_at.desc())):
            last = s.scalar(select(db.Run).where(db.Run.watch_id == w.id)
                            .order_by(db.Run.created_at.desc()).limit(1))
            out.append({"id": w.id, "disease": w.disease, "interval_days": w.interval_days,
                        "active": w.active, "last_run_at": w.last_run_at,
                        "signals_tracked": len(w.seen_signals or []),
                        "last_run": run_out(last) if last else None})
        return out


@app.post("/watches", status_code=201)
def add_watch(body: WatchIn, who: str = Depends(user)):
    with db.Session() as s:
        w = s.scalar(select(db.Watch).where(func.lower(db.Watch.disease)
                                            == body.disease.strip().lower()))
        query = {**(body.query or {}), "_regions": body.regions} if body.query else None
        if w:
            w.active, w.interval_days = True, body.interval_days
            w.query = query or w.query
        else:
            w = db.Watch(disease=body.disease.strip(), interval_days=body.interval_days,
                         created_by=who, query=query)
            s.add(w)
        s.commit()
        return {"id": w.id, "disease": w.disease, "interval_days": w.interval_days}


@app.delete("/watches/{wid}", status_code=204)
def stop_watch(wid: int, _: str = Depends(user)):
    with db.Session() as s:
        w = s.get(db.Watch, wid)
        if w:
            w.active = False
            s.commit()
