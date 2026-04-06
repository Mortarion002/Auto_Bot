from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin

from config import Settings
from models import DiscoveredPost


POST_URL_PATTERN = re.compile(
    r"(?:https?://(?:www\.)?x\.com)?/([^/]+)/status/(\d+)",
    re.IGNORECASE,
)
METRIC_PATTERN = re.compile(r"(\d+(?:[\d,.]*\d)?)([kmb]?)", re.IGNORECASE)


def normalize_handle(handle: str) -> str:
    return handle.lstrip("@").strip().lower()


def parse_metric_count(raw: str | None) -> int:
    if not raw:
        return 0
    match = METRIC_PATTERN.search(raw.replace(" ", ""))
    if not match:
        return 0

    value = float(match.group(1).replace(",", ""))
    suffix = match.group(2).lower()
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    return int(value * multiplier)


def compute_engagement_score(
    likes: int,
    replies: int,
    reposts: int,
    created_at: datetime,
    now: datetime | None = None,
) -> float:
    current = now or datetime.now(timezone.utc)
    base = likes + (replies * 2) + (reposts * 1.5)
    age_seconds = (current - created_at.astimezone(timezone.utc)).total_seconds()
    multiplier = 1.5 if age_seconds <= 7200 else 1.0
    return base * multiplier


def extract_post_ref(href: str | None) -> tuple[str, str, str] | None:
    if not href:
        return None
    match = POST_URL_PATTERN.search(href)
    if not match:
        return None
    handle = match.group(1)
    post_id = match.group(2)
    post_url = urljoin("https://x.com", f"/{handle}/status/{post_id}")
    return post_url, handle, post_id


class XSearcher:
    def __init__(self, settings: Settings, db: Any, logger: Any):
        self.settings = settings
        self.db = db
        self.logger = logger

    def discover_posts(
        self,
        page: Any,
        keywords: list[str],
        *,
        record_seen: bool = True,
    ) -> tuple[list[DiscoveredPost], int]:
        candidates: dict[str, DiscoveredPost] = {}

        for keyword in keywords:
            live_posts = self._filter_and_score_posts(
                self._search_keyword(page, keyword, "live"),
                record_seen=record_seen,
            )
            merged = {post.post_id: post for post in live_posts}

            if len(live_posts) < self.settings.min_valid_posts_before_top_fallback:
                top_posts = self._filter_and_score_posts(
                    self._search_keyword(page, keyword, "top"),
                    record_seen=record_seen,
                )
                for post in top_posts:
                    merged.setdefault(post.post_id, post)

            for post in merged.values():
                existing = candidates.get(post.post_id)
                if existing is None or post.score > existing.score:
                    candidates[post.post_id] = post

        ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
        return ranked[: self.settings.top_posts_to_comment], len(keywords)

    def _search_keyword(self, page: Any, keyword: str, mode: str) -> list[DiscoveredPost]:
        search_url = self._build_search_url(keyword, mode)
        self.logger.info("Searching X for '%s' (%s).", keyword, mode)
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self._scroll_results(page)

        posts: list[DiscoveredPost] = []
        articles = page.locator("article[data-testid='tweet']")
        article_count = min(articles.count(), self.settings.posts_per_keyword_per_run)

        for index in range(article_count):
            article = articles.nth(index)
            post = self._scrape_article(article, keyword, mode)
            if post is not None:
                posts.append(post)

        return posts

    def _build_search_url(self, keyword: str, mode: str) -> str:
        return (
            f"https://x.com/search?q={quote_plus(keyword)}&src=typed_query&f={mode}"
        )

    def _scroll_results(self, page: Any) -> None:
        articles = page.locator("article[data-testid='tweet']")
        for _ in range(self.settings.max_scroll_rounds):
            current_count = articles.count()
            if current_count >= self.settings.posts_per_keyword_per_run:
                break
            page.mouse.wheel(0, random.randint(1400, 2200))
            page.wait_for_timeout(self.settings.scroll_pause_seconds * 1000)

    def _scrape_article(
        self,
        article: Any,
        keyword: str,
        mode: str,
    ) -> DiscoveredPost | None:
        ref = self._extract_post_reference(article)
        if ref is None:
            return None
        post_url, author_handle, post_id = ref

        text = self._safe_inner_text(article.locator("[data-testid='tweetText']").first)
        if not text:
            return None

        likes = self._extract_metric(article, "like")
        replies = self._extract_metric(article, "reply")
        reposts = self._extract_metric(article, "retweet")
        created_at = self._extract_created_at(article)

        return DiscoveredPost(
            post_id=post_id,
            post_url=post_url,
            author_handle=author_handle,
            text=text,
            likes=likes,
            replies=replies,
            reposts=reposts,
            created_at=created_at,
            keyword=keyword,
            search_mode=mode,
        )

    def _extract_post_reference(self, article: Any) -> tuple[str, str, str] | None:
        links = article.locator("a[href*='/status/']")
        for index in range(links.count()):
            href = self._safe_attribute(links.nth(index), "href")
            ref = extract_post_ref(href)
            if ref is not None:
                return ref
        return None

    def _extract_metric(self, article: Any, test_id: str) -> int:
        locator = article.locator(f"[data-testid='{test_id}']").first
        raw = self._safe_inner_text(locator) or self._safe_attribute(locator, "aria-label")
        return parse_metric_count(raw)

    def _extract_created_at(self, article: Any) -> datetime:
        locator = article.locator("time").first
        raw = self._safe_attribute(locator, "datetime")
        if not raw:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)

    def _filter_and_score_posts(
        self,
        posts: list[DiscoveredPost],
        *,
        record_seen: bool,
    ) -> list[DiscoveredPost]:
        now = datetime.now(timezone.utc)
        filtered: list[DiscoveredPost] = []

        for post in posts:
            if record_seen:
                self.db.mark_post_seen(post.post_id, now.isoformat())
            if self.db.has_commented(post.post_id):
                continue
            if normalize_handle(post.author_handle) == self.settings.normalized_account_handle:
                continue

            age_hours = (
                now - post.created_at.astimezone(timezone.utc)
            ).total_seconds() / 3600
            if age_hours > self.settings.max_post_age_hours:
                continue
            if post.likes < self.settings.min_likes:
                continue
            if post.likes > self.settings.max_likes:
                continue

            post.score = compute_engagement_score(
                post.likes,
                post.replies,
                post.reposts,
                post.created_at,
                now=now,
            )
            filtered.append(post)

        return filtered

    def _safe_inner_text(self, locator: Any) -> str:
        try:
            return locator.inner_text().strip()
        except Exception:
            return ""

    def _safe_attribute(self, locator: Any, attribute: str) -> str:
        try:
            value = locator.get_attribute(attribute)
        except Exception:
            return ""
        return value or ""
