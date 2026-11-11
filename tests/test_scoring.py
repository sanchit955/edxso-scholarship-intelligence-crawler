from src.scoring import score_record, verification_status


def _full_evidence(**overrides):
    kwargs = dict(
        is_official=True,
        presence_confirmed=True,
        deadline_evidenced=True,
        eligibility_evidenced=True,
        application_url_official=True,
        fetched_ok=True,
        conflicts=0,
        populated_fields=12,
        evidenced_fields=12,
    )
    kwargs.update(overrides)
    return score_record(**kwargs)


def test_full_evidence_scores_100_and_verifies():
    score, components = _full_evidence()
    assert score == 100.0
    assert verification_status(score) == "VERIFIED"
    assert sum(c["max_points"] for c in components) == 100


def test_missing_deadline_drops_below_threshold():
    score, _ = _full_evidence(deadline_evidenced=False)
    assert score == 85.0
    assert verification_status(score) == "REVIEW_REQUIRED"


def test_aggregator_source_cannot_verify():
    score, _ = _full_evidence(is_official=False)
    assert score == 75.0
    assert verification_status(score) == "REVIEW_REQUIRED"


def test_conflict_removes_points():
    score, components = _full_evidence(conflicts=1)
    rule = [c for c in components if c["rule"] == "no_conflicts"][0]
    assert rule["points"] == 0
    assert score == 95.0


def test_traceability_scales():
    score, components = _full_evidence(populated_fields=10, evidenced_fields=6)
    rule = [c for c in components if c["rule"] == "field_traceability"][0]
    assert rule["points"] == 2.0
    assert score == 95.0
