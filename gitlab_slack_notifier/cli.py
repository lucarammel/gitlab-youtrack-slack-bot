"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .clients import GitLab, Slack, YouTrack
from .config import Config, ConfigError
from .http import ApiError
from .runner import Notifier

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("notifier")

DESCRIPTION = """Poll GitLab (and YouTrack) and post notifications to a Slack conversation.

Sources: GitLab to-dos, new MRs on watched projects, activity and pipelines on your MRs,
YouTrack issues that concern you, plus a morning summary.
Config in config.toml, secrets in environment variables (see .env.example)."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-c", "--config", default=ROOT / "config.toml", type=Path)
    ap.add_argument("--state", default=ROOT / "state.json", type=Path)
    ap.add_argument("--loop", type=int, metavar="SECONDS", help="Keep running, polling every N seconds.")
    ap.add_argument("--dry-run", action="store_true", help="Print messages instead of posting; don't save state.")
    ap.add_argument("--flush", action="store_true", help="Deliver held notifications now, ignoring quiet hours.")
    ap.add_argument("--test-slack", action="store_true", help="Send a test message and exit.")
    return ap.parse_args(argv)


def build_slack(cfg: Config) -> Slack:
    return Slack(
        webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
        bot_token=os.environ.get("SLACK_BOT_TOKEN"),
        channel=os.environ.get("SLACK_CHANNEL") or cfg.slack_channel,
        workflow_url=os.environ.get("SLACK_WORKFLOW_URL"),
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    try:
        cfg = Config.load(args.config)
    except ConfigError as e:
        sys.exit(str(e))

    try:
        slack = None if args.dry_run and not args.test_slack else build_slack(cfg)
    except ValueError as e:
        sys.exit(str(e))

    if args.test_slack:
        try:
            slack.post(":wave: GitLab notifier is connected.")
        except ApiError as e:
            sys.exit(str(e))
        print(f"Test message sent ({slack.mode}).")
        return

    token = os.environ.get("GITLAB_TOKEN") or sys.exit("Set GITLAB_TOKEN (scope: read_api).")
    yt_token = os.environ.get("YOUTRACK_TOKEN")
    notifier = Notifier(
        cfg,
        GitLab(cfg.gitlab_url, token),
        slack,
        args.state,
        yt=YouTrack(cfg.youtrack_url, yt_token) if yt_token and cfg.youtrack_url else None,
        dry_run=args.dry_run,
    )

    while True:
        try:
            r = notifier.run_once(flush=args.flush)
            held = f", {r.held} held" if r.held else ""
            log.info("%d new, %d sent%s%s", r.collected, r.sent, held, " (dry run)" if args.dry_run else "")
        except ApiError as e:
            log.error("%s", e)
            if not args.loop:
                sys.exit(1)
        if not args.loop:
            return
        time.sleep(args.loop)
