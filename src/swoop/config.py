"""User preferences stored in ~/.config/swoop/config.toml.

Holds the queue limits; an unreadable or invalid file falls back to defaults
instead of preventing Swoop from starting.
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from swoop.aria2.process import QueueLimits

log = logging.getLogger(__name__)


def load_limits(path: Path) -> QueueLimits:
    try:
        data = tomllib.loads(path.read_text())
        return QueueLimits(
            max_concurrent_downloads=data.get("max_concurrent_downloads", 3),
            max_download_speed=data.get("max_download_speed", 0),
        )
    except FileNotFoundError:
        return QueueLimits()
    except (OSError, ValueError, TypeError) as exc:  # TOMLDecodeError is a ValueError
        log.warning("ignoring invalid %s: %s", path, exc)
        return QueueLimits()


def save_limits(path: Path, limits: QueueLimits) -> None:
    """Write atomically, so a crash never leaves a truncated file behind."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        f"max_concurrent_downloads = {limits.max_concurrent_downloads}\n"
        f"max_download_speed = {limits.max_download_speed}\n"
    )
    os.replace(temporary, path)
