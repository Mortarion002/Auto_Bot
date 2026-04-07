from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be missing in tests
    requests = None  # type: ignore[assignment]


REDDIT_BASE_URL = "https://www.reddit.com"
DEFAULT_POSTS_PER_SUBREDDIT = 50
DEFAULT_SEARCH_RESULTS_PER_KEYWORD = 10
REQUEST_PAUSE_SECONDS = 0.25


@dataclass(slots=True)
class RedditPost:
    post_id: str
    subreddit: str
    title: str
    body: str
    author: str
    post_url: str
    created_at: datetime
    upvotes: int
    comment_count: int

    @property
    def text(self) -> str:
        body = self.body.strip()
        if not body:
            return self.title.strip()
        return f"{self.title.strip()}\n\n{body}"


@dataclass(slots=True)
class RedditScanResult:
    posts: list[RedditPost]
    scanned_count: int
    per_subreddit_counts: dict[str, int]
    errors: list[str]


class RedditScraper:
    def __init__(self, settings: Any, logger: Any):
        self.settings = settings
        self.logger = logger
        self.session = requests.Session() if requests is not None else None

    def scan_subreddits(
        self,
        subreddits: list[str],
        *,
        posts_per_subreddit: int = DEFAULT_POSTS_PER_SUBREDDIT,
    ) -> RedditScanResult:
        posts: list[RedditPost] = []
        scanned_count = 0
        per_subreddit_counts: dict[str, int] = {}
        errors: list[str] = []

        for index, subreddit in enumerate(subreddits):
            if index > 0:
                time.sleep(REQUEST_PAUSE_SECONDS)

            try:
                subreddit_posts = self.fetch_subreddit_posts(
                    subreddit,
                    limit=posts_per_subreddit,
                )
            except Exception as exc:
                message = f"r/{subreddit}: {exc}"
                self.logger.warning("Reddit fetch failed for %s", message)
                errors.append(message)
                continue

            posts.extend(subreddit_posts)
            scanned_count += len(subreddit_posts)
            per_subreddit_counts[subreddit] = len(subreddit_posts)

        return RedditScanResult(
            posts=posts,
            scanned_count=scanned_count,
            per_subreddit_counts=per_subreddit_counts,
            errors=errors,
        )

    def fetch_subreddit_posts(
        self,
        subreddit: str,
        *,
        limit: int = DEFAULT_POSTS_PER_SUBREDDIT,
    ) -> list[RedditPost]:
        url = f"{REDDIT_BASE_URL}/r/{subreddit}/new.json"
        params = {
            "limit": max(1, min(limit, 100)),
        }
        posts = self._fetch_posts(url, subreddit=subreddit, params=params)
        self.logger.info(
            "Fetched %s posts from r/%s.",
            len(posts),
            subreddit,
        )
        return posts

    def search_keywords(
        self,
        subreddits: list[str],
        keywords: list[str],
        *,
        results_per_keyword: int = DEFAULT_SEARCH_RESULTS_PER_KEYWORD,
    ) -> RedditScanResult:
        posts: list[RedditPost] = []
        scanned_count = 0
        per_subreddit_counts: dict[str, int] = {}
        errors: list[str] = []

        for subreddit in subreddits:
            for keyword in keywords:
                if posts or errors:
                    time.sleep(REQUEST_PAUSE_SECONDS)

                try:
                    keyword_posts = self.search_subreddit_posts(
                        subreddit,
                        keyword,
                        limit=results_per_keyword,
                    )
                except Exception as exc:
                    message = f"r/{subreddit} [{keyword}]: {exc}"
                    self.logger.warning("Reddit keyword search failed for %s", message)
                    errors.append(message)
                    continue

                posts.extend(keyword_posts)
                scanned_count += len(keyword_posts)
                per_subreddit_counts[subreddit] = (
                    per_subreddit_counts.get(subreddit, 0) + len(keyword_posts)
                )

        return RedditScanResult(
            posts=posts,
            scanned_count=scanned_count,
            per_subreddit_counts=per_subreddit_counts,
            errors=errors,
        )

    def search_subreddit_posts(
        self,
        subreddit: str,
        keyword: str,
        *,
        limit: int = DEFAULT_SEARCH_RESULTS_PER_KEYWORD,
    ) -> list[RedditPost]:
        url = f"{REDDIT_BASE_URL}/r/{subreddit}/search.json"
        if self.session is None:
            raise RuntimeError("requests is required for Reddit scraping.")
        params = {
            "q": keyword,
            "restrict_sr": "on",
            "sort": "new",
            "t": "week",
            "limit": max(1, min(limit, 100)),
        }
        posts = self._fetch_posts(url, subreddit=subreddit, params=params)
        self.logger.info(
            "Keyword search fetched %s posts from r/%s for '%s'.",
            len(posts),
            subreddit,
            keyword,
        )
        return posts

    def _fetch_posts(
        self,
        url: str,
        *,
        subreddit: str,
        params: dict[str, Any],
    ) -> list[RedditPost]:
        if self.session is None:
            raise RuntimeError("requests is required for Reddit scraping.")

        headers = {
            "User-Agent": "ElvanRedditMonitor/1.0 by AmanKumar",
        }
        response = self.session.get(
            url,
            headers=headers,
            params=params,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        children = payload.get("data", {}).get("children", [])

        posts: list[RedditPost] = []
        for child in children:
            item = child.get("data", {})
            post = self._parse_post(subreddit, item)
            if post is not None:
                posts.append(post)
        return posts

    def _parse_post(self, subreddit: str, item: dict[str, Any]) -> RedditPost | None:
        if item.get("stickied") or item.get("pinned"):
            return None
        if item.get("removed_by_category"):
            return None

        post_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        permalink = str(item.get("permalink") or "").strip()
        if not post_id or not title or not permalink:
            return None

        created_utc = item.get("created_utc")
        if created_utc is None:
            return None

        try:
            created_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

        body = str(item.get("selftext") or "").strip()
        author = str(item.get("author") or "[deleted]").strip()
        upvotes = int(item.get("ups") or 0)
        comment_count = int(item.get("num_comments") or 0)
        post_url = f"{REDDIT_BASE_URL}{permalink}"

        return RedditPost(
            post_id=post_id,
            subreddit=subreddit,
            title=title,
            body=body,
            author=author,
            post_url=post_url,
            created_at=created_at,
            upvotes=upvotes,
            comment_count=comment_count,
        )
