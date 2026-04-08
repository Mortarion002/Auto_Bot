from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ai import AnthropicContentGenerator
from config import Settings, load_settings
from db import Database
from logger import setup_logger
from notifier import TelegramNotifier
from poster import XPoster
from searcher import XSearcher
from stats_reporter import StatsReporter
from session import BrowserSession

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency may be missing in tests
    def load_dotenv(*_: Any, **__: Any) -> bool:
        return False


def current_timestamp(settings: Settings) -> str:
    return datetime.now(settings.zoneinfo()).isoformat()


def apply_run_jitter(settings: Settings, logger: Any, *, dry_run: bool) -> None:
    if dry_run:
        logger.info("Dry-run mode enabled; skipping start jitter.")
        return
    if settings.run_jitter_max <= 0:
        return
    delay_seconds = random.randint(settings.run_jitter_min, settings.run_jitter_max)
    logger.info("Applying run jitter of %s seconds.", delay_seconds)
    time.sleep(delay_seconds)


def wait_between_comments(settings: Settings, logger: Any, *, dry_run: bool) -> None:
    if dry_run:
        logger.info("Dry-run mode enabled; skipping inter-comment wait.")
        return
    delay_seconds = random.randint(settings.comment_delay_min, settings.comment_delay_max)
    logger.info("Waiting %s seconds before the next comment.", delay_seconds)
    time.sleep(delay_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elvan X agent orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("health-check", "engage", "publish", "daily-report", "stats-report"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--dry-run", action="store_true", help="Avoid live posting.")

    return parser


def maybe_send_limit_alert(
    notifier: TelegramNotifier,
    logger: Any,
    *,
    dry_run: bool,
    reason: str,
) -> None:
    logger.warning(reason)
    if not dry_run:
        notifier.send_alert(f"WARNING: Elvan X agent stopped early. Reason: {reason}")


def build_daily_report_message(
    settings: Settings,
    counts: dict[str, int | str],
    failure_count: int,
    failure_summary: str | None,
) -> str:
    zone = settings.zoneinfo()
    now = datetime.now(zone)
    next_run = datetime.combine(
        (now + timedelta(days=1)).date(),
        datetime.strptime("09:00", "%H:%M").time(),
        tzinfo=zone,
    )
    summary = failure_summary or "none"
    return (
        "Elvan X Agent Daily Report\n"
        f"Date: {now.strftime('%B %d, %Y')}\n\n"
        f"Comments posted: {counts['comments_posted']}/{settings.max_comments_per_day}\n"
        f"Standalone posts: {counts['standalone_posted']}/{settings.max_posts_per_day}\n"
        f"Searches run: {counts['searches_run']}/{settings.max_searches_per_day}\n\n"
        f"Errors: {failure_count} ({summary})\n\n"
        f"Next run: {next_run.strftime('%B %d, %Y %H:%M')}"
    )


def run_health_check(
    settings: Settings,
    logger: Any,
    db: Database,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    started_at = current_timestamp(settings)
    run_id = db.start_run("health-check", started_at)
    stop_reason: str | None = None
    errors: list[str] = []
    session: BrowserSession | None = None

    try:
        session = BrowserSession(settings, logger)
        health = session.check_health()
        if not health.ok:
            stop_reason = health.reason
            logger.error("Health check failed: %s", health.reason)
            if not dry_run:
                notifier.send_alert(
                    f"CRITICAL: Elvan X agent browser session failure. {health.reason}"
                )
            return 1

        logger.info("Health check passed: %s", health.reason)
        return 0
    except Exception as exc:
        stop_reason = str(exc)
        errors.append(str(exc))
        logger.exception("Health check failed unexpectedly.")
        if not dry_run:
            notifier.send_alert(
                f"CRITICAL: Elvan X agent health check crashed. {exc}"
            )
        return 1
    finally:
        if session is not None:
            session.close()
        db.finish_run(
            run_id,
            finished_at=current_timestamp(settings),
            stop_reason=stop_reason,
            errors=" | ".join(errors) if errors else None,
        )


def run_engage(
    settings: Settings,
    logger: Any,
    db: Database,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    apply_run_jitter(settings, logger, dry_run=dry_run)
    started_at = current_timestamp(settings)
    run_id = db.start_run("engage", started_at)
    posts_found = 0
    comments_posted = 0
    searches_run = 0
    stop_reason: str | None = None
    errors: list[str] = []
    session: BrowserSession | None = None

    try:
        counts = db.get_daily_activity_counts(settings.timezone)
        remaining_comments = settings.max_comments_per_day - int(counts["comments_posted"])
        remaining_searches = settings.max_searches_per_day - int(counts["searches_run"])

        if remaining_comments <= 0:
            stop_reason = "Daily comment limit already reached."
            maybe_send_limit_alert(
                notifier,
                logger,
                dry_run=dry_run,
                reason=stop_reason,
            )
            return 0
        if remaining_searches <= 0:
            stop_reason = "Daily search limit already reached."
            maybe_send_limit_alert(
                notifier,
                logger,
                dry_run=dry_run,
                reason=stop_reason,
            )
            return 0

        keyword_batch_size = min(settings.keyword_batch_size, remaining_searches)
        keywords = db.get_rotating_keywords(
            settings.keywords,
            keyword_batch_size,
            updated_at=started_at,
            advance=not dry_run,
        )
        if not keywords:
            stop_reason = "No keywords configured."
            return 1

        session = BrowserSession(settings, logger)
        health = session.check_health()
        if not health.ok:
            stop_reason = health.reason
            logger.error("Browser session unhealthy: %s", health.reason)
            if not dry_run:
                notifier.send_alert(
                    f"CRITICAL: Elvan X agent browser session failure. {health.reason}"
                )
            return 1

        page = session.get_page()
        searcher = XSearcher(settings, db, logger)
        generator = AnthropicContentGenerator(settings, logger)
        poster = XPoster(settings, logger)

        candidates, searches_run = searcher.discover_posts(
            page,
            keywords,
            record_seen=not dry_run,
        )
        posts_found = len(candidates)
        comment_budget = min(settings.top_posts_to_comment, remaining_comments, posts_found)

        for index, post in enumerate(candidates[:comment_budget], start=1):
            draft = generator.generate_comment(post, dry_run=dry_run)
            if draft.validation_errors:
                reason = "; ".join(draft.validation_errors)
                logger.warning("Skipping post %s because validation failed: %s", post.post_id, reason)
                if not dry_run:
                    db.log_comment(
                        post,
                        draft.text,
                        status="skipped",
                        status_reason=reason,
                        commented_at=current_timestamp(settings),
                    )
                errors.append(f"{post.post_id}: {reason}")
                continue

            result = poster.post_comment(page, post, draft.text, dry_run=dry_run)
            timestamp = current_timestamp(settings)

            if result.success and result.submitted:
                comments_posted += 1
                logger.info("Comment posted successfully for post %s.", post.post_id)
                if not dry_run:
                    db.log_comment(
                        post,
                        draft.text,
                        status="success",
                        status_reason=result.reason,
                        commented_at=timestamp,
                    )
                    db.set_consecutive_comment_failures(0, timestamp)
                if index < comment_budget:
                    wait_between_comments(settings, logger, dry_run=dry_run)
                continue

            if result.success and not result.submitted:
                logger.info("Dry-run comment typed for post %s; submission skipped.", post.post_id)
                continue

            reason = result.reason or "Comment submission failed."
            logger.warning("Comment failed for post %s: %s", post.post_id, reason)
            errors.append(f"{post.post_id}: {reason}")
            if not dry_run:
                db.log_comment(
                    post,
                    draft.text,
                    status="failed",
                    status_reason=reason,
                    commented_at=timestamp,
                )
                consecutive = db.get_consecutive_comment_failures() + 1
                db.set_consecutive_comment_failures(consecutive, timestamp)
                if consecutive >= 3:
                    notifier.send_alert(
                        "WARNING: Elvan X agent hit 3 consecutive comment failures."
                    )

        if posts_found == 0 and stop_reason is None:
            stop_reason = "No eligible posts found."

        return 0
    except Exception as exc:
        stop_reason = str(exc)
        errors.append(str(exc))
        logger.exception("Engage run failed.")
        return 1
    finally:
        if session is not None:
            session.close()
        db.finish_run(
            run_id,
            finished_at=current_timestamp(settings),
            posts_found=posts_found,
            comments_posted=comments_posted,
            searches_run=searches_run,
            stop_reason=stop_reason,
            errors=" | ".join(errors) if errors else None,
        )


def run_publish(
    settings: Settings,
    logger: Any,
    db: Database,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    apply_run_jitter(settings, logger, dry_run=dry_run)
    started_at = current_timestamp(settings)
    run_id = db.start_run("publish", started_at)
    standalone_posted = 0
    stop_reason: str | None = None
    errors: list[str] = []
    session: BrowserSession | None = None

    try:
        counts = db.get_daily_activity_counts(settings.timezone)
        remaining_posts = settings.max_posts_per_day - int(counts["standalone_posted"])
        if remaining_posts <= 0:
            stop_reason = "Daily standalone post limit already reached."
            maybe_send_limit_alert(
                notifier,
                logger,
                dry_run=dry_run,
                reason=stop_reason,
            )
            return 0

        topic_category, generation_number, allow_elvan_reference = db.get_next_topic(
            settings.topic_rotation,
            updated_at=started_at,
            advance=not dry_run,
        )
        logger.info(
            "Standalone generation #%s selected topic '%s' (Elvan allowed: %s).",
            generation_number,
            topic_category,
            allow_elvan_reference,
        )

        session = BrowserSession(settings, logger)
        health = session.check_health()
        if not health.ok:
            stop_reason = health.reason
            logger.error("Browser session unhealthy: %s", health.reason)
            if not dry_run:
                notifier.send_alert(
                    f"CRITICAL: Elvan X agent browser session failure. {health.reason}"
                )
            return 1

        generator = AnthropicContentGenerator(settings, logger)
        draft = generator.generate_standalone_post(
            topic_category,
            allow_elvan_reference=allow_elvan_reference,
            dry_run=dry_run,
        )
        if draft.validation_errors:
            reason = "; ".join(draft.validation_errors)
            logger.warning("Skipping standalone post because validation failed: %s", reason)
            if not dry_run:
                db.log_standalone_post(
                    draft.text,
                    topic_category,
                    status="skipped",
                    status_reason=reason,
                    posted_at=current_timestamp(settings),
                )
            errors.append(reason)
            return 0

        page = session.get_page()
        poster = XPoster(settings, logger)
        result = poster.publish_post(page, draft.text, dry_run=dry_run)
        timestamp = current_timestamp(settings)

        if result.success and result.submitted:
            standalone_posted = 1
            logger.info("Standalone post published successfully.")
            if not dry_run:
                db.log_standalone_post(
                    draft.text,
                    topic_category,
                    status="success",
                    status_reason=result.reason,
                    posted_at=timestamp,
                )
            return 0

        if result.success and not result.submitted:
            logger.info("Dry-run standalone post typed; submission skipped.")
            return 0

        reason = result.reason or "Standalone post submission failed."
        logger.warning("Standalone post failed: %s", reason)
        errors.append(reason)
        if not dry_run:
            db.log_standalone_post(
                draft.text,
                topic_category,
                status="failed",
                status_reason=reason,
                posted_at=timestamp,
            )
        return 1
    except Exception as exc:
        stop_reason = str(exc)
        errors.append(str(exc))
        logger.exception("Publish run failed.")
        return 1
    finally:
        if session is not None:
            session.close()
        db.finish_run(
            run_id,
            finished_at=current_timestamp(settings),
            standalone_posted=standalone_posted,
            stop_reason=stop_reason,
            errors=" | ".join(errors) if errors else None,
        )


def run_daily_report(
    settings: Settings,
    logger: Any,
    db: Database,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    apply_run_jitter(settings, logger, dry_run=dry_run)
    started_at = current_timestamp(settings)
    run_id = db.start_run("daily-report", started_at)
    stop_reason: str | None = None
    errors: list[str] = []

    try:
        counts = db.get_daily_activity_counts(settings.timezone)
        report_day = str(counts["day_key"])
        if not dry_run and db.get_state("last_daily_report_date") == report_day:
            stop_reason = f"Daily report already sent for {report_day}."
            logger.info(stop_reason)
            return 0

        failure_count, failure_summary = db.get_daily_failure_summary(settings.timezone)
        message = build_daily_report_message(
            settings,
            counts,
            failure_count,
            failure_summary,
        )
        logger.info("Daily report message:\n%s", message)

        if not dry_run:
            notifier.send_alert(message)
            db.set_state("last_daily_report_date", report_day, current_timestamp(settings))

        return 0
    except Exception as exc:
        stop_reason = str(exc)
        errors.append(str(exc))
        logger.exception("Daily report run failed.")
        return 1
    finally:
        db.finish_run(
            run_id,
            finished_at=current_timestamp(settings),
            stop_reason=stop_reason,
            errors=" | ".join(errors) if errors else None,
        )


def run_stats_report(
    settings: Settings,
    logger: Any,
    db: Database,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    reporter = StatsReporter(settings, db, logger, notifier)
    return reporter.run(dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings(Path(__file__).resolve().parent)
    settings.dry_run = settings.dry_run or bool(args.dry_run)
    logger = setup_logger(settings)
    db = Database(settings.db_path, logger)
    notifier = TelegramNotifier(settings, logger)

    try:
        if args.command == "health-check":
            return run_health_check(settings, logger, db, notifier, dry_run=settings.dry_run)
        if args.command == "engage":
            return run_engage(settings, logger, db, notifier, dry_run=settings.dry_run)
        if args.command == "publish":
            return run_publish(settings, logger, db, notifier, dry_run=settings.dry_run)
        if args.command == "daily-report":
            return run_daily_report(settings, logger, db, notifier, dry_run=settings.dry_run)
        if args.command == "stats-report":
            return run_stats_report(settings, logger, db, notifier, dry_run=settings.dry_run)
        parser.error(f"Unsupported command: {args.command}")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
