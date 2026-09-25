# BConz DIA — DIA + PCIA

Finds organisations that have **publicly stated they need data** in a disease, ranks them, and
resolves **contacts that were published to be contacted**, each with its source URL and lawful basis.

```
disease ──► DIA (Demand Intelligence Agent) ──► ranked leads + verbatim stated needs
                 Europe PMC · NIH RePORTER · ClinicalTrials.gov
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
