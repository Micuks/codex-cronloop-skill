from __future__ import annotations

import json
import os
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
