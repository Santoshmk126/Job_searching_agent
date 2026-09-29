from datetime import datetime, timezone
import pytest
from edgedash.config import Config
from edgedash.state import SystemState, read_state
from edgedash.planning import build_plan, Plan, Task
import edgedash.storage as storage


@pytest.fixture
def mock_config(tmp_path):
    db_file = str(tmp_path / "test_state.db")
    storage.init_db(db_file)
    return Config(
        target_role="AI Engineer",
        target_city="Bengaluru",
        keywords=["AI"],
        my_skills=["Python"],
        experience_years=1,
        db_path=db_file,
        min_fit_score=70,
        fetch_interval_hours=6.0,
        fetch_max_pages=5,
        fetch_max_listings=50,
        score_batch_size=25,
        score_max_seconds=60,
        analyse_max_seconds=30,
    )


def test_build_plan_everything_stale(mock_config):
    state = SystemState(
        last_fetch_at="2026-09-29T00:00:00+00:00",
        hours_since_fetch=12.5,
        unscored_count=15,
        gaps_computed_at="2026-09-29T01:00:00+00:00",
        gaps_stale=True,
        last_cycle_verdict="passed",
        last_cycle_at="2026-09-29T01:00:05+00:00",
    )

    plan = build_plan(state, mock_config)
    assert len(plan) == 3

    # All three agents must run
    fetch_task, score_task, analyse_task = plan[0], plan[1], plan[2]

    assert fetch_task.agent_name == "fetcher"
    assert not fetch_task.skipped
    assert "hours_since_fetch=12.5" in fetch_task.reason
    assert fetch_task.stop_conditions == {"max_pages": 5, "max_listings": 50}

    assert score_task.agent_name == "scorer"
    assert not score_task.skipped
    assert score_task.reason == "unscored_count=15"
    assert score_task.stop_conditions == {"max_items": 25, "max_seconds": 60}

    assert analyse_task.agent_name == "gap_analyzer"
    assert not analyse_task.skipped
    assert analyse_task.reason == "gaps_stale=True"
    assert analyse_task.stop_conditions == {"max_seconds": 30}


def test_build_plan_nothing_to_do(mock_config):
    state = SystemState(
        last_fetch_at="2026-09-29T10:00:00+00:00",
        hours_since_fetch=2.0,
        unscored_count=0,
        gaps_computed_at="2026-09-29T10:05:00+00:00",
        gaps_stale=False,
        last_cycle_verdict="passed",
        last_cycle_at="2026-09-29T10:05:05+00:00",
    )

    plan = build_plan(state, mock_config)
    assert len(plan) == 3

    # All three must be skipped WITH a reason per Rule 31
    for task in plan:
        assert task.skipped is True
        assert task.reason.startswith("skipped:")

    assert plan[0].reason == "skipped: hours_since_fetch=2.0"
    assert plan[1].reason == "skipped: unscored_count=0"
    assert plan[2].reason == "skipped: gaps_stale=False"

    # Render check
    rendered = plan.render()
    lines = rendered.strip().split("\n")
    assert len(lines) == 3
    for line in lines:
        assert "[SKIP]" in line
        assert "Goal:" in line
        assert "Stop:" in line
        assert "Reason: skipped:" in line


def test_build_plan_only_unscored_listings(mock_config):
    state = SystemState(
        last_fetch_at="2026-09-29T11:00:00+00:00",
        hours_since_fetch=1.0,
        unscored_count=42,
        gaps_computed_at="2026-09-29T11:05:00+00:00",
        gaps_stale=False,
        last_cycle_verdict="passed",
        last_cycle_at="2026-09-29T11:05:05+00:00",
    )

    plan = build_plan(state, mock_config)
    assert plan[0].skipped is True
    assert plan[1].skipped is False
    assert plan[2].skipped is True

    assert plan[0].reason == "skipped: hours_since_fetch=1.0"
    assert plan[1].reason == "unscored_count=42"
    assert plan[2].reason == "skipped: gaps_stale=False"


def test_build_plan_gaps_stale_but_nothing_unscored(mock_config):
    state = SystemState(
        last_fetch_at="2026-09-29T09:00:00+00:00",
        hours_since_fetch=3.0,
        unscored_count=0,
        gaps_computed_at="2026-09-29T08:00:00+00:00",
        gaps_stale=True,
        last_cycle_verdict="passed",
        last_cycle_at="2026-09-29T08:00:05+00:00",
    )

    plan = build_plan(state, mock_config)
    assert plan[0].skipped is True
    assert plan[1].skipped is True
    assert plan[2].skipped is False

    assert plan[0].reason == "skipped: hours_since_fetch=3.0"
    assert plan[1].reason == "skipped: unscored_count=0"
    assert plan[2].reason == "gaps_stale=True"


def test_build_plan_initial_state_never_fetched_never_computed(mock_config):
    state = SystemState(
        last_fetch_at=None,
        hours_since_fetch=None,
        unscored_count=0,
        gaps_computed_at=None,
        gaps_stale=False,
        last_cycle_verdict=None,
        last_cycle_at=None,
    )

    plan = build_plan(state, mock_config)
    # Fetch runs because never fetched
    assert plan[0].skipped is False
    assert "hours_since_fetch=None" in plan[0].reason

    # Score skipped because unscored_count is 0
    assert plan[1].skipped is True

    # Analyse runs because gaps_computed_at is None
    assert plan[2].skipped is False
    assert plan[2].reason == "gaps_computed_at=None"


def test_read_state_deterministic(mock_config):
    db_path = mock_config.db_path
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)

    # Empty DB
    state_empty = read_state(mock_config, fixed_now)
    assert state_empty.last_fetch_at is None
    assert state_empty.hours_since_fetch is None
    assert state_empty.unscored_count == 0
    assert state_empty.gaps_computed_at is None
    assert state_empty.gaps_stale is False
    assert state_empty.last_cycle_verdict is None

    # Insert 1 unscored listing fetched 4 hours before fixed_now
    fetched_iso = "2026-09-29T08:00:00+00:00"
    storage.upsert_listings([
        {
            "title": "ML Engineer",
            "company": "Tech Corp",
            "url": "https://example.com/ml1",
            "source": "arbeitnow",
            "fetched_at": fetched_iso,
        }
    ], db_path=db_path)

    state_with_job = read_state(mock_config, fixed_now)
    assert state_with_job.last_fetch_at == fetched_iso
    assert state_with_job.hours_since_fetch == 4.0
    assert state_with_job.unscored_count == 1
    assert state_with_job.gaps_computed_at is None
    assert state_with_job.gaps_stale is False
