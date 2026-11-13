import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gitlab_slack_notifier.runner import Notifier

from .fakes import ME, FakeGitLab, FakeSlack, make_config, mr

MONDAY_NOON = datetime(2026, 11, 9, 12, 0)
RECENT = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()


def todo(id, action="review_requested", author="alice"):
    return {
        "id": id,
        "action_name": action,
        "target_url": f"https://gitlab.example.com/t/{id}",
        "target": {"title": f"MR {id}", "references": {"full": f"g/p!{id}"}},
        "author": {"username": author, "name": author.title()},
    }


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "state.json"
        self.gl = FakeGitLab()
        self.slack = FakeSlack()

    def tearDown(self):
        self.tmp.cleanup()

    def notifier(self, now=MONDAY_NOON, **cfg):
        cfg.setdefault("morning_greeting", False)
        c = make_config(**cfg)
        return Notifier(
            c, self.gl, self.slack, self.state_path,
            clock=lambda: now, sleep=lambda _: None,
        )

    def test_first_run_records_without_sending(self):
        self.gl.todos = [todo(1)]
        self.notifier().run_once()
        self.assertEqual(self.slack.sent, [])
        self.gl.todos = [todo(1), todo(2)]
        self.notifier().run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("MR 2", self.slack.sent[0])

    def test_my_mr_comments_skip_mentions_and_self(self):
        self.notifier().run_once()
        self.gl.my_mrs = [mr(100, 7, author=ME)]
        alice = {"id": 2, "username": "alice", "name": "Alice"}
        self.gl.notes[7] = [
            {"id": 1, "created_at": RECENT, "author": alice, "body": "nice", "system": False},
            {"id": 2, "created_at": RECENT, "author": alice, "body": "@me look", "system": False},
            {"id": 3, "created_at": RECENT, "author": ME, "body": "thx", "system": False},
            {"id": 4, "created_at": RECENT, "author": alice, "body": "approved this merge request", "system": True},
        ]
        self.notifier().run_once()
        self.assertEqual(len(self.slack.sent), 2)
        self.assertIn("Comment", self.slack.sent[0])
        self.assertIn("Approved", self.slack.sent[1])

    def test_morning_greeting_once_a_day(self):
        self.notifier().run_once()
        self.gl.review_mrs = [mr(200, 9)]
        self.notifier(morning_greeting=True).run_once()
        self.notifier(morning_greeting=True).run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("Bonjour Lucas", self.slack.sent[0])
        self.assertIn("1 MR en attente de ta review", self.slack.sent[0])


if __name__ == "__main__":
    unittest.main()
