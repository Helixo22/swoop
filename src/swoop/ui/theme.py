"""Visual identity: stylesheet, icon and pointer cursor on clickable widgets.

The stylesheet and the logo ship inside the Python package, so they show even
when Swoop runs from a source checkout without being installed.
"""

from __future__ import annotations

from importlib.resources import files

from gi.repository import Gdk, GObject, Gtk

_UI = files("swoop.ui")


def install(display: Gdk.Display) -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(_UI.joinpath("style.css").read_text())
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    Gtk.IconTheme.get_for_display(display).add_search_path(str(_UI.joinpath("icons")))
    _use_pointer_on_clickables()


_CLICKABLE = (Gtk.Button, Gtk.Switch, Gtk.CheckButton, Gtk.DropDown)


def _use_pointer_on_clickables() -> None:
    """Show the hand cursor over every button, switch and link, including library ones.

    GTK CSS has no cursor property, so an emission hook on "realize" sets it on
    each clickable widget as it appears.
    """
    for widget_type in _CLICKABLE:
        GObject.type_class_ref(widget_type)  # the signal must be known before hooking it

    def set_pointer(widget: Gtk.Widget, *_: object) -> bool:
        if isinstance(widget, _CLICKABLE):
            widget.set_cursor_from_name("pointer")
        return True  # keep the hook installed

    GObject.add_emission_hook(Gtk.Widget.__gtype__, "realize", set_pointer)
