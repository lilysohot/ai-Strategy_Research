"""Isolated storage audit: no production DB, worker, network or model calls."""
from __future__ import annotations
import asyncio  # imported BEFORE the Popen guard — see below
import os
import json
import time
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

with tempfile.TemporaryDirectory(prefix="frontier-storage-audit-") as tmp:
    os.environ.update({
        "SERVER_DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/bootstrap.db",
        "SERVER_RUNS_ROOT": f"{tmp}/runs",
        "SERVER_UPLOADS_ROOT": f"{tmp}/uploads",
        "SERVER_DEBUG": "true",
        "SERVER_MASTER_KEY": "audit-only-synthetic-master-key",
        "SERVER_JWT_SECRET": "audit-only-synthetic-jwt-secret-32bytes-minimum",
    })
    original_connect = socket.socket.connect
    def connect_guard(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError("Audit forbids network connections")
        return original_connect(sock, address)
    socket.socket.connect = connect_guard

    # Windows portability: the proactor event loop builds its self-pipe with
    # ``socket.socketpair()``, which CPython emulates over an AF_INET loopback
    # connect — refused by the guard above, so no test could even start
    # ("Audit forbids network connections" at fixture setup). A socketpair can
    # only ever produce a connected LOCAL pair, so letting just that call
    # through opens no network path; the guard is restored immediately after.
    original_socketpair = socket.socketpair

    def socketpair_guard(*args, **kwargs):
        socket.socket.connect = original_connect
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            socket.socket.connect = connect_guard

    socket.socketpair = socketpair_guard
    def subprocess_guard(*args, **kwargs):
        raise RuntimeError("Audit forbids child processes / real workers")
    subprocess.Popen = subprocess_guard
    # Windows portability of this guard (no behaviour change on POSIX):
    #  1) ``asyncio`` is imported at module top so ``asyncio.windows_utils``
    #     captures the REAL ``subprocess.Popen`` before it is replaced —
    #     otherwise its ``class Popen(subprocess.Popen)`` fails with
    #     "argument 'code' must be code, not str".
    #  2) The asyncio spawn helpers are blocked explicitly, because on Windows
    #     they reach the Popen class captured at import, not the patched
    #     attribute — so patching ``subprocess.Popen`` alone would not stop a
    #     ``create_subprocess_exec`` from starting a real worker.
    asyncio.create_subprocess_exec = subprocess_guard  # type: ignore[assignment]
    asyncio.create_subprocess_shell = subprocess_guard  # type: ignore[assignment]
    import pytest
    args = list(sys.argv[1:])
    report_name = "audit-results.json"
    if "--audit-report" in args:
        pos = args.index("--audit-report")
        report_name = args[pos + 1]
        del args[pos:pos + 2]
    if Path(report_name).name != report_name:
        raise ValueError("report must be a basename in the audit directory")
    targets = list(args)
    if not any(".py" in arg and not arg.startswith("-") for arg in targets):
        targets.insert(0, str(Path(__file__).with_name("test_storage_chain.py")))
    class Results:
        def __init__(self):
            self.records = []
        def pytest_runtest_logreport(self, report):
            if report.when == "call" or report.failed:
                self.records.append({"test": report.nodeid, "phase": report.when,
                    "outcome": report.outcome, "duration_s": report.duration,
                    "evidence": report.longreprtext if report.failed else ""})
    capture = Results()
    result = pytest.main([*targets, "-q", "--tb=short", "-p", "no:cacheprovider",
                          "--basetemp", f"{tmp}/pytest", "-o", "asyncio_mode=auto"], plugins=[capture])
    Path(__file__).with_name(report_name).write_text(json.dumps({
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "exit_code": int(result), "network_blocked": True, "subprocesses_blocked": True,
        "production_data_accessed": False, "targets": targets, "records": capture.records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(result)
