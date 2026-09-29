from datetime import datetime, timezone
import json
import pytest
from unittest.mock import MagicMock, patch

from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config
from edgedash.orchestrator import run_cycle, AGENT_REGISTRY
from edgedash.planning import Task, Plan
from edgedash.state import SystemState
import edgedash.storage as storage


@pytest.fixture
def mock_config(tmp_path):
    db_file = str(tmp_path / "test_orch.db")
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
        score_batch_size=25,
    )


def test_orchestrator_nothing_to_do(mock_config):
    # State where hours_since_fetch is 1.0, unscored is 0, gaps_stale is False
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    
    # Pre-populate db with recent fetch, 0 unscored, and recent gap
    storage.upsert_listings([{
        "title": "ML Eng", "company": "Co", "url": "https://a.com", "source": "src",
        "fetched_at": "2026-09-29T11:00:00+00:00", "fit_score": 85, "fit_reason": "ok"
    }], db_path=mock_config.db_path)
    storage.save_skill_gaps_snapshot(
        run_id="gap_1", computed_at="2026-09-29T11:05:00+00:00", gaps=[{"skill": "k8s", "listings_blocked": 1, "opportunity_cost": 0.8, "mean_score": 80, "top_score": 80}], db_path=mock_config.db_path
    )

    outcome = run_cycle(mock_config, now=fixed_now)
    assert outcome == "nothing_to_do"

    # Exactly one cycle summary row written
    with storage._get_connection(mock_config.db_path) as conn:
        rows = conn.execute("SELECT * FROM cycle_log").fetchall()
        assert len(rows) == 1
        summary_row = dict(rows[0])
        assert summary_row["agent"] == "orchestrator"
        assert summary_row["status"] == "nothing_to_do"
        notes = json.loads(summary_row["notes"])
        assert notes["outcome"] == "nothing_to_do"
        assert notes["ran"] == []
        assert "fetcher" in notes["skipped"]
        assert "scorer" in notes["skipped"]
        assert "gap_analyzer" in notes["skipped"]


def test_orchestrator_partial_on_agent_failure(mock_config):
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)

    # Fake failing agent in registry
    class FailingAgent(Agent):
        name = "failing"
        def run(self, config, storage_mod, goal=None, stop_conditions=None):
            raise RuntimeError("Simulated network crash")

    class WorkingAgent(Agent):
        name = "working"
        def run(self, config, storage_mod, goal=None, stop_conditions=None):
            return AgentResult(agent=self.name, status="ok", records_touched=5, notes="Done")

    plan = Plan(tasks=[
        Task(agent_name="failing", goal="Task 1", stop_conditions={}, reason="test", skipped=False),
        Task(agent_name="working", goal="Task 2", stop_conditions={}, reason="test", skipped=False),
    ])

    with patch.dict(AGENT_REGISTRY, {"failing": FailingAgent, "working": WorkingAgent}, clear=False):
        with patch("edgedash.orchestrator.build_plan", return_value=plan):
            outcome = run_cycle(mock_config, now=fixed_now)

    assert outcome == "partial"

    with storage._get_connection(mock_config.db_path) as conn:
        rows = conn.execute("SELECT * FROM cycle_log WHERE agent = 'orchestrator'").fetchall()
        assert len(rows) == 1
        summary = json.loads(rows[0]["notes"])
        assert summary["outcome"] == "partial"
        assert "working" in summary["ran"]
        assert "failing" in summary["durations"]


def test_orchestrator_complete_execution(mock_config):
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    storage.upsert_listings([{
        "title": "ML Eng", "company": "Co", "url": "https://a.com", "source": "src",
        "fetched_at": "2026-09-29T11:00:00+00:00", "fit_score": 85, "fit_reason": "ok"
    }], db_path=mock_config.db_path)
    storage.save_skill_gaps_snapshot(
        run_id="gap_1", computed_at="2026-09-29T11:05:00+00:00",
        gaps=[{"skill": "k8s", "listings_blocked": 5, "opportunity_cost": 0.8, "mean_score": 80, "top_score": 80}],
        db_path=mock_config.db_path
    )

    class SuccessAgent(Agent):
        name = "success_agent"
        def run(self, config, storage_mod, goal=None, stop_conditions=None):
            assert goal == "Goal 1"
            assert stop_conditions == {"max_items": 10}
            return AgentResult(agent=self.name, status="ok", records_touched=10, notes="Success")

    plan = Plan(tasks=[
        Task(agent_name="success_agent", goal="Goal 1", stop_conditions={"max_items": 10}, reason="unscored_count=10", skipped=False),
        Task(agent_name="fetcher", goal="Goal 2", stop_conditions={}, reason="skipped: hours", skipped=True),
    ])

    with patch.dict(AGENT_REGISTRY, {"success_agent": SuccessAgent}, clear=False):
        with patch("edgedash.orchestrator.build_plan", return_value=plan):
            outcome = run_cycle(mock_config, now=fixed_now)

    assert outcome == "complete"

    with storage._get_connection(mock_config.db_path) as conn:
        rows = conn.execute("SELECT * FROM cycle_log WHERE agent = 'orchestrator'").fetchall()
        assert len(rows) == 1
        summary = json.loads(rows[0]["notes"])
        assert summary["outcome"] == "complete"
        assert "success_agent" in summary["ran"]
        assert "verifier" in summary["ran"]
        assert "fetcher" in summary["skipped"]


def test_orchestrator_dry_run(mock_config):
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    with storage._get_connection(mock_config.db_path) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM cycle_log").fetchone()[0]

    outcome = run_cycle(mock_config, now=fixed_now, dry_run=True)
    assert outcome == "dry_run"

    with storage._get_connection(mock_config.db_path) as conn:
        after_count = conn.execute("SELECT COUNT(*) FROM cycle_log").fetchone()[0]
        assert after_count == before_count  # Zero writes performed


def test_orchestrator_force_flag_override(mock_config):
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)

    # State where fetcher would normally skip (e.g., hours_since_fetch = 1.0)
    storage.upsert_listings([{
        "title": "ML Eng", "company": "Co", "url": "https://a.com", "source": "src",
        "fetched_at": "2026-09-29T11:00:00+00:00", "fit_score": 85, "fit_reason": "ok"
    }], db_path=mock_config.db_path)

    class CustomFetcher(Agent):
        name = "fetcher"
        def run(self, config, storage_mod, goal=None, stop_conditions=None):
            return AgentResult(agent=self.name, status="ok", records_touched=1, notes="Forced run ok")

    with patch.dict(AGENT_REGISTRY, {"fetcher": CustomFetcher}, clear=False):
        outcome = run_cycle(mock_config, now=fixed_now, force_agents=["fetcher"])

    with storage._get_connection(mock_config.db_path) as conn:
        rows = conn.execute("SELECT * FROM cycle_log WHERE agent = 'orchestrator' ORDER BY id DESC LIMIT 1").fetchall()
        summary = json.loads(rows[0]["notes"])
        assert "fetcher" in summary["ran"]
        assert "fetcher" in summary.get("overrides", [])


def test_explain_state_output(mock_config):
    state = SystemState(
        last_fetch_at="2026-09-29T03:53:23Z",
        hours_since_fetch=5.3,
        unscored_count=45,
        gaps_computed_at="2026-09-29T03:54:58Z",
        gaps_stale=True,
        last_cycle_verdict="complete",
        last_cycle_at="2026-09-29T09:10:10Z",
    )
    from edgedash.state import explain_state
    text = explain_state(state, mock_config)
    assert "last_fetch_at" in text
    assert "2026-09-29T03:53:23Z" in text
    assert "hours_since_fetch" in text
    assert "unscored_count" in text
    assert "45" in text
    assert "gaps_stale" in text


def test_orchestrator_verification_retry_and_degraded(mock_config):
    fixed_now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    from edgedash.verification import CheckResult, Verdict

    # Verifier that always fails
    class AlwaysFailingVerifier(Agent):
        name = "verifier"
        def run(self, config, storage_mod, goal=None, stop_conditions=None, context=None):
            fail_check = CheckResult("check_score_spread", False, {"spread": 2.0}, {"min_score_spread": 10.0}, "Score spread failed")
            v = Verdict(passed=False, failed_checks=[fail_check], summary="Verification failed")
            res = AgentResult(agent=self.name, status="failed", records_touched=0, notes="VERDICT: fail")
            res.verdict = v
            return res

    retried = []
    class MockScorer(Agent):
        name = "scorer"
        def run(self, config, storage_mod, goal=None, stop_conditions=None):
            if stop_conditions and stop_conditions.get("stricter"):
                retried.append(True)
            return AgentResult(agent=self.name, status="ok", records_touched=5, notes="Scored")

    plan = Plan(tasks=[Task(agent_name="scorer", goal="Score", stop_conditions={}, reason="test", skipped=False)])

    with patch.dict(AGENT_REGISTRY, {"verifier": AlwaysFailingVerifier, "scorer": MockScorer}, clear=False):
        with patch("edgedash.orchestrator.build_plan", return_value=plan):
            outcome = run_cycle(mock_config, now=fixed_now)

    # Must be marked degraded after exactly 1 retry and stop (Rule 36)
    assert outcome == "degraded"
    assert len(retried) == 1

    with storage._get_connection(mock_config.db_path) as conn:
        row = conn.execute("SELECT * FROM cycle_log WHERE agent = 'orchestrator' ORDER BY id DESC LIMIT 1").fetchone()
        assert row["status"] == "degraded"
        notes = json.loads(row["notes"])
        assert notes["verdict"]["passed"] is False
        assert notes["verdict"]["retry_count"] == 1
        assert notes["verdict"]["failed_checks"][0]["name"] == "check_score_spread"


def test_get_latest_verified_cycle(mock_config):
    # Log a passing cycle
    storage.log_cycle(
        agent="orchestrator", started_at="2026-09-29T10:00:00Z", finished_at="2026-09-29T10:01:00Z",
        records_touched=10, status="complete", notes=json.dumps({"verdict": {"passed": True, "status": "pass"}}),
        db_path=mock_config.db_path
    )
    # Log a subsequent degraded cycle
    storage.log_cycle(
        agent="orchestrator", started_at="2026-09-29T11:00:00Z", finished_at="2026-09-29T11:01:00Z",
        records_touched=10, status="degraded", notes=json.dumps({"verdict": {"passed": False, "status": "fail"}}),
        db_path=mock_config.db_path
    )

    passing_cycle = storage.get_latest_verified_cycle(db_path=mock_config.db_path)
    assert passing_cycle is not None
    assert passing_cycle["status"] == "complete"
    assert passing_cycle["started_at"] == "2026-09-29T10:00:00Z"
