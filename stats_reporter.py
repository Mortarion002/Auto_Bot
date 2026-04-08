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
        x_today = self._get_x_stats_today()
        x_week = self._get_x_stats_week()
        top_keywords = self._get_top_keywords_today()
        reddit_today = self._get_reddit_stats_today()
        reddit_week = self._get_reddit_stats_week()
        next_run_day = now + timedelta(days=1)

        lines = [
            "📊 Elvan Agent — Daily Stats",
            f"📅 {now.strftime('%B %d, %Y')}",
            "",
            "━━━ X AGENT ━━━",
            (
                "💬 Comments: "
                f"{x_today['comments_posted']}/{self.settings.max_comments_per_day}"
            ),
            f"📝 Posts: {x_today['standalone_posted']}/{self.settings.max_posts_per_day}",
            f"🔍 Searches: {x_today['searches_run']}/{self.settings.max_searches_per_day}",
            f"✅ Success rate: {x_today['success_rate']}%",
            f"⚠️ Failures: {x_today['failure_count']}",
            "",
            "🔥 Top keywords today:",
        ]

        if top_keywords:
            lines.extend(
                [
                    f"{index}. {keyword} ({hits} hits)"
                    for index, (keyword, hits) in enumerate(top_keywords, start=1)
                ]
            )
        else:
            lines.append("No keyword hits today")

        if reddit_today is not None:
            lines.extend(
                [
                    "",
                    "━━━ REDDIT MONITOR ━━━",
                    f"📋 Posts scanned: {reddit_today['posts_scanned']}",
                    f"🎯 Leads found: {reddit_today['leads_found']}",
                    f"🔴 High priority: {reddit_today['high_priority']}",
                    f"🟡 Worth reading: {reddit_today['worth_reading']}",
                ]
            )

        weekly_reddit_leads = (
            int(reddit_week["reddit_leads"]) if reddit_week is not None else 0
        )
        lines.extend(
            [
                "",
                "━━━ WEEK SUMMARY ━━━",
                f"💬 Comments this week: {x_week['comments_posted']}",
                f"📝 Posts this week: {x_week['standalone_posted']}",
                f"🎯 Reddit leads this week: {weekly_reddit_leads}",
                "",
                f"Next run: {next_run_day.strftime('%B %d, %Y')} 09:00",
            ]
        )
        return "\n".join(lines)

    def _get_x_stats_today(self) -> dict[str, int | str]:
        counts = self.db.get_daily_activity_counts(self.settings.timezone)
        start_at, end_at, _ = self.db._day_bounds(self.settings.timezone)
        failure_row = self.db.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM commented_posts
            WHERE status = 'failed'
              AND commented_at IS NOT NULL
              AND julianday(commented_at) >= julianday(?)
              AND julianday(commented_at) < julianday(?)
            """,
            (start_at, end_at),
        ).fetchone()
        failure_count = int(failure_row["count"])
        comments_posted = int(counts["comments_posted"])

        if failure_count == 0:
            success_rate = 100
        else:
            attempts = comments_posted + failure_count
            success_rate = self._round_half_up((comments_posted / attempts) * 100)

        return {
            "day_key": str(counts["day_key"]),
            "comments_posted": comments_posted,
            "standalone_posted": int(counts["standalone_posted"]),
            "searches_run": int(counts["searches_run"]),
            "success_rate": success_rate,
            "failure_count": failure_count,
        }

    def _get_x_stats_week(self) -> dict[str, int]:
        start_at, end_at = self._week_bounds()
        comments_row = self.db.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM commented_posts
            WHERE status = 'success'
              AND commented_at IS NOT NULL
              AND julianday(commented_at) >= julianday(?)
              AND julianday(commented_at) < julianday(?)
            """,
            (start_at, end_at),
        ).fetchone()
        posts_row = self.db.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM standalone_posts
            WHERE status = 'success'
              AND posted_at IS NOT NULL
              AND julianday(posted_at) >= julianday(?)
              AND julianday(posted_at) < julianday(?)
            """,
            (start_at, end_at),
        ).fetchone()
        return {
            "comments_posted": int(comments_row["count"]),
            "standalone_posted": int(posts_row["count"]),
        }

    def _get_top_keywords_today(self) -> list[tuple[str, int]]:
        start_at, end_at, _ = self.db._day_bounds(self.settings.timezone)
        rows = self.db.conn.execute(
            """
            SELECT keyword, COUNT(*) AS hits
            FROM commented_posts
            WHERE status = 'success'
              AND commented_at IS NOT NULL
              AND keyword IS NOT NULL
              AND TRIM(keyword) != ''
              AND julianday(commented_at) >= julianday(?)
              AND julianday(commented_at) < julianday(?)
            GROUP BY keyword
            ORDER BY hits DESC, keyword ASC
            LIMIT 3
            """,
            (start_at, end_at),
        ).fetchall()
        return [(str(row["keyword"]), int(row["hits"])) for row in rows]

    def _get_reddit_stats_today(self) -> dict[str, int] | None:
        conn = self._open_reddit_connection()
        if conn is None:
            return None

        try:
            start_at, end_at, _ = self.db._day_bounds(self.settings.timezone)
            run_row = conn.execute(
                """
                SELECT posts_scanned
                FROM reddit_run_log
                WHERE julianday(started_at) >= julianday(?)
                  AND julianday(started_at) < julianday(?)
                ORDER BY started_at DESC
                LIMIT 1
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
                "posts_scanned": int(run_row["posts_scanned"]) if run_row else 0,
                "leads_found": leads_found,
                "high_priority": priority_counts["high"],
                "worth_reading": priority_counts["medium"],
            }
        except Exception:
            return None
        finally:
            conn.close()

    def _get_reddit_stats_week(self) -> dict[str, int] | None:
        conn = self._open_reddit_connection()
        if conn is None:
            return None

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
            return None
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
    def _round_half_up(value: float) -> int:
        return int(value + 0.5)
