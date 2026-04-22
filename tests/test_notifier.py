from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import load_settings
from notifier import TELEGRAM_MESSAGE_LIMIT, TelegramNotifier


class TelegramNotifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.settings = load_settings(self.base_dir)
        self.settings.telegram_bot_token = "token"
        self.settings.telegram_chat_id = "chat"
        self.logger = logging.getLogger(f"notifier-test-{self.id()}")
        self.notifier = TelegramNotifier(self.settings, self.logger)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_split_message_breaks_large_payload_on_line_boundaries(self) -> None:
        line = "A" * 200
        message = "\n".join([line] * 30)

        chunks = self.notifier._split_message(message)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks))

    def test_send_alert_sends_multiple_chunks_when_needed(self) -> None:
        line = "B" * 200
        message = "\n".join([line] * 30)

        with mock.patch.object(
            self.notifier,
            "_send_single_alert",
            return_value=True,
        ) as send_single:
            sent = self.notifier.send_alert(message)

        self.assertTrue(sent)
        self.assertGreater(send_single.call_count, 1)

    def test_persist_failed_message_writes_to_delivery_failures_directory(self) -> None:
        path = self.notifier.persist_failed_message("reddit-digest", "hello world")

        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), "hello world")
        self.assertEqual(path.parent, self.settings.delivery_failures_dir)


if __name__ == "__main__":
    unittest.main()
