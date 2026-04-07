from __future__ import annotations

import random
import time
from typing import Any, Iterable

from config import Settings
from models import DiscoveredPost, PosterResult


class XPoster:
    def __init__(self, settings: Settings, logger: Any):
        self.settings = settings
        self.logger = logger

    def post_comment(
        self,
        page: Any,
        post: DiscoveredPost,
        comment_text: str,
        *,
        dry_run: bool = False,
    ) -> PosterResult:
        return self._run_with_retries(
            lambda: self._post_comment_once(page, post, comment_text, dry_run=dry_run),
            action_name="comment",
            target_id=post.post_id,
        )

    def publish_post(
        self,
        page: Any,
        post_text: str,
        *,
        dry_run: bool = False,
    ) -> PosterResult:
        return self._run_with_retries(
            lambda: self._publish_post_once(page, post_text, dry_run=dry_run),
            action_name="standalone post",
            target_id=post_text[:40],
        )

    def _run_with_retries(
        self,
        operation: Any,
        *,
        action_name: str,
        target_id: str,
    ) -> PosterResult:
        last_error = "unknown failure"
        for attempt in range(1, self.settings.post_retry_count + 1):
            try:
                result = operation()
            except Exception as exc:
                last_error = str(exc)
                self.logger.warning(
                    "Attempt %s/%s failed for %s %s: %s",
                    attempt,
                    self.settings.post_retry_count,
                    action_name,
                    target_id,
                    exc,
                )
                result = PosterResult(success=False, submitted=False, reason=str(exc))

            if result.success:
                return result

            last_error = result.reason or last_error
            if attempt < self.settings.post_retry_count:
                self._sleep(2)

        return PosterResult(success=False, submitted=False, reason=last_error)

    def _post_comment_once(
        self,
        page: Any,
        post: DiscoveredPost,
        comment_text: str,
        *,
        dry_run: bool,
    ) -> PosterResult:
        self._goto(page, post.post_url)
        self._move_mouse_human_like(page)

        reply_button = self._find_first_locator(page, ["[data-testid='reply']"])
        if reply_button is None:
            return PosterResult(False, False, "Reply button not found.")
        self._click(reply_button)

        compose_box = self._find_first_locator(page, ["[data-testid='tweetTextarea_0']"])
        if compose_box is None:
            return PosterResult(False, False, "Reply composer not found.")
        self._type_text(page, compose_box, comment_text)

        if dry_run:
            return PosterResult(True, False, "dry-run")

        self._pause_before_submit(
            self.settings.reply_pause_min_seconds,
            self.settings.reply_pause_max_seconds,
        )
        submit_button = self._find_first_locator(
            page,
            ["[data-testid='tweetButtonInline']", "[data-testid='tweetButton']"],
        )
        if submit_button is None:
            return PosterResult(False, False, "Reply submit button not found.")
        self._click(submit_button)

        if self._confirm_comment_posted(page, comment_text):
            return PosterResult(True, True, "submitted")
        return PosterResult(False, False, "Reply submission could not be confirmed.")

    def _publish_post_once(
        self,
        page: Any,
        post_text: str,
        *,
        dry_run: bool,
    ) -> PosterResult:
        self._goto(page, "https://x.com/home")
        self._move_mouse_human_like(page)

        compose_box = self._find_first_locator(page, ["[data-testid='tweetTextarea_0']"])
        if compose_box is None:
            compose_button = self._find_first_locator(
                page,
                ["[data-testid='SideNav_NewTweet_Button']"],
            )
            if compose_button is None:
                return PosterResult(False, False, "Compose entry point not found.")
            self._click(compose_button)
            compose_box = self._find_first_locator(
                page,
                ["[data-testid='tweetTextarea_0']"],
            )
        if compose_box is None:
            return PosterResult(False, False, "Post composer not found.")

        self._type_text(page, compose_box, post_text)

        if dry_run:
            return PosterResult(True, False, "dry-run")

        self._pause_before_submit(
            self.settings.post_pause_min_seconds,
            self.settings.post_pause_max_seconds,
        )
        submit_button = self._find_first_locator(
            page,
            ["[data-testid='tweetButtonInline']", "[data-testid='tweetButton']"],
        )
        if submit_button is None:
            return PosterResult(False, False, "Post submit button not found.")
        self._click(submit_button)

        if self._confirm_standalone_posted(page, post_text):
            return PosterResult(True, True, "submitted")
        return PosterResult(False, False, "Standalone post submission could not be confirmed.")

    def _goto(self, page: Any, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

    def _find_first_locator(self, page: Any, selectors: Iterable[str]) -> Any | None:
        for selector in selectors:
            locator = page.locator(selector).first
            if self._locator_exists(locator):
                return locator
        return None

    def _locator_exists(self, locator: Any) -> bool:
        try:
            if locator.count() == 0:
                return False
            return locator.is_visible()
        except Exception:
            return False

    def _click(self, locator: Any) -> None:
        locator.scroll_into_view_if_needed()
        locator.click()

    def _type_text(self, page: Any, locator: Any, text: str) -> None:
        locator.click()
        keyboard = getattr(page, "keyboard", None)
        if keyboard is None:
            locator.fill(text)
            return
        for char in text:
            if char == "\n":
                keyboard.press("Shift+Enter")
                continue
            keyboard.type(
                char,
                delay=random.randint(
                    self.settings.typing_delay_min_ms,
                    self.settings.typing_delay_max_ms,
                ),
            )

    def _move_mouse_human_like(self, page: Any) -> None:
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return
        safe_positions = [(200, 300), (400, 200), (300, 400)]
        for x, y in safe_positions:
            try:
                mouse.move(x, y)
            except Exception:
                pass

    def _pause_before_submit(self, min_seconds: int, max_seconds: int) -> None:
        self._sleep(random.randint(min_seconds, max_seconds))

    def _confirm_comment_posted(self, page: Any, comment_text: str) -> bool:
        page.wait_for_timeout(3000)
        compose_box = self._find_first_locator(page, ["[data-testid='tweetTextarea_0']"])
        if compose_box is None:
            return True
        try:
            remaining_text = compose_box.inner_text().strip()
            if not remaining_text:
                return True
        except Exception:
            pass
        excerpt = comment_text[:30]
        try:
            return page.locator(f"text={excerpt}").count() > 0
        except Exception:
            return False

    def _confirm_standalone_posted(self, page: Any, post_text: str) -> bool:
        page.wait_for_timeout(3000)
        compose_box = self._find_first_locator(page, ["[data-testid='tweetTextarea_0']"])
        if compose_box is None:
            return True
        try:
            remaining_text = compose_box.inner_text().strip()
            if not remaining_text:
                return True
        except Exception:
            pass
        excerpt = post_text[:30]
        try:
            return page.locator(f"text={excerpt}").count() > 0
        except Exception:
            return False

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)
