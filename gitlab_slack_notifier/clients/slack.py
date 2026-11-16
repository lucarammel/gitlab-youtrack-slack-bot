from __future__ import annotations

import urllib.parse

from ..formatting import to_plain
from ..http import ApiError, request, request_json


class Slack:
    """Posts to Slack through a Workflow Builder trigger, an incoming webhook, or a bot token."""

    def __init__(
        self,
        webhook_url: str | None = None,
        bot_token: str | None = None,
        channel: str | None = None,
        workflow_url: str | None = None,
    ):
        if not (workflow_url or webhook_url or (bot_token and channel)):
            raise ValueError("Set SLACK_WORKFLOW_URL, SLACK_WEBHOOK_URL, or SLACK_BOT_TOKEN + SLACK_CHANNEL.")
        # A Workflow Builder URL (/triggers/) put in SLACK_WEBHOOK_URL: treat it as a workflow.
        if not workflow_url and webhook_url and "/triggers/" in webhook_url:
            workflow_url, webhook_url = webhook_url, None
        self.workflow_url = workflow_url
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.channel = channel

    @staticmethod
    def lookup_user_id(bot_token: str, email: str) -> str:
        """Slack member ID for `email` (the bot needs the `users:read.email` scope)."""
        data, _ = request_json(
            "https://slack.com/api/users.lookupByEmail?" + urllib.parse.urlencode({"email": email}),
            headers={"Authorization": f"Bearer {bot_token}"},
        )
        if not data.get("ok"):
            raise ApiError(f"Slack users.lookupByEmail({email}): {data.get('error')}")
        return data["user"]["id"]

    @property
    def mode(self) -> str:
        return "workflow" if self.workflow_url else "webhook" if self.webhook_url else "bot"

    def post(self, text: str) -> None:
        if self.workflow_url:
            # Workflow Builder webhook trigger: body keys must match the declared variables.
            request(self.workflow_url, data={"text": to_plain(text)})
            return
        payload = {"text": text, "unfurl_links": False, "unfurl_media": False}
        if self.webhook_url:
            request(self.webhook_url, data=payload)
            return
        data, _ = request_json(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {self.bot_token}"},
            data={**payload, "channel": self.channel},
        )
        if not data.get("ok"):
            raise ApiError(f"Slack error: {data.get('error')}")
