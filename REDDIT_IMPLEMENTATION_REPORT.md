# Reddit Monitor Implementation Report

## Summary

This report documents the Phase 2 Reddit monitor work completed in `X_POST/`.

The goal was to add a read-only Reddit intelligence workflow that:

- scans relevant subreddits
- identifies posts related to NPS, feedback tooling, churn, and Delighted alternatives
- scores and filters leads
- deduplicates already-seen posts
- sends a Telegram digest

## What Was Done

### 1. Built the Reddit monitor runner

Created [reddit_monitor.py](/c:/Users/resoa/Videos/X_Post/reddit_monitor.py) to:

- run the full Reddit scan flow
- collect posts from the target subreddits
- rank matching posts
- filter out already-seen items
- format the daily digest
- send the digest through the existing Telegram notifier
- log each Reddit monitor run in a dedicated SQLite database

### 2. Built the Reddit scraper

Created [reddit_scraper.py](/c:/Users/resoa/Videos/X_Post/reddit_scraper.py) to:

- fetch recent posts from monitored subreddits
- query subreddit search results for direct keywords
- parse post title, body, author, permalink, age, upvotes, and comments
- skip stickied, pinned, or removed items

### 3. Built the scoring and lead-ranking logic

Created [reddit_scorer.py](/c:/Users/resoa/Videos/X_Post/reddit_scorer.py) to:

- define direct, pain-point, and discovery keyword groups
- classify keyword matches by intent
- score matches using keyword strength, recency, engagement, and subreddit weight
- filter out promotional/self-promotional posts
- prioritize more explicit buying-intent and switching-intent threads

### 4. Built Reddit-specific persistence

Created [reddit_db.py](/c:/Users/resoa/Videos/X_Post/reddit_db.py) to:

- store seen Reddit posts
- prevent duplicate surfacing
- log Reddit monitor run summaries

### 5. Added documentation

Created [README_REDDIT.md](/c:/Users/resoa/Videos/X_Post/README_REDDIT.md) with:

- module overview
- command examples
- workflow notes
- operational assumptions

### 6. Added tests

Created:

- [tests/test_reddit_scorer.py](/c:/Users/resoa/Videos/X_Post/tests/test_reddit_scorer.py)
- [tests/test_reddit_db.py](/c:/Users/resoa/Videos/X_Post/tests/test_reddit_db.py)
- [tests/test_reddit_monitor.py](/c:/Users/resoa/Videos/X_Post/tests/test_reddit_monitor.py)

These cover:

- scoring behavior
- filtering behavior
- dedup behavior
- run-log behavior
- digest formatting

## What Failed

### 1. Browser-based Reddit scraping failed on this machine

The original plan in [Reddit.md](/c:/Users/resoa/Videos/X_Post/Reddit.md) described using Chrome automation with `undetected-chromedriver`.

That approach failed in practice because Reddit returned a network-security block page when accessed through browser automation from this environment.

Observed behavior during verification:

- direct browser access hit a Reddit block/interstitial
- public HTML scraping was not reliable from this machine
- `old.reddit.com` requests were also blocked in normal HTTP fetches

### 2. First scoring pass produced noisy results

Early versions of the scorer surfaced weak matches because:

- multi-word keyword matching was too loose
- body-only mentions created false positives
- generic questions were overvalued
- some promotional posts were slipping through

This was corrected by tightening:

- keyword phrase matching
- title-weighting
- promotion filtering
- buying-intent heuristics

### 3. Broad recent-post scan often found no strong leads

During dry-run validation, the newest-post scan across the target subreddits often returned zero strong matches inside the current 72-hour window.

To improve recall, a fallback direct-keyword subreddit search was added for high-intent terms like:

- `Delighted`
- `Delighted alternative`
- `NPS tool`
- `customer feedback tool`

## Final Technical Decision

Because live HTML/browser scraping was blocked, the implementation was adjusted to use Reddit’s public JSON listing and search endpoints instead.

This means the shipped version is:

- still read-only
- still no-login
- still no Reddit API credentials required
- more reliable in this environment than the original browser approach

## Files Created

New files added:

- [reddit_monitor.py](/c:/Users/resoa/Videos/X_Post/reddit_monitor.py)
- [reddit_scraper.py](/c:/Users/resoa/Videos/X_Post/reddit_scraper.py)
- [reddit_scorer.py](/c:/Users/resoa/Videos/X_Post/reddit_scorer.py)
- [reddit_db.py](/c:/Users/resoa/Videos/X_Post/reddit_db.py)
- [README_REDDIT.md](/c:/Users/resoa/Videos/X_Post/README_REDDIT.md)
- [tests/test_reddit_scorer.py](/c:/Users/resoa/Videos/X_Post/tests/test_reddit_scorer.py)
- [tests/test_reddit_db.py](/c:/Users/resoa/Videos/X_Post/tests/test_reddit_db.py)
- [tests/test_reddit_monitor.py](/c:/Users/resoa/Videos/X_Post/tests/test_reddit_monitor.py)
- [REDDIT_IMPLEMENTATION_REPORT.md](/c:/Users/resoa/Videos/X_Post/REDDIT_IMPLEMENTATION_REPORT.md)

## Old Files Changed

Only one pre-existing project file was edited as part of this Reddit work:

- [README_REDDIT.md](/c:/Users/resoa/Videos/X_Post/README_REDDIT.md)

Note:

`README_REDDIT.md` was new during this work session, but after creation it was updated once to reflect the direct-keyword fallback behavior.

## Old Files Not Changed By This Work

The Reddit monitor intentionally reused existing project infrastructure without editing it:

- [config.py](/c:/Users/resoa/Videos/X_Post/config.py)
- [notifier.py](/c:/Users/resoa/Videos/X_Post/notifier.py)
- [db.py](/c:/Users/resoa/Videos/X_Post/db.py)
- [session.py](/c:/Users/resoa/Videos/X_Post/session.py)
- [orchestrator.py](/c:/Users/resoa/Videos/X_Post/orchestrator.py)

These files were read and reused for compatibility, but not modified by this implementation.

## Verification Performed

### Tests

Ran:

```powershell
python -m unittest discover -s tests -v
```

Result:

- all tests passed

### Dry run

Ran:

```powershell
python reddit_monitor.py --dry-run
```

Result:

- completed successfully
- fetched posts from all 7 target subreddits
- exercised the fallback keyword search path
- generated a digest message

## Current Limitations

- Browser/Chrome scraping for Reddit is not used in the final implementation because Reddit blocked that path in this environment.
- Current scoring is tuned for precision, so lead volume may be low unless the subreddit activity contains explicit matching intent.
- The fallback keyword search increases runtime, though it improves recall.

## Recommended Next Steps

- Add a Windows Task Scheduler job for `python reddit_monitor.py`
- Decide whether to relax scoring thresholds for higher lead volume
- Optionally persist richer metadata if Ravi wants deeper review context in the digest
