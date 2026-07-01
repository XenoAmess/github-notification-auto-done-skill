"""Tests for the GitHub API client."""

from __future__ import annotations

import pytest
import responses

from github_notification_auto_done.client import (
    GITHUB_API_BASE,
    GitHubAPIError,
    GitHubClient,
)


@pytest.fixture
def client(settings) -> GitHubClient:
    return GitHubClient(settings)


class TestParseLinkHeader:
    def test_parses_next_link(self):
        header = '<https://api.github.com/notifications?page=2>; rel="next"'
        result = GitHubClient._parse_link_header(header)
        assert result["next"] == "https://api.github.com/notifications?page=2"

    def test_parses_multiple_links(self):
        header = (
            '<https://api.github.com/notifications?page=2>; rel="next", '
            '<https://api.github.com/notifications?page=5>; rel="last"'
        )
        result = GitHubClient._parse_link_header(header)
        assert result["next"] == "https://api.github.com/notifications?page=2"
        assert result["last"] == "https://api.github.com/notifications?page=5"

    def test_empty_header(self):
        assert GitHubClient._parse_link_header("") == {}


class TestGetNotifications:
    @responses.activate
    def test_fetches_single_page(self, client):
        responses.get(
            f"{GITHUB_API_BASE}/notifications",
            json=[{"id": "1"}],
            status=200,
            match=[
                responses.matchers.query_param_matcher(
                    {"per_page": "100", "all": "true"}
                )
            ],
        )
        result = client.get_notifications()
        assert len(result) == 1
        assert result[0]["id"] == "1"

    @responses.activate
    def test_follows_pagination(self, client):
        responses.get(
            f"{GITHUB_API_BASE}/notifications",
            json=[{"id": "1"}],
            status=200,
            headers={
                "Link": '<https://api.github.com/notifications?page=2>; rel="next"'
            },
            match=[
                responses.matchers.query_param_matcher(
                    {"per_page": "100", "all": "true"}
                )
            ],
        )
        responses.get(
            "https://api.github.com/notifications?page=2",
            json=[{"id": "2"}],
            status=200,
        )
        result = client.get_notifications()
        assert [item["id"] for item in result] == ["1", "2"]

    @responses.activate
    def test_raises_on_401(self, client):
        responses.get(f"{GITHUB_API_BASE}/notifications", status=401)
        with pytest.raises(GitHubAPIError, match="401 Unauthorized"):
            client.get_notifications()


class TestArchiveNotification:
    @responses.activate
    def test_archive_success(self, client):
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/123",
            status=204,
        )
        assert client.archive_notification("123") is True

    @responses.activate
    def test_archive_failure(self, client):
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/123",
            status=500,
        )
        assert client.archive_notification("123") is False


class TestRetryAndRateLimit:
    @responses.activate
    def test_retries_429_and_succeeds(self, client):
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/123",
            status=429,
            headers={"Retry-After": "0"},
        )
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/123",
            status=204,
        )
        assert client.archive_notification("123") is True

    @responses.activate
    def test_respects_ratelimit_reset(self, client):
        import time

        reset_time = int(time.time()) + 1
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/123",
            status=403,
            headers={"X-RateLimit-Reset": str(reset_time)},
        )
        responses.delete(
            f"{GITHUB_API_BASE}/notifications/threads/123",
            status=204,
        )
        assert client.archive_notification("123") is True


class TestExtractThreadId:
    def test_extracts_id(self):
        assert (
            GitHubClient.extract_thread_id_from_url(
                "https://api.github.com/notifications/threads/12345"
            )
            == "12345"
        )

    def test_returns_none_for_invalid(self):
        assert GitHubClient.extract_thread_id_from_url("https://example.com") is None
