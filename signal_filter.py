from __future__ import annotations

import math
import re

# ---------------------------------------------------------------------------
# Keyword lists used for the pass/fail filter
# ---------------------------------------------------------------------------

PRODUCT_TERMS = [
    "nps", "csat", "ces", "net promoter", "customer satisfaction",
    "customer effort", "survey tool", "feedback tool", "customer feedback tool",
    "in-app feedback", "user feedback tool", "voice of customer", "voc",
    "churn survey", "customer feedback", "user feedback", "collect feedback",
    "gather feedback", "feedback from customers", "feedback from users",
]

COMPETITOR_TERMS = [
    "qualtrics", "delighted", "survicate", "medallia", "uservoice",
    "getsatisfaction", "hotjar", "intercom survey",
]

BROAD_FORM_TERMS = ["typeform", "form builder", "forms"]

PAIN_TERMS = [
    "alternative", "replace", "replacement", "switch", "switching",
    "migrate", "migration", "pricing", "expensive", "cost", "too complex",
    "hard to justify", "recommend", "what do you use", "looking for",
    "anyone found", "room to build", "frustration", "shut down", "shutdown",
    "monetize", "monetization",
]

# Acronyms that need word-boundary matching to avoid false positives.
_ACRONYM_TERMS = frozenset({"nps", "csat", "ces", "voc"})

# ---------------------------------------------------------------------------
# Keyword groups used for scoring (ordered by intent strength)
# ---------------------------------------------------------------------------

_DIRECT_TERMS = frozenset({
    "nps", "csat", "ces", "net promoter", "survey tool", "feedback tool",
    "customer feedback tool", "in-app feedback", "user feedback tool",
    "churn survey", "customer satisfaction", "customer effort",
})

_COMPETITOR_SCORE_TERMS = frozenset({
    "qualtrics", "delighted", "survicate", "medallia", "uservoice",
    "getsatisfaction", "hotjar", "intercom survey",
})

_PAIN_SCORE_TERMS = frozenset({
    "voice of customer", "voc", "customer feedback", "user feedback",
    "collect feedback", "gather feedback", "feedback from customers",
    "feedback from users",
})

_BUYING_SIGNAL_TERMS = frozenset({
    "alternative", "replace", "replacement", "looking for", "recommend",
    "switch", "switching", "what do you use", "anyone using", "anyone tried",
    "moved away", "migrated", "shut down", "shutdown", "pricing", "expensive",
    "hard to justify",
})

_INTENT_BASE: dict[str, float] = {
    "direct": 28.0,
    "competitor": 26.0,
    "pain": 16.0,
    "discovery": 10.0,
}

_LOCATION_SCORE: dict[str, float] = {
    "title": 24.0,
    "body": 16.0,
}

_SOURCE_BONUS: dict[str, float] = {
    "HackerNews": 5.0,
    "ProductHunt": 3.0,
}

HOT_THRESHOLD = 70.0
MEDIUM_THRESHOLD = 40.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _has_term(text: str, term: str) -> bool:
    if term in _ACRONYM_TERMS:
        return bool(re.search(
            r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])",
            text,
            re.IGNORECASE,
        ))
    return term.lower() in text.lower()


def _is_self_signal(title: str, url: str, body: str, source: str) -> bool:
    t = title.strip().lower()
    u = url.lower()
    if t in ("elvan", "elvan.ai") or t.startswith("elvan -"):
        return True
    if "producthunt.com/products/elvan" in u:
        return True
    if "elvan.ai" in u or "blog.elvan.ai" in u:
        return True
    if source == "ProductHunt" and "elvan" in t and "nps" in body.lower():
        return True
    return False


def _best_keyword_match(title: str, body: str) -> tuple[str, str]:
    """Return (intent, location) for the highest-priority keyword found."""
    for intent, terms in [
        ("direct", _DIRECT_TERMS),
        ("competitor", _COMPETITOR_SCORE_TERMS),
        ("pain", _PAIN_SCORE_TERMS),
    ]:
        for term in terms:
            if _has_term(title, term):
                return intent, "title"
        for term in terms:
            if _has_term(body, term):
                return intent, "body"
    return "discovery", "body"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def passes_keyword_filter(title: str, body: str, url: str, source: str) -> bool:
    if _is_self_signal(title, url, body, source):
        return False

    text = (title + " " + body).lower()
    has_product = any(_has_term(text, t) for t in PRODUCT_TERMS)
    has_competitor = any(_has_term(text, t) for t in COMPETITOR_TERMS)
    has_broad_form = any(_has_term(text, t) for t in BROAD_FORM_TERMS)
    has_pain = any(_has_term(text, t) for t in PAIN_TERMS)

    if has_product or has_competitor:
        return True
    if has_broad_form and has_pain and has_product:
        return True
    return False


def score_signal(
    title: str,
    body: str,
    *,
    upvotes: int,
    comments_count: int,
    source: str,
) -> tuple[float, str]:
    """Score a signal post and return (score, tier).

    Tier is 'hot', 'medium', or 'low' — same categories as the Reddit scorer.
    No AI required; scoring is purely rule-based.
    """
    intent, location = _best_keyword_match(title, body)

    score = _INTENT_BASE[intent] + _LOCATION_SCORE[location]

    # Buying-signal bonus
    full_text = (title + " " + body).lower()
    buying_in_title = any(_has_term(title.lower(), t) for t in _BUYING_SIGNAL_TERMS)
    buying_in_body = any(_has_term(full_text, t) for t in _BUYING_SIGNAL_TERMS)
    if buying_in_title:
        score += 8.0
    elif buying_in_body:
        score += 4.0

    # Engagement (same formula as reddit_scorer)
    score += min(8.0, math.log10(max(upvotes, 1)) * 4.0)
    score += min(10.0, comments_count * 1.0)

    # Source bonus
    score += _SOURCE_BONUS.get(source, 0.0)

    score = round(score, 2)
    tier = "hot" if score >= HOT_THRESHOLD else "medium" if score >= MEDIUM_THRESHOLD else "low"
    return score, tier
