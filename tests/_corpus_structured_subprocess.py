"""Zero-external-I/O subprocess boundary for structured publication tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BOOTSTRAP = """
import socket
def denied(*args, **kwargs):
    raise AssertionError('structured test external I/O forbidden')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
socket.getaddrinfo = denied
import dotenv, dotenv.main
dotenv.load_dotenv = denied
dotenv.main.load_dotenv = denied
import httpx
httpx.HTTPTransport.handle_request = denied
httpx.AsyncHTTPTransport.handle_async_request = denied
from plugins.corpus.service import CorpusService
CorpusService._connect = denied
"""


def isolated_process(script: str, *, cwd: Path, root: Path, run_id: str = "synthetic"):
    """Start a child with no inherited credentials and blockers before task imports."""
    repo = Path(__file__).resolve().parents[1]
    return subprocess.Popen(
        [sys.executable, "-c", BOOTSTRAP + "\n" + script],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "PATH": os.pathsep.join((str(Path(sys.executable).parent), "/usr/bin", "/bin")),
            "PYTHONPATH": os.pathsep.join((str(repo), str(repo / "tests"))),
            "PYTHONNOUSERSITE": "1",
            "HOME": str(cwd),
            "CORPUS_STRUCTURED_ROOT": str(root),
            "RESEARCH_RUN_ID": f"{run_id}:{cwd.name}",
        },
    )


def finish_process(process, expected_code: int = 0) -> str:
    """Bound child execution and expose failures without leaking inherited secrets."""
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    assert process.returncode == expected_code, stderr
    return stdout


def run_isolated(script: str, *, cwd: Path, root: Path, expected_code: int = 0) -> str:
    """Run an isolated child to completion."""
    return finish_process(isolated_process(script, cwd=cwd, root=root), expected_code)
