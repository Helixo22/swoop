"""First-run setup guide.

"Set Up Automatically" applies the recommended setup in one click: system
download folder, default queue limits, browser host registration, launcher
entry with icon and magnet links. "Customize" walks through the same choices.
Both end on a page that installs the browser extension in each browser.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Adw, Gtk

from swoop.aria2.process import QueueLimits
from swoop.browser_integration import Browser, has_signed_firefox_package
from swoop.paths import APP_ID
from swoop.ui.dialogs import FolderRow, LimitRows, Run

EXTENSION_HELP = "https://github.com/Helixo22/swoop#browser-extension"


@dataclass(frozen=True)
class SetupChoices:
    download_dir: Path
    limits: QueueLimits
    connect_browsers: bool
    desktop_integration: bool


def _pill(label: str, *, accent: bool = False) -> Gtk.Button:
    button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    if accent:
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


def _extension_hint(browser: Browser, signed: bool) -> str:
    if browser.sandboxed:
        return "Flatpak keeps this browser in a sandbox that cannot start Swoop; use a native build"
    if browser.firefox and signed:
        return f"{browser.name} asks you to confirm the add-on"
    if browser.firefox:
        return "Choose Load Temporary Add-on and pick manifest.json in the folder Swoop opens"
    return "Turn on Developer mode, choose Load unpacked and pick the folder Swoop opens"


class SetupGuide(Adw.Dialog):
    def __init__(
        self,
        *,
        download_dir: Path,
        limits: QueueLimits,
        browsers: list[Browser],
        desktop_integration: bool,
        run: Run,
        on_finish: Callable[[SetupChoices], None],
        on_install_extension: Callable[[Browser], None],
    ) -> None:
        super().__init__(title="Welcome to Swoop", content_width=500, content_height=620)
        self.set_can_close(False)  # finished through the guide's own buttons
        self.add_css_class("swoop-guide")
        self._recommended = SetupChoices(
            download_dir,
            limits,
            connect_browsers=bool(browsers),
            desktop_integration=desktop_integration,
        )
        self._browsers = browsers
        self._on_finish = on_finish
        self._on_install_extension = on_install_extension
        self._folder = FolderRow(download_dir, run)
        self._limits = LimitRows(limits)
        self._connect = Adw.SwitchRow(
            title="Connect my browsers",
            subtitle="Hand browser downloads over to Swoop",
            active=bool(browsers),
            sensitive=bool(browsers),
        )
        self._desktop = Adw.SwitchRow(
            title="Add to the app launcher",
            subtitle="Show Swoop with its icon and open magnet links with it",
            active=desktop_integration,
            visible=desktop_integration,
        )
        self._navigation = Adw.NavigationView()
        self._navigation.add(self._welcome_page())
        self.set_child(self._navigation)
        self._pages = [self._folder_page(), self._queue_page(), self._integration_page()]

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
        automatic = _pill("Set Up Automatically", accent=True)
        automatic.set_margin_top(18)
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
        page = Adw.ToolbarView(content=box)
        page.add_top_bar(Adw.HeaderBar(show_title=False, show_end_title_buttons=False))
        return Adw.NavigationPage(title="Welcome", child=page)

    def _next_button(self, index: int) -> Gtk.Button:
        button = _pill("Continue", accent=True)
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

    def _integration_page(self) -> Adw.NavigationPage:
        detected = Adw.PreferencesGroup(title="Detected browsers")
        names = [browser.name for browser in self._browsers] or ["No supported browser found"]
        for name in names:
            row = Adw.ActionRow(title=name)
            row.add_prefix(Gtk.Image(icon_name="web-browser-symbolic"))
            detected.add(row)
        switches = Adw.PreferencesGroup()
        switches.add(self._connect)
        switches.add(self._desktop)
        description = "Swoop can take over downloads from your browser and your desktop."
        content = _group_page("Integration", description, detected, switches)
        finish = _pill("Continue", accent=True)
        finish.connect("clicked", lambda _: self._finish(self._customized()))
        return _page("Integration", content, finish)

    def _extension_page(self) -> Adw.NavigationPage:
        group = Adw.PreferencesGroup()
        for browser in self._browsers:
            hint = _extension_hint(browser, has_signed_firefox_package())
            row = Adw.ActionRow(title=browser.name, subtitle=hint, subtitle_lines=2)
            row.add_prefix(Gtk.Image(icon_name="web-browser-symbolic"))
            if not browser.sandboxed:
                install = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
                install.add_css_class("swoop-accent")
                install.connect("clicked", lambda _, b=browser: self._on_install_extension(b))
                row.add_suffix(install)
            group.add(row)
        help_group = Adw.PreferencesGroup()
        help_group.add(Gtk.LinkButton(uri=EXTENSION_HELP, label="More about the extension"))
        content = _group_page(
            "Extension",
            "Last step: add the Swoop extension, so downloads you start in the browser "
            "arrive in Swoop.",
            group,
            help_group,
        )
        done = _pill("Done", accent=True)
        done.connect("clicked", lambda _: self.force_close())
        page = _page("Install the Extension", content, done)
        page.set_can_pop(False)  # the setup has been applied already
        return page

    def _customized(self) -> SetupChoices:
        return SetupChoices(
            self._folder.folder,
            self._limits.limits(),
            connect_browsers=self._connect.get_active(),
            desktop_integration=self._desktop.get_active(),
        )

    def _finish(self, choices: SetupChoices) -> None:
        self._on_finish(choices)
        if choices.connect_browsers and self._browsers:
            self._navigation.push(self._extension_page())
        else:
            self.force_close()
