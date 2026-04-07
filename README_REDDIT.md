# Elvan Reddit Monitor

Phase 2 adds a read-only Reddit intelligence job that scans the target subreddits, scores recent posts against Elvan's ICP keywords, deduplicates previously surfaced leads, and sends a Telegram digest.

## Files

- `reddit_monitor.py`: main runner for scan, score, dedup, and digest delivery
- `reddit_scraper.py`: public Reddit collector for recent subreddit posts
- `reddit_scorer.py`: keyword matching, priority scoring, and lead ranking
- `reddit_db.py`: SQLite tracking for seen posts and monitor run history

## How It Works

1. Fetch the newest posts from each monitored subreddit.
2. Score posts against direct, pain-point, and discovery keyword groups.
3. If the broad scan finds nothing, run a direct-keyword search fallback.
4. Filter out posts older than 72 hours.
5. Skip anything already seen in `reddit_monitor.db`.
6. Send a Telegram digest with high-priority leads first.

## Command

```powershell
python reddit_monitor.py --dry-run
python reddit_monitor.py
```

## Notes

- The monitor is read-only. It never comments or posts to Reddit.
- It uses public Reddit listing endpoints with a descriptive user agent and does not require login or developer credentials.
- Digest delivery reuses the existing Telegram notifier configuration from `.env`.
