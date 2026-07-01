"""GitHub API client with retry, pagination and rate-limit handling."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.0


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an unrecoverable error."""


class GitHubClient:
    """Low-level GitHub API client.

    Handles authentication, retries with jitter, rate-limit waiting and
    pagination. The official API to archive/mark-as-done a notification is
    ``DELETE /notifications/threads/{thread_id}`` ("Mark a thread as done").
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = GITHUB_API_BASE
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=frozenset(["GET", "DELETE", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=5,
            pool_maxsize=max(10, self.settings.max_workers * 2),
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "Authorization": self.settings.auth_header,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        return session

    @staticmethod
    def _parse_link_header(link_header: str) -> Dict[str, str]:
        """Parse an RFC 5988 Link header into a mapping of rel -> URL."""
        links: Dict[str, str] = {}
        if not link_header:
            return links
        for part in link_header.split(","):
            match = re.match(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"', part)
            if match:
                links[match.group(2)] = match.group(1)
        return links

    def _sleep_if_ratelimited(self, response: requests.Response) -> None:
        """Sleep if the response indicates rate limiting."""
        if response.status_code != 403 and response.status_code != 429:
            return

        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                sleep_seconds = int(retry_after)
                logger.warning(
                    "Rate limited; sleeping %d seconds (Retry-After).", sleep_seconds
                )
                time.sleep(sleep_seconds)
                return
            except ValueError:
                pass

        reset_header = response.headers.get("X-RateLimit-Reset")
        if reset_header:
            try:
                reset_timestamp = int(reset_header)
                now = time.time()
                sleep_seconds = max(1, reset_timestamp - int(now) + 1)
                logger.warning(
                    "Rate limited; sleeping %d seconds until X-RateLimit-Reset.",
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
            except ValueError:
                pass

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        allow_retry_once: bool = True,
    ) -> requests.Response:
        """Make an authenticated request and handle rate limiting."""
        response = self.session.request(
            method,
            url,
            params=params,
            json=json_body,
            timeout=DEFAULT_TIMEOUT,
        )

        if response.status_code in (403, 429) and allow_retry_once:
            self._sleep_if_ratelimited(response)
            response = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                timeout=DEFAULT_TIMEOUT,
            )

        if response.status_code == 401:
            raise GitHubAPIError(
                "GitHub API returned 401 Unauthorized. Check your token."
            )

        return response

    def get_notifications(
        self,
        since: Optional[str] = None,
        all_notifications: bool = True,
    ) -> List[dict[str, Any]]:
        """Fetch notifications with pagination.

        Args:
            since: ISO 8601 timestamp to filter notifications updated after.
            all_notifications: If True, include read notifications.
        """
        url: Optional[str] = f"{self.base_url}/notifications"
        params: Dict[str, Any] = {"per_page": 100}
        if all_notifications:
            params["all"] = "true"
        if since:
            params["since"] = since

        notifications: List[dict[str, Any]] = []
        page = 0
        while url:
            page += 1
            response = self._request("GET", url, params=params)
            if response.status_code == 304:
                logger.debug("No new notifications (304).")
                break
            if response.status_code != 200:
                raise GitHubAPIError(
                    f"Failed to fetch notifications: "
                    f"{response.status_code} {response.text}"
                )

            data = response.json()
            if not isinstance(data, list):
                raise GitHubAPIError(f"Unexpected notifications response: {data!r}")

            notifications.extend(data)
            logger.debug("Fetched page %d with %d notifications.", page, len(data))

            links = self._parse_link_header(response.headers.get("Link", ""))
            url = links.get("next")
            params = {}

            poll_interval = response.headers.get("X-Poll-Interval")
            if poll_interval and url:
                with contextlib.suppress(ValueError):
                    time.sleep(max(0, int(poll_interval) - 1))

        return notifications

    def get_pull_request(self, pr_url: str) -> Optional[dict[str, Any]]:
        """Fetch a pull request by its API URL."""
        response = self._request("GET", pr_url)
        if response.status_code != 200:
            logger.warning(
                "Failed to fetch PR %s: %s %s",
                pr_url,
                response.status_code,
                response.text,
            )
            return None
        data = response.json()
        if not isinstance(data, dict):
            logger.warning("Unexpected PR response for %s: %r", pr_url, data)
            return None
        return data

    def archive_notification(self, thread_id: str) -> bool:
        """Mark a notification thread as done.

        Uses the official GitHub REST API endpoint
        ``DELETE /notifications/threads/{thread_id}`` which is documented as
        "Mark a thread as done" (equivalent to archiving a notification in the
        GitHub inbox).
        """
        url = f"{self.base_url}/notifications/threads/{thread_id}"
        response = self._request("DELETE", url)
        if response.status_code == 204:
            return True
        logger.warning(
            "Failed to archive thread %s: %s %s",
            thread_id,
            response.status_code,
            response.text,
        )
        return False

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    @staticmethod
    def extract_thread_id_from_url(notification_url: str) -> Optional[str]:
        """Extract the numeric thread id from a notification API URL."""
        path = urlparse(notification_url).path
        match = re.search(r"/notifications/threads/(\d+)", path)
        return match.group(1) if match else None
