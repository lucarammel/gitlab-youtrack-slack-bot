"""Weekly / monthly recap of your GitLab activity (MRs merged and opened, reviews, commits, repos)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .clients import GitLab
from .config import Config
from .formatting import link, parse_ts, short_ref
from .models import Notification
from .state import State

MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MONTHS_FULL = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
MAX_LISTED = 8
TOP_PROJECTS = 3
PUSH_ACTIONS = {"pushed to", "pushed new"}


@dataclass(frozen=True)
class Period:
    kind: str  # "week" | "month"
    start: date  # inclusive
    end: date  # exclusive

    @property
    def key(self) -> str:
        if self.kind == "week":
            y, w, _ = self.start.isocalendar()
            return f"{y}-W{w:02d}"
        return f"{self.start:%Y-%m}"

    @property
    def state_key(self) -> str:
        return f"last_{self.kind}_recap"

    @property
    def title(self) -> str:
        if self.kind == "month":
            return f"Récap du mois · {MONTHS_FULL[self.start.month - 1]} {self.start.year}"
        last = self.end - timedelta(days=1)
        if last.month == self.start.month:
            span = f"{self.start.day} au {last.day} {MONTHS[last.month - 1]}"
        else:
            span = f"{self.start.day} {MONTHS[self.start.month - 1]} au {last.day} {MONTHS[last.month - 1]}"
        return f"Récap de la semaine · du {span}"

    def contains(self, ts: str) -> bool:
        local = parse_ts(ts).astimezone()  # periods are in local time
        return self.start <= local.date() < self.end


def previous(kind: str, today: date) -> Period:
    """The last complete week (Mon-Sun) or month before `today`."""
    if kind == "week":
        end = today - timedelta(days=today.weekday())
        return Period(kind, end - timedelta(days=7), end)
    end = today.replace(day=1)
    return Period(kind, (end - timedelta(days=1)).replace(day=1), end)


def due(state: State, cfg: Config, now: datetime) -> list[Period]:
    """Recaps not sent yet for the last complete period, from morning_hour on (weekdays only if
    morning_weekdays_only: a recap due on a Saturday the 1st goes out on Monday)."""
    if now.hour < cfg.morning_hour or (cfg.morning_weekdays_only and now.weekday() >= 5):
        return []
    enabled = [k for k, on in (("week", cfg.weekly_recap), ("month", cfg.monthly_recap)) if on]
    periods = [previous(k, now.date()) for k in enabled]
    return [p for p in periods if state.data.get(p.state_key) != p.key]


def mark_sent(state: State, period: Period) -> None:
    state.data[period.state_key] = period.key


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n <= 1 else many}"


def _fmt_days(x: float) -> str:
    if x < 1:
        return f"{round(x * 24)} h"
    return f"{x:.1f}".replace(".", ",") + " j"


def message(gl: GitLab, me: dict, period: Period) -> Notification:
    after = (period.start - timedelta(days=1)).isoformat()  # the events API bounds are exclusive
    events = [e for e in gl.user_events(me["id"], after=after, before=period.end.isoformat())
              if period.contains(e["created_at"])]
    since = datetime.combine(period.start, time()).astimezone().isoformat(timespec="seconds")
    merged = sorted(
        (m for m in gl.my_merged_mrs(since) if m.get("merged_at") and period.contains(m["merged_at"])),
        key=lambda m: m["merged_at"],
    )

    opened = {(e["project_id"], e.get("target_iid")) for e in events
              if e.get("action_name") == "opened" and e.get("target_type") == "MergeRequest"}
    approved = {(e["project_id"], e.get("target_iid")) for e in events
                if e.get("action_name") == "approved" and e.get("target_type") == "MergeRequest"}
    comments = sum(1 for e in events if e.get("action_name") == "commented on"
                   and (e.get("note") or {}).get("noteable_type") == "MergeRequest")
    commits = sum((e.get("push_data") or {}).get("commit_count", 0) for e in events
                  if e.get("action_name") in PUSH_ACTIONS)
    active_days = {parse_ts(e["created_at"]).astimezone().date() for e in events}
    per_project = Counter(e["project_id"] for e in events if e.get("project_id"))

    lines = [f"*:bar_chart: {period.title}*"]
    if not events and not merged:
        lines.append("_Aucune activité GitLab sur la période._")
        return Notification("recap", "\n".join(lines))

    if merged:
        lead = [(parse_ts(m["merged_at"]) - parse_ts(m["created_at"])).total_seconds() / 86400 for m in merged]
        lines.append(f"• :tada: {_plural(len(merged), 'MR mergée', 'MR mergées')} · délai moyen avant merge : "
                     f"{_fmt_days(sum(lead) / len(lead))}")
        for m in merged[:MAX_LISTED]:
            ref = short_ref((m.get("references") or {}).get("full") or f"!{m['iid']}")
            label = f"{ref} {m['title']}"
            lines.append(f"    – {link(m['web_url'], label)}")
        if len(merged) > MAX_LISTED:
            lines.append(f"    – … et {len(merged) - MAX_LISTED} autre(s)")
    else:
        lines.append("• :tada: Aucune MR mergée")
    lines.append(f"• :new: {_plural(len(opened), 'MR ouverte', 'MR ouvertes')}")
    lines.append(f"• :eyes: Reviews : {_plural(len(approved), 'MR approuvée', 'MR approuvées')}, "
                 f"{_plural(comments, 'commentaire', 'commentaires')} sur des MR")
    lines.append(f"• :arrow_up: {_plural(commits, 'commit poussé', 'commits poussés')}")
    lines.append(f"• :calendar: {_plural(len(active_days), 'jour', 'jours')} d'activité")
    if per_project:
        top = []
        for pid, n in per_project.most_common(TOP_PROJECTS):
            p = gl.project(pid)
            top.append(f"{link(p['web_url'], p.get('path') or p['name'])} ({n})")
        lines.append(f"• :file_folder: Repos les plus actifs : {', '.join(top)}")
    return Notification("recap", "\n".join(lines))
