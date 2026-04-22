from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


PRIORITY_KEYWORDS = [
    "Delighted alternative",
    "Delighted shutdown",
    "replacing Delighted",
    "SurveyMonkey alternative",
    "Typeform alternative",
    "customer feedback tool",
    "NPS tool",
    "survey tool SaaS",
]

ROTATION_KEYWORDS = [
    "survey fatigue",
    "low NPS response rate",
    "NPS response rate",
    "feedback loop broken",
    "customers not responding to surveys",
    "net promoter score",
    "voice of customer",
    "feedback loop",
    "CSAT score",
    "NPS methodology",
    "churn feedback",
    "customer health score",
]

DEFAULT_KEYWORDS = [*PRIORITY_KEYWORDS, *ROTATION_KEYWORDS]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


@dataclass(slots=True)
class Settings:
    base_dir: Path
    db_path: Path
    logs_dir: Path
    delivery_failures_dir: Path
    account_handle: str = "@yourhandle"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    x_username: str | None = None
    x_password: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    timezone: str = "Asia/Calcutta"
    dry_run: bool = False
    daily_report_time: str = "22:00"
    queue_run_time: str = "08:00"
    queue_max_reply_drafts: int = 25
    max_searches_per_day: int = 40
    posts_per_keyword_per_run: int = 20
    top_posts_to_comment: int = 5
    keyword_batch_size: int = 10
    min_valid_posts_before_top_fallback: int = 2
    min_likes: int = 10
    min_likes_research: int = 5
    max_likes: int = 50000
    max_post_age_hours: int = 48
    max_scroll_rounds: int = 6
    scroll_pause_seconds: int = 2
    request_timeout_seconds: int = 20
    priority_keywords: list[str] = field(default_factory=lambda: list(PRIORITY_KEYWORDS))
    rotation_keywords: list[str] = field(default_factory=lambda: list(ROTATION_KEYWORDS))
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))

    @property
    def normalized_account_handle(self) -> str:
        return self.account_handle.lstrip("@").lower()

    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_settings(base_dir: Path | None = None) -> Settings:
    root = base_dir or Path(__file__).resolve().parent
    return Settings(
        base_dir=root,
        db_path=root / "agent.db",
        logs_dir=root / "logs",
        delivery_failures_dir=root / "delivery_failures",
        account_handle=_env_str("ACCOUNT_HANDLE", "@yourhandle"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=_env_str("GEMINI_MODEL", "gemini-2.5-flash"),
        x_username=os.getenv("X_USERNAME"),
        x_password=os.getenv("X_PASSWORD"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        timezone=_env_str("TIMEZONE", "Asia/Calcutta"),
        dry_run=_env_bool("DRY_RUN", False),
        daily_report_time=_env_str("DAILY_REPORT_TIME", "22:00"),
        queue_run_time=_env_str("QUEUE_RUN_TIME", "08:00"),
        queue_max_reply_drafts=_env_int("QUEUE_MAX_REPLY_DRAFTS", 25),
        max_searches_per_day=_env_int("MAX_SEARCHES_PER_DAY", 40),
        posts_per_keyword_per_run=_env_int("POSTS_PER_KEYWORD_PER_RUN", 20),
        top_posts_to_comment=_env_int("TOP_POSTS_TO_COMMENT", 5),
        keyword_batch_size=_env_int("KEYWORD_BATCH_SIZE", 10),
        min_valid_posts_before_top_fallback=_env_int(
            "MIN_VALID_POSTS_BEFORE_TOP_FALLBACK",
            2,
        ),
        min_likes=_env_int("MIN_LIKES", 10),
        min_likes_research=_env_int("MIN_LIKES_RESEARCH", 5),
        max_likes=_env_int("MAX_LIKES", 50000),
        max_post_age_hours=_env_int("MAX_POST_AGE_HOURS", 48),
        max_scroll_rounds=_env_int("MAX_SCROLL_ROUNDS", 6),
        scroll_pause_seconds=_env_int("SCROLL_PAUSE_SECONDS", 2),
        request_timeout_seconds=_env_int("REQUEST_TIMEOUT_SECONDS", 20),
    )
