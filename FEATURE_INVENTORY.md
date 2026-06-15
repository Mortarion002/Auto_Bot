# Feature Inventory

This file classifies the current project by what is actively used in the research-bot workflow, what is intentionally protected, and what remains only as historical compatibility.

## Active Runtime Features

### X research digest

Purpose:

- open a logged-in X session
- search configured keywords
- filter and score candidate posts
- generate optional reply suggestions
- send a digest to Telegram

Primary files:

- `orchestrator.py`
- `queue_builder.py`
- `searcher.py`
- `session.py`
- `ai.py`
- `notifier.py`

### Reddit monitoring

Purpose:

- scan target subreddits via Atom/RSS feed (no credentials required)
- rank relevant posts
- optionally send hot-lead alerts
- send a Reddit digest to Telegram

Notes:

- `reddit_scraper.py` uses Reddit's public Atom/RSS feed (`/new/.rss`, `/search.rss`)
- switched from the `.json` API in June 2026 after Reddit began returning 403 for all unauthenticated JSON requests
- upvote and comment counts are not available in the RSS feed and default to 0; keyword/recency scoring is unaffected
- rate limiting handled dynamically via `X-Ratelimit-Reset` / `X-Ratelimit-Remaining` headers; Reddit enforces ~60 s per request for unauthenticated RSS

Primary files:

- `reddit_monitor.py`
- `reddit_scraper.py`
- `reddit_scorer.py`
- `reddit_db.py`
- `notifier.py`

### HackerNews + Product Hunt signal monitoring

Purpose:

- scan HackerNews (Algolia API, no credentials) for NPS/feedback/competitor discussions
- scan Product Hunt (GraphQL API, developer token) for relevant product launches
- keyword-filter and score signals using the same rule-based approach as the Reddit scorer
- dedup via Neon `signal_events` table to avoid re-processing seen posts
- send a daily digest to Telegram
- upsert all new signals to Neon for dashboard visibility

Notes:

- `hn_scraper.py` runs 8 keyword queries against the Algolia HN API with a 14-day lookback; no credentials required
- `ph_scraper.py` runs 2 GraphQL queries (customer-success topic + newest posts); requires `PRODUCTHUNT_DEV_TOKEN`
- `signal_filter.py` contains keyword lists (product terms, competitor terms, pain terms) and a `score_signal()` function; no AI used
- scoring mirrors `reddit_scorer.py`: intent base + location bonus + buying-signal bonus + engagement + source bonus
- tiers: hot ≥ 70, medium ≥ 40, low < 40

Primary files:

- `signal_monitor.py`
- `hn_scraper.py`
- `ph_scraper.py`
- `signal_filter.py`
- `neon_store.py`
- `notifier.py`

### Reporting and persistence

Purpose:

- log runs
- track already-seen items
- provide a daily stats summary
- preserve failed Telegram deliveries

Primary files:

- `db.py`
- `reddit_db.py`
- `stats_reporter.py`
- `logs/`
- `delivery_failures/`

## Protected Surface

These files are intentionally sensitive and should only be changed when there is a concrete production issue to fix.

- `session.py`
- `searcher.py`
- `x_cookies.json`

## Removed Legacy Paths

These paths belonged to the older posting workflow and were removed because they are not part of the current research-bot runtime:

- `poster.py`
- `tests/test_poster.py`
- standalone X-post generation in `ai.py`
- posting-only config settings for publish/retry/typing cadence

## Historical Compatibility Still Present

These pieces are still in the codebase because they hold old data or support compatibility, but they are not part of the active research workflow.

- `commented_posts` table in `agent.db`
  kept as an archive-only record of the older comment-posting workflow
- `standalone_posts` table in `agent.db`
  kept as an archive-only record of the older standalone-post workflow
- `post_ideas_generated` column in `queue_runs`
  retained as a legacy compatibility column; active research code treats it as archival only
- disabled CLI commands in `orchestrator.py`: `engage`, `publish`, `daily-report`

## Suggested Next Cleanup Pass

1. Decide whether the archive-only posting tables should stay in `agent.db` long-term or move to a one-time export.
2. If the research workflow stays stable, consider a future SQLite migration that renames legacy columns instead of only annotating them in code.
3. Review whether historical compatibility wrappers in `db.py` should remain indefinitely or be removed in a later cleanup cycle.
