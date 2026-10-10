"""Run compiled test binaries with a timeout and bounded output capture.

This is NOT a security sandbox. The binary runs with the full privileges of the current
user; the timeout only bounds wall-clock time. See docs/limitations.md.
"""

from __future__ import annotations

import os
import signal as signal_module
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import IO

from .errors import ExecutionError
from .models import ExecResult

_WINDOWS_ERROR_MASK = 0xC0000000


def _read_limited(handle: IO[bytes], limit: int) -> tuple[str, bool]:
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(0)
    data = handle.read(limit)
    return data.decode("utf-8", errors="replace"), size > limit


def _kill(proc: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal_module.SIGKILL)
    except ProcessLookupError:
        pass


def interpret_returncode(returncode: int) -> tuple[int | None, bool]:
    """Return (signal number or None, crashed) for a raw subprocess return code."""
    if sys.platform == "win32":
        code = returncode & 0xFFFFFFFF
        return None, code >= _WINDOWS_ERROR_MASK
    if returncode < 0:
        return -returncode, True
    return None, False


def run_binary(
    binary: Path,
    timeout: float,
    *,
    args: Sequence[str] = (),
    cwd: Path | None = None,
    max_output_bytes: int = 1_000_000,
) -> ExecResult:
    """Execute ``binary`` and capture stdout/stderr (each truncated to ``max_output_bytes``)."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        start = time.perf_counter()
        popen_kwargs: dict[str, bool] = {} if sys.platform == "win32" else {"start_new_session": True}
        try:
            proc = subprocess.Popen(
                [str(binary), *args],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                cwd=cwd,
                **popen_kwargs,
            )
        except OSError as exc:
            raise ExecutionError(f"cannot start {binary}: {exc}") from exc
        timed_out = False
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            returncode = proc.wait()
        duration = time.perf_counter() - start
        stdout, out_truncated = _read_limited(out, max_output_bytes)
        stderr, err_truncated = _read_limited(err, max_output_bytes)
    if timed_out:
        return ExecResult(None, stdout, stderr, duration, timed_out=True, truncated=out_truncated or err_truncated)
    sig, crashed = interpret_returncode(returncode)
    exit_code = None if sig is not None else returncode
    return ExecResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration=duration,
        signal=sig,
        crashed=crashed,
        truncated=out_truncated or err_truncated,
    )
