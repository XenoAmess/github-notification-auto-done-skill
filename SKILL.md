# GitHub Notification Auto Done

Auto-archive dependabot Pull Request notifications on GitHub when they are merged or closed.

## When to use

- Your GitHub notifications inbox is cluttered with dependabot PRs.
- You want to automatically clean up notifications for merged/closed dependabot PRs.
- You want to run this as a scheduled task (cron).

## Prerequisites

- Python 3.8+
- GitHub Personal Access Token (classic with `notifications` and `repo` scopes, or fine-grained PAT with equivalent permissions)

## Setup

1. Create a GitHub Personal Access Token at https://github.com/settings/tokens
2. Set the token in a `.env` file or as the environment variable `GITHUB_TOKEN`.
3. Install dependencies:
   ```bash
   pip install -e .
   ```

## Usage

### Manual run

```bash
python -m github_notification_auto_done
```

### Dry run

```bash
python -m github_notification_auto_done --dry-run
```

### Cron (hourly)

```cron
0 * * * * /usr/bin/python3 -m github_notification_auto_done
```

## How it works

1. Fetches notifications via `GET /notifications` with pagination.
2. Filters for `PullRequest` notifications.
3. Identifies dependabot PRs by title, latest comment URL, or PR author.
4. Fetches each PR to confirm status.
5. Archives qualifying notifications via the official endpoint `DELETE /notifications/threads/{thread_id}` ("Mark a thread as done").

## Parameters

| Source | Name | Required | Description |
|--------|------|----------|-------------|
| `.env` / env | `GITHUB_TOKEN` | Yes | GitHub Personal Access Token |
| CLI | `--dry-run` | No | Preview without archiving |
| CLI / env / config | `--since` / `SINCE` | No | ISO 8601 timestamp; defaults to 24 hours ago |
| CLI / env / config | `--max-workers` / `MAX_WORKERS` | No | Concurrency; default `4` |
| CLI / env / config | `--exclude-repo` / `EXCLUDE_REPOS` | No | Comma-separated `owner/repo` blacklist |
| CLI / env / config | `--log-file` / `LOG_FILE` | No | Optional log file path |
| CLI / env / config | `--json-logs` / `JSON_LOGS` | No | Output logs as JSON |
| CLI / env / config | `-v` / `VERBOSE` | No | Enable DEBUG logging |
| CLI | `--config` | No | JSON or TOML config file |

## Notes

- Open PRs are intentionally skipped.
- Uses a thread pool for concurrent PR status checks.
- Retries on 429/502/503/504 and respects `Retry-After` / `X-RateLimit-Reset`.
- Supports both classic PAT (`ghp_*`) and fine-grained PAT (`github_*`).
- The package entry point is `python -m github_notification_auto_done`.
- A backward-compatible wrapper remains at `scripts/github_notification_auto_done.py`.
