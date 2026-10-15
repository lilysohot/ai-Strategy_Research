"""108 号 生产 PG/web 读链：只读端点的常驻测试（全离线，不触生产库）。

Exercises the ``/api/corpus/*`` routes (108 号 four, plus 109 号 ``/items``) with
a fake corpus service and a synthetic claims-store root, so no test ever opens a
real PG connection or the production structured store. The corpus side's
fail-closed refusals must surface as 4xx responses, never as empty-200s.

Run with::

    uv run pytest tests/test_web_corpus_read_chain.py -q
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest


# ── app + auth fixtures (same pattern as tests/test_web_m1.py) ────
@pytest.fixture
async def app_client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_headers(app_client):
    from server.store import init_db

    await init_db()
    pwd = "Str0ngPass1"
    reg = await app_client.post(
        "/api/auth/register", json={"username": "corpus-web-test", "password": pwd}
    )
    assert reg.status_code in (201, 409), reg.text
    login = await app_client.post(
        "/api/auth/login", json={"username": "corpus-web-test", "password": pwd}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── fake corpus service ───────────────────────────────────────────
@dataclass
class _FakeHit:
    doc_id: str
    locator: str
    title: str
    snippet: str
    score: float
    published: str
    source_id: str = "src"
    build_id: str = "bld"


class _FakeEvidence:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeService:
    def __init__(self) -> None:
        self._target_db = "postgres"

    def read_chain(self) -> str:
        return "new"

    def search_with_coverage(self, query: str, *, limit: int = 10):
        return (
            [_FakeHit("cv2:abc", "chunk:abc:body:0000", "t", "s", 1.0, "2026-10-15")],
            {"query_status": "matched"},
        )

    def fetch_verbatim(self, doc_id: str, locator: str) -> _FakeEvidence:
        return _FakeEvidence("权威原文")


class _RefusingService(_FakeService):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    def search_with_coverage(self, query: str, *, limit: int = 10):
        raise self._exc


# ── synthetic claims store root ───────────────────────────────────
_HEAD = {
    "build_id": "bld-1",
    "generation": 1,
    "manifest_sha256": "sha256:" + "0" * 64,
    "publication_id": "sha256:" + "1" * 64,
    "source_id": "src-1",
}


@pytest.fixture
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    heads = tmp_path / "cache" / "heads"
    heads.mkdir(parents=True)
    (heads / "h1.json").write_text(json.dumps(_HEAD), encoding="utf-8")
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> _FakeService:
    service = _FakeService()
    monkeypatch.setattr("server.routes.corpus._corpus_service", lambda: service)
    return service


# ── tests ─────────────────────────────────────────────────────────
async def test_corpus_routes_require_auth(app_client) -> None:
    for path in (
        "/api/corpus/status",
        "/api/corpus/search?query=x",
        "/api/corpus/claims/src-1",
        "/api/corpus/items/src-1",
    ):
        response = await app_client.get(path)
        assert response.status_code == 401, path


async def test_status_reports_chain_and_publications(
    app_client, auth_headers, fake_service, store_root
) -> None:
    response = await app_client.get("/api/corpus/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["read_chain"] == "new"
    assert body["target_db"] == "postgres"
    assert body["structured_store_root"] == str(store_root)
    assert [p["publication_id"] for p in body["claims_publications"]] == [_HEAD["publication_id"]]


async def test_search_serializes_hits(app_client, auth_headers, fake_service, store_root) -> None:
    response = await app_client.get(
        "/api/corpus/search", params={"query": "光模块", "limit": 3}, headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == {"query_status": "matched"}
    assert body["hits"][0]["doc_id"] == "cv2:abc"


async def test_document_fetch(app_client, auth_headers, fake_service) -> None:
    response = await app_client.get(
        "/api/corpus/documents/cv2:abc",
        params={"locator": "chunk:abc:body:0000"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["text"] == "权威原文"


def _structured_error(code: str, reason: str) -> Exception:
    from plugins.corpus.structured.ledger import StructuredExecutionError

    return StructuredExecutionError(code, reason)


def _store_error(message: str) -> Exception:
    from plugins.corpus.preparation.repository import StoreError

    return StoreError(message)


def _withdrawn_error(message: str) -> Exception:
    from plugins.corpus.preparation.read_pg import WithdrawnError

    return WithdrawnError(message)


def _legacy_error(message: str) -> Exception:
    from plugins.corpus.preparation.read_pg import LegacyHandleError

    return LegacyHandleError(message)


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        pytest.param(
            _structured_error("CS_NOT_PUBLISHED", "publication_head_missing"),
            404,
            id="cs-not-published",
        ),
        pytest.param(_store_error("拒绝：current_database='x' ≠ 'y'"), 409, id="store-refusal"),
        pytest.param(_withdrawn_error("source withdrawn"), 410, id="withdrawn"),
        pytest.param(_legacy_error("archive_required"), 400, id="legacy-handle"),
    ],
)
async def test_failures_surface_as_4xx(
    app_client, auth_headers, store_root, monkeypatch, exc, expected_status
) -> None:
    monkeypatch.setattr("server.routes.corpus._corpus_service", lambda: _RefusingService(exc))
    response = await app_client.get(
        "/api/corpus/search", params={"query": "x"}, headers=auth_headers
    )
    assert response.status_code == expected_status
    assert response.json()["detail"]


async def test_claims_without_store_root_conflicts(
    app_client, auth_headers, fake_service, monkeypatch
) -> None:
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", "")
    response = await app_client.get("/api/corpus/claims/src-1", headers=auth_headers)
    assert response.status_code == 409


async def test_claims_unknown_source_not_found(
    app_client, auth_headers, fake_service, store_root
) -> None:
    response = await app_client.get("/api/corpus/claims/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


async def test_claims_resolves_build_and_returns_page(
    app_client, auth_headers, fake_service, store_root, monkeypatch
) -> None:
    captured: dict = {}

    class _FakePage:
        def model_dump(self, mode: str) -> dict:
            return {"publication_id": _HEAD["publication_id"], "records": [1, 2]}

    def _fake_query_semantic(source_id, build_id, **kwargs):
        captured["args"] = (source_id, build_id)
        captured["kwargs"] = kwargs
        return _FakePage()

    import plugins.corpus.structured.query as query_module

    monkeypatch.setattr(query_module, "query_semantic", _fake_query_semantic)
    response = await app_client.get(
        "/api/corpus/claims/src-1",
        params={"purpose": "compare", "limit": 5},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["records"] == [1, 2]
    assert captured["args"] == ("src-1", "bld-1")
    assert captured["kwargs"]["purpose"] == "compare"
    assert captured["kwargs"]["store_root"] == str(store_root)
    assert captured["kwargs"]["limit"] == 5


async def test_items_without_store_root_conflicts(
    app_client, auth_headers, fake_service, monkeypatch
) -> None:
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", "")
    response = await app_client.get("/api/corpus/items/src-1", headers=auth_headers)
    assert response.status_code == 409


async def test_items_unknown_source_not_found(
    app_client, auth_headers, fake_service, store_root
) -> None:
    response = await app_client.get("/api/corpus/items/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


async def test_items_filters_role_and_reuses_build_resolution(
    app_client, auth_headers, fake_service, store_root, monkeypatch
) -> None:
    captured: dict = {}

    class _FakePage:
        def model_dump(self, mode: str) -> dict:
            return {"publication_id": _HEAD["publication_id"], "records": ["item"]}

    def _fake_query_semantic(source_id, build_id, **kwargs):
        captured["args"] = (source_id, build_id)
        captured["kwargs"] = kwargs
        return _FakePage()

    import plugins.corpus.structured.query as query_module

    monkeypatch.setattr(query_module, "query_semantic", _fake_query_semantic)
    response = await app_client.get(
        "/api/corpus/items/src-1",
        params={"limit": 5, "cursor": "p7-cursor"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["records"] == ["item"]
    assert captured["args"] == ("src-1", "bld-1")
    assert captured["kwargs"]["field_filters"] == {"role": "material_items"}
    assert captured["kwargs"]["store_root"] == str(store_root)
    # pagination round-trip: the cursor the response carries must be accepted back verbatim
    assert captured["kwargs"]["cursor"] == "p7-cursor"
