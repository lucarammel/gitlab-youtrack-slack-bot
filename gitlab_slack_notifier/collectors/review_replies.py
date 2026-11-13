"""Replies in your threads on MRs you review (GitLab only creates a to-do for those when you're @-mentioned)."""

from __future__ import annotations

from ..formatting import esc, link, mentions, parse_ts, short_ref, snippet
from ..models import Notification
from .base import Context

SEEN_KEY = "review_note_ids"


def collect(ctx: Context) -> list[Notification]:
    if not ctx.since:
        return []
    since = parse_ts(ctx.since)
    me = ctx.me
    seen = ctx.state.seen(SEEN_KEY)
    out = []
    for mr in ctx.gl.reviewed_mrs_updated_after(me["username"], ctx.since):
        if mr["author"]["id"] == me["id"]:
            continue  # your own MR: covered by my_mrs
        mr_link = link(mr["web_url"], f"{short_ref(mr['references']['full'])} {mr['title']}")
        for d in ctx.gl.mr_discussions(mr["project_id"], mr["iid"]):
            notes = [n for n in d.get("notes", []) if not n.get("system")]
            mine = [i for i, n in enumerate(notes) if n["author"]["id"] == me["id"]]
            if not mine:
                continue  # not one of your threads
            for n in notes[mine[0] + 1 :]:
                if n["id"] in seen or parse_ts(n["created_at"]) < since:
                    continue
                seen.add(n["id"])
                ctx.state.mark_seen(SEEN_KEY, [n["id"]])
                author = n["author"]
                body = n.get("body", "")
                # Your own follow-ups, and mentions (already come through the to-do list).
                if author["id"] == me["id"] or mentions(body, me["username"]):
                    continue
                out.append(
                    Notification(
                        "review_reply",
                        f"*:leftwards_arrow_with_hook: Reply* by {esc(author['name'])} in your thread\n"
                        f"{mr_link}\n> {snippet(body)}",
                        author["username"],
                        mr["title"],
                        mr_link,
                    )
                )
    return out
