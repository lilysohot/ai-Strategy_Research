"""Regressions from the run whose saved allocation could not reach sizing."""

import json
import uuid

import httpx
import pytest

from plugins.tools.investment_context import (
    bind_investment_context,
    investment_position_sizing,
    reset_investment_context,
)
from plugins.tools.investment_input_request import (
    bind_input_intent,
    pending_input_intent,
    request_investment_input,
    reset_input_intent,
)


def current_context():
    values = {
        "account.capital_basis": "tradable_assets",
        "account.total_capital": "200000",
        "account.available_capital": "200000",
        "account.currency": "CNY",
        "account.as_of": "2026-10-09T11:33:47+00:00",
        "plan.symbol": "601138",
        "plan.market": "CN",
        "plan.direction": "buy",
        "plan.allocated_capital": "20000",
    }
    return {
        "run_id": "audit-regression",
        "values": {k: {"value": v, "status": "user_provided"} for k, v in values.items()},
    }


async def test_current_allocation_supports_explicit_price_scenario_without_inventing_risk():
    tokens = bind_investment_context(current_context())
    try:
        result = json.loads(
            await investment_position_sizing.func(
                stop_loss=46.5,
                entry_low=46.7,
                entry_high=48,
            )
        )
    finally:
        reset_investment_context(tokens)
    assert result["ok"] is True
    assert result["calculation_mode"] == "capital_ceiling"
    assert result["risk_validated"] is False
    assert result["max_affordable_shares"] == 400
    assert result["capital_budget"] == 20000
    assert "shares" not in result  # a ceiling is not a recommended position


async def test_complete_current_facts_do_not_promise_an_unnecessary_input_dialog():
    context = bind_investment_context(current_context())
    intent = bind_input_intent()
    try:
        reply = await request_investment_input.func("plan_analysis", "需要确认资金")
        assert pending_input_intent() is None
        assert "无需" in reply
    finally:
        reset_input_intent(intent)
        reset_investment_context(context)


@pytest.mark.parametrize("cash,expected", [("5000", 100), ("200000", 400)])
async def test_capital_ceiling_never_exceeds_cash_or_allocation(cash, expected):
    context = current_context()
    context["values"]["account.available_capital"]["value"] = cash
    tokens = bind_investment_context(context)
    try:
        result = json.loads(
            await investment_position_sizing.func(46.5, entry_low=46.7, entry_high=48)
        )
        assert result["max_affordable_shares"] == expected
        assert result["max_affordable_amount"] <= min(float(cash), 20000)
    finally:
        reset_investment_context(tokens)


@pytest.mark.parametrize(
    "field,value",
    [
        ("account.available_capital", "NaN"),
        ("plan.allocated_capital", "-1"),
        ("plan.risk_budget_value", "unknown"),
        ("plan.position_limit_value", "101"),
        ("plan.market", "US"),
        ("account.currency", "USD"),
        ("plan.direction", "sell"),
    ],
)
async def test_invalid_frozen_facts_do_not_become_a_position(field, value):
    context = current_context()
    context["values"][field] = {"value": value, "status": "user_provided"}
    tokens = bind_investment_context(context)
    try:
        result = json.loads(
            await investment_position_sizing.func(46.5, entry_low=46.7, entry_high=48)
        )
        assert result["ok"] is False
    finally:
        reset_investment_context(tokens)


async def test_tool_failure_cannot_be_marked_successful_on_board():
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.tools.task_board import clear_board, snapshot_tasks, update_task

    scope = set_current_execution_scope(ExecutionScope(task_id="audit-sizing"))
    tokens = bind_investment_context(current_context())
    try:
        await investment_position_sizing.func(46.5)
        task = snapshot_tasks("audit-sizing")[0]
        assert task["resolution"] == "open"
        reply = await update_task.func([{"id": task["id"], "resolution": "resolved"}])
        assert "须重试成功" in reply
        assert snapshot_tasks("audit-sizing")[0]["resolution"] == "open"
        reply = await update_task.func([{"id": task["id"], "resolution": "cancelled"}])
        assert "reason" in reply
        await investment_position_sizing.func(46.5, entry_low=46.7, entry_high=48)
        assert snapshot_tasks("audit-sizing")[0]["resolution"] == "resolved"
        assert "风险仓位未验证" in snapshot_tasks("audit-sizing")[0]["description"]
    finally:
        clear_board("audit-sizing")
        reset_current_execution_scope(scope)
        reset_investment_context(tokens)


async def test_explicit_risk_and_position_cap_are_applied_to_current_plan():
    context = current_context()
    for key, value in {
        "risk_budget_value": "0.1",
        "risk_budget_unit": "percent",
        "position_limit_value": "5",
        "position_limit_unit": "percent",
    }.items():
        context["values"][f"plan.{key}"] = {"value": value, "status": "user_provided"}
    tokens = bind_investment_context(context)
    try:
        result = json.loads(
            await investment_position_sizing.func(46.5, entry_low=46.7, entry_high=48)
        )
        assert result["ok"] is True
        assert result["risk_validated"] is True
        assert result["shares"] == 100  # 200 risk / (48 - 46.5), rounded to lots
        assert result["amount"] <= 10000
    finally:
        reset_investment_context(tokens)


def test_china_bar_dates_and_intraday_close_are_unambiguous():
    from plugins.market.temporal import annotate_history

    result = annotate_history(
        {
            "items": [
                {"date_ms": 1791907200000, "close_price": 49.92},
                {"date_ms": 1791820800000, "close_price": 50},
            ]
        },
        "601138.SH",
        1791907200000 + 13 * 3600000,
    )
    assert result["raw_count"] == 2
    assert result["count"] == 1
    assert result["items"][0]["trade_date"] == "2026-10-13"
    assert result["items"][0]["bar_status"] == "closed"
    assert result["items"][0]["comparison_eligible"] is True
    assert result["provisional_items"][0]["trade_date"] == "2026-10-14"
    assert result["provisional_items"][0]["bar_status"] == "provisional"
    assert result["provisional_items"][0]["comparison_eligible"] is False
    assert result["provisional_items"][0]["close_price"] == 49.92
    assert result["latest_closed_trade_date"] == "2026-10-13"
    assert result["retrieved_at"].startswith("2026-10-14T")
    assert "不能确认支撑守住" in result["provisional_policy"]


def test_business_failure_is_projected_as_failed_tool_activity():
    from deploy.huggingface.adapter import _looks_like_error

    assert _looks_like_error('{"ok": false, "error": "缺少资料"}')
    assert _looks_like_error('{"passed": false, "errors": []}')
    assert not _looks_like_error('{"ok": true, "risk_validated": false}')
    assert not _looks_like_error('{"items": [{"ok": false}]}')


@pytest.mark.parametrize("complete", [False, True])
async def test_saved_facts_retire_only_satisfied_owned_requests_without_creating_run(complete):
    from sqlalchemy import func, select

    from server import business_service as biz
    from server import store
    from server.app import app
    from server.security import create_access_token

    await store.init_db()
    owner = await store.create_user(username=f"reconcile-{complete}", password_hash="x")
    other = await store.create_user(username=f"other-{complete}", password_hash="x")
    research = await store.create_session(user_id=owner.id)
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://audit.test"
    ) as client:

        async def write(method, path, data):
            response = await client.request(
                method,
                path,
                json=data,
                headers={
                    **headers,
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            )
            assert response.status_code in (200, 201), response.text
            return response.json()

        base = f"/api/business/sessions/{research.id}"
        account = await write(
            "POST",
            "/api/business/accounts",
            {
                "name": "主账户",
                "base_currency": "CNY",
                "declared": {
                    "total_capital": "200000",
                    "available_capital": "200000",
                    "capital_basis": "tradable_assets",
                    "as_of": "2026-10-09T00:00:00Z",
                },
            },
        )
        await write(
            "PUT", f"{base}/link", {"account_id": account["account_id"], "primary_plan_id": None}
        )
        request = await write(
            "POST",
            f"{base}/input-requests",
            {
                "use_case": "plan_analysis",
                "fields": [
                    {"name": f"plan.{name}"}
                    for name in ("symbol", "market", "direction", "allocated_capital")
                ],
                "continuation": {
                    "message": "继续研究工业富联",
                    "investment_input": {
                        "use_case": "plan_analysis",
                        "account": {"id": account["account_id"], "expected_revision": 1},
                    },
                },
            },
        )
        request_id = request["request_id"]
        declared = {"symbol": "601138", "market": "CN", "direction": "buy"}
        if complete:
            declared["allocated_capital"] = "20000"
        plan = await write("POST", f"{base}/plans", {"name": "工业富联", "declared": declared})
        await write(
            "PUT",
            f"{base}/link",
            {"account_id": account["account_id"], "primary_plan_id": plan["plan_id"]},
        )
        # Another user's read cannot reconcile this user's request.
        await client.get(
            "/api/business/input-requests",
            headers={
                "Authorization": f"Bearer {create_access_token(other.id)}",
            },
        )
        async with biz.business_transaction() as session:
            row = await session.get(store.InputRequest, uuid.UUID(request_id))
            assert row.status == "pending"
        response = await client.get(f"/api/business/input-requests/{request_id}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == ("cancelled" if complete else "pending")
        assert body["follow_up_run_id"] is None
        if complete:
            assert body["resolution_reason"] == "facts_updated"
            assert body["remaining_fields"] == []
        again = await client.get(f"/api/business/input-requests/{request_id}", headers=headers)
        assert again.json()["revision"] == body["revision"]
        pending = await client.get("/api/business/input-requests?status=pending", headers=headers)
        assert pending.json()["total"] == (0 if complete else 1)
        async with biz.business_transaction() as session:
            assert (
                await session.execute(select(func.count()).select_from(store.Run))
            ).scalar_one() == 0
