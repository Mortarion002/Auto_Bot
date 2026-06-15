from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Settings, load_settings
from hn_scraper import HNPost, HNScraper
from logger import setup_logger
from neon_store import NeonStore
from notifier import TelegramNotifier
from ph_scraper import PHPost, PHScraper
from signal_filter import passes_keyword_filter, score_signal

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_: Any, **__: Any) -> bool:
        return False


MAX_HOT_IN_DIGEST = 5
MAX_MEDIUM_IN_DIGEST = 5
WORKFLOW_NAME = "signal-monitor-hn-ph"
SOURCE_SYSTEM = "signal_monitor"


def _hn_to_signal(post: HNPost) -> dict[str, Any]:
    return {
        "dedupe_key": f"hn:{post.object_id}",
        "source": "HackerNews",
        "external_id": post.object_id,
        "title": post.title,
        "body": post.body,
        "url": post.url,
        "author": post.author,
        "upvotes": post.points,
        "comments_count": post.num_comments,
        "occurred_at": post.created_at.isoformat(),
        "score": 0.0,
        "tier": "low",
    }


def _ph_to_signal(post: PHPost) -> dict[str, Any]:
    return {
        "dedupe_key": f"ph:{post.ph_id}",
        "source": "ProductHunt",
        "external_id": post.ph_id,
        "title": post.title,
        "body": post.body,
        "url": post.url,
        "author": None,
        "upvotes": post.votes,
        "comments_count": post.comments_count,
        "occurred_at": post.created_at.isoformat(),
        "score": 0.0,
        "tier": "low",
    }


def _to_neon_row(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "dedupe_key": signal["dedupe_key"],
        "source": signal["source"].lower().replace(" ", ""),
        "source_system": SOURCE_SYSTEM,
        "workflow": WORKFLOW_NAME,
        "external_id": signal.get("external_id"),
        "title": signal["title"],
        "body": signal.get("body") or None,
        "url": signal.get("url") or None,
        "author": signal.get("author") or None,
        "subreddit": None,
        "matched_keyword": None,
        "intent": None,
        "urgency": None,
        "priority": signal["tier"],
        "tool_mentioned": None,
        "pain_point": None,
        "elvan_angle": None,
        "draft_reply": None,
        "score": signal["score"],
        "base_score": signal["score"],
        "boosted_score": signal["score"],
        "likes": None,
        "replies": None,
        "reposts": None,
        "comments_count": signal.get("comments_count"),
        "upvotes": signal.get("upvotes"),
        "alerted": signal["tier"] == "hot",
        "hot_lead": signal["tier"] == "hot",
        "occurred_at": signal.get("occurred_at"),
        "metadata": {"kind": "signal_hn_ph", "source_detail": signal["source"]},
    }


def _build_digest(
    settings: Settings,
    *,
    hot: list[dict[str, Any]],
    medium: list[dict[str, Any]],
    total_scanned: int,
    hn_count: int,
    ph_count: int,
    keyword_matches: int,
    new_count: int,
) -> str:
    zone = settings.zoneinfo()
    now = datetime.now(zone)

    lines = [
        f"Elvan Signal Monitor — HN + Product Hunt — {now.strftime('%B %d, %Y')}",
        "",
        f"Hot Leads ({len(hot)} posts)",
    ]

    if hot:
        for item in hot[:MAX_HOT_IN_DIGEST]:
            lines.extend(_format_signal(item))
    else:
        lines.append("  No hot leads today.")

    lines.extend(["", f"Worth Reading ({len(medium)} posts)"])

    if medium:
        for item in medium[:MAX_MEDIUM_IN_DIGEST]:
            lines.extend(_format_signal(item))
    else:
        lines.append("  No medium-priority signals today.")

    lines.extend([
        "",
        f"Total scanned: {total_scanned} (HN: {hn_count} | PH: {ph_count})",
        f"Keyword matches: {keyword_matches} | New today: {new_count}",
    ])

    return "\n".join(lines)


def _format_signal(item: dict[str, Any]) -> list[str]:
    tag = "HN" if item["source"] == "HackerNews" else "PH"
    engagement = (
        f"Points: {item['upvotes']} | Comments: {item['comments_count']}"
        if item["source"] == "HackerNews"
        else f"Votes: {item['upvotes']} | Comments: {item['comments_count']}"
    )
    return [
        "",
        f"[{tag}] {item['title']}  (Score: {item['score']})",
        f"  {engagement}",
        f"  Link: {item['url']}",
    ]


def run_monitor(
    settings: Settings,
    logger: Any,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    started_at = datetime.now(settings.zoneinfo()).isoformat()
    neon_store = NeonStore(settings, logger)
    status = "success"
    stop_reason: str | None = None
    errors: list[str] = []
    hn_count = 0
    ph_count = 0
    keyword_matches = 0
    new_count = 0
    hot: list[dict[str, Any]] = []
    medium: list[dict[str, Any]] = []
    new_signals: list[dict[str, Any]] = []

    try:
        # --- Scrape ---
        hn_posts: list[HNPost] = []
        try:
            hn_posts = HNScraper(settings, logger).fetch_all()
            hn_count = len(hn_posts)
            logger.info("HN: %d total posts fetched.", hn_count)
        except Exception as exc:
            errors.append(f"HN scrape failed: {exc}")
            logger.error("HN scrape failed: %s", exc)

        ph_posts: list[PHPost] = []
        try:
            ph_posts = PHScraper(settings, logger).fetch_all()
            ph_count = len(ph_posts)
            logger.info("PH: %d total posts fetched.", ph_count)
        except Exception as exc:
            errors.append(f"PH scrape failed: {exc}")
            logger.error("PH scrape failed: %s", exc)

        all_signals = [_hn_to_signal(p) for p in hn_posts] + [_ph_to_signal(p) for p in ph_posts]

        # --- Keyword filter ---
        filtered = [
            s for s in all_signals
            if passes_keyword_filter(s["title"], s["body"] or "", s["url"] or "", s["source"])
        ]
        keyword_matches = len(filtered)
        logger.info("Keyword filter: %d/%d posts passed.", keyword_matches, hn_count + ph_count)

        # --- Neon dedup ---
        existing_keys: set[str] = set()
        if neon_store.enabled:
            try:
                existing_keys = neon_store.get_existing_dedupe_keys(
                    [s["dedupe_key"] for s in filtered]
                )
                logger.info(
                    "Neon dedup: %d already seen, %d new.",
                    len(existing_keys),
                    keyword_matches - len(existing_keys),
                )
            except Exception as exc:
                logger.warning("Neon dedup check failed — will process all: %s", exc)

        new_signals = [s for s in filtered if s["dedupe_key"] not in existing_keys]
        new_count = len(new_signals)

        # --- Score (rule-based, no AI) ---
        for signal in new_signals:
            signal["score"], signal["tier"] = score_signal(
                signal["title"],
                signal["body"] or "",
                upvotes=signal["upvotes"],
                comments_count=signal["comments_count"],
                source=signal["source"],
            )

        hot = [s for s in new_signals if s["tier"] == "hot"]
        medium = [s for s in new_signals if s["tier"] == "medium"]
        logger.info(
            "Tiers — hot: %d, medium: %d, low: %d",
            len(hot), len(medium), new_count - len(hot) - len(medium),
        )

        # --- Build digest ---
        message = _build_digest(
            settings,
            hot=hot,
            medium=medium,
            total_scanned=hn_count + ph_count,
            hn_count=hn_count,
            ph_count=ph_count,
            keyword_matches=keyword_matches,
            new_count=new_count,
        )
        logger.info("Signal digest:\n%s", message)

        if not dry_run:
            # Upsert to Neon
            if neon_store.enabled and new_signals:
                try:
                    saved = neon_store.record_signal_rows([_to_neon_row(s) for s in new_signals])
                    logger.info("Neon: upserted %d signal rows.", saved)
                except Exception as exc:
                    errors.append(f"Neon upsert failed: {exc}")
                    logger.warning("Neon upsert failed: %s", exc)

            # Send Telegram digest
            sent = notifier.send_alert(message)
            if not sent:
                archived = notifier.persist_failed_message("signal-digest", message)
                error = "Failed to send signal digest Telegram message."
                errors.append(error)
                logger.error("%s Saved a copy to %s.", error, archived)
                status = "failed"
                stop_reason = error
                return 1

        return 0

    except Exception as exc:
        status = "failed"
        stop_reason = str(exc)
        errors.append(str(exc))
        logger.exception("Signal monitor run failed.")
        return 1

    finally:
        finished_at = datetime.now(settings.zoneinfo()).isoformat()
        if not dry_run and neon_store.enabled:
            try:
                neon_store.record_workflow_run(
                    source_system=SOURCE_SYSTEM,
                    workflow=WORKFLOW_NAME,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=status,
                    posts_scanned=hn_count + ph_count,
                    matches_found=keyword_matches,
                    new_matches=new_count,
                    high_priority_count=len(hot),
                    digest_sent=(status == "success"),
                    stop_reason=stop_reason,
                    errors=" | ".join(errors) if errors else None,
                    metadata={"hn_count": hn_count, "ph_count": ph_count},
                )
            except Exception as exc:
                logger.warning("Neon workflow run log failed: %s", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elvan HN + Product Hunt signal monitor")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram sends and DB writes.")
    return parser


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
