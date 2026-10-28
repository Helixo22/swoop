"""Typed view of aria2 download status.

Converts the string-valued dictionaries returned by aria2.tellStatus into
immutable dataclasses used by the rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from swoop.aria2.rpc import Aria2Error

STATUS_KEYS = (
    "gid",
    "status",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "connections",
    "dir",
    "files",
    "errorMessage",
    "uploadSpeed",
    "seeder",
    "bittorrent",
    "followedBy",
)


class DownloadStatus(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    PAUSED = "paused"
    ERROR = "error"
    COMPLETE = "complete"
    REMOVED = "removed"


@dataclass(frozen=True)
class Download:
    gid: str
    status: DownloadStatus
    total_length: int
    completed_length: int
    download_speed: int
    connections: int
    directory: str
    paths: tuple[str, ...]
    url: str
    error_message: str
    upload_speed: int = 0
    seeder: bool = False  # a torrent that has all its data and is now uploading
    torrent_name: str = ""
    followed_by: tuple[str, ...] = ()  # e.g. a magnet's metadata, followed by the real torrent

    @classmethod
    def from_status(cls, status: Any) -> Download:
        """Build from an aria2.tellStatus result; raise Aria2Error if it is malformed."""
        try:
            return cls._parse(status)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise Aria2Error("malformed aria2.tellStatus result") from exc

    @classmethod
    def _parse(cls, status: dict[str, Any]) -> Download:
        return cls(
            gid=status["gid"],
            status=DownloadStatus(status["status"]),
            total_length=int(status.get("totalLength", 0)),
            completed_length=int(status.get("completedLength", 0)),
            download_speed=int(status.get("downloadSpeed", 0)),
            connections=int(status.get("connections", 0)),
            directory=status.get("dir", ""),
            paths=tuple(file["path"] for file in status.get("files", []) if file.get("path")),
            url=_first_uri(status.get("files", [])),
            error_message=status.get("errorMessage", ""),
            upload_speed=int(status.get("uploadSpeed", 0)),
            seeder=status.get("seeder") == "true",
            torrent_name=str(status.get("bittorrent", {}).get("info", {}).get("name", "")),
            followed_by=tuple(status.get("followedBy", [])),
        )

    @property
    def name(self) -> str:
        if self.torrent_name:
            return self.torrent_name
        return PurePosixPath(self.paths[0]).name if self.paths else ""

    @property
    def progress(self) -> float:
        return self.completed_length / self.total_length if self.total_length else 0.0


def _first_uri(files: list[dict[str, Any]]) -> str:
    uris = files[0].get("uris", []) if files else []
    return str(uris[0]["uri"]) if uris else ""
