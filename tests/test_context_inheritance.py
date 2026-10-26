"""Cross-turn context inheritance: the dump contract and the replay prefix.

The property under test is the one a provider's prefix cache needs: turn N+1's
request must *begin* with turn N's request, byte for byte. Everything else here —
the dump header, the turn-aligned trim, the rejection reasons, the server-side
transport — exists to keep that property provable instead of hoped for.

See ``.scratch/web-business-context/issues/01-context-inheritance.md`` §9.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from frontier_agent.components.observers.conversation_snapshot import (
    SCHEMA,
    SUMMARY_TAG,
    ConversationSnapshotObserver,
    build_dump,
    build_summarizer,
    canonical_json,
    render_summary_content,
    select_replay,
    summary_from,
    tool_schema_sha256,
    trim_to_turns,
    validate_messages,
)
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import AgentLoopResult, LoopConfig, LoopPolicy
from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from server.history import CONVERSATION_DUMP_RELPATH
from server.orchestrator import _stage_prior_payload

_SYSTEM = "SYSTEM PROMPT"
_TOOLS = [
    {"type": "function", "function": {"name": "alpha", "description": "a", "parameters": {}}},
    {"type": "function", "function": {"name": "beta", "description": "b", "parameters": {}}},
]
_TOOL_NAMES = ["alpha", "beta"]
_PIPELINE = "stateful-react-agent"
_NODE = "react_agent"
_SESSION = "sess-1"


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
        "session_id": _SESSION,
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
        "session_id": _SESSION,
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


@pytest.mark.parametrize("stored_estimate", [None, 0, 1])
def test_old_payload_is_rejected_against_current_budget(stored_estimate) -> None:
    document = _dump(messages=[system_msg(_SYSTEM), user_msg("x " * 8_000)])
    if stored_estimate is None:
        document.pop("messages_est_tokens")
    else:
        document["messages_est_tokens"] = stored_estimate
    replay, decision = _select(document, max_replay_tokens=100)
    assert replay is None
    assert decision["reason"] == "replay token budget exceeded"
    assert decision["est_tokens"] > decision["token_budget"] == 100


def test_read_budget_change_rejects_without_rewriting_valid_payload() -> None:
    from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

    document = _dump()
    original = canonical_json(document)
    size = estimate_tokens(canonical_json(document["messages"]))
    replay, decision = _select(document, max_replay_tokens=size)
    assert replay == document["messages"]
    assert decision["decision"] == "used"
    assert _select(document, max_replay_tokens=size - 1)[0] is None
    assert _select(document, max_replay_tokens=0)[0] == document["messages"]
    assert canonical_json(document) == original


@pytest.mark.parametrize("budget", [100, 0])
async def test_node_enforces_read_budget_before_starting_the_loop(tmp_path, monkeypatch, budget):
    from types import SimpleNamespace

    from workflows.stateful_react_agent.nodes import main_agent as node

    # Exercise real node wiring through select_replay, stopping at the loop
    # boundary so no LLM or observer can make a model request.
    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *args, **kwargs: (
            SimpleNamespace(model_name="mock"),
            {"agent": {"direct": True, "replay_max_tokens": budget}},
            None,
        ),
    )
    monkeypatch.setattr(
        node, "registry", SimpleNamespace(get=lambda _: None, get_optional=lambda _: None)
    )
    monkeypatch.setattr(node, "_tools_for_stateful_react", lambda *args: [])
    monkeypatch.setattr(node, "get_direct_system_prompt", lambda: _SYSTEM)
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda _: "bwrap")
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *args: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *args: ((), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *args: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *args: tmp_path / "conversation.json"
    )
    document = _dump(
        messages=[system_msg(_SYSTEM), user_msg("large " * 8_000)],
        tool_names=[],
        tools_hash=tool_schema_sha256([]),
        node_id="react_agent",
    )

    class LoopReached(Exception):
        pass

    async def loop(**kwargs):
        expected = None if budget else document["messages"]
        assert kwargs["initial_messages"] == expected
        raise LoopReached

    monkeypatch.setattr(node, "run_agent_loop", loop)
    # The node supports a CLI compatibility override when apodex is imported.
    import apodex.session

    monkeypatch.setattr(apodex.session, "run_agent_loop", loop)
    with pytest.raises(LoopReached):
        await node.react_agent_node(
            {
                "original_question": "next",
                "replay_payload": canonical_json(document),
                "metadata": {"session_id": _SESSION},
            },
            SimpleNamespace(task_id="budget-test"),
        )


def test_the_dump_carries_the_header_the_reader_matches_on() -> None:
    document = _dump()

    assert document["schema"] == SCHEMA
    assert document["system_prompt"] == _SYSTEM
    assert document["tool_names"] == _TOOL_NAMES
    assert document["tool_schema_sha256"] == tool_schema_sha256(_TOOLS)
    assert document["trim"] is None


def test_the_dump_measures_the_window_it_will_send() -> None:
    """The writer measures the kept window once; the reader reports it (S1-a).

    This is what lets a run's ``usage_json`` say "replayed the previous turn's
    window of N estimated tokens" without a consumer re-tokenising the history,
    and it is measured on the *kept* list — so a trimmed dump reports the window
    it actually replays, not the one it started with.
    """
    document = _dump()

    assert document["messages_est_tokens"] > 0

    messages, decision = _select(document)

    assert messages is not None
    assert decision["est_tokens"] == document["messages_est_tokens"]
    assert decision["payload_bytes"] == len(
        json.dumps(document, ensure_ascii=False).encode("utf-8")
    )


def test_a_dump_from_before_the_window_measurement_still_replays() -> None:
    """The field is informational: its absence must not refuse a valid dump."""
    from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

    document = _dump()
    document.pop("messages_est_tokens")

    messages, decision = _select(document)

    assert messages is not None
    assert decision["decision"] == "used"
    assert decision["est_tokens"] == estimate_tokens(canonical_json(messages))


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
        ({"session_id": "sess-2"}, "session_id mismatch"),
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


def test_the_token_budget_drops_older_turns_when_a_turn_count_is_not_a_size() -> None:
    """Token count, not turn count, is what the provider's ceiling answers to.

    A run may legally end just under its input ceiling; replaying that dump plus
    the new turn is what would push the next run's first request over it — and no
    in-run compaction can help there, because it never gets to run.
    """
    from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

    messages = [system_msg(_SYSTEM)]
    for index in range(1, 4):
        messages.append(user_msg(f"Q{index} " + "填" * 400))
        messages.append(assistant_msg(f"A{index} " + "答" * 400))
    messages.append(user_msg("Q4 short"))
    messages.append(assistant_msg("A4 short"))

    full = estimate_tokens(canonical_json(messages))
    document = _dump(
        messages=messages,
        max_replay_turns=10,
        max_replay_tokens=full // 2,
    )

    kept = document["messages"]
    user_contents = [m["content"] for m in kept if m["role"] == "user"]
    assert user_contents[-1] == "Q4 short"
    assert f"Q1 {'填' * 400}" not in user_contents  # the oldest turn is gone
    assert len(user_contents) < 4
    assert kept[0] == system_msg(_SYSTEM)
    assert document["trim"]["token_budget"] == full // 2
    assert document["trim"]["dropped_for_tokens"] >= 1
    assert document["trim"]["est_tokens"] <= full // 2
    assert validate_messages(kept) is None


def test_the_token_budget_drops_the_only_oversized_turn() -> None:
    """A single huge turn must not make the next run's first request fail.

    There is no older turn to evict in this shape.  The continuity carrier must
    therefore degrade to a non-replayable system-only document instead of
    preserving an over-budget last turn.
    """
    from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

    messages = [
        system_msg(_SYSTEM),
        user_msg("Q " + "填" * 8_000),
        assistant_msg("A " + "答" * 8_000),
    ]
    budget = estimate_tokens(canonical_json([messages[0]])) + 10

    document = _dump(messages=messages, max_replay_tokens=budget)

    assert document["messages"] == [messages[0]]
    assert document["messages_est_tokens"] <= budget
    assert document["trim"]["dropped_turns"] == 1
    assert document["trim"]["kept_turns"] == 0
    assert document["trim"]["dropped_for_tokens"] == 1
    replay, decision = _select(document)
    assert replay is None
    assert decision["reason"] == "no prior turn to replay"


def test_the_token_budget_can_drop_an_oversized_summary_too() -> None:
    """A protected summary is memory, but the size guard still wins."""
    from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

    system = system_msg(_SYSTEM)
    messages = [
        system,
        user_msg(render_summary_content("记" * 8_000)),
        user_msg("Q " + "填" * 8_000),
        assistant_msg("A"),
    ]
    budget = estimate_tokens(canonical_json([system])) + 10

    kept, trim = trim_to_turns(messages, 0, max_tokens=budget, head=2)

    assert kept == [system]
    assert trim is not None
    assert trim["est_tokens"] <= budget
    assert trim["dropped_turns"] == 1
    assert trim["kept_turns"] == 0
    assert trim["dropped_summary_for_tokens"] is True


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


def test_staging_writes_the_stored_payload_and_removes_a_stale_one(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dest = run_dir / "prior_conversation.json"
    dest.write_text("stale", encoding="utf-8")
    payload = '{"schema": "conversation-dump/1", "messages": []}'

    _stage_prior_payload(run_dir, payload)
    assert dest.read_text(encoding="utf-8") == payload

    # No payload must leave nothing behind for the next run to pick up as if it
    # were this conversation.
    dest.write_text("stale", encoding="utf-8")
    _stage_prior_payload(run_dir, None)
    assert not dest.exists()
    _stage_prior_payload(run_dir, "")
    assert not dest.exists()


# ── the carrier's revision (issue 01 §11.5) ──────────────────────────


def test_the_session_store_revision_is_wired_into_the_graph() -> None:
    """One head, chained onto the previous revision.

    ``readiness.expected_heads()`` parses the migration files, so a fork (or a
    revision that forgets its ``down_revision``) makes every deploy fail closed
    with ``schema_ambiguous``. The model's table name is asserted against the
    migration here as well, because the two are written by hand.
    """
    from server.readiness import expected_heads
    from server.store import SessionConversation

    repo_root = Path(__file__).resolve().parents[1]
    carrier_migration = (
        repo_root / "server/alembic/versions/0019_session_conversations.py"
    ).read_text(encoding="utf-8")
    head_migration = (repo_root / "server/alembic/versions/0023_capital_trade_plans.py").read_text(
        encoding="utf-8"
    )

    assert expected_heads() == ("0023_capital_trade_plans",)
    assert SessionConversation.__tablename__ == "session_conversations"
    assert 'down_revision = "0018_plan_capital_terms"' in carrier_migration
    assert f'"{SessionConversation.__tablename__}"' in carrier_migration
    assert 'down_revision = "0022_run_context_sources"' in head_migration


# ── writing the carrier: the parent's ingest (issue 01 §11.3) ────────


def _write_dump(run_dir: Path, payload: str = '{"schema": "conversation-dump/1"}') -> Path:
    dump = run_dir / "run" / "conversation.json"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(payload, encoding="utf-8")
    return dump


async def _session_for_ingest(db) -> uuid.UUID:
    from server.store import ensure_session

    session_uuid = uuid.uuid4()
    await ensure_session(session_id=session_uuid, user_id=await _new_user_id(), title="t")
    return session_uuid


@pytest.mark.asyncio
async def test_ingest_stores_the_dump_and_drops_the_file(db, tmp_path, monkeypatch) -> None:
    """The carrier moves: bytes land in the session row, the file is removed."""
    from server import orchestrator as orch_mod
    from server.store import read_session_conversation

    run_hex = uuid.uuid4().hex
    run_root = tmp_path / run_hex
    payload = '{"schema": "conversation-dump/1", "messages": [{"role": "system"}]}'
    dump = _write_dump(run_root, payload)
    monkeypatch.setattr(orch_mod, "run_dir_for", lambda _rid: run_root)
    session_uuid = await _session_for_ingest(db)

    orch = orch_mod.Orchestrator()
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid)

    assert await read_session_conversation(session_id=session_uuid) == payload
    assert not dump.exists(), "the dump must not survive its own ingest"
    # Stored once, not copied forward: the run directory keeps no carrier.
    assert list(run_root.rglob("conversation.json")) == []


@pytest.mark.asyncio
async def test_ingest_is_idempotent_for_the_same_run(db, tmp_path, monkeypatch) -> None:
    """The crash-recovery pass re-runs ingest; it must not inflate the revision."""
    from server import orchestrator as orch_mod
    from server.store import SessionConversation, get_sessionmaker

    run_hex = uuid.uuid4().hex
    run_root = tmp_path / run_hex
    _write_dump(run_root, '{"schema": "conversation-dump/1"}')
    monkeypatch.setattr(orch_mod, "run_dir_for", lambda _rid: run_root)
    session_uuid = await _session_for_ingest(db)

    orch = orch_mod.Orchestrator()
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid)
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid)

    async with get_sessionmaker()() as session:
        row = await session.get(SessionConversation, session_uuid)
    assert row is not None and row.revision == 1


@pytest.mark.asyncio
async def test_ingest_keeps_the_dump_when_the_store_fails(db, tmp_path, monkeypatch) -> None:
    """Fail-open with a kept file: a store outage must not lose the payload."""
    from server import orchestrator as orch_mod
    from server.store import read_session_conversation

    run_hex = uuid.uuid4().hex
    run_root = tmp_path / run_hex
    dump = _write_dump(run_root, '{"schema": "conversation-dump/1"}')
    monkeypatch.setattr(orch_mod, "run_dir_for", lambda _rid: run_root)
    session_uuid = await _session_for_ingest(db)

    async def boom(**_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(orch_mod, "upsert_session_conversation", boom)

    orch = orch_mod.Orchestrator()
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid)  # must not raise

    assert dump.exists(), "the only copy must be kept when storing failed"
    assert await read_session_conversation(session_id=session_uuid) is None


@pytest.mark.asyncio
async def test_ingest_refuses_a_file_that_is_not_a_dump(db, tmp_path, monkeypatch) -> None:
    """A foreign file must never be stored under the continuity key."""
    from server import orchestrator as orch_mod
    from server.store import read_session_conversation

    run_hex = uuid.uuid4().hex
    run_root = tmp_path / run_hex
    dump = _write_dump(run_root, "not a dump at all")
    monkeypatch.setattr(orch_mod, "run_dir_for", lambda _rid: run_root)
    session_uuid = await _session_for_ingest(db)

    orch = orch_mod.Orchestrator()
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid)

    assert await read_session_conversation(session_id=session_uuid) is None
    assert dump.exists()


@pytest.mark.asyncio
async def test_read_only_ingest_does_not_replace_the_chat_carrier(
    db, tmp_path, monkeypatch
) -> None:
    """A monitor may read the chat carrier but can never replace it (§13)."""
    from server import orchestrator as orch_mod
    from server.store import read_session_conversation, upsert_session_conversation

    run_hex = uuid.uuid4().hex
    run_root = tmp_path / run_hex
    dump = _write_dump(run_root, '{"schema": "conversation-dump/1", "marker": "monitor"}')
    monkeypatch.setattr(orch_mod, "run_dir_for", lambda _rid: run_root)
    session_uuid = await _session_for_ingest(db)
    original = '{"schema": "conversation-dump/1", "marker": "chat"}'
    await upsert_session_conversation(
        session_id=session_uuid, payload=original, run_id=uuid.uuid4()
    )

    orch = orch_mod.Orchestrator()
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid, continuity="read")

    assert await read_session_conversation(session_id=session_uuid) == original
    assert dump.exists(), "a read-only ingest must not touch a stray monitor dump"


@pytest.mark.asyncio
async def test_ingest_without_a_dump_is_a_noop(db, tmp_path, monkeypatch) -> None:
    """Runs that never wrote a dump (agent_team, killed mid-loop) store nothing."""
    from server import orchestrator as orch_mod
    from server.store import read_session_conversation

    run_hex = uuid.uuid4().hex
    run_root = tmp_path / run_hex
    run_root.mkdir(parents=True)
    monkeypatch.setattr(orch_mod, "run_dir_for", lambda _rid: run_root)
    session_uuid = await _session_for_ingest(db)

    orch = orch_mod.Orchestrator()
    await orch._ingest_conversation(run_hex, session_uuid=session_uuid)

    assert await read_session_conversation(session_id=session_uuid) is None


def test_writer_and_reader_agree_on_where_the_dump_lives() -> None:
    """The node writes into ``metadata["_trial_dir"]`` (worker: ``paths["run"]``);
    the ingest step reads a fixed run-relative path. If those two ever drift, the
    payload silently stops being stored — with no error anywhere — so the
    equivalence is pinned here."""
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


def test_the_native_filesystem_note_is_kept_out_of_the_stable_prefix(monkeypatch) -> None:
    """A per-run byte must never reach the system prompt.

    Native mode names the run's physical directories, and a web run gets a fresh
    run id every turn — the acceptance run refused the replay with exactly
    ``system prompt mismatch`` because of that one sentence (issue 01 §9.15). The
    fix splits the text: the prefix half is byte-identical across runs, the
    per-run half rides in the request tail.
    """
    from workflows.stateful_react_agent._runtime import (
        render_per_run_tail_notes,
        render_stable_system_prompt_notes,
    )

    monkeypatch.delenv("FRONTIER_AGENT_PROJECT_DIR", raising=False)
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", "/runs/aaaa/ws")
    monkeypatch.setenv("FRONTIER_AGENT_INPUTS_DIR", "/runs/aaaa/inputs")
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", "/runs/aaaa/ws/outputs")
    stable_first = render_stable_system_prompt_notes(
        sandbox_mode="native",
        tool_names=["bash", "read_file"],
    )
    tail_first = render_per_run_tail_notes(sandbox_mode="native")

    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", "/runs/bbbb/ws")
    monkeypatch.setenv("FRONTIER_AGENT_INPUTS_DIR", "/runs/bbbb/inputs")
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", "/runs/bbbb/ws/outputs")
    stable_second = render_stable_system_prompt_notes(
        sandbox_mode="native",
        tool_names=["bash", "read_file"],
    )
    tail_second = render_per_run_tail_notes(sandbox_mode="native")

    # The cached prefix: identical for both turns, and free of run-specific paths.
    assert (
        stable_first
        == stable_second
        == render_stable_system_prompt_notes(
            sandbox_mode="native",
            tool_names=["bash", "read_file"],
        )
    )
    assert "/runs/" not in stable_first
    # The tail: carries the paths, so the model still learns where it is.
    assert "/runs/aaaa/ws" in tail_first
    assert "/runs/bbbb/ws" in tail_second
    # Container mode's directories are fixed, so nothing needs the tail.
    assert render_per_run_tail_notes(sandbox_mode="container") == ""


# ── the state channel (extra_input → the node's filtered state) ──────


def test_the_react_spec_lets_the_replay_payload_reach_the_node() -> None:
    from frontier_agent.core.runtime.dag.graph_builder import apply_context_filter
    from workflows.stateful_react_agent.spec import REACT_SPEC

    policy = REACT_SPEC.nodes[0].context_policy

    filtered = apply_context_filter(
        policy,
        {
            "original_question": "q",
            "replay_payload": '{"schema": "x"}',
            "continuity_read_enabled": True,
            "continuity_write_enabled": False,
            "unrelated": 1,
        },
    )

    assert filtered["replay_payload"] == '{"schema": "x"}'
    assert filtered["continuity_read_enabled"] is True
    assert filtered["continuity_write_enabled"] is False
    assert "unrelated" not in filtered


# ── watch-triggered runs read chat context without replacing it ──────


async def _new_user_id() -> uuid.UUID:
    """A real user row: ``sessions.user_id`` is a foreign key."""
    from server.store import create_user

    user = await create_user(
        username=f"ctx-{uuid.uuid4().hex[:10]}",
        password_hash="synthetic",
    )
    return user.id


@pytest.mark.asyncio
async def test_is_watch_run_is_false_for_an_ordinary_run(db) -> None:
    """Negative case only: the positive one needs a watch_rule → watch_event →
    watch_event_run fixture chain, which no cheap helper builds today. The
    orchestrator-side wiring is covered by the next test with the query stubbed."""
    from server.store import is_watch_run

    assert await is_watch_run(run_id=uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_a_watch_run_reads_the_chat_carrier_without_replacing_it(db, tmp_path, monkeypatch):
    """Watch runs replay the authoritative chat row in read-only mode (§13).

    The monitor needs the research already completed in this session. Its own raw
    messages remain excluded from the write side, so the next human turn still
    reads this same chat payload.
    """
    from unittest.mock import AsyncMock

    from server import orchestrator as orch_mod
    from server.config import run_dir_for
    from server.store import append_turn, create_run, ensure_session

    orch = orch_mod.Orchestrator()
    monkeypatch.setattr(orch, "_acquire_slot", AsyncMock())
    monkeypatch.setattr(orch, "_release_slot", AsyncMock())
    monkeypatch.setattr(
        orch_mod.Orchestrator,
        "_pump_frames",
        AsyncMock(return_value=None),
    )

    captured: dict[str, dict] = {}

    async def fake_launch(self, run_id, params):
        captured[run_id] = dict(params)
        proc = SimpleNamespace(returncode=0, stdout=None, pid=0)
        return orch_mod.RunHandle(
            run_id=run_id,
            session_id=params["session_id"],
            proc=proc,
        )

    monkeypatch.setattr(orch_mod.Orchestrator, "_launch", fake_launch)

    prior_run = uuid.uuid4()
    prior_root = tmp_path / prior_run.hex
    dump = prior_root / "run" / "conversation.json"
    dump.parent.mkdir(parents=True)
    # Deliberately *not* what the session row will hold: whichever the chat arm
    # reads tells us which carrier is live.
    dump.write_text('{"schema": "conversation-dump/1", "marker": "on-disk"}', encoding="utf-8")
    real_run_dir_for = run_dir_for
    monkeypatch.setattr(
        "server.config.run_dir_for",
        lambda rid: prior_root if rid == prior_run.hex else real_run_dir_for(rid),
    )

    user_id = await _new_user_id()
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    session_uuid = orch_mod._session_uuid(session_id)
    await ensure_session(session_id=session_uuid, user_id=user_id, title="t")
    # turns.run_id is a foreign key, so the prior run needs a real row.
    await create_run(
        run_id=prior_run,
        session_id=session_uuid,
        user_id=user_id,
        prompt="chat q",
        pipeline_id="stateful-react-agent",
        run_dir=str(prior_root),
        status="stopped",
    )
    await append_turn(session_id=session_uuid, role="user", content="chat q", run_id=prior_run)
    await append_turn(session_id=session_uuid, role="assistant", content="chat a", run_id=prior_run)

    async def _seed(label: str) -> str:
        run_hex = uuid.uuid4().hex
        await create_run(
            run_id=uuid.UUID(run_hex),
            session_id=session_uuid,
            user_id=user_id,
            prompt=label,
            pipeline_id="stateful-react-agent",
            run_dir=str(tmp_path / run_hex),
            status="queued",
        )
        return run_hex

    from server.store import reset_engine, upsert_session_conversation

    stored = '{"schema": "conversation-dump/1", "marker": "from-store"}'
    await upsert_session_conversation(session_id=session_uuid, payload=stored, run_id=prior_run)
    # Drop every in-process handle on the store before the read: continuity must
    # come from the row, so an engine nobody has touched yet proves the point
    # (this is the cheap form of "survives a process restart", issue 01 §11.7-4).
    await reset_engine()

    monkeypatch.setattr(orch_mod, "is_watch_run", AsyncMock(return_value=False))
    chat_run = await _seed("chat q2")
    await orch._spawn(
        run_id=chat_run,
        session_id=session_id,
        session_uuid=session_uuid,
        prompt="chat q2",
        user_id=user_id,
    )
    assert captured[chat_run]["_continuity"] == "on"
    # The session row wins over the dump that is sitting on disk (which says
    # "on-disk") — that is the file carrier being retired, observable.
    assert captured[chat_run]["_prior_payload"] == stored

    monkeypatch.setattr(orch_mod, "is_watch_run", AsyncMock(return_value=True))
    watch_run = await _seed("监控触发：x")
    await orch._spawn(
        run_id=watch_run,
        session_id=session_id,
        session_uuid=session_uuid,
        prompt="监控触发：x",
        user_id=user_id,
    )
    assert captured[watch_run]["_continuity"] == "read"
    assert captured[watch_run]["_prior_payload"] == stored


@pytest.mark.asyncio
async def test_worker_reports_read_only_continuity_to_the_workflow(db, tmp_path, monkeypatch):
    """``--continuity read`` reaches the workflow as two explicit directions."""
    import os
    import uuid as _uuid
    from argparse import Namespace

    from server import worker as worker_mod
    from server.config import run_dir_for

    run_id = _uuid.uuid4().hex
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
        prompt="监控触发：x",
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
        continuity="read",
    )
    env_snapshot = dict(os.environ)
    try:
        assert await worker_mod.run_once(args) == 0
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)

    assert captured["extra_input"]["continuity_read_enabled"] is True
    assert captured["extra_input"]["continuity_write_enabled"] is False


@pytest.mark.asyncio
async def test_read_only_node_replays_without_registering_a_snapshot(tmp_path, monkeypatch):
    """Read-only mode reaches the loop with history and no dump producer."""
    from workflows.stateful_react_agent.nodes import main_agent as node

    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *args, **kwargs: (
            SimpleNamespace(model_name="mock"),
            {"agent": {"direct": True, "replay_max_tokens": 0}},
            None,
        ),
    )
    monkeypatch.setattr(
        node, "registry", SimpleNamespace(get=lambda _: None, get_optional=lambda _: None)
    )
    monkeypatch.setattr(node, "_tools_for_stateful_react", lambda *args: [])
    monkeypatch.setattr(node, "get_direct_system_prompt", lambda: _SYSTEM)
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda _: "bwrap")
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *args: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *args: ((), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *args: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *args: tmp_path / "conversation.json"
    )
    document = _dump(
        messages=[system_msg(_SYSTEM), user_msg("prior q"), assistant_msg("prior a")],
        tool_names=[],
        tools_hash=tool_schema_sha256([]),
        node_id="react_agent",
    )

    class LoopReached(Exception):
        pass

    async def loop(**kwargs):
        assert kwargs["initial_messages"] == document["messages"]
        assert not any(
            isinstance(observer, ConversationSnapshotObserver) for observer in kwargs["observers"]
        )
        raise LoopReached

    monkeypatch.setattr(node, "run_agent_loop", loop)
    import apodex.session

    monkeypatch.setattr(apodex.session, "run_agent_loop", loop)
    with pytest.raises(LoopReached):
        await node.react_agent_node(
            {
                "original_question": "monitor trigger",
                "replay_payload": canonical_json(document),
                "continuity_read_enabled": True,
                "continuity_write_enabled": False,
                "metadata": {"session_id": _SESSION},
            },
            SimpleNamespace(task_id="watch-read-only"),
        )


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
            return {
                "final_answer": "ok",
                "replay_decision": {"decision": "used"},
                # Rides the pipeline state into the run summary (§12.11 待办 2).
                "summary_usage": {"calls": 1, "prompt_tokens": 300, "cache_read_tokens": 64},
            }

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
    # §12.11 待办 2: the write-time summary's own tokens survive the state hop, so
    # ``usage_json.replay.summary_usage`` can be filled from the run row alone.
    assert summary["summary_usage"] == {"calls": 1, "prompt_tokens": 300, "cache_read_tokens": 64}
    assert summary["session_id"] == args.session_id
    # Read the actual worker artifact, not a hand-built approximation. No dump
    # exists after normal ingestion; summary must suffice for both fields.
    from scripts.replay_stats import load_from_runs_root

    stat = next(row for row in load_from_runs_root(run_root.parent) if row.run_id == run_id)
    assert stat.session_id == args.session_id
    assert stat.summary_calls == 1
    assert stat.summary_prompt_tokens == 300
    assert stat.summary_cache_read_tokens == 64


@pytest.mark.asyncio
async def test_worker_non_business_prefix_hides_unbound_calculation_tools(db, monkeypatch):
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
    assert "position_sizing" not in tools
    assert "strategy_lint" not in tools
    assert "investment_position_sizing" not in tools
    assert "BUSINESS CONTEXT POLICY" not in captured["meta"]["_sys_prompt_addendum"]
    assert "CONTEXT INTEGRITY POLICY" in captured["meta"]["_sys_prompt_addendum"]


# ── per-run guidance rides in the tail, never in the prefix (S1-b) ───


@pytest.mark.asyncio
async def test_worker_puts_per_run_guidance_in_the_request_tail(db, monkeypatch) -> None:
    """The uploaded-file note lands after the prompt, not inside the system prompt.

    The file list names *this run's* inputs, so inside the system prompt it would
    change the cached request prefix on any turn that carries an attachment and
    invalidate reuse for the whole conversation (issue 01 §10.2 S1-b). The model
    sees the same bytes; only their position moves.
    """
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
            captured["instruction"] = instruction
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

    note = "The user attached 1 input file(s) for this task. Read it from /inputs/brief.md"
    args = Namespace(
        run_id=run_id,
        session_id="s",
        turn_index=2,
        prompt="read the brief",
        prompt_addendum=note,
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
    env_snapshot = dict(os.environ)
    try:
        assert await worker_mod.run_once(args) == 0
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)

    # Tail: after the prompt, in the message the model sees as this turn's ask.
    assert captured["instruction"].startswith("read the brief")
    assert note in captured["instruction"]
    # Prefix: the system-prompt addendum carries only what is constant per turn.
    assert note not in captured["meta"]["_sys_prompt_addendum"]
    assert (
        "Input files are mounted read-only at /inputs." in captured["meta"]["_sys_prompt_addendum"]
    )


# ── S3: the summary block a trim leaves behind (issue 01 §12) ────────


class _RecordingSummarizer:
    """A stand-in summarizer that records what it was asked to summarize."""

    def __init__(self, reply: str | None = "SUMMARY") -> None:
        self.calls: list[tuple[str | None, int]] = []
        self._reply = reply

    async def __call__(self, old_summary: str | None, dropped: list[dict]) -> str | None:
        self.calls.append((old_summary, len(dropped)))
        return self._reply


def _turn(question: str) -> list[dict]:
    """One real turn: a user message and the assistant reply that answers it."""
    return [user_msg(question), assistant_msg(f"A: {question}")]


async def _dump_with(
    tmp_path: Path,
    messages: list[dict],
    *,
    summarizer: object = None,
    max_replay_turns: int = 0,
    max_replay_tokens: int = 0,
    max_replay_turn_step: int | None = None,
) -> dict:
    path = tmp_path / "conversation.json"
    kwargs = {} if max_replay_turn_step is None else {"max_replay_turn_step": max_replay_turn_step}
    observer = ConversationSnapshotObserver(
        path,
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_names=_TOOL_NAMES,
        thinking_format="none",
        pipeline_id=_PIPELINE,
        node_id=_NODE,
        max_replay_turns=max_replay_turns,
        max_replay_tokens=max_replay_tokens,
        summarizer=summarizer,
        **kwargs,
    )
    await observer.on_loop_end(
        AgentLoopResult(messages=messages, turns_used=1, stopped_by="no_tool")
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _tagged(messages: list[dict]) -> list[dict]:
    return [m for m in messages if SUMMARY_TAG in str(m.get("content") or "")]


async def test_a_dump_without_a_trim_carries_no_summary_and_calls_nothing(tmp_path) -> None:
    """No dropped turns ⇒ no summary: the observer must not pay for one."""
    summarizer = _RecordingSummarizer()

    document = await _dump_with(
        tmp_path,
        [system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2")],
        summarizer=summarizer,
        max_replay_turns=5,
    )

    assert summarizer.calls == []
    assert summary_from(document["messages"]) == (1, None)
    assert _tagged(document["messages"]) == []


async def test_a_trim_summarizes_what_it_drops_into_one_block(tmp_path) -> None:
    """The dropped turns become one fixed block right after the system prompt."""
    summarizer = _RecordingSummarizer("第一轮的记忆")

    document = await _dump_with(
        tmp_path,
        [system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2"), *_turn("Q3")],
        summarizer=summarizer,
        max_replay_turns=1,
    )

    assert len(summarizer.calls) == 1
    old_summary, dropped = summarizer.calls[0]
    assert old_summary is None
    assert dropped == 4, "two whole turns, user and assistant each"
    assert summary_from(document["messages"]) == (2, "第一轮的记忆")
    assert len(_tagged(document["messages"])) == 1
    assert document["messages"][2] == user_msg("Q3"), "the kept turn follows the block"


@pytest.mark.parametrize("reply_size", [200, 4_000])
@pytest.mark.parametrize("old_memory", [None, "old memory"])
async def test_final_evictions_all_reach_the_single_summary_call(
    tmp_path, monkeypatch, reply_size, old_memory
) -> None:
    """Reserve memory before deciding the cut, including existing summaries."""
    import frontier_agent.components.observers.conversation_snapshot as snapshots

    # Freeze the estimator so background tokenizer loading cannot change the
    # reproducer's tight budget between the probe and the final write.
    monkeypatch.setattr(snapshots, "estimate_tokens", lambda text: len(text) // 4)
    messages = [system_msg(_SYSTEM)]
    if old_memory:
        messages.append(user_msg(render_summary_content(old_memory)))
    turns = []
    for i in range(3):
        turns.extend([user_msg(f"Q{i}:" + "q" * 200), assistant_msg(f"A{i}:" + "a" * 200)])
    messages.extend(turns)
    calls = []

    async def summarize(old, dropped):
        calls.append((old, list(dropped)))
        return "s" * reply_size

    document = await _dump_with(tmp_path, messages, summarizer=summarize, max_replay_tokens=300)
    assert len(calls) == 1
    assert calls[0][0] == old_memory
    kept = document["messages"][2:]
    assert kept, "reserve should leave the newest small turn intact"
    assert calls[0][1] + kept == turns
    assert len(_tagged(document["messages"])) == 1
    assert document["messages_est_tokens"] <= 300
    assert document["trim"]["dropped_turns"] == len(calls[0][1]) // 2
    assert document["trim"]["kept_turns"] == len(kept) // 2
    assert validate_messages(document["messages"]) is None


async def test_summary_failure_does_not_apply_reserved_extra_evictions(tmp_path, monkeypatch):
    import frontier_agent.components.observers.conversation_snapshot as snapshots

    monkeypatch.setattr(snapshots, "estimate_tokens", lambda text: len(text) // 4)
    messages = [system_msg(_SYSTEM)]
    for i in range(3):
        messages.extend([user_msg(f"Q{i}" + "q" * 200), assistant_msg("a" * 200)])
    fallback, _ = trim_to_turns(messages, 0, max_tokens=300)
    document = await _dump_with(
        tmp_path, messages, summarizer=_RecordingSummarizer(None), max_replay_tokens=300
    )
    assert document["messages"] == fallback
    assert document["trim"]["summary_status"] == "failed"


async def test_a_second_trim_replaces_the_block_and_feeds_the_old_one_back(tmp_path) -> None:
    """Memory accumulates across trims — as one block, never two."""
    first = await _dump_with(
        tmp_path,
        [system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2"), *_turn("Q3")],
        summarizer=_RecordingSummarizer("S1"),
        max_replay_turns=1,
    )
    summarizer = _RecordingSummarizer("S2")

    second = await _dump_with(
        tmp_path,
        [*first["messages"], *_turn("Q4"), *_turn("Q5")],
        summarizer=summarizer,
        max_replay_turns=1,
    )

    assert summarizer.calls, "a trim happened, so the summarizer ran"
    assert summarizer.calls[0][0] == "S1", "the previous memory is an input to the new one"
    assert summary_from(second["messages"]) == (2, "S2")
    assert len(_tagged(second["messages"])) == 1


async def test_an_untouched_summary_is_rewritten_byte_identically(tmp_path) -> None:
    """No trim ⇒ the block is untouched: it is part of the cached prefix."""
    first = await _dump_with(
        tmp_path,
        [system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2")],
        summarizer=_RecordingSummarizer("S1"),
        max_replay_turns=1,
    )
    summarizer = _RecordingSummarizer("SHOULD NOT BE CALLED")

    second = await _dump_with(
        tmp_path,
        [*first["messages"], *_turn("Q3")],
        summarizer=summarizer,
        max_replay_turns=5,
    )

    assert summarizer.calls == []
    assert canonical_json(second["messages"][1]) == canonical_json(first["messages"][1])


async def test_a_failed_summary_keeps_the_previous_memory(tmp_path) -> None:
    """A failed update must not delete what an earlier trim paid for."""
    first = await _dump_with(
        tmp_path,
        [system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2")],
        summarizer=_RecordingSummarizer("S1"),
        max_replay_turns=1,
    )

    document = await _dump_with(
        tmp_path,
        [*first["messages"], *_turn("Q3"), *_turn("Q4")],
        summarizer=_RecordingSummarizer(None),
        max_replay_turns=1,
    )

    assert summary_from(document["messages"]) == (2, "S1")


async def test_a_hanging_summarizer_cannot_hold_the_run_open(tmp_path, monkeypatch) -> None:
    """The bound lives here because ``on_loop_end`` is drained without one.

    ``notify_observers`` schedules a non-critical observer's ``on_loop_end`` as a
    background task and drains it with a bare ``asyncio.gather`` — so a summary
    call with only its own (hundreds of seconds) transport timeout would postpone
    the loop's return until the run's wall deadline killed it.
    """
    import frontier_agent.components.observers.conversation_snapshot as snapshot_mod

    monkeypatch.setattr(snapshot_mod, "SUMMARY_TIMEOUT_S", 0.05)

    async def hang(old_summary: str | None, dropped: list[dict]) -> str | None:
        await asyncio.sleep(5)
        return "too late"

    document = await _dump_with(
        tmp_path,
        [system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2")],
        summarizer=hang,
        max_replay_turns=1,
    )

    head, memory = summary_from(document["messages"])
    assert head == 2 and "Q1" in memory
    assert "Verbatim earlier user excerpts" in memory
    assert document["trim"]["summary_status"] == "fallback_excerpts"
    assert document["messages"][head:] == _turn("Q2")


def test_the_summary_block_is_not_counted_as_a_real_turn() -> None:
    """Counting it as a turn would evict a real turn to keep a paragraph.

    ``head=1`` (forgetting the block) is asserted too, because that is exactly
    the mistake the parameter exists to prevent — and it silently costs the
    memory a previous trim paid for.
    """
    block = user_msg(render_summary_content("memory"))
    messages = [system_msg(_SYSTEM), block, *_turn("Q1"), *_turn("Q2"), *_turn("Q3")]

    kept, trim = trim_to_turns(messages, 2, head=2)
    assert trim is not None and trim["cut_at"] == 4
    assert trim["dropped_turns"] == 1
    assert trim["kept_turns"] == 2
    assert kept[0] == messages[0] and kept[1] == block
    assert kept[2:] == [*_turn("Q2"), *_turn("Q3")]

    _, decision = _select(_dump(messages=messages, max_replay_turns=2))
    assert decision["prior_turns"] == 2

    dropped_memory, _ = trim_to_turns(messages, 2, head=1)
    assert dropped_memory[1] != block, "head=1 loses the memory (the bug this prevents)"


# ── S3: the turn bound keeps a hysteresis band (issue 01 §12.6) ──────


def _conversation(turns: int) -> list[dict]:
    """``system`` + *turns* complete turns, in the order a loop would end with."""
    messages = [system_msg(_SYSTEM)]
    for index in range(1, turns + 1):
        messages.extend(_turn(f"Q{index}"))
    return messages


async def _chain(
    tmp_path: Path,
    *,
    turns: int,
    summarizer: object,
    max_replay_turns: int,
    max_replay_turn_step: int | None = None,
    max_replay_tokens: int = 0,
) -> list[dict]:
    """Drive *turns* writes the way a conversation does: each dump feeds the next.

    Feeding the previous dump back is what makes this a prefix test rather than a
    trim test — the window a real turn replays is the previous run's output.
    """
    documents: list[dict] = []
    messages = [system_msg(_SYSTEM)]
    for index in range(1, turns + 1):
        messages = [*messages, *_turn(f"Q{index}")]
        documents.append(
            await _dump_with(
                tmp_path,
                messages,
                summarizer=summarizer,
                max_replay_turns=max_replay_turns,
                max_replay_turn_step=max_replay_turn_step,
                max_replay_tokens=max_replay_tokens,
            )
        )
        messages = documents[-1]["messages"]
    return documents


class _CountingSummarizer:
    """A stand-in whose memory changes per call, like a real one does."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, old_summary: str | None, dropped: list[dict]) -> str | None:
        self.calls += 1
        return f"memory-{self.calls} (was {len(dropped)} messages)"


async def test_the_turn_bound_waits_for_the_hysteresis_step(tmp_path) -> None:
    """Inside the band nothing is cut; one turn over it, and the cut is one-shot.

    The bound is re-evaluated on every write, so without the band a conversation
    that has reached ``max_replay_turns`` is over it on every later turn — one
    dropped turn per write, and the window slides by one position forever.
    """
    for turns in (1, 2, 3, 4, 5):
        document = await _dump_with(
            tmp_path,
            _conversation(turns),
            max_replay_turns=2,
            max_replay_turn_step=3,
        )
        assert document["trim"] is None, f"{turns} turns is inside the 2..5 band"

    cut = await _dump_with(tmp_path, _conversation(6), max_replay_turns=2, max_replay_turn_step=3)
    assert cut["trim"] is not None
    assert cut["trim"]["cut_at"] == 9, "cut back to the bound, not to one turn less"
    assert [m for m in cut["messages"] if m["role"] == "user"] == [
        user_msg("Q5"),
        user_msg("Q6"),
    ]


async def test_the_summary_is_written_once_per_cut_not_once_per_turn(tmp_path) -> None:
    """The band is what makes "trimming is rare" true (issue 01 §12.3).

    Every cut rewrites the block, and the block sits inside the cached prefix —
    so a cut per turn is a cache reset per turn *and* a summary call per turn.
    """
    banded = _CountingSummarizer()
    documents = await _chain(
        tmp_path,
        turns=12,
        summarizer=banded,
        max_replay_turns=2,
        max_replay_turn_step=3,
    )
    cuts = sum(1 for doc in documents if doc["trim"])

    assert cuts == 2, "12 turns at 2..5 with one turn per write: cuts at 6 and 10"
    assert banded.calls == cuts, "one summary per cut — not one per turn"

    unbanded = _CountingSummarizer()
    await _chain(
        tmp_path,
        turns=12,
        summarizer=unbanded,
        max_replay_turns=2,
        max_replay_turn_step=0,
    )
    assert unbanded.calls == 10, "without the band every turn past the bound cuts"


async def test_the_prefix_survives_every_turn_between_cuts(tmp_path) -> None:
    """The property the band exists for, stated on our side of the wire.

    Between cuts each dump is the previous dump plus one turn, so the next
    request's first bytes are byte-identical to the previous request's. At a cut
    it diverges at index 1 — the memory block, which is the price of the cut.
    """
    documents = await _chain(
        tmp_path,
        turns=12,
        summarizer=_CountingSummarizer(),
        max_replay_turns=2,
        max_replay_turn_step=3,
    )

    appended = 0
    for previous, current in itertools.pairwise(documents):
        if current["trim"] is None:
            assert current["messages"][: len(previous["messages"])] == previous["messages"], (
                "an uncut write must be a pure append"
            )
            appended += 1
        else:
            assert current["messages"][0] == previous["messages"][0], "the system prompt is stable"
            assert current["messages"][1] != previous["messages"][1], "the memory block moved"

    assert appended == 9, "11 transitions, 2 of them cuts"


async def test_step_zero_is_byte_identical_to_the_pre_hysteresis_writes(tmp_path) -> None:
    """The regression guard: not passing the knob must change nothing.

    ``max_replay_turn_step=0`` is documented as "the behaviour before the band",
    so it has to reproduce the old dumps exactly — including the cut on every
    turn past the bound.
    """
    for turns in range(1, 13):
        implicit = await _dump_with(tmp_path, _conversation(turns), max_replay_turns=2)
        explicit = await _dump_with(
            tmp_path, _conversation(turns), max_replay_turns=2, max_replay_turn_step=0
        )
        assert canonical_json(implicit) == canonical_json(explicit), f"diverged at {turns} turns"


async def test_a_long_conversation_cuts_on_a_fixed_cadence(tmp_path) -> None:
    """The standing regression for the band (issue 01 §12.11 待办 1).

    The unit tests above check single decisions. This one drives a whole
    conversation through the real write path and states the property in the shape
    a reader can check at a glance: cuts land on a fixed cadence, and **every turn
    in between is a pure append** — which is exactly what the provider's prefix
    cache can reuse and what a per-turn cut destroys.

    ``max_turns=2, step=2`` keeps it fast: the bound is ``turns > 4``, so the cuts
    fall on turns 5, 8, 11, 14, 17 (one every ``step + 1`` turns).
    """
    documents = await _chain(
        tmp_path,
        turns=18,
        summarizer=_CountingSummarizer(),
        max_replay_turns=2,
        max_replay_turn_step=2,
    )

    cut_turns = [index for index, doc in enumerate(documents, 1) if doc["trim"]]
    assert cut_turns == [5, 8, 11, 14, 17]

    appended = 0
    for previous, current in itertools.pairwise(documents):
        real = [
            m
            for m in current["messages"][1:]
            if m.get("role") == "user" and SUMMARY_TAG not in str(m.get("content") or "")
        ]
        if current["trim"]:
            assert len(real) == 2, "a cut lands back on the bound, not one turn past it"
        else:
            assert len(real) <= 4, "an uncut write stays inside max_turns + step"
            assert current["messages"][: len(previous["messages"])] == previous["messages"], (
                "an uncut turn must be a pure append"
            )
            appended += 1

    assert appended == 12, "17 transitions, 5 of them cuts"
    assert (
        len([m for m in documents[-1]["messages"] if SUMMARY_TAG in str(m.get("content") or "")])
        == 1
    )


async def test_the_hysteresis_buys_back_the_cacheable_prefix(tmp_path) -> None:
    """The value regression: band on ⇒ most transitions reuse the prefix.

    Without the band the window slides every turn, so *no* transition can reuse
    anything (issue 01 §12.6/§12.10 measured 0.0% reuse live). This asserts the
    side of the trade the feature was bought for, in the only currency a prefix
    cache understands: how many transitions leave the previous message list intact
    as a prefix.
    """

    async def append_share(step: int) -> float:
        documents = await _chain(
            tmp_path,
            turns=18,
            summarizer=_CountingSummarizer(),
            max_replay_turns=2,
            max_replay_turn_step=step,
        )
        pairs = list(itertools.pairwise(documents))
        appended = sum(
            1
            for previous, current in pairs
            if current["messages"][: len(previous["messages"])] == previous["messages"]
        )
        return appended / len(pairs)

    banded = await append_share(5)
    unbanded = await append_share(0)

    assert banded >= 0.75, f"band on: expected most transitions to be appends, got {banded:.0%}"
    assert unbanded <= 0.5, f"band off: expected the window to slide, got {unbanded:.0%} appends"


async def test_the_summary_call_reports_its_own_tokens(tmp_path) -> None:
    """The write-time summary's tokens reach the loop result (issue 01 §12.11 #2).

    This call runs after the loop's own usage was accounted and inside an observer
    the trajectory never sees, so without an explicit channel it is unbilled
    everywhere — which is how a 45-turn run's summary calls went uncounted.
    """
    seen: dict[str, Any] = {}

    class _UsageLLM:
        async def chat(self, messages: Any) -> Any:
            return SimpleNamespace(
                content="S",
                usage={"prompt_tokens": 120, "completion_tokens": 30, "cached_tokens": 64},
            )

    summarizer = build_summarizer(_UsageLLM())
    observer = ConversationSnapshotObserver(
        tmp_path / "conversation.json",
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_names=_TOOL_NAMES,
        thinking_format="none",
        pipeline_id=_PIPELINE,
        node_id=_NODE,
        max_replay_turns=1,
        max_replay_turn_step=0,
        summarizer=summarizer,
    )
    result = AgentLoopResult(
        messages=[system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2")],
        turns_used=2,
        stopped_by="no_tool",
    )
    await observer.on_loop_end(result)
    seen.update(result.metadata)

    assert summarizer.calls == 1
    assert summarizer.usage == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "cache_read_tokens": 64,
    }, "the compactor's call must be counted, with cached_tokens normalised"
    assert seen["summary_usage"] == {"calls": 1, "status": "updated", **summarizer.usage}


async def test_a_summarizer_without_usage_still_reports_the_call(tmp_path) -> None:
    """A plain callable (many tests pass one) reports the count, not fake tokens."""

    class _Bare:
        calls = 1

        async def __call__(self, old_summary: str | None, dropped: list[dict]) -> str:
            return "S"

    observer = ConversationSnapshotObserver(
        tmp_path / "conversation.json",
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_names=_TOOL_NAMES,
        thinking_format="none",
        pipeline_id=_PIPELINE,
        node_id=_NODE,
        max_replay_turns=1,
        max_replay_turn_step=0,
        summarizer=_Bare(),
    )
    result = AgentLoopResult(
        messages=[system_msg(_SYSTEM), *_turn("Q1"), *_turn("Q2")],
        turns_used=2,
        stopped_by="no_tool",
    )
    await observer.on_loop_end(result)

    assert result.metadata["summary_usage"] == {"calls": 1, "status": "updated"}


async def test_the_token_budget_keeps_biting_inside_the_band(tmp_path) -> None:
    """The band is for the *turn* bound only: the size guard is not negotiable.

    The token budget exists so a dump can never make the next request unrunnable;
    deferring it by a few turns to protect the cache would trade a cheap miss for
    a failed run.
    """
    document = await _dump_with(
        tmp_path,
        _conversation(4),
        max_replay_turns=2,
        max_replay_turn_step=3,
        max_replay_tokens=1,
    )

    assert document["trim"] is not None, "4 turns is inside the band, the budget still cut"
    assert "replay_max_tokens" in document["trim"]["reason"]
