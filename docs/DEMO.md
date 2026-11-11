# Demonstration — the full loop, run live

This document records three real runs of the crawler against live
official sources on 11 November 2026. Full transcripts: `data/run1.log`,
`data/run2.log` and `data/run3.log`. The resulting database is
`data/scholarships.db` and a full export is `data/scholarships.json`.

## Run 1 — discover, extract, verify, score, store

Command: `.venv/bin/python -m src.crawler`

What happened, stage by stage:

1. **Discover.** The National Scholarship Portal seed (a listing page,
   no hand-entered records) yielded 30 scheme blocks; a balanced 14 were
   selected across ministries. Listing indexes of the Commonwealth
   Scholarship Commission, USIEF (home page + its fellowships-for-Indian
   -citizens index), Inlaks, Tata Trusts, Foundation For Excellence and
   the LIC Golden Jubilee Foundation yielded further candidate pages.
2. **Crawl.** Every candidate was fetched from the provider's own
   official site — HTML pages and, for NSP schemes and the LIC scheme
   documents, the official guideline PDFs published by the provider.
3. **Extract.** Rule-based extractors populated the 17-field schema.
   Fields a source does not state were left as `Not specified`.
4. **Verify & score.** Each record was scored by the deterministic
   rule set (see README). Example — *AICTE Swanath Scholarship*:
   official NSP guideline PDF (25) + name confirmed in the document
   (20) + closing date evidenced by the portal listing (15) +
   eligibility evidenced (10) + official portal application URL (10) +
   fetched this run (8) + no conflicts (5) + full field traceability
   (7) = **100.0, VERIFIED**.
5. **Store.** 28 records written to SQLite with per-field evidence
   snippets and a snapshot for the run.

Run 1 totals: **28 records · 15 VERIFIED (confidence ≥ 95) · 13 review
required · 4 source types (Government, International, NGO/Trust,
Corporate CSR) · 9 active · 13 expiring soon · 6 expired · average
confidence 92.3%**.

Expired examples found by Run 1 (closing dates evidenced on the
official source and already past on the crawl date):

- *Financial Assistance for Education to the Wards of Beedi/Cine/IOMC/
  LSDM Workers* (NSP) — student applications closed 31-10-2026.
- *Pre-Matric Scholarship for Students with Disabilities* (NSP) —
  closed 31-10-2026.
- *Commonwealth Fellowships — information for candidates* (CSC UK) and
  the 2026-27 Fulbright-Nehru / Fulbright Distinguished Awards pages
  (USIEF) — cycles closed.

## Inspect it yourself

```bash
sqlite3 data/scholarships.db \
  "SELECT name, confidence, verification_status, lifecycle_status FROM scholarships ORDER BY confidence DESC;"
streamlit run dashboard/app.py   # metrics, search, detail, "Why this score?", evidence, change history
```

## Runs 2 and 3 — re-crawl and change detection

Command: `.venv/bin/python -m src.crawler` (same command, later the
same day; the crawler is built to be re-run, e.g. from cron).
Transcripts: `data/run2.log`, `data/run3.log`.

The re-runs re-fetched every official source, re-extracted every
record, and diffed the new snapshots against the previous ones. **30
field-level changes** were detected and stored with old value, new
value, detection time, source and evidence — nothing was overwritten.
The dashboard's detail view shows this history per scholarship, and
the raw rows are in the `changes` table.

What the detected changes actually were, stated plainly:

- **Source reachability changes (the majority).** In Run 2 the NSP
  guideline PDFs for *AICTE Swanath* and *Ishan Uday* could not be
  fetched (portal/network timeouts), so their PDF-derived fields —
  amount, eligibility, income criteria and others — reverted to
  `Not specified` and their confidence dropped (both records fell out
  of VERIFIED for that run: 15 → 13 verified). In Run 3 the same
  documents fetched successfully again and every field was restored
  with fresh evidence (13 → 15 verified). This is the stale-data
  problem the system exists to manage, caught in the act: a record is
  only ever as strong as what the latest crawl could evidence, and
  the history shows exactly when that changed and why.
- **An extractor correction.** *Foundation For Excellence*: amount
  changed from `Rs 4.00 Lacs` to `Not specified`. The 4.00 Lacs figure
  on FFE's page is its family-income ceiling, not an award amount;
  an extraction rule was corrected between runs (an income-statement
  figure is never an amount) and the diff engine recorded the
  correction with evidence on both sides.
- **A different evidenced figure selected on re-crawl.** *National
  Fellowship and Scholarship for Higher Education of ST Students*:
  amount changed from `Rs.6.0 lakh per annum` to `Rs.2.50 lakh`. The
  scheme's official document states several money figures (tuition
  and fellowship components); the re-crawl's extraction selected a
  different one. Both values are retained in the change record with
  their evidence, which is precisely what a reviewer needs to audit
  the discrepancy.

No source was observed changing its own published deadline between
the runs (the runs were hours apart); deadline-extension changes are
detected by exactly the same field-diff mechanism, and `tests/`
contains labelled fixture tests that pin the semantics: a changed
deadline is detected with old/new values retained, and an identical
re-crawl produces no changes.

Final corpus after Run 3: **28 records · 15 VERIFIED · 13 review
required · 4 source types · 9 active · 13 expiring soon · 6 expired ·
average confidence 92.3% · 30 change records across 3 runs**.
