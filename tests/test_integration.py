"""End-to-end integration tests mocking the full GitHub API flow."""

from __future__ import annotations

import responses

from github_notification_auto_done.cli import main
from github_notification_auto_done.client import GITHUB_API_BASE


def _notification_payload(
    thread_id: str,
    title: str,
    pr_number: int,
    repo: str = "owner/demo",
    updated_at: str = "2024-06-15T12:00:00Z",
) -> dict:
    return {
        "id": thread_id,
        "unread": True,
        "reason": "subscribed",
        "updated_at": updated_at,
        "last_read_at": None,
        "url": f"{GITHUB_API_BASE}/notifications/threads/{thread_id}",
        "subscription_url": (
            f"{GITHUB_API_BASE}/notifications/threads/{thread_id}/subscription"
        ),
        "repository": {
            "id": 1,
            "node_id": "R_1",
            "name": "demo",
            "full_name": repo,
            "private": False,
            "html_url": f"https://github.com/{repo}",
            "url": f"{GITHUB_API_BASE}/repos/{repo}",
        },
        "subject": {
            "title": title,
            "url": f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}",
            "latest_comment_url": f"{GITHUB_API_BASE}/repos/{repo}/issues/comments/1",
            "type": "PullRequest",
        },
    }


def _pr_payload(
    pr_number: int,
    author: str,
    state: str,
    merged: bool,
    repo: str = "owner/demo",
) -> dict:
    return {
        "url": f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}",
        "id": pr_number,
        "number": pr_number,
        "state": state,
        "title": f"PR #{pr_number}",
        "user": {"login": author, "id": 1},
        "merged": merged,
    }


@responses.activate
def test_full_flow_archives_merged_dependabot(caplog, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_integration")

    notifications = [
        _notification_payload("1", "Bump requests", 1),
    ]

    responses.get(
        f"{GITHUB_API_BASE}/notifications",
        json=notifications,
        status=200,
    )
    responses.get(
        f"{GITHUB_API_BASE}/repos/owner/demo/pulls/1",
        json=_pr_payload(1, "dependabot[bot]", "closed", True),
    )
    responses.delete(
        f"{GITHUB_API_BASE}/notifications/threads/1",
        status=204,
    )

    with caplog.at_level("INFO"):
        rc = main(["--dry-run", "--since", "2024-01-01T00:00:00Z"])

    assert rc == 0
    assert "Would archive" in caplog.text or "Archived" in caplog.text


@responses.activate
def test_full_flow_skips_open_human_pr(caplog, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_integration")

    notifications = [
        _notification_payload("2", "Feature", 2),
    ]

    responses.get(
        f"{GITHUB_API_BASE}/notifications",
        json=notifications,
        status=200,
    )
    responses.get(
        f"{GITHUB_API_BASE}/repos/owner/demo/pulls/2",
        json=_pr_payload(2, "dependabot[bot]", "open", False),
    )

    with caplog.at_level("INFO"):
        rc = main(["--dry-run", "--since", "2024-01-01T00:00:00Z"])

    assert rc == 0
    assert "Skip unfinished PR [open]" in caplog.text


@responses.activate
def test_full_flow_respects_exclude_repo(caplog, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_integration")

    notifications = [
        _notification_payload("3", "Bump foo", 3, repo="owner/other"),
    ]

    responses.get(
        f"{GITHUB_API_BASE}/notifications",
        json=notifications,
        status=200,
    )

    with caplog.at_level("INFO"):
        rc = main(
            [
                "--dry-run",
                "--since",
                "2024-01-01T00:00:00Z",
                "--exclude-repo",
                "owner/other",
            ]
        )

    assert rc == 0
    assert "Skip excluded repo" in caplog.text


@responses.activate
def test_full_flow_non_pr_notification_skipped(caplog, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_integration")

    notification = _notification_payload("4", "Issue", 4)
    notification["subject"]["type"] = "Issue"
    notification["subject"]["url"] = f"{GITHUB_API_BASE}/repos/owner/demo/issues/4"

    responses.get(
        f"{GITHUB_API_BASE}/notifications",
        json=[notification],
        status=200,
    )

    with caplog.at_level("INFO"):
        rc = main(["--dry-run", "--since", "2024-01-01T00:00:00Z"])

    assert rc == 0
    assert "Skip non-pull-request" in caplog.text
