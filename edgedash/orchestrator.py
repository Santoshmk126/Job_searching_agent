from datetime import datetime, timezone
import json
import time
from typing import Any
from edgedash.agents.base import Agent, AgentResult
from edgedash.agents.fetcher import Fetcher
from edgedash.agents.scorer import Scorer
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.agents.mock_fetcher import MockFetcher
from edgedash.agents.verifier import Verifier
from edgedash.config import Config
from edgedash.planning import build_plan, Plan
from edgedash.state import read_state, explain_state
import edgedash.storage as storage

AGENT_REGISTRY: dict[str, type[Agent]] = {
    "fetcher": Fetcher, "scorer": Scorer, "gap_analyzer": GapAnalyzer, "verifier": Verifier,
    "fetch": Fetcher, "score": Scorer, "analyse": GapAnalyzer, "verify": Verifier,
}
FAIL_MAP = {"check_score_spread": "scorer", "check_extraction_sanity": "scorer",
            "check_gap_sample_size": "gap_analyzer", "check_freshness": "fetcher"}


def run_cycle(config: Config, now: datetime | None = None, dry_run: bool = False,
              force_agents: list[str] | None = None, explain: bool = False) -> str:
    """State-driven autonomous orchestrator cycle with verification (Rules 28-39)."""
    start_iso = datetime.now(timezone.utc).isoformat()
    storage.init_db(config.db_path)
    eval_now = now or datetime.now(timezone.utc)

    state = read_state(config, eval_now)
    if explain:
        print(explain_state(state, config))
    plan: Plan = build_plan(state, config)

    overrides = []
    if force_agents:
        for f in force_agents:
            fc = f.strip().lower()
            for t in plan:
                if t.agent_name == fc and t.skipped:
                    t.skipped, t.reason = False, "forced by operator"
                    overrides.append(str(t.agent_name))
        if overrides:
            print("=" * 70 + f"\n⚠️  WARNING: Manual override active. Forced: {', '.join(overrides)}")

    print("=" * 70 + "\n                      EDGEDASH ORCHESTRATOR PLAN\n" + "=" * 70)
    print(plan.render() + "\n" + "-" * 70)
    if dry_run:
        print("[DRY-RUN] Execution halted. No agents executed.\n" + "=" * 70)
        return "dry_run"

    active_reg = dict(AGENT_REGISTRY)
    if config.use_mock_fetcher:
        active_reg["fetcher"] = active_reg["fetch"] = MockFetcher

    has_fail, durations, ran_results, total_recs = False, {}, [], 0
    for task in plan:
        if task.skipped:
            continue
        akey = str(task.agent_name)
        cls_ = active_reg.get(akey)
        if not cls_:
            has_fail = True
            continue
        t0 = time.time()
        try:
            res = cls_().run(config, storage, goal=task.goal, stop_conditions=task.stop_conditions)
            durations[akey] = round(time.time() - t0, 3)
            ran_results.append(res)
            total_recs += res.records_touched
            if res.status == "failed":
                has_fail = True
            print(f" * {akey:<14} [{res.status.upper()}] ({durations[akey]:.2f}s) -> {res.notes}")
        except Exception as exc:
            durations[akey] = round(time.time() - t0, 3)
            has_fail = True
            print(f" ! {akey:<14} [FAILED] ({durations[akey]:.2f}s) -> {exc}")

    if all(t.skipped for t in plan):
        outcome = "nothing_to_do"
        verdict_dict = {"status": "pass", "passed": True, "failed_checks": [], "retry_count": 0}
    else:
        # Run Verifier after scorer and gap analyzer (Rule 34-36)
        verifier = active_reg.get("verifier", Verifier)()
        t0 = time.time()
        vres = verifier.run(config, storage, context={"now": eval_now})
        durations["verifier"] = round(time.time() - t0, 3)
        ran_results.append(vres)
        print(f" * verifier       [{vres.status.upper()}] ({durations['verifier']:.2f}s) -> {vres.notes}")

        retries, v_obj = 0, getattr(vres, "verdict", None)
        failed_checks = getattr(v_obj, "failed_checks", []) if v_obj else []

        if vres.status == "failed" and failed_checks:
            retries = 1
            target = FAIL_MAP.get(failed_checks[0].name, "scorer")
            print(f"⚠️  Verification failed ({vres.notes}). Retrying '{target}' with adjusted context...")
            if target in active_reg:
                rstops = {"stricter": True, "max_seconds": getattr(config, "score_max_seconds", 60)}
                t_r = time.time()
                r_res = active_reg[target]().run(config, storage, goal="Retry strictly", stop_conditions=rstops)
                durations[f"{target}_retry"] = round(time.time() - t_r, 3)
                print(f" * {target:<14} [RETRY] -> {r_res.notes}")

            t_v2 = time.time()
            vres2 = verifier.run(config, storage, context={"now": eval_now})
            durations["verifier_retry"] = round(time.time() - t_v2, 3)
            ran_results.append(vres2)
            print(f" * verifier       [{vres2.status.upper()}] (post-retry) -> {vres2.notes}")
            v_obj2 = getattr(vres2, "verdict", None)
            failed_checks = getattr(v_obj2, "failed_checks", []) if v_obj2 else []
            final_v_passed = (vres2.status != "failed")
        else:
            final_v_passed = (vres.status != "failed")

        if not final_v_passed:
            outcome = "degraded"
            storage.rollback_unverified_cycle(start_iso, db_path=config.db_path)
        else:
            outcome = "partial" if has_fail else "complete" 
        verdict_dict = {
            "status": "pass" if final_v_passed else "fail", "passed": final_v_passed,
            "failed_checks": [{"name": c.name, "observed": c.observed, "threshold": c.threshold, "message": c.message} for c in failed_checks],
            "retry_count": retries,
        }

    summary = {
        "plan": plan.render(), "ran": list(dict.fromkeys(r.agent for r in ran_results)),
        "skipped": {str(t.agent_name): t.reason for t in plan if t.skipped},
        "durations": durations, "outcome": outcome, "overrides": overrides, "verdict": verdict_dict,
    }
    storage.log_cycle(agent="orchestrator", started_at=start_iso, finished_at=datetime.now(timezone.utc).isoformat(),
                      records_touched=total_recs, status=outcome, notes=json.dumps(summary), db_path=config.db_path)
    print("-" * 70 + f"\nCYCLE OUTCOME: {outcome.upper()} | Records Touched: {total_recs}\n" + "=" * 70)
    return outcome
