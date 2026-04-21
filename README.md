# X_Post

Automated social-intelligence and publishing system for Elvan.

This project combines X engagement, standalone post generation, Reddit monitoring, SQLite persistence, Telegram notifications, and scheduled execution on Windows.

## What It Does

- Finds relevant opportunities on X
- Generates and validates replies and standalone posts
- Tracks daily limits, run history, and failure state in SQLite
- Sends Telegram alerts and summaries
- Monitors Reddit for relevant leads
- Runs on a scheduled cadence through Windows Task Scheduler

## Main Workflows

### X engagement

The X agent can:

- check browser health
- search for relevant posts
- generate replies with AI
- publish standalone posts
- send a daily report
- send a richer stats report

### Reddit monitoring

The Reddit monitor scans selected subreddits, ranks posts by relevance, deduplicates results, and sends a Telegram digest.

#### Hot Lead Alert System

On top of the regular digest, the monitor applies conversion intent scoring bonuses and fires urgent Telegram alerts for high-value posts before the digest is sent.

**Scoring bonuses (applied after base scoring):**

- **+25 points** — post contains a question mark (`?`) AND any of: `alternative`, `replace`, `replacement`, `looking for`, `recommend`, `switch`, `switching`, `what do you use`, `anyone using`, `anyone tried`, `moved away`, `moved from`, `migrated`, `shut down`, `shutdown`
- **+10 points** — post mentions `Delighted` anywhere (case-insensitive)

Both bonuses stack.

**Hot lead threshold:** any post with a boosted relevance score ≥ 8 is a "hot lead."

**Per-alert Telegram message** (sent before the digest):

```
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

- `orchestrator.py` for the X agent commands
- `reddit_monitor.py` for the Reddit digest flow
- `register_elvan_tasks.ps1` for Windows scheduled task setup

## Commands

Run the X orchestrator with one of these commands:

- `health-check`
- `engage`
- `publish`
- `daily-report`
- `stats-report`

Example:

```powershell
python orchestrator.py stats-report
```

Dry run:

```powershell
python orchestrator.py stats-report --dry-run
```

Run the Reddit monitor:

```powershell
python reddit_monitor.py
```

## Project Structure

- `config.py` loads environment-based settings
- `db.py` stores X agent state in `agent.db`
- `reddit_db.py` stores Reddit state in `reddit_monitor.db`
- `ai.py` generates and validates content
- `searcher.py` discovers relevant X posts
- `poster.py` handles reply and post publishing
- `notifier.py` sends Telegram messages
- `logger.py` configures logging

## Configuration

The project reads settings from `.env` and environment variables.

Common values include:

- `X_USERNAME`
- `X_PASSWORD`
- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TIMEZONE`

## Data Files

The main SQLite files are:

- `agent.db`
- `reddit_monitor.db`

These files store operational history, run logs, seen items, and daily counters.

`reddit_monitor.db` schema includes a `hot_lead_alerted` column (integer, default 0) in the `reddit_seen_posts` table. This flag is set to 1 after a hot lead Telegram alert is sent for that post, preventing duplicate alerts across runs.

## Scheduled Tasks

`register_elvan_tasks.ps1` registers the Windows scheduled tasks for the X agent.

It is intended to run the automation without manual intervention.

## Development Notes

- The project uses standard Python tooling and SQLite for persistence
- Telegram messages are used for alerts and summaries
- The codebase is designed to be stateful and repeatable rather than one-off

## Author

- Initials: Mortarion002
- GitHub: Mortarion002
- Email: resoamankumar@gmail.com

## Built For

[elvan.ai](https://elvan.ai)
