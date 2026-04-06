from __future__ import annotations

from typing import Any

from config import Settings

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be missing in tests
    requests = None  # type: ignore[assignment]


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

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network failure path
            self.logger.warning("Telegram alert failed: %s", exc)
            return False

        self.logger.info("Telegram alert sent successfully.")
        return True
