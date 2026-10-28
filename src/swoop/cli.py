"""Command line entry point of Swoop.

Validates arguments locally, runs the setup commands (browser host and extension,
launcher entry) in place, and forwards every other command to the primary Swoop
instance over D-Bus (Gio.Application), starting it first if needed.
"""

from __future__ import annotations

import logging
import sys

from gi.events import GLibEventLoopPolicy
from gi.repository import Gio

from swoop.app import HeadlessApplication
from swoop.browser_integration import export_extension, install_host_manifests
from swoop.commands import CommandError, build_parser
from swoop.desktop import current_executable, install_desktop_entry
from swoop.paths import AppPaths


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per RPC call
    try:
        args = build_parser().parse_args(argv[1:])
    except CommandError as exc:
        print(f"swoop: {exc}", file=sys.stderr)
        return 2
    if args.command == "open":
        argv = [argv[0], *(_open_command(args.target) if args.target else [])]
    if args.command in _LOCAL_COMMANDS:
        try:
            return _LOCAL_COMMANDS[args.command]()
        except OSError as exc:
            print(f"swoop: {exc}", file=sys.stderr)
            return 1
    # The stubs target Python 3.11, whose policy ABC still declares child watchers.
    with GLibEventLoopPolicy():  # type: ignore[abstract]
        return int(_application().run(argv))


def _application() -> Gio.Application:
    """The GUI when GTK 4, libadwaita and a display are available, else headless."""
    try:
        from swoop.ui.application import SwoopApplication, display_available
    except (ImportError, ValueError):  # ValueError: typelib missing for the required version
        return HeadlessApplication()
    return SwoopApplication() if display_available() else HeadlessApplication()


def _open_command(target: str) -> list[str]:
    """Turn a desktop "open" (link, magnet, file:// URI or path) into an add command.

    Local paths are made absolute here, because the running instance may have
    another working directory.
    """
    path = Gio.File.new_for_commandline_arg(target)
    if path.is_native() and (local := path.get_path()):
        return ["add-torrent", "--present", "--", local]
    return ["add", "--present", "--", target]


def _setup_browsers() -> int:
    build = export_extension(AppPaths.from_environment().data_dir / "browser-extension")
    for path in (*install_host_manifests(), build.firefox_package, build.chromium_dir):
        print(path)
    return 0


def _install_desktop() -> int:
    data_home = AppPaths.from_environment().data_dir.parent
    for path in install_desktop_entry(data_home, current_executable()):
        print(path)
    return 0


# Commands that run in this process instead of being forwarded to the running instance.
_LOCAL_COMMANDS = {"setup-browsers": _setup_browsers, "install-desktop": _install_desktop}
