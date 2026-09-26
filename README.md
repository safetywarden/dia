# BCONZ DIA — DIA + PCIA

Finds organisations that have **publicly stated they need data** in a disease, ranks them, and
resolves **contacts that were published to be contacted**, each with its source URL and lawful basis.

```
disease ──► DIA (Demand Intelligence Agent) ──► ranked leads + verbatim stated needs
                 Europe PMC · ClinicalTrials.gov (global)
                 US: NIH RePORTER · EU: CTIS, CORDIS · UK: ISRCTN, UKRI
                                   │
                                   ▼
            PCIA (Provenance-first Contact Intelligence Agent) ──► gated contacts
                 corresponding authors · registry study contacts · named PIs
```

| Part | Where | What |
|---|---|---|
| `backend/bconz/` | library + CLI | `dia.py`, `pcia.py`, `orgs.py` (organisation identity) |
| `backend/app/` | Railway | FastAPI, Postgres, background worker, watch scheduler |
| `web/` | Vercel | Next.js app: searches, lead cards, contacts, gated export, do-not-contact |

## Rules the code enforces

- **No invented values.** Organisations are only named from a head noun in the published
  affiliation; no fallback guesses. Contacts are never inferred (no email patterns, no SMTP probes,
  no social platforms, no bought lists). A record stamped `INFERRED` is refused even with a basis claimed.
- **No manufactured variance.** Each scoring dimension is checked per run; one that doesn't
  separate leads is shown as a flag and left out of the score. Scores are absolute.
- **Export gate.** Only `(source_type, lawful_basis)` pairs in `pcia.EXPORTABLE` leave the system.
  Exclusions are counted and reported, never dropped silently. Every export is logged (who, when, rows).
- **Do-not-contact** is applied at resolve time *and* at export/read time, so it reaches stored records.
- **Jurisdiction** is resolved from published evidence (corresponding text, email ccTLD, phone
  prefix, official's affiliation, single-country trial footprint, lead country) and recorded with
  the evidence used. It decides the basis: DPDP §3(c)(ii) for IN and elsewhere, GDPR legitimate
  interest for EU/UK.

> Legal status: the lawful-basis model is an engineering position, not legal advice. Get written
> advice from Indian counsel on PCIA (DPDP) and EU counsel on GDPR Art. 14 notice obligations
> before contacting anyone at scale.

## Run locally

```bash
cd backend && pip install -r requirements.txt
python -m bconz.dia --disease "multiple myeloma" --out ../out_mm
python -m bconz.pcia --leads ../out_mm/leads.json --out ../out_mm --top 20
```

API + web:

```bash
cd backend && DIA_API_TOKEN=dev-token uvicorn app.main:app --port 8077
cd web && cp .env.example .env.local && npm install && npm run dev
```

In development only, `DIA_DEV_USER=<email>` in `web/.env.local` skips sign-in.

Tests: `cd backend && python -m pytest -q tests`

## Deploy

**Railway (API)** — service root `backend/`, add a Postgres plugin. Variables:
`DATABASE_URL` (from the plugin), `DIA_API_TOKEN` (random, 32+ chars),
`DIA_CORS` (optional). Start command and health check are in `backend/railway.json`.
Keep one replica: the worker and scheduler run in-process.

**Database** — Railway Postgres in the same project, reached only over the private network
(`postgres.railway.internal`; no public TCP proxy). Volume backups are scheduled in
Railway → Postgres → Backups (first manual backup 2026-09-25). Point-in-time recovery is off;
enable it there if minute-level restore becomes necessary. To restore: Backups → pick a
backup → Restore, then redeploy the `dia` service. `LEGACY_DATABASE_URL` triggers a one-time
copy onto a new `DATABASE_URL` if the database ever moves (see `app/db.py`).

**Vercel (web)** — project root `web/`. Variables: `DIA_API_URL` (Railway URL),
`DIA_API_TOKEN` (same as Railway), `DIA_ALLOWED_EMAILS`, `DIA_ACCESS_CODE`,
`SESSION_SECRET` (random, 32+ chars).

## API

All routes except `/health` need `Authorization: Bearer $DIA_API_TOKEN`.

| Method | Path | |
|---|---|---|
| POST | `/runs` | `{disease, top_contacts, years}` — queue a search |
| GET | `/runs`, `/runs/{id}` | status, summary, diagnostics, progress |
| GET | `/runs/{id}/leads?tier=AB&new_only=` | ranked leads with evidence |
| GET | `/runs/{id}/contacts` | all records incl. gate reason |
| GET | `/runs/{id}/contacts.csv?strict=` | gated export; `X-Exported-Rows`, `X-Excluded-Rows` |
| GET/POST/DELETE | `/suppression` | do-not-contact list |
| GET/POST/DELETE | `/watches` | weekly re-runs that flag only new signals |

## Sources by market

| Market | Trials | Funding | Contacts PCIA may use |
|---|---|---|---|
| Global | ClinicalTrials.gov | — | Registry central contacts; open-access corresponding authors (Europe PMC) |
| US | — | NIH RePORTER | PI names only (no email published) |
| EU | CTIS | CORDIS (Horizon) | **None from CTIS** — its investigator/CRO emails are published under trial-transparency law, not for contact |
| UK | ISRCTN | UKRI Gateway to Research | ISRCTN contacts the registrant marked **Public** |
| India | **CTRI — not connected** | — | — |

A trial registered in several registries is counted once (matched on NCT, EU CT/EudraCT
and ISRCTN numbers only — never on shared grant or protocol codes). CTIS lists EU sites
only, so its trials never assert "no Indian sites".

**CTRI** requires a CAPTCHA on every search, which this tool will not bypass. Routes to
lawful access: (1) request the WHO ICTRP data service, which republishes CTRI; (2) ask
ICMR-NIMS (CTRI's operator) for a data-sharing arrangement. Until then India is covered
through Indian sites on ClinicalTrials.gov and Indian-affiliated papers in Europe PMC.
