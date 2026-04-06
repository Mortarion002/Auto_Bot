# X_AGENT_SPEC.md
## Elvan — X (Twitter) Social Agent
**Version:** 1.0  
**Author:** Eternal  
**Status:** Draft — Pending Review  
**Last Updated:** April 2026

---

## 1. Overview

This document specifies the architecture, behavior, and implementation plan for Elvan's X (Twitter) social agent. The agent runs fully autonomously on a local Windows machine, using browser automation (Playwright) instead of the X API. It operates under the developer persona — a technical co-founder building Elvan — and is designed to grow organic presence in SaaS, NPS, CX, and Build-in-Public communities on X.

The agent does two things:
1. **Engage** — Find relevant posts and leave meaningful, value-adding comments
2. **Publish** — Post original standalone content on a schedule

---

## 2. Goals

| Goal | Description |
|---|---|
| Brand awareness | Build Elvan's name in the NPS/CX/SaaS space organically |
| Community presence | Establish the developer persona as a credible voice |
| Traffic | Drive curious users to getelvan.com over time |
| Signups | Convert engaged readers into trial users |

**Non-goals:**
- Spamming or promotional blasting
- Posting low-quality or irrelevant content
- Triggering X rate limits or account flags

---

## 3. Persona

**Who is posting:** A developer who is actively building Elvan with their team. Not a marketer. Not a brand account.

**Voice:**
- Technical, genuine, and opinionated
- Shares real builder insights and lessons
- Comments add value first — Elvan is mentioned only when contextually natural
- Occasionally references "we're building something in this space" without hard-selling
- Engages like a peer, not a vendor

**Example comment tone:**
> "This is exactly the problem we ran into when building our feedback loop — most tools either oversimplify NPS or bury the data. Curious what your response rates looked like?"

**Example standalone post tone:**
> "Unpopular opinion: a 40% NPS survey response rate is actually a red flag, not a win. It usually means you're only hearing from your happiest users. We learned this the hard way while building Elvan. Here's what changed when we fixed our distribution timing 🧵"

---

## 4. Keyword Universe

### 4.1 Direct / NPS / Feedback
- `NPS`, `net promoter score`, `CSAT`, `CES`
- `customer feedback`, `feedback tool`, `survey tool`
- `Delighted alternative`, `Delighted shutdown`
- `Typeform alternative`, `SurveyMonkey alternative`
- `customer satisfaction score`, `measuring customer sentiment`

### 4.2 SaaS / Startup
- `SaaS metrics`, `churn`, `churn rate`, `customer retention`
- `product-market fit`, `early stage SaaS`, `bootstrapped SaaS`
- `SaaS founder`, `B2B SaaS`, `indie SaaS`
- `customer success`, `customer onboarding`

### 4.3 Build in Public
- `#buildinpublic`, `#indiehacker`, `#SaaS`
- `shipped today`, `launched today`, `week N of building`
- `building in public`, `my startup`, `#makersoftwitter`

### 4.4 Product Hunt / Launch
- `just launched on PH`, `Product Hunt launch`, `#ProductHunt`
- `new tool`, `just shipped`, `soft launch`

### 4.5 Pain Points (high intent)
- `collecting NPS`, `NPS response rate`, `customer survey`
- `survey fatigue`, `feedback loop`, `voice of customer`
- `customer health score`, `retention metrics`

---

## 5. Architecture

```
Windows Task Scheduler
        │
        ▼
  orchestrator.py          ← main entry point, runs on schedule
        │
        ├──► session.py    ← manages persistent Playwright browser session
        │                     (uses already-logged-in Chrome profile)
        │
        ├──► searcher.py   ← searches X for keywords, scrapes post data,
        │                     scores and filters posts
        │
        ├──► ai.py         ← Claude API wrapper
        │                     generates comments + standalone posts
        │                     enforces persona and content rules
        │
        ├──► poster.py     ← types and submits content on X via Playwright
        │                     handles human-like delays and typing speed
        │
        ├──► db.py         ← SQLite database
        │                     tracks posts seen, posts commented on,
        │                     standalone posts published, errors
        │
        └──► logger.py     ← structured logging to file + console
```

---

## 6. Module Specifications

### 6.1 session.py — Browser Session Manager
- Connects to existing Chrome instance via `--remote-debugging-port` OR
- Launches Playwright with a persistent profile directory (already logged-in state)
- Does **not** log in fresh every run — avoids login detection
- Exposes a single `get_page()` function used by all other modules

### 6.2 searcher.py — Post Discovery
**Inputs:** keyword list (from config)  
**Process:**
1. Navigate to `x.com/search?q=<keyword>&f=live` or `&f=top`
2. Scroll to load N posts (configurable, default: 20 per keyword)
3. For each post, scrape:
   - Post ID (for dedup)
   - Author handle
   - Post text
   - Like count, reply count, repost count
   - Timestamp
4. Filter out:
   - Posts already in SQLite (`commented_posts` table)
   - Posts from Elvan's own account
   - Posts older than 48 hours
   - Posts with <10 likes (too low signal)
   - Posts with >50k likes (too big, reply will be buried)
5. Score remaining posts:
   - Engagement score = likes + (replies × 2) + (reposts × 1.5)
   - Recency bonus: posts < 2hr old get 1.5× multiplier
6. Return top N posts sorted by score (default: top 5 per run)

**Output:** List of scored post objects

### 6.3 ai.py — Claude API Content Generator
**Model:** claude-sonnet-4-20250514  
**Two modes:**

**Mode 1: Comment Generation**
- Input: post text + author handle + keyword context
- System prompt enforces:
  - Developer persona
  - Value-first, non-promotional tone
  - 1–3 sentences max (X comment best practice)
  - Never mention Elvan unless post is directly about NPS/feedback tools
  - No hashtags in comments
  - No emojis unless contextually natural
- Output: comment text (validated for length < 280 chars)

**Mode 2: Standalone Post Generation**
- Input: topic category (rotates through predefined list)
- System prompt enforces:
  - Developer persona
  - Hook in first line (no "I" starts)
  - 150–250 chars for single posts, or thread format (🧵) for longer
  - 1–2 relevant hashtags max
  - Subtle Elvan reference allowed in ~30% of posts
- Topic rotation (cycles daily):
  1. NPS insight / data point
  2. Build-in-public update (Elvan progress)
  3. CX / customer retention take
  4. SaaS founder lesson
  5. Contrarian opinion on feedback/surveys

**Output:** post text (validated)

### 6.4 poster.py — X Interaction Layer
**Comment posting flow:**
1. Navigate to post URL
2. Click reply button
3. Type comment with human-like random keystroke delay (50–150ms per char)
4. Random pause before submitting (3–8 seconds)
5. Click "Reply" button
6. Confirm post appeared (check for success state)
7. Log to SQLite

**Standalone post flow:**
1. Navigate to x.com home
2. Click compose box
3. Type post with human-like delay
4. Optional: add image (future feature)
5. Random pause (5–12 seconds)
6. Click "Post"
7. Log to SQLite

**Anti-detection measures:**
- Random mouse movement before clicks
- Randomized delays between all actions
- Never runs at exact scheduled times (±5 min jitter)
- Max 3 retries on failure before skipping

### 6.5 db.py — SQLite Database

**Tables:**

```sql
CREATE TABLE commented_posts (
  post_id TEXT PRIMARY KEY,
  author TEXT,
  post_text TEXT,
  comment_text TEXT,
  keyword TEXT,
  commented_at TIMESTAMP,
  status TEXT  -- 'success' | 'failed' | 'skipped'
);

CREATE TABLE standalone_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_text TEXT,
  topic_category TEXT,
  posted_at TIMESTAMP,
  status TEXT
);

CREATE TABLE seen_posts (
  post_id TEXT PRIMARY KEY,
  first_seen TIMESTAMP
);

CREATE TABLE run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TIMESTAMP,
  posts_found INTEGER,
  comments_posted INTEGER,
  standalone_posted INTEGER,
  errors TEXT
);
```

### 6.6 orchestrator.py — Main Runner

**Daily schedule (approximate, all times have ±5–15 min jitter):**

| Time | Action |
|---|---|
| 09:00 | Morning run: search + comment (5 posts) |
| 10:30 | Standalone post #1 |
| 12:30 | Midday run: search + comment (5 posts) |
| 14:00 | Standalone post #2 |
| 17:00 | Evening run: search + comment (5 posts) |
| 19:30 | Standalone post #3 |
| 21:00 | Optional late run: search + comment (3 posts) |

**Per run logic:**
1. Initialize browser session
2. Run searcher across N keywords (rotates keyword list each run)
3. For each top-scored post:
   - Generate comment via ai.py
   - Validate comment
   - Post via poster.py
   - Wait random 20–40 min before next comment
4. If standalone post scheduled: generate + post
5. Log run to DB
6. Close browser session

**Daily hard limits (safety caps):**
- Max 18 comments/day
- Max 4 standalone posts/day
- Max 40 searches/day
- If any limit hit → stop for the day, log reason

---

## 7. Configuration File (config.py)

```python
# Account
ACCOUNT_HANDLE = "@yourhandle"
CHROME_PROFILE_PATH = "C:/Users/Gojo/AppData/Local/Google/Chrome/User Data"

# Claude API
ANTHROPIC_API_KEY = "sk-ant-..."  # store in .env, not here

# Limits
MAX_COMMENTS_PER_DAY = 18
MAX_POSTS_PER_DAY = 4
MAX_SEARCHES_PER_DAY = 40

# Search settings
POSTS_PER_KEYWORD_PER_RUN = 20
TOP_POSTS_TO_COMMENT = 5
MIN_LIKES = 10
MAX_LIKES = 50000
MAX_POST_AGE_HOURS = 48

# Timing
COMMENT_DELAY_MIN = 1200   # 20 min in seconds
COMMENT_DELAY_MAX = 2400   # 40 min in seconds
RUN_JITTER_MIN = 300       # 5 min
RUN_JITTER_MAX = 900       # 15 min

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
KEYWORDS = [
    "NPS", "net promoter score", "CSAT",
    "customer feedback tool", "Delighted alternative",
    "survey tool SaaS", "churn rate", "customer retention",
    "#buildinpublic", "#indiehacker SaaS",
    "bootstrapped SaaS", "B2B SaaS founder",
    "Product Hunt launch", "just shipped",
    "feedback loop", "voice of customer",
    "customer satisfaction", "survey fatigue"
]
```

---

## 8. Content Rules (AI Guardrails)

The Claude prompt enforces these rules on every generation:

**Always:**
- Add genuine value to the conversation
- Sound like a real developer, not a tool
- Keep comments under 280 chars
- Be specific to the post content

**Never:**
- Start with "As a developer building Elvan..."
- Use generic phrases: "Great post!", "Totally agree!", "This is so true"
- Drop a link to getelvan.com in comments (too spammy)
- Use more than 2 hashtags in standalone posts
- Post anything political, controversial, or off-brand
- Mention competitors negatively

**Elvan mention rules:**
- In comments: only if post is directly about NPS/feedback tools AND it fits naturally
- In standalone posts: ~30% of posts can reference Elvan naturally
- Always framed as "we're building" not "use our tool"

---

## 9. Reddit Module (Phase 2)

Lower priority. Monitor only for now, no posting.

**Subreddits to watch:**
- r/SaaS, r/startups, r/Entrepreneur
- r/CustomerSuccess, r/ProductManagement
- r/indiehackers, r/SideProject

**Keywords to flag:**
- "NPS tool", "Delighted", "customer feedback", "survey tool"
- "churn", "customer satisfaction", "CSAT"

**Output:** Daily digest CSV of flagged posts → reviewed manually by Eternal/Ravi

**Implementation:** Python + PRAW (if API access works) or Playwright scrape fallback

---

## 10. File Structure

```
elvan-x-agent/
├── orchestrator.py       ← main runner
├── session.py            ← browser session
├── searcher.py           ← post discovery
├── ai.py                 ← Claude API wrapper
├── poster.py             ← X interaction
├── db.py                 ← SQLite handler
├── logger.py             ← logging
├── notifier.py           ← Telegram alerts
├── config.py             ← settings (no secrets)
├── .env                  ← API keys (gitignored)
├── .gitignore
├── requirements.txt
├── agent.db              ← SQLite database (gitignored)
├── logs/
│   └── agent_YYYY-MM-DD.log
└── README.md
```

---

## 11. Dependencies

```
playwright
anthropic
python-dotenv
schedule
sqlite3 (stdlib)
loguru
```

---

## 12. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| X detects automation | Medium | Human-like delays, persistent session, jitter on all timing |
| Account flagged/banned | Low-Medium | Stay within safe limits, avoid aggressive keyword stuffing |
| AI generates bad comment | Low | Content validation layer, length check, keyword filter for off-brand terms |
| Duplicate comments | Low | SQLite dedup on post_id before every action |
| Chrome session expires | Medium | Session health check at start of every run, alert on failure |
| API key exposed | Low | .env file, .gitignore, never hardcoded |

---

## 13. Phase Roadmap

| Phase | Scope | Timeline |
|---|---|---|
| Phase 1 | X comment agent + standalone posts | Build now |
| Phase 2 | Reddit monitor + digest | After Phase 1 stable |
| Phase 3 | LinkedIn (minimal) | TBD |
| Phase 4 | Analytics dashboard (what's working) | TBD |

---

## 14. Telegram Alerts

The agent sends a Telegram message at the end of every daily run via a bot.

**Setup required (one-time):**
1. Create a bot via @BotFather on Telegram → get `BOT_TOKEN`
2. Get your personal `CHAT_ID` (message the bot once, then hit `api.telegram.org/bot<token>/getUpdates`)
3. Add both to `.env`

**Alert format (end of day summary):**
```
🤖 Elvan X Agent — Daily Report
📅 April 06, 2026

✅ Comments posted: 15/18
📝 Standalone posts: 4/4
🔍 Searches run: 32/40

⚠️ Errors: 1 (post_id: xyz123 — timeout)

Next run: tomorrow 09:00
```

**Alert triggers:**
| Event | Alert |
|---|---|
| Daily run complete | Full summary (above) |
| Hard limit hit mid-day | ⚠️ Warning with reason |
| Browser session failure | 🚨 Critical — agent stopped |
| 3 consecutive comment failures | ⚠️ Warning |

**Implementation:** `notifier.py` module using `python-telegram-bot` or raw `requests` to Telegram Bot API (simpler, no extra lib needed).

```python
# notifier.py (raw requests approach)
import requests, os

def send_alert(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
```

---

## 15. Decisions Locked

| # | Question | Answer |
|---|---|---|
| 1 | Chrome profile path | `C:/Users/Gojo/AppData/Local/Google/Chrome/User Data` |
| 2 | Images in standalone posts | No |
| 3 | DMs | No — humans handle all direct outreach |

All questions resolved. Spec is final. ✅

---

*This spec is the source of truth for the X agent build. Any changes to behavior, limits, or persona should be updated here first.*