from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Settings, load_settings
from hn_scraper import HNPost, HNScraper
from logger import setup_logger
from neon_store import NeonStore
from notifier import TelegramNotifier
from ph_scraper import PHPost, PHScraper
from signal_filter import compute_boost, passes_keyword_filter

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_: Any, **__: Any) -> bool:
        return False


MAX_HOT_IN_DIGEST = 5
MAX_MEDIUM_IN_DIGEST = 5
WORKFLOW_NAME = "signal-monitor-hn-ph"
SOURCE_SYSTEM = "signal_monitor"

_ANALYSIS_PROMPT = (
    "You are an analyst for Elvan.ai, a B2B SaaS NPS/CSAT/CES survey platform.\n\n"
    "Analyze this community post and return a JSON object ONLY. No explanation, no markdown.\n\n"
    "Post title: {title}\n"
    "Post body: {body}\n"
    "Source: {source}\n\n"
    "Return this exact JSON:\n"
    '{{\n'
    '  "pain_point": "one sentence describing the core problem",\n'
    '  "intent": "buying | venting | learning | comparing",\n'
    '  "urgency": "high | medium | low",\n'
    '  "tool_mentioned": "name of tool or competitor mentioned, or null",\n'
    '  "elvan_angle": "one sentence on how Elvan could address this",\n'
    '  "score": 5,\n'
    '  "draft_reply": "a helpful, non-promotional comment Elvan could post. Sound human, not salesy. Max 3 sentences."\n'
    '}}'
)


def _safe_json_parse(raw: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"```json\s*|```\s*", "", raw, flags=re.IGNORECASE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except (ValueError, TypeError):
        return None


def _analyze_post(settings: Settings, logger: Any, title: str, body: str, source: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "pain_point": None,
        "intent": "learning",
        "urgency": "low",
        "tool_mentioned": None,
        "elvan_angle": None,
        "base_score": 1.0,
        "draft_reply": None,
    }
    if not settings.gemini_api_key:
        return defaults

    try:
        from google import genai  # type: ignore[import]
    except ImportError:
        logger.warning("google-genai not installed — skipping AI analysis.")
        return defaults

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = _ANALYSIS_PROMPT.format(
            title=title,
            body=body[:600],
            source=source,
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config={"temperature": 0.4, "max_output_tokens": 350},
        )
        parsed = _safe_json_parse(response.text or "")
        if not parsed:
            logger.warning("AI analysis returned unparseable JSON for '%s'.", title[:60])
            return defaults

        return {
            "pain_point": str(parsed.get("pain_point") or "").strip() or None,
            "intent": str(parsed.get("intent") or "learning").strip().lower(),
            "urgency": str(parsed.get("urgency") or "low").strip().lower(),
            "tool_mentioned": str(parsed.get("tool_mentioned") or "").strip() or None,
            "elvan_angle": str(parsed.get("elvan_angle") or "").strip() or None,
            "base_score": float(parsed.get("score") or 1),
            "draft_reply": str(parsed.get("draft_reply") or "").strip() or None,
        }
    except Exception as exc:
        logger.warning("AI analysis failed for '%s': %s", title[:60], exc)
        return defaults


def _hn_to_signal(post: HNPost) -> dict[str, Any]:
    return {
        "dedupe_key": f"hn:{post.object_id}",
        "source": "HackerNews",
        "external_id": post.object_id,
        "title": post.title,
        "body": post.body,
        "url": post.url,
        "author": post.author,
        "upvotes": post.points,
        "comments_count": post.num_comments,
        "occurred_at": post.created_at.isoformat(),
        # AI fields filled later
        "pain_point": None,
        "intent": "learning",
        "urgency": "low",
        "tool_mentioned": None,
        "elvan_angle": None,
        "base_score": 1.0,
        "draft_reply": None,
        "boosted_score": 1.0,
        "tier": "low",
    }


def _ph_to_signal(post: PHPost) -> dict[str, Any]:
    return {
        "dedupe_key": f"ph:{post.ph_id}",
        "source": "ProductHunt",
        "external_id": post.ph_id,
        "title": post.title,
        "body": post.body,
        "url": post.url,
        "author": None,
        "upvotes": post.votes,
        "comments_count": post.comments_count,
        "occurred_at": post.created_at.isoformat(),
        "pain_point": None,
        "intent": "learning",
        "urgency": "low",
        "tool_mentioned": None,
        "elvan_angle": None,
        "base_score": 1.0,
        "draft_reply": None,
        "boosted_score": 1.0,
        "tier": "low",
    }


def _to_neon_row(signal: dict[str, Any]) -> dict[str, Any]:
    priority = signal["tier"]
    return {
        "dedupe_key": signal["dedupe_key"],
        "source": signal["source"].lower().replace(" ", ""),
        "source_system": SOURCE_SYSTEM,
        "workflow": WORKFLOW_NAME,
        "external_id": signal.get("external_id"),
        "title": signal["title"],
        "body": signal.get("body") or None,
        "url": signal.get("url") or None,
        "author": signal.get("author") or None,
        "subreddit": None,
        "matched_keyword": None,
        "intent": signal.get("intent"),
        "urgency": signal.get("urgency"),
        "priority": priority,
        "tool_mentioned": signal.get("tool_mentioned"),
        "pain_point": signal.get("pain_point"),
        "elvan_angle": signal.get("elvan_angle"),
        "draft_reply": signal.get("draft_reply"),
        "score": signal.get("boosted_score"),
        "base_score": signal.get("base_score"),
        "boosted_score": signal.get("boosted_score"),
        "likes": None,
        "replies": None,
        "reposts": None,
        "comments_count": signal.get("comments_count"),
        "upvotes": signal.get("upvotes"),
        "alerted": signal["tier"] == "hot",
        "hot_lead": signal["tier"] == "hot",
        "occurred_at": signal.get("occurred_at"),
        "metadata": {
            "kind": "signal_hn_ph",
            "source_detail": signal["source"],
        },
    }


def _build_digest(
    settings: Settings,
    *,
    hot: list[dict[str, Any]],
    medium: list[dict[str, Any]],
    total_scanned: int,
    hn_count: int,
    ph_count: int,
    keyword_matches: int,
    new_count: int,
) -> str:
    zone = settings.zoneinfo()
    now = datetime.now(zone)

    lines = [
        f"Elvan Signal Monitor — HN + Product Hunt — {now.strftime('%B %d, %Y')}",
        "",
        f"Hot Leads ({len(hot)} posts)",
    ]

    if hot:
        for item in hot[:MAX_HOT_IN_DIGEST]:
            lines.extend(_format_signal_lines(item))
    else:
        lines.append("  No hot leads today.")

    lines.extend(["", f"Worth Reading ({len(medium)} posts)"])

    if medium:
        for item in medium[:MAX_MEDIUM_IN_DIGEST]:
            lines.extend(_format_signal_lines(item))
    else:
        lines.append("  No medium-priority signals today.")

    lines.extend([
        "",
        f"Total scanned: {total_scanned} (HN: {hn_count} | PH: {ph_count})",
        f"Keyword matches: {keyword_matches} | New today: {new_count}",
    ])

    return "\n".join(lines)


def _format_signal_lines(item: dict[str, Any]) -> list[str]:
    source_tag = "HN" if item["source"] == "HackerNews" else "PH"
    lines = [
        f"",
        f"[{source_tag}] {item['title']}",
    ]
    if item.get("pain_point"):
        lines.append(f"  Pain: {item['pain_point']}")
    if item.get("intent") and item.get("urgency"):
        lines.append(f"  Intent: {item['intent']} | Urgency: {item['urgency']}")
    if item.get("tool_mentioned"):
        lines.append(f"  Tool mentioned: {item['tool_mentioned']}")
    if item.get("elvan_angle"):
        lines.append(f"  Elvan angle: {item['elvan_angle']}")
    if item.get("draft_reply"):
        lines.append(f"  Draft reply: {item['draft_reply']}")
    lines.append(f"  Link: {item['url']}")
    return lines


def run_monitor(
    settings: Settings,
    logger: Any,
    notifier: TelegramNotifier,
    *,
    dry_run: bool,
) -> int:
    started_at = datetime.now(settings.zoneinfo()).isoformat()
    neon_store = NeonStore(settings, logger)
    status = "success"
    stop_reason: str | None = None
    errors: list[str] = []
    hn_count = 0
    ph_count = 0

    try:
        # --- Scrape ---
        hn_posts: list[HNPost] = []
        try:
            hn_posts = HNScraper(settings, logger).fetch_all()
            hn_count = len(hn_posts)
            logger.info("HN: %d total posts fetched.", hn_count)
        except Exception as exc:
            errors.append(f"HN scrape failed: {exc}")
            logger.error("HN scrape failed: %s", exc)

        ph_posts: list[PHPost] = []
        try:
            ph_posts = PHScraper(settings, logger).fetch_all()
            ph_count = len(ph_posts)
            logger.info("PH: %d total posts fetched.", ph_count)
        except Exception as exc:
            errors.append(f"PH scrape failed: {exc}")
            logger.error("PH scrape failed: %s", exc)

        total_scanned = hn_count + ph_count

        # --- Build unified signal list ---
        all_signals = [_hn_to_signal(p) for p in hn_posts] + [_ph_to_signal(p) for p in ph_posts]

        # --- Keyword filter ---
        filtered = [
            s for s in all_signals
            if passes_keyword_filter(s["title"], s["body"] or "", s["url"] or "", s["source"])
        ]
        keyword_matches = len(filtered)
        logger.info("Keyword filter: %d/%d posts passed.", keyword_matches, total_scanned)

        # --- Dedup via Neon (skip AI for already-seen posts) ---
        existing_keys: set[str] = set()
        if neon_store.enabled:
            try:
                existing_keys = neon_store.get_existing_dedupe_keys(
                    [s["dedupe_key"] for s in filtered]
                )
                logger.info("Neon dedup: %d already seen, %d new.", len(existing_keys), keyword_matches - len(existing_keys))
            except Exception as exc:
                logger.warning("Neon dedup check failed — will analyze all: %s", exc)

        new_signals = [s for s in filtered if s["dedupe_key"] not in existing_keys]
        new_count = len(new_signals)

        # --- AI analysis (only for new signals) ---
        for signal in new_signals:
            analysis = _analyze_post(settings, logger, signal["title"], signal["body"] or "", signal["source"])
            signal.update(analysis)

        # --- Score boost ---
        for signal in new_signals:
            boosted, tier = compute_boost(signal["title"], signal["body"] or "", signal["base_score"])
            signal["boosted_score"] = boosted
            signal["tier"] = tier

        hot = [s for s in new_signals if s["tier"] == "hot"]
        medium = [s for s in new_signals if s["tier"] == "medium"]
        logger.info("Tiers — hot: %d, medium: %d, low: %d", len(hot), len(medium), new_count - len(hot) - len(medium))

        # --- Build digest ---
        message = _build_digest(
            settings,
            hot=hot,
            medium=medium,
            total_scanned=total_scanned,
            hn_count=hn_count,
            ph_count=ph_count,
            keyword_matches=keyword_matches,
            new_count=new_count,
        )
        logger.info("Signal digest:\n%s", message)

        if not dry_run:
            # Upsert new signals to Neon
            if neon_store.enabled and new_signals:
                try:
                    neon_rows = [_to_neon_row(s) for s in new_signals]
                    saved = neon_store.record_signal_rows(neon_rows)
                    logger.info("Neon: upserted %d signal rows.", saved)
                except Exception as exc:
                    errors.append(f"Neon upsert failed: {exc}")
                    logger.warning("Neon upsert failed: %s", exc)

            # Send Telegram digest
            sent = notifier.send_alert(message)
            if not sent:
                archived_path = notifier.persist_failed_message("signal-digest", message)
                error = "Failed to send signal digest Telegram message."
                errors.append(error)
                logger.error("%s Saved a copy to %s.", error, archived_path)
                status = "failed"
                stop_reason = error
                return 1

        return 0

    except Exception as exc:
        status = "failed"
        stop_reason = str(exc)
        errors.append(str(exc))
        logger.exception("Signal monitor run failed.")
        return 1

    finally:
        finished_at = datetime.now(settings.zoneinfo()).isoformat()
        if not dry_run and neon_store.enabled:
            try:
                neon_store.record_workflow_run(
                    source_system=SOURCE_SYSTEM,
                    workflow=WORKFLOW_NAME,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=status,
                    posts_scanned=hn_count + ph_count,
                    matches_found=keyword_matches if "keyword_matches" in dir() else None,
                    new_matches=new_count if "new_count" in dir() else None,
                    high_priority_count=len(hot) if "hot" in dir() else None,
                    digest_sent=(status == "success"),
                    stop_reason=stop_reason,
                    errors=" | ".join(errors) if errors else None,
                    metadata={"hn_count": hn_count, "ph_count": ph_count},
                )
            except Exception as exc:
                logger.warning("Neon workflow run log failed: %s", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elvan HN + Product Hunt signal monitor")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram sends and DB writes.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings(Path(__file__).resolve().parent)
    settings.dry_run = settings.dry_run or bool(args.dry_run)
    logger = setup_logger(settings)
    notifier = TelegramNotifier(settings, logger)

    return run_monitor(settings, logger, notifier, dry_run=settings.dry_run)


if __name__ == "__main__":
    sys.exit(main())
