from datetime import datetime, timezone
import os
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
class ApifySource(Source):
    name: str = "apify"
    _ACTOR_ID: str = "apify~google-jobs-scraper"
    _MAX_RESULTS: int = 100

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        # Rule 13: Read APIFY_TOKEN from environment. If absent, skip without crashing.
        token = os.environ.get("APIFY_TOKEN", "").strip()
        if not token:
            print(f"[{self.name}] apify: no APIFY_TOKEN, skipping")
            return []

        search_query = f"{config.target_role} in {config.target_city}".strip()
        api_url = f"https://api.apify.com/v2/acts/{self._ACTOR_ID}/run-sync-get-dataset-items"
        params = {
            "token": token,
            "queries": search_query,
            "maxItems": self._MAX_RESULTS,
        }

        raw_response = get_json(api_url, params=params)
        raw_items: list[dict[str, Any]] = raw_response if isinstance(raw_response, list) else raw_response.get("items", [])
        
        # Hard cap at 100 to avoid consuming free credits accidentally
        raw_items = raw_items[: self._MAX_RESULTS]

        normalised: list[dict[str, Any]] = []
        for item in raw_items:
            ext_id = (
                item.get("id")
                or item.get("jobId")
                or item.get("googleJobId")
                or item.get("idJob")
                or item.get("slug")
                or item.get("url")
            )
            title = item.get("title") or item.get("jobTitle") or item.get("positionName")
            company = item.get("company") or item.get("companyName") or item.get("employerName")
            
            location = item.get("location") or item.get("jobLocation") or item.get("address")
            if isinstance(location, dict):
                location = location.get("addressLocality") or location.get("name") or str(location)
            elif not location and item.get("isRemote"):
                location = "Remote"

            url = item.get("url") or item.get("jobUrl") or item.get("applyUrl") or item.get("link")
            description = item.get("description") or item.get("jobDescription") or item.get("snippet")
            posted_at = item.get("postedAt") or item.get("datePosted") or item.get("postedTime")

            row = {
                "source": self.name,
                "external_id": _clean(ext_id),
                "title": _clean(title),
                "company": _clean(company),
                "location": _clean(location),
                "url": _clean(url),
                "description": _clean(description),
                "posted_at": _format_posted_at(posted_at),
                "raw": item,
            }
            normalised.append(row)

        print(f"[{self.name}] Raw results: {len(raw_items)}. Survived filtering: {len(normalised)}.")
        return normalised
