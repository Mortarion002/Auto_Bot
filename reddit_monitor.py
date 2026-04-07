from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import Settings, load_settings
from logger import setup_logger
from notifier import TelegramNotifier
from reddit_db import RedditDatabase
from reddit_scraper import DEFAULT_POSTS_PER_SUBREDDIT, RedditPost, RedditScraper
from reddit_scorer import DIRECT_KEYWORDS, TARGET_SUBREDDITS, RedditLead, rank_posts

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency may be missing in tests
    def load_dotenv(*_: Any, **__: Any) -> bool:
        return False


REDDIT_DB_FILENAME = "reddit_monitor.db"
MAX_HIGH_PRIORITY_ITEMS = 5
MAX_WORTH_READING_ITEMS = 5


def current_timestamp(settings: Settings) -> str:
    return datetime.now(settings.zoneinfo()).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elvan Reddit monitor")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram sends and DB writes.")
    return parser


def build_digest_message(
    settings: Settings,
    *,
    leads: list[RedditLead],
    scanned_count: int,
    matched_count: int,
    new_count: int,
    scanned_subreddit_count: int,
) -> str:
    zone = settings.zoneinfo()
    now = datetime.now(zone)
    next_digest_time = datetime.strptime(settings.daily_report_time, "%H:%M").time()
    next_digest = datetime.combine(
        now.date() + timedelta(days=1),
        next_digest_time,
        tzinfo=zone,
    )

    high_priority = [lead for lead in leads if lead.priority == "high"][:MAX_HIGH_PRIORITY_ITEMS]
    worth_reading = [lead for lead in leads if lead.priority == "medium"][:MAX_WORTH_READING_ITEMS]

    lines = [
        f"Elvan Reddit Monitor - {now.strftime('%B %d, %Y')}",
        "",
        f"High Priority ({len(high_priority)} posts)",
    ]

    if high_priority:
        for lead in high_priority:
            lines.extend(_format_lead_lines(lead))
    else:
        lines.append("- No high-priority Reddit leads today.")

    lines.extend(
        [
            "",
            f"Worth Reading ({len(worth_reading)} posts)",
        ]
    )

    if worth_reading:
        for lead in worth_reading:
            lines.extend(_format_lead_lines(lead))
    else:
        lines.append("- No medium-priority Reddit leads today.")

    lines.extend(
        [
            "",
            f"Total scanned: {scanned_count} posts across {scanned_subreddit_count} subreddits",
            f"Keyword matches today: {matched_count}",
            f"New (not seen before): {new_count}",
            "",
            f"Next digest: {next_digest.strftime('%B %d, %Y at %H:%M')}",
        ]
    )
    return "\n".join(lines)


def _format_lead_lines(lead: RedditLead) -> list[str]:
    return [
        f'- r/{lead.post.subreddit} - "{lead.post.title}"',
        (
            f"  Keyword: {lead.primary_keyword} | "
            f"{lead.post.upvotes} upvotes | {lead.post.comment_count} comments"
        ),
        f"  Link: {lead.post.post_url}",
    ]


def _dedupe_posts(posts: list[RedditPost]) -> list[RedditPost]:
    unique_posts: dict[str, RedditPost] = {}
    for post in posts:
        unique_posts.setdefault(post.post_id, post)
    return list(unique_posts.values())


def run_monitor(
    settings: Settings,
    logger: Any,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    db_path = settings.base_dir / REDDIT_DB_FILENAME
    db = RedditDatabase(db_path, logger)
    started_at = current_timestamp(settings)
    run_id = db.start_run(started_at)

    scanned_count = 0
    matched_count = 0
    new_count = 0
    high_priority_count = 0
    digest_sent = False
    errors: list[str] = []

    try:
        scraper = RedditScraper(settings, logger)
        scrape_result = scraper.scan_subreddits(
            TARGET_SUBREDDITS,
            posts_per_subreddit=DEFAULT_POSTS_PER_SUBREDDIT,
        )
        errors.extend(scrape_result.errors)
        all_posts = _dedupe_posts(scrape_result.posts)
        ranked_leads = rank_posts(all_posts)

        if not ranked_leads:
            logger.info(
                "No leads found in subreddit-new scan; running direct keyword search fallback."
            )
            keyword_result = scraper.search_keywords(
                TARGET_SUBREDDITS,
                DIRECT_KEYWORDS,
            )
            errors.extend(keyword_result.errors)
            all_posts = _dedupe_posts(all_posts + keyword_result.posts)
            ranked_leads = rank_posts(all_posts)

        scanned_count = len(all_posts)
        matched_count = len(ranked_leads)
        new_leads = [lead for lead in ranked_leads if not db.has_seen(lead.post.post_id)]
        surfaced_leads = [lead for lead in new_leads if lead.priority != "low"]

        new_count = len(new_leads)
        high_priority_count = len([lead for lead in surfaced_leads if lead.priority == "high"])

        message = build_digest_message(
            settings,
            leads=surfaced_leads,
            scanned_count=scanned_count,
            matched_count=matched_count,
            new_count=new_count,
            scanned_subreddit_count=len(scrape_result.per_subreddit_counts),
        )
        logger.info("Reddit digest message:\n%s", message)

        if not dry_run:
            if new_leads:
                db.mark_many_seen(new_leads, current_timestamp(settings))
            digest_sent = notifier.send_alert(message)

        return 0
    except Exception as exc:
        errors.append(str(exc))
        logger.exception("Reddit monitor run failed.")
        return 1
    finally:
        db.finish_run(
            run_id,
            finished_at=current_timestamp(settings),
            posts_scanned=scanned_count,
            matches_found=matched_count,
            new_matches=new_count,
            high_priority_count=high_priority_count,
            digest_sent=digest_sent,
            errors=" | ".join(errors) if errors else None,
        )
        db.close()


def main(argv: list[str] | None = None) -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings(Path(__file__).resolve().parent)
    settings.dry_run = settings.dry_run or bool(args.dry_run)
    logger = setup_logger(settings)
    notifier = TelegramNotifier(settings, logger)
    return run_monitor(settings, logger, notifier, dry_run=settings.dry_run)


if __name__ == "__main__":
    sys.exit(main())
