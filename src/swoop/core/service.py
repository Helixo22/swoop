"""Runtime composition of the Swoop backend.

Owns the aria2c process, the download manager and the history, and archives
completed downloads periodically while running.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from pathlib import Path

from swoop.aria2.process import Aria2Process, Aria2Settings
from swoop.aria2.rpc import Aria2Error
from swoop.core.history import History
from swoop.core.manager import DownloadManager
from swoop.paths import AppPaths

log = logging.getLogger(__name__)

ARCHIVE_INTERVAL = 2.0


class SwoopService:
    """Starts and stops everything the frontends (GUI, CLI, browser) talk to."""

    def __init__(self, paths: AppPaths, allowed_root: Path | None = None) -> None:
        paths.create()
        self._aria2 = Aria2Process(
            Aria2Settings(download_dir=paths.download_dir, session_file=paths.session_file)
        )
        self._history = History(paths.history_db)
        self.manager = DownloadManager(
            self._aria2.client, allowed_root or Path.home(), self._history
        )
        self._archiver: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._aria2.start()
        self._archiver = asyncio.create_task(self._archive_periodically())

    async def stop(self) -> None:
        if self._archiver:
            self._archiver.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._archiver
        await self._aria2.stop()
        self._history.close()

    async def _archive_periodically(self) -> None:
        while True:
            try:
                await self.manager.archive_completed()
            except (Aria2Error, sqlite3.Error) as exc:
                # aria2 may be restarting after a crash or the database may be busy;
                # try again on the next tick instead of letting the task die.
                log.warning("cannot archive completed downloads: %s", exc)
            await asyncio.sleep(ARCHIVE_INTERVAL)
