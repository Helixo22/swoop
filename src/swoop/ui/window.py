"""Main window: unfinished downloads with live progress, and recent completions.

The window shows a spinner until the backend is ready, then mirrors every
snapshot published by the service, with an animated speed graph, and opens the
setup guide on first run. Closing it hides it: downloads continue.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import sqlite3
from collections.abc import Awaitable

from gi.repository import Adw, Gio, GLib, Gtk

from swoop.aria2.rpc import Aria2Error
from swoop.browser_integration import install_host_manifests, installed_browsers
from swoop.config import Preferences
from swoop.core.history import HistoryEntry
from swoop.core.models import Download, DownloadStatus
from swoop.core.service import Snapshot, SwoopService
from swoop.paths import APP_ID
from swoop.ui.dialogs import present_add_dialog, present_preferences
from swoop.ui.download_row import RUNNING, DownloadRow, completed_row, set_label
from swoop.ui.setup_guide import SetupChoices, SetupGuide
from swoop.ui.speed_graph import SpeedGraph, SpeedLabel
from swoop.validation import ValidationError, validate_url

log = logging.getLogger(__name__)


class SwoopWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Swoop", icon_name=APP_ID)
        self.set_default_size(780, 680)
        self.add_css_class("swoop")
        self.set_hide_on_close(True)  # downloads keep running in the background
        self._application = application
        self._service: SwoopService | None = None
        self._rows: dict[str, DownloadRow] = {}
        self._completed: tuple[HistoryEntry, ...] = ()

        add_button = Gtk.Button(
            child=Adw.ButtonContent(icon_name="list-add-symbolic", label="Add"),
            tooltip_text="Add Download (Ctrl+N)",
            action_name="win.add",
        )
        add_button.add_css_class("swoop-accent")
        add_button.add_css_class("swoop-add")
        set_label(add_button, "Add Download")
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Setup Guide", "app.setup")
        menu.append("About Swoop", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main Menu", primary=True
        )
        set_label(menu_button, "Main Menu")
        header = Adw.HeaderBar(title_widget=Adw.WindowTitle())
        header.pack_start(add_button)
        header.pack_end(menu_button)

        self._tagline = Gtk.Label(xalign=0)
        self._tagline.add_css_class("swoop-tagline")
        self._speed = SpeedLabel()
        self._speed.add_css_class("title-1")
        self._graph = SpeedGraph(height=96)
        self._active = Adw.PreferencesGroup(title="Downloads")
        self._finished = Adw.PreferencesGroup(title="Completed")
        self._finished_rows: list[Gtk.Widget] = []
        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        for widget in (self._hero(), self._speed_card(), self._active, self._finished):
            lists.append(widget)
        for side in ("top", "bottom"):
            lists.set_property(f"margin-{side}", 12)
        clamp = Adw.Clamp(child=lists, maximum_size=820)
        for side in ("start", "end"):
            clamp.set_property(f"margin-{side}", 16)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
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
                icon_name=APP_ID,
                title="No Downloads",
                description="Add a link with the Add button or download from your browser",
            ),
            "empty",
        )
        self._stack.add_named(Gtk.ScrolledWindow(child=clamp, vexpand=True), "downloads")

        self._toasts = Adw.ToastOverlay(child=self._stack)
        view = Adw.ToolbarView(content=self._toasts, top_bar_style=Adw.ToolbarStyle.FLAT)
        view.add_top_bar(header)
        self.set_content(view)

        self._add_action = Gio.SimpleAction(name="add", enabled=False)  # until attached
        self._add_action.connect("activate", lambda *_: self.run(self._open_add_dialog()))
        self.add_action(self._add_action)
        application.set_accels_for_action("win.add", ["<Control>n"])

    def _hero(self) -> Gtk.Widget:
        logo = Gtk.Image(icon_name=APP_ID, pixel_size=64)
        logo.add_css_class("swoop-logo")
        wordmark = Gtk.Label(label="Swoop", xalign=0)
        wordmark.add_css_class("swoop-wordmark")
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        names.append(wordmark)
        names.append(self._tagline)
        hero = Gtk.Box(spacing=16)
        hero.add_css_class("swoop-hero")
        hero.append(logo)
        hero.append(names)
        return hero

    def _speed_card(self) -> Gtk.Widget:
        caption = Gtk.Label(label="Download speed", xalign=0)
        caption.add_css_class("caption-heading")
        caption.add_css_class("dim-label")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("card")
        card.add_css_class("swoop-speed-card")
        card.set_overflow(Gtk.Overflow.HIDDEN)  # clip the graph to the rounded corners
        for widget in (caption, self._speed, self._graph):
            card.append(widget)
        return card

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
        if not self._service.preferences.setup_done:
            self.present_setup_guide()

    def show_snapshot(self, snapshot: Snapshot) -> None:
        self._update_active(snapshot.downloads)
        if snapshot.completed != self._completed:
            self._update_completed(snapshot.completed)
        self._active.set_visible(bool(snapshot.downloads))
        self._finished.set_visible(bool(snapshot.completed))
        empty = not snapshot.downloads and not snapshot.completed
        self._stack.set_visible_child_name("empty" if empty else "downloads")
        active = sum(download.status is DownloadStatus.ACTIVE for download in snapshot.downloads)
        self._tagline.set_label(f"{active} downloading" if active else "Ready when you are")
        self._speed.set_speed(snapshot.download_speed)
        self._graph.push(snapshot.download_speed)

    def present_preferences(self) -> None:
        if self._service is not None:
            service = self._service
            present_preferences(
                self, service.preferences, service.download_dir, self.run, self._change_preferences
            )

    def present_setup_guide(self) -> None:
        if self._service is not None:
            SetupGuide(
                download_dir=self._service.download_dir,
                limits=self._service.preferences.limits,
                browsers=installed_browsers(),
                run=self.run,
                on_finish=lambda choices: self.run(self._apply_setup(choices)),
            ).present(self)

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
            leaving = self._rows.pop(gid)
            leaving.dismiss(functools.partial(self._active.remove, leaving))
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

    def _change_preferences(self, preferences: Preferences) -> None:
        if self._service is not None:
            self.run(self._service.update_preferences(preferences))

    async def _apply_setup(self, choices: SetupChoices) -> None:
        assert self._service is not None
        await self._service.update_preferences(
            Preferences(choices.limits, choices.download_dir, setup_done=True)
        )
        if choices.connect_browsers:
            install_host_manifests()
        self._toasts.add_toast(Adw.Toast(title="Swoop is ready"))

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
