from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal
from edgedash.config import Config


@dataclass
class AgentResult:
    agent: str
    status: Literal["ok", "failed", "suspect", "passed"]
    records_touched: int
    notes: str


class Agent(ABC):
    name: str

    @abstractmethod
    def run(
        self,
        config: Config,
        storage: Any,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute the agent task respecting assigned goal and stop conditions."""
        pass
