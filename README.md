# GitLab → Slack notifier

Get a Slack DM when something on GitLab (and YouTrack) needs you, so you can stop refreshing tabs.

## What it looks like

Someone needs you on GitLab:

> **👀 Review requested** by Alice Martin\
> [api!412 Add rate limiting to the export endpoint](#)

Activity on your MR, grouped in one message:

> [api!398 Cache pricing results](#)\
> **💬 Comment** by Bob Durand on your MR\
> │ Looks good, just one question about the TTL\
> **✅ Approved** by Bob Durand\
> **🟢 Pipeline passed** on your MR · #88123

> **🎉 Merged**\
> [api!398 Cache pricing results](#)

A reply in a thread you started while reviewing (no @-mention needed):

> **↩️ Reply** by Alice Martin in your thread\
> [web!77 New onboarding flow](#)\
> │ Good catch, fixed in the last commit

YouTrack (optional):

> **🔄 State**: In Progress → Done\
> [PROJ-1234 Export fails on large files](#)

Every morning:

> **☀️ Bonjour Camille !**\
> • 3 to-do GitLab en attente\
> • 2 MR en attente de ta review :\
> &nbsp;&nbsp;&nbsp;&nbsp;– [web!77 New onboarding flow](#) · 3 j ⏳\
> &nbsp;&nbsp;&nbsp;&nbsp;– [api!412 Add rate limiting to the export endpoint](#) · 0 j\
> • 1 MR ouverte(s) à toi\
> Bonne journée ☕

Every Monday (and on the 1st for the month):

> **📊 Récap de la semaine · du 9 au 15 nov.**\
> • 🎉 3 MR mergées · délai moyen avant merge : 1,5 j\
> • 🆕 2 MR ouvertes\
> • 👀 Reviews : 4 MR approuvées, 12 commentaires sur des MR\
> • ⬆️ 59 commits poussés\
> • 📅 5 jours d'activité\
> • 📁 Repos les plus actifs : api (18), web (5)

Also: new MRs on projects you watch, mentions, assignments, failed pipelines. When many arrive at
once (after a meeting, in the morning after quiet hours…), they come as a single digest.

## Install (2 minutes)

```sh
uv tool install git+https://github.com/lucarammel/gitlab-youtrack-slack-bot
gitlab-slack-notifier init
```

No `uv` yet? [Install it first](https://docs.astral.sh/uv/getting-started/installation/).

`init` walks you through everything, checks each step and sends you a test message on Slack. Have these ready:

- **GitLab token**: avatar → *Edit profile* → *Access tokens* → scope `read_api`
- **Slack bot token** (`xoxb-…`): ask your team, it's shared once for everybody (see [below](#for-the-team-admin-create-the-slack-app))
- **YouTrack token** (optional): *Profile* → *Account Security* → *New token*

At the end, it starts in the background and keeps running after a reboot. Nothing is sent for what
already exists; you're only notified about what's new.

## Everyday commands

```sh
gitlab-slack-notifier --status          # is it running fine? anything waiting?
gitlab-slack-notifier --flush           # send held notifications now (quiet hours)
gitlab-slack-notifier recap             # last week's recap now (`recap month` for last month)
gitlab-slack-notifier init              # change tokens or watched projects
gitlab-slack-notifier uninstall-service # stop it
```

**Update** to the latest version:

```sh
uv tool upgrade gitlab-slack-notifier && gitlab-slack-notifier install-service
```

## Customize

Edit `~/.config/gitlab-slack-notifier/config.toml`, then run `gitlab-slack-notifier install-service`
to apply. The most useful options:

```toml
quiet_hours = "19:00-08:30"   # hold notifications at night, get them in the morning
quiet_weekends = true
morning_hour = 9              # time of the morning summary
weekly_recap = true           # Monday recap of last week
monthly_recap = true          # recap of last month, on the 1st
ignore_authors = ["renovate-bot"]          # silence bots
ignore_title_patterns = ["^chore\\(deps\\)"]
```

Every option is explained in [`config.example.toml`](config.example.toml).

## Something's wrong?

- **No messages**: run `gitlab-slack-notifier --status`, then check the logs:
  `journalctl --user -u gitlab-slack-notifier -f` (Linux / WSL) or
  `tail -f ~/.config/gitlab-slack-notifier/notifier.log` (macOS).
- **VPN down / GitLab unreachable**: you get one Slack alert, then a "back online" message.
  Nothing is lost in between.
- **WSL**: systemd must be enabled (`[boot] systemd=true` in `/etc/wsl.conf`). The notifier stops
  when WSL shuts down and starts again with it.
- **Your Slack email differs from your GitLab one**: add `SLACK_EMAIL=you@company.com` to
  `~/.config/gitlab-slack-notifier/secrets.env`.

## For the team admin: create the Slack app

Done once for the whole team. Everyone then gets DMs from the same app.

1. Go to https://api.slack.com/apps → *Create New App* → *From a manifest* → paste
   [`slack-app-manifest.yml`](slack-app-manifest.yml) → *Install to workspace* (may need a Slack admin).
2. Copy the *Bot User OAuth Token* (`xoxb-…`) and share it with the team through a password manager.
   It can only post messages, not read them.

No Slack app possible? `init` also accepts a Slack Workflow Builder webhook URL (paid plans):
*Workflow Builder* → *Start from a webhook* → add a `text` variable → *Send a message* to yourself
with that variable → *Publish* → copy the URL.

## Contributing

Python 3.11+, no dependencies. From a clone, `python3 -m gitlab_slack_notifier --dry-run` runs it
with the clone's code and prints messages instead of sending them; tests: `python3 -m unittest`.
