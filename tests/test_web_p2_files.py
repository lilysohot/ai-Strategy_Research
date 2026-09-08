"""P2.3 artifact preview endpoint tests (cli-web-parity.md §5.4).

The preview route must reuse ``resolve_artifact_path`` — the single path
containment point — and return ``{kind, content?, truncated}``:

  * text files: content with size/line truncation (``truncated`` flag);
  * images: ``data:`` URL payload (rendered by the frontend ``<img>``);
  * binary: no content — the UI falls back to the download button.

Traversal, missing files and foreign-run access stay 404 (no existence
oracle), unauthenticated stays 401 — same contract as the download route.
"""

from __future__ import annotations

import uuid

import pytest

from server.config import build_run_paths, get_config
from server.store import create_run, init_db


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
        "/api/auth/register", json={"username": "p23-user", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "p23-user", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def alt_headers(app_client):
    """A second user, used to prove run ownership isolation."""
    await init_db()
    pwd = "Str0ngPass2"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "p23-other", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "p23-other", "password": pwd}
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
        session_id=_session_uuid("p23-preview"),
        user_id=uid,
        prompt="p",
        pipeline_id="stateful-react-agent",
        run_dir=str(tmp_path / run_id.hex),
        status="completed",
    )
    outputs = build_run_paths(run_id.hex)["outputs"]
    return run_id.hex, outputs


async def _preview(client, headers: dict, run_id: str, path: str):
    return await client.get(
        f"/api/runs/{run_id}/artifacts/preview",
        params={"path": path},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_preview_requires_auth(app_client):
    """Unauthenticated preview must be 401 (same as list/download)."""
    resp = await _preview(app_client, {}, uuid.uuid4().hex, "report.md")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_preview_text_file(app_client, auth_headers, owned_run):
    """A markdown deliverable previews as full text, not truncated."""
    run_id, outputs = owned_run
    (outputs / "report.md").write_text(
        "# Report\n\nhello web preview\n", encoding="utf-8"
    )
    resp = await _preview(app_client, auth_headers, run_id, "report.md")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "text"
    assert body["content"] == "# Report\n\nhello web preview\n"
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_preview_truncates_large_text(app_client, auth_headers, owned_run):
    """Oversized text is cut to the preview cap with truncated=True."""
    run_id, outputs = owned_run
    big = "\n".join(f"line {i}" for i in range(50_000))
    (outputs / "big.log").write_text(big + "\n", encoding="utf-8")
    resp = await _preview(app_client, auth_headers, run_id, "big.log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "text"
    assert body["truncated"] is True
    assert len(body["content"]) < len(big)
    assert body["content"].startswith("line 0\n")


@pytest.mark.asyncio
async def test_preview_image_returns_data_url(app_client, auth_headers, owned_run):
    """Images come back as a data URL the frontend can put in ``<img>``."""
    run_id, outputs = owned_run
    (outputs / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
    resp = await _preview(app_client, auth_headers, run_id, "chart.png")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "image"
    assert body["content"].startswith("data:image/png;base64,")
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_preview_binary_kinds(app_client, auth_headers, owned_run):
    """Known binary containers and sniffed binary blobs get kind=binary."""
    run_id, outputs = owned_run
    (outputs / "pack.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    (outputs / "blob.dat").write_bytes(b"\x00\x01\x02binary-ish\x00")
    zip_resp = await _preview(app_client, auth_headers, run_id, "pack.zip")
    assert zip_resp.status_code == 200
    assert zip_resp.json()["kind"] == "binary"
    assert "content" not in zip_resp.json()
    dat_resp = await _preview(app_client, auth_headers, run_id, "blob.dat")
    assert dat_resp.status_code == 200
    assert dat_resp.json()["kind"] == "binary"


@pytest.mark.asyncio
async def test_preview_rejects_traversal_and_missing(app_client, auth_headers,
                                                     owned_run):
    """Traversal attempts and missing files read as 404 (no oracle)."""
    run_id, _outputs = owned_run
    for bad in ("../../secret.txt", "/etc/passwd", "nope.md", "../ws/run.json"):
        resp = await _preview(app_client, auth_headers, run_id, bad)
        assert resp.status_code == 404, f"not blocked: {bad}"


@pytest.mark.asyncio
async def test_preview_404_for_foreign_run(app_client, auth_headers, alt_headers,
                                           owned_run):
    """Another user's run reads as 404 (no existence oracle)."""
    run_id, outputs = owned_run
    (outputs / "report.md").write_text("secret-ish", encoding="utf-8")
    resp = await _preview(app_client, alt_headers, run_id, "report.md")
    assert resp.status_code == 404
