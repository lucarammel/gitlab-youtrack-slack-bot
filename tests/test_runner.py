import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gitlab_slack_notifier.delivery import Deliverer
from gitlab_slack_notifier.http import ApiError
from gitlab_slack_notifier.runner import Notifier
from gitlab_slack_notifier.state import State

from .fakes import ME, FakeGitLab, FakeSlack, make_config, mr

MONDAY_NOON = datetime(2026, 11, 9, 12, 0)
MONDAY_NIGHT = datetime(2026, 11, 9, 23, 0)
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
        cfg.setdefault("batch_threshold", 0)
        c = make_config(**cfg)
        return Notifier(
            c, self.gl, self.slack, self.state_path,
            clock=lambda: now, deliverer=Deliverer(self.slack.post, c, sleep=lambda _: None),
        )

    def test_first_run_records_without_sending(self):
        self.gl.todos = [todo(1)]
        self.notifier().run_once()
        self.assertEqual(self.slack.sent, [])
        self.gl.todos = [todo(1), todo(2)]
        self.notifier().run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("MR 2", self.slack.sent[0])

    def test_ignore_rules(self):
        self.notifier().run_once()
        self.gl.todos = [todo(1, author="renovate"), todo(2, author="bob")]
        self.notifier(ignore_authors=["renovate"]).run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("Bob", self.slack.sent[0])

    def test_quiet_hours_hold_then_deliver(self):
        self.notifier().run_once()
        self.gl.todos = [todo(1)]
        r = self.notifier(now=MONDAY_NIGHT, quiet_hours="19:00-08:30").run_once()
        self.assertEqual((r.sent, r.held), (0, 1))
        self.assertEqual(len(State.load(self.state_path).outbox), 1)
        r = self.notifier(now=MONDAY_NOON, quiet_hours="19:00-08:30").run_once()
        self.assertEqual((r.sent, r.held), (1, 0))

    def test_slack_failure_retries_next_run(self):
        self.notifier().run_once()
        self.gl.todos = [todo(1), todo(2)]
        self.slack.fail_after = 1
        with self.assertRaises(ApiError):
            self.notifier().run_once()
        self.slack.fail_after = None
        self.notifier().run_once()
        self.assertEqual(len(self.slack.sent), 2)
        self.assertIn("MR 2", self.slack.sent[1])

    def test_connectivity_alert_and_recovery(self):
        self.notifier().run_once()
        self.gl.todos = [todo(1)]
        self.gl.fail = True
        for _ in range(3):
            with self.assertRaises(ApiError):
                self.notifier(alert_after_failures=3).run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("can't poll", self.slack.sent[0])
        self.gl.fail = False
        self.notifier(alert_after_failures=3).run_once()
        self.assertIn("back online", self.slack.sent[1])
        self.assertIn("MR 1", self.slack.sent[2])  # nothing lost while failing

    def test_pipeline_success_notified_once(self):
        self.gl.my_mrs = [mr(100, 7, author=ME)]
        self.gl.pipelines[7] = {"id": 5, "status": "running", "created_at": RECENT, "updated_at": RECENT, "web_url": "u"}
        self.notifier().run_once()
        self.gl.pipelines[7] = {**self.gl.pipelines[7], "status": "success"}
        self.notifier().run_once()
        self.notifier().run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("Pipeline passed", self.slack.sent[0])

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

    def test_merge_of_my_mr_is_reported(self):
        self.notifier().run_once()
        alice = {"id": 2, "username": "alice", "name": "Alice"}
        self.gl.merged_mrs = [mr(101, 8, author=ME, state="merged")]
        self.gl.notes[8] = [{"id": 9, "created_at": RECENT, "author": alice, "body": "merged", "system": True}]
        self.notifier().run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("Merged", self.slack.sent[0])

    def test_morning_greeting_lists_stale_reviews(self):
        self.notifier().run_once()
        self.gl.review_mrs = [mr(200, 9, title="Old one", created_at="2026-01-01T00:00:00Z")]
        self.notifier(morning_greeting=True).run_once()
        self.notifier(morning_greeting=True).run_once()
        self.assertEqual(len(self.slack.sent), 1)
        self.assertIn("Bonjour Lucas", self.slack.sent[0])
        self.assertIn("Old one", self.slack.sent[0])
        self.assertIn(":hourglass:", self.slack.sent[0])


if __name__ == "__main__":
    unittest.main()
