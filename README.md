# Elvan X Agent

Autonomous Phase 1 X agent for Elvan. The agent runs on Windows, launches your installed Chrome via `nodriver`, and supports:

- `health-check` to confirm the X session is still logged in
- `engage` to discover posts, generate comments, and reply
- `publish` to generate and publish a standalone post
- `daily-report` to send a Telegram summary

## Setup

1. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in:

- `ACCOUNT_HANDLE`
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

3. `nodriver` launches Chrome automatically. The browser path, user data directory, and profile directory are currently defined in `session.py`.

4. Make sure that the configured Chrome profile is already logged into X.

## Commands

```powershell
python orchestrator.py health-check
python orchestrator.py engage --dry-run
python orchestrator.py publish --dry-run
python orchestrator.py daily-report --dry-run
```

`--dry-run` skips run jitter, inter-comment waits, database state rotation, Telegram alerts, and final submit clicks. It still exercises discovery, draft generation, and typing flows.

## Windows Task Scheduler

Create separate scheduled tasks that invoke:

- `python orchestrator.py engage`
- `python orchestrator.py publish`
- `python orchestrator.py daily-report`

Recommended schedule:

- `engage`: 09:00, 12:30, 17:00, 21:00
- `publish`: 10:30, 14:00, 19:30
- `daily-report`: 22:00

The agent applies its own 5-15 minute start jitter on scheduled runs.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The test suite covers:

- DB schema and rotation state
- content validation guardrails
- search scoring helpers
- poster retry and dry-run logic
