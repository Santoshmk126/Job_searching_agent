from collections import defaultdict, deque
import re
import time
from typing import Any

from edgedash.config import Config
import edgedash.storage as storage

# Compiled regex for stripping ASCII control characters (keep printable chars)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Suspicious instruction injection patterns
_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?previous",
    r"system\s+prompt",
    r"you\s+are\s+now",
    r"forget\s+(?:all\s+)?previous",
    r"new\s+instructions?",
    r"disregard\s+(?:all\s+)?previous",
    r"override\s+(?:all\s+)?instructions?",
    r"jailbreak",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


class SessionRateLimiter:
    """Sliding-window in-memory rate limiter per session (10 queries / 10 minutes)."""

    def __init__(self, max_queries: int = 10, window_seconds: int = 600) -> None:
        self.max_queries = max_queries
        self.window_seconds = window_seconds
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def check_and_record(self, session_id: str) -> tuple[bool, int]:
        """Check if request is permitted. If yes, records timestamp; if no, returns wait time in seconds."""
        now = time.time()
        q = self._history[session_id]

        # Evict timestamps outside window
        while q and (q[0] <= now - self.window_seconds):
            q.popleft()

        if len(q) >= self.max_queries:
            wait_seconds = int(self.window_seconds - (now - q[0])) + 1
            return False, max(1, wait_seconds)

        q.append(now)
        return True, 0

    def reset(self, session_id: str | None = None) -> None:
        """Reset history for a session or all sessions (useful for tests)."""
        if session_id:
            self._history.pop(session_id, None)
        else:
            self._history.clear()


GLOBAL_SESSION_LIMITER = SessionRateLimiter(max_queries=10, window_seconds=600)


def sanitize_input(text: str) -> str:
    """Strip control characters and collapse excessive whitespace."""
    if not text:
        return ""
    cleaned = _CONTROL_CHARS_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def validate_input_guards(raw_question: str) -> tuple[bool, str, str | None, str | None]:
    """
    Validate input against abuse rules before any model call.
    Returns: (is_valid, sanitized_question, user_facing_error, rejection_reason)
    """
    sanitized = sanitize_input(raw_question)

    if not sanitized:
        return False, "", "Please enter a non-empty question.", "rejected: empty input"

    if len(sanitized) > 300:
        return (
            False,
            sanitized,
            f"Questions must be 300 characters or fewer (your input is {len(sanitized)} characters). Please shorten your question.",
            f"rejected: input length {len(sanitized)} exceeds 300 chars",
        )

    if _INJECTION_RE.search(sanitized):
        return (
            False,
            sanitized,
            None,  # Will trigger standard can't-answer response without disclosing filter
            "rejected: suspicious input",
        )

    return True, sanitized, None, None


def check_daily_cap(config: Config) -> tuple[bool, int, int]:
    """
    Check if the global daily query cap has been reached.
    Returns: (is_exceeded, current_count, cap)
    """
    current_count = storage.get_daily_query_count(config.db_path)
    cap = getattr(config, "daily_query_cap", 200)
    return (current_count >= cap), current_count, cap
