"""One profile key must mean the same thing to the coordinator and to a member.

Task 05's last open item is that a team member actually reaches the stage. The
wiring is trivial and that is exactly why it is worth pinning: a member that
silently assembles no stage looks identical to a member whose reading is simply
short, and only one of those is a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from workflows._shared.reading_stage import build_reading_stage


class _LLM:
    async def chat(self, messages, **kwargs):
        raise AssertionError("the extractor must not be called just by building")


def test_an_absent_key_leaves_the_stage_off() -> None:
    assert build_reading_stage(llm=_LLM(), agent_cfg={}, task_id="t") is None
    assert build_reading_stage(llm=_LLM(), agent_cfg=None, task_id="t") is None


@pytest.mark.parametrize("value", ["off", "false", "0", "no", "", "OFF"])
def test_the_off_spellings_are_all_off(value: str) -> None:
    assert (
        build_reading_stage(
            llm=_LLM(),
            agent_cfg={"reading_checkpoint": value},
            task_id="t",
        )
        is None
    )


def test_an_unrecognised_value_does_not_silently_enable_archiving() -> None:
    """A typo must not turn on a mechanism that rewrites history."""
    assert (
        build_reading_stage(
            llm=_LLM(),
            agent_cfg={"reading_checkpoint": "maybe"},
            task_id="t",
        )
        is None
    )


def test_an_enabled_stage_carries_the_profile_budgets() -> None:
    stage = build_reading_stage(
        llm=_LLM(),
        agent_cfg={
            "reading_checkpoint": "on",
            "reading_checkpoint_working_set": 12_345,
            "reading_checkpoint_min_body_chars": 2_000,
            "reading_checkpoint_record_limit": 2_500,
            "reading_checkpoint_attempts": 3,
            "reading_checkpoint_timeout_s": 12.5,
        },
        task_id="run-42",
    )

    assert stage is not None
    config = stage.config
    assert config.enabled is True
    assert config.working_set_limit == 12_345
    assert config.min_body_chars == 2_000
    assert config.record_limit == 2_500
    assert config.max_attempts == 3
    assert config.total_timeout_s == 12.5


@pytest.mark.parametrize("bad", ["abc", -5, 0, None])
def test_a_nonsensical_budget_falls_back_rather_than_disabling(bad) -> None:
    """A bad knob should not quietly switch the feature off — the profile asked
    for it. The default is used instead, and the stage still runs."""
    stage = build_reading_stage(
        llm=_LLM(),
        agent_cfg={"reading_checkpoint": "on", "reading_checkpoint_working_set": bad},
        task_id="t",
    )

    assert stage is not None
    assert stage.config.working_set_limit == 40_000


def test_no_llm_means_no_stage() -> None:
    """Without a model there is nothing to extract with, and a stage that cannot
    extract would retire nothing — but it would also claim to be on."""
    assert (
        build_reading_stage(
            llm=None,
            agent_cfg={"reading_checkpoint": "on"},
            task_id="t",
        )
        is None
    )


def test_the_team_member_spec_builds_a_stage_from_the_same_key() -> None:
    """The member's loop config is where "turn it on" has to land. Built through
    the real spec builder so the assertion covers the wiring, not the helper."""
    from frontier_agent.components.agent_bus.models import SubTask
    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    runtime = SwarmSubagentRuntime(
        sub_agent_llm=_LLM(),
        reading_checkpoint_cfg={
            "reading_checkpoint": "on",
            "reading_checkpoint_working_set": 9_000,
        },
    )
    spec = build_swarm_session_runtime_spec(
        runtime,
        session_name="member-1",
        task_id="job-1",
    )
    assert spec.config_builder is not None

    item = SubTask(question="读完整篇财报", role_id="researcher")
    config = spec.config_builder("job-1", item, 20)

    assert config.reading_stage is not None
    assert config.reading_stage.config.enabled is True
    assert config.reading_stage.config.working_set_limit == 9_000


def test_the_team_member_spec_leaves_it_off_by_default() -> None:
    from frontier_agent.components.agent_bus.models import SubTask
    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    runtime = SwarmSubagentRuntime(sub_agent_llm=_LLM())
    spec = build_swarm_session_runtime_spec(
        runtime,
        session_name="member-1",
        task_id="job-1",
    )
    assert spec.config_builder is not None

    config = spec.config_builder("job-1", SubTask(question="q", role_id="researcher"), 20)

    assert config.reading_stage is None


def test_each_job_gets_its_own_stage() -> None:
    """The stage holds a sequence and the list of checkpoints it produced. Shared
    across members, two archives would interleave under one counter."""
    from frontier_agent.components.agent_bus.models import SubTask
    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    runtime = SwarmSubagentRuntime(
        sub_agent_llm=_LLM(),
        reading_checkpoint_cfg={"reading_checkpoint": "on"},
    )
    spec = build_swarm_session_runtime_spec(
        runtime,
        session_name="member-1",
        task_id="job-1",
    )
    assert spec.config_builder is not None

    item = SubTask(question="q", role_id="researcher")
    first = spec.config_builder("job-a", item, 20)
    second = spec.config_builder("job-b", item, 20)

    assert first.reading_stage is not second.reading_stage


@dataclass
class _Config:
    reading_checkpoint: str = "on"


def test_a_non_dict_profile_section_is_tolerated() -> None:
    """``agent_cfg`` is whatever the loader produced; a typed object must not
    crash the loop before it starts."""
    stage = build_reading_stage(llm=_LLM(), agent_cfg=_Config(), task_id="t")  # type: ignore[arg-type]

    assert stage is None


@pytest.mark.asyncio
async def test_a_team_member_loop_actually_runs_the_stage(tmp_path, monkeypatch) -> None:
    """The end of the chain: the config a member is built with, executed.

    The extraction here yields nothing usable (a page with no citable receipts),
    so the assertion is that the stage *ran* on the member's config and then
    declined — which is the fail-safe direction and also the only thing this
    fixture can prove without a corpus backend.
    """
    import json

    from frontier_agent.components.agent_bus.models import SubTask
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import BaseObserver
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from frontier_agent.core.tool import tool
    from workflows.agent_team.subagent_runtime import (
        SwarmSubagentRuntime,
        build_swarm_session_runtime_spec,
    )

    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path))

    @tool
    async def corpus_fetch(doc_id: str) -> str:
        """Read a page.

        Args:
            doc_id: Document identifier.
        """
        return "散文段落，没有可引用收据。" * 200

    class _LLM2:
        model = "stub"

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            return LLMResponse(
                content=json.dumps({"findings": [], "open_questions": []}),
                finish_reason="stop",
            )

    runtime = SwarmSubagentRuntime(
        sub_agent_llm=_LLM2(),
        reading_checkpoint_cfg={
            "reading_checkpoint": "on",
            "reading_checkpoint_working_set": 10,
            "reading_checkpoint_min_body_chars": 10,
            "reading_checkpoint_keep_recent": 0,
        },
    )
    spec = build_swarm_session_runtime_spec(
        runtime,
        session_name="member-1",
        task_id="job-1",
    )
    assert spec.config_builder is not None
    config = spec.config_builder(
        "job-1",
        SubTask(question="读完整篇财报", role_id="researcher"),
        5,
    )
    assert config.reading_stage is not None

    events: list = []

    class _Spy(BaseObserver):
        critical = True

        async def on_reading_checkpoint(self, event) -> None:
            events.append(event)
            return None

    class _Agent:
        model = "stub"

        def __init__(self) -> None:
            self.calls = 0
            self.seen: list[list] = []

        async def chat(self, messages, **kwargs):
            del kwargs
            self.calls += 1
            self.seen.append([dict(m) for m in messages])
            if self.calls == 1:
                return LLMResponse(
                    content="reading",
                    tool_calls=[
                        {
                            "id": "r1",
                            "type": "function",
                            "function": {"name": "corpus_fetch", "arguments": '{"doc_id":"d"}'},
                        }
                    ],
                    finish_reason="tool_calls",
                )
            if self.calls == 2:
                return LLMResponse(
                    content="reading again",
                    tool_calls=[
                        {
                            "id": "r2",
                            "type": "function",
                            "function": {"name": "corpus_fetch", "arguments": '{"doc_id":"d"}'},
                        }
                    ],
                    finish_reason="tool_calls",
                )
            return LLMResponse(content="done", tool_calls=[], finish_reason="stop")

    agent = _Agent()
    await run_agent_loop(
        system_prompt="system",
        user_message="读",
        llm=agent,
        tools=[corpus_fetch],
        config=config,
        observers=[_Spy()],
    )

    assert events, "the member's loop never reached the reading stage"
    assert any(event.triggered for event in events), events
    assert not any(event.installed for event in events)
    assert all(
        "没有可引用收据" in str(message.get("content") or "")
        for message in agent.seen[-1]
        if message.get("role") == "tool"
    ), "a declined checkpoint must leave the bodies in place"
