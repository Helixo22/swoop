"""Command line entry point of Swoop.

Validates arguments locally, installs the browser host manifests, and forwards
every other command to the running Swoop instance (Gio.Application over D-Bus).
"""

from __future__ import annotations

import logging
import sys

from gi.events import GLibEventLoopPolicy

from swoop.app import SwoopApplication
from swoop.browser_integration import install_host_manifests
from swoop.commands import CommandError, build_parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    try:
        args = build_parser().parse_args(argv[1:])
    except CommandError as exc:
        print(f"swoop: {exc}", file=sys.stderr)
        return 2
    if args.command == "install-browser-host":
        for path in install_host_manifests():
            print(path)
        return 0
    # The stubs target Python 3.11, whose policy ABC still declares child watchers.
    with GLibEventLoopPolicy():  # type: ignore[abstract]
        return SwoopApplication().run(argv)
