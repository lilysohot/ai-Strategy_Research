"""T2.9 artifact-chain tests (mock LLM for the end-to-end path, zero API cost).

Covers the two things plan.md T2.9 asks for:

  1. a run's deliverables in ``ws/outputs`` (nested inside the workspace, per
     tech-stack.md §5.1) are scanned at the run's terminal state and recorded in
     the artifacts table with size + sha256;
  2. the download endpoint resolves a caller-supplied ``rel_path`` only inside that
     outputs dir — absolute paths, ``..`` traversal and escaping symlinks are all
     rejected.

The end-to-end test drives a real worker (create_file writes into ws/outputs) so
the scan timing in the orchestrator is exercised, not just the helper functions.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
from server.artifacts import resolve_artifact_path, scan_outputs
from server.config import build_run_paths, get_config, run_dir_for
from server.store import (
    create_run,
    init_db,
    list_artifacts,
    record_artifacts,
)


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(app_client):
    """Register + log in a fixture user so authed routes can be exercised."""
    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "t29-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "t29-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def alt_headers(app_client):
    """A second user, used to prove artifact ownership isolation."""
    await init_db()
    pwd = "Str0ngPass2"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "t29-other", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "t29-other", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _user_id(auth_headers: dict) -> uuid.UUID:
    from server.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    return decode_access_token(token)


# ── scan_outputs ───────────────────────────────────────────────


def test_scan_outputs_records_size_and_sha256(tmp_path, monkeypatch):
    """Scanning a run's outputs yields posix rel_paths with size + sha256."""
    run_id = uuid.uuid4().hex
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    paths = build_run_paths(run_id)
    outputs = paths["outputs"]

    (outputs / "report.md").write_text("# hello\n", encoding="utf-8")
    (outputs / "nested").mkdir()
    (outputs / "nested" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    found = {a["rel_path"]: a for a in scan_outputs(run_id)}
    assert set(found) == {"report.md", "nested/data.csv"}

    body = b"# hello\n"
    entry = found["report.md"]
    assert entry["size"] == len(body)
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()

    csv_body = b"a,b\n1,2\n"
    assert found["nested/data.csv"]["sha256"] == hashlib.sha256(csv_body).hexdigest()


def test_scan_outputs_empty_when_nothing_written(tmp_path, monkeypatch):
    run_id = uuid.uuid4().hex
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    build_run_paths(run_id)
    assert scan_outputs(run_id) == []


def test_scan_outputs_ignores_escaping_symlink(tmp_path, monkeypatch):
    """A symlink pointing outside outputs is not recorded (containment)."""
    run_id = uuid.uuid4().hex
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    outputs = build_run_paths(run_id)["outputs"]

    outside = tmp_path / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")
    try:
        (outputs / "leak.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported in this environment")
    assert scan_outputs(run_id) == []


# ── path containment (download safety) ─────────────────────────


def test_resolve_artifact_path_accepts_inside_and_rejects_escape(tmp_path,
                                                                 monkeypatch):
    run_id = uuid.uuid4().hex
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    outputs = build_run_paths(run_id)["outputs"]
    target = outputs / "report.md"
    target.write_text("ok", encoding="utf-8")

    # Normal relative path resolves inside the outputs dir.
    assert resolve_artifact_path(run_id, "report.md") == target.resolve()

    # Traversal escapes the root → rejected.
    assert resolve_artifact_path(run_id, "../ws/outputs/report.md") is None
    assert resolve_artifact_path(run_id, "../../../../etc/passwd") is None
    # Absolute paths are rejected outright.
    assert resolve_artifact_path(run_id, "/etc/passwd") is None
    assert resolve_artifact_path(run_id, "//etc/passwd") is None
    # Empty / NUL are rejected.
    assert resolve_artifact_path(run_id, "") is None
    assert resolve_artifact_path(run_id, "a\x00b") is None
    # The root itself is a directory, not a downloadable file.
    assert resolve_artifact_path(run_id, ".") is None
    # A path that exists but is a directory inside outputs is not a file.
    (outputs / "sub").mkdir()
    assert resolve_artifact_path(run_id, "sub") is None
    # Non-existent file inside the root still resolves to a path (caller 404s later).
    assert resolve_artifact_path(run_id, "missing.md") is None


def test_resolve_artifact_path_rejects_symlink_escape(tmp_path, monkeypatch):
    run_id = uuid.uuid4().hex
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    outputs = build_run_paths(run_id)["outputs"]
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    try:
        (outputs / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported in this environment")
    assert resolve_artifact_path(run_id, "link.txt") is None


# ── store layer ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_artifacts_upserts_and_isolates_owners(monkeypatch, tmp_path):
    """Artifacts are keyed by (run_id, rel_path) and only visible to the owner."""
    from server import store

    cfg = get_config()
    orig_url = cfg.database_url
    monkeypatch.setattr(cfg, "database_url", f"sqlite+aiosqlite:///{tmp_path}/t29.db")
    await store.reset_engine()
    await init_db()

    try:
        owner = uuid.uuid4()
        other = uuid.uuid4()
        sid = uuid.uuid4()
        run_id = uuid.uuid4()
        await create_run(
            run_id=run_id, session_id=sid, user_id=owner, prompt="p",
            pipeline_id="stateful-react-agent", run_dir="/tmp/x", status="completed",
        )

        await record_artifacts(run_id=run_id, artifacts=[
            {"rel_path": "report.md", "size": 10, "sha256": "abc"},
            {"rel_path": "a/b.csv", "size": 5, "sha256": "def"},
        ])
        rows = await list_artifacts(run_id=run_id, user_id=owner)
        assert {r.rel_path for r in rows} == {"report.md", "a/b.csv"}
        assert next(r for r in rows if r.rel_path == "report.md").sha256 == "abc"

        # Re-recording the same run updates in place (no duplicate rows).
        await record_artifacts(run_id=run_id, artifacts=[
            {"rel_path": "report.md", "size": 12, "sha256": "zzz"},
        ])
        rows = await list_artifacts(run_id=run_id, user_id=owner)
        assert len(rows) == 2
        assert next(r for r in rows if r.rel_path == "report.md").sha256 == "zzz"

        # A different user sees nothing (anti-IDOR).
        assert await list_artifacts(run_id=run_id, user_id=other) == []
    finally:
        cfg.database_url = orig_url
        await store.reset_engine()


# ── HTTP endpoints ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artifact_endpoints_require_auth(app_client):
    """Unauthenticated listing/download must be 401."""
    run_id = uuid.uuid4().hex
    listed = await app_client.get(f"/api/runs/{run_id}/artifacts")
    assert listed.status_code == 401
    down = await app_client.get(
        f"/api/runs/{run_id}/artifacts/download", params={"path": "report.md"}
    )
    assert down.status_code == 401


@pytest.mark.asyncio
async def test_artifact_listing_404_for_foreign_run(app_client, auth_headers,
                                                    alt_headers):
    """Another user's run reads as 404 (no existence oracle)."""
    await init_db()
    # Alice creates a run of her own (via a session + run row).
    from server.orchestrator import _session_uuid
    from server.store import create_run

    uid = _user_id(auth_headers)
    sid = _session_uuid("t29-iso")
    run_id = uuid.uuid4()
    await create_run(
        run_id=run_id, session_id=sid, user_id=uid, prompt="p",
        pipeline_id="stateful-react-agent", run_dir="/tmp/x", status="completed",
    )
    # Alice sees it; Bob does not (404 rather than an empty 200 list).
    mine = await app_client.get(
        f"/api/runs/{run_id}/artifacts", headers=auth_headers
    )
    assert mine.status_code == 200
    theirs = await app_client.get(
        f"/api/runs/{run_id}/artifacts", headers=alt_headers
    )
    assert theirs.status_code == 404


# ── end-to-end: real run → scan → download ─────────────────────


@pytest.fixture
async def mock_llm_report():
    server = MockLLMServer(script=[
        tool_call_turn("create_file", {
            "path": "/outputs/report.md",
            "content": "# Report\n\nDeliverable written by create_file.\n",
        }),
        text_turn("Report written to /outputs/report.md."),
    ]).start()
    yield server
    server.stop()


@pytest.fixture
def isolated_orchestrator(monkeypatch):
    """Swap in a private Orchestrator so a leftover run from another test file
    cannot occupy the concurrency slot this test's run needs."""
    import server.orchestrator as orch_mod

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch_mod, "_orchestrator", orch)
    return orch


def _spawn_approver(orch, run_id: str, client, headers):
    """Answer the P3.2 approval gate the way a user would.

    Since the gate landed (P3.2), a worker's ``create_file`` suspends on
    ``approval_requested`` until a decision arrives — an old e2e that never
    answers would hang the worker for the gate's 300s timeout. This task
    subscribes to the run's event fan-out and approves ``once`` via the real
    API route, so the approval path itself stays exercised.
    """

    async def run() -> None:
        q = orch.subscribe(run_id)
        while True:
            evt = await asyncio.wait_for(q.get(), timeout=90)
            if evt and evt.get("type") == "approval_requested":
                resp = await client.post(
                    f"/api/runs/{run_id}/approve",
                    json={"approval_id": evt["approval_id"], "decision": "once"},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text
                return

    return asyncio.ensure_future(run())


@pytest.mark.asyncio
async def test_run_scans_outputs_and_downloads(mock_llm_report, app_client,
                                               auth_headers, isolated_orchestrator,
                                               monkeypatch):
    """T2.9 end-to-end: a run's deliverable is indexed and downloadable."""
    monkeypatch.setenv("OPENAI_BASE_URL", mock_llm_report.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-spike-mock")
    monkeypatch.setenv("OPENAI_MODEL", mock_llm_report.model)
    cfg = get_config()
    monkeypatch.setattr(cfg, "wall_timeout_s", 120)
    monkeypatch.setattr(cfg, "worker_pool_size", 1)
    await init_db()

    resp = await app_client.post("/api/runs", json={
        "message": "write a short report to /outputs/report.md using create_file",
        "session_id": "t29-artifacts-session",
    }, headers=auth_headers)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    # A create_file now suspends on the approval gate (P3.2) — answer it.
    approver = _spawn_approver(isolated_orchestrator, run_id, app_client, auth_headers)

    # The orchestrator scans outputs after the worker exits; poll for the index.
    listed = None
    for _ in range(120):
        await asyncio.sleep(0.5)
        listed = await app_client.get(
            f"/api/runs/{run_id}/artifacts", headers=auth_headers
        )
        if listed.status_code == 200 and listed.json()["artifacts"]:
            break
    assert listed is not None and listed.status_code == 200
    artifacts = listed.json()["artifacts"]
    assert artifacts, "no artifact indexed for the run"
    # The run cannot have produced a deliverable without passing the gate.
    await asyncio.wait_for(approver, timeout=5)

    entry = next(a for a in artifacts if a["rel_path"] == "report.md")
    assert entry["size"] and entry["size"] > 0
    assert entry["sha256"] and len(entry["sha256"]) == 64

    # The recorded sha256 must match the file actually on disk.
    on_disk = run_dir_for(run_id) / "ws" / "outputs" / "report.md"
    assert on_disk.exists()
    digest = hashlib.sha256(on_disk.read_bytes()).hexdigest()
    assert entry["sha256"] == digest

    # Download by rel_path returns the deliverable.
    down = await app_client.get(
        f"/api/runs/{run_id}/artifacts/download",
        params={"path": "report.md"}, headers=auth_headers,
    )
    assert down.status_code == 200, down.text
    assert b"Deliverable written by create_file" in down.content

    # Traversal attempts never escape the outputs dir (404, not 400 — no oracle).
    for bad in ("../../../../etc/passwd", "/etc/passwd", "../ws/outputs/report.md"):
        bad_resp = await app_client.get(
            f"/api/runs/{run_id}/artifacts/download",
            params={"path": bad}, headers=auth_headers,
        )
        assert bad_resp.status_code == 404, f"traversal not blocked: {bad}"
