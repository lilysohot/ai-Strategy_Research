"""Cross-turn context inheritance: the dump contract and the replay prefix.

The property under test is the one a provider's prefix cache needs: turn N+1's
request must *begin* with turn N's request, byte for byte. Everything else here —
the dump header, the turn-aligned trim, the rejection reasons, the server-side
transport — exists to keep that property provable instead of hoped for.

See ``.scratch/web-business-context/issues/01-context-inheritance.md`` §9.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from frontier_agent.components.observers.conversation_snapshot import (
    SCHEMA,
    ConversationSnapshotObserver,
    build_dump,
    canonical_json,
    select_replay,
    tool_schema_sha256,
    trim_to_turns,
    validate_messages,
)
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import AgentLoopResult, LoopConfig, LoopPolicy
from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from server.history import CONVERSATION_DUMP_RELPATH, resolve_prior_conversation
from server.orchestrator import _stage_prior_conversation

_SYSTEM = "SYSTEM PROMPT"
_TOOLS = [
    {"type": "function", "function": {"name": "alpha", "description": "a", "parameters": {}}},
    {"type": "function", "function": {"name": "beta", "description": "b", "parameters": {}}},
]
_TOOL_NAMES = ["alpha", "beta"]
_PIPELINE = "stateful-react-agent"
_NODE = "react_agent"


@pytest.fixture
async def db(tmp_path):
    """Throwaway SQLite database — the web tests' per-file fixture, mirrored.

    ``run_once`` builds its run tree through ``server.config`` and may touch the
    store, so it needs the same isolated database the sibling tests use.
    """
    from server.config import get_config
    from server.store import init_db, reset_engine

    cfg = get_config()
    orig_url, orig_key = cfg.database_url, cfg.master_key
    cfg.database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()
    yield cfg
    cfg.database_url, cfg.master_key = orig_url, orig_key
    await reset_engine()


def _tool_call(call_id: str, *, name: str = "alpha") -> dict:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def _history() -> list[dict]:
    """A two-turn history that exercises tool pairing as well as the plain turns."""
    return [
        system_msg(_SYSTEM),
        user_msg("Q1"),
        _tool_call("c1"),
        {"content": "tool out", "role": "tool", "tool_call_id": "c1"},
        assistant_msg("A1"),
        user_msg("Q2"),
        assistant_msg("A2"),
    ]


def _dump(messages: list[dict] | None = None, **overrides: Any) -> dict:
    kwargs: dict[str, Any] = {
        "messages": _history() if messages is None else messages,
        "system_prompt": _SYSTEM,
        "tool_names": _TOOL_NAMES,
        "tools_hash": tool_schema_sha256(_TOOLS),
        "thinking_format": "none",
        "pipeline_id": _PIPELINE,
        "node_id": _NODE,
    }
    kwargs.update(overrides)
    return build_dump(**kwargs)


def _select(document: dict, **overrides: Any) -> tuple[list[dict] | None, dict]:
    kwargs: dict[str, Any] = {
        "system_prompt": _SYSTEM,
        "tool_names": _TOOL_NAMES,
        "tools_hash": tool_schema_sha256(_TOOLS),
        "thinking_format": "none",
        "pipeline_id": _PIPELINE,
        "node_id": _NODE,
    }
    kwargs.update(overrides)
    return select_replay(json.dumps(document, ensure_ascii=False), **kwargs)


# ── the dump contract ────────────────────────────────────────────────


def test_a_dump_replays_byte_for_byte() -> None:
    document = _dump()

    messages, decision = _select(document)

    assert decision["decision"] == "used"
    assert decision["prior_turns"] == 2
    assert messages is not None
    assert [canonical_json(m) for m in messages] == [
        canonical_json(m) for m in document["messages"]
    ]


def test_the_dump_carries_the_header_the_reader_matches_on() -> None:
    document = _dump()

    assert document["schema"] == SCHEMA
    assert document["system_prompt"] == _SYSTEM
    assert document["tool_names"] == _TOOL_NAMES
    assert document["tool_schema_sha256"] == tool_schema_sha256(_TOOLS)
    assert document["trim"] is None


def test_non_wire_keys_never_reach_the_dump() -> None:
    tainted = {**assistant_msg("A1"), "duration_ms": 5, "is_error": False}

    document = _dump(messages=[system_msg(_SYSTEM), user_msg("Q1"), tainted])

    assert "duration_ms" not in document["messages"][2]
    assert "is_error" not in document["messages"][2]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"system_prompt": "OTHER"}, "system prompt mismatch"),
        ({"tool_names": ["alpha"]}, "tool list mismatch"),
        ({"tools_hash": tool_schema_sha256([])}, "tool schema mismatch"),
        ({"thinking_format": "tag"}, "thinking_format mismatch"),
        ({"pipeline_id": "agent_team"}, "pipeline_id mismatch"),
        ({"node_id": "other"}, "node_id mismatch"),
    ],
)
def test_replay_is_refused_when_the_prefix_config_moved(
    overrides: dict[str, Any],
    reason: str,
) -> None:
    """Every input to the cached prefix that can drift must fail the replay.

    These are the rejections that keep a profile/tool/policy change from
    silently feeding the model a prefix it never saw — the alternative would be a
    cache miss *plus* a wrong history.
    """
    messages, decision = _select(_dump(), **overrides)

    assert messages is None
    assert decision["decision"] == "skipped"
    assert decision["reason"] == reason


def test_replay_is_refused_for_a_changed_system_message_byte_shape() -> None:
    document = _dump()
    # Same text, different key order: the request's first bytes would differ.
    document["messages"][0] = {"role": "system", "content": _SYSTEM}

    messages, decision = _select(document)

    assert messages is None
    assert decision["reason"] == "system message bytes differ"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("", "no_payload"),
        ("   ", "no_payload"),
        ("{not json", "unparsable payload: JSONDecodeError"),
        ("[]", "payload is not an object"),
        ('{"schema": "conversation-dump/0"}', "schema mismatch: 'conversation-dump/0'"),
    ],
)
def test_a_payload_the_reader_cannot_vouch_for_is_skipped(payload: str, reason: str) -> None:
    messages, decision = select_replay(
        payload,
        system_prompt=_SYSTEM,
        tool_names=_TOOL_NAMES,
        tools_hash=tool_schema_sha256(_TOOLS),
        thinking_format="none",
        pipeline_id=_PIPELINE,
        node_id=_NODE,
    )

    assert messages is None
    assert decision == {"decision": "skipped", "reason": reason}


# ── message validation ───────────────────────────────────────────────


def test_a_history_that_would_400_upstream_is_refused() -> None:
    orphaned = [system_msg(_SYSTEM), user_msg("Q1"), _tool_call("c1")]

    assert validate_messages(orphaned) == "assistant tool_call 'c1' has no tool result"
    assert validate_messages([system_msg(_SYSTEM), user_msg("Q1")]) is None

    messages, decision = _select(_dump(messages=orphaned))
    assert messages is None
    assert decision["reason"].startswith("invalid messages:")


def test_unrooted_and_mis_role_histories_are_refused() -> None:
    assert validate_messages([]) == "empty"
    assert validate_messages([user_msg("no system")]) == "first message is not the system prompt"
    assert validate_messages([system_msg(_SYSTEM), {"role": "robot", "content": "x"}]) == (
        "message[1] has unknown role 'robot'"
    )
    assert validate_messages([system_msg(_SYSTEM), {"role": "tool", "content": "x"}]) == (
        "tool message[1] has no tool_call_id"
    )
    stray = validate_messages([system_msg(_SYSTEM), {**user_msg("Q1"), "spill_refs": ["p"]}])
    assert stray == "message[1] carries non-wire keys ['spill_refs']"


# ── the turn-aligned trim (write-time, so the prefix stays stable) ───


def _four_turns() -> list[dict]:
    messages: list[dict] = [system_msg(_SYSTEM)]
    for index in range(1, 5):
        messages.append(user_msg(f"Q{index}"))
        messages.append(assistant_msg(f"A{index}"))
    return messages


def test_trimming_cuts_whole_turns_and_keeps_the_system_prompt() -> None:
    document = _dump(messages=_four_turns(), max_replay_turns=2)

    kept = document["messages"]
    assert kept[0] == system_msg(_SYSTEM)
    assert [m["content"] for m in kept if m["role"] == "user"] == ["Q3", "Q4"]
    assert document["trim"] == {
        "dropped_turns": 2,
        "kept_turns": 2,
        "cut_at": 5,
        "reason": "over max_replay_turns=2",
    }
    assert validate_messages(kept) is None


def test_the_trim_never_leaves_an_orphaned_tool_result() -> None:
    messages = [
        system_msg(_SYSTEM),
        user_msg("Q1"),
        _tool_call("c1"),
        {"content": "tool out", "role": "tool", "tool_call_id": "c1"},
        assistant_msg("A1"),
        user_msg("Q2"),
        assistant_msg("A2"),
    ]

    trimmed, trim = trim_to_turns(messages, 1)

    assert trim is not None and trim["dropped_turns"] == 1
    assert validate_messages(trimmed) is None
    assert [m.get("role") for m in trimmed] == ["system", "user", "assistant"]


def test_zero_disables_the_cap() -> None:
    trimmed, trim = trim_to_turns(_four_turns(), 0)

    assert trim is None
    assert len(trimmed) == 9


# ── the observer ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_observer_writes_a_dump_and_refuses_a_broken_history(tmp_path) -> None:
    path = tmp_path / "conversation.json"
    observer = ConversationSnapshotObserver(
        path,
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_names=_TOOL_NAMES,
        thinking_format="none",
        pipeline_id=_PIPELINE,
        node_id=_NODE,
        max_replay_turns=10,
    )

    await observer.on_loop_end(
        AgentLoopResult(messages=_history(), turns_used=2, stopped_by="no_tool"),
    )
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema"] == SCHEMA
    assert written["turns_used"] == 2
    assert written["stopped_by"] == "no_tool"

    broken = tmp_path / "broken.json"
    await ConversationSnapshotObserver(
        broken,
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_names=_TOOL_NAMES,
    ).on_loop_end(AgentLoopResult(messages=[system_msg(_SYSTEM), _tool_call("c9")]))
    # No dump at all is the safe outcome: the next turn simply starts fresh.
    assert not broken.exists()


# ── the property: turn two's request starts with turn one's request ──


class _RecordingLLM:
    """Records every request verbatim, then answers in plain text."""

    model = "recording"

    def __init__(self) -> None:
        self.requests: list[list[dict]] = []

    async def chat(self, messages: list, **kwargs: object) -> LLMResponse:
        del kwargs
        self.requests.append([dict(message) for message in messages])
        return LLMResponse(content="answer", finish_reason="stop")


@pytest.mark.asyncio
async def test_turn_two_request_starts_with_turn_one_request() -> None:
    llm = _RecordingLLM()
    config = LoopConfig(max_turns=4, loop_policy=LoopPolicy(no_tool_behavior="stop"))

    first = await run_agent_loop(
        system_prompt=_SYSTEM,
        user_message="Q1",
        llm=llm,
        tools=[],
        config=config,
    )
    assert llm.requests[0] == [system_msg(_SYSTEM), user_msg("Q1")]

    payload = json.dumps(
        build_dump(
            messages=first.messages,
            system_prompt=_SYSTEM,
            tool_names=[],
            tools_hash=tool_schema_sha256([]),
            thinking_format="none",
            pipeline_id=_PIPELINE,
            node_id=_NODE,
        ),
        ensure_ascii=False,
    )
    replayed, decision = select_replay(
        payload,
        system_prompt=_SYSTEM,
        tool_names=[],
        tools_hash=tool_schema_sha256([]),
        thinking_format="none",
        pipeline_id=_PIPELINE,
        node_id=_NODE,
    )
    assert decision["decision"] == "used"

    await run_agent_loop(
        system_prompt=_SYSTEM,
        user_message="Q2",
        llm=llm,
        tools=[],
        config=config,
        initial_messages=replayed,
    )

    second = llm.requests[1]
    # The cached-prefix property, stated as the provider sees it.
    assert [canonical_json(m) for m in second[: len(first.messages)]] == [
        canonical_json(m) for m in first.messages
    ]
    assert second[len(first.messages)] == user_msg("Q2")
    # The kernel must not prepend a second system message on the replay path.
    assert sum(1 for m in second if m["role"] == "system") == 1


# ── server-side transport ────────────────────────────────────────────


def test_the_prior_conversation_is_the_newest_run_that_has_one(tmp_path) -> None:
    older, newer, current = "aa" * 16, "bb" * 16, "cc" * 16
    for name in (older, current):
        dump = tmp_path / name / "run" / "conversation.json"
        dump.parent.mkdir(parents=True)
        dump.write_text("{}", encoding="utf-8")

    turns = [
        SimpleNamespace(run_id=None),  # steers carry no run id
        SimpleNamespace(run_id=older),
        SimpleNamespace(run_id=newer),  # newest, but it never wrote a dump
        SimpleNamespace(run_id=current),
    ]

    found = resolve_prior_conversation(
        turns,
        current_run_id=current,
        path_for=lambda run_hex: tmp_path / run_hex,
    )

    assert found == tmp_path / older / "run" / "conversation.json"
    assert resolve_prior_conversation([], path_for=lambda _: tmp_path) is None
    assert (
        resolve_prior_conversation(
            [SimpleNamespace(run_id=current)],
            current_run_id=current,
            path_for=lambda run_hex: tmp_path / run_hex,
        )
        is None
    )


def test_staging_copies_the_dump_and_removes_a_stale_one(tmp_path) -> None:
    source = tmp_path / "src.json"
    source.write_text('{"schema": "conversation-dump/1"}', encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dest = run_dir / "prior_conversation.json"
    dest.write_text("stale", encoding="utf-8")

    _stage_prior_conversation(run_dir, str(source))
    assert dest.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

    # No source (or a vanished one) must leave nothing behind for the next run to
    # pick up as if it were this conversation.
    _stage_prior_conversation(run_dir, None)
    assert not dest.exists()

    dest.write_text("stale", encoding="utf-8")
    _stage_prior_conversation(run_dir, str(run_dir / "gone.json"))
    assert not dest.exists()


def test_writer_and_reader_agree_on_where_the_dump_lives() -> None:
    """The node writes into ``metadata["_trial_dir"]`` (worker: ``paths["run"]``);
    the server reads a fixed run-relative path. If those two ever drift, replay
    silently stops happening — with no error anywhere — so the equivalence is
    pinned here."""
    import shutil

    from server.config import build_run_paths, run_dir_for

    run_hex = uuid.uuid4().hex
    root = Path(run_dir_for(run_hex))
    assert not root.exists()
    try:
        written = build_run_paths(run_hex)["run"] / "conversation.json"
        read = root.joinpath(*CONVERSATION_DUMP_RELPATH)
        assert written == read
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── the phase-1 precondition, pinned at its real chokepoint ──────────


def test_the_native_filesystem_note_embeds_a_per_run_path(monkeypatch) -> None:
    """Native mode puts the *physical* workspace path into the system prompt.

    Those paths carry the run id, so the request prefix differs on every turn of
    one conversation — the acceptance run refused the replay with exactly
    ``system prompt mismatch`` because of this single line. Container mode renders
    the logical ``/workspace`` convention and is byte-stable, which is why phase 1
    is cache-effective there. Pinned so the defect (or its fix) cannot slip by
    unnoticed.
    """
    from workflows.stateful_react_agent._runtime import render_system_prompt_notes

    monkeypatch.delenv("FRONTIER_AGENT_PROJECT_DIR", raising=False)
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", "/runs/aaaa/ws")
    monkeypatch.setenv("FRONTIER_AGENT_INPUTS_DIR", "/runs/aaaa/inputs")
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", "/runs/aaaa/ws/outputs")
    first = render_system_prompt_notes(sandbox_mode="native", tool_names=["read_file"])

    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", "/runs/bbbb/ws")
    monkeypatch.setenv("FRONTIER_AGENT_INPUTS_DIR", "/runs/bbbb/inputs")
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", "/runs/bbbb/ws/outputs")
    second = render_system_prompt_notes(sandbox_mode="native", tool_names=["read_file"])

    assert "/runs/aaaa/ws" in first
    assert "/runs/bbbb/ws" in second and "/runs/aaaa/ws" not in second

    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", "/runs/cccc/ws")
    third = render_system_prompt_notes(sandbox_mode="container", tool_names=["read_file"])
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", "/runs/dddd/ws")
    fourth = render_system_prompt_notes(sandbox_mode="container", tool_names=["read_file"])

    assert third == fourth
    assert "/runs/" not in third


# ── the state channel (extra_input → the node's filtered state) ──────


def test_the_react_spec_lets_the_replay_payload_reach_the_node() -> None:
    from frontier_agent.core.runtime.dag.graph_builder import apply_context_filter
    from workflows.stateful_react_agent.spec import REACT_SPEC

    policy = REACT_SPEC.nodes[0].context_policy

    filtered = apply_context_filter(
        policy,
        {"original_question": "q", "replay_payload": '{"schema": "x"}', "unrelated": 1},
    )

    assert filtered["replay_payload"] == '{"schema": "x"}'
    assert "unrelated" not in filtered


# ── the worker's half of the transport chain ─────────────────────────


@pytest.mark.asyncio
async def test_worker_hands_the_dump_to_the_workflow_verbatim(db, tmp_path, monkeypatch):
    """The worker must not parse the dump — it passes the bytes through, and the
    session-level business flag (not this run's snapshot) picks the prefix
    config."""
    import os
    import uuid
    from argparse import Namespace

    from server import worker as worker_mod
    from server.config import run_dir_for

    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    payload = '{"schema": "conversation-dump/1", "messages": []}'
    (run_root / "prior_conversation.json").write_text(payload, encoding="utf-8")

    captured: dict[str, Any] = {}

    class FakeBenchmarkSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def run(self, instruction, *, meta=None, pipeline_id="", extra_input=None):
            captured["extra_input"] = extra_input or {}
            captured["meta"] = meta or {}
            return {"final_answer": "ok", "replay_decision": {"decision": "used"}}

    monkeypatch.setattr(
        "benchmarks.public.core.kernel_adapter.BenchmarkSession",
        FakeBenchmarkSession,
    )
    monkeypatch.setattr(
        "server.config.run_dir_for",
        lambda rid: run_root if rid == run_id else run_dir_for(rid),
    )

    args = Namespace(
        run_id=run_id,
        session_id="s",
        turn_index=2,
        prompt="q",
        prompt_addendum="",
        pipeline_id="stateful-react-agent",
        backend="native",
        wall_time=10,
        max_turns=5,
        model="",
        base_url="",
        api_key="",
        agent_tools="",
        business_prefix=1,
    )
    # run_once installs the per-run environment into os.environ by contract;
    # restore it so later tests do not inherit workspace/sandbox vars.
    env_snapshot = dict(os.environ)
    try:
        assert await worker_mod.run_once(args) == 0
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)

    assert captured["extra_input"]["replay_payload"] == payload
    tools = captured["meta"]["profile_overrides"]["agent"]["agent_tools"]
    assert "investment_position_sizing" in tools
    assert "position_sizing" not in tools
    assert "BUSINESS CONTEXT POLICY" in captured["meta"]["_sys_prompt_addendum"]
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["replay"] == {"decision": "used"}


@pytest.mark.asyncio
async def test_worker_non_business_prefix_keeps_the_calculation_tools(db, monkeypatch):
    import os
    import uuid
    from argparse import Namespace

    from server import worker as worker_mod
    from server.config import run_dir_for

    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True, exist_ok=True)

    captured: dict[str, Any] = {}

    class FakeBenchmarkSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def run(self, instruction, *, meta=None, pipeline_id="", extra_input=None):
            captured["extra_input"] = extra_input or {}
            captured["meta"] = meta or {}
            return {"final_answer": "ok"}

    monkeypatch.setattr(
        "benchmarks.public.core.kernel_adapter.BenchmarkSession",
        FakeBenchmarkSession,
    )
    monkeypatch.setattr(
        "server.config.run_dir_for",
        lambda rid: run_root if rid == run_id else run_dir_for(rid),
    )

    args = Namespace(
        run_id=run_id,
        session_id="s",
        turn_index=1,
        prompt="q",
        prompt_addendum="",
        pipeline_id="stateful-react-agent",
        backend="native",
        wall_time=10,
        max_turns=5,
        model="",
        base_url="",
        api_key="",
        agent_tools="",
        business_prefix=0,
    )
    env_snapshot = dict(os.environ)
    try:
        await worker_mod.run_once(args)
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)

    # No dump staged: the payload key must be absent, not empty.
    assert "replay_payload" not in captured["extra_input"]
    tools = captured["meta"]["profile_overrides"]["agent"]["agent_tools"]
    assert "position_sizing" in tools
    assert "investment_position_sizing" not in tools
    assert "BUSINESS CONTEXT POLICY" not in captured["meta"]["_sys_prompt_addendum"]
