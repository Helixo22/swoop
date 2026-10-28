"""Download operations exposed to the GUI, the CLI and the browser host.

Validates every request, then delegates the actual work (segmented download,
pause, resume, removal) to aria2 and archives completed downloads in the history.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from swoop.aria2.rpc import Aria2Client, Aria2Error, Aria2RpcError
from swoop.core.history import History
from swoop.core.models import STATUS_KEYS, Download, DownloadStatus
from swoop.validation import resolve_directory, validate_filename, validate_url

# aria2 keeps at most this many stopped results by default (--max-download-result).
_MAX_STOPPED = 1000


class DownloadManager:
    """Facade over aria2; destinations are confined to allowed_root."""

    def __init__(self, client: Aria2Client, allowed_root: Path, history: History) -> None:
        self._client = client
        self._allowed_root = allowed_root
        self._history = history

    async def add(
        self, url: str, *, directory: str | Path | None = None, filename: str | None = None
    ) -> str:
        """Queue url for download and return its aria2 GID."""
        options: dict[str, str] = {}
        if directory is not None:
            options["dir"] = str(resolve_directory(directory, self._allowed_root))
        if filename is not None:
            options["out"] = validate_filename(filename)
        gid = await self._client.call("aria2.addUri", [validate_url(url)], options)
        if not isinstance(gid, str):
            raise Aria2Error("malformed aria2.addUri result")
        return gid

    async def pause(self, gid: str) -> None:
        await self._client.call("aria2.pause", gid)

    async def resume(self, gid: str) -> None:
        await self._client.call("aria2.unpause", gid)

    async def remove(self, gid: str) -> None:
        """Stop a download if it is running and forget it once it has stopped."""
        try:
            await self._client.call("aria2.remove", gid)
        except Aria2RpcError:
            # Not active or waiting: it has already stopped, so drop its result instead.
            await self._client.call("aria2.removeDownloadResult", gid)

    async def get(self, gid: str) -> Download:
        return Download.from_status(await self._client.call("aria2.tellStatus", gid, STATUS_KEYS))

    async def archive_completed(self) -> list[Download]:
        """Move completed downloads out of aria2's results and into the history."""
        stopped = await self._client.call("aria2.tellStopped", 0, _MAX_STOPPED, STATUS_KEYS)
        if not isinstance(stopped, list):
            raise Aria2Error("malformed aria2.tellStopped result")
        completed = [
            download
            for download in map(Download.from_status, stopped)
            if download.status is DownloadStatus.COMPLETE
        ]
        for download in completed:
            self._history.record(download)
            # Recorded first: if aria2 already dropped the result there is nothing to lose.
            with contextlib.suppress(Aria2RpcError):
                await self._client.call("aria2.removeDownloadResult", download.gid)
        return completed
