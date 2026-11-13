#!/usr/bin/env python3
"""Poll GitLab and post notifications to a Slack conversation.

Sources:
  - GitLab To-Do list: mentions, review requests, assignments, failed pipelines, ...
  - New merge requests on watched projects.
  - New comments / approvals on your own open merge requests.
  - YouTrack: mentions, assignments, comments / field changes on issues that concern you.

Stdlib only. Config in config.toml, secrets in environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

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


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def http_json(url: str, *, headers: dict, data: dict | None = None) -> tuple:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers)
    if body is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode() or "null"
        return json.loads(raw), resp.headers


class GitLab:
    def __init__(self, base_url: str, token: str):
        self.api = base_url.rstrip("/") + "/api/v4"
        self.headers = {"PRIVATE-TOKEN": token}

    def get(self, path: str, **params) -> list | dict:
        """GET with automatic pagination for list endpoints."""
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("per_page", 100)
        out: list = []
        page = 1
        while True:
            params["page"] = page
            url = f"{self.api}{path}?{urllib.parse.urlencode(params)}"
            data, headers = http_json(url, headers=self.headers)
            if not isinstance(data, list):
                return data
            out.extend(data)
            nxt = headers.get("X-Next-Page")
            if not nxt:
                return out
            page = int(nxt)

    def project_id(self, path_or_id: str | int) -> str:
        return urllib.parse.quote(str(path_or_id), safe="")


EMOJI = {
    "arrows_counterclockwise": "🔄", "bookmark": "🔖", "bust_in_silhouette": "👤", "coffee": "☕",
    "eyes": "👀", "key": "🔑", "new": "🆕", "no_entry_sign": "🚫", "speech_balloon": "💬",
    "sunny": "☀️", "tada": "🎉", "warning": "⚠️", "wave": "👋", "white_check_mark": "✅", "x": "❌",
}


def to_plain(text: str) -> str:
    """Workflow Builder variables render neither <url|label> links nor :emoji: shortcodes:
    turn links into 'label (url)' and shortcodes into Unicode emoji."""
    text = re.sub(r":([a-z_]+):", lambda m: EMOJI.get(m.group(1), m.group(0)), text)
    text = re.sub(r"<([^|>]+)\|([^>]*)>", r"\2 (\1)", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


class YouTrack:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def get(self, path: str, **params) -> list | dict:
        """GET with $skip/$top pagination for list endpoints."""
        top = 200
        out: list = []
        skip = 0
        while True:
            q = {**params, "$top": top, "$skip": skip}
            data, _ = http_json(f"{self.base}/api{path}?{urllib.parse.urlencode(q)}", headers=self.headers)
            if not isinstance(data, list):
                return data
            out.extend(data)
            if len(data) < top:
                return out
            skip += top

    def issue_url(self, issue_id: str) -> str:
        return f"{self.base}/issue/{issue_id}"


class Slack:
    def __init__(
        self,
        webhook_url: str | None,
        bot_token: str | None,
        channel: str | None,
        workflow_url: str | None = None,
    ):
        if not (workflow_url or webhook_url or (bot_token and channel)):
            sys.exit("Set SLACK_WORKFLOW_URL, SLACK_WEBHOOK_URL, or SLACK_BOT_TOKEN + SLACK_CHANNEL.")
        # A Workflow Builder URL (/triggers/) put in SLACK_WEBHOOK_URL: treat it as a workflow.
        if not workflow_url and webhook_url and "/triggers/" in webhook_url:
            workflow_url, webhook_url = webhook_url, None
        self.workflow_url = workflow_url
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.channel = channel

    def post(self, text: str) -> None:
        if self.workflow_url:
            # Workflow Builder webhook trigger: body keys must match the declared variables.
            req = urllib.request.Request(
                self.workflow_url,
                data=json.dumps({"text": to_plain(text)}).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=30).read()
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"Slack workflow error {e.code}: {e.read().decode(errors='replace')}") from None
            return
        payload = {"text": text, "unfurl_links": False, "unfurl_media": False}
        if self.webhook_url:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=30).read()
            return
        payload["channel"] = self.channel
        data, _ = http_json(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {self.bot_token}"},
            data=payload,
        )
        if not data.get("ok"):
            raise RuntimeError(f"Slack error: {data.get('error')}")


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def trim(ids: list, keep: int = 2000) -> list:
    return ids[-keep:]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def since_with_margin(state: dict, minutes: int = 10) -> str | None:
    """last_run minus a margin, to tolerate clock skew; seen-ids dedupe the overlap."""
    last = state.get("last_run")
    if not last:
        return None
    return (datetime.fromisoformat(last) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str, text: str) -> str:
    return f"<{url}|{esc(text)}>"


def snippet(body: str, n: int = 200) -> str:
    body = " ".join(body.split())
    return esc(body if len(body) <= n else body[: n - 1] + "…")


# --------------------------------------------------------------------------- #
# Collectors: each returns a list of Slack message strings and updates state
# --------------------------------------------------------------------------- #
def collect_todos(gl: GitLab, state: dict, cfg: dict) -> list[str]:
    wanted = set(cfg.get("todo_actions") or TODO_LABELS.keys())
    seen = set(state.get("todo_ids", []))
    msgs = []
    todos = gl.get("/todos", state="pending")
    for t in sorted(todos, key=lambda t: t["id"]):
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        if t["action_name"] not in wanted:
            continue
        label = TODO_LABELS.get(t["action_name"], t["action_name"])
        target = t.get("target") or {}
        title = target.get("title") or t.get("target_type", "")
        ref = target.get("references", {}).get("full") or ""
        author = (t.get("author") or {}).get("name", "someone")
        msg = f"*{label}* by {esc(author)}\n{link(t['target_url'], f'{ref} {title}'.strip())}"
        if t.get("body") and t["action_name"] in ("mentioned", "directly_addressed"):
            msg += f"\n> {snippet(t['body'])}"
        msgs.append(msg)
    state["todo_ids"] = trim(sorted(seen))
    return msgs


def collect_new_mrs(gl: GitLab, state: dict, cfg: dict, me: dict) -> list[str]:
    projects = cfg.get("watched_projects") or []
    since = since_with_margin(state)
    seen = set(state.get("mr_ids", []))
    msgs = []
    for proj in projects:
        mrs = gl.get(
            f"/projects/{gl.project_id(proj)}/merge_requests",
            state="opened",
            created_after=since,
            order_by="created_at",
            sort="asc",
        )
        for mr in mrs:
            if mr["id"] in seen:
                continue
            seen.add(mr["id"])
            if mr["author"]["id"] == me["id"] and not cfg.get("include_own_mrs", False):
                continue
            if mr.get("draft") and not cfg.get("include_drafts", True):
                continue
            draft = " _(draft)_" if mr.get("draft") else ""
            msgs.append(
                f"*:new: New MR* in `{esc(proj)}` by {esc(mr['author']['name'])}{draft}\n"
                f"{link(mr['web_url'], '!' + str(mr['iid']) + ' ' + mr['title'])}"
            )
    state["mr_ids"] = trim(sorted(seen))
    return msgs


def collect_my_mr_activity(gl: GitLab, state: dict, cfg: dict, me: dict) -> list[str]:
    since = since_with_margin(state)
    if not since:
        return []
    seen = set(state.get("note_ids", []))
    msgs = []
    mrs = gl.get(
        "/merge_requests",
        scope="created_by_me",
        state="opened",
        updated_after=since,
    )
    for mr in mrs:
        notes = gl.get(
            f"/projects/{mr['project_id']}/merge_requests/{mr['iid']}/notes",
            sort="desc",
            order_by="created_at",
            per_page=50,
        )
        mr_link = link(mr["web_url"], f"{mr['references']['full']} {mr['title']}")
        for n in reversed(notes):
            if n["id"] in seen or parse_ts(n["created_at"]) < parse_ts(since):
                continue
            seen.add(n["id"])
            if n["author"]["id"] == me["id"]:
                continue
            who = esc(n["author"]["name"])
            body = n.get("body", "")
            if n.get("system"):
                if body.startswith("approved"):
                    msgs.append(f"*:white_check_mark: Approved* by {who}\n{mr_link}")
                elif body.startswith("unapproved"):
                    msgs.append(f"*:no_entry_sign: Approval revoked* by {who}\n{mr_link}")
                elif body.startswith("merged"):
                    msgs.append(f"*:tada: Merged* by {who}\n{mr_link}")
                continue
            # Mentions already come through the to-do list.
            if f"@{me['username']}" in body:
                continue
            msgs.append(f"*:speech_balloon: Comment* by {who} on your MR\n{mr_link}\n> {snippet(body)}")
    state["note_ids"] = trim(sorted(seen))
    return msgs


YT_ACTIVITY_FIELDS = (
    "id,timestamp,author(login,fullName),category(id),field(presentation),"
    "target(idReadable,summary,text,issue(idReadable,summary)),"
    "added(id,name,login,fullName,text,presentation),removed(name,login,fullName,presentation)"
)
YT_DEFAULT_QUERY = "for: me or reporter: me or commenter: me or tag: Star"


def yt_value(v) -> str:
    if isinstance(v, dict):
        return v.get("fullName") or v.get("name") or v.get("presentation") or v.get("login") or "?"
    return str(v)


def yt_values(vals) -> str:
    if vals is None:
        return "∅"
    if not isinstance(vals, list):
        vals = [vals]
    return ", ".join(yt_value(v) for v in vals) or "∅"


def collect_youtrack(yt: YouTrack, state: dict, cfg: dict) -> list[str]:
    since = since_with_margin(state)
    if not since:
        return []
    me = yt.get("/users/me", fields="login,fullName")
    login = me["login"]
    start_ms = int(datetime.fromisoformat(since).timestamp() * 1000)
    acts = yt.get(
        "/activities",
        categories="CommentsCategory,CustomFieldCategory,IssueCreatedCategory",
        start=start_ms,
        fields=YT_ACTIVITY_FIELDS,
    )
    seen_list = state.get("yt_activity_ids", [])
    seen = set(seen_list)
    acts = [a for a in sorted(acts, key=lambda a: a["timestamp"]) if a["id"] not in seen]
    for a in acts:
        seen_list.append(a["id"])
    state["yt_activity_ids"] = seen_list[-2000:]
    acts = [a for a in acts if (a.get("author") or {}).get("login") != login]
    if not acts:
        return []

    def issue_of(a: dict) -> dict:
        t = a.get("target") or {}
        return t.get("issue") or t

    # Which of the touched issues "concern me" according to youtrack_query?
    ids = sorted({issue_of(a).get("idReadable") for a in acts} - {None})
    query = cfg.get("youtrack_query") or YT_DEFAULT_QUERY
    mine = {
        i["idReadable"]
        for i in yt.get("/issues", query=f"({query}) and issue id: {', '.join(ids)}", fields="idReadable")
    } if ids else set()
    fields_wanted = set(cfg.get("youtrack_fields") or ["State", "Priority"])

    msgs = []
    for a in acts:
        issue = issue_of(a)
        iid = issue.get("idReadable")
        if not iid:
            continue
        who = esc((a.get("author") or {}).get("fullName") or "someone")
        ilink = link(yt.issue_url(iid), f"{iid} {issue.get('summary', '')}".strip())
        cat = (a.get("category") or {}).get("id")
        if cat == "CommentsCategory":
            for c in a.get("added") or []:
                text = c.get("text") or ""
                if f"@{login}" in text:
                    msgs.append(f"*:speech_balloon: Mentioned* by {who} (YouTrack)\n{ilink}\n> {snippet(text)}")
                elif iid in mine:
                    msgs.append(f"*:speech_balloon: Comment* by {who} (YouTrack)\n{ilink}\n> {snippet(text)}")
        elif cat == "CustomFieldCategory":
            fname = (a.get("field") or {}).get("presentation") or ""
            added = a.get("added") or []
            if fname == "Assignee" and any(v.get("login") == login for v in added if isinstance(v, dict)):
                msgs.append(f"*:bust_in_silhouette: Assigned to you* by {who} (YouTrack)\n{ilink}")
            elif iid in mine and fname in fields_wanted:
                msgs.append(
                    f"*:arrows_counterclockwise: {esc(fname)}*: {esc(yt_values(a.get('removed')))} → "
                    f"{esc(yt_values(added))} by {who} (YouTrack)\n{ilink}"
                )
        elif cat == "IssueCreatedCategory" and iid in mine:
            msgs.append(f"*:new: New issue* by {who} (YouTrack)\n{ilink}")
    return msgs


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def morning_due(state: dict, cfg: dict) -> bool:
    """True once per day, on the first run at/after morning_hour (local time)."""
    if not cfg.get("morning_greeting", True):
        return False
    now = datetime.now()
    if cfg.get("morning_weekdays_only", True) and now.weekday() >= 5:
        return False
    return now.hour >= int(cfg.get("morning_hour", 8)) and state.get("last_greeting") != now.date().isoformat()


def morning_message(gl: GitLab, yt: YouTrack | None, me: dict) -> str:
    first = (me.get("name") or me["username"]).split()[0]
    lines = [f"*:sunny: Bonjour {esc(first)} !*"]
    try:
        todos = gl.get("/todos", state="pending")
        reviews = gl.get("/merge_requests", reviewer_username=me["username"], state="opened", scope="all")
        mine = gl.get("/merge_requests", scope="created_by_me", state="opened")
        lines.append(f"• {len(todos)} to-do GitLab en attente")
        lines.append(f"• {len(reviews)} MR en attente de ta review")
        lines.append(f"• {len(mine)} MR ouverte(s) à toi")
        if yt:
            issues = yt.get("/issues", query="for: me #Unresolved", fields="idReadable")
            lines.append(f"• {len(issues)} issue(s) YouTrack non résolue(s) assignée(s) à toi")
    except (urllib.error.URLError, KeyError) as e:
        lines.append(f"_(résumé indisponible : {esc(str(e))})_")
    lines.append("Bonne journée :coffee:")
    return "\n".join(lines)


def run_once(
    gl: GitLab, yt: YouTrack | None, slack: Slack, cfg: dict, state_path: Path, dry_run: bool
) -> None:
    state = load_state(state_path)
    first_run = "last_run" not in state
    started = now_iso()
    me = gl.get("/user")

    msgs: list[str] = []
    if cfg.get("notify_todos", True):
        msgs += collect_todos(gl, state, cfg)
    if cfg.get("notify_new_mrs", True):
        msgs += collect_new_mrs(gl, state, cfg, me)
    if cfg.get("notify_my_mr_activity", True):
        msgs += collect_my_mr_activity(gl, state, cfg, me)
    if yt and cfg.get("notify_youtrack", True):
        msgs += collect_youtrack(yt, state, cfg)

    if first_run:
        print(f"First run: recorded {len(msgs)} existing item(s) as seen, nothing sent.")
        msgs = []

    greeting = morning_due(state, cfg)
    if greeting:
        msgs.insert(0, morning_message(gl, yt, me))

    for m in msgs:
        if dry_run:
            print("---\n" + m)
        else:
            slack.post(m)
            time.sleep(1.1)  # Slack rate limit: ~1 msg/s per channel

    state["last_run"] = started
    if greeting:
        state["last_greeting"] = datetime.now().date().isoformat()
    if not dry_run:
        save_state(state_path, state)
    print(f"[{started}] {len(msgs)} notification(s) {'(dry run)' if dry_run else 'sent'}.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=HERE / "config.toml", type=Path)
    ap.add_argument("--state", default=HERE / "state.json", type=Path)
    ap.add_argument("--loop", type=int, metavar="SECONDS", help="Keep running, polling every N seconds.")
    ap.add_argument("--dry-run", action="store_true", help="Print messages instead of posting; don't save state.")
    ap.add_argument("--test-slack", action="store_true", help="Send a test message and exit.")
    args = ap.parse_args()

    cfg = tomllib.loads(args.config.read_text())
    token = os.environ.get("GITLAB_TOKEN") or sys.exit("Set GITLAB_TOKEN (scope: read_api).")
    gl = GitLab(cfg["gitlab_url"], token)
    yt_token = os.environ.get("YOUTRACK_TOKEN")
    yt = YouTrack(cfg["youtrack_url"], yt_token) if yt_token and cfg.get("youtrack_url") else None
    slack = Slack(
        os.environ.get("SLACK_WEBHOOK_URL"),
        os.environ.get("SLACK_BOT_TOKEN"),
        os.environ.get("SLACK_CHANNEL") or cfg.get("slack_channel"),
        os.environ.get("SLACK_WORKFLOW_URL"),
    )

    if args.test_slack:
        try:
            slack.post(":wave: GitLab notifier is connected.")
        except RuntimeError as e:
            sys.exit(str(e))
        print("Test message sent.")
        return

    while True:
        try:
            run_once(gl, yt, slack, cfg, args.state, args.dry_run)
        except (urllib.error.URLError, RuntimeError) as e:
            print(f"[{now_iso()}] error: {e}", file=sys.stderr)
            if not args.loop:
                sys.exit(1)
        if not args.loop:
            return
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
