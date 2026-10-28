"""Desktop integration for Swoop installed from source or with pip.

Installs the .desktop entry (which also opens magnet links and .torrent files)
and the logo into the user's XDG data directory, so launchers, docks and window
lists show Swoop with its icon. A Flatpak exports these itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from gi.repository import Gio

from swoop.paths import APP_ID

DESKTOP_FILE = f"{APP_ID}.desktop"
MAGNET_TYPE = "x-scheme-handler/magnet"
_EXEC_RESERVED = frozenset(" \t\n\"'\\><~|&;$*?#()`")


def in_flatpak() -> bool:
    return "FLATPAK_ID" in os.environ


def install_desktop_entry(data_home: Path, executable: Path) -> list[Path]:
    """Write the launcher (pointing at executable) and the icons; return what was written.

    Every size of the logo is installed: launchers that render SVG poorly (or
    not at all) pick the pre-rendered PNG closest to the size they need.
    """
    entry = data_home / "applications" / DESKTOP_FILE
    template = (files("swoop") / "data" / DESKTOP_FILE).read_text()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(template.replace("Exec=swoop ", f"Exec={exec_quote(executable)} ", 1))
    written = [entry]
    themes = data_home / "icons" / "hicolor"
    for size in (files("swoop") / "ui" / "icons" / "hicolor").iterdir():
        for icon in (size / "apps").iterdir():
            target = themes / size.name / "apps" / icon.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(icon.read_bytes())
            written.append(target)
    _refresh_caches(data_home)
    return written


def open_magnets_with_swoop() -> None:
    """Make Swoop the default handler for magnet links (needs the installed entry)."""
    app = desktop_app(DESKTOP_FILE)
    if app is None:
        raise FileNotFoundError(f"{DESKTOP_FILE} is not installed")
    app.set_as_default_for_type(MAGNET_TYPE)


def desktop_app(desktop_id: str) -> Gio.DesktopAppInfo | None:
    """The installed application with this desktop file id, if any."""
    try:
        return Gio.DesktopAppInfo.new(desktop_id)
    except TypeError:  # PyGObject raises when the constructor returns NULL
        return None


def current_executable() -> Path:
    found = shutil.which("swoop")
    return Path(found) if found else Path(sys.argv[0]).resolve()


def exec_quote(path: Path) -> str:
    """Quote a path for a desktop entry Exec key (Desktop Entry Specification rules)."""
    text = str(path)
    if not _EXEC_RESERVED.intersection(text):
        return text
    escaped = "".join(f"\\{char}" if char in '"`$\\' else char for char in text)
    return f'"{escaped}"'


def _refresh_caches(data_home: Path) -> None:
    """Let launchers notice the new entry; harmless when the tools are missing."""
    for command in (
        ["update-desktop-database", str(data_home / "applications")],
        ["gtk-update-icon-cache", "--ignore-theme-index", str(data_home / "icons" / "hicolor")],
    ):
        if shutil.which(command[0]):
            subprocess.run(command, check=False, capture_output=True)  # noqa: S603
