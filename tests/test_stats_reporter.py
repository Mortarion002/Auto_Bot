from __future__ import annotations

import logging
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from config import load_settings
from db import Database
from stats_reporter import StatsReporter


class DummyNotifier:
    def send_alert(self, message: str, disable_notification: bool = False) -> bool:
        return True


class StatsReporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.settings = load_settings(self.base_dir)
        self.logger = logging.getLogger(f"stats-reporter-test-{self.id()}")
        self.db = Database(self.settings.db_path, self.logger)
        self.reporter = StatsReporter(
            self.settings,
            self.db,
            self.logger,
            DummyNotifier(),
        )

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_build_message_uses_research_first_wording(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.log_queue_run(
            run_at=now,
            posts_discovered=5,
            drafts_generated=3,
            legacy_post_ideas_generated=0,
            reddit_leads=2,
            queue_sent=True,
        )

        reddit_conn = sqlite3.connect(self.base_dir / "reddit_monitor.db")
        reddit_conn.execute(
            """
            CREATE TABLE reddit_run_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              posts_scanned INTEGER DEFAULT 0,
              matches_found INTEGER DEFAULT 0,
              new_matches INTEGER DEFAULT 0,
              high_priority_count INTEGER DEFAULT 0,
              digest_sent INTEGER DEFAULT 0,
              errors TEXT
            )
            """
        )
        reddit_conn.execute(
            """
            CREATE TABLE reddit_seen_posts (
              post_id TEXT PRIMARY KEY,
              post_url TEXT NOT NULL,
              subreddit TEXT NOT NULL,
              author TEXT,
              title TEXT NOT NULL,
              matched_keywords TEXT,
              primary_keyword TEXT,
              priority TEXT,
              score REAL,
              created_at TEXT,
              first_seen TEXT NOT NULL,
              hot_lead_alerted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        reddit_conn.execute(
            """
            INSERT INTO reddit_run_log(
              started_at, finished_at, posts_scanned, matches_found,
              new_matches, high_priority_count, digest_sent, errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, now, 100, 2, 2, 1, 1, None),
        )
        reddit_conn.execute(
            """
            INSERT INTO reddit_seen_posts(
              post_id, post_url, subreddit, author, title, matched_keywords,
              primary_keyword, priority, score, created_at, first_seen, hot_lead_alerted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "reddit-1",
                "https://reddit.com/example",
                "SaaS",
                "founder",
                "Need a Delighted alternative",
                "Delighted alternative",
                "Delighted alternative",
                "high",
                88.0,
                now,
                now,
                0,
            ),
        )
        reddit_conn.commit()
        reddit_conn.close()

        message = self.reporter._build_message()

        self.assertIn("X DIGEST", message)
        self.assertIn("Findings surfaced: 5", message)
        self.assertIn("Response suggestions generated: 3", message)
        self.assertIn("Digest runs today: 1", message)
        self.assertIn("REDDIT MONITOR", message)
        self.assertIn("Leads found: 1", message)
        self.assertIn("WEEK SUMMARY", message)
        self.assertIn("X findings surfaced: 5", message)


if __name__ == "__main__":
    unittest.main()
