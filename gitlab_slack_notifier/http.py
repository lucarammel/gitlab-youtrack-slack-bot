"""Minimal JSON-over-HTTP helpers with retries on transient failures (stdlib only)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from typing import Any, Callable

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 60


class ApiError(RuntimeError):
    """Any failure talking to a remote API (network, HTTP status, bad payload)."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _retry_after(headers: Message | None) -> float | None:
    try:
        value = float((headers or {}).get("Retry-After", ""))
    except ValueError:
        return None
    return min(value, MAX_RETRY_AFTER)


def request(
    url: str,
    *,
    headers: dict | None = None,
    data: Any = None,
    retries: int = 2,
    timeout: float = 30,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, Message]:
    """GET (or POST JSON when `data` is given). Retries 429/5xx and network errors."""
    body = json.dumps(data).encode() if data is not None else None
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=dict(headers or {}))
        if body is not None:
            req.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.headers
        except urllib.error.HTTPError as e:  # before URLError: HTTPError subclasses it
            detail = e.read().decode(errors="replace")[:500]
            if e.code not in RETRY_STATUSES or attempt == retries:
                raise ApiError(f"{host}: HTTP {e.code} {detail}".strip(), status=e.code, body=detail) from None
            delay = _retry_after(e.headers) or 2**attempt
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                raise ApiError(f"{host}: {getattr(e, 'reason', e)}") from None
            delay = 2**attempt
        log.debug("Retrying %s in %ss (attempt %d/%d)", host, delay, attempt + 1, retries)
        sleep(delay)
    raise AssertionError("unreachable")


def request_json(url: str, **kwargs) -> tuple[Any, Message]:
    raw, headers = request(url, **kwargs)
    try:
        return json.loads(raw.decode() or "null"), headers
    except ValueError as e:
        raise ApiError(f"{urllib.parse.urlsplit(url).netloc}: invalid JSON ({e})") from None
