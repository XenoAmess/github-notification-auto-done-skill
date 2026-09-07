"""Notification processing logic."""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence

from .client import GitHubClient
from .config import Settings
from .models import Notification, PullRequest

logger = logging.getLogger(__name__)

DEPENDABOT_LOGIN = "dependabot[bot]"

REBASE_COMMAND = "@dependabot rebase"
REBASE_COMMENT_PATTERN = re.compile(r"@dependabot\s+rebase\b", re.IGNORECASE)
PASSING_CHECK_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
MERGEABLE_STATE_RETRY_DELAY = 3.0  # seconds


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
    commented: bool = False


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


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_mergeable_state(
    client: GitHubClient,
    notification: Notification,
    pr: PullRequest,
) -> PullRequest:
    """Re-fetch the PR once when GitHub has not computed mergeable_state yet."""
    if pr.mergeable_state != "unknown":
        return pr
    logger.debug("mergeable_state is unknown; re-fetching PR: %s", notification.title)
    time.sleep(MERGEABLE_STATE_RETRY_DELAY)
    refreshed = _fetch_pr_status(client, notification)
    return refreshed if refreshed is not None else pr


def _all_checks_passed(client: GitHubClient, pr: PullRequest) -> bool:
    """Return True if every check run and legacy status on the head succeeded."""
    if not pr.repo_full_name or not pr.head_sha:
        return False
    for run in client.get_check_runs(pr.repo_full_name, pr.head_sha):
        if run.get("status") != "completed":
            return False
        if run.get("conclusion") not in PASSING_CHECK_CONCLUSIONS:
            return False
    status = client.get_combined_status(pr.repo_full_name, pr.head_sha)
    if status is None:
        return False
    total = int(status.get("total_count") or 0)
    return total == 0 or status.get("state") == "success"


def _latest_rebase_request(client: GitHubClient, pr: PullRequest) -> Optional[datetime]:
    """Return the creation time of the newest '@dependabot rebase' comment."""
    if not pr.comments_url:
        return None
    latest: Optional[datetime] = None
    for comment in client.get_issue_comments(pr.comments_url):
        if not REBASE_COMMENT_PATTERN.search(comment.get("body") or ""):
            continue
        created = _parse_timestamp(comment.get("created_at"))
        if created is not None and (latest is None or created > latest):
            latest = created
    return latest


def _result(notification: Notification, status: str, **flags: bool) -> ProcessResult:
    """Build a ProcessResult for a notification with the given status."""
    return ProcessResult(
        thread_id=notification.thread_id,
        title=notification.title,
        repository=notification.repository_full_name,
        status=status,
        **flags,
    )


def _handle_open_pr(
    client: GitHubClient,
    notification: Notification,
    pr: PullRequest,
    settings: Settings,
) -> ProcessResult:
    """Handle an open dependabot PR, optionally requesting a dependabot rebase.

    A rebase is requested only when all of the following hold:

    - the branch is out-of-date with the base branch (mergeable_state behind)
    - all checks on the head commit have passed
    - no '@dependabot rebase' comment was posted within the cooldown window
      (which means dependabot is not currently rebasing)
    """
    if not settings.auto_rebase:
        logger.info("Skip unfinished PR [%s]: %s", pr.status, notification.title)
        return _result(notification, f"skip_{pr.status}", skipped=True)

    pr = _ensure_mergeable_state(client, notification, pr)
    if not pr.is_behind_base:
        logger.info(
            "Skip open PR not behind base [%s]: %s",
            pr.mergeable_state or "unknown",
            notification.title,
        )
        return _result(notification, "skip_open_not_behind", skipped=True)

    if not _all_checks_passed(client, pr):
        logger.info("Skip open PR with pending/failing checks: %s", notification.title)
        return _result(notification, "skip_open_checks_not_passed", skipped=True)

    last_request = _latest_rebase_request(client, pr)
    if last_request is not None:
        age = datetime.now(timezone.utc) - last_request
        if age < timedelta(minutes=settings.rebase_cooldown_minutes):
            logger.info(
                "Skip open PR; rebase already requested %.1f min ago: %s",
                age.total_seconds() / 60,
                notification.title,
            )
            return _result(notification, "skip_open_rebase_pending", skipped=True)

    if settings.dry_run:
        logger.info(
            "[DRY-RUN] Would comment '%s': %s", REBASE_COMMAND, notification.title
        )
        return _result(notification, "rebase_requested", skipped=True)

    if client.create_comment(pr.comments_url, REBASE_COMMAND):
        logger.info(
            "Commented '%s' on behind-base PR: %s",
            REBASE_COMMAND,
            notification.title,
        )
        return _result(notification, "rebase_requested", commented=True)

    logger.error("Failed to comment rebase request: %s", notification.title)
    return _result(notification, "comment_failed", error=True)


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
        return _handle_open_pr(client, notification, pr, settings)

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
        "commented": sum(1 for r in results if r.commented),
        "total": len(results),
    }
