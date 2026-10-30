"""Regression for a stop arriving while a member generates its final report."""

import asyncio
import json

import pytest

from frontier_agent.components.agent_bus.stop_signal import get_stop_registry
from frontier_agent.components.observers.stop_signal_observer import StopSignalObserver
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.tool import tool
from plugins.tools.submit_report import submit_report
from workflows._shared.research.observers.finalize_answer_observer import FinalizeAnswerObserver
from workflows.agent_team.subagent_runtime import SwarmSubagentRuntime, _swarm_observers


@pytest.mark.parametrize("first_action", [
    "report", "search", "mixed", "invalid_report", "checkpoint", "cancel",
])
async def test_stop_during_generation_preserves_submission_and_tool_validation(first_action):
    sid = "handoff-race::worker"
    started, release = asyncio.Event(), asyncio.Event()
    search_calls = []
    draft = "Scope: existing research\nFinding: partial\nEvidence: https://example.org"

    @tool
    async def search(query: str) -> str:
        """Search for evidence."""
        search_calls.append(query)
        return "evidence"

    def call(name, args, suffix):
        return {"id": f"call-{suffix}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert self.calls <= 2, "handoff must not repeatedly regenerate the report"
            args = {"content": draft}
            if self.calls == 1:
                started.set()
                await release.wait()
                if first_action == "invalid_report":
                    args["attachments"] = ["/workspace/not-published.md"]
                if first_action == "checkpoint":
                    args.update(finish=False, verification_results=[])
                calls = [call("submit_report", args, "report")]
                if first_action in {"search", "mixed"}:
                    calls = [call("search", {"query": "more research"}, "search")]
                    if first_action == "mixed":
                        calls.append(call("submit_report", args, "report"))
            else:
                if first_action == "invalid_report":
                    assert any(m["role"] == "tool" and "rejected" in str(m.get("content"))
                               for m in messages), "normal report validation must still run"
                else:
                    assert any("[stop signal]" in str(m.get("content")) for m in messages)
                calls = [call("submit_report", {"content": draft}, "fixed")]
            return LLMResponse(content="", tool_calls=calls, finish_reason="tool_calls")

    runtime = SwarmSubagentRuntime(
        sub_agent_tools=[search, submit_report], sub_agent_tool_names=["search", "submit_report"],
    )
    # Use the production workflow wiring, including its terminal-response policy.
    observers = [o for o in _swarm_observers(runtime, task_id="handoff-race", session_name="worker")
                 if isinstance(o, (StopSignalObserver, FinalizeAnswerObserver))]
    client = Client()
    worker = asyncio.create_task(run_agent_loop(
        system_prompt="research", user_message="report findings", llm=client,
        tools=[search, submit_report], observers=observers,
        config=LoopConfig(task_id="handoff-race", max_turns=3, max_llm_retries=1),
    ))
    try:
        await asyncio.wait_for(started.wait(), 2)
        get_stop_registry().request_stop(sid, "job-1")
        if first_action == "cancel":
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
            assert client.calls == 1
            assert search_calls == []
            return
        release.set()
        result = await asyncio.wait_for(worker, 3)
    finally:
        release.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        get_stop_registry().consume(sid)

    assert search_calls == []
    assert client.calls == (1 if first_action == "report" else 2)
    assert result.stopped_by == "final_answer"
    assert result.final_content == draft
    successful_reports = [m for m in result.messages if m["role"] == "tool"
                          and "Report submitted" in str(m.get("content"))]
    assert len(successful_reports) == 1
