from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..clients import GitLab, YouTrack
from ..config import Config
from ..models import Notification
from ..state import State


@dataclass
class Context:
    """Everything a collector needs. Collectors read/update `state` (seen ids) and return notifications."""

    cfg: Config
    state: State
    gl: GitLab
    me: dict  # GitLab current user
    yt: YouTrack | None = None
    since: str | None = field(init=False)

    def __post_init__(self) -> None:
        self.since = self.state.since()


@dataclass(frozen=True)
class Collector:
    name: str
    enabled: Callable[[Context], bool]
    collect: Callable[[Context], list[Notification]]
