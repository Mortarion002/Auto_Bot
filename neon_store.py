from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import Settings

try:
    import psycopg
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None


SIGNAL_EVENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signal_events (
  id BIGSERIAL PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  source_system TEXT NOT NULL,
  workflow TEXT NOT NULL,
  external_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  body TEXT,
  url TEXT,
  author TEXT,
  subreddit TEXT,
  matched_keyword TEXT,
  intent TEXT,
  urgency TEXT,
  priority TEXT,
  tool_mentioned TEXT,
  pain_point TEXT,
  elvan_angle TEXT,
  draft_reply TEXT,
  score DOUBLE PRECISION,
  base_score DOUBLE PRECISION,
  boosted_score DOUBLE PRECISION,
  likes INTEGER,
  replies INTEGER,
  reposts INTEGER,
  comments_count INTEGER,
  upvotes INTEGER,
  alerted BOOLEAN NOT NULL DEFAULT FALSE,
  hot_lead BOOLEAN NOT NULL DEFAULT FALSE,
  occurred_at TIMESTAMPTZ,
  first_captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_signal_events_source_occurred
ON signal_events(source, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_priority_occurred
ON signal_events(priority, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_tool
ON signal_events(tool_mentioned);
"""

WORKFLOW_RUNS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_runs (
  id BIGSERIAL PRIMARY KEY,
  source_system TEXT NOT NULL,
  workflow TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  posts_discovered INTEGER,
  drafts_generated INTEGER,
  reddit_leads INTEGER,
  queue_sent BOOLEAN,
  searches_run INTEGER,
  posts_scanned INTEGER,
  matches_found INTEGER,
  new_matches INTEGER,
  high_priority_count INTEGER,
  digest_sent BOOLEAN,
  hot_lead_alerts_sent INTEGER,
  stop_reason TEXT,
  errors TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_source_started
ON workflow_runs(source_system, started_at DESC);
"""

UPSERT_SIGNAL_SQL = """
INSERT INTO signal_events (
  dedupe_key, source, source_system, workflow, external_id, title, body, url,
  author, subreddit, matched_keyword, intent, urgency, priority, tool_mentioned,
  pain_point, elvan_angle, draft_reply, score, base_score, boosted_score, likes,
  replies, reposts, comments_count, upvotes, alerted, hot_lead, occurred_at,
  metadata
) VALUES (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
)
ON CONFLICT (dedupe_key) DO UPDATE SET
  source = EXCLUDED.source,
  source_system = EXCLUDED.source_system,
  workflow = EXCLUDED.workflow,
  external_id = EXCLUDED.external_id,
  title = EXCLUDED.title,
  body = EXCLUDED.body,
  url = EXCLUDED.url,
  author = EXCLUDED.author,
  subreddit = EXCLUDED.subreddit,
  matched_keyword = EXCLUDED.matched_keyword,
  intent = EXCLUDED.intent,
  urgency = EXCLUDED.urgency,
  priority = EXCLUDED.priority,
  tool_mentioned = EXCLUDED.tool_mentioned,
  pain_point = EXCLUDED.pain_point,
  elvan_angle = EXCLUDED.elvan_angle,
  draft_reply = EXCLUDED.draft_reply,
  score = EXCLUDED.score,
  base_score = EXCLUDED.base_score,
  boosted_score = EXCLUDED.boosted_score,
  likes = EXCLUDED.likes,
  replies = EXCLUDED.replies,
  reposts = EXCLUDED.reposts,
  comments_count = EXCLUDED.comments_count,
  upvotes = EXCLUDED.upvotes,
  alerted = EXCLUDED.alerted,
  hot_lead = EXCLUDED.hot_lead,
  occurred_at = EXCLUDED.occurred_at,
  metadata = signal_events.metadata || EXCLUDED.metadata,
  last_updated_at = NOW();
"""

INSERT_WORKFLOW_RUN_SQL = """
INSERT INTO workflow_runs (
  source_system, workflow, started_at, finished_at, status, posts_discovered,
  drafts_generated, reddit_leads, queue_sent, searches_run, posts_scanned,
  matches_found, new_matches, high_priority_count, digest_sent,
  hot_lead_alerts_sent, stop_reason, errors, metadata
) VALUES (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
  %s::jsonb
);
"""


class NeonStore:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger
        self.database_url = settings.neon_database_url
        self._schema_ready = False

    @property
    def enabled(self) -> bool:
        return bool(self.database_url) and psycopg is not None

    def ensure_schema(self) -> bool:
        if not self.enabled:
            return False
        if self._schema_ready:
            return True

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(SIGNAL_EVENTS_SCHEMA_SQL)
                cursor.execute(WORKFLOW_RUNS_SCHEMA_SQL)
            conn.commit()

        self._schema_ready = True
        return True

    def record_x_findings(
        self,
        findings: list[dict[str, Any]],
        *,
        observed_at: str | datetime,
        workflow: str = "build-queue",
        source_system: str = "x_post",
    ) -> int:
        rows = []
        for finding in findings:
            post_id = str(finding.get("post_id") or "").strip()
            post_url = str(finding.get("post_url") or "").strip()
            if not post_id and not post_url:
                continue

            full_text = str(
                finding.get("post_text")
                or finding.get("post_text_excerpt")
                or ""
            ).strip()
            title = str(finding.get("post_text_excerpt") or full_text or f"X post {post_id}").strip()
            rows.append(
                {
                    "dedupe_key": f"x:{post_id or post_url}",
                    "source": "x",
                    "source_system": source_system,
                    "workflow": workflow,
                    "external_id": post_id or None,
                    "title": title,
                    "body": full_text or None,
                    "url": post_url or None,
                    "author": self._normalized_author(finding.get("author_handle")),
                    "subreddit": None,
                    "matched_keyword": self._optional_text(finding.get("keyword")),
                    "intent": None,
                    "urgency": None,
                    "priority": None,
                    "tool_mentioned": None,
                    "pain_point": None,
                    "elvan_angle": None,
                    "draft_reply": self._optional_text(finding.get("response_suggestion")),
                    "score": self._optional_float(finding.get("score")),
                    "base_score": None,
                    "boosted_score": None,
                    "likes": self._optional_int(finding.get("likes")),
                    "replies": self._optional_int(finding.get("replies")),
                    "reposts": self._optional_int(finding.get("reposts")),
                    "comments_count": None,
                    "upvotes": None,
                    "alerted": False,
                    "hot_lead": False,
                    "occurred_at": self._coerce_datetime(
                        finding.get("post_created_at") or observed_at
                    ),
                    "metadata": {
                        "kind": "x_finding",
                        "search_mode": self._optional_text(finding.get("search_mode")),
                    },
                }
            )

        return self.record_signal_rows(rows)

    def record_reddit_leads(
        self,
        leads: list[dict[str, Any]],
        *,
        observed_at: str | datetime,
        workflow: str,
        source_system: str,
    ) -> int:
        rows = []
        for lead in leads:
            post_id = str(lead.get("post_id") or "").strip()
            post_url = str(lead.get("url") or "").strip()
            if not post_id and not post_url:
                continue

            rows.append(
                {
                    "dedupe_key": f"reddit:{post_id or post_url}",
                    "source": "reddit",
                    "source_system": source_system,
                    "workflow": workflow,
                    "external_id": post_id or None,
                    "title": self._optional_text(lead.get("post_title")) or "Reddit lead",
                    "body": self._optional_text(lead.get("post_body")),
                    "url": post_url or None,
                    "author": self._optional_text(lead.get("author")),
                    "subreddit": self._optional_text(lead.get("subreddit")),
                    "matched_keyword": self._optional_text(lead.get("primary_keyword")),
                    "intent": self._optional_text(lead.get("keyword_intent")),
                    "urgency": None,
                    "priority": self._optional_text(lead.get("priority")),
                    "tool_mentioned": None,
                    "pain_point": None,
                    "elvan_angle": None,
                    "draft_reply": self._optional_text(lead.get("draft_reply")),
                    "score": self._optional_float(lead.get("score")),
                    "base_score": None,
                    "boosted_score": self._optional_float(lead.get("boosted_score")),
                    "likes": None,
                    "replies": None,
                    "reposts": None,
                    "comments_count": self._optional_int(lead.get("comments")),
                    "upvotes": self._optional_int(lead.get("upvotes")),
                    "alerted": bool(lead.get("hot_lead_alerted") or lead.get("alerted")),
                    "hot_lead": bool(lead.get("hot_lead")),
                    "occurred_at": self._coerce_datetime(
                        lead.get("created_at") or observed_at
                    ),
                    "metadata": {
                        "kind": "reddit_lead",
                        "matched_keywords": list(lead.get("matched_keywords") or []),
                    },
                }
            )

        return self.record_signal_rows(rows)

    def record_signal_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows or not self.ensure_schema():
            return 0

        payloads = [
            (
                row["dedupe_key"],
                row["source"],
                row["source_system"],
                row["workflow"],
                row["external_id"],
                row["title"],
                row["body"],
                row["url"],
                row["author"],
                row["subreddit"],
                row["matched_keyword"],
                row["intent"],
                row["urgency"],
                row["priority"],
                row["tool_mentioned"],
                row["pain_point"],
                row["elvan_angle"],
                row["draft_reply"],
                row["score"],
                row["base_score"],
                row["boosted_score"],
                row["likes"],
                row["replies"],
                row["reposts"],
                row["comments_count"],
                row["upvotes"],
                row["alerted"],
                row["hot_lead"],
                row["occurred_at"],
                json.dumps(row.get("metadata") or {}),
            )
            for row in rows
        ]

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(UPSERT_SIGNAL_SQL, payloads)
            conn.commit()

        return len(rows)

    def record_workflow_run(
        self,
        *,
        source_system: str,
        workflow: str,
        started_at: str | datetime,
        finished_at: str | datetime | None,
        status: str,
        posts_discovered: int | None = None,
        drafts_generated: int | None = None,
        reddit_leads: int | None = None,
        queue_sent: bool | None = None,
        searches_run: int | None = None,
        posts_scanned: int | None = None,
        matches_found: int | None = None,
        new_matches: int | None = None,
        high_priority_count: int | None = None,
        digest_sent: bool | None = None,
        hot_lead_alerts_sent: int | None = None,
        stop_reason: str | None = None,
        errors: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if not self.ensure_schema():
            return False

        payload = (
            source_system,
            workflow,
            self._coerce_datetime(started_at),
            self._coerce_datetime(finished_at),
            status,
            posts_discovered,
            drafts_generated,
            reddit_leads,
            queue_sent,
            searches_run,
            posts_scanned,
            matches_found,
            new_matches,
            high_priority_count,
            digest_sent,
            hot_lead_alerts_sent,
            stop_reason,
            errors,
            json.dumps(metadata or {}),
        )

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(INSERT_WORKFLOW_RUN_SQL, payload)
            conn.commit()

        return True

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalized_author(value: Any) -> str | None:
        text = NeonStore._optional_text(value)
        if text is None:
            return None
        return text if text.startswith("@") else f"@{text}"

    @staticmethod
    def _coerce_datetime(value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
