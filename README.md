# Elvan X Agent

Autonomous Phase 1 X agent for Elvan. The agent runs on Windows, attaches to an already-running Chrome instance over the DevTools debug port, and supports:

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
python -m playwright install chromium
```

2. Start Chrome once and leave it running:

```powershell
chrome.exe --remote-debugging-port=9222 --profile-directory="Profile 1"
```

3. Copy `.env.example` to `.env` and fill in:

- `ACCOUNT_HANDLE`
- `CHROME_PROFILE_NAME`
- `CHROME_REMOTE_DEBUG_URL`
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

4. Make sure that Chrome profile is already logged into X.

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

If you want Chrome to start automatically at login, add the same debug-port command to Windows Task Scheduler or a startup shortcut before the agent jobs run.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The test suite covers:

- DB schema and rotation state
- content validation guardrails
- search scoring helpers
- poster retry and dry-run logic
