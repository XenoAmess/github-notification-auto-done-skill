"""Tests for configuration loading."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest

from github_notification_auto_done.config import (
    Settings,
    _coerce_since,
    load_settings,
)


class TestCoerceSince:
    def test_parses_iso8601_with_z(self):
        result = _coerce_since("2024-01-15T10:30:00Z")
        assert result == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)

    def test_parses_iso8601_with_offset(self):
        result = _coerce_since("2024-01-15T10:30:00+08:00")
        assert result.hour == 2
        assert result.tzinfo == timezone.utc

    def test_defaults_to_24h_ago_when_empty(self):
        before = datetime.now(timezone.utc)
        result = _coerce_since("")
        after = datetime.now(timezone.utc)
        assert before - timedelta(hours=25) < result < after

    def test_raises_on_invalid_value(self):
        with pytest.raises(ValueError):
            _coerce_since("not-a-date")


class TestSettings:
    def test_auth_header_bears_token(self):
        settings = Settings(github_token="ghp_secret", since=datetime.now(timezone.utc))
        assert settings.auth_header == "Bearer ghp_secret"


class TestLoadSettings:
    def test_missing_token_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["prog"])
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            load_settings()
        assert exc.value.code == 1

    def test_env_token_used(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
        monkeypatch.setattr(sys, "argv", ["prog"])
        settings = load_settings()
        assert settings.github_token == "ghp_env_token"

    def test_cli_overrides_max_workers(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        monkeypatch.setattr(sys, "argv", ["prog", "--max-workers", "8"])
        settings = load_settings()
        assert settings.max_workers == 8

    def test_cli_dry_run(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        monkeypatch.setattr(sys, "argv", ["prog", "--dry-run"])
        settings = load_settings()
        assert settings.dry_run is True

    def test_exclude_repos_parsed(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        monkeypatch.setattr(sys, "argv", ["prog", "--exclude-repo", "owner/a, owner/b"])
        settings = load_settings()
        assert settings.exclude_repos == ["owner/a", "owner/b"]

    def test_config_file_json(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        config_file = tmp_path / "config.json"
        config_file.write_text('{"max_workers": 10, "dry_run": true}')
        monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_file)])
        settings = load_settings()
        assert settings.max_workers == 10
        assert settings.dry_run is True


# Need timedelta import for test_defaults_to_24h_ago_when_empty
from datetime import timedelta  # noqa: E402
