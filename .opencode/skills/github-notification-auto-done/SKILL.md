---
name: github-notification-auto-done
description: >
  Use when the user wants to clean up, archive, or mark-as-done GitHub
  notifications for merged or closed dependabot Pull Requests, or mentions
  GitHub notification inbox clutter, dependabot notifications, auto-archiving
  PR notifications, or running a scheduled notification cleanup task.
---

# GitHub Notification Auto Done

Archive merged/closed dependabot Pull Request notifications from the GitHub
inbox using the official GitHub REST API.

## When to use

Trigger this skill when the user asks for any of the following:

- "Archive my dependabot GitHub notifications"
- "Clean up merged/closed dependabot PRs from my GitHub inbox"
- "Mark dependabot PR notifications as done"
- "Auto-archive dependabot notifications"
- "Run the GitHub notification cleanup tool"
- "Set up a cron job to archive dependabot PRs"

Do **not** use this skill for non-dependabot notifications, GitHub Issues,
Discussions, or repository-level automation unrelated to notification cleanup.

## Before running

1. Verify the project is installed:
   ```bash
   pip install -e .
   ```
2. Check that `.env` exists and contains a non-empty `GITHUB_TOKEN`.
3. If `.env` is missing or empty, stop and ask the user to create a GitHub
   Personal Access Token at https://github.com/settings/tokens.
4. Required token scopes:
   - Classic PAT: `notifications` and `repo`
   - Fine-grained PAT: read access to notifications and repository
     contents/pull requests
5. **Never** commit `.env` or expose the token in chat output or logs.

## How to run

Always prefer `--dry-run` first unless the user explicitly asks to archive
notifications immediately.

### Preview mode (recommended first step)

```bash
python -m github_notification_auto_done --dry-run
```

### Actually archive notifications

```bash
python -m github_notification_auto_done
```

### Backwards-compatible script entry

```bash
python scripts/github_notification_auto_done.py --dry-run
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--dry-run` | `false` | Preview which notifications would be archived |
| `--since` | 24 hours ago | ISO 8601 timestamp; only process notifications updated after this time |
| `--max-workers` | `4` | Concurrent API workers |
| `--exclude-repo` | none | Comma-separated `owner/repo` blacklist |
| `--log-file` | none | Also write logs to a file |
| `--json-logs` | `false` | Emit logs as newline-delimited JSON |
| `-v` / `--verbose` | `false` | DEBUG level logging |
| `--config` | none | JSON or TOML config file with defaults |

Environment variables with the same names (`SINCE`, `MAX_WORKERS`,
`EXCLUDE_REPOS`, `LOG_FILE`, `JSON_LOGS`, `VERBOSE`) are also supported.

## What the tool does

1. Fetches notifications from `GET /notifications` with pagination.
2. Keeps only `PullRequest` notifications.
3. Identifies dependabot PRs by title, latest comment URL, or PR author.
4. Fetches each candidate PR to confirm it is `merged` or `closed`.
5. Archives qualifying notifications via the official GitHub endpoint
   `DELETE /notifications/threads/{thread_id}` ("Mark a thread as done").

## Scheduling

To run hourly, add a cron entry:

```cron
0 * * * * cd /path/to/repo && /path/to/venv/bin/python -m github_notification_auto_done >> /var/log/github_cleanup.log 2>&1
```

## Error handling

- If `GITHUB_TOKEN` is missing, the tool exits with an error. Ask the user to
  set it before re-running.
- If GitHub returns rate-limit headers, the tool sleeps and retries.
- If a single notification fails, the tool logs the error and continues with
  the remaining notifications.

## Safety rules

- Do not run the real archive command without user confirmation or a prior
  `--dry-run`, unless the user explicitly requests immediate execution.
- Never modify, commit, or leak the contents of `.env`.
- Do not share the token value in responses.
