"""List rows for unfinished and completed downloads.

A DownloadRow updates in place on every snapshot: its progress bar glides to
the new value, a sparkline shows the recent speed, and rows fade in and out.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gtk, Pango

from swoop import text
from swoop.core.history import HistoryEntry
from swoop.core.models import Download, DownloadStatus
from swoop.ui.speed_graph import SpeedGraph

DownloadAction = Callable[[Download], None]
RUNNING = frozenset({DownloadStatus.ACTIVE, DownloadStatus.WAITING})
PROGRESS_MS = 800
FADE_MS = 250


def icon_button(icon: str, tooltip: str) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.add_css_class("circular")
    set_label(button, tooltip)
    return button


def set_label(widget: Gtk.Widget, label: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])


def _fade(widget: Gtk.Widget, start: float, end: float) -> Adw.TimedAnimation:
    target = Adw.PropertyAnimationTarget.new(widget, "opacity")
    return Adw.TimedAnimation.new(widget, start, end, FADE_MS, target)


class DownloadRow(Gtk.ListBoxRow):
    """Title, status line, sparkline, progress bar, pause/resume and remove buttons."""

    def __init__(
        self, download: Download, on_toggle: DownloadAction, on_remove: DownloadAction
    ) -> None:
        super().__init__(activatable=False, opacity=0)
        self.add_css_class("download-row")
        self._title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self._title.add_css_class("download-title")
        self._status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._status.add_css_class("dim-label")
        self._status.add_css_class("caption")
        self._sparkline = SpeedGraph(height=28, line_width=1.6, width=88)
        self._progress = Gtk.ProgressBar()
        self._shown_fraction = download.progress
        self._fraction_from = self._fraction_to = download.progress
        target = Adw.CallbackAnimationTarget.new(self._step_progress)
        self._progress_animation = Adw.TimedAnimation.new(self, 0, 1, PROGRESS_MS, target)
        self._progress_animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._toggle = icon_button("media-playback-pause-symbolic", "Pause")
        self._toggle.connect("clicked", lambda _: on_toggle(self.download))
        self._remove = icon_button("user-trash-symbolic", "Remove")
        self._remove.add_css_class("destructive-hover")
        self._remove.connect("clicked", lambda _: on_remove(self.download))

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        labels.append(self._title)
        labels.append(self._status)
        header = Gtk.Box(spacing=8)
        for widget in (labels, self._sparkline, self._toggle, self._remove):
            header.append(widget)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("start", "end"):
            content.set_property(f"margin-{side}", 16)
        for side in ("top", "bottom"):
            content.set_property(f"margin-{side}", 14)
        content.append(header)
        content.append(self._progress)
        self.set_child(content)
        self.download = download
        self.update(download)
        self._progress.set_fraction(download.progress)
        _fade(self, 0, 1).play()

    def update(self, download: Download) -> None:
        self.download = download
        title = text.title(download)
        self._title.set_label(title)
        self._status.set_label(text.status_text(download))
        self._glide_to(download.progress)
        active = download.status is DownloadStatus.ACTIVE
        self._sparkline.set_visible(active)
        if active:
            self._sparkline.push(download.download_speed)
        running = download.status in RUNNING
        self._toggle.set_visible(download.status is not DownloadStatus.ERROR)
        self._toggle.set_icon_name(
            "media-playback-pause-symbolic" if running else "media-playback-start-symbolic"
        )
        action = "Pause" if running else "Resume"
        self._toggle.set_tooltip_text(action)
        set_label(self._toggle, f"{action} {title}")
        set_label(self._remove, f"Remove {title}")
        for css_class, on in (
            ("error", download.status is DownloadStatus.ERROR),
            ("paused", download.status is DownloadStatus.PAUSED),
        ):
            if on:
                self._progress.add_css_class(css_class)
            else:
                self._progress.remove_css_class(css_class)

    def dismiss(self, then: Callable[[], None]) -> None:
        """Fade out, then call then (typically removing the row from its list)."""
        animation = _fade(self, self.get_opacity(), 0)
        animation.connect("done", lambda _: then())
        animation.play()

    def _glide_to(self, fraction: float) -> None:
        if fraction == self._fraction_to:
            return
        self._fraction_from, self._fraction_to = self._shown_fraction, fraction
        self._progress_animation.reset()
        self._progress_animation.play()

    def _step_progress(self, value: float) -> None:
        span = self._fraction_to - self._fraction_from
        self._shown_fraction = self._fraction_from + span * value
        self._progress.set_fraction(self._shown_fraction)


def completed_row(entry: HistoryEntry, on_open_folder: Callable[[str], None]) -> Adw.ActionRow:
    finished = datetime.fromtimestamp(entry.completed_at).strftime("%x %H:%M")
    title = entry.name or entry.url
    row = Adw.ActionRow(title=title, subtitle=f"{text.size(entry.size)} · {finished}")
    row.set_title_lines(1)
    row.set_tooltip_text(entry.path)
    done = Gtk.Image(icon_name="object-select-symbolic")
    done.add_css_class("success")
    row.add_prefix(done)
    button = icon_button("folder-open-symbolic", "Show in folder")
    set_label(button, f"Show {title} in folder")
    button.connect("clicked", lambda _: on_open_folder(entry.path))
    row.add_suffix(button)
    return row
