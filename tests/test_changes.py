"""Change-detection tests using clearly labelled synthetic records.

These prove the snapshot/diff mechanism: a field that differs between two
runs produces a change row retaining old and new values, and an identical
re-crawl produces none. The scholarship below is fictional test data.
"""

from src import extract as ex
from src.store import Store

BASE_FIELDS = {f: ex.NOT_SPECIFIED for f in ex.SCHEMA_FIELDS}
BASE_FIELDS.update(
    {
        "name": "Fixture Scholarship For Change Detection",
        "provider": "Fixture Trust",
        "closing_date": "2026-08-31",
        "amount": "Rs. 10,000 per annum",
        "eligibility": "Fixture eligibility text.",
    }
)


def _save(store, run_id, fields):
    return store.save_record(
        run_id=run_id,
        dedupe_key="https://fixture.example.org/scholarship",
        fields=fields,
        evidence={f: "fixture evidence" for f in fields if fields[f] != ex.NOT_SPECIFIED},
        source_type="NGO/Trust",
        official_source_url="https://fixture.example.org/scholarship",
        application_url="https://fixture.example.org/apply",
        discovered_via="fixture",
        confidence=98.0,
        score_components=[],
        lifecycle_status="ACTIVE",
        verification_status="VERIFIED",
    )


def test_change_detected_with_old_and_new_values(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    run1 = store.start_run()
    _save(store, run1, dict(BASE_FIELDS))
    run2 = store.start_run()
    updated = dict(BASE_FIELDS)
    updated["closing_date"] = "2026-09-15"
    _, is_new, changes = _save(store, run2, updated)
    assert not is_new
    assert len(changes) == 1
    change = changes[0]
    assert change["field"] == "closing_date"
    assert change["old_value"] == "2026-08-31"
    assert change["new_value"] == "2026-09-15"
    # The change must also be persisted, not only returned
    rows = store.export_records()
    assert rows[0]["changes"][0]["new_value"] == "2026-09-15"


def test_identical_recrawl_produces_no_changes(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    _save(store, store.start_run(), dict(BASE_FIELDS))
    _, _, changes = _save(store, store.start_run(), dict(BASE_FIELDS))
    assert changes == []


def test_no_longer_verifiable_transition(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    run = store.start_run()
    sid, _, _ = _save(store, run, dict(BASE_FIELDS))
    store.mark_no_longer_verifiable(run, sid, "fixture: source unreachable")
    rec = store.export_records()[0]
    assert rec["lifecycle_status"] == "NO_LONGER_VERIFIABLE"
    fields = [c["field"] for c in rec["changes"]]
    assert "lifecycle_status" in fields
