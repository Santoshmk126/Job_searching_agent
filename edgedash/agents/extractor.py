import hashlib
from typing import Any
from edgedash.llm import complete_json
from edgedash.normalizer import normalize_skill
import edgedash.storage as storage

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "required_skills": {"type": "array", "items": {"type": "string"}},
        "nice_to_have": {"type": "array", "items": {"type": "string"}},
        "seniority": {"type": "string", "enum": ["junior", "mid", "senior", "lead", "unknown"]},
        "years_required": {"type": ["integer", "null"]},
        "remote_ok": {"type": ["boolean", "null"]},
    },
    "required": [
        "required_skills",
        "nice_to_have",
        "seniority",
        "years_required",
        "remote_ok",
    ],
}

EXTRACTION_PROMPT_TEMPLATE: str = """You are an objective document information extraction engine.
Analyze the following job listing text and extract facts explicitly stated by the employer.

CRITICAL EXTRACTION RULES:
1. Extract ONLY facts explicitly stated in the listing text.
2. Do NOT guess, assume, extrapolate, or infer any unmentioned details.
3. If an item is not explicitly stated in the text, return null (for years_required or remote_ok) or an empty list [] (for skills).
4. Do not evaluate any candidate or role suitability. Extract structured document facts only.

FIELDS TO EXTRACT:
- "required_skills": List of strings. Specific technical, tool, language, or domain skills explicitly stated as required or mandatory.
- "nice_to_have": List of strings. Skills explicitly designated as preferred, bonus, optional, or plus.
- "seniority": Exactly one of "junior", "mid", "senior", "lead", or "unknown". Use "unknown" if not explicitly specified.
- "years_required": Integer or null. The minimum years of experience explicitly demanded. Null if not stated (never guess).
- "remote_ok": Boolean or null. True if remote work is permitted, False if strictly on-site, or null if unmentioned.

JOB TITLE: {title}
COMPANY: {company}
LOCATION: {location}

JOB DESCRIPTION:
{description}

Respond ONLY with a valid JSON object matching the requested schema. Do not include markdown code fences or conversational prose."""


def compute_description_hash(description: str | None) -> str:
    text = (description or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract(listing: dict[str, Any], *, db_path: str | None = None) -> dict[str, Any]:
    description = listing.get("description") or ""
    desc_hash = compute_description_hash(description)

    # 1. Check extraction cache first (Rule 18)
    cached = storage.get_cached_extraction(desc_hash, db_path=db_path)
    if cached is not None:
        return cached

    # 2. Build prompt from listing details
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        title=listing.get("title") or "Unknown",
        company=listing.get("company") or "Unknown",
        location=listing.get("location") or "Not specified",
        description=description if description.strip() else "(No description provided)",
    )

    # 3. Call LLM gateway with schema
    raw = complete_json(prompt, EXTRACTION_SCHEMA)

    # 4. Normalise skill names canonically (Rule 16 / unified normalizer)
    req_skills = list(dict.fromkeys(
        normalize_skill(s) for s in raw.get("required_skills", [])
        if isinstance(s, str) and normalize_skill(s)
    ))
    nice_skills = list(dict.fromkeys(
        normalize_skill(s) for s in raw.get("nice_to_have", [])
        if isinstance(s, str) and normalize_skill(s)
    ))
    seniority = raw.get("seniority")
    if seniority not in {"junior", "mid", "senior", "lead", "unknown"}:
        seniority = "unknown"
    years = raw.get("years_required")
    years_val = int(years) if isinstance(years, (int, float)) else None
    remote = raw.get("remote_ok")
    remote_val = bool(remote) if isinstance(remote, bool) else None

    extracted: dict[str, Any] = {
        "required_skills": req_skills,
        "nice_to_have": nice_skills,
        "seniority": seniority,
        "years_required": years_val,
        "remote_ok": remote_val,
    }

    # 5. Store in cache
    storage.save_cached_extraction(desc_hash, extracted, db_path=db_path)
    return extracted
