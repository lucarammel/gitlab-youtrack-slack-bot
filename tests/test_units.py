import unittest

from gitlab_slack_notifier.config import Config
from gitlab_slack_notifier.delivery import Deliverer, compose
from gitlab_slack_notifier.formatting import mentions, to_plain
from gitlab_slack_notifier.models import Notification

from .fakes import make_config


def n(kind="mr_comment", text="hello", **kw) -> Notification:
    return Notification(kind, text, **kw)


class FormattingTest(unittest.TestCase):
    def test_mentions_whole_handle_only(self):
        self.assertTrue(mentions("ping @me please", "me"))
        self.assertTrue(mentions("thanks @me.", "me"))
        self.assertFalse(mentions("ping @meyer", "me"))
        self.assertFalse(mentions("ping @me.bot", "me"))

    def test_to_plain(self):
        self.assertEqual(to_plain(":tada: <https://x|A &amp; B>"), "🎉 A & B (https://x)")


class ConfigTest(unittest.TestCase):
    def test_unknown_keys_warn(self):
        with self.assertLogs("gitlab_slack_notifier.config", "WARNING"):
            Config.from_dict({"gitlab_url": "u", "notfy_todos": False})


class DeliveryTest(unittest.TestCase):
    def test_compose_individual_below_threshold(self):
        msgs = compose([n(text="a"), n(text="b")], batch_threshold=3)
        self.assertEqual([m.text for m in msgs], ["a", "b"])

    def test_compose_digest_keeps_system_separate(self):
        items = [n(kind="morning", text="hi")] + [n(text=f"m{i}") for i in range(3)]
        msgs = compose(items, batch_threshold=3)
        self.assertEqual(msgs[0].text, "hi")
        self.assertEqual(len(msgs), 2)
        self.assertIn("3 notifications", msgs[1].text)
        self.assertIn("m2", msgs[1].text)

    def test_compose_digest_chunks_long_messages(self):
        items = [n(text="x" * 1000) for _ in range(10)]
        msgs = compose(items, batch_threshold=2)
        self.assertGreater(len(msgs), 1)
        self.assertEqual(sum(len(m.items) for m in msgs), 10)
        self.assertTrue(all(len(m.text) <= 3500 for m in msgs))

    def test_failure_keeps_unsent(self):
        sent = []

        def post(text):
            if len(sent) == 1:
                raise RuntimeError("boom")
            sent.append(text)

        d = Deliverer(post, make_config(), sleep=lambda _: None)
        outbox = [n(text="a"), n(text="b")]
        with self.assertRaises(RuntimeError):
            d.deliver(outbox)
        self.assertEqual([x.text for x in outbox], ["b"])


if __name__ == "__main__":
    unittest.main()
