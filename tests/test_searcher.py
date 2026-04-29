from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import load_settings
from db import Database
from models import DiscoveredPost
from searcher import XSearcher, compute_engagement_score, has_strong_relevance, parse_metric_count


class SearcherHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = load_settings(Path(self.temp_dir.name))
        self.settings.account_handle = "@elvan"
        self.logger = logging.getLogger(f"search-test-{self.id()}")
        self.db = Database(self.settings.db_path, self.logger)
        self.searcher = XSearcher(self.settings, self.db, self.logger)

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_parse_metric_count_supports_suffixes(self) -> None:
        self.assertEqual(parse_metric_count("12"), 12)
        self.assertEqual(parse_metric_count("1.4K Likes"), 1400)
        self.assertEqual(parse_metric_count("2.5M"), 2500000)
        self.assertEqual(parse_metric_count(None), 0)

    def test_recent_posts_receive_recency_bonus(self) -> None:
        now = datetime.now(timezone.utc)
        recent_score = compute_engagement_score(10, 2, 1, now - timedelta(minutes=30), now=now)
        older_score = compute_engagement_score(10, 2, 1, now - timedelta(hours=4), now=now)
        self.assertGreater(recent_score, older_score)

    def test_filtering_removes_old_low_signal_and_own_posts(self) -> None:
        now = datetime.now(timezone.utc)
        posts = [
            DiscoveredPost(
                post_id="old",
                post_url="https://x.com/other/status/old",
                author_handle="other",
                text="Old post",
                likes=20,
                replies=1,
                reposts=1,
                created_at=now - timedelta(hours=60),
                keyword="NPS",
                search_mode="live",
            ),
            DiscoveredPost(
                post_id="low",
                post_url="https://x.com/other/status/low",
                author_handle="other",
                text="Low signal",
                likes=1,
                replies=0,
                reposts=0,
                created_at=now - timedelta(hours=1),
                keyword="NPS",
                search_mode="live",
            ),
            DiscoveredPost(
                post_id="own",
                post_url="https://x.com/elvan/status/own",
                author_handle="elvan",
                text="Own post",
                likes=40,
                replies=1,
                reposts=1,
                created_at=now - timedelta(hours=1),
                keyword="NPS",
                search_mode="live",
            ),
            DiscoveredPost(
                post_id="good",
                post_url="https://x.com/other/status/good",
                author_handle="other",
                text="Good NPS post",
                likes=40,
                replies=5,
                reposts=2,
                created_at=now - timedelta(minutes=20),
                keyword="NPS",
                search_mode="live",
            ),
        ]
        filtered = self.searcher._filter_and_score_posts(posts, record_seen=False)
        self.assertEqual([post.post_id for post in filtered], ["good"])

    def test_filtering_skips_previously_seen_posts_when_recording_is_enabled(self) -> None:
        now = datetime.now(timezone.utc)
        self.db.mark_post_seen("seen-post", now.isoformat())
        posts = [
            DiscoveredPost(
                post_id="seen-post",
                post_url="https://x.com/other/status/seen-post",
                author_handle="other",
                text="Fresh NPS post",
                likes=40,
                replies=5,
                reposts=2,
                created_at=now - timedelta(minutes=20),
                keyword="NPS",
                search_mode="live",
            )
        ]

        filtered, stats = self.searcher.filter_and_score_posts_with_stats(
            posts,
            record_seen=True,
        )

        self.assertEqual(filtered, [])
        self.assertEqual(stats["already_seen"], 1)

    def test_strong_relevance_rejects_generic_direct_term_mentions(self) -> None:
        self.assertFalse(
            has_strong_relevance(
                "Work should not come at the cost of mental health. 37% of workers report survey fatigue.",
                "survey fatigue",
            )
        )
        self.assertTrue(
            has_strong_relevance(
                "Looking for a Delighted alternative that handles B2B onboarding surveys.",
                "Delighted alternative",
            )
        )
