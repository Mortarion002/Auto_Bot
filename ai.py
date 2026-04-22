from __future__ import annotations

import re
import time
from typing import Any

from config import Settings
from models import CommentDraft, DiscoveredPost


GENERIC_COMMENT_PHRASES = (
    "great post",
    "totally agree",
    "this is so true",
)
OFF_BRAND_TERMS = (
    "politics",
    "election",
    "religion",
    "partisan",
)
COMPETITOR_TERMS = ("delighted", "surveymonkey", "typeform")
NEGATIVE_TERMS = ("sucks", "garbage", "terrible", "awful", "hate")
DIRECT_NPS_TERMS = (
    "nps",
    "net promoter",
    "csat",
    "ces",
    "customer feedback tool",
    "feedback tool",
    "survey tool",
    "voice of customer",
    "delighted",
    "surveymonkey",
    "typeform",
    "feedback loop",
    "response rate",
    "survey fatigue",
)


def _sentence_count(text: str) -> int:
    parts = [part.strip() for part in re.split(r"[.!?]+", text) if part.strip()]
    return max(1, len(parts))


def _mentions_elvan(text: str) -> bool:
    return "elvan" in text.lower()


def _has_hashtag(text: str) -> bool:
    return re.search(r"(^|\s)#\w+", text) is not None


def _has_url(text: str) -> bool:
    lowered = text.lower()
    return "http://" in lowered or "https://" in lowered or "www." in lowered


def _contains_off_brand_term(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in OFF_BRAND_TERMS)


def _contains_negative_competitor_reference(text: str) -> bool:
    lowered = text.lower()
    return any(
        competitor in lowered and negative in lowered
        for competitor in COMPETITOR_TERMS
        for negative in NEGATIVE_TERMS
    )


class GeminiContentGenerator:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger
        self.client = self._build_client()

    def _build_client(self) -> Any | None:
        if not self.settings.gemini_api_key:
            return None
        try:
            from google import genai

            return genai.Client(api_key=self.settings.gemini_api_key)
        except ImportError:
            self.logger.warning("google-genai not installed; API generation unavailable.")
            return None
        except Exception as exc:
            self.logger.warning("Failed to build Gemini client: %s", exc)
            return None

    def generate_comment(
        self,
        post: DiscoveredPost,
        *,
        dry_run: bool = False,
    ) -> CommentDraft:
        allow_elvan_reference = self._comment_elvan_reference_allowed(post)
        feedback: list[str] = []
        last_draft = CommentDraft(
            post_id=post.post_id,
            text="",
            char_count=0,
            mentions_elvan=False,
            validation_errors=["Comment generation did not run."],
        )

        for _ in range(3):
            text = self._generate_comment_text(
                post,
                allow_elvan_reference=allow_elvan_reference,
                feedback=feedback,
                dry_run=dry_run,
            )
            last_draft = self.validate_comment(
                post.post_id,
                text,
                allow_elvan_reference=allow_elvan_reference,
            )
            if not last_draft.validation_errors:
                return last_draft
            feedback = last_draft.validation_errors

        return last_draft

    def validate_comment(
        self,
        post_id: str,
        text: str,
        *,
        allow_elvan_reference: bool,
    ) -> CommentDraft:
        errors: list[str] = []
        cleaned = text.strip().strip('"')
        mentions_elvan = _mentions_elvan(cleaned)
        lowered = cleaned.lower()

        if not cleaned:
            errors.append("Comment is empty.")
        if len(cleaned) > 280:
            errors.append("Comment exceeds 280 characters.")
        sentence_count = _sentence_count(cleaned) if cleaned else 0
        if sentence_count < 1 or sentence_count > 3:
            errors.append("Comment must be between 1 and 3 sentences.")
        if _has_hashtag(cleaned):
            errors.append("Comments cannot contain hashtags.")
        if _has_url(cleaned):
            errors.append("Comments cannot contain links.")
        if any(phrase in lowered for phrase in GENERIC_COMMENT_PHRASES):
            errors.append("Comment uses a banned generic phrase.")
        if lowered.startswith("as a developer building elvan"):
            errors.append("Comment cannot start with the banned Elvan phrase.")
        if mentions_elvan and not allow_elvan_reference:
            errors.append("Elvan mention is not allowed for this comment context.")
        if _contains_off_brand_term(cleaned):
            errors.append("Comment includes an off-brand topic.")
        if _contains_negative_competitor_reference(cleaned):
            errors.append("Comment mentions a competitor negatively.")

        return CommentDraft(
            post_id=post_id,
            text=cleaned,
            char_count=len(cleaned),
            mentions_elvan=mentions_elvan,
            validation_errors=errors,
        )

    def _comment_elvan_reference_allowed(self, post: DiscoveredPost) -> bool:
        context = f"{post.keyword} {post.text}".lower()
        return any(term in context for term in DIRECT_NPS_TERMS)

    def _generate_comment_text(
        self,
        post: DiscoveredPost,
        *,
        allow_elvan_reference: bool,
        feedback: list[str],
        dry_run: bool,
    ) -> str:
        if self.client is None:
            if dry_run:
                return self._mock_comment(post, allow_elvan_reference)
            raise RuntimeError(
                "Gemini API credentials are missing. Set GEMINI_API_KEY or use --dry-run."
            )

        elvan_guidance = (
            "You may mention Elvan naturally once if it is genuinely relevant - "
            "for example: 'we ran into this exact problem building Elvan' or "
            "'this is one of the core things we are solving with Elvan'. "
            "Do not plug Elvan unless it adds real context to the reply. "
            "Do not start the reply with Elvan."
            if allow_elvan_reference
            else "Do not mention Elvan or any product you are building."
        )

        prompt = (
            "You are Aman, a B.Tech student interning at Elvan - an early-stage B2B SaaS "
            "that helps teams collect and act on NPS, CSAT, and customer feedback. "
            "You are active on X as a builder engaging with practitioners and founders in the "
            "customer experience, SaaS, and feedback tooling space.\n\n"
            "Write a reply to the post below. The reply must:\n"
            "- Be 1 to 3 sentences, under 280 characters total\n"
            "- Directly engage with the specific situation or question in the post - "
            "not just the general topic\n"
            "- Sound like a peer talking to a peer, not a brand or a bot\n"
            "- Add a concrete observation, a follow-up question, or a brief experience "
            "from building in this space\n"
            "- Contain no hashtags, no links, no generic phrases like 'great post' "
            "or 'totally agree', no em dashes\n\n"
            f"Post author: @{post.author_handle.lstrip('@')}\n"
            f"Found via keyword: {post.keyword}\n"
            f"Post text:\n{post.text}\n\n"
            f"Elvan mention: {elvan_guidance}\n\n"
            "Previous attempts failed validation for: "
            f"{', '.join(feedback) if feedback else 'none - this is the first attempt'}\n\n"
            "Reply with only the reply text. No quotes around it. Nothing else."
        )
        return self._call_model(prompt)

    def _call_model(self, prompt: str) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config={
                    "temperature": 0.6,
                    "max_output_tokens": 220,
                },
            )
            return response.text.strip()
        except Exception as exc:
            error_str = str(exc)
            if "429" in error_str or "503" in error_str:
                self.logger.warning(
                    "Gemini rate limit or overload hit; waiting 65 seconds before retry."
                )
                time.sleep(65)
            self.logger.error("Gemini API call failed: %s", exc)
            raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    def _mock_comment(self, post: DiscoveredPost, allow_elvan_reference: bool) -> str:
        keyword_lower = post.keyword.lower()

        if "delighted" in keyword_lower:
            base = (
                "The migration window is tighter than most teams expect once you factor in "
                "historical data export and re-configuring send logic."
            )
            elvan = " We went through this while building Elvan's import flow."
        elif "response rate" in keyword_lower or "nps response" in keyword_lower:
            base = (
                "Response rate drop usually tracks to timing changes or audience segment drift, "
                "not survey design. Worth isolating which changed first."
            )
            elvan = " Saw the same pattern repeatedly while building Elvan."
        elif "survey fatigue" in keyword_lower or "survey" in keyword_lower:
            base = (
                "The teams with the best response rates send fewer surveys, not more. "
                "Frequency is almost always the first thing to cut."
            )
            elvan = " Something we kept running into while building Elvan."
        elif "churn" in keyword_lower or "retention" in keyword_lower:
            base = (
                "Churn interviews consistently surface things that survey data misses - "
                "usually it is the gap between what customers say and what they actually did."
            )
            elvan = " We kept seeing this pattern while building Elvan."
        else:
            base = (
                "The useful signal is usually in who responds, not just how many. "
                "Segment by lifecycle stage and the pattern usually becomes clearer."
            )
            elvan = " Ran into this a lot while building Elvan's feedback flows."

        if allow_elvan_reference:
            return (base + elvan)[:280]
        return base[:280]


# Alias for backwards compatibility with orchestrator.py imports
AnthropicContentGenerator = GeminiContentGenerator
