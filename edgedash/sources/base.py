from abc import ABC, abstractmethod
from typing import Any, TypeVar
from edgedash.config import Config
from edgedash.sources.http import SourceError, get_json

__all__ = ["Source", "SOURCES", "register", "SourceError", "get_json"]


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self, config: Config) -> list[dict[str, Any]]:
        """Fetch listings and return normalised dicts adhering to steering rule 10."""
        pass


SOURCES: dict[str, type[Source]] = {}

T = TypeVar("T", bound=type[Source])


def register(cls: T) -> T:
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"Source class '{cls.__name__}' must define a non-empty 'name' attribute.")
    SOURCES[cls.name] = cls
    return cls
