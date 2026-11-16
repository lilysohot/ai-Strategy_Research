"""The request-boundary composition is what makes growth arguments checkable.

Log character counts are not request sizes: the provider re-serialises, adds
tool definitions, and bills replayed reasoning as input tokens. These pin the
measurement to the list that actually goes out, and pin it to sizes, identities
and hashes rather than content.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import BaseObserver, LoopConfig, TurnContext
from frontier_agent.core.messages import (
    assistant_msg,
    assistant_msg_with_reasoning,
    tool_msg,
    user_msg,
)
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.runtime.loop.request_composition import (
    REQUEST_COMPOSITION_KEY,
    request_composition,
)


def _history() -> list[dict]:
    return [
        {"role": "system", "content": "S" * 100},
        user_msg("U" * 50),
        assistant_msg(
            "A" * 30,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "corpus_fetch", "arguments": '{"doc_id":"x"}'},
                }
            ],
        ),
        tool_msg("T" * 400, "c1"),
    ]


def test_categories_are_split_by_role_and_origin() -> None:
    chars = request_composition(_history())["chars"]

    assert chars["system"] == 100
    assert chars["user"] == 50
    assert chars["assistant_text"] == 30
    # The serialised call is not tool output, so it is counted on its own.
    assert chars["tool_call_args"] == len('{"doc_id":"x"}')
    assert chars["tool_results"] == 400
    assert chars["total"] == 100 + 50 + 30 + chars["tool_call_args"] + 400


def test_tool_results_are_attributed_to_the_tool_that_produced_them() -> None:
    composition = request_composition(_history())

    assert composition["tool_results_by_name"] == {"corpus_fetch": 400}
    largest = composition["largest"][0]
    assert largest["role"] == "tool"
    assert largest["tool"] == "corpus_fetch"
    assert largest["chars"] == 400


def test_only_sizes_identities_and_hashes_are_recorded() -> None:
    """The composition describes the request; it must not become a copy of it."""
    composition = request_composition(_history())

    rendered = str(composition)
    assert "T" * 20 not in rendered
    assert "S" * 20 not in rendered
    assert len(composition["largest"][0]["hash"]) == 12
    assert len(composition["sha256"]) == 64


def test_the_same_history_produces_the_same_digest() -> None:
    """Byte-stability checks (prefix caching) need a comparable fingerprint."""
    first = request_composition(_history())
    second = request_composition(_history())
    assert first["sha256"] == second["sha256"]

    changed = _history()
    changed.append(user_msg("one more turn"))
    assert request_composition(changed)["sha256"] != first["sha256"]


def test_the_largest_blocks_name_the_roles_that_grow() -> None:
    composition = request_composition(_history())
    assert [block["role"] for block in composition["largest"][:2]] == ["tool", "system"]
    assert composition["messages"] == 4


def test_replayed_reasoning_is_its_own_category() -> None:
    """Reasoning is billed on every replay and touched by no compactor, so it
    cannot hide inside assistant text."""
    history = [user_msg("q"), assistant_msg("A" * 30, reasoning="R" * 500)]

    chars = request_composition(history)["chars"]

    assert chars["assistant_text"] == 30
    assert chars["reasoning"] == 500
    assert chars["total"] == 1 + 30 + 500


def test_tag_inlined_reasoning_is_split_out_of_assistant_text() -> None:
    """The ``tag`` format writes reasoning into ``content``; counting the whole
    string as assistant text is how a thinking-heavy turn looks small."""
    message = assistant_msg_with_reasoning("A" * 30, "R" * 500, thinking_format="tag")

    chars = request_composition([message])["chars"]

    assert chars["reasoning"] == 500
    assert chars["assistant_text"] == 30


def test_truncated_reasoning_block_still_counts_as_reasoning() -> None:
    message = {"role": "assistant", "content": "<think>" + "R" * 100}

    chars = request_composition([message])["chars"]

    assert chars["reasoning"] == 100
    assert chars["assistant_text"] == 0


def test_a_literal_think_prefix_in_plain_text_is_not_rewritten() -> None:
    """Only an opening block is inlined reasoning. Anything else stays text."""
    message = {"role": "assistant", "content": "say <think> out loud"}

    chars = request_composition([message])["chars"]

    assert chars["reasoning"] == 0
    assert chars["assistant_text"] == len("say <think> out loud")


def test_reasoning_changes_the_digest() -> None:
    """Two requests differing only in replayed reasoning are different requests;
    calling them equal would report a cache hit that never happened."""
    first = [user_msg("q"), assistant_msg("A", reasoning="R" * 10)]
    second = [user_msg("q"), assistant_msg("A", reasoning="R" * 11)]

    assert request_composition(first)["sha256"] != request_composition(second)["sha256"]


def test_the_largest_block_counts_reasoning_in_its_billed_size() -> None:
    """A turn made almost entirely of reasoning must still sort as large."""
    history = [assistant_msg("A" * 10, reasoning="R" * 500)]

    block = request_composition(history)["largest"][0]

    assert block["reasoning"] == 500
    assert block["chars"] == 510


class _CompositionSpy(BaseObserver):
    critical = True

    def __init__(self) -> None:
        self.seen: list[dict] = []
        self.sent_chars: list[int] = []

    async def on_llm_response(self, ctx: TurnContext) -> None:
        composition = ctx.metadata.get(REQUEST_COMPOSITION_KEY)
        if isinstance(composition, dict):
            self.seen.append(composition)
        self.sent_chars.append(
            sum(len(str(message.get("content") or "")) for message in ctx.messages),
        )
        return None


class _OneShotLLM:
    model = "stub"

    def __init__(self) -> None:
        self.sent: list[list] = []

    async def chat(self, messages: list, **kwargs: object) -> LLMResponse:
        del kwargs
        self.sent.append(messages)
        return LLMResponse(content="done", tool_calls=[], finish_reason="stop")


@pytest.mark.asyncio
async def test_the_loop_publishes_the_composition_of_the_request_it_sent() -> None:
    """Measured where the list is final: after injections and the per-call
    addendum, before the call. Sampling ``ctx.messages`` at turn end describes a
    different, larger request."""
    spy = _CompositionSpy()
    llm = _OneShotLLM()
    addendum = "ADDENDUM " * 20

    await run_agent_loop(
        system_prompt="system prompt",
        user_message="go",
        llm=llm,
        tools=[],
        config=LoopConfig(
            max_turns=1,
            system_addendum_per_call=addendum,
            system_addendum_min_turn=0,
        ),
        observers=[spy],
    )

    assert spy.seen, "the loop published no composition"
    composition = spy.seen[0]
    # The addendum is a system message appended per call, so it is billed as
    # system text and must appear there rather than being lost.
    assert composition["chars"]["system"] >= len(addendum)
    # Same list, same size: the composition describes exactly what was sent.
    assert composition["messages"] == len(llm.sent[0])
    sent_text = sum(len(str(message.get("content") or "")) for message in llm.sent[0])
    sent_args = sum(
        len(str(call.get("function", {}).get("arguments") or ""))
        for message in llm.sent[0]
        for call in (message.get("tool_calls") or [])
    )
    assert composition["chars"]["total"] == sent_text + sent_args


@pytest.mark.asyncio
async def test_the_trajectory_record_carries_the_composition(tmp_path: Path) -> None:
    """The trajectory is where the measurement is read later, so the record has
    to carry it — under ``request``, not folded into ``usage``."""
    observer = TrajectoryFileObserver(tmp_path, filename="traj", formats=("jsonl",))

    await run_agent_loop(
        system_prompt="system prompt",
        user_message="go",
        llm=_OneShotLLM(),
        tools=[],
        config=LoopConfig(max_turns=1, task_id="traj"),
        observers=[observer],
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "traj.jsonl").read_text().splitlines()
        if line.strip()
    ]
    llm_records = [record for record in records if record.get("t") == "llm"]
    assert llm_records, records
    composition = llm_records[0]["request"]
    assert composition["chars"]["total"] > 0
    assert composition["sha256"]
