"""The unit of work passed from collectors to delivery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Notification:
    kind: str  # e.g. "review_requested", "new_mr", "pipeline_success", "yt_comment", "morning"
    text: str  # Slack mrkdwn
    author: str | None = None  # GitLab username / YouTrack login
    title: str | None = None  # MR / issue title
