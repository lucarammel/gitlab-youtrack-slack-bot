"""The unit of work passed from collectors to delivery."""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Kinds that are always sent on their own and never held by quiet hours.
SYSTEM_KINDS = frozenset({"morning", "recap", "connectivity"})


@dataclass
class Notification:
    kind: str  # e.g. "review_requested", "new_mr", "pipeline_success", "yt_comment", "morning"
    text: str  # Slack mrkdwn
    author: str | None = None  # GitLab username / YouTrack login, used by ignore rules
    title: str | None = None  # MR / issue title, used by ignore rules
    subject: str | None = None  # mrkdwn link to the MR / issue, on its own line in `text`; used for grouping

    @property
    def is_system(self) -> bool:
        return self.kind in SYSTEM_KINDS

    @property
    def body(self) -> str:
        """`text` without the subject line (shown once per group instead)."""
        if not self.subject:
            return self.text
        lines = self.text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith(self.subject):
                rest = line[len(self.subject) :]
                if rest:  # e.g. " · <pipeline link>": keep it on the line above
                    lines[i - 1] += rest
                del lines[i]
                break
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Notification:
        return cls(
            kind=d["kind"], text=d["text"], author=d.get("author"), title=d.get("title"), subject=d.get("subject")
        )
