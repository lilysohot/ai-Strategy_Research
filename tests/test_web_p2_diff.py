"""P2.5 run diff tests (cli-web-parity.md §5.4).

Baseline semantics: the FIRST file-tool write to a path snapshots the content
that existed before it (missing → /dev/null baseline → status "added"). At run
end a unified diff with +/- statistics is produced from those baselines;
bash-only changes surface as display-only entries (``source="bash_scan"``, no
hunks, not revertible — that waits for P3.3). The route serves the generated
``diff.json`` behind the same ownership gate as the other artifact routes.

The recorder maps sandbox aliases (/outputs, /workspace) through the existing
``resolve_runtime_path`` — no second path-resolution point — and refuses to
snapshot anything that resolves outside the two writable roots.
"""

from __future__ import annotations

import json
import types
import uuid

import pytest

from server.config import build_run_paths, get_config
from server.diff import DiffRecorder
from server.store import create_run, init_db

# ── DiffRecorder unit tests ─────────────────────────────────────


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    """A fake run root whose mount aliases point into it (worker does the same)."""
    run_root = tmp_path / "run1"
    outputs = run_root / "ws" / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", str(run_root / "ws"))
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", str(outputs))
    return run_root, outputs


def _recorder(run_root):
    from server.diff import DiffRecorder

    return DiffRecorder(run_root=run_root, outputs_root=run_root / "ws" / "outputs")


def _call(name: str, **args) -> dict:
    return {"id": "call_1", "name": name, "args": args}


async def _record(rec, name: str, **args) -> None:
    ctx = types.SimpleNamespace(turn=1)
    await rec.on_tool_call(ctx, _call(name, **args))


@pytest.mark.asyncio
async def test_added_file_diff(run_env):
    """A file-tool write to a path that did not exist diffs against /dev/null."""
    run_root, outputs = run_env
    rec = _recorder(run_root)
    await _record(rec, "create_file", path="/outputs/report.md")
    (outputs / "report.md").write_text("hello\n", encoding="utf-8")

    body = rec.write_diff()
    files = body["files"]
    assert len(files) == 1
    entry = files[0]
    assert entry["path"] == "/outputs/report.md"
    assert entry["status"] == "added"
    assert entry["source"] == "file_tool"
    assert entry["additions"] == 1
    assert entry["deletions"] == 0
    assert "+hello" in entry["hunks"]


@pytest.mark.asyncio
async def test_modified_diff_uses_first_touch_baseline(run_env):
    """The baseline is the content at FIRST touch; later edits do not re-snapshot."""
    run_root, outputs = run_env
    (outputs / "notes.txt").write_text("v1\n", encoding="utf-8")
    rec = _recorder(run_root)
    await _record(rec, "write_file", path="/outputs/notes.txt", content="v2")
    (outputs / "notes.txt").write_text("v2\n", encoding="utf-8")
    # A second touch must NOT refresh the baseline.
    await _record(
        rec, "file_editor_str_replace", path="/outputs/notes.txt", old_str="v2", new_str="v3"
    )
    (outputs / "notes.txt").write_text("v3\n", encoding="utf-8")

    entry = rec.write_diff()["files"][0]
    assert entry["status"] == "modified"
    assert "-v1" in entry["hunks"]
    assert "+v3" in entry["hunks"]
    assert entry["additions"] == 1
    assert entry["deletions"] == 1


@pytest.mark.asyncio
async def test_ignores_non_file_tools_and_bad_args(run_env):
    """bash and malformed calls record nothing; an empty run yields no files."""
    run_root, _outputs = run_env
    rec = _recorder(run_root)
    await _record(rec, "bash", command="echo hi > /outputs/x.txt")
    await _record(rec, "create_file")  # missing path
    await _record(rec, "write_file", path=42)  # non-string path
    await _record(rec, "file_editor_view", path="/outputs/read_only.md")  # read-only tool

    assert rec.write_diff() == {"files": []}


@pytest.mark.asyncio
async def test_deleted_status(run_env):
    """A file removed after being snapshotted reports status=deleted."""
    run_root, outputs = run_env
    (outputs / "gone.txt").write_text("bye\n", encoding="utf-8")
    rec = _recorder(run_root)
    await _record(rec, "write_file", path="/outputs/gone.txt", content="bye")
    (outputs / "gone.txt").unlink()

    entry = rec.write_diff()["files"][0]
    assert entry["status"] == "deleted"
    assert entry["deletions"] == 1


@pytest.mark.asyncio
async def test_outside_roots_never_snapshotted(run_env):
    """Traversal and paths outside the two writable roots are refused (read
    containment, fail-closed): they cannot leak into the diff either."""
    run_root, _outputs = run_env
    (run_root / "secret.txt").write_text("top secret\n", encoding="utf-8")
    rec = _recorder(run_root)
    await _record(rec, "write_file", path="/outputs/../../secret.txt")
    await _record(rec, "write_file", path="/etc/passwd")
    await _record(rec, "write_file", path="relative/path.txt")

    assert rec.write_diff() == {"files": []}
    assert "top secret" not in json.dumps(rec.write_diff())


@pytest.mark.asyncio
async def test_bash_scan_entries_are_display_only(run_env):
    """Files changed only via bash come from the run-start baseline scan: real
    status, no hunks, source=bash_scan."""
    run_root, outputs = run_env
    (outputs / "base.txt").write_text("orig\n", encoding="utf-8")
    rec = _recorder(run_root)
    rec.snapshot_outputs_baseline()

    # Simulate bash writes after the baseline was taken.
    (outputs / "base.txt").write_text("rewritten\n", encoding="utf-8")
    (outputs / "new.txt").write_text("created\n", encoding="utf-8")

    files = {f["path"]: f for f in rec.write_diff()["files"]}
    assert files["/outputs/base.txt"]["source"] == "bash_scan"
    assert files["/outputs/base.txt"]["status"] == "modified"
    assert files["/outputs/new.txt"]["status"] == "added"
    for entry in files.values():
        assert entry["hunks"] == ""
        assert entry["additions"] == 0 and entry["deletions"] == 0


@pytest.mark.asyncio
async def test_binary_file_skipped_in_diff(run_env):
    """Binary content (docx etc.) is skipped in the payload (§2.2: binary and
    oversized files leave no comparable baseline). The on-disk snapshot taken
    at first touch is still kept for P3.3 /revert."""
    run_root, outputs = run_env
    rec = _recorder(run_root)
    await _record(rec, "create_file", path="/outputs/report.docx")
    (outputs / "report.docx").write_bytes(b"PK\x03\x04\x00\x01binary")

    assert rec.write_diff() == {"files": []}


@pytest.mark.asyncio
async def test_bash_scan_covers_working_directory(run_env):
    """§2.2 第二类扫描的是工作目录: bash writes inside ws/ (outside the
    deliverable outputs dir) surface as display-only bash_scan entries too."""
    run_root, _outputs = run_env
    ws = run_root / "ws"
    rec = DiffRecorder(
        run_root=run_root,
        outputs_root=run_root / "ws" / "outputs",
        workspace_root=ws,
    )
    rec.snapshot_outputs_baseline()
    (ws / "scratch.log").write_text("bash wrote this\n", encoding="utf-8")

    files = {f["path"]: f for f in rec.write_diff()["files"]}
    entry = files["/workspace/scratch.log"]
    assert entry["source"] == "bash_scan"
    assert entry["status"] == "added"
    assert entry["hunks"] == ""


@pytest.mark.asyncio
async def test_write_diff_persists_diff_json(run_env):
    """write_diff also persists run_root/diff.json for the serving route."""
    run_root, outputs = run_env
    rec = _recorder(run_root)
    await _record(rec, "create_file", path="/outputs/a.md")
    (outputs / "a.md").write_text("x\n", encoding="utf-8")

    body = rec.write_diff()
    persisted = json.loads((run_root / "diff.json").read_text(encoding="utf-8"))
    assert persisted == body


# ── GET /api/runs/{id}/diff route tests ─────────────────────────


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
        "/api/auth/register", json={"username": "p25-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post("/api/auth/login", json={"username": "p25-user", "password": pwd})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def alt_headers(app_client):
    await init_db()
    pwd = "Str0ngPass2"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "p25-other", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "p25-other", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def owned_run(auth_headers, tmp_path, monkeypatch):
    """A completed run owned by the fixture user, with a private runs root."""
    monkeypatch.setattr(get_config(), "runs_root", tmp_path)
    from server.orchestrator import _session_uuid
    from server.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ").strip()
    uid = decode_access_token(token)
    run_id = uuid.uuid4()
    await create_run(
        run_id=run_id,
        session_id=_session_uuid("p25-diff"),
        user_id=uid,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir=str(tmp_path / run_id.hex),
        status="completed",
    )
    build_run_paths(run_id.hex)
    return run_id.hex


@pytest.mark.asyncio
async def test_diff_requires_auth(app_client):
    resp = await app_client.get(f"/api/runs/{uuid.uuid4().hex}/diff")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_diff_404_for_foreign_run(app_client, alt_headers, owned_run):
    """Another user's run reads as 404 (no existence oracle)."""
    resp = await app_client.get(f"/api/runs/{owned_run}/diff", headers=alt_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diff_serves_generated_payload(app_client, auth_headers, owned_run, tmp_path):
    """The route returns the worker-generated diff.json verbatim."""
    payload = {
        "files": [
            {
                "path": "/outputs/report.md",
                "status": "added",
                "source": "file_tool",
                "hunks": "+hi\n",
                "additions": 1,
                "deletions": 0,
                "binary": False,
            }
        ]
    }
    (tmp_path / owned_run / "diff.json").write_text(json.dumps(payload), encoding="utf-8")
    resp = await app_client.get(f"/api/runs/{owned_run}/diff", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == payload


@pytest.mark.asyncio
async def test_diff_404_when_never_generated(app_client, auth_headers, owned_run):
    """No diff.json (old run / crashed run) reads as 404 → the UI hides the tab."""
    resp = await app_client.get(f"/api/runs/{owned_run}/diff", headers=auth_headers)
    assert resp.status_code == 404
