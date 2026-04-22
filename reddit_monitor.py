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
HOT_LEAD_THRESHOLD = 8.0

CONVERSION_PHRASES = (
    "alternative",
    "replace",
    "replacement",
    "looking for",
    "recommend",
    "switch",
    "switching",
    "what do you use",
    "anyone using",
    "anyone tried",
    "moved away",
    "moved from",
    "migrated",
    "shut down",
    "shutdown",
)

_HOT_LEAD_PROMPT_TEMPLATE = (
    "You are a community engagement specialist for Elvan (elvan.ai) — a B2B NPS/CSAT/CES "
    "survey SaaS. Elvan is positioned as a direct Delighted replacement (Delighted shuts "
    "down June 30, 2026).\n\n"
    "Write a helpful Reddit comment responding to the post below. Rules:\n"
    "- Sound like a real person, not a company rep\n"
    "- Lead with genuine help or empathy, not a pitch\n"
    "- Mention Elvan naturally only if it fits — never force it\n"
    "- Keep it under 120 words\n"
    "- No emojis, no bullet points, conversational tone\n"
    "- If the post is asking for a tool recommendation, you can suggest Elvan directly\n"
    "- If the post is venting, acknowledge the pain first\n\n"
    "Post title: {title}\n"
    "Post body: {body}\n"
    "Subreddit: {subreddit}"
)


def current_timestamp(settings: Settings) -> str:
    return datetime.now(settings.zoneinfo()).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elvan Reddit monitor")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram sends and DB writes.")
    return parser


def _apply_conversion_intent_boost(lead: RedditLead) -> float:
    full_text = f"{lead.post.title} {lead.post.body}"
    lowered = full_text.lower()
    bonus = 0.0

    has_question = "?" in full_text
    has_conversion = any(phrase in lowered for phrase in CONVERSION_PHRASES)
    if has_question and has_conversion:
        bonus += 25.0

    if "delighted" in lowered:
        bonus += 10.0

    return lead.score + bonus


def _generate_hot_lead_comment(settings: Settings, logger: Any, lead: RedditLead) -> str:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai not installed")

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = _HOT_LEAD_PROMPT_TEMPLATE.format(
        title=lead.post.title,
        body=lead.post.body[:500],
        subreddit=lead.post.subreddit,
    )

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config={"temperature": 0.6, "max_output_tokens": 220},
    )
    return response.text.strip()


def _build_hot_lead_alert(lead: RedditLead, boosted_score: float, comment: str | None) -> str:
    body = lead.post.body
    if len(body) > 300:
        preview = f'"{body[:300]}..."'
    elif body:
        preview = f'"{body}"'
    else:
        preview = f'"{lead.post.title}"'

    if comment:
        draft_line = f"💬 Draft comment:\n{comment}"
    else:
        draft_line = "💬 Draft comment: [Generation failed — reply manually]"

    return "\n".join([
        f"🔥 HOT LEAD — r/{lead.post.subreddit}",
        "",
        f"👤 u/{lead.post.author} · Score: {round(boosted_score)}",
        f"📌 {lead.post.title}",
        "",
        preview,
        "",
        draft_line,
        "",
        f"🔗 {lead.post.post_url}",
        "",
        "─────────────────────",
        "Copy the draft → paste it manually on Reddit",
    ])


def build_digest_message(
    settings: Settings,
    *,
    leads: list[RedditLead],
    scanned_count: int,
    matched_count: int,
    new_count: int,
    scanned_subreddit_count: int,
    hot_lead_post_ids: set[str] | None = None,
) -> str:
    if hot_lead_post_ids is None:
        hot_lead_post_ids = set()

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
            is_hot = lead.post.post_id in hot_lead_post_ids
            lines.extend(_format_lead_lines(lead, is_hot_lead=is_hot))
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
            is_hot = lead.post.post_id in hot_lead_post_ids
            lines.extend(_format_lead_lines(lead, is_hot_lead=is_hot))
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


def _format_lead_lines(lead: RedditLead, *, is_hot_lead: bool = False) -> list[str]:
    title = f"🔥 {lead.post.title}" if is_hot_lead else lead.post.title
    return [
        f'- r/{lead.post.subreddit} - "{title}"',
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


def _send_preserved_message(
    notifier: TelegramNotifier,
    logger: Any,
    *,
    label: str,
    message: str,
    errors: list[str],
) -> bool:
    sent = notifier.send_alert(message)
    if sent:
        return True

    archived_path = notifier.persist_failed_message(label, message)
    error = f"Failed to send {label} Telegram message."
    errors.append(error)
    logger.error("%s Saved a copy to %s.", error, archived_path)
    return False


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
    hot_lead_alerts_sent = 0
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

        # Apply conversion intent boosts and identify hot leads
        boosted_scores: dict[str, float] = {
            lead.post.post_id: _apply_conversion_intent_boost(lead)
            for lead in ranked_leads
        }
        hot_lead_post_ids: set[str] = {
            post_id
            for post_id, score in boosted_scores.items()
            if score >= HOT_LEAD_THRESHOLD
        }
        hot_leads_to_alert = [
            lead for lead in ranked_leads
            if lead.post.post_id in hot_lead_post_ids
            and not db.has_hot_lead_alerted(lead.post.post_id)
        ]

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
            hot_lead_post_ids=hot_lead_post_ids,
        )
        logger.info("Reddit digest message:\n%s", message)

        if not dry_run:
            # Mark seen before sending (idempotent, safe order)
            if new_leads:
                db.mark_many_seen(new_leads, current_timestamp(settings))

            # Send hot lead alerts before regular digest
            for lead in hot_leads_to_alert:
                comment: str | None = None
                try:
                    comment = _generate_hot_lead_comment(settings, logger, lead)
                except Exception as exc:
                    logger.error(
                        "Hot lead comment generation failed for %s: %s",
                        lead.post.post_id,
                        exc,
                    )
                alert_msg = _build_hot_lead_alert(
                    lead, boosted_scores[lead.post.post_id], comment
                )
                sent = _send_preserved_message(
                    notifier,
                    logger,
                    label=f"reddit-hot-lead-{lead.post.post_id}",
                    message=alert_msg,
                    errors=errors,
                )
                if sent:
                    hot_lead_alerts_sent += 1
                    db.mark_hot_lead_alerted(lead.post.post_id)

            digest_sent = _send_preserved_message(
                notifier,
                logger,
                label="reddit-digest",
                message=message,
                errors=errors,
            )
            if not digest_sent:
                return 1

        logger.info("Hot lead alerts sent: %d", hot_lead_alerts_sent)
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
