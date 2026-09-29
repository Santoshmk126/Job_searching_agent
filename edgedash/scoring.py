from datetime import datetime, timezone
from typing import Any
from edgedash.skills import canonical

SENIORITY_BANDS: list[str] = ["junior", "mid", "senior", "lead"]
DEFAULT_WEIGHTS: dict[str, float] = {
    "skill_match": 0.45, "seniority_fit": 0.25, "location_fit": 0.15, "recency": 0.15
}


def _calculate_skill_match(facts: dict[str, Any], config: Any) -> tuple[float, str, list[str]]:
    raw_req, raw_nice = facts.get("required_skills", []), facts.get("nice_to_have", [])
    aliases = getattr(config, "skill_aliases", {}) or {}
    req_skills = list(dict.fromkeys(canonical(s, aliases) for s in raw_req if canonical(s, aliases)))
    nice_skills = list(dict.fromkeys(canonical(s, aliases) for s in raw_nice if canonical(s, aliases)))
    user_skills = set(canonical(s, aliases) for s in getattr(config, "my_skills", []) if canonical(s, aliases))

    matched_req = [s for s in req_skills if s in user_skills]
    missing_req = [s for s in req_skills if s not in user_skills]
    matched_nice = [s for s in nice_skills if s in user_skills]

    n_req, n_nice = len(req_skills), len(nice_skills)
    if n_req == 0 and n_nice == 0:
        score, desc = 0.5, "no skills listed"
    elif n_req == 0:
        score, desc = len(matched_nice) / n_nice, f"{len(matched_nice)}/{n_nice} preferred skills"
    elif n_nice == 0:
        score, desc = len(matched_req) / n_req, f"{len(matched_req)}/{n_req} required skills"
    else:
        denom = n_req + (1.0 / 3.0) * n_nice
        score = (len(matched_req) + (1.0 / 3.0) * len(matched_nice)) / denom if denom > 0 else 0.5
        desc = f"{len(matched_req)}/{n_req} required skills"

    return round(max(0.0, min(1.0, score)), 4), desc, missing_req


def _calculate_seniority_fit(facts: dict[str, Any], config: Any) -> tuple[float, str]:
    target = (getattr(config, "target_seniority", "junior") or "junior").strip().lower()
    fact_sen = (facts.get("seniority") or "unknown").strip().lower()
    if fact_sen not in SENIORITY_BANDS or target not in SENIORITY_BANDS:
        return 0.5, "seniority unstated" if fact_sen == "unknown" else f"seniority {fact_sen}"
    dist = abs(SENIORITY_BANDS.index(fact_sen) - SENIORITY_BANDS.index(target))
    mapping = {0: (1.0, "seniority fits"), 1: (0.6, f"seniority 1 band off ({fact_sen})"), 2: (0.25, f"seniority 2 bands off ({fact_sen})")}
    return mapping.get(dist, (0.0, f"seniority gap ({fact_sen})"))


def _calculate_location_fit(listing: dict[str, Any], facts: dict[str, Any], config: Any) -> tuple[float, str]:
    remote_ok, loc_raw = facts.get("remote_ok"), (listing.get("location") or "").strip().lower()
    target_city = (getattr(config, "target_city", "") or "").strip().lower()
    if remote_ok is True or "remote" in loc_raw:
        return 1.0, "remote"
    if target_city and target_city in loc_raw:
        return 1.0, f"in {config.target_city}"
    if remote_ok is None and not loc_raw:
        return 0.5, "location unstated"
    if remote_ok is False or (loc_raw and target_city and target_city not in loc_raw):
        return 0.1, f"located in {listing.get('location') or 'on-site'}"
    return 0.5, "location unstated"


def _calculate_recency(posted_at: str | None, as_of: Any = None) -> tuple[float, str]:
    if not posted_at:
        return 0.5, "posted date unknown"
    try:
        dt = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")) if as_of else datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        days = max(0, (ref.date() - dt.date()).days)
        return round(max(0.0, 1.0 - (days / 30.0)), 4), "posted today" if days == 0 else f"posted {days}d ago"
    except Exception:
        return 0.5, "posted date unknown"


def build_reason(
    components: dict[str, float], facts: dict[str, Any] | None = None,
    config: Any = None, listing: dict[str, Any] | None = None, missing_skills: list[str] | None = None,
) -> str:
    """Assemble deterministic human-readable reason strictly from component values (Rule 19)."""
    ld, fd = listing or {}, facts or {}
    if fd and config:
        _, skill_desc, missing = _calculate_skill_match(fd, config)
    else:
        skill_desc, missing = f"{int(round(components.get('skill_match', 0.0) * 100))}% skill match", []

    sen_score, sen_val = components.get("seniority_fit", 0.5), (fd.get("seniority") or "").strip().lower()
    sen_map = {1.0: "seniority fits", 0.6: f"seniority 1 band off ({sen_val})" if sen_val else "seniority 1 band off",
               0.25: f"seniority 2 bands off ({sen_val})" if sen_val else "seniority 2 bands off",
               0.0: f"seniority gap ({sen_val})" if sen_val else "seniority gap", 0.5: "seniority unstated"}
    sen_desc = sen_map.get(sen_score, f"seniority fit {sen_score}")

    loc_score, loc_raw = components.get("location_fit", 0.5), ld.get("location")
    if loc_score == 1.0:
        loc_desc = "remote" if (fd.get("remote_ok") or "remote" in (loc_raw or "").lower()) else f"in {getattr(config, 'target_city', '')}"
    elif loc_score == 0.1:
        loc_desc = f"located in {loc_raw or 'on-site'}"
    else:
        loc_desc = "location unstated"

    rec_score, posted_at = components.get("recency", 0.5), ld.get("posted_at")
    if not posted_at or (rec_score == 0.5 and not posted_at):
        rec_desc = "posted date unknown"
    else:
        days = max(0, int(round((1.0 - rec_score) * 30.0)))
        rec_desc = "posted today" if days == 0 else f"posted {days}d ago"

    gaps = missing_skills if missing_skills is not None else missing
    return f"{skill_desc} · {sen_desc} · {loc_desc} · {rec_desc} · {'gap: ' + ', '.join(gaps) if gaps else 'no skill gaps'}"


def score_listing(listing: dict[str, Any], facts: dict[str, Any], config: Any, stricter: bool = False) -> dict[str, Any]:
    cfg_weights = getattr(config, "scoring_weights", None)
    weights = cfg_weights if (isinstance(cfg_weights, dict) and cfg_weights) else DEFAULT_WEIGHTS

    skill_score, _, missing_skills = _calculate_skill_match(facts, config)
    sen_score, _ = _calculate_seniority_fit(facts, config)
    loc_score, _ = _calculate_location_fit(listing, facts, config)
    rec_score, _ = _calculate_recency(listing.get("posted_at"), as_of=listing.get("fetched_at"))

    if stricter:
        if missing_skills:
            skill_score = round(skill_score * (0.85 ** len(missing_skills)), 4)
        sen_score = 0.3 if sen_score == 0.6 else (0.05 if sen_score == 0.25 else sen_score)

    components = {
        "skill_match": skill_score, "seniority_fit": sen_score,
        "location_fit": loc_score, "recency": rec_score,
    }
    w_sum = sum(weights.get(k, DEFAULT_WEIGHTS[k]) for k in components) or 1.0
    weighted_total = sum(components[k] * weights.get(k, DEFAULT_WEIGHTS[k]) for k in components) / w_sum

    if stricter:
        diff = weighted_total - 0.50
        sign = 1.0 if diff >= 0 else -1.0
        weighted_total = max(0.0, min(1.0, 0.50 + sign * 0.50 * ((abs(diff) / 0.50) ** 0.65)))

    score = max(0, min(100, int(round(weighted_total * 100))))
    reason = build_reason(components, facts, config, listing=listing, missing_skills=missing_skills)
    if stricter:
        reason = f"[strict] {reason}"

    return {"score": score, "reason": reason, "components": components}
