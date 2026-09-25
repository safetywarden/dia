"""Persistence. Postgres in production (DATABASE_URL), SQLite locally."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _url() -> str:
    return _normalise(os.environ.get("DATABASE_URL", "sqlite:///./bconz_dia.db"))


def _normalise(url: str) -> str:
    url = url.strip()
    # Railway and Supabase hand out postgres(ql)://; SQLAlchemy wants a driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


URL = _url()
engine = create_engine(URL, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if URL.startswith("sqlite") else {})
Session = sessionmaker(engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    watch_id: Mapped[int | None] = mapped_column(ForeignKey("watches.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    org_key: Mapped[str] = mapped_column(String(300), index=True)
    org_display: Mapped[str] = mapped_column(String(300))
    org_type: Mapped[str] = mapped_column(String(30))
    country: Mapped[str] = mapped_column(String(4), default="")
    score: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(1), index=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)   # watch mode
    data: Mapped[dict] = mapped_column(JSON)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    org_key: Mapped[str] = mapped_column(String(300), index=True)
    org_display: Mapped[str] = mapped_column(String(300))
    person_name: Mapped[str] = mapped_column(String(300))
    person_role: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(10))
    value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40))
    lawful_basis: Mapped[str] = mapped_column(String(40))
    jurisdiction: Mapped[str] = mapped_column(String(10))
    exportable: Mapped[bool] = mapped_column(Boolean)
    gate_reason: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)


class Suppression(Base):
    """Do-not-contact list. Honoured at resolve time AND at export time, so a
    request to stop reaches records already stored."""
    __tablename__ = "suppression"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(300), unique=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Export(Base):
    """Audit trail: who took which personal data out of the system, when."""
    __tablename__ = "exports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    rows: Mapped[int] = mapped_column(Integer)
    excluded: Mapped[int] = mapped_column(Integer)
    exported_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Watch(Base):
    """A disease re-run on a schedule; only signals not seen before are flagged."""
    __tablename__ = "watches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease: Mapped[str] = mapped_column(String(200), unique=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=7)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    seen_signals: Mapped[list] = mapped_column(JSON, default=list)   # signal URLs
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def init() -> None:
    Base.metadata.create_all(engine)
    migrate_from_legacy()


# Parents before children, so foreign keys hold during the copy.
COPY_ORDER = [Watch, Run, Lead, Contact, Suppression, Export]


def migrate_from_legacy() -> dict[str, int] | None:
    """One-time move of existing data onto a new database (e.g. Railway
    Postgres -> Supabase). Runs only when LEGACY_DATABASE_URL is set and the
    new database has no runs yet, so restarts never duplicate rows. IDs are
    preserved so links to /runs/<id> keep working."""
    import logging

    from sqlalchemy import func, insert, select, text

    legacy = os.environ.get("LEGACY_DATABASE_URL", "").strip()
    if not legacy:
        return None
    src_url = _normalise(legacy)
    if src_url == URL:
        return None
    log = logging.getLogger("bconz.migrate")
    with Session() as s:
        if s.scalar(select(func.count()).select_from(Run)):
            log.info("target already has runs; legacy migration skipped")
            return None
    src = create_engine(src_url, pool_pre_ping=True)
    counts: dict[str, int] = {}
    with src.connect() as rc, engine.begin() as wc:
        for model in COPY_ORDER:
            t = model.__table__
            rows = [dict(r._mapping) for r in rc.execute(select(t))]
            if rows:
                wc.execute(insert(t), rows)
            counts[t.name] = len(rows)
        if engine.dialect.name == "postgresql":
            # Copied explicit IDs; move each sequence past them.
            for model in COPY_ORDER:
                n = model.__tablename__
                wc.execute(text(f"SELECT setval(pg_get_serial_sequence('{n}', 'id'), "
                                f"COALESCE((SELECT MAX(id) FROM {n}), 0) + 1, false)"))
    src.dispose()
    log.info("legacy migration copied %s", counts)
    return counts
