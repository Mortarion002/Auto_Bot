from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


HN_ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
HN_LOOKBACK_DAYS = 14
HN_RESULTS_PER_QUERY = 20
HN_REQUEST_PAUSE_SECONDS = 0.5

HN_QUERIES: list[tuple[str, str]] = [
    ("customer feedback", "customer_feedback"),
    ("survey tool", "survey_tool"),
    ("nps csat", "nps_csat"),
    ("qualtrics alternative", "qualtrics_alternative"),
    ("delighted alternative", "delighted_alternative"),
    ("typeform alternative", "typeform_alternative"),
    ("uservoice alternative", "uservoice_alternative"),
    ("in app feedback", "in_app_feedback"),
]


@dataclass(slots=True)
class HNPost:
    object_id: str
    title: str
    body: str
    url: str
    author: str
    points: int
    num_comments: int
    created_at: datetime
    query_type: str

    @property
    def text(self) -> str:
        if self.body:
            return f"{self.title}\n\n{self.body}"
        return self.title


class HNScraper:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger
        self.session = requests.Session() if requests is not None else None

    def fetch_all(self) -> list[HNPost]:
        if self.session is None:
            raise RuntimeError("requests is required for HN scraping.")

        since = int(time.time()) - (HN_LOOKBACK_DAYS * 24 * 60 * 60)
        seen: dict[str, HNPost] = {}

        for query, query_type in HN_QUERIES:
            try:
                batch = self._fetch_query(query, query_type, since)
                for post in batch:
                    seen.setdefault(post.object_id, post)
                self.logger.info("HN: fetched %d posts for '%s'.", len(batch), query)
            except Exception as exc:
                self.logger.warning("HN fetch failed for '%s': %s", query, exc)
            time.sleep(HN_REQUEST_PAUSE_SECONDS)

        return list(seen.values())

    def _fetch_query(self, query: str, query_type: str, since: int) -> list[HNPost]:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since}",
            "hitsPerPage": HN_RESULTS_PER_QUERY,
        }
        url = f"{HN_ALGOLIA_BASE}/search_by_date?{urlencode(params)}"
        resp = self.session.get(url, timeout=self.settings.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()

        posts: list[HNPost] = []
        for hit in data.get("hits", []):
            if not hit.get("title"):
                continue
            try:
                created_at = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
            except (KeyError, TypeError, ValueError):
                created_at = datetime.now(timezone.utc)

            posts.append(HNPost(
                object_id=str(hit.get("objectID", "")),
                title=str(hit.get("title", "")).strip(),
                body=str(hit.get("story_text") or hit.get("comment_text") or "").strip(),
                url=f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                author=str(hit.get("author", "")).strip(),
                points=int(hit.get("points") or 0),
                num_comments=int(hit.get("num_comments") or 0),
                created_at=created_at,
                query_type=query_type,
            ))
        return posts
