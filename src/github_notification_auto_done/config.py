"""Configuration management for GitHub notification auto done."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

from dotenv import load_dotenv

DEFAULT_SINCE_HOURS = 24
DEFAULT_MAX_WORKERS = 4


@dataclass(frozen=True)
class Settings:
    """Application settings aggregated from env, .env, config file and CLI."""

    github_token: str
    since: datetime
    max_workers: int = DEFAULT_MAX_WORKERS
    exclude_repos: List[str] = field(default_factory=list)
    dry_run: bool = False
    log_file: Optional[Path] = None
    json_logs: bool = False
    verbose: bool = False

    @property
    def auth_header(self) -> str:
        """Return the Authorization header value.

        Supports both classic PAT (ghp_*) and fine-grained PAT (github_*).
        GitHub recommends the Bearer scheme for both token types.
        """
        return f"Bearer {self.github_token}"


def _parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 timestamp string into an aware datetime."""
    # Python 3.8 does not support datetime.fromisoformat for 'Z' suffix.
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_since() -> datetime:
    """Return the default 'since' value (24 hours ago UTC)."""
    return datetime.now(timezone.utc) - timedelta(hours=DEFAULT_SINCE_HOURS)


def _load_dotenv() -> None:
    """Load environment variables from the project .env file if present."""
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if not env_file.exists():
        env_file = Path.cwd() / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def _load_config_file(path: Path) -> dict[str, Any]:
    """Load an optional JSON or TOML configuration file."""
    data: dict[str, Any] = {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".json"}:
        data = json.loads(text)
    else:
        try:
            import tomllib  # Python 3.11+

            data = tomllib.loads(text)
        except ImportError:
            import tomli

            data = tomli.loads(text)
    return data


def _coerce_since(value: Optional[str]) -> datetime:
    """Coerce a 'since' string to a UTC datetime."""
    if not value:
        return _default_since()
    try:
        return _parse_iso8601(value)
    except ValueError as exc:
        raise ValueError(f"Invalid --since value: {value!r}") from exc


def _coerce_exclude_repos(value: Optional[str]) -> List[str]:
    """Coerce a comma-separated repository list into a clean list."""
    if not value:
        return []
    return [repo.strip() for repo in value.split(",") if repo.strip()]


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="github-notification-auto-done",
        description=(
            "Auto-archive dependabot Pull Request notifications on GitHub "
            "when they are merged or closed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the notifications that would be archived without archiving them.",
    )
    parser.add_argument(
        "--since",
        metavar="ISO8601",
        help="Only process notifications updated after this time (ISO 8601). "
        f"Defaults to {DEFAULT_SINCE_HOURS} hours ago.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=(
            "Maximum concurrent workers for API calls "
            f"(default: {DEFAULT_MAX_WORKERS})."
        ),
    )
    parser.add_argument(
        "--exclude-repo",
        metavar="OWNER/REPO",
        help="Comma-separated list of repositories to exclude (e.g. owner/a,owner/b).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        metavar="PATH",
        help="Optional log file path. If omitted, logs are written to stdout only.",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="Emit logs in JSON format.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG level logging.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="Optional JSON or TOML configuration file.",
    )
    return parser


def load_settings(argv: Optional[Sequence[str]] = None) -> Settings:
    """Aggregate settings from .env, environment variables, config file and CLI."""
    _load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)

    config: dict[str, Any] = {}
    if args.config:
        config = _load_config_file(args.config)

    token = os.environ.get("GITHUB_TOKEN") or config.get("github_token", "")
    if not token:
        print(
            "error: GITHUB_TOKEN is not set. "
            "Create a .env file or export the environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    since_str = args.since or os.environ.get("SINCE") or config.get("since")
    since = _coerce_since(since_str)

    max_workers_env = os.environ.get("MAX_WORKERS")
    max_workers = config.get("max_workers", DEFAULT_MAX_WORKERS)
    if max_workers_env:
        max_workers = int(max_workers_env)
    if args.max_workers != DEFAULT_MAX_WORKERS:
        max_workers = args.max_workers

    exclude_env = os.environ.get("EXCLUDE_REPOS")
    exclude_str = args.exclude_repo or exclude_env or config.get("exclude_repos", "")
    exclude_repos = _coerce_exclude_repos(exclude_str)

    dry_run = args.dry_run or config.get("dry_run", False)
    log_file = args.log_file or config.get("log_file")
    json_logs = args.json_logs or config.get("json_logs", False)
    verbose = args.verbose or config.get("verbose", False)

    return Settings(
        github_token=token,
        since=since,
        max_workers=max_workers,
        exclude_repos=exclude_repos,
        dry_run=dry_run,
        log_file=Path(log_file) if log_file else None,
        json_logs=json_logs,
        verbose=verbose,
    )
