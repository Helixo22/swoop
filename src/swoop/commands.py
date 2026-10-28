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
    commands.add_parser("list", help="show unfinished downloads")
    commands.add_parser("quit", help="stop the running Swoop instance")
    commands.add_parser("install-browser-host", help="register the browser extension host")
    return parser
