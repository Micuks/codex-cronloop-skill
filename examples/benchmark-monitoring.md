# Example: monitor a multi-round benchmark

This is a representative pattern. Paths and metrics are illustrative.

## Short request

```text
$cronloop 30m monitor ./runs/exp-42 until all 8 configurations have 3 valid
rounds for q01-q15 and results.xlsx is generated. Check runner/process health,
newest logs, matrix completeness, disk, and load. If stalled, diagnose first;
restart only when the runner is absent and no duplicate exists. Do not change
benchmark parameters or delete artifacts. Report progress and ETA every round.
```

## In-turn monitoring contract

```text
Scope
- Work only in ./runs/exp-42 and the benchmark processes that write to it.
- Treat the runner state file, process table, newest per-query logs, raw result
  files, and results.xlsx as authoritative evidence.

Each round
1. Inspect runner PID/process identity and confirm whether it is active.
2. Read the newest logs and classify new failures; do not infer success merely
   from a running PID.
3. Count valid matrix cells for 8 configurations x 15 queries x 3 rounds.
4. Check free disk space and host load for conditions that threaten validity.
5. Report completed/running/pending/failed cells, newest progress time, health,
   and an ETA based on observed completed durations. Mark missing evidence.

Authorized recovery
- Diagnose from logs and process evidence before acting.
- If and only if the runner is absent, no benchmark child remains, and the
  resumable state is internally consistent, restart the existing runner once.
- After recovery, verify one active runner and new log progress. Never start a
  second instance.

Forbidden
- Do not change benchmark parameters, source code, input data, or baselines.
- Do not delete or overwrite raw artifacts and do not bypass approvals.

Completion
- Complete only when all 360 expected cells are present and valid and the
  generated results.xlsx passes its integrity checks.
- Then report the final per-configuration summary and end without another wait.

Waiting
- Check once now. If incomplete, run bash -lc 'sleep 1800' as the foreground
  process of a TTY and wait on its returned session ID.
- Do not use cron, resume another Codex process, detach the sleep, or restart the
  interval after the execution tool yields.
- Do not reject or shorten the 30-minute wait because it exceeds 60 seconds.
```

## Representative first round

```text
Matrix: 248/360 valid; 1 running; 111 pending; 0 invalid
Runner: healthy, one instance, latest progress 4m ago
Host: load 5.2/64 CPUs; disk 418 GiB free
Newest result: chen-only/q11/r2 completed in 18m42s
ETA: about 4h10m, based on the last 12 completed cells
Action: none—progress and health are normal
Next check: in 30 minutes; foreground TTY sleep started
```

## Representative wait lifecycle

```text
exec_command bash -lc 'sleep 1800'  (tty=true)
  -> yields session_id=4812 while sleep remains foreground
write_stdin session_id=4812 chars=""
  -> still running; continue polling the same session
write_stdin session_id=4812 chars=""
  -> exit 0 after the original 30-minute deadline
next monitoring round begins in the same Codex task
```

## Representative completion report

```text
Matrix: 360/360 valid
Artifact: results.xlsx exists and passed row/count checks
Action: completion verified; no further TTY sleep started
```
