from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal
from edgedash.config import Config


@dataclass
class AgentResult:
    agent: str
    status: Literal["ok", "failed"]
    records_touched: int
    notes: str


class Agent(ABC):
    name: str

    @abstractmethod
    def run(self, config: Config, storage: Any) -> AgentResult:
        """Execute the agent task and return the resulting status and metrics."""
        pass
