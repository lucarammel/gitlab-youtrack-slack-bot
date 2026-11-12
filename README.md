# gitlab-slack-notifier

Polls GitLab and posts to a Slack conversation when:
- something lands in your GitLab To-Do list (mention, review request, assignment, failed pipeline, ...)
- a new MR is opened on a watched project
- someone comments on / approves / merges one of your MRs

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
     4. Publish, copy the `https://hooks.slack.com/triggers/…` URL into `SLACK_WORKFLOW_URL`.

     Links show up as `title (url)` because workflow variables don't render Slack link markup.
3. Configure:
   ```sh
   cp config.example.toml config.toml   # edit projects / channel
   cp .env.example .env                 # fill in tokens
   source .env
   ./notifier.py --test-slack           # checks Slack
   ./notifier.py --dry-run              # checks GitLab, prints instead of posting
   ./notifier.py                        # first real run: records existing items, sends nothing
   ```

## Running

- In a terminal / tmux: `./notifier.py --loop 120`
- Cron (every 2 min): `*/2 * * * * cd ~/repos/gitlab-slack-notifier && . ./.env && ./notifier.py >> notifier.log 2>&1`
