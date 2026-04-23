from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from config import load_settings
from db import Database
from models import DiscoveredPost


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.settings = load_settings(self.base_dir)
        self.logger = logging.getLogger(f"db-test-{self.id()}")
        self.db = Database(self.settings.db_path, self.logger)

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_schema_initialization_is_idempotent(self) -> None:
        self.db.close()
        reopened = Database(self.settings.db_path, self.logger)
        tables = {
            row["name"]
            for row in reopened.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("commented_posts", tables)
        self.assertIn("standalone_posts", tables)
        self.assertIn("run_log", tables)
        self.assertIn("agent_state", tables)
        reopened.close()

    def test_comment_upsert_preserves_single_row_per_post(self) -> None:
        now = datetime.now(timezone.utc)
        post = DiscoveredPost(
            post_id="abc123",
            post_url="https://x.com/test/status/abc123",
            author_handle="tester",
            text="A post about NPS timing.",
            likes=25,
            replies=4,
            reposts=1,
            created_at=now,
            keyword="NPS",
            search_mode="live",
            score=33.5,
        )
        self.db.log_comment(
            post,
            "First draft",
            status="failed",
            status_reason="timeout",
            commented_at=now.isoformat(),
        )
        self.db.log_comment(
            post,
            "Second draft",
            status="success",
            status_reason="submitted",
            commented_at=now.isoformat(),
        )
        row = self.db.conn.execute(
            "SELECT comment_text, status FROM commented_posts WHERE post_id = ?",
            ("abc123",),
        ).fetchone()
        self.assertEqual(row["comment_text"], "Second draft")
        self.assertEqual(row["status"], "success")

    def test_research_and_legacy_archive_counts_and_keyword_rotation_state(self) -> None:
        now = datetime.now(timezone.utc)
        post = DiscoveredPost(
            post_id="xyz789",
            post_url="https://x.com/test/status/xyz789",
            author_handle="tester",
            text="A post about retention.",
            likes=30,
            replies=3,
            reposts=2,
            created_at=now,
            keyword="retention",
            search_mode="live",
            score=39.0,
        )
        self.db.log_comment(
            post,
            "Useful comment",
            status="success",
            status_reason="submitted",
            commented_at=now.isoformat(),
        )
        self.db.log_standalone_post(
            "A standalone post",
            "SaaS founder lesson",
            status="success",
            status_reason="submitted",
            posted_at=now.isoformat(),
        )
        run_id = self.db.start_run("build-queue", now.isoformat())
        self.db.finish_run(
            run_id,
            finished_at=now.isoformat(),
            searches_run=10,
        )
        self.db.log_queue_run(
            run_at=now.isoformat(),
            posts_discovered=4,
            drafts_generated=2,
            legacy_post_ideas_generated=0,
            reddit_leads=1,
            queue_sent=True,
        )

        research_counts = self.db.get_daily_research_activity_counts("Asia/Calcutta", now=now)
        legacy_counts = self.db.get_daily_legacy_publish_archive_counts("Asia/Calcutta", now=now)
        compatibility_counts = self.db.get_daily_activity_counts("Asia/Calcutta", now=now)

        self.assertEqual(research_counts["x_findings_surfaced"], 4)
        self.assertEqual(research_counts["response_suggestions_generated"], 2)
        self.assertEqual(research_counts["digest_runs"], 1)
        self.assertEqual(research_counts["searches_run"], 10)
        self.assertIsNotNone(research_counts["latest_digest_run_at"])
        self.assertEqual(legacy_counts["legacy_comments_posted"], 1)
        self.assertEqual(legacy_counts["legacy_standalone_posts_published"], 1)
        self.assertEqual(compatibility_counts, legacy_counts)

        keywords = self.db.get_rotating_keywords(
            ["one", "two", "three"],
            2,
            updated_at=now.isoformat(),
            advance=True,
        )
        self.assertEqual(keywords, ["one", "two"])
        keywords = self.db.get_rotating_keywords(
            ["one", "two", "three"],
            2,
            updated_at=now.isoformat(),
            advance=True,
        )
        self.assertEqual(keywords, ["three", "one"])

    def test_mark_posts_seen_tracks_unique_ids(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.mark_posts_seen(["one", "two", "one"], now)

        self.assertTrue(self.db.has_seen("one"))
        self.assertTrue(self.db.has_seen("two"))

        row = self.db.conn.execute(
            "SELECT COUNT(*) AS count FROM seen_posts",
        ).fetchone()
        self.assertEqual(int(row["count"]), 2)

    def test_research_failure_summary_truncates_each_error_entry(self) -> None:
        now = datetime.now(timezone.utc)
        first_error = "A" * 130
        second_error = "B" * 150

        run_id = self.db.start_run("build-queue", now.isoformat())
        self.db.finish_run(
            run_id,
            finished_at=now.isoformat(),
            errors=f"{first_error} | {second_error}",
        )

        failure_count, failure_summary = self.db.get_daily_research_failure_summary("UTC", now=now)

        self.assertEqual(failure_count, 2)
        self.assertEqual(
            failure_summary,
            f"{first_error[:120]} | {second_error[:120]}",
        )

    def test_legacy_publish_failure_summary_is_separate_from_research_failures(self) -> None:
        now = datetime.now(timezone.utc)
        post = DiscoveredPost(
            post_id="legacy-failure",
            post_url="https://x.com/test/status/legacy-failure",
            author_handle="tester",
            text="Legacy workflow failure example.",
            likes=10,
            replies=1,
            reposts=0,
            created_at=now,
            keyword="NPS",
            search_mode="live",
            score=12.0,
        )
        self.db.log_comment(
            post,
            "Old comment",
            status="failed",
            status_reason="legacy timeout",
            commented_at=now.isoformat(),
        )

        legacy_count, legacy_summary = self.db.get_daily_legacy_publish_failure_summary("UTC", now=now)
        combined_count, combined_summary = self.db.get_daily_failure_summary("UTC", now=now)

        self.assertEqual(legacy_count, 1)
        self.assertIn("legacy comment legacy-failure: legacy timeout", legacy_summary)
        self.assertEqual(combined_count, 1)
        self.assertEqual(combined_summary, legacy_summary)
