"""Shared test fixtures and helpers."""

from __future__ import annotations

import pytest

from github_notification_auto_done.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Return a minimal Settings object for testing."""
    return Settings(
        github_token="ghp_test_token",
        since="2024-01-01T00:00:00Z",
        max_workers=2,
        dry_run=True,
    )


@pytest.fixture
def base_notification() -> dict:
    """Return a base notification payload that can be customized."""
    return {
        "id": "12345",
        "unread": True,
        "reason": "subscribed",
        "updated_at": "2024-06-15T12:00:00Z",
        "last_read_at": None,
        "url": "https://api.github.com/notifications/threads/12345",
        "subscription_url": "https://api.github.com/notifications/threads/12345/subscription",
        "repository": {
            "id": 1,
            "node_id": "R_1",
            "name": "demo",
            "full_name": "owner/demo",
            "private": False,
            "html_url": "https://github.com/owner/demo",
            "description": None,
            "fork": False,
            "url": "https://api.github.com/repos/owner/demo",
        },
        "subject": {
            "title": "Bump requests from 2.30.0 to 2.31.0 by dependabot",
            "url": "https://api.github.com/repos/owner/demo/pulls/42",
            "latest_comment_url": "https://api.github.com/repos/owner/demo/issues/comments/1",
            "type": "PullRequest",
        },
    }


def _dependabot_pr_payload() -> dict:
    """Return a merged dependabot PR payload."""
    return {
        "url": "https://api.github.com/repos/owner/demo/pulls/42",
        "id": 42,
        "node_id": "PR_42",
        "html_url": "https://github.com/owner/demo/pull/42",
        "number": 42,
        "state": "closed",
        "locked": False,
        "title": "Bump requests from 2.30.0 to 2.31.0",
        "user": {
            "login": "dependabot[bot]",
            "id": 49699333,
        },
        "merged": True,
        "mergeable": None,
        "merged_by": {
            "login": "owner",
        },
    }


@pytest.fixture
def dependabot_pr_payload() -> dict:
    """Return a merged dependabot PR payload."""
    return _dependabot_pr_payload()


@pytest.fixture
def open_dependabot_pr_payload() -> dict:
    """Return an open dependabot PR payload."""
    payload = _dependabot_pr_payload()
    payload["state"] = "open"
    payload["merged"] = False
    return payload


@pytest.fixture
def human_pr_payload() -> dict:
    """Return a PR payload authored by a human."""
    payload = _dependabot_pr_payload()
    payload["user"] = {"login": "human", "id": 1}
    return payload
