# Scholarship Intelligence Crawler

An automated intelligence engine that keeps a repository of scholarship
opportunities for Indian students continuously updated and — above all —
trustworthy. Built for the Atlas Funding prototype (edxso AI Engineer
Intern, Assignment 2).

The pipeline runs **Discover → Crawl → Extract → Verify → Score → Store →
Update** against primary sources: government portals (National Scholarship
Portal), international programme sites (Commonwealth Scholarship
Commission, USIEF), foundations/trusts (Inlaks, Tata Trusts, Foundation
For Excellence) and corporate CSR programmes (LIC Golden Jubilee
Foundation).

**Applicant:** Sanchit — AI Engineer Intern applicant, edxso
**Applicant resume:** https://drive.google.com/file/d/1ebEJU9fXKUT00wCWKyyKihG4sMMkH31E/view?usp=drivesdk

## Why it can be trusted

- **Primary sources only.** Aggregators are never used as the authority
  for a record. Every record points at the provider's own official page
  or official guideline document.
- **Evidence for every field.** Each extracted value is stored together
  with the verbatim source snippet it came from (`field_evidence` table),
  so any value can be traced: database → official source → evidence →
  extracted value.
- **No invented values.** If the official source does not state a field,
  the record says `Not specified`. Extraction is rule-based (regex +
  DOM/heading heuristics); no language model generates field values or
  confidence scores.
- **Deterministic confidence.** Scores come from a fixed, published
  rule set (see below). A record is `VERIFIED` only at **≥ 95** points;
  anything lower is `REVIEW_REQUIRED`.
- **History is never overwritten.** Every run snapshots every record.
  Field-level differences between runs are written to a `changes` table
  with old value, new value, detection time, source and evidence.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run the crawler (one full discover/crawl/verify/store cycle)
.venv/bin/python -m src.crawler

# Run it again later -- the second run re-verifies every known source
# and records any changes it detects
.venv/bin/python -m src.crawler

# Launch the dashboard
.venv/bin/streamlit run dashboard/app.py

# Inspect the database directly
sqlite3 data/scholarships.db "SELECT name, confidence, verification_status FROM scholarships;"
```

Outputs:

- `data/scholarships.db` — SQLite database (schema in `schema.sql`)
- `data/scholarships.json` — full export incl. evidence and change history
- `data/run1.log`, `data/run2.log`, `data/run3.log` — transcripts of the demo runs
- `docs/DEMO.md` — worked demonstration of the full loop

## How it works

### Discovery (`src/discovery.py`, `config/seeds.json`)

Only *index* pages are configured as seeds — no scholarship record is
hand-entered. The crawler parses each index for candidate programme
pages on the provider's own domain. The National Scholarship Portal seed
is a structured listing: each scheme block yields the scheme name,
ministry/department, opening/closing dates and the URL of the official
scheme guideline PDF, which is then fetched and mined for the remaining
fields. Seeds can be extended in `config/seeds.json` without code changes.

### Source classification (`src/classify.py`)

Domains are classified into Atlas source types (Government, University,
Corporate CSR, NGO/Trust, International). Known aggregator domains are
explicitly recognised so they can never become an authoritative source.

### Extraction (`src/extract.py`)

Rule-based extractors pull the 17-field schema (name, provider, amount,
eligibility, academic/income/age/gender/category criteria, course level,
domicile, institution requirements, opening/closing dates, documents,
selection process, renewal terms) from HTML pages and from official PDF
guideline documents. Dates are normalised to ISO form before comparison
so that a pure reformatting of the same date is not reported as a change.

### Verification & confidence (`src/scoring.py`)

| Rule | Points | What it checks |
|---|---|---|
| official_primary_source | 25 | Source is the provider's own official site/portal |
| presence_confirmed | 20 | Scholarship name matched on the official source |
| deadline_evidenced | 15 | Closing date backed by stored source evidence |
| eligibility_evidenced | 10 | Eligibility text backed by stored source evidence |
| official_application_url | 10 | Application URL present on an official domain |
| information_current | 8 | Official source fetched successfully in the latest run |
| no_conflicts | 5 | No second source contradicts the extracted fields |
| field_traceability | 7 | Share of populated fields that carry evidence (≥90% → full points) |

`VERIFIED` ≥ 95 · otherwise `REVIEW_REQUIRED`. The dashboard shows the
per-rule breakdown for every record ("Why this score?").

### Change & stale detection (`src/store.py`, `src/crawler.py`)

- Snapshots are compared field by field; differences become change
  records (old value, new value, when, source, evidence).
- Lifecycle status is derived from the evidenced closing date:
  `EXPIRED` (date passed), `EXPIRING_SOON` (≤ 30 days), else `ACTIVE`.
- A previously known record whose official source can no longer be
  fetched or confirmed becomes `NO_LONGER_VERIFIABLE`, and the status
  transition itself is recorded as a change.

## Dashboard

`dashboard/app.py` (Streamlit) shows totals (discovered, verified,
review required, active, expiring soon, expired, average confidence), a
searchable list, and a detail view per scholarship with all fields, the
score breakdown, change history and source evidence.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Extraction, scoring and change-detection tests use clearly labelled
synthetic fixtures under `tests/fixtures/` (fixture data is never part of
the crawled corpus).

## Project layout

```
config/seeds.json     seed index pages (configuration, not records)
src/fetcher.py        polite HTTP fetching (retries, backoff, per-domain delay)
src/discovery.py      candidate discovery from index pages
src/classify.py       source-type classification, aggregator guard
src/extract.py        rule-based field extraction + evidence capture
src/scoring.py        deterministic confidence methodology
src/store.py          SQLite storage, snapshots, change detection
src/crawler.py        pipeline orchestration + CLI
dashboard/app.py      Streamlit dashboard
schema.sql            database schema
data/                 generated database, JSON export, run logs
docs/                 technical note (md + pdf) and demo transcript
tests/                pytest suite with labelled fixtures
```

Free and open-source tools only; no paid APIs or services.
