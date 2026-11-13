"""Typed configuration loaded from config.toml (flat keys, all optional except gitlab_url)."""

from __future__ import annotations

import dataclasses
import logging
import re
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

log = logging.getLogger(__name__)

YT_DEFAULT_QUERY = "for: me or reporter: me or commenter: me or tag: Star"


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    gitlab_url: str
    slack_channel: str = ""

    # --- GitLab sources ---
    watched_projects: list[str] = field(default_factory=list)
    notify_todos: bool = True
    notify_new_mrs: bool = True
    notify_my_mr_activity: bool = True
    include_own_mrs: bool = False
    include_drafts: bool = True
    todo_actions: list[str] | None = None

    # --- Filtering ---
    ignore_authors: list[str] = field(default_factory=list)  # GitLab usernames / YouTrack logins
    ignore_title_patterns: list[str] = field(default_factory=list)  # regexes, case-insensitive
    muted_kinds: list[str] = field(default_factory=list)

    # --- YouTrack ---
    youtrack_url: str | None = None
    notify_youtrack: bool = True
    youtrack_query: str = YT_DEFAULT_QUERY
    youtrack_fields: list[str] = field(default_factory=lambda: ["State", "Priority"])

    # --- Morning greeting ---
    morning_greeting: bool = True
    morning_hour: int = 8
    morning_weekdays_only: bool = True

    # --- Delivery ---
    quiet_hours: str | None = None  # "19:00-08:30": notifications are held, then sent as a digest
    quiet_weekends: bool = False
    quiet_bypass: list[str] = field(default_factory=list)  # kinds delivered even during quiet hours
    batch_threshold: int = 5  # >= this many pending notifications are merged into a digest (0 = never)

    def __post_init__(self) -> None:
        self.quiet_window  # validate early
        for p in self.ignore_title_patterns:
            try:
                re.compile(p)
            except re.error as e:
                raise ConfigError(f"ignore_title_patterns: invalid regex {p!r}: {e}") from None
        if not 0 <= self.morning_hour <= 23:
            raise ConfigError("morning_hour must be between 0 and 23")

    @property
    def quiet_window(self) -> tuple[time, time] | None:
        if not self.quiet_hours:
            return None
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", self.quiet_hours)
        if not m:
            raise ConfigError(f"quiet_hours must look like '19:00-08:30', got {self.quiet_hours!r}")
        h1, m1, h2, m2 = map(int, m.groups())
        try:
            return time(h1, m1), time(h2, m2)
        except ValueError as e:
            raise ConfigError(f"quiet_hours: {e}") from None

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        known = {f.name for f in dataclasses.fields(cls)}
        for key in sorted(set(data) - known):
            log.warning("config: unknown key %r ignored (typo?)", key)
        if "gitlab_url" not in data:
            raise ConfigError("config: gitlab_url is required")
        try:
            return cls(**{k: v for k, v in data.items() if k in known})
        except TypeError as e:
            raise ConfigError(f"config: {e}") from None

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            return cls.from_dict(tomllib.loads(path.read_text()))
        except FileNotFoundError:
            raise ConfigError(f"{path} not found (cp config.example.toml config.toml)") from None
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from None
