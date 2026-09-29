from datetime import datetime, timezone
from typing import Any
from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config
import edgedash.storage as storage
from edgedash.verification import run_all_checks, Verdict


class Verifier(Agent):
    name: str = "verifier"

    def run(
        self,
        config: Config,
        storage_module: Any = storage,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Reads scores, facts, gaps, and fetch time; runs checks. Writes NO data (Rule 34)."""
        store = storage_module or storage
        now = (context.get("now") if context and "now" in context else None) or datetime.now(timezone.utc)

        # 1. Read cycle data via storage module only (Rule 2)
        scored_listings = store.get_scored_listings_with_facts(db_path=config.db_path)
        scores = [float(l["score"]) for l in scored_listings if "score" in l and l["score"] is not None]
        facts_list = [l["facts"] for l in scored_listings if "facts" in l and l["facts"]]
        gaps = store.get_latest_skill_gaps(limit=50, db_path=config.db_path)
        latest_fetch = store.last_fetch_time(db_path=config.db_path)

        # 2. Run deterministic verification checks
        verdict: Verdict = run_all_checks(
            config=config,
            now=now,
            scores=scores,
            facts_list=facts_list,
            gaps=gaps,
            latest_fetch_at=latest_fetch,
        )

        status = "ok" if verdict.passed else "failed"
        if verdict.passed:
            notes = "VERDICT: pass — all checks passed"
        else:
            first = verdict.failed_checks[0]
            notes = f"VERDICT: fail — {first.name} {first.message}"

        result = AgentResult(
            agent=self.name,
            status=status,
            records_touched=len(scores),
            notes=notes,
        )
        result.verdict = verdict  # type: ignore[attr-defined]
        return result
