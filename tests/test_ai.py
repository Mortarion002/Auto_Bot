from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ai import AnthropicContentGenerator
from config import load_settings
from models import DiscoveredPost


class AIGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = load_settings(Path(self.temp_dir.name))
        self.logger = logging.getLogger(f"ai-test-{self.id()}")
        self.generator = AnthropicContentGenerator(self.settings, self.logger)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_comment_validation_rejects_generic_hashtag_and_elvan_mention(self) -> None:
        draft = self.generator.validate_comment(
            "post-1",
            "Great post! We are building Elvan for this. #NPS",
            allow_elvan_reference=False,
        )
        self.assertIn("Comment uses a banned generic phrase.", draft.validation_errors)
        self.assertIn("Comments cannot contain hashtags.", draft.validation_errors)
        self.assertIn(
            "Elvan mention is not allowed for this comment context.",
            draft.validation_errors,
        )

    def test_dry_run_generation_returns_valid_comment_for_direct_feedback_post(self) -> None:
        post = DiscoveredPost(
            post_id="nps-1",
            post_url="https://x.com/test/status/nps-1",
            author_handle="founder",
            text="Our NPS response rate dropped after we changed send timing.",
            likes=20,
            replies=4,
            reposts=1,
            created_at=datetime.now(timezone.utc),
            keyword="NPS",
            search_mode="live",
            score=0.0,
        )
        draft = self.generator.generate_comment(post, dry_run=True)
        self.assertFalse(draft.validation_errors)
        self.assertLessEqual(draft.char_count, 280)
