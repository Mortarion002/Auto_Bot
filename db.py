from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from models import DiscoveredPost


class Database:
    def __init__(self, db_path: Path, logger: Any):
        self.db_path = db_path
        self.logger = logger
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self.conn.close()

    def _initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS commented_posts (
              post_id TEXT PRIMARY KEY,
              post_url TEXT,
              author TEXT,
              post_text TEXT,
              comment_text TEXT,
              keyword TEXT,
              post_created_at TEXT,
              engagement_score REAL,
              commented_at TEXT,
              status TEXT,
              status_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS standalone_posts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_text TEXT,
              topic_category TEXT,
              posted_at TEXT,
              status TEXT,
              status_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS seen_posts (
              post_id TEXT PRIMARY KEY,
              first_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS run_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_type TEXT,
              run_at TEXT,
              started_at TEXT,
              finished_at TEXT,
              posts_found INTEGER DEFAULT 0,
              comments_posted INTEGER DEFAULT 0,
              standalone_posted INTEGER DEFAULT 0,
              searches_run INTEGER DEFAULT 0,
              stop_reason TEXT,
              errors TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_state (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_commented_posts_commented_at
            ON commented_posts(commented_at);

            CREATE INDEX IF NOT EXISTS idx_standalone_posts_posted_at
            ON standalone_posts(posted_at);

            CREATE INDEX IF NOT EXISTS idx_run_log_run_at
            ON run_log(run_at);
            """
        )

        self._ensure_column("commented_posts", "post_url", "TEXT")
        self._ensure_column("commented_posts", "post_created_at", "TEXT")
        self._ensure_column("commented_posts", "engagement_score", "REAL")
        self._ensure_column("commented_posts", "status_reason", "TEXT")
        self._ensure_column("standalone_posts", "status_reason", "TEXT")
        self._ensure_column("run_log", "run_type", "TEXT")
        self._ensure_column("run_log", "searches_run", "INTEGER DEFAULT 0")
        self._ensure_column("run_log", "stop_reason", "TEXT")
        self._ensure_column("run_log", "started_at", "TEXT")
        self._ensure_column("run_log", "finished_at", "TEXT")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def start_run(self, run_type: str, started_at: str) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO run_log (
              run_type, run_at, started_at, finished_at,
              posts_found, comments_posted, standalone_posted, searches_run,
              stop_reason, errors
            ) VALUES (?, ?, ?, NULL, 0, 0, 0, 0, NULL, NULL)
            """,
            (run_type, started_at, started_at),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        finished_at: str,
        posts_found: int = 0,
        comments_posted: int = 0,
        standalone_posted: int = 0,
        searches_run: int = 0,
        stop_reason: str | None = None,
        errors: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE run_log
            SET finished_at = ?,
                posts_found = ?,
                comments_posted = ?,
                standalone_posted = ?,
                searches_run = ?,
                stop_reason = ?,
                errors = ?
            WHERE id = ?
            """,
            (
                finished_at,
                posts_found,
                comments_posted,
                standalone_posted,
                searches_run,
                stop_reason,
                errors,
                run_id,
            ),
        )
        self.conn.commit()

    def has_commented(self, post_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM commented_posts WHERE post_id = ? LIMIT 1",
            (post_id,),
        ).fetchone()
        return row is not None

    def mark_post_seen(self, post_id: str, seen_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO seen_posts(post_id, first_seen)
            VALUES(?, ?)
            ON CONFLICT(post_id) DO NOTHING
            """,
            (post_id, seen_at),
        )
        self.conn.commit()

    def log_comment(
        self,
        post: DiscoveredPost,
        comment_text: str,
        *,
        status: str,
        status_reason: str,
        commented_at: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO commented_posts (
              post_id, post_url, author, post_text, comment_text, keyword,
              post_created_at, engagement_score, commented_at, status, status_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
              post_url = excluded.post_url,
              author = excluded.author,
              post_text = excluded.post_text,
              comment_text = excluded.comment_text,
              keyword = excluded.keyword,
              post_created_at = excluded.post_created_at,
              engagement_score = excluded.engagement_score,
              commented_at = excluded.commented_at,
              status = excluded.status,
              status_reason = excluded.status_reason
            """,
            (
                post.post_id,
                post.post_url,
                post.author_handle,
                post.text,
                comment_text,
                post.keyword,
                post.created_at.isoformat(),
                post.score,
                commented_at,
                status,
                status_reason,
            ),
        )
        self.conn.commit()

    def log_standalone_post(
        self,
        post_text: str,
        topic_category: str,
        *,
        status: str,
        status_reason: str,
        posted_at: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO standalone_posts (
              post_text, topic_category, posted_at, status, status_reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (post_text, topic_category, posted_at, status, status_reason),
        )
        self.conn.commit()

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM agent_state WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_state(self, key: str, value: str, updated_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_state(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              updated_at = excluded.updated_at
            """,
            (key, value, updated_at),
        )
        self.conn.commit()

    def get_int_state(self, key: str, default: int = 0) -> int:
        raw = self.get_state(key)
        if raw is None:
            return default
        return int(raw)

    def increment_state(self, key: str, updated_at: str, amount: int = 1) -> int:
        value = self.get_int_state(key, 0) + amount
        self.set_state(key, str(value), updated_at)
        return value

    def get_rotating_keywords(
        self,
        keywords: list[str],
        batch_size: int,
        *,
        updated_at: str,
        advance: bool = True,
    ) -> list[str]:
        if not keywords or batch_size <= 0:
            return []

        cursor = self.get_int_state("keyword_cursor", 0)
        selected = [
            keywords[(cursor + index) % len(keywords)]
            for index in range(min(batch_size, len(keywords)))
        ]
        if advance:
            self.set_state("keyword_cursor", str(cursor + len(selected)), updated_at)
        return selected

    def get_next_topic(
        self,
        topics: list[str],
        *,
        updated_at: str,
        advance: bool = True,
    ) -> tuple[str, int, bool]:
        if not topics:
            raise ValueError("Topic rotation cannot be empty.")

        cursor = self.get_int_state("topic_cursor", 0)
        topic = topics[cursor % len(topics)]
        generation_number = cursor + 1
        allow_elvan_reference = generation_number % 3 == 0
        if advance:
            self.set_state("topic_cursor", str(cursor + 1), updated_at)
        return topic, generation_number, allow_elvan_reference

    def get_consecutive_comment_failures(self) -> int:
        return self.get_int_state("consecutive_comment_failures", 0)

    def set_consecutive_comment_failures(self, value: int, updated_at: str) -> None:
        self.set_state("consecutive_comment_failures", str(value), updated_at)

    def _day_bounds(
        self,
        timezone_name: str,
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone) if now else datetime.now(zone)
        start_local = datetime.combine(local_now.date(), time.min, tzinfo=zone)
        end_local = start_local + timedelta(days=1)
        return start_local.isoformat(), end_local.isoformat(), local_now.date().isoformat()

    def get_daily_activity_counts(
        self,
        timezone_name: str,
        now: datetime | None = None,
    ) -> dict[str, int | str]:
        start_at, end_at, day_key = self._day_bounds(timezone_name, now)

        comments_row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM commented_posts
            WHERE status = 'success'
              AND commented_at IS NOT NULL
              AND commented_at >= ?
              AND commented_at < ?
            """,
            (start_at, end_at),
        ).fetchone()

        posts_row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM standalone_posts
            WHERE status = 'success'
              AND posted_at IS NOT NULL
              AND posted_at >= ?
              AND posted_at < ?
            """,
            (start_at, end_at),
        ).fetchone()

        searches_row = self.conn.execute(
            """
            SELECT COALESCE(SUM(searches_run), 0) AS count
            FROM run_log
            WHERE run_at >= ?
              AND run_at < ?
            """,
            (start_at, end_at),
        ).fetchone()

        return {
            "day_key": day_key,
            "comments_posted": int(comments_row["count"]),
            "standalone_posted": int(posts_row["count"]),
            "searches_run": int(searches_row["count"]),
        }

    def get_daily_failure_summary(
        self,
        timezone_name: str,
        now: datetime | None = None,
    ) -> tuple[int, str | None]:
        start_at, end_at, _ = self._day_bounds(timezone_name, now)
        failures: list[str] = []

        comment_rows = self.conn.execute(
            """
            SELECT post_id, status_reason
            FROM commented_posts
            WHERE status = 'failed'
              AND commented_at IS NOT NULL
              AND commented_at >= ?
              AND commented_at < ?
            ORDER BY commented_at DESC
            LIMIT 5
            """,
            (start_at, end_at),
        ).fetchall()
        failures.extend(
            [
                f"comment {row['post_id']}: {row['status_reason']}"
                for row in comment_rows
                if row["status_reason"]
            ]
        )

        standalone_rows = self.conn.execute(
            """
            SELECT topic_category, status_reason
            FROM standalone_posts
            WHERE status = 'failed'
              AND posted_at IS NOT NULL
              AND posted_at >= ?
              AND posted_at < ?
            ORDER BY posted_at DESC
            LIMIT 5
            """,
            (start_at, end_at),
        ).fetchall()
        failures.extend(
            [
                f"post {row['topic_category']}: {row['status_reason']}"
                for row in standalone_rows
                if row["status_reason"]
            ]
        )

        run_rows = self.conn.execute(
            """
            SELECT stop_reason, errors
            FROM run_log
            WHERE run_at >= ?
              AND run_at < ?
              AND (stop_reason IS NOT NULL OR errors IS NOT NULL)
            ORDER BY run_at DESC
            LIMIT 5
            """,
            (start_at, end_at),
        ).fetchall()
        for row in run_rows:
            if row["stop_reason"]:
                failures.append(str(row["stop_reason"]))
            if row["errors"]:
                failures.append(str(row["errors"]))

        summary = failures[0] if failures else None
        return len(failures), summary
