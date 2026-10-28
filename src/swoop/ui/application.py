"""Swoop desktop application (libadwaita).

Wraps the shared Backend: the main window opens on activation, and the
application keeps running in the background until Quit is chosen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib.metadata import version

from gi.repository import Adw, Gdk, Gio, Gtk

from swoop.app import Backend
from swoop.paths import APP_ID
from swoop.ui import theme
from swoop.ui.window import SwoopWindow

WEBSITE = "https://github.com/Helixo22/swoop"


def display_available() -> bool:
    return bool(Gtk.init_check())


class SwoopApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._backend = Backend(self, on_stopped=self._close_windows)
        self._window: SwoopWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display is not None:
            theme.install(display)
        self._backend.start()
        self._add_action(
            "quit", lambda: self.create_asyncio_task(self._backend.quit()), ["<Control>q"]
        )
        self._add_action(
            "preferences", lambda: self._present_window().present_preferences(), ["<Control>comma"]
        )
        self._add_action("setup", lambda: self._present_window().present_setup_guide())
        self._add_action("about", self._present_about)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        return self._backend.handle(command_line)

    def do_activate(self) -> None:
        self._present_window()

    def _add_action(
        self, name: str, callback: Callable[[], object], accels: Sequence[str] = ()
    ) -> None:
        action = Gio.SimpleAction(name=name)
        action.connect("activate", lambda *_: callback())
        self.add_action(action)
        self.set_accels_for_action(f"app.{name}", list(accels))

    def _present_window(self) -> SwoopWindow:
        if self._window is None:
            self._window = SwoopWindow(self)
            self.create_asyncio_task(self._window.attach(self._backend.service))
        self._window.present()
        return self._window

    def _present_about(self) -> None:
        about = Adw.AboutDialog(
            application_name="Swoop",
            application_icon=APP_ID,
            version=version("swoop"),
            comments="Download manager powered by aria2",
            website=WEBSITE,
            issue_url=f"{WEBSITE}/issues",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self._present_window())

    def _close_windows(self) -> None:
        for window in self.get_windows():
            window.destroy()
