"""Dialogs and preference rows of the main window: adding a download and preferences.

The rows built here are shared with the first-run setup guide.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from swoop.aria2.process import QueueLimits
from swoop.config import Preferences

_KIB = 1024
Run = Callable[[Awaitable[object]], None]


def present_add_dialog(parent: Gtk.Widget, initial_url: str, on_add: Callable[[str], None]) -> None:
    entry = Gtk.Entry(
        text=initial_url,
        placeholder_text="https://example.com/file.iso",
        input_purpose=Gtk.InputPurpose.URL,
        activates_default=True,
    )
    dialog = Adw.AlertDialog(heading="Add Download", extra_child=entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("add", "Add")
    dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("add")
    dialog.set_close_response("cancel")

    def update_enabled(*_: object) -> None:
        dialog.set_response_enabled("add", bool(entry.get_text().strip()))

    def respond(_: Adw.AlertDialog, response: str) -> None:
        if response == "add":
            on_add(entry.get_text().strip())

    entry.connect("changed", update_enabled)
    dialog.connect("response", respond)
    update_enabled()
    dialog.present(parent)


class LimitRows:
    """Spin rows for the number of simultaneous downloads and the speed limit."""

    def __init__(self, limits: QueueLimits) -> None:
        self.concurrent = Adw.SpinRow.new_with_range(1, 16, 1)
        self.concurrent.set_title("Simultaneous downloads")
        self.concurrent.set_value(limits.max_concurrent_downloads)
        self.speed = Adw.SpinRow.new_with_range(0, 10_000_000, 64)
        self.speed.set_title("Speed limit")
        self.speed.set_subtitle("KiB/s for all downloads, 0 means unlimited")
        self.speed.set_value(limits.max_download_speed // _KIB)

    def limits(self) -> QueueLimits:
        return QueueLimits(
            max_concurrent_downloads=int(self.concurrent.get_value()),
            max_download_speed=int(self.speed.get_value()) * _KIB,
        )


class FolderRow(Adw.ActionRow):
    """Shows the download folder and lets the user pick another one."""

    def __init__(self, folder: Path, run: Run) -> None:
        super().__init__(title="Download folder", subtitle=str(folder))
        self.folder = folder
        self._run = run
        button = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _: run(self._choose()))
        self.add_prefix(Gtk.Image(icon_name="folder-download-symbolic"))
        self.add_suffix(button)

    async def _choose(self) -> None:
        initial = Gio.File.new_for_path(str(self.folder))
        dialog = Gtk.FileDialog(title="Download Folder", initial_folder=initial)
        root = self.get_root()
        try:
            chosen = await dialog.select_folder(root if isinstance(root, Gtk.Window) else None)
        except GLib.Error:  # dismissed by the user
            return
        if chosen is not None and (path := chosen.get_path()):
            self.folder = Path(path)
            self.set_subtitle(path)


def present_preferences(
    parent: Gtk.Widget,
    preferences: Preferences,
    folder: Path,
    run: Run,
    on_change: Callable[[Preferences], None],
) -> None:
    folder_row = FolderRow(folder, run)
    limit_rows = LimitRows(preferences.limits)
    downloads = Adw.PreferencesGroup(title="Downloads")
    downloads.add(folder_row)
    queue = Adw.PreferencesGroup(title="Queue")
    queue.add(limit_rows.concurrent)
    queue.add(limit_rows.speed)
    page = Adw.PreferencesPage()
    page.add(downloads)
    page.add(queue)
    dialog = Adw.PreferencesDialog()
    dialog.add(page)

    def closed(_: Adw.Dialog) -> None:
        updated = replace(preferences, limits=limit_rows.limits(), download_dir=folder_row.folder)
        if updated != preferences:
            on_change(updated)

    dialog.connect("closed", closed)
    dialog.present(parent)
