"""Validation of untrusted input before it reaches aria2.

Checks download URLs, magnet links, torrent files, request headers, output
file names and destination directories so that only supported schemes are
accepted, nothing can be injected into aria2 options and nothing escapes the
allowed root.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https", "ftp", "sftp"})
MAX_URL_LENGTH = 8192
MAX_FILENAME_BYTES = 255
ALLOWED_HEADERS = frozenset({"Cookie", "Referer", "User-Agent"})
MAX_HEADER_LENGTH = 16 * 1024
MAX_TORRENT_SIZE = 10 * 1024 * 1024
_MAGNET_TOPICS = ("urn:btih:", "urn:btmh:")  # BitTorrent v1 and v2 info hashes


class ValidationError(ValueError):
    """Input rejected because it is malformed or unsafe."""


def _check_text(uri: str) -> None:
    if not uri or len(uri) > MAX_URL_LENGTH:
        raise ValidationError("URL is empty or too long")
    if any(char.isspace() or not char.isprintable() for char in uri):
        raise ValidationError("URL contains whitespace or control characters")


def validate_url(url: str) -> str:
    """Return url unchanged if it is a well-formed URL with a supported scheme."""
    _check_text(url)
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


def validate_magnet(uri: str) -> str:
    """Return uri unchanged if it is a magnet link carrying a BitTorrent info hash."""
    _check_text(uri)
    parts = urlsplit(uri)
    if parts.scheme.lower() != "magnet":
        raise ValidationError("not a magnet link")
    topics = parse_qs(parts.query).get("xt", [])
    if not any(topic.lower().startswith(_MAGNET_TOPICS) for topic in topics):
        raise ValidationError("magnet link has no BitTorrent info hash")
    return uri


def validate_download_uri(uri: str) -> str:
    """A URL with a supported scheme, or a BitTorrent magnet link."""
    return validate_magnet(uri) if uri[:7].lower() == "magnet:" else validate_url(uri)


def read_torrent_file(path: Path) -> bytes:
    """Contents of a .torrent file, checked to be a reasonably sized bencoded dictionary."""
    if not path.is_absolute():
        raise ValidationError("torrent path must be absolute")
    try:
        # O_NONBLOCK: a FIFO planted at this path must not hang Swoop.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ValidationError("torrent path is not a regular file")
            data = file.read(MAX_TORRENT_SIZE + 1)
    except OSError as exc:
        raise ValidationError(f"cannot read torrent file: {exc.strerror}") from exc
    if len(data) > MAX_TORRENT_SIZE or not data.startswith(b"d"):
        raise ValidationError("not a torrent file")
    return data


def validate_headers(headers: object) -> list[str]:
    """Return aria2 "header" option lines for the request headers a browser may forward."""
    if not isinstance(headers, dict) or not all(isinstance(v, str) for v in headers.values()):
        raise ValidationError("headers must map names to strings")
    if not ALLOWED_HEADERS.issuperset(headers):
        raise ValidationError("only Cookie, Referer and User-Agent headers are allowed")
    for name, value in headers.items():
        # Values are never echoed back: they may hold session cookies.
        if len(value) > MAX_HEADER_LENGTH or not (value.isascii() and value.isprintable()):
            raise ValidationError(f"invalid {name} header")
    if "Referer" in headers:
        validate_url(headers["Referer"])
    return [f"{name}: {value}" for name, value in headers.items()]


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
    try:
        path = Path(requested).expanduser()
    except RuntimeError as exc:  # "~name" of an unknown user
        raise ValidationError(f"invalid destination: {str(requested)!r}") from exc
    resolved = (root / path).resolve()  # an absolute path replaces root here
    if not resolved.is_relative_to(root.resolve()):
        raise ValidationError(f"destination {str(requested)!r} is outside {str(root)!r}")
    return resolved


def _has_control_chars(text: str) -> bool:
    # Rejects NUL (crashes path APIs) and newlines (could inject lines into aria2 session files).
    return not all(char.isprintable() or char == " " for char in text)
