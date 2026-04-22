from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orchestrator
from config import load_settings


class OrchestratorTests(unittest.TestCase):
    def test_disabled_publish_command_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_settings(Path(temp_dir))
            logger = logging.getLogger(f"orchestrator-test-{self.id()}")

            with mock.patch.object(orchestrator, "load_settings", return_value=settings), mock.patch.object(
                orchestrator, "setup_logger", return_value=logger
            ), mock.patch.object(
                logger, "warning"
            ) as warning_mock:
                result = orchestrator.main(["publish"])

        self.assertEqual(result, 0)
        warning_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
