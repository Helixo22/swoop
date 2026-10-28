"""XDG locations used by Swoop.

Configuration lives in ~/.config/swoop and data (aria2 session, history) in
~/.local/share/swoop, which is created private because it stores URLs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gi.repository import GLib

APP_ID = "io.github.swoop.Swoop"


def _xdg_dir(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    # The XDG spec requires absolute paths and says relative ones must be ignored.
    return Path(value) if os.path.isabs(value) else Path.home() / fallback


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    download_dir: Path

    @classmethod
    def from_environment(cls) -> AppPaths:
        return cls(
            config_dir=_xdg_dir("XDG_CONFIG_HOME", ".config") / "swoop",
            data_dir=_xdg_dir("XDG_DATA_HOME", ".local/share") / "swoop",
            download_dir=_user_download_dir(),
        )

    @property
    def session_file(self) -> Path:
        return self.data_dir / "aria2.session"

    @property
    def history_db(self) -> Path:
        return self.data_dir / "history.db"

    def create(self) -> None:
        """Create the directories; data is private to the user (0700)."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)
        self.download_dir.mkdir(parents=True, exist_ok=True)


def _user_download_dir() -> Path:
    special = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
    return Path(special) if special else Path.home() / "Downloads"
