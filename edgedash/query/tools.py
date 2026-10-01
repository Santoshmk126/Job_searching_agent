from typing import Any, Callable
import functools

from edgedash.config import Config, load_config
from edgedash.skills import canonical, DEFAULT_ALIASES
import edgedash.storage as storage

TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, description: str, parameters: dict[str, Any]) -> Callable[..., Any]:
    """Register a tool with its JSON-schema spec in the TOOLS registry."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        spec = {
            "name": name,
            "description": description.strip(),
            "parameters": parameters,
            "func": func,
        }
        TOOLS[name] = spec

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        wrapper.tool_spec = spec  # type: ignore[attr-defined]
        return wrapper

    return decorator


def clamp_int(val: Any, min_val: int, max_val: int, default: int) -> int:
    """Validate and clamp model-supplied integers to safe ranges (Rule 41)."""
    try:
        v = int(val)
        return max(min_val, min(max_val, v))
    except (ValueError, TypeError):
        return default


def _validate_and_canonicalize_skill(skill_raw: Any, config: Config) -> str | None:
    """Validate and canonicalize skill against database presence (Rule 41)."""
    if not skill_raw or not isinstance(skill_raw, str):
        return None
    alias_map = getattr(config, "skill_aliases", None) or DEFAULT_ALIASES
    canon = canonical(skill_raw, alias_map).strip().lower()
    if not canon:
        return None

    # Verify skill is actually present in database
    known = storage.get_known_skills(config.db_path)
    if canon in known:
        return canon
    for k in known:
        if canon in k or k in canon:
            return k
    return None


def _get_verified_as_of(db_path: str) -> str | None:
    """Get cutoff timestamp of the latest verified passing cycle (Rule 46)."""
    cycle = storage.get_latest_passing_cycle(db_path=db_path)
    return cycle.get("finished_at") if cycle else None


@tool(
    name="companies_hiring",
    description="Companies with listings posted in the last N days, with counts. Use when asked about hiring companies or active employers.",
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of days in the past to inspect for job postings (clamped 1-90, default 7).",
                "default": 7,
            }
        },
        "required": [],
    },
)
def companies_hiring(days: int = 7, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    safe_days = clamp_int(days, 1, 90, 7)
    as_of = _get_verified_as_of(cfg.db_path)
    rows, total_examined = storage.get_companies_hiring(days=safe_days, as_of=as_of, db_path=cfg.db_path)
    summary = f"{len(rows)} companies across {total_examined} listings from the last {safe_days} days"
    return {"summary": summary, "rows": rows}


@tool(
    name="best_matches",
    description="Highest-scoring listings with score, title, company, reason. Use when asked for best matching jobs or top recommendations.",
    parameters={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of top matching listings to return (clamped 1-25, default 10).",
                "default": 10,
            }
        },
        "required": [],
    },
)
def best_matches(n: int = 10, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    safe_n = clamp_int(n, 1, 25, 10)
    as_of = _get_verified_as_of(cfg.db_path)
    rows, total_scored = storage.get_best_matches(n=safe_n, as_of=as_of, db_path=cfg.db_path)
    summary = f"Top {len(rows)} highest-scoring job listings evaluated out of {total_scored} scored listings"
    return {"summary": summary, "rows": rows}


@tool(
    name="top_gaps",
    description="Top skill gaps by opportunity cost, with listings_blocked. Use when asked about missing skills or what skills to learn next.",
    parameters={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of top skill gaps to return (clamped 1-25, default 5).",
                "default": 5,
            }
        },
        "required": [],
    },
)
def top_gaps(n: int = 5, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    safe_n = clamp_int(n, 1, 25, 5)
    as_of = _get_verified_as_of(cfg.db_path)
    rows, total = storage.get_top_gaps(n=safe_n, as_of=as_of, db_path=cfg.db_path)
    summary = f"Top {len(rows)} skill gaps ranked by opportunity cost"
    return {"summary": summary, "rows": rows}


@tool(
    name="gap_detail",
    description="The listings blocked by one named skill — rule 26 drill-down. Use when asked which specific jobs require a named skill.",
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Specific skill name to inspect (e.g. 'docker', 'kubernetes').",
            }
        },
        "required": ["skill"],
    },
)
def gap_detail(skill: str, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    canon_skill = _validate_and_canonicalize_skill(skill, cfg)
    if not canon_skill:
        return {"summary": f"Skill '{skill}' not found in job data", "rows": []}

    as_of = _get_verified_as_of(cfg.db_path)
    rows, total_examined = storage.get_gap_detail(skill=canon_skill, as_of=as_of, db_path=cfg.db_path)
    summary = f"{len(rows)} listings blocked by missing skill '{canon_skill}' across {total_examined} scored listings"
    return {"summary": summary, "rows": rows}


@tool(
    name="trend",
    description="Gap opportunity_cost change over N weeks from the snapshots. Use when asked about skill trends over time.",
    parameters={
        "type": "object",
        "properties": {
            "weeks": {
                "type": "integer",
                "description": "Number of weeks of historical snapshots to examine (clamped 1-12, default 3).",
                "default": 3,
            }
        },
        "required": [],
    },
)
def trend(weeks: int = 3, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    safe_weeks = clamp_int(weeks, 1, 12, 3)
    as_of = _get_verified_as_of(cfg.db_path)
    rows, num_snapshots = storage.get_trend(weeks=safe_weeks, as_of=as_of, db_path=cfg.db_path)
    summary = f"Skill gap opportunity cost changes across {num_snapshots} snapshots over the past {safe_weeks} weeks"
    return {"summary": summary, "rows": rows}


@tool(
    name="listing_count",
    description="Totals: listings, scored, unscored, newest listing date. Use when asked how many jobs are in the system or data freshness.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def listing_count(config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    as_of = _get_verified_as_of(cfg.db_path)
    stats = storage.get_listing_count_stats(as_of=as_of, db_path=cfg.db_path)
    summary = f"Total listings: {stats['total_listings']} ({stats['scored_listings']} scored, {stats['unscored_listings']} unscored)"
    return {"summary": summary, "rows": [stats]}


@tool(
    name="skill_demand",
    description="How often one skill appears in required vs nice_to_have. Use when asked about the demand or frequency of a single skill.",
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Specific skill name to evaluate demand for.",
            }
        },
        "required": ["skill"],
    },
)
def skill_demand(skill: str, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    canon_skill = _validate_and_canonicalize_skill(skill, cfg)
    if not canon_skill:
        return {"summary": f"Skill '{skill}' not found in job data", "rows": []}

    as_of = _get_verified_as_of(cfg.db_path)
    stats, total_examined = storage.get_skill_demand(skill=canon_skill, as_of=as_of, db_path=cfg.db_path)
    summary = f"Demand for '{canon_skill}': {stats['required_count']} required, {stats['nice_to_have_count']} nice-to-have out of {total_examined} listings"
    return {"summary": summary, "rows": [stats]}


@tool(
    name="location_breakdown",
    description="Breakdown of job listings by city or remote location, with counts and average fit score. Use when asked where jobs are located, which cities have the most openings, or remote vs on-site distribution.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of top locations to return (clamped 1-25, default 10).",
                "default": 10,
            }
        },
        "required": [],
    },
)
def location_breakdown(limit: int = 10, config: Config | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    safe_limit = clamp_int(limit, 1, 25, 10)
    as_of = _get_verified_as_of(cfg.db_path)
    rows, total_examined = storage.get_location_breakdown(limit=safe_limit, as_of=as_of, db_path=cfg.db_path)
    summary = f"Top {len(rows)} job locations across {total_examined} listings"
    return {"summary": summary, "rows": rows}
