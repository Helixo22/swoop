"""Dialogs of the main window: adding a download and editing preferences."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from swoop.aria2.process import QueueLimits

_KIB = 1024


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


def present_preferences(
    parent: Gtk.Widget, limits: QueueLimits, on_change: Callable[[QueueLimits], None]
) -> None:
    concurrent = Adw.SpinRow.new_with_range(1, 16, 1)
    concurrent.set_title("Simultaneous downloads")
    concurrent.set_value(limits.max_concurrent_downloads)
    speed = Adw.SpinRow.new_with_range(0, 10_000_000, 64)
    speed.set_title("Speed limit")
    speed.set_subtitle("KiB/s for all downloads, 0 means unlimited")
    speed.set_value(limits.max_download_speed // _KIB)
    group = Adw.PreferencesGroup(title="Queue")
    group.add(concurrent)
    group.add(speed)
    page = Adw.PreferencesPage()
    page.add(group)
    dialog = Adw.PreferencesDialog()
    dialog.add(page)

    def closed(_: Adw.Dialog) -> None:
        updated = QueueLimits(
            max_concurrent_downloads=int(concurrent.get_value()),
            max_download_speed=int(speed.get_value()) * _KIB,
        )
        if updated != limits:
            on_change(updated)

    dialog.connect("closed", closed)
    dialog.present(parent)
