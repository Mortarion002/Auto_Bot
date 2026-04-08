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

        elvan_guidance = (
            "You may mention Elvan naturally once if it is genuinely relevant — "
            "for example: 'we ran into this exact problem building Elvan' or "
            "'this is one of the core things we are solving with Elvan'. "
            "Do not plug Elvan unless it adds real context to the reply. "
            "Do not start the reply with Elvan."
            if allow_elvan_reference
            else
            "Do not mention Elvan or any product you are building."
        )

        prompt = (
            "You are Aman, a B.Tech student interning at Elvan — an early-stage B2B SaaS "
            "that helps teams collect and act on NPS, CSAT, and customer feedback. "
            "You are active on X as a builder engaging with practitioners and founders in the "
            "customer experience, SaaS, and feedback tooling space.\n\n"
            "Write a reply to the post below. The reply must:\n"
            "- Be 1 to 3 sentences, under 280 characters total\n"
            "- Directly engage with the specific situation or question in the post — "
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
            f"Previous attempts failed validation for: "
            f"{', '.join(feedback) if feedback else 'none — this is the first attempt'}\n\n"
            "Reply with only the reply text. No quotes around it. Nothing else."
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

        topic_context = {
            "NPS insight / data point": (
                "Share a specific, opinionated observation about NPS — response rates, "
                "timing, score interpretation, or what teams get wrong. Make it quotable."
            ),
            "Elvan build-in-public update": (
                "Share something real from building Elvan — a problem encountered, "
                "a decision made, something that surprised you, or a lesson from talking "
                "to customers. Be specific, not vague. Avoid 'we are building X' as the "
                "entire post — say something about what you learned or found."
            ),
            "Delighted migration take": (
                "Delighted is shutting down June 30 2026. Write a take aimed at SaaS teams "
                "currently evaluating replacements — what to look for, what most alternatives "
                "miss, or what the migration process actually involves. Topical and useful."
            ),
            "CX / customer retention take": (
                "Share an opinionated take on customer experience, retention, or the gap "
                "between collecting feedback and acting on it. Aimed at CS leaders and "
                "SaaS founders. Make it specific enough to spark a reply."
            ),
            "SaaS intern / builder perspective": (
                "Write from Aman's perspective — a B.Tech student interning at an early-stage "
                "SaaS. Something specific that changed how you think about product, customers, "
                "or building. Authentic and grounded, not generic startup wisdom."
            ),
            "Survey response rate observation": (
                "Write a specific take about survey response rates — why teams misread them, "
                "what actually drives them up or down, or what a low response rate is really "
                "telling you. Practitioners will relate to this."
            ),
            "Contrarian opinion on feedback/surveys": (
                "Write a contrarian or counterintuitive take on feedback collection, NPS, "
                "or surveys. Challenge a common assumption. Should be specific enough to "
                "be disagreeable — vague contrarianism is not interesting."
            ),
        }.get(
            topic_category,
            "Write a specific, opinionated observation about customer feedback, NPS, "
            "or SaaS product development. Make it useful to a practitioner or founder."
        )

        elvan_guidance = (
            "You may mention Elvan once, naturally, at the end — for example: "
            "'building this into Elvan' or 'something we kept running into while building Elvan'. "
            "Only include it if it genuinely fits. Do not force it."
            if allow_elvan_reference
            else
            "Do not mention Elvan or any product."
        )

        prompt = (
            "You are Aman, a B.Tech student interning at Elvan — an early-stage B2B SaaS "
            "that helps teams collect and act on NPS, CSAT, and customer feedback. "
            "You post on X as a builder in the customer experience and SaaS space.\n\n"
            "Write a standalone X post based on the topic below. The post must:\n"
            "- Be between 120 and 270 characters (strict — count carefully)\n"
            "- Open with a strong hook that is not a question and does not start with 'I'\n"
            "- Use at most 2 hashtags, placed at the end\n"
            "- Contain no links\n"
            "- Sound like a real person with an opinion, not a content calendar post\n\n"
            f"Topic: {topic_category}\n"
            f"What to write about: {topic_context}\n\n"
            f"Elvan mention: {elvan_guidance}\n\n"
            f"Previous attempts failed validation for: "
            f"{', '.join(feedback) if feedback else 'none — this is the first attempt'}\n\n"
            "Reply with only the post text. No quotes around it. Nothing else."
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
                "Churn interviews consistently surface things that survey data misses — "
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
            "Elvan build-in-public update": (
                "Building Elvan keeps teaching us the same lesson: collecting feedback is the easy part. "
                "Turning it into something a team can actually act on is where the real product work starts. #buildinpublic"
            ),
            "Delighted migration take": (
                "A Delighted replacement should do more than send a score survey. "
                "The real value is in helping a team understand who responded, why they responded, and what to change next. #CX"
            ),
            "CX / customer retention take": (
                "Retention work breaks when every team reads customer feedback in a different way. "
                "The biggest unlock is a tighter path from sentiment to action, not another dashboard. #SaaS"
            ),
            "SaaS intern / builder perspective": (
                "Building in a small SaaS team changes how you think about product feedback fast. "
                "The surprising part is not getting responses. It is learning how much signal gets lost before anyone acts on it. #SaaS"
            ),
            "Survey response rate observation": (
                "Most teams obsess over the score and ignore the response rate. "
                "But if the right users are not answering, the feedback system is already telling you something is broken. #CX"
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