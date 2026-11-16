"""Readable report citations must not replace or leak machine evidence bindings."""

from types import SimpleNamespace

import pytest

from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.loop_types import TurnContext
from plugins.corpus.ledger import reset_run_ledgers
from plugins.tools.task_board import add_task, snapshot_tasks
from tests.test_team_atomic_delivery import delivery_run as delivery_run_fixture
from workflows.agent_team.delivery import deliver_answer
from workflows.agent_team.observers.bare_text_finalize import BareTextFinalizeObserver
from workflows.stateful_react_agent.delivery import CorpusDeliveryObserver

delivery_run = delivery_run_fixture


@pytest.fixture(autouse=True)
def clean_ledgers():
    reset_run_ledgers()
    yield
    reset_run_ledgers()


RAW = "The source estimates 50 units (`ce:" + "a" * 32 + "`)."
READABLE = "The source estimates 50 units (Research report, p. 3)."


def context(text, turn=1, max_turns=6):
    return TurnContext(
        turn=turn,
        max_turns=max_turns,
        task_id="run",
        role_id="main_agent",
        ai_text=text,
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )


async def test_atomic_delivery_keeps_board_uncommitted_until_readable_revision(delivery_run):
    await add_task.func([{"description": "Read the report"}])
    updates = [{"id": "t1", "resolution": "resolved", "notes": "Read"}]
    with pytest.raises(ValueError, match="corpus_citation_readability"):
        await deliver_answer.func(content=RAW, updates=updates)
    assert snapshot_tasks("run")[0]["resolution"] == "open"
    scope = get_current_execution_scope()
    assert scope.metadata["delivery_candidate"]["content"] == RAW
    await deliver_answer.func(content=READABLE, base_version=1, revise_content=True)
    assert snapshot_tasks("run")[0]["resolution"] == "resolved"


async def test_bare_text_requests_one_repair_before_acceptance(delivery_run):
    observer = BareTextFinalizeObserver()
    draft = context(RAW)
    repair = await observer.on_llm_response(draft)
    assert repair and repair.continue_to_next_turn
    assert "evidence_ref" in "\n".join(repair.inject_messages)
    assert "final_answer" not in draft.metadata
    assert "delivery_record" not in get_current_execution_scope().metadata
    fixed = context(READABLE, turn=2)
    accepted = await observer.on_llm_response(fixed)
    assert accepted.stop_reason == "final_answer"
    assert fixed.metadata["final_answer"] == READABLE


async def test_style_repair_is_bounded_and_does_not_silently_edit_evidence(delivery_run):
    observer = BareTextFinalizeObserver()
    await observer.on_llm_response(context(RAW))
    repeated = context(RAW, turn=2)
    result = await observer.on_llm_response(repeated)
    assert result.stop_reason == "final_answer"
    assert repeated.metadata["final_answer"] == RAW
    assert repeated.metadata["corpus_citation_readability"] == "unresolved"


async def test_last_turn_preserves_useful_answer_and_records_style_gap(delivery_run):
    ctx = context(RAW, turn=5)
    result = await BareTextFinalizeObserver().on_llm_response(ctx)
    assert result.stop_reason == "final_answer"
    assert ctx.metadata["final_answer"] == RAW
    assert ctx.metadata["corpus_citation_readability"] == "unresolved"


async def test_verified_react_answer_still_gets_readability_repair(monkeypatch):
    module = "workflows.stateful_react_agent.delivery"
    ledger = SimpleNamespace(has_activity=lambda: True, replayed_only=False)
    monkeypatch.setattr(f"{module}.get_run_ledger", lambda: ledger)
    monkeypatch.setattr(f"{module}.identity_manifest", lambda *args: None)
    monkeypatch.setattr(
        f"{module}.verify_and_record", lambda *args, **kwargs: {"status": "verified"}
    )
    observer = CorpusDeliveryObserver()
    repair = await observer.on_llm_response(context(RAW))
    assert repair and repair.continue_to_next_turn
    assert "binding is incomplete" not in "\n".join(repair.inject_messages)
    assert await observer.on_llm_response(context(READABLE, turn=2)) is None


async def test_structured_receipt_is_preserved_with_readable_body(delivery_run, monkeypatch):
    captured = []
    reference = "ce:" + "a" * 32
    conclusions = [
        {"id": "c1", "report_quote": READABLE, "evidence": [{"evidence_ref": reference}]}
    ]

    def prepare(content, rows, ledger):
        # Evidence validity is tested separately; observe the actual delivery
        # boundary to ensure this presentation check never edits machine refs.
        captured.append((content, rows))
        return None

    monkeypatch.setattr("plugins.corpus.final_delivery.prepare_delivery_manifest", prepare)
    await deliver_answer.func(content=READABLE, corpus_conclusions=conclusions)
    assert captured == [(READABLE, conclusions)]
    record = get_current_execution_scope().metadata["delivery_record"]
    assert record["content"] == READABLE
