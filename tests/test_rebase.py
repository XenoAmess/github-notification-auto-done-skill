"""Tests for the dependabot auto-rebase nudge logic."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import responses

from github_notification_auto_done.client import GITHUB_API_BASE, GitHubClient
from github_notification_auto_done.models import Notification
from github_notification_auto_done.processor import process_notification

PR_URL = f"{GITHUB_API_BASE}/repos/owner/demo/pulls/42"
COMMENTS_URL = f"{GITHUB_API_BASE}/repos/owner/demo/issues/42/comments"
CHECK_RUNS_URL = f"{GITHUB_API_BASE}/repos/owner/demo/commits/abc123/check-runs"
STATUS_URL = f"{GITHUB_API_BASE}/repos/owner/demo/commits/abc123/status"
HEAD_SHA = "abc123"


def _open_pr_payload(mergeable_state: str = "behind") -> dict:
    """Return an open dependabot PR payload with mergeable state details."""
    return {
        "url": PR_URL,
        "number": 42,
        "state": "open",
        "merged": False,
        "title": "Bump requests from 2.30.0 to 2.31.0",
        "user": {"login": "dependabot[bot]", "id": 49699333},
        "mergeable_state": mergeable_state,
        "head": {"sha": HEAD_SHA},
        "comments_url": COMMENTS_URL,
        "base": {"repo": {"full_name": "owner/demo"}},
    }


def _green_check_runs() -> dict:
    return {
        "total_count": 3,
        "check_runs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "skipped"},
            {"status": "completed", "conclusion": "neutral"},
        ],
    }


def _register_green_checks() -> None:
    responses.get(CHECK_RUNS_URL, json=_green_check_runs())
    responses.get(
        STATUS_URL,
        json={"state": "success", "total_count": 1, "statuses": []},
    )


def _register_no_comments() -> None:
    responses.get(COMMENTS_URL, json=[])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class TestAutoRebaseComment:
    @responses.activate
    def test_comments_when_all_conditions_met(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True, dry_run=False)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        _register_green_checks()
        _register_no_comments()
        responses.post(COMMENTS_URL, json={"id": 1}, status=201)

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.commented is True
        assert result.status == "rebase_requested"

    @responses.activate
    def test_dry_run_does_not_comment(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True, dry_run=True)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        _register_green_checks()
        _register_no_comments()

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.commented is False
        assert result.status == "rebase_requested"

    @responses.activate
    def test_skips_when_not_behind(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True)
        responses.get(PR_URL, json=_open_pr_payload("clean"))

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.status == "skip_open_not_behind"

    @responses.activate
    def test_skips_when_check_run_failing(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        responses.get(
            CHECK_RUNS_URL,
            json={
                "total_count": 1,
                "check_runs": [{"status": "completed", "conclusion": "failure"}],
            },
        )

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.status == "skip_open_checks_not_passed"

    @responses.activate
    def test_skips_when_check_run_pending(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        responses.get(
            CHECK_RUNS_URL,
            json={
                "total_count": 1,
                "check_runs": [{"status": "in_progress", "conclusion": None}],
            },
        )

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.status == "skip_open_checks_not_passed"

    @responses.activate
    def test_skips_when_combined_status_failing(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        responses.get(CHECK_RUNS_URL, json=_green_check_runs())
        responses.get(
            STATUS_URL,
            json={"state": "failure", "total_count": 1, "statuses": []},
        )

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.status == "skip_open_checks_not_passed"


class TestRebaseCooldown:
    @responses.activate
    def test_skips_when_recent_rebase_request(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True, dry_run=False)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        _register_green_checks()
        responses.get(
            COMMENTS_URL,
            json=[
                {
                    "body": "@dependabot rebase",
                    "created_at": _iso(datetime.now(timezone.utc)),
                }
            ],
        )

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.commented is False
        assert result.status == "skip_open_rebase_pending"

    @responses.activate
    def test_comments_when_previous_request_expired(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True, dry_run=False)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        _register_green_checks()
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        responses.get(
            COMMENTS_URL,
            json=[{"body": "@dependabot rebase", "created_at": _iso(old)}],
        )
        responses.post(COMMENTS_URL, json={"id": 1}, status=201)

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.commented is True
        assert result.status == "rebase_requested"

    @responses.activate
    def test_ignores_unrelated_comments(self, settings, base_notification):
        settings = replace(settings, auto_rebase=True, dry_run=False)
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        _register_green_checks()
        responses.get(
            COMMENTS_URL,
            json=[
                {
                    "body": "LGTM, please rebase soon",
                    "created_at": _iso(datetime.now(timezone.utc)),
                }
            ],
        )
        responses.post(COMMENTS_URL, json={"id": 1}, status=201)

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.commented is True
        assert result.status == "rebase_requested"


class TestMergeableStateUnknown:
    @responses.activate
    def test_refetches_when_mergeable_state_unknown(
        self, settings, base_notification, monkeypatch
    ):
        monkeypatch.setattr(
            "github_notification_auto_done.processor.MERGEABLE_STATE_RETRY_DELAY", 0
        )
        settings = replace(settings, auto_rebase=True, dry_run=False)
        responses.get(PR_URL, json=_open_pr_payload("unknown"))
        responses.get(PR_URL, json=_open_pr_payload("behind"))
        _register_green_checks()
        _register_no_comments()
        responses.post(COMMENTS_URL, json={"id": 1}, status=201)

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.commented is True
        assert result.status == "rebase_requested"


class TestAutoRebaseDisabled:
    @responses.activate
    def test_skips_open_pr_without_touching_checks(self, settings, base_notification):
        # auto_rebase defaults to False: no check-runs/comments calls allowed.
        responses.get(PR_URL, json=_open_pr_payload("behind"))

        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)

        assert result.skipped is True
        assert result.commented is False
        assert result.status == "skip_open"
