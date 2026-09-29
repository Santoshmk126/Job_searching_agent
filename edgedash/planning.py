from dataclasses import dataclass, field
from typing import Any
from edgedash.config import Config
from edgedash.state import SystemState


class AgentName(str):
    """String subclass representing an agent name that flexibly matches aliases."""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (str, AgentName)):
            return False
        s_self, s_other = str(self).lower(), str(other).lower()
        if s_self == s_other:
            return True
        aliases = {
            "fetch": "fetcher",
            "fetcher": "fetch",
            "score": "scorer",
            "scorer": "score",
            "analyse": "gap_analyzer",
            "analyze": "gap_analyzer",
            "gap_analyzer": "analyse",
        }
        return aliases.get(s_self) == s_other or aliases.get(s_other) == s_self

    def __hash__(self) -> int:
        return hash(str(self))


@dataclass
class Task:
    agent_name: AgentName | str
    goal: str
    stop_conditions: dict[str, Any]
    reason: str
    skipped: bool = False


@dataclass
class Plan:
    tasks: list[Task] = field(default_factory=list)

    def __iter__(self):
        return iter(self.tasks)

    def __len__(self) -> int:
        return len(self.tasks)

    def __getitem__(self, index: int) -> Task:
        return self.tasks[index]

    def render(self) -> str:
        lines = []
        for t in self.tasks:
            status = "[SKIP]" if t.skipped else "[RUN]"
            stop_str = ", ".join(f"{k}={v}" for k, v in t.stop_conditions.items())
            lines.append(
                f"{str(t.agent_name):<12} {status} Goal: {t.goal} | Stop: {stop_str} | Reason: {t.reason}"
            )
        return "\n".join(lines)


def build_plan(state: SystemState, config: Config) -> Plan:
    tasks: list[Task] = []
    fetch_interval = getattr(config, "fetch_interval_hours", 6.0)

    # 1. Fetcher decision
    fetch_stop = {
        "max_pages": getattr(config, "fetch_max_pages", 5),
        "max_listings": getattr(config, "fetch_max_listings", 50),
    }
    fetch_goal = "Fetch latest job listings and deduplicate against storage"
    if state.hours_since_fetch is None:
        fetch_run = True
        fetch_reason = "hours_since_fetch=None"
    elif state.hours_since_fetch >= fetch_interval:
        fetch_run = True
        fetch_reason = f"hours_since_fetch={state.hours_since_fetch}"
    else:
        fetch_run = False
        fetch_reason = f"skipped: hours_since_fetch={state.hours_since_fetch}"

    tasks.append(
        Task(
            agent_name=AgentName("fetcher"),
            goal=fetch_goal,
            stop_conditions=fetch_stop,
            reason=fetch_reason,
            skipped=not fetch_run,
        )
    )

    # 2. Scorer decision
    score_stop = {
        "max_items": getattr(config, "score_batch_size", 25),
        "max_seconds": getattr(config, "score_max_seconds", 60),
    }
    score_goal = "Score unscored job listings against candidate profile"
    if state.unscored_count > 0:
        score_run = True
        score_reason = f"unscored_count={state.unscored_count}"
    else:
        score_run = False
        score_reason = "skipped: unscored_count=0"

    tasks.append(
        Task(
            agent_name=AgentName("scorer"),
            goal=score_goal,
            stop_conditions=score_stop,
            reason=score_reason,
            skipped=not score_run,
        )
    )

    # 3. Gap Analyzer decision
    analyse_stop = {
        "max_seconds": getattr(config, "analyse_max_seconds", 30),
    }
    analyse_goal = "Compute market skill gaps and opportunity cost snapshot"
    if state.gaps_computed_at is None:
        analyse_run = True
        analyse_reason = "gaps_computed_at=None"
    elif state.gaps_stale:
        analyse_run = True
        analyse_reason = "gaps_stale=True"
    else:
        analyse_run = False
        analyse_reason = "skipped: gaps_stale=False"

    tasks.append(
        Task(
            agent_name=AgentName("gap_analyzer"),
            goal=analyse_goal,
            stop_conditions=analyse_stop,
            reason=analyse_reason,
            skipped=not analyse_run,
        )
    )

    return Plan(tasks=tasks)
