# Cronloop for Codex CLI

[简体中文](README.zh-CN.md) · [Example](examples/benchmark-monitoring.md) · [MIT License](LICENSE)

Cronloop turns a short request such as “check this experiment every 30 minutes” into a guarded, recurring resume of the **exact current Codex CLI thread**. Each wake-up runs one evidence-driven round, records status and logs, and removes only its own cron entry after the completion condition is verified.

![Cronloop architecture](docs/images/architecture.svg)

## Why Cronloop

Long experiments often outlive one interactive Codex turn. A plain cron command can wake a process, but it does not preserve the agent's context or define when recovery is safe. Cronloop adds that missing contract:

- exact-thread resume; never a best-effort `--last` lookup;
- one bounded agent round per wake-up—no sleeping agent and no nested scheduler;
- duplicate-run protection with file locking and a recent-activity window;
- explicit scope, checks, recovery authority, reporting, and completion criteria;
- timeout shorter than the interval and optional completion-file fast path;
- marker-scoped, idempotent crontab updates that preserve unrelated entries;
- local audit trail with permission-restricted prompt, config, status, and logs.

Cronloop is a local fallback. Prefer a product-native scheduled-task feature when one is available for your environment.

## Requirements

- Linux or another Unix-like host with `cron`, `crontab`, and `flock` support
- Python 3.9+
- An authenticated `codex` CLI
- A locally resumable Codex thread with `CODEX_THREAD_ID` available

The runner has no third-party Python dependencies.

## Install

```bash
git clone https://github.com/Micuks/codex-cronloop-skill.git
mkdir -p ~/.codex/skills
ln -s "$PWD/codex-cronloop-skill/cronloop" ~/.codex/skills/cronloop
```

Restart Codex CLI if the skill is not discovered in the current process. To install without a symlink, copy the `cronloop/` directory to `~/.codex/skills/cronloop/`.

## Quick start

Ask from the Codex thread that should own the recurring work:

```text
$cronloop 30m monitor ./runs/exp-42. Check process health, logs, result validity,
and free disk space. Safely restart only after proving the runner is dead and no
duplicate exists. Stop after all 3 rounds pass validation and results.xlsx is built.
```

The skill expands the request into a bounded operating contract, shows it for review when needed, installs the cron entry, verifies daemon/marker status, and reports the job ID and removal command.

![Example install and status output](docs/images/demo-terminal.svg)

Inspect or stop a job directly:

```bash
python3 ~/.codex/skills/cronloop/scripts/cronloop.py list
python3 ~/.codex/skills/cronloop/scripts/cronloop.py status --job-id benchmark-watch
python3 ~/.codex/skills/cronloop/scripts/cronloop.py remove --job-id benchmark-watch
```

Supported intervals are `30m`, hour divisors of 24 (`1h`, `2h`, `3h`, `4h`, `6h`, `8h`, `12h`), and `1d`. Intervals below 30 minutes are intentionally rejected.

## Effect example

The included [benchmark-monitoring example](examples/benchmark-monitoring.md) models an 8-configuration × 15-query × 3-round experiment:

1. Every 30 minutes, Cronloop resumes the same thread and inspects the runner, newest logs, result matrix, disk, and host load.
2. If progress is healthy, it reports evidence and leaves the run untouched.
3. If the runner is absent, it diagnoses the failure and may perform only the explicitly authorized, duplicate-safe recovery.
4. When every matrix cell is valid, it builds the final table, verifies the artifact, reports completion, and removes its own marked cron block.

This pattern keeps the agent in the loop without keeping a model process alive between checks.

## Safety model

| Risk | Guardrail |
|---|---|
| Wrong conversation resumed | Exact UUID and exact local rollout are required |
| Overlapping agent runs | Non-blocking file lock plus recent-thread activity check |
| Runaway invocation | Per-run timeout is shorter than the schedule interval |
| Prompt leaks credentials | Secret-like assignments are rejected; stored files use mode `0600` |
| Proxy leaks credentials | Credential-bearing proxy URLs are not persisted |
| Existing crontab is damaged | Only a named `BEGIN/END CRONLOOP` block is replaced or removed |
| Recovery exceeds authority | Expanded prompt must state scope, allowed recovery, and forbidden actions |
| Loop survives completion | Verified completion triggers its per-job removal command |

Cronloop never uses approval-bypass flags and does not claim it can wake a web/API chat. It only resumes threads that the local Codex CLI can locate and resume.

## Repository layout

```text
cronloop/                 installable Codex skill
  SKILL.md
  agents/openai.yaml
  scripts/cronloop.py
docs/images/              versioned diagrams used by both READMEs
examples/                 expanded prompt and representative artifacts
tests/                    isolated tests with fake crontab and fake Codex binary
```

## Development

```bash
python3 -m unittest discover -s tests -v
python3 cronloop/scripts/cronloop.py --help
```

Tests use temporary files and never install a real crontab entry or resume a real thread.

## License

[MIT](LICENSE)
