# GitHub Notification Auto Done

Auto-archive dependabot Pull Request notifications on GitHub when they are merged or closed.

## When to use

- Your GitHub notifications inbox is cluttered with dependabot PRs
- You want to automatically clean up notifications for merged/closed dependabot PRs
- You want to run this as a scheduled task (cron)

## Prerequisites

- Python 3.8+
- GitHub Personal Access Token with `notifications` and `repo` scopes

## Setup

1. Create a GitHub Personal Access Token at https://github.com/settings/tokens
   - Required scopes: `notifications`, `repo`

2. Set environment variable or create `.env` file:
   ```bash
   export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Manual run

```bash
python scripts/github_notification_auto_done.py
```

### Cron (hourly)

```cron
0 * * * * /usr/bin/python3 /path/to/scripts/github_notification_auto_done.py >> /tmp/github_cleanup.log 2>&1
```

## How it works

1. Fetches all notifications via `GET /notifications`
2. Filters for PullRequest notifications
3. Checks PR author — must be `dependabot[bot]`
4. Checks PR status — must be `merged` or `closed`
5. Archives matching notifications via `DELETE /notifications/threads/{id}`

## Parameters

| Env Var | Required | Description |
|---------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub Personal Access Token |

## Notes

- Open PRs are intentionally skipped
- Uses 2 concurrent workers with retry logic to avoid rate limits
- The script reads `.env` file automatically if present
