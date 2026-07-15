#!/usr/bin/env python3
"""Manage recurring, exact-thread Codex CLI checks via a guarded cron fallback."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shlex
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
STATE_ROOT = DEFAULT_HOME / "cronloop"
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
JOB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
NOTIFY_TARGET_RE = re.compile(r"^(?:ou|oc)_[A-Za-z0-9]+$")
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")
MAX_NOTIFICATION_CHARS = 12_000


def fail(message: str) -> "None":
    raise SystemExit(f"cronloop: {message}")


def parse_interval(raw: str) -> tuple[str, int, str]:
    match = re.fullmatch(r"\s*(\d+)\s*([mhdMHD])\s*", raw)
    if not match:
        fail("interval must look like 30m, 1h, 2h, or 1d")
    value, unit = int(match.group(1)), match.group(2).lower()
    if value <= 0:
        fail("interval must be positive")
    seconds = value * {"m": 60, "h": 3600, "d": 86400}[unit]
    if seconds < 1800:
        fail("interval must be at least 30 minutes")
    if seconds == 86400:
        return "1d", seconds, "0 0 * * *"
    if seconds < 3600 and 3600 % seconds == 0:
        minutes = seconds // 60
        return f"{minutes}m", seconds, f"*/{minutes} * * * *"
    if seconds < 86400 and seconds % 3600 == 0 and 86400 % seconds == 0:
        hours = seconds // 3600
        return f"{hours}h", seconds, ("0 * * * *" if hours == 1 else f"0 */{hours} * * *")
    fail(f"{raw!r} cannot be represented by five-field cron with constant spacing; use 30m, a divisor-of-24 hour interval, or 1d")


def safe_proxy_environment() -> tuple[dict[str, str], list[str]]:
    result: dict[str, str] = {}
    skipped: list[str] = []
    for key in PROXY_KEYS:
        value = os.environ.get(key)
        if not value:
            continue
        if key.lower() == "no_proxy":
            if any(ch in value for ch in "\r\n"):
                skipped.append(key)
            else:
                result[key] = value
            continue
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(ch in value for ch in "\r\n"):
            skipped.append(key)
        else:
            result[key] = value
    return result, skipped


def find_rollout(thread_id: str, codex_home: Path) -> Path:
    candidates = list((codex_home / "sessions").glob(f"**/*{thread_id}*.jsonl"))
    if not candidates:
        fail(f"no local rollout found for exact thread {thread_id}; cannot safely schedule resume")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def default_timeout(interval_seconds: int) -> int:
    return min(interval_seconds - 300, 3300)


def cron_daemon_status() -> str:
    if not shutil.which("systemctl"):
        return "unknown"
    for service in ("cron", "crond"):
        proc = subprocess.run(["systemctl", "is-active", service], text=True, capture_output=True)
        if proc.stdout.strip() == "active":
            return f"active:{service}"
    return "inactive-or-unknown"


def validate_timeout(value: int, interval_seconds: int) -> None:
    if value <= 0 or value >= interval_seconds:
        fail("timeout must be positive and shorter than the interval")


def command_json(command: list[str], *, env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(command, text=True, capture_output=True, env=env)
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        fail(f"command failed: {detail}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        fail(f"command returned invalid JSON: {exc}")


def prepare_notification(args: argparse.Namespace) -> dict | None:
    if not args.notify:
        if args.notify_target:
            fail("--notify-target requires --notify")
        return None
    cli = Path(args.notify_cli or shutil.which("lark-cli") or "")
    if not cli.is_file():
        fail("cannot locate lark-cli; install it or pass --notify-cli")
    cli = cli.resolve()
    env = os.environ.copy()
    env["LARK_CLI_NO_PROXY_WARN"] = "1"
    bot = command_json([str(cli), "whoami", "--as", "bot"], env=env)
    if not bot.get("available") or bot.get("tokenStatus") not in {"ready", "valid"}:
        fail("lark-cli bot identity is not ready; run lark-cli config init/auth login first")
    target = args.notify_target or "me"
    if target == "me":
        user = command_json([str(cli), "whoami", "--as", "user"], env=env)
        target = ((user.get("onBehalfOf") or {}).get("openId") or "").strip()
        if not user.get("available") or not NOTIFY_TARGET_RE.fullmatch(target):
            fail("cannot resolve the authenticated Feishu user for --notify-target me")
    if not NOTIFY_TARGET_RE.fullmatch(target):
        fail("--notify-target must be me, an ou_ user open_id, or an oc_ chat_id")
    return {
        "mode": args.notify,
        "cli": str(cli),
        "target_type": "chat_id" if target.startswith("oc_") else "user_id",
        "target": target,
    }


def state_dir(root: Path, job_id: str) -> Path:
    return root / "jobs" / job_id


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read state {path}: {exc}")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def crontab_text(args: argparse.Namespace) -> str:
    if args.crontab_file:
        path = Path(args.crontab_file)
        return path.read_text() if path.exists() else ""
    proc = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    if proc.returncode not in (0, 1):
        fail(f"crontab -l failed: {proc.stderr.strip()}")
    return proc.stdout


def save_crontab(args: argparse.Namespace, text: str) -> None:
    if args.crontab_file:
        Path(args.crontab_file).write_text(text)
        return
    proc = subprocess.run(["crontab", "-"], input=text, text=True, capture_output=True)
    if proc.returncode:
        fail(f"crontab install failed: {proc.stderr.strip()}")


def markers(job_id: str) -> tuple[str, str]:
    return f"# BEGIN CRONLOOP {job_id}", f"# END CRONLOOP {job_id}"


def strip_block(text: str, job_id: str) -> str:
    begin, end = markers(job_id)
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    inside = False
    for line in lines:
        content = line.rstrip("\r\n")
        if content == begin:
            if inside:
                fail(f"malformed duplicate marker for {job_id}")
            inside = True
            continue
        if content == end and inside:
            inside = False
            continue
        if not inside:
            output.append(line)
    if inside:
        fail(f"unterminated crontab marker for {job_id}")
    # A stray end marker is left untouched; it cannot cause accidental deletion.
    return "".join(output)


@contextmanager
def crontab_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock_file = (root / "crontab.lock").open("a+")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def install(args: argparse.Namespace) -> None:
    normalized, interval_seconds, schedule = parse_interval(args.interval)
    if not UUID_RE.fullmatch(args.thread_id):
        fail("--thread-id must be an exact UUID from CODEX_THREAD_ID")
    workdir = Path(args.workdir).expanduser().resolve()
    if not workdir.is_dir():
        fail(f"workdir does not exist: {workdir}")
    prompt_path = Path(args.prompt_file)
    prompt = prompt_path.read_text().strip()
    if not prompt:
        fail("expanded prompt is empty")
    if re.search(r"(?i)(password|passwd|token|secret|private[_ -]?key)\s*[:=]\s*\S+", prompt):
        fail("expanded prompt appears to contain a secret; reference a secure retrieval method instead")
    root = Path(args.state_root).expanduser().resolve()
    codex_home = Path(args.codex_home).expanduser().resolve()
    rollout = find_rollout(args.thread_id, codex_home)
    codex_bin = Path(args.codex_bin or shutil.which("codex") or "")
    if not codex_bin.is_file():
        fail("cannot locate codex executable; pass --codex-bin")
    timeout_seconds = args.timeout or default_timeout(interval_seconds)
    validate_timeout(timeout_seconds, interval_seconds)
    if args.active_window < 0 or args.active_window >= interval_seconds:
        fail("active window must be nonnegative and shorter than the interval")
    if args.completion_file and not Path(args.completion_file).is_absolute():
        fail("completion file must be an absolute path")
    if args.model and not MODEL_RE.fullmatch(args.model):
        fail("model must be a plain model id without whitespace or shell characters")
    notification = prepare_notification(args)

    job_id = args.job_id or f"job-{dt.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    if not JOB_RE.fullmatch(job_id):
        fail("job id must be 3-64 lowercase letters, digits, or hyphens")
    job_dir = state_dir(root, job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(job_dir, 0o700)
    removal_parts = [
        "python3",
        shlex.quote(str(Path(__file__).resolve())),
        "remove",
        "--job-id",
        shlex.quote(job_id),
        "--state-root",
        shlex.quote(str(root)),
    ]
    if args.crontab_file:
        removal_parts.extend(["--crontab-file", shlex.quote(str(Path(args.crontab_file).resolve()))])
    removal = " ".join(removal_parts)
    envelope = (
        "\n\n[cronloop contract]\n"
        "Execute exactly one scheduled round. Do not sleep, wait for another round, or create any loop/cron/scheduler. "
        "Use the current thread context. Before recovery, diagnose from evidence; act only within the authority stated above; avoid duplicate starts. "
        f"When and only when the completion condition is verified, stop future wake-ups by running: {removal}\n"
    )
    stored_prompt = prompt + envelope
    (job_dir / "prompt.txt").write_text(stored_prompt)
    os.chmod(job_dir / "prompt.txt", 0o600)
    proxies, skipped = safe_proxy_environment()
    existing_config_path = job_dir / "config.json"
    existing_created_at = None
    if existing_config_path.exists():
        existing_created_at = read_json(existing_config_path).get("created_at")
    config = {
        "version": 3,
        "job_id": job_id,
        "enabled": True,
        "created_at": existing_created_at or dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "interval": normalized,
        "interval_seconds": interval_seconds,
        "schedule": schedule,
        "thread_id": args.thread_id,
        "rollout": str(rollout),
        "workdir": str(workdir),
        "codex_home": str(codex_home),
        "codex_bin": str(codex_bin.resolve()),
        "model": args.model,
        "home": str(Path.home()),
        "path": f"{Path.home() / '.local/bin'}:/usr/local/bin:/usr/bin:/bin",
        "active_window_seconds": args.active_window,
        "timeout_seconds": timeout_seconds,
        "completion_file": args.completion_file,
        "notify": notification,
        "proxy_env": proxies,
        "prompt_sha256": hashlib.sha256(stored_prompt.encode()).hexdigest(),
    }
    write_json(job_dir / "config.json", config)
    runner = Path(__file__).resolve()
    launcher_log = job_dir / "launcher.log"
    command = " ".join(
        [
            f"HOME={shlex.quote(str(Path.home()))}",
            f"PATH={shlex.quote('/usr/local/bin:/usr/bin:/bin')}",
            shlex.quote(sys.executable),
            shlex.quote(str(runner)),
            "run",
            "--job-id",
            shlex.quote(job_id),
            "--state-root",
            shlex.quote(str(root)),
            *( ["--crontab-file", shlex.quote(str(Path(args.crontab_file).resolve()))] if args.crontab_file else [] ),
            ">>",
            shlex.quote(str(launcher_log)),
            "2>&1",
        ]
    )
    begin, end = markers(job_id)
    block = f"{begin}\n{schedule} {command}\n{end}\n"
    with crontab_lock(root):
        current = strip_block(crontab_text(args), job_id)
        if current and not current.endswith("\n"):
            current += "\n"
        save_crontab(args, current + block)
    result = {"job_id": job_id, "interval": normalized, "schedule": schedule, "timeout_seconds": timeout_seconds, "notify": notification, "state_dir": str(job_dir), "cron_daemon": cron_daemon_status(), "skipped_credentialed_proxy_keys": skipped}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def remove(args: argparse.Namespace, *, automatic: bool = False) -> None:
    root = Path(args.state_root).expanduser().resolve()
    job_dir = state_dir(root, args.job_id)
    config_path = job_dir / "config.json"
    config = read_json(config_path) if config_path.exists() else None
    with crontab_lock(root):
        current = crontab_text(args)
        save_crontab(args, strip_block(current, args.job_id))
    if config:
        config["enabled"] = False
        config["removed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        config["removed_automatically"] = automatic
        write_json(config_path, config)
    if args.purge and job_dir.exists():
        shutil.rmtree(job_dir)
    print(json.dumps({"job_id": args.job_id, "enabled": False, "purged": bool(args.purge)}))


def list_jobs(args: argparse.Namespace) -> None:
    root = Path(args.state_root).expanduser().resolve()
    jobs = []
    for config_path in sorted((root / "jobs").glob("*/config.json")):
        config = read_json(config_path)
        jobs.append({k: config.get(k) for k in ("job_id", "enabled", "interval", "schedule", "thread_id", "model", "notify", "workdir", "updated_at", "removed_at")})
    print(json.dumps(jobs, ensure_ascii=False, indent=2))


def status(args: argparse.Namespace) -> None:
    root = Path(args.state_root).expanduser().resolve()
    job_dir = state_dir(root, args.job_id)
    config = read_json(job_dir / "config.json")
    status_path = job_dir / "status.json"
    current = crontab_text(args)
    begin, _ = markers(args.job_id)
    payload = {"config": config, "cron_marker_present": begin in current, "last_run": read_json(status_path) if status_path.exists() else None, "log_dir": str(job_dir)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def update_status(job_dir: Path, **fields: object) -> None:
    status_path = job_dir / "status.json"
    current = read_json(status_path) if status_path.exists() else {}
    current.update(fields)
    write_json(status_path, current)


def redact_notification(text: str) -> str:
    text = re.sub(
        r"(?i)\b(password|passwd|token|secret|private[_ -]?key|authorization)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=***",
        text,
    )
    text = re.sub(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/\S+", "[redacted webhook]", text)
    if len(text) > MAX_NOTIFICATION_CHARS:
        text = text[: MAX_NOTIFICATION_CHARS - 40].rstrip() + "\n\n[notification truncated]"
    return text


def send_notification(
    config: dict,
    job_dir: Path,
    *,
    state: str,
    rc: int,
    message: str | None,
    event_id: str,
) -> None:
    notify = config.get("notify")
    if not notify:
        return
    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    detail = message.strip() if message and message.strip() else "No final assistant message was produced; inspect codex.log."
    body = redact_notification(
        f"## Cronloop · {config['job_id']}\n\n"
        f"- state: `{state}`\n"
        f"- rc: `{rc}`\n"
        f"- time: `{finished}`\n\n"
        f"{detail}"
    )
    target_flag = "--chat-id" if notify["target_type"] == "chat_id" else "--user-id"
    idempotency = "cl-" + hashlib.sha256(f"{config['job_id']}:{event_id}".encode()).hexdigest()[:24]
    command = [
        notify["cli"],
        "im",
        "+messages-send",
        "--as",
        "bot",
        target_flag,
        notify["target"],
        "--markdown",
        body,
        "--idempotency-key",
        idempotency,
        "--format",
        "json",
    ]
    env = {"HOME": config["home"], "PATH": config["path"], "LARK_CLI_NO_PROXY_WARN": "1"}
    env.update(config.get("proxy_env", {}))
    notify_log = job_dir / "notify.log"
    try:
        proc = subprocess.run(command, text=True, capture_output=True, env=env, timeout=30)
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        if proc.returncode or not payload.get("ok"):
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            raise RuntimeError(detail)
        message_id = ((payload.get("data") or {}).get("message_id"))
        with notify_log.open("a") as log:
            log.write(f"[{finished}] sent state={state} rc={rc} message_id={message_id or '-'}\n")
        os.chmod(notify_log, 0o600)
        update_status(job_dir, last_notify_at=finished, last_notify_state="sent", last_notify_message_id=message_id)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as exc:
        error = str(exc).replace("\n", " ")[:1000]
        with notify_log.open("a") as log:
            log.write(f"[{finished}] warning state={state} rc={rc} error={error}\n")
        os.chmod(notify_log, 0o600)
        update_status(job_dir, last_notify_at=finished, last_notify_state="failed", last_notify_error=error)


def run(args: argparse.Namespace) -> None:
    root = Path(args.state_root).expanduser().resolve()
    job_dir = state_dir(root, args.job_id)
    config = read_json(job_dir / "config.json")
    if not config.get("enabled"):
        return
    lock_path = job_dir / "run.lock"
    lock_file = lock_path.open("a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        update_status(job_dir, last_skip_at=dt.datetime.now(dt.timezone.utc).isoformat(), last_skip_reason="already-running")
        return
    completion = config.get("completion_file")
    if completion and Path(completion).exists():
        event_id = dt.datetime.now(dt.timezone.utc).isoformat()
        send_notification(
            config,
            job_dir,
            state="complete",
            rc=0,
            message=f"Completion marker detected: {completion}",
            event_id=event_id,
        )
        remove(argparse.Namespace(job_id=args.job_id, state_root=str(root), purge=False, crontab_file=args.crontab_file), automatic=True)
        update_status(job_dir, last_skip_at=dt.datetime.now(dt.timezone.utc).isoformat(), last_skip_reason="completion-file-present")
        return
    rollout = Path(config["rollout"])
    now = time.time()
    if rollout.exists() and now - rollout.stat().st_mtime < config["active_window_seconds"]:
        update_status(job_dir, last_skip_at=dt.datetime.now(dt.timezone.utc).isoformat(), last_skip_reason="thread-active")
        return
    prompt_path = job_dir / "prompt.txt"
    prompt = prompt_path.read_text()
    if hashlib.sha256(prompt.encode()).hexdigest() != config["prompt_sha256"]:
        fail("stored prompt checksum mismatch")
    env = {"HOME": config["home"], "PATH": config["path"], "CODEX_HOME": config["codex_home"]}
    env.update(config.get("proxy_env", {}))
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    update_status(job_dir, last_started_at=started, state="running")
    last_message_path = job_dir / "last-message.txt"
    if config.get("notify") and last_message_path.exists():
        last_message_path.unlink()
    with (job_dir / "codex.log").open("a") as log:
        log.write(f"\n[{started}] cronloop invocation\n")
        log.flush()
        command = [config["codex_bin"], "exec"]
        if config.get("notify"):
            command.extend(["--output-last-message", str(last_message_path)])
        command.append("resume")
        if config.get("model"):
            command.extend(["--model", config["model"]])
        command.extend([config["thread_id"], "-"])
        proc = subprocess.Popen(
                command,
                text=True,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=config["workdir"],
                env=env,
                start_new_session=True,
            )
        try:
            proc.communicate(input=prompt, timeout=config["timeout_seconds"])
            rc = proc.returncode
            state = "exited"
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            rc = 124
            state = "timed-out"
    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    update_status(job_dir, last_finished_at=finished, state=state, last_rc=rc)
    last_message = None
    if last_message_path.exists():
        os.chmod(last_message_path, 0o600)
        last_message = last_message_path.read_text(errors="replace")
    send_notification(config, job_dir, state=state, rc=rc, message=last_message, event_id=started)
    if rc:
        raise SystemExit(rc)


def common_state(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-root", default=str(STATE_ROOT))
    parser.add_argument("--crontab-file", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install")
    p.add_argument("--interval", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--workdir", required=True)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--job-id")
    p.add_argument("--timeout", type=int, help="seconds; default is interval minus 5m, capped at 55m")
    p.add_argument("--active-window", type=int, default=600, help="seconds since thread activity that suppresses a wake-up")
    p.add_argument("--completion-file")
    p.add_argument("--codex-home", default=str(DEFAULT_HOME))
    p.add_argument("--codex-bin")
    p.add_argument("--model", help="model id to pin for every scheduled resume")
    p.add_argument("--notify", choices=("feishu-cli",), help="send each completed round through the selected channel")
    p.add_argument("--notify-target", help="me (default), an ou_ user open_id, or an oc_ chat_id")
    p.add_argument("--notify-cli", help=argparse.SUPPRESS)
    common_state(p)
    p.set_defaults(func=install)
    for name, func in (("remove", remove), ("status", status)):
        p = sub.add_parser(name)
        p.add_argument("--job-id", required=True)
        if name == "remove":
            p.add_argument("--purge", action="store_true")
        common_state(p)
        p.set_defaults(func=func)
    p = sub.add_parser("list")
    common_state(p)
    p.set_defaults(func=list_jobs)
    p = sub.add_parser("run", help=argparse.SUPPRESS)
    p.add_argument("--job-id", required=True)
    common_state(p)
    p.set_defaults(func=run)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
