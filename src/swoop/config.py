"""User preferences stored in ~/.config/swoop/config.toml.

Holds the queue limits, the download folder and whether the first-run setup
guide was completed; an unreadable or invalid file falls back to defaults
instead of preventing Swoop from starting.
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from swoop.aria2.process import QueueLimits

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preferences:
    limits: QueueLimits = field(default_factory=QueueLimits)
    download_dir: Path | None = None  # None: the user's XDG download folder
    setup_done: bool = False


def load_preferences(path: Path) -> Preferences:
    try:
        data = tomllib.loads(path.read_text())
        return _parse(data)
    except FileNotFoundError:
        return Preferences()
    except (OSError, ValueError, TypeError) as exc:  # TOMLDecodeError is a ValueError
        log.warning("ignoring invalid %s: %s", path, exc)
        return Preferences()


def _parse(data: dict[str, object]) -> Preferences:
    limits = QueueLimits(
        max_concurrent_downloads=_integer(data, "max_concurrent_downloads", 3),
        max_download_speed=_integer(data, "max_download_speed", 0),
    )
    directory = data.get("download_dir")
    if directory is not None and not (isinstance(directory, str) and os.path.isabs(directory)):
        raise ValueError("download_dir must be an absolute path")
    setup_done = data.get("setup_done", False)
    if not isinstance(setup_done, bool):
        raise ValueError("setup_done must be true or false")
    return Preferences(limits, Path(directory) if directory else None, setup_done)


def _integer(data: dict[str, object], key: str, default: int) -> int:
    value = data.get(key, default)
    if type(value) is not int:  # bool is an int subclass, so compare the exact type
        raise ValueError(f"{key} must be an integer")
    return value


def save_preferences(path: Path, preferences: Preferences) -> None:
    """Write atomically, so a crash never leaves a truncated file behind."""
    limits = preferences.limits
    lines = [
        f"max_concurrent_downloads = {limits.max_concurrent_downloads}",
        f"max_download_speed = {limits.max_download_speed}",
        f"setup_done = {str(preferences.setup_done).lower()}",
    ]
    if preferences.download_dir is not None:
        # A JSON string literal is also a valid TOML basic string.
        lines.append(f"download_dir = {json.dumps(str(preferences.download_dir))}")
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n")
    os.replace(temporary, path)
