"""Native messaging host for the Swoop browser extension.

Reads length-prefixed JSON messages from the browser on stdin, validates them
strictly and hands accepted downloads to Swoop by running "swoop add"; request
headers (cookies) are passed on its stdin, never on the command line.
"""

from __future__ import annotations

import json
import logging
import struct
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, BinaryIO

from swoop.validation import (
    ValidationError,
    validate_filename,
    validate_headers,
    validate_url,
)

log = logging.getLogger(__name__)

MAX_MESSAGE_SIZE = 64 * 1024
LAUNCH_TIMEOUT = 3.0
_HEADER = struct.Struct("=I")  # native-endian uint32, as the browsers send it
_ALLOWED_KEYS = frozenset({"action", "url", "filename", "headers"})

Reply = dict[str, Any]


@dataclass(frozen=True)
class LaunchRequest:
    """A validated "swoop add" invocation and the data to write on its stdin."""

    arguments: list[str]
    stdin: bytes = b""


Launcher = Callable[[LaunchRequest], Reply]


class ProtocolError(Exception):
    """The byte stream from the browser violates the native messaging framing."""


def read_message(stream: BinaryIO) -> Any:
    """Return the next decoded message, or None at end of input."""
    header = stream.read(_HEADER.size)
    if not header:
        return None
    if len(header) < _HEADER.size:
        raise ProtocolError("truncated message header")
    (size,) = _HEADER.unpack(header)
    if size > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"message of {size} bytes exceeds the limit")
    body = stream.read(size)
    if len(body) < size:
        raise ProtocolError("truncated message body")
    try:
        return json.loads(body)
    except (ValueError, RecursionError) as exc:  # RecursionError: deeply nested JSON
        raise ProtocolError("message is not valid JSON") from exc


def write_message(stream: BinaryIO, message: Reply) -> None:
    body = json.dumps(message).encode()
    stream.write(_HEADER.pack(len(body)) + body)
    stream.flush()


def parse_download(message: Any) -> LaunchRequest:
    """Turn a browser message into a "swoop add" invocation, rejecting anything unexpected."""
    if not isinstance(message, dict) or message.get("action") != "download":
        raise ValidationError("unsupported message")
    if not _ALLOWED_KEYS.issuperset(message):
        raise ValidationError("unexpected fields in message")
    url, filename = message.get("url"), message.get("filename")
    if not isinstance(url, str) or not isinstance(filename, str | None):
        raise ValidationError("url and filename must be strings")
    options = [] if filename is None else [f"--out={validate_filename(filename)}"]
    headers = message.get("headers")
    if headers is None:
        return LaunchRequest(["add", *options, "--", validate_url(url)])
    validate_headers(headers)
    arguments = ["add", *options, "--headers-from-stdin", "--", validate_url(url)]
    return LaunchRequest(arguments, json.dumps(headers).encode())


def launch_swoop(request: LaunchRequest) -> Reply:
    """Run "swoop add"; if it is still running after a while it became the primary instance."""
    process = subprocess.Popen(  # noqa: S603 - fixed executable, validated arguments, no shell
        # -P: never import a "swoop" module from the browser's working directory.
        [sys.executable, "-P", "-m", "swoop", *request.arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # survive the browser closing this host
    )
    try:
        process.communicate(request.stdin, timeout=LAUNCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": True}
    code = process.returncode
    return {"ok": True} if code == 0 else {"ok": False, "error": f"swoop exited with {code}"}


def handle(message: Any, launch: Launcher) -> Reply:
    try:
        request = parse_download(message)
    except ValidationError as exc:
        return {"ok": False, "error": str(exc)}
    return launch(request)


def serve(stdin: BinaryIO, stdout: BinaryIO, launch: Launcher = launch_swoop) -> None:
    while (message := read_message(stdin)) is not None:
        write_message(stdout, handle(message, launch))


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)  # stdout belongs to the protocol
    try:
        serve(sys.stdin.buffer, sys.stdout.buffer)
    except ProtocolError as exc:
        log.error("closing connection: %s", exc)
        return 1
    return 0
