from datetime import datetime, timezone
import json
import time
from typing import Any
from edgedash.agents.base import Agent, AgentResult
from edgedash.agents.fetcher import Fetcher
from edgedash.agents.scorer import Scorer
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.agents.mock_fetcher import MockFetcher
from edgedash.config import Config
from edgedash.planning import build_plan, Plan
from edgedash.state import read_state, explain_state
import edgedash.storage as storage

AGENT_REGISTRY: dict[str, type[Agent]] = {
    "fetcher": Fetcher,
    "scorer": Scorer,
    "gap_analyzer": GapAnalyzer,
    "fetch": Fetcher,
    "score": Scorer,
    "analyse": GapAnalyzer,
}


def run_cycle(
    config: Config,
    now: datetime | None = None,
    dry_run: bool = False,
    force_agents: list[str] | None = None,
    explain: bool = False,
) -> str:
    """State-driven autonomous orchestrator cycle (Rules 28-33)."""
    start_cycle_iso = datetime.now(timezone.utc).isoformat()
    storage.init_db(config.db_path)

    # 1. State inspection and planning (Rule 28)
    evaluation_now = now or datetime.now(timezone.utc)
    current_state = read_state(config, evaluation_now)
    if explain:
        print(explain_state(current_state, config))

    plan: Plan = build_plan(current_state, config)

    # 2. Apply manual agent overrides (--force)
    overrides_applied: list[str] = []
    if force_agents:
        for forced in force_agents:
            forced_clean = forced.strip().lower()
            for task in plan:
                if task.agent_name == forced_clean and task.skipped:
                    task.skipped = False
                    task.reason = "forced by operator"
                    overrides_applied.append(str(task.agent_name))

    if overrides_applied:
        print("=" * 70)
        print(f"⚠️  WARNING: Manual override active. Forced: {', '.join(overrides_applied)}")

    # 3. Print rendered plan before executing (Rule 31)
    print("=" * 70)
    print("                      EDGEDASH ORCHESTRATOR PLAN")
    print("=" * 70)
    print(plan.render())
    print("-" * 70)

    # 4. Handle dry-run: exit without writes or execution
    if dry_run:
        print("[DRY-RUN] Execution halted. No agents executed and no storage writes performed.")
        print("=" * 70)
        return "dry_run"

    active_registry = dict(AGENT_REGISTRY)
    if config.use_mock_fetcher:
        active_registry["fetcher"] = MockFetcher
        active_registry["fetch"] = MockFetcher

    # 5. Execute unskipped tasks in order; pass goal & stop_conditions (Rule 29 & 32)
    has_failure = False
    durations: dict[str, float] = {}
    ran_results: list[AgentResult] = []
    total_records = 0

    for task in plan:
        if task.skipped:
            continue

        agent_key = str(task.agent_name)
        agent_cls = active_registry.get(agent_key)
        if not agent_cls:
            print(f" ! {agent_key:<14} [FAILED] -> Unregistered agent in registry")
            has_failure = True
            continue

        agent = agent_cls()
        t0 = time.time()
        try:
            result = agent.run(config, storage, goal=task.goal, stop_conditions=task.stop_conditions)
            duration = round(time.time() - t0, 3)
            durations[agent_key] = duration
            ran_results.append(result)
            total_records += result.records_touched
            if result.status == "failed":
                has_failure = True
            print(f" * {agent_key:<14} [{result.status.upper()}] ({duration:.2f}s) -> {result.notes}")
        except Exception as exc:
            duration = round(time.time() - t0, 3)
            durations[agent_key] = duration
            has_failure = True
            print(f" ! {agent_key:<14} [FAILED] ({duration:.2f}s) -> {exc}")

    # 6. Outcome determination: complete | partial | nothing_to_do (Rule 33)
    if all(t.skipped for t in plan):
        outcome = "nothing_to_do"
    elif has_failure:
        outcome = "partial"
    else:
        outcome = "complete"

    # Write single cycle summary row with overrides logged (Rule 33)
    end_cycle_iso = datetime.now(timezone.utc).isoformat()
    summary_data = {
        "plan": plan.render(),
        "ran": [r.agent for r in ran_results],
        "skipped": {str(t.agent_name): t.reason for t in plan if t.skipped},
        "durations": durations,
        "outcome": outcome,
        "overrides": overrides_applied,
    }
    storage.log_cycle(
        agent="orchestrator",
        started_at=start_cycle_iso,
        finished_at=end_cycle_iso,
        records_touched=total_records,
        status=outcome,
        notes=json.dumps(summary_data),
        db_path=config.db_path,
    )

    print("-" * 70)
    print(f"CYCLE OUTCOME: {outcome.upper()} | Records Touched: {total_records}")
    print("=" * 70)
    return outcome
