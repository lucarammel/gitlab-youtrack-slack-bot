# gitlab-slack-notifier

Polls GitLab and posts to a Slack conversation when:
- something lands in your GitLab To-Do list (mention, review request, assignment, failed pipeline, ...)
- a new MR is opened on a watched project
- someone comments on / approves / merges one of your MRs
- someone replies in one of your threads on an MR you review (even without @-mentioning you)
- the pipeline of one of your MRs finishes (green by default — "you can merge")
- YouTrack (optional): you're mentioned or assigned, or an issue that concerns you gets a comment,
  a change on a field listed in `youtrack_fields` (State, Priority, Activity…), or is created

Plus a morning greeting (once a day, first poll after `morning_hour`, weekdays) confirming the service
is up, with a short summary: pending GitLab to-dos, MRs awaiting your review (oldest first, with their
age and an :hourglass: past `stale_review_days`), your open MRs, your unresolved YouTrack issues.

Delivery features (see comments in `config.example.toml`):
- **Quiet hours** (`quiet_hours = "19:00-08:30"`, `quiet_weekends`): notifications are held and
  delivered when the quiet period ends; `quiet_bypass` lets urgent kinds through.
- **Grouping**: notifications about the same MR / issue are sent as one message, the link shown once.
- **Digest**: when `batch_threshold` or more notifications are pending at once (after quiet hours,
  after a laptop resume…), they are merged into a single message instead of flooding the channel
  (counted after grouping).
- **Ignore rules**: `ignore_authors` (bots…), `ignore_title_patterns` (regexes), `muted_kinds`.
- **Reliable delivery**: notifications go through an outbox persisted in `state.json`; if Slack fails
  halfway, the rest is sent on the next run (no loss, no duplicates).
- **Retries**: transient HTTP errors (429/5xx/timeouts) are retried with backoff.
- **Connectivity alert**: after `alert_after_failures` consecutive failed polls (VPN down…), one
  Slack alert, then a "back online" message once polling works again.

Polling (not GitLab webhooks) so it works from a laptop behind the VPN. Python 3.11+, no dependencies.
Linux, WSL and macOS.

## Quick start

```sh
# 1. Install (uv fetches Python 3.11+ if needed: https://docs.astral.sh/uv/getting-started/installation/)
uv tool install git+https://github.com/lucarammel/gitlab-youtrack-slack-bot

# 2. Set up: asks for your tokens and checks each one, sends a Slack test message,
#    suggests projects to watch, then offers to start the background service.
gitlab-slack-notifier init
```

That's it. Everything lives in `~/.config/gitlab-slack-notifier/` (`config.toml`, `secrets.env`,
`state.json`). The first run records what already exists and sends nothing; later runs notify what's new.

What `init` asks for:
- **GitLab token**: avatar → Edit profile → Access tokens → scope `read_api`.
- **Slack**: the team bot token (see [below](#team-slack-app-one-time-for-the-whole-team)); your DM is
  found from your GitLab email. No app? Use a Workflow Builder URL instead (see [Slack options](#slack-options)).
- **YouTrack token** (optional): Profile → Account Security → *New token* (scope YouTrack).

Tip: put `GITLAB_URL=https://gitlab.your-company.com` in your team's onboarding doc (or export it before
`init`) so it's pre-filled.

Day-to-day:

```sh
gitlab-slack-notifier --status          # last run, pending/held notifications, health
gitlab-slack-notifier --flush           # deliver held notifications now, ignoring quiet hours
gitlab-slack-notifier init              # change tokens / projects (current values are the defaults)
gitlab-slack-notifier install-service   # (re)install the background service
gitlab-slack-notifier uninstall-service # stop it
uv tool upgrade gitlab-slack-notifier   # update, then: gitlab-slack-notifier install-service
```

Logs: `journalctl --user -u gitlab-slack-notifier -f` (Linux / WSL),
`tail -f ~/.config/gitlab-slack-notifier/notifier.log` (macOS).
Fine-tuning (quiet hours, ignore rules, YouTrack fields…): edit `config.toml`, options documented in
[`config.example.toml`](config.example.toml), then `gitlab-slack-notifier install-service` to restart.

## Team Slack app (one time, for the whole team)

One Slack app serves everybody: each person gets DMs from it, matched by their GitLab email.

1. https://api.slack.com/apps → *Create New App* → *From a manifest* → paste
   [`slack-app-manifest.yml`](slack-app-manifest.yml) → *Install to workspace* (may need a Slack admin's approval).
2. Copy the *Bot User OAuth Token* (`xoxb-…`) and share it with the team through a password manager
   (not Slack / email). Anyone with it can post as the app, nothing more: it can't read messages.

## Slack options

- **Team bot** (above): DMs, nothing to set up per person. If your Slack email differs from your
  GitLab one, set `SLACK_EMAIL` in `secrets.env`, or `slack_channel` (your member ID, or a channel ID
  after `/invite @GitLab Notifier`) in `config.toml`.
- **Workflow Builder** (no app needed; paid plans only):
  1. Slack → Tools → Workflow Builder → New workflow → *Start from a webhook*.
  2. *Set up variables* → add a variable named `text` (type: Text).
  3. Add step *Messages → Send a message to a person* (pick yourself) or *to a channel*;
     message body = the `text` variable.
  4. **Publish**, copy the `https://hooks.slack.com/triggers/…` URL.

  Links show up as `title — url` because workflow variables don't render Slack link markup.
  If the test fails with `workflow_not_published`, (re)publish the workflow — any edit after
  publishing needs a new publish.
- **Incoming webhook**: an app → Incoming Webhooks → add to a channel → copy the URL.

## Configuration reference

The config directory is, in order: `--home DIR`, `$NOTIFIER_HOME`, the current directory if it
contains a `config.toml` (running from a clone), else `~/.config/gitlab-slack-notifier`.

Secrets are read from the environment, then from `secrets.env` / `.env` in that directory
(see [`.env.example`](.env.example)): `GITLAB_TOKEN`, `SLACK_BOT_TOKEN` (+ optional `SLACK_CHANNEL`,
`SLACK_EMAIL`), `SLACK_WORKFLOW_URL`, `SLACK_WEBHOOK_URL`, `YOUTRACK_TOKEN`. `GITLAB_URL` overrides
`gitlab_url`.

Other flags: `--dry-run` (print instead of posting, don't save state), `--test-slack`,
`--loop SECONDS`, `-v` (debug logs). `install-service` runs a systemd user unit on Linux / WSL
(WSL needs `[boot] systemd=true` in `/etc/wsl.conf`) or a launchd agent on macOS. On WSL, the VM
shuts down a while after the last WSL window closes; the service starts again with WSL.

Without the service: `gitlab-slack-notifier --loop 120` in a terminal / tmux, or cron
(`*/2 * * * * ~/.local/bin/gitlab-slack-notifier >> /tmp/notifier.log 2>&1`).

## Development

```
gitlab_slack_notifier/
  __main__.py                    # python3 -m gitlab_slack_notifier (also the `gitlab-slack-notifier` script)
  cli.py                         # argument parsing, main loop
  paths.py                       # config directory resolution, secrets.env loading
  wizard.py                      # `init`: interactive setup
  service.py                     # `install-service`: systemd / launchd
  runner.py                      # one cycle: collect → filter → outbox → deliver → save state
  config.py                      # typed Config (dataclass) + validation
  state.py                       # state.json: seen ids, outbox, last run
  models.py                      # Notification(kind, text, author, title)
  collectors/                    # one module per source, registered in collectors/__init__.py
    todos.py  new_mrs.py  my_mrs.py  review_replies.py  pipelines.py  youtrack.py
  delivery.py                    # quiet hours, digest composition, posting
  filters.py                     # ignore rules
  health.py                      # connectivity alert / recovery
  morning.py                     # daily greeting
  clients/                       # GitLab, YouTrack, Slack API clients
  http.py                        # JSON over urllib, retries, ApiError
tests/                           # stdlib unittest, with fake clients
```

From a clone: `python3 -m gitlab_slack_notifier …` uses the clone's code (and `./config.toml` if
present); `uv tool install --editable .` installs the command from it. Run the tests with
`python3 -m unittest`. To add a source: write `collectors/<name>.py` exposing
`collect(ctx) -> list[Notification]`, then register it in `COLLECTORS`.
