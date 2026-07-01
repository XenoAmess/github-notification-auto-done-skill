"""Notification processing logic."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from .client import GitHubClient
from .config import Settings
from .models import Notification, PullRequest

logger = logging.getLogger(__name__)

DEPENDABOT_LOGIN = "dependabot[bot]"


@dataclass(frozen=True)
class ProcessResult:
    """Result of processing a single notification."""

    thread_id: str
    title: str
    repository: str
    status: str
    archived: bool = False
    skipped: bool = False
    error: bool = False


def _is_pull_request(notification: Notification) -> bool:
    return notification.type == "PullRequest"


def _should_exclude(notification: Notification, exclude_repos: Sequence[str]) -> bool:
    if not exclude_repos:
        return False
    return notification.repository_full_name in exclude_repos


def _is_updated_since(notification: Notification, since: datetime) -> bool:
    if not notification.updated_at:
        return True
    try:
        updated = datetime.fromisoformat(notification.updated_at.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return updated >= since
    except ValueError:
        return True


def _confirm_dependabot(client: GitHubClient, notification: Notification) -> bool:
    """Confirm the PR author is dependabot via the PR API."""
    if not notification.pr_url:
        return False
    pr_data = client.get_pull_request(notification.pr_url)
    if pr_data is None:
        return False
    pr = PullRequest.from_api(pr_data)
    return pr.author.lower() == DEPENDABOT_LOGIN.lower()


def _is_dependabot(
    client: GitHubClient,
    notification: Notification,
) -> bool:
    """Determine whether a notification belongs to a dependabot PR.

    Uses a fast heuristic first (title / latest comment URL) and falls back
    to fetching the PR details only when necessary.
    """
    if notification.looks_like_dependabot():
        return True
    return _confirm_dependabot(client, notification)


def _fetch_pr_status(
    client: GitHubClient,
    notification: Notification,
) -> Optional[PullRequest]:
    """Fetch and return the PR if it exists; otherwise None."""
    if not notification.pr_url:
        return None
    pr_data = client.get_pull_request(notification.pr_url)
    if pr_data is None:
        return None
    return PullRequest.from_api(pr_data)


def process_notification(
    client: GitHubClient,
    notification: Notification,
    settings: Settings,
) -> ProcessResult:
    """Process a single notification and return the outcome."""
    if not _is_pull_request(notification):
        logger.info("Skip non-pull-request: %s", notification.title)
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status="not_pull_request",
            skipped=True,
        )

    if _should_exclude(notification, settings.exclude_repos):
        logger.info(
            "Skip excluded repo %s: %s",
            notification.repository_full_name,
            notification.title,
        )
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status="excluded_repo",
            skipped=True,
        )

    if not _is_dependabot(client, notification):
        logger.info("Skip non-dependabot: %s", notification.title)
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status="not_dependabot",
            skipped=True,
        )

    pr = _fetch_pr_status(client, notification)
    if pr is None:
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status="fetch_pr_failed",
            error=True,
        )

    if not pr.is_done:
        logger.info("Skip unfinished PR [%s]: %s", pr.status, notification.title)
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status=f"skip_{pr.status}",
            skipped=True,
        )

    if settings.dry_run:
        logger.info(
            "[DRY-RUN] Would archive [%s]: %s",
            pr.status,
            notification.title,
        )
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status=pr.status,
            skipped=True,
        )

    archived = client.archive_notification(notification.thread_id)
    if archived:
        logger.info("Archived [%s]: %s", pr.status, notification.title)
        return ProcessResult(
            thread_id=notification.thread_id,
            title=notification.title,
            repository=notification.repository_full_name,
            status=pr.status,
            archived=True,
        )

    logger.error("Failed to archive: %s", notification.title)
    return ProcessResult(
        thread_id=notification.thread_id,
        title=notification.title,
        repository=notification.repository_full_name,
        status="archive_failed",
        error=True,
    )


def run(
    client: GitHubClient,
    settings: Settings,
    notifications: Iterable[Notification],
) -> List[ProcessResult]:
    """Process all notifications concurrently and return the results."""
    notification_list = list(notifications)
    if not notification_list:
        logger.info("No notifications to process.")
        return []

    results: List[ProcessResult] = []
    with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
        future_to_notif = {
            executor.submit(process_notification, client, notif, settings): notif
            for notif in notification_list
        }
        for future in as_completed(future_to_notif):
            try:
                result = future.result()
            except Exception:
                notif = future_to_notif[future]
                logger.exception("Unhandled error processing %s", notif.title)
                result = ProcessResult(
                    thread_id=notif.thread_id,
                    title=notif.title,
                    repository=notif.repository_full_name,
                    status="exception",
                    error=True,
                )
            results.append(result)

    return results


def summarize(results: Sequence[ProcessResult]) -> dict[str, int]:
    """Return a summary count of results."""
    return {
        "archived": sum(1 for r in results if r.archived),
        "skipped": sum(1 for r in results if r.skipped),
        "errors": sum(1 for r in results if r.error),
        "total": len(results),
    }
