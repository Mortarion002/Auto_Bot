from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from reddit_scraper import RedditPost
from reddit_scorer import HIGH_PRIORITY_THRESHOLD, rank_posts, score_post


class RedditScorerTests(unittest.TestCase):
    def test_direct_keyword_title_match_scores_high_priority(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
        post = RedditPost(
            post_id="post-1",
            subreddit="SaaS",
            title="Need a Delighted alternative ASAP",
            body="Our contract renews next month and we need to switch.",
            author="founder_1",
            post_url="https://www.reddit.com/r/SaaS/comments/post-1/example/",
            created_at=now - timedelta(hours=6),
            upvotes=47,
            comment_count=12,
        )

        lead = score_post(post, now=now)

        self.assertIsNotNone(lead)
        assert lead is not None
        self.assertEqual(lead.primary_keyword, "Delighted alternative")
        self.assertEqual(lead.priority, "high")
        self.assertGreaterEqual(lead.score, HIGH_PRIORITY_THRESHOLD)

    def test_old_post_is_filtered_out(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
        post = RedditPost(
            post_id="post-2",
            subreddit="startups",
            title="Customer retention is a mess",
            body="Looking for a better feedback loop before churn gets worse.",
            author="founder_2",
            post_url="https://www.reddit.com/r/startups/comments/post-2/example/",
            created_at=now - timedelta(hours=90),
            upvotes=20,
            comment_count=4,
        )

        self.assertIsNone(score_post(post, now=now))

    def test_rank_posts_orders_stronger_matches_first(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
        strong = RedditPost(
            post_id="post-3",
            subreddit="CustomerSuccess",
            title="Best NPS tool for B2B SaaS?",
            body="We need something lightweight.",
            author="cs_lead",
            post_url="https://www.reddit.com/r/CustomerSuccess/comments/post-3/example/",
            created_at=now - timedelta(hours=5),
            upvotes=30,
            comment_count=9,
        )
        weaker = RedditPost(
            post_id="post-4",
            subreddit="Entrepreneur",
            title="Looking for better product feedback options",
            body="Trying to improve our response rate.",
            author="builder",
            post_url="https://www.reddit.com/r/Entrepreneur/comments/post-4/example/",
            created_at=now - timedelta(hours=30),
            upvotes=5,
            comment_count=1,
        )

        ranked = rank_posts([weaker, strong], now=now)

        self.assertEqual([lead.post.post_id for lead in ranked], ["post-3", "post-4"])

    def test_promotional_post_is_filtered_out(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
        post = RedditPost(
            post_id="post-5",
            subreddit="SaaS",
            title="I built a new churn dashboard for SaaS teams",
            body="Check out the launch and let me know what you think.",
            author="maker",
            post_url="https://www.reddit.com/r/SaaS/comments/post-5/example/",
            created_at=now - timedelta(hours=3),
            upvotes=22,
            comment_count=4,
        )

        self.assertIsNone(score_post(post, now=now))


if __name__ == "__main__":
    unittest.main()
