"""Background execution of runs, and the watch scheduler.

One worker thread per process. Runs are claimed with a conditional UPDATE so
that two replicas never execute the same run.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import timedelta

from sqlalchemy import select, update

from bconz import dia, pcia

from . import db

log = logging.getLogger("bconz.worker")
POLL_SECONDS = 3


def _append_progress(run_id: int, msg: str) -> None:
    with db.Session() as s:
        run = s.get(db.Run, run_id)
        if run is None:
            return
        run.progress = [*(run.progress or []), msg][-200:]
        s.commit()


def _claim() -> int | None:
    with db.Session() as s:
        rid = s.scalar(select(db.Run.id).where(db.Run.status == "queued")
                       .order_by(db.Run.created_at).limit(1))
        if rid is None:
            return None
        got = s.execute(update(db.Run).where(db.Run.id == rid, db.Run.status == "queued")
                        .values(status="running", started_at=db.now()))
        s.commit()
        return rid if got.rowcount == 1 else None


def suppression_set() -> set[str]:
    with db.Session() as s:
        return {v.lower() for v in s.scalars(select(db.Suppression.value))}


def execute(run_id: int) -> None:
    with db.Session() as s:
        run = s.get(db.Run, run_id)
        disease, params, watch_id = run.disease, dict(run.params or {}), run.watch_id

    def progress(msg: str) -> None:
        log.info("run %s: %s", run_id, msg)
        _append_progress(run_id, msg)

    doc = dia.run(disease, years=params.get("years", 3),
                  max_pubs=params.get("max_pubs", 200),
                  max_grants=params.get("max_grants", 100),
                  max_trials=params.get("max_trials", 300), log=progress,
                  regions=params.get("regions") or dia.REGIONS)
    progress(f"DIA done: {doc['summary']['organisations']} organisations — resolving contacts")
    contacts = pcia.resolve(doc, top=params.get("top_contacts", 20),
                            suppression=suppression_set(), log=progress)

    with db.Session() as s:
        seen: set[str] = set()
        watch = s.get(db.Watch, watch_id) if watch_id else None
        if watch:
            seen = set(watch.seen_signals or [])
        first_watch_run = watch is not None and not seen

        for rank, l in enumerate(doc["leads"], 1):
            urls = {sg["url"] for sg in l["signals"]}
            s.add(db.Lead(run_id=run_id, rank=rank, org_key=l["org_key"],
                          org_display=l["org_display"], org_type=l["org_type"],
                          country=l["country"] or "", score=l["score"], tier=l["tier"],
                          is_new=bool(watch) and not first_watch_run and bool(urls - seen),
                          data=l))
        for c in pcia.to_json(contacts, disease)["contacts"]:
            p = c["provenance"]
            s.add(db.Contact(run_id=run_id, org_key=c["org_key"], org_display=c["org_display"],
                             person_name=c["person_name"], person_role=c["person_role"],
                             channel=c["channel"], value=c["value"],
                             source_url=p["source_url"], source_type=p["source_type"],
                             lawful_basis=p["lawful_basis"], jurisdiction=p["jurisdiction"],
                             exportable=c["exportable"], gate_reason=c["gate_reason"],
                             data=c))
        if watch:
            all_urls = {sg["url"] for l in doc["leads"] for sg in l["signals"]}
            doc["summary"]["new_signals"] = 0 if first_watch_run else len(all_urls - seen)
            watch.seen_signals = sorted(seen | all_urls)
            watch.last_run_at = db.now()

        run = s.get(db.Run, run_id)
        ok = [c for c in contacts if c.exportable]
        run.summary = {**doc["summary"], "contacts": len(contacts), "contactable": len(ok)}
        run.diagnostics = doc["diagnostics"]
        run.status = "done"
        run.finished_at = db.now()
        s.commit()
    progress(f"done: {len(ok)} contactable of {len(contacts)} records")


def _schedule_watches() -> None:
    with db.Session() as s:
        for w in s.scalars(select(db.Watch).where(db.Watch.active.is_(True))):
            due = w.last_run_at is None or db.now() - _aware(w.last_run_at) >= timedelta(
                days=w.interval_days)
            busy = s.scalar(select(db.Run.id).where(
                db.Run.watch_id == w.id, db.Run.status.in_(("queued", "running"))))
            if due and not busy:
                s.add(db.Run(disease=w.disease, watch_id=w.id, created_by="watch",
                             params={"top_contacts": 20}))
                w.last_run_at = db.now()      # stops re-queueing while it runs
        s.commit()


def _aware(dt):
    # SQLite drops tzinfo; treat stored naive datetimes as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=db.now().tzinfo)


def recover_stale() -> None:
    """A run left 'running' by a restart will never finish: requeue it."""
    with db.Session() as s:
        s.execute(update(db.Run).where(db.Run.status == "running")
                  .values(status="queued", started_at=None))
        s.commit()


def loop(stop: threading.Event) -> None:
    last_sched = 0.0
    while not stop.is_set():
        try:
            if time.time() - last_sched > 60:
                _schedule_watches()
                last_sched = time.time()
            rid = _claim()
            if rid is None:
                stop.wait(POLL_SECONDS)
                continue
            try:
                execute(rid)
            except Exception as exc:
                log.exception("run %s failed", rid)
                with db.Session() as s:
                    run = s.get(db.Run, rid)
                    run.status = "failed"
                    run.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}"
                    run.finished_at = db.now()
                    s.commit()
        except Exception:
            log.exception("worker loop error")
            stop.wait(POLL_SECONDS)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop,), name="bconz-dia-worker", daemon=True).start()
    return stop
