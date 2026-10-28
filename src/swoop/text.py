"""Human-readable descriptions of downloads for the GUI and the CLI.

Sizes and speeds use GLib's locale-aware formatting.
"""

from __future__ import annotations

from gi.repository import GLib

from swoop.core.models import Download, DownloadStatus


def size(value: int) -> str:
    return str(GLib.format_size(value))


def speed(value: int) -> str:
    return f"{size(value)}/s"


def remaining_time(remaining: int, bytes_per_second: int) -> str:
    if bytes_per_second <= 0 or remaining <= 0:
        return ""
    seconds = remaining // bytes_per_second
    if seconds < 60:
        return f"{seconds} s left"
    if seconds < 3600:
        return f"{seconds // 60} min left"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min left"


def title(download: Download) -> str:
    if download.name.startswith("[METADATA]"):  # aria2's name for a magnet's metadata
        return "Fetching torrent metadata…"
    return download.name or download.url or download.gid


def progress(download: Download) -> str:
    done = size(download.completed_length)
    return f"{done} of {size(download.total_length)}" if download.total_length else done


def status_text(download: Download) -> str:
    """One line describing the state of an unfinished download."""
    match download.status:
        case DownloadStatus.ACTIVE if download.seeder:
            return f"Seeding · ↑ {speed(download.upload_speed)}"
        case DownloadStatus.ACTIVE:
            remaining = download.total_length - download.completed_length
            eta = remaining_time(remaining, download.download_speed)
            parts = [progress(download), speed(download.download_speed), eta]
            return " · ".join(part for part in parts if part)
        case DownloadStatus.WAITING:
            return "Queued"
        case DownloadStatus.PAUSED:
            return f"Paused · {progress(download)}"
        case DownloadStatus.ERROR:
            return f"Failed: {download.error_message or 'unknown error'}"
        case _:
            return download.status.value.capitalize()


def describe(download: Download) -> str:
    return f"{title(download)} — {status_text(download)}"
