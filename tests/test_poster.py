from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from config import load_settings
from models import DiscoveredPost, PosterResult
from poster import XPoster


class FakeLocator:
    def __init__(self, visible: bool):
        self.visible = visible
        self.first = self

    def count(self) -> int:
        return 1 if self.visible else 0

    def is_visible(self) -> bool:
        return self.visible


class FakePage:
    def __init__(self, mapping: dict[str, FakeLocator]):
        self.mapping = mapping

    def locator(self, selector: str) -> FakeLocator:
        return self.mapping.get(selector, FakeLocator(False))


class PosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = load_settings(Path(self.temp_dir.name))
        self.settings.post_retry_count = 3
        self.logger = logging.getLogger(f"poster-test-{self.id()}")
        self.poster = XPoster(self.settings, self.logger)
        self.post = DiscoveredPost(
            post_id="post-1",
            post_url="https://x.com/test/status/post-1",
            author_handle="test",
            text="A post",
            likes=10,
            replies=1,
            reposts=0,
            created_at=datetime.now(timezone.utc),
            keyword="NPS",
            search_mode="live",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_find_first_locator_returns_first_visible_match(self) -> None:
        page = FakePage(
            {
                "one": FakeLocator(False),
                "two": FakeLocator(True),
            }
        )
        locator = self.poster._find_first_locator(page, ["one", "two"])
        self.assertIsNotNone(locator)
        self.assertTrue(locator.is_visible())

    def test_post_comment_retries_until_success(self) -> None:
        with mock.patch.object(
            self.poster,
            "_post_comment_once",
            side_effect=[
                PosterResult(False, False, "timeout"),
                PosterResult(True, True, "submitted"),
            ],
        ) as operation, mock.patch.object(self.poster, "_sleep") as sleeper:
            result = self.poster.post_comment(object(), self.post, "Hello", dry_run=False)
        self.assertTrue(result.success)
        self.assertEqual(operation.call_count, 2)
        sleeper.assert_called_once()

    def test_dry_run_comment_returns_without_submission(self) -> None:
        page = object()
        fake_locator = mock.Mock()
        with mock.patch.object(self.poster, "_goto"), mock.patch.object(
            self.poster, "_move_mouse_human_like"
        ), mock.patch.object(
            self.poster, "_find_first_locator", side_effect=[fake_locator, fake_locator]
        ), mock.patch.object(
            self.poster, "_click"
        ), mock.patch.object(
            self.poster, "_type_text"
        ) as type_text:
            result = self.poster._post_comment_once(
                page,
                self.post,
                "Hello world",
                dry_run=True,
            )
        self.assertTrue(result.success)
        self.assertFalse(result.submitted)
        type_text.assert_called_once()

    def test_failures_are_logged_during_retries(self) -> None:
        with mock.patch.object(
            self.poster,
            "_post_comment_once",
            side_effect=RuntimeError("boom"),
        ), mock.patch.object(self.poster.logger, "warning") as warning_mock, mock.patch.object(
            self.poster, "_sleep"
        ):
            result = self.poster.post_comment(object(), self.post, "Hi", dry_run=False)
        self.assertFalse(result.success)
        self.assertGreaterEqual(warning_mock.call_count, 1)
