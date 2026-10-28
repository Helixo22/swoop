"""Swoop single-instance application.

The first process becomes the primary instance and owns the backend; later
invocations (CLI, browser host) are forwarded to it over D-Bus by Gio.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from swoop.commands import build_parser  # noqa: E402
from swoop.core.service import SwoopService  # noqa: E402
from swoop.paths import APP_ID, AppPaths  # noqa: E402

log = logging.getLogger(__name__)

MAX_STDIN_SIZE = 64 * 1024


class SwoopApplication(Gio.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._service: asyncio.Task[SwoopService] | None = None
        self._quitting = False

    def do_startup(self) -> None:
        Gio.Application.do_startup(self)
        self.hold()  # headless backend: stay alive until "swoop quit"
        self._service = self.create_asyncio_task(self._start_service())

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        self.create_asyncio_task(self._run(command_line))
        return 0

    async def _start_service(self) -> SwoopService:
        try:
            service = SwoopService(AppPaths.from_environment())
            await service.start()
        except Exception:
            log.exception("cannot start the Swoop backend")
            self.release()
            raise
        return service

    async def _run(self, command_line: Gio.ApplicationCommandLine) -> None:
        try:
            args = build_parser().parse_args(command_line.get_arguments()[1:])
            await self._execute(args, command_line)
        except SystemExit:
            # argparse exits on --help; a forwarded command must never end the primary.
            command_line.set_exit_status(2)
        except Exception as exc:  # boundary: every failure is reported to the caller
            command_line.printerr_literal(f"swoop: {exc}\n")
            command_line.set_exit_status(1)
        finally:
            command_line.done()

    async def _execute(
        self, args: argparse.Namespace, command_line: Gio.ApplicationCommandLine
    ) -> None:
        if self._quitting:
            raise RuntimeError("Swoop is shutting down")
        # Set before any await so that concurrent quits cannot stop and release twice.
        self._quitting = args.command == "quit"
        assert self._service is not None
        service = await self._service
        if args.command == "add":
            # Headers travel on stdin because argv is visible to other users (ps).
            headers = await _read_json_stdin(command_line) if args.headers_from_stdin else None
            gid = await service.manager.add(
                args.url, directory=args.dir, filename=args.out, headers=headers
            )
            command_line.print_literal(f"{gid}\n")
        elif args.command == "quit":
            try:
                await service.stop()
            finally:
                self.release()  # exit even if the shutdown failed


async def _read_json_stdin(command_line: Gio.ApplicationCommandLine) -> object:
    """Read the caller's stdin (forwarded over D-Bus for remote callers) as JSON."""
    stream = command_line.get_stdin()
    if stream is None:
        raise ValueError("no standard input to read headers from")
    data = bytearray()
    while chunk := (
        await stream.read_bytes_async(MAX_STDIN_SIZE, GLib.PRIORITY_DEFAULT)
    ).get_data():
        data += chunk
        if len(data) > MAX_STDIN_SIZE:
            raise ValueError("standard input is too large")
    try:
        return json.loads(data)
    except ValueError as exc:
        raise ValueError("standard input is not valid JSON") from exc
