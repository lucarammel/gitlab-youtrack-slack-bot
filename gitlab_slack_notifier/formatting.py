"""Slack mrkdwn helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

EMOJI = {
    "arrows_counterclockwise": "🔄", "bookmark": "🔖", "bust_in_silhouette": "👤", "coffee": "☕",
    "electric_plug": "🔌", "eyes": "👀", "hourglass": "⏳", "inbox_tray": "📥", "key": "🔑",
    "large_green_circle": "🟢", "new": "🆕", "no_entry_sign": "🚫", "red_circle": "🔴",
    "rotating_light": "🚨", "speech_balloon": "💬", "sunny": "☀️", "tada": "🎉", "warning": "⚠️",
    "wave": "👋", "white_check_mark": "✅", "white_circle": "⚪", "x": "❌",
}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str, text: str) -> str:
    return f"<{url}|{esc(text)}>"


def snippet(body: str, n: int = 200) -> str:
    body = " ".join(body.split())
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
