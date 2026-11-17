"""Offline verification of worker exit capture (registration §20.3).

The launch path used to send the worker's stderr to ``DEVNULL`` and record only the
synthesized ``stopped_by=sigkill`` stamp, so a worker that died on its own was
indistinguishable from one the orchestrator killed — exactly the ambiguity that left
run ``1344f244…`` unexplainable. These tests drive the real capture code with a fake
worker: no model calls, no database.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from server import orchestrator as orch


def _handle(proc: asyncio.subprocess.Process, stderr_path: Path, stderr_file: Any) -> Any:
    handle = orch.RunHandle(
        run_id=uuid.uuid4().hex,
        session_id="pilot-test",
        proc=proc,
        wall_timeout_s=1800,
    )
    handle._stderr_path = stderr_path
    handle._stderr_file = stderr_file
    return handle


async def test_worker_exit_record_keeps_stderr_and_real_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run-root"
    (run_root / "run").mkdir(parents=True)
    monkeypatch.setattr(orch, "run_dir_for", lambda run_id: run_root)

    stderr_path = run_root / "run" / "engine.stderr.log"
    stderr_file = open(stderr_path, "ab", buffering=0)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('boom: fake worker died\\n'); sys.exit(3)",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=stderr_file,
    )
    await proc.wait()

    handle = _handle(proc, stderr_path, stderr_file)
    record = orch._record_worker_exit(handle)

    # A self-exit keeps its own code and is not attributed to the parent.
    assert record["exit_code"] == 3
    assert record["signal"] is None
    assert record["stopped_by_parent"] is False
    assert record["finished_frame"] is False
    assert record["stderr_bytes"] > 0
    assert "boom: fake worker died" in stderr_path.read_text(encoding="utf-8", errors="replace")

    on_disk = json.loads((run_root / "run" / "worker_exit.json").read_text(encoding="utf-8"))
    assert on_disk == record
    assert handle._stderr_file is None  # closed once the record is written


async def test_parent_kill_is_marked_and_signal_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run-root-killed"
    (run_root / "run").mkdir(parents=True)
    monkeypatch.setattr(orch, "run_dir_for", lambda run_id: run_root)

    stderr_path = run_root / "run" / "engine.stderr.log"
    stderr_file = open(stderr_path, "ab", buffering=0)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=stderr_file,
        start_new_session=True,
    )
    handle = _handle(proc, stderr_path, stderr_file)

    # Drive the real kill path with a stubbed config, so the flag is set by the
    # production code and not by the test.
    killer = orch.Orchestrator.__new__(orch.Orchestrator)
    killer._cfg = SimpleNamespace(stop_grace_period_s=1)  # type: ignore[assignment]
    await killer._kill_handle(handle, grace=1)

    record = orch._record_worker_exit(handle)
    assert handle._killed_by_parent is True
    assert record["stopped_by_parent"] is True
    assert record["signal"] in {signal.SIGTERM, signal.SIGKILL}
    assert record["exit_code"] is None
    assert (run_root / "run" / "worker_exit.json").exists()
