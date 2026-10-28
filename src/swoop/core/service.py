"""Runtime composition of the Swoop backend.

Owns the aria2c process, the download manager, the history and the user's
queue limits, and publishes a snapshot of all downloads every second.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from swoop.aria2.process import Aria2Process, Aria2Settings, QueueLimits
from swoop.aria2.rpc import Aria2Error
from swoop.config import load_limits, save_limits
from swoop.core.history import History, HistoryEntry
from swoop.core.manager import DownloadManager
from swoop.core.models import Download
from swoop.paths import AppPaths

log = logging.getLogger(__name__)

REFRESH_INTERVAL = 1.0
HISTORY_LIMIT = 100


@dataclass(frozen=True)
class Snapshot:
    downloads: tuple[Download, ...]
    completed: tuple[HistoryEntry, ...]

    @property
    def download_speed(self) -> int:
        return sum(download.download_speed for download in self.downloads)


Listener = Callable[[Snapshot], None]


class SwoopService:
    """Starts and stops everything the frontends (GUI, CLI, browser) talk to."""

    def __init__(self, paths: AppPaths, allowed_root: Path | None = None) -> None:
        paths.create()
        self._config_file = paths.config_file
        self._limits = load_limits(paths.config_file)
        self._aria2 = Aria2Process(
            Aria2Settings(
                download_dir=paths.download_dir,
                session_file=paths.session_file,
                limits=self._limits,
            )
        )
        self._history = History(paths.history_db)
        self.manager = DownloadManager(
            self._aria2.client, allowed_root or Path.home(), self._history
        )
        self._listeners: list[Listener] = []
        self._refresher: asyncio.Task[None] | None = None

    @property
    def limits(self) -> QueueLimits:
        return self._limits

    async def start(self) -> None:
        await self._aria2.start()
        self._refresher = asyncio.create_task(self._refresh_periodically())

    async def stop(self) -> None:
        if self._refresher:
            self._refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresher
        await self._aria2.stop()
        self._history.close()

    async def set_limits(self, limits: QueueLimits) -> None:
        """Apply new queue limits now and remember them for the next start."""
        await self._aria2.apply_limits(limits)
        self._limits = limits
        save_limits(self._config_file, limits)

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Call listener with every new snapshot; return a function that unsubscribes."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def refresh(self) -> Snapshot:
        """Archive completed downloads, then publish and return a fresh snapshot."""
        downloads = await self.manager.list_downloads()
        snapshot = Snapshot(tuple(downloads), tuple(self._history.entries(HISTORY_LIMIT)))
        for listener in list(self._listeners):
            try:
                listener(snapshot)
            except Exception:  # a broken frontend must not stop the refresh loop
                log.exception("snapshot listener failed")
        return snapshot

    async def _refresh_periodically(self) -> None:
        while True:
            try:
                await self.refresh()
            except (Aria2Error, sqlite3.Error) as exc:
                # aria2 may be restarting after a crash or the database may be busy;
                # try again on the next tick instead of letting the task die.
                log.warning("cannot refresh downloads: %s", exc)
            await asyncio.sleep(REFRESH_INTERVAL)
