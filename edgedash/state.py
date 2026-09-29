from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from edgedash.config import Config
import edgedash.storage as storage


@dataclass
class SystemState:
    last_fetch_at: str | None
    hours_since_fetch: float | None
    unscored_count: int
    gaps_computed_at: str | None
    gaps_stale: bool
    last_cycle_verdict: str | None
    last_cycle_at: str | None


def _parse_timestamp(ts: str) -> datetime:
    clean_ts = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def read_state(config: Config, now: datetime) -> SystemState:
    """Read current system state using cheap aggregate queries through storage (Rule 2).
    
     is an explicit parameter for deterministic testing.
    """
    db_path = config.db_path
    last_fetch_at = storage.last_fetch_time(db_path)
    hours_since_fetch: float | None = None
    if last_fetch_at is not None:
        try:
            fetch_dt = _parse_timestamp(last_fetch_at)
            now_aware = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
            diff_hours = (now_aware - fetch_dt).total_seconds() / 3600.0
            hours_since_fetch = round(max(0.0, diff_hours), 2)
        except Exception:
            hours_since_fetch = None

    unscored_count = storage.count_unscored(db_path)
    gaps_computed_at = storage.latest_gap_snapshot_time(db_path)

    gaps_stale = False
    if gaps_computed_at is not None:
        gaps_stale = storage.has_scores_newer_than(gaps_computed_at, db_path)

    last_verdict, last_cycle_at = storage.last_cycle_info(db_path)

    return SystemState(
        last_fetch_at=last_fetch_at,
        hours_since_fetch=hours_since_fetch,
        unscored_count=unscored_count,
        gaps_computed_at=gaps_computed_at,
        gaps_stale=gaps_stale,
        last_cycle_verdict=last_verdict,
        last_cycle_at=last_cycle_at,
    )


def explain_state(state: SystemState, config: Config) -> str:
    """Format a full explanatory table detailing every state value and driven decision."""
    interval = getattr(config, "fetch_interval_hours", 6.0)
    lines = [
        "=" * 75,
        "                    EDGEDASH SYSTEM STATE & EXPLANATION",
        "=" * 75,
        f"  {'State Field':<20} | {'Current Value':<24} | {'Decision Driven'}",
        "-" * 75,
    ]

    # 1. Fetcher
    if state.hours_since_fetch is None:
        fetch_decision = "fetcher: never fetched -> RUN"
        hours_str = "None (initial)"
    elif state.hours_since_fetch >= interval:
        fetch_decision = f"fetcher: {state.hours_since_fetch}h >= {interval}h -> RUN"
        hours_str = f"{state.hours_since_fetch} hrs"
    else:
        fetch_decision = f"fetcher: {state.hours_since_fetch}h < {interval}h -> SKIP"
        hours_str = f"{state.hours_since_fetch} hrs"

    lines.append(f"  {'last_fetch_at':<20} | {str(state.last_fetch_at):<24} | {fetch_decision}")
    lines.append(f"  {'hours_since_fetch':<20} | {hours_str:<24} | threshold = {interval} hrs")

    # 2. Scorer
    if state.unscored_count > 0:
        score_decision = f"scorer: {state.unscored_count} unscored (> 0) -> RUN"
    else:
        score_decision = "scorer: 0 unscored -> SKIP"
    lines.append(f"  {'unscored_count':<20} | {str(state.unscored_count):<24} | {score_decision}")

    # 3. Gap Analyzer
    if state.gaps_computed_at is None:
        gap_decision = "gap_analyzer: snapshot missing -> RUN"
    elif state.gaps_stale:
        gap_decision = "gap_analyzer: scores newer than snapshot -> RUN"
    else:
        gap_decision = "gap_analyzer: no new scores since snapshot -> SKIP"

    lines.append(f"  {'gaps_computed_at':<20} | {str(state.gaps_computed_at):<24} | baseline snapshot timestamp")
    lines.append(f"  {'gaps_stale':<20} | {str(state.gaps_stale):<24} | {gap_decision}")

    # 4. Cycle verdict
    lines.append(f"  {'last_cycle_verdict':<20} | {str(state.last_cycle_verdict):<24} | previous cycle outcome")
    lines.append(f"  {'last_cycle_at':<20} | {str(state.last_cycle_at):<24} | previous cycle finished timestamp")
    lines.append("=" * 75)
    return "\n".join(lines)
