from typing import Any
import time
import requests


class SourceError(Exception):
    """Raised when an external source network request fails."""
    pass


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    retries: int = 2,
    backoff_factor: float = 1.0,
) -> Any:
    req_headers = {
        "User-Agent": "EdgeDash-CareerAgent/1.0 (+https://github.com/Santoshmk126/edgedash)"
    }
    if headers:
        req_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, headers=req_headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(backoff_factor * (2 ** attempt))

    raise SourceError(
        f"Failed to fetch JSON from '{url}' after {retries + 1} attempts: {last_error}"
    ) from last_error
