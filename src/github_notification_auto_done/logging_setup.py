"""Logging configuration supporting stdout, file and JSON output."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional


class JsonFormatter(logging.Formatter):
    """Emit log records as newline-delimited JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(
    *,
    verbose: bool = False,
    log_file: Optional[Path] = None,
    json_logs: bool = False,
) -> None:
    """Configure application logging.

    By default logs are written to stdout only. Optionally also write to a
    file. JSON formatting can be enabled for both destinations.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = []

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.set_name("stdout")
    handlers.append(stdout_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.set_name("file")
        handlers.append(file_handler)

    if json_logs:
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    for handler in handlers:
        handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)

    # Only replace existing handlers of the same type so that test capture
    # handlers (e.g. pytest's caplog) are preserved.
    existing_names = {h.get_name() for h in root.handlers}
    for handler in handlers:
        if handler.get_name() in existing_names:
            for existing in list(root.handlers):
                if existing.get_name() == handler.get_name():
                    root.removeHandler(existing)
        root.addHandler(handler)

    # Keep third-party libraries quieter unless verbose.
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
