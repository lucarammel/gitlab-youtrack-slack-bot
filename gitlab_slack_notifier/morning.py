"""Daily morning greeting with a short summary of what's waiting for you."""

from __future__ import annotations

import logging
from datetime import datetime

from .clients import GitLab, YouTrack
from .config import Config
from .formatting import age_days, esc, link
from .http import ApiError
from .models import Notification
from .state import State

log = logging.getLogger(__name__)

KEY = "last_greeting"
MAX_LISTED = 5


def due(state: State, cfg: Config, now: datetime) -> bool:
    """True once per day, on the first run at/after morning_hour (local time)."""
    if not cfg.morning_greeting:
        return False
    if cfg.morning_weekdays_only and now.weekday() >= 5:
        return False
    return now.hour >= cfg.morning_hour and state.data.get(KEY) != now.date().isoformat()


def mark_sent(state: State, now: datetime) -> None:
    state.data[KEY] = now.date().isoformat()


def _mr_line(mr: dict, stale_days: int) -> str:
    days = age_days(mr["created_at"])
    stale = " :hourglass:" if stale_days and days >= stale_days else ""
    draft = " _(draft)_" if mr.get("draft") else ""
    ref = mr.get("references", {}).get("full") or f"!{mr['iid']}"
    label = f"{ref} {mr['title']}"
    return f"    – {link(mr['web_url'], label)}{draft} · {days} j{stale}"


def _mr_section(header: str, mrs: list[dict], stale_days: int) -> list[str]:
    if not mrs:
        return [header]
    mrs = sorted(mrs, key=lambda m: m["created_at"])  # oldest first: they need attention
    lines = [header + " :"] + [_mr_line(m, stale_days) for m in mrs[:MAX_LISTED]]
    if len(mrs) > MAX_LISTED:
        lines.append(f"    – … et {len(mrs) - MAX_LISTED} autre(s)")
    return lines


def message(gl: GitLab, yt: YouTrack | None, me: dict, cfg: Config, held: int = 0) -> Notification:
    first = (me.get("name") or me["username"]).split()[0]
    lines = [f"*:sunny: Bonjour {esc(first)} !*"]
    try:
        todos = gl.pending_todos()
        reviews = gl.mrs_to_review(me["username"])
        mine = gl.my_open_mrs()
        lines.append(f"• {len(todos)} to-do GitLab en attente")
        lines += _mr_section(f"• {len(reviews)} MR en attente de ta review", reviews, cfg.stale_review_days)
        lines += _mr_section(f"• {len(mine)} MR ouverte(s) à toi", mine, 0)
        if yt:
            issues = yt.search_issues("for: me #Unresolved")
            lines.append(f"• {len(issues)} issue(s) YouTrack non résolue(s) assignée(s) à toi")
    except (ApiError, KeyError) as e:
        log.warning("Morning summary unavailable: %s", e)
        lines.append(f"_(résumé indisponible : {esc(str(e))})_")
    if held:
        lines.append(f"• {held} notification(s) mise(s) de côté pendant les heures calmes :inbox_tray:")
    lines.append("Bonne journée :coffee:")
    return Notification("morning", "\n".join(lines))
