from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from config import Settings
from db import Database
from notifier import TelegramNotifier


class StatsReporter:
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

    def run(self, *, dry_run: bool = False) -> int:
        try:
            message = self._build_message()
            self.logger.info("Stats report message:\n%s", message)

            if not dry_run:
                self.notifier.send_alert(message)

            return 0
        except Exception:
            self.logger.exception("Stats report run failed.")
            return 1

    def _build_message(self) -> str:
        now = datetime.now(self.settings.zoneinfo())
        queue_today = self._get_queue_stats_today()
        queue_week = self._get_queue_stats_week()
        reddit_today = self._get_reddit_stats_today()
        reddit_week = self._get_reddit_stats_week()
        next_run_day = now + timedelta(days=1)
        next_run_time = self._parse_clock_time(self.settings.queue_run_time)
        next_run = datetime.combine(
            next_run_day.date(),
            next_run_time,
            tzinfo=self.settings.zoneinfo(),
        )

        lines = [
            "Elvan Research Stats",
            now.strftime("%B %d, %Y"),
            "",
            "X RESEARCH",
            f"Posts surfaced: {queue_today['posts_discovered']}",
            f"Response suggestions generated: {queue_today['drafts_generated']}",
            f"Latest digest run: {queue_today['queue_time']}",
            "",
            "REDDIT MONITOR",
            f"Posts scanned: {reddit_today['posts_scanned']}",
            f"Leads found: {reddit_today['leads_found']}",
            f"High priority: {reddit_today['high_priority']}",
            f"Worth reading: {reddit_today['worth_reading']}",
            "",
            "WEEK SUMMARY",
            f"X posts surfaced: {queue_week['posts_discovered']}",
            f"Reddit leads found: {reddit_week['reddit_leads']}",
            "",
            f"Next run: {next_run.strftime('%B %d, %Y')} {self.settings.queue_run_time}",
        ]
        return "\n".join(lines)

    def _get_queue_stats_today(self) -> dict[str, int | str]:
        start_at, end_at, _ = self.db._day_bounds(self.settings.timezone)
        row = self.db.conn.execute(
            """
            SELECT
              COALESCE(SUM(posts_discovered), 0) AS posts_discovered,
              COALESCE(SUM(drafts_generated), 0) AS drafts_generated
            FROM queue_runs
            WHERE julianday(run_at) >= julianday(?)
              AND julianday(run_at) < julianday(?)
            """,
            (start_at, end_at),
        ).fetchone()
        last_row = self.db.conn.execute(
            """
            SELECT run_at
            FROM queue_runs
            WHERE julianday(run_at) >= julianday(?)
              AND julianday(run_at) < julianday(?)
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (start_at, end_at),
        ).fetchone()

        queue_time = self._format_clock_time(last_row["run_at"] if last_row else None)
        return {
            "posts_discovered": int(row["posts_discovered"]),
            "drafts_generated": int(row["drafts_generated"]),
            "queue_time": queue_time,
        }

    def _get_queue_stats_week(self) -> dict[str, int]:
        start_at, end_at = self._week_bounds()
        row = self.db.conn.execute(
            """
            SELECT COALESCE(SUM(posts_discovered), 0) AS count
            FROM queue_runs
            WHERE julianday(run_at) >= julianday(?)
              AND julianday(run_at) < julianday(?)
            """,
            (start_at, end_at),
        ).fetchone()
        return {"posts_discovered": int(row["count"])}

    def _get_reddit_stats_today(self) -> dict[str, int]:
        conn = self._open_reddit_connection()
        if conn is None:
            return {
                "posts_scanned": 0,
                "leads_found": 0,
                "high_priority": 0,
                "worth_reading": 0,
            }

        try:
            start_at, end_at, _ = self.db._day_bounds(self.settings.timezone)
            scanned_row = conn.execute(
                """
                SELECT COALESCE(SUM(posts_scanned), 0) AS count
                FROM reddit_run_log
                WHERE julianday(started_at) >= julianday(?)
                  AND julianday(started_at) < julianday(?)
                """,
                (start_at, end_at),
            ).fetchone()
            priority_rows = conn.execute(
                """
                SELECT priority, COUNT(*) AS count
                FROM reddit_seen_posts
                WHERE julianday(first_seen) >= julianday(?)
                  AND julianday(first_seen) < julianday(?)
                  AND priority IN ('high', 'medium')
                GROUP BY priority
                """,
                (start_at, end_at),
            ).fetchall()

            priority_counts = {"high": 0, "medium": 0}
            for row in priority_rows:
                priority_counts[str(row["priority"])] = int(row["count"])

            leads_found = priority_counts["high"] + priority_counts["medium"]
            return {
                "posts_scanned": int(scanned_row["count"]),
                "leads_found": leads_found,
                "high_priority": priority_counts["high"],
                "worth_reading": priority_counts["medium"],
            }
        except Exception:
            return {
                "posts_scanned": 0,
                "leads_found": 0,
                "high_priority": 0,
                "worth_reading": 0,
            }
        finally:
            conn.close()

    def _get_reddit_stats_week(self) -> dict[str, int]:
        conn = self._open_reddit_connection()
        if conn is None:
            return {"reddit_leads": 0}

        try:
            start_at, end_at = self._week_bounds()
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM reddit_seen_posts
                WHERE julianday(first_seen) >= julianday(?)
                  AND julianday(first_seen) < julianday(?)
                  AND priority IN ('high', 'medium')
                """,
                (start_at, end_at),
            ).fetchone()
            return {"reddit_leads": int(row["count"])}
        except Exception:
            return {"reddit_leads": 0}
        finally:
            conn.close()

    def _week_bounds(self) -> tuple[str, str]:
        zone = self.settings.zoneinfo()
        local_now = datetime.now(zone)
        start_local = datetime.combine(
            local_now.date() - timedelta(days=6),
            time.min,
            tzinfo=zone,
        )
        end_local = datetime.combine(
            local_now.date() + timedelta(days=1),
            time.min,
            tzinfo=zone,
        )
        return start_local.isoformat(), end_local.isoformat()

    def _open_reddit_connection(self) -> sqlite3.Connection | None:
        for db_path in self._reddit_db_candidates():
            if not db_path.exists():
                continue
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
        return None

    def _reddit_db_candidates(self) -> list[Path]:
        primary = self.settings.base_dir / "reddit_monitor.db"
        fallback = self.settings.base_dir / "reddit.db"
        if fallback == primary:
            return [primary]
        return [primary, fallback]

    @staticmethod
    def _parse_clock_time(value: str) -> time:
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return time(8, 0)

    @staticmethod
    def _format_clock_time(timestamp: str | None) -> str:
        if not timestamp:
            return "none today"
        try:
            return datetime.fromisoformat(timestamp).strftime("%H:%M")
        except ValueError:
            return "none today"
