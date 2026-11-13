"""The unit of work passed from collectors to delivery."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Notification:
    kind: str  # e.g. "review_requested", "new_mr", "pipeline_success", "yt_comment", "morning"
    text: str  # Slack mrkdwn
    author: str | None = None  # GitLab username / YouTrack login
    title: str | None = None  # MR / issue title

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Notification:
        return cls(kind=d["kind"], text=d["text"], author=d.get("author"), title=d.get("title"))
