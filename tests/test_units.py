import unittest

from gitlab_slack_notifier.config import Config
from gitlab_slack_notifier.formatting import mentions, to_plain


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


if __name__ == "__main__":
    unittest.main()
