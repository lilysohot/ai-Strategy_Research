"""P3.3 run revert tests (cli-web-parity.md §6.3).

Terminal semantics being replicated: ``/revert`` undoes the FIRST diff class
only — files a file tool explicitly targeted, snapshotted before the write. The
second class (§2.2: the bash scan) is display-only and is handed to a human,
because a scan cannot tell the agent's write from the user's editor or a dev
server writing in the same window; reverting it would destroy unrelated work.

The manifest written by ``DiffRecorder`` is the allow-list: a path is
revertible iff a file tool snapshotted it. Two restore outcomes:

* ``restored`` — a baseline existed and was written back;
* ``removed``  — the baseline was /dev/null, so deleting the file IS the revert.

Route-level contract: ownership (404 on a foreign id), post-run only (409 while
the worker is still writing), and per-path results so the UI can explain a
row that is not revertable instead of failing the whole selection.
"""

from __future__ import annotations

import json
import os
import types
import uuid

import pytest

from server.config import get_config
from server.diff import DiffRecorder, revert_paths
from server.store import create_run, init_db

# ── helpers ────────────────────────────────────────────────────────


def _call(name: str, **args) -> dict:
    return {"id": "call_1", "name": name, "args": args}


async def _record(rec: DiffRecorder, name: str, **args) -> None:
    await rec.on_tool_call(types.SimpleNamespace(turn=1), _call(name, **args))


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    """A fake run root whose mount aliases point into it (worker does the same)."""
    run_root = tmp_path / "run1"
    outputs = run_root / "ws" / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", str(run_root / "ws"))
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", str(outputs))
    return run_root, outputs


def _recorder(run_root, outputs):
    return DiffRecorder(run_root=run_root, outputs_root=outputs)


# ── revert_paths unit tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_revert_restores_modified_file(run_env):
    """A file the agent overwrote goes back to its pre-run content."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    target = outputs / "report.md"
    target.write_text("original\n", encoding="utf-8")
    await _record(rec, "write_file", path="/outputs/report.md", content="changed")
    target.write_text("changed\n", encoding="utf-8")
    rec.write_diff()

    out = revert_paths(run_root, ["/outputs/report.md"])
    assert out["reverted"] == ["/outputs/report.md"]
    assert out["results"][0]["status"] == "restored"
    assert target.read_text(encoding="utf-8") == "original\n"


@pytest.mark.asyncio
async def test_revert_removes_file_created_by_the_run(run_env):
    """Baseline /dev/null: the file did not exist before, so deleting it is the
    revert — leaving it behind would preserve exactly the change being undone."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    target = outputs / "new.md"
    await _record(rec, "create_file", path="/outputs/new.md", content="hi")
    target.write_text("hi\n", encoding="utf-8")
    rec.write_diff()

    out = revert_paths(run_root, ["/outputs/new.md"])
    assert out["results"][0]["status"] == "removed"
    assert not target.exists()


@pytest.mark.asyncio
async def test_revert_restores_deleted_file(run_env):
    """A file the agent deleted comes back with its pre-run bytes."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    target = outputs / "keep.txt"
    target.write_text("keep me\n", encoding="utf-8")
    await _record(rec, "write_file", path="/outputs/keep.txt", content="x")
    target.unlink()
    rec.write_diff()

    out = revert_paths(run_root, ["/outputs/keep.txt"])
    assert out["results"][0]["status"] == "restored"
    assert target.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.asyncio
async def test_revert_refuses_bash_scan_class(run_env):
    """§6.3: the scan class is never auto-reverted — it must say so explicitly,
    or the user reads the refusal as a bug."""
    run_root, outputs = run_env
    scanned = outputs / "base.txt"
    scanned.write_text("orig\n", encoding="utf-8")
    rec = _recorder(run_root, outputs)
    rec.snapshot_outputs_baseline()
    scanned.write_text("rewritten by someone\n", encoding="utf-8")
    rec.write_diff()

    out = revert_paths(run_root, ["/outputs/base.txt"])
    result = out["results"][0]
    assert result["status"] == "rejected"
    assert result["reason"] == "not_snapshotted"
    assert result["message"]
    assert out["reverted"] == []
    # Untouched: the whole point is not to destroy work we cannot attribute.
    assert scanned.read_text(encoding="utf-8") == "rewritten by someone\n"


@pytest.mark.asyncio
async def test_revert_refuses_everything_it_never_snapshotted(run_env):
    """The manifest is the allow-list, so a path no file tool targeted is refused
    before any filesystem work happens — including aliases that were never
    writable (``/inputs``), host paths and relative/empty junk."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    await _record(rec, "create_file", path="/outputs/ok.md")
    (outputs / "ok.md").write_text("x\n", encoding="utf-8")
    rec.write_diff()

    outside = run_root / "secret.txt"
    outside.write_text("untouched\n", encoding="utf-8")

    out = revert_paths(
        run_root,
        [
            "/outputs/never-touched.md",
            "/inputs/upload.pdf",
            "/etc/passwd",
            "relative/path.md",
            "",
        ],
    )
    assert out["reverted"] == []
    assert {r["status"] for r in out["results"]} == {"rejected"}
    assert {r["reason"] for r in out["results"]} == {"not_snapshotted"}
    assert outside.read_text(encoding="utf-8") == "untouched\n"


@pytest.mark.asyncio
async def test_revert_rechecks_containment_per_manifest_entry(run_env):
    """Containment is enforced a second time at revert, not only when the
    snapshot was taken: a hand-edited manifest (the tamper case) must still not
    be able to aim a restore outside the run's writable roots."""
    run_root, _outputs = run_env
    secret = run_root / "secret.txt"
    secret.write_text("untouched\n", encoding="utf-8")
    # What a tampered manifest would look like (keys kept normpath-stable so the
    # lookup hits) — DiffRecorder itself refuses to record either of them, see
    # test_outside_roots_never_snapshotted in test_web_p2_diff.
    (run_root / "diff").mkdir(parents=True, exist_ok=True)
    (run_root / "diff" / "manifest.json").write_text(
        json.dumps(
            {"/inputs/leak.pdf": {"snapshot": None}, "/secret.txt": {"snapshot": None}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = revert_paths(run_root, ["/inputs/leak.pdf", "/outputs/../../secret.txt"])
    assert out["reverted"] == []
    for result in out["results"]:
        assert result["status"] == "rejected"
        assert result["reason"] == "outside_roots"
    assert secret.read_text(encoding="utf-8") == "untouched\n"


@pytest.mark.asyncio
async def test_revert_refuses_symlink_escape(run_env, tmp_path):
    """A symlink planted inside outputs must not redirect the restore outside."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    await _record(rec, "create_file", path="/outputs/link.md")
    victim = tmp_path / "victim.txt"
    victim.write_text("user data\n", encoding="utf-8")
    link = outputs / "link.md"
    if link.exists():
        link.unlink()
    os.symlink(victim, link)
    rec.write_diff()

    out = revert_paths(run_root, ["/outputs/link.md"])
    assert out["results"][0]["status"] == "rejected"
    assert out["results"][0]["reason"] == "outside_roots"
    assert victim.read_text(encoding="utf-8") == "user data\n"


@pytest.mark.asyncio
async def test_revert_restores_binary_file_skipped_from_diff(run_env):
    """§2.2 keeps binary out of the diff payload but still snapshots it, so a
    binary deliverable is revertible even though it never showed a hunk."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    target = outputs / "report.docx"
    await _record(rec, "create_file", path="/outputs/report.docx")
    target.write_bytes(b"PK\x03\x04\x00\x01binary")
    assert rec.write_diff() == {"files": []}

    out = revert_paths(run_root, ["/outputs/report.docx"])
    assert out["results"][0]["status"] == "removed"
    assert not target.exists()


@pytest.mark.asyncio
async def test_revert_reports_missing_baseline(run_env):
    """A manifest entry whose snapshot file is gone is refused, not half-applied."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    target = outputs / "a.md"
    target.write_text("before\n", encoding="utf-8")
    await _record(rec, "write_file", path="/outputs/a.md", content="after")
    target.write_text("after\n", encoding="utf-8")
    rec.write_diff()
    for snap in (run_root / "diff" / "base").iterdir():
        snap.unlink()

    out = revert_paths(run_root, ["/outputs/a.md"])
    assert out["results"][0]["status"] == "rejected"
    assert out["results"][0]["reason"] == "missing_baseline"
    assert target.read_text(encoding="utf-8") == "after\n"


@pytest.mark.asyncio
async def test_revert_drops_restored_entry_from_diff_json(run_env):
    """After a successful revert the path is no longer a change, so the Diff tab
    must stop listing it (base == current is what write_diff omits too)."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    kept = outputs / "kept.md"
    kept.write_text("k1\n", encoding="utf-8")
    reverted = outputs / "gone.md"
    reverted.write_text("v1\n", encoding="utf-8")
    await _record(rec, "write_file", path="/outputs/gone.md", content="v2")
    reverted.write_text("v2\n", encoding="utf-8")
    rec.write_diff()

    revert_paths(run_root, ["/outputs/gone.md"])
    payload = json.loads((run_root / "diff.json").read_text(encoding="utf-8"))
    assert [f["path"] for f in payload["files"]] == []


@pytest.mark.asyncio
async def test_revert_mixed_batch_reports_each_path(run_env):
    """A bulk selection gets one result per path: partial success stays usable."""
    run_root, outputs = run_env
    rec = _recorder(run_root, outputs)
    a = outputs / "a.md"
    a.write_text("a1\n", encoding="utf-8")
    await _record(rec, "write_file", path="/outputs/a.md", content="a2")
    a.write_text("a2\n", encoding="utf-8")
    rec.write_diff()

    out = revert_paths(run_root, ["/outputs/a.md", "/outputs/scan.txt"])
    by_path = {r["path"]: r for r in out["results"]}
    assert by_path["/outputs/a.md"]["status"] == "restored"
    assert by_path["/outputs/scan.txt"]["status"] == "rejected"
    assert out["reverted"] == ["/outputs/a.md"]
    assert a.read_text(encoding="utf-8") == "a1\n"


@pytest.mark.asyncio
async def test_revert_without_manifest_is_a_noop(tmp_path):
    """A run that never wrote has nothing to revert; every path is refused."""
    out = revert_paths(tmp_path, ["/outputs/anything.md"])
    assert out["reverted"] == []
    assert out["results"][0]["reason"] == "not_snapshotted"


# ── POST /api/runs/{id}/revert route tests ─────────────────────────


@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(app_client):
    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "p33-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post("/api/auth/login", json={"username": "p33-user", "password": pwd})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def alt_headers(app_client):
    await init_db()
    pwd = "Str0ngPass2"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "p33-other", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "p33-other", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_run(client, headers, tmp_path, monkeypatch, *, session: str, status: str):
    """Create an owned run with status, its runs_root redirected at tmp_path."""
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    from server.orchestrator import _session_uuid
    from server.security import decode_access_token

    token = headers["Authorization"].removeprefix("Bearer ").strip()
    uid = decode_access_token(token)
    run_id = uuid.uuid4()
    await create_run(
        run_id=run_id,
        session_id=_session_uuid(session),
        user_id=uid,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir=str(tmp_path / run_id.hex),
        status=status,
    )
    return run_id.hex


@pytest.fixture
async def owned_run(app_client, auth_headers, tmp_path, monkeypatch):
    return await _make_run(
        app_client, auth_headers, tmp_path, monkeypatch,
        session="p33-revert", status="completed",
    )


@pytest.fixture
async def running_run(app_client, auth_headers, tmp_path, monkeypatch):
    return await _make_run(
        app_client, auth_headers, tmp_path, monkeypatch,
        session="p33-running", status="running",
    )


async def _seed_manifest(run_root, outputs, monkeypatch, *, existed: bool, after: str | None):
    """Drive the recorder the way the worker does, inside ``run_root``."""
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", str(run_root / "ws"))
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", str(outputs))
    rec = DiffRecorder(run_root=run_root, outputs_root=outputs)
    target = outputs / "report.md"
    if existed:
        target.write_text("before\n", encoding="utf-8")
    await _record(rec, "create_file" if not existed else "write_file", path="/outputs/report.md")
    if after is not None:
        target.write_text(after, encoding="utf-8")
    rec.write_diff()
    return target


@pytest.mark.asyncio
async def test_revert_requires_auth(app_client):
    resp = await app_client.post(
        f"/api/runs/{uuid.uuid4().hex}/revert", json={"paths": ["/outputs/a.md"]}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_revert_404_for_foreign_run(app_client, alt_headers, owned_run):
    """Another user's run is invisible (no existence oracle), as everywhere else."""
    resp = await app_client.post(
        f"/api/runs/{owned_run}/revert",
        headers=alt_headers,
        json={"paths": ["/outputs/report.md"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revert_409_while_run_is_still_running(
    app_client, auth_headers, running_run, tmp_path, monkeypatch
):
    """A live worker owns the tree; restoring a baseline underneath it would
    either be undone by its next write or leave the file half-reverted."""
    run_root = tmp_path / running_run
    outputs = run_root / "ws" / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    await _seed_manifest(run_root, outputs, monkeypatch, existed=True, after="after\n")

    resp = await app_client.post(
        f"/api/runs/{running_run}/revert",
        headers=auth_headers,
        json={"paths": ["/outputs/report.md"]},
    )
    assert resp.status_code == 409
    # Nothing was touched.
    assert (outputs / "report.md").read_text(encoding="utf-8") == "after\n"


@pytest.mark.asyncio
async def test_revert_restores_file_via_route(
    app_client, auth_headers, owned_run, tmp_path, monkeypatch
):
    run_root = tmp_path / owned_run
    outputs = run_root / "ws" / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    target = await _seed_manifest(
        run_root, outputs, monkeypatch, existed=True, after="after\n"
    )

    resp = await app_client.post(
        f"/api/runs/{owned_run}/revert",
        headers=auth_headers,
        json={"paths": ["/outputs/report.md"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reverted"] == ["/outputs/report.md"]
    assert body["results"][0]["status"] == "restored"
    assert target.read_text(encoding="utf-8") == "before\n"

    # diff.json no longer lists it; /diff reflects that immediately.
    diff = await app_client.get(f"/api/runs/{owned_run}/diff", headers=auth_headers)
    assert diff.status_code == 200
    assert diff.json()["files"] == []


@pytest.mark.asyncio
async def test_revert_refuses_scan_class_via_route(
    app_client, auth_headers, owned_run, tmp_path, monkeypatch
):
    """The §2.2 第二类 refusal survives the wire: the UI needs the reason text."""
    run_root = tmp_path / owned_run
    outputs = run_root / "ws" / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    scanned = outputs / "scan.txt"
    scanned.write_text("user edited\n", encoding="utf-8")

    resp = await app_client.post(
        f"/api/runs/{owned_run}/revert",
        headers=auth_headers,
        json={"paths": ["/outputs/scan.txt"]},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["reason"] == "not_snapshotted"
    assert result["message"]
    assert scanned.read_text(encoding="utf-8") == "user edited\n"


@pytest.mark.asyncio
async def test_revert_rejects_empty_paths(app_client, auth_headers, owned_run):
    resp = await app_client.post(
        f"/api/runs/{owned_run}/revert", headers=auth_headers, json={"paths": []}
    )
    assert resp.status_code == 422


# ── GET /api/runs/{id} (§6.4 P2 + §5.7 failure reason) ───────────────


async def test_get_run_returns_run_dir_and_status(app_client, auth_headers, owned_run, tmp_path, monkeypatch):
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    resp = await app_client.get(f"/api/runs/{owned_run}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"].replace("-", "") == owned_run
    assert body["status"] == "completed"
    assert body["run_dir"]


async def test_get_run_404_for_foreign(app_client, alt_headers, owned_run):
    """Ownership gate (uniform 404) applies to the single-run view too."""
    resp = await app_client.get(f"/api/runs/{owned_run}", headers=alt_headers)
    assert resp.status_code == 404


async def test_get_run_surfaces_error_for_failed_run(app_client, auth_headers, tmp_path, monkeypatch):
    """The persisted run row is the only place a failed run's reason lives; the
    single-run view must surface it (the live SSE never carries it)."""
    from server.store import update_run_result

    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    run_id = await _make_run(
        app_client, auth_headers, tmp_path, monkeypatch,
        session="p33-err", status="failed",
    )
    await update_run_result(run_id=uuid.UUID(run_id), status="failed", error="boom")
    resp = await app_client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["error"] == "boom"
