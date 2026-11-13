import unittest

from gitlab_slack_notifier.config import Config
from gitlab_slack_notifier.delivery import Deliverer
from gitlab_slack_notifier.formatting import mentions, to_plain
from gitlab_slack_notifier.models import Notification


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
    def test_failure_keeps_unsent(self):
        sent = []

        def post(text):
            if len(sent) == 1:
                raise RuntimeError("boom")
            sent.append(text)

        d = Deliverer(post, sleep=lambda _: None)
        outbox = [n(text="a"), n(text="b")]
        with self.assertRaises(RuntimeError):
            d.deliver(outbox)
        self.assertEqual([x.text for x in outbox], ["b"])


if __name__ == "__main__":
    unittest.main()
