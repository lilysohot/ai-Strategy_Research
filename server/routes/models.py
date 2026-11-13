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

import asyncio
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
async def _audit(action: str, *, user: User, request: Request, detail: dict | None = None) -> None:
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
    await _audit(
        "llm_config_created",
        user=user,
        request=request,
        detail={"config_id": cfg["id"], "name": cfg["name"]},
    )
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
    await _audit(
        "llm_config_updated",
        user=user,
        request=request,
        detail={"config_id": cfg["id"], "name": cfg["name"]},
    )
    return cfg


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    try:
        await delete_llm_config(user_id=user.id, config_id=uuid.UUID(config_id))
    except (ConfigNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="配置不存在") from None
    except OnlyOneDefaultAllowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能删除用户唯一的 LLM 配置",
        ) from None
    await _audit("llm_config_deleted", user=user, request=request, detail={"config_id": config_id})


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
    """Test the configured model with one bounded, low-token chat request.

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

    model = (view.get("model") or "").strip()
    if not model:
        return False, "模型名缺失。建议：填写供应商提供的完整模型 ID 后重新测试。"

    # Match the runtime's OpenAI-compatible base URL semantics. A successful
    # /models lookup cannot prove that this particular model is callable.
    url = f"{base_url}/chat/completions"

    try:
        async with (
            asyncio.timeout(_PROBE_TIMEOUT_S),
            httpx.AsyncClient(
                timeout=_PROBE_TIMEOUT_S,
            ) as client,
        ):
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply only OK."}],
                    "max_tokens": 64,
                    "stream": False,
                },
            )
    except (httpx.TimeoutException, TimeoutError):
        return False, (
            "模型调用超时（10 秒），暂时无法确认配置是否可用。"
            "建议：检查服务响应速度及网络连接，稍后重试；超时不代表密钥无效。"
        )
    except httpx.InvalidURL:
        return False, "Base URL 格式错误。建议：填写供应商提供的 API 基础地址。"
    except httpx.HTTPError:
        return False, (
            "网络连接失败，未取得有效的模型响应。"
            "建议：检查 Base URL、DNS、代理及 TLS 证书，确认服务器可以访问供应商。"
        )
    except Exception:
        # Exception strings can include URLs, credentials or request headers.
        return False, "预检请求异常，无法确认配置是否可用。建议：检查配置并重试。"

    if resp.status_code == 200:
        try:
            body = resp.json()
        except ValueError:
            body = None
        choices = body.get("choices") if isinstance(body, dict) else None
        if (
            isinstance(choices, list)
            and choices
            and isinstance(choices[0], dict)
            and isinstance(choices[0].get("message"), dict)
        ):
            return True, "模型调用成功：密钥认证通过，所填模型已接受测试请求。"
        return False, (
            "响应格式异常（HTTP 200），未收到兼容的模型响应。"
            "建议：确认 Base URL 指向 OpenAI 兼容 API，而不是网页地址。"
        )
    return False, _probe_http_error(resp)


def _probe_http_error(response: httpx.Response) -> str:
    """Classify upstream errors without reflecting potentially secret-bearing text."""
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error", {}) if isinstance(body, dict) else {}
    if isinstance(error, dict):
        signal = " ".join(str(error.get(k) or "") for k in ("code", "type", "message"))
    else:
        signal = str(error)
    signal = signal.lower()
    status = response.status_code
    if status == 401:
        reason = "认证失败：API Key 无效、已过期，或与当前供应商不匹配"
        advice = "核对 Base URL 与密钥是否属于同一供应商；在供应商后台确认密钥有效后更新。"
    elif status in (400, 403, 404, 422) and any(
        marker in signal
        for marker in (
            "model_not_found",
            "invalid_model",
            "model not found",
            "model does not exist",
            "model is not supported",
            "unsupported model",
            "supported api model names",
            "model_not_supported",
            "model not supported",
            "模型不存在",
            "不支持的模型",
        )
    ):
        reason = "模型不可用：模型名不存在、不受支持，或当前密钥无权使用"
        advice = "从该供应商复制完整模型 ID，核对拼写与版本，并确认账号已开通该模型。"
    elif status == 403:
        reason = "访问被拒绝：当前账号、密钥或来源地址没有调用权限"
        advice = "检查模型授权、账号状态、IP 白名单及地区限制；必要时联系供应商。"
    elif status == 402 or (
        status in (400, 429)
        and any(
            marker in signal
            for marker in (
                "insufficient_quota",
                "insufficient_balance",
                "insufficient balance",
                "credit balance",
                "quota_exceeded",
                "余额不足",
                "额度不足",
            )
        )
    ):
        reason = "账户余额或可用额度不足"
        advice = "检查供应商账户余额、套餐及调用额度，恢复可用额度后重试。"
    elif status == 429:
        reason = "触发请求限流，暂时无法确认模型是否可用"
        advice = "降低并发或请求频率，等待限流窗口恢复后重试；也可检查账户调用限额。"
    elif status == 404:
        reason = "接口路径不存在，或供应商未开放该接口"
        advice = "核对 Base URL 是否包含供应商要求的版本路径，不要填写网页或完整对话接口地址。"
    elif status in (400, 422):
        reason = "请求参数不兼容，供应商拒绝了模型测试请求"
        advice = "核对模型 ID 与 OpenAI Chat Completions 兼容性，以及供应商要求的参数。"
    elif status >= 500:
        reason = "供应商或网关服务暂时不可用"
        advice = "稍后重试，并检查供应商服务状态；持续失败时联系供应商。"
    else:
        reason = "供应商未接受模型测试请求"
        advice = "检查 API 地址、供应商接口要求与服务状态后重试。"
    return f"{reason}（HTTP {status}）。建议：{advice}"
