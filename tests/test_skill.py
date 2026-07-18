from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "cronloop" / "SKILL.md"


class CronloopSkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL.read_text()

    def test_frontmatter_is_minimal_and_named_cronloop(self) -> None:
        match = re.match(r"^---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(match)
        keys = [line.split(":", 1)[0] for line in match.group(1).splitlines()]
        self.assertEqual(keys, ["name", "description"])
        self.assertIn("name: cronloop", match.group(1))

    def test_foreground_tty_protocol_is_explicit(self) -> None:
        for required in (
            "bash -lc 'sleep 1800'",
            "tty: true",
            "yield_time_ms: 30000",
            "yield_time_ms: 300000",
            'chars: ""',
        ):
            self.assertIn(required, self.text)

    def test_long_wait_must_not_be_refused_or_replaced(self) -> None:
        self.assertIn("Do not refuse, shorten, simulate, or replace the wait", self.text)
        self.assertIn("Do not replace the foreground wait with cron", self.text)
        self.assertIn("Do not claim that Codex or a foreground TTY has a 60-second process lifetime", self.text)

    def test_notifications_are_opt_in_and_fail_open(self) -> None:
        self.assertIn("Send notifications only when the user explicitly requests them", self.text)
        self.assertIn("Make delivery fail-open", self.text)
        self.assertIn("not after sleep polling chunks", self.text)

    def test_legacy_cron_runner_is_removed(self) -> None:
        self.assertFalse((ROOT / "cronloop" / "scripts" / "cronloop.py").exists())


if __name__ == "__main__":
    unittest.main()
