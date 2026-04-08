from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ai import AnthropicContentGenerator
from config import Settings
from db import Database
from models import DiscoveredPost
from notifier import TelegramNotifier
from reddit_scraper import DEFAULT_POSTS_PER_SUBREDDIT, RedditScraper
from reddit_scorer import DIRECT_KEYWORDS, TARGET_SUBREDDITS, RedditLead, rank_posts
from searcher import XSearcher
from session import BrowserSession


X_EXCERPT_LIMIT = 100
REPLY_DRAFT_LIMIT = 280
REDDIT_HIGH_PRIORITY_LIMIT = 5
REDDIT_WORTH_READING_LIMIT = 5


class QueueBuilder:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        logger: Any,
        notifier: TelegramNotifier,
    ):
        self.settings = settings
        self.db = db
        self.logger = logger
        self.notifier = notifier
        self.searcher = XSearcher(settings, db, logger)
        self.generator = AnthropicContentGenerator(settings, logger)
        self._run_errors: list[str] = []
        self._posts_discovered_count = 0
        self._searches_run_count = 0
        self._dry_run = False

    def run(self, *, dry_run: bool = False) -> int:
        started_at = self._timestamp()
        run_id: int | None = None
        if not dry_run:
            run_id = self.db.start_run("build-queue", started_at)

        self._dry_run = dry_run
        original_client = self.generator.client
        if dry_run:
            self.generator.client = None
        self._run_errors = []
        self._posts_discovered_count = 0
        self._searches_run_count = 0

        posts_discovered: list[DiscoveredPost] = []
        reply_drafts: list[dict[str, Any]] = []
        post_ideas: list[dict[str, Any]] = []
        reddit_leads: list[dict[str, Any]] = []
        queue_sent = False
        stop_reason: str | None = None

        try:
            posts_discovered = self._collect_x_posts(dry_run=dry_run)
            self._posts_discovered_count = len(posts_discovered)
            self.logger.info(
                "X research completed with %s ranked posts.",
                self._posts_discovered_count,
            )

            reddit_leads = self._run_reddit_scan()
            reply_drafts = self._generate_drafts(posts_discovered, dry_run=dry_run)
            post_ideas = self._generate_post_ideas(dry_run=dry_run)

            self._send_queue(
                reply_drafts,
                post_ideas,
                reddit_leads,
                dry_run=dry_run,
            )
            queue_sent = not dry_run

            self.logger.info(
                "Queue build finished: %s posts discovered, %s reply drafts, %s post ideas, %s reddit leads.",
                self._posts_discovered_count,
                len(reply_drafts),
                len(post_ideas),
                len(reddit_leads),
            )
            return 0
        except Exception as exc:
            stop_reason = str(exc)
            self._run_errors.append(str(exc))
            self.logger.exception("Queue build failed.")
            return 1
        finally:
            if dry_run:
                self.generator.client = original_client
            if not dry_run and run_id is not None:
                try:
                    self.db.log_queue_run(
                        run_at=started_at,
                        posts_discovered=self._posts_discovered_count,
                        drafts_generated=len(reply_drafts),
                        post_ideas_generated=len(post_ideas),
                        reddit_leads=len(reddit_leads),
                        queue_sent=queue_sent,
                        errors=" | ".join(self._run_errors) if self._run_errors else None,
                    )
                finally:
                    self.db.finish_run(
                        run_id,
                        finished_at=self._timestamp(),
                        posts_found=self._posts_discovered_count,
                        searches_run=self._searches_run_count,
                        stop_reason=stop_reason,
                        errors=" | ".join(self._run_errors) if self._run_errors else None,
                    )

    def _collect_x_posts(self, *, dry_run: bool) -> list[DiscoveredPost]:
        session = BrowserSession(self.settings, self.logger)
        try:
            try:
                health = session.check_health()
            except Exception as exc:
                if dry_run:
                    self.logger.warning("Dry-run X browser session unavailable: %s", exc)
                    return []
                raise RuntimeError(f"Browser session failed: {exc}") from exc

            if not health.ok:
                if dry_run:
                    self.logger.warning(
                        "Dry-run X browser session unavailable: %s",
                        health.reason,
                    )
                    return []
                raise RuntimeError(health.reason or "Could not confirm a logged-in X session.")

            page = session.get_page()
            self._searches_run_count = len(self.settings.keywords)
            return self._run_x_search(page)
        finally:
            session.close()

    def _run_x_search(self, page: Any) -> list[DiscoveredPost]:
        candidates: dict[str, DiscoveredPost] = {}

        for keyword in self.settings.keywords:
            try:
                live_posts = self.searcher._filter_and_score_posts(  # noqa: SLF001
                    self.searcher._search_keyword(page, keyword, "live"),  # noqa: SLF001
                    record_seen=not self._dry_run,
                )
                merged = {post.post_id: post for post in live_posts}

                if len(live_posts) < self.settings.min_valid_posts_before_top_fallback:
                    top_posts = self.searcher._filter_and_score_posts(  # noqa: SLF001
                        self.searcher._search_keyword(page, keyword, "top"),  # noqa: SLF001
                        record_seen=not self._dry_run,
                    )
                    for post in top_posts:
                        merged.setdefault(post.post_id, post)

                for post in merged.values():
                    existing = candidates.get(post.post_id)
                    if existing is None or post.score > existing.score:
                        candidates[post.post_id] = post
            except Exception as exc:
                message = f"X search failed for keyword '{keyword}': {exc}"
                self.logger.warning(message)
                self._run_errors.append(message)

        ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
        return ranked

    def _run_reddit_scan(self) -> list[dict[str, Any]]:
        try:
            scraper = RedditScraper(self.settings, self.logger)
            scan_result = scraper.scan_subreddits(
                TARGET_SUBREDDITS,
                posts_per_subreddit=DEFAULT_POSTS_PER_SUBREDDIT,
            )
            if scan_result.errors:
                self._run_errors.extend(scan_result.errors)

            all_posts = self._dedupe_reddit_posts(scan_result.posts)
            ranked_leads = rank_posts(all_posts)

            if not ranked_leads:
                self.logger.info(
                    "No Reddit leads found in subreddit scan; running keyword fallback."
                )
                keyword_result = scraper.search_keywords(
                    TARGET_SUBREDDITS,
                    DIRECT_KEYWORDS,
                )
                if keyword_result.errors:
                    self._run_errors.extend(keyword_result.errors)
                all_posts = self._dedupe_reddit_posts(all_posts + keyword_result.posts)
                ranked_leads = rank_posts(all_posts)

            surfaced_leads = [
                self._reddit_lead_to_dict(lead)
                for lead in ranked_leads
                if lead.priority in {"high", "medium"}
            ]
            self.logger.info("Reddit scan produced %s surfaced leads.", len(surfaced_leads))
            return surfaced_leads
        except Exception as exc:
            message = f"Reddit scan failed: {exc}"
            self.logger.warning(message)
            self._run_errors.append(message)
            return []

    def _generate_drafts(
        self,
        posts: list[DiscoveredPost],
        *,
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        drafts: list[dict[str, Any]] = []
        limit = max(0, self.settings.queue_max_reply_drafts)

        for post in posts[:limit]:
            if self.db.has_commented(post.post_id):
                self.logger.info(
                    "Skipping post %s because it already exists in commented_posts.",
                    post.post_id,
                )
                continue

            try:
                draft = self.generator.generate_comment(post, dry_run=dry_run)
            except Exception as exc:
                message = f"Reply draft generation failed for {post.post_id}: {exc}"
                self.logger.warning(message)
                self._run_errors.append(message)
                continue

            if draft.validation_errors:
                reason = "; ".join(draft.validation_errors)
                self.logger.warning(
                    "Skipping post %s because validation failed: %s",
                    post.post_id,
                    reason,
                )
                continue

            draft_text = self._squash_whitespace(draft.text)
            if self._contains_getelvan_link(draft_text):
                self.logger.warning(
                    "Skipping post %s because the reply draft contains a getelvan.com link.",
                    post.post_id,
                )
                continue

            drafts.append(
                {
                    "post_id": post.post_id,
                    "author_handle": post.author_handle.lstrip("@"),
                    "post_text_excerpt": self._truncate_text(
                        self._squash_whitespace(post.text),
                        X_EXCERPT_LIMIT,
                    ),
                    "score": post.score,
                    "likes": post.likes,
                    "replies": post.replies,
                    "draft_comment": self._truncate_text(draft_text, REPLY_DRAFT_LIMIT),
                    "post_url": post.post_url,
                }
            )

        return drafts

    def _generate_post_ideas(self, *, dry_run: bool) -> list[dict[str, Any]]:
        ideas: list[dict[str, Any]] = []
        count = max(0, self.settings.queue_max_post_ideas)
        topics = self.settings.topic_rotation
        if not topics or count <= 0:
            if not topics:
                self.logger.warning("No topic rotation configured; skipping post ideas.")
            return ideas

        if dry_run:
            cursor = self.db.get_int_state("topic_cursor", 0)
            topic_entries = [
                (
                    topics[(cursor + offset) % len(topics)],
                    cursor + offset + 1,
                    (cursor + offset + 1) % 3 == 0,
                )
                for offset in range(count)
            ]
        else:
            topic_entries = []
            for _ in range(count):
                topic_entries.append(
                    self.db.get_next_topic(
                        topics,
                        updated_at=self._timestamp(),
                        advance=True,
                    )
                )

        for topic_category, generation_number, allow_elvan_reference in topic_entries:
            try:
                draft = self.generator.generate_standalone_post(
                    topic_category,
                    allow_elvan_reference=allow_elvan_reference,
                    dry_run=dry_run,
                )
            except Exception as exc:
                message = f"Standalone post generation failed for {topic_category}: {exc}"
                self.logger.warning(message)
                self._run_errors.append(message)
                continue

            if draft.validation_errors:
                reason = "; ".join(draft.validation_errors)
                self.logger.warning(
                    "Skipping post idea %s because validation failed: %s",
                    topic_category,
                    reason,
                )
                continue

            draft_text = self._squash_whitespace(draft.text)
            if self._contains_getelvan_link(draft_text):
                self.logger.warning(
                    "Skipping post idea %s because it contains a getelvan.com link.",
                    topic_category,
                )
                continue

            ideas.append(
                {
                    "topic_category": topic_category,
                    "generation_number": generation_number,
                    "draft_post_text": self._truncate_text(draft_text, REPLY_DRAFT_LIMIT),
                }
            )

        return ideas

    def _send_queue(
        self,
        reply_drafts: list[dict[str, Any]],
        post_ideas: list[dict[str, Any]],
        reddit_leads: list[dict[str, Any]],
        *,
        dry_run: bool,
    ) -> None:
        messages: list[str] = [
            self._build_header_message(len(reply_drafts), len(post_ideas)),
        ]

        if self._posts_discovered_count == 0:
            messages.append("No X posts found today. Try again tomorrow.")

        for index, draft in enumerate(reply_drafts, start=1):
            messages.append(
                self._format_reply_message(
                    index=index,
                    total=len(reply_drafts),
                    draft=draft,
                )
            )

        if post_ideas:
            messages.append(self._format_post_ideas_message(post_ideas))

        reddit_message = self._format_reddit_leads_message(reddit_leads)
        if reddit_message is not None:
            messages.append(reddit_message)

        messages.append(self._build_footer_message())

        for message in messages:
            self._deliver_message(message, dry_run=dry_run)

    def _deliver_message(self, message: str, *, dry_run: bool) -> None:
        if dry_run:
            self.logger.info("%s", message)
            return

        if not self.notifier.send_alert(message):
            raise RuntimeError("Failed to send queue message to Telegram.")

    def _build_header_message(self, reply_count: int, post_idea_count: int) -> str:
        now = datetime.now(self.settings.zoneinfo())
        return (
            f"🎯 Elvan X Queue — {now.strftime('%B %d, %Y')}\n"
            f"📬 {self._posts_discovered_count} posts discovered | {reply_count} reply drafts | {post_idea_count} post ideas\n"
            f"⏰ Generated at {now.strftime('%H:%M')}\n\n"
            "Review each draft below. Tap the link to open the post, paste the reply, post manually."
        )

    def _format_reply_message(self, *, index: int, total: int, draft: dict[str, Any]) -> str:
        return (
            f"━━━ REPLY {index} of {total} ━━━\n"
            f"👤 @{draft['author_handle']}\n"
            f"📌 \"{draft['post_text_excerpt']}\"\n"
            f"⭐ Score: {self._format_score(draft['score'])} | 👍 {draft['likes']} | 💬 {draft['replies']}\n\n"
            f"✍️ Draft reply:\n"
            f"\"{draft['draft_comment']}\"\n\n"
            f"🔗 {draft['post_url']}"
        )

    def _format_post_ideas_message(self, post_ideas: list[dict[str, Any]]) -> str:
        lines = ["━━━ POST IDEAS FOR TODAY ━━━", ""]
        for index, idea in enumerate(post_ideas, start=1):
            lines.extend(
                [
                    f"💡 Idea {index} — {idea['topic_category']}",
                    f"\"{idea['draft_post_text']}\"",
                    "",
                ]
            )
        lines.append("Post any of these manually on X today.")
        return "\n".join(lines)

    def _format_reddit_leads_message(self, reddit_leads: list[dict[str, Any]]) -> str | None:
        if not reddit_leads:
            return None

        high_priority = [
            lead for lead in reddit_leads if lead["priority"] == "high"
        ][:REDDIT_HIGH_PRIORITY_LIMIT]
        worth_reading = [
            lead for lead in reddit_leads if lead["priority"] == "medium"
        ][:REDDIT_WORTH_READING_LIMIT]

        if not high_priority and not worth_reading:
            return None

        lines = ["━━━ REDDIT LEADS TODAY ━━━", ""]
        if high_priority:
            lines.append(f"🔴 High Priority ({len(high_priority)})")
            for lead in high_priority:
                lines.extend(self._format_reddit_lead_lines(lead))

        if worth_reading:
            if high_priority:
                lines.append("")
            lines.append(f"🟡 Worth Reading ({len(worth_reading)})")
            for lead in worth_reading:
                lines.extend(self._format_reddit_lead_lines(lead))

        lines.append("")
        lines.append("Consider replying manually on Reddit to high priority leads.")
        return "\n".join(lines)

    def _format_reddit_lead_lines(self, lead: dict[str, Any]) -> list[str]:
        return [
            f"• r/{lead['subreddit']} — \"{lead['post_title']}\"",
            f"  {lead['upvotes']} upvotes | {lead['comments']} comments",
            f"  🔗 {lead['url']}",
        ]

    def _build_footer_message(self) -> str:
        now = datetime.now(self.settings.zoneinfo())
        return (
            f"✅ Queue complete — {now.strftime('%B %d, %Y')}\n"
            "📊 Next stats report: 22:05"
        )

    def _reddit_lead_to_dict(self, lead: RedditLead) -> dict[str, Any]:
        return {
            "subreddit": lead.post.subreddit,
            "post_title": lead.post.title,
            "upvotes": lead.post.upvotes,
            "comments": lead.post.comment_count,
            "url": lead.post.post_url,
            "priority": lead.priority,
            "score": lead.score,
            "primary_keyword": lead.primary_keyword,
        }

    def _dedupe_reddit_posts(self, posts: list[Any]) -> list[Any]:
        unique_posts: dict[str, Any] = {}
        for post in posts:
            unique_posts.setdefault(post.post_id, post)
        return list(unique_posts.values())

    @staticmethod
    def _squash_whitespace(text: str) -> str:
        return " ".join(text.split()).strip()

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        cleaned = QueueBuilder._squash_whitespace(text)
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit]

    @staticmethod
    def _contains_getelvan_link(text: str) -> bool:
        return "getelvan.com" in text.lower()

    @staticmethod
    def _format_score(value: float) -> str:
        return f"{value:.2f}"

    def _timestamp(self) -> str:
        return datetime.now(self.settings.zoneinfo()).isoformat()
