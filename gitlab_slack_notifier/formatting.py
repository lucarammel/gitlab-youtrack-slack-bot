"""Slack mrkdwn helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

EMOJI = {
    "arrow_up": "⬆️", "arrows_counterclockwise": "🔄", "bar_chart": "📊", "bookmark": "🔖", "bust_in_silhouette": "👤", "calendar": "📅", "coffee": "☕",
    "electric_plug": "🔌", "eyes": "👀", "file_folder": "📁", "hourglass": "⏳", "inbox_tray": "📥", "key": "🔑",
    "large_green_circle": "🟢", "new": "🆕", "no_entry_sign": "🚫", "red_circle": "🔴",
    "rotating_light": "🚨", "speech_balloon": "💬", "sunny": "☀️", "tada": "🎉", "warning": "⚠️",
    "wave": "👋", "white_check_mark": "✅", "white_circle": "⚪", "x": "❌",
}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str, text: str) -> str:
    return f"<{url}|{esc(text)}>"


def strip_markdown(body: str) -> str:
    """Reduce a GitLab / YouTrack markdown comment to readable text for a one-line preview."""
    body = re.sub(r"```.*?```", " ", body, flags=re.S)  # code blocks
    body = re.sub(r"<!--.*?-->|<[^>\n]+>", " ", body, flags=re.S)  # HTML comments and tags
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)  # images
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)  # links -> their text
    body = re.sub(r"(?m)^\s*(#{1,6}|>|[-*+]|\d+\.)\s+", "", body)  # headings, quotes, list bullets
    body = re.sub(r"(?m)^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", "", body)  # table separator rows
    return re.sub(r"\*\*|~~|`|\|", " ", body)  # emphasis, code, table pipes (not "__": dunder names)


def short_ref(full: str) -> str:
    """'group/sub/project!12' -> 'project!12' (same for issues '#12')."""
    return full.rsplit("/", 1)[-1]


def snippet(body: str, n: int = 200) -> str:
    body = " ".join(strip_markdown(body).split())
    return esc(body if len(body) <= n else body[: n - 1] + "…")


def to_plain(text: str) -> str:
    """Workflow Builder variables are plain text: no <url|label> links, :emoji: shortcodes,
    *bold*, _italic_, `code` or > quotes. Turn links into 'label — url' (no brackets around the
    url: Slack's autolinker would include a closing one in the link), shortcodes into Unicode
    emoji, quotes into a bar, and drop the emphasis markers."""
    text = re.sub(r":([a-z_]+):", lambda m: EMOJI.get(m.group(1), m.group(0)), text)
    text = re.sub(r"<([^|>]+)\|([^>]*)>", r"\2 — \1", text)
    for mark in "*_`":
        m = re.escape(mark)
        text = re.sub(rf"(?<!\w){m}([^{m}\n]+){m}(?!\w)", r"\1", text)
    text = re.sub(r"(?m)^> ", "│ ", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def mentions(body: str, username: str) -> bool:
    """True if `body` contains @username as a whole handle (not @username2 or @username.bot)."""
    return re.search(rf"@{re.escape(username)}(?![\w.-]*\w)", body) is not None


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def age_days(ts: str, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return max(0, (now - parse_ts(ts)).days)
