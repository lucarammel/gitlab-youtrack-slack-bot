"""YouTrack: mentions, assignments, and comments / field changes / creation on issues that concern you."""

from __future__ import annotations

from datetime import datetime

from ..formatting import esc, link, snippet
from ..models import Notification
from .base import Context

SEEN_KEY = "yt_activity_ids"
CATEGORIES = "CommentsCategory,CustomFieldCategory,IssueCreatedCategory"


def _value(v) -> str:
    if isinstance(v, dict):
        return v.get("fullName") or v.get("name") or v.get("presentation") or v.get("login") or "?"
    return str(v)


def _values(vals) -> str:
    if vals is None:
        return "∅"
    if not isinstance(vals, list):
        vals = [vals]
    return ", ".join(_value(v) for v in vals) or "∅"


def _issue_of(activity: dict) -> dict:
    t = activity.get("target") or {}
    return t.get("issue") or t


def collect(ctx: Context) -> list[Notification]:
    yt = ctx.yt
    if not yt or not ctx.since:
        return []
    login = yt.me()["login"]
    start_ms = int(datetime.fromisoformat(ctx.since).timestamp() * 1000)
    seen = ctx.state.seen(SEEN_KEY)
    acts = [a for a in sorted(yt.activities(start_ms, CATEGORIES), key=lambda a: a["timestamp"]) if a["id"] not in seen]
    ctx.state.mark_seen(SEEN_KEY, [a["id"] for a in acts])
    acts = [a for a in acts if (a.get("author") or {}).get("login") != login]
    if not acts:
        return []

    # Which of the touched issues "concern me" according to youtrack_query?
    ids = sorted({_issue_of(a).get("idReadable") for a in acts} - {None})
    mine = yt.matching_issue_ids(ctx.cfg.youtrack_query, ids)
    fields_wanted = set(ctx.cfg.youtrack_fields)

    out = []
    for a in acts:
        issue = _issue_of(a)
        iid = issue.get("idReadable")
        if not iid:
            continue
        author = a.get("author") or {}
        who = esc(author.get("fullName") or "someone")
        summary = issue.get("summary", "")
        ilink = link(yt.issue_url(iid), f"{iid} {summary}".strip())

        def note(kind: str, text: str) -> None:
            out.append(Notification(kind, text, author=author.get("login"), title=summary))

        cat = (a.get("category") or {}).get("id")
        if cat == "CommentsCategory":
            for c in a.get("added") or []:
                text = c.get("text") or ""
                if f"@{login}" in text:
                    note("yt_mention", f"*:speech_balloon: Mentioned* by {who} (YouTrack)\n{ilink}\n> {snippet(text)}")
                elif iid in mine:
                    note("yt_comment", f"*:speech_balloon: Comment* by {who} (YouTrack)\n{ilink}\n> {snippet(text)}")
        elif cat == "CustomFieldCategory":
            fname = (a.get("field") or {}).get("presentation") or ""
            added = a.get("added") or []
            if fname == "Assignee" and any(isinstance(v, dict) and v.get("login") == login for v in added):
                note("yt_assigned", f"*:bust_in_silhouette: Assigned to you* by {who} (YouTrack)\n{ilink}")
            elif iid in mine and fname in fields_wanted:
                note(
                    "yt_field",
                    f"*:arrows_counterclockwise: {esc(fname)}*: {esc(_values(a.get('removed')))} → "
                    f"{esc(_values(added))} by {who} (YouTrack)\n{ilink}",
                )
        elif cat == "IssueCreatedCategory" and iid in mine:
            note("yt_new_issue", f"*:new: New issue* by {who} (YouTrack)\n{ilink}")
    return out
