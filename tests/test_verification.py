from datetime import datetime, timezone, timedelta
import pytest
from edgedash.config import Config
from edgedash.verification import (
    CheckResult,
    Verdict,
    check_score_spread,
    check_extraction_sanity,
    check_gap_sample_size,
    check_freshness,
    run_all_checks,
)


@pytest.fixture
def base_config() -> Config:
    return Config(
        target_role="AI Engineer",
        target_city="Bengaluru",
        keywords=["AI"],
        my_skills=["Python"],
        experience_years=1,
        db_path=":memory:",
        min_fit_score=70,
        min_score_spread=10.0,
        min_score_stdev=5.0,
        max_empty_extraction_pct=0.20,
        max_skills_per_listing=20,
        min_gap_sample=3,
        max_data_age_days=3.0,
    )


def test_score_spread_passing(base_config: Config):
    scores = [25.0, 50.0, 70.0, 85.0, 95.0]
    res = check_score_spread(scores, base_config)
    assert res.passed is True
    assert res.observed["spread"] == 70.0
    assert "Score spread passed" in res.message


def test_score_spread_failing(base_config: Config):
    # Compressed scores: spread = 2.0 < 10, stdev < 5
    scores = [70.0, 71.0, 72.0, 70.5, 71.5]
    res = check_score_spread(scores, base_config)
    assert res.passed is False
    assert res.observed["spread"] < 10.0
    assert "Score spread failed" in res.message


def test_score_spread_fewer_than_five_trivially_passes(base_config: Config):
    scores = [70.0, 71.0, 72.0]
    res = check_score_spread(scores, base_config)
    assert res.passed is True
    assert res.observed["count"] == 3
    assert "fewer than 5 scores" in res.message.lower()


def test_extraction_sanity_passing(base_config: Config):
    facts = [
        {"required_skills": ["python", "sql"]},
        {"required_skills": ["pytorch", "docker"]},
        {"required_skills": ["pandas"]},
    ]
    res = check_extraction_sanity(facts, base_config)
    assert res.passed is True
    assert res.observed["empty_pct"] == 0.0
    assert "passed" in res.message.lower()


def test_extraction_sanity_failing_too_many_empty(base_config: Config):
    # 2 out of 3 empty (66.7% > 20%)
    facts = [
        {"required_skills": []},
        {"required_skills": []},
        {"required_skills": ["python"]},
    ]
    res = check_extraction_sanity(facts, base_config)
    assert res.passed is False
    assert "empty_pct" in res.message


def test_extraction_sanity_failing_skills_per_listing_limit(base_config: Config):
    # One listing has 25 skills (> 20 limit)
    facts = [
        {"required_skills": [f"skill_{i}" for i in range(25)]},
        {"required_skills": ["python"]},
    ]
    res = check_extraction_sanity(facts, base_config)
    assert res.passed is False
    assert "max_skills" in res.message


def test_gap_sample_size_passing(base_config: Config):
    gaps = [{"skill": "kubernetes", "listings_blocked": 5, "opportunity_cost": 4.2}]
    res = check_gap_sample_size(gaps, base_config)
    assert res.passed is True
    assert res.observed["listings_blocked"] == 5
    assert "passed" in res.message.lower()


def test_gap_sample_size_failing(base_config: Config):
    # Only 2 listings (< 3 min_gap_sample)
    gaps = [{"skill": "rust", "listings_blocked": 2, "opportunity_cost": 1.8}]
    res = check_gap_sample_size(gaps, base_config)
    assert res.passed is False
    assert "sample 2 < 3" in res.message


def test_freshness_passing(base_config: Config):
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    latest_fetch_at = (now - timedelta(days=1)).isoformat()
    res = check_freshness(latest_fetch_at, base_config, now)
    assert res.passed is True
    assert res.observed["age_days"] == 1.0
    assert "passed" in res.message.lower()


def test_freshness_failing(base_config: Config):
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    latest_fetch_at = (now - timedelta(days=5)).isoformat()
    res = check_freshness(latest_fetch_at, base_config, now)
    assert res.passed is False
    assert res.observed["age_days"] == 5.0
    assert "failed" in res.message.lower()


def test_run_all_checks_combined(base_config: Config):
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    scores = [20.0, 40.0, 60.0, 80.0, 100.0]
    facts = [{"required_skills": ["python", "docker"]}] * 5
    gaps = [{"skill": "k8s", "listings_blocked": 4, "opportunity_cost": 3.2}]
    latest_fetch_at = (now - timedelta(hours=6)).isoformat()

    # All pass
    verdict = run_all_checks(
        config=base_config,
        now=now,
        scores=scores,
        facts_list=facts,
        gaps=gaps,
        latest_fetch_at=latest_fetch_at,
    )
    assert verdict.passed is True
    assert len(verdict.failed_checks) == 0
    assert "All 4 checks passed" in verdict.summary

    # One check fails (freshness stale by 10 days)
    stale_fetch = (now - timedelta(days=10)).isoformat()
    bad_verdict = run_all_checks(
        config=base_config,
        now=now,
        scores=scores,
        facts_list=facts,
        gaps=gaps,
        latest_fetch_at=stale_fetch,
    )
    assert bad_verdict.passed is False
    assert len(bad_verdict.failed_checks) == 1
    assert bad_verdict.failed_checks[0].name == "check_freshness"
