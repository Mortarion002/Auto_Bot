from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import load_settings
from reddit_monitor import build_digest_message
from reddit_scraper import RedditPost
from reddit_scorer import rank_posts


class RedditMonitorMessageTests(unittest.TestCase):
    def test_digest_message_includes_counts_and_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_settings(Path(temp_dir))
            now = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
            posts = [
                RedditPost(
                    post_id="reddit-1",
                    subreddit="SaaS",
                    title="Need a Delighted alternative ASAP",
                    body="Looking for options.",
                    author="founder",
                    post_url="https://www.reddit.com/r/SaaS/comments/reddit-1/example/",
                    created_at=now - timedelta(hours=5),
                    upvotes=40,
                    comment_count=8,
                ),
                RedditPost(
                    post_id="reddit-2",
                    subreddit="startups",
                    title="Churn is killing us",
                    body="Need a better feedback loop.",
                    author="operator",
                    post_url="https://www.reddit.com/r/startups/comments/reddit-2/example/",
                    created_at=now - timedelta(hours=20),
                    upvotes=11,
                    comment_count=2,
                ),
            ]

            leads = rank_posts(posts, now=now)
            message = build_digest_message(
                settings,
                leads=leads,
                scanned_count=340,
                matched_count=8,
                new_count=6,
                scanned_subreddit_count=7,
            )

            self.assertIn("Elvan Reddit Monitor", message)
            self.assertIn("High Priority", message)
            self.assertIn("Worth Reading", message)
            self.assertIn("Total scanned: 340 posts across 7 subreddits", message)
            self.assertIn("Keyword matches today: 8", message)
            self.assertIn("New (not seen before): 6", message)


if __name__ == "__main__":
    unittest.main()
