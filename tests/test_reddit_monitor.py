from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import load_settings
from reddit_db import RedditDatabase
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

    def test_seen_current_leads_still_belong_in_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_settings(Path(temp_dir))
            logger = __import__("logging").getLogger(f"reddit-monitor-test-{self.id()}")
            db = RedditDatabase(Path(temp_dir) / "reddit_monitor.db", logger)
            try:
                now = datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc)
                post = RedditPost(
                    post_id="reddit-seen-current",
                    subreddit="CustomerSuccess",
                    title="Looking for a customer feedback tool",
                    body="Need something better for onboarding churn notes.",
                    author="operator",
                    post_url="https://www.reddit.com/r/CustomerSuccess/comments/reddit-seen-current/example/",
                    created_at=now - timedelta(hours=2),
                    upvotes=18,
                    comment_count=5,
                )
                lead = rank_posts([post], now=now)[0]
                db.mark_seen(lead, now.isoformat())

                ranked_leads = rank_posts([post], now=now)
                new_leads = [
                    current_lead
                    for current_lead in ranked_leads
                    if not db.has_seen(current_lead.post.post_id)
                ]
                surfaced_leads = [
                    current_lead
                    for current_lead in ranked_leads
                    if current_lead.priority != "low"
                ]

                message = build_digest_message(
                    settings,
                    leads=surfaced_leads,
                    scanned_count=1,
                    matched_count=1,
                    new_count=len(new_leads),
                    scanned_subreddit_count=1,
                )

                self.assertEqual(new_leads, [])
                self.assertIn("Looking for a customer feedback tool", message)
                self.assertIn("New (not seen before): 0", message)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
