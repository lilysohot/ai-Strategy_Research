"""Preflight must use the same public builders as the real workflows."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tools.preflight import check_workflow_llm


@pytest.mark.parametrize("pipeline", ["stateful-react-agent", "stateful_react_agent"])
async def test_react_preflight_uses_current_profile_facade(monkeypatch, pipeline):
    import workflows.stateful_react_agent.profile as profile

    chat = AsyncMock()
    load = Mock(return_value={"llm": {"model": "test"}})
    build = Mock(return_value=SimpleNamespace(chat=chat))
    monkeypatch.setattr(profile, "load_react_profile", load)
    monkeypatch.setattr(profile, "create_react_llm", build)
    assert await check_workflow_llm(pipeline, "keep5") is None
    load.assert_called_once_with("keep5")
    build.assert_called_once_with(load.return_value)
    chat.assert_awaited_once()
