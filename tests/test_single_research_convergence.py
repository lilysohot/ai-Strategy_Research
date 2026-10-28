"""Single research must turn acquired evidence into a deliverable, not more searches."""

import json

import pytest

from frontier_agent.core.execution_context import (
    ExecutionScope,
    reset_current_execution_scope,
    set_current_execution_scope,
)
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.tool import tool
from plugins.tools.task_board import (
    add_task,
    clear_board,
    render_board,
    restore_board_from_messages,
    snapshot_tasks,
    update_task,
)
from workflows.stateful_react_agent.convergence import ResearchConvergenceObserver


def call(name, args, ident="call"):
    return {
        "id": ident,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args),
        },
    }


@pytest.fixture
def scope():
    token = set_current_execution_scope(
        ExecutionScope(
            task_id="convergence",
            metadata={"research_convergence": True},
        )
    )
    yield "convergence"
    clear_board("convergence")
    reset_current_execution_scope(token)


async def test_new_round_keeps_old_ids_without_counting_old_work(scope):
    history = [
        {
            "role": "assistant",
            "tool_calls": [
                call(
                    "add_task",
                    {
                        "tasks": [{"description": "DeepSeek research"}],
                    },
                )
            ],
        },
        {
            "role": "assistant",
            "tool_calls": [
                call(
                    "update_task",
                    {
                        "updates": [
                            {"id": "t1", "resolution": "resolved", "notes": "Prior answer"}
                        ],
                    },
                )
            ],
        },
    ]
    original = json.dumps(history)
    restore_board_from_messages(scope, history, archive=True)
    await add_task.func(
        tasks=[
            {
                "description": "NOW channels",
                "kind": "research",
                "done_when": "Explain the main customer acquisition routes",
            }
        ]
    )
    assert "DeepSeek" not in render_board(scope)
    assert "resolved 0/1" in render_board(scope)
    assert [t["id"] for t in snapshot_tasks(scope)] == ["t2"]
    assert json.dumps(history) == original
    # Explicit continuation can reactivate an old id without rewriting replay.
    await update_task.func(
        updates=[
            {"id": "t1", "resolution": "in_progress", "gap": "Check the newly requested release"}
        ]
    )
    assert [t["id"] for t in snapshot_tasks(scope)] == ["t1", "t2"]


async def test_resolution_preserves_basis_and_requires_a_reason(scope):
    await add_task.func(
        tasks=[
            {
                "description": "NOW channels",
                "kind": "research",
                "done_when": "Identify channels with sources",
            }
        ]
    )
    rejected = await update_task.func(updates=[{"id": "t1", "resolution": "resolved"}])
    assert "Error" in rejected
    assert snapshot_tasks(scope)[0]["resolution"] == "open"
    await update_task.func(
        updates=[
            {
                "id": "t1",
                "resolution": "resolved",
                "notes": "Direct sales and partners",
                "evidence_refs": ["https://example.org/report"],
                "gap": "",
            }
        ]
    )
    task = snapshot_tasks(scope)[0]
    assert task["notes"] == "Direct sales and partners"
    assert task["evidence_refs"] == ["https://example.org/report"]
    assert task["done_when"] == "Identify channels with sources"


def test_rejected_updates_do_not_become_resolved_when_replayed(scope):
    history = [
        {
            "role": "assistant",
            "tool_calls": [
                call(
                    "add_task",
                    {
                        "tasks": [{"description": "Channels"}, {"description": "Verification"}],
                    },
                    "add",
                )
            ],
        },
        {"role": "tool", "tool_call_id": "add", "content": "Added ['t1', 't2']."},
        {
            "role": "assistant",
            "tool_calls": [
                call(
                    "update_task",
                    {
                        "updates": [
                            {"id": "t1", "resolution": "resolved", "notes": "Evidence obtained"},
                            {"id": "t2", "resolution": "resolved"},
                        ]
                    },
                    "update",
                )
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "update",
            "content": "Updated ['t1'].\n[task board] ...\nerrors: t2: provide notes",
        },
    ]
    restore_board_from_messages(scope, history)
    tasks = snapshot_tasks(scope)
    assert tasks[0]["resolution"] == "resolved"
    assert tasks[1]["resolution"] == "open"


async def test_completed_research_blocks_more_search_but_allows_citation_repair(scope):
    searches = []
    repairs = []

    @tool
    async def web_search(q: str) -> str:
        """Search the web."""
        searches.append(q)
        return "New material"

    @tool
    async def corpus_submit_manifest() -> str:
        """Verify the report citations."""
        repairs.append(True)
        return '{"ok":true,"publish_status":"verified"}'

    await add_task.func(
        tasks=[
            {"description": "NOW channels", "kind": "research"},
            {"description": "Deliver answer", "kind": "delivery"},
        ]
    )
    await update_task.func(
        updates=[
            {"id": "t1", "resolution": "resolved", "notes": "Channels covered by acquired sources"}
        ]
    )

    class Model:
        model = "stub"

        def __init__(self):
            self.requests = []

        async def chat(self, messages, **kwargs):
            self.requests.append(list(messages))
            if len(self.requests) == 1:
                return LLMResponse(tool_calls=[call("web_search", {"q": "optional acquisitions"})])
            if len(self.requests) == 2:
                return LLMResponse(tool_calls=[call("corpus_submit_manifest", {})])
            return LLMResponse(content="NOW expands through direct sales and partners.")

    llm = Model()
    result = await run_agent_loop(
        system_prompt="Answer from evidence",
        user_message="How does NOW expand?",
        llm=llm,
        tools=[web_search, corpus_submit_manifest],
        config=LoopConfig(
            task_id=scope, max_turns=600, loop_policy=LoopPolicy(no_tool_behavior="stop")
        ),
        observers=[ResearchConvergenceObserver(research_s=450, reserve_s=180)],
        scope_metadata={"research_convergence": True},
    )
    assert not searches
    assert repairs == [True]
    assert result.stopped_by == "no_tool"
    assert result.metadata["finalization_phase"] is True
    assert "direct sales" in result.final_content
    assert any("finalization" in str(m).lower() for m in llm.requests[0])


def test_web_profile_uses_research_not_scientific_scoring():
    from server.profile import build_profile_overrides

    agent = build_profile_overrides()["agent"]
    assert agent["fs_mode"] is False
    assert agent["research_convergence"] is True
    assert agent["finalization_reserve_s"] >= 120


async def test_time_reserve_fires_with_600_turns_and_never_extends_deadline(scope, monkeypatch):
    from frontier_agent.core.execution_context import get_current_execution_scope
    from frontier_agent.core.loop_types import WALL_DEADLINE_MONOTONIC_KEY, TurnContext
    from workflows.stateful_react_agent import convergence

    clock = [0.0]
    monkeypatch.setattr(convergence.time, "monotonic", lambda: clock[0])
    get_current_execution_scope().metadata[WALL_DEADLINE_MONOTONIC_KEY] = 400.0
    observer = ResearchConvergenceObserver(research_s=450, reserve_s=180)
    await observer.on_loop_start(LoopConfig())
    ctx = TurnContext(7, 600, scope, "stateful_react", "", "", [], [], None, {})
    clock[0] = 275
    transition = await observer.on_before_llm(ctx)
    assert transition and ctx.metadata["finalization_reason"] == "time_reserve"
    assert get_current_execution_scope().metadata[WALL_DEADLINE_MONOTONIC_KEY] == 400
    clock[0] = 401
    assert (await observer.on_before_llm(ctx)).stop_reason == "wall_deadline"


async def test_slow_model_cannot_start_search_after_crossing_reserve(scope, monkeypatch):
    from frontier_agent.core.loop_types import TurnContext
    from workflows.stateful_react_agent import convergence

    clock = [0.0]
    monkeypatch.setattr(convergence.time, "monotonic", lambda: clock[0])
    observer = ResearchConvergenceObserver(research_s=450, reserve_s=180)
    await observer.on_loop_start(LoopConfig())
    ctx = TurnContext(7, 600, scope, "stateful_react", "", "", [], [], None, {})
    clock[0] = 250
    assert await observer.on_before_llm(ctx) is None
    clock[0] = 350
    denied = await observer.on_tool_call(ctx, {"name": "web_search", "args": {"q": "more"}})
    assert denied and denied.skip_is_error
    assert ctx.metadata["finalization_phase"]
    notice = await observer.on_turn_end(ctx)
    assert notice and "finalization" in notice.inject_messages[0]


async def test_accepted_user_addition_renews_research_without_old_tasks_closing_it(scope):
    from frontier_agent.core.execution_context import get_current_execution_scope
    from frontier_agent.core.loop_types import WALL_DEADLINE_MONOTONIC_KEY, TurnContext
    from frontier_agent.infra.wall_time_lease import (
        WALL_TIME_LEASE_SCOPE_KEY,
        RenewableWallTimeLease,
    )

    lease = RenewableWallTimeLease()
    outer = lease.bind_duration(630)
    metadata = get_current_execution_scope().metadata
    metadata[WALL_TIME_LEASE_SCOPE_KEY] = lease
    metadata[WALL_DEADLINE_MONOTONIC_KEY] = outer
    await add_task.func(tasks=[{"description": "Original research", "kind": "research"}])
    await update_task.func(updates=[{"id": "t1", "resolution": "resolved", "notes": "Done"}])
    observer = ResearchConvergenceObserver(research_s=450, reserve_s=180)
    await observer.on_loop_start(LoopConfig())
    ctx = TurnContext(7, 600, scope, "stateful_react", "", "", [], [], None, {})
    assert await observer.on_before_llm(ctx)
    assert ctx.metadata["finalization_phase"]
    lease.renew()
    assert await observer.on_before_llm(ctx) is None
    assert not ctx.metadata.get("finalization_phase")
    assert metadata[WALL_DEADLINE_MONOTONIC_KEY] is outer
    assert (
        await observer.on_tool_call(ctx, {"name": "web_search", "args": {"q": "new request"}})
        is None
    )


async def test_search_batch_requires_progress_update_before_more_searches(scope):
    searches = []

    @tool
    async def web_search(q: str) -> str:
        """Search for evidence."""
        searches.append(q)
        return "Evidence for direct sales"

    class Model:
        model = "stub"
        count = 0

        async def chat(self, messages, **kwargs):
            self.count += 1
            actions = {
                1: call("add_task", {"tasks": [{"description": "Channels"}]}),
                2: call("web_search", {"q": "channels"}),
                3: call("web_search", {"q": "optional customer count"}),
                4: call(
                    "update_task",
                    {
                        "updates": [
                            {
                                "id": "t1",
                                "resolution": "resolved",
                                "notes": "Direct sales supported",
                                "evidence_refs": ["source:1"],
                            }
                        ]
                    },
                ),
            }
            return (
                LLMResponse(tool_calls=[actions[self.count]])
                if self.count in actions
                else (LLMResponse(content="Answer with source:1"))
            )

    result = await run_agent_loop(
        system_prompt="Answer",
        user_message="Channels?",
        llm=Model(),
        tools=[add_task, update_task, web_search],
        config=LoopConfig(
            task_id=scope, max_turns=600, loop_policy=LoopPolicy(no_tool_behavior="stop")
        ),
        observers=[ResearchConvergenceObserver(research_s=450, reserve_s=180)],
        scope_metadata={"research_convergence": True},
    )
    assert searches == ["channels"]
    assert result.stopped_by == "no_tool"


@pytest.mark.parametrize("valid_update", [True, False])
async def test_same_batch_update_is_applied_before_search_authorization(scope, valid_update):
    searches = []

    @tool
    async def web_search(q: str) -> str:
        """Return local evidence for a regression test."""
        searches.append(q)
        return "Evidence"

    class Model:
        model = "stub"
        count = 0

        async def chat(self, messages, **kwargs):
            self.count += 1
            actions = {
                1: [call("add_task", {"tasks": [{"description": "Two facts"}]}, "add")],
                2: [call("web_search", {"q": "first"}, "first")],
                3: [
                    call("update_task", {"updates": [{
                        "id": "t1" if valid_update else "missing-task",
                        "resolution": "in_progress", "notes": "First fact found",
                        "gap": "Second fact",
                    }]}, "update"),
                    call("web_search", {"q": "second"}, "second"),
                ],
            }
            return LLMResponse(tool_calls=actions[self.count]) if self.count in actions else LLMResponse(content="Done")

    result = await run_agent_loop(
        system_prompt="Answer", user_message="Two facts", llm=Model(),
        tools=[add_task, update_task, web_search],
        config=LoopConfig(task_id=scope, max_turns=8, loop_policy=LoopPolicy(no_tool_behavior="stop")),
        observers=[ResearchConvergenceObserver(research_s=450, reserve_s=180)],
        scope_metadata={"research_convergence": True},
    )
    assert searches == (["first", "second"] if valid_update else ["first"])
    assert result.stopped_by == "no_tool"


async def test_entering_finalization_does_not_discard_remaining_loop_budget(scope, monkeypatch):
    from frontier_agent.core.execution_context import get_current_execution_scope
    from frontier_agent.core.loop_types import WALL_DEADLINE_MONOTONIC_KEY, TurnContext
    from workflows.stateful_react_agent import convergence

    clock = [0.0]
    monkeypatch.setattr(convergence.time, "monotonic", lambda: clock[0])
    metadata = get_current_execution_scope().metadata
    metadata[WALL_DEADLINE_MONOTONIC_KEY] = 630.0
    observer = ResearchConvergenceObserver(research_s=450, reserve_s=180)
    await observer.on_loop_start(LoopConfig())
    ctx = TurnContext(10, 600, scope, "stateful_react", "", "", [], [], None, {})
    clock[0] = 270.0
    assert await observer.on_before_llm(ctx)
    assert metadata[WALL_DEADLINE_MONOTONIC_KEY] == 630.0
    clock[0] = 450.0
    assert await observer.on_before_llm(ctx) is None
    assert await observer.on_tool_call(ctx, {"name": "investment_strategy_lint"}) is None
    denied = await observer.on_tool_call(ctx, {"name": "web_search"})
    assert denied and denied.skip_is_error
    clock[0] = 631.0
    assert (await observer.on_before_llm(ctx)).stop_reason == "wall_deadline"


@pytest.mark.parametrize("recover", [True, False])
async def test_reasoning_interruption_has_one_bounded_tool_enabled_continuation(scope, recover):
    from frontier_agent.core.errors import LLMReasoningRunaway

    @tool
    async def corpus_fetch() -> str:
        """Read original evidence."""
        return '{"ok":true,"text":"source evidence"}'

    class Model:
        model = "stub"
        count = 0

        async def chat(self, messages, **kwargs):
            self.count += 1
            if self.count == 1:
                return LLMResponse(tool_calls=[call("corpus_fetch", {})])
            if recover and self.count == 3:
                assert kwargs.get("tools"), "Recovery must retain validation tools"
                return LLMResponse(content="Limited answer from source evidence")
            raise LLMReasoningRunaway(
                elapsed_s=120,
                estimated_tokens=4000,
                trigger="time",
                partial_response=LLMResponse(content="", reasoning_content="unfinished"),
            )

    llm = Model()
    result = await run_agent_loop(
        system_prompt="Use verified evidence",
        user_message="Explain",
        llm=llm,
        tools=[corpus_fetch],
        config=LoopConfig(
            task_id=scope,
            max_turns=600,
            max_llm_retries=1,
            loop_policy=LoopPolicy(no_tool_behavior="stop"),
        ),
        observers=[ResearchConvergenceObserver(research_s=450, reserve_s=180)],
    )
    assert llm.count == 3
    assert result.stopped_by == ("no_tool" if recover else "llm_error")
    if recover:
        assert result.final_content == "Limited answer from source evidence"
