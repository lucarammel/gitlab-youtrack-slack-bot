"""Daily morning greeting with a short summary of what's waiting for you."""

from __future__ import annotations

import logging
from datetime import datetime

from .clients import GitLab, YouTrack
from .config import Config
from .formatting import esc
from .http import ApiError
from .models import Notification
from .state import State

log = logging.getLogger(__name__)

KEY = "last_greeting"


def due(state: State, cfg: Config, now: datetime) -> bool:
    """True once per day, on the first run at/after morning_hour (local time)."""
    if not cfg.morning_greeting:
        return False
    if cfg.morning_weekdays_only and now.weekday() >= 5:
        return False
    return now.hour >= cfg.morning_hour and state.data.get(KEY) != now.date().isoformat()


def mark_sent(state: State, now: datetime) -> None:
    state.data[KEY] = now.date().isoformat()


def message(gl: GitLab, yt: YouTrack | None, me: dict) -> Notification:
    first = (me.get("name") or me["username"]).split()[0]
    lines = [f"*:sunny: Bonjour {esc(first)} !*"]
    try:
        todos = gl.pending_todos()
        reviews = gl.mrs_to_review(me["username"])
        mine = gl.my_open_mrs()
        lines.append(f"• {len(todos)} to-do GitLab en attente")
        lines.append(f"• {len(reviews)} MR en attente de ta review")
        lines.append(f"• {len(mine)} MR ouverte(s) à toi")
        if yt:
            issues = yt.search_issues("for: me #Unresolved")
            lines.append(f"• {len(issues)} issue(s) YouTrack non résolue(s) assignée(s) à toi")
    except (ApiError, KeyError) as e:
        log.warning("Morning summary unavailable: %s", e)
        lines.append(f"_(résumé indisponible : {esc(str(e))})_")
    lines.append("Bonne journée :coffee:")
    return Notification("morning", "\n".join(lines))
