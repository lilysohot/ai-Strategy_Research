"""M0 immutable archive tests for cross-mode context sources."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from server.store import (
    ContextHeadConflictError,
    ContextSourceConflictError,
    create_user,
    ensure_session,
    list_session_archived_contexts,
    read_run_context_source,
    read_session_context_head,
    read_session_conversation,
    upsert_session_conversation,
)


@pytest.fixture
async def db(_isolated_database):
    from server.store import init_db

    await init_db()
    yield


async def _session() -> uuid.UUID:
    user = await create_user(username=f"context-{uuid.uuid4().hex}", password_hash="x")
    session_id = uuid.uuid4()
    await ensure_session(session_id=session_id, user_id=user.id, title="context archive")
    return session_id


@pytest.mark.asyncio
async def test_ingest_archives_exact_native_and_portable_source_bytes(db) -> None:
    session_id = await _session()
    run_id = uuid.uuid4()
    native = '{"schema":"conversation-dump/1","marker":"native"}'
    portable = '{"schema":"cross-mode-context/1","records":[]}'

    await upsert_session_conversation(
        session_id=session_id,
        run_id=run_id,
        payload=native,
        pipeline_id="stateful-react-agent",
        portable_payload=portable,
        completeness={"status": "available_window"},
    )

    source = await read_run_context_source(run_id=run_id)
    assert source is not None
    assert source.session_id == session_id
    assert source.pipeline_id == "stateful-react-agent"
    assert source.native_payload == native
    assert source.native_sha256 == hashlib.sha256(native.encode()).hexdigest()
    assert source.portable_payload == portable
    assert source.portable_sha256 == hashlib.sha256(portable.encode()).hexdigest()
    assert source.completeness_json == {"status": "available_window"}
    assert await read_session_conversation(session_id=session_id) == native
    head = await read_session_context_head(session_id=session_id)
    assert head is not None
    assert head.run_id == run_id
    assert head.pipeline_id == "stateful-react-agent"
    assert head.native_payload == native
    assert head.portable_payload == portable
    archived = await list_session_archived_contexts(session_id=session_id)
    assert [(item.run_id, item.portable_payload) for item in archived] == [
        (run_id, portable)
    ]


@pytest.mark.asyncio
async def test_same_run_same_bytes_is_idempotent_without_losing_archive(db) -> None:
    session_id = await _session()
    run_id = uuid.uuid4()
    payload = '{"schema":"conversation-dump/1"}'

    await upsert_session_conversation(session_id=session_id, run_id=run_id, payload=payload)
    await upsert_session_conversation(session_id=session_id, run_id=run_id, payload=payload)

    source = await read_run_context_source(run_id=run_id)
    assert source is not None and source.native_payload == payload


@pytest.mark.asyncio
async def test_same_run_different_bytes_fails_without_mutating_archive_or_head(db) -> None:
    session_id = await _session()
    run_id = uuid.uuid4()
    original = '{"schema":"conversation-dump/1","value":1}'
    replacement = '{"schema":"conversation-dump/1","value":2}'
    await upsert_session_conversation(session_id=session_id, run_id=run_id, payload=original)

    with pytest.raises(ContextSourceConflictError, match="different immutable"):
        await upsert_session_conversation(session_id=session_id, run_id=run_id, payload=replacement)

    source = await read_run_context_source(run_id=run_id)
    assert source is not None and source.native_payload == original
    assert await read_session_conversation(session_id=session_id) == original


@pytest.mark.asyncio
async def test_head_compare_and_swap_rejects_a_late_run(db) -> None:
    session_id = await _session()
    first_run = uuid.uuid4()
    second_run = uuid.uuid4()
    late_run = uuid.uuid4()
    await upsert_session_conversation(
        session_id=session_id,
        run_id=first_run,
        payload='{"schema":"conversation-dump/1","run":1}',
        enforce_expected_head=True,
    )
    await upsert_session_conversation(
        session_id=session_id,
        run_id=second_run,
        payload='{"schema":"conversation-dump/1","run":2}',
        expected_head_run_id=first_run,
        enforce_expected_head=True,
    )

    with pytest.raises(ContextHeadConflictError, match="context head changed"):
        await upsert_session_conversation(
            session_id=session_id,
            run_id=late_run,
            payload='{"schema":"conversation-dump/1","run":"late"}',
            expected_head_run_id=first_run,
            enforce_expected_head=True,
        )

    head = await read_session_context_head(session_id=session_id)
    assert head is not None and head.run_id == second_run
    late_source = await read_run_context_source(run_id=late_run)
    assert late_source is not None
    assert late_source.native_payload == '{"schema":"conversation-dump/1","run":"late"}'


@pytest.mark.asyncio
async def test_worker_export_and_parent_ingest_commit_both_contracts(
    db, tmp_path: Path, monkeypatch
) -> None:
    from frontier_agent.components.observers.conversation_snapshot import build_dump
    from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
    from server import orchestrator as orchestrator_module
    from server.history import CROSS_MODE_CONTEXT_RELPATH
    from server.worker import _export_cross_mode_context

    session_id = await _session()
    run_id = uuid.uuid4()
    run_root = tmp_path / run_id.hex
    native_path = run_root / "run" / "conversation.json"
    native_path.parent.mkdir(parents=True)
    native = build_dump(
        messages=[
            system_msg("single system"),
            user_msg("Keep the five-year horizon."),
            assistant_msg("Constraint retained."),
        ],
        system_prompt="single system",
        tool_names=[],
        tools_hash="tool-hash",
        thinking_format="none",
        pipeline_id="stateful-react-agent",
        node_id="react_agent",
        role_id="stateful_react",
        run_id=run_id.hex,
        session_id=str(session_id),
    )
    native_path.write_text(json.dumps(native), encoding="utf-8")

    portable_path = _export_cross_mode_context(
        run_root,
        published_answer="Published answer after citation repair.",
        answer_status="complete",
    )
    assert portable_path == run_root.joinpath(*CROSS_MODE_CONTEXT_RELPATH)
    monkeypatch.setattr(orchestrator_module, "run_dir_for", lambda _run_id: run_root)

    orchestrator = orchestrator_module.Orchestrator()
    await orchestrator._ingest_conversation(
        run_id.hex,
        session_uuid=session_id,
        pipeline_id="stateful-react-agent",
    )

    source = await read_run_context_source(run_id=run_id)
    assert source is not None
    assert source.pipeline_id == "stateful-react-agent"
    assert source.portable_payload is not None
    assert "Keep the five-year horizon." in source.portable_payload
    assert "Published answer after citation repair." in source.portable_payload
    assert '"kind":"published_answer"' in source.portable_payload
    assert source.completeness_json == {"portable": "available"}
    assert not native_path.exists()
    assert not portable_path.exists()
