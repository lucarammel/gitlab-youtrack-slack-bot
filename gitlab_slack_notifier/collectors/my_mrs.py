"""Comments, approvals and merges on your own merge requests."""

from __future__ import annotations

from ..formatting import esc, link, mentions, parse_ts, short_ref, snippet
from ..models import Notification
from .base import Context

SEEN_KEY = "note_ids"

# System note prefix -> (kind, label)
SYSTEM_EVENTS = {
    "approved": ("mr_approved", ":white_check_mark: Approved"),
    "unapproved": ("mr_unapproved", ":no_entry_sign: Approval revoked"),
    "merged": ("mr_merged", ":tada: Merged"),
}


def collect(ctx: Context) -> list[Notification]:
    if not ctx.since:
        return []
    since = parse_ts(ctx.since)
    me = ctx.me
    seen = ctx.state.seen(SEEN_KEY)
    out = []
    for mr in ctx.gl.my_mrs_updated_after(ctx.since):
        mr_link = link(mr["web_url"], f"{short_ref(mr['references']['full'])} {mr['title']}")
        for n in ctx.gl.latest_mr_notes(mr["project_id"], mr["iid"]):
            if n["id"] in seen or parse_ts(n["created_at"]) < since:
                continue
            seen.add(n["id"])
            ctx.state.mark_seen(SEEN_KEY, [n["id"]])
            author = n["author"]
            body = n.get("body", "")
            by_me = author["id"] == me["id"]
            # Your own actions are skipped, except merges: with auto-merge ("merge when pipeline
            # succeeds") GitLab attributes the merge to you, and it happens while you're elsewhere.
            if by_me and not (n.get("system") and body.startswith("merged")):
                continue
            who = esc(author["name"])
            if n.get("system"):
                event = next((v for k, v in SYSTEM_EVENTS.items() if body.startswith(k)), None)
                if event:
                    kind, label = event
                    text = f"*{label}*\n{mr_link}" if by_me else f"*{label}* by {who}\n{mr_link}"
                    out.append(Notification(kind, text, author["username"], mr["title"], mr_link))
                continue
            # Mentions already come through the to-do list.
            if mentions(body, me["username"]):
                continue
            out.append(
                Notification(
                    "mr_comment",
                    f"*:speech_balloon: Comment* by {who} on your MR\n{mr_link}\n> {snippet(body)}",
                    author["username"],
                    mr["title"],
                    mr_link,
                )
            )
    return out
