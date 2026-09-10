"""构造真实 `MarketService`（读 `.env`），并处理「未启用 / 缺凭据」。

工具层只依赖本工厂：拿不到可用服务时返回**明确的失败原因**，
做到「不静默返回空数据、不拖垮主流程」（§6）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from plugins.market.adapters.fuyao_rest import FuyaoRestAdapter
from plugins.market.service import MarketService
from plugins.market.sink import build_sink, trace_enabled
from plugins.market.transport import CircuitBreaker, MarketTransport

ENV_API_KEY = "THS_API_KEY"
ENV_BASE_URL = "THS_API_BASE_URL"
ENV_ENABLED = "MARKET_ENABLED"
ENV_TRACE_DIR = "MARKET_TRACE_DIR"

DEFAULT_BASE_URL = "https://fuyao.aicubes.cn"
DEFAULT_TRACE_DIR = ".apodex/market-trace"


def _env(source: dict[str, str] | None) -> dict[str, str]:
    return source if source is not None else dict(os.environ)


def is_enabled(env: dict[str, str] | None = None) -> bool:
    """`MARKET_ENABLED` 总开关（默认 **true**）。"""
    return _env(env).get(ENV_ENABLED, "true").strip().lower() not in {"0", "false", "no", "off"}


def get_api_key(env: dict[str, str] | None = None) -> str:
    return _env(env).get(ENV_API_KEY, "").strip()


def get_base_url(env: dict[str, str] | None = None) -> str:
    return _env(env).get(ENV_BASE_URL, "").strip() or DEFAULT_BASE_URL


def get_trace_dir(env: dict[str, str] | None = None) -> Path:
    """留痕目录：`MARKET_TRACE_DIR`，缺省写到 `./.apodex/market-trace`。"""
    configured = _env(env).get(ENV_TRACE_DIR, "").strip()
    return Path(configured or DEFAULT_TRACE_DIR)


def unavailability(env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """不可用则返回失败字典（含 `next`），可用则返回 `None`。"""
    if not is_enabled(env):
        return {
            "ok": False,
            "kind": "credentials",
            "reason": f"{ENV_ENABLED}=false：market 模块已关闭",
            "next": "如需启用市场数据工具，请在 .env 中设置 MARKET_ENABLED=true",
        }
    if not get_api_key(env):
        return {
            "ok": False,
            "kind": "credentials",
            "reason": f"{ENV_API_KEY} 未配置",
            "next": "在 .env 中配置 THS_API_KEY（§7）；也可设 MARKET_ENABLED=false 让流程退化为未接入形态",
        }
    return None


def resolve_or_error(service: MarketService, query: str) -> tuple[str | None, dict[str, Any] | None]:
    """消歧：成功返回 `thscode`；多义 / 未找到返回可直接给模型的失败体。"""
    resolved = service.resolve(query)
    if not resolved.ok:
        return None, {
            "ok": False,
            "query": query,
            "reason": resolved.reason,
            "next": "换用更完整的名称或代码（如「贵州茅台」「600519」「600519.SH」）",
        }
    if resolved.ambiguous:
        payload = resolved.to_dict()
        payload["next"] = "请指定其中一个 thscode 后重试"
        return None, payload
    return resolved.thscode, None


def build_service(
    env: dict[str, str] | None = None,
    *,
    trace: bool | None = None,
) -> MarketService | None:
    """按环境变量构造真实服务；不可用时返回 `None`（原因用 `unavailability()` 取）。"""
    if unavailability(env) is not None:
        return None
    transport = MarketTransport(
        base_url=get_base_url(env),
        api_key=get_api_key(env),
        sink=build_sink(
            get_trace_dir(env),
            enabled=trace if trace is not None else trace_enabled(_env(env)),
        ),
        breaker=CircuitBreaker(),
    )
    return MarketService(adapter=FuyaoRestAdapter(transport))
