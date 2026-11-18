"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import __version__, recap, service, wizard
from .clients import GitLab, Slack, YouTrack
from .config import Config, ConfigError
from .delivery import is_quiet
from .http import ApiError
from .paths import CONFIG_FILE, STATE_FILE, default_home, load_secrets, resolve_home
from .runner import Notifier
from .state import State

log = logging.getLogger("notifier")

DESCRIPTION = """Poll GitLab (and YouTrack) and post notifications to a Slack conversation.

Sources: GitLab to-dos, new MRs on watched projects, activity and pipelines on your MRs,
YouTrack issues that concern you, plus a morning summary.
First time: `gitlab-slack-notifier init`. Config in HOME/config.toml, secrets in HOME/secrets.env
(or environment variables, see .env.example)."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="gitlab-slack-notifier",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument(
        "--home", type=Path, help="Directory with config.toml, secrets.env and state.json "
        f"(default: $NOTIFIER_HOME, ./ if it has a config.toml, else {default_home()})."
    )
    ap.add_argument("-c", "--config", type=Path, help="Config file (default: HOME/config.toml).")
    ap.add_argument("--state", type=Path, help="State file (default: HOME/state.json).")
    ap.add_argument("--loop", type=int, metavar="SECONDS", help="Keep running, polling every N seconds.")
    ap.add_argument("--dry-run", action="store_true", help="Print messages instead of posting; don't save state.")
    ap.add_argument("--flush", action="store_true", help="Deliver held notifications now, ignoring quiet hours.")
    ap.add_argument("--test-slack", action="store_true", help="Send a test message and exit.")
    ap.add_argument("--status", action="store_true", help="Show state (last run, pending outbox, health) and exit.")
    ap.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    sub = ap.add_subparsers(dest="command", metavar="COMMAND")
    sub.add_parser("init", help="Interactive setup: tokens, Slack, projects (checks each step).")
    svc = sub.add_parser("install-service", help="Run in the background at boot (systemd on Linux/WSL, launchd on macOS).")
    svc.add_argument("--interval", type=int, default=120, metavar="SECONDS", help="Polling interval (default: 120).")
    sub.add_parser("uninstall-service", help="Stop and remove the background service.")
    rc = sub.add_parser("recap", help="Send the recap of your GitLab activity now (with --dry-run: print it).")
    rc.add_argument("period", choices=["week", "month"], nargs="?", default="week",
                    help="Last complete week (default) or month.")
    return ap.parse_args(argv)


def build_slack(cfg: Config, gitlab: GitLab | None = None) -> Slack:
    """Slack client from env vars. With a bot token and no channel, DMs the user found by email
    (SLACK_EMAIL, else the GitLab account's email)."""
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL") or cfg.slack_channel
    webhooks = os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_WORKFLOW_URL")
    if bot_token and not channel and not webhooks:
        email = os.environ.get("SLACK_EMAIL")
        if not email and gitlab:
            user = gitlab.current_user()
            email = user.get("email") or user.get("commit_email") or user.get("public_email")
        if email:
            channel = Slack.lookup_user_id(bot_token, email)
            log.info("Slack: sending DMs to %s (%s)", email, channel)
    return Slack(
        webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
        bot_token=bot_token,
        channel=channel,
        workflow_url=os.environ.get("SLACK_WORKFLOW_URL"),
    )


def show_status(cfg: Config, state_path: Path) -> None:
    state = State.load(state_path)
    outbox = state.outbox
    h = state.data.get("health") or {}
    now = datetime.now()
    print(f"State file     : {state_path}")
    print(f"Last run       : {state.last_run or 'never'}")
    print(f"Last greeting  : {state.data.get('last_greeting', 'never')}")
    print(f"Quiet now      : {'yes' if is_quiet(now, cfg) else 'no'} (quiet_hours={cfg.quiet_hours!r})")
    kinds = ", ".join(f"{k}×{n}" for k, n in Counter(n.kind for n in outbox).most_common())
    print(f"Outbox         : {len(outbox)} pending{f' ({kinds})' if kinds else ''}")
    if h.get("failures"):
        print(f"Health         : {h['failures']} consecutive failure(s) since {h.get('failing_since')}")
        print(f"Last error     : {h.get('last_error')}")
    else:
        print("Health         : OK")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    home = resolve_home(args.home)
    if args.command == "uninstall-service":
        service.uninstall()
        return
    if args.command == "init":
        if wizard.run(home):
            service.install(home)
        else:
            print("Start it later with: gitlab-slack-notifier install-service  (or --loop 120 in a terminal)")
        return
    if args.command == "install-service":
        service.install(home, args.interval)
        return

    load_secrets(home)
    config_path = args.config or home / CONFIG_FILE
    state_path = args.state or home / STATE_FILE
    try:
        cfg = Config.load(config_path, os.environ)
    except ConfigError as e:
        sys.exit(str(e))

    if args.status:
        show_status(cfg, state_path)
        return

    token = os.environ.get("GITLAB_TOKEN")
    gitlab = GitLab(cfg.gitlab_url, token) if token else None
    try:
        slack = None if args.dry_run and not args.test_slack else build_slack(cfg, gitlab)
    except (ValueError, ApiError) as e:
        sys.exit(str(e))

    if args.test_slack:
        try:
            slack.post(":wave: GitLab notifier is connected.")
        except ApiError as e:
            sys.exit(str(e))
        print(f"Test message sent ({slack.mode}).")
        return

    if not gitlab:
        sys.exit("Set GITLAB_TOKEN (scope: read_api), or run `gitlab-slack-notifier init`.")
    if args.command == "recap":
        try:
            msg = recap.message(gitlab, gitlab.current_user(), recap.previous(args.period, datetime.now().date()))
            (print if args.dry_run else slack.post)(msg.text)
        except ApiError as e:
            sys.exit(str(e))
        return

    yt_token = os.environ.get("YOUTRACK_TOKEN")
    notifier = Notifier(
        cfg,
        gitlab,
        slack,
        state_path,
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
