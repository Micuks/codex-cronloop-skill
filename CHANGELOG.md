# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Foreground TTY `bash sleep` cycles that keep monitoring in the current Codex task.
- Explicit long-wait contract distinguishing a tool-call yield from the lifetime of the foreground process.
- Arbitrary integer minute, hour, and day intervals instead of five-field cron-compatible intervals only.
- Optional user-requested external delivery of completed round reports, including Feishu.
- Static contract tests and an isolated end-to-end foreground-session forward test.

### Changed

- Reimplemented Cronloop as a lightweight, continuous agent-in-the-loop skill with no scheduler state or cold thread resumes.
- External notifications now run in the current task after real monitoring rounds and remain fail-open.

### Removed

- Crontab installation, daemon checks, persisted job state, locking, and repeated `codex exec resume` invocations.
- The Python cron runner and its scheduler-specific tests.

### Security

- Secret-like fields and webhook URLs are redacted before notification delivery.
- Notification failures are fail-open and cannot change a successful monitoring round into a failed one.

## [0.1.0] - 2026-07-13

### Added

- Initial exact-thread Cronloop skill release.
- Guarded single-round execution, overlap protection, timeout enforcement, completion-file cleanup, and marker-scoped crontab management.
