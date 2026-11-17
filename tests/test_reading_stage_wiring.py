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


def _citable_page() -> str:
    """A corpus page whose item carries a receipt, i.e. an applicable input."""
    import json

    return json.dumps(
        {
            "ok": True,
            "doc_id": "cv2:" + "a" * 64,
            "items": [
                {
                    "text": "2025 财年营收 123 百万美元，不含并购贡献。" * 40,
                    "location": "unit:0001",
                    "evidence_ref": "ce:" + "0" * 32,
                }
            ],
        },
        ensure_ascii=False,
    )


async def _run_member(tmp_path, monkeypatch, *, page: str):
    """Build a member exactly as the workflow does and run one loop."""
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
        return page

    class _ExtractionLLM:
        model = "stub"

        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            self.calls += 1
            return LLMResponse(
                content=json.dumps({"findings": [], "open_questions": []}),
                finish_reason="stop",
            )

    extraction_llm = _ExtractionLLM()
    runtime = SwarmSubagentRuntime(
        sub_agent_llm=extraction_llm,
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
            if self.calls <= 2:
                return LLMResponse(
                    content="reading",
                    tool_calls=[
                        {
                            "id": f"r{self.calls}",
                            "type": "function",
                            "function": {
                                "name": "corpus_fetch",
                                "arguments": '{"doc_id":"d"}',
                            },
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
    return events, agent, extraction_llm


@pytest.mark.asyncio
async def test_a_team_member_loop_actually_runs_the_stage(tmp_path, monkeypatch) -> None:
    """The end of the chain: the config a member is built with, executed.

    The page here carries a receipt, so the input IS applicable and the extraction
    is really attempted; its (empty) result is then refused, which is the fail-safe
    direction: no archive, bodies untouched.
    """
    events, agent, extraction_llm = await _run_member(
        tmp_path, monkeypatch, page=_citable_page(),
    )

    assert events, "the member's loop never reached the reading stage"
    assert any(event.triggered for event in events), events
    assert not any(event.installed for event in events)
    assert extraction_llm.calls >= 1, "an applicable input must reach the extractor"
    installed = [event for event in events if event.installed]
    assert not installed
    assert all(
        "2025 财年营收" in str(message.get("content") or "")
        for message in agent.seen[-1]
        if message.get("role") == "tool"
    ), "a declined checkpoint must leave the bodies in place"


@pytest.mark.asyncio
async def test_a_page_with_no_receipts_never_reaches_the_extractor(
    tmp_path, monkeypatch,
) -> None:
    """No citable refs means no possible finding, so the call is not paid for.

    Before the applicability probe this case still bought a model call whose every
    finding had to be discarded, and the failure was indistinguishable from a slow
    provider.
    """
    events, agent, extraction_llm = await _run_member(
        tmp_path, monkeypatch, page="散文段落，没有可引用收据。" * 200,
    )

    assert extraction_llm.calls == 0, "an inapplicable input must cost zero calls"
    declined = [event for event in events if event.reason == "input_not_applicable"]
    assert declined, [event.reason for event in events]
    assert declined[0].triggered is False
    assert declined[0].failure == "no_evidence_refs"
    assert declined[0].ref_count == 0
    assert declined[0].digest_chars and declined[0].digest_chars > 0
    assert not any(event.phase == "start" for event in events)
    assert all(
        "没有可引用收据" in str(message.get("content") or "")
        for message in agent.seen[-1]
        if message.get("role") == "tool"
    ), "a skipped checkpoint must leave the bodies in place"


def test_profile_keys_map_onto_the_stage_budget(tmp_path, monkeypatch) -> None:
    """The three new knobs must reach the stage, and absence must mean "on".

    The default matters: ``skip_unchanged_failed_input`` protects a long turn from
    paying for the same unchanged bodies every turn. An inverted default would
    silently disable that protection while every other test still passed.
    """
    from workflows._shared.reading_stage import build_reading_stage

    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(tmp_path))

    default = build_reading_stage(
        llm=object(), agent_cfg={"reading_checkpoint": "on"}, task_id="t",
    )
    assert default is not None
    assert default.config.skip_unchanged_failed_input is True
    assert default.config.min_remaining_budget_s == 45.0
    assert default.config.min_attempt_s == 5.0
    # The scope gate is on unless a profile opts out: an installed record is what
    # replaces the body, so structure-only validation is the weaker default.
    assert default.config.statement_check is not None

    opted_in = build_reading_stage(
        llm=object(),
        agent_cfg={
            "reading_checkpoint": "on",
            "reading_checkpoint_retry_same_input": "on",
            "reading_checkpoint_min_remaining_s": 90,
        },
        task_id="t",
    )
    assert opted_in is not None
    assert opted_in.config.skip_unchanged_failed_input is False
    assert opted_in.config.min_remaining_budget_s == 90.0

    gate_off = build_reading_stage(
        llm=object(),
        agent_cfg={"reading_checkpoint": "on", "reading_checkpoint_scope_gate": "off"},
        task_id="t",
    )
    assert gate_off is not None
    assert gate_off.config.statement_check is None
