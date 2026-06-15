# X_Post

Analysis-first social research system for Elvan.

This project scans X, Reddit, HackerNews, and Product Hunt, ranks relevant conversations, generates optional response suggestions, stores run history in SQLite, and sends research digests through Telegram.
It also mirrors findings and run summaries into Neon Postgres as a parallel analytics channel for dashboard visibility.

## What It Does

- Finds relevant conversations on X
- Surfaces notable Reddit leads
- Monitors HackerNews and Product Hunt for NPS/feedback/competitor signals
- Generates optional response suggestions for X findings
- Sends research digests and stats reports through Telegram
- Preserves failed Telegram deliveries in `delivery_failures/` for manual recovery
- Tracks run history, seen items, and failures in SQLite
- Writes all surfaced signals to Neon Postgres (`signal_events` table) for dashboard visibility
- Runs on a schedule through Windows Task Scheduler

## Main Workflows

### X research

The X agent can:

- check browser health
- search for relevant posts
- rank and filter conversations
- send an X research digest to Telegram
- send a daily research stats summary

### HN + Product Hunt signal monitoring

`signal_monitor.py` fetches posts from HackerNews (Algolia API, no auth) and Product Hunt (GraphQL API) daily, keyword-filters them for NPS/feedback/competitor relevance, scores them with the same rule-based approach used for Reddit, deduplicates via Neon, and sends a Telegram digest. New signals are upserted into the `signal_events` Neon table so they appear in the dashboard alongside Reddit and X findings.

### Reddit monitoring

The Reddit monitor scans selected subreddits via Atom/RSS (no credentials required), ranks posts by relevance, deduplicates results, and sends a Telegram digest. Rate limiting is handled dynamically using Reddit's own `X-Ratelimit-Reset` response headers.

#### Hot Lead Alert System

On top of the regular digest, the monitor applies conversion intent scoring bonuses and fires urgent Telegram alerts for high-value posts before the digest is sent.

**Scoring bonuses (applied after base scoring):**

- **+25 points** — post contains a question mark (`?`) AND any of: `alternative`, `replace`, `replacement`, `looking for`, `recommend`, `switch`, `switching`, `what do you use`, `anyone using`, `anyone tried`, `moved away`, `moved from`, `migrated`, `shut down`, `shutdown`
- **+10 points** — post mentions `Delighted` anywhere (case-insensitive)

Both bonuses stack.

**Hot lead threshold:** any post with a boosted relevance score ≥ 8 is a "hot lead."

**Per-alert Telegram message** (sent before the digest):

```text
🔥 HOT LEAD — r/{subreddit}

👤 u/{author} · Score: {boosted_score}
📌 {title}

"{body preview up to 300 chars}..."

💬 Draft comment:
{Gemini-generated Reddit comment}

🔗 {url}

─────────────────────
Copy the draft → paste it manually on Reddit
```

If Gemini comment generation fails, the draft section shows `[Generation failed — reply manually]` and the alert is still sent.

**Digest integration:** hot lead posts appear in the regular digest with a `🔥` prefix on their title so they're visually distinct.

**Deduplication:** once an alert is sent for a post, `hot_lead_alerted = 1` is written to `reddit_monitor.db`. The same post never triggers a second alert across runs.

## Entry Points

- `orchestrator.py` for X research commands
- `reddit_monitor.py` for the Reddit digest flow
- `signal_monitor.py` for the HN + Product Hunt signal digest
- `register_elvan_tasks.ps1` for Windows scheduled task setup

## Commands

Run the X orchestrator with one of these commands:

- `health-check`
- `build-queue`
- `stats-report`

Example:

```powershell
python orchestrator.py build-queue
```

Dry run:

```powershell
python orchestrator.py build-queue --dry-run
```

Run the Reddit monitor:

```powershell
python reddit_monitor.py
```

Run the HN + Product Hunt signal monitor:

```powershell
python signal_monitor.py
```

Dry run (no Telegram, no Neon writes):

```powershell
python signal_monitor.py --dry-run
```

## Project Structure

- `config.py` loads environment-based settings
- `db.py` stores X research state in `agent.db`
- `reddit_db.py` stores Reddit state in `reddit_monitor.db`
- `ai.py` generates and validates response suggestions
- `neon_store.py` mirrors findings and workflow runs into Neon when configured
- `searcher.py` discovers relevant X posts
- `queue_builder.py` builds the X and Reddit Telegram digest
- `reddit_scraper.py` fetches Reddit posts via Atom/RSS feed
- `reddit_scorer.py` scores and ranks Reddit leads
- `hn_scraper.py` fetches HackerNews posts via Algolia API
- `ph_scraper.py` fetches Product Hunt posts via GraphQL API
- `signal_filter.py` keyword-filters and scores HN/PH signals
- `signal_monitor.py` orchestrates the HN + PH daily digest
- `notifier.py` sends Telegram messages
- `logger.py` configures logging

For an operational map of the current stages and safe cleanup boundaries, see `PROJECT_STAGES.md`.
For a classification of active vs legacy features, see `FEATURE_INVENTORY.md`.

## Configuration

The project reads settings from `.env` and environment variables.

Common values include:

- `X_USERNAME`
- `X_PASSWORD`
- `GEMINI_API_KEY`
- `NEON_DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TIMEZONE`
- `PRODUCTHUNT_DEV_TOKEN` — required for Product Hunt scraping (get from producthunt.com/v2/oauth/applications)

## Data Files

The main SQLite files are:

- `agent.db`
- `reddit_monitor.db`

Failed Telegram deliveries are preserved as timestamped text files in:

- `delivery_failures/`

These files store operational history, seen items, run logs, and research summaries.

If `NEON_DATABASE_URL` is set, the bot also writes parallel copies of surfaced findings and workflow runs into Neon tables:

- `signal_events`
- `workflow_runs`

`agent.db` also retains `commented_posts` and `standalone_posts` as archive-only tables from the older posting workflow. They are kept for history, not as part of the active research-bot flow.

`reddit_monitor.db` schema includes a `hot_lead_alerted` column (integer, default 0) in the `reddit_seen_posts` table. This flag is set to 1 after a hot lead Telegram alert is sent for that post, preventing duplicate alerts across runs.

## Scheduled Tasks

`register_elvan_tasks.ps1` registers all scheduled tasks:

| Task name | Script | Default time |
| --- | --- | --- |
| `ElvanAgent_BuildQueue` | `orchestrator.py build-queue` | 09:50 daily |
| `ElvanAgent_Reddit_Monitor` | `reddit_monitor.py` | 09:40 daily |
| `ElvanAgent_Signal_Monitor` | `signal_monitor.py` | 09:30 daily |
| `ElvanAgent_StatsReport` | `orchestrator.py stats-report` | 22:05 daily |

Run the script as Administrator to register or update all tasks:

```powershell
.\register_elvan_tasks.ps1
```

## Development Notes

- The project uses standard Python tooling and SQLite for persistence
- Telegram messages are used for digests, alerts, and summaries
- X live posting and posting reports are disabled in analysis-only mode

## Author

- Initials: Mortarion002
- GitHub: Mortarion002
- Email: [resoamankumar@gmail.com](mailto:resoamankumar@gmail.com)

## Built For

[elvan.ai](https://elvan.ai)
