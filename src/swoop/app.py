"""Single-instance backend shared by the GUI and the headless application.

The first process becomes the primary instance and owns the backend; later
invocations (CLI, browser host) are forwarded to it over D-Bus by Gio and
executed here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from swoop.commands import build_parser  # noqa: E402
from swoop.core.service import SwoopService  # noqa: E402
from swoop.paths import APP_ID, AppPaths  # noqa: E402
from swoop.text import describe  # noqa: E402

log = logging.getLogger(__name__)

MAX_STDIN_SIZE = 64 * 1024


class Backend:
    """Runs the service for one primary instance and executes forwarded commands.

    The application is held while the backend runs, so closing the window does
    not stop downloads; quitting stops aria2 cleanly and releases it.
    """

    def __init__(self, app: Gio.Application, on_stopped: Callable[[], None] = lambda: None) -> None:
        self._app = app
        self._on_stopped = on_stopped
        self._service: asyncio.Task[SwoopService] | None = None
        self._held = False
        self._quitting = False

    @property
    def service(self) -> asyncio.Task[SwoopService]:
        assert self._service is not None, "the backend has not been started"
        return self._service

    def start(self) -> None:
        self._app.hold()
        self._held = True
        self._service = self._app.create_asyncio_task(self._start_service())

    def handle(self, command_line: Gio.ApplicationCommandLine) -> int:
        self._app.create_asyncio_task(self._run(command_line))
        return 0

    async def quit(self) -> None:
        """Stop the backend and let the application exit; later calls do nothing."""
        if self._quitting:
            return
        self._quitting = True  # set before any await: concurrent quits stop only once
        try:
            await (await self.service).stop()
        except Exception:
            log.exception("Swoop did not shut down cleanly")
        finally:
            self._on_stopped()
            self._release()

    def _release(self) -> None:
        if self._held:
            self._held = False
            self._app.release()

    async def _start_service(self) -> SwoopService:
        try:
            service = SwoopService(AppPaths.from_environment())
            await service.start()
        except Exception:
            log.exception("cannot start the Swoop backend")
            self._release()
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
        if args.command is None:
            self._app.activate()
        elif args.command == "quit":
            await self.quit()
        elif args.command == "add":
            # Headers travel on stdin because argv is visible to other users (ps).
            headers = await _read_json_stdin(command_line) if args.headers_from_stdin else None
            manager = (await self.service).manager
            gid = await manager.add(
                args.url, directory=args.dir, filename=args.out, headers=headers
            )
            self._added(gid, args.present, command_line)
        elif args.command == "add-torrent":
            manager = (await self.service).manager
            gid = await manager.add_torrent(Path(args.file), directory=args.dir)
            self._added(gid, args.present, command_line)
        elif args.command == "list":
            for download in await (await self.service).manager.list_downloads():
                command_line.print_literal(f"{download.gid}  {describe(download)}\n")

    def _added(self, gid: str, present: bool, command_line: Gio.ApplicationCommandLine) -> None:
        command_line.print_literal(f"{gid}\n")
        if present:  # opened from the desktop (magnet link, .torrent file): show the window
            self._app.activate()


class HeadlessApplication(Gio.Application):
    """Swoop without a window, used when no display is available."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._backend = Backend(self)

    def do_startup(self) -> None:
        Gio.Application.do_startup(self)
        self._backend.start()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        return self._backend.handle(command_line)

    def do_activate(self) -> None:
        """Nothing to show without a display; downloads run in the background."""


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
