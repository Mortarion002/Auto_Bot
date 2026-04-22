from __future__ import annotations

import time
from typing import Any

from config import Settings

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be missing in tests
    requests = None  # type: ignore[assignment]

TELEGRAM_MAX_RETRIES = 4
TELEGRAM_RETRY_DELAY_SECONDS = 3


class TelegramNotifier:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger

    def send_alert(self, message: str, disable_notification: bool = False) -> bool:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            self.logger.warning("Telegram credentials not configured; alert skipped.")
            return False
        if requests is None:
            self.logger.warning("requests is not installed; Telegram alert skipped.")
            return False

        url = (
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        )
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": message,
            "disable_notification": disable_notification,
        }

        last_exc: Exception | None = None
        for attempt in range(1, TELEGRAM_MAX_RETRIES + 1):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    timeout=self.settings.request_timeout_seconds,
                )
                response.raise_for_status()
                self.logger.info("Telegram alert sent successfully.")
                return True
            except Exception as exc:
                last_exc = exc
                if attempt < TELEGRAM_MAX_RETRIES:
                    self.logger.warning(
                        "Telegram send attempt %d/%d failed: %s — retrying in %ds...",
                        attempt,
                        TELEGRAM_MAX_RETRIES,
                        exc,
                        TELEGRAM_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(TELEGRAM_RETRY_DELAY_SECONDS)

        self.logger.warning("Telegram alert failed after %d attempts: %s", TELEGRAM_MAX_RETRIES, last_exc)
        return False
