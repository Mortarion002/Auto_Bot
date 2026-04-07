from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reddit_db import RedditDatabase
from reddit_scraper import RedditPost
from reddit_scorer import score_post


class RedditDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.logger = logging.getLogger(f"reddit-db-test-{self.id()}")
        self.db = RedditDatabase(self.base_dir / "reddit_monitor.db", self.logger)

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_schema_initialization_is_idempotent(self) -> None:
        self.db.close()
        reopened = RedditDatabase(self.base_dir / "reddit_monitor.db", self.logger)
        tables = {
            row["name"]
            for row in reopened.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("reddit_seen_posts", tables)
        self.assertIn("reddit_run_log", tables)
        reopened.close()

    def test_seen_posts_are_tracked_once(self) -> None:
        now = datetime.now(timezone.utc)
        post = RedditPost(
            post_id="reddit-1",
            subreddit="SaaS",
            title="Looking for a Delighted alternative",
            body="Current setup is too expensive.",
            author="user123",
            post_url="https://www.reddit.com/r/SaaS/comments/reddit-1/example/",
            created_at=now - timedelta(hours=4),
            upvotes=16,
            comment_count=3,
        )
        lead = score_post(post, now=now)
        assert lead is not None

        self.db.mark_seen(lead, now.isoformat())
        self.db.mark_seen(lead, now.isoformat())

        row = self.db.conn.execute(
            "SELECT COUNT(*) AS count FROM reddit_seen_posts WHERE post_id = ?",
            ("reddit-1",),
        ).fetchone()
        self.assertEqual(int(row["count"]), 1)
        self.assertTrue(self.db.has_seen("reddit-1"))

    def test_run_log_records_summary(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        run_id = self.db.start_run(now)
        self.db.finish_run(
            run_id,
            finished_at=now,
            posts_scanned=210,
            matches_found=8,
            new_matches=6,
            high_priority_count=3,
            digest_sent=True,
            errors=None,
        )

        row = self.db.conn.execute(
            """
            SELECT posts_scanned, matches_found, new_matches, high_priority_count, digest_sent
            FROM reddit_run_log
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        self.assertEqual(int(row["posts_scanned"]), 210)
        self.assertEqual(int(row["matches_found"]), 8)
        self.assertEqual(int(row["new_matches"]), 6)
        self.assertEqual(int(row["high_priority_count"]), 3)
        self.assertEqual(int(row["digest_sent"]), 1)


if __name__ == "__main__":
    unittest.main()
