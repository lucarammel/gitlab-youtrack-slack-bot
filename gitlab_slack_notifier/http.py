"""Minimal JSON-over-HTTP helpers (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from typing import Any


class ApiError(RuntimeError):
    """Any failure talking to a remote API (network, HTTP status, bad payload)."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def request(url: str, *, headers: dict | None = None, data: Any = None, timeout: float = 30) -> tuple[bytes, Message]:
    """GET (or POST JSON when `data` is given)."""
    body = json.dumps(data).encode() if data is not None else None
    host = urllib.parse.urlsplit(url).netloc
    req = urllib.request.Request(url, data=body, headers=dict(headers or {}))
    if body is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers
    except urllib.error.HTTPError as e:  # before URLError: HTTPError subclasses it
        detail = e.read().decode(errors="replace")[:500]
        raise ApiError(f"{host}: HTTP {e.code} {detail}".strip(), status=e.code, body=detail) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ApiError(f"{host}: {getattr(e, 'reason', e)}") from None


def request_json(url: str, **kwargs) -> tuple[Any, Message]:
    raw, headers = request(url, **kwargs)
    try:
        return json.loads(raw.decode() or "null"), headers
    except ValueError as e:
        raise ApiError(f"{urllib.parse.urlsplit(url).netloc}: invalid JSON ({e})") from None
