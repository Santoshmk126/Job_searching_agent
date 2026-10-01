from dataclasses import dataclass
import json
import time
from typing import Any

from edgedash.config import Config, load_config
import edgedash.llm as llm
from edgedash.query.guards import (
    GLOBAL_SESSION_LIMITER,
    check_daily_cap,
    validate_input_guards,
)
from edgedash.query.tools import TOOLS
import edgedash.storage as storage


@dataclass
class Answer:
    text: str
    rows: list[dict[str, Any]]
    tool_used: str | None
    params: dict[str, Any]


_UNANSWERABLE_MSG = (
    "I cannot answer that question because it is outside the scope of my verified job intelligence queries. "
    "I do not guess or provide general opinion. Here are the questions I can answer:\n\n"
    "• Active Employers: 'Which companies are hiring in the last 14 days?'\n"
    "• Best Matches: 'What are my top 5 job matches?'\n"
    "• Skill Gaps: 'What are my top skill gaps by opportunity cost?'\n"
    "• Gap Drill-Down: 'Which jobs are blocked by missing Docker?'\n"
    "• Historical Trends: 'How have skill gaps changed over the last 3 weeks?'\n"
    "• Database Freshness: 'How many total and scored listings do we have?'\n"
    "• Skill Market Demand: 'How often does PyTorch appear as required vs nice-to-have?'\n"
    "• Job Locations: 'Where are the jobs located or what are the top cities?'"
)


def _build_route_prompt(question: str) -> str:
    tools_doc = "\n".join(
        f"Tool: {k}\nDescription: {v['description']}\nSchema: {json.dumps(v.get('parameters', {}))}"
        for k, v in TOOLS.items()
    )
    return (
        "You are a deterministic query router. Match the question to EXACTLY ONE tool from AVAILABLE TOOLS.\n\n"
        f"AVAILABLE TOOLS:\n{tools_doc}\n\n"
        f'USER QUESTION: "{question}"\n\n'
        "RULES (Rule 45):\n"
        "1. If no tool directly matches the question, return {\"tool\": null, \"params\": {}}.\n"
        "2. DO NOT GUESS OR PICK ADJACENT TOOLS. Return null if outside scope.\n"
        "3. Output schema: {\"tool\": str|null, \"params\": dict, \"confidence\": \"high\"|\"low\"}."
    )


def _build_phrase_prompt(question: str, summary: str, rows: list[dict[str, Any]]) -> str:
    return (
        "You are EdgeDash, a factual career intelligence assistant.\n"
        "Write a concise 2-3 sentence answer strictly grounded in the returned rows.\n\n"
        f'USER QUESTION: "{question}"\n'
        f'DATA SUMMARY: "{summary}"\n'
        f"RETURNED ROWS: {json.dumps(rows[:20])}\n\n"
        "RULES (Rule 43):\n"
        "1. Use ONLY exact numbers and facts in the rows and summary. No guessing or external facts.\n"
        "2. If rows are empty, state plainly that no matching records were found.\n"
        "3. Output schema: {\"answer\": \"<2-3 sentence prose>\"}."
    )


def ask(question: str, session_id: str = "default", config: Config | None = None) -> Answer:
    """Execute the two-call query pipeline with strict abuse guards (Rules 40-46)."""
    start_time = time.time()
    cfg = config or load_config()

    # Guard 1: Global Daily Cap (Point 3)
    is_cap_exceeded, current_count, cap = check_daily_cap(cfg)
    if is_cap_exceeded:
        dur = (time.time() - start_time) * 1000.0
        reason = f"rejected: daily cap reached ({current_count}/{cap})"
        storage.log_query(question, None, {"rejection_reason": reason}, False, dur, db_path=cfg.db_path)
        return Answer(
            f"The daily question limit has been reached ({current_count}/{cap}). The ask box will reset at midnight UTC.",
            [], None, {"rejection_reason": reason}
        )

    # Guard 2: Session Rate Limit (Point 1: 10 queries per 10 mins)
    allowed, wait_sec = GLOBAL_SESSION_LIMITER.check_and_record(session_id)
    if not allowed:
        dur = (time.time() - start_time) * 1000.0
        wait_min = max(1, (wait_sec + 59) // 60)
        reason = f"rejected: session rate limit exceeded ({wait_sec}s wait)"
        storage.log_query(question, None, {"rejection_reason": reason}, False, dur, db_path=cfg.db_path)
        return Answer(
            f"Rate limit reached (max 10 queries per 10 minutes). Please wait {wait_min} minute(s) before asking another question.",
            [], None, {"rejection_reason": reason}
        )

    # Guard 3: Input Guards & Injection Filters (Point 2)
    is_valid, cleaned_q, user_msg, rejection_reason = validate_input_guards(question)
    if not is_valid:
        dur = (time.time() - start_time) * 1000.0
        storage.log_query(question, None, {"rejection_reason": rejection_reason}, False, dur, db_path=cfg.db_path)
        # Point 2: Suspicious input returns standard refusal without explaining filter
        resp_text = _UNANSWERABLE_MSG if rejection_reason == "rejected: suspicious input" else (user_msg or _UNANSWERABLE_MSG)
        return Answer(resp_text, [], None, {"rejection_reason": rejection_reason})

    # Step 1: ROUTE (Rule 42, 45)
    route_res = llm.complete_json(_build_route_prompt(cleaned_q), {"required": ["tool"]}, config=cfg)
    chosen_tool = route_res.get("tool")
    params = route_res.get("params") or {}

    if not chosen_tool:
        dur = (time.time() - start_time) * 1000.0
        storage.log_query(cleaned_q, None, params, False, dur, db_path=cfg.db_path)
        return Answer(_UNANSWERABLE_MSG, [], None, {})

    if chosen_tool not in TOOLS:
        raise ValueError(f"Router returned invalid tool '{chosen_tool}' not in TOOLS registry.")

    # Step 2: EXECUTE (Deterministic query)
    res = TOOLS[chosen_tool]["func"](**params, config=cfg)
    summary, rows = res.get("summary", ""), res.get("rows", [])

    # Step 3: PHRASE (Rule 42, 43)
    if not rows:
        prose = f"Based on verified data ({summary}), no matching records were found."
    else:
        phrase_res = llm.complete_json(_build_phrase_prompt(cleaned_q, summary, rows), {"required": ["answer"]}, config=cfg)
        prose = phrase_res.get("answer", summary)

    dur = (time.time() - start_time) * 1000.0
    storage.log_query(cleaned_q, chosen_tool, params, True, dur, db_path=cfg.db_path)
    return Answer(prose, rows, chosen_tool, params)
