"""Main window: unfinished downloads with live progress, and recent completions.

The window shows a spinner until the backend is ready, then mirrors every
snapshot published by the service. Closing it hides it: downloads continue.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable

from gi.repository import Adw, Gio, GLib, Gtk

from swoop import text
from swoop.aria2.process import QueueLimits
from swoop.aria2.rpc import Aria2Error
from swoop.core.history import HistoryEntry
from swoop.core.models import Download, DownloadStatus
from swoop.core.service import Snapshot, SwoopService
from swoop.ui.dialogs import present_add_dialog, present_preferences
from swoop.ui.download_row import RUNNING, DownloadRow, completed_row, icon_button
from swoop.validation import ValidationError, validate_url

log = logging.getLogger(__name__)


class SwoopWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Swoop")
        self.set_default_size(760, 560)
        self.set_hide_on_close(True)  # downloads keep running in the background
        self._application = application
        self._service: SwoopService | None = None
        self._rows: dict[str, DownloadRow] = {}
        self._completed: tuple[HistoryEntry, ...] = ()

        self._title = Adw.WindowTitle(title="Swoop")
        add_button = icon_button("list-add-symbolic", "Add Download")
        add_button.set_action_name("win.add")
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About Swoop", "app.about")
        menu.append("Quit", "app.quit")
        header = Adw.HeaderBar(title_widget=self._title)
        header.pack_start(add_button)
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main Menu", primary=True
        )
        menu_button.update_property([Gtk.AccessibleProperty.LABEL], ["Main Menu"])
        header.pack_end(menu_button)

        self._active = Adw.PreferencesGroup(title="Downloads")
        self._finished = Adw.PreferencesGroup(title="Completed")
        self._finished_rows: list[Gtk.Widget] = []
        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=24)
        lists.set_margin_bottom(24)
        lists.append(self._active)
        lists.append(self._finished)
        clamp = Adw.Clamp(child=lists, maximum_size=900)
        for side in ("start", "end"):
            clamp.set_property(f"margin-{side}", 12)

        self._stack = Gtk.Stack()
        self._stack.add_named(
            Adw.StatusPage(title="Starting aria2…", paintable=Adw.SpinnerPaintable(widget=self)),
            "loading",
        )
        self._error = Adw.StatusPage(
            icon_name="dialog-error-symbolic", title="Swoop could not start"
        )
        self._stack.add_named(self._error, "error")
        self._stack.add_named(
            Adw.StatusPage(
                icon_name="folder-download-symbolic",
                title="No Downloads",
                description="Add a link with the + button or download from your browser",
            ),
            "empty",
        )
        self._stack.add_named(Gtk.ScrolledWindow(child=clamp, vexpand=True), "downloads")

        self._toasts = Adw.ToastOverlay(child=self._stack)
        view = Adw.ToolbarView(content=self._toasts)
        view.add_top_bar(header)
        self.set_content(view)

        self._add_action = Gio.SimpleAction(name="add", enabled=False)  # until attached
        self._add_action.connect("activate", lambda *_: self.run(self._open_add_dialog()))
        self.add_action(self._add_action)
        application.set_accels_for_action("win.add", ["<Control>n"])

    async def attach(self, service: asyncio.Task[SwoopService]) -> None:
        """Wait for the backend, then follow its snapshots."""
        try:
            self._service = await service
        except Exception as exc:
            self._error.set_description(str(exc))
            self._stack.set_visible_child_name("error")
            self.set_hide_on_close(False)  # nothing runs in the background: closing exits
            return
        self._add_action.set_enabled(True)
        unsubscribe = self._service.subscribe(self.show_snapshot)
        self.connect("destroy", lambda _: unsubscribe())
        self.run(self._service.refresh())

    def show_snapshot(self, snapshot: Snapshot) -> None:
        self._update_active(snapshot.downloads)
        if snapshot.completed != self._completed:
            self._update_completed(snapshot.completed)
        self._active.set_visible(bool(snapshot.downloads))
        self._finished.set_visible(bool(snapshot.completed))
        empty = not snapshot.downloads and not snapshot.completed
        self._stack.set_visible_child_name("empty" if empty else "downloads")
        active = sum(download.status is DownloadStatus.ACTIVE for download in snapshot.downloads)
        self._title.set_subtitle(
            f"{active} active · {text.speed(snapshot.download_speed)}" if active else ""
        )

    def present_preferences(self) -> None:
        if self._service is not None:
            present_preferences(self, self._service.limits, self._change_limits)

    def run(self, awaitable: Awaitable[object]) -> None:
        """Run an action in the background, reporting failures as a toast."""
        self._application.create_asyncio_task(self._report_failures(awaitable))

    async def _report_failures(self, awaitable: Awaitable[object]) -> None:
        try:
            await awaitable
        except (Aria2Error, ValidationError, OSError, sqlite3.Error, GLib.Error) as exc:
            log.warning("action failed: %s", exc)
            self._toasts.add_toast(Adw.Toast(title=str(exc)))

    def _update_active(self, downloads: tuple[Download, ...]) -> None:
        current = {download.gid: download for download in downloads}
        for gid in self._rows.keys() - current.keys():
            self._active.remove(self._rows.pop(gid))
        for download in downloads:
            if row := self._rows.get(download.gid):
                row.update(download)
            else:
                self._rows[download.gid] = DownloadRow(download, self._toggle, self._remove)
                self._active.add(self._rows[download.gid])

    def _update_completed(self, entries: tuple[HistoryEntry, ...]) -> None:
        for row in self._finished_rows:
            self._finished.remove(row)
        self._finished_rows = [completed_row(entry, self._open_folder) for entry in entries]
        for row in self._finished_rows:
            self._finished.add(row)
        self._completed = entries

    def _toggle(self, download: Download) -> None:
        if self._service is not None:
            manager = self._service.manager
            action = manager.pause if download.status in RUNNING else manager.resume
            self.run(self._then_refresh(action(download.gid)))

    def _remove(self, download: Download) -> None:
        if self._service is not None:
            self.run(self._then_refresh(self._service.manager.remove(download.gid)))

    def _change_limits(self, limits: QueueLimits) -> None:
        if self._service is not None:
            self.run(self._service.set_limits(limits))

    def _open_folder(self, path: str) -> None:
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(path))
        self.run(launcher.open_containing_folder(self))

    async def _open_add_dialog(self) -> None:
        present_add_dialog(self, await self._url_from_clipboard(), self._add)

    async def _url_from_clipboard(self) -> str:
        try:
            content = (await self.get_clipboard().read_text_async()) or ""
            return validate_url(content.strip())
        except (GLib.Error, ValidationError):
            return ""

    def _add(self, url: str) -> None:
        if self._service is not None:
            self.run(self._then_refresh(self._service.manager.add(url)))

    async def _then_refresh(self, action: Awaitable[object]) -> None:
        await action
        if self._service is not None:
            await self._service.refresh()
