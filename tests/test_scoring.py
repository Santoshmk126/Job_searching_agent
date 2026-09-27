from datetime import datetime, timezone
import pytest
from edgedash.config import Config
from edgedash.scoring import score_listing, build_reason


@pytest.fixture
def mock_config() -> Config:
    return Config(
        target_role="Data Analyst",
        target_city="Bengaluru",
        keywords=["Python", "SQL"],
        my_skills=["Python", "SQL", "Pandas"],
        experience_years=1,
        db_path=":memory:",
        min_fit_score=70,
        target_seniority="junior",
        score_batch_size=25,
        scoring_weights={
            "skill_match": 0.45,
            "seniority_fit": 0.25,
            "location_fit": 0.15,
            "recency": 0.15,
        },
    )


def test_perfect_match(mock_config: Config) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    listing = {
        "title": "Junior Python Developer",
        "company": "Tech Corp",
        "location": "Bengaluru",
        "posted_at": now_iso,
    }
    facts = {
        "required_skills": ["python", "sql", "pandas"],
        "nice_to_have": [],
        "seniority": "junior",
        "years_required": 1,
        "remote_ok": True,
    }

    res = score_listing(listing, facts, mock_config)
    assert res["score"] == 100
    assert res["components"]["skill_match"] == 1.0
    assert res["components"]["seniority_fit"] == 1.0
    assert res["components"]["location_fit"] == 1.0
    assert res["components"]["recency"] == 1.0
    assert "seniority fits" in res["reason"]
    assert "remote" in res["reason"]
    assert "no skill gaps" in res["reason"]


def test_zero_match(mock_config: Config) -> None:
    old_iso = "2020-01-01T00:00:00+00:00"
    listing = {
        "title": "Lead Rust Engineer",
        "company": "Rust Co",
        "location": "Berlin",
        "posted_at": old_iso,
    }
    facts = {
        "required_skills": ["rust", "c++", "embedded"],
        "nice_to_have": ["assembly"],
        "seniority": "lead",
        "years_required": 10,
        "remote_ok": False,
    }

    res = score_listing(listing, facts, mock_config)
    assert res["score"] <= 5
    assert res["components"]["skill_match"] == 0.0
    assert res["components"]["seniority_fit"] == 0.0
    assert res["components"]["location_fit"] == 0.1
    assert res["components"]["recency"] == 0.0
    assert "gap: rust, c++, embedded" in res["reason"]
    assert "seniority gap (lead)" in res["reason"]


def test_empty_required_skills(mock_config: Config) -> None:
    listing = {"title": "General Intern", "location": "Bengaluru", "posted_at": None}
    facts_with_nice = {
        "required_skills": [],
        "nice_to_have": ["python"],
        "seniority": "junior",
        "years_required": None,
        "remote_ok": None,
    }

    # Case 1: Empty required, 1 nice-to-have matched -> must not divide by zero
    res1 = score_listing(listing, facts_with_nice, mock_config)
    assert res1["components"]["skill_match"] == 1.0
    assert "1/1 preferred skills" in res1["reason"]

    # Case 2: Neither required nor nice-to-have listed -> neutral 0.5, no divide by zero
    facts_none = {
        "required_skills": [],
        "nice_to_have": [],
        "seniority": "junior",
        "years_required": None,
        "remote_ok": None,
    }
    res2 = score_listing(listing, facts_none, mock_config)
    assert res2["components"]["skill_match"] == 0.5
    assert "no skills listed" in res2["reason"]


def test_null_posted_at(mock_config: Config) -> None:
    listing = {"title": "Analyst", "location": "Bengaluru", "posted_at": None}
    facts = {
        "required_skills": ["sql"],
        "nice_to_have": [],
        "seniority": "junior",
        "years_required": 1,
        "remote_ok": True,
    }

    res = score_listing(listing, facts, mock_config)
    assert res["components"]["recency"] == 0.5
    assert "posted date unknown" in res["reason"]


def test_null_remote_ok(mock_config: Config) -> None:
    listing = {"title": "Analyst", "location": None, "posted_at": None}
    facts = {
        "required_skills": ["sql"],
        "nice_to_have": [],
        "seniority": "junior",
        "years_required": 1,
        "remote_ok": None,
    }

    res = score_listing(listing, facts, mock_config)
    assert res["components"]["location_fit"] == 0.5
    assert "location unstated" in res["reason"]


def test_seniority_three_bands_off(mock_config: Config) -> None:
    # Target is "junior" (index 0), job is "lead" (index 3) -> distance 3
    listing = {"title": "Lead Architect", "location": "Bengaluru", "posted_at": None}
    facts = {
        "required_skills": ["sql"],
        "nice_to_have": [],
        "seniority": "lead",
        "years_required": 8,
        "remote_ok": True,
    }

    res = score_listing(listing, facts, mock_config)
    assert res["components"]["seniority_fit"] == 0.0
    assert "seniority gap (lead)" in res["reason"]


def test_case_insensitive_matching(mock_config: Config) -> None:
    listing = {"title": "Data Engineer", "location": "bengaluru", "posted_at": None}
    facts = {
        "required_skills": ["PYTHON", "SqL"],
        "nice_to_have": ["PANDAS"],
        "seniority": "JUNIOR",
        "years_required": 1,
        "remote_ok": True,
    }

    res = score_listing(listing, facts, mock_config)
    assert res["components"]["skill_match"] == 1.0
    assert res["components"]["seniority_fit"] == 1.0
    assert "no skill gaps" in res["reason"]

def test_stability_same_listing_scored_twice(mock_config: Config) -> None:
    listing = {
        "title": "Machine Learning Engineer",
        "company": "DeepTech",
        "location": "Bengaluru",
        "posted_at": "2026-09-25T10:00:00Z",
    }
    facts = {
        "required_skills": ["python", "pytorch", "docker"],
        "nice_to_have": ["kubernetes"],
        "seniority": "junior",
        "years_required": 1,
        "remote_ok": True,
    }

    res1 = score_listing(listing, facts, mock_config)
    res2 = score_listing(listing, facts, mock_config)

    assert res1["score"] == res2["score"]
    assert res1["reason"] == res2["reason"]
    assert res1["components"] == res2["components"]


def test_skill_alias_and_whitespace_normalization(mock_config: Config) -> None:
    # Test Node.js vs nodejs vs node, and sklearn vs Scikit-Learn
    cfg = Config(
        target_role="Software Engineer",
        target_city="Bengaluru",
        keywords=["Node", "React"],
        my_skills=["Node.js", "ReactJS", "Scikit Learn", "PostgreSQL"],
        experience_years=2,
        db_path=":memory:",
        min_fit_score=70,
        target_seniority="mid",
        score_batch_size=25,
        scoring_weights={"skill_match": 1.0, "seniority_fit": 0.0, "location_fit": 0.0, "recency": 0.0},
    )
    listing = {"title": "Fullstack Engineer", "location": "Remote", "posted_at": None}
    facts = {
        "required_skills": ["  node  ", "react.js", "sklearn", "postgres"],
        "nice_to_have": [],
        "seniority": "mid",
        "years_required": 2,
        "remote_ok": True,
    }

    res = score_listing(listing, facts, cfg)
    assert res["components"]["skill_match"] == 1.0
    assert "no skill gaps" in res["reason"]
