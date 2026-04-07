# Mouse Movement Fix Report

**Date:** April 7, 2026

## Issue

Posting could fail with:

`move target out of bounds`

The failure came from `_move_mouse_human_like()` in `poster.py`. The old implementation generated random mouse coordinates from the viewport size and then moved the cursor in steps. In practice, this could still produce positions that were invalid for the active browser window.

## What Changed

I updated `_move_mouse_human_like()` in `poster.py` to stop using random viewport-based coordinates.

The new behavior:

- Uses a small list of fixed safe positions: `(200, 300)`, `(400, 200)`, and `(300, 400)`
- Returns early if `page.mouse` is unavailable
- Wraps each `mouse.move()` call in `try/except` so a single move failure does not abort the posting flow

## Why This Fix Works

The previous logic depended on viewport-derived randomness, which made the movement less predictable and could still lead to invalid cursor targets. The replacement uses known safe coordinates and removes stepped random movement, which reduces the risk of moving outside the usable browser area.

## Test Coverage Added

I added a regression test in `tests/test_poster.py`:

- `test_move_mouse_human_like_uses_safe_positions`

This test verifies that `_move_mouse_human_like()` sends the exact expected sequence of safe coordinates.

## Verification

I verified the change with:

```powershell
python -m unittest tests.test_poster
```

Result:

- 5 tests ran
- All tests passed

## Files Updated

- `poster.py`
- `tests/test_poster.py`
- `MOUSE_MOVE_FIX_REPORT.md`
