from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


PH_API_URL = "https://api.producthunt.com/v2/api/graphql"

_CX_QUERY = """
query {
  posts(order: NEWEST, topic: "customer-success", first: 20) {
    edges {
      node {
        id name tagline description url votesCount commentsCount createdAt
      }
    }
  }
}
"""

_NEWEST_QUERY = """
query {
  posts(order: NEWEST, first: 20) {
    edges {
      node {
        id name tagline description url votesCount createdAt
        comments(first: 5, order: VOTES) {
          edges { node { body } }
        }
      }
    }
  }
}
"""


@dataclass(slots=True)
class PHPost:
    ph_id: str
    title: str
    body: str
    url: str
    votes: int
    comments_count: int
    created_at: datetime
    query_type: str

    @property
    def text(self) -> str:
        if self.body:
            return f"{self.title}\n\n{self.body}"
        return self.title


class PHScraper:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger
        self.session = requests.Session() if requests is not None else None

    def fetch_all(self) -> list[PHPost]:
        if self.session is None:
            raise RuntimeError("requests is required for PH scraping.")

        token = self.settings.producthunt_dev_token
        if not token:
            raise RuntimeError("PRODUCTHUNT_DEV_TOKEN not set — cannot fetch Product Hunt posts.")

        seen: dict[str, PHPost] = {}
        for query_type, gql in [("cx_posts", _CX_QUERY), ("competitor_search", _NEWEST_QUERY)]:
            try:
                batch = self._fetch_query(gql, query_type, token)
                for post in batch:
                    seen.setdefault(post.ph_id, post)
                self.logger.info("PH: fetched %d posts for '%s'.", len(batch), query_type)
            except Exception as exc:
                self.logger.warning("PH fetch failed for '%s': %s", query_type, exc)

        return list(seen.values())

    def _fetch_query(self, gql: str, query_type: str, token: str) -> list[PHPost]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = self.session.post(
            PH_API_URL,
            json={"query": gql},
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()

        edges = ((data.get("data") or {}).get("posts") or {}).get("edges") or []
        posts: list[PHPost] = []

        for edge in edges:
            node = edge.get("node") or {}
            if not node.get("name"):
                continue

            comment_bodies = " | ".join(
                e["node"]["body"]
                for e in ((node.get("comments") or {}).get("edges") or [])
                if (e.get("node") or {}).get("body")
            )
            body_parts = [node.get("tagline"), node.get("description"), comment_bodies]
            body = " ".join(p for p in body_parts if p).strip()

            try:
                raw_date = str(node["createdAt"]).replace("Z", "+00:00")
                created_at = datetime.fromisoformat(raw_date)
            except (KeyError, TypeError, ValueError):
                created_at = datetime.now(timezone.utc)

            posts.append(PHPost(
                ph_id=str(node.get("id", "")),
                title=str(node.get("name", "")).strip(),
                body=body,
                url=str(node.get("url", "")).strip(),
                votes=int(node.get("votesCount") or 0),
                comments_count=int(node.get("commentsCount") or 0),
                created_at=created_at,
                query_type=query_type,
            ))

        return posts
