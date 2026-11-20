"""Post-process boundary, independent inspection, and queue admission regressions."""

import asyncio
import hashlib
import json
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from server import dispatch_outbox, store
from server.config import get_config, run_dir_for
from server.super_link import coordination, events, runtime, service
from server.super_link import models as sl
from server.super_link.contracts import CollaborationError, DeliveryContent
from tests.test_super_link import make_run, published, seed_pair


@pytest.fixture
async def case(monkeypatch):
    await store.init_db()
    async with store.get_engine().begin() as connection:
        await connection.run_sync(sl.Base.metadata.create_all)
    monkeypatch.setattr(get_config(), "super_link_enabled", True)
    sessions = store.get_sessionmaker()
    uid, pair = await seed_pair(sessions)
    return sessions, uid, pair


async def test_completion_frame_cannot_publish_before_exit_and_memory(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="running", archive=False)
    context = await runtime.prepare(binding.run_id, None)
    assert context["peers"] == [{"participant_id": str(pair.single_id), "role": "single"}]
    args = {
        "recipient_id": str(pair.single_id),
        "registration_key": str(uuid.uuid4()),
        "content": {"body": "Evidence supports next research", "requests_execution": True},
    }
    receipt = await runtime.register_from_worker(binding.run_id, args)
    assert await runtime.register_from_worker(binding.run_id, args) == receipt
    async with sessions.begin() as session:
        run = await session.get(store.Run, binding.run_id)
        run.status, run.finished_at = "completed", datetime.now(UTC)
    assert not await runtime.finalize(binding.run_id)
    await runtime.witness_exit(binding.run_id, 0)
    assert not await runtime.finalize(binding.run_id)
    async with sessions.begin() as session:
        final = await session.get(sl.SuperLinkFinalization, binding.run_id)
        assert final.error_code == "continuity_not_saved"
        session.add(
            store.RunContextSource(
                run_id=binding.run_id,
                session_id=pair.team_session_id,
                pipeline_id="agent_team",
                native_payload="PRIVATE",
                native_sha256=hashlib.sha256(b"PRIVATE").hexdigest(),
            )
        )
    await store.upsert_session_conversation(
        session_id=pair.team_session_id,
        run_id=binding.run_id,
        pipeline_id="agent_team",
        payload="PRIVATE",
    )
    assert await runtime.finalize(binding.run_id)
    assert await runtime.finalize(binding.run_id)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkOutbox)) == 1
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 0
    with pytest.raises(CollaborationError, match="registration_closed"):
        await runtime.register_from_worker(binding.run_id, args)


@pytest.mark.parametrize("exit_code,status", [(9, "completed"), (0, "failed"), (0, "stopped")])
async def test_failed_run_never_publishes(case, exit_code, status):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="running")
    await runtime.prepare(binding.run_id, None)
    await runtime.register_from_worker(
        binding.run_id,
        {
            "recipient_id": str(pair.single_id),
            "registration_key": str(uuid.uuid4()),
            "content": {"body": "partial"},
        },
    )
    async with sessions.begin() as session:
        run = await session.get(store.Run, binding.run_id)
        run.status, run.finished_at = status, datetime.now(UTC)
    await runtime.witness_exit(binding.run_id, exit_code)
    assert not await runtime.finalize(binding.run_id)
    async with sessions() as session:
        assert (await session.get(sl.SuperLinkFinalization, binding.run_id)).state == "failed"
        assert await session.scalar(select(func.count()).select_from(sl.SuperLinkOutbox)) == 0


async def test_evidence_is_fixed_snapshot_and_changed_output_blocks(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, status="running")
    await runtime.prepare(binding.run_id, None)
    path = run_dir_for(binding.run_id.hex) / "ws/outputs/report.md"
    path.parent.mkdir(parents=True)
    original = "Evidence: source value is 42."
    digest = hashlib.sha256(original.encode()).hexdigest()
    path.write_text(original)
    result = await runtime.register_from_worker(
        binding.run_id,
        {
            "recipient_id": str(pair.single_id),
            "registration_key": str(uuid.uuid4()),
            "content": {
                "schema_version": 2,
                "body": "Please follow up",
                "requests_execution": True,
                "artifacts": [{"rel_path": "report.md", "sha256": digest}],
            },
        },
    )
    mid = uuid.UUID(result["message_id"])
    async with sessions.begin() as session:
        run = await session.get(store.Run, binding.run_id)
        run.status, run.finished_at = "completed", datetime.now(UTC)
        session.add(store.Artifact(run_id=run.id, rel_path="report.md", sha256=digest))
    await runtime.witness_exit(binding.run_id, 0)
    async with sessions() as session:
        source = await session.get(store.RunContextSource, binding.run_id)
        payload = source.native_payload
    await store.upsert_session_conversation(
        session_id=pair.team_session_id,
        run_id=binding.run_id,
        pipeline_id="agent_team",
        payload=payload,
    )
    path.write_text("altered")
    assert not await runtime.finalize(binding.run_id)
    async with sessions() as session:
        assert await session.get(sl.SuperLinkOutbox, mid) is None
    path.write_text(original)
    assert await runtime.finalize(binding.run_id)
    path.write_text("Changed after publication")
    async with sessions() as session:
        evidence = await coordination.evidence_for(
            session, await session.get(sl.SuperLinkMessage, mid)
        )
        assert evidence[0]["text"] == original


@pytest.mark.parametrize(
    "verdict,accepted", [("pass", True), ("caveat", True), ("block", False), ("incomplete", False)]
)
async def test_review_is_independent_and_only_admission_creates_run(case, verdict, accepted):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair)
    mid = await published(
        sessions,
        binding,
        pair.single_id,
        content=DeliveryContent(body="Research", requests_execution=True),
    )
    async with sessions.begin() as session:
        await service.receive(session, mid)
        await events.seal_changes(session)

    async def inspect(envelope):
        assert "PRIVATE" not in json.dumps(envelope)
        assert set(envelope) == {
            "goal",
            "goal_version",
            "message_id",
            "content",
            "evidence",
            "task_basis",
        }
        return coordination.Inspection(verdict=verdict, explanation="Evidence and scope checked")

    await coordination.inspect_delivery(mid, inspect, reviewer="test-independent")
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.Run)) == 1
    rid = await coordination.accept_delivery(mid)
    assert (rid is not None) == accepted
    assert await coordination.accept_delivery(mid) == rid
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 0
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == int(
            accepted
        )
        if accepted:
            run = await session.get(store.Run, rid)
            assert run.pipeline_id == "stateful-react-agent"
            assert "不是人工消息" in run.prompt
            assert verdict in run.prompt


async def test_inspector_failure_and_stale_goal_do_not_launch(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair)
    mid = await published(
        sessions,
        binding,
        pair.single_id,
        content=DeliveryContent(body="Research", requests_execution=True),
    )
    async with sessions.begin() as session:
        await service.receive(session, mid)
        await events.seal_changes(session)

    async def broken(envelope):
        raise RuntimeError("secret-provider-data")

    await coordination.inspect_delivery(mid, broken, reviewer="test")
    assert await coordination.accept_delivery(mid) is None
    async with sessions.begin() as session:
        row = await session.get(sl.SuperLinkReview, mid)
        assert row.explanation == "inspection_failed"
        row.verdict = "pass"
        space = await session.get(sl.SuperLinkSpace, pair.space_id)
        space.goal_version += 1
    with pytest.raises(CollaborationError, match="stale_or_invalid_review"):
        await coordination.accept_delivery(mid)


async def test_fifo_does_not_overtake_retry_or_unfinished_finalization(case):
    sessions, uid, pair = case
    first = await make_run(sessions, uid, pair, role="single", status="queued", archive=False)
    second = await make_run(sessions, uid, pair, role="single", status="queued", archive=False)
    async with sessions.begin() as session:
        a, b = (
            await session.get(store.Run, first.run_id),
            await session.get(store.Run, second.run_id),
        )
        a.created_at, b.created_at = datetime.now(UTC) - timedelta(seconds=2), datetime.now(UTC)
        for run in (a, b):
            await dispatch_outbox.enqueue(
                session,
                run_id=run.id,
                user_id=uid,
                research_id=run.session_id,
                session_key=str(run.session_id),
                prompt="task",
            )
        dispatch = await dispatch_outbox.get_for_run(session, run_id=a.id)
        dispatch.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)
        assert await dispatch_outbox.claim_due(session) == []
        await events.seal_changes(session)
    async with sessions.begin() as session:
        a, b = (
            await session.get(store.Run, first.run_id),
            await session.get(store.Run, second.run_id),
        )
        a.status = "completed"
        session.add(
            sl.SuperLinkFinalization(
                run_id=a.id, state="pending", exit_code=0, worker_exited_at=datetime.now(UTC)
            )
        )
        await session.flush()
        assert await coordination.fifo_blocked(session, b)
        final = await session.get(sl.SuperLinkFinalization, a.id)
        final.state = "ready"
        await session.flush()
        assert not await coordination.fifo_blocked(session, b)


async def test_direct_submission_uses_durable_queue_once(case):
    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, role="single", status="queued", archive=False)
    for _ in range(2):
        assert await coordination.enqueue_direct(
            binding.run_id, prompt="human", prompt_addendum="", user_id=uid
        )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.Turn)) == 1
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1


async def test_direct_submission_reuses_run_created_event_from_add_run(case):
    sessions, uid, pair = case
    run_id = uuid.uuid4()
    async with sessions.begin() as session:
        await store.add_run(
            session,
            run_id=run_id,
            session_id=pair.single_session_id,
            user_id=uid,
            prompt="pipeline prompt",
            pipeline_id="stateful-react-agent",
            run_dir="unused-test-directory",
        )
        await events.seal_changes(session)

    assert await coordination.enqueue_direct(
        run_id, prompt="human", prompt_addendum="", user_id=uid
    )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(store.RunDispatch)) == 1
        events_for_run = await session.scalar(
            select(func.count())
            .select_from(sl.SuperLinkEvent)
            .where(sl.SuperLinkEvent.change_key == f"run:{run_id}:created")
        )
        assert events_for_run == 1


async def test_disabling_feature_holds_already_queued_collaboration(case, monkeypatch):
    from server.super_link.contracts import DISPATCH_MARKER

    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, role="single", status="queued", archive=False)
    await coordination.enqueue_direct(
        binding.run_id, prompt="human", prompt_addendum="attached files", user_id=uid
    )
    monkeypatch.setattr(get_config(), "super_link_enabled", False)
    async with sessions.begin() as session:
        row = await dispatch_outbox.get_for_run(session, run_id=binding.run_id)
        assert row.prompt_addendum == DISPATCH_MARKER + "attached files"
        assert await dispatch_outbox.claim_due(session) == []
        assert row.status == "pending"


async def test_wrong_mode_rejected_before_execution(case):
    _, _, pair = case
    with pytest.raises(CollaborationError, match="participant_mode_mismatch"):
        await runtime.require_session_mode(pair.team_session_id, "stateful-react-agent")
    await runtime.require_session_mode(pair.team_session_id, "agent_team")
    await runtime.require_session_mode(uuid.uuid4(), "stateful-react-agent")


@pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bwrap") is None, reason="Linux worker boundary"
)
@pytest.mark.parametrize(
    "role,fail_ingest,correction",
    [
        ("single", False, False),
        ("team", False, False),
        ("single", True, False),
        ("single", False, True),
        ("team", False, True),
    ],
)
async def test_real_worker_registers_and_parent_publishes_after_exit(
    case, monkeypatch, tmp_path, role, fail_ingest, correction
):
    from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
    from server.orchestrator import Orchestrator

    sessions, uid, pair = case
    binding = await make_run(sessions, uid, pair, role=role, status="queued", archive=False)
    recipient = pair.team_id if role == "single" else pair.single_id
    server = MockLLMServer().start()
    delivered = False
    reply_to = None
    reply_sent = False
    inbox_reply_id = None
    inbox_read = False
    correcting = False
    revised = False
    inspections = 0
    requests = []

    def next_turn(payload):
        nonlocal delivered, reply_sent, inbox_read, revised, inspections
        requests.append(payload)
        names = {item["function"]["name"] for item in payload.get("tools", [])}
        if "独立的 Super-link" in str(payload.get("messages")):
            inspections += 1
            if correction and inspections == 1:
                return text_turn('{"verdict":"block","explanation":"Supply evidence limits"}')
            return text_turn(
                '{"verdict":"caveat","explanation":"Scripted inspection: preserve limitations"}'
            )
        if inbox_reply_id and not inbox_read and "read_super_link_inbox" in names:
            inbox_read = True
            return tool_call_turn("read_super_link_inbox", {"message_id": str(inbox_reply_id)})
        if correcting and not revised and "register_super_link_delivery" in names:
            revised = True
            return tool_call_turn(
                "register_super_link_delivery",
                {
                    "recipient_id": str(recipient),
                    "registration_key": str(uuid.uuid4()),
                    "body": "Revised research with explicit evidence limits.",
                    "revises_message_id": str(reply_to),
                    "requests_execution": True,
                },
            )
        if (
            reply_to
            and not correcting
            and not reply_sent
            and "register_super_link_delivery" in names
        ):
            reply_sent = True
            return tool_call_turn(
                "register_super_link_delivery",
                {
                    "recipient_id": str(binding.participant_id),
                    "registration_key": str(uuid.uuid4()),
                    "body": "Follow-up completed; limitations retained.",
                    "in_reply_to": str(reply_to),
                    "requests_execution": False,
                },
            )
        if not delivered and "register_super_link_delivery" in names:
            delivered = True
            return tool_call_turn(
                "register_super_link_delivery",
                {
                    "recipient_id": str(recipient),
                    "registration_key": str(uuid.uuid4()),
                    "body": "A completed research result with explicit limits.",
                    "requests_execution": True,
                },
            )
        if names == {"deliver_answer"}:
            return tool_call_turn(
                "deliver_answer", {"content": "Research completed.", "updates": []}
            )
        if not names and "current_request" in str(payload.get("messages")):
            return text_turn('{"decision":"ready"}')
        return text_turn("Research completed.")

    monkeypatch.setattr(server._script, "next_turn", next_turn)
    cfg = get_config()
    monkeypatch.setattr(cfg, "sandbox_backend", "bwrap")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    from plugins.corpus.structured.ledger import _writer

    _writer(corpus).close()
    monkeypatch.setattr(cfg, "semantic_store_root", corpus)
    monkeypatch.setattr(cfg, "wall_timeout_s", 90)
    monkeypatch.setattr(cfg, "max_turns", 8)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    orch = Orchestrator()

    async def mock_credentials(user_id):
        return {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": server.base_url,
            "OPENAI_MODEL": server.model,
            "LLM_PROVIDER": "openai",
        }

    monkeypatch.setattr(orch, "_resolve_llm_env", mock_credentials)
    original_ingest = orch._ingest_conversation
    if fail_ingest:

        async def unavailable_ingest(*args, **kwargs):
            raise OSError("test archive outage")

        monkeypatch.setattr(orch, "_ingest_conversation", unavailable_ingest)
    try:
        await asyncio.wait_for(
            orch._spawn(
                run_id=binding.run_id.hex,
                session_id=str(
                    pair.single_session_id if role == "single" else pair.team_session_id
                ),
                session_uuid=pair.single_session_id if role == "single" else pair.team_session_id,
                user_id=uid,
                prompt="Finish this short supplied research and register a formal delivery.",
                pipeline_id="stateful-react-agent" if role == "single" else "agent_team",
                agent_tools="",
                prompt_addendum="",
                turn_index=1,
            ),
            timeout=120,
        )
        if fail_ingest:
            async with sessions() as session:
                assert (
                    await session.get(sl.SuperLinkFinalization, binding.run_id)
                ).state == "pending"
                assert (
                    await session.scalar(select(func.count()).select_from(sl.SuperLinkOutbox)) == 0
                )
            monkeypatch.setattr(orch, "_ingest_conversation", original_ingest)
            from server.super_link.worker import recover_finalizations

            await recover_finalizations(orch)
        async with sessions() as session:
            run = await session.get(store.Run, binding.run_id)
            final = await session.get(sl.SuperLinkFinalization, binding.run_id)
            assert final is not None, run.error
            assert final.state == "ready", (run.status, run.error, run.stopped_by, final.error_code)
            message = await session.scalar(
                select(sl.SuperLinkMessage).where(sl.SuperLinkMessage.source_run_id == run.id)
            )
            assert message is not None, requests[-1] if requests else "no model calls"
            assert message.state == "published"
            assert await session.get(store.RunContextSource, run.id) is not None
            assert await session.get(sl.SuperLinkOutbox, message.id) is not None
            reply_to = message.id
            root_request = message.request_id
        async with sessions.begin() as session:
            await service.receive(session, reply_to)
            await events.seal_changes(session)
        from server.super_link.worker import model_inspection

        monkeypatch.setattr(store, "resolve_user_llm_env", mock_credentials)

        async def independent_inspect(envelope):
            return await model_inspection(uid, envelope)

        await coordination.inspect_delivery(reply_to, independent_inspect, reviewer="mock-endpoint")
        if correction:
            correcting = True
            feedback_run = await coordination.accept_feedback(reply_to)
            assert feedback_run is not None
            assert await dispatch_outbox.dispatch_once(orch) == 1
            async with asyncio.timeout(45):
                while True:
                    async with sessions() as session:
                        final = await session.get(sl.SuperLinkFinalization, feedback_run)
                        if final is not None and final.state in {"ready", "failed"}:
                            assert final.state == "ready", final.error_code
                            revision = await session.scalar(
                                select(sl.SuperLinkMessage).where(
                                    sl.SuperLinkMessage.source_run_id == feedback_run
                                )
                            )
                            assert revision is not None and revision.state == "published"
                            assert revision.revises_message_id == reply_to
                            assert revision.request_id == root_request
                            reply_to = revision.id
                            break
                    await asyncio.sleep(0.1)
            correcting = False
            async with sessions.begin() as session:
                await service.receive(session, reply_to)
                await events.seal_changes(session)
            await coordination.inspect_delivery(
                reply_to, independent_inspect, reviewer="mock-endpoint"
            )
        peer_run_id = await coordination.accept_delivery(reply_to)
        assert peer_run_id is not None
        assert await dispatch_outbox.dispatch_once(orch) == 1
        async with asyncio.timeout(45):
            while True:
                async with sessions() as session:
                    final = await session.get(sl.SuperLinkFinalization, peer_run_id)
                    if final is not None and final.state in {"ready", "failed"}:
                        assert final.state == "ready", final.error_code
                        break
                await asyncio.sleep(0.1)
        async with sessions() as session:
            reply = await session.scalar(
                select(sl.SuperLinkMessage).where(sl.SuperLinkMessage.source_run_id == peer_run_id)
            )
            assert reply is not None and reply.state == "published"
            assert reply.in_reply_to == reply_to and reply.request_id == root_request
            assert (
                await session.scalar(
                    select(func.count()).select_from(store.Turn).where(store.Turn.role == "user")
                )
                == 0
            )
            inbox_reply_id = reply.id
        # An information-only reply does not create a run, but a later genuine
        # run can read it through the real tool and retain it in native memory.
        async with sessions.begin() as session:
            await service.receive(session, inbox_reply_id)
            await events.seal_changes(session)
        await coordination.inspect_delivery(
            inbox_reply_id, independent_inspect, reviewer="mock-endpoint"
        )
        assert await coordination.accept_delivery(inbox_reply_id) is None
        next_run = await make_run(sessions, uid, pair, role=role, status="queued", archive=False)
        session_id = pair.single_session_id if role == "single" else pair.team_session_id
        await asyncio.wait_for(
            orch._spawn(
                run_id=next_run.run_id.hex,
                session_id=str(session_id),
                session_uuid=session_id,
                user_id=uid,
                prompt="Read the informational reply and retain its evidence limits.",
                pipeline_id="stateful-react-agent" if role == "single" else "agent_team",
                agent_tools="",
                prompt_addendum="",
                turn_index=2,
            ),
            timeout=120,
        )
        assert inbox_read
        async with sessions() as session:
            final = await session.get(sl.SuperLinkFinalization, next_run.run_id)
            assert final.state == "ready", final.error_code
            source = await session.get(store.RunContextSource, next_run.run_id)
            assert "Follow-up completed; limitations retained." in source.native_payload
    finally:
        await orch.shutdown()
        server.stop()


async def test_member_cannot_use_root_delivery_tool(monkeypatch):
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.tools.super_link import register_super_link_delivery

    token = set_current_execution_scope(ExecutionScope(role_id="sub_agent"))
    try:
        result = await register_super_link_delivery.func(
            recipient_id=str(uuid.uuid4()),
            registration_key=str(uuid.uuid4()),
            body="private child report",
        )
        assert json.loads(result)["error"] == "delivery_requires_main_agent"
    finally:
        reset_current_execution_scope(token)
