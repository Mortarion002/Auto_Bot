from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Settings, load_settings
from db import Database
from logger import setup_logger
from notifier import TelegramNotifier
from queue_builder import QueueBuilder
from session import BrowserSession
from stats_reporter import StatsReporter

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency may be missing in tests
    def load_dotenv(*_: Any, **__: Any) -> bool:
        return False


DISABLED_COMMANDS = {"engage", "publish", "daily-report"}
DRY_RUN_HELP = "Skip Telegram sends and non-essential writes where possible."


def current_timestamp(settings: Settings) -> str:
    return datetime.now(settings.zoneinfo()).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elvan research orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("health-check", "build-queue", "stats-report"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)

    for command in sorted(DISABLED_COMMANDS):
        subparser = subparsers.add_parser(
            command,
            help="disabled (analysis-only mode)",
        )
        subparser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)

    return parser


def run_disabled_command(command: str, logger: Any) -> int:
    logger.warning(
        "'%s' is disabled. This project now runs in analysis-only mode. "
        "Use 'build-queue' for the X and Reddit digest or 'stats-report' for the summary.",
        command,
    )
    return 0


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


def run_build_queue(
    settings: Settings,
    logger: Any,
    db: Database,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    builder = QueueBuilder(settings, db, logger, notifier)
    return builder.run(dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings(Path(__file__).resolve().parent)
    settings.dry_run = settings.dry_run or bool(args.dry_run)
    logger = setup_logger(settings)

    if args.command in DISABLED_COMMANDS:
        return run_disabled_command(args.command, logger)

    db = Database(settings.db_path, logger)
    notifier = TelegramNotifier(settings, logger)

    try:
        if args.command == "health-check":
            return run_health_check(settings, logger, db, notifier, dry_run=settings.dry_run)
        if args.command == "build-queue":
            return run_build_queue(settings, logger, db, notifier, dry_run=settings.dry_run)
        if args.command == "stats-report":
            return run_stats_report(settings, logger, db, notifier, dry_run=settings.dry_run)
        parser.error(f"Unsupported command: {args.command}")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
