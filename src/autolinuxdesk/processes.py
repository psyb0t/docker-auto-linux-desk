"""Launching desktop programs and running shell commands.

Everything runs as the container user. Launched programs are detached into
their own session on the virtual display and tracked so they can be listed
and stopped later. Commands run to completion with a timeout and capped
output, and the whole process group is killed on timeout.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from autolinuxdesk.logger import get_logger

log = get_logger(__name__)

OUTPUT_CAP_BYTES = 1024 * 1024
COMMAND_TIMEOUT_DEFAULT_S = 30.0
COMMAND_TIMEOUT_MAX_S = 600.0
STDIN_CAP_BYTES = 1024 * 1024
LAUNCH_LOG_DIR = os.environ.get("DESK_LAUNCH_LOG_DIR", "/tmp/auto-linux-desk/launched")
LAUNCH_LOG_TAIL_BYTES = 16 * 1024
_KILL_GRACE_S = 2.0
_EXIT_POLL_S = 0.02
_READ_CHUNK = 65536
_SIGNALS = {"TERM": signal.SIGTERM, "KILL": signal.SIGKILL, "INT": signal.SIGINT}
_ENV_LIMIT = 200


class ProcessError(Exception):
    """A launch or command request was invalid or could not start."""


def _argv(value: Any, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(part, str) and part for part in value)
    ):
        raise ProcessError(f"{name} must be a non-empty list of non-empty strings")
    return list(value)


def _env(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > _ENV_LIMIT:
        raise ProcessError(f"env must be an object with at most {_ENV_LIMIT} entries")
    for key, item in value.items():
        if not isinstance(key, str) or not key or "=" in key or "\0" in key:
            raise ProcessError("env keys must be non-empty names without '='")
        if not isinstance(item, str) or "\0" in item:
            raise ProcessError("env values must be strings")
    return dict(value)


def _cwd(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProcessError("cwd must be a non-empty string")
    if not os.path.isdir(value):
        raise ProcessError(f"cwd does not exist: {value}")
    return value


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":99")
    env.update(extra)
    return env


def redact_command(command: Any) -> str:
    """First token only, so arguments and secrets stay out of the logs."""
    if isinstance(command, list) and command:
        return str(command[0])
    if isinstance(command, str):
        stripped = command.strip()
        return stripped.split(maxsplit=1)[0] if stripped else ""
    return ""


def _tail(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - LAUNCH_LOG_TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


@dataclass
class Launched:
    id: int
    argv: list[str]
    process: subprocess.Popen
    started_at: float
    log_path: str
    cwd: str | None = None

    def describe(self, with_output: bool = False) -> dict[str, Any]:
        code = self.process.poll()
        info: dict[str, Any] = {
            "id": self.id,
            "pid": self.process.pid,
            "argv": self.argv,
            "running": code is None,
            "exit_code": code,
            "started_at": self.started_at,
            "log_path": self.log_path,
        }
        if with_output:
            info["output_tail"] = _tail(self.log_path)
        return info


@dataclass
class ProcessManager:
    launched: dict[int, Launched] = field(default_factory=dict)
    _next_id: int = 1

    def launch(self, cmd: dict) -> dict[str, Any]:
        argv = _argv(cmd.get("command"), "command")
        cwd = _cwd(cmd.get("cwd"))
        env = _child_env(_env(cmd.get("env")))
        os.makedirs(LAUNCH_LOG_DIR, exist_ok=True)
        launch_id = self._next_id
        log_path = os.path.join(LAUNCH_LOG_DIR, f"{launch_id}.log")
        try:
            with open(log_path, "wb") as log_file:
                process = subprocess.Popen(  # noqa: S603 - argv list, no shell
                    argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as error:
            raise ProcessError(f"failed to launch {argv[0]}: {error}") from error
        self._next_id += 1
        entry = Launched(launch_id, argv, process, time.time(), log_path, cwd)
        self.launched[launch_id] = entry
        log.info(
            "launched program",
            extra={"id": launch_id, "pid": process.pid, "program": argv[0]},
        )
        return entry.describe()

    def list(self, with_output: bool = False) -> list[dict[str, Any]]:
        return [entry.describe(with_output) for entry in self.launched.values()]

    def get(self, launch_id: Any) -> Launched:
        if isinstance(launch_id, bool) or not isinstance(launch_id, int):
            raise ProcessError("id must be an integer from list_launched")
        entry = self.launched.get(launch_id)
        if entry is None:
            raise ProcessError(f"no launched program with id {launch_id}")
        return entry

    def kill(self, launch_id: Any, signal_name: Any = "TERM") -> dict[str, Any]:
        entry = self.get(launch_id)
        if not isinstance(signal_name, str) or signal_name.upper() not in _SIGNALS:
            raise ProcessError(f"signal must be one of {', '.join(_SIGNALS)}")
        if entry.process.poll() is None:
            try:
                os.killpg(entry.process.pid, _SIGNALS[signal_name.upper()])
            except ProcessLookupError:
                pass
            try:
                entry.process.wait(timeout=_KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
        return entry.describe()

    def forget_finished(self) -> int:
        finished = [key for key, entry in self.launched.items() if entry.process.poll() is not None]
        for key in finished:
            del self.launched[key]
        return len(finished)

    def shutdown(self) -> None:
        for entry in self.launched.values():
            if entry.process.poll() is None:
                try:
                    os.killpg(entry.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


def command_timeout(value: Any) -> float:
    if value is None:
        return COMMAND_TIMEOUT_DEFAULT_S
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcessError("timeout_s must be a number")
    if not 0 < value <= COMMAND_TIMEOUT_MAX_S:
        raise ProcessError(
            f"timeout_s must be greater than 0 and at most {COMMAND_TIMEOUT_MAX_S:g}"
        )
    return float(value)


async def _read_capped(stream: asyncio.StreamReader) -> tuple[bytes, bool]:
    """Read to EOF, keeping the first OUTPUT_CAP_BYTES. Draining avoids a full pipe."""
    kept = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            return bytes(kept), truncated
        room = OUTPUT_CAP_BYTES - len(kept)
        if room > 0:
            kept.extend(chunk[:room])
        if len(chunk) > room:
            truncated = True


async def _finish_read(task: asyncio.Task) -> tuple[bytes, bool]:
    """A process that left the group can hold the pipe open; stop waiting for it."""
    try:
        return await asyncio.wait_for(asyncio.shield(task), _KILL_GRACE_S)
    except TimeoutError:
        task.cancel()
        return b"", True


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def run_command(cmd: dict) -> dict[str, Any]:
    """Run a command to completion. A string runs under bash -c, a list runs directly."""
    command = cmd.get("command")
    if isinstance(command, str):
        if not command.strip():
            raise ProcessError("command must not be empty")
        argv = ["bash", "-c", command]
    else:
        argv = _argv(command, "command")
    cwd = _cwd(cmd.get("cwd"))
    env = _child_env(_env(cmd.get("env")))
    timeout = command_timeout(cmd.get("timeout_s"))
    stdin_text = cmd.get("stdin")
    if stdin_text is not None:
        if not isinstance(stdin_text, str):
            raise ProcessError("stdin must be a string")
        stdin_bytes = stdin_text.encode()
        if len(stdin_bytes) > STDIN_CAP_BYTES:
            raise ProcessError(f"stdin must be at most {STDIN_CAP_BYTES} bytes")
    else:
        stdin_bytes = None

    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        raise ProcessError(f"failed to start {argv[0]}: {error}") from error

    async def feed() -> None:
        if stdin_bytes is None or process.stdin is None:
            return
        try:
            process.stdin.write(stdin_bytes)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    assert process.stdout is not None and process.stderr is not None
    out_task = asyncio.create_task(_read_capped(process.stdout))
    err_task = asyncio.create_task(_read_capped(process.stderr))
    feed_task = asyncio.create_task(feed())
    timed_out = False
    # Process.wait() also waits for the pipes to close, which a background
    # child keeps open, so watch the exit status itself.
    deadline = time.monotonic() + timeout
    while process.returncode is None:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        await asyncio.sleep(_EXIT_POLL_S)
    # Kill the group either way: on timeout it stops the command, otherwise
    # it stops background children that would hold the pipes open forever.
    _kill_group(process.pid)
    await process.wait()
    feed_task.cancel()
    stdout, out_cut = await _finish_read(out_task)
    stderr, err_cut = await _finish_read(err_task)

    result = {
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "stdout_truncated": out_cut,
        "stderr_truncated": err_cut,
        "timed_out": timed_out,
        "duration": round(time.monotonic() - started, 3),
    }
    log.info(
        "command finished",
        extra={
            "program": redact_command(command),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "duration": result["duration"],
        },
    )
    return result
