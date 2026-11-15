"""Delivery retries repair fields, not the whole answer."""

import json
from types import SimpleNamespace

import pytest

from plugins.corpus.ledger import reset_run_ledgers
from plugins.tools.task_board import add_task, snapshot_tasks
from tests.test_corpus_manifest_tool import _conclusion
from tests.test_team_atomic_delivery import delivery_run as _team_delivery_run
from workflows.agent_team.delivery import deliver_answer

delivery_run = _team_delivery_run
ACCEPTED = "Final answer and task dispositions accepted."


@pytest.fixture(autouse=True)
def _clean_ledgers():
    reset_run_ledgers()
    yield
    reset_run_ledgers()


def raw(call):
    return str(call.value)


async def test_state_only_retry_reuses_the_candidate_body(delivery_run):
    await add_task.func([{"description": "提取全文关键论断"}])
    body = "全文关键论断如下：第一，需求成立。第二，预算受限。"

    with pytest.raises(ValueError) as first:
        await deliver_answer.func(
            content=body,
            updates=[{"id": "t1", "resolution": "cancelled", "notes": "成员未完成"}],
        )
    assert "candidate v1" in raw(first)
    stored = snapshot_tasks("run")[0]
    assert stored["resolution"] == "open"

    accepted = await deliver_answer.func(
        base_version=1,
        updates=[{"id": "t1", "resolution": "resolved", "notes": "已完成提取"}],
    )
    assert accepted == ACCEPTED
    assert snapshot_tasks("run")[0]["resolution"] == "resolved"

    # A successful retry is published once; the candidate cannot be replayed.
    with pytest.raises(ValueError) as replay:
        await deliver_answer.func(base_version=1)
    assert "No recoverable delivery candidate" in raw(replay)


async def test_anchor_retry_only_replaces_the_named_entry(delivery_run):
    from frontier_agent.core.execution_context import get_current_execution_scope

    await add_task.func([{"description": "提取全文关键论断"}])
    body = "第一项结论成立。第二项结论待核。"
    with pytest.raises(ValueError) as first:
        await deliver_answer.func(
            content=body,
            updates=[{"id": "t1", "resolution": "cancelled", "notes": "未完成"}],
            corpus_conclusions=[
                _conclusion(id="c1", report_quote="第一项结论成立。"),
                _conclusion(id="c2", report_quote="不存在的句子"),
            ],
        )
    assert "corpus_manifest_anchor_mismatch" in raw(first)
    assert "required_task_cancelled" in raw(first)

    # Only c2 is resubmitted; the disposition stays rejected so the retry is
    # still a candidate, which lets us inspect what the runtime kept.
    with pytest.raises(ValueError) as second:
        await deliver_answer.func(
            base_version=1,
            corpus_conclusions=[
                _conclusion(id="c2", report_quote="第二项结论待核。"),
            ],
        )
    assert "candidate v2" in raw(second)
    merged = get_current_execution_scope().metadata["delivery_candidate"]["conclusions"]
    assert [row["id"] for row in merged] == ["c1", "c2"]
    assert merged[0]["report_quote"] == "第一项结论成立。"
    assert merged[1]["report_quote"] == "第二项结论待核。"


async def test_keep_body_retry_rejects_a_sneaked_change(delivery_run):
    await add_task.func([{"description": "提取全文关键论断"}])
    body = "结论一。"
    with pytest.raises(ValueError):
        await deliver_answer.func(
            content=body,
            updates=[{"id": "t1", "resolution": "cancelled", "notes": "未完成"}],
        )

    with pytest.raises(ValueError) as sneaked:
        await deliver_answer.func(
            content=body + "补充一句。",
            base_version=1,
            updates=[{"id": "t1", "resolution": "resolved", "notes": "已完成"}],
        )
    assert "revise_content=true" in raw(sneaked)


async def test_body_revision_rechecks_old_anchors(delivery_run):
    from frontier_agent.core.execution_context import get_current_execution_scope

    await add_task.func([{"description": "提取全文关键论断"}])
    with pytest.raises(ValueError):
        await deliver_answer.func(
            content="原句成立。",
            updates=[{"id": "t1", "resolution": "cancelled", "notes": "未完成"}],
            corpus_conclusions=[
                _conclusion(id="c1", report_quote="原句成立。"),
            ],
        )

    with pytest.raises(ValueError) as revised:
        await deliver_answer.func(
            base_version=1,
            revise_content=True,
            content="改后的正文。",
            updates=[{"id": "t1", "resolution": "resolved", "notes": "已完成"}],
        )
    assert "corpus_manifest_anchor_mismatch" in raw(revised)
    assert "candidate v2" in raw(revised)
    stored = get_current_execution_scope().metadata["delivery_candidate"]
    assert stored["content"] == "改后的正文。"
    assert stored["conclusions"][0]["report_quote"] == "原句成立。"


async def test_retry_without_a_candidate_requires_full_resubmission(delivery_run):
    await add_task.func([{"description": "提取全文关键论断"}])
    with pytest.raises(ValueError) as missing:
        await deliver_answer.func(base_version=3)
    assert "No recoverable delivery candidate" in raw(missing)


async def test_changed_body_without_base_version_requires_a_revision(delivery_run):
    await add_task.func([{"description": "提取全文关键论断"}])
    with pytest.raises(ValueError):
        await deliver_answer.func(
            content="Original answer.",
            updates=[{"id": "t1", "resolution": "cancelled", "notes": "unfinished"}],
        )

    with pytest.raises(ValueError) as bypass:
        await deliver_answer.func(
            content="A different answer with a newly added assertion.",
            updates=[{"id": "t1", "resolution": "resolved", "notes": "done"}],
        )
    assert "revise_content=true" in raw(bypass)


async def test_board_validation_failure_also_retains_the_candidate(delivery_run):
    from frontier_agent.core.execution_context import get_current_execution_scope

    await add_task.func([{"description": "Original whole goal"}])
    await add_task.func([{"description": "Required part", "parent_id": "t1"}])

    with pytest.raises(ValueError):
        await deliver_answer.func(
            content="Answer with the available evidence.",
            updates=[{"id": "t1", "resolution": "resolved", "notes": "t2 covers this"}],
        )
    candidate = get_current_execution_scope().metadata["delivery_candidate"]
    assert candidate["content"] == "Answer with the available evidence."


async def test_field_retry_publishes_the_saved_body_through_the_real_loop(
    delivery_run, monkeypatch,
):
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import LoopConfig
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from workflows.agent_team.delivery import TeamDeliveryObserver

    _, budget = delivery_run
    await add_task.func([{"description": "Explain evidence"}])
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 786.6)
    body = "The requested interpretation is complete."

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert self.calls <= 2, "field repair must terminate on turn 2"
            if self.calls == 1:
                args = {
                    "content": body,
                    "updates": [
                        {"id": "t1", "resolution": "cancelled", "notes": "unfinished"},
                    ],
                }
            else:
                args = {
                    "base_version": 1,
                    "updates": [{"id": "t1", "resolution": "resolved", "notes": "done"}],
                }
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": f"finish{self.calls}",
                    "type": "function",
                    "function": {"name": "deliver_answer", "arguments": json.dumps(args)},
                }],
                finish_reason="tool_calls",
            )

    result = await run_agent_loop(
        llm=Client(),
        system_prompt="Answer with evidence",
        user_message="Explain evidence",
        config=LoopConfig(task_id="run", max_turns=2),
        scope_metadata={SWARM_SCOPE_KEY: SimpleNamespace(original_question="Explain evidence")},
        tools=[deliver_answer],
        observers=[TeamDeliveryObserver(budget)],
    )
    assert result.stopped_by == "final_answer"
    assert result.final_content == body


# --- W3: normalized delivery record, audit, idempotence and recovery -------------


@pytest.mark.parametrize("empty_content", [False, True])
async def test_explicit_empty_content_retry_publishes_saved_body(
    delivery_run, monkeypatch, empty_content,
):
    """D1: a field repair may omit content entirely or pass an empty string."""
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import LoopConfig
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from plugins.tools._bus_scope import SWARM_SCOPE_KEY
    from workflows.agent_team.delivery import TeamDeliveryObserver

    _, budget = delivery_run
    await add_task.func([{"description": "Explain evidence"}])
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 786.6)
    body = "The requested interpretation is complete."

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert self.calls <= 2, "A successful field repair must terminate on turn 2"
            if self.calls == 1:
                args = {"content": body, "updates": [
                    {"id": "t1", "resolution": "cancelled", "notes": "unfinished"},
                ]}
            else:
                args = {"base_version": 1, "updates": [
                    {"id": "t1", "resolution": "resolved", "notes": "done"},
                ]}
                if empty_content:
                    args["content"] = ""
            return LLMResponse(
                content="", tool_calls=[{
                    "id": f"finish{self.calls}", "type": "function",
                    "function": {"name": "deliver_answer", "arguments": json.dumps(args)},
                }], finish_reason="tool_calls",
            )

    result = await run_agent_loop(
        llm=Client(),
        system_prompt="Answer with evidence",
        user_message="Explain evidence",
        config=LoopConfig(task_id="run", max_turns=2),
        scope_metadata={SWARM_SCOPE_KEY: SimpleNamespace(original_question="Explain evidence")},
        tools=[deliver_answer],
        observers=[TeamDeliveryObserver(budget)],
    )
    assert result.stopped_by == "final_answer"
    assert result.final_content == body


async def test_accepted_delivery_record_and_audit_are_separate(delivery_run):
    """D6: one normalized record; audit keeps the original checks out of the body."""
    from frontier_agent.core.execution_context import get_current_execution_scope
    from tests.test_team_atomic_delivery import prepare

    bus, _ = delivery_run
    await prepare(bus)
    body = "The independently checked amount is 50."
    accepted = await deliver_answer.func(
        content=body,
        updates=[{"id": "t1", "resolution": "resolved", "notes": "Bound check passed"}],
    )
    assert accepted == ACCEPTED
    metadata = get_current_execution_scope().metadata
    record = metadata["delivery_record"]
    assert record["protocol_version"] == 1
    assert record["published"] is True and record["status"] == "accepted"
    assert record["content"] == body
    assert record["content_sha256"]
    assert record["dispositions"][0]["id"] == "t1"
    assert record["evidence"]["manifest_committed"] is False
    assert any(c.get("check_id") == "amount" for c in record["verification"]["checks"])
    assert metadata["delivered_answer"] == body
    audit = metadata["delivery_audit"]
    assert [event["event"] for event in audit][-1] == "accepted"
    assert "amount" in audit[-1]["check_ids"]
    assert "content" not in audit[-1], "audit must not duplicate the body"


async def test_finalize_gate_failure_keeps_candidate_without_partial_commit(delivery_run):
    """D3: a terminal-gate rejection leaves the board untouched but keeps the body."""
    from frontier_agent.core.execution_context import get_current_execution_scope

    await add_task.func([{"description": "Explain evidence"}])
    before = snapshot_tasks("run")
    body = "The requested interpretation is complete."
    with pytest.raises(ValueError) as failed:
        await deliver_answer.func(content=body, updates=[])
    assert "candidate v1" in raw(failed)
    assert "Cannot finish" in raw(failed)
    assert snapshot_tasks("run") == before
    assert get_current_execution_scope().metadata["delivery_candidate"]["content"] == body


async def test_accepted_submission_replay_does_not_publish_again(delivery_run):
    """D4: replaying the same submission is idempotent; a new body cannot replace it."""
    from frontier_agent.core.execution_context import get_current_execution_scope

    await add_task.func([{"description": "Explain evidence"}])
    body = "The requested interpretation is complete."
    updates = [{"id": "t1", "resolution": "resolved", "notes": "done"}]
    assert await deliver_answer.func(content=body, updates=updates) == ACCEPTED
    before = snapshot_tasks("run")
    assert await deliver_answer.func(content=body, updates=updates) == ACCEPTED
    assert snapshot_tasks("run") == before
    audit = get_current_execution_scope().metadata["delivery_audit"]
    assert len([event for event in audit if event["event"] == "accepted"]) == 1
    with pytest.raises(ValueError, match="already published"):
        await deliver_answer.func(content=body + " Changed.", updates=updates)


async def test_older_candidate_version_cannot_overwrite_a_newer_candidate(delivery_run):
    """D4: an accepted repair must name the current candidate version."""
    await add_task.func([{"description": "Explain evidence"}])
    body = "The requested interpretation is complete."
    rejected = [{"id": "t1", "resolution": "cancelled", "notes": "unfinished"}]
    with pytest.raises(ValueError) as first:
        await deliver_answer.func(content=body, updates=rejected)
    assert "candidate v1" in raw(first)
    with pytest.raises(ValueError) as second:
        await deliver_answer.func(base_version=1, updates=rejected)
    assert "candidate v2" in raw(second)
    with pytest.raises(ValueError, match="No recoverable delivery candidate at version 1"):
        await deliver_answer.func(
            base_version=1,
            updates=[{"id": "t1", "resolution": "resolved", "notes": "done"}],
        )
    assert await deliver_answer.func(
        base_version=2,
        updates=[{"id": "t1", "resolution": "resolved", "notes": "done"}],
    ) == ACCEPTED


# --- W5: offline fault injection ----------------------------------------------


async def test_manifest_commit_failure_keeps_candidate_without_partial_commit(
    delivery_run, monkeypatch,
):
    """D3: a persistence failure rolls back and reports its exact location."""
    from frontier_agent.core.execution_context import get_current_execution_scope

    await add_task.func([{"description": "Explain evidence"}])
    body = "The requested interpretation is complete."
    updates = [{"id": "t1", "resolution": "resolved", "notes": "done"}]
    before = snapshot_tasks("run")
    monkeypatch.setattr(
        "plugins.corpus.final_delivery.prepare_delivery_manifest",
        lambda *args, **kwargs: {"stub": "manifest"},
    )

    def fail_commit(payload):
        raise ValueError("disk write failed")

    monkeypatch.setattr("plugins.tools.corpus_manifest.commit_final_manifest", fail_commit)
    with pytest.raises(ValueError) as failed:
        await deliver_answer.func(content=body, updates=updates)
    assert "candidate v1" in raw(failed)
    assert "disk write failed" in raw(failed)
    assert snapshot_tasks("run") == before
    assert get_current_execution_scope().metadata["delivery_candidate"]["content"] == body
