from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from config import load_settings
from db import Database
from models import DiscoveredPost
from queue_builder import QueueBuilder


class DummyNotifier:
    def send_alert(self, message: str, disable_notification: bool = False) -> bool:
        return True


class QueueBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.settings = load_settings(self.base_dir)
        self.logger = logging.getLogger(f"queue-builder-test-{self.id()}")
        self.db = Database(self.settings.db_path, self.logger)
        self.builder = QueueBuilder(self.settings, self.db, self.logger, DummyNotifier())

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_run_marks_sent_x_findings_as_seen(self) -> None:
        now = datetime.now(timezone.utc)
        post = DiscoveredPost(
            post_id="post-1",
            post_url="https://x.com/test/status/post-1",
            author_handle="@founder",
            text="Our NPS timing change hurt response quality.",
            likes=32,
            replies=6,
            reposts=1,
            created_at=now,
            keyword="NPS",
            search_mode="live",
            score=42.0,
        )
        finding = {
            "post_id": post.post_id,
            "author_handle": "founder",
            "keyword": post.keyword,
            "post_text_excerpt": post.text,
            "score": post.score,
            "likes": post.likes,
            "replies": post.replies,
            "response_suggestion": "Timing changes usually distort who answers, not just how many.",
            "post_url": post.post_url,
        }

        with mock.patch.object(self.builder, "_collect_x_posts", return_value=[post]), mock.patch.object(
            self.builder, "_run_reddit_scan", return_value=[]
        ), mock.patch.object(
            self.builder, "_build_x_findings", return_value=[finding]
        ), mock.patch.object(
            self.builder, "_send_queue"
        ):
            result = self.builder.run(dry_run=False)

        self.assertEqual(result, 0)
        self.assertTrue(self.db.has_seen(post.post_id))

    def test_header_and_reddit_message_use_analysis_language(self) -> None:
        x_findings = [
            {
                "post_id": "post-1",
                "author_handle": "founder",
                "keyword": "NPS",
                "post_text_excerpt": "Response rates dropped after a timing change.",
                "score": 41.0,
                "likes": 28,
                "replies": 5,
                "response_suggestion": "Timing changes often shift the respondent mix before they change raw volume.",
                "post_url": "https://x.com/test/status/post-1",
            }
        ]
        reddit_leads = [
            {
                "subreddit": "SaaS",
                "post_title": "Need a Delighted alternative",
                "upvotes": 20,
                "comments": 4,
                "url": "https://reddit.com/example",
                "priority": "high",
                "score": 75.0,
                "primary_keyword": "Delighted alternative",
            }
        ]

        header = self.builder._build_header_message(x_findings, reddit_leads)
        reddit_message = self.builder._format_reddit_leads_message(reddit_leads)

        self.assertIn("Elvan Social Research Digest", header)
        self.assertNotIn("post manually", header.lower())
        assert reddit_message is not None
        self.assertIn("REDDIT LEADS TODAY", reddit_message)
        self.assertNotIn("replying manually", reddit_message.lower())


if __name__ == "__main__":
    unittest.main()
