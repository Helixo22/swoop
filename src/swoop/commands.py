"""Command grammar shared by the CLI and the primary instance.

The CLI validates arguments before forwarding them; the primary instance parses
the forwarded arguments again with the same parser.
"""

from __future__ import annotations

import argparse
from typing import NoReturn


class CommandError(Exception):
    """Invalid command line."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # Raise instead of exiting: the primary instance parses forwarded commands too.
        raise CommandError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="swoop", description="Download manager powered by aria2.")
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("add", help="queue a download")
    add.add_argument("url")
    add.add_argument("--dir", help="destination directory (relative paths start at home)")
    add.add_argument("--out", help="output file name")
    add.add_argument(
        "--headers-from-stdin",
        action="store_true",
        help="read request headers (JSON object: Cookie, Referer, User-Agent) from stdin",
    )
    add.add_argument("--present", action="store_true", help=argparse.SUPPRESS)
    torrent = commands.add_parser("add-torrent", help="queue the torrent in a .torrent file")
    torrent.add_argument("file")
    torrent.add_argument("--dir", help="destination directory (relative paths start at home)")
    torrent.add_argument("--present", action="store_true", help=argparse.SUPPRESS)
    opener = commands.add_parser("open", help="open a link, magnet or .torrent file")
    opener.add_argument("target")
    commands.add_parser("list", help="show unfinished downloads")
    commands.add_parser("quit", help="stop the running Swoop instance")
    commands.add_parser(
        "setup-browsers", help="register the browser host and export the browser extension"
    )
    commands.add_parser("install-desktop", help="add Swoop and its icon to the app launcher")
    return parser
