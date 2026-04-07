from __future__ import annotations

import re
from typing import Any

from config import Settings
from models import CommentDraft, DiscoveredPost, StandaloneDraft


THREAD_MARKER = "\U0001F9F5"
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
    "feedback",
    "survey",
    "voice of customer",
    "customer satisfaction",
    "delighted",
    "surveymonkey",
    "typeform",
)


def _sentence_count(text: str) -> int:
    parts = [part.strip() for part in re.split(r"[.!?]+", text) if part.strip()]
    return max(1, len(parts))


def _mentions_elvan(text: str) -> bool:
    return "elvan" in text.lower()


def _has_hashtag(text: str) -> bool:
    return re.search(r"(^|\s)#\w+", text) is not None


def _count_hashtags(text: str) -> int:
    return len(re.findall(r"(^|\s)#\w+", text))


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

    def generate_standalone_post(
        self,
        topic_category: str,
        *,
        allow_elvan_reference: bool,
        dry_run: bool = False,
    ) -> StandaloneDraft:
        feedback: list[str] = []
        last_draft = StandaloneDraft(
            text="",
            topic_category=topic_category,
            char_count=0,
            is_thread=False,
            mentions_elvan=False,
            validation_errors=["Standalone post generation did not run."],
        )

        for _ in range(3):
            text = self._generate_standalone_text(
                topic_category,
                allow_elvan_reference=allow_elvan_reference,
                feedback=feedback,
                dry_run=dry_run,
            )
            last_draft = self.validate_standalone_post(
                text,
                topic_category=topic_category,
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

    def validate_standalone_post(
        self,
        text: str,
        *,
        topic_category: str,
        allow_elvan_reference: bool,
    ) -> StandaloneDraft:
        errors: list[str] = []
        cleaned = text.strip().strip('"')
        mentions_elvan = _mentions_elvan(cleaned)
        first_line = cleaned.splitlines()[0].strip() if cleaned else ""

        if not cleaned:
            errors.append("Standalone post is empty.")
        if len(cleaned) < 120:
            errors.append("Standalone post should be at least 120 characters.")
        if len(cleaned) > 280:
            errors.append("Standalone post exceeds 280 characters.")
        if _count_hashtags(cleaned) > 2:
            errors.append("Standalone post cannot contain more than 2 hashtags.")
        if _has_url(cleaned):
            errors.append("Standalone post cannot contain links.")
        if first_line.lower().startswith("i "):
            errors.append("Standalone post hook cannot start with 'I'.")
        if mentions_elvan and not allow_elvan_reference:
            errors.append("Elvan mention is not allowed for this generation.")
        if _contains_off_brand_term(cleaned):
            errors.append("Standalone post includes an off-brand topic.")
        if _contains_negative_competitor_reference(cleaned):
            errors.append("Standalone post mentions a competitor negatively.")

        return StandaloneDraft(
            text=cleaned,
            topic_category=topic_category,
            char_count=len(cleaned),
            is_thread=THREAD_MARKER in cleaned or cleaned.lower().startswith("thread:"),
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

        prompt = (
            "You are drafting X replies for a technical co-founder building Elvan. "
            "Be specific, peer-like, and useful. Keep replies to 1-3 sentences, "
            "under 280 characters, no hashtags, no links, and no generic praise.\n\n"
            f"Author handle: @{post.author_handle.lstrip('@')}\n"
            f"Keyword context: {post.keyword}\n"
            f"Post text:\n{post.text}\n\n"
            f"Elvan mention allowed: {'yes' if allow_elvan_reference else 'no'}\n"
            f"Previous validation errors to avoid: {', '.join(feedback) if feedback else 'none'}\n\n"
            "Reply with only the comment text, nothing else."
        )
        return self._call_model(prompt)

    def _generate_standalone_text(
        self,
        topic_category: str,
        *,
        allow_elvan_reference: bool,
        feedback: list[str],
        dry_run: bool,
    ) -> str:
        if self.client is None:
            if dry_run:
                return self._mock_standalone(topic_category, allow_elvan_reference)
            raise RuntimeError(
                "Gemini API credentials are missing. Set GEMINI_API_KEY or use --dry-run."
            )

        prompt = (
            "You are drafting standalone X posts for a technical co-founder building Elvan. "
            "Open with a strong hook, avoid starting with 'I', and use at most 2 relevant "
            "hashtags. Your post MUST be between 150 and 250 characters. Never generate a "
            "post shorter than 120 characters.\n\n"
            f"Topic category: {topic_category}\n"
            f"Elvan mention allowed: {'yes' if allow_elvan_reference else 'no'}\n"
            f"Previous validation errors to avoid: {', '.join(feedback) if feedback else 'none'}\n\n"
            "Reply with only the post text, nothing else."
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
            self.logger.error("Gemini API call failed: %s", exc)
            raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    def _mock_comment(self, post: DiscoveredPost, allow_elvan_reference: bool) -> str:
        base = (
            "The useful signal here is usually in who answers, not just how many answer."
        )
        follow_up = "Curious what changed once you adjusted timing or segmentation?"
        if allow_elvan_reference:
            return (
                "We ran into the same pattern while building feedback loops. "
                f"{base} {follow_up}"
            )[:280]
        return f"{base} {follow_up}"[:280]

    def _mock_standalone(
        self,
        topic_category: str,
        allow_elvan_reference: bool,
    ) -> str:
        templates = {
            "NPS insight / data point": (
                "Hot take: response rate without response quality is a vanity metric. "
                "The real insight shows up when timing, audience, and follow-up are tuned together. #CX"
            ),
            "Build-in-public update": (
                "Shipping product is easy compared to closing the loop on feedback. "
                "The hardest part has been turning survey answers into operational changes the team actually trusts. #buildinpublic"
            ),
            "CX / customer retention take": (
                "Retention work breaks when every team reads customer feedback in a different way. "
                "The biggest unlock is a tighter path from sentiment to action, not another dashboard. #SaaS"
            ),
            "SaaS founder lesson": (
                "Most early SaaS mistakes are not about acquiring more users. "
                "They come from learning too slowly from the users you already have, then scaling the wrong assumptions. #SaaS"
            ),
            "Contrarian opinion on feedback/surveys": (
                "Contrarian take: sending more surveys usually makes your feedback system worse. "
                "The better move is sending fewer, better-timed prompts and making every answer operationally useful. #CX"
            ),
        }
        text = templates.get(
            topic_category,
            "The fastest way to lose product signal is to collect more feedback than your team can act on. "
            "Consistency in timing and follow-through matters more than survey volume. #SaaS",
        )
        if allow_elvan_reference:
            text = text.rstrip() + " We keep seeing this while building Elvan."
        return text[:280]


# Alias for backwards compatibility with orchestrator.py imports
AnthropicContentGenerator = GeminiContentGenerator
