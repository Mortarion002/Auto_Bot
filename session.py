from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from config import Settings
from models import SessionHealth


CHROME_USER_DATA_DIR = r"C:\Users\resoa\AppData\Local\Google\Chrome\User Data"
CHROME_EXECUTABLE_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_PROFILE_DIRECTORY = "Profile 4"


def _load_uc() -> Any:
    try:
        import undetected_chromedriver as uc
        return uc
    except ImportError as exc:
        raise RuntimeError(
            "undetected-chromedriver is required. Run: pip install undetected-chromedriver"
        ) from exc


class _SyncMouse:
    def __init__(self, driver: Any):
        self.driver = driver

    def wheel(self, _x: int, y: int) -> None:
        self.driver.execute_script(f"window.scrollBy(0, {int(y)})")

    def move(self, x: int, y: int, steps: int = 10) -> None:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self.driver).move_by_offset(x, y).perform()


class _SyncKeyboard:
    def __init__(self, page: "_SyncPage"):
        self.page = page

    def type(self, text: str, delay: int = 0) -> None:
        locator = self.page._active_locator
        if locator is None:
            raise RuntimeError("No active element focused for typing.")
        element = locator._element
        if element is None:
            raise RuntimeError("No active element focused for typing.")
        for char in text:
            element.send_keys(char)
            if delay:
                time.sleep(delay / 1000)

    def press(self, key: str) -> None:
        from selenium.webdriver.common.keys import Keys
        locator = self.page._active_locator
        if locator is None:
            raise RuntimeError("No active element focused for key press.")
        element = locator._element
        if element is None:
            raise RuntimeError("No active element focused for key press.")
        if key == "Shift+Enter":
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(self.page.driver)\
                .key_down(Keys.SHIFT)\
                .send_keys(Keys.ENTER)\
                .key_up(Keys.SHIFT)\
                .perform()
            return
        element.send_keys(key)


class _SyncLocator:
    def __init__(self, page: "_SyncPage", selector: str, index: int | None = None):
        self.page = page
        self.selector = selector
        self.index = index
        self._element: Any = None

    @property
    def first(self) -> "_SyncLocator":
        return _SyncLocator(self.page, self.selector, index=0)

    def nth(self, index: int) -> "_SyncLocator":
        return _SyncLocator(self.page, self.selector, index=index)

    def locator(self, selector: str) -> "_SyncLocator":
        return _SyncLocator(self.page, selector)

    def count(self) -> int:
        return len(self._find_elements())

    def is_visible(self) -> bool:
        elements = self._find_elements()
        if not elements:
            return False
        try:
            return elements[0].is_displayed()
        except Exception:
            return False

    def inner_text(self) -> str:
        elements = self._find_elements()
        if not elements:
            return ""
        try:
            return (elements[0].text or "").strip()
        except Exception:
            return ""

    def get_attribute(self, attribute: str) -> str:
        elements = self._find_elements()
        if not elements:
            return ""
        try:
            return elements[0].get_attribute(attribute) or ""
        except Exception:
            return ""

    def scroll_into_view_if_needed(self) -> None:
        elements = self._find_elements()
        if not elements:
            return
        try:
            self.page.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", elements[0]
            )
        except Exception:
            pass

    def click(self) -> None:
        elements = self._find_elements()
        if not elements:
            raise RuntimeError(f"Element not found: {self.selector}")
        element = elements[0]
        self.page.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", element
        )
        try:
            element.click()
        except Exception:
            self.page.driver.execute_script("arguments[0].click();", element)
        self._element = element
        self.page._active_locator = self

    def fill(self, text: str) -> None:
        elements = self._find_elements()
        if not elements:
            raise RuntimeError(f"Element not found: {self.selector}")
        element = elements[0]
        element.clear()
        element.send_keys(text)
        self._element = element
        self.page._active_locator = self

    def send_keys(self, text: str) -> None:
        elements = self._find_elements()
        if not elements:
            raise RuntimeError(f"Element not found: {self.selector}")
        element = elements[0]
        element.send_keys(text)
        self._element = element
        self.page._active_locator = self

    def _find_elements(self) -> list[Any]:
        from selenium.webdriver.common.by import By
        try:
            if self.selector.startswith("text="):
                text = self.selector[5:]
                elements = self.page.driver.find_elements(
                    By.XPATH, f"//*[contains(text(), '{text}')]"
                )
            else:
                elements = self.page.driver.find_elements(By.CSS_SELECTOR, self.selector)

            if self.index is not None:
                if 0 <= self.index < len(elements):
                    return [elements[self.index]]
                return []
            return elements
        except Exception:
            return []


class _SyncPage:
    def __init__(self, driver: Any):
        self.driver = driver
        self._active_locator: _SyncLocator | None = None
        self.mouse = _SyncMouse(driver)
        self.keyboard = _SyncKeyboard(self)
        self.viewport_size = {"width": 1280, "height": 720}

    @property
    def url(self) -> str:
        try:
            return self.driver.current_url or ""
        except Exception:
            return ""

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.driver.get(url)
        time.sleep(2)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        time.sleep(timeout_ms / 1000)

    def locator(self, selector: str) -> _SyncLocator:
        return _SyncLocator(self, selector)


class BrowserSession:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger
        self._driver: Any = None
        self._page: _SyncPage | None = None

    def open(self) -> _SyncPage:
        if self._page is not None:
            return self._page

        uc = _load_uc()
        self.logger.info(
            "Launching Chrome with undetected-chromedriver using profile %s.",
            CHROME_PROFILE_DIRECTORY,
        )

        try:
            options = uc.ChromeOptions()
            options.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
            options.add_argument(f"--profile-directory={CHROME_PROFILE_DIRECTORY}")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-notifications")
            options.add_argument("--start-maximized")

            self._driver = uc.Chrome(
                options=options,
                browser_executable_path=CHROME_EXECUTABLE_PATH,
                driver_executable_path=r"C:\Users\resoa\AppData\Local\Temp\chromedriver\chromedriver-win64\chromedriver.exe",
                headless=False,
                use_subprocess=True,
            )
            self._page = _SyncPage(self._driver)
            self.logger.info("Chrome launched successfully.")
            return self._page

        except Exception as exc:
            raise RuntimeError(
                f"Failed to launch Chrome via undetected-chromedriver. Root cause: {exc}"
            ) from exc

    def get_page(self) -> _SyncPage:
        return self.open()

    def check_health(self) -> SessionHealth:
        try:
            page = self.get_page()
            page.goto("https://x.com/home", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception as exc:
            return SessionHealth(ok=False, reason=f"Browser navigation failed: {exc}")

        url = page.url
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
            if self._driver is not None:
                self._driver.quit()
                self.logger.info("Browser session closed.")
        except Exception as exc:
            self.logger.warning("Browser close warning (non-critical): %s", exc)
        finally:
            self._driver = None
            self._page = None
