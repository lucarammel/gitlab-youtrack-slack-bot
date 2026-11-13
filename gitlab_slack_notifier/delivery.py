"""Outbox delivery: quiet hours, digests, and at-least-once posting to Slack."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .config import Config
from .models import Notification

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 3500  # Slack truncates long messages in the UI around 4000 chars
SLACK_INTERVAL = 1.1  # Slack rate limit: ~1 msg/s per channel


def is_quiet(now: datetime, cfg: Config) -> bool:
    """`now` is local, naive time."""
    if cfg.quiet_weekends and now.weekday() >= 5:
        return True
    window = cfg.quiet_window
    if not window:
        return False
    start, end = window
    t = now.time()
    return start <= t < end if start <= end else (t >= start or t < end)


@dataclass
class Message:
    text: str
    items: list[Notification]


def group(items: list[Notification]) -> list[Message]:
    """One block per MR / issue (in order of first appearance): the subject once, then each
    notification without it. Notifications without a subject stay on their own."""
    by_subject: dict[str, list[Notification]] = {}
    for i, n in enumerate(items):
        by_subject.setdefault(n.subject or f"#{i}", []).append(n)

    blocks: list[Message] = []
    for ns in by_subject.values():
        if len(ns) == 1:
            blocks.append(Message(ns[0].text, ns))
            continue
        current = Message(ns[0].subject, [])
        for n in ns:
            if current.items and len(current.text) + len(n.body) + 1 > MAX_MESSAGE_CHARS:
                blocks.append(current)
                current = Message(n.subject, [])
            current.text += "\n" + n.body
            current.items.append(n)
        blocks.append(current)
    return blocks


def compose(items: list[Notification], batch_threshold: int) -> list[Message]:
    """Notifications about the same MR / issue are grouped; the resulting blocks are sent one per
    message, or as a digest (split into chunks) when there are at least `batch_threshold`."""
    system = [Message(n.text, [n]) for n in items if n.is_system]
    rest = [n for n in items if not n.is_system]
    blocks = group(rest)
    if not batch_threshold or len(blocks) < batch_threshold:
        return system + blocks

    chunks: list[Message] = []
    current = Message(f"*:inbox_tray: {len(rest)} notifications*", [])
    for b in blocks:
        if current.items and len(current.text) + len(b.text) + 2 > MAX_MESSAGE_CHARS:
            chunks.append(current)
            current = Message("", [])
        current.text = f"{current.text}\n\n{b.text}" if current.text else b.text
        current.items += b.items
    chunks.append(current)
    return system + chunks


class Deliverer:
    def __init__(
        self,
        post: Callable[[str], None],
        cfg: Config,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.post = post
        self.cfg = cfg
        self.sleep = sleep

    def deliver(self, outbox: list[Notification], now: datetime, *, force: bool = False) -> tuple[int, int]:
        """Send what is due and remove it from `outbox` (in place, one message at a time, so a
        failure halfway keeps the unsent ones for the next run). Returns (sent, held)."""
        quiet = not force and is_quiet(now, self.cfg)
        bypass = set(self.cfg.quiet_bypass)
        due = [n for n in outbox if not quiet or n.is_system or n.kind in bypass]
        sent = 0
        for i, msg in enumerate(compose(due, self.cfg.batch_threshold)):
            if i:
                self.sleep(SLACK_INTERVAL)
            self.post(msg.text)
            for n in msg.items:
                outbox.remove(n)
            sent += len(msg.items)
        if quiet and outbox:
            log.info("Quiet hours: holding %d notification(s)", len(outbox))
        return sent, len(outbox)
