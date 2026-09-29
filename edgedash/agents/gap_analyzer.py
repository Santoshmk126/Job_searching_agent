from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
import uuid

from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config
from edgedash.skills import canonical
import edgedash.storage as storage


def compute_skill_gaps(
    scored_listings: list[dict[str, Any]],
    my_skills: list[str],
    skill_aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic skill gap calculation (Rules 22, 23, 24, 26, 27).

    Returns a list of gap dictionaries sorted by opportunity_cost descending.
    """
    user_skills = set(
        canonical(s, skill_aliases) for s in my_skills if canonical(s, skill_aliases)
    )

    blocked_by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
    nice_counts: dict[str, int] = defaultdict(int)

    for item in scored_listings:
        lid = item["id"]
        score = int(item["score"])
        facts = item.get("facts") or {}

        # 1. Required skills (contribute to opportunity cost & listings blocked)
        raw_req = facts.get("required_skills") or []
        req_canon = list(dict.fromkeys(
            canonical(s, skill_aliases) for s in raw_req if canonical(s, skill_aliases)
        ))
        for skill in req_canon:
            if skill not in user_skills:
                blocked_by_skill[skill].append({"id": lid, "score": score})

        # 2. Nice to have skills (tracked separately per rule 24)
        raw_nice = facts.get("nice_to_have") or []
        nice_canon = list(dict.fromkeys(
            canonical(s, skill_aliases) for s in raw_nice if canonical(s, skill_aliases)
        ))
        for skill in nice_canon:
            if skill not in user_skills:
                nice_counts[skill] += 1

    gaps: list[dict[str, Any]] = []
    for skill, listings in blocked_by_skill.items():
        n_blocked = len(listings)
        if n_blocked == 0:
            continue

        # Rule 24: opportunity_cost = sum of (listing.score / 100)
        opp_cost = round(sum(l["score"] / 100.0 for l in listings), 2)
        mean_score = round(sum(l["score"] for l in listings) / n_blocked, 1)
        top_score = max(l["score"] for l in listings)

        # Rule 26: up to 5 listing IDs, highest score first
        sorted_listings = sorted(listings, key=lambda x: x["score"], reverse=True)
        example_ids = [l["id"] for l in sorted_listings[:5]]

        # Rule 27: low confidence flag if fewer than 3 listings
        low_conf = n_blocked < 3

        gaps.append({
            "skill": skill,
            "listings_blocked": n_blocked,
            "opportunity_cost": opp_cost,
            "mean_score": mean_score,
            "top_score": top_score,
            "example_ids": example_ids,
            "also_nice_to_have": nice_counts.get(skill, 0),
            "low_confidence": low_conf,
        })

    # Rank by opportunity_cost descending (Rule 24), then listings_blocked descending
    gaps.sort(key=lambda x: (x["opportunity_cost"], x["listings_blocked"]), reverse=True)
    return gaps


class GapAnalyzer(Agent):
    name = "gap_analyzer"

    def run(
        self,
        config: Config,
        storage_module: Any = storage,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        scored = storage_module.get_scored_listings_with_facts(db_path=config.db_path)
        if not scored:
            return AgentResult(
                agent=self.name,
                records_touched=0,
                status="passed",
                notes="0 scored listings to analyse",
            )

        gaps = compute_skill_gaps(
            scored_listings=scored,
            my_skills=getattr(config, "my_skills", []),
            skill_aliases=getattr(config, "skill_aliases", None),
        )

        top_10 = gaps[:10]
        run_id = f"gap_run_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Rule 25: write timestamped snapshot (never overwrite)
        storage_module.save_skill_gaps_snapshot(
            run_id=run_id,
            computed_at=now_iso,
            gaps=top_10,
            db_path=config.db_path,
        )

        top_summary = "none"
        if top_10:
            top_g = top_10[0]
            top_summary = f"{top_g['skill']} ({top_g['listings_blocked']} listings, cost {top_g['opportunity_cost']})"

        notes = f"{len(top_10)} gaps · top: {top_summary} · {len(scored)} listings analysed"

        return AgentResult(
            agent=self.name,
            records_touched=len(top_10),
            status="passed",
            notes=notes,
        )
