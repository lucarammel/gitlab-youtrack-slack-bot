import unittest
from datetime import datetime

from gitlab_slack_notifier.config import Config, ConfigError
from gitlab_slack_notifier.delivery import Deliverer, compose, is_quiet
from gitlab_slack_notifier.filters import NotificationFilter
from gitlab_slack_notifier.formatting import mentions, short_ref, snippet, to_plain
from gitlab_slack_notifier.models import Notification

from .fakes import make_config

MONDAY_NOON = datetime(2026, 11, 9, 12, 0)
MONDAY_NIGHT = datetime(2026, 11, 9, 23, 0)
SATURDAY_NOON = datetime(2026, 11, 14, 12, 0)


def n(kind="mr_comment", text="hello", **kw) -> Notification:
    return Notification(kind, text, **kw)


class FormattingTest(unittest.TestCase):
    def test_mentions_whole_handle_only(self):
        self.assertTrue(mentions("ping @me please", "me"))
        self.assertTrue(mentions("thanks @me.", "me"))
        self.assertFalse(mentions("ping @meyer", "me"))
        self.assertFalse(mentions("ping @me.bot", "me"))

    def test_to_plain(self):
        self.assertEqual(to_plain(":tada: <https://x|A &amp; B>"), "🎉 A & B — https://x")

    def test_short_ref(self):
        self.assertEqual(short_ref("my-group/my-subgroup/my-project!1981"), "my-project!1981")
        self.assertEqual(short_ref("proj#12"), "proj#12")

    def test_snippet_strips_markdown(self):
        body = (
            "## SonarQube Code Analysis\n## Quality Gate passed\n"
            "Issues [![](https://s/passed-16px.png '')](https://s/x) 0 New issues\n"
            "- see **[the docs](https://d)**\n| a | b |\n|---|---|\n<details>`x = 1`</details> `test__run`"
        )
        self.assertEqual(
            snippet(body),
            "SonarQube Code Analysis Quality Gate passed Issues 0 New issues see the docs a b x = 1 test__run",
        )

    def test_to_plain_drops_mrkdwn_markers(self):
        text = "*:new: New MR* in `my-project` _(draft)_\n<https://x/deal_method_a|fix deal_method>\n> quoted"
        self.assertEqual(to_plain(text), "🆕 New MR in my-project (draft)\nfix deal_method — https://x/deal_method_a\n│ quoted")
        self.assertEqual(to_plain("*State of deal_method*: a → b"), "State of deal_method: a → b")


class NotificationTest(unittest.TestCase):
    def test_body_drops_subject_line(self):
        link = "<https://x/1|p!1 Fix>"
        self.assertEqual(n(text=f"*Comment* by A\n{link}\n> hi", subject=link).body, "*Comment* by A\n> hi")
        self.assertEqual(n(text=f"*Passed*\n{link} · <https://x/p|#5>", subject=link).body, "*Passed* · <https://x/p|#5>")
        self.assertEqual(n(text="plain").body, "plain")

    def test_roundtrip(self):
        x = n(subject="<u|s>", author="a", title="t")
        self.assertEqual(Notification.from_dict(x.to_dict()), x)


class ConfigTest(unittest.TestCase):
    def test_unknown_keys_warn(self):
        with self.assertLogs("gitlab_slack_notifier.config", "WARNING"):
            Config.from_dict({"gitlab_url": "u", "notfy_todos": False})

    def test_invalid_quiet_hours(self):
        with self.assertRaises(ConfigError):
            make_config(quiet_hours="7pm")

    def test_invalid_regex(self):
        with self.assertRaises(ConfigError):
            make_config(ignore_title_patterns=["("])


class QuietHoursTest(unittest.TestCase):
    def test_overnight_window(self):
        cfg = make_config(quiet_hours="19:00-08:30")
        self.assertTrue(is_quiet(MONDAY_NIGHT, cfg))
        self.assertTrue(is_quiet(datetime(2026, 11, 9, 8, 0), cfg))
        self.assertFalse(is_quiet(datetime(2026, 11, 9, 8, 30), cfg))
        self.assertFalse(is_quiet(MONDAY_NOON, cfg))

    def test_weekends(self):
        self.assertTrue(is_quiet(SATURDAY_NOON, make_config(quiet_weekends=True)))
        self.assertFalse(is_quiet(SATURDAY_NOON, make_config()))


class FilterTest(unittest.TestCase):
    def test_rules(self):
        f = NotificationFilter(
            make_config(ignore_authors=["@Renovate-Bot"], ignore_title_patterns=[r"^chore\(deps\)"], muted_kinds=["new_mr"])
        )
        self.assertFalse(f.allows(n(author="renovate-bot")))
        self.assertFalse(f.allows(n(title="chore(deps): bump x")))
        self.assertFalse(f.allows(n(kind="new_mr")))
        self.assertTrue(f.allows(n(author="alice", title="feat: x")))
        self.assertTrue(f.allows(n(kind="morning")))


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

    def test_quiet_hours_hold_except_bypass_and_system(self):
        sent = []
        d = Deliverer(sent.append, make_config(quiet_hours="19:00-08:30", quiet_bypass=["review_requested"]), sleep=lambda _: None)
        outbox = [n(text="held"), n(kind="review_requested", text="urgent"), n(kind="connectivity", text="down")]
        self.assertEqual(d.deliver(outbox, MONDAY_NIGHT), (2, 1))
        self.assertEqual(sorted(sent), ["down", "urgent"])
        self.assertEqual([x.text for x in outbox], ["held"])
        self.assertEqual(d.deliver(outbox, MONDAY_NIGHT, force=True), (1, 0))

    def test_failure_keeps_unsent(self):
        sent = []

        def post(text):
            if len(sent) == 1:
                raise RuntimeError("boom")
            sent.append(text)

        d = Deliverer(post, make_config(), sleep=lambda _: None)
        outbox = [n(text="a"), n(text="b")]
        with self.assertRaises(RuntimeError):
            d.deliver(outbox, MONDAY_NOON)
        self.assertEqual([x.text for x in outbox], ["b"])


if __name__ == "__main__":
    unittest.main()
