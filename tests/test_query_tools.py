from datetime import datetime, timezone
import pytest
from edgedash.config import Config
import edgedash.storage as storage
from edgedash.query.tools import (
    clamp_int,
    companies_hiring,
    best_matches,
    top_gaps,
    gap_detail,
    trend,
    listing_count,
    skill_demand,
    TOOLS,
)


@pytest.fixture
def test_env(tmp_path):
    db_file = str(tmp_path / "test_query.db")
    storage.init_db(db_file)

    now_iso = datetime.now(timezone.utc).isoformat()
    # Insert test listings
    storage.upsert_listings([
        {
            "id": "job1", "title": "Senior AI Engineer", "company": "Acme Corp", "location": "Bengaluru",
            "url": "https://example.com/1", "description": "Needs Python and Docker and Kubernetes", "source": "test",
            "posted_at": now_iso, "fetched_at": now_iso, "fit_score": 92, "fit_reason": "Skill match",
        },
        {
            "id": "job2", "title": "Data Scientist", "company": "Acme Corp", "location": "Remote",
            "url": "https://example.com/2", "description": "Needs Python and SQL", "source": "test",
            "posted_at": now_iso, "fetched_at": now_iso, "fit_score": 85, "fit_reason": "Good match",
        },
        {
            "id": "job3", "title": "ML Engineer", "company": "Beta Labs", "location": "Bengaluru",
            "url": "https://example.com/3", "description": "Needs PyTorch and Docker", "source": "test",
            "posted_at": now_iso, "fetched_at": now_iso, "fit_score": 78, "fit_reason": "Fair match",
        },
    ], db_path=db_file)

    # Save extraction cache
    import hashlib
    storage.save_cached_extraction(
        hashlib.sha256("Needs Python and Docker and Kubernetes".encode()).hexdigest(),
        {"required_skills": ["python", "docker", "kubernetes"], "nice_to_have": ["sql"]},
        db_path=db_file,
    )
    storage.save_cached_extraction(
        hashlib.sha256("Needs PyTorch and Docker".encode()).hexdigest(),
        {"required_skills": ["pytorch", "docker"], "nice_to_have": []},
        db_path=db_file,
    )

    # Save snapshot
    storage.save_skill_gaps_snapshot("run1", now_iso, [
        {"skill": "docker", "listings_blocked": 2, "opportunity_cost": 45.0, "mean_score": 85.0, "top_score": 92, "example_ids": ["job1", "job3"]},
        {"skill": "kubernetes", "listings_blocked": 1, "opportunity_cost": 25.0, "mean_score": 92.0, "top_score": 92, "example_ids": ["job1"]},
    ], db_path=db_file)

    # Log passing cycle so as_of is established per Rule 46
    storage.log_cycle("orchestrator", now_iso, now_iso, 3, "complete", '{"verdict": {"passed": true}}', db_path=db_file)

    cfg = Config(
        target_role="AI Engineer",
        target_city="Bengaluru",
        keywords=["AI"],
        my_skills=["Python"],
        experience_years=1,
        db_path=db_file,
        min_fit_score=70,
    )
    return cfg


def test_clamp_int():
    assert clamp_int(5, 1, 10, 5) == 5
    assert clamp_int(-5, 1, 10, 5) == 1
    assert clamp_int(100, 1, 10, 5) == 10
    assert clamp_int("invalid", 1, 10, 7) == 7


def test_tools_registered():
    expected = {"companies_hiring", "best_matches", "top_gaps", "gap_detail", "trend", "listing_count", "skill_demand"}
    assert expected.issubset(set(TOOLS.keys()))


def test_companies_hiring_clamping_and_shape(test_env):
    # Days clamped 1-90
    res = companies_hiring(days=-10, config=test_env)
    assert "summary" in res
    assert isinstance(res["rows"], list)
    assert len(res["rows"]) >= 1
    assert res["rows"][0]["company"] == "Acme Corp"


def test_best_matches_shape(test_env):
    res = best_matches(n=2, config=test_env)
    assert "summary" in res
    assert len(res["rows"]) == 2
    assert res["rows"][0]["fit_score"] >= res["rows"][1]["fit_score"]


def test_top_gaps_shape(test_env):
    res = top_gaps(n=10, config=test_env)
    assert "summary" in res
    assert len(res["rows"]) == 2
    assert res["rows"][0]["skill"] == "docker"


def test_gap_detail_known_vs_unknown(test_env):
    # Known skill
    res = gap_detail("docker", config=test_env)
    assert len(res["rows"]) == 2

    # Unknown skill: must return empty list rather than raising (Rule 41)
    unknown_res = gap_detail("completely_nonexistent_skill_xyz", config=test_env)
    assert unknown_res["rows"] == []
    assert "not found" in unknown_res["summary"].lower()


def test_trend_shape(test_env):
    res = trend(weeks=5, config=test_env)
    assert "summary" in res
    assert isinstance(res["rows"], list)


def test_listing_count_shape(test_env):
    res = listing_count(config=test_env)
    assert "summary" in res
    assert len(res["rows"]) == 1
    assert res["rows"][0]["total_listings"] == 3


def test_skill_demand_known_vs_unknown(test_env):
    res = skill_demand("docker", config=test_env)
    assert res["rows"][0]["required_count"] == 2

    unknown_res = skill_demand("unknown_magic_skill", config=test_env)
    assert unknown_res["rows"] == []


def test_location_breakdown_clamping_and_shape(test_env):
    from edgedash.query.tools import location_breakdown
    # Limit clamped 1-25
    res = location_breakdown(limit=-5, config=test_env)
    assert "summary" in res
    assert isinstance(res["rows"], list)
    assert len(res["rows"]) >= 1
    locs = [r["location"] for r in res["rows"]]
    assert "Bengaluru" in locs or "Remote" in locs
