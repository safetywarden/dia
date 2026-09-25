"""Atlas demand API: runs DIA -> PCIA and serves leads, contacts and gated export.

Every route except /health requires `Authorization: Bearer $ATLAS_API_TOKEN`.
The web app holds that token server-side and forwards the signed-in user's
identity in `X-Atlas-User`, which is recorded on runs, exports and
suppressions for the audit trail.
"""
from __future__ import annotations

import csv
import hmac
import io
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from atlas import dia, pcia

from . import db, worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
TOKEN = os.environ.get("ATLAS_API_TOKEN", "").strip()
RUN_WORKER = os.environ.get("ATLAS_RUN_WORKER", "1") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not TOKEN:
        logging.warning("ATLAS_API_TOKEN is not set — every authenticated route will refuse")
    db.init()
    stop = None
    if RUN_WORKER:
        worker.recover_stale()
        stop = worker.start()
    yield
    if stop:
        stop.set()


app = FastAPI(title="Atlas Demand API", version=dia.VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=[o for o in os.environ.get("ATLAS_CORS", "").split(",") if o],
                   allow_methods=["*"], allow_headers=["*"])


def user(authorization: str = Header(default=""),
         x_atlas_user: str = Header(default="")) -> str:
    supplied = authorization.removeprefix("Bearer ").strip()
    if not TOKEN or not hmac.compare_digest(supplied, TOKEN):
        raise HTTPException(401, "invalid or missing API token")
    return x_atlas_user or "api"


# ------------------------------------------------------------------ schemas

class RunIn(BaseModel):
    disease: str = Field(min_length=3, max_length=200)
    top_contacts: int = Field(20, ge=0, le=60)
    years: int = Field(3, ge=1, le=10)


class SuppressIn(BaseModel):
    value: str = Field(min_length=3, max_length=300)
    reason: str = ""


class WatchIn(BaseModel):
    disease: str = Field(min_length=3, max_length=200)
    interval_days: int = Field(7, ge=1, le=90)


def run_out(r: db.Run, full: bool = False) -> dict:
    out = {"id": r.id, "disease": r.disease, "status": r.status, "summary": r.summary,
           "created_by": r.created_by, "watch_id": r.watch_id,
           "created_at": r.created_at, "finished_at": r.finished_at}
    if full:
        out |= {"diagnostics": r.diagnostics, "progress": r.progress, "params": r.params,
                "error": r.error.splitlines()[0] if r.error else ""}
    return out


def _run(s, run_id: int) -> db.Run:
    r = s.get(db.Run, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r


# ------------------------------------------------------------------- routes

@app.get("/health")
def health():
    with db.Session() as s:
        s.execute(select(1))
    return {"ok": True, "dia": dia.VERSION, "pcia": pcia.VERSION}


@app.post("/runs", status_code=201)
def create_run(body: RunIn, who: str = Depends(user)):
    with db.Session() as s:
        r = db.Run(disease=body.disease.strip(), created_by=who,
                   params={"top_contacts": body.top_contacts, "years": body.years})
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
                    "why_this_person"])
        for c in ok:
            p = c.data["provenance"]
            w.writerow([c.org_display, c.person_name, c.person_role, c.channel, c.value,
                        c.source_url, c.source_type, c.lawful_basis, c.jurisdiction,
                        p.get("retrieved_at", ""), c.data.get("why_this_person", "")])
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
        if w:
            w.active, w.interval_days = True, body.interval_days
        else:
            w = db.Watch(disease=body.disease.strip(), interval_days=body.interval_days,
                         created_by=who)
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
