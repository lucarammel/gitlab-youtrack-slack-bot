#!/usr/bin/env python3
"""Entry point for the systemd unit / cron; the code lives in gitlab_slack_notifier/."""

from gitlab_slack_notifier.cli import main

if __name__ == "__main__":
    main()
