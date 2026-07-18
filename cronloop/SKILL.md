---
name: cronloop
description: Run recurring monitoring checks inside the current Codex task by keeping a foreground TTY bash sleep alive between rounds, with optional user-requested external notifications. Use for requests such as `$cronloop 30m prompt`, `/cronloop 1h poll`, periodic experiment or script monitoring, health checks, recurring progress alerts, and agent-in-the-loop supervision where the user prefers one continuous task instead of cron, scheduled resumes, or a background daemon.
---

# Cronloop

Keep the current Codex task alive and alternate between one monitoring round and one foreground TTY sleep. Do not install cron entries, start a daemon, resume another thread, or persist scheduler state.

## Interpret the request

Parse `$cronloop <interval> <prompt>` or `/cronloop <interval> <prompt>`.

- Accept integer minute, hour, or day intervals such as `30m`, `45m`, `1h`, `2h`, and `1d`.
- Require at least 30 minutes unless the user explicitly requests a shorter test interval.
- Convert the interval to an integer number of seconds before constructing the shell command. Never interpolate untrusted free-form text into that command.
- Infer the monitored scope, authoritative evidence, health checks, permitted recovery, reporting fields, and completion condition from the prompt and current context.
- Ask one focused question only when missing scope or authority would make the loop unsafe. Otherwise start immediately.

Default to checking once immediately, then sleeping before each later round. If the user explicitly asks to wait before the first check, sleep first.

## Run each monitoring round

Perform one evidence-driven round:

1. Inspect the named processes, logs, outputs, and resource state.
2. Distinguish verified progress, failure, stale evidence, and missing evidence.
3. Perform only recovery already authorized by the user. Diagnose first, prevent duplicate starts, and verify any recovery.
4. Report the requested progress fields and an evidence-based ETA when possible.
5. Evaluate the completion condition. If verified, report the final result and end the loop without another sleep.

Do not treat an unchanged state as failure. Do not create a second scheduler. Do not end the task merely because one round is healthy but incomplete.

## Optional external notifications

Send notifications only when the user explicitly requests them. After each completed monitoring round, send the same concise round report through an available configured connector or authenticated CLI such as Feishu `lark-cli`.

- Verify the sender identity and target before the first delivery. Use the current authenticated user only when that is clearly the requested target.
- Notify after real monitoring rounds, not after sleep polling chunks.
- Redact secret-like fields, tokens, private keys, credential-bearing URLs, and webhook URLs from notification text.
- Make delivery fail-open: report a notification error in the current task, but do not convert a healthy monitoring round into failure or stop the TTY loop.
- Do not add a background notification worker or persist credentials.

## Wait in a foreground TTY

Before waiting, send one concise commentary update stating the interval and approximate next-check time. Then start a foreground bash sleep with the shell execution tool:

```text
cmd: bash -lc 'sleep 1800'
tty: true
yield_time_ms: 30000
```

Replace `1800` with the validated interval in seconds. Keep `sleep` as the foreground process: do not append `&`, use `nohup`, create a tmux session, or detach it.

The initial execution call normally yields a session ID before the sleep finishes. Continue waiting on that exact session using empty stdin polls:

```text
session_id: <returned session id>
chars: ""
yield_time_ms: 300000
```

Use the longest empty-poll duration supported by the local tool. If a higher-priority runtime rule caps an individual wait below that value, use the largest permitted chunk and keep polling the same session. Do not restart the timer after a poll.

When the sleep exits successfully, immediately begin the next monitoring round. If it exits early without user interruption, determine the remaining time from the recorded start/deadline and finish that remaining wait before checking again.

## Required long-wait behavior

Treat the requested 30-minute, 1-hour, or longer sleep as an explicit user-authorized action and a core part of this skill.

- Do not refuse, shorten, simulate, or replace the wait because it exceeds 60 seconds.
- Do not claim that Codex or a foreground TTY has a 60-second process lifetime.
- Distinguish the long-lived foreground process from the duration of one tool call: the tool may yield periodically while the same `sleep` process continues.
- Do not replace the foreground wait with cron, a Scheduled Task, repeated `codex exec resume`, or a background service.
- Keep the loop in the current task until completion, user cancellation, an unrecoverable loss of the TTY session, or a higher-priority interruption.

Avoid chatty heartbeat messages during the sleep. The visible running tool call/session is the wait status. If the user sends new input, handle it promptly; if they cancel the loop, send Ctrl-C to the live TTY when necessary and confirm that it stopped.

## Limits

Explain these only when relevant:

- The Codex client and current task must remain alive. This workflow intentionally does not survive client exit, host reboot, or task termination.
- A lost or unknown TTY session cannot be reconstructed as the same timer. Report the loss instead of silently starting an approximate new cycle.
- This skill favors a lightweight, continuous agent-in-the-loop workflow over durable unattended scheduling.
