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

    def persist_failed_message(self, channel: str, message: str) -> Path:
        return Path(channel)


class FailingNotifier:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def send_alert(self, message: str, disable_notification: bool = False) -> bool:
        return False

    def persist_failed_message(self, channel: str, message: str) -> Path:
        path = self.base_dir / f"{channel}.txt"
        path.write_text(message, encoding="utf-8")
        return path


class FailingNeonStore:
    enabled = True

    def record_x_findings(self, *args, **kwargs):
        raise RuntimeError("neon unavailable")

    def record_reddit_leads(self, *args, **kwargs):
        return 0

    def record_workflow_run(self, *args, **kwargs):
        return False


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

    def test_run_does_not_mark_seen_when_delivery_fails(self) -> None:
        self.builder = QueueBuilder(
            self.settings,
            self.db,
            self.logger,
            FailingNotifier(self.base_dir),
        )
        now = datetime.now(timezone.utc)
        post = DiscoveredPost(
            post_id="post-delivery-fail",
            post_url="https://x.com/test/status/post-delivery-fail",
            author_handle="@founder",
            text="We are reevaluating our feedback stack.",
            likes=18,
            replies=4,
            reposts=1,
            created_at=now,
            keyword="feedback tool",
            search_mode="live",
            score=36.0,
        )
        finding = {
            "post_id": post.post_id,
            "author_handle": "founder",
            "keyword": post.keyword,
            "post_text_excerpt": post.text,
            "score": post.score,
            "likes": post.likes,
            "replies": post.replies,
            "response_suggestion": None,
            "post_url": post.post_url,
        }

        with mock.patch.object(self.builder, "_collect_x_posts", return_value=[post]), mock.patch.object(
            self.builder, "_run_reddit_scan", return_value=[]
        ), mock.patch.object(
            self.builder, "_build_x_findings", return_value=[finding]
        ):
            result = self.builder.run(dry_run=False)

        self.assertEqual(result, 1)
        self.assertFalse(self.db.has_seen(post.post_id))
        archived_files = list(self.base_dir.glob("queue-*.txt"))
        self.assertTrue(archived_files)

    def test_run_ignores_neon_parallel_failures(self) -> None:
        self.builder.neon_store = FailingNeonStore()
        now = datetime.now(timezone.utc)
        post = DiscoveredPost(
            post_id="post-neon-fail",
            post_url="https://x.com/test/status/post-neon-fail",
            author_handle="@founder",
            text="Need a Delighted alternative with better onboarding feedback.",
            likes=22,
            replies=3,
            reposts=1,
            created_at=now,
            keyword="Delighted alternative",
            search_mode="live",
            score=38.0,
        )
        finding = {
            "post_id": post.post_id,
            "author_handle": "founder",
            "keyword": post.keyword,
            "post_text": post.text,
            "post_text_excerpt": post.text,
            "post_created_at": post.created_at.isoformat(),
            "score": post.score,
            "likes": post.likes,
            "replies": post.replies,
            "reposts": post.reposts,
            "search_mode": post.search_mode,
            "response_suggestion": "Teams usually switch when onboarding feedback gets trapped in a survey silo.",
            "post_url": post.post_url,
        }

        with mock.patch.object(self.builder, "_collect_x_posts", return_value=[post]), mock.patch.object(
            self.builder, "_run_reddit_scan", return_value=[]
        ), mock.patch.object(
            self.builder, "_build_x_findings", return_value=[finding]
        ), mock.patch.object(
            self.builder, "_send_queue", return_value=True
        ):
            result = self.builder.run(dry_run=False)

        self.assertEqual(result, 0)
        self.assertTrue(self.db.has_seen(post.post_id))


if __name__ == "__main__":
    unittest.main()
