# GitHub Notification Auto Done

Auto-archive dependabot Pull Request notifications on GitHub when they are merged or closed.

## What it does

Scans your GitHub notifications hourly, identifies dependabot PRs that are already merged or closed, and archives them from your inbox using the GitHub REST API (`DELETE /notifications/threads/{id}`).

## Prerequisites

- Python 3.8+
- A GitHub Personal Access Token with `notifications` and `repo` permissions

## Setup

1. Copy `.env.example` to `.env` and fill in your token:
   ```bash
   cp .env.example .env
   # edit .env
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run manually:
   ```bash
   python scripts/github_notification_auto_done.py
   ```

4. Or add to cron (hourly):
   ```cron
   0 * * * * /usr/bin/python3 /path/to/scripts/github_notification_auto_done.py >> /tmp/github_cleanup.log 2>&1
   ```

## How it works

1. Fetches all notifications from `GET /notifications`
2. Filters for PullRequest type notifications
3. For each PR, checks if the author is `dependabot[bot]`
4. Checks PR status via the PR API (`merged` or `closed`)
5. Archives qualifying notifications with `DELETE /notifications/threads/{id}`

## Notes

- Open PRs are skipped (not archived)
- Uses concurrent requests (2 workers) with retry logic to handle rate limits
- Logs are written to stdout; redirect to file for cron jobs
