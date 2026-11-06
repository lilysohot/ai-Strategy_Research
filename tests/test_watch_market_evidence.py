"""Real market receipts and deterministic arithmetic for autonomous monitors."""

import json

import pytest

from plugins.market.evidence import (
    bind_market_evidence,
    record_market_result,
    record_watch_state,
    reset_market_evidence,
)
from plugins.tools.watch_targets import submit_watch_intents


def snapshot():
    values = {"buy_sell.count": "2", "buy_sell.total_count": "2", "buy_sell.truncated": "false"}
    for i, price in enumerate(("44.25", "47.22"), 1):
        values.update(
            {
                f"buy_sell.{i}.{k}": v
                for k, v in {
                    "symbol": "601138",
                    "market": "CN",
                    "currency": "CNY",
                    "side": "buy",
                    "price": price,
                    "quantity": "100",
                }.items()
            }
        )
    return {
        "snapshot_id": "frozen-test",
        "values": {k: {"value": v, "status": "user_provided"} for k, v in values.items()},
    }


@pytest.fixture
def evidence(tmp_path):
    token = bind_market_evidence(snapshot(), tmp_path)
    yield tmp_path
    reset_market_evidence(token)


def quote():
    return record_market_result(
        "market_quote",
        {
            "ok": True,
            "thscode": "601138.SH",
            "items": [
                {
                    "thscode": "601138.SH",
                    "last_price": 44.89,
                    "turnover": 6798439757.85,
                    "volume": 156452337,
                    "as_of": "2026-11-05T10:04:12+08:00",
                }
            ],
        },
    )


def test_market_facts_use_quantities_units_and_explicit_denominators(evidence):
    record_watch_state(
        {
            "ok": True,
            "targets": [
                {
                    "id": "r1",
                    "symbol": "601138.SH",
                    "threshold": "41.51",
                    "direction": "down",
                }
            ],
        }
    )
    result = quote()
    row = result["items"][0]
    assert row["display_numbers"]["turnover_yi_cny"] == "67.9843975785"
    facts = row["monitoring_metrics"]
    assert facts["recorded_buys"]["cost_cny"] == "9147"
    assert facts["recorded_buys"]["pnl_cny"] == "-169"
    distance = facts["targets"][0]
    assert distance["target_vs_last_pct"] == "-7.529517"
    assert distance["last_vs_target_pct"] == "8.142616"
    assert result["evidence_ref"].startswith("mref:")
    assert len(list((evidence / "market").glob("*.json"))) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"buy_sell.truncated": "true"},
        {"buy_sell.2.side": "sell"},
        {"buy_sell.1.quantity": None},
        {"buy_sell.total_count": "3"},
    ],
)
def test_incomplete_or_mixed_trades_do_not_invent_position(change):
    context = snapshot()
    for key, value in change.items():
        context["values"][key]["value"] = value
    token = bind_market_evidence(context, None)
    try:
        position = quote()["items"][0]["monitoring_metrics"]["recorded_buys"]
        assert position["available"] is False
        assert "pnl_cny" not in position
    finally:
        reset_market_evidence(token)


async def test_state_receipt_cannot_substitute_for_market_when_changing_price(
    evidence, monkeypatch
):
    import plugins.tools.watch_targets as watch

    calls = []

    async def request(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(watch, "request", request)
    state = record_watch_state(
        {
            "ok": True,
            "targets": [
                {
                    "id": "r1",
                    "symbol": "601138.SH",
                    "threshold": "41.51",
                }
            ],
        }
    )
    result = await submit_watch_intents.ainvoke(
        {
            "intents": [
                {
                    "operation": "update",
                    "rule_id": "r1",
                    "spec": {"threshold": "40"},
                    "evidence_refs": [state["evidence_ref"]],
                }
            ]
        }
    )
    assert not json.loads(result)["ok"]
    assert not calls


async def test_submit_rejects_unknown_receipts_before_write(evidence, monkeypatch):
    import plugins.tools.watch_targets as watch

    calls = []

    async def request(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(watch, "request", request)
    result = json.loads(
        await submit_watch_intents.ainvoke(
            {
                "intents": [
                    {
                        "operation": "create",
                        "evidence_refs": ["mref:invented"],
                    }
                ]
            }
        )
    )
    assert result["ok"] is False
    assert not calls


async def test_submit_binds_receipt_and_rejects_cross_run_reuse(evidence, monkeypatch):
    import plugins.tools.watch_targets as watch

    calls = []

    async def request(operation, payload):
        calls.append(payload)
        return {"ok": True, "status": "applied"}

    monkeypatch.setattr(watch, "request", request)
    ref = quote()["evidence_ref"]
    intent = {"operation": "create", "spec": {"symbol": "601138.SH"}, "evidence_refs": [ref]}
    assert json.loads(await submit_watch_intents.ainvoke({"intents": [intent]}))["ok"]
    assert calls[0]["intents"][0]["evidence_receipts"][0]["tool"] == "market_quote"
    token = bind_market_evidence(None, None)
    try:
        assert not json.loads(await submit_watch_intents.ainvoke({"intents": [intent]}))["ok"]
    finally:
        reset_market_evidence(token)
    assert len(calls) == 1


def test_history_receipt_uses_top_level_symbol(evidence):
    from plugins.market.evidence import bind_intent_evidence

    history = record_market_result(
        "market_history",
        {
            "ok": True,
            "thscode": "601138.SH",
            "retrieved_at": "2026-11-05T10:04:12+08:00",
            "items": [{"close_price": 44.89, "turnover": 6798439757.85}],
        },
    )
    intents = bind_intent_evidence(
        [
            {
                "operation": "create",
                "spec": {"symbol": "601138.SH"},
                "evidence_refs": [history["evidence_ref"]],
            }
        ]
    )
    assert intents[0]["evidence_receipts"][0]["symbols"] == ["601138.SH"]
