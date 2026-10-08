"""DATA-05 定向验收：用户回填实际成交价后触发重新分析（2026-10-08 口径）。

覆盖 PRD v0.7 §4.4 与契约 v0.2 §7「成交回填」：

* 回填成交价与建新 Run 同一事务：成交记录与快照同时成立；
* 回填后的分析按 `holding_cost` 用途冻结快照，快照含该实际成交价；
* 旧 Run 快照不变（AC-06）；同键重放不产生第二个 Run（AC-05）。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text

from server import business_service as biz
from server import store
from server.app import app
from server.security import create_access_token

pytestmark = pytest.mark.pg

CAPITAL = {
    "total_capital": "100000",
    "available_capital": "60000",
    "capital_basis": "total",
    "as_of": "2026-10-02T00:00:00Z",
}
PLAN = {
    "symbol": "600519.SH",
    "market": "CN",
    "direction": "buy",
    "allocated_capital": "10000",
    "currency": "CNY",
}
TRADE = {
    "symbol": "600519.SH",
    "market": "CN",
    "side": "buy",
    "quantity": "100",
    "price": "20.10",
    "currency": "CNY",
    "traded_at": "2026-10-08T02:00:00Z",
}


@pytest.fixture
async def client(pg_clean):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fill.test"
    ) as http:
        yield http


async def _new_user(name: str) -> tuple[str, uuid.UUID]:
    user_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, username, password_hash, status) "
                "VALUES (:id, :name, 'x', 'active')"
            ),
            {"id": user_id, "name": name},
        )
    return f"Bearer {create_access_token(user_id)}", user_id


async def _new_research(user_id: uuid.UUID) -> uuid.UUID:
    research_id = uuid.uuid4()
    async with biz.business_transaction() as session:
        await session.execute(
            text("INSERT INTO sessions (id, user_id, title) VALUES (:id, :uid, '研究')"),
            {"id": research_id, "uid": user_id, "title": "研究"},
        )
    return research_id


async def _create_account(client, token: str) -> dict:
    response = await client.post(
        "/api/business/accounts",
        json={"name": "主账户", "base_currency": "CNY", "declared": dict(CAPITAL)},
        headers={"Authorization": token, "Idempotency-Key": "fill-acc"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_plan(client, token: str, research_id: uuid.UUID) -> dict:
    response = await client.post(
        f"/api/business/sessions/{research_id}/plans",
        json={"name": "计划A", "declared": dict(PLAN)},
        headers={"Authorization": token, "Idempotency-Key": "fill-plan"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _input(account_id, plan_id, *, use_case="plan_analysis", **extra) -> dict:
    payload = {
        "use_case": use_case,
        "account": {"id": str(account_id)},
        "plan": {"id": str(plan_id)},
        "idempotency_key": f"analyze:{uuid.uuid4()}",
    }
    payload.update(extra)
    return payload


async def _submit(client, token: str, research_id, investment_input, message="按计划分析"):
    return await client.post(
        "/api/runs",
        json={"message": message, "session_id": str(research_id), "investment_input": investment_input},
        headers={"Authorization": token},
    )


async def _snapshot(client, token: str, run_id: str) -> dict:
    response = await client.get(
        f"/api/runs/{run_id}/investment-snapshot", headers={"Authorization": token}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_filling_trade_price_creates_follow_up_run_with_frozen_trade(client) -> None:
    token, user_id = await _new_user("pg-fill-rerun")
    research_id = await _new_research(user_id)
    account = await _create_account(client, token)
    plan = await _create_plan(client, token, research_id)

    first = await _submit(client, token, research_id, _input(account["account_id"], plan["plan_id"]))
    assert first.status_code == 202, first.text
    first_run = first.json()["run_id"]
    assert "trade.price" not in (await _snapshot(client, token, first_run))["values"]

    # 回填实际成交价：成交记录 + 新 Run + 快照在同一事务完成。
    payload = _input(
        account["account_id"],
        plan["plan_id"],
        use_case="holding_cost",
        declared={"trade": dict(TRADE)},
    )
    message = "已按 20.10 买入 100 股，请重新分析"
    second = await _submit(client, token, research_id, payload, message=message)
    assert second.status_code == 202, second.text
    second_run = second.json()["run_id"]
    assert second_run != first_run

    async with biz.business_transaction() as session:
        trades = (await session.execute(select(store.TradeRecord))).scalars().all()
    assert len(trades) == 1
    assert trades[0].side == "buy"
    assert trades[0].price == Decimal("20.10")

    snapshot = await _snapshot(client, token, second_run)
    assert Decimal(snapshot["values"]["trade.price"]["value"]) == Decimal("20.10")
    # 旧快照不变（AC-06）。
    assert "trade.price" not in (await _snapshot(client, token, first_run))["values"]

    # 同键重放：返回原 Run，不产生第二个后续分析（AC-05）。
    replay = await _submit(client, token, research_id, payload, message=message)
    assert replay.json()["run_id"] == second_run
    async with biz.business_transaction() as session:
        run_count = (
            await session.execute(
                select(func.count())
                .select_from(store.Run)
                .where(store.Run.session_id == research_id)
            )
        ).scalar_one()
    assert run_count == 2
