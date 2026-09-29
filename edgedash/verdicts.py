from collections import Counter
from datetime import datetime
import sys
import argparse
from typing import Any
from edgedash.config import load_config
import edgedash.storage as storage

GREEN = "\033[92m"
RED = "\033[91;1m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _format_dt(ts_str: str | None) -> str:
    if not ts_str:
        return "-"
    try:
        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_str)[:19]


def extract_cycle_verdict(cycle: dict[str, Any]) -> tuple[str, list[dict[str, Any]], int, str]:
    notes = cycle.get("notes_parsed", {})
    status = (cycle.get("status") or "unknown").lower()
    v_data = notes.get("verdict", {})

    if v_data:
        passed = v_data.get("passed", True)
        if status == "degraded" or not passed:
            verdict = "degraded" if status == "degraded" else "fail"
        else:
            verdict = "pass"
        failed_checks = v_data.get("failed_checks", [])
        retries = v_data.get("retry_count", 0)
    else:
        if status in ("complete", "nothing_to_do"):
            verdict, failed_checks, retries = "pass", [], 0
        elif status == "degraded":
            verdict, failed_checks, retries = "degraded", [], 0
        else:
            verdict, failed_checks, retries = "fail", [], 0

    ran_agents = ", ".join(notes.get("ran", [])) or "none"
    return verdict, failed_checks, retries, ran_agents


def _color_badge(v: str, use_color: bool) -> str:
    raw = f"{v.upper():<8}"
    if not use_color:
        return raw
    if v == "pass":
        return f"{GREEN}{raw}{RESET}"
    if v == "degraded":
        return f"{RED}{raw}{RESET}"
    return f"{YELLOW}{raw}{RESET}"


def render_verdicts_table(cycles: list[dict[str, Any]], check_filter: str | None = None, use_color: bool = True) -> tuple[str, dict[str, Any]]:
    filtered_data = []
    for c in cycles:
        verdict, failed_checks, retries, ran = extract_cycle_verdict(c)
        if check_filter:
            check_names = [fc.get("name", "").lower() for fc in failed_checks]
            if check_filter.lower() not in check_names:
                continue
        filtered_data.append((c, verdict, failed_checks, retries, ran))

    if not filtered_data:
        msg = "No verification records found" + (f" matching check '{check_filter}'" if check_filter else "") + "."
        return msg, {"total": 0, "passed": 0, "pass_rate": 0.0, "most_frequent_fail": None}

    lines = []
    header = f"{'Timestamp':<20} | {'Verdict':<8} | {'Retries':<7} | {'Agents Ran':<25} | {'Failed Checks / Observed'}"
    sep = "-" * 105
    lines.append(header)
    lines.append(sep)

    passed_count = 0
    fail_counter: Counter[str] = Counter()

    for c, verdict, failed_checks, retries, ran in filtered_data:
        if verdict == "pass":
            passed_count += 1

        if failed_checks:
            fails_str = "; ".join(f"{fc.get('name')}: {fc.get('message', '')}" for fc in failed_checks)
            for fc in failed_checks:
                fail_counter[fc.get("name", "unknown")] += 1
        else:
            fails_str = "-"

        dt_str = _format_dt(c.get("finished_at") or c.get("started_at"))
        badge = _color_badge(verdict, use_color)
        lines.append(f"{dt_str:<20} | {badge} | {retries:<7} | {ran:<25} | {fails_str}")

    total = len(filtered_data)
    rate = (passed_count / total) * 100.0 if total > 0 else 0.0
    most_freq = fail_counter.most_common(1)[0] if fail_counter else None

    lines.append(sep)
    lines.append(f"Summary: {total} cycles evaluated | Pass Rate: {rate:.1f}% ({passed_count}/{total})")
    if most_freq:
        lines.append(f"Most frequently failing check: {most_freq[0]} ({most_freq[1]} failure(s))")
    else:
        lines.append("Most frequently failing check: None (100% clean)")

    stats = {
        "total": total, "passed": passed_count, "pass_rate": round(rate, 2),
        "most_frequent_fail": most_freq[0] if most_freq else None, "fail_counts": dict(fail_counter),
    }
    return "\n".join(lines), stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only verification history view from cycle_log.")
    parser.add_argument("--check", type=str, default=None, help="Filter to cycles where this specific check failed.")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent cycles to inspect (default: 20).")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cycles = storage.get_recent_cycles(limit=args.limit, agent="orchestrator", db_path=cfg.db_path)
    output, _ = render_verdicts_table(cycles, check_filter=args.check, use_color=sys.stdout.isatty())
    print(output)


if __name__ == "__main__":
    main()
