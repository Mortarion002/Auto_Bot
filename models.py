from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class DiscoveredPost:
    post_id: str
    post_url: str
    author_handle: str
    text: str
    likes: int
    replies: int
    reposts: int
    created_at: datetime
    keyword: str
    search_mode: str
    score: float = 0.0


@dataclass(slots=True)
class CommentDraft:
    post_id: str
    text: str
    char_count: int
    mentions_elvan: bool
    validation_errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SessionHealth:
    ok: bool
    reason: str = ""
