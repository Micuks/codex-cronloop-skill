# Example: monitor a multi-round benchmark

This is a representative pattern. Paths, job IDs, and metrics are illustrative.

## Short request

```text
$cronloop 30m monitor ./runs/exp-42 until all 8 configurations have 3 valid
rounds for q01-q15 and results.xlsx is generated. Check runner/process health,
newest logs, matrix completeness, disk, and load. If stalled, diagnose first;
restart only when the runner is absent and no duplicate exists. Do not change
benchmark parameters or delete artifacts. Report progress and ETA every round.
```

## Expanded scheduled prompt

```text
Scope
- Work only in ./runs/exp-42 and the benchmark processes that write to it.
- Treat the runner state file, process table, newest per-query logs, raw result
  files, and results.xlsx as authoritative evidence.

One-round checks
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
- Then report the final per-configuration summary and remove this cronloop with
  the job-specific removal command included below.

Execute exactly one scheduled round. Do not sleep, wait for another round, or
create any loop, cron entry, or scheduler.
```

## Representative round report

```text
Job: benchmark-watch | Round: scheduled check
Matrix: 248/360 valid; 1 running; 111 pending; 0 invalid
Runner: healthy, one instance, latest progress 4m ago
Host: load 5.2/64 CPUs; disk 418 GiB free
Newest result: chen-only/q11/r2 completed in 18m42s
ETA: about 4h10m, based on the last 12 completed cells
Action: none—progress and health are normal
```

## Representative completion report

```text
Matrix: 360/360 valid
Artifact: results.xlsx exists and passed row/count checks
Action: removed CRONLOOP benchmark-watch marker block
Audit trail: ~/.codex/cronloop/jobs/benchmark-watch/
```
