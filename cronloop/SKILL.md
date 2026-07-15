---
name: cronloop
description: Create, inspect, update, and remove safe recurring Codex CLI thread checks backed by cron, with optional Feishu CLI notifications. Use for requests such as `/cronloop 1h prompt`, `$cronloop`, periodic polling, health checks, experiment monitoring, recurring notifications, or a bounded task that should resume the current thread until a verified stop condition. Prefer a product-native Scheduled task when available; use this skill as the local CLI fallback.
---

# Cronloop

Turn a short monitoring request into one bounded action per scheduled wake-up, then install it with `scripts/cronloop.py`.

## Build the scheduled prompt

Before installing, infer and show the user a concise expanded prompt containing:

1. Scope and authoritative systems/artifacts to inspect.
2. Checks to perform each round, including progress, process health, logs, failures, resources, and result validity as relevant.
3. Safe recovery allowed without new authority. Require diagnosis from evidence, reversible actions, verification, and duplicate-start prevention.
4. Actions explicitly forbidden or out of scope.
5. Reporting fields, completeness rules, and handling of missing evidence.
6. A concrete completion condition and instruction to remove this cronloop only after verifying it.
7. “Run exactly one round; do not sleep, wait for the next round, or create another scheduler.”

Do not invent consequential recovery authority. If the short prompt leaves scope or completion materially ambiguous, ask one focused question before installing. Otherwise expand it using current conversation context. Store no passwords, tokens, private keys, or credential-bearing URLs in the prompt.

## Install

Require `CODEX_THREAD_ID`; never substitute `--last`. Save the expanded prompt to a permission-0600 temporary file, then run:

```bash
python3 <skill-dir>/scripts/cronloop.py install \
  --interval 1h \
  --thread-id "$CODEX_THREAD_ID" \
  --workdir "$PWD" \
  --model gpt-5.6-luna \
  --prompt-file /path/to/expanded-prompt.txt
```

To send each executed round to the currently authenticated Feishu user as a bot DM, add:

```bash
  --notify feishu-cli
```

Notification is opt-in and requires `lark-cli whoami --as user` and `--as bot` to report ready identities. The default target is `me`; use `--notify-target ou_xxx` for another user or `--notify-target oc_xxx` for a group chat. The installer resolves `me` once and stores only the non-secret target ID and absolute CLI path. Each real Codex round sends its final assistant message; nonzero or timed-out rounds send an explicit fallback when no final message exists. Notification failures are logged to `notify.log` and never fail or block the cron job. Lock-contention and thread-active skips do not notify. A `--completion-file` fast-path sends a minimal completion-marker notice before automatic removal.

Omit `--model` to inherit the normal Codex CLI default. Use `--model` when the
user explicitly requests a particular available model for scheduled resumes.

Accepted exact cron intervals are `30m`, hour divisors of 24 (`1h`, `2h`, `3h`, `4h`, `6h`, `8h`, `12h`), and `1d`; equivalent `60m` and `24h` normalize. Reject intervals below 30 minutes or intervals cron cannot express with constant spacing. Explain that native Scheduled tasks are preferable when the product exposes them.

The installer prints the generated job ID. Report that ID, interval, expanded prompt, log directory, and removal command. Delete the temporary prompt after installation.
Verify that the host's cron daemon is active and run `status` after installation. If daemon state cannot be determined, say so rather than claiming periodic execution is proven.

To update an existing job idempotently, pass its ID:

```bash
python3 <skill-dir>/scripts/cronloop.py install ... --job-id <id>
```

Optionally pass `--completion-file /absolute/path` only when a trustworthy marker file unambiguously proves completion. The runner then removes itself before another model call once that marker exists. Otherwise the resumed agent must verify completion and execute the removal command included in its prompt.

## Inspect and stop

```bash
python3 <skill-dir>/scripts/cronloop.py list
python3 <skill-dir>/scripts/cronloop.py status --job-id <id>
python3 <skill-dir>/scripts/cronloop.py remove --job-id <id>
```

`remove` disables the job and removes only its marked crontab block; it retains prompt, status, and logs for audit. Use `--purge` only if the user asks to delete them.

## Guardrails

- Preserve every unrelated crontab line.
- Use exact thread UUID, `flock`-equivalent locking, an inactivity window, and a timeout shorter than the interval.
- Run under an explicit minimal `HOME` and `PATH`. Persist only proxy URLs without embedded credentials.
- Enable `--notify` only when the user requested external notifications. Do not include secrets or credential-bearing URLs in notification text.
- Never use `--last`, `--dangerously-bypass-approvals-and-sandbox`, or `--dangerously-bypass-hook-trust`.
- Do not install Ralph Loop or Temporal for this workflow.
- Do not claim the scheduler can wake a web/API chat unless the exact thread is locally resumable by Codex CLI.
- Test with `--crontab-file` and `--codex-bin` fakes; never resume an active real thread merely to test installation.
