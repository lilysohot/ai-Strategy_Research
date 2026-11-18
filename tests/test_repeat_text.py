"""A repeated block may be abbreviated only while its full form is still live.

The two failure modes this pins down:

* abbreviating on "we sent it earlier" after compaction rewrote the history, so
  the model is told "unchanged" with nothing above it to compare against;
* abbreviating on a text that changed in the meantime, so the short reference
  claims staleness the block itself would have contradicted.

Both are tested at the unit level (the gate itself), at the loop level (does the
generation actually reach a tool after a rewrite?), and at the call site that
motivated the gate — ``collect_reports`` replaying the verification list.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace
from typing import Any

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.runtime.loop.compact import COMPACTION_SEQ_KEY
from frontier_agent.core.runtime.loop.tool_exec import TOOL_RESULT_CAP_KEY
from frontier_agent.core.runtime.repeat_text import (
    GENERATION_KEY,
    REWRITE_SEQ_KEY,
    context_generation,
    full_still_visible,
    mark_full_sent,
    may_abbreviate,
    note_context_rewrite,
    publish_generation,
)
from frontier_agent.core.tool import tool
from plugins.tools.collect_reports import (
    _ASSUMED_CAP_CHARS,
    _VERIFICATION_STATUS_REF,
    _verification_status_block,
)

# ``plugins.tools.collect_reports`` is re-exported as a Tool by the package, so the
# module has to be resolved through ``sys.modules`` to patch its collaborators.
collect_reports_module = importlib.import_module("plugins.tools.collect_reports")

_FULL = "[version-bound checks]\n" + json.dumps({"status": "unchecked"}, ensure_ascii=False)


# ── The gate itself ──────────────────────────────────────────────────────


def test_an_unmarked_scope_never_abbreviates() -> None:
    assert may_abbreviate({}, key="k", full=_FULL) is False
    assert may_abbreviate(None, key="k", full=_FULL) is False


def test_identical_text_in_the_same_generation_abbreviates() -> None:
    scope: dict[str, Any] = {}
    mark_full_sent(scope, key="k", full=_FULL)

    assert may_abbreviate(scope, key="k", full=_FULL) is True
    assert may_abbreviate(scope, key="k", full=_FULL + " ") is False


def test_a_compaction_pass_invalidates_the_abbreviation() -> None:
    loop: dict[str, Any] = {}
    scope: dict[str, Any] = {}
    publish_generation(loop, scope)
    mark_full_sent(scope, key="k", full=_FULL)
    assert may_abbreviate(scope, key="k", full=_FULL) is True

    loop[COMPACTION_SEQ_KEY] = 1
    publish_generation(loop, scope)

    assert may_abbreviate(scope, key="k", full=_FULL) is False


def test_a_reading_rewrite_invalidates_the_abbreviation() -> None:
    """A checkpoint retires bodies without being a compaction pass."""
    loop: dict[str, Any] = {}
    scope: dict[str, Any] = {}
    publish_generation(loop, scope)
    mark_full_sent(scope, key="k", full=_FULL)

    note_context_rewrite(loop)
    publish_generation(loop, scope)

    assert loop[REWRITE_SEQ_KEY] == 1
    assert context_generation(loop) == 1
    assert may_abbreviate(scope, key="k", full=_FULL) is False


def test_generation_sums_both_counters() -> None:
    assert context_generation({}) == 0
    assert context_generation({COMPACTION_SEQ_KEY: 2}) == 2
    assert context_generation({REWRITE_SEQ_KEY: 3}) == 3
    assert context_generation({COMPACTION_SEQ_KEY: 2, REWRITE_SEQ_KEY: 3}) == 5
    assert context_generation("not a mapping") == 0
    assert context_generation({COMPACTION_SEQ_KEY: "bad"}) == 0


def test_an_unreadable_generation_never_abbreviates() -> None:
    """``"invalid"`` must not be coerced to 0 and match a real initial generation."""
    scope: dict[str, Any] = {}
    mark_full_sent(scope, key="k", full=_FULL)
    assert may_abbreviate(scope, key="k", full=_FULL) is True

    scope[GENERATION_KEY] = "invalid"

    assert may_abbreviate(scope, key="k", full=_FULL) is False


def test_an_unreadable_counter_is_not_read_as_zero() -> None:
    loop: dict[str, Any] = {COMPACTION_SEQ_KEY: "invalid"}
    assert context_generation(loop) == 0  # display only, never a licence

    scope: dict[str, Any] = {}
    publish_generation(loop, scope)

    assert scope[GENERATION_KEY] is None
    mark_full_sent(scope, key="k", full=_FULL)
    assert may_abbreviate(scope, key="k", full=_FULL) is False


def test_nothing_is_recorded_while_the_generation_is_unreadable() -> None:
    scope: dict[str, Any] = {GENERATION_KEY: "invalid"}
    mark_full_sent(scope, key="k", full=_FULL)

    scope[GENERATION_KEY] = 0  # repaired afterwards

    assert may_abbreviate(scope, key="k", full=_FULL) is False


def test_an_unmirrored_scope_reads_as_the_first_generation() -> None:
    """A sub-agent that never received a mirror must not inherit a licence."""
    fresh: dict[str, Any] = {}
    mark_full_sent(fresh, key="k", full=_FULL)

    other_fresh: dict[str, Any] = {}
    assert may_abbreviate(other_fresh, key="k", full=_FULL) is False


def test_visibility_is_an_exact_substring_test() -> None:
    messages = [{"role": "tool", "content": "prefix " + _FULL + " suffix"}]

    assert full_still_visible(messages, _FULL) is True
    assert full_still_visible(messages, _FULL + " extra") is False
    assert full_still_visible(messages, "") is False
    assert full_still_visible([], _FULL) is False
    assert (
        full_still_visible([{"role": "tool", "content": "[archived] text retired"}], _FULL) is False
    )


def test_a_non_mapping_entry_is_not_visible() -> None:
    assert full_still_visible([SimpleNamespace(content=_FULL)], _FULL) is False


# ── The loop publishes the generation where tools can read it ────────────


@tool
async def generation_probe() -> str:
    """Report the context generation this tool can see.

    Returns:
        The mirrored generation as a decimal string.
    """
    from frontier_agent.core.execution_context import get_current_execution_scope

    scope = get_current_execution_scope()
    return str(context_generation(getattr(scope, "metadata", None)))


class _ScriptedClient:
    """Three calls: probe, probe again, then a final answer."""

    model = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.calls <= 2:
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {"name": "generation_probe", "arguments": "{}"},
                    }
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(content="done", finish_reason="stop")


def _probe_outputs(result: Any) -> list[str]:
    return [
        str(message.get("content"))
        for message in result.messages
        if isinstance(message, dict) and message.get("role") == "tool"
    ]


def test_a_compaction_pass_reaches_the_tool_scope() -> None:
    client = _ScriptedClient()
    result = asyncio.run(
        run_agent_loop(
            system_prompt="s",
            user_message="u",
            llm=client,
            tools=[generation_probe],
            config=LoopConfig(
                task_id="repeat-text-compaction",
                max_turns=6,
                compact_after_turns=0,
                loop_policy=LoopPolicy(no_tool_behavior="stop"),
            ),
        )
    )

    assert _probe_outputs(result) == ["0", "1"]
    assert result.metadata[COMPACTION_SEQ_KEY] == 2


class _Stage:
    """A reading checkpoint that always installs, so the rewrite is observable."""

    def __init__(self) -> None:
        self.calls = 0

    async def maybe_checkpoint(self, messages: list[Any], turn: int = 0) -> Any:
        self.calls += 1
        return SimpleNamespace(installed=True, turn=turn)


def test_a_reading_checkpoint_reaches_the_tool_scope() -> None:
    client = _ScriptedClient()
    stage = _Stage()
    result = asyncio.run(
        run_agent_loop(
            system_prompt="s",
            user_message="u",
            llm=client,
            tools=[generation_probe],
            config=LoopConfig(
                task_id="repeat-text-reading",
                max_turns=6,
                compact_after_turns=99,
                reading_stage=stage,
                loop_policy=LoopPolicy(no_tool_behavior="stop"),
            ),
        )
    )

    assert stage.calls >= 1
    assert _probe_outputs(result) == ["0", "1"]
    assert COMPACTION_SEQ_KEY not in result.metadata


# ── The call site: a replayed verification list ──────────────────────────


class _Bus:
    def list_task_jobs(self, _task_id: str) -> list[object]:
        return []


def _patch_block(monkeypatch: Any, block: str) -> None:
    monkeypatch.setattr(
        collect_reports_module, "render_verification_status", lambda bus, task: block
    )


def test_the_status_block_is_sent_once_then_referenced(monkeypatch: Any) -> None:
    _patch_block(monkeypatch, _FULL)
    scope = SimpleNamespace(metadata={})

    assert _verification_status_block(scope, _Bus(), "run", 200) == _FULL
    assert _verification_status_block(scope, _Bus(), "run", 200) == _VERIFICATION_STATUS_REF


def test_a_changed_block_is_sent_in_full_again(monkeypatch: Any) -> None:
    scope = SimpleNamespace(metadata={})
    _patch_block(monkeypatch, _FULL)
    _verification_status_block(scope, _Bus(), "run", 200)

    changed = _FULL + "\nverdict: failed"
    _patch_block(monkeypatch, changed)

    assert _verification_status_block(scope, _Bus(), "run", 200) == changed


def test_a_compaction_pass_forces_the_full_block(monkeypatch: Any) -> None:
    _patch_block(monkeypatch, _FULL)
    loop: dict[str, Any] = {}
    scope = SimpleNamespace(metadata={})
    publish_generation(loop, scope.metadata)
    assert _verification_status_block(scope, _Bus(), "run", 200) == _FULL

    loop[COMPACTION_SEQ_KEY] = 1
    publish_generation(loop, scope.metadata)

    assert _verification_status_block(scope, _Bus(), "run", 200) == _FULL


def test_a_result_too_long_to_reach_the_model_is_never_marked(monkeypatch: Any) -> None:
    """Without a published cap the conservative fallback still refuses."""
    _patch_block(monkeypatch, _FULL)
    scope = SimpleNamespace(metadata={})

    assert _verification_status_block(scope, _Bus(), "run", _ASSUMED_CAP_CHARS) == _FULL
    assert _verification_status_block(scope, _Bus(), "run", 200) == _FULL


def test_the_published_cap_is_what_decides_marking(monkeypatch: Any) -> None:
    """Not a constant: the loop says what the model will actually receive."""
    _patch_block(monkeypatch, _FULL)
    scope = SimpleNamespace(metadata={TOOL_RESULT_CAP_KEY: 1_500})

    # 1_480 + the block is past the published cap, so this send is not complete.
    assert _verification_status_block(scope, _Bus(), "run", 1_480) == _FULL
    assert _verification_status_block(scope, _Bus(), "run", 1_480) == _FULL

    # A larger cap makes an 9_000-character return deliverable, so it is marked.
    scope.metadata[TOOL_RESULT_CAP_KEY] = 30_000
    assert _verification_status_block(scope, _Bus(), "run", 9_000) == _FULL
    assert _verification_status_block(scope, _Bus(), "run", 9_000) == _VERIFICATION_STATUS_REF


def test_an_unverifiable_projection_never_marks(monkeypatch: Any) -> None:
    """A built-in cap of ``None`` means a custom post-processor decides the cut."""
    _patch_block(monkeypatch, _FULL)
    scope = SimpleNamespace(metadata={TOOL_RESULT_CAP_KEY: None})

    assert _verification_status_block(scope, _Bus(), "run", 10) == _FULL
    assert _verification_status_block(scope, _Bus(), "run", 10) == _FULL


def test_the_mirrored_key_is_the_generation_a_tool_reads() -> None:
    scope: dict[str, Any] = {GENERATION_KEY: 7, COMPACTION_SEQ_KEY: 99}

    assert context_generation(scope) == 7


# ── End to end: the real result post-processor decides what was delivered ──

#: A block with a marker that survives a partial cut, so "partially visible" can
#: be told apart from "delivered".
_E2E_BLOCK = "[version-bound checks]\nMARKER-UNIQUE " + "y" * 40


@tool
async def replay_checks(pad: int) -> str:
    """Return padding followed by the current verification block.

    Args:
        pad: Characters of padding placed before the block.

    Returns:
        The padded body with the check block appended at the end.
    """
    from frontier_agent.core.execution_context import get_current_execution_scope

    scope = get_current_execution_scope()
    body = "x" * pad
    return body + _verification_status_block(scope, _Bus(), "run", len(body))


class _ReplayClient:
    """Two tool calls with independent padding, then a final answer."""

    model = "scripted"

    def __init__(self, pads: tuple[int, int]) -> None:
        self.pads = pads
        self.calls = 0

    async def chat(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.calls <= 2:
            pad = self.pads[self.calls - 1]
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {
                            "name": "replay_checks",
                            "arguments": json.dumps({"pad": pad}),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(content="done", finish_reason="stop")


def _replay(monkeypatch: Any, *, cap: int, pads: tuple[int, int]) -> list[str]:
    _patch_block(monkeypatch, _E2E_BLOCK)
    result = asyncio.run(
        run_agent_loop(
            system_prompt="s",
            user_message="u",
            llm=_ReplayClient(pads),
            tools=[replay_checks],
            config=LoopConfig(
                task_id="repeat-text-e2e",
                max_turns=6,
                tool_result_max_chars=cap,
                loop_policy=LoopPolicy(no_tool_behavior="stop"),
            ),
        )
    )
    return _probe_outputs(result)


def test_a_truncated_result_cannot_license_the_next_abbreviation(monkeypatch: Any) -> None:
    """The block was partly visible, the cap still cut it: send it again."""
    first, second = _replay(monkeypatch, cap=400, pads=(360, 0))

    assert "truncated" in first  # the loop's own marker
    assert "MARKER-UNIQUE" in first  # partially visible...
    assert _E2E_BLOCK not in first  # ...but never delivered whole

    assert second == _E2E_BLOCK
    assert _VERIFICATION_STATUS_REF not in second


def test_a_delivered_result_licenses_the_abbreviation(monkeypatch: Any) -> None:
    first, second = _replay(monkeypatch, cap=5_000, pads=(360, 360))

    assert "truncated" not in first
    assert first.endswith(_E2E_BLOCK)

    assert second.endswith(_VERIFICATION_STATUS_REF)
    assert "MARKER-UNIQUE" not in second
