from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
import yaml

# Central environment loading (Rule 4)
load_dotenv()


@dataclass
class Config:
    target_role: str
    target_city: str
    keywords: list[str]
    my_skills: list[str]
    experience_years: int
    db_path: str
    min_fit_score: int
    sources: list[str] = field(default_factory=lambda: ["arbeitnow"])
    use_mock_fetcher: bool = False
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.1-flash-lite"
    target_seniority: str = "junior"
    score_batch_size: int = 25
    scoring_weights: dict[str, float] = field(default_factory=lambda: {
        "skill_match": 0.45,
        "seniority_fit": 0.25,
        "location_fit": 0.15,
        "recency": 0.15,
    })
    skill_aliases: dict[str, str] = field(default_factory=dict)
    fetch_interval_hours: float = 6.0
    fetch_max_pages: int = 5
    fetch_max_listings: int = 50
    score_max_seconds: int = 60
    analyse_max_seconds: int = 30


def load_config(path: str | Path = "config.yaml") -> Config:
    config_file = Path(path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Configuration file not found: '{config_file.resolve()}'. "
            "Please ensure config.yaml exists at the project root."
        )

    # Ensure .env is refreshed relative to config if present
    load_dotenv(dotenv_path=config_file.parent / ".env")

    with config_file.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    raw_sources = data.get("sources")
    sources = list(raw_sources) if raw_sources is not None else ["arbeitnow"]
    use_mock_fetcher = bool(data.get("use_mock_fetcher", False))

    return Config(
        target_role=str(data.get("target_role", "Data Analyst")),
        target_city=str(data.get("target_city", "Bengaluru")),
        keywords=list(data.get("keywords", [])),
        my_skills=list(data.get("my_skills", [])),
        experience_years=int(data.get("experience_years", 0)),
        db_path=str(data.get("db_path", "edgedash.db")),
        min_fit_score=int(data.get("min_fit_score", 70)),
        sources=sources,
        use_mock_fetcher=use_mock_fetcher,
        llm_provider=str(data.get("llm_provider", "gemini")),
        llm_model=str(data.get("llm_model", "gemini-3.1-flash-lite")),
        target_seniority=str(data.get("target_seniority", "junior")),
        score_batch_size=int(data.get("score_batch_size", 25)),
        scoring_weights=dict(data.get("scoring_weights", {
            "skill_match": 0.45,
            "seniority_fit": 0.25,
            "location_fit": 0.15,
            "recency": 0.15,
        })),
        skill_aliases=dict(data.get("skill_aliases", {})),
        fetch_interval_hours=float(data.get("fetch_interval_hours", 6.0)),
        fetch_max_pages=int(data.get("fetch_max_pages", 5)),
        fetch_max_listings=int(data.get("fetch_max_listings", 50)),
        score_max_seconds=int(data.get("score_max_seconds", 60)),
        analyse_max_seconds=int(data.get("analyse_max_seconds", 30)),
    )
