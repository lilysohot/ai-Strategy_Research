"""M10：模块隔离架构测试（§5.0「独立性可机械验证」）。

保证 market 是**可选的旁路**，而不是新的硬依赖：
1. `plugins.corpus.*` 与 `workflows.*` 的 import 图里**不含** `plugins.market`；
2. `MARKET_ENABLED=false`（或缺 `THS_API_KEY`）时，工具恒定 `ok=false`，
   核心流程退化为未接入形态 —— corpus / P0a 不受影响。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.market import factory

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MODULES = ("plugins.market",)


def _market_imports(path: Path) -> list[str]:
    """静态解析：收集该文件**模块级**对 plugins.market 的 import（不执行代码）。

    只查顶层：import 该模块时若会连带 import market，隔离即告破；
    而函数内的**延迟 import** 是「由调用方注入」的合法实现（§5.7）——
    例如 verify 的 CLI 在给了 `--market-trace` 时才加载 market 的 resolver，
    不装 market 也能正常跑 corpus verify。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in tree.body:  # 仅顶层，不下钻函数体
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return [name for name in found if any(name.startswith(mod) for mod in FORBIDDEN_MODULES)]


@pytest.mark.parametrize(
    "package",
    ["plugins/corpus", "workflows"],
)
def test_no_reverse_dependency_on_market(package: str) -> None:
    """corpus 与 workflows 不得 import market（依赖单向，market 只是可选旁路）。"""
    base = REPO_ROOT / package
    offenders: list[str] = []

    for path in base.rglob("*.py"):
        for name in _market_imports(path):
            offenders.append(f"{path.relative_to(REPO_ROOT)} -> {name}")

    assert not offenders, "出现反向依赖（market 不应被上层依赖）：\n" + "\n".join(offenders)


def test_disabled_by_flag_returns_actionable_failure() -> None:
    denied = factory.unavailability({"MARKET_ENABLED": "false", "THS_API_KEY": "k"})
    assert denied is not None
    assert denied["ok"] is False
    assert denied["kind"] == "credentials"
    assert denied.get("next")


def test_missing_api_key_returns_actionable_failure() -> None:
    denied = factory.unavailability({"MARKET_ENABLED": "true", "THS_API_KEY": ""})
    assert denied is not None
    assert "THS_API_KEY" in denied["reason"]


def test_build_service_is_none_when_unavailable() -> None:
    assert factory.build_service({"MARKET_ENABLED": "false", "THS_API_KEY": "k"}) is None


def test_enabled_by_default_with_key() -> None:
    env = {"MARKET_ENABLED": "true", "THS_API_KEY": "dummy-key"}
    assert factory.unavailability(env) is None
    service = factory.build_service(env, trace=False)
    assert service is not None
    assert service.health()["ok"] is True
