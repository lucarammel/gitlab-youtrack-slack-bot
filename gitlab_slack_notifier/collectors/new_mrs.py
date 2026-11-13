"""New merge requests on watched projects."""

from __future__ import annotations

from ..formatting import esc, link
from ..models import Notification
from .base import Context

SEEN_KEY = "mr_ids"


def collect(ctx: Context) -> list[Notification]:
    cfg = ctx.cfg
    seen = ctx.state.seen(SEEN_KEY)
    out = []
    for proj in cfg.watched_projects:
        for mr in ctx.gl.project_open_mrs(proj, created_after=ctx.since):
            if mr["id"] in seen:
                continue
            seen.add(mr["id"])
            ctx.state.mark_seen(SEEN_KEY, [mr["id"]])
            if mr["author"]["id"] == ctx.me["id"] and not cfg.include_own_mrs:
                continue
            if mr.get("draft") and not cfg.include_drafts:
                continue
            draft = " _(draft)_" if mr.get("draft") else ""
            mr_link = link(mr["web_url"], "!" + str(mr["iid"]) + " " + mr["title"])
            text = f"*:new: New MR* in `{esc(str(proj))}` by {esc(mr['author']['name'])}{draft}\n{mr_link}"
            out.append(
                Notification("new_mr", text, author=mr["author"].get("username"), title=mr["title"], subject=mr_link)
            )
    return out
