"""Validation of untrusted input before it reaches aria2.

Checks download URLs, output file names and destination directories so that
only supported schemes are accepted and nothing escapes the allowed root.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https", "ftp", "sftp"})
MAX_URL_LENGTH = 8192
MAX_FILENAME_BYTES = 255


class ValidationError(ValueError):
    """Input rejected because it is malformed or unsafe."""


def validate_url(url: str) -> str:
    """Return url unchanged if it is a well-formed URL with a supported scheme."""
    if not url or len(url) > MAX_URL_LENGTH:
        raise ValidationError("URL is empty or too long")
    if any(char.isspace() or not char.isprintable() for char in url):
        raise ValidationError("URL contains whitespace or control characters")
    try:
        parts = urlsplit(url)
        has_host = bool(parts.hostname)
        parts.port  # noqa: B018 - raises ValueError on an invalid port
    except ValueError as exc:
        raise ValidationError(f"malformed URL: {exc}") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValidationError(f"unsupported URL scheme: {parts.scheme!r}")
    if not has_host:
        raise ValidationError("URL has no host")
    return url


def validate_filename(name: str) -> str:
    """Return name if it is a single path component safe to use as output file name."""
    if name in {"", ".", ".."} or "/" in name or _has_control_chars(name):
        raise ValidationError(f"invalid file name: {name!r}")
    if len(name.encode()) > MAX_FILENAME_BYTES:
        raise ValidationError("file name is too long")
    return name


def resolve_directory(requested: str | Path, root: Path) -> Path:
    """Resolve requested (absolute or relative to root) and ensure it stays inside root."""
    if _has_control_chars(str(requested)):
        raise ValidationError(f"invalid destination: {str(requested)!r}")
    path = Path(requested).expanduser()
    resolved = (root / path).resolve()  # an absolute path replaces root here
    if not resolved.is_relative_to(root.resolve()):
        raise ValidationError(f"destination {str(requested)!r} is outside {str(root)!r}")
    return resolved


def _has_control_chars(text: str) -> bool:
    # Rejects NUL (crashes path APIs) and newlines (could inject lines into aria2 session files).
    return not all(char.isprintable() or char == " " for char in text)
