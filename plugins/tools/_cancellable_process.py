"""Cooperatively cancel a threaded local command and reap its process group."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time


def run_cancellable(
    argv: list[str],
    *,
    timeout: float,
    env: dict[str, str],
    input: str | None,
    cancel: threading.Event,
) -> subprocess.CompletedProcess[str]:
    """Keep cancellation scoped to this command, including its child processes."""
    if cancel.is_set():
        return subprocess.CompletedProcess(argv, -signal.SIGKILL, "", "cancelled")
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    ) as proc:
        try:
            pending_input = input
            while True:
                if cancel.is_set():
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    stdout, stderr = proc.communicate()
                    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    stdout, stderr = proc.communicate(pending_input, timeout=min(0.1, remaining))
                    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    # communicate keeps its partially sent stdin between retries.
                    pending_input = None
        finally:
            # Also close descendants retaining pipes when a timeout/exception fires.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
