"""One polling cycle: collect -> post -> save state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import morning
from .clients import GitLab, Slack, YouTrack
from .collectors import COLLECTORS, Context
from .config import Config
from .models import Notification
from .state import State, now_iso

log = logging.getLogger(__name__)

SLACK_INTERVAL = 1.1  # Slack rate limit: ~1 msg/s per channel


@dataclass
class RunResult:
    collected: int = 0
    sent: int = 0


class Notifier:
    def __init__(
        self,
        cfg: Config,
        gl: GitLab,
        slack: Slack | None,
        state_path: Path,
        *,
        yt: YouTrack | None = None,
        dry_run: bool = False,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cfg = cfg
        self.gl = gl
        self.yt = yt
        self.state_path = state_path
        self.dry_run = dry_run
        self.clock = clock
        self.post = self._print if dry_run else slack.post
        self.sleep = (lambda _: None) if dry_run else sleep

    @staticmethod
    def _print(text: str) -> None:
        print("---\n" + text)

    def collect(self, state: State, now: datetime) -> list[Notification]:
        started = now_iso()
        me = self.gl.current_user()
        ctx = Context(cfg=self.cfg, state=state, gl=self.gl, me=me, yt=self.yt)
        fresh: list[Notification] = []
        for c in COLLECTORS:
            if c.enabled(ctx):
                items = c.collect(ctx)
                log.debug("%s: %d new item(s)", c.name, len(items))
                fresh += items

        if state.first_run:
            log.info("First run: recorded %d existing item(s) as seen, nothing sent.", len(fresh))
            fresh = []

        if morning.due(state, self.cfg, now):
            fresh.insert(0, morning.message(self.gl, self.yt, me))
            morning.mark_sent(state, now)

        state.last_run = started
        return fresh

    def run_once(self) -> RunResult:
        """Posts everything, then saves state: on error nothing is saved and the run is retried."""
        state = State.load(self.state_path)
        fresh = self.collect(state, self.clock())
        for i, n in enumerate(fresh):
            if i:
                self.sleep(SLACK_INTERVAL)
            self.post(n.text)
        if not self.dry_run:
            state.save()
        return RunResult(collected=len(fresh), sent=len(fresh))
