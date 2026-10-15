"""Corpus read-chain HTTP routes (108 号 生产 PG/web 读链).

    GET /api/corpus/status                    读链/目标库/claims store 状态
    GET /api/corpus/search                    生产活动 build 检索（band 生产默认）
    GET /api/corpus/documents/{doc_id}        §7.2 句柄取证回读（doc+locator）
    GET /api/corpus/claims/{source_id}        已发布 claims 语义查询（cite/compare/calculate）
    GET /api/corpus/items/{source_id}         已发布 material_items 语义查询（role 过滤）

This layer is deliberately **read-only**: every handler binds the authenticated
user (:func:`server.deps.get_current_user`), resolves the request, and translates
corpus-side failures into HTTP status codes. Nothing here writes the corpus PG
schema or the structured store, and nothing relaxes the fail-closed guards —
``CORPUS_TARGET_DB``/``CORPUS_STRUCTURED_ROOT`` keep their :mod:`pg_target`
/ ledger semantics; an unauthorised process still gets the same refusal the CLI
would (surfaced as 409, never swallowed into an empty 200).

The claims side reads the *production* structured store (``CORPUS_STRUCTURED_ROOT``);
a missing/empty store is a 409 with the ledger's own error, not a silent empty page.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, status

from server.deps import get_current_user
from server.store import User

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Same pattern as server/worker.py: make repo-root .env values
# (CORPUS_TARGET_DB / CORPUS_STRUCTURED_ROOT / CORPUS_DSN) visible to
# os.environ without overriding real process env.
load_dotenv(REPO_ROOT / ".env", override=False)

router = APIRouter(prefix="/api/corpus", tags=["corpus"])

_MAX_LIMIT = 50


# ── lazily-built singletons (per process) ─────────────────────────
if TYPE_CHECKING:
    from plugins.corpus.service import CorpusService

_service_lock = threading.Lock()
_service: CorpusService | None = None


def _corpus_service() -> CorpusService:
    """Build the read-only corpus service once; DSN/target resolve at call time."""
    global _service
    with _service_lock:
        if _service is None:
            from plugins.corpus.service import CorpusService

            _service = CorpusService()
        return _service


def _store_root() -> str | None:
    import os

    root = (os.environ.get("CORPUS_STRUCTURED_ROOT") or "").strip()
    return root or None


def _heads(store_root: str) -> list[dict]:
    """Read the publication head cache (source_id → current publication)."""
    heads: list[dict] = []
    cache_dir = Path(store_root) / "cache" / "heads"
    if not cache_dir.is_dir():
        return heads
    for path in sorted(cache_dir.glob("*.json")):
        try:
            heads.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("skipping unreadable head cache file: %s", path)
    return heads


def _resolve_build_id(store_root: str, source_id: str) -> str:
    heads = [
        head
        for head in _heads(store_root)
        if head.get("source_id") == source_id and head.get("build_id")
    ]
    if not heads:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"该 source 无已发布 claims：{source_id[:16]}…",
        )
    heads.sort(key=lambda head: int(head.get("generation", 0)), reverse=True)
    return str(heads[0]["build_id"])


def _translate_corpus_error(exc: Exception) -> HTTPException:
    """Fail-closed translation: corpus refusals become 4xx, never empty 200s."""
    from plugins.corpus.preparation.read_pg import LegacyHandleError, WithdrawnError
    from plugins.corpus.structured.ledger import StructuredExecutionError

    if isinstance(exc, StructuredExecutionError):
        if getattr(exc, "code", "") == "CS_NOT_PUBLISHED":
            return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, WithdrawnError):
        return HTTPException(status.HTTP_410_GONE, detail=str(exc))
    if isinstance(exc, LegacyHandleError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    from plugins.corpus.preparation.repository import StoreError

    if isinstance(exc, StoreError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ── routes ────────────────────────────────────────────────────────
@router.get("/status")
async def corpus_status(user: User = Depends(get_current_user)) -> dict:
    """Read-chain, target DB and claims store status (no secrets)."""
    import os

    service = _corpus_service()
    try:
        read_chain = service.read_chain()
    except Exception as exc:  # fail-closed refusals surface as their message
        raise _translate_corpus_error(exc) from exc
    store_root = _store_root()
    return {
        "read_chain": read_chain,
        "target_db": getattr(service, "_target_db", None),
        "dsn_configured": bool(os.environ.get("CORPUS_DSN") or os.environ.get("CORPUS_I2_DSN")),
        "structured_store_root": store_root,
        "claims_publications": _heads(store_root) if store_root else [],
    }


@router.get("/search")
async def corpus_search(
    query: str = Query(min_length=1, max_length=400),
    limit: int = Query(default=10, ge=1, le=_MAX_LIMIT),
    user: User = Depends(get_current_user),
) -> dict:
    """检索生产活动 build（band 生产默认管线），返回命中 + 覆盖元数据。"""
    service = _corpus_service()
    try:
        hits, coverage = service.search_with_coverage(query, limit=limit)
    except Exception as exc:
        raise _translate_corpus_error(exc) from exc
    return {
        "query": query,
        "hits": [asdict(hit) for hit in hits],
        "coverage": coverage,
    }


@router.get("/documents/{doc_id}")
async def corpus_document(
    doc_id: str,
    locator: str = Query(min_length=1, max_length=200),
    user: User = Depends(get_current_user),
) -> dict:
    """按 §7.2 句柄（cv2:<build_id> + chunk:<chunk_id>）回读权威原文块。"""
    service = _corpus_service()
    try:
        evidence = service.fetch_verbatim(doc_id, locator)
    except Exception as exc:
        raise _translate_corpus_error(exc) from exc
    return {
        "doc_id": doc_id,
        "locator": locator,
        "text": evidence.text,
    }


def _semantic_page(
    source_id: str,
    *,
    purpose: str,
    query_text: str,
    limit: int,
    build_id: str | None,
    cursor: str | None,
    field_filters: dict[str, str] | None = None,
) -> dict:
    store_root = _store_root()
    if not store_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CORPUS_STRUCTURED_ROOT 未配置：语义生产 store 未落位",
        )
    from plugins.corpus.structured.query import query_semantic

    resolved_build = build_id or _resolve_build_id(store_root, source_id)
    try:
        page = query_semantic(
            source_id,
            resolved_build,
            purpose=purpose,  # type: ignore[arg-type]
            query_text=query_text,
            limit=limit,
            cursor=cursor,
            field_filters=field_filters,
            store_root=store_root,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_corpus_error(exc) from exc
    return page.model_dump(mode="json")


@router.get("/claims/{source_id}")
async def corpus_claims(
    source_id: str,
    purpose: Literal["cite", "compare", "calculate"] = "cite",
    query_text: str = Query(default="", max_length=400),
    limit: int = Query(default=10, ge=1, le=_MAX_LIMIT),
    build_id: str | None = Query(default=None, max_length=128),
    cursor: str | None = Query(default=None, max_length=4096),
    user: User = Depends(get_current_user),
) -> dict:
    """已发布 claims 语义查询（读生产 structured store，零模型、确定性词法匹配）。

    分页经 ``next_cursor`` 往返：把响应里的 ``next_cursor`` 原样回传即可续页。
    """
    return _semantic_page(
        source_id,
        purpose=purpose,
        query_text=query_text,
        limit=limit,
        build_id=build_id,
        cursor=cursor,
    )


@router.get("/items/{source_id}")
async def corpus_items(
    source_id: str,
    purpose: Literal["cite", "compare", "calculate"] = "cite",
    query_text: str = Query(default="", max_length=400),
    limit: int = Query(default=10, ge=1, le=_MAX_LIMIT),
    build_id: str | None = Query(default=None, max_length=128),
    cursor: str | None = Query(default=None, max_length=4096),
    user: User = Depends(get_current_user),
) -> dict:
    """已发布 material_items 语义查询：同一读路径上加 role=material_items 过滤。

    与 claims 端点共用解析、分页与 fail-closed 翻译；items 未发布时由 ledger 的
    ``publication_head_missing`` 走 404，而不是返回空页。
    """
    return _semantic_page(
        source_id,
        purpose=purpose,
        query_text=query_text,
        limit=limit,
        build_id=build_id,
        cursor=cursor,
        field_filters={"role": "material_items"},
    )
