"""Domain models for GitHub notifications and pull requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PullRequest:
    """Minimal representation of a GitHub Pull Request."""

    url: str
    author: str
    state: str
    merged: bool

    @property
    def status(self) -> str:
        """Return 'merged' if merged, otherwise the PR state (open/closed)."""
        return "merged" if self.merged else self.state

    @property
    def is_done(self) -> bool:
        """Return True if the PR is merged or closed."""
        return self.merged or self.state == "closed"

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> PullRequest:
        """Build a PullRequest from a GitHub PR API response."""
        user = payload.get("user") or {}
        return cls(
            url=payload.get("url", ""),
            author=user.get("login", ""),
            state=payload.get("state", ""),
            merged=bool(payload.get("merged")),
        )


@dataclass(frozen=True)
class Notification:
    """Minimal representation of a GitHub notification thread."""

    thread_id: str
    title: str
    type: str
    pr_url: str
    latest_comment_url: Optional[str]
    repository_full_name: str
    updated_at: str
    unread: bool
    reason: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Notification:
        """Build a Notification from a GitHub notifications API response."""
        subject = payload.get("subject") or {}
        repository = payload.get("repository") or {}
        return cls(
            thread_id=str(payload.get("id", "")),
            title=subject.get("title", ""),
            type=subject.get("type", ""),
            pr_url=subject.get("url", ""),
            latest_comment_url=subject.get("latest_comment_url"),
            repository_full_name=repository.get("full_name", ""),
            updated_at=payload.get("updated_at", ""),
            unread=bool(payload.get("unread", True)),
            reason=payload.get("reason", ""),
        )

    def looks_like_dependabot(self) -> bool:
        """Return True if the notification title or comment URL hints dependabot."""
        text = " ".join(
            part for part in (self.title, self.latest_comment_url or "") if part
        )
        return "dependabot" in text.lower()
