#!/usr/bin/env python3
"""
GitHub Dependabot PR 通知自动清理脚本（并发优化版）

功能：每小时检查 GitHub 通知，自动将 dependabot 发起的、状态为 merged/closed 的 PR 通知 archive。

使用 DELETE /notifications/threads/{id} 从 Inbox 真正移除通知。

用法：
    export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
    python3 github_dependabot_cleanup.py

需要 token 权限：notifications, repo
"""

import os
import sys
import requests
import logging
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# 尝试从 .env 文件加载环境变量
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key not in os.environ:
                    os.environ[key] = val.strip().strip('"\'')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("github-cleanup")

GITHUB_API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {}

# 并发控制
MAX_WORKERS = 2

# 创建带重试的 session
def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "DELETE"]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = create_session()


def init_auth():
    if not TOKEN:
        logger.error("GITHUB_TOKEN 未设置")
        sys.exit(1)
    HEADERS.update(
        {
            "Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )


def get_notifications(all_notifs: bool = True) -> List[Dict]:
    """获取通知（默认包含已读和未读）"""
    params = {"all": "true" if all_notifs else "false", "per_page": 100}
    url = f"{GITHUB_API}/notifications"
    notifications = []

    while url:
        resp = SESSION.get(url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 401:
            logger.error("Token 无效或已过期")
            sys.exit(1)
        elif resp.status_code == 403:
            logger.error("API 限流或权限不足: %s", resp.text)
            sys.exit(1)
        elif resp.status_code != 200:
            logger.error("获取通知失败: %s %s", resp.status_code, resp.text)
            break

        data = resp.json()
        notifications.extend(data)
        url = None
        if "Link" in resp.headers:
            links = parse_link_header(resp.headers["Link"])
            url = links.get("next")
        params = None

    return notifications


def parse_link_header(link_header: str) -> Dict[str, str]:
    """解析 HTTP Link header 分页"""
    links = {}
    for part in link_header.split(","):
        section = part.strip().split(";")
        url = section[0].strip()[1:-1]
        name = section[1].strip().split("=")[1][1:-1]
        links[name] = url
    return links


def get_pr_info(pr_url: str) -> Tuple[Optional[str], Optional[str]]:
    """获取 PR 作者和状态 (author, status)"""
    if not pr_url:
        return None, None
    resp = SESSION.get(pr_url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        logger.warning("获取 PR 失败: %s %s", resp.status_code, pr_url)
        return None, None
    pr = resp.json()
    author = pr.get("user", {}).get("login", "")
    status = "merged" if pr.get("merged") else pr.get("state")
    return author, status


def is_dependabot_pr(notification: Dict) -> bool:
    """快速判断：先查标题，不含 dependabot 的再通过 PR API 确认作者"""
    subject = notification.get("subject", {})
    if subject.get("type") != "PullRequest":
        return False

    title = subject.get("title", "")
    if "dependabot" in title.lower():
        return True

    latest_comment = notification.get("latest_comment_url", "")
    if latest_comment and "dependabot" in latest_comment.lower():
        return True

    return None  # 需要进一步查 PR API


def archive_notification(thread_id: str) -> bool:
    """DELETE 通知，真正从 Inbox 移除"""
    url = f"{GITHUB_API}/notifications/threads/{thread_id}"
    resp = SESSION.delete(url, headers=HEADERS, timeout=30)
    return resp.status_code in (204, 200)


def process_notification(notif: Dict) -> Tuple[str, str, bool]:
    """处理单条通知，返回 (title, status, success)"""
    thread_id = notif.get("id")
    title = notif.get("subject", {}).get("title", "无标题")
    pr_url = notif.get("subject", {}).get("url")

    author, status = get_pr_info(pr_url)
    if not author or not status:
        return title, "error", False

    if "dependabot" not in author.lower():
        return title, "not_dependabot", True

    if status not in ("merged", "closed"):
        return title, f"skip_{status}", True

    success = archive_notification(thread_id)
    return title, status, success


def main():
    init_auth()
    logger.info("开始获取通知...")
    notifications = get_notifications(all_notifs=True)
    logger.info("共获取 %d 条通知", len(notifications))

    # 第一步：快速筛选 PR 通知，标题不含 dependabot 的标记为待查
    pr_notifs = []
    for notif in notifications:
        result = is_dependabot_pr(notif)
        if result is True:
            # 标题已确认是 dependabot，直接加入处理队列
            pr_notifs.append(notif)
        elif result is None:
            # 需要查 PR API 确认作者
            pr_notifs.append(notif)

    logger.info("PR 通知候选: %d 条", len(pr_notifs))

    # 第二步：并发处理
    dependabot_done = 0
    skipped = 0
    errors = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_notif = {
            executor.submit(process_notification, notif): notif
            for notif in pr_notifs
        }

        for future in concurrent.futures.as_completed(future_to_notif):
            title, status, success = future.result()

            if status == "not_dependabot":
                continue
            elif status.startswith("skip_"):
                skipped += 1
                logger.info("跳过未关闭 PR [%s]: %s", status[5:], title)
            elif status == "error":
                errors += 1
                logger.warning("处理失败: %s", title)
            elif success:
                dependabot_done += 1
                logger.info("已 archive [%s]: %s", status, title)
            else:
                errors += 1
                logger.error("archive 失败: %s", title)

    logger.info(
        "完成。archive: %d, 跳过: %d, 失败: %d", dependabot_done, skipped, errors
    )


if __name__ == "__main__":
    main()
