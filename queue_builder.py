from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
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
from searcher import XSearcher, compute_engagement_score, compute_relevance_bonus
from session import BrowserSession


X_EXCERPT_LIMIT = 100
REPLY_DRAFT_LIMIT = 260
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
        self._discovery_summary: str | None = None
        self._discovery_notes: list[str] = []
        self._keyword_diagnostics: list[dict[str, Any]] = []

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
        self._discovery_summary = None
        self._discovery_notes = []
        self._keyword_diagnostics = []

        posts_discovered: list[DiscoveredPost] = []
        x_findings: list[dict[str, Any]] = []
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
            x_findings = self._build_x_findings(posts_discovered, dry_run=dry_run)

            queue_sent = self._send_queue(
                x_findings,
                reddit_leads,
                dry_run=dry_run,
            )
            if not dry_run:
                if queue_sent:
                    self.db.mark_posts_seen(
                        [finding["post_id"] for finding in x_findings],
                        self._timestamp(),
                    )
                else:
                    stop_reason = "Failed to deliver one or more queue messages to Telegram."
                    self._run_errors.append(stop_reason)
                    self.logger.error(
                        "Research digest was generated but not fully delivered to Telegram."
                    )
                    return 1

            self.logger.info(
                "Research digest finished: %s posts discovered, %s X findings, %s response suggestions, %s reddit leads.",
                self._posts_discovered_count,
                len(x_findings),
                self._count_response_suggestions(x_findings),
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
                        drafts_generated=self._count_response_suggestions(x_findings),
                        legacy_post_ideas_generated=0,
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
        selected_keywords = self._select_queue_keywords(dry_run=dry_run)
        self.logger.info(
            "Starting X discovery across %s selected keywords: %s",
            len(selected_keywords),
            ", ".join(selected_keywords),
        )
        session = BrowserSession(self.settings, self.logger)
        try:
            try:
                health = session.check_health()
            except Exception as exc:
                return self._handle_browser_unavailable(str(exc), dry_run=dry_run)

            if not health.ok:
                return self._handle_browser_unavailable(
                    health.reason or "Could not confirm a logged-in X session.",
                    dry_run=dry_run,
                )

            page = session.get_page()
            self._searches_run_count = len(selected_keywords)
            posts = self._run_x_search(page, selected_keywords)
            self._posts_discovered_count = len(posts)
            self._discovery_summary = self._build_discovery_summary()
            return posts
        finally:
            session.close()

    def _run_x_search(self, page: Any, keywords: list[str]) -> list[DiscoveredPost]:
        candidates: dict[str, DiscoveredPost] = {}

        for keyword in keywords:
            try:
                live_scraped_posts, live_search_stats = self.searcher.search_keyword_with_stats(
                    page,
                    keyword,
                    "live",
                )
                live_posts, live_filter_stats = self.searcher.filter_and_score_posts_with_stats(
                    live_scraped_posts,
                    record_seen=not self._dry_run,
                    min_likes_override=self.settings.min_likes_research,
                )
                merged = {post.post_id: post for post in live_posts}
                top_search_stats = {"raw_articles": 0, "scraped_posts": 0}
                top_filter_stats = self._empty_filter_stats()

                if len(live_posts) < self.settings.min_valid_posts_before_top_fallback:
                    top_scraped_posts, top_search_stats = self.searcher.search_keyword_with_stats(
                        page,
                        keyword,
                        "top",
                    )
                    top_posts, top_filter_stats = self.searcher.filter_and_score_posts_with_stats(
                        top_scraped_posts,
                        record_seen=not self._dry_run,
                        min_likes_override=self.settings.min_likes_research,
                    )
                    for post in top_posts:
                        merged.setdefault(post.post_id, post)

                for post in merged.values():
                    existing = candidates.get(post.post_id)
                    if existing is None or post.score > existing.score:
                        candidates[post.post_id] = post

                diagnostic = self._build_keyword_diagnostic(
                    keyword=keyword,
                    live_search_stats=live_search_stats,
                    top_search_stats=top_search_stats,
                    live_filter_stats=live_filter_stats,
                    top_filter_stats=top_filter_stats,
                    unique_kept=len(merged),
                )
                self._keyword_diagnostics.append(diagnostic)
                self.logger.info(
                    '[build-queue] Keyword "%s": %s raw articles, %s scraped -> %s passed filter%s (%s dropped: %s)',
                    keyword,
                    diagnostic["raw_articles"],
                    diagnostic["scraped_posts"],
                    diagnostic["passed_filter"],
                    diagnostic["duplicate_suffix"],
                    diagnostic["dropped_count"],
                    diagnostic["reason_breakdown"],
                )
            except Exception as exc:
                message = f"X search failed for keyword '{keyword}': {exc}"
                self.logger.warning(message)
                self._run_errors.append(message)

        ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
        return ranked

    def _select_queue_keywords(self, *, dry_run: bool) -> list[str]:
        priority_keywords = self._dedupe_keywords(self.settings.priority_keywords)
        rotation_keywords = [
            keyword
            for keyword in self._dedupe_keywords(self.settings.rotation_keywords)
            if keyword not in priority_keywords
        ]

        if not priority_keywords and not rotation_keywords:
            return self._dedupe_keywords(self.settings.keywords)

        batch_size = max(1, self.settings.keyword_batch_size)
        selected_priority = priority_keywords[:batch_size]
        remaining_slots = max(0, batch_size - len(selected_priority))
        rotated_keywords = self.db.get_rotating_keywords(
            rotation_keywords,
            remaining_slots,
            updated_at=self._timestamp(),
            advance=not dry_run,
        )
        selected_keywords = self._dedupe_keywords(selected_priority + rotated_keywords)

        # If the rotation pool is smaller than the remaining slots, backfill from the
        # combined keyword list so the queue still uses the configured batch size.
        if len(selected_keywords) < batch_size:
            fallback_keywords = [
                keyword
                for keyword in self._dedupe_keywords(self.settings.keywords)
                if keyword not in selected_keywords
            ]
            selected_keywords.extend(
                fallback_keywords[: batch_size - len(selected_keywords)]
            )

        return selected_keywords[:batch_size]

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

    def _build_x_findings(
        self,
        posts: list[DiscoveredPost],
        *,
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        limit = max(0, self.settings.queue_max_reply_drafts)

        for post in posts[:limit]:
            response_suggestion: str | None = None

            try:
                draft = self.generator.generate_comment(post, dry_run=dry_run)
            except Exception as exc:
                message = f"Response suggestion generation failed for {post.post_id}: {exc}"
                self.logger.warning(message)
                self._run_errors.append(message)
            else:
                if draft.validation_errors:
                    reason = "; ".join(draft.validation_errors)
                    self.logger.warning(
                        "Suggestion skipped for post %s because validation failed: %s",
                        post.post_id,
                        reason,
                    )
                else:
                    draft_text = self._squash_whitespace(draft.text)
                    if self._contains_getelvan_link(draft_text):
                        self.logger.warning(
                            "Suggestion skipped for post %s because it contains a getelvan.com link.",
                            post.post_id,
                        )
                    else:
                        if len(draft_text) > REPLY_DRAFT_LIMIT:
                            self.logger.info(
                                "Response suggestion %s is %s chars; keeping full validated text because it passed the 280-char validator.",
                                post.post_id,
                                len(draft_text),
                            )
                        response_suggestion = draft_text

            findings.append(
                {
                    "post_id": post.post_id,
                    "author_handle": post.author_handle.lstrip("@"),
                    "keyword": post.keyword,
                    "post_text_excerpt": self._truncate_text(
                        self._squash_whitespace(post.text),
                        X_EXCERPT_LIMIT,
                    ),
                    "score": post.score,
                    "likes": post.likes,
                    "replies": post.replies,
                    "response_suggestion": response_suggestion,
                    "post_url": post.post_url,
                }
            )

        return findings

    def _send_queue(
        self,
        x_findings: list[dict[str, Any]],
        reddit_leads: list[dict[str, Any]],
        *,
        dry_run: bool,
    ) -> bool:
        messages: list[str] = [
            self._build_header_message(x_findings, reddit_leads),
        ]

        if self._posts_discovered_count == 0:
            messages.append("No X conversations met the current filter today.")

        for index, finding in enumerate(x_findings, start=1):
            messages.append(
                self._format_x_finding_message(
                    index=index,
                    total=len(x_findings),
                    finding=finding,
                )
            )

        reddit_message = self._format_reddit_leads_message(reddit_leads)
        if reddit_message is not None:
            messages.append(reddit_message)

        messages.append(self._build_footer_message())

        all_sent = True
        for index, message in enumerate(messages, start=1):
            label = self._queue_message_label(index=index, message=message)
            delivered = self._deliver_message(
                message,
                dry_run=dry_run,
                label=label,
            )
            all_sent = all_sent and delivered
        return all_sent

    def _deliver_message(self, message: str, *, dry_run: bool, label: str) -> bool:
        if dry_run:
            self.logger.info("%s", message)
            return True

        if not self.notifier.send_alert(message):
            archived_path = self.notifier.persist_failed_message(
                f"queue-{label}",
                message,
            )
            self.logger.error(
                "Failed to send queue message '%s' to Telegram. Saved a copy to %s.",
                label,
                archived_path,
            )
            return False
        return True

    @staticmethod
    def _queue_message_label(*, index: int, message: str) -> str:
        first_line = message.splitlines()[0].strip().lower() if message else ""
        if first_line.startswith("x finding"):
            return f"x-finding-{index}"
        if first_line.startswith("reddit leads today"):
            return f"reddit-leads-{index}"
        if first_line.startswith("research digest complete"):
            return f"footer-{index}"
        if first_line.startswith("elvan social research digest"):
            return f"header-{index}"
        return f"message-{index}"

    def _build_header_message(
        self,
        x_findings: list[dict[str, Any]],
        reddit_leads: list[dict[str, Any]],
    ) -> str:
        now = datetime.now(self.settings.zoneinfo())
        suggestion_count = self._count_response_suggestions(x_findings)
        lines = [
            f"Elvan Social Research Digest - {now.strftime('%B %d, %Y')}",
            (
                f"X findings: {len(x_findings)} surfaced"
                f" | response suggestions: {suggestion_count}"
                f" | Reddit leads: {len(reddit_leads)}"
            ),
            f"Generated at {now.strftime('%H:%M')}",
        ]
        if self._discovery_summary:
            lines.append(f"Note: {self._discovery_summary}")
        lines.extend(
            [
                "",
                "Top X conversations and Reddit leads are below.",
            ]
        )
        return "\n".join(lines)

    def _format_x_finding_message(
        self,
        *,
        index: int,
        total: int,
        finding: dict[str, Any],
    ) -> str:
        lines = [
            f"X FINDING {index} of {total}",
            f"@{finding['author_handle']}",
            f"Matched keyword: {finding['keyword']}",
            f"\"{finding['post_text_excerpt']}\"",
            (
                f"Score: {self._format_score(finding['score'])}"
                f" | Likes: {finding['likes']}"
                f" | Replies: {finding['replies']}"
            ),
        ]
        if finding["response_suggestion"]:
            lines.extend(
                [
                    "",
                    "Suggested response angle:",
                    f"\"{finding['response_suggestion']}\"",
                ]
            )
        lines.extend(
            [
                "",
                f"Link: {finding['post_url']}",
            ]
        )
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

        lines = ["REDDIT LEADS TODAY", ""]
        if high_priority:
            lines.append(f"High Priority ({len(high_priority)})")
            for lead in high_priority:
                lines.extend(self._format_reddit_lead_lines(lead))

        if worth_reading:
            if high_priority:
                lines.append("")
            lines.append(f"Worth Reading ({len(worth_reading)})")
            for lead in worth_reading:
                lines.extend(self._format_reddit_lead_lines(lead))

        return "\n".join(lines)

    def _format_reddit_lead_lines(self, lead: dict[str, Any]) -> list[str]:
        return [
            f"- r/{lead['subreddit']} - \"{lead['post_title']}\"",
            f"  {lead['upvotes']} upvotes | {lead['comments']} comments",
            f"  Link: {lead['url']}",
        ]

    def _build_footer_message(self) -> str:
        now = datetime.now(self.settings.zoneinfo())
        return (
            f"Research digest complete - {now.strftime('%B %d, %Y')}\n"
            "Next stats report: 22:05"
        )

    @staticmethod
    def _count_response_suggestions(x_findings: list[dict[str, Any]]) -> int:
        return sum(1 for finding in x_findings if finding["response_suggestion"])

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
        if limit <= 3:
            return cleaned[:limit]
        candidate = cleaned[: limit - 3].rstrip()
        if " " in candidate:
            candidate = candidate.rsplit(" ", 1)[0]
        candidate = candidate.rstrip(" ,;:-")
        if not candidate:
            candidate = cleaned[: limit - 3].rstrip()
        return f"{candidate}..."

    @staticmethod
    def _contains_getelvan_link(text: str) -> bool:
        return "getelvan.com" in text.lower()

    @staticmethod
    def _format_score(value: float) -> str:
        return f"{value:.2f}"

    def _timestamp(self) -> str:
        return datetime.now(self.settings.zoneinfo()).isoformat()

    def _handle_browser_unavailable(
        self,
        reason: str,
        *,
        dry_run: bool,
    ) -> list[DiscoveredPost]:
        if dry_run:
            message = f"Chrome session unavailable: {reason}"
            self.logger.error(
                "Dry-run X browser session unavailable: %s. Using mock posts instead.",
                reason,
            )
            self._run_errors.append(message)
            self._discovery_notes.append(
                "Low discovery: Chrome session unavailable - using mock posts for dry-run formatting."
            )
            mock_posts = self._mock_posts()
            self._posts_discovered_count = len(mock_posts)
            self._discovery_summary = self._build_discovery_summary()
            return mock_posts

        raise RuntimeError(reason)

    @staticmethod
    def _empty_filter_stats() -> dict[str, int]:
        return {
            "input_count": 0,
            "passed": 0,
            "already_seen": 0,
            "own_post": 0,
            "too_old": 0,
            "low_likes": 0,
            "high_likes": 0,
            "irrelevant": 0,
        }

    def _build_keyword_diagnostic(
        self,
        *,
        keyword: str,
        live_search_stats: dict[str, int],
        top_search_stats: dict[str, int],
        live_filter_stats: dict[str, int],
        top_filter_stats: dict[str, int],
        unique_kept: int,
    ) -> dict[str, Any]:
        combined_filter_stats = self._merge_filter_stats(live_filter_stats, top_filter_stats)
        passed_filter = combined_filter_stats["passed"]
        duplicate_count = max(0, passed_filter - unique_kept)
        return {
            "keyword": keyword,
            "raw_articles": live_search_stats["raw_articles"] + top_search_stats["raw_articles"],
            "scraped_posts": live_search_stats["scraped_posts"] + top_search_stats["scraped_posts"],
            "passed_filter": passed_filter,
            "unique_kept": unique_kept,
            "dropped_count": max(0, combined_filter_stats["input_count"] - passed_filter),
            "duplicate_suffix": (
                f", {duplicate_count} duplicate(s) merged" if duplicate_count else ""
            ),
            "reason_breakdown": self._format_reason_breakdown(combined_filter_stats),
        }

    @staticmethod
    def _merge_filter_stats(
        first: dict[str, int],
        second: dict[str, int],
    ) -> dict[str, int]:
        keys = set(first) | set(second)
        return {key: first.get(key, 0) + second.get(key, 0) for key in keys}

    @staticmethod
    def _format_reason_breakdown(stats: dict[str, int]) -> str:
        labels = {
            "too_old": "too old",
            "low_likes": "low likes",
            "high_likes": "high likes",
            "already_seen": "already shared",
            "own_post": "own post",
            "irrelevant": "irrelevant",
        }
        parts = [
            f"{count} {labels[key]}"
            for key, count in (
                ("too_old", stats.get("too_old", 0)),
                ("low_likes", stats.get("low_likes", 0)),
                ("high_likes", stats.get("high_likes", 0)),
                ("already_seen", stats.get("already_seen", 0)),
                ("own_post", stats.get("own_post", 0)),
                ("irrelevant", stats.get("irrelevant", 0)),
            )
            if count
        ]
        return ", ".join(parts) if parts else "no filter drops"

    def _build_discovery_summary(self) -> str | None:
        if self._discovery_notes:
            return self._discovery_notes[0]
        if not self._keyword_diagnostics:
            return None

        zero_keywords = sum(
            1
            for diagnostic in self._keyword_diagnostics
            if diagnostic["unique_kept"] == 0
        )
        if self._posts_discovered_count <= 3:
            if zero_keywords:
                return (
                    f"Low discovery: {zero_keywords} keywords returned 0 results "
                    "(check logs for drop reasons)."
                )
            return (
                f"Low discovery: only {self._posts_discovered_count} unique X posts surfaced "
                "(check logs for drop reasons)."
            )

        if zero_keywords >= max(3, len(self._keyword_diagnostics) // 2):
            return (
                f"Low discovery: {zero_keywords} keywords returned 0 results "
                "(check logs for drop reasons)."
            )
        return None

    @staticmethod
    def _dedupe_keywords(keywords: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            normalized = keyword.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(keyword)
        return ordered

    def _mock_posts(self) -> list[DiscoveredPost]:
        now = datetime.now(timezone.utc)
        mock_specs = [
            (
                "2041800000000000001",
                "https://x.com/cxsignals/status/2041800000000000001",
                "@cxsignals",
                "NPS gets noisy fast when teams ask too early. What timing changes actually improved response quality for you?",
                18,
                7,
                2,
                2,
                "NPS",
            ),
            (
                "2041800000000000002",
                "https://x.com/saasops/status/2041800000000000002",
                "@saasops",
                "CSAT is easy to collect and hard to operationalize. How are people segmenting support feedback without creating another dashboard?",
                14,
                6,
                1,
                4,
                "CSAT",
            ),
            (
                "2041800000000000003",
                "https://x.com/founderloop/status/2041800000000000003",
                "@founderloop",
                "Looking for a Delighted alternative that works better for B2B onboarding feedback. What are founders switching to right now?",
                11,
                5,
                1,
                6,
                "Delighted alternative",
            ),
            (
                "2041800000000000004",
                "https://x.com/retainbetter/status/2041800000000000004",
                "@retainbetter",
                "Churn interviews helped more than another retention dashboard for us. Anyone pairing churn reasons with survey answers in one workflow?",
                16,
                8,
                2,
                3,
                "churn rate",
            ),
            (
                "2041800000000000005",
                "https://x.com/buildsignal/status/2041800000000000005",
                "@buildsignal",
                "#buildinpublic update: we changed when we ask for feedback during onboarding and the answer quality jumped almost immediately.",
                13,
                4,
                1,
                1,
                "#buildinpublic",
            ),
        ]
        return [
            DiscoveredPost(
                post_id=post_id,
                post_url=post_url,
                author_handle=author_handle,
                text=text,
                likes=likes,
                replies=replies,
                reposts=reposts,
                created_at=now - timedelta(hours=hours_ago),
                keyword=keyword,
                search_mode="mock",
                score=compute_engagement_score(
                    likes,
                    replies,
                    reposts,
                    now - timedelta(hours=hours_ago),
                    now=now,
                )
                + compute_relevance_bonus(text, keyword),
            )
            for (
                post_id,
                post_url,
                author_handle,
                text,
                likes,
                replies,
                reposts,
                hours_ago,
                keyword,
            ) in mock_specs
        ]
