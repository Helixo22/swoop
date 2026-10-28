"""SQLite history of completed downloads.

Only finished downloads are stored here; the pending queue is persisted by
aria2 itself through its session file.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from swoop.core.models import Download

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    gid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    completed_at REAL NOT NULL
)
"""


@dataclass(frozen=True)
class HistoryEntry:
    gid: str
    name: str
    url: str
    path: str
    size: int
    completed_at: float


class History:
    """Append-only store of completed downloads, newest first when listed."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(_SCHEMA)

    def record(self, download: Download) -> None:
        """Store a completed download; recording the same GID twice is a no-op."""
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO history VALUES (?, ?, ?, ?, ?, ?)",
                (
                    download.gid,
                    download.name,
                    download.url,
                    download.paths[0] if download.paths else download.directory,
                    download.total_length,
                    time.time(),
                ),
            )

    def entries(self, limit: int = 500) -> list[HistoryEntry]:
        rows = self._db.execute(
            "SELECT gid, name, url, path, size, completed_at FROM history"
            " ORDER BY completed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [HistoryEntry(*row) for row in rows]

    def close(self) -> None:
        self._db.close()
