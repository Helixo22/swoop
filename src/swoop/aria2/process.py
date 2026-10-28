"""Supervisor of the background aria2c process.

Starts aria2c with RPC bound to localhost and a fresh random secret, waits for
the endpoint to answer, restarts it after crashes and shuts it down cleanly.
Queue limits are aria2 global options and are kept across restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import socket
from dataclasses import dataclass, field, replace
from pathlib import Path

from swoop.aria2.rpc import Aria2Client, Aria2ConnectionError, Aria2Error

log = logging.getLogger(__name__)

_READY_POLL_INTERVAL = 0.05
_RESTART_BASE_DELAY = 0.5
_RESTART_MAX_DELAY = 30.0
_STABLE_UPTIME = 30.0
_SESSION_SAVE_INTERVAL = 10


class Aria2StartError(Aria2Error):
    """aria2c could not be launched or never became reachable."""


@dataclass(frozen=True)
class QueueLimits:
    """Queue limits enforced by aria2 itself."""

    max_concurrent_downloads: int = 3
    max_download_speed: int = 0  # bytes per second, 0 means unlimited

    def __post_init__(self) -> None:
        # Values may come from the config file: anything but a plain int would reach aria2.
        if not all(
            type(value) is int for value in (self.max_concurrent_downloads, self.max_download_speed)
        ):
            raise ValueError("queue limits must be integers")
        if self.max_concurrent_downloads < 1:
            raise ValueError("max_concurrent_downloads must be at least 1")
        if self.max_download_speed < 0:
            raise ValueError("max_download_speed must not be negative")

    def as_options(self) -> dict[str, str]:
        return {
            "max-concurrent-downloads": str(self.max_concurrent_downloads),
            "max-overall-download-limit": str(self.max_download_speed),
        }


@dataclass(frozen=True)
class Aria2Settings:
    """Static launch parameters of aria2c."""

    download_dir: Path
    session_file: Path
    executable: str = "aria2c"
    connections_per_download: int = 8
    limits: QueueLimits = field(default_factory=QueueLimits)
    startup_timeout: float = 10.0
    shutdown_timeout: float = 10.0

    def __post_init__(self) -> None:
        # aria2c refuses to start when max-connection-per-server is outside 1..16.
        if not 1 <= self.connections_per_download <= 16:
            raise ValueError("connections_per_download must be between 1 and 16")


def build_arguments(settings: Aria2Settings, port: int, conf_fd: int) -> list[str]:
    """Command line of aria2c; the secret travels in the conf file, never in argv."""
    return [
        settings.executable,
        f"--conf-path=/proc/self/fd/{conf_fd}",
        "--enable-rpc=true",
        "--rpc-listen-all=false",
        f"--rpc-listen-port={port}",
        f"--dir={settings.download_dir}",
        f"--input-file={settings.session_file}",
        f"--save-session={settings.session_file}",
        f"--save-session-interval={_SESSION_SAVE_INTERVAL}",
        f"--split={settings.connections_per_download}",
        f"--max-connection-per-server={settings.connections_per_download}",
        "--min-split-size=1M",
        "--continue=true",
        *(f"--{name}={value}" for name, value in settings.limits.as_options().items()),
        f"--stop-with-process={os.getpid()}",
        "--quiet=true",
    ]


def find_free_port(port: int = 0) -> int:
    """Return port (or a random free one for 0); raise OSError if it is taken."""
    with socket.socket() as sock:
        # Like aria2, ignore TIME_WAIT leftovers; a live listener still makes bind fail.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        return int(sock.getsockname()[1])


class Aria2Process:
    """Owns the aria2c process and the RPC client connected to it."""

    def __init__(self, settings: Aria2Settings) -> None:
        self._settings = settings
        self._secret = secrets.token_urlsafe(32)
        self._port = find_free_port()
        self.client = Aria2Client(f"http://127.0.0.1:{self._port}/jsonrpc", self._secret)
        self._process: asyncio.subprocess.Process | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._limits_lock = asyncio.Lock()

    @property
    def port(self) -> int:
        return self._port

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    async def apply_limits(self, limits: QueueLimits) -> None:
        """Change queue limits at runtime; later restarts launch aria2c with them too."""
        # Serialized so overlapping calls cannot reach aria2 out of order and leave it
        # with other limits than the stored ones.
        async with self._limits_lock:
            # Stored first so that a restart racing with this call still picks them up.
            self._settings = replace(self._settings, limits=limits)
            await self.client.call("aria2.changeGlobalOption", limits.as_options())

    async def start(self) -> None:
        """Launch aria2c and keep it alive until stop() is called."""
        await self._spawn()
        self._watchdog = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        """Shut aria2 down gracefully, killing it if it does not comply."""
        if self._watchdog:
            self._watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog
            self._watchdog = None
        if self._process and self._process.returncode is None:
            await self._shutdown(self._process)
        await self.client.aclose()

    async def _spawn(self) -> None:
        try:
            # On restart the port may have been taken meanwhile: never send the token there.
            find_free_port(self._port)
            self._process = await self._launch()
        except OSError as exc:
            raise Aria2StartError(f"cannot launch {self._settings.executable}: {exc}") from exc
        try:
            await self._wait_ready(self._process)
        except BaseException:
            await _kill(self._process)
            raise

    async def _launch(self) -> asyncio.subprocess.Process:
        _ensure_session_file(self._settings.session_file)
        conf_fd = os.memfd_create("swoop-aria2-conf")
        try:
            os.write(conf_fd, f"rpc-secret={self._secret}\n".encode())
            os.lseek(conf_fd, 0, os.SEEK_SET)
            return await asyncio.create_subprocess_exec(
                *build_arguments(self._settings, self._port, conf_fd),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                pass_fds=(conf_fd,),
            )
        finally:
            os.close(conf_fd)

    async def _wait_ready(self, process: asyncio.subprocess.Process) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.startup_timeout
        while loop.time() < deadline:
            if process.returncode is not None:
                raise Aria2StartError(f"aria2c exited with code {process.returncode} on startup")
            try:
                await self.client.get_version()
            except Aria2ConnectionError:
                await asyncio.sleep(_READY_POLL_INTERVAL)
            else:
                log.info("aria2c ready on port %d (pid %d)", self._port, process.pid)
                return
        raise Aria2StartError("aria2c did not answer before the startup timeout")

    async def _supervise(self) -> None:
        loop = asyncio.get_running_loop()
        failures = 0
        while True:
            assert self._process is not None
            started = loop.time()
            code = await self._process.wait()
            failures = 0 if loop.time() - started > _STABLE_UPTIME else failures + 1
            delay = min(_RESTART_BASE_DELAY * 2**failures, _RESTART_MAX_DELAY)
            log.warning("aria2c exited unexpectedly (code %s), restarting in %.1fs", code, delay)
            await asyncio.sleep(delay)
            try:
                await self._spawn()
            except Aria2Error:
                log.exception("aria2c restart failed")

    async def _shutdown(self, process: asyncio.subprocess.Process) -> None:
        # aria2 treats the first SIGTERM as a graceful shutdown; it is faster than
        # aria2.shutdown over RPC and works even when the RPC server is unresponsive.
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), self._settings.shutdown_timeout)
        except TimeoutError:
            log.warning("aria2c did not exit in time, killing it")
            await _kill(process)


def _ensure_session_file(path: Path) -> None:
    """aria2c refuses to start when --input-file is missing, so create it empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


async def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    await process.wait()
