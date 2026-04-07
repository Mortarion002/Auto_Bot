# Elvan Reddit Monitor
## Phase 2 — Keyword Intelligence & Lead Discovery

**Part of:** Elvan X Agent project (`X_POST/`)  
**Status:** Planning  
**Built by:** Aman Kumar (Intern)  
**Manager:** Raviraj

---

## What We Are Building

A Reddit keyword monitor that watches relevant subreddits daily and surfaces posts where people are talking about NPS tools, customer feedback, churn, and Delighted alternatives — the exact pain points Elvan solves.

This is a **read-only intelligence tool**. It does not post or comment on Reddit. It finds opportunities and delivers them to Ravi via a daily Telegram digest, so humans can decide what to do with each one.

---

## Why Reddit

Reddit is where SaaS founders, indie hackers, and customer success professionals ask genuine questions and vent real frustrations. Unlike X where content is often promotional, Reddit discussions tend to be raw and honest. A post like "our Delighted contract ends next month, what are people switching to?" on r/SaaS is a live sales opportunity — and it gets buried fast if nobody catches it in time.

The monitor catches it for us automatically, every day.

---

## What It Watches

### Subreddits

| Subreddit | Why |
|---|---|
| r/SaaS | SaaS founders discussing tools and stack decisions |
| r/startups | Early-stage founders making tooling decisions |
| r/Entrepreneur | Business owners looking for feedback/survey tools |
| r/CustomerSuccess | CS professionals discussing NPS and feedback |
| r/ProductManagement | PMs evaluating survey and feedback tools |
| r/indiehackers | Indie builders, high overlap with Elvan's ICP |
| r/SideProject | Builders shipping early products, potential Elvan users |

### Keywords

**Direct (high intent):**
- `NPS tool`, `net promoter score`, `CSAT tool`
- `Delighted`, `Delighted alternative`, `Delighted shutdown`
- `customer feedback tool`, `survey tool`
- `SurveyMonkey alternative`, `Typeform alternative`

**Pain points (medium intent):**
- `churn`, `customer retention`, `feedback loop`
- `survey fatigue`, `response rate`, `voice of customer`
- `customer satisfaction`, `customer health score`

**Community (discovery):**
- `NPS`, `customer feedback`, `product feedback`

---

## How It Works

```
Windows Task Scheduler (once daily — 08:00)
        ↓
reddit_monitor.py
        ↓
  ┌─────────────────────────┐
  │  Reddit Scraper         │
  │  - Opens Chrome         │
  │  - No login needed      │  ← Public pages, no auth required
  │  - Visits each sub      │
  │  - Searches keywords    │
  │  - Scrapes post data    │
  └─────────────────────────┘
        ↓
  ┌─────────────────────────┐
  │  Scorer & Filter        │
  │  - Keyword match check  │
  │  - Recency filter       │  ← Posts < 72 hours old only
  │  - Dedup via SQLite     │  ← Never surfaces same post twice
  │  - Priority scoring     │
  └─────────────────────────┘
        ↓
  ┌─────────────────────────┐
  │  Telegram Digest        │
  │  - High priority posts  │
  │  - Direct Reddit links  │
  │  - Sent every evening   │
  └─────────────────────────┘
```

---

## What the Daily Digest Looks Like

```
📊 Elvan Reddit Monitor — April 8, 2026

🔥 High Priority (3 posts)

• r/SaaS — "We need a Delighted replacement ASAP"
  Keyword: Delighted alternative | 47 upvotes | 12 comments
  → reddit.com/r/saas/comments/xyz

• r/CustomerSuccess — "Best NPS tools for B2B SaaS?"
  Keyword: NPS tool | 31 upvotes | 8 comments
  → reddit.com/r/customersuccess/comments/abc

• r/indiehackers — "How do you collect NPS at scale?"
  Keyword: NPS | 18 upvotes | 5 comments
  → reddit.com/r/indiehackers/comments/def

📌 Worth Reading (5 posts)
• r/startups — "Churn is killing us, need better feedback loops"
  → reddit.com/r/startups/comments/ghi
...

Total scanned: 340 posts across 7 subreddits
Keyword matches today: 8
New (not seen before): 6

Next digest: April 9, 2026 at 22:00
```

---

## New Files Being Added

```
X_POST/
├── reddit_monitor.py      ← main runner (scrapes, scores, digests)
├── reddit_scraper.py      ← Chrome automation for Reddit pages
├── reddit_scorer.py       ← keyword matching and priority scoring
├── reddit_db.py           ← SQLite tables for seen/flagged posts
└── README_REDDIT.md       ← this file
```

Everything else in the project (`session.py`, `notifier.py`, `db.py`, `config.py`) is **reused as-is**. The Reddit monitor is a self-contained addition, not a rewrite.

---

## Approach

**No Reddit API, no login.**

Reddit's public pages are fully accessible without authentication. We use the same `undetected-chromedriver` setup already working for X to navigate subreddit pages and search results directly. This means:

- No Reddit developer account needed
- No API rate limits to worry about
- No session management or credential storage
- Same Chrome automation stack already tested and working

**Scoring logic:**

Each post gets a priority score based on:
- Keyword match strength (exact phrase > partial match)
- Post recency (newer = higher score)
- Engagement (upvotes + comment count)
- Subreddit relevance weight (r/SaaS > r/Entrepreneur for our ICP)

Posts above a threshold go into "High Priority", the rest into "Worth Reading". Posts already seen are filtered out via SQLite so the digest only shows new discoveries.

---

## What Ravi Does With the Digest

The monitor surfaces the opportunity — humans decide what to do:

1. **Reply on Reddit** — Drop a genuine, helpful comment mentioning Elvan where it fits naturally
2. **Feed into X content** — A Reddit question about NPS response rates becomes a standalone X post topic
3. **Sales signal** — A post asking for Delighted alternatives gets forwarded to the outreach pipeline

---

## Timeline

| Step | What |
|---|---|
| Step 1 | Build `reddit_scraper.py` — navigate subreddits, scrape post data |
| Step 2 | Build `reddit_scorer.py` — keyword match and priority scoring |
| Step 3 | Build `reddit_db.py` — SQLite dedup and history |
| Step 4 | Build `reddit_monitor.py` — orchestrate scrape → score → digest |
| Step 5 | Add Task Scheduler job — daily 08:00 run |
| Step 6 | Test and verify digest output |

---

## Dependencies

No new dependencies needed. Reuses:
- `undetected-chromedriver` — already installed
- `selenium` — already installed
- `sqlite3` — stdlib
- `requests` — already installed (for Telegram)

---

*This document will be updated as the module is built.*