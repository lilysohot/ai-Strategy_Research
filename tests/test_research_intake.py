"""Missing research subjects must stop before the research loop and survive replay."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import AgentLoopResult

QUESTION = "请进行深度研究：\n- 研究对象：\n- 时间范围：\n- 输出：结构化报告。"
CLARIFICATION = "当前研究对象不明确，需要补充。您希望研究什么事物或主题？"


@pytest.fixture
def react_case(tmp_path, monkeypatch):
    from workflows.stateful_react_agent.nodes import main_agent as node

    llm = SimpleNamespace(
        model="mock",
        chat=AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({"decision": "clarify", "question": CLARIFICATION}),
                finish_reason="stop",
            )
        ),
    )
    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *a, **kw: (
            llm,
            {"agent": {"direct": True, "replay_max_tokens": 0}},
            None,
        ),
    )
    monkeypatch.setattr(
        node, "registry", SimpleNamespace(get=lambda _: None, get_optional=lambda _: None)
    )
    monkeypatch.setattr(node, "_tools_for_stateful_react", lambda *args: [])
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda _: "bwrap")
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *args: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *args: ((), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *args: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *args: tmp_path / "conversation.json"
    )
    research = AsyncMock(
        return_value=AgentLoopResult(
            messages=[],
            final_content="错误地启动了研究",
            stopped_by="no_tool",
        )
    )
    monkeypatch.setattr(node, "run_agent_loop", research)
    import apodex.session

    monkeypatch.setattr(apodex.session, "run_agent_loop", research)
    return node, llm, research, tmp_path


async def test_missing_subject_clarifies_before_research_and_keeps_continuity(react_case):
    node, llm, research, root = react_case
    result = await node.react_agent_node(
        {
            "original_question": QUESTION,
            "metadata": {"research_intake": True, "session_id": "intake-test"},
        },
        SimpleNamespace(task_id="intake-test"),
    )
    assert result["final_answer"] == CLARIFICATION
    assert result["stopped_by"] == "no_tool"
    research.assert_not_awaited()
    assert llm.chat.await_count == 1
    dump = (root / "conversation.json").read_text()
    assert json.loads(dump)["messages"][-1]["content"] == CLARIFICATION

    llm.chat.return_value = LLMResponse(content='{"decision":"ready"}', finish_reason="stop")
    await node.react_agent_node(
        {
            "original_question": "我想研究城市里的鸟类迁徙现象",
            "replay_payload": dump,
            "metadata": {"research_intake": True, "session_id": "intake-test"},
        },
        SimpleNamespace(task_id="intake-test-2"),
    )
    research.assert_awaited_once()
    assert research.call_args.kwargs["initial_messages"][-1]["content"] == CLARIFICATION


@pytest.mark.parametrize("question", ["研究鸟类迁徙", "解释递归这个概念", "你好"])
async def test_ready_intent_enters_research_without_changing_request(react_case, question):
    node, llm, research, _ = react_case
    llm.chat.return_value = LLMResponse(content='{"decision":"ready"}', finish_reason="stop")
    await node.react_agent_node(
        {
            "original_question": question,
            "metadata": {"research_intake": True},
        },
        SimpleNamespace(task_id="intake-ready"),
    )
    assert research.call_args.kwargs["user_message"] == question


async def test_disabled_intake_does_not_call_classifier(react_case):
    node, llm, research, _ = react_case
    await node.react_agent_node(
        {
            "original_question": QUESTION,
            "metadata": {"research_intake": False},
        },
        SimpleNamespace(task_id="intake-disabled"),
    )
    llm.chat.assert_not_awaited()
    research.assert_awaited_once()


async def test_stop_before_intake_does_not_start_a_model_or_research(react_case):
    node, llm, research, _ = react_case
    result = await node.react_agent_node(
        {
            "original_question": QUESTION,
            "metadata": {"research_intake": True, "pause_check": AsyncMock(return_value=True)},
        },
        SimpleNamespace(task_id="intake-stopped"),
    )
    assert result["stopped_by"] == "paused"
    llm.chat.assert_not_awaited()
    research.assert_not_awaited()


async def test_provider_failure_is_not_misrepresented_as_missing_subject(react_case):
    node, llm, research, root = react_case
    llm.chat.side_effect = ValueError("synthetic provider failure")
    with pytest.raises(RuntimeError, match="did not complete"):
        await node.react_agent_node(
            {"original_question": QUESTION, "metadata": {"research_intake": True}},
            SimpleNamespace(task_id="intake-provider-failure"),
        )
    research.assert_not_awaited()
    assert not (root / "conversation.json").exists()


@pytest.mark.parametrize(
    "payload", ["invalid", "[]", '{"decision":"guess"}', '{"decision":"clarify","question":""}']
)
async def test_invalid_classification_never_launches_research(react_case, payload):
    node, llm, research, _ = react_case
    llm.chat.return_value = LLMResponse(content=payload, finish_reason="stop")
    with pytest.raises(RuntimeError, match="Research intake"):
        await node.react_agent_node(
            {
                "original_question": QUESTION,
                "metadata": {"research_intake": True},
            },
            SimpleNamespace(task_id="intake-invalid"),
        )
    research.assert_not_awaited()


async def test_team_clarification_does_not_dispatch_or_generate_report(tmp_path, monkeypatch):
    from frontier_agent.components.agent_bus import AgentBus
    from frontier_agent.core.runtime.registries import services as registry
    from frontier_agent.core.runtime.resources.manager import ResourceManager
    from workflows._shared.cross_mode_context import export_conversation_context
    from workflows.agent_team.edges import should_run_reporter
    from workflows.agent_team.nodes import main_agent as node

    llm = SimpleNamespace(
        model="mock",
        chat=AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({"decision": "clarify", "question": CLARIFICATION}),
                finish_reason="stop",
            )
        ),
    )
    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *a, **kw: (
            llm,
            {"agent": {"reporter": True, "replay_max_tokens": 0}},
            None,
        ),
    )
    monkeypatch.setattr(node, "_resolve_profile_tools", lambda *a, **kw: ([], []))
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda *a: "bwrap")
    monkeypatch.setattr(node, "bwrap_available", lambda: False)
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *a: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *a: tmp_path / "conversation.json"
    )
    research = AsyncMock(side_effect=AssertionError("must not enter team research"))
    monkeypatch.setattr(node, "run_agent_loop", research)
    before = registry.snapshot()
    registry.register(AgentBus, AgentBus())
    registry.register(ResourceManager, object())
    try:
        result = await node.main_agent_node(
            {
                "original_question": QUESTION,
                "metadata": {"research_intake": True, "session_id": "team-intake"},
            },
            SimpleNamespace(task_id="team-intake"),
        )
    finally:
        registry.restore(before)
    assert result["final_answer"] == CLARIFICATION
    assert should_run_reporter(result) == "__END__"
    research.assert_not_awaited()
    portable = export_conversation_context((tmp_path / "conversation.json").read_text())
    assert any(record["content"] == CLARIFICATION for record in portable["records"])
