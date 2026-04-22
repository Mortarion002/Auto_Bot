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
- scan target subreddits
- rank relevant posts
- optionally send hot-lead alerts
- send a Reddit digest to Telegram

Primary files:
- `reddit_monitor.py`
- `reddit_scraper.py`
- `reddit_scorer.py`
- `reddit_db.py`
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

These pieces are still in the codebase because they hold old data or support reporting, but they are not part of the active research workflow.

- `commented_posts` table in `agent.db`
- `standalone_posts` table in `agent.db`
- `post_ideas_generated` column in `queue_runs`
- disabled CLI commands in `orchestrator.py`: `engage`, `publish`, `daily-report`

## Suggested Next Cleanup Pass

1. Rename or annotate historical database fields that no longer describe active behavior.
2. Decide whether `commented_posts` and `standalone_posts` should remain as archival tables or move to a migration/export step.
3. If the research workflow is stable, simplify queue/report wording so only active concepts appear in logs and summaries.
