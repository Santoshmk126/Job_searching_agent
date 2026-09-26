from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml


@dataclass
class Config:
    target_role: str
    target_city: str
    keywords: list[str]
    my_skills: list[str]
    experience_years: int
    db_path: str
    min_fit_score: int


def load_config(path: str | Path = "config.yaml") -> Config:
    config_file = Path(path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Configuration file not found: '{config_file.resolve()}'. "
            "Please ensure config.yaml exists at the project root."
        )

    with config_file.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return Config(
        target_role=str(data.get("target_role", "Data Analyst")),
        target_city=str(data.get("target_city", "Bengaluru")),
        keywords=list(data.get("keywords", [])),
        my_skills=list(data.get("my_skills", [])),
        experience_years=int(data.get("experience_years", 0)),
        db_path=str(data.get("db_path", "edgedash.db")),
        min_fit_score=int(data.get("min_fit_score", 70)),
    )
