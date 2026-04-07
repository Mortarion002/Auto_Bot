from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from reddit_scraper import RedditPost


TARGET_SUBREDDITS = [
    "SaaS",
    "startups",
    "Entrepreneur",
    "CustomerSuccess",
    "ProductManagement",
    "indiehackers",
    "SideProject",
]

DIRECT_KEYWORDS = [
    "NPS tool",
    "net promoter score",
    "CSAT tool",
    "Delighted",
    "Delighted alternative",
    "Delighted shutdown",
    "customer feedback tool",
    "survey tool",
    "SurveyMonkey alternative",
    "Typeform alternative",
]

PAIN_POINT_KEYWORDS = [
    "churn",
    "customer retention",
    "feedback loop",
    "survey fatigue",
    "response rate",
    "voice of customer",
    "customer satisfaction",
    "customer health score",
]

DISCOVERY_KEYWORDS = [
    "NPS",
    "customer feedback",
    "product feedback",
]

ALL_KEYWORDS = DIRECT_KEYWORDS + PAIN_POINT_KEYWORDS + DISCOVERY_KEYWORDS
RECENCY_WINDOW_HOURS = 72
HIGH_PRIORITY_THRESHOLD = 75.0
WORTH_READING_THRESHOLD = 45.0

SUBREDDIT_BONUS = {
    "saas": 8.0,
    "customersuccess": 7.0,
    "productmanagement": 6.0,
    "indiehackers": 5.0,
    "startups": 4.0,
    "entrepreneur": 3.0,
    "sideproject": 2.0,
}

INTENT_BASE_SCORE = {
    "direct": 28.0,
    "pain": 16.0,
    "discovery": 10.0,
}

KEYWORD_GROUPS = {
    "direct": {keyword.lower() for keyword in DIRECT_KEYWORDS},
    "pain": {keyword.lower() for keyword in PAIN_POINT_KEYWORDS},
    "discovery": {keyword.lower() for keyword in DISCOVERY_KEYWORDS},
}

PROMOTIONAL_PATTERNS = [
    "free audit",
    "i built",
    "we built",
    "i made",
    "check out",
    "looking for users",
    "roast my",
    "launching",
    "launched",
    "promo",
]

BUYING_SIGNAL_PATTERNS = [
    "looking for",
    "need",
    "best",
    "alternative",
    "replacement",
    "replace",
    "switch",
    "recommend",
    "what are people using",
    "help",
]


@dataclass(frozen=True, slots=True)
class KeywordMatch:
    keyword: str
    intent: str
    strength: int
    location: str


@dataclass(slots=True)
class RedditLead:
    post: RedditPost
    matched_keywords: tuple[str, ...]
    primary_keyword: str
    priority: str
    score: float
    age_hours: float
    keyword_intent: str


def rank_posts(
    posts: list[RedditPost],
    *,
    now: datetime | None = None,
) -> list[RedditLead]:
    current = now or datetime.now(timezone.utc)
    leads: list[RedditLead] = []

    for post in posts:
        lead = score_post(post, now=current)
        if lead is not None:
            leads.append(lead)

    return sorted(leads, key=lambda item: item.score, reverse=True)


def score_post(
    post: RedditPost,
    *,
    now: datetime | None = None,
) -> RedditLead | None:
    current = now or datetime.now(timezone.utc)
    normalized_text = _normalize_text(post.text)
    age_hours = (
        current - post.created_at.astimezone(timezone.utc)
    ).total_seconds() / 3600
    if age_hours > RECENCY_WINDOW_HOURS:
        return None
    if _is_promotional(normalized_text):
        return None

    matches = _find_keyword_matches(post)
    if not matches:
        return None

    title_matches = [match for match in matches if match.location == "title"]
    primary = max(title_matches or matches, key=_keyword_sort_key)
    matched_keywords = tuple(sorted({match.keyword for match in matches}, key=str.lower))
    buying_signal_score = _buying_signal_score(post)

    if primary.intent in {"pain", "discovery"} and primary.location != "title":
        return None
    if primary.intent != "direct" and primary.location != "title" and buying_signal_score <= 0:
        return None

    score = 0.0
    score += INTENT_BASE_SCORE[primary.intent]
    score += _match_strength_score(primary)
    score += min(12.0, 4.0 * max(0, len(matched_keywords) - 1))
    score += _recency_score(age_hours)
    score += _engagement_score(post.upvotes, post.comment_count)
    score += SUBREDDIT_BONUS.get(post.subreddit.lower(), 0.0)
    score += buying_signal_score

    if score >= HIGH_PRIORITY_THRESHOLD:
        priority = "high"
    elif score >= WORTH_READING_THRESHOLD:
        priority = "medium"
    else:
        priority = "low"

    return RedditLead(
        post=post,
        matched_keywords=matched_keywords,
        primary_keyword=primary.keyword,
        priority=priority,
        score=round(score, 2),
        age_hours=round(age_hours, 2),
        keyword_intent=primary.intent,
    )


def _find_keyword_matches(post: RedditPost) -> list[KeywordMatch]:
    title = _normalize_text(post.title)
    body = _normalize_text(post.body)
    matches: list[KeywordMatch] = []

    for keyword in ALL_KEYWORDS:
        normalized_keyword = keyword.lower()
        phrase = _normalize_text(keyword)
        location = ""
        strength = 0

        if _contains_keyword(title, phrase):
            location = "title"
            strength = 3
        elif _contains_keyword(body, phrase):
            location = "body"
            strength = 2

        if strength == 0:
            continue

        matches.append(
            KeywordMatch(
                keyword=keyword,
                intent=_keyword_intent(normalized_keyword),
                strength=strength,
                location=location,
            )
        )

    return matches


def _keyword_intent(keyword: str) -> str:
    for intent, keywords in KEYWORD_GROUPS.items():
        if keyword in keywords:
            return intent
    return "discovery"


def _keyword_sort_key(match: KeywordMatch) -> tuple[int, int, int, int]:
    intent_priority = {
        "direct": 3,
        "pain": 2,
        "discovery": 1,
    }
    location_priority = {
        "title": 3,
        "body": 2,
        "full_text": 1,
    }
    return (
        intent_priority.get(match.intent, 0),
        match.strength,
        location_priority.get(match.location, 0),
        len(match.keyword),
    )


def _match_strength_score(match: KeywordMatch) -> float:
    if match.location == "title":
        return 24.0
    if match.location == "body":
        return 16.0
    return 8.0


def _recency_score(age_hours: float) -> float:
    if age_hours <= 12:
        return 20.0
    if age_hours <= 24:
        return 14.0
    if age_hours <= 48:
        return 8.0
    return 4.0


def _engagement_score(upvotes: int, comment_count: int) -> float:
    raw = min(8.0, math.log10(max(upvotes, 1)) * 4.0)
    raw += min(10.0, comment_count * 1.25)
    return raw


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _contains_keyword(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False

    tokens = keyword.split()
    if not tokens:
        return False

    if len(tokens) == 1:
        pattern = rf"\b{re.escape(keyword)}\b"
        return bool(re.search(pattern, text))

    prefix = r"\s+".join(re.escape(token) for token in tokens[:-1])
    last_token = re.escape(tokens[-1])
    pattern = rf"\b{prefix}\s+{last_token}s?\b"
    return bool(re.search(pattern, text))


def _buying_signal_score(post: RedditPost) -> float:
    normalized_title = _normalize_text(post.title)
    normalized_text = _normalize_text(post.text)

    for pattern in BUYING_SIGNAL_PATTERNS:
        if pattern in normalized_title:
            return 8.0
        if pattern in normalized_text:
            return 4.0

    return 0.0


def _is_promotional(text: str) -> bool:
    return any(pattern in text for pattern in PROMOTIONAL_PATTERNS)
