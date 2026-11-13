"""Final pipeline status on your own open merge requests ("CI is green, you can merge")."""

from __future__ import annotations

from ..formatting import link, parse_ts, short_ref
from ..models import Notification
from .base import Context

STATE_KEY = "mr_pipelines"  # {mr_id: "pipeline_id:status"} last reported per MR
FINAL = {
    "success": ":large_green_circle: Pipeline passed",
    "failed": ":red_circle: Pipeline failed",
    "canceled": ":white_circle: Pipeline canceled",
}


def collect(ctx: Context) -> list[Notification]:
    wanted = set(ctx.cfg.pipeline_statuses) & FINAL.keys()
    if not wanted:
        return []
    known: dict = ctx.state.data.get(STATE_KEY, {})
    current: dict = {}
    out = []
    for mr in ctx.gl.my_open_mrs():
        key = str(mr["id"])
        p = ctx.gl.latest_mr_pipeline(mr["project_id"], mr["iid"])
        if not p:
            continue
        marker = f"{p['id']}:{p['status']}"
        current[key] = marker
        if p["status"] not in FINAL or known.get(key) == marker:
            continue
        # Without a reference point (first run / newly seen MR), only report recent pipelines.
        if not ctx.since or parse_ts(p.get("updated_at") or p["created_at"]) < parse_ts(ctx.since):
            continue
        if p["status"] not in wanted:
            continue
        mr_link = link(mr["web_url"], f"{short_ref(mr['references']['full'])} {mr['title']}")
        out.append(
            Notification(
                f"pipeline_{p['status']}",
                f"*{FINAL[p['status']]}* on your MR\n{mr_link} · {link(p['web_url'], '#' + str(p['id']))}",
                title=mr["title"],
                subject=mr_link,
            )
        )
    ctx.state.data[STATE_KEY] = current  # drops MRs that are no longer open
    return out
