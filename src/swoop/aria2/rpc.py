"""Thin asynchronous JSON-RPC client for aria2.

Sends requests to aria2's JSON-RPC endpoint with httpx, injects the secret
token and maps transport and RPC failures to typed exceptions.
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx

_TOKENLESS_PREFIX = "system."


class Aria2Error(Exception):
    """Base class for every failure while talking to aria2."""


class Aria2ConnectionError(Aria2Error):
    """aria2 could not be reached."""


class Aria2RpcError(Aria2Error):
    """aria2 answered with a JSON-RPC error object."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"aria2 error {code}: {message}")
        self.code = code
        self.message = message


class Aria2Client:
    """Calls aria2 RPC methods; the secret token is never exposed by repr or errors."""

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._token = f"token:{secret}"
        self._ids = itertools.count(1)
        # trust_env=False keeps proxy settings from routing the token off localhost.
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport, trust_env=False)

    def __repr__(self) -> str:
        return f"Aria2Client(url={self._url!r})"

    async def call(self, method: str, *params: Any) -> Any:
        """Invoke an RPC method and return its result."""
        if not method.startswith(_TOKENLESS_PREFIX):
            params = (self._token, *params)
        payload = {
            "jsonrpc": "2.0",
            "id": str(next(self._ids)),
            "method": method,
            "params": list(params),
        }
        try:
            response = await self._http.post(self._url, json=payload)
        except httpx.TransportError as exc:
            raise Aria2ConnectionError(f"cannot reach aria2 at {self._url}") from exc
        return _parse_response(response)

    async def get_version(self) -> str:
        result = await self.call("aria2.getVersion")
        if not isinstance(result, dict) or "version" not in result:
            raise Aria2Error("malformed aria2.getVersion result")
        return str(result["version"])

    async def aclose(self) -> None:
        await self._http.aclose()


def _parse_response(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError as exc:
        raise Aria2Error(f"invalid JSON from aria2 (HTTP {response.status_code})") from exc
    if not isinstance(body, dict):
        raise Aria2Error("malformed JSON-RPC response from aria2")
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        raise Aria2RpcError(code if isinstance(code, int) else -1, str(error.get("message", "")))
    if "result" not in body:
        raise Aria2Error("JSON-RPC response from aria2 has no result")
    return body["result"]
