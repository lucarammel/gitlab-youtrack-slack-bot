"""Slack mrkdwn helpers."""

from __future__ import annotations

import re
from datetime import datetime

EMOJI = {
    "arrows_counterclockwise": "🔄", "bookmark": "🔖", "bust_in_silhouette": "👤", "coffee": "☕",
    "eyes": "👀", "key": "🔑",
    "new": "🆕", "no_entry_sign": "🚫",
    "speech_balloon": "💬", "sunny": "☀️", "tada": "🎉", "warning": "⚠️",
    "wave": "👋", "white_check_mark": "✅", "x": "❌",
}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str, text: str) -> str:
    return f"<{url}|{esc(text)}>"


def snippet(body: str, n: int = 200) -> str:
    body = " ".join(body.split())
    return esc(body if len(body) <= n else body[: n - 1] + "…")


def to_plain(text: str) -> str:
    """Workflow Builder variables render neither <url|label> links nor :emoji: shortcodes:
    turn links into 'label (url)' and shortcodes into Unicode emoji."""
    text = re.sub(r":([a-z_]+):", lambda m: EMOJI.get(m.group(1), m.group(0)), text)
    text = re.sub(r"<([^|>]+)\|([^>]*)>", r"\2 (\1)", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
