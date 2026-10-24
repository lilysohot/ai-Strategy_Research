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


def test_team_profile_keeps_business_tools_on_coordinator_only() -> None:
    from server.profile import BUSINESS_TOOL_NAMES, build_profile_overrides

    agent = build_profile_overrides(
        has_investment_context=True,
        pipeline_id="agent_team",
    )["agent"]
    main_tools = set(agent["main_agent_tools"])
    sub_tools = set(agent["sub_agent_tools"])

    assert set(BUSINESS_TOOL_NAMES) <= main_tools
    assert "request_investment_input" in main_tools
    assert set(BUSINESS_TOOL_NAMES).isdisjoint(sub_tools)
    assert "request_investment_input" not in sub_tools
    assert "research_history" in main_tools
    assert "research_history" not in sub_tools
    assert {"create_subagent", "assign_task", "collect_reports"} <= main_tools


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
