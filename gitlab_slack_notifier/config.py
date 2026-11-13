"""Typed configuration loaded from config.toml (flat keys, all optional except gitlab_url)."""

from __future__ import annotations

import dataclasses
import logging
import tomllib
from dataclasses import dataclass, field
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

    # --- YouTrack ---
    youtrack_url: str | None = None
    notify_youtrack: bool = True
    youtrack_query: str = YT_DEFAULT_QUERY
    youtrack_fields: list[str] = field(default_factory=lambda: ["State", "Priority"])

    # --- Morning greeting ---
    morning_greeting: bool = True
    morning_hour: int = 8
    morning_weekdays_only: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.morning_hour <= 23:
            raise ConfigError("morning_hour must be between 0 and 23")

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
