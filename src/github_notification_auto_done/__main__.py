"""Allow running the package with ``python -m github_notification_auto_done``."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
