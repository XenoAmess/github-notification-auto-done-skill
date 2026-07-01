#!/usr/bin/env python3
"""Backward-compatible script entry point.

This thin wrapper imports the package and invokes the CLI. It exists so that
existing cron jobs and documentation referencing ``scripts/...`` continue to
work.
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from github_notification_auto_done.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
