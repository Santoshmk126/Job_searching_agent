import pytest
from edgedash.agents.gap_analyzer import compute_skill_gaps


def test_opportunity_cost_arithmetic() -> None:
    # 2 listings requiring 'kubernetes': one scored 85, one scored 20
    listings = [
        {
            "id": "job_1",
            "score": 85,
            "facts": {"required_skills": ["kubernetes"], "nice_to_have": []},
        },
        {
            "id": "job_2",
            "score": 20,
            "facts": {"required_skills": ["kubernetes"], "nice_to_have": []},
        },
    ]

    gaps = compute_skill_gaps(listings, my_skills=["python"])
    assert len(gaps) == 1
    k8s = gaps[0]

    assert k8s["skill"] == "kubernetes"
    assert k8s["listings_blocked"] == 2
    # Rule 24: opportunity_cost = 0.85 + 0.20 = 1.05
    assert k8s["opportunity_cost"] == 1.05
    assert k8s["mean_score"] == 52.5
    assert k8s["top_score"] == 85
    assert k8s["example_ids"] == ["job_1", "job_2"]
    assert k8s["low_confidence"] is True  # 2 < 3 listings (Rule 27)


def test_higher_fit_ranking_over_raw_frequency() -> None:
    # Skill A: 1 listing with score 90 -> opp cost = 0.90
    # Skill B: 3 listings with score 20 each -> opp cost = 0.60
    listings = [
        {"id": "high_1", "score": 90, "facts": {"required_skills": ["terraform"], "nice_to_have": []}},
        {"id": "low_1", "score": 20, "facts": {"required_skills": ["php"], "nice_to_have": []}},
        {"id": "low_2", "score": 20, "facts": {"required_skills": ["php"], "nice_to_have": []}},
        {"id": "low_3", "score": 20, "facts": {"required_skills": ["php"], "nice_to_have": []}},
    ]

    gaps = compute_skill_gaps(listings, my_skills=["python"])
    assert len(gaps) == 2
    # Rule 24: terraform (0.90) ranks ABOVE php (0.60) despite php having 3x the frequency
    assert gaps[0]["skill"] == "terraform"
    assert gaps[0]["opportunity_cost"] == 0.90
    assert gaps[1]["skill"] == "php"
    assert gaps[1]["opportunity_cost"] == 0.60


def test_nice_to_have_tracked_separately() -> None:
    listings = [
        {"id": "j1", "score": 70, "facts": {"required_skills": ["docker"], "nice_to_have": ["redis"]}},
        {"id": "j2", "score": 60, "facts": {"required_skills": ["docker"], "nice_to_have": ["docker"]}},
    ]

    gaps = compute_skill_gaps(listings, my_skills=["python"])
    docker_gap = next(g for g in gaps if g["skill"] == "docker")
    redis_gap = next((g for g in gaps if g["skill"] == "redis"), None)

    # redis was only nice_to_have -> 0 listings blocked, never in required gaps
    assert redis_gap is None
    # docker required in 2, nice_to_have in 1
    assert docker_gap["listings_blocked"] == 2
    assert docker_gap["also_nice_to_have"] == 1


def test_low_confidence_flag() -> None:
    # 2 listings -> low_confidence True, 3 listings -> low_confidence False
    listings_2 = [
        {"id": f"id_{i}", "score": 50, "facts": {"required_skills": ["rust"], "nice_to_have": []}}
        for i in range(2)
    ]
    listings_3 = [
        {"id": f"id_{i}", "score": 50, "facts": {"required_skills": ["rust"], "nice_to_have": []}}
        for i in range(3)
    ]

    gaps_2 = compute_skill_gaps(listings_2, my_skills=[])
    gaps_3 = compute_skill_gaps(listings_3, my_skills=[])

    assert gaps_2[0]["low_confidence"] is True
    assert gaps_3[0]["low_confidence"] is False


def test_example_ids_capped_at_five() -> None:
    # 7 listings with different scores
    listings = [
        {"id": f"job_{i}", "score": i * 10, "facts": {"required_skills": ["aws"], "nice_to_have": []}}
        for i in range(1, 8)
    ]

    gaps = compute_skill_gaps(listings, my_skills=[])
    aws_gap = gaps[0]

    assert len(aws_gap["example_ids"]) == 5
    # Must be sorted highest score first (job_7 with 70 down to job_3 with 30)
    assert aws_gap["example_ids"] == ["job_7", "job_6", "job_5", "job_4", "job_3"]


from edgedash.gaps import compute_gap_trends, print_gap_trends


def test_trend_empty_snapshots() -> None:
    res = compute_gap_trends([], [], [])
    assert res["status"] == "empty"


def test_trend_single_snapshot_no_extrapolation() -> None:
    runs = [{"run_id": "run_1", "computed_at": "2026-09-20T10:00:00+00:00"}]
    res = compute_gap_trends(runs, [], [])
    assert res["status"] == "single"
    assert res["run_id"] == "run_1"
    assert res["days_needed"] == 1
    assert "Only one snapshot" in res["message"]
    assert "top_10_trends" not in res  # No trend fabricated from single point


def test_trend_multi_snapshots_calculations() -> None:
    runs = [
        {"run_id": "run_early", "computed_at": "2026-09-20T10:00:00+00:00"},
        {"run_id": "run_late", "computed_at": "2026-09-27T10:00:00+00:00"},
    ]

    earliest_gaps = [
        {"skill": "kubernetes", "opportunity_cost": 5.0},
        {"skill": "terraform", "opportunity_cost": 4.0},
        {"skill": "java", "opportunity_cost": 3.0},
        {"skill": "spark", "opportunity_cost": 2.0},  # will drop out of top 10
    ] + [{"skill": f"old_skill_{i}", "opportunity_cost": 1.0} for i in range(6)]

    latest_gaps = [
        {"skill": "kubernetes", "opportunity_cost": 6.0},  # +1.0 (+20%)
        {"skill": "terraform", "opportunity_cost": 3.0},   # -1.0 (-25%)
        {"skill": "java", "opportunity_cost": 3.0},        # 0.0 (FLAT)
        {"skill": "rust", "opportunity_cost": 4.5},        # NEW
    ] + [{"skill": f"old_skill_{i}", "opportunity_cost": 1.0} for i in range(6)]

    res = compute_gap_trends(runs, earliest_gaps, latest_gaps)
    assert res["status"] == "ok"
    assert res["days_apart"] == 7
    assert res["earliest_run_id"] == "run_early"
    assert res["latest_run_id"] == "run_late"

    top_trends = {t["skill"]: t for t in res["top_10_trends"]}

    # 1. Rising skill
    k8s = top_trends["kubernetes"]
    assert k8s["earliest_cost"] == 5.0
    assert k8s["latest_cost"] == 6.0
    assert k8s["diff_abs"] == 1.0
    assert k8s["diff_pct"] == 20.0
    assert k8s["status"] == "RISING"

    # 2. Falling skill
    tf = top_trends["terraform"]
    assert tf["earliest_cost"] == 4.0
    assert tf["latest_cost"] == 3.0
    assert tf["diff_abs"] == -1.0
    assert tf["diff_pct"] == -25.0
    assert tf["status"] == "FALLING"

    # 3. Flat skill
    java = top_trends["java"]
    assert java["diff_abs"] == 0.0
    assert java["diff_pct"] == 0.0
    assert java["status"] == "FLAT"

    # 4. NEW skill
    rust = top_trends["rust"]
    assert rust["is_new"] is True
    assert rust["earliest_cost"] is None
    assert rust["latest_cost"] == 4.5
    assert rust["diff_abs"] == 4.5
    assert rust["status"] == "NEW"

    # 5. DROPPED OUT skill
    dropped = {d["skill"]: d for d in res["dropped_out"]}
    assert "spark" in dropped
    spark = dropped["spark"]
    assert spark["earliest_cost"] == 2.0
    assert spark["latest_cost"] is None
    assert spark["diff_abs"] == -2.0
    assert spark["diff_pct"] == -100.0
    assert spark["status"] == "DROPPED OUT"


def test_print_gap_trends_cli(capsys, monkeypatch) -> None:
    # 1. Test single snapshot printing
    monkeypatch.setattr(
        "edgedash.gaps.get_gap_trends",
        lambda db_path=None: {
            "status": "single",
            "snapshot_date": "2026-09-27 10:00:00 UTC",
            "run_id": "run_xyz",
            "days_needed": 1,
            "message": "1 more day of runs needed.",
        },
    )
    print_gap_trends()
    captured = capsys.readouterr().out
    assert "Only one snapshot recorded so far" in captured
    assert "1 more day of runs needed to show a trend" in captured
    assert "No trend fabricated, interpolated, or extrapolated" in captured
    assert "2026-09-27 10:00:00 UTC" in captured

    # 2. Test multi-snapshot printing
    monkeypatch.setattr(
        "edgedash.gaps.get_gap_trends",
        lambda db_path=None: {
            "status": "ok",
            "earliest_run_id": "run_1",
            "latest_run_id": "run_2",
            "earliest_date": "2026-09-20 10:00:00 UTC",
            "latest_date": "2026-09-27 10:00:00 UTC",
            "window_str": "2026-09-20 to 2026-09-27 (7 days apart)",
            "days_apart": 7,
            "top_10_trends": [
                {
                    "rank": 1,
                    "skill": "kubernetes",
                    "earliest_cost": 5.0,
                    "latest_cost": 6.0,
                    "diff_abs": 1.0,
                    "diff_pct": 20.0,
                    "is_new": False,
                    "status": "RISING",
                },
                {
                    "rank": 2,
                    "skill": "rust",
                    "earliest_cost": None,
                    "latest_cost": 4.5,
                    "diff_abs": 4.5,
                    "diff_pct": None,
                    "is_new": True,
                    "status": "NEW",
                },
            ],
            "dropped_out": [
                {
                    "skill": "spark",
                    "earliest_cost": 2.0,
                    "latest_cost": None,
                    "diff_abs": -2.0,
                    "diff_pct": -100.0,
                    "status": "DROPPED OUT",
                }
            ],
        },
    )
    print_gap_trends()
    captured2 = capsys.readouterr().out
    assert "CURRENT TOP 10 SKILL GAPS:" in captured2
    assert "kubernetes" in captured2
    assert "+1.00" in captured2
    assert "+20.0%" in captured2
    assert "rust" in captured2
    assert "NEW" in captured2
    assert "SKILLS DROPPED OUT OF TOP 10" in captured2
    assert "spark" in captured2
    assert "-2.00" in captured2
    assert "-100.0%" in captured2
    assert "DROPPED OUT" in captured2
