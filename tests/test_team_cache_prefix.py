import json
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.runtime.loop.context_budget import estimate_tokens
from frontier_agent.core.runtime.loop.model_profile import ModelProfile
from frontier_agent.core.runtime.registries import services as registry
from frontier_agent.core.runtime.resources.manager import ResourceManager
from workflows._shared.cross_mode_context import SCHEMA, render_context_tail


def context():
    return {
        "schema": SCHEMA,
        "records": [{"source_id": "old", "role": "assistant", "content": "Known evidence " * 100}],
        "sources": [{"run_id": "prior"}],
        "archived_records": [{"source_id": "archive", "role": "user", "content": "ARCHIVE_ONLY"}],
    }


@pytest.mark.parametrize("large_history", [False, True])
async def test_team_node_sends_stable_history_before_new_question(
    tmp_path, monkeypatch, large_history
):
    from workflows.agent_team.nodes import main_agent as node

    requests = []

    class Client:
        model = "offline"

        async def chat(self, messages, **kwargs):
            requests.append(json.loads(json.dumps(messages)))
            return LLMResponse(content="Answer based on prior evidence.")

    profile = {
        "llm": {"max_tokens": 2048},
        "agent": {
            "planning_mode": False,
            "reporter": False,
            "main_max_turns": 2,
            "context_compaction": "off",
            "replay_max_tokens": 0,
            "reasoning_only_timeout_s": 0,
            "reasoning_only_max_tokens": 0,
        },
    }
    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *a, **kw: (Client(), profile, ModelProfile(model_id="offline", provider="openai")),
    )
    monkeypatch.setattr(node, "_resolve_profile_tools", lambda *a, **kw: ([], []))
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda *a: "bwrap")
    monkeypatch.setattr(node, "bwrap_available", lambda: False)
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *a: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *a: ((), (), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *a: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *a: tmp_path / "conversation.json"
    )
    before = registry.snapshot()
    registry.register(AgentBus, AgentBus())
    registry.register(ResourceManager, object())
    prior = context()
    if large_history:
        prior["records"] = [
            {
                "source_id": f"old-{i}",
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Round {i}: " + "Known evidence " * 1500,
            }
            for i in range(30)
        ]
    try:
        for question in ("First question; snapshot A", "Different question; snapshot B"):
            await node.main_agent_node(
                {
                    "original_question": question,
                    "cross_mode_context": prior,
                    "metadata": {"bus_task_id": "cache-test", "run_id": "cache-test"},
                },
                SimpleNamespace(task_id="cache-test"),
            )
        assert len(requests) == 2
        assert requests[0][:2] == requests[1][:2]
        assert requests[0][1]["role"] == "user"
        assert "Known evidence" in requests[0][1]["content"]
        assert requests[1][2]["content"] == "Different question; snapshot B"
        assert "ARCHIVE_ONLY" not in json.dumps(requests)
        assert estimate_tokens(requests[0][1]["content"]) <= 12000
    finally:
        registry.restore(before)


def test_appending_records_keeps_existing_history_prefix():
    old = context()
    new = context()
    new["records"].append({"source_id": "new", "role": "user", "content": "follow up"})
    new["sources"].append({"run_id": "next"})
    new["completeness"] = {"status": "windowed"}
    a, b = render_context_tail(old), render_context_tail(new)
    end = a.index("Known evidence") + len("Known evidence " * 100)
    assert a[:end] == b[:end]
