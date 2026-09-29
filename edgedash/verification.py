from dataclasses import dataclass, field
from datetime import datetime, timezone
import statistics
from typing import Any
from edgedash.config import Config


@dataclass
class CheckResult:
    name: str
    passed: bool
    observed: Any
    threshold: Any
    message: str


@dataclass
class Verdict:
    passed: bool
    failed_checks: list[CheckResult]
    summary: str
    results: list[CheckResult] = field(default_factory=list)


def check_score_spread(scores: list[float], config: Config) -> CheckResult:
    """Fails if max-min < min_score_spread (default 10) or stdev < min_score_stdev (default 5)."""
    min_spread = float(getattr(config, "min_score_spread", 10.0))
    min_stdev = float(getattr(config, "min_score_stdev", 5.0))
    thresholds = {"min_score_spread": min_spread, "min_score_stdev": min_stdev}

    if len(scores) < 5:
        return CheckResult(
            "check_score_spread", True, {"count": len(scores)},
            {"min_count": 5}, f"Passed trivially: fewer than 5 scores ({len(scores)} evaluated)",
        )

    spread = float(max(scores) - min(scores))
    stdev = float(statistics.stdev(scores))
    observed = {"count": len(scores), "spread": round(spread, 2), "stdev": round(stdev, 2)}
    fails = [r for r, c in [(f"spread {spread:.1f} < {min_spread}", spread < min_spread),
                            (f"stdev {stdev:.1f} < {min_stdev}", stdev < min_stdev)] if c]
    if fails:
        return CheckResult("check_score_spread", False, observed, thresholds,
                           f"Score spread failed: {', '.join(fails)}")
    return CheckResult("check_score_spread", True, observed, thresholds,
                       f"Score spread passed: spread={spread:.1f}, stdev={stdev:.1f}")


def check_extraction_sanity(facts_list: list[dict[str, Any]], config: Config) -> CheckResult:
    """Fails if > max_empty_extraction_pct empty or any listing > max_skills_per_listing."""
    max_empty_pct = float(getattr(config, "max_empty_extraction_pct", 0.20))
    max_skills = int(getattr(config, "max_skills_per_listing", 20))
    thresholds = {"max_empty_extraction_pct": max_empty_pct, "max_skills_per_listing": max_skills}

    if not facts_list:
        return CheckResult("check_extraction_sanity", True, {"count": 0}, thresholds,
                           "Passed trivially: no extracted facts to inspect")

    empty_count = sum(1 for f in facts_list if not f.get("required_skills"))
    empty_pct = empty_count / len(facts_list)
    max_observed_skills = max(len(f.get("required_skills", [])) for f in facts_list)
    observed = {"count": len(facts_list), "empty_pct": round(empty_pct, 3), "max_skills": max_observed_skills}

    fails = [r for r, c in [(f"empty_pct {empty_pct:.1%} > {max_empty_pct:.1%}", empty_pct > max_empty_pct),
                            (f"max_skills {max_observed_skills} > {max_skills}", max_observed_skills > max_skills)] if c]
    if fails:
        return CheckResult("check_extraction_sanity", False, observed, thresholds,
                           f"Extraction sanity failed: {', '.join(fails)}")
    return CheckResult("check_extraction_sanity", True, observed, thresholds,
                       f"Extraction sanity passed: empty_pct={empty_pct:.1%}, max_skills={max_observed_skills}")


def check_gap_sample_size(gaps: list[dict[str, Any]], config: Config) -> CheckResult:
    """Fails if top-ranked gap was computed from fewer than min_gap_sample (default 3) listings."""
    min_sample = int(getattr(config, "min_gap_sample", 3))
    thresholds = {"min_gap_sample": min_sample}
    if not gaps:
        return CheckResult("check_gap_sample_size", True, {"count": 0}, thresholds,
                           "Passed trivially: no gaps in snapshot")

    top_gap = gaps[0]
    sample = int(top_gap.get("listings_blocked", 0))
    skill = str(top_gap.get("skill", "unknown"))
    observed = {"top_skill": skill, "listings_blocked": sample}
    if sample < min_sample:
        return CheckResult("check_gap_sample_size", False, observed, thresholds,
                           f"Gap sample failed: top gap '{skill}' sample {sample} < {min_sample}")
    return CheckResult("check_gap_sample_size", True, observed, thresholds,
                       f"Gap sample passed: top gap '{skill}' sample {sample} >= {min_sample}")


def check_freshness(latest_fetch_at: datetime | str | None, config: Config, now: datetime) -> CheckResult:
    """Fails if newest listing is older than max_data_age_days (default 3). `now` is a parameter."""
    max_days = float(getattr(config, "max_data_age_days", 3.0))
    thresholds = {"max_data_age_days": max_days}
    if latest_fetch_at is None:
        return CheckResult("check_freshness", False, {"latest_fetch_at": None}, thresholds,
                           "Freshness failed: no fetch timestamp recorded")

    dt = datetime.fromisoformat(latest_fetch_at) if isinstance(latest_fetch_at, str) else latest_fetch_at
    if now.tzinfo is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif now.tzinfo is None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    age_days = (now - dt).total_seconds() / 86400.0
    observed = {"latest_fetch_at": dt.isoformat(), "age_days": round(age_days, 2)}
    if age_days > max_days:
        return CheckResult("check_freshness", False, observed, thresholds,
                           f"Freshness failed: age {age_days:.1f}d > {max_days:.1f}d")
    return CheckResult("check_freshness", True, observed, thresholds,
                       f"Freshness passed: age {age_days:.1f}d <= {max_days:.1f}d")


def run_all_checks(
    *, config: Config, now: datetime,
    scores: list[float] | None = None,
    facts_list: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
    latest_fetch_at: datetime | str | None = None,
) -> Verdict:
    """Runs every check, collects results, passes only if all pass."""
    results = [
        check_score_spread(scores if scores is not None else [], config),
        check_extraction_sanity(facts_list if facts_list is not None else [], config),
        check_gap_sample_size(gaps if gaps is not None else [], config),
        check_freshness(latest_fetch_at, config, now),
    ]
    failed = [r for r in results if not r.passed]
    passed = len(failed) == 0
    names = ", ".join(r.name for r in failed) if failed else "all"
    summary = f"All {len(results)} checks passed." if passed else f"Verification failed: {len(failed)}/{len(results)} failed ({names})."
    return Verdict(passed=passed, failed_checks=failed, summary=summary, results=results)
