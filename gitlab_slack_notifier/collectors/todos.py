"""GitLab To-Do list: mentions, review requests, assignments, failed pipelines, ..."""

from __future__ import annotations

from ..formatting import esc, link, snippet
from ..models import Notification
from .base import Context

TODO_LABELS = {
    "mentioned": ":speech_balloon: Mentioned",
    "directly_addressed": ":speech_balloon: Directly addressed",
    "assigned": ":bust_in_silhouette: Assigned",
    "review_requested": ":eyes: Review requested",
    "approval_required": ":white_check_mark: Approval required",
    "build_failed": ":x: Pipeline failed",
    "unmergeable": ":warning: Unmergeable",
    "marked": ":bookmark: Added to-do",
    "merge_train_removed": ":warning: Removed from merge train",
    "member_access_requested": ":key: Access requested",
}

SEEN_KEY = "todo_ids"


def collect(ctx: Context) -> list[Notification]:
    wanted = set(ctx.cfg.todo_actions or TODO_LABELS)
    seen = ctx.state.seen(SEEN_KEY)
    new = [t for t in sorted(ctx.gl.pending_todos(), key=lambda t: t["id"]) if t["id"] not in seen]
    ctx.state.mark_seen(SEEN_KEY, [t["id"] for t in new])

    out = []
    for t in new:
        action = t["action_name"]
        if action not in wanted:
            continue
        target = t.get("target") or {}
        title = target.get("title") or t.get("target_type", "")
        ref = (target.get("references") or {}).get("full") or ""
        author = t.get("author") or {}
        text = (
            f"*{TODO_LABELS.get(action, action)}* by {esc(author.get('name', 'someone'))}\n"
            f"{link(t['target_url'], f'{ref} {title}'.strip())}"
        )
        if t.get("body") and action in ("mentioned", "directly_addressed"):
            text += f"\n> {snippet(t['body'])}"
        out.append(Notification(action, text, author=author.get("username"), title=title))
    return out
