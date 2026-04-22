from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from config import Settings

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be missing in tests
    requests = None  # type: ignore[assignment]

TELEGRAM_MAX_RETRIES = 4
TELEGRAM_RETRY_DELAY_SECONDS = 3
DNS_FALLBACK_SERVER = "1.1.1.1"
TELEGRAM_HOST = "api.telegram.org"
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class TelegramNotifier:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger

    def send_alert(self, message: str, disable_notification: bool = False) -> bool:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            self.logger.warning("Telegram credentials not configured; alert skipped.")
            return False

        url = (
            f"https://{TELEGRAM_HOST}/bot{self.settings.telegram_bot_token}/sendMessage"
        )
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": message,
            "disable_notification": disable_notification,
        }

        if requests is not None:
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
                    if self._looks_like_dns_failure(exc):
                        self.logger.info("Retrying Telegram send with DNS-resolve fallback.")
                        return self._send_with_curl_resolve(
                            message,
                            disable_notification=disable_notification,
                        )
                    if attempt < TELEGRAM_MAX_RETRIES:
                        self.logger.warning(
                            "Telegram send attempt %d/%d failed: %s — retrying in %ds...",
                            attempt,
                            TELEGRAM_MAX_RETRIES,
                            exc,
                            TELEGRAM_RETRY_DELAY_SECONDS,
                        )
                        time.sleep(TELEGRAM_RETRY_DELAY_SECONDS)

            self.logger.warning(
                "Telegram alert failed after %d attempts: %s",
                TELEGRAM_MAX_RETRIES,
                last_exc,
            )
            return False

        self.logger.warning("requests is not installed; trying curl-based Telegram fallback.")
        return self._send_with_curl_resolve(
            message,
            disable_notification=disable_notification,
        )

    def _send_with_curl_resolve(
        self,
        message: str,
        *,
        disable_notification: bool,
    ) -> bool:
        resolved_ip = self._resolve_telegram_ipv4()
        if resolved_ip is None:
            self.logger.warning("Telegram fallback failed: could not resolve Telegram API host.")
            return False

        curl_path = self._find_curl()
        if curl_path is None:
            self.logger.warning("Telegram fallback failed: curl.exe not found.")
            return False

        command = [
            curl_path,
            "--silent",
            "--show-error",
            "--fail",
            "--resolve",
            f"{TELEGRAM_HOST}:443:{resolved_ip}",
            "-X",
            "POST",
            f"https://{TELEGRAM_HOST}/bot{self.settings.telegram_bot_token}/sendMessage",
            "--data-urlencode",
            f"chat_id={self.settings.telegram_chat_id}",
            "--data-urlencode",
            f"text={message}",
            "--data-urlencode",
            f"disable_notification={'true' if disable_notification else 'false'}",
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.settings.request_timeout_seconds,
                check=True,
            )
        except Exception as exc:  # pragma: no cover - subprocess failure path
            self.logger.warning("Telegram curl fallback failed: %s", exc)
            return False

        if '"ok":true' not in (result.stdout or ""):
            self.logger.warning(
                "Telegram curl fallback returned an unexpected response: %s",
                (result.stdout or "").strip()[:200],
            )
            return False

        self.logger.info("Telegram alert sent successfully via curl fallback.")
        return True

    def _resolve_telegram_ipv4(self) -> str | None:
        try:
            result = subprocess.run(
                ["nslookup", TELEGRAM_HOST, DNS_FALLBACK_SERVER],
                capture_output=True,
                text=True,
                timeout=self.settings.request_timeout_seconds,
                check=True,
            )
        except Exception as exc:  # pragma: no cover - subprocess failure path
            self.logger.warning("Telegram DNS fallback lookup failed: %s", exc)
            return None

        for match in IPV4_PATTERN.findall(result.stdout or ""):
            if match != DNS_FALLBACK_SERVER:
                return match
        return None

    @staticmethod
    def _looks_like_dns_failure(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            marker in text
            for marker in (
                "failed to resolve",
                "name resolution",
                "getaddrinfo failed",
                "nodename nor servname provided",
                "connection aborted",
                "connectionreset",
            )
        )

    @staticmethod
    def _find_curl() -> str | None:
        for candidate in ("curl.exe", r"C:\Windows\System32\curl.exe"):
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
            except Exception:
                continue
            if result.stdout:
                return candidate
        return None
