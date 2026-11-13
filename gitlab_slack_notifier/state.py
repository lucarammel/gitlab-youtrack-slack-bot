"""Persistent state (state.json): seen ids, outbox, last run, health counters."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Notification

SEEN_KEEP = 2000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path, data: dict | None = None):
        self.path = path
        self.data: dict = data or {}

    @classmethod
    def load(cls, path: Path) -> State:
        return cls(path, json.loads(path.read_text()) if path.exists() else {})

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False))
        tmp.replace(self.path)

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)

    def restore(self, snapshot: dict) -> None:
        self.data = snapshot

    # --- run bookkeeping ---
    @property
    def first_run(self) -> bool:
        return "last_run" not in self.data

    @property
    def last_run(self) -> str | None:
        return self.data.get("last_run")

    @last_run.setter
    def last_run(self, value: str) -> None:
        self.data["last_run"] = value

    def since(self, margin_minutes: int = 10) -> str | None:
        """last_run minus a margin, to tolerate clock skew; seen-ids dedupe the overlap."""
        if not self.last_run:
            return None
        return (datetime.fromisoformat(self.last_run) - timedelta(minutes=margin_minutes)).isoformat(
            timespec="seconds"
        )

    # --- seen ids (insertion-ordered, bounded) ---
    def seen(self, key: str) -> set:
        return set(self.data.get(key, []))

    def mark_seen(self, key: str, ids) -> None:
        current = self.data.get(key, [])
        known = set(current)
        current += [i for i in ids if i not in known and not known.add(i)]
        self.data[key] = current[-SEEN_KEEP:]

    # --- outbox: notifications collected but not yet delivered ---
    @property
    def outbox(self) -> list[Notification]:
        return [Notification.from_dict(d) for d in self.data.get("outbox", [])]

    @outbox.setter
    def outbox(self, items: list[Notification]) -> None:
        self.data["outbox"] = [n.to_dict() for n in items]
