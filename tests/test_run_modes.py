"""Per-Run Web mode contract before the UI feature flag is enabled."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from server.routes.runs import RunRequest, _require_team_mode_available
from server.run_modes import RunMode, mode_for_pipeline, pipeline_for_mode
from server.worker import _compose_run_instruction


def test_legacy_submit_defaults_to_single() -> None:
    request = RunRequest(message="continue")

    assert request.mode is RunMode.SINGLE
    assert pipeline_for_mode(request.mode) == "stateful-react-agent"


def test_mode_mapping_is_explicit_and_round_trips() -> None:
    assert pipeline_for_mode(RunMode.TEAM) == "agent_team"
    assert mode_for_pipeline("stateful-react-agent") is RunMode.SINGLE
    assert mode_for_pipeline("agent_team") is RunMode.TEAM


def test_invalid_mode_is_rejected_instead_of_falling_back() -> None:
    with pytest.raises(ValidationError):
        RunRequest(message="continue", mode="swarm")

    with pytest.raises(ValueError, match="has no Web run mode"):
        mode_for_pipeline("agent_team_report")


@pytest.mark.parametrize("bound", [False, True])
def test_team_profile_reuses_cli_roles_without_business_tools(bound) -> None:
    from server.profile import (
        BUSINESS_TOOL_NAMES,
        MARKET_TOOL_NAMES,
        PROFILE_NAME,
        RESEARCH_TOOL_NAMES,
        build_profile_overrides,
    )
    from workflows.agent_team.profile import load_swarm_profile

    agent = build_profile_overrides(
        has_investment_context=bound,
        pipeline_id="agent_team",
    )["agent"]
    cli = load_swarm_profile(PROFILE_NAME)["agent"]
    main_tools = set(agent["main_agent_tools"])
    sub_tools = set(agent["sub_agent_tools"])

    assert agent["main_agent_tools"] == [*cli["main_agent_tools"], "research_history"]
    assert agent["sub_agent_tools"] == cli["sub_agent_tools"]
    unavailable = set(BUSINESS_TOOL_NAMES + MARKET_TOOL_NAMES + RESEARCH_TOOL_NAMES)
    assert unavailable.isdisjoint(main_tools | sub_tools)
    assert "publish_handoff" in sub_tools
    assert {"web_search", "web_fetch", "bash", "read_file", "create_file"}.isdisjoint(main_tools)
    assert "research_history" not in sub_tools
    assert {"create_subagent", "assign_task", "collect_reports"} <= main_tools
    assert agent["fs_mode"] == cli.get("fs_mode", False)


@pytest.mark.parametrize("bound", [False, True])
def test_team_prompt_additions_preserve_roles_and_history_without_unavailable_tools(bound):
    from server.profile import (
        BUSINESS_CONTEXT_POLICY,
        CONTEXT_INTEGRITY_POLICY,
        INPUT_REQUEST_POLICY,
        RESEARCH_HISTORY_POLICY,
        build_prompt_addenda,
    )

    additions = build_prompt_addenda(pipeline_id="agent_team", has_investment_context=bound)
    main = additions["_sys_prompt_addendum"]
    sub = additions["_subagent_prompt_addendum"]
    assert BUSINESS_CONTEXT_POLICY not in main
    assert INPUT_REQUEST_POLICY not in main
    assert RESEARCH_HISTORY_POLICY in main
    assert "single publisher carrying output_paths" in main
    assert "unavailable" in main
    assert CONTEXT_INTEGRITY_POLICY in main and CONTEXT_INTEGRITY_POLICY in sub
    assert "research_history" not in sub


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("history", [False, True])
def test_single_prompt_prefix_is_byte_identical(bound, history):
    from server.profile import (
        BUSINESS_CONTEXT_POLICY,
        CONTEXT_INTEGRITY_POLICY,
        INPUT_REQUEST_POLICY,
        RESEARCH_HISTORY_POLICY,
        build_prompt_addenda,
    )

    expected = (
        "Input files are mounted read-only at /inputs. Write the final deliverable to /outputs."
        "\n" + CONTEXT_INTEGRITY_POLICY
    )
    if bound:
        expected += "\n" + BUSINESS_CONTEXT_POLICY
    expected += "\n" + INPUT_REQUEST_POLICY
    if history:
        expected += "\n" + RESEARCH_HISTORY_POLICY
    assert build_prompt_addenda(
        pipeline_id="stateful-react-agent",
        has_investment_context=bound,
        enable_research_history=history,
    ) == {"_sys_prompt_addendum": expected}


async def test_team_worker_rejects_tool_override_before_initializing_run():
    from types import SimpleNamespace

    from server.worker import run_once

    with pytest.raises(ValueError, match="CLI role tools"):
        await run_once(SimpleNamespace(pipeline_id="agent_team", agent_tools="market_quote"))


def test_pure_single_profile_is_unchanged_until_session_uses_team() -> None:
    from server.orchestrator import _needs_mixed_mode_history
    from server.profile import build_profile_overrides

    pure = build_profile_overrides(pipeline_id="stateful-react-agent")["agent"]
    mixed = build_profile_overrides(
        pipeline_id="stateful-react-agent", enable_research_history=True
    )["agent"]

    assert "research_history" not in pure["agent_tools"]
    assert "research_history" in mixed["agent_tools"]
    assert _needs_mixed_mode_history("stateful-react-agent", []) is False
    assert _needs_mixed_mode_history("agent_team", []) is True
    assert _needs_mixed_mode_history("stateful-react-agent", ["agent_team"]) is True


def test_team_delegation_question_excludes_authenticated_context() -> None:
    context = {
        "run_id": "a" * 32,
        "account": {"available_capital": 123456},
        "plan": {"symbol": "SECRET-PLAN"},
    }

    instruction, delegation = _compose_run_instruction(
        "研究公开市场信息",
        prompt_addendum="材料在 /inputs/source.pdf",
        investment_context=context,
    )

    assert "123456" in instruction
    assert "SECRET-PLAN" in instruction
    assert "<investment_context_data>" in instruction
    assert delegation == "研究公开市场信息\n\n材料在 /inputs/source.pdf"
    assert "123456" not in delegation
    assert "SECRET-PLAN" not in delegation


def test_team_mode_rejects_native_backend_without_role_identity(monkeypatch) -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    monkeypatch.setattr("plugins.tools._sandbox.tool_identity_or_none", lambda: None)
    cfg = SimpleNamespace(agent_team_enabled=True, sandbox_backend="native")

    with pytest.raises(HTTPException, match="工具用户隔离") as exc_info:
        _require_team_mode_available(cfg)

    assert exc_info.value.status_code == 503


def test_team_mode_accepts_bwrap_without_tool_identity() -> None:
    from types import SimpleNamespace

    _require_team_mode_available(
        SimpleNamespace(agent_team_enabled=True, sandbox_backend="bwrap")
    )


@pytest.mark.asyncio
async def test_team_submit_fails_closed_while_feature_is_disabled(monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from server.app import app
    from server.config import get_config
    from server.store import init_db

    await init_db()
    cfg = get_config()
    monkeypatch.setattr(cfg, "agent_team_enabled", False)
    username = f"mode-{uuid.uuid4().hex}"
    password = "Str0ngPass1"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        registered = await client.post(
            "/api/auth/register", json={"username": username, "password": password}
        )
        assert registered.status_code == 201
        login = await client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        unauthenticated = await client.get("/api/runs/modes")
        assert unauthenticated.status_code == 401
        capabilities = await client.get("/api/runs/modes", headers=headers)
        assert capabilities.status_code == 200
        assert capabilities.json()["single"]["available"] is True
        assert capabilities.json()["team"]["available"] is False
        monkeypatch.setattr(cfg, "agent_team_enabled", True)
        monkeypatch.setattr(cfg, "sandbox_backend", "bwrap")
        enabled = await client.get("/api/runs/modes", headers=headers)
        assert enabled.json()["team"] == {"available": True, "reason": None}
        monkeypatch.setattr(cfg, "sandbox_backend", "native")
        monkeypatch.setattr("plugins.tools._sandbox.tool_identity_or_none", lambda: None)
        unavailable = await client.get("/api/runs/modes", headers=headers)
        assert unavailable.json()["team"]["available"] is False
        monkeypatch.setattr(cfg, "agent_team_enabled", False)

        disabled = await client.post(
            "/api/runs",
            json={"message": "research", "session_id": "mode-test", "mode": "team"},
            headers=headers,
        )
        invalid = await client.post(
            "/api/runs",
            json={"message": "research", "session_id": "mode-test", "mode": "swarm"},
            headers=headers,
        )

    assert disabled.status_code == 503
    assert disabled.json()["detail"] == "团队研究模式尚未启用"
    assert invalid.status_code == 422
