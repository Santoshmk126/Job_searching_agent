from datetime import datetime, timezone
from typing import Any

from edgedash.agents.base import Agent, AgentResult
from edgedash.agents.mock_fetcher import MockFetcher
from edgedash.config import Config
import edgedash.storage as storage


class PlaceholderScorer(Agent):
    name: str = "scorer"

    def run(self, config: Config, storage_module: Any) -> AgentResult:
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=0,
            notes="Skipped (not implemented yet)",
        )


class PlaceholderGapAnalyzer(Agent):
    name: str = "gap_analyzer"

    def run(self, config: Config, storage_module: Any) -> AgentResult:
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=0,
            notes="Skipped (not implemented yet)",
        )


# Agent Registry: Swap MockFetcher with RealFetcher when available
AGENT_REGISTRY: dict[str, type[Agent]] = {
    "fetcher": MockFetcher,
    "scorer": PlaceholderScorer,
    "gap_analyzer": PlaceholderGapAnalyzer,
}


def run_cycle(config: Config) -> None:
    storage.init_db(config.db_path)

    last_fetch = storage.last_fetch_time(config.db_path)
    unscored = storage.count_unscored(config.db_path)

    print("=" * 70)
    print("                   EDGEDASH ORCHESTRATOR CYCLE")
    print("=" * 70)
    print(f"Target Role   : {config.target_role}")
    print(f"Target City   : {config.target_city}")
    print(f"Database Path : {config.db_path}")
    print(f"Last Fetch    : {last_fetch or 'Never (Initial crawl)'}")
    print(f"Unscored Jobs : {unscored}")
    print("-" * 70)

    print("[PLAN]")
    print("  1. fetcher      -> Fetch latest jobs and deduplicate against storage.")
    print("  2. scorer       -> Evaluate fit score for unscored jobs (placeholder).")
    print("  3. gap_analyzer -> Detect missing skills from job descriptions (placeholder).")
    print("-" * 70)

    print("[EXECUTION]")
    results: list[AgentResult] = []

    for _, agent_cls in AGENT_REGISTRY.items():
        agent = agent_cls()
        start_iso = datetime.now(timezone.utc).isoformat()
        try:
            result = agent.run(config, storage)
            end_iso = datetime.now(timezone.utc).isoformat()
            storage.log_cycle(
                agent=result.agent,
                started_at=start_iso,
                finished_at=end_iso,
                records_touched=result.records_touched,
                status=result.status,
                notes=result.notes,
                db_path=config.db_path,
            )
            print(f"  * {agent.name:<14} [{result.status.upper()}] -> {result.notes}")
            results.append(result)
        except Exception as exc:
            end_iso = datetime.now(timezone.utc).isoformat()
            storage.log_cycle(
                agent=agent.name,
                started_at=start_iso,
                finished_at=end_iso,
                records_touched=0,
                status="failed",
                notes=str(exc),
                db_path=config.db_path,
            )
            print(f"  ! {agent.name:<14} [FAILED] -> {exc}")
            raise exc

    print("-" * 70)
    print("[CYCLE SUMMARY]")
    print(f"{'Agent':<15} | {'Status':<6} | {'Records':<7} | {'Notes'}")
    print("-" * 70)
    for r in results:
        print(f"{r.agent:<15} | {r.status.upper():<6} | {r.records_touched:<7} | {r.notes}")
    print("=" * 70)
