from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from reddit_scorer import RedditLead


class RedditDatabase:
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
            CREATE TABLE IF NOT EXISTS reddit_seen_posts (
              post_id TEXT PRIMARY KEY,
              post_url TEXT NOT NULL,
              subreddit TEXT NOT NULL,
              author TEXT,
              title TEXT NOT NULL,
              matched_keywords TEXT,
              primary_keyword TEXT,
              priority TEXT,
              score REAL,
              created_at TEXT,
              first_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reddit_run_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              posts_scanned INTEGER DEFAULT 0,
              matches_found INTEGER DEFAULT 0,
              new_matches INTEGER DEFAULT 0,
              high_priority_count INTEGER DEFAULT 0,
              digest_sent INTEGER DEFAULT 0,
              errors TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_reddit_seen_first_seen
            ON reddit_seen_posts(first_seen);

            CREATE INDEX IF NOT EXISTS idx_reddit_run_log_started_at
            ON reddit_run_log(started_at);
            """
        )
        self.conn.commit()

    def start_run(self, started_at: str) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO reddit_run_log(
              started_at, finished_at, posts_scanned, matches_found,
              new_matches, high_priority_count, digest_sent, errors
            ) VALUES (?, NULL, 0, 0, 0, 0, 0, NULL)
            """,
            (started_at,),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        finished_at: str,
        posts_scanned: int,
        matches_found: int,
        new_matches: int,
        high_priority_count: int,
        digest_sent: bool,
        errors: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE reddit_run_log
            SET finished_at = ?,
                posts_scanned = ?,
                matches_found = ?,
                new_matches = ?,
                high_priority_count = ?,
                digest_sent = ?,
                errors = ?
            WHERE id = ?
            """,
            (
                finished_at,
                posts_scanned,
                matches_found,
                new_matches,
                high_priority_count,
                int(digest_sent),
                errors,
                run_id,
            ),
        )
        self.conn.commit()

    def has_seen(self, post_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM reddit_seen_posts WHERE post_id = ? LIMIT 1",
            (post_id,),
        ).fetchone()
        return row is not None

    def mark_seen(self, lead: RedditLead, seen_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO reddit_seen_posts (
              post_id, post_url, subreddit, author, title, matched_keywords,
              primary_keyword, priority, score, created_at, first_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
              post_url = excluded.post_url,
              subreddit = excluded.subreddit,
              author = excluded.author,
              title = excluded.title,
              matched_keywords = excluded.matched_keywords,
              primary_keyword = excluded.primary_keyword,
              priority = excluded.priority,
              score = excluded.score,
              created_at = excluded.created_at
            """,
            (
                lead.post.post_id,
                lead.post.post_url,
                lead.post.subreddit,
                lead.post.author,
                lead.post.title,
                ", ".join(lead.matched_keywords),
                lead.primary_keyword,
                lead.priority,
                lead.score,
                lead.post.created_at.isoformat(),
                seen_at,
            ),
        )
        self.conn.commit()

    def mark_many_seen(self, leads: list[RedditLead], seen_at: str) -> None:
        for lead in leads:
            self.conn.execute(
                """
                INSERT INTO reddit_seen_posts (
                  post_id, post_url, subreddit, author, title, matched_keywords,
                  primary_keyword, priority, score, created_at, first_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                  post_url = excluded.post_url,
                  subreddit = excluded.subreddit,
                  author = excluded.author,
                  title = excluded.title,
                  matched_keywords = excluded.matched_keywords,
                  primary_keyword = excluded.primary_keyword,
                  priority = excluded.priority,
                  score = excluded.score,
                  created_at = excluded.created_at
                """,
                (
                    lead.post.post_id,
                    lead.post.post_url,
                    lead.post.subreddit,
                    lead.post.author,
                    lead.post.title,
                    ", ".join(lead.matched_keywords),
                    lead.primary_keyword,
                    lead.priority,
                    lead.score,
                    lead.post.created_at.isoformat(),
                    seen_at,
                ),
            )
        self.conn.commit()
