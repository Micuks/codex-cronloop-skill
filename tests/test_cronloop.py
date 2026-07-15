from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "cronloop" / "scripts" / "cronloop.py"
THREAD_ID = "12345678-1234-4234-8234-123456789abc"


class CronloopCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state_root = self.root / "state"
        self.codex_home = self.root / "codex-home"
        sessions = self.codex_home / "sessions" / "2026" / "07" / "13"
        sessions.mkdir(parents=True)
        (sessions / f"rollout-{THREAD_ID}.jsonl").write_text("{}\n")

        self.fake_codex = self.root / "codex"
        self.fake_codex.write_text("#!/bin/sh\nexit 0\n")
        self.fake_codex.chmod(0o755)

        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text(
            "Inspect the fake run once. Report evidence. Stop only after completion."
        )
        self.crontab = self.root / "crontab.txt"
        self.crontab.write_text("17 4 * * * /usr/local/bin/unrelated-backup\n")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=check,
        )

    def install(self, *extra: str) -> dict:
        result = self.cli(
            "install",
            "--interval",
            "30m",
            "--thread-id",
            THREAD_ID,
            "--workdir",
            str(self.root),
            "--prompt-file",
            str(self.prompt),
            "--job-id",
            "benchmark-watch",
            "--state-root",
            str(self.state_root),
            "--crontab-file",
            str(self.crontab),
            "--codex-home",
            str(self.codex_home),
            "--codex-bin",
            str(self.fake_codex),
            *extra,
        )
        return json.loads(result.stdout)

    def test_install_status_and_remove_preserve_unrelated_crontab(self) -> None:
        payload = self.install()
        self.assertEqual(payload["job_id"], "benchmark-watch")
        self.assertEqual(payload["schedule"], "*/30 * * * *")

        installed = self.crontab.read_text()
        self.assertIn("/usr/local/bin/unrelated-backup", installed)
        self.assertEqual(installed.count("# BEGIN CRONLOOP benchmark-watch"), 1)
        self.assertEqual(installed.count("# END CRONLOOP benchmark-watch"), 1)

        status = json.loads(
            self.cli(
                "status",
                "--job-id",
                "benchmark-watch",
                "--state-root",
                str(self.state_root),
                "--crontab-file",
                str(self.crontab),
            ).stdout
        )
        self.assertTrue(status["cron_marker_present"])
        self.assertEqual(status["config"]["thread_id"], THREAD_ID)

        self.cli(
            "remove",
            "--job-id",
            "benchmark-watch",
            "--state-root",
            str(self.state_root),
            "--crontab-file",
            str(self.crontab),
        )
        removed = self.crontab.read_text()
        self.assertIn("/usr/local/bin/unrelated-backup", removed)
        self.assertNotIn("CRONLOOP benchmark-watch", removed)
        config = json.loads(
            (self.state_root / "jobs" / "benchmark-watch" / "config.json").read_text()
        )
        self.assertFalse(config["enabled"])

    def test_reinstall_is_idempotent_and_files_are_private(self) -> None:
        self.install()
        self.install()
        installed = self.crontab.read_text()
        self.assertEqual(installed.count("# BEGIN CRONLOOP benchmark-watch"), 1)

        job = self.state_root / "jobs" / "benchmark-watch"
        self.assertEqual(os.stat(job).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(job / "prompt.txt").st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(job / "config.json").st_mode & 0o777, 0o600)

    def test_rejects_intervals_below_thirty_minutes(self) -> None:
        result = self.cli(
            "install",
            "--interval",
            "10m",
            "--thread-id",
            THREAD_ID,
            "--workdir",
            str(self.root),
            "--prompt-file",
            str(self.prompt),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least 30 minutes", result.stderr)

    def test_rejects_secret_like_prompt_assignments(self) -> None:
        self.prompt.write_text("Check the run once. token=do-not-store-this")
        result = self.cli(
            "install",
            "--interval",
            "30m",
            "--thread-id",
            THREAD_ID,
            "--workdir",
            str(self.root),
            "--prompt-file",
            str(self.prompt),
            "--state-root",
            str(self.state_root),
            "--codex-home",
            str(self.codex_home),
            "--codex-bin",
            str(self.fake_codex),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("appears to contain a secret", result.stderr)


class CronloopModelPinTest(unittest.TestCase):
    def test_fake_resume_receives_pinned_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex_home = root / "codex-home"
            sessions = codex_home / "sessions"
            sessions.mkdir(parents=True)
            (sessions / f"rollout-{THREAD_ID}.jsonl").write_text("{}\n")

            prompt = root / "prompt.txt"
            prompt.write_text(
                "Inspect fake state. Run exactly one round; do not sleep or schedule.\n"
            )
            crontab = root / "crontab"
            crontab.write_text("MAILTO=test@example.invalid\n")
            argv_log = root / "argv.txt"
            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$@\" > {shlex.quote(str(argv_log))}\n"
                "cat >/dev/null\n"
            )
            fake_codex.chmod(0o755)
            state_root = root / "state"

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "install",
                    "--interval",
                    "30m",
                    "--thread-id",
                    THREAD_ID,
                    "--workdir",
                    str(root),
                    "--prompt-file",
                    str(prompt),
                    "--job-id",
                    "fake-luna-monitor",
                    "--model",
                    "gpt-5.6-luna",
                    "--active-window",
                    "0",
                    "--codex-home",
                    str(codex_home),
                    "--codex-bin",
                    str(fake_codex),
                    "--state-root",
                    str(state_root),
                    "--crontab-file",
                    str(crontab),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--job-id",
                    "fake-luna-monitor",
                    "--state-root",
                    str(state_root),
                    "--crontab-file",
                    str(crontab),
                ],
                check=True,
            )
            self.assertEqual(
                argv_log.read_text().splitlines(),
                ["exec", "resume", "--model", "gpt-5.6-luna", THREAD_ID, "-"],
            )


class CronloopFeishuNotifyTest(unittest.TestCase):
    def test_completed_round_sends_last_message_with_fake_lark_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex_home = root / "codex-home"
            sessions = codex_home / "sessions"
            sessions.mkdir(parents=True)
            (sessions / f"rollout-{THREAD_ID}.jsonl").write_text("{}\n")
            prompt = root / "prompt.txt"
            prompt.write_text("Inspect fake state once, report, then return.\n")
            crontab = root / "crontab"
            crontab.write_text("")

            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                "#!/bin/sh\n"
                "out=\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = --output-last-message ]; then shift; out=$1; fi\n"
                "  shift\n"
                "done\n"
                "cat >/dev/null\n"
                "test -z \"$out\" || printf 'fake round is healthy\\n' > \"$out\"\n"
            )
            fake_codex.chmod(0o755)

            lark_argv = root / "lark-argv.txt"
            fake_lark = root / "lark-cli"
            fake_lark.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = whoami ]; then\n"
                "  printf '%s\\n' '{\"identity\":\"bot\",\"available\":true,\"tokenStatus\":\"ready\"}'\n"
                "  exit 0\n"
                "fi\n"
                f"printf '%s\\n' \"$@\" > {shlex.quote(str(lark_argv))}\n"
                "printf '%s\\n' '{\"ok\":true,\"data\":{\"message_id\":\"om_test\"}}'\n"
            )
            fake_lark.chmod(0o755)
            state_root = root / "state"

            installed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "install",
                    "--interval",
                    "30m",
                    "--thread-id",
                    THREAD_ID,
                    "--workdir",
                    str(root),
                    "--prompt-file",
                    str(prompt),
                    "--job-id",
                    "fake-feishu-monitor",
                    "--active-window",
                    "0",
                    "--codex-home",
                    str(codex_home),
                    "--codex-bin",
                    str(fake_codex),
                    "--notify",
                    "feishu-cli",
                    "--notify-target",
                    "ou_testuser",
                    "--notify-cli",
                    str(fake_lark),
                    "--state-root",
                    str(state_root),
                    "--crontab-file",
                    str(crontab),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(installed.stdout)["notify"]["target"], "ou_testuser")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--job-id",
                    "fake-feishu-monitor",
                    "--state-root",
                    str(state_root),
                    "--crontab-file",
                    str(crontab),
                ],
                check=True,
            )

            sent = lark_argv.read_text().splitlines()
            self.assertEqual(
                sent[:6],
                ["im", "+messages-send", "--as", "bot", "--user-id", "ou_testuser"],
            )
            self.assertIn("fake round is healthy", lark_argv.read_text())
            status = json.loads(
                (state_root / "jobs" / "fake-feishu-monitor" / "status.json").read_text()
            )
            self.assertEqual(status["last_notify_state"], "sent")
            self.assertEqual(status["last_notify_message_id"], "om_test")


if __name__ == "__main__":
    unittest.main()
