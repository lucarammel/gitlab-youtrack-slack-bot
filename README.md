# gitlab-slack-notifier

Polls GitLab and posts to a Slack conversation when:
- something lands in your GitLab To-Do list (mention, review request, assignment, failed pipeline, ...)
- a new MR is opened on a watched project
- someone comments on / approves / merges one of your MRs
- the pipeline of one of your MRs finishes (green by default — "you can merge")
- YouTrack (optional): you're mentioned or assigned, or an issue that concerns you gets a comment,
  a change on a field listed in `youtrack_fields` (State, Priority, Activity…), or is created

Plus a morning greeting (once a day, first poll after `morning_hour`, weekdays) confirming the service
is up, with a short summary: pending GitLab to-dos, MRs awaiting your review (oldest first, with their
age and an :hourglass: past `stale_review_days`), your open MRs, your unresolved YouTrack issues.

Delivery features (see comments in `config.example.toml`):
- **Quiet hours** (`quiet_hours = "19:00-08:30"`, `quiet_weekends`): notifications are held and
  delivered when the quiet period ends; `quiet_bypass` lets urgent kinds through.
- **Digest**: when `batch_threshold` or more notifications are pending at once (after quiet hours,
  after a laptop resume…), they are merged into a single message instead of flooding the channel.
- **Ignore rules**: `ignore_authors` (bots…), `ignore_title_patterns` (regexes), `muted_kinds`.
- **Reliable delivery**: notifications go through an outbox persisted in `state.json`; if Slack fails
  halfway, the rest is sent on the next run (no loss, no duplicates).
- **Retries**: transient HTTP errors (429/5xx/timeouts) are retried with backoff.
- **Connectivity alert**: after `alert_after_failures` consecutive failed polls (VPN down…), one
  Slack alert, then a "back online" message once polling works again.

Polling (not GitLab webhooks) so it works from a laptop behind the VPN. Python 3.11+, no dependencies.

## Setup

1. **GitLab token**: User settings → Access tokens → scope `read_api`.
2. **Slack** (pick one):
   - **Bot** (recommended, can DM you): https://api.slack.com/apps → Create app → OAuth & Permissions →
     bot scope `chat:write` → Install → copy `xoxb-…` token. Set `slack_channel` to your member ID
     (Profile → ⋮ → Copy member ID) to get DMs, or to a channel ID after `/invite @yourapp` in it.
   - **Incoming webhook**: app → Incoming Webhooks → add to a channel → copy the URL.
   - **Workflow Builder** (no app needed — use this if you can't create Slack apps; paid plans only):
     1. Slack → Tools → Workflow Builder → New workflow → *Start from a webhook*.
     2. *Set up variables* → add a variable named `text` (type: Text).
     3. Add step *Messages → Send a message to a person* (pick yourself) or *to a channel*;
        message body = the `text` variable.
     4. **Publish**, copy the `https://hooks.slack.com/triggers/…` URL into `SLACK_WORKFLOW_URL`
        (a `/triggers/` URL in `SLACK_WEBHOOK_URL` is detected and works too).

     Links show up as `title (url)` because workflow variables don't render Slack link markup.
     If `--test-slack` fails with `workflow_not_published`, (re)publish the workflow — any edit
     after publishing needs a new publish.
3. **YouTrack token** (optional): YouTrack → Profile → Account Security → *New token* (scope YouTrack)
   → `YOUTRACK_TOKEN` in `.env`. Tune `youtrack_query` / `youtrack_fields` in `config.toml`.
4. Configure:
   ```sh
   cp config.example.toml config.toml   # edit projects / channel
   cp .env.example .env                 # fill in tokens
   set -a; . ./.env; set +a
   ./notifier.py --test-slack           # checks Slack
   ./notifier.py --dry-run              # checks GitLab, prints instead of posting
   ./notifier.py                        # first real run: records existing items, sends nothing
   ./notifier.py --status               # last run, pending/held notifications, health
   ```

   `--flush` delivers held notifications immediately, ignoring quiet hours. `-v` enables debug logs.

## Running

### Start automatically with WSL / Linux (systemd user service — recommended)

Requires systemd (on WSL: `[boot] systemd=true` in `/etc/wsl.conf`). The unit file
[`gitlab-slack-notifier.service`](gitlab-slack-notifier.service) loads `.env` and runs
`notifier.py --loop 120`, restarting on failure. It assumes the repo is at `~/repos/gitlab-slack-notifier`
(edit `WorkingDirectory` otherwise).

```sh
mkdir -p ~/.config/systemd/user
cp gitlab-slack-notifier.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gitlab-slack-notifier
loginctl enable-linger "$USER"   # start at boot, without an interactive login
```

Day-to-day:

```sh
journalctl --user -u gitlab-slack-notifier -f        # follow logs
systemctl --user restart gitlab-slack-notifier       # after editing .env or config.toml
systemctl --user stop gitlab-slack-notifier          # stop
systemctl --user disable --now gitlab-slack-notifier # don't start at boot anymore
```

On WSL, the VM shuts down after a while with no WSL window open; the service starts again the
next time WSL boots.

### Alternatives

- In a terminal / tmux: `./notifier.py --loop 120`
- Cron (every 2 min): `*/2 * * * * cd ~/repos/gitlab-slack-notifier && . ./.env && ./notifier.py >> notifier.log 2>&1`

## Development

```
notifier.py                      # entry point (also: python3 -m gitlab_slack_notifier)
gitlab_slack_notifier/
  cli.py                         # argument parsing, main loop
  runner.py                      # one cycle: collect → filter → outbox → deliver → save state
  config.py                      # typed Config (dataclass) + validation
  state.py                       # state.json: seen ids, outbox, last run
  models.py                      # Notification(kind, text, author, title)
  collectors/                    # one module per source, registered in collectors/__init__.py
    todos.py  new_mrs.py  my_mrs.py  pipelines.py  youtrack.py
  delivery.py                    # quiet hours, digest composition, posting
  filters.py                     # ignore rules
  health.py                      # connectivity alert / recovery
  morning.py                     # daily greeting
  clients/                       # GitLab, YouTrack, Slack API clients
  http.py                        # JSON over urllib, retries, ApiError
tests/                           # stdlib unittest, with fake clients
```

Run the tests with `python3 -m unittest`. To add a source: write `collectors/<name>.py` exposing
`collect(ctx) -> list[Notification]`, then register it in `COLLECTORS`.
