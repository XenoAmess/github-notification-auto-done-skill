"""Command-line interface."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .client import GitHubAPIError, GitHubClient
from .config import load_settings
from .logging_setup import setup_logging
from .models import Notification
from .processor import run, summarize

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI."""
    settings = load_settings(argv)
    setup_logging(
        verbose=settings.verbose,
        log_file=settings.log_file,
        json_logs=settings.json_logs,
    )

    since_iso = settings.since.strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("Starting GitHub notification cleanup")
    logger.debug(
        "Configuration: since=%s, workers=%d, dry_run=%s",
        since_iso,
        settings.max_workers,
        settings.dry_run,
    )

    try:
        with GitHubClient(settings) as client:
            logger.info("Fetching notifications updated since %s...", since_iso)
            raw_notifications = client.get_notifications(since=since_iso)
            logger.info("Fetched %d notification(s)", len(raw_notifications))

            notifications = [Notification.from_api(item) for item in raw_notifications]

            # Filter by updated_at locally as well to ensure exact since boundary.
            notifications = [
                n for n in notifications if _updated_at_or_min(n) >= settings.since
            ]
            logger.info(
                "%d notification(s) after local since filter", len(notifications)
            )

            results = run(client, settings, notifications)
    except GitHubAPIError as exc:
        logger.error("GitHub API error: %s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error")
        return 1

    summary = summarize(results)
    logger.info(
        "Done. archived=%d skipped=%d errors=%d total=%d",
        summary["archived"],
        summary["skipped"],
        summary["errors"],
        summary["total"],
    )
    return 0 if summary["errors"] == 0 else 1


def _updated_at_or_min(notification: Notification) -> datetime:
    if not notification.updated_at:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(notification.updated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
