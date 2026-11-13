"""Outbox delivery: at-least-once posting to Slack."""

from __future__ import annotations

import time
from typing import Callable

from .models import Notification

SLACK_INTERVAL = 1.1  # Slack rate limit: ~1 msg/s per channel


class Deliverer:
    def __init__(self, post: Callable[[str], None], *, sleep: Callable[[float], None] = time.sleep):
        self.post = post
        self.sleep = sleep

    def deliver(self, outbox: list[Notification]) -> int:
        """Send everything and remove it from `outbox` (in place, one message at a time, so a
        failure halfway keeps the unsent ones for the next run). Returns the number sent."""
        sent = 0
        for n in list(outbox):
            if sent:
                self.sleep(SLACK_INTERVAL)
            self.post(n.text)
            outbox.remove(n)
            sent += 1
        return sent
