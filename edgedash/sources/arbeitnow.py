from datetime import datetime, timezone
import time
from typing import Any
from edgedash.config import Config
from edgedash.sources.base import Source, register
from edgedash.sources.http import get_json


def _clean(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return None if not s or s.upper() == "N/A" else s


def _format_posted_at(val: Any) -> str | None:
    if not val:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, timezone.utc).isoformat()
        except (ValueError, OSError):
            return None
    if isinstance(val, str):
        return _clean(val)
    return None


@register
class ArbeitnowSource(Source):
    name: str = "arbeitnow"
    _API_URL: str = "https://www.arbeitnow.com/api/job-board-api"
    _MAX_PAGES: int = 5

    def _matches_keywords(self, job: dict[str, Any], config: Config) -> bool:
        if not config.keywords:
            return True
        title = str(job.get("title") or "")
        desc = str(job.get("description") or "")
        tags = " ".join(job.get("tags") or [])
        search_corpus = f"{title} {desc} {tags}".lower()
        return any(kw.strip().lower() in search_corpus for kw in config.keywords if kw.strip())

    def _matches_location(self, job: dict[str, Any], city: str) -> bool:
        if not city:
            return True
        loc = str(job.get("location") or "").lower()
        is_remote = bool(job.get("remote")) or "remote" in loc
        return city in loc or is_remote or city == "remote"

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        all_raw_jobs: list[dict[str, Any]] = []

        for page in range(1, self._MAX_PAGES + 1):
            data = get_json(self._API_URL, params={"page": page})
            page_jobs: list[dict[str, Any]] = data.get("data", [])
            if not page_jobs:
                break

            all_raw_jobs.extend(page_jobs)
            page_matches = sum(1 for j in page_jobs if self._matches_keywords(j, config))

            # Keep paging only while results keep matching keywords
            if page_matches == 0:
                break

            links = data.get("links", {})
            if not links.get("next"):
                break

            if page < self._MAX_PAGES:
                time.sleep(1.0)  # Rate limit: max 1 req/sec (steering rule 14)

        # 1. Filter against keywords
        keyword_matched = [j for j in all_raw_jobs if self._matches_keywords(j, config)]

        # 2. Filter against target city
        target_city = (config.target_city or "").strip().lower()
        location_matched = [j for j in keyword_matched if self._matches_location(j, target_city)]

        if len(location_matched) >= 5:
            survived = location_matched
        else:
            print(
                f"[{self.name}] Location '{config.target_city}' produced {len(location_matched)} results (< 5); "
                "relaxing location filter."
            )
            survived = keyword_matched

        normalised: list[dict[str, Any]] = []
        for j in survived:
            loc = _clean(j.get("location"))
            if not loc and j.get("remote"):
                loc = "Remote"

            row = {
                "source": self.name,
                "external_id": _clean(j.get("slug")),
                "title": _clean(j.get("title")),
                "company": _clean(j.get("company_name")),
                "location": loc,
                "url": _clean(j.get("url")),
                "description": _clean(j.get("description")),
                "posted_at": _format_posted_at(j.get("created_at")),
                "raw": j,
            }
            normalised.append(row)

        print(f"[{self.name}] Raw results: {len(all_raw_jobs)}. Survived filtering: {len(normalised)}.")
        return normalised
