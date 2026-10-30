import json

from frontier_agent.components.agent_bus import AgentBus, JobEntry, SubAgentResult, SubTask
from frontier_agent.core.loop_types import LoopConfig
from frontier_agent.core.messages import system_msg, user_msg
from frontier_agent.core.runtime.loop.agent_loop import _prepare_llm_request
from frontier_agent.core.runtime.registries import services as registry


async def test_synthesis_receives_execution_and_access_limits_without_an_extra_model_turn(tmp_path):
    from workflows.agent_team.nodes.main_agent import _build_observers

    bus = AgentBus()
    bus._jobs["job-1"] = JobEntry(
        job_id="job-1",
        parent_task_id="boundary",
        session_id="boundary::pricing",
        item=SubTask("check prices"),
        status="completed",
        result=SubAgentResult(
            question="check prices",
            role_id="researcher",
            success=True,
            final_content="partial observations",
            metadata={
                "stopped_by": "wall_deadline",
                "final_answer_source": "tool_observations",
                "content_acquisition": [
                    {
                        "source": "https://example.org/pricing",
                        "obtained": False,
                        "status": "unavailable",
                    }
                ],
            },
        ),
    )
    before = registry.snapshot()
    registry.register(AgentBus, bus)
    try:
        observers = _build_observers(
            traj_dir=tmp_path,
            task_id="boundary",
            budget_tokens=None,
            max_input_tokens=None,
            event_store=None,
            tool_names=[],
        )
        messages = [system_msg("synthesize"), user_msg("compare prices")]
        cfg = LoopConfig(task_id="boundary")
        _, request, reason = await _prepare_llm_request(
            cfg, observers, object(), object(), messages, {}, 1
        )
        text = json.dumps(request, ensure_ascii=False)
        assert "Evidence boundary" in text
        assert "wall_deadline" in text
        assert "https://example.org/pricing" in text
        assert "not_assessed" in text
        assert "lowest" in text and "same basis" in text
        assert not reason
        count = len(messages)
        await _prepare_llm_request(cfg, observers, object(), object(), messages, {}, 2)
        assert len(messages) == count
        # Compaction can remove the notice while leaving the evidence unchanged.
        messages[:] = [m for m in messages if "[Evidence boundary]" not in str(m)]
        await _prepare_llm_request(cfg, observers, object(), object(), messages, {}, 3)
        assert len(messages) == count
        assert sum("[Evidence boundary]" in str(m) for m in messages) == 1
        assert bus._jobs["job-1"].status == "completed"
    finally:
        registry.restore(before)


async def test_real_loop_injects_boundary_after_scoped_tool_dispatch(tmp_path):
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from frontier_agent.core.tool import tool
    from workflows.agent_team.nodes.main_agent import _build_observers

    bus = AgentBus()
    previous = registry.snapshot()
    registry.register(AgentBus, bus)
    seen = []

    @tool
    async def dispatch() -> str:
        """Register one completed research job."""
        bus._jobs["scoped-job"] = JobEntry(
            job_id="scoped-job",
            parent_task_id="isolated-bus",
            session_id="isolated-bus::reader",
            item=SubTask("read source"),
            status="completed",
            result=SubAgentResult(
                question="read source",
                role_id="reader",
                success=True,
                final_content="observations",
                metadata={
                    "stopped_by": "wall_deadline",
                    "content_acquisition": [{"source": "https://example.test", "obtained": False}],
                },
            ),
        )
        return "research observations collected"

    class Client:
        model = "offline"

        async def chat(self, messages, **kwargs):
            seen.append(json.loads(json.dumps(messages)))
            if len(seen) == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        {
                            "id": "dispatch-1",
                            "type": "function",
                            "function": {"name": "dispatch", "arguments": "{}"},
                        }
                    ],
                )
            return LLMResponse(
                content="Available evidence is incomplete; the source could not be read."
            )

    try:
        result = await run_agent_loop(
            system_prompt="research",
            user_message="compare",
            llm=Client(),
            tools=[dispatch],
            scope_metadata={"bus_task_id": "isolated-bus"},
            config=LoopConfig(task_id="visible-root", max_turns=3, max_llm_retries=1),
            observers=_build_observers(
                traj_dir=tmp_path,
                task_id="visible-root",
                budget_tokens=None,
                max_input_tokens=None,
                event_store=None,
                tool_names=["dispatch"],
            ),
        )
        assert len(seen) == 2
        assert "[Evidence boundary]" in json.dumps(seen[1])
        assert "https://example.test" in json.dumps(seen[1])
        assert result.stopped_by == "final_answer"
        audit = result.metadata["evidence_boundary"]
        assert audit["checks"] == 2 and audit["injections"] == 1
        assert audit["bus_task_id"] == "isolated-bus"
        assert audit["jobs_seen"] == 1
        trace = json.loads((tmp_path / "main_agent.json").read_text())
        assert "[Evidence boundary]" in json.dumps(trace["messages"])
        assert '"t":"context"' in (tmp_path / "main_agent.jsonl").read_text().replace(" ", "")
    finally:
        registry.restore(previous)


async def test_node_exports_summary_failure_and_evidence_injection_metadata(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.loop.model_profile import ModelProfile
    from frontier_agent.core.runtime.resources.manager import ResourceManager
    from frontier_agent.core.tool import tool
    from workflows.agent_team.nodes import main_agent as node

    bus = AgentBus()

    @tool
    async def dispatch() -> str:
        """Collect an incomplete research job."""
        bus._jobs["node-job"] = JobEntry(
            job_id="node-job",
            parent_task_id="node-bus",
            session_id="node-bus::reader",
            item=SubTask("read"),
            status="completed",
            result=SubAgentResult(
                question="read",
                role_id="reader",
                success=True,
                final_content="partial observations",
                metadata={"stopped_by": "wall_deadline"},
            ),
        )
        return "observations"

    class Client:
        model = "offline"
        calls = 0

        async def chat(self, messages, **kwargs):
            if kwargs.get("max_tokens") == 1024:
                raise TimeoutError("summary deadline")
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        {
                            "id": "d",
                            "type": "function",
                            "function": {"name": "dispatch", "arguments": "{}"},
                        }
                    ],
                )
            assert "[Evidence boundary]" in json.dumps(messages)
            return LLMResponse(
                content="Partial finding: the research deadline prevented reading the required source. No exhaustive comparison or verified conclusion is available."
            )

    client = Client()
    profile = {
        "llm": {"model": "offline", "max_tokens": 2048},
        "agent": {
            "planning_mode": False,
            "reporter": False,
            "main_max_turns": 4,
            "context_compaction": "off",
            "replay_max_tokens": 100,
            "replay_max_turns": 1,
            "reasoning_only_timeout_s": 0,
            "reasoning_only_max_tokens": 0,
        },
    }
    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *a, **kw: (client, profile, ModelProfile(model_id="offline", provider="openai")),
    )
    monkeypatch.setattr(node, "_resolve_profile_tools", lambda *a, **kw: ([dispatch], ["dispatch"]))
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda *a: "bwrap")
    monkeypatch.setattr(node, "bwrap_available", lambda: False)
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *a: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *a: ((), (), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *a: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *a: tmp_path / "conversation.json"
    )
    before = registry.snapshot()
    registry.register(AgentBus, bus)
    registry.register(ResourceManager, object())
    try:
        result = await node.main_agent_node(
            {
                "original_question": "Compare sources",
                "metadata": {"bus_task_id": "node-bus", "run_id": "node-test"},
            },
            SimpleNamespace(task_id="node-root"),
        )
        assert result["summary_usage"]["calls"] == 1
        assert result["summary_usage"]["error_type"] == "TimeoutError"
        assert result["evidence_boundary"]["injections"] >= 1
        assert result["evidence_boundary"]["bus_task_id"] == "node-bus"
        assert client.calls == 2
    finally:
        registry.restore(before)
