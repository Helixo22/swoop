"""First-run setup guide.

One click applies the recommended setup (system download folder, default queue
limits, browser integration for every installed browser); "Customize" walks
through the same choices page by page.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Adw, Gtk

from swoop.aria2.process import QueueLimits
from swoop.paths import APP_ID
from swoop.ui.dialogs import FolderRow, LimitRows, Run

EXTENSION_HELP = "https://github.com/Helixo22/swoop#browser-extension"


@dataclass(frozen=True)
class SetupChoices:
    download_dir: Path
    limits: QueueLimits
    connect_browsers: bool


def _pill(label: str, *, suggested: bool = False) -> Gtk.Button:
    button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    if suggested:
        button.add_css_class("swoop-accent")
    return button


def _page(title: str, content: Gtk.Widget, action: Gtk.Button) -> Adw.NavigationPage:
    bottom = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=18)
    bottom.append(action)
    view = Adw.ToolbarView(content=content)
    view.add_top_bar(Adw.HeaderBar(show_title=False, show_end_title_buttons=False))
    view.add_bottom_bar(bottom)
    return Adw.NavigationPage(title=title, child=view)


def _group_page(title: str, description: str, *groups: Adw.PreferencesGroup) -> Adw.PreferencesPage:
    page = Adw.PreferencesPage(title=title, description=description)
    for group in groups:
        page.add(group)
    return page


class SetupGuide(Adw.Dialog):
    def __init__(
        self,
        *,
        download_dir: Path,
        limits: QueueLimits,
        browsers: list[str],
        run: Run,
        on_finish: Callable[[SetupChoices], None],
    ) -> None:
        super().__init__(title="Welcome to Swoop", content_width=480, content_height=600)
        self.set_can_close(False)  # finished through one of the two buttons
        self.add_css_class("swoop-guide")
        self._recommended = SetupChoices(download_dir, limits, connect_browsers=bool(browsers))
        self._on_finish = on_finish
        self._folder = FolderRow(download_dir, run)
        self._limits = LimitRows(limits)
        self._browsers = Adw.SwitchRow(
            title="Connect my browsers",
            subtitle="Hand browser downloads over to Swoop",
            active=bool(browsers),
            sensitive=bool(browsers),
        )
        self._navigation = Adw.NavigationView()
        self._navigation.add(self._welcome_page())
        self.set_child(self._navigation)
        self._pages = [self._folder_page(), self._queue_page(), self._browser_page(browsers)]

    def _welcome_page(self) -> Adw.NavigationPage:
        logo = Gtk.Image(icon_name=APP_ID, pixel_size=128)
        logo.add_css_class("swoop-logo")
        title = Gtk.Label(label="Welcome to Swoop", wrap=True)
        title.add_css_class("title-1")
        body = Gtk.Label(
            label="Fast downloads powered by aria2. Swoop can set itself up for you "
            "with the recommended settings, or you can choose them yourself.",
            wrap=True,
            justify=Gtk.Justification.CENTER,
            max_width_chars=40,
        )
        body.add_css_class("dim-label")
        automatic = _pill("Set Up Automatically", suggested=True)
        automatic.connect("clicked", lambda _: self._finish(self._recommended))
        customize = Gtk.Button(label="Customize…", halign=Gtk.Align.CENTER)
        customize.add_css_class("flat")
        customize.connect("clicked", lambda _: self._navigation.push(self._pages[0]))
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            valign=Gtk.Align.CENTER,
            margin_start=24,
            margin_end=24,
        )
        for widget in (logo, title, body, automatic, customize):
            box.append(widget)
        automatic.set_margin_top(18)
        page = Adw.ToolbarView(content=box)
        page.add_top_bar(Adw.HeaderBar(show_title=False, show_end_title_buttons=False))
        return Adw.NavigationPage(title="Welcome", child=page)

    def _next_button(self, index: int) -> Gtk.Button:
        button = _pill("Continue", suggested=True)
        button.connect("clicked", lambda _: self._navigation.push(self._pages[index]))
        return button

    def _folder_page(self) -> Adw.NavigationPage:
        group = Adw.PreferencesGroup()
        group.add(self._folder)
        content = _group_page("Downloads", "Where should Swoop save your files?", group)
        return _page("Download Folder", content, self._next_button(1))

    def _queue_page(self) -> Adw.NavigationPage:
        group = Adw.PreferencesGroup()
        group.add(self._limits.concurrent)
        group.add(self._limits.speed)
        description = "aria2 splits each download over several connections."
        content = _group_page("Speed", description, group)
        return _page("Speed", content, self._next_button(2))

    def _browser_page(self, browsers: list[str]) -> Adw.NavigationPage:
        detected = Adw.PreferencesGroup(title="Detected browsers")
        for name in browsers or ["No supported browser found"]:
            row = Adw.ActionRow(title=name)
            row.add_prefix(Gtk.Image(icon_name="web-browser-symbolic"))
            detected.add(row)
        connect = Adw.PreferencesGroup()
        connect.add(self._browsers)
        extension = Adw.PreferencesGroup(
            description="Then add the Swoop extension to your browser: it needs to be "
            "installed once by hand until it is published in the add-on stores."
        )
        extension.add(Gtk.LinkButton(uri=EXTENSION_HELP, label="How to install the extension"))
        content = _group_page(
            "Browsers",
            "Swoop can take over downloads from your browser.",
            detected,
            connect,
            extension,
        )
        finish = _pill("Finish Setup", suggested=True)
        finish.connect("clicked", lambda _: self._finish(self._customized()))
        return _page("Browsers", content, finish)

    def _customized(self) -> SetupChoices:
        return SetupChoices(self._folder.folder, self._limits.limits(), self._browsers.get_active())

    def _finish(self, choices: SetupChoices) -> None:
        self._on_finish(choices)
        self.force_close()
