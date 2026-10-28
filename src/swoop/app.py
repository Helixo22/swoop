"""Swoop single-instance application.

The first process becomes the primary instance and owns the backend; later
invocations (CLI, browser host) are forwarded to it over D-Bus by Gio.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from swoop.commands import build_parser  # noqa: E402
from swoop.core.service import SwoopService  # noqa: E402
from swoop.paths import APP_ID, AppPaths  # noqa: E402

log = logging.getLogger(__name__)


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
            gid = await service.manager.add(args.url, directory=args.dir, filename=args.out)
            command_line.print_literal(f"{gid}\n")
        elif args.command == "quit":
            try:
                await service.stop()
            finally:
                self.release()  # exit even if the shutdown failed
