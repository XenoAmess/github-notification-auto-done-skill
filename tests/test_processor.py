"""Tests for notification processing logic."""

from __future__ import annotations

from dataclasses import replace

import responses

from github_notification_auto_done.client import GITHUB_API_BASE, GitHubClient
from github_notification_auto_done.models import Notification
from github_notification_auto_done.processor import (
    _is_dependabot,
    _is_pull_request,
    process_notification,
    run,
    summarize,
)


class TestFilters:
    def test_is_pull_request(self, base_notification):
        notif = Notification.from_api(base_notification)
        assert _is_pull_request(notif) is True

    def test_not_pull_request(self, base_notification):
        base_notification["subject"]["type"] = "Issue"
        notif = Notification.from_api(base_notification)
        assert _is_pull_request(notif) is False

    def test_looks_like_dependabot_by_title(self, base_notification):
        notif = Notification.from_api(base_notification)
        assert notif.looks_like_dependabot() is True

    def test_confirm_dependabot_via_api(
        self, settings, base_notification, dependabot_pr_payload
    ):
        base_notification["subject"]["title"] = "Feature"
        with responses.RequestsMock() as rsps:
            rsps.get(
                "https://api.github.com/repos/owner/demo/pulls/42",
                json=dependabot_pr_payload,
                status=200,
            )
            client = GitHubClient(settings)
            notif = Notification.from_api(base_notification)
            assert _is_dependabot(client, notif) is True

    def test_confirm_not_dependabot_via_api(
        self, settings, base_notification, human_pr_payload
    ):
        base_notification["subject"]["title"] = "Feature"
        with responses.RequestsMock() as rsps:
            rsps.get(
                "https://api.github.com/repos/owner/demo/pulls/42",
                json=human_pr_payload,
                status=200,
            )
            client = GitHubClient(settings)
            notif = Notification.from_api(base_notification)
            assert _is_dependabot(client, notif) is False


class TestProcessNotification:
    @responses.activate
    def test_archives_merged_dependabot_pr(
        self, settings, base_notification, dependabot_pr_payload
    ):
        responses.get(
            "https://api.github.com/repos/owner/demo/pulls/42",
            json=dependabot_pr_payload,
        )
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/12345",
            status=204,
        )
        client = GitHubClient(replace(settings, dry_run=False))
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, replace(settings, dry_run=False))
        assert result.archived is True
        assert result.status == "merged"

    @responses.activate
    def test_skips_open_dependabot_pr(
        self, settings, base_notification, open_dependabot_pr_payload
    ):
        responses.get(
            "https://api.github.com/repos/owner/demo/pulls/42",
            json=open_dependabot_pr_payload,
        )
        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)
        assert result.skipped is True
        assert result.status == "skip_open"

    @responses.activate
    def test_dry_run_does_not_archive(
        self, settings, base_notification, dependabot_pr_payload
    ):
        responses.get(
            "https://api.github.com/repos/owner/demo/pulls/42",
            json=dependabot_pr_payload,
        )
        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)
        assert result.skipped is True
        assert result.archived is False

    @responses.activate
    def test_excluded_repo_skipped(self, settings, base_notification):
        settings = replace(settings, exclude_repos=["owner/demo"])
        client = GitHubClient(settings)
        notif = Notification.from_api(base_notification)
        result = process_notification(client, notif, settings)
        assert result.skipped is True
        assert result.status == "excluded_repo"


class TestRunAndSummarize:
    @responses.activate
    def test_run_processes_multiple_notifications(
        self, settings, base_notification, dependabot_pr_payload
    ):
        responses.get(
            "https://api.github.com/repos/owner/demo/pulls/42",
            json=dependabot_pr_payload,
        )
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/12345",
            status=204,
        )
        client = GitHubClient(replace(settings, dry_run=False, max_workers=1))
        notif = Notification.from_api(base_notification)
        results = run(client, replace(settings, dry_run=False), [notif])
        summary = summarize(results)
        assert summary["archived"] == 1

    def test_summarize_counts(self):
        from github_notification_auto_done.processor import ProcessResult

        results = [
            ProcessResult("1", "a", "owner/a", "merged", archived=True),
            ProcessResult("2", "b", "owner/b", "skip_open", skipped=True),
            ProcessResult("3", "c", "owner/c", "error", error=True),
        ]
        summary = summarize(results)
        assert summary == {"archived": 1, "skipped": 1, "errors": 1, "total": 3}
