"""Deterministic, rule-based confidence scoring.

The score is computed from observable evidence only -- never generated.
Each rule contributes a fixed number of points and produces a human
readable reason, so the dashboard can answer "Why this score?" exactly.

Rules (100 points total):
  official_primary_source   25  source is the provider's own official site
  presence_confirmed        20  scholarship name found on the official source
  deadline_evidenced        15  closing date extracted with source evidence
  eligibility_evidenced     10  eligibility text extracted with evidence
  official_application_url  10  application URL on an official domain
  information_current        8  official source fetched OK during this run
  no_conflicts               5  no second source contradicts extracted fields
  field_traceability         7  populated fields carry retrievable evidence

VERIFIED requires score >= 95. Anything lower is REVIEW REQUIRED.
"""

from __future__ import annotations

VERIFIED_THRESHOLD = 95.0

RULES = [
    ("official_primary_source", 25),
    ("presence_confirmed", 20),
    ("deadline_evidenced", 15),
    ("eligibility_evidenced", 10),
    ("official_application_url", 10),
    ("information_current", 8),
    ("no_conflicts", 5),
    ("field_traceability", 7),
]


def score_record(
    *,
    is_official: bool,
    presence_confirmed: bool,
    deadline_evidenced: bool,
    eligibility_evidenced: bool,
    application_url_official: bool,
    fetched_ok: bool,
    conflicts: int,
    populated_fields: int,
    evidenced_fields: int,
) -> tuple[float, list[dict]]:
    components: list[dict] = []

    def add(rule: str, max_pts: int, earned: float, detail: str) -> None:
        components.append(
            {
                "rule": rule,
                "points": round(earned, 1),
                "max_points": max_pts,
                "detail": detail,
            }
        )

    add(
        "official_primary_source", 25, 25 if is_official else 0,
        "Source is the provider's official website/portal"
        if is_official
        else "Source is not a primary/official provider source",
    )
    add(
        "presence_confirmed", 20, 20 if presence_confirmed else 0,
        "Scholarship name matched on the official source"
        if presence_confirmed
        else "Scholarship name could not be confirmed on the official source",
    )
    add(
        "deadline_evidenced", 15, 15 if deadline_evidenced else 0,
        "Closing date backed by source evidence"
        if deadline_evidenced
        else "No closing date could be evidenced from the source",
    )
    add(
        "eligibility_evidenced", 10, 10 if eligibility_evidenced else 0,
        "Eligibility criteria backed by source evidence"
        if eligibility_evidenced
        else "Eligibility criteria not evidenced on the source",
    )
    add(
        "official_application_url", 10, 10 if application_url_official else 0,
        "Application URL present on an official domain"
        if application_url_official
        else "No official application URL found",
    )
    add(
        "information_current", 8, 8 if fetched_ok else 0,
        "Official source fetched successfully in the latest run"
        if fetched_ok
        else "Official source could not be fetched in the latest run",
    )
    add(
        "no_conflicts", 5, 5 if conflicts == 0 else 0,
        "No conflicting values found across sources"
        if conflicts == 0
        else f"{conflicts} conflicting field value(s) across sources",
    )
    if populated_fields > 0:
        ratio = evidenced_fields / populated_fields
    else:
        ratio = 0.0
    if ratio >= 0.9:
        trace_pts = 7.0
    elif ratio >= 0.7:
        trace_pts = 4.0
    elif ratio >= 0.5:
        trace_pts = 2.0
    else:
        trace_pts = 0.0
    add(
        "field_traceability", 7, trace_pts,
        f"{evidenced_fields}/{populated_fields} populated fields carry source evidence",
    )

    total = round(sum(c["points"] for c in components), 1)
    return total, components


def verification_status(score: float) -> str:
    return "VERIFIED" if score >= VERIFIED_THRESHOLD else "REVIEW_REQUIRED"
