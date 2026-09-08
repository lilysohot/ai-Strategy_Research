"""User LLM config routes (T2.4).

    GET    /api/models                 list (masked)
    POST   /api/models                 create
    GET    /api/models/{id}            read one (masked)
    PUT    /api/models/{id}            update
    DELETE /api/models/{id}            delete
    POST   /api/models/{id}/test       connectivity preflight

Every route is guarded by :func:`server.deps.get_current_user`, so the user is
resolved in exactly one place (see T2.2). Configs are owned by ``user_id`` and the
store layer enforces that ownership (IDOR guard) — these routes only ever pass
the authenticated user's id, never a client-supplied one, to the store.

Secrets handling, deliberately uniform with the rest of the platform:
* the api_key is encrypted at rest by the store layer (T2.3) and is **never**
  returned in any response — only ``masked_api_key`` leaves the server;
* the connectivity test decrypts the key in-process, uses it for exactly one
  outbound probe with a tight timeout, and discards it; it is never logged and
  never echoed back;
* a failed probe records a short, key-free error summary (``_last_verify_error``
  in ``params_json``) so the UI can show "why" without leaking credentials.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from server.deps import _client_ip, get_current_user
from server.store import (
    ConfigNotFoundError,
    OnlyOneDefaultAllowed,
    User,
    create_llm_config,
    delete_llm_config,
    get_decrypted_api_key,
    get_llm_config,
    list_llm_configs,
    record_verify_result,
    update_llm_config,
    write_audit_log,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])

# Outbound probe budget: a config test must never hang a request thread.
_PROBE_TIMEOUT_S = 10.0


# ── Request / response models ────────────────────────────────────
class ConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=1, max_length=2048)
    params: dict | None = None
    is_default: bool = False


class ConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)
    params: dict | None = None
    is_default: bool | None = None


class TestResult(BaseModel):
    ok: bool
    detail: str


# ── Audit helper (same pattern as T2.2: awaited, never breaks response) ──
async def _audit(action: str, *, user: User, request: Request,
                 detail: dict | None = None) -> None:
    try:
        await write_audit_log(
            action=action,
            user_id=user.id,
            detail=detail,
            ip=_client_ip(request),
        )
    except Exception:
        logger.exception("audit_log write failed for action=%s", action)


# ── Routes ──────────────────────────────────────────────────────
@router.get("", response_model=list[dict])
async def list_configs(user: User = Depends(get_current_user)) -> list[dict]:
    """List the caller's configs (masked)."""
    return await list_llm_configs(user_id=user.id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=dict)
async def create_config(
    body: ConfigCreate,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Create a config; api_key is encrypted at rest by the store."""
    try:
        cfg = await create_llm_config(
            user_id=user.id,
            name=body.name,
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
            params=body.params,
            is_default=body.is_default,
        )
    except OnlyOneDefaultAllowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="默认配置操作冲突，请重试",
        ) from None
    await _audit("llm_config_created", user=user, request=request,
                 detail={"config_id": cfg["id"], "name": cfg["name"]})
    return cfg


@router.get("/{config_id}", response_model=dict)
async def read_config(
    config_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return await get_llm_config(user_id=user.id, config_id=uuid.UUID(config_id))
    except (ConfigNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="配置不存在") from None


@router.put("/{config_id}", response_model=dict)
async def update_config(
    config_id: str,
    body: ConfigUpdate,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        cfg = await update_llm_config(
            user_id=user.id,
            config_id=uuid.UUID(config_id),
            name=body.name,
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
            params=body.params,
            is_default=body.is_default,
        )
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="配置不存在") from None
    except OnlyOneDefaultAllowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="默认配置操作冲突，请重试",
        ) from None
    await _audit("llm_config_updated", user=user, request=request,
                 detail={"config_id": cfg["id"], "name": cfg["name"]})
    return cfg


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    try:
        await delete_llm_config(user_id=user.id, config_id=uuid.UUID(config_id))
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="配置不存在") from None
    except OnlyOneDefaultAllowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能删除用户唯一的 LLM 配置",
        ) from None
    await _audit("llm_config_deleted", user=user, request=request,
                 detail={"config_id": config_id})


@router.post("/{config_id}/test", response_model=TestResult)
async def test_config(
    config_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> TestResult:
    """Probe the stored endpoint for connectivity (FR: 连通性预检).

    The api_key is decrypted in-process, used for one outbound request, and
    discarded. The result is recorded via :func:`record_verify_result` (updating
    ``last_verified_at`` / ``last_verify_ok`` and a key-free error summary).
    """
    try:
        cid = uuid.UUID(config_id)
        api_key = await get_decrypted_api_key(user_id=user.id, config_id=cid)
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="配置不存在") from None
    except ValueError:
        raise HTTPException(status_code=404, detail="配置不存在") from None

    ok, detail = await _probe_connectivity(user.id, cid, api_key)
    await record_verify_result(
        user_id=user.id,
        config_id=cid,
        ok=ok,
        error_summary=None if ok else detail,
    )
    await _audit(
        "llm_config_tested",
        user=user,
        request=request,
        detail={"config_id": config_id, "ok": ok},
    )
    return TestResult(ok=ok, detail=detail)


async def _probe_connectivity(
    user_id: uuid.UUID, config_id: uuid.UUID, api_key: str
) -> tuple[bool, str]:
    """Send one lightweight authenticated request to the configured base_url.

    Returns ``(ok, detail)``. ``detail`` is a short human-readable message that
    never contains the api_key. Any failure mode (bad URL, timeout, non-2xx,
    transport error) is folded into a safe summary. ``base_url``/``model`` are read
    from the masked store view (no key exposure) using the authenticated user id.
    """
    from server.store import get_llm_config

    try:
        view = await get_llm_config(user_id=user_id, config_id=config_id)
    except ConfigNotFoundError:
        return False, "无法读取配置信息"

    base_url = (view.get("base_url") or "").strip().rstrip("/")
    if not base_url or not base_url.startswith(("http://", "https://")):
        return False, "base_url 非法或缺失"

    # OpenAI-compatible: prefer {base_url}/v1/models, fall back to {base_url}/models.
    url = f"{base_url}/models" if "/v1" in base_url else f"{base_url}/v1/models"

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        return False, "连接超时（>10s）"
    except httpx.HTTPError as exc:
        return False, f"网络错误：{type(exc).__name__}"
    except Exception as exc:
        return False, f"请求异常：{type(exc).__name__}"

    if resp.status_code == 200:
        return True, "连通正常"
    if resp.status_code in (401, 403):
        return False, f"认证失败（HTTP {resp.status_code}）"
    if resp.status_code == 404:
        # Endpoint may not implement /models; treat as reachable but warn.
        return True, "端点可达（/models 未实现，连通性 OK）"
    return False, f"端点返回 HTTP {resp.status_code}"
