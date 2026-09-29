import json
import pytest
from edgedash.verdicts import render_verdicts_table, extract_cycle_verdict


def test_extract_cycle_verdict_passing():
    cycle = {
        "status": "complete",
        "notes_parsed": {
            "ran": ["fetcher", "scorer"],
            "verdict": {"passed": True, "status": "pass", "failed_checks": [], "retry_count": 0}
        }
    }
    verdict, failed_checks, retries, ran = extract_cycle_verdict(cycle)
    assert verdict == "pass"
    assert len(failed_checks) == 0
    assert retries == 0
    assert ran == "fetcher, scorer"


def test_extract_cycle_verdict_degraded():
    cycle = {
        "status": "degraded",
        "notes_parsed": {
            "ran": ["scorer", "verifier"],
            "verdict": {
                "passed": False,
                "status": "fail",
                "failed_checks": [{"name": "check_score_spread", "message": "spread 5 < 10"}],
                "retry_count": 1,
            }
        }
    }
    verdict, failed_checks, retries, ran = extract_cycle_verdict(cycle)
    assert verdict == "degraded"
    assert len(failed_checks) == 1
    assert failed_checks[0]["name"] == "check_score_spread"
    assert retries == 1


def test_render_verdicts_table_stats():
    cycles = [
        {
            "finished_at": "2026-09-29T10:00:00Z",
            "status": "complete",
            "notes_parsed": {
                "ran": ["gap_analyzer"],
                "verdict": {"passed": True, "status": "pass", "failed_checks": [], "retry_count": 0}
            }
        },
        {
            "finished_at": "2026-09-29T11:00:00Z",
            "status": "degraded",
            "notes_parsed": {
                "ran": ["scorer", "verifier"],
                "verdict": {
                    "passed": False,
                    "status": "fail",
                    "failed_checks": [{"name": "check_score_spread", "message": "spread < 10"}],
                    "retry_count": 1,
                }
            }
        },
        {
            "finished_at": "2026-09-29T12:00:00Z",
            "status": "degraded",
            "notes_parsed": {
                "ran": ["scorer", "verifier"],
                "verdict": {
                    "passed": False,
                    "status": "fail",
                    "failed_checks": [{"name": "check_score_spread", "message": "spread < 10"}],
                    "retry_count": 1,
                }
            }
        },
    ]

    out, stats = render_verdicts_table(cycles, use_color=False)
    assert stats["total"] == 3
    assert stats["passed"] == 1
    assert stats["pass_rate"] == 33.33
    assert stats["most_frequent_fail"] == "check_score_spread"
    assert "Pass Rate: 33.3%" in out
    assert "check_score_spread (2 failure(s))" in out


def test_render_verdicts_table_filter_by_check():
    cycles = [
        {
            "finished_at": "2026-09-29T10:00:00Z",
            "status": "degraded",
            "notes_parsed": {
                "ran": ["scorer"],
                "verdict": {
                    "passed": False,
                    "failed_checks": [{"name": "check_score_spread", "message": "spread < 10"}],
                    "retry_count": 1,
                }
            }
        },
        {
            "finished_at": "2026-09-29T11:00:00Z",
            "status": "degraded",
            "notes_parsed": {
                "ran": ["fetcher"],
                "verdict": {
                    "passed": False,
                    "failed_checks": [{"name": "check_freshness", "message": "age > 3d"}],
                    "retry_count": 1,
                }
            }
        },
    ]

    out_spread, stats_spread = render_verdicts_table(cycles, check_filter="check_score_spread", use_color=False)
    assert stats_spread["total"] == 1
    assert "check_score_spread" in out_spread
    assert "check_freshness" not in out_spread

    out_none, stats_none = render_verdicts_table(cycles, check_filter="non_existent_check", use_color=False)
    assert stats_none["total"] == 0
    assert "No verification records found" in out_none
