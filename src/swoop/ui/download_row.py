"""List rows for unfinished and completed downloads.

A DownloadRow updates in place on every snapshot, so the list does not flicker.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gtk, Pango

from swoop import text
from swoop.core.history import HistoryEntry
from swoop.core.models import Download, DownloadStatus

DownloadAction = Callable[[Download], None]
RUNNING = frozenset({DownloadStatus.ACTIVE, DownloadStatus.WAITING})


def icon_button(icon: str, tooltip: str) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.add_css_class("circular")
    button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    return button


class DownloadRow(Gtk.ListBoxRow):
    """Title, status line, progress bar, pause/resume and remove buttons."""

    def __init__(
        self, download: Download, on_toggle: DownloadAction, on_remove: DownloadAction
    ) -> None:
        super().__init__(activatable=False)
        self._title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self._title.add_css_class("heading")
        self._status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._status.add_css_class("dim-label")
        self._status.add_css_class("caption")
        self._progress = Gtk.ProgressBar()
        self._toggle = icon_button("media-playback-pause-symbolic", "Pause")
        self._toggle.connect("clicked", lambda _: on_toggle(self.download))
        remove = icon_button("user-trash-symbolic", "Remove")
        remove.connect("clicked", lambda _: on_remove(self.download))

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        labels.append(self._title)
        labels.append(self._status)
        header = Gtk.Box(spacing=6)
        for widget in (labels, self._toggle, remove):
            header.append(widget)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("start", "end", "top", "bottom"):
            content.set_property(f"margin-{side}", 12)
        content.append(header)
        content.append(self._progress)
        self.set_child(content)
        self.download = download
        self.update(download)

    def update(self, download: Download) -> None:
        self.download = download
        self._title.set_label(text.title(download))
        self._status.set_label(text.status_text(download))
        self._progress.set_fraction(download.progress)
        running = download.status in RUNNING
        self._toggle.set_visible(download.status is not DownloadStatus.ERROR)
        self._toggle.set_icon_name(
            "media-playback-pause-symbolic" if running else "media-playback-start-symbolic"
        )
        tooltip = "Pause" if running else "Resume"
        self._toggle.set_tooltip_text(tooltip)
        self._toggle.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
        if download.status is DownloadStatus.ERROR:
            self._progress.add_css_class("error")
        else:
            self._progress.remove_css_class("error")


def completed_row(entry: HistoryEntry, on_open_folder: Callable[[str], None]) -> Adw.ActionRow:
    finished = datetime.fromtimestamp(entry.completed_at).strftime("%x %H:%M")
    row = Adw.ActionRow(
        title=entry.name or entry.url, subtitle=f"{text.size(entry.size)} · {finished}"
    )
    row.set_title_lines(1)
    row.set_tooltip_text(entry.path)
    button = icon_button("folder-open-symbolic", "Show in folder")
    button.connect("clicked", lambda _: on_open_folder(entry.path))
    row.add_suffix(button)
    return row
