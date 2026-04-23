# Project Stages

This project is easiest to reason about as four stages. The X browser/session layer is the most sensitive part of the system and should be treated as a protected area unless there is a concrete production issue to fix.

## Stage 1: X Session And Discovery

Purpose:
- open Chrome
- restore X cookies or log in
- search configured keywords
- scrape, filter, and score posts

Primary files:
- `session.py`
- `searcher.py`
- `x_cookies.json`

Risk level:
- high

Notes:
- avoid cleanup work here unless the X flow is broken
- small selector or timing changes can break discovery entirely

## Stage 2: Research Enrichment

Purpose:
- generate optional AI response suggestions for X findings
- rank and surface Reddit leads
- optionally generate Reddit hot-lead comments

Primary files:
- `ai.py`
- `reddit_monitor.py`
- `reddit_scorer.py`
- `reddit_scraper.py`

Risk level:
- medium

Notes:
- failures here should degrade gracefully
- network or model outages should not erase already-collected research

## Stage 3: Delivery

Purpose:
- send digests and alerts to Telegram
- preserve failed deliveries for manual recovery

Primary files:
- `notifier.py`
- `delivery_failures/`

Risk level:
- low to medium

Notes:
- this stage should never be the only copy of the research
- delivery failure is different from discovery failure

## Stage 4: State And Reporting

Purpose:
- log runs
- track seen items
- support daily stats
- preserve enough history to debug failures

Primary files:
- `db.py`
- `reddit_db.py`
- `stats_reporter.py`
- `agent.db`
- `reddit_monitor.db`
- `logs/`

Risk level:
- low

Notes:
- this is the safest place for cleanup and better observability
- `commented_posts` and `standalone_posts` are now treated as archive-only legacy tables

## Recommended Cleanup Order

1. Delivery and failure preservation
2. Feature inventory and removal of dead paths
3. Reddit flow simplification
4. AI enrichment toggles and fallbacks
5. X session/search changes only when necessary

The current feature classification lives in `FEATURE_INVENTORY.md`.
