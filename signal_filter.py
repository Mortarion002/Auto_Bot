from __future__ import annotations

import re

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

INTENT_BOOST_TERMS = [
    "alternative", "replace", "replacement", "looking for",
    "recommend", "switch", "switching", "what do you use",
    "anyone using", "anyone tried", "moved away", "moved from",
    "migrated", "shut down", "shutdown", "pricing", "expensive",
    "cost-effective", "hard to justify", "room to build",
]

COMPETITOR_BOOST_TERMS = [
    "delighted", "qualtrics", "survicate", "medallia", "uservoice",
    "getsatisfaction", "hotjar", "intercom",
]

CATEGORY_BOOST_TERMS = [
    "nps", "csat", "net promoter", "customer feedback", "feedback tool",
    "customer feedback tool", "survey tool", "customer satisfaction",
    "customer effort", "voice of customer", "in-app feedback",
]

# Acronyms that must be word-boundary matched to avoid false positives.
_ACRONYM_TERMS = frozenset({"nps", "csat", "ces", "voc"})


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


def compute_boost(title: str, body: str, base_score: float) -> tuple[float, str]:
    text = (title + " " + body).lower()
    boost = 0.0
    if any(_has_term(text, t) for t in INTENT_BOOST_TERMS):
        boost += 2
    if any(_has_term(text, t) for t in COMPETITOR_BOOST_TERMS):
        boost += 2
    if any(_has_term(text, t) for t in CATEGORY_BOOST_TERMS):
        boost += 1

    boosted = max(0.0, min(10.0, base_score + boost))
    tier = "hot" if boosted >= 8 else "medium" if boosted >= 5 else "low"
    return boosted, tier
