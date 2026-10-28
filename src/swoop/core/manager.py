"""Download operations exposed to the GUI, the CLI and the browser host.

Validates every request, then delegates the actual work (segmented download,
pause, resume, removal) to aria2 through its RPC interface.
"""

from __future__ import annotations

from pathlib import Path

from swoop.aria2.rpc import Aria2Client, Aria2Error, Aria2RpcError
from swoop.core.models import STATUS_KEYS, Download
from swoop.validation import resolve_directory, validate_filename, validate_url


class DownloadManager:
    """Facade over aria2; destinations are confined to allowed_root."""

    def __init__(self, client: Aria2Client, allowed_root: Path) -> None:
        self._client = client
        self._allowed_root = allowed_root

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
