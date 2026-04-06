from __future__ import annotations

from typing import Any

from config import Settings
from models import SessionHealth


def _load_playwright() -> tuple[Any, type[Exception]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency may be missing in tests
        raise RuntimeError(
            "Playwright is required for browser automation. Install dependencies first."
        ) from exc
    return sync_playwright, Exception


class BrowserSession:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._attached_via_cdp = False

    def open(self) -> Any:
        if self._page is not None:
            return self._page

        sync_playwright, _ = _load_playwright()
        self._playwright = sync_playwright().start()

        if self.settings.chrome_remote_debug_url:
            self.logger.info(
                "Connecting to Chrome over CDP at %s.",
                self.settings.chrome_remote_debug_url,
            )
            self._attached_via_cdp = True
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(
                    self.settings.chrome_remote_debug_url
                )
            except Exception as exc:
                raise RuntimeError(
                    "Could not attach to Chrome on the configured debug port. "
                    "Start Chrome with --remote-debugging-port=9222 and leave it running."
                ) from exc
            if not self._browser.contexts:
                raise RuntimeError(
                    "Chrome debug session is available but no browser context was found."
                )
            self._context = self._browser.contexts[0]
        else:
            args = [f"--profile-directory={self.settings.chrome_profile_name}"]
            self.logger.info(
                "Launching persistent Chrome session with profile %s.",
                self.settings.chrome_profile_name,
            )
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.settings.chrome_user_data_dir),
                    channel=self.settings.chrome_channel,
                    headless=False,
                    args=args,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Failed to launch Chrome with the configured profile. "
                    "Close active Chrome windows or switch to CDP attach mode."
                ) from exc

        if hasattr(self._context, "set_default_timeout"):
            self._context.set_default_timeout(15000)
        pages = getattr(self._context, "pages", [])
        self._page = pages[0] if pages else self._context.new_page()
        return self._page

    def get_page(self) -> Any:
        return self.open()

    def check_health(self) -> SessionHealth:
        try:
            page = self.get_page()
            page.goto("https://x.com/home", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception as exc:
            return SessionHealth(ok=False, reason=f"Browser navigation failed: {exc}")

        url = getattr(page, "url", "")
        if "/login" in url or "/i/flow/login" in url:
            return SessionHealth(ok=False, reason="X session is logged out.")

        login_input = page.locator("input[name='text']")
        try:
            if login_input.count() > 0:
                return SessionHealth(ok=False, reason="X login screen detected.")
        except Exception:
            pass

        selectors = [
            "[data-testid='SideNav_NewTweet_Button']",
            "[data-testid='AppTabBar_Home_Link']",
            "[data-testid='primaryColumn']",
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() > 0 and locator.is_visible():
                    return SessionHealth(ok=True, reason="Logged-in X session is healthy.")
            except Exception:
                continue

        return SessionHealth(
            ok=False,
            reason="Could not confirm a logged-in X home session.",
        )

    def close(self) -> None:
        try:
            if self._context is not None and not self._attached_via_cdp:
                self._context.close()
            if self._browser is not None and not self._attached_via_cdp:
                self._browser.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
