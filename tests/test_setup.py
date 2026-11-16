import os
import plistlib
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

from gitlab_slack_notifier import cli, service, wizard
from gitlab_slack_notifier.config import Config
from gitlab_slack_notifier.paths import (
    load_secrets,
    parse_env,
    resolve_home,
    write_secrets,
)

from .fakes import make_config


class PathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_env(self):
        text = (
            "# comment\n"
            "export GITLAB_TOKEN=glpat-abc          # personal access token\n"
            "SLACK_WEBHOOK_URL=https://x/y#frag\n"
            "QUOTED='a b # not a comment'\n"
            "EMPTY=\n"
            "not a line\n"
        )
        self.assertEqual(
            parse_env(text),
            {"GITLAB_TOKEN": "glpat-abc", "SLACK_WEBHOOK_URL": "https://x/y#frag", "QUOTED": "a b # not a comment",
             "EMPTY": ""},
        )

    def test_secrets_roundtrip_private_and_env_wins(self):
        path = self.dir / "secrets.env"
        write_secrets(path, {"GITLAB_TOKEN": "t$o'k", "SLACK_WORKFLOW_URL": "", "YOUTRACK_TOKEN": "perm:1"})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn("SLACK_WORKFLOW_URL", path.read_text())
        with mock.patch.dict(os.environ, {"YOUTRACK_TOKEN": "from-env"}, clear=True):
            load_secrets(self.dir)
            self.assertEqual(os.environ["GITLAB_TOKEN"], "t$o'k")
            self.assertEqual(os.environ["YOUTRACK_TOKEN"], "from-env")

    def test_resolve_home(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.dir / "xdg")}, clear=True):
            self.assertEqual(resolve_home(cwd=self.dir), self.dir / "xdg" / "gitlab-slack-notifier")
            (self.dir / "config.toml").write_text("")
            self.assertEqual(resolve_home(cwd=self.dir), self.dir.resolve())
            os.environ["NOTIFIER_HOME"] = str(self.dir / "env")
            self.assertEqual(resolve_home(cwd=self.dir), (self.dir / "env").resolve())
            self.assertEqual(resolve_home(self.dir / "arg", cwd=self.dir), (self.dir / "arg").resolve())

    def test_gitlab_url_env_override(self):
        path = self.dir / "config.toml"
        path.write_text('gitlab_url = "https://a"\n')
        self.assertEqual(Config.load(path, {"GITLAB_URL": "https://b"}).gitlab_url, "https://b")
        self.assertEqual(Config.load(path, {}).gitlab_url, "https://a")


class FakeGL:
    def __init__(self, url, token):
        if token != "good":
            raise_api("401 Unauthorized")

    def current_user(self):
        return {"id": 1, "username": "me", "email": "me@corp.example"}

    def recent_projects(self):
        return ["grp/api", "grp/web"]


class FakeSlack:
    posts: ClassVar[list] = []

    def __init__(self, **kw):
        self.kw = kw

    @staticmethod
    def lookup_user_id(token, email):
        return "U123" if email == "me@corp.example" else raise_api("users_not_found")

    def post(self, text):
        FakeSlack.posts.append((self.kw, text))


def raise_api(msg):
    from gitlab_slack_notifier.http import ApiError

    raise ApiError(msg)


class WizardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        FakeSlack.posts = []
        patches = [mock.patch.object(wizard, "GitLab", FakeGL), mock.patch.object(wizard, "Slack", FakeSlack)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_wizard(self, answers, secrets):
        answers, secrets = iter(answers), iter(secrets)
        p = wizard.Prompter(ask=lambda q: next(answers), secret=lambda q: next(secrets))
        with mock.patch("builtins.print"):
            return wizard.run(self.home, p, env={})

    def test_bot_flow_finds_slack_user_by_gitlab_email(self):
        install = self.run_wizard(
            # url, (retry after bad token), slack mode, projects, youtrack?, install?
            ["https://gitlab.corp", "y", "", "", "2, other/proj", "n", "y"],
            ["bad", "good", "xoxb-1"],
        )
        self.assertTrue(install)
        cfg = tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(cfg["gitlab_url"], "https://gitlab.corp")
        self.assertEqual(cfg["slack_channel"], "U123")
        self.assertEqual(cfg["watched_projects"], ["grp/web", "other/proj"])
        self.assertNotIn("youtrack_url", cfg)
        self.assertEqual(
            parse_env((self.home / "secrets.env").read_text()), {"GITLAB_TOKEN": "good", "SLACK_BOT_TOKEN": "xoxb-1"}
        )
        self.assertEqual(FakeSlack.posts[0][0], {"bot_token": "xoxb-1", "channel": "U123"})

    def test_workflow_flow_and_rerun_keeps_defaults(self):
        self.run_wizard(["", "2", "1", "n", "n"], ["good", "https://hooks.slack.com/triggers/x"])
        cfg = tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(cfg["gitlab_url"], "https://gitlab.com")
        self.assertEqual(cfg["watched_projects"], ["grp/api"])
        # Re-run: decline reconfiguring → nothing changes.
        self.assertFalse(self.run_wizard(["n"], []))


class BuildSlackTest(unittest.TestCase):
    def test_bot_without_channel_dms_gitlab_email(self):
        gl = mock.Mock()
        gl.current_user.return_value = {"email": "me@corp.example"}
        with mock.patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb"}, clear=True), \
                mock.patch.object(cli.Slack, "lookup_user_id", return_value="U9") as lookup:
            slack = cli.build_slack(make_config(), gl)
        lookup.assert_called_once_with("xoxb", "me@corp.example")
        self.assertEqual(slack.channel, "U9")

    def test_configured_channel_skips_lookup(self):
        with mock.patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb"}, clear=True), \
                mock.patch.object(cli.Slack, "lookup_user_id") as lookup:
            slack = cli.build_slack(make_config(slack_channel="C1"), mock.Mock())
        lookup.assert_not_called()
        self.assertEqual(slack.channel, "C1")


class ServiceTest(unittest.TestCase):
    def test_systemd_unit_from_source_checkout(self):
        unit = service.systemd_unit(Path("/h"), 60)
        self.assertIn("--home /h --loop 60", unit)
        self.assertIn(f"Environment=PYTHONPATH={Path(service.__file__).resolve().parent.parent}", unit)

    def test_launchd_plist_is_valid(self):
        plist = plistlib.loads(service.launchd_plist(Path("/h & co"), 120).encode())
        self.assertEqual(plist["ProgramArguments"][-4:], ["--home", "/h & co", "--loop", "120"])
        self.assertTrue(plist["KeepAlive"])
        self.assertIn("PYTHONPATH", plist["EnvironmentVariables"])
