from __future__ import annotations

import html as html_module
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be missing in tests
    requests = None  # type: ignore[assignment]


REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_USER_AGENT = "script:ElvanRedditMonitor:1.0 (by /u/AmanKumar)"
ATOM_NS = "http://www.w3.org/2005/Atom"
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


def _extract_body_from_atom_content(raw_html: str) -> str:
    """Pull plain text from the HTML blob inside an Atom <content> element."""
    match = re.search(r"<!-- SC_OFF -->(.*?)<!-- SC_ON -->", raw_html, re.DOTALL)
    if match:
        inner = match.group(1)
    else:
        inner = raw_html
    stripped = re.sub(r"<[^>]+>", " ", inner)
    decoded = html_module.unescape(stripped)
    return re.sub(r"\s+", " ", decoded).strip()


def _parse_atom_entry(entry: ET.Element, subreddit: str) -> RedditPost | None:
    """Parse a single Atom <entry> into a RedditPost, or None if malformed."""
    raw_id = (entry.findtext(f"{{{ATOM_NS}}}id") or "").strip()
    post_id = raw_id.removeprefix("t3_")
    if not post_id:
        return None

    title = (entry.findtext(f"{{{ATOM_NS}}}title") or "").strip()
    if not title:
        return None

    link_el = entry.find(f"{{{ATOM_NS}}}link")
    post_url = (link_el.get("href", "") if link_el is not None else "").strip()
    if not post_url:
        return None

    author_el = entry.find(f"{{{ATOM_NS}}}author/{{{ATOM_NS}}}name")
    raw_author = (author_el.text or "").strip() if author_el is not None else ""
    author = raw_author.lstrip("/u").lstrip("/").strip() or "[deleted]"

    published_text = (entry.findtext(f"{{{ATOM_NS}}}published") or "").strip()
    try:
        created_at = datetime.fromisoformat(published_text)
    except (ValueError, TypeError):
        created_at = datetime.now(timezone.utc)

    content_el = entry.find(f"{{{ATOM_NS}}}content")
    body = _extract_body_from_atom_content(content_el.text or "") if content_el is not None else ""

    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title=title,
        body=body,
        author=author,
        post_url=post_url,
        created_at=created_at,
        upvotes=0,
        comment_count=0,
    )


class RedditScraper:
    def __init__(self, settings: Any, logger: Any):
        self.settings = settings
        self.logger = logger
        self.session = requests.Session() if requests is not None else None

    def _get_headers(self) -> dict[str, str]:
        return {"User-Agent": REDDIT_USER_AGENT}

    def _fetch_rss(self, url: str) -> list[ET.Element]:
        """Fetch a Reddit Atom feed URL and return all <entry> elements."""
        if self.session is None:
            raise RuntimeError("requests is required for Reddit scraping.")
        response = self.session.get(
            url,
            headers=self._get_headers(),
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        return root.findall(f"{{{ATOM_NS}}}entry")

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
        capped = max(1, min(limit, 100))
        url = f"{REDDIT_BASE_URL}/r/{subreddit}/new/.rss?limit={capped}"
        entries = self._fetch_rss(url)
        posts = [
            p
            for entry in entries
            if (p := _parse_atom_entry(entry, subreddit)) is not None
        ]
        self.logger.info("Fetched %s posts from r/%s.", len(posts), subreddit)
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
        capped = max(1, min(limit, 100))
        url = (
            f"{REDDIT_BASE_URL}/r/{subreddit}/search.rss"
            f"?q={quote_plus(keyword)}&restrict_sr=on&sort=new&t=week&limit={capped}"
        )
        entries = self._fetch_rss(url)
        posts = [
            p
            for entry in entries
            if (p := _parse_atom_entry(entry, subreddit)) is not None
        ]
        self.logger.info(
            "Keyword search fetched %s posts from r/%s for '%s'.",
            len(posts),
            subreddit,
            keyword,
        )
        return posts
