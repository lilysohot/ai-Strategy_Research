"""同轮同参 single-flight：请求 2／执行 1／唯一送达 1 + 第二条简短关联回执。

去重发生在授权检查之后、``execute_tools`` 创建 ``ainvoke`` 任务之前；
两条请求各有审计行，但只有首份正文进入覆盖并集。首份失败或未送达时
绝不拿关联回执冒充送达。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from frontier_agent.core.loop_types import (
    BaseObserver,
    LoopConfig,
    ToolCallIntervention,
    ToolResult,
    TurnContext,
)
from frontier_agent.core.runtime.loop.agent_loop import _execute_tool_batch
from frontier_agent.core.tool import Tool, tool
from plugins.corpus import projection, tool_refs
from plugins.corpus.ledger import (
    BLOCKED_BY_BUDGET,
    DEDUP_REF,
    DEDUP_TARGET_NOT_DELIVERED,
    DELIVERED,
    UNKNOWN,
    ConsumptionLedger,
    ConsumptionLedgerObserver,
)

DOC = "cv2:" + "d" * 64
LOC = "chunk:document1/unit%3A0001"
LOC2 = "chunk:document1/unit%3A0002"
TEXT = "轨道算力 2028 年 1GW"
C1 = "call_fetch_first"
C2 = "call_fetch_duplicate"


@pytest.fixture(autouse=True)
def _isolated_snapshots(monkeypatch):
    projection.reset_snapshot_index()
    monkeypatch.setattr(tool_refs, "metadata_snapshot_index", lambda: {})
    yield
    projection.reset_snapshot_index()


def _envelope() -> dict[str, Any]:
    return {
        "ok": True,
        "scope": "document",
        "doc_id": DOC,
        "build_id": DOC[4:],
        "items": [
            {
                "locator": LOC,
                "unit_id": "0001",
                "text": TEXT,
                "evidence_ref": "ce:receipt",
            }
        ],
        "item_errors": [],
        "unresolved": [],
        "next_cursor": None,
        "exhausted": True,
        "fetch_complete": True,
    }


def _fetch_tool(invocations: list[dict[str, str]], *, fail: bool = False) -> Tool:
    @tool
    async def corpus_fetch(doc_id: str, locator: str, **kwargs: Any) -> str:
        """Read one verbatim block from a version-pinned document."""
        invocations.append({"doc_id": doc_id, "locator": locator})
        if fail:
            return json.dumps({"ok": False, "error": "read_failed"}, ensure_ascii=False)
        return json.dumps(_envelope(), ensure_ascii=False)

    corpus_fetch.metadata["dedup_within_turn"] = True
    return corpus_fetch


def _calls(*, second_locator: str = LOC) -> list[dict[str, Any]]:
    return [
        {"id": C1, "name": "corpus_fetch", "args": {"doc_id": DOC, "locator": LOC}},
        {"id": C2, "name": "corpus_fetch", "args": {"doc_id": DOC, "locator": second_locator}},
    ]


async def _batch(
    tool_obj: Tool,
    calls: list[dict[str, Any]],
    ledger: ConsumptionLedger,
    *extra_observers: BaseObserver,
) -> tuple[list[dict[str, Any]], str]:
    messages: list[dict[str, Any]] = []
    ctx = TurnContext(1, 2, "task", "test", "", "", calls, messages, None, {})
    reason, _count = await _execute_tool_batch(
        LoopConfig(),
        [ConsumptionLedgerObserver(ledger=ledger), *extra_observers],
        {tool_obj.name: tool_obj},
        messages,
        {},
        1,
        0,
        ctx,
        calls,
    )
    return messages, reason


def _body(message: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(message["content"])
    assert isinstance(payload, dict)
    return payload


async def test_same_turn_same_args_execute_once_with_two_audit_receipts() -> None:
    invocations: list[dict[str, str]] = []
    ledger = ConsumptionLedger()
    messages, reason = await _batch(_fetch_tool(invocations), _calls(), ledger)

    assert reason == ""
    assert len(invocations) == 1  # 执行 1
    assert [message["tool_call_id"] for message in messages] == [C1, C2]

    first, second = _body(messages[0]), _body(messages[1])
    assert first["ok"] is True and first["items"][0]["text"] == TEXT
    assert second["dedup"] is True
    assert second["dedup_of"] == C1
    assert second["result_call_id"] == C1
    assert "text" not in second and "items" not in second and "ok" not in second
    assert len(messages[1]["content"]) < len(messages[0]["content"])

    assert len(ledger.requested) == 2
    assert [row["ordinal"] for row in ledger.requested] == [1, 2]
    assert [row["dedup_of"] for row in ledger.requested] == ["", C1]
    assert len(ledger.responses) == 2
    assert ledger.responses[1]["dedup_of"] == C1
    assert ledger.responses[1]["ranges"] == []
    assert ledger.responses[1]["delivery_state"] == DEDUP_REF

    ledger.finalize(messages)
    assert ledger.responses[0]["delivery_state"] == DELIVERED
    assert ledger.responses[1]["delivery_state"] == DEDUP_REF

    assert ledger.dedup_accounting() == {
        "requests": 2,
        "executions": 1,
        "unique_deliveries": 1,
        "dedup_refs": 1,
        "unresolved_dedup_refs": 0,
    }
    assert ledger.to_dict()["dedup_accounting"]["unique_deliveries"] == 1
    assert len(ledger.fetched) == 1
    assert len(ledger.coverage_deliveries()) == 1


async def test_distinct_arguments_are_not_coalesced() -> None:
    invocations: list[dict[str, str]] = []
    ledger = ConsumptionLedger()
    messages, _ = await _batch(_fetch_tool(invocations), _calls(second_locator=LOC2), ledger)

    assert len(invocations) == 2
    assert all(_body(message)["ok"] is True for message in messages)
    assert all("dedup" not in _body(message) for message in messages)
    assert ledger.dedup_accounting()["dedup_refs"] == 0
    assert ledger.dedup_accounting()["executions"] == 2


async def test_tool_without_declaration_is_never_coalesced() -> None:
    invocations: list[dict[str, str]] = []
    tool_obj = _fetch_tool(invocations)
    del tool_obj.metadata["dedup_within_turn"]
    ledger = ConsumptionLedger()
    messages, _ = await _batch(tool_obj, _calls(), ledger)

    assert len(invocations) == 2
    assert all("dedup" not in _body(message) for message in messages)


async def test_rewrite_args_are_used_for_the_dedup_key() -> None:
    """授权改写后的参数才算数：两个不同目标不得因原始 args 相同而合并。"""

    class RewriteGuard(BaseObserver):
        async def on_tool_call(self, ctx, call):
            if call["id"] == C2:
                return ToolCallIntervention(
                    rewrite_args={**call["args"], "locator": LOC2},
                )
            return None

    invocations: list[dict[str, str]] = []
    ledger = ConsumptionLedger()
    await _batch(_fetch_tool(invocations), _calls(), ledger, RewriteGuard())
    assert len(invocations) == 2


async def test_failed_first_result_executes_the_duplicate_for_real() -> None:
    invocations: list[dict[str, str]] = []
    ledger = ConsumptionLedger()
    messages, _ = await _batch(_fetch_tool(invocations, fail=True), _calls(), ledger)

    assert len(invocations) == 2  # 不复用失败结果
    assert all(_body(message)["ok"] is False for message in messages)
    assert all(row["delivery_state"] == "failed" for row in ledger.responses)
    assert ledger.dedup_accounting() == {
        "requests": 2,
        "executions": 2,
        "unique_deliveries": 0,
        "dedup_refs": 0,
        "unresolved_dedup_refs": 0,
    }


async def test_dedup_ref_is_downgraded_when_the_target_was_not_delivered() -> None:
    invocations: list[dict[str, str]] = []
    ledger = ConsumptionLedger()
    messages, _ = await _batch(_fetch_tool(invocations), _calls(), ledger)

    # 首份在消息边界被预算替换 → 省略第二份的前提不再成立。
    ledger.responses[0]["delivery_state"] = BLOCKED_BY_BUDGET
    ledger.finalize(messages)

    assert ledger.responses[1]["delivery_state"] == DEDUP_TARGET_NOT_DELIVERED
    assert ledger.responses[1]["error"] == f"dedup_target_{BLOCKED_BY_BUDGET}"
    assert ledger.dedup_accounting()["unique_deliveries"] == 0
    assert ledger.dedup_accounting()["unresolved_dedup_refs"] == 1


def test_dedup_ref_requires_an_identifiable_target() -> None:
    ledger = ConsumptionLedger()
    ledger.record_dedup_response(tool_call_id=C2, turn=1, dedup_of="", visible_chars=80)
    assert ledger.responses[0]["delivery_state"] == UNKNOWN
    assert ledger.responses[0]["error"] == "dedup_target_unidentified"


def test_dedup_ref_without_a_live_target_is_downgraded() -> None:
    ledger = ConsumptionLedger()
    ledger.record_dedup_response(tool_call_id=C2, turn=1, dedup_of="call_missing")
    ledger.finalize([{"role": "tool", "tool_call_id": C2, "content": "{}"}])
    assert ledger.responses[0]["delivery_state"] == DEDUP_TARGET_NOT_DELIVERED
    assert ledger.responses[0]["error"] == "dedup_target_missing"


def test_replay_restores_the_dedup_ref_instead_of_a_failed_response() -> None:
    args = json.dumps({"doc_id": DOC, "locator": LOC}, ensure_ascii=False)
    receipt = json.dumps(
        {"tool": "corpus_fetch", "dedup": True, "dedup_of": C1}, ensure_ascii=False
    )
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": C1, "function": {"name": "corpus_fetch", "arguments": args}},
                {"id": C2, "function": {"name": "corpus_fetch", "arguments": args}},
            ],
        },
        {
            "role": "tool",
            "tool_call_id": C1,
            "content": json.dumps(_envelope(), ensure_ascii=False),
        },
        {"role": "tool", "tool_call_id": C2, "content": receipt},
    ]
    ledger = ConsumptionLedger()
    ConsumptionLedgerObserver(ledger=ledger)._restore_replayed_evidence(messages)

    assert len(ledger.requested) == 2
    assert [row["dedup_of"] for row in ledger.requested] == ["", C1]
    assert [row["delivery_state"] for row in ledger.responses] == [DELIVERED, DEDUP_REF]
    assert ledger.errors == []
    assert ledger.dedup_accounting()["unique_deliveries"] == 1


def test_short_receipt_survives_the_workflow_post_processor() -> None:
    """关联回执不得被语料投影/预算 fitter 改写掉 ``dedup_of``。"""
    from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor

    body = json.dumps(
        {"tool": "corpus_fetch", "dedup": True, "dedup_of": C1, "result_call_id": C1},
        ensure_ascii=False,
    )
    result = ToolResult(
        name="corpus_fetch",
        args={},
        result=body,
        duration_ms=0,
        tool_call_id=C2,
        is_error=False,
        execution_status="dedup_ref",
    )
    assert ReactToolResultPostProcessor().process(result) == body
