"""Download operations exposed to the GUI, the CLI and the browser host.

Validates every request, then delegates the actual work (segmented download,
pause, resume, removal) to aria2 and archives completed downloads in the history.
"""

from __future__ import annotations

import base64
import contextlib
from pathlib import Path

from swoop.aria2.rpc import Aria2Client, Aria2Error, Aria2RpcError
from swoop.core.history import History
from swoop.core.models import STATUS_KEYS, Download, DownloadStatus
from swoop.validation import (
    read_torrent_file,
    resolve_directory,
    validate_download_uri,
    validate_filename,
    validate_headers,
)

# aria2 keeps at most this many stopped results by default (--max-download-result).
_MAX_RESULTS = 1000
_FINISHED = frozenset({DownloadStatus.COMPLETE, DownloadStatus.REMOVED})


class DownloadManager:
    """Facade over aria2; destinations are confined to allowed_root."""

    def __init__(self, client: Aria2Client, allowed_root: Path, history: History) -> None:
        self._client = client
        self._allowed_root = allowed_root
        self._history = history

    async def add(
        self,
        url: str,
        *,
        directory: str | Path | None = None,
        filename: str | None = None,
        headers: object = None,
    ) -> str:
        """Queue a URL or magnet link for download and return its aria2 GID.

        headers (Cookie, Referer, User-Agent) apply to this download only.
        """
        options = self._options(directory)
        if filename is not None:
            options["out"] = validate_filename(filename)
        if headers is not None:
            options["header"] = validate_headers(headers)
        uri = validate_download_uri(url)
        return _gid(await self._client.call("aria2.addUri", [uri], options), "aria2.addUri")

    async def add_torrent(self, path: Path, *, directory: str | Path | None = None) -> str:
        """Queue the torrent described by the .torrent file at path."""
        content = base64.b64encode(read_torrent_file(path)).decode()
        result = await self._client.call("aria2.addTorrent", content, [], self._options(directory))
        return _gid(result, "aria2.addTorrent")

    def _options(self, directory: str | Path | None) -> dict[str, str | list[str]]:
        if directory is None:
            return {}
        return {"dir": str(resolve_directory(directory, self._allowed_root))}

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

    async def list_downloads(self) -> list[Download]:
        """Archive completed downloads, then return the rest: active, waiting and failed."""
        results = await self._client.multicall(
            [
                ("aria2.tellActive", [STATUS_KEYS]),
                ("aria2.tellWaiting", [0, _MAX_RESULTS, STATUS_KEYS]),
                ("aria2.tellStopped", [0, _MAX_RESULTS, STATUS_KEYS]),
            ]
        )
        if not all(isinstance(result, list) for result in results):
            raise Aria2Error("malformed aria2 download list")
        downloads = [Download.from_status(status) for result in results for status in result]
        for download in downloads:
            # A result followed by another download (magnet metadata, a fetched .torrent)
            # is only a preparation step, not something the user downloaded.
            if download.status is DownloadStatus.COMPLETE and not download.followed_by:
                # Recorded first: if aria2 already dropped the result there is nothing to lose.
                self._history.record(download)
            if download.status in _FINISHED:
                await self._forget(download.gid)
        return [download for download in downloads if download.status not in _FINISHED]

    async def _forget(self, gid: str) -> None:
        """Drop a finished result so aria2 does not report it again."""
        with contextlib.suppress(Aria2RpcError):  # already dropped, e.g. by a concurrent refresh
            await self._client.call("aria2.removeDownloadResult", gid)


def _gid(result: object, method: str) -> str:
    if not isinstance(result, str):
        raise Aria2Error(f"malformed {method} result")
    return result
