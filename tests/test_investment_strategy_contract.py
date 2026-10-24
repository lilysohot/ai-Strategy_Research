from __future__ import annotations

import json

import pytest

from plugins.tools.investment_context import (
    bind_investment_context,
    investment_position_sizing,
    investment_strategy_lint,
    reset_investment_context,
)


def snapshot(*, risk=False):
    values = {
        "account.total_capital": "200000",
        "account.available_capital": "200000",
        "account.capital_basis": "tradable_assets",
        "account.currency": "CNY",
        "plan.allocated_capital": "20000",
        "plan.direction": "buy",
        "plan.market": "CN",
        "plan.symbol": "601138",
    }
    if risk:
        values.update({"plan.risk_budget_value": "1", "plan.risk_budget_unit": "percent"})
    return {
        "run_id": "regression-e859",
        "snapshot_id": "snapshot-e859",
        "values": {
            key: {"value": value, "status": "user_provided"} for key, value in values.items()
        },
    }


def proposal(calculation_id):
    return {
        "calculation_id": calculation_id,
        "horizon": "1-3M",
        "invalidation": "收盘跌破分析止损位，情景失效",
        "evidence": [
            {
                "source_ref": "quote",
                "page": "quote/as_of",
                "quote": "last_price=48.85; as_of=2026-10-24",
                "kind": "fact",
            }
        ],
        "sources": [{"id": "quote", "url": "market_quote://601138.SH"}],
    }


async def calculate():
    return json.loads(
        await investment_position_sizing.ainvoke(
            {
                "entry_low": 46,
                "entry_high": 47,
                "stop_loss": 44,
            }
        )
    )


@pytest.mark.parametrize("risk", [False, True])
async def test_server_assembles_card_from_registered_calculation(risk):
    tokens = bind_investment_context(snapshot(risk=risk))
    try:
        sizing = await calculate()
        assert "calculation_id" in sizing
        result = json.loads(
            await investment_strategy_lint.ainvoke(
                {
                    "strategy": proposal(sizing["calculation_id"]),
                }
            )
        )
        assert result["passed"], result
        card = result["card"]
        assert card["position"]["entry"] == {"low": 46, "high": 47}
        assert card["position"]["sizing"] == sizing
        assert result["risk_validated"] is risk
        assert result["delivery_mode"] == ("strategy" if risk else "capital_analysis")
        if not risk:
            assert sizing["max_affordable_shares"] == 400
            assert "shares" not in card["position"]["sizing"]
            assert not result["recommendation_allowed"]
    finally:
        reset_investment_context(tokens)


async def test_calculation_ids_do_not_cross_runs():
    tokens = bind_investment_context(snapshot())
    try:
        sizing = await calculate()
        assert "calculation_id" in sizing
    finally:
        reset_investment_context(tokens)
    tokens = bind_investment_context(snapshot())
    try:
        result = json.loads(
            await investment_strategy_lint.ainvoke(
                {
                    "strategy": proposal(sizing["calculation_id"]),
                }
            )
        )
        assert not result["passed"]
        assert result["errors"][0]["code"] == "unknown_calculation"
    finally:
        reset_investment_context(tokens)


async def test_three_changed_invalid_cards_exhaust_revisions():
    tokens = bind_investment_context(snapshot())
    try:
        for index in range(3):
            card = {
                "entry": {"low": 46, "high": 47},
                "position": {"stop_loss": 44},
                "note": str(index),
            }
            result = json.loads(
                await investment_strategy_lint.ainvoke(
                    {
                        "strategy_json": json.dumps(card),
                    }
                )
            )
            assert not result["passed"]
            assert result["attempts_remaining"] == 2 - index
        assert not result["retry_allowed"]
        result = json.loads(await investment_strategy_lint.ainvoke({"strategy": proposal("new")}))
        assert result["errors"][0]["code"] == "strategy_revision_limit"
    finally:
        reset_investment_context(tokens)


async def test_typed_contract_rejects_model_owned_sizing():
    tokens = bind_investment_context(snapshot())
    try:
        sizing = await calculate()
        assert "calculation_id" in sizing
        data = proposal(sizing["calculation_id"])
        data["sizing"] = {"computed_by": "position_sizing@v1", "shares": 400}
        result = json.loads(await investment_strategy_lint.ainvoke({"strategy": data}))
        assert not result["passed"]
        assert result["errors"][0]["field"] == "strategy.sizing"
    finally:
        reset_investment_context(tokens)


def test_exposed_schema_is_structured_and_excludes_legacy_json():
    params = investment_strategy_lint.parameters
    assert set(params["properties"]) == {"strategy"}
    assert params["required"] == ["strategy"]


async def test_exhaustion_stops_loop_and_replaces_unverified_conclusion():
    from types import SimpleNamespace

    from plugins.tools.investment_strategy import InvestmentStrategyObserver, publication_boundary

    tokens = bind_investment_context(snapshot())
    try:
        observer = InvestmentStrategyObserver()
        for _ in range(3):
            await investment_strategy_lint.ainvoke({"strategy": proposal("unknown")})
        intervention = await observer.on_turn_end(SimpleNamespace())
        assert intervention.stop_reason == "strategy_validation_failed"
        answer = publication_boundary("可以买，400股合理。", "complete")
        assert answer["answer_status"] == "partial"
        assert "可以买" not in answer["final_text"]
        assert "unknown_calculation" in answer["final_text"]
    finally:
        reset_investment_context(tokens)


async def test_capital_analysis_finalization_and_artifact_gate(tmp_path, monkeypatch):
    from plugins.tools.investment_strategy import publication_boundary
    from server import artifacts
    from server.worker import _finalize_investment_context

    tokens = bind_investment_context(snapshot())
    sizing = await calculate()
    await investment_strategy_lint.ainvoke({"strategy": proposal(sizing["calculation_id"])})
    answer = publication_boundary("建议先买200股，然后加仓。", "complete")
    assert "建议先买" not in answer["final_text"]
    assert "400" in answer["final_text"] and "18,800" in answer["final_text"]
    output = tmp_path / "ws" / "outputs"
    output.mkdir(parents=True)
    (output / "unsafe.md").write_text("可以买400股")
    _finalize_investment_context(tmp_path, tokens)
    monkeypatch.setattr(artifacts, "run_dir_for", lambda _: tmp_path)
    rows = artifacts.scan_outputs("regression-e859")
    assert [r["rel_path"] for r in rows] == ["investment-analysis.md"]
    assert artifacts.resolve_artifact_path("regression-e859", "unsafe.md") is None
    safe = artifacts.resolve_artifact_path("regression-e859", "investment-analysis.md")
    assert safe is not None
    safe.write_text("tampered")
    assert artifacts.resolve_artifact_path("regression-e859", "investment-analysis.md") is None


async def test_analysis_still_requires_evidence_and_valid_price_target():
    tokens = bind_investment_context(snapshot())
    try:
        sizing = await calculate()
        data = proposal(sizing["calculation_id"])
        data["target"] = 40.0
        data["evidence"][0]["source_ref"] = "undeclared"
        result = json.loads(await investment_strategy_lint.ainvoke({"strategy": data}))
        assert not result["passed"]
        codes = {e["code"] for e in result["errors"]}
        assert "target_not_above_entry" in codes
        assert any("source" in code for code in codes)
    finally:
        reset_investment_context(tokens)


@pytest.mark.parametrize("failure_count", [1, 3])
def test_real_worker_stops_after_invalid_strategies(failure_count):
    import os
    import subprocess
    import sys
    import uuid
    from pathlib import Path

    from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
    from server.config import run_dir_for

    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True)
    context = snapshot()
    context["run_id"] = run_id
    (run_root / "investment-context.json").write_text(json.dumps(context))
    script = [
        tool_call_turn("investment_strategy_lint", {"strategy": proposal(str(i))}) for i in range(failure_count)
    ] + [text_turn("可以买，400股合理。")]
    with MockLLMServer(script=script) as endpoint:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "server.worker",
                "--run-id",
                run_id,
                "--session-id",
                str(uuid.uuid4()),
                "--prompt",
                "校验投资策略卡",
                "--backend",
                "native",
                "--wall-time",
                "900",
                "--max-turns",
                "8",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                "OPENAI_MODEL": "mock-frontier-model",
                "OPENAI_BASE_URL": endpoint.base_url,
                "OPENAI_API_KEY": "sk-test",
                "SERVER_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            },
            capture_output=True,
            text=True,
            timeout=35,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads((run_root / "summary.json").read_text())
    assert summary["stopped_by"] == "strategy_validation_failed", summary
    assert "校验未通过" in summary["final_answer"]
    assert "可以买" not in summary["final_answer"]
    assert len(endpoint.requests) == (3 if failure_count == 3 else 2)
    receipt = json.loads((run_root / "investment-strategy-verification.json").read_text())
    assert receipt["attempts_remaining"] == 3 - failure_count
    assert receipt["allowed_artifacts"] == {}
