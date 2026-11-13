"""User-defined ignore rules applied to every collected notification."""

from __future__ import annotations

import re

from .config import Config
from .models import Notification


class NotificationFilter:
    def __init__(self, cfg: Config):
        self.muted = set(cfg.muted_kinds)
        self.authors = {a.lower().lstrip("@") for a in cfg.ignore_authors}
        self.titles = [re.compile(p, re.IGNORECASE) for p in cfg.ignore_title_patterns]

    def allows(self, n: Notification) -> bool:
        if n.is_system:
            return True
        if n.kind in self.muted:
            return False
        if n.author and n.author.lower() in self.authors:
            return False
        return not (n.title and any(p.search(n.title) for p in self.titles))

    def apply(self, items: list[Notification]) -> list[Notification]:
        return [n for n in items if self.allows(n)]
