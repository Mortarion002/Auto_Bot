from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import Settings
from models import SessionHealth


CHROME_EXECUTABLE_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROMEDRIVER_PATH = r"C:\Users\resoa\AppData\Local\Temp\chromedriver\chromedriver-win64\chromedriver.exe"


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
            ActionChains(self.page.driver) \
                .key_down(Keys.SHIFT) \
                .send_keys(Keys.ENTER) \
                .key_up(Keys.SHIFT) \
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
        self._cookie_path: Path = settings.base_dir / "x_cookies.json"

    def _save_cookies(self) -> None:
        try:
            cookies = self._driver.get_cookies()
            self._cookie_path.write_text(json.dumps(cookies), encoding="utf-8")
            self.logger.info("X session cookies saved (%d cookies).", len(cookies))
        except Exception as exc:
            self.logger.warning("Could not save cookies: %s", exc)

    def _load_cookies(self) -> bool:
        if not self._cookie_path.exists():
            return False
        try:
            cookies = json.loads(self._cookie_path.read_text(encoding="utf-8"))
            # Must be on x.com domain before injecting cookies
            self._driver.get("https://x.com")
            time.sleep(2)
            for cookie in cookies:
                cookie.pop("sameSite", None)
                try:
                    self._driver.add_cookie(cookie)
                except Exception:
                    pass
            self.logger.info("X session cookies loaded (%d cookies).", len(cookies))
            return True
        except Exception as exc:
            self.logger.warning("Could not load cookies: %s", exc)
            return False

    def open(self) -> _SyncPage:
        if self._page is not None:
            return self._page

        uc = _load_uc()
        self.logger.info("Launching Chrome with undetected-chromedriver (fresh session).")

        try:
            options = uc.ChromeOptions()
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-notifications")
            options.add_argument("--start-maximized")

            self._driver = uc.Chrome(
                options=options,
                browser_executable_path=CHROME_EXECUTABLE_PATH,
                driver_executable_path=CHROMEDRIVER_PATH,
                headless=False,
                use_subprocess=True,
            )
            self._page = _SyncPage(self._driver)
            self.logger.info("Chrome launched successfully.")
            return self._page

        except Exception as exc:
            raise RuntimeError(
                f"Failed to launch Chrome. Root cause: {exc}"
            ) from exc

    def _login_to_x(self, page: _SyncPage) -> None:
        """Log into X using credentials from settings."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        username = self.settings.x_username
        password = self.settings.x_password

        if not username or not password:
            raise RuntimeError(
                "X_USERNAME and X_PASSWORD must be set in .env for fresh login."
            )

        self.logger.info("Logging into X as %s.", username)
        page.goto("https://x.com/i/flow/login")
        time.sleep(3)

        wait = WebDriverWait(self._driver, 20)

        # Step 1 — enter username
        username_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[autocomplete='username']"))
        )
        username_input.click()
        time.sleep(0.5)
        for char in username:
            username_input.send_keys(char)
            time.sleep(0.05)
        time.sleep(1)

        # Click Next
        next_buttons = self._driver.find_elements(By.XPATH, "//span[text()='Next']")
        if next_buttons:
            next_buttons[0].click()
        time.sleep(2)

        # Step 2 — handle unusual activity check (asks for email/phone)
        unusual_input = self._driver.find_elements(
            By.CSS_SELECTOR, "input[data-testid='ocfEnterTextTextInput']"
        )
        if unusual_input:
            self.logger.info("Unusual activity check detected — entering username again.")
            unusual_input[0].click()
            for char in username:
                unusual_input[0].send_keys(char)
                time.sleep(0.05)
            time.sleep(1)
            next_btn = self._driver.find_elements(By.XPATH, "//span[text()='Next']")
            if next_btn:
                next_btn[0].click()
            time.sleep(2)

        # Step 3 — enter password
        password_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='password']"))
        )
        password_input.click()
        time.sleep(0.5)
        for char in password:
            password_input.send_keys(char)
            time.sleep(0.05)
        time.sleep(1)

        # Click Log in
        login_buttons = self._driver.find_elements(By.XPATH, "//span[text()='Log in']")
        if login_buttons:
            login_buttons[0].click()
        time.sleep(4)

        self.logger.info("Login flow completed.")

    def get_page(self) -> _SyncPage:
        return self.open()

    def check_health(self) -> SessionHealth:
        try:
            page = self.open()

            # Inject saved cookies before navigating so X sees an existing session
            cookies_loaded = self._load_cookies()

            if cookies_loaded:
                # Try home directly — cookies may restore the session
                page.goto("https://x.com/home")
                time.sleep(4)
                url = page.url
                # If cookies didn't work, fall through to fresh login below
                if "login" not in url and "/i/flow/login" not in url:
                    # May still be on landing page — check for home selectors below
                    pass
                else:
                    self.logger.info("Saved cookies did not restore session — performing fresh login.")
                    self._login_to_x(page)
                    time.sleep(3)
                    url = page.url
                    if "login" not in url and "/i/flow/login" not in url:
                        self._save_cookies()
                    if "login" in url or "/i/flow/login" in url:
                        return SessionHealth(ok=False, reason="Login failed — still on login page.")
            else:
                # No cookies — go straight to login page (X no longer reliably redirects)
                self._login_to_x(page)
                time.sleep(3)
                url = page.url
                if "login" not in url and "/i/flow/login" not in url:
                    self._save_cookies()
                if "login" in url or "/i/flow/login" in url:
                    return SessionHealth(ok=False, reason="Login failed — still on login page.")

        except Exception as exc:
            return SessionHealth(ok=False, reason=f"Browser navigation failed: {exc}")

        # Confirm logged-in UI elements are present — wait up to 15s for React to render
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        css_selectors = [
            "[data-testid='SideNav_NewTweet_Button']",
            "[data-testid='AppTabBar_Home_Link']",
            "[data-testid='primaryColumn']",
        ]
        try:
            wait = WebDriverWait(self._driver, 15)
            wait.until(
                EC.any_of(
                    *[EC.visibility_of_element_located((By.CSS_SELECTOR, sel)) for sel in css_selectors]
                )
            )
            return SessionHealth(ok=True, reason="Logged-in X session is healthy.")
        except Exception:
            pass

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