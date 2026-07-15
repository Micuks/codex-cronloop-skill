# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Optional Feishu delivery with `--notify feishu-cli`.
- User and group routing with `--notify-target` (`me`, `ou_xxx`, or `oc_xxx`).
- Final-response capture through Codex `--output-last-message`, per-job notification status, and `notify.log` diagnostics.
- Minimal Feishu completion notices for completion-file fast paths.
- Explicit model pinning with `--model` for deterministic thread resumes.
- Isolated regression tests using fake Codex and Lark CLI binaries.

### Changed

- Job configuration schema advanced to version 3 to persist non-secret model and notification settings.

### Security

- Secret-like fields and webhook URLs are redacted before notification delivery.
- Notification failures are fail-open and cannot change a successful monitoring round into a failed one.

## [0.1.0] - 2026-07-13

### Added

- Initial exact-thread Cronloop skill release.
- Guarded single-round execution, overlap protection, timeout enforcement, completion-file cleanup, and marker-scoped crontab management.
