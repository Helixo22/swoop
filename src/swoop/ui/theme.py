"""Visual identity: loads Swoop's stylesheet and makes its icon available.

Both ship inside the Python package, so the logo shows even when Swoop runs
from a source checkout without being installed.
"""

from __future__ import annotations

from importlib.resources import files

from gi.repository import Gdk, Gtk

_UI = files("swoop.ui")


def install(display: Gdk.Display) -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(_UI.joinpath("style.css").read_text())
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    Gtk.IconTheme.get_for_display(display).add_search_path(str(_UI.joinpath("icons")))
